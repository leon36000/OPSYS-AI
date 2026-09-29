"""Le retrait du consentement (STOP), publié sur le bus pour les départements qui en dépendent (PLAN T4.17-c).

Un correspondant qui écrit STOP se retire des messages (`outils._enregistrer_retrait`, POLITIQUE-consentement-sms §4).
Ce retrait ne concerne pas que M1 : un client qui ne veut plus être contacté n'a pas consenti non plus à ce que son
chantier serve de contenu public. M1 le dit donc au bus (`m1.retrait_consentement`), et M7 en tire ses propres
conséquences (registre `retraits_consentement_marketing`). M1 n'importe pas M7 : il publie un fait.

**Le lien entre le correspondant et son chantier est le `lead_id`, jamais un contact.** M1 crée le `lead_id` (il
vient de la conversation, du texte et de l'identité du canal), M2 le reprend tel quel, le WCT de M4 le porte : M7 le
connaît. Le numéro du correspondant, lui, ne sort pas du registre de M1 : l'événement ne porte ni téléphone, ni
courriel, ni `conversation_id` (une empreinte du numéro). M2 dérive un `client_id` du contact ; M1 n'y a pas accès sans
copier son algorithme, ce que la séparation des départements interdit : le `lead_id` suffit.

Ce que ce lien ne couvre PAS : un même client qui écrit d'un autre numéro, ou par un autre canal, est un autre
correspondant pour M1 (une autre conversation, d'autres leads). Le retrait ne le suit pas.

Un lead que le même correspondant ouvre APRÈS son STOP est couvert aussi : M1 publie alors un second événement, pour ce
lead seul, avec l'heure et le signal du STOP d'origine (le retrait ne se lève pas : `transferts.retire`).

Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .conversation import MARQUEUR_RETRAIT

TYPE_EVENEMENT = "m1.retrait_consentement"
_PREFIXE_IDENTIFIANT = "m1-retrait-consentement-"


def leads_de_la_conversation(lignes: Iterable[Mapping[str, Any]], conversation_id: str) -> tuple[str, ...]:
    """Les `lead_id` que M1 a émis pour cette conversation (un correspondant, un canal), dans l'ordre du registre, sans
    répétition. Vide si aucun lead n'a été qualifié : rien n'est alors à retirer chez un consommateur."""
    vus: list[str] = []
    for ligne in lignes:
        if ligne.get("type_entree") != "lead_emis" or ligne.get("conversation_id") != conversation_id:
            continue
        lead = ligne.get("lead")
        lead_id = lead.get("lead_id") if isinstance(lead, Mapping) else None
        if isinstance(lead_id, str) and lead_id and lead_id not in vus:
            vus.append(lead_id)
    return tuple(vus)


def alerte_de_retrait(lignes: Iterable[Mapping[str, Any]], conversation_id: str) -> Mapping[str, Any] | None:
    """La PREMIÈRE ligne de retrait de cette conversation, ou `None` : c'est elle qui date le retrait (un second STOP
    ne le déplace pas)."""
    for ligne in lignes:
        if (
            ligne.get("type_entree") == "alerte" and ligne.get("marqueur") == MARQUEUR_RETRAIT
            and ligne.get("conversation_id") == conversation_id
        ):
            return ligne
    return None


def charge(alerte: Mapping[str, Any], lead_ids: Sequence[str]) -> dict[str, Any]:
    """La charge de `m1.retrait_consentement` : les leads, le canal du core, l'heure et le signal du STOP. Aucun
    contact, aucun texte du client (l'alerte n'en porte pas)."""
    return {
        "lead_ids": list(lead_ids),
        "canal": alerte["source"],
        "horodatage": alerte["horodatage"],
        "signal_id": alerte["signal_id"],
    }


def identifiant_evenement(signal_id: str, lead_ids: Sequence[str]) -> str:
    """Déterministe : le même STOP pour les mêmes leads est le même événement (`opsys.evenements.publier`, idempotent).
    L'ordre des leads ne compte pas ; le signal du STOP les distingue d'un autre STOP."""
    materiau = "|".join(f"{len(x)}:{x}" for x in (signal_id, *sorted(lead_ids)))
    return f"{_PREFIXE_IDENTIFIANT}{hashlib.sha256(materiau.encode('utf-8')).hexdigest()[:24]}"
