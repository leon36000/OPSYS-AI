"""Plan de réparation du filet anti-perte (M2-C1 ; DEFINITION-PRODUIT §7 M2.13 « scan, violations, plan de réparation
»).

Module PUR : il transforme des violations SLA (`sla.py`) et des anomalies d'intégrité (`integrite.py`) en un plan par
cible (un lead, sinon un client ou un devis) : des ACTIONS PROPOSÉES, dans l'ordre d'urgence. Il n'exécute RIEN :

- chaque action porte `execute: False` ; aucune ne part d'ici ;
- une action qui passe par un outil dit lequel et son NIVEAU RÉEL (relu du manifeste par l'appelant, jamais recopié) ;
  quand ce niveau est N3 ou plus, l'action est SENSIBLE (`approbation_requise: True`) : une personne l'approuve dans le
  sas avant qu'elle n'ait un effet. Aucune demande d'approbation n'est créée ici : ce plan est une lecture ;
- aucune action n'envoie un message au client, ne change un prix ni une date, ne fusionne ni ne supprime quoi que ce
  soit. Fusionner des doublons reste une décision humaine hors de ce module (`m2_arbitrer_doublon` constate « distincts
  »
  seulement).

« Via la prochaine meilleure action existante » : quand l'appelant fournit la suggestion déterministe de
`suggestions.suggerer` pour un lead (règle citée), elle accompagne le plan, telle quelle.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from . import integrite, sla

__all__ = ["ACTIONS", "NIVEAUX_SENSIBLES", "OUTILS_CITES", "planifier"]

NIVEAUX_SENSIBLES = ("N3", "N4", "N5")

# (action_id, libellé, outil ou None, note quand aucun outil ne l'exécute)
_A_ASSIGNER = (
    "assigner_proprietaire",
    "Assigner un propriétaire et qualifier le lead (propriétaire et prochaine action datée).",
    "m2_transitionner_statut",
    None,
)
_A_ACTION = (
    "fixer_prochaine_action",
    "Fixer une prochaine action datée pour ce lead (qualifier ou revoir le dossier).",
    "m2_transitionner_statut",
    None,
)
_A_APPELER = (
    "appeler_maintenant",
    "Appeler le client maintenant, puis noter l'appel au dossier.",
    None,
    "l'appel est un geste humain ; le résultat se note au dossier (m2_enregistrer_interaction, niveau N3)",
)
_A_PHOTOS = (
    "demander_photos",
    "Demander des photos au client (un brouillon que le propriétaire valide ; rien n'est envoyé d'ici).",
    None,
    "aucun outil de M2 ne prépare cette demande : le message part par le sas courriel de M1 (approbation N3)",
)
_A_RELANCER = (
    "relancer_soumission",
    "Préparer la relance du devis (appel d'abord : rien n'est envoyé d'ici).",
    "m2_preparer_relance",
    None,
)
_A_ESCALADER = (
    "escalader_plainte",
    "Appeler le client insatisfait et prévenir le propriétaire de l'entreprise ; noter la prise en charge.",
    None,
    "aucun outil de M2 n'escalade : une personne appelle, puis note le résultat (m2_enregistrer_interaction)",
)
_A_FAIRE = (
    "faire_ou_replanifier_action",
    "Faire l'action échue, ou fixer et dater la suivante.",
    "m2_suggerer_prochaine_action",
    None,
)
_A_REVUE = (
    "revue_administrateur",
    "Revue par un administrateur : rétablir la donnée par une écriture validée (rien n'est corrigé automatiquement).",
    None,
    "aucune correction automatique : l'historique d'un registre append-only ne se réécrit pas",
)
_A_CONTACT = (
    "corriger_contact",
    "Corriger ou compléter le contact du client (avant/après et motif consignés).",
    "m2_corriger_contact_client",
    None,
)
_A_REASSIGNER = (
    "reassigner_lead",
    "Confirmer le propriétaire de ce lead (réassignation motivée).",
    "m2_reassigner_lead",
    None,
)
_A_ARBITRER = (
    "arbitrer_doublon",
    "Arbitrer le doublon probable : constater « distincts » ou décider de la suite (aucune fusion automatique).",
    "m2_arbitrer_doublon",
    None,
)

ACTIONS = {
    sla.R_PROPRIETAIRE: _A_ASSIGNER,
    sla.R_ACTION: _A_ACTION,
    sla.R_CHAUD: _A_APPELER,
    sla.R_PHOTOS: _A_PHOTOS,
    sla.R_SOUMISSION: _A_RELANCER,
    sla.R_PLAINTE: _A_ESCALADER,
    sla.R_RETARD: _A_FAIRE,
    integrite.C_STATUT: _A_REVUE,
    integrite.C_CONTACT: _A_CONTACT,
    integrite.C_PROPRIETAIRE: _A_REASSIGNER,
    integrite.C_SOUMISSION: _A_REVUE,
    integrite.C_ACTIVITE: _A_REVUE,
    integrite.C_CLIENT: _A_REVUE,
    integrite.C_PIPELINE: _A_REVUE,
    integrite.C_DOUBLON: _A_ARBITRER,
}
# Les outils que le plan peut citer : l'appelant en relit le niveau réel au manifeste.
OUTILS_CITES = tuple(sorted({a[2] for a in ACTIONS.values() if a[2] is not None}))

# Urgence : 1 est le plus urgent. Une plainte avant un lead chaud, avant un lead orphelin, avant le reste.
_PRIORITE = {
    sla.R_PLAINTE: 1,
    sla.R_CHAUD: 2,
    sla.R_PROPRIETAIRE: 3,
    sla.R_ACTION: 4,
    sla.R_SOUMISSION: 5,
    sla.R_RETARD: 6,
    sla.R_PHOTOS: 7,
    integrite.C_PIPELINE: 8,
    integrite.C_PROPRIETAIRE: 8,
    integrite.C_STATUT: 8,
    integrite.C_CONTACT: 9,
    integrite.C_CLIENT: 9,
    integrite.C_ACTIVITE: 10,
    integrite.C_SOUMISSION: 10,
    integrite.C_DOUBLON: 11,
}


def _action(code: str, niveaux: Mapping[str, str | None]) -> dict[str, Any]:
    action_id, libelle, outil, note = ACTIONS[code]
    niveau = niveaux.get(outil) if outil is not None else None
    sortie: dict[str, Any] = {
        "action_id": action_id,
        "libelle": libelle,
        "outil": outil,
        "niveau": niveau,
        # fail-closed : un outil cité dont le niveau est inconnu demande l'approbation d'une personne
        "approbation_requise": outil is not None and (niveau is None or niveau in NIVEAUX_SENSIBLES),
        "execute": False,
    }
    if note is not None:
        sortie["note"] = note
    return sortie


def _cible(violation_ou_anomalie: Mapping[str, Any]) -> tuple[str, str]:
    """`(type, identifiant)` de la cible du plan : le lead d'abord, sinon le client, sinon le devis."""
    if violation_ou_anomalie.get("lead_id"):
        return "lead", str(violation_ou_anomalie["lead_id"])
    if violation_ou_anomalie.get("client_id"):
        return "client", str(violation_ou_anomalie["client_id"])
    donnee = violation_ou_anomalie.get("donnee") or {}
    if donnee.get("devis_id"):
        return "devis", str(donnee["devis_id"])
    return "inconnue", "-"


def planifier(
    violations: Iterable[Mapping[str, Any]],
    anomalies: Iterable[Mapping[str, Any]],
    *,
    niveaux: Mapping[str, str | None],
    suggestions: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Le plan : une entrée par cible, triées par urgence puis par identifiant (ordre total, donc déterministe).

    `niveaux` : `{nom d'outil: niveau}` relu du manifeste (un outil absent est un niveau inconnu, `None`). `suggestions`
    :
    `{lead_id: suggestion de suggestions.suggerer}`. Chaque entrée : `cible`, `statut`, `proprietaire`, `priorite`,
    `problemes` (la règle ou le contrôle, la raison), `actions` (sans doublon, `execute: False`),
    `prochaine_action_suggeree`. Aucune écriture, aucun effet."""
    suggestions = suggestions or {}
    plan: dict[tuple[str, str], dict[str, Any]] = {}

    def entree(cible: tuple[str, str], statut: Any, proprietaire: Any) -> dict[str, Any]:
        if cible not in plan:
            plan[cible] = {
                "cible": {"type": cible[0], "id": cible[1]},
                "statut": statut,
                "proprietaire": proprietaire,
                "priorite": 99,
                "problemes": [],
                "actions": [],
                "prochaine_action_suggeree": suggestions.get(cible[1]) if cible[0] == "lead" else None,
            }
        return plan[cible]

    def ajouter(cible: tuple[str, str], code: str, source: str, raison: str, statut: Any, proprietaire: Any) -> None:
        e = entree(cible, statut, proprietaire)
        e["priorite"] = min(e["priorite"], _PRIORITE[code])
        e["problemes"].append({"source": source, "code": code, "raison": raison})
        action = _action(code, niveaux)
        existante = next((a for a in e["actions"] if a["action_id"] == action["action_id"]), None)
        if existante is None:
            e["actions"].append({**action, "_p": _PRIORITE[code]})
        else:
            existante["_p"] = min(existante["_p"], _PRIORITE[code])

    for v in violations:
        ajouter(_cible(v), v["regle"], "sla", v["raison"], v.get("statut"), v.get("proprietaire"))
    for a in anomalies:
        ajouter(_cible(a), a["controle"], "integrite", f"{a['controle']} : {a['nature']}", None, None)

    resultat = list(plan.values())
    for e in resultat:
        e["problemes"].sort(key=lambda p: (_PRIORITE[p["code"]], p["source"], p["code"], p["raison"]))
        e["actions"].sort(key=lambda a: (a["_p"], a["action_id"]))
        for a in e["actions"]:
            del a["_p"]
    resultat.sort(key=lambda e: (e["priorite"], e["cible"]["type"], e["cible"]["id"]))
    return resultat
