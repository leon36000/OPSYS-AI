"""État d'un contenu de chantier, calculé des registres append-only (PLAN T4.17).

Rien ne se modifie : une proposition, une décision, un export et un retrait sont chacun un maillon écrit une
fois. L'état d'un contenu est le PLIAGE de ces maillons, recalculé à chaque lecture. Le retrait l'emporte sur
tout : un contenu dont le chantier a un retrait de consentement est `CONSENTEMENT_RETIRE`, qu'il ait été
proposé, approuvé ou exporté (Loi 25 : un retrait bloque aussi un paquet déjà proposé).

Statuts : les trois du contrat `content-item.v1` (`PROPOSE`, `APPROVED`, `REJECTED`) et `CONSENTEMENT_RETIRE`.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .retrait import retrait_applicable

STATUT_PROPOSE = "PROPOSE"
STATUT_APPROUVE = "APPROVED"
STATUT_REJETE = "REJECTED"
STATUT_RETIRE = "CONSENTEMENT_RETIRE"
STATUTS = (STATUT_PROPOSE, STATUT_APPROUVE, STATUT_REJETE, STATUT_RETIRE)


def dernieres_revisions(
    propositions: Iterable[Mapping[str, Any]], wct_id: str | None = None,
) -> list[Mapping[str, Any]]:
    """La dernière révision de chaque (chantier, plateforme), de la plus ancienne à la plus récente.

    Une révision naît seulement après un rejet (nouveau texte) : les précédentes restent au registre, elles
    ne sont plus « le contenu du moment »."""
    courantes: dict[tuple[str, str], Mapping[str, Any]] = {}
    for proposition in propositions:
        if wct_id is not None and proposition["wct_id"] != wct_id:
            continue
        cle = (proposition["wct_id"], proposition["plateforme"])
        courantes.pop(cle, None)  # la révision la plus récente prend la place de la plus récente
        courantes[cle] = proposition
    return list(courantes.values())


def proposition_par_id(propositions: Iterable[Mapping[str, Any]], contenu_id: str) -> Mapping[str, Any] | None:
    for proposition in propositions:
        if proposition["contenu_id"] == contenu_id:
            return proposition
    return None


def est_derniere_revision(proposition: Mapping[str, Any], propositions: Iterable[Mapping[str, Any]]) -> bool:
    cle = (proposition["wct_id"], proposition["plateforme"])
    plus_recente = max(
        (p["revision"] for p in propositions if (p["wct_id"], p["plateforme"]) == cle), default=proposition["revision"],
    )
    return proposition["revision"] >= plus_recente


def decision_de(contenu_id: str, decisions: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    trouvee = None
    for decision in decisions:
        if decision["contenu_id"] == contenu_id:
            trouvee = decision
    return trouvee


def export_de(contenu_id: str, exports: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for export in exports:
        if export["contenu_id"] == contenu_id:
            return export
    return None


def statut(
    proposition: Mapping[str, Any], decisions: Iterable[Mapping[str, Any]], retraits: Iterable[Mapping[str, Any]],
) -> str:
    """Le statut d'une proposition : le retrait de son chantier, sinon sa décision, sinon `PROPOSE`."""
    if retrait_applicable(proposition["wct_id"], proposition.get("lead_id"), retraits) is not None:
        return STATUT_RETIRE
    decision = decision_de(proposition["contenu_id"], decisions)
    if decision is None:
        return STATUT_PROPOSE
    return STATUT_APPROUVE if decision["decision"] == STATUT_APPROUVE else STATUT_REJETE


def vue(
    proposition: Mapping[str, Any], decisions: Iterable[Mapping[str, Any]], exports: Iterable[Mapping[str, Any]],
    retraits: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """La proposition, avec son statut du moment, sa décision (qui, quand) et si elle a été exportée."""
    decisions = list(decisions)
    retraits = list(retraits)
    decision = decision_de(proposition["contenu_id"], decisions)
    return {
        **proposition,
        "approval_status": statut(proposition, decisions, retraits),
        "decision": None if decision is None else {
            "decision": decision["decision"], "par": decision["par"], "role": decision["role"],
            "source": decision["source"], "motif": decision["motif"], "horodatage": decision["horodatage"],
        },
        "exporte": export_de(proposition["contenu_id"], exports) is not None,
    }
