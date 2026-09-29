"""Qualification par conversation (PLAN T2.1-b, `docs/departements/M1-canaux.md` §6).

Un client écrit souvent le service dans un message et la ville dans le suivant. Qualifié message par message, il ne
donne jamais un lead complet. Ce module rassemble, PAR DU CODE, les messages d'une même `conversation_id` dans une
fenêtre bornée, à partir du registre anti-perte, et dit ce qu'il reste à demander quand le lead n'est pas complet.

Règles (aucune n'est laissée au modèle) :

- **La durée de la fenêtre est un paramètre fourni** (`fenetre_conversation_minutes` du profil d'entreprise,
  `opsys.taxonomie`). Ce module n'en connaît aucune : sans elle, l'appelant ne l'utilise pas, et la qualification
  reste message par message.
- **Une conversation ouverte** commence au premier message que ni un retrait de consentement (STOP) ni la fenêtre
  n'ont fermé. Un message s'y joint si son heure de réception est à au plus `fenetre` minutes de celle du premier
  (l'heure de réception fait foi, pas l'ordre d'arrivée). Au-delà, il ouvre une nouvelle conversation : les messages
  d'avant restent au registre, jamais perdus, mais ne se joignent plus à lui.
- **Un seul lead par conversation ouverte.** Une fois le lead émis, les messages suivants de la même fenêtre s'y
  rattachent sans en créer un second. Un message rejoué n'est jamais relu ici : l'appelant le reconnaît avant.
- **Un retrait ferme la conversation** : ce qui a été écrit avant STOP n'est jamais qualifié.
- Le registre est la seule mémoire : chaque appel relit l'état, rien n'est gardé entre deux appels.

Ce qui est demandé au client reste un BROUILLON : un texte déterministe, passé au garde-fou des interdits, que
l'agent propose par `m1_emettre_notification` (N4, approbation humaine). Rien n'est envoyé ici.

Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from . import garde_fou, qualification

TYPE_LEAD = "lead_emis"
TYPE_SIGNAL = "signal"
MARQUEUR_RETRAIT = "retrait_consentement"


@dataclass(frozen=True)
class ConversationOuverte:
    """L'état de la conversation ouverte d'un correspondant, avant le message qui arrive."""

    ouverture: str | None  # heure de réception du premier message de la conversation ouverte
    messages: tuple[dict[str, Any], ...]  # lignes `signal` de la conversation ouverte, dans l'ordre d'arrivée
    lead: dict[str, Any] | None  # ligne `lead_emis` si la conversation est déjà qualifiée
    retire: bool  # le correspondant a déjà écrit un mot de retrait : aucun brouillon ne lui est proposé
    hors_fenetre: int  # messages sans lead d'une conversation que la fenêtre vient de fermer


def _instant(horodatage: str) -> dt.datetime:
    return dt.datetime.fromisoformat(horodatage)


def lire(
    lignes: Iterable[dict[str, Any]], conversation_id: str, horodatage: str, fenetre_minutes: int
) -> ConversationOuverte:
    """La conversation ouverte de `conversation_id` juste avant un message reçu à `horodatage`.

    `lignes` : le registre anti-perte dans l'ordre d'écriture. Le message qui arrive n'y est PAS encore.
    """
    fenetre = dt.timedelta(minutes=fenetre_minutes)
    ouverture: dt.datetime | None = None
    messages: list[dict[str, Any]] = []
    lead: dict[str, Any] | None = None
    retire = False
    hors_fenetre = 0
    for ligne in lignes:
        if ligne.get("conversation_id") != conversation_id:
            continue
        type_entree = ligne.get("type_entree")
        if type_entree == TYPE_SIGNAL:
            recu = _instant(ligne["horodatage"])
            if ouverture is not None and abs(recu - ouverture) > fenetre:
                ouverture, messages, lead = None, [], None
            if ouverture is None:
                ouverture = recu
            messages.append(ligne)
        elif type_entree == TYPE_LEAD:
            lead = ligne
        elif type_entree == "alerte" and ligne.get("marqueur") == MARQUEUR_RETRAIT:
            ouverture, messages, lead, retire = None, [], None, True
    courant = _instant(horodatage)
    if ouverture is not None and abs(courant - ouverture) > fenetre:
        hors_fenetre = 0 if lead is not None else len(messages)
        ouverture, messages, lead = None, [], None
    return ConversationOuverte(
        ouverture=None if ouverture is None else ouverture.isoformat(),
        messages=tuple(messages),
        lead=lead,
        retire=retire,
        hors_fenetre=hors_fenetre,
    )


def contenu_rassemble(conversation: ConversationOuverte, contenu_courant: str) -> str:
    """Les messages de la conversation ouverte, dans l'ordre d'arrivée, puis le message courant.

    Ce sont les contenus DÉJÀ filtrés par la provenance (`contenu_filtre` du registre) : aucun texte brut n'est relu.
    """
    return "\n".join([m["contenu_filtre"] for m in conversation.messages] + [contenu_courant])


def signaux_rassembles(conversation: ConversationOuverte, signal_courant: str) -> list[str]:
    """Les identifiants de signal des messages rassemblés, le message courant en dernier."""
    return [m["signal_id"] for m in conversation.messages] + [signal_courant]


def decrire(
    conversation: ConversationOuverte, horodatage: str, fenetre_minutes: int, signaux: Sequence[str],
    diagnostic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Le bloc `conversation` de la réponse de l'outil : la fenêtre, ce qui est rassemblé, ce qui est connu.

    Les heures sont calculées ici, par du code : ouverture (le premier message rassemblé, ou celui-ci) et
    expiration (ouverture + fenêtre). `diagnostic` (de `qualification.diagnostiquer`) ajoute ce qui est connu.
    """
    ouverture = conversation.ouverture or horodatage
    bloc: dict[str, Any] = {
        "mode": "fenetre",
        "fenetre_minutes": fenetre_minutes,
        "messages": len(signaux),
        "signaux": list(signaux),
        "ouverte_le": ouverture,
        "expire_le": (_instant(ouverture) + dt.timedelta(minutes=fenetre_minutes)).isoformat(),
        "hors_fenetre": conversation.hors_fenetre,
    }
    if diagnostic is not None:
        bloc["connu"] = connu(diagnostic)
    return bloc


def connu(diagnostic: dict[str, Any]) -> dict[str, Any]:
    """Ce que la conversation établit, cumulé sur tous ses messages : le service et la ville (ou `None`), la source du
    contact (`canal` : l'identité que la plateforme a vérifiée ; `texte` : écrit par le client ; ou `None`), et
    l'urgence, vraie dès qu'UN message la déclare."""
    return {
        "service": diagnostic["service"],
        "ville": diagnostic["ville"],
        "contact": diagnostic["contact"],
        "urgence_declaree": diagnostic["urgence_declaree"],
    }


def ce_qui_manque(diagnostic: dict[str, Any]) -> list[str]:
    """Chaque champ du lead que la conversation n'établit pas (`service`, `ville`, `contact`), dans cet ordre."""
    return qualification.champs_manquants(diagnostic)


def _liste_ou(libelles: Sequence[str]) -> str:
    """« A », « A ou B », « A, B ou C »."""
    if len(libelles) == 1:
        return libelles[0]
    return f"{', '.join(libelles[:-1])} ou {libelles[-1]}"


_PIECE_VILLE = "dans quelle ville se trouve la propriété"
_PIECE_CONTACT = "à quel numéro de téléphone ou à quelle adresse courriel pouvons-nous vous joindre"


def _demande(diagnostic: dict[str, Any], libelles: dict[str, str]) -> str:
    """La question, selon ce qui manque : un service (aucun ou plusieurs évoqués), une ville, un contact, ou plusieurs.
    """
    evoques = diagnostic["services_evoques"]
    pieces = []
    for champ in ce_qui_manque(diagnostic):
        if champ == "ville":
            pieces.append(_PIECE_VILLE)
        elif champ == "contact":
            pieces.append(_PIECE_CONTACT)
        elif len(evoques) > 1:
            choix = ", ".join(libelles[code] for code in evoques)
            pieces.append(f"Vous parlez de plusieurs services : {choix}. Par lequel souhaitez-vous commencer")
        else:
            pieces.append(f"Quel service vous intéresse ({_liste_ou(list(libelles.values()))})")
    pieces[0] = pieces[0][0].upper() + pieces[0][1:]
    if len(pieces) == 1:
        return f"{pieces[0]}?"
    return f"{', '.join(pieces[:-1])}, et {pieces[-1]}?"


def proposer_precisions(
    diagnostic: dict[str, Any], libelles_services: dict[str, str], retire: bool
) -> dict[str, Any]:
    """Ce qui reste à demander, et un brouillon pour le demander. Le brouillon est `None` quand :

    - le correspondant s'est retiré (STOP) : aucun message ne lui est proposé ;
    - ou le garde-fou des interdits refuse le texte (un libellé de service déclaré ne doit pas y glisser un prix).

    `libelles_services` : `{code: libellé}` des services déclarés par l'entreprise (jamais une liste locale).
    """
    manque = ce_qui_manque(diagnostic)
    resultat: dict[str, Any] = {"a_demander": manque, "brouillon_reponse": None, "envoye": False}
    if retire:
        resultat["sans_brouillon"] = "retrait_consentement"
        return resultat
    texte = f"Bonjour, merci de votre message. {_demande(diagnostic, libelles_services)}"
    verdict = garde_fou.verifier_sortie(texte)
    if verdict["code"] != "OK":
        resultat["sans_brouillon"] = verdict["code"]
        return resultat
    resultat["brouillon_reponse"] = texte
    return resultat
