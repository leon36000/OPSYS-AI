"""Outils d'actions M9.17 : proposer à la file d'approbation native, réconcilier, lire. Rien n'est jamais exécuté par
M9.

Proposer crée une demande ``en_attente`` pour un outil de la liste blanche (port ``opsys.actions_m9``) avec les
arguments
exacts, et inscrit la proposition dans le registre chaîné ``actions`` DANS LA MÊME transaction : si l'un échoue, l'autre
aussi. L'approbation et l'exécution restent humaines, aux rôles du département cible. Réconcilier relit l'état natif et
n'ajoute un constat que s'il change.
"""

from __future__ import annotations

from typing import Any

from opsys import contexte, stockage
from opsys.idempotence import empreinte_arguments
from opsys.outils import Autonomie, Niveau, Outil

from . import orchestrateur
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_ACTIONS = "actions"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}
_ID = {"type": "string", "minLength": 1, "maxLength": 128}


def construire_outils(*, budget_sortie: int, proposeur: Any = None, actions_cible: Any = None) -> tuple[Outil, ...]:
    def registre() -> Any:
        return actions_cible if actions_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_ACTIONS)

    def chaine() -> list[dict]:
        liste = list(registre())
        ok, raison = orchestrateur.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-ACTION-CHAINE-INVALIDE : registre des actions invalide ({raison})")
        return liste

    def personne() -> str:
        appelante = contexte.identite_appelante()
        return appelante.personne if appelante is not None else "inconnu"

    def exiger_port() -> Any:
        if proposeur is None:
            raise ValueError("REJ-ACTION-PORT-ABSENT : le port d'actions vers la file d'approbation n'est pas installé")
        return proposeur

    def proposer(
        departement: str, outil: str, arguments: dict[str, Any], sources: list[str], motif: str, horodatage: str
    ) -> dict[str, Any]:
        exiger_admin_strict()
        port = exiger_port()
        orchestrateur.controler(departement, outil, sources, motif, horodatage)
        liste = chaine()
        # Contrôle de rejeu AVANT toute écriture native : l'empreinte est précalculée, le port la confirme ensuite.
        empreinte = empreinte_arguments(dict(arguments))
        action_id = orchestrateur.identifiant_action(departement, outil, empreinte)
        courante = orchestrateur.etat(liste).get(action_id)
        if courante is not None and courante["etat"] in orchestrateur.ETATS_BLOQUANTS:
            raise ValueError(f"REJ-ACTION-REJEU : action déjà {courante['etat']} (tentative {courante['tentative']})")
        reponse = port("proposer", departement=departement, outil=outil, arguments=arguments, motif=motif)
        if reponse.get("ok") is not True:
            raise ValueError(f"REJ-ACTION-REFUSEE : {reponse.get('erreur')} — {reponse.get('details')}")
        if reponse["arguments_sha256"] != empreinte:
            raise ValueError("REJ-ACTION-ARGUMENTS : empreinte divergente entre le port et M9, rien n'est conservé")
        maillon = orchestrateur.proposition(
            liste,
            departement=departement,
            outil=outil,
            arguments_sha256=empreinte,
            demande_id=reponse["demande_id"],
            niveau=reponse["niveau"],
            sources=sources,
            motif=motif,
            recu_a=horodatage,
            propose_par=personne(),
        )
        registre().append(maillon, rang_attendu=len(liste))
        return {
            "accepte": True,
            "action_id": action_id,
            "tentative": maillon["tentative"],
            "demande_id": reponse["demande_id"],
            "niveau": reponse["niveau"],
            "etat": "EN_ATTENTE_APPROBATION",
            "execute": False,
            "prochaine_etape": "un humain approuve ou refuse dans la file d'approbation du propriétaire",
        }

    def reconcilier(action_id: str, horodatage: str) -> dict[str, Any]:
        exiger_admin_strict()
        port = exiger_port()
        liste = chaine()
        courante = orchestrateur.etat(liste).get(action_id)
        if courante is None:
            raise ValueError("REJ-ACTION-INCONNUE : action jamais proposée")
        natif = port("lire", demande_id=courante["demande_id"])
        maillon = orchestrateur.reconciliation(liste, action_id, natif, recu_a=horodatage)
        if maillon is not None:
            registre().append(maillon, rang_attendu=len(liste))
        nouvel_etat = orchestrateur.etat(list(registre()))[action_id]
        return {
            "accepte": True,
            "action_id": action_id,
            "etat": nouvel_etat["etat"],
            "constat_ajoute": maillon is not None,
            "demande_id": courante["demande_id"],
            "rejeu_autorise": nouvel_etat["etat"] in {"REFUSEE", "ECHEC"},
        }

    def lire_actions(action_id: str | None = None) -> dict[str, Any]:
        exiger_admin_strict()
        projection = orchestrateur.vue(chaine())
        if action_id is not None:
            projection["actions"] = [a for a in projection["actions"] if a["action_id"] == action_id]
        return borner({"accepte": True, **projection}, budget_sortie)

    def outil(nom, description, proprietes, requis, fonction, *, ecriture=False):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=Autonomie.T1 if ecriture else Autonomie.T0,
            niveau=Niveau.N2 if ecriture else Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        )

    return (
        outil(
            "m9_proposer_action",
            "Propose à la file d'approbation native une action d'un autre département (liste blanche : relance ou "
            "réassignation M2, planification ou demande d'écart M4) avec ses arguments exacts et des sources citées. "
            "M9 n'exécute rien ; une action déjà en attente, exécutée ou inconnue ne se repropose pas.",
            {
                "departement": _ID,
                "outil": _ID,
                "arguments": {"type": "object"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 200},
                    "minItems": 1,
                    "maxItems": 12,
                },
                "motif": {"type": "string", "minLength": 1, "maxLength": 300},
                "horodatage": _INSTANT,
            },
            ["departement", "outil", "arguments", "sources", "motif", "horodatage"],
            proposer,
            ecriture=True,
        ),
        outil(
            "m9_reconcilier_action",
            "Relit l'état natif de la demande d'une action proposée (en attente, refusée, exécutée avec succès "
            "déclaré, échec, inconnu) et inscrit un constat s'il a changé ; un effet inconnu ne se rejoue jamais.",
            {"action_id": _ID, "horodatage": _INSTANT},
            ["action_id", "horodatage"],
            reconcilier,
            ecriture=True,
        ),
        outil(
            "m9_lire_actions",
            "État des actions proposées : tentatives, demande native, constats, sources ; sans les arguments.",
            {"action_id": _ID},
            [],
            lire_actions,
        ),
    )
