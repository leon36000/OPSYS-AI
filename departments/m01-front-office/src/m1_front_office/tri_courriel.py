"""Tri déterministe des courriels de M1 (M1.6) : une classe, une confiance, des raisons, un aiguillage.

Entrée : la vue NEUTRALISÉE d'un courriel (objet, corps, expéditeur, verdicts d'authentification rapportés, nombre de
pièces). Sortie : la classe parmi `tri_regles.CLASSES`, une confiance de 0 à 1 (formule fixe), la liste des règles
déclenchées avec leur libellé, le département aiguillé et si une personne doit relire. AUCUN modèle, aucune horloge,
aucun réseau, aucune action externe : le tri ne fait que décrire. Les effets (événement d'aiguillage, ouverture d'un
transfert pour une plainte) sont à l'adaptateur (`tri_courriel_outils`), jamais ici.

Garde-fous structurels (ils ne dépendent d'aucune règle apprise) :
- `interne` n'est possible que si l'expéditeur est du domaine de l'entreprise ET si SPF, DKIM et DMARC rapportés sont
  tous « pass » ; un courriel qui porte le domaine de l'entreprise sans cette preuve compte comme usurpation
  (hameçonnage) ;
- un texte déjà neutralisé (consigne cachée reconnue) force la relecture humaine ; il ne change jamais la classe : une
  consigne glissée dans un courriel ne peut pas choisir où il va ;
- à égalité, la classe la plus prudente l'emporte (`tri_regles.PRESEANCE`) ; sous le seuil d'indices, la classe est
  `autre`, jamais une devinette.
"""

from __future__ import annotations

import dataclasses
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from . import provenance
from .tri_regles import CLASSES, JEU_V1, PRESEANCE, JeuRegles, RegleTri

SEUIL_INDICES = 3  # score minimal de la meilleure classe ; en dessous : « autre »
SEUIL_CONFIANCE = Decimal("0.60")  # en dessous : relecture humaine
ECART_MIN_SANS_REVUE = 2  # écart minimal avec la deuxième classe pour se passer de relecture
TEXTE_MAX = 20_000

# Où va chaque classe. « m02 » : le lead naît déjà du pipeline de réception de M1 (`m1.lead_qualifie`) ; le tri ne
# crée jamais un second lead.
AIGUILLAGE: Mapping[str, str] = {
    "demande_soumission": "m02",
    "plainte": "m01_plaintes",
    "facture_fournisseur": "m05",
    "commande_materiaux": "m06",
    "confirmation_fournisseur": "m06",
    "reponse_client": "m01_suivi",
    "interne": "aucun",
    "pourriel_hameconnage": "quarantaine",
    "autre": "revue_humaine",
}

_ZERO_LARGEUR = re.compile("[​‌‍⁠﻿]")
_LIGNE_DE_FIL = re.compile(
    r"^\s*(?:le .{5,80} a [ée]crit\s*:|on .{5,80} wrote\s*:|-{2,}\s*(?:message d'origine|original message))",
    re.IGNORECASE,
)
_ENTETE_DE = re.compile(r"^\s*de\s*:", re.IGNORECASE)
_ENTETE_ENVOYE = re.compile(r"^\s*(?:envoy[ée]|date)\s*:", re.IGNORECASE)
_LIGNE_MAX = 300  # une ligne plus longue n'est pas un en-tête de fil : on ne la lit pas plus loin (temps linéaire)
_LETTRES_ESPACEES = re.compile(r"(?<![a-z0-9])((?:[a-z] ){3,}[a-z])(?![a-z0-9])")
_MAJ_MOTS = re.compile(r"\s+")


@dataclasses.dataclass(frozen=True)
class CourrielATrier:
    objet: str
    corps: str
    expediteur: str
    spf: str = "absent"
    dkim: str = "absent"
    dmarc: str = "absent"
    nb_pieces: int = 0
    neutralise: bool = False
    domaines_entreprise: tuple[str, ...] = ()
    # Vrai seulement si le serveur qui a écrit les verdicts SPF/DKIM/DMARC est un serveur de réception de confiance
    # déclaré (`Authentification.fiable`). Sinon l'en-tête a pu être écrit par l'expéditeur : aucun verdict ne compte
    # comme preuve.
    auth_fiable: bool = True


@dataclasses.dataclass(frozen=True)
class RegleDeclenchee:
    identifiant: str
    libelle: str
    poids: int

    def vers_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ResultatTri:
    classe: str
    confiance: str
    scores: Mapping[str, int]
    raisons: tuple[RegleDeclenchee, ...]
    aiguillage: str
    revue_humaine: bool
    motifs_revue: tuple[str, ...]
    version_regles: str
    empreinte_regles: str
    deuxieme_classe: str | None

    def vers_json(self) -> dict[str, Any]:
        return {
            "classe": self.classe,
            "confiance": self.confiance,
            "scores": dict(self.scores),
            "raisons": [r.vers_json() for r in self.raisons],
            "aiguillage": self.aiguillage,
            "revue_humaine": self.revue_humaine,
            "motifs_revue": list(self.motifs_revue),
            "version_regles": self.version_regles,
            "empreinte_regles": self.empreinte_regles,
            "deuxieme_classe": self.deuxieme_classe,
        }


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, sans caractères de largeur nulle, espaces réduits, lettres espacées recollées."""
    if not isinstance(texte, str):
        return ""
    t = unicodedata.normalize("NFKC", texte[:TEXTE_MAX])
    t = _ZERO_LARGEUR.sub("", t)
    t = unicodedata.normalize("NFKD", t.lower().replace("’", "'"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _MAJ_MOTS.sub(" ", t)
    return _LETTRES_ESPACEES.sub(lambda m: m.group(1).replace(" ", ""), t).strip()


def _sans_fil_cite(corps: str) -> str:
    """Le texte NOUVEAU du message : sans lignes citées (« > ») ni historique du fil. Lecture ligne par ligne, bornée :
    aucun motif ne relit une suite à chaque départ."""
    lignes = corps.splitlines()
    gardees: list[str] = []
    for i, ligne in enumerate(lignes):
        debut = ligne[:_LIGNE_MAX]
        if _LIGNE_DE_FIL.match(debut) or (
            _ENTETE_DE.match(debut) and i + 1 < len(lignes) and _ENTETE_ENVOYE.match(lignes[i + 1][:_LIGNE_MAX])
        ):
            break
        if debut.lstrip().startswith(">"):
            continue
        gardees.append(ligne)
    return "\n".join(gardees)


def _domaine(adresse: str) -> str:
    return adresse.rsplit("@", 1)[-1].strip().lower() if "@" in adresse else ""


def est_domaine_interne(courriel: CourrielATrier) -> bool:
    d = _domaine(courriel.expediteur)
    return bool(d) and d in {x.lower() for x in courriel.domaines_entreprise}


def auth_complete(courriel: CourrielATrier) -> bool:
    return courriel.auth_fiable and courriel.spf == courriel.dkim == courriel.dmarc == "pass"


def _confiance(haut: int, deuxieme: int) -> Decimal:
    if haut <= 0:
        return Decimal("0.00")
    brut = Decimal(max(haut - deuxieme, 0) + 1) / Decimal(haut + 2)
    return min(brut, Decimal("0.99")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _champs(courriel: CourrielATrier) -> dict[str, str]:
    objet = normaliser(courriel.objet)
    corps = normaliser(_sans_fil_cite(courriel.corps))
    return {"objet": objet, "corps": corps, "tout": f"{objet}\n{corps}".strip()}


def _regle_applicable(regle: RegleTri, champs: Mapping[str, str]) -> bool:
    return re.search(regle.motif, champs[regle.champ], re.MULTILINE) is not None


def classer(courriel: CourrielATrier, jeu: JeuRegles = JEU_V1) -> ResultatTri:
    """Classe un courriel. Pure et déterministe : mêmes entrées, même résultat."""
    champs = _champs(courriel)
    declenchees: list[tuple[RegleTri, int]] = [(r, r.poids) for r in jeu.regles if _regle_applicable(r, champs)]
    scores = {c: 0 for c in CLASSES}
    for regle, poids in declenchees:
        scores[regle.classe] += poids
    raisons = [RegleDeclenchee(r.identifiant, r.libelle, p) for r, p in declenchees]

    # -- méta : authentification, domaine, pièces jointes -------------------------------------------------------
    interne = est_domaine_interne(courriel)
    if interne and not auth_complete(courriel):
        scores["pourriel_hameconnage"] += 5
        raisons.append(
            RegleDeclenchee(
                "meta-usurpation-domaine",
                "porte le domaine de l'entreprise sans preuve "
                "d'authentification complète (SPF, DKIM, DMARC) : usurpation possible",
                5,
            )
        )
    elif interne:
        scores["interne"] += 2  # un a priori seulement : un collègue peut aussi demander des matériaux
        raisons.append(
            RegleDeclenchee(
                "meta-domaine-interne", "expéditeur du domaine de l'entreprise, authentification complète", 2
            )
        )
    else:
        scores["interne"] = 0  # sans la preuve, aucune règle de vie d'équipe ne fait un courriel interne
    echecs = sum(v in ("fail", "softfail") for v in (courriel.spf, courriel.dkim, courriel.dmarc))
    if courriel.dmarc == "fail" or courriel.spf == "fail":
        scores["pourriel_hameconnage"] += 2
        raisons.append(RegleDeclenchee("meta-auth-echec", "l'authentification de l'expéditeur a échoué", 2))
    elif echecs:
        scores["pourriel_hameconnage"] += 1
        raisons.append(RegleDeclenchee("meta-auth-douteuse", "l'authentification de l'expéditeur est douteuse", 1))
    if courriel.nb_pieces > 0 and scores["facture_fournisseur"] >= 2:
        scores["facture_fournisseur"] += 1
        raisons.append(
            RegleDeclenchee("meta-piece-jointe", "pièce jointe présente avec un vocabulaire de facturation", 1)
        )

    # -- décision ---------------------------------------------------------------------------------------------------
    scores = {c: max(v, 0) for c, v in scores.items()}
    ordre = sorted(PRESEANCE, key=lambda c: (-scores[c], PRESEANCE.index(c)))
    haut, deuxieme = ordre[0], ordre[1]
    motifs: list[str] = []
    if scores[haut] < SEUIL_INDICES:
        classe = "autre"
        motifs.append("indices_insuffisants")
        deuxieme_classe = haut if scores[haut] > 0 else None
        confiance = Decimal("0.30") if scores[haut] > 0 else Decimal("0.10")
    else:
        classe = haut
        deuxieme_classe = deuxieme if scores[deuxieme] > 0 else None
        confiance = _confiance(scores[haut], scores[deuxieme])
        if scores[haut] - scores[deuxieme] < ECART_MIN_SANS_REVUE and scores[deuxieme] > 0:
            motifs.append("classes_proches")
    if confiance < SEUIL_CONFIANCE:
        motifs.append("confiance_basse")
    if classe == "autre":
        motifs.append("classe_autre")
    if courriel.neutralise:
        motifs.append("consigne_neutralisee")
    if classe != "pourriel_hameconnage" and scores["pourriel_hameconnage"] >= 3:
        motifs.append("signaux_hameconnage")
    motifs = list(dict.fromkeys(motifs))
    return ResultatTri(
        classe=classe,
        confiance=str(confiance),
        scores=scores,
        raisons=tuple(raisons),
        aiguillage=AIGUILLAGE[classe],
        revue_humaine=bool(motifs),
        motifs_revue=tuple(motifs),
        version_regles=jeu.version,
        empreinte_regles=jeu.empreinte(),
        deuxieme_classe=deuxieme_classe,
    )


# ---------------------------------------------------------------------------------------------- évaluation
def _fusionner(valeurs: Iterable[str]) -> str:
    return "\n".join(valeurs)


def courriel_depuis_cas(
    cas: Mapping[str, Any],
    domaines_entreprise: Sequence[str] = ("atelier.example.test",),
) -> CourrielATrier:
    """Un cas du corpus devient un courrier à trier, APRÈS le filtre de provenance (comme en production : le tri ne voit
    jamais le texte brut)."""
    m = cas["message"]
    auth = m.get("authentification", {})
    objet, sain_objet = provenance.filtrer(m.get("objet", ""))
    corps, sain_corps = provenance.filtrer(m.get("corps", ""))
    return CourrielATrier(
        objet=objet,
        corps=corps,
        expediteur=m.get("expediteur_courriel", ""),
        spf=auth.get("spf", "absent"),
        dkim=auth.get("dkim", "absent"),
        dmarc=auth.get("dmarc", "absent"),
        nb_pieces=len(m.get("pieces_jointes", [])),
        neutralise=not (sain_objet and sain_corps),
        domaines_entreprise=tuple(domaines_entreprise),
    )


def charger_corpus(chemin: Path) -> dict[str, Any]:
    donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    if donnees.get("schema") != "opsys.m1.tri_courriel.corpus/v1" or donnees.get("fictif") is not True:
        raise ValueError("REJ-M1-TRI-CORPUS: corpus fictif (schema opsys.m1.tri_courriel.corpus/v1) requis")
    ids = [c["id"] for c in donnees["cas"]]
    if len(set(ids)) != len(ids):
        raise ValueError("REJ-M1-TRI-CORPUS: identifiants de cas en double")
    for c in donnees["cas"]:
        if c["classe"] not in CLASSES:
            raise ValueError(f"REJ-M1-TRI-CORPUS: classe inconnue {c['classe']!r} ({c['id']})")
    return donnees


def _rapport_classe(vp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = Decimal(vp) / Decimal(vp + fp) if vp + fp else None
    rappel = Decimal(vp) / Decimal(vp + fn) if vp + fn else None
    f1 = (
        (2 * precision * rappel / (precision + rappel))
        if precision and rappel and (precision + rappel)
        else (Decimal(0) if vp + fp + fn else None)
    )

    def q(x: Decimal | None) -> str | None:
        return None if x is None else str(x.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))

    return {
        "vrais_positifs": vp,
        "faux_positifs": fp,
        "faux_negatifs": fn,
        "precision": q(precision),
        "rappel": q(rappel),
        "f1": q(f1),
        "support": vp + fn,
    }


def evaluer(
    cas: Sequence[Mapping[str, Any]],
    jeu: JeuRegles = JEU_V1,
    domaines_entreprise: Sequence[str] = ("atelier.example.test",),
) -> dict[str, Any]:
    """Précision et rappel par classe, justesse globale, matrice de confusion et liste des erreurs."""
    confusion: dict[str, dict[str, int]] = {a: {b: 0 for b in CLASSES} for a in CLASSES}
    erreurs: list[dict[str, Any]] = []
    revues = 0
    justes = 0
    justes_injection = total_injection = 0
    for c in cas:
        r = classer(courriel_depuis_cas(c, domaines_entreprise), jeu)
        confusion[c["classe"]][r.classe] += 1
        revues += r.revue_humaine
        ok = r.classe == c["classe"]
        justes += ok
        if c.get("injection"):
            total_injection += 1
            justes_injection += ok
        if not ok:
            erreurs.append(
                {
                    "id": c["id"],
                    "attendu": c["classe"],
                    "obtenu": r.classe,
                    "confiance": r.confiance,
                    "ambigu": bool(c.get("ambigu")),
                    "difficulte": c.get("difficulte"),
                    "raisons": [x.identifiant for x in r.raisons],
                }
            )
    par_classe = {}
    for k in CLASSES:
        vp = confusion[k][k]
        fp = sum(confusion[a][k] for a in CLASSES if a != k)
        fn = sum(confusion[k][b] for b in CLASSES if b != k)
        par_classe[k] = _rapport_classe(vp, fp, fn)
    f1s = [Decimal(v["f1"]) for v in par_classe.values() if v["f1"] is not None]
    macro = (sum(f1s) / len(f1s)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP) if f1s else None
    n = len(cas)
    return {
        "effectif": n,
        "justes": justes,
        "justesse": str((Decimal(justes) / Decimal(n)).quantize(Decimal("0.001"))) if n else None,
        "f1_macro": None if macro is None else str(macro),
        "par_classe": par_classe,
        "confusion": confusion,
        "erreurs": erreurs,
        "revue_humaine": revues,
        "injection": {"effectif": total_injection, "justes": justes_injection},
        "version_regles": jeu.version,
        "empreinte_regles": jeu.empreinte(),
    }
