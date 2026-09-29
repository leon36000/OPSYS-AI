"""Liaison d'une session à une affaire (PLAN T3.3-suite-b) : l'affaire vient de la SESSION, jamais du texte.

Sur un canal client (M1), le texte de la demande est celui du client : une ligne ``affaire_id: <lead_id>``
qu'il écrit ne prouve rien, et un client pourrait nommer l'affaire d'un autre. L'affaire d'un tour doit
donc venir de ce que la plateforme fixe : la CLÉ DE SESSION (``agent:<agent>:<canal>:direct:<pair>``, que le
core compose depuis le routage du canal, jamais depuis un texte). M10 garde le lien clé de session -> affaire ;
le moteur de contexte du core le lit par ``m10_affaire_de_la_session`` quand la configuration de l'agent
dit ``"affaire": "session"``.

Qui écrit le lien : un HUMAIN identifié (``humain.py``), avec son motif, jamais un modèle. Le lien est un
maillon ``session_affaire_liee`` du registre Affaires, append-only : lier une session à une autre affaire
(un client qui revient pour un nouveau projet) ajoute un maillon, le DERNIER fait foi, les précédents
restent lisibles. Aucun lien n'est déduit ni deviné : sans lien, la lecture dit « aucune affaire liée »
et le moteur de contexte travaille SANS paquet (marqueur « indisponible », actions N3 bloquées).

Ce que ce module ne fait pas encore : le lien automatique à la création d'un lead par M1. Il exige que M1 (ou
M2) sache la clé de session de la conversation qui crée le lead, et un producteur qui l'écrive par du code
déterministe (événement du bus), pas par un modèle. Jusque-là, c'est un humain qui lie (app admin).

Module pur (DA-M10-08) : aucun import d'``opsys``. ``horodatage`` est fourni par l'appelant.
"""

from __future__ import annotations

import re
from typing import Any

from . import affaire, humain, validation

TYPE_ENTREE_LIAISON = "session_affaire_liee"

REJ_LIAISON_CLE_SESSION_INVALIDE = "REJ-LIAISON-CLE-SESSION-INVALIDE"
REJ_LIAISON_AFFAIRE_INVALIDE = "REJ-LIAISON-AFFAIRE-INVALIDE"

# Clé de session d'un agent, telle que le core la compose (`buildAgentPeerSessionKey`) : `agent:<agent>:` (agent
# en minuscules) puis le reste (canal, pair, fil), tel quel : le core garde tels quels les identifiants opaques
# des correspondants (`normalizeSessionKeyPreservingOpaquePeerIds`), majuscules comprises. La clé est comparée
# à l'identique, jamais normalisée ici : le moteur de contexte envoie celle qu'il a reçue. Aucun espace ni
# caractère de contrôle.
_CLE_SESSION = re.compile(r"^agent:[a-z0-9][a-z0-9_-]{0,63}:[^\s\x00-\x1f\x7f]{1,200}$")
SESSION_PRINCIPALE = "main"


def cle_session_valide(cle_session: Any) -> bool:
    """Vrai pour la clé d'une session d'UN correspondant. La session principale d'un agent (``agent:<agent>:
    main``) est partagée par tous ses correspondants : la lier à une affaire l'attribuerait à tous les clients."""
    if not isinstance(cle_session, str) or _CLE_SESSION.fullmatch(cle_session) is None:
        return False
    return cle_session.split(":", 2)[2] != SESSION_PRINCIPALE


def affaire_valide(affaire_id: Any) -> bool:
    """La forme d'affaire commune au core et à M10 (`affaire.py`) : un lead, ou l'opportunité que M2 ouvre pour un
    client qui revient, à laquelle un humain lie sa nouvelle conversation."""
    return affaire.valide(affaire_id)


def lier_session_affaire(
    cle_session: str,
    affaire_id: str,
    par: str,
    role: str,
    source_decision: str,
    motif: str,
    horodatage: str,
    registre_affaires: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Écrit le lien ; rend ``(maillon, None)`` ou ``(None, verdict)``. Un refus n'écrit rien."""
    if not cle_session_valide(cle_session):
        return None, validation.construire_verdict(
            REJ_LIAISON_CLE_SESSION_INVALIDE,
            "clé de session attendue : agent:<agent>:<canal>:direct:<pair>, telle que le core "
            "la compose ; la session principale d'un agent (agent:<agent>:main) est partagée : jamais liée",
        )
    if not affaire_valide(affaire_id):
        return None, validation.construire_verdict(
            REJ_LIAISON_AFFAIRE_INVALIDE,
            "affaire_id attendu : le lead_id de l'affaire, ou <lead>~opp~<wct_id> pour l'opportunité que M2 ouvre "
            "(lettres, chiffres et ._:-, 197 caractères au plus)",
        )
    defaut = humain.verifier_ecriture(par, role, source_decision, motif, horodatage)
    if defaut is not None:
        return None, defaut
    ligne_id = registre_affaires.ajouter(
        {
            "type_entree": TYPE_ENTREE_LIAISON,
            "horodatage": horodatage,
            "cle_session": cle_session,
            "affaire_id": affaire_id,
            "par": par,
            "role": role,
            "source_decision": source_decision,
            "motif": motif.strip(),
        }
    )
    for maillon in registre_affaires.lire():
        if maillon.get("ligne_id") == ligne_id:
            return maillon, None
    raise RuntimeError("Maillon ajouté introuvable.")


def affaire_de_la_session(cle_session: Any, registre_affaires: Any) -> dict[str, Any]:
    """Le lien courant de cette session, ou ``{"lie": False, "affaire_id": None}`` : jamais une affaire
    par défaut. Un maillon dont l'auteur n'a pas la forme d'un humain identifié est ignoré."""
    if not cle_session_valide(cle_session):
        raise ValueError("cle_session invalide : agent:<agent>:<canal>:direct:<pair>, telle que le core la compose")
    courant = None
    for maillon in registre_affaires.lire():
        if (
            maillon.get("type_entree") == TYPE_ENTREE_LIAISON
            and maillon.get("cle_session") == cle_session
            and affaire_valide(maillon.get("affaire_id"))
            and humain.acteur_valide(maillon.get("par"), maillon.get("role"), maillon.get("source_decision"))
        ):
            courant = maillon
    if courant is None:
        return {"lie": False, "affaire_id": None}
    return {
        "lie": True,
        "affaire_id": courant["affaire_id"],
        "lie_par": courant["par"],
        "lie_le": courant["horodatage"],
    }
