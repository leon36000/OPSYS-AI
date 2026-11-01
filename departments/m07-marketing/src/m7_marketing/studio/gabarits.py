"""Les gabarits déterministes : carte d'affaires, affiche, bannière de réseau social, image de couverture.

Un gabarit transforme un brief (+ une police OFL épinglée, une couleur de fond, un logo vectoriel facultatif) en
`plan.Plan` : mêmes entrées, même plan, au pixel près. TOUT le texte, le logo et les mentions sont posés ici ; l'image
générée n'est qu'un fond (R5 §0 n°3). Le gabarit ne modifie jamais un texte : il l'envoie à la ligne sur les espaces
(et, pour une adresse, d'abord après les virgules) ou il REFUSE (`REJ-STUDIO-TEXTE-NE-TIENT-PAS`). Il ne tronque pas,
ne coupe pas un mot et ne descend pas sous la taille minimale.

Mise en page (hypothèses de R5 §4.2, niveau [S] : usage courant des imprimeurs, À CONFIRMER auprès de l'imprimeur) :
  - fond perdu de 0,125 po par côté, zone de sécurité de 0,125 po vers l'intérieur du format fini ;
  - carte d'affaires 3,5 × 2 po (texte ≥ 7 pt), affiches 11 × 17 et 18 × 24 po ;
  - réseaux sociaux (pixels) : 1080×1350, 1080×1080, 1080×1920, 1200×627, 1280×720 ; couverture 1640×624 [S] ;
    zone de sécurité de 5 %, et pour le 9:16 les bandes réservées à l'interface (haut 14 %, bas 20 %) [S].
Le texte vit toujours sur un PANNEAU de la couleur primaire de la marque : le contraste ne dépend pas du fond généré.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from typing import Any

from . import plan as p
from .brief import Brief
from .polices import Police, PoliceErreur, RegistrePolices
from .toile import hex_couleur, rapport_contraste

REJ_TEXTE_NE_TIENT_PAS = "REJ-STUDIO-TEXTE-NE-TIENT-PAS"
REJ_POLICE_GLYPHE = "REJ-STUDIO-POLICE-GLYPHE-ABSENT"
REJ_FORMAT = "REJ-STUDIO-FORMAT-INCONNU"
FACTEUR_ANGLAIS = 0.65  # l'anglais est posé plus petit que le français (français nettement prédominant)


# Libellés posés devant une donnée critique ambiguë seule (un numéro nu ne dit pas ce qu'il est). Ils font partie du
# texte affiché ET du texte que le contrôle qualité attend : `texte_affiche`.
LIBELLES = {"telephone": "Tél. :", "licence_rbq": "Licence RBQ :", "neq": "NEQ :", "prix": "Prix :"}


def texte_affiche(type_critique: str, valeur: str) -> str:
    """Le texte exact posé pour un élément critique (libellé éventuel, une espace, la valeur du brief)."""
    libelle = LIBELLES.get(type_critique)
    return f"{libelle} {valeur}" if libelle else valeur


class GabaritErreur(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail


@dataclasses.dataclass(frozen=True)
class FormatPiece:
    gabarit: str
    nom: str
    impression: bool
    largeur: float  # pouces (impression) ou pixels (écran)
    hauteur: float
    fond_perdu_po: float
    surete: float  # pouces (impression) ou fraction de la dimension de référence (écran)
    ppp_defaut: int
    ppp_min: int
    taille_min_pt: float
    cibles: Mapping[str, float]  # rôle -> points (impression) ou fraction de sqrt(L×H) (écran)
    reserve_haut: float = 0.0
    reserve_bas: float = 0.0
    source: str = "R5 §4.2 [S]"


_CARTE = {"marque": 14, "titre": 12, "sous_titre": 9, "appel_action": 9, "critique": 8, "mention": 7}
_AFFICHE_11 = {"marque": 40, "titre": 60, "sous_titre": 28, "appel_action": 32, "critique": 22, "mention": 14}
_AFFICHE_18 = {k: round(v * 1.6) for k, v in _AFFICHE_11.items()}
_ECRAN = {
    "marque": 0.040,
    "titre": 0.065,
    "sous_titre": 0.036,
    "appel_action": 0.045,
    "critique": 0.030,
    "mention": 0.024,
}

FORMATS: dict[tuple[str, str], FormatPiece] = {
    ("carte_affaires", "3.5x2"): FormatPiece(
        "carte_affaires", "3.5x2", True, 3.5, 2.0, 0.125, 0.125, 300, 300, 7.0, _CARTE, source="R5 §4.2 l.270 [S]"
    ),
    ("affiche", "11x17"): FormatPiece(
        "affiche",
        "11x17",
        True,
        11.0,
        17.0,
        0.125,
        0.25,
        150,
        150,
        12.0,
        _AFFICHE_11,
        source="R5 §4.2 l.276 [S] ; texte minimal 12 pt : heuristique",
    ),
    ("affiche", "18x24"): FormatPiece(
        "affiche", "18x24", True, 18.0, 24.0, 0.125, 0.25, 150, 150, 12.0, _AFFICHE_18, source="R5 §4.2 l.277 [S]"
    ),
    **{
        ("banniere_social", n): FormatPiece(
            "banniere_social",
            n,
            False,
            float(n.split("x")[0]),
            float(n.split("x")[1]),
            0.0,
            0.05,
            72,
            72,
            0.0,
            _ECRAN,
            source="R5 §4.2 l.279 [S]",
        )
        for n in ("1200x627", "1080x1350", "1080x1080", "1280x720")
    },
    ("banniere_social", "1080x1920"): FormatPiece(
        "banniere_social",
        "1080x1920",
        False,
        1080.0,
        1920.0,
        0.0,
        0.05,
        72,
        72,
        0.0,
        _ECRAN,
        reserve_haut=0.14,
        reserve_bas=0.20,
        source="R5 §4.2 l.279 [S] ; bandes d'interface [S]",
    ),
    ("couverture", "1640x624"): FormatPiece(
        "couverture",
        "1640x624",
        False,
        1640.0,
        624.0,
        0.0,
        0.05,
        72,
        72,
        0.0,
        _ECRAN,
        source="dimension courante d'une couverture (2×820×312) [S]",
    ),
}


@dataclasses.dataclass(frozen=True)
class Geometrie:
    largeur: int
    hauteur: int
    fond_perdu: int
    rognage: p.Boite
    surete: p.Boite
    taille_min_px: float
    reservees: tuple[p.Boite, ...]
    ppp: int


def format_de(gabarit: str, nom: str) -> FormatPiece:
    try:
        return FORMATS[(gabarit, nom)]
    except KeyError:
        raise GabaritErreur(REJ_FORMAT, f"gabarit {gabarit!r}, format {nom!r} inconnu") from None


def geometrie(fmt: FormatPiece, ppp: int) -> Geometrie:
    if fmt.impression:
        fp = round(fmt.fond_perdu_po * ppp)
        largeur = round(fmt.largeur * ppp) + 2 * fp
        hauteur = round(fmt.hauteur * ppp) + 2 * fp
        rognage = (float(fp), float(fp), float(largeur - fp), float(hauteur - fp))
        marge = round(fmt.surete * ppp)
        surete = (rognage[0] + marge, rognage[1] + marge, rognage[2] - marge, rognage[3] - marge)
        return Geometrie(largeur, hauteur, fp, rognage, surete, fmt.taille_min_pt * ppp / 72, (), ppp)
    largeur, hauteur = int(fmt.largeur), int(fmt.hauteur)
    ref = math.sqrt(largeur * hauteur)
    marge = round(fmt.surete * min(largeur, hauteur))
    haut = round(fmt.reserve_haut * hauteur)
    bas = round(fmt.reserve_bas * hauteur)
    surete = (float(marge), float(max(marge, haut)), float(largeur - marge), float(hauteur - max(marge, bas)))
    reservees = tuple(
        b
        for b in (
            (0.0, 0.0, float(largeur), float(haut)) if haut else None,
            (0.0, float(hauteur - bas), float(largeur), float(hauteur)) if bas else None,
        )
        if b
    )
    return Geometrie(
        largeur,
        hauteur,
        0,
        (0.0, 0.0, float(largeur), float(hauteur)),
        surete,
        max(18.0, round(0.021 * ref)),
        reservees,
        72,
    )


def _taille_cible(fmt: FormatPiece, geo: Geometrie, role: str) -> float:
    cible = fmt.cibles[role]
    if fmt.impression:
        return cible * geo.ppp / 72
    return cible * math.sqrt(geo.largeur * geo.hauteur)


# -- contenu --------------------------------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Item:
    id: str
    role: str  # marque | titre | sous_titre | appel_action | critique | mention
    texte: str
    langue: str | None
    critique: str | None
    lignes_max: int
    coupures: tuple[str, ...]  # séparateurs préférés avant les espaces


def _items(brief: Brief) -> dict[str, list[Item]]:
    marque = [Item("marque", "marque", brief.marque["nom"], None, "marque", 2, ())]
    message: list[Item] = []
    for role in ("titre", "sous_titre", "appel_action"):
        par_langue = brief.textes.get(role)
        if not par_langue:
            continue
        for langue in brief.langues:
            if langue in par_langue:
                message.append(
                    Item(
                        f"{role}.{langue}",
                        role,
                        par_langue[langue],
                        langue,
                        None,
                        3 if role != "appel_action" else 2,
                        (),
                    )
                )
    contact = []
    compteurs: dict[str, int] = {}
    for element in brief.elements_critiques:
        type_ = element["type"]
        compteurs[type_] = compteurs.get(type_, 0) + 1
        contact.append(
            Item(
                f"critique.{type_}.{compteurs[type_] - 1}",
                "critique",
                texte_affiche(type_, element["valeur"]),
                None,
                type_,
                3 if type_ == "adresse" else 1,
                (", ",) if type_ == "adresse" else (),
            )
        )
    mentions = [
        Item(f"mention.{i}", "mention", texte, None, "mention", 3, ()) for i, texte in enumerate(brief.mentions)
    ]
    return {"identite": marque, "message": message, "contact": contact, "mentions": mentions}


def _panneaux(gabarit: str, geo: Geometrie) -> list[tuple[p.Boite, tuple[str, ...]]]:
    L, H = float(geo.largeur), float(geo.hauteur)
    rogn, surete = geo.rognage, geo.surete
    tout = ("identite", "message", "contact", "mentions")
    if gabarit == "carte_affaires":
        return [((0.0, 0.0, rogn[0] + 0.62 * (rogn[2] - rogn[0]), H), tout)]
    if gabarit == "affiche":
        haut = (0.0, 0.0, L, rogn[1] + 0.34 * (rogn[3] - rogn[1]))
        bas = (0.0, H - (rogn[1] + 0.30 * (rogn[3] - rogn[1])), L, H)
        return [(haut, ("identite", "message")), (bas, ("contact", "mentions"))]
    if gabarit == "couverture":
        return [((0.0, 0.0, 0.46 * L, H), tout)]
    if L > H:
        return [((0.0, 0.0, 0.58 * L, H), tout)]
    if geo.reservees:  # 9:16 : le panneau reste entre les bandes d'interface
        return [((0.0, surete[1] + 0.30 * (surete[3] - surete[1]), L, surete[3]), tout)]
    return [((0.0, 0.50 * H, L, H), tout)]


def choisir_couleurs(couleurs: Sequence[str]) -> tuple[p.Couleur, p.Couleur, p.Couleur]:
    """(panneau, texte, filet). Le texte est la couleur de contraste le plus élevé avec le panneau, parmi blanc, noir et
    la palette de la marque. Pour toute couleur de panneau, le blanc ou le noir atteint au moins 4,58:1 (le maximum des
    deux est minimal vers L = 0,179) : le seuil AA de 4,5:1 est donc toujours atteignable, aucun refus n'existe ici."""
    panneau = tuple(int(couleurs[0][i : i + 2], 16) for i in (1, 3, 5))
    candidates = [(255, 255, 255), (0, 0, 0), *[tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in couleurs[1:]]]
    meilleure = max(candidates, key=lambda c: (rapport_contraste(c, panneau), c))
    filet = tuple(int(couleurs[1][i : i + 2], 16) for i in (1, 3, 5)) if len(couleurs) > 1 else meilleure
    return panneau, meilleure, filet  # type: ignore[return-value]


def _atomes(texte: str, coupures: tuple[str, ...]) -> list[str]:
    """Unités insécables : le texte coupé après chaque séparateur préféré (« , »). Joindre les atomes par une espace
    redonne exactement le texte (le séparateur finit par une espace)."""
    atomes = [texte]
    for separateur in coupures:
        suivants: list[str] = []
        for atome in atomes:
            parties = atome.split(separateur)
            suivants += [x + separateur.rstrip(" ") for x in parties[:-1]] + [parties[-1]]
        atomes = suivants
    return atomes


def envelopper(
    texte: str, ttf: Any, taille: float, largeur_max: float, lignes_max: int, coupures: tuple[str, ...]
) -> list[str] | None:
    """Les lignes du texte, ou `None` si un mot dépasse la largeur ou si les lignes dépassent `lignes_max`. Propriété
    garantie : `" ".join(lignes) == texte` (aucun caractère ajouté, retiré ni déplacé)."""
    if ttf.largeur(texte, taille) <= largeur_max:
        return [texte]
    lignes: list[str] = []
    courante = ""
    for atome in _atomes(texte, coupures):
        unites = [atome] if ttf.largeur(atome, taille) <= largeur_max else atome.split(" ")
        for unite in unites:
            if ttf.largeur(unite, taille) > largeur_max:
                return None
            essai = unite if not courante else courante + " " + unite
            if ttf.largeur(essai, taille) <= largeur_max:
                courante = essai
            else:
                lignes.append(courante)
                courante = unite
    if courante:
        lignes.append(courante)
    return lignes if 1 <= len(lignes) <= lignes_max else None


def _disposer(
    items: Sequence[Item],
    facteur: float,
    largeur_max: float,
    fmt: FormatPiece,
    geo: Geometrie,
    police: Police,
) -> tuple[list[tuple[Item, float, list[str]]], float, bool] | None:
    """(dispositions, hauteur totale, tout_au_minimum) pour ce facteur d'échelle, ou `None` si un mot ne tient pas."""
    dispositions: list[tuple[Item, float, list[str]]] = []
    total = 0.0
    au_minimum = True
    for item in items:
        cible = _taille_cible(fmt, geo, item.role)
        brute = cible * facteur * (FACTEUR_ANGLAIS if item.langue == "en" else 1.0)
        taille = max(geo.taille_min_px, brute)
        au_minimum = au_minimum and brute <= geo.taille_min_px
        lignes = envelopper(item.texte, police.ttf, taille, largeur_max, item.lignes_max, item.coupures)
        if lignes is None:
            return None
        dispositions.append((item, taille, lignes))
        total += len(lignes) * 1.25 * taille + 0.35 * taille
    return dispositions, total - 0.35 * dispositions[-1][1], au_minimum


def _empiler(
    items: Sequence[Item],
    boite: p.Boite,
    fmt: FormatPiece,
    geo: Geometrie,
    police: Police,
    couleur: p.Couleur,
    reserve_haut: float,
) -> list[p.Ligne]:
    """Pose les items en pile verticale dans `boite`, tailles réduites uniformément jusqu'à ce que tout tienne."""
    if not items:
        return []
    largeur_max = boite[2] - boite[0]
    hauteur_max = boite[3] - boite[1] - reserve_haut
    ne_tient_pas = GabaritErreur(
        REJ_TEXTE_NE_TIENT_PAS,
        "le texte ne tient pas dans la zone de sécurité à la taille minimale : raccourcir le brief "
        "(le gabarit ne tronque, ne coupe ni ne rapetisse sous le minimum)",
    )
    if largeur_max <= 0 or hauteur_max <= 0:
        raise ne_tient_pas
    ttf = police.ttf
    asc = ttf.ascendante / ttf.unites_par_em
    desc = -ttf.descendante / ttf.unites_par_em
    facteur = 1.0
    retenue = None
    while facteur >= 0.05:
        disposition = _disposer(items, facteur, largeur_max, fmt, geo, police)
        if disposition is not None and disposition[1] <= hauteur_max:
            retenue = disposition[0]
            break
        if disposition is not None and disposition[2]:
            break  # tout est déjà à la taille minimale : réduire davantage ne change plus rien
        facteur *= 0.96
    if retenue is None:
        raise ne_tient_pas
    lignes_posees: list[p.Ligne] = []
    y = boite[1] + reserve_haut
    for item, taille, lignes in retenue:
        for n, ligne in enumerate(lignes):
            baseline = y + 0.95 * taille
            largeur = ttf.largeur(ligne, taille)
            boite_ligne = (boite[0], baseline - asc * taille, boite[0] + largeur, baseline + desc * taille)
            lignes_posees.append(
                p.Ligne(
                    id=item.id,
                    n=n,
                    texte=ligne,
                    x=boite[0],
                    baseline=baseline,
                    taille_px=taille,
                    couleur=couleur,
                    police_id=police.id,
                    role=item.role,
                    langue=item.langue,
                    critique=item.critique,
                    largeur_px=largeur,
                    boite=boite_ligne,
                )
            )
            y += 1.25 * taille
        y += 0.35 * taille
    return lignes_posees


def _intersection(a: p.Boite, b: p.Boite) -> p.Boite:
    return max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])


def composer(
    brief: Brief,
    polices: RegistrePolices,
    police_id: str,
    *,
    ppp: int | None = None,
    fond: Mapping[str, Any],
    logo: Mapping[str, Any] | None = None,
) -> p.Plan:
    """Le plan du brief. `fond` : `{"mode", "couleur", "couleur2"?, "actif_sha256"?, "largeur_px"?, "hauteur_px"?}`.
    `logo` : `{"chemins": [...], "vb_w", "vb_h", "id"}` d'un logo vectoriel approuvé, ou `None`."""
    fmt = format_de(brief.gabarit, brief.format)
    ppp_effectif = ppp or brief.donnees.get("ppp") or fmt.ppp_defaut
    geo = geometrie(fmt, ppp_effectif)
    police = polices.obtenir(police_id)
    manquants = police.ttf.couvre(
        "".join(
            [
                brief.marque["nom"],
                *brief.mentions,
                *(t for v in brief.textes.values() for t in v.values()),
                *(e["valeur"] for e in brief.elements_critiques),
            ]
        )
    )
    if manquants:
        raise GabaritErreur(
            REJ_POLICE_GLYPHE, f"la police {police_id} n'a pas de glyphe pour : {''.join(sorted(manquants))!r}"
        )
    try:
        panneau, couleur_texte, filet = choisir_couleurs(brief.marque["couleurs"])
        contenu = _items(brief)
        elements: list[Any] = []
        lignes: list[p.Ligne] = []
        logo_pose = None
        pad = 0.03 * min(geo.largeur, geo.hauteur)
        for index, (boite, groupes) in enumerate(_panneaux(brief.gabarit, geo)):
            elements.append(
                p.Rect(
                    f"panneau.{index}",
                    boite[0],
                    boite[1],
                    boite[2] - boite[0],
                    boite[3] - boite[1],
                    panneau,
                    0.96,
                    "panneau",
                )
            )
            elements.append(
                p.Rect(
                    f"filet.{index}",
                    boite[0],
                    boite[1],
                    boite[2] - boite[0],
                    max(2.0, round(0.012 * min(geo.largeur, geo.hauteur))),
                    filet,
                    1.0,
                    "filet",
                )
            )
            interieur = _intersection((boite[0] + pad, boite[1] + pad, boite[2] - pad, boite[3] - pad), geo.surete)
            reserve = 0.0
            if logo is not None and index == 0 and "identite" in groupes:
                hauteur_logo = 0.14 * (interieur[3] - interieur[1])
                largeur_logo = hauteur_logo * float(logo["vb_w"]) / float(logo["vb_h"])
                logo_pose = p.LogoPose(
                    str(logo["id"]),
                    tuple(logo["chemins"]),
                    float(logo["vb_w"]),
                    float(logo["vb_h"]),
                    interieur[0],
                    interieur[1],
                    largeur_logo,
                    hauteur_logo,
                    couleur_texte,
                )
                reserve = hauteur_logo + 0.4 * hauteur_logo
            items = [it for g in groupes for it in contenu[g]]
            lignes += _empiler(items, interieur, fmt, geo, police, couleur_texte, reserve)
        if logo_pose is not None:
            elements.append(logo_pose)
        elements += lignes
    except PoliceErreur as exc:
        raise GabaritErreur(REJ_POLICE_GLYPHE, exc.detail) from None
    fond_normal = dict(fond)
    fond_normal.setdefault("couleur", hex_couleur(panneau))
    return p.Plan(
        gabarit=brief.gabarit,
        format=brief.format,
        largeur_px=geo.largeur,
        hauteur_px=geo.hauteur,
        ppp=geo.ppp,
        impression=fmt.impression,
        fond_perdu_px=geo.fond_perdu,
        rognage=geo.rognage,
        surete=geo.surete,
        fond=fond_normal,
        elements=tuple(elements),
        polices=(police_id,),
        taille_min_px=geo.taille_min_px,
        zones_reservees=geo.reservees,
    )
