"""Les moteurs de calcul commerciaux de M2 et leurs REÇUS rejouables (M2.4, M2.15).

Quatre moteurs, tous déterministes : `score_lead` (un score et son explication), `calibration_score_lead` (la mesure
fictive), `analytique_pipeline` (pipeline, taux, délai de cycle, valeur pondérée) et `prevision_commerciale`
(prévision par intervalle). Chacun a la forme du moteur de calcul de M5 : `moteur(entrees, parametres) -> (sortie,
None) | (None, verdict)`, où `sortie` porte `methode`, `precision`, `parametres`, `entrees`, `resultat`,
`avertissements`. Le REÇU est construit par le pont du socle (`opsys.recu_calcul_pont`), c'est-à-dire par le format
`recu-calcul.v1` de M5 : un reçu de M2 se vérifie avec l'outil de M5 (`m5_verifier_recu_calcul`) et se REJOUE ici
(`rejouer`) : même moteur, mêmes entrées, mêmes paramètres, mêmes empreintes — ou le refus d'un reçu retouché, compact
ou d'un moteur inconnu.

Aucune horloge, aucun registre, aucune écriture : les entrées sont celles que l'outil a lues, normalisées.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from opsys import recu_calcul_pont

from . import calibration_scoring, previsions, scoring
from .verdicts_commercial import construire_verdict

__all__ = ["MOTEURS", "VERSION_ANALYTIQUE", "VERSION_PREVISION", "produire", "rejouer"]

VERSION_ANALYTIQUE = "1.0.0"
VERSION_PREVISION = "1.0.0"
_PRECISION_SCORE = {
    "arithmetique": "entiers et fractions exactes (aucun flottant)",
    "affichage": "texte décimal, 2 décimales",
}


def moteur_score(entrees: Any, parametres: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le score d'un lead ouvert et son explication, à partir de faits normalisés (liste fermée du modèle)."""
    if parametres not in (None, {}):
        return None, construire_verdict("REJ-SCORE-FAITS-INVALIDES", detail="le score n'a aucun paramètre")
    resultat, verdict = scoring.calculer(entrees)
    if verdict is not None:
        return None, verdict
    return {
        "methode": (
            "Score = Σ (poids du facteur × sous-score) / Σ poids évalués ; sous-score = points obtenus / points "
            "possibles des signaux évalués ; signal sans donnée non évalué ; modèle et poids déclarés."
        ),
        "precision": dict(_PRECISION_SCORE),
        "parametres": {},
        "entrees": dict(scoring.valider_faits(entrees)[0]),
        "resultat": scoring.sans_exact(resultat),
        "avertissements": [scoring.AVERTISSEMENT_RANG, previsions.AVERTISSEMENT_INFO],
    }, None


def moteur_calibration(entrees: Any, parametres: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La calibration du modèle courant sur le jeu FICTIF de `graine` (voir `calibration_scoring`)."""
    if not isinstance(entrees, Mapping) or set(entrees) != {"graine", "n"} or parametres not in (None, {}):
        return None, construire_verdict("REJ-PREV-PARAMETRE-INVALIDE", detail="entrées : {graine, n} ; aucun paramètre")
    rapport, verdict = calibration_scoring.mesurer(entrees["graine"], entrees["n"])
    if verdict is not None:
        return None, verdict
    return {
        "methode": "Jeu synthétique à graine ; AUC de Mann-Whitney ; Brier ; régression isotone ; courbe en 10 "
        "tranches.",
        "precision": {
            "arithmetique": "entiers et fractions exactes (aucun flottant)",
            "affichage": "texte décimal, 4 décimales",
        },
        "parametres": {},
        "entrees": {"graine": entrees["graine"], "n": entrees["n"]},
        "resultat": rapport,
        "avertissements": [rapport["valeur_probante"], scoring.AVERTISSEMENT_RANG],
    }, None


MOTEURS: dict[tuple[str, str], Callable[[Any, Any], tuple[dict[str, Any] | None, dict[str, str] | None]]] = {
    ("score_lead", scoring.VERSION): moteur_score,
    ("calibration_score_lead", scoring.VERSION): moteur_calibration,
    ("analytique_pipeline", VERSION_ANALYTIQUE): previsions.analyser,
    ("prevision_commerciale", VERSION_PREVISION): previsions.prevoir,
}


def produire(
    moteur: str, version: str, entrees: Any, parametres: Any
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """`(reçu complet, None)` ou `(None, verdict)` : le moteur calcule, le pont construit le reçu `recu-calcul.v1`."""
    fonction = MOTEURS.get((moteur, version))
    if fonction is None:
        return None, construire_verdict(
            "REJ-PREV-RECU-INVALIDE", detail=f"moteur {moteur!r} version {version!r} inconnu"
        )
    sortie, verdict = fonction(entrees, parametres)
    if verdict is not None:
        return None, verdict
    return recu_calcul_pont.construire(
        moteur=moteur,
        version_moteur=version,
        methode=sortie["methode"],
        precision=sortie["precision"],
        parametres=sortie["parametres"],
        entrees=sortie["entrees"],
        resultat=sortie["resultat"],
        avertissements=sortie["avertissements"],
    ), None


def rejouer(recu: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Refait le calcul d'un reçu COMPLET et compare les empreintes. Un reçu retouché, compact (sans entrées) ou d'un
    moteur que ce code ne connaît pas est `REJ-PREV-RECU-INVALIDE` ; un reçu intact rend `{"identique": ...}`."""
    valide, raison = recu_calcul_pont.verifier(recu)
    if not valide:
        return None, construire_verdict("REJ-PREV-RECU-INVALIDE", detail=raison)
    if "entrees" not in recu:
        return None, construire_verdict(
            "REJ-PREV-RECU-INVALIDE",
            detail=(
                "reçu compact (sans entrées) : son empreinte est vérifiée, mais il ne se rejoue qu'avec ses entrées"
            ),
        )
    cle = (recu["moteur"], recu["version_moteur"])
    if cle not in MOTEURS:
        return None, construire_verdict(
            "REJ-PREV-RECU-INVALIDE", detail=f"moteur {cle[0]!r} version {cle[1]!r} : non rejouable par M2"
        )
    refait, verdict = produire(cle[0], cle[1], recu["entrees"], recu["parametres"] or None)
    if verdict is not None:
        return None, verdict
    return {
        "identique": refait["empreinte"] == recu["empreinte"],
        "moteur": cle[0],
        "version_moteur": cle[1],
        "empreinte_recue": recu["empreinte"],
        "empreinte_recalculee": refait["empreinte"],
    }, None
