"""Suivi d'une conversation ouverte (PLAN T4.4) : une conversation qui n'est pas finie a une PROCHAINE ACTION datée
au registre anti-perte, pour qu'aucune ne meure à la porte (§7 M1 : « M1 ne doit jamais laisser une conversation sans
prochaine action »). Le digest de M1 (M1.11) la relit pour dire les conversations « sans suivi ».

Les dates ne viennent jamais de l'horloge du modèle ni de celle du système :

- `inscrite_le` est l'heure de réception du message que la plateforme a livrée (ou l'instant fourni par l'appelant) ;
- `a_faire_avant` est la fin de la fenêtre de la conversation : `ouverture + fenetre_conversation_minutes` (profil
  d'entreprise). Passé ce moment, les messages suivants du client ne se rejoignent plus : c'est l'échéance réelle.
  Aucun délai de relance n'est inventé.

La prochaine action est un choix fermé, décidé par règles :

| Action                           | Quand                                                                   |
|----------------------------------|-------------------------------------------------------------------------|
| `demander_precisions`            | il manque un champ du lead (service, ville, contact)                    |
| `poser_les_questions_du_service` | le lead est complet, mais des questions du service restent sans réponse |
| `decision_humaine_apres_retrait` | l'une ou l'autre reste à demander, mais le client s'est retiré (STOP)   |
| (aucune)                         | rien à demander : la ligne est fermée                                   |

Le message qu'elle décrit n'est JAMAIS envoyé par M1 : c'est un brouillon, que `m1_emettre_notification` (N4) propose à
une personne. Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

TYPE_SUIVI = "suivi_conversation"
STATUT_OUVERTE = "ouverte"
STATUT_CLOSE = "close"
MOTIF_RETRAIT = "retrait_consentement"
MOTIF_RIEN_A_DEMANDER = "rien_a_demander"

ACTION_DEMANDER_PRECISIONS = "demander_precisions"
ACTION_POSER_LES_QUESTIONS = "poser_les_questions_du_service"
ACTION_DECISION_HUMAINE = "decision_humaine_apres_retrait"


def prochaine_action(
    champs_manquants: Sequence[str], questions_restantes: Sequence[str], retire: bool, inscrite_le: str,
    a_faire_avant: str,
) -> dict[str, Any] | None:
    """La prochaine action de la conversation, datée, ou `None` quand il n'y a plus rien à demander.

    `inscrite_le`, `a_faire_avant` : fournis par l'appelant (heure de la plateforme, fin de la fenêtre)."""
    if champs_manquants:
        action = ACTION_DEMANDER_PRECISIONS
        reste = f"demander au client : {', '.join(champs_manquants)}"
    elif questions_restantes:
        action = ACTION_POSER_LES_QUESTIONS
        reste = f"poser les questions du service : {', '.join(questions_restantes)}"
    else:
        return None
    detail = reste
    if retire:
        action = ACTION_DECISION_HUMAINE
        detail = f"le client s'est retiré des messages, rien ne lui est proposé : une personne décide ({reste})"
    return {"action": action, "detail": detail, "inscrite_le": inscrite_le, "a_faire_avant": a_faire_avant}


def ligne(
    *,
    canal: str,
    source: str | None,
    conversation_id: str,
    signal_id: str,
    horodatage: str,
    ouverte_le: str,
    connu: dict[str, Any],
    champs_manquants: Sequence[str],
    questions: dict[str, Any],
    score: dict[str, Any],
    action: dict[str, Any] | None,
    lead_id: str | None,
) -> dict[str, Any]:
    """La ligne `suivi_conversation` du registre : l'état de la conversation après CE message, sans texte du client.

    `questions` : le bloc `questions` de la réponse (seuls les codes sont gardés). Une ligne par message reçu (jamais
    pour un rejeu) : la dernière ligne d'une conversation dit où elle en est. `horodatage` est l'heure de réception."""
    ligne_suivi: dict[str, Any] = {
        "type_entree": TYPE_SUIVI,
        "canal": canal,
        "conversation_id": conversation_id,
        "signal_id": signal_id,
        "horodatage": horodatage,
        "ouverte_le": ouverte_le,
        "statut": STATUT_OUVERTE if action is not None else STATUT_CLOSE,
        "connu": connu,
        "champs_manquants": list(champs_manquants),
        "questions": {
            "statut": questions["statut"],
            "repondues": list(questions["repondues"]),
            "restantes": [q["code"] for q in questions["restantes"]],
        },
        "score": score,
        "prochaine_action": action,
        "lead_id": lead_id,
    }
    if source is not None:
        ligne_suivi["source"] = source
    if action is None:
        ligne_suivi["motif_fermeture"] = MOTIF_RIEN_A_DEMANDER
    return ligne_suivi


def ligne_de_fermeture(
    *, canal: str, source: str | None, conversation_id: str, signal_id: str, horodatage: str, ouverte_le: str,
    motif: str,
) -> dict[str, Any]:
    """La ligne qui ferme une conversation ouverte parce qu'un événement la termine (un retrait STOP), sans prochaine
    action : le digest ne la compte plus parmi les conversations ouvertes."""
    ligne_suivi: dict[str, Any] = {
        "type_entree": TYPE_SUIVI,
        "canal": canal,
        "conversation_id": conversation_id,
        "signal_id": signal_id,
        "horodatage": horodatage,
        "ouverte_le": ouverte_le,
        "statut": STATUT_CLOSE,
        "motif_fermeture": motif,
        "prochaine_action": None,
    }
    if source is not None:
        ligne_suivi["source"] = source
    return ligne_suivi
