"""Classification des maillons du registre Événements de M10 (PLAN T3.3).

Le Work Completion Trigger de M4 (``m4.travaux_termines``) et la variance matériaux de M6
(``m6.variance_chantier``) vivent dans le MÊME registre, sous le MÊME ``type_entree``
(``evenement_memorise``) — ce sont tous deux des événements opérationnels reçus du bus (ADR-0009
§3). Ce module les distingue à la LECTURE par un champ structurellement propre à chacun (jamais un
tag ajouté a posteriori) : le WCT porte ``duree_reelle_minutes`` (``contrats.CHAMPS_WCT``, figé par
M4) ; la variance porte ``statut_variance`` (catalogue socle
``m6.variance_chantier.json``). Fournit aussi la résolution de l'affaire (``lead_id``) d'un
événement : directe pour un WCT, par ``wct_id`` pour une variance — qui ne porte pas de ``lead_id``
propre (``chantier_id`` de M6 est un concept distinct, M6-audit.md).

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

from collections.abc import Iterable

TYPE_WCT = "m4.travaux_termines"
TYPE_VARIANCE = "m6.variance_chantier"

_TYPE_ENTREE_EVENEMENT = "evenement_memorise"
_CLE_DISCRIMINANTE = {TYPE_VARIANCE: "statut_variance", TYPE_WCT: "duree_reelle_minutes"}
_CLE_IDENTIFIANT = {TYPE_WCT: "wct_id", TYPE_VARIANCE: "evenement_id"}


def type_evenement(maillon: dict) -> str | None:
    """Type opérationnel d'un maillon du registre Événements, ou ``None`` (pas un événement connu
    — ex. un maillon d'un autre ``type_entree``, ou un événement futur non encore classifié)."""
    if not isinstance(maillon, dict) or maillon.get("type_entree") != _TYPE_ENTREE_EVENEMENT:
        return None
    if _CLE_DISCRIMINANTE[TYPE_VARIANCE] in maillon:
        return TYPE_VARIANCE
    if _CLE_DISCRIMINANTE[TYPE_WCT] in maillon:
        return TYPE_WCT
    return None


def identifiant(maillon: dict) -> str | None:
    """La clé PUBLIQUE par laquelle un producteur (ou un audit) désigne ce fait — ``wct_id`` pour
    un WCT, ``evenement_id`` pour une variance — jamais ``ligne_id``, interne au registre."""
    type_ = type_evenement(maillon)
    if type_ is None:
        return None
    return maillon.get(_CLE_IDENTIFIANT[type_])


def index_lead_id_par_wct_id(maillons: Iterable[dict]) -> dict[str, str]:
    """``wct_id -> lead_id``, à partir des seuls maillons WCT (source unique du lien vers
    l'affaire : une variance ne porte jamais son propre ``lead_id``)."""
    index: dict[str, str] = {}
    for maillon in maillons:
        if type_evenement(maillon) == TYPE_WCT:
            wct_id = maillon.get("wct_id")
            lead_id = maillon.get("lead_id")
            if wct_id is not None and lead_id is not None:
                index[wct_id] = lead_id
    return index


def lead_id(maillon: dict, index_wct: dict[str, str]) -> str | None:
    """L'affaire (``lead_id``) d'un événement : directe pour un WCT, résolue via ``wct_id`` pour
    une variance ; ``None`` si non résolvable (variance reçue avant son WCT, ou WCT jamais
    mémorisé) — jamais deviné."""
    type_ = type_evenement(maillon)
    if type_ == TYPE_WCT:
        return maillon.get("lead_id")
    if type_ == TYPE_VARIANCE:
        return index_wct.get(maillon.get("wct_id"))
    return None


def evenements_de_laffaire(affaire_id: str, maillons: Iterable[dict]) -> list[dict]:
    """Tous les événements (WCT + variance) d'une affaire, dans l'ordre du registre reçu."""
    maillons = list(maillons)
    index_wct = index_lead_id_par_wct_id(maillons)
    return [m for m in maillons if lead_id(m, index_wct) == affaire_id]
