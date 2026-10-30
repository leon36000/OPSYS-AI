"""Orchestrateur d'actions M9.17 : proposer, suivre et réconcilier des actions sans jamais les exécuter ni les rejouer.

Module pur. M9 ne possède aucun moyen d'agir : une action est une PROPOSITION d'un outil d'un autre département, déposée
dans la file d'approbation native avec ses arguments exacts (port ``opsys.actions_m9``). Le registre chaîné ``actions``
ne garde que ce qui permet de contrôler : le département et l'outil, l'empreinte des arguments (jamais leur contenu, qui
vit dans la demande native), les sources citées, l'identifiant de la demande native et les constats de réconciliation.

Un constat vient de l'état NATIF de la demande :

* ``en_attente`` → EN_ATTENTE_APPROBATION ; ``refusee`` → REFUSEE ;
* ``executee`` avec succès déclaré par le producteur lui-même → EXECUTEE_CONFIRMEE ;
* ``echec`` → ECHEC (la transaction native est atomique : aucun effet partiel) ;
* tout le reste (demande introuvable, ``en_cours``, arguments divergents, exécutée sans succès déclaré) → INCONNU.

Pas de rejeu : une action (même outil, mêmes arguments) ne se propose pas de nouveau tant qu'elle est en attente,
exécutée ou INCONNUE ; seuls REFUSEE et ECHEC permettent une nouvelle tentative, numérotée. Un effet inconnu ne se
rejoue
jamais : il se réconcilie ou se tranche par un humain.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs
from . import chainage

SCHEMA = "m9.actions.v1"
TYPES = frozenset({"PROPOSITION", "RECONCILIATION"})
ETATS_BLOQUANTS = frozenset({"EN_ATTENTE_APPROBATION", "EXECUTEE_CONFIRMEE", "INCONNU"})
ETATS_FINAUX = frozenset({"REFUSEE", "EXECUTEE_CONFIRMEE", "ECHEC"})
# Reflet de ``opsys.actions_m9.ACTIONS_AUTORISEES`` (un test impose l'égalité) : la frontière réelle est côté socle.
ACTIONS: dict[str, frozenset[str]] = {
    "m02-revenue-crm": frozenset({"m2_preparer_relance", "m2_reassigner_lead"}),
    "m04-field-ops": frozenset({"m4_planifier_intervention", "m4_creer_demande_ecart"}),
    "m10-memoire": frozenset({"m10_journaliser_decision"}),
}
_SHA = r"[0-9a-f]{64}"
_SOURCE = re.compile(
    r"(?:[a-z0-9_.]+#\d+:p\d+\.[A-Za-z0-9_.\[\]]+|(?:playbook|priorisation|radar|conseil|veille):[0-9a-f]{12,64})"
)
_DEMANDE = re.compile(r"[0-9a-f]{12}")
MAX_SOURCES = 12
_LIMITES = (
    "M9 propose ; l'exécution appartient à la file d'approbation native et au département cible, sous leurs rôles.",
    "Les arguments ne sont pas conservés ici (seule leur empreinte) ; un effet inconnu ne se rejoue jamais.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def valider_chaine(chaine: Sequence[Mapping]) -> tuple[bool, str]:
    return chainage.valider(SCHEMA, TYPES, chaine)


def identifiant_action(departement: str, outil: str, arguments_sha256: str) -> str:
    return cs.empreinte({"departement": departement, "outil": outil, "arguments": arguments_sha256})[:32]


def etat(chaine: Sequence[Mapping]) -> dict[str, dict]:
    """Projection ``action_id → état courant`` (tentative, état, demande native, constats)."""
    actions: dict[str, dict] = {}
    for evenement in chaine:
        courante = actions.setdefault(
            evenement["action_id"],
            {"action_id": evenement["action_id"], "tentative": 0, "etat": None, "demande_id": None, "constats": []},
        )
        if evenement["type"] == "PROPOSITION":
            courante.update(
                {
                    "tentative": evenement["tentative"],
                    "etat": "EN_ATTENTE_APPROBATION",
                    "demande_id": evenement["demande_id"],
                    "departement": evenement["departement"],
                    "outil": evenement["outil"],
                    "arguments_sha256": evenement["arguments_sha256"],
                    "niveau": evenement["niveau"],
                    "sources": evenement["sources"],
                    "motif": evenement["motif"],
                    "propose_le": evenement["recu_a"],
                }
            )
        else:
            courante["etat"] = evenement["constat"]
            courante["constats"].append({k: evenement[k] for k in ("constat", "statut_natif", "recu_a", "decide_par")})
    return actions


def controler(departement: str, outil: str, sources: Sequence[str], motif: str, recu_a: str) -> None:
    """Contrôles purs faits AVANT toute écriture native : liste blanche, sources citées, motif, instant."""
    if outil not in ACTIONS.get(departement, frozenset()):
        raise _refus("REJ-ACTION-NON-AUTORISEE", "outil absent de la liste blanche des actions proposables")
    if not isinstance(sources, Sequence) or isinstance(sources, str) or not 1 <= len(sources) <= MAX_SOURCES:
        raise _refus("REJ-ACTION-SOURCES", f"1 à {MAX_SOURCES} sources citées requises : aucune action sans fondement")
    if any(type(s) is not str or not _SOURCE.fullmatch(s) for s in sources):
        raise _refus(
            "REJ-ACTION-SOURCES", "source : adresse de fait ou référence playbook/priorisation/radar/conseil/veille"
        )
    if type(motif) is not str or not motif.strip() or len(motif) > 300:
        raise _refus("REJ-ACTION-MOTIF", "motif borné requis")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")


def proposition(
    chaine: Sequence[Mapping],
    *,
    departement: str,
    outil: str,
    arguments_sha256: str,
    demande_id: str,
    niveau: str,
    sources: Sequence[str],
    motif: str,
    recu_a: str,
    propose_par: str,
) -> dict:
    """Maillon PROPOSITION, après contrôle de la liste blanche, des sources et du rejeu."""
    controler(departement, outil, sources, motif, recu_a)
    if type(arguments_sha256) is not str or not re.fullmatch(_SHA, arguments_sha256):
        raise _refus("REJ-ACTION-ARGUMENTS", "empreinte d'arguments invalide")
    if type(demande_id) is not str or not _DEMANDE.fullmatch(demande_id):
        raise _refus("REJ-ACTION-DEMANDE", "identifiant de demande native invalide")
    action_id = identifiant_action(departement, outil, arguments_sha256)
    courante = etat(chaine).get(action_id)
    if courante is not None and courante["etat"] in ETATS_BLOQUANTS:
        raise _refus(
            "REJ-ACTION-REJEU",
            f"action déjà {courante['etat']} (tentative {courante['tentative']}) : "
            + (
                "réconcilier ou faire trancher par un humain, ne jamais rejouer"
                if courante["etat"] == "INCONNU"
                else "aucune nouvelle proposition"
            ),
        )
    tentative = (courante["tentative"] if courante is not None else 0) + 1
    return chainage.suivant(
        SCHEMA,
        chaine,
        {
            "type": "PROPOSITION",
            "action_id": action_id,
            "tentative": tentative,
            "departement": departement,
            "outil": outil,
            "arguments_sha256": arguments_sha256,
            "demande_id": demande_id,
            "niveau": niveau,
            "sources": list(sources),
            "motif": motif,
            "recu_a": recu_a,
            "par": propose_par,
        },
    )


def constater(natif: Mapping | None, proposition_courante: Mapping) -> tuple[str, str]:
    """(constat, statut natif) d'après la lecture native d'une demande."""
    if not isinstance(natif, Mapping) or natif.get("ok") is not True or natif.get("trouvee") is not True:
        return "INCONNU", "introuvable"
    statut = natif.get("statut")
    if (
        natif.get("arguments_sha256") != proposition_courante["arguments_sha256"]
        or natif.get("outil") != proposition_courante["outil"]
    ):
        return "INCONNU", str(statut)
    if statut == "en_attente":
        return "EN_ATTENTE_APPROBATION", statut
    if statut == "refusee":
        return "REFUSEE", statut
    if statut == "echec":
        return "ECHEC", statut
    if statut == "executee":
        return ("EXECUTEE_CONFIRMEE" if natif.get("succes_declare") is True else "INCONNU"), statut
    return "INCONNU", str(statut)


def reconciliation(chaine: Sequence[Mapping], action_id: str, natif: Mapping | None, *, recu_a: str) -> dict | None:
    """Maillon RECONCILIATION, ou ``None`` si le constat est identique au dernier connu (idempotent)."""
    courante = etat(chaine).get(action_id)
    if courante is None or courante["etat"] is None:
        raise _refus("REJ-ACTION-INCONNUE", "action jamais proposée")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    constat, statut_natif = constater(natif, courante)
    if (
        constat == courante["etat"]
        and courante["constats"]
        and courante["constats"][-1]["statut_natif"] == statut_natif
    ):
        return None
    if constat == courante["etat"] == "EN_ATTENTE_APPROBATION" and not courante["constats"]:
        return None  # l'état initial est déjà celui de la proposition
    return chainage.suivant(
        SCHEMA,
        chaine,
        {
            "type": "RECONCILIATION",
            "action_id": action_id,
            "tentative": courante["tentative"],
            "demande_id": courante["demande_id"],
            "constat": constat,
            "statut_natif": statut_natif,
            "decide_par": natif.get("decide_par") if isinstance(natif, Mapping) else None,
            "resultat_sha256": natif.get("resultat_sha256") if isinstance(natif, Mapping) else None,
            "recu_a": recu_a,
        },
    )


def vue(chaine: Sequence[Mapping]) -> dict:
    actions = sorted(etat(chaine).values(), key=lambda a: a["action_id"])
    comptes: dict[str, int] = {}
    for action in actions:
        comptes[action["etat"]] = comptes.get(action["etat"], 0) + 1
    return {
        "type": "ACTIONS_M9",
        "total": len(actions),
        "par_etat": comptes,
        "actions": actions,
        "limites": list(_LIMITES),
    }
