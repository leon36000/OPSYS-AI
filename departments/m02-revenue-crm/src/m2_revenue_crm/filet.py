"""Assemblage du filet anti-perte : les registres de M2 -> des dossiers -> SLA + audit d'intégrité (M2-C1).

Module PUR (aucune entrée-sortie, aucune horloge) : l'adaptateur (`outils_integrite.py`) lit les registres UNE fois et
les
passe ici ; ce module ne fait que ranger les faits de chaque lead pour `sla.py` et `integrite.py`, et rend les deux
rapports. Il ne lit que, n'écrit rien, ne modifie aucune des entrées reçues.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import assignation, faits_interconnexion, integrite, liste_leads, relances, scoring_faits, segments, sla, statuts

__all__ = ["construire_dossiers", "produire"]


def _qualifie_le(maillons_du_lead: Sequence[Mapping[str, Any]]) -> str | None:
    instant = None
    for m in maillons_du_lead:
        if m.get("type_entree") == statuts.TYPE_ENTREE and m.get("statut") == "qualifie":
            instant = m.get("horodatage")
    return instant


def construire_dossiers(
    maillons: list[dict[str, Any]],
    *,
    devis: Sequence[Mapping[str, Any]] | None,
    preparees: Sequence[Mapping[str, Any]] | None,
    satisfactions: Sequence[Mapping[str, Any]] | None,
    maillons_propriete: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Un dossier par lead ingéré, dans l'ordre des identifiants (déterministe). Une source `None` (illisible) met la
    clé du dossier à `None` : la règle qui en dépend est alors « non évaluée » (`sla.evaluer`, `sources`)."""
    fiches = liste_leads.fiches_des_leads(maillons)
    proprietaires = assignation.proprietaires(liste_leads.Vue(maillons))
    interactions = liste_leads.interactions_humaines(fiches)
    satisfaction_de = faits_interconnexion.satisfaction_par_lead(satisfactions or ())
    profils = scoring_faits.profils_confirmes(list(maillons_propriete)) if maillons_propriete is not None else None
    devis_par_lead: dict[Any, list[Mapping[str, Any]]] = {}
    for fait in devis or ():
        devis_par_lead.setdefault(fait.get("lead_id"), []).append(fait)
    preparees_par_lead: dict[Any, list[str]] = {}
    for p in preparees or ():
        if p.get("regle") == relances.REGLE_DEVIS and isinstance(p.get("prepare_le"), str):
            preparees_par_lead.setdefault(p.get("lead_id"), []).append(p["prepare_le"])
    dossiers = []
    for lead_id in sorted(fiches):
        fiche = fiches[lead_id]
        statut = fiche.statut
        if statut is None:
            continue  # sans statut : c'est l'audit d'intégrité qui le dit, pas une règle de délai
        client_id = fiche.client_id
        dossiers.append(
            {
                "lead_id": lead_id,
                "statut": statut,
                "proprietaire": proprietaires.get(lead_id),
                "ingere_le": fiche.ingere_le,
                "qualifie_le": _qualifie_le(fiche.vue.lire()),
                "derniere_activite": fiche.derniere_activite,
                "prochaine_action": fiche.prochaine_action,
                "urgence_declaree": fiche.contrat.get("urgence_declaree"),
                "interactions": interactions.get(lead_id, []),
                "devis": devis_par_lead.get(lead_id, []) if devis is not None else None,
                "relances_preparees": preparees_par_lead.get(lead_id, []) if preparees is not None else None,
                "satisfaction": satisfaction_de.get(lead_id, {}) if satisfactions is not None else None,
                "photos": (profils.get(client_id or "", {}).get("photos", 0) if profils is not None else None),
            }
        )
    return dossiers


def produire(
    maillons: list[dict[str, Any]],
    *,
    maintenant: str,
    reglages: Mapping[str, Mapping[str, Any]],
    devis: Sequence[Mapping[str, Any]] | None,
    preparees: Sequence[Mapping[str, Any]] | None,
    satisfactions: Sequence[Mapping[str, Any]] | None,
    maillons_propriete: Sequence[dict[str, Any]] | None,
    devis_integrite: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """`{"sla", "integrite"}` : le scan SLA (`sla.evaluer`) et l'audit d'intégrité (`integrite.auditer`) sur les MÊMES
    registres lus une fois. `devis` : les devis envoyés connus (`relances.devis_connus`) pour la règle de soumission ;
    `devis_integrite` : tous les devis reçus de M3 (envoyés, sans réponse, acceptés) pour le contrôle des soumissions
    orphelines. `maintenant` sans fuseau ou illisible : `ValueError`."""
    segments.instant_utc(maintenant)
    dossiers = construire_dossiers(
        maillons, devis=devis, preparees=preparees, satisfactions=satisfactions, maillons_propriete=maillons_propriete
    )
    sources = {
        "devis": devis is not None and preparees is not None,
        "satisfaction": satisfactions is not None,
        "photos": maillons_propriete is not None,
    }
    return {
        "sla": sla.evaluer(dossiers, maintenant=maintenant, reglages=reglages, sources=sources),
        "integrite": integrite.auditer(maillons, devis=devis_integrite),
    }
