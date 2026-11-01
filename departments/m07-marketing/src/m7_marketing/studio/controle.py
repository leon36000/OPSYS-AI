"""Contrôle qualité automatique d'une composition, avant toute revue humaine.

Un rapport liste des CONSTATS (`QC-*`), chacun critique ou avertissement. Un seul constat critique en échec rend le
rapport non conforme et le visuel NE PEUT PAS passer en revue (`actifs.demander_revue`). Le rapport est signé par son
empreinte SHA-256 (JSON canonique) ; l'approbation humaine porte cette empreinte, donc un rapport retouché ou refait
après coup ne couvre plus l'approbation.

Ce qui est lu, et comment (R5 §5.1, E3) :
  - les éléments attendus viennent du BRIEF (marque, textes, éléments critiques, mentions), pas du plan : un gabarit
    qui oublierait une mention ou changerait un chiffre est pris en défaut ;
  - la SORTIE est relue par un `LecteurOCR` par format (PNG, SVG, PDF). Zéro écart toléré sur tout élément attendu
    (espaces normalisées, rien d'autre : ni casse, ni tirets, ni chiffres) ; tout numéro de téléphone, courriel, prix,
    licence, NEQ ou adresse web lu dans la sortie et absent du brief est un échec (texte halluciné par un fond) ;
  - contraste (WCAG 2.2 AA, 4,5:1, 3:1 pour le grand texte) mesuré sur les pixels du PNG livré ; taille minimale ;
    zone de sécurité ; fond perdu et boîtes du PDF ; résolution du fond ; reproductibilité (le plan, refait, redonne
    EXACTEMENT les artefacts) ; polices OFL ; marquage « généré par IA » ; licence du modèle revérifiée maintenant ;
    prix non expiré ; mention de licence du modèle présente ;
  - le français nettement prédominant est une HEURISTIQUE (part de la surface de texte, seuil paramétrable) : le seuil
    réglementaire n'est pas établi ; à valider par un avocat.

Aucun lecteur n'est supposé : un format sans lecteur est un échec critique (`QC-OCR-ABSENT`), un lecteur qui échoue
aussi. La NATURE de chaque lecteur (réel ou double) est consignée au rapport.

Module sans entrée-sortie ; l'instant de contrôle est un argument.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

from . import gabarits, ocr, png, rendus
from . import plan as p
from .composition import Composition
from .polices import RegistrePolices

SCHEMA_RAPPORT = "opsys.studio.rapport/v1"
LIMITES_DECLAREES = (
    "Le lecteur OCR réel (profil Tesseract + pdfium) n'a pas tourné pour ce contrôle si la nature du lecteur est "
    "« double » : un double atteste la chaîne de composition, pas la lisibilité réelle.",
    "Le contrôle de prédominance du français est une heuristique sur la surface du texte ; le seuil réglementaire "
    "n'est "
    "pas établi (à valider par un avocat).",
    "Le PDF est en RVB sans profil de sortie : il n'est pas PDF/X ; le preflight de l'imprimeur reste requis.",
    "Aucune détection de visage, de plaque, de marque de tiers ni de contenu inapproprié n'est faite sur le fond ; la "
    "revue humaine (N3) l'atteste.",
)
_ESPACES = re.compile(r"[\s    ]+")
_TELEPHONE = re.compile(r"(?<![0-9])(?:\+?1[ .-])?\(?[2-9][0-9]{2}\)?[ .-]?[2-9][0-9]{2}[ .-]?[0-9]{4}(?![0-9])")
_COURRIEL = re.compile(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PRIX = re.compile(r"[0-9]{1,3}(?: [0-9]{3})*(?:[.,][0-9]{2})? ?\$")
_RBQ = re.compile(r"(?<![0-9])[0-9]{4}-[0-9]{4}-[0-9]{2}(?![0-9])")
_NEQ = re.compile(r"(?<![0-9])[0-9]{10}(?![0-9])")
_WEB = re.compile(r"(?:https?://)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|ca|net|org|qc\.ca|example|test)\b")
MOTIFS_CRITIQUES = {
    "telephone": _TELEPHONE,
    "courriel": _COURRIEL,
    "prix": _PRIX,
    "licence_rbq": _RBQ,
    "neq": _NEQ,
    "site_web": _WEB,
}
CODES = (
    "QC-ELEMENTS",
    "QC-OCR-ABSENT",
    "QC-OCR",
    "QC-INCONNU-CRITIQUE",
    "QC-CONTRASTE",
    "QC-TAILLE-MIN",
    "QC-ZONE-SECURITE",
    "QC-FOND-PERDU",
    "QC-RESOLUTION",
    "QC-LANGUE-FR",
    "QC-MARQUAGE-IA",
    "QC-LICENCE",
    "QC-PRIX-VALIDITE",
    "QC-MENTION-LICENCE",
    "QC-POLICES",
    "QC-REPRODUCTIBILITE",
    "QC-FORMAT",
)


@dataclasses.dataclass(frozen=True)
class PolitiqueControle:
    """Seuils du contrôle ; des valeurs explicites, jamais devinées par un modèle."""

    ratio_francais_min: float = 2.0
    contraste_texte: float = 4.5
    contraste_grand_texte: float = 3.0
    taille_grand_texte_pt: float = 18.0


@dataclasses.dataclass(frozen=True)
class Constat:
    code: str
    critique: bool
    ok: bool
    detail: str
    mesure: Any = None

    def vers_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "critique": self.critique,
            "ok": self.ok,
            "detail": self.detail,
            "mesure": self.mesure,
        }


POLITIQUE_PAR_DEFAUT = PolitiqueControle()


def normaliser(texte: str) -> str:
    """Forme de comparaison : NFC, toute suite d'espaces (insécables compris) ramenée à une espace. Rien d'autre."""
    return _ESPACES.sub(" ", unicodedata.normalize("NFC", texte)).strip()


def attendus(composition_brief) -> dict[str, str]:
    """Les textes que la sortie DOIT porter, tirés du brief seul : `{id logique: texte}`."""
    brief = composition_brief
    sortie = {"marque": brief.marque["nom"]}
    for role in ("titre", "sous_titre", "appel_action"):
        for langue in brief.langues:
            texte = brief.textes.get(role, {}).get(langue)
            if texte is not None:
                sortie[f"{role}.{langue}"] = texte
    compteurs: dict[str, int] = {}
    for element in brief.elements_critiques:
        type_ = element["type"]
        sortie[f"critique.{type_}.{compteurs.get(type_, 0)}"] = gabarits.texte_affiche(type_, element["valeur"])
        compteurs[type_] = compteurs.get(type_, 0) + 1
    for i, mention in enumerate(brief.mentions):
        sortie[f"mention.{i}"] = mention
    return sortie


@dataclasses.dataclass(frozen=True)
class Rapport:
    donnees: Mapping[str, Any]

    @property
    def conforme(self) -> bool:
        return bool(self.donnees["conforme"])

    @property
    def empreinte(self) -> str:
        return self.donnees["empreinte"]

    @property
    def constats(self) -> list[dict[str, Any]]:
        return self.donnees["constats"]

    def echecs_critiques(self) -> list[str]:
        return [c["code"] for c in self.constats if c["critique"] and not c["ok"]]


def empreinte_rapport(corps: Mapping[str, Any]) -> str:
    texte = json.dumps(
        {k: v for k, v in corps.items() if k != "empreinte"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(("opsys-studio-rapport/v1\n" + texte).encode("utf-8")).hexdigest()


def verifier_empreinte_rapport(rapport: Mapping[str, Any]) -> bool:
    return isinstance(rapport, Mapping) and rapport.get("empreinte") == empreinte_rapport(rapport)


# -- lecture et attribution ------------------------------------------------------------------------------------
def _assigner(lecture: ocr.LectureOCR, plan: p.Plan) -> tuple[dict[str, str], list[ocr.Jeton]]:
    """`({id logique: texte lu}, jetons orphelins)`. Un jeton à `ref` est attribué à sa ligne ; un jeton à boîte est
    attribué à la ligne du plan qui le contient ; le reste est orphelin (texte lu hors de toute zone attendue)."""
    lignes = {f"{ligne.id}#{ligne.n}": ligne for ligne in plan.lignes}
    par_ligne: dict[str, list[ocr.Jeton]] = {}
    orphelins: list[ocr.Jeton] = []
    for jeton in lecture.jetons:
        ref = jeton.ref
        if (
            ref is None
            and jeton.x0 is not None
            and jeton.y0 is not None
            and jeton.x1 is not None
            and jeton.y1 is not None
        ):
            cx, cy = (jeton.x0 + jeton.x1) / 2, (jeton.y0 + jeton.y1) / 2
            for cle, ligne in lignes.items():
                haut = ligne.boite[3] - ligne.boite[1]
                if (
                    ligne.boite[0] - 4 <= cx <= ligne.boite[2] + 4
                    and ligne.boite[1] - 0.25 * haut <= cy <= ligne.boite[3] + 0.25 * haut
                ):
                    ref = cle
                    break
        if ref is None or ref not in lignes:
            orphelins.append(jeton)
        else:
            par_ligne.setdefault(ref, []).append(jeton)
    par_id: dict[str, list[tuple[int, str]]] = {}
    for cle, jetons in par_ligne.items():
        identifiant, _, n = cle.rpartition("#")
        ordonnes = sorted(jetons, key=lambda j: j.x0 if j.x0 is not None else 0.0)
        par_id.setdefault(identifiant, []).append((int(n), " ".join(j.texte for j in ordonnes)))
    return ({i: normaliser(" ".join(t for _n, t in sorted(v))) for i, v in par_id.items()}, orphelins)


def _occurrences(texte: str) -> Counter[tuple[str, str]]:
    compte: Counter[tuple[str, str]] = Counter()
    for type_, motif in MOTIFS_CRITIQUES.items():
        for trouve in motif.finditer(texte):
            compte[(type_, normaliser(trouve.group(0)))] += 1
    return compte


# -- le contrôle -----------------------------------------------------------------------------------------------
def controler(
    composition: Composition,
    polices: RegistrePolices,
    lecteurs: Mapping[str, ocr.LecteurOCR],
    *,
    maintenant: dt.datetime,
    politique: PolitiqueControle = POLITIQUE_PAR_DEFAUT,
    verdict_licence: Callable[[], Mapping[str, Any] | None] | None = None,
    mention_licence_requise: str | None = None,
    composition_enregistree: str | None = None,
) -> Rapport:
    """`composition_enregistree` : l'empreinte de composition du REGISTRE ; le rapport s'y rattache même si les fichiers
    relus ont changé (le constat de reproductibilité le dit) : c'est l'actif du registre qui est contrôlé, jamais une
    autre
    composition. Absente, l'empreinte de la composition passée est utilisée."""
    brief, plan = composition.brief, composition.plan
    constats: list[Constat] = []
    ajouter = constats.append
    attendu = attendus(brief)

    # 1. Éléments du plan = éléments du brief, texte pour texte.
    logiques = plan.elements_logiques()
    texte_plan = {i: normaliser(" ".join(ligne.texte for ligne in lignes)) for i, lignes in logiques.items()}
    manquants = sorted(set(attendu) - set(texte_plan))
    en_trop = sorted(set(texte_plan) - set(attendu))
    differents = sorted(i for i in set(attendu) & set(texte_plan) if texte_plan[i] != normaliser(attendu[i]))
    ajouter(
        Constat(
            "QC-ELEMENTS",
            True,
            not (manquants or en_trop or differents),
            "tous les éléments du brief sont posés, sans autre texte"
            if not (manquants or en_trop or differents)
            else f"manquants {manquants} ; non demandés {en_trop} ; texte différent {differents}",
            {"manquants": manquants, "en_trop": en_trop, "differents": differents},
        )
    )

    # 2. Relecture de chaque artefact par un lecteur.
    lectures: list[ocr.LectureOCR] = []
    for format_ in sorted(composition.artefacts):
        lecteur = lecteurs.get(format_)
        if lecteur is None or format_ not in lecteur.formats:
            ajouter(
                Constat("QC-OCR-ABSENT", True, False, f"aucun lecteur pour l'artefact {format_} : rien n'est supposé")
            )
            continue
        try:
            lecture = lecteur.lire(composition.artefacts[format_], format_, plan)
        except (ocr.LectureImpossible, rendus.SvgInvalide, rendus.PdfInvalide, png.PngInvalide) as exc:
            ajouter(Constat("QC-OCR", True, False, f"{format_} : lecture impossible ({type(exc).__name__}: {exc})"))
            continue
        lectures.append(lecture)
        lus, orphelins = _assigner(lecture, plan)
        ecarts = {
            i: {"attendu": attendu[i], "lu": lus.get(i)}
            for i in sorted(attendu)
            if normaliser(attendu[i]) != lus.get(i)
        }
        for i in sorted(set(lus) - set(attendu)):
            ecarts[i] = {"attendu": None, "lu": lus[i]}
        ajouter(
            Constat(
                "QC-OCR",
                True,
                not ecarts and not orphelins,
                f"{format_} lu par {lecture.lecteur} ({lecture.nature}) : zéro écart sur {len(attendu)} éléments"
                if not ecarts and not orphelins
                else f"{format_} : {len(ecarts)} élément(s) lu(s) autrement que demandé, "
                f"{len(orphelins)} texte(s) hors zone",
                {"format": format_, "ecarts": ecarts, "hors_zone": [j.texte for j in orphelins]},
            )
        )
        lu_total = " ".join([*lus.values(), *(j.texte for j in orphelins)])
        permis = _occurrences(" ".join(attendu.values()))
        inconnus = sorted((_occurrences(lu_total) - permis).items())
        ajouter(
            Constat(
                "QC-INCONNU-CRITIQUE",
                True,
                not inconnus,
                f"{format_} : aucune donnée critique lue hors du brief"
                if not inconnus
                else f"{format_} : donnée critique lue qui n'est pas dans le brief : "
                f"{[f'{t} {v}' for (t, v), _n in inconnus]}",
                {"format": format_, "inconnus": [[t, v] for (t, v), _n in inconnus]},
            )
        )

    # 3. Contraste, taille minimale, zone de sécurité.
    _controler_geometrie(constats, composition, politique)

    # 4. Fond perdu, résolution.
    _controler_impression(constats, composition)

    # 5. Langue, marquage, licence, prix, mention, polices, reproductibilité, format.
    _controler_langue(constats, composition, politique)
    _controler_marquage(constats, composition)
    _controler_licence(constats, composition, verdict_licence, mention_licence_requise)
    _controler_couleur(constats, brief)
    _controler_prix(constats, brief, maintenant)
    _controler_polices(constats, composition, polices)
    _controler_reproductibilite(constats, composition, polices)

    donnees = {
        "schema": SCHEMA_RAPPORT,
        "constats": [c.vers_dict() for c in constats],
        "conforme": all(c.ok for c in constats if c.critique),
        "lecteurs": [lecture.vers_resume() for lecture in lectures],
        "artefacts": composition.empreintes(),
        "composition_empreinte": composition_enregistree or composition.empreinte(),
        "plan_empreinte": p.empreinte(plan),
        "brief_empreinte": brief.empreinte(),
        "ia_generee": composition.ia_generee,
        "fictif": brief.fictif,
        "controle_le": maintenant.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limites": list(LIMITES_DECLAREES),
    }
    donnees["empreinte"] = empreinte_rapport(donnees)
    return Rapport(json.loads(json.dumps(donnees)))


def _luminance(c: tuple[int, int, int]) -> float:
    def canal(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(c[0]) + 0.7152 * canal(c[1]) + 0.0722 * canal(c[2])


def _controler_geometrie(constats: list[Constat], composition: Composition, politique: PolitiqueControle) -> None:
    plan = composition.plan
    # Contraste mesuré sur les pixels du PNG livré, à l'extérieur de l'encre.
    pires: list[dict[str, Any]] = []
    try:
        image = png.decoder(composition.artefacts["png"])
    except (KeyError, png.PngInvalide):
        image = None
    if image is None:
        constats.append(Constat("QC-CONTRASTE", True, False, "PNG illisible : contraste non mesurable"))
    else:
        for ligne in plan.lignes:
            zone = (
                max(0, int(ligne.boite[0]) - 2),
                max(0, int(ligne.boite[1]) - 2),
                min(image.largeur, int(ligne.boite[2]) + 3),
                min(image.hauteur, int(ligne.boite[3]) + 3),
            )
            _encre, fond = ocr.separer(image, zone, ligne.couleur)
            if not fond:
                continue
            luminances = sorted(_luminance(c) for c in fond)
            bas, haut = luminances[int(0.05 * (len(luminances) - 1))], luminances[int(0.95 * (len(luminances) - 1))]
            lt = _luminance(ligne.couleur)
            pire = min((max(lt, b) + 0.05) / (min(lt, b) + 0.05) for b in (bas, haut))
            pt = ligne.taille_px * 72 / plan.ppp if plan.impression else ligne.taille_px * 0.75
            seuil = (
                politique.contraste_grand_texte if pt >= politique.taille_grand_texte_pt else politique.contraste_texte
            )
            if pire < seuil:
                pires.append({"ligne": f"{ligne.id}#{ligne.n}", "contraste": round(pire, 2), "seuil": seuil})
        constats.append(
            Constat(
                "QC-CONTRASTE",
                True,
                not pires,
                "contraste WCAG AA respecté sur toutes les lignes" if not pires else f"contraste insuffisant : {pires}",
                {"lignes_en_echec": pires},
            )
        )
    petites = [f"{ligne.id}#{ligne.n}" for ligne in plan.lignes if ligne.taille_px < plan.taille_min_px - 1e-6]
    constats.append(
        Constat(
            "QC-TAILLE-MIN",
            True,
            not petites,
            f"aucun texte sous {plan.taille_min_px:.1f} px"
            if not petites
            else f"texte sous la taille minimale ({plan.taille_min_px:.1f} px) : {petites}",
            {"taille_min_px": round(plan.taille_min_px, 2)},
        )
    )
    dehors = []
    zones = list(plan.zones_reservees)
    for ligne in plan.lignes:
        b = ligne.boite
        s = plan.surete
        hors_surete = b[0] < s[0] - 0.5 or b[1] < s[1] - 0.5 or b[2] > s[2] + 0.5 or b[3] > s[3] + 0.5
        dans_bande = any(not (b[2] <= z[0] or b[0] >= z[2] or b[3] <= z[1] or b[1] >= z[3]) for z in zones)
        if hors_surete or dans_bande:
            dehors.append(f"{ligne.id}#{ligne.n}")
    logo = plan.logo
    if logo is not None and not (
        plan.surete[0] - 0.5 <= logo.x
        and logo.x + logo.w <= plan.surete[2] + 0.5
        and plan.surete[1] - 0.5 <= logo.y
        and logo.y + logo.h <= plan.surete[3] + 0.5
    ):
        dehors.append(logo.id)
    constats.append(
        Constat(
            "QC-ZONE-SECURITE",
            True,
            not dehors,
            "tout le texte et le logo sont dans la zone de sécurité"
            if not dehors
            else f"hors de la zone de sécurité : {dehors}",
            {"surete": [round(v, 1) for v in plan.surete]},
        )
    )


def _controler_impression(constats: list[Constat], composition: Composition) -> None:
    plan = composition.plan
    fmt = gabarits.format_de(plan.gabarit, plan.format)
    if plan.impression:
        detail, ok = [], True
        minimum = 0.125 * plan.ppp - 0.5
        if plan.fond_perdu_px < minimum:
            ok = False
            detail.append(f"fond perdu de {plan.fond_perdu_px} px, {minimum:.1f} px (0,125 po) au moins")
        try:
            pdf = rendus.lire_pdf(composition.artefacts["pdf"])
            k = 72.0 / plan.ppp
            media, rogne, saigne = (
                pdf["boites"].get("MediaBox"),
                pdf["boites"].get("TrimBox"),
                pdf["boites"].get("BleedBox"),
            )
            attendu_rogne = [
                plan.rognage[0] * k,
                (plan.hauteur_px - plan.rognage[3]) * k,
                plan.rognage[2] * k,
                (plan.hauteur_px - plan.rognage[1]) * k,
            ]
            if not (media and rogne and saigne):
                ok = False
                detail.append("MediaBox, TrimBox ou BleedBox absente du PDF")
            elif any(abs(a - b) > 0.05 for a, b in zip(rogne, attendu_rogne, strict=True)):
                ok = False
                detail.append(f"TrimBox {rogne} différente du format fini {[round(v, 2) for v in attendu_rogne]}")
            elif rogne[0] - saigne[0] < 0.125 * 72 - 0.6 or saigne[2] - rogne[2] < 0.125 * 72 - 0.6:
                ok = False
                detail.append("BleedBox : moins de 0,125 po de fond perdu autour du format fini")
        except (rendus.PdfInvalide, KeyError) as exc:
            ok = False
            detail.append(f"PDF illisible : {exc}")
        constats.append(
            Constat(
                "QC-FOND-PERDU",
                True,
                ok,
                "fond perdu de 0,125 po et boîtes du PDF conformes" if ok else " ; ".join(detail),
            )
        )
    ratio = None
    if composition.fond_png is not None:
        image = png.decoder(composition.fond_png)
        echelle = max(plan.largeur_px / image.largeur, plan.hauteur_px / image.hauteur)  # >1 : fond agrandi
        ratio = round(echelle, 3)
        if plan.impression:
            ppp_effectif = plan.ppp / echelle
            ok = ppp_effectif >= fmt.ppp_min - 0.5
            constats.append(
                Constat(
                    "QC-RESOLUTION",
                    True,
                    ok,
                    f"résolution effective du fond : {ppp_effectif:.0f} ppp (minimum {fmt.ppp_min})",
                    {"ppp_effectif": round(ppp_effectif, 1), "ppp_minimum": fmt.ppp_min},
                )
            )
        else:
            ok = echelle <= 2.0
            constats.append(
                Constat(
                    "QC-RESOLUTION",
                    True,
                    ok,
                    f"fond agrandi {echelle:.2f}× pour l'écran (2× au plus)",
                    {"agrandissement": ratio},
                )
            )
    elif plan.impression and plan.ppp < fmt.ppp_min:
        constats.append(
            Constat(
                "QC-RESOLUTION",
                True,
                False,
                f"rendu à {plan.ppp} ppp, {fmt.ppp_min} ppp exigés pour ce gabarit",
                {"ppp": plan.ppp, "ppp_minimum": fmt.ppp_min},
            )
        )
    else:
        constats.append(Constat("QC-RESOLUTION", True, True, "aucun fond raster : texte et aplats vectoriels"))


def _controler_langue(constats: list[Constat], composition: Composition, politique: PolitiqueControle) -> None:
    aires: dict[str, float] = {"fr": 0.0, "en": 0.0}
    for ligne in composition.plan.lignes:
        if ligne.langue in aires:
            aires[ligne.langue] += ligne.largeur_px * ligne.taille_px
    if aires["en"] == 0.0:
        constats.append(
            Constat(
                "QC-LANGUE-FR",
                True,
                True,
                "texte entièrement en français (heuristique ; seuil à valider par un avocat)",
                {"aire_fr": round(aires["fr"], 1), "aire_en": 0.0},
            )
        )
        return
    rapport = aires["fr"] / aires["en"]
    constats.append(
        Constat(
            "QC-LANGUE-FR",
            True,
            rapport >= politique.ratio_francais_min,
            f"surface du français / autre langue = {rapport:.2f} (seuil {politique.ratio_francais_min}, "
            "HEURISTIQUE : le seuil réglementaire de « nettement prédominant » n'est pas établi ; à valider par un "
            "avocat)",
            {"ratio": round(rapport, 3), "seuil": politique.ratio_francais_min},
        )
    )


def _controler_marquage(constats: list[Constat], composition: Composition) -> None:
    marquage, ia = composition.marquage, composition.brief.genere
    problemes = []
    if bool(marquage.get("ia_generee")) != ia:
        problemes.append("le marquage ne correspond pas à la nature du fond")
    if ia and not marquage.get("provenance"):
        problemes.append("fond généré sans empreinte de provenance")
    lus: dict[str, Any] = {}
    try:
        lus["png"] = json.loads(png.metadonnees(composition.artefacts["png"]).get(rendus.CLE_MARQUAGE_PNG, "null"))
        lus["svg"] = rendus.lire_svg(composition.artefacts["svg"])["metadonnees"]
        if "pdf" in composition.artefacts:
            lus["pdf"] = rendus.lire_pdf(composition.artefacts["pdf"])["marquage"]
    except (png.PngInvalide, rendus.SvgInvalide, rendus.PdfInvalide, json.JSONDecodeError, KeyError) as exc:
        problemes.append(f"marquage illisible : {exc}")
    for format_, lu in lus.items():
        if lu != dict(marquage):
            problemes.append(f"le marquage de l'artefact {format_} diffère de celui de la composition")
    constats.append(
        Constat(
            "QC-MARQUAGE-IA",
            True,
            not problemes,
            "marquage « généré par IA » cohérent dans tous les artefacts" if not problemes else " ; ".join(problemes),
            {"ia_generee": ia},
        )
    )


def _controler_licence(
    constats: list[Constat],
    composition: Composition,
    verdict_licence: Callable[[], Mapping[str, Any] | None] | None,
    mention_requise: str | None,
) -> None:
    if not composition.brief.genere:
        constats.append(Constat("QC-LICENCE", True, True, "aucun modèle utilisé : aucune licence de modèle à vérifier"))
        return
    verdict = verdict_licence() if verdict_licence is not None else None
    if verdict is None:
        constats.append(
            Constat("QC-LICENCE", True, False, "licence du modèle NON vérifiée au moment du contrôle (fail-closed)")
        )
    else:
        constats.append(
            Constat(
                "QC-LICENCE",
                True,
                bool(verdict.get("conforme")),
                "licence du modèle revérifiée conforme au profil du client"
                if verdict.get("conforme")
                else f"licence du modèle non conforme maintenant : {verdict.get('codes')}",
                {"fournisseur": verdict.get("fournisseur_id"), "codes": verdict.get("codes")},
            )
        )
    if mention_requise:
        presente = mention_requise in composition.brief.mentions
        constats.append(
            Constat(
                "QC-MENTION-LICENCE",
                True,
                presente,
                f"la mention exigée par la licence du modèle est posée : « {mention_requise} »"
                if presente
                else f"la licence du modèle exige la mention « {mention_requise} » : l'ajouter aux mentions "
                "obligatoires du brief",
            )
        )


def _controler_couleur(constats: list[Constat], brief: Any) -> None:
    """Le profil couleur DÉCLARÉ : les artefacts sont en RVB (sRGB). Un brief qui demande du CMJN n'est pas servi : le
    constat n'est pas critique (la revue humaine et l'imprimeur décident) mais il dit la vérité (R5 §4.1)."""
    demande = brief.donnees["couleur"]
    constats.append(Constat(
        "QC-COULEUR", False, demande == "rvb",
        "profil couleur RVB (sRGB) déclaré" if demande == "rvb" else
        "CMJN demandé et NON réalisé : les artefacts sont en RVB, sans profil de sortie ni PDF/X ; la conversion et le "
        "preflight reviennent à l'imprimeur (plan : WeasyPrint ≥ 67, Little CMS, pikepdf)",
        {"profil_demande": demande, "profil_livre": "rvb"}))


def _controler_prix(constats: list[Constat], brief: Any, maintenant: dt.datetime) -> None:
    aujourd_hui = maintenant.astimezone(dt.UTC).date()
    expires = [
        e["valeur"]
        for e in brief.elements_critiques
        if e["type"] == "prix" and dt.date.fromisoformat(e["valide_jusqu_au"]) < aujourd_hui
    ]
    if any(e["type"] == "prix" for e in brief.elements_critiques):
        constats.append(
            Constat(
                "QC-PRIX-VALIDITE",
                True,
                not expires,
                "prix encore valides" if not expires else f"prix expiré(s) : {expires}",
            )
        )


def _controler_polices(constats: list[Constat], composition: Composition, polices: RegistrePolices) -> None:
    problemes = []
    for identifiant in composition.plan.polices:
        try:
            police = polices.obtenir(identifiant)
        except Exception as exc:  # noqa: BLE001 - tout échec de résolution est un constat
            problemes.append(f"{identifiant} : {exc}")
            continue
        if police.licence != "OFL-1.1":
            problemes.append(f"{identifiant} : licence {police.licence}")
        manquants = police.ttf.couvre("".join(ligne.texte for ligne in composition.plan.lignes))
        if manquants:
            problemes.append(f"{identifiant} : glyphes absents {sorted(manquants)}")
    constats.append(
        Constat(
            "QC-POLICES",
            True,
            not problemes,
            "polices OFL épinglées, glyphes présents" if not problemes else " ; ".join(problemes),
            {"polices": list(composition.plan.polices)},
        )
    )


def _controler_reproductibilite(constats: list[Constat], composition: Composition, polices: RegistrePolices) -> None:
    plan, marquage, fond = composition.plan, composition.marquage, composition.fond_png
    problemes = []
    try:
        if rendus.rendre_svg(plan, fond, polices, marquage) != composition.artefacts.get("svg"):
            problemes.append("svg")
        refait = png.decoder(rendus.rendre_png(plan, fond, polices, marquage))
        if refait != png.decoder(composition.artefacts["png"]):
            problemes.append("png")
        if (
            "pdf" in composition.artefacts
            and rendus.rendre_pdf(plan, fond, polices, marquage) != composition.artefacts["pdf"]
        ):
            problemes.append("pdf")
        dims = png.dimensions(composition.artefacts["png"])
        if dims != (plan.largeur_px, plan.hauteur_px):
            problemes.append(f"dimensions du png {dims}")
    except (KeyError, png.PngInvalide, ValueError) as exc:
        problemes.append(f"rendu impossible : {exc}")
    constats.append(
        Constat(
            "QC-REPRODUCTIBILITE",
            True,
            not problemes,
            "le plan, refait, redonne exactement les artefacts (pixels du PNG, octets du SVG et du PDF)"
            if not problemes
            else f"artefact(s) différent(s) du plan : {problemes}",
        )
    )
    constats.append(
        Constat(
            "QC-FORMAT",
            True,
            set(composition.artefacts) == ({"svg", "png", "pdf"} if plan.impression else {"svg", "png"}),
            "jeu d'artefacts attendu pour ce gabarit",
        )
    )
