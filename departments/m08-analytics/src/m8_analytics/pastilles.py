"""Pastilles de confiance d'une mesure (M8.4) : FRESH, STALE, PARTIAL, MISSING, QUALITY_FAIL, GATED.

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge, aucune table. Une pastille n'est PAS une donnée de
plus : elle est DÉRIVÉE, en une fonction déterministe, d'états qui existent déjà (le verdict de qualité, le statut de la
mesure, sa fraîcheur, sa couverture et, quand le planificateur a pu être lu, l'état de la collecte). Deux surfaces ne
peuvent donc pas dire deux pastilles pour la même mesure.

Il n'y a PAS de pastille ``LIVE`` : aucune source de M8 n'est temps réel (faits évènementiels, fenêtres de 24 h,
cadences déclarées) ; le rafraîchissement du wallboard relit des faits, il ne les rend pas plus frais. Pas non plus
d'``ESTIMATED`` : M8 ne produit aucune estimation, ses prévisions viendront d'un moteur déterministe avec reçu (autre
chantier).

Ordre d'application (le premier qui s'applique), du plus grave au plus rassurant :

1. ``QUALITY_FAIL`` : une règle de qualité échoue, la mesure est bloquée (une donnée fausse l'emporte sur tout : une
mesure à la fois vieille et fausse est d'abord fausse) ;
2. ``GATED`` : la mesure n'est pas calculable et c'est un GESTE HUMAIN qui la retient (constat qui nourrit la mesure
jamais activé, en ombre, expiré, ou planificateur coupé) ; seulement quand l'état de la collecte a pu être lu ;
3. ``MISSING`` : la mesure n'est pas calculable pour une autre raison (rien reçu, le département source dit « non
   calculable »), ou pour la même raison mais sans état de collecte lisible ;
4. ``STALE`` : calculée mais périmée, ou de fraîcheur inconnue (on ne peut pas dire qu'elle est fraîche) ;
5. ``PARTIAL`` : calculée et fraîche mais à couverture partielle (la valeur ne couvre qu'une partie de ce qu'elle
devrait) ; 6. ``FRESH`` : calculée, à jour (ou cumul terminal où la fraîcheur ne s'applique pas), couverture complète.

La pastille n'ajoute aucune valeur ni aucun chiffre : elle porte un code, un libellé et une phrase en français.
"""

from __future__ import annotations

from typing import Any

from . import entonnoir, qualite_mesures

FRESH = "FRESH"
STALE = "STALE"
PARTIAL = "PARTIAL"
MISSING = "MISSING"
QUALITY_FAIL = "QUALITY_FAIL"
GATED = "GATED"

# Les états de collecte (``collecte``) où c'est une décision humaine qui retient la mesure.
_ETATS_RETENUS_PAR_UN_GESTE = frozenset({"planificateur_coupe", "constat_expire", "constat_inactif",
"constat_en_ombre"})

_LIBELLES = {
    FRESH: "À jour",
    STALE: "Périmée",
    PARTIAL: "Partielle",
    MISSING: "Manquante",
    QUALITY_FAIL: "Qualité en échec",
    GATED: "En attente d'une activation",
}
_EXPLICATIONS = {
    FRESH: "La mesure est calculée, à jour et complète.",
    STALE: "La mesure est périmée ou sa fraîcheur est inconnue : ne vous y fiez pas.",
    PARTIAL: "La mesure est à jour mais ne couvre qu'une partie de ce qu'elle devrait couvrir.",
    MISSING: "La mesure n'est pas calculable : une donnée manque.",
    QUALITY_FAIL: "Un contrôle de qualité des données a échoué : la valeur est retenue, elle n'est pas montrée.",
    GATED: "La mesure attend un geste humain (activer le constat qui la nourrit).",
}


def pastilles_possibles() -> tuple[str, ...]:
    """L'ensemble FERMÉ des pastilles (une fonction : la garde de conformité de M8 exige une échappatoire «
    indéterminé »
    pour toute énumération publique de domaine, ce qui n'a pas de sens ici — chaque pastille est un fait dérivé)."""
    return (FRESH, STALE, PARTIAL, MISSING, QUALITY_FAIL, GATED)


def code_pastille(mesure: dict[str, Any], etat_collecte: str | None = None) -> str:
    """Le code de la pastille d'une mesure lue AVEC sa fraîcheur (``fraicheur_mesures.lire_mesures_avec_fraicheur``).
    ``etat_collecte`` : l'état de collecte de la mesure (``collecte.diagnostiquer``), ou ``None`` quand il n'a pas pu
    être
    lu (jamais deviné)."""
    if qualite_mesures.en_echec(mesure):
        return QUALITY_FAIL
    if mesure["statut"] != entonnoir.STATUT_CALCULEE:
        return GATED if etat_collecte in _ETATS_RETENUS_PAR_UN_GESTE else MISSING
    if not mesure["fraicheur"]["peut_etre_montree_comme_a_jour"]:
        return STALE
    if (mesure.get("couverture") or {}).get("etat") == "partielle":
        return PARTIAL
    return FRESH


def pastille(mesure: dict[str, Any], etat_collecte: str | None = None) -> dict[str, str]:
    """``{code, libelle, explication}`` de la pastille d'une mesure (dérivée, jamais stockée)."""
    code = code_pastille(mesure, etat_collecte)
    return {"code": code, "libelle": _LIBELLES[code], "explication": _EXPLICATIONS[code]}


def ajouter(mesures: list[dict[str, Any]], etats_collecte: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Les mesures, chacune avec sa ``pastille``. ``etats_collecte`` : ``{metric_id: état}`` si le planificateur a pu
    être
    lu, sinon ``None`` (GATED ne se dérive pas sans lui : MISSING)."""
    lus = etats_collecte or {}
    return [{**m, "pastille": pastille(m, lus.get(m["metric_id"]))} for m in mesures]


__all__ = [
    "FRESH",
    "GATED",
    "MISSING",
    "PARTIAL",
    "QUALITY_FAIL",
    "STALE",
    "ajouter",
    "code_pastille",
    "pastille",
    "pastilles_possibles",
]
