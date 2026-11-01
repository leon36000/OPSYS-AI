"""Réception d'un courriel ENTRANT par M1 : ce que les connecteurs remettent, et rien de plus.

Un courriel qui arrive (synchronisation incrémentale, jamais l'historique d'onboarding) devient une réception de M1 par
le même pipeline qu'un message de canal : provenance, registre anti-perte, qualification, bus. Ce module fabrique le
colis `CourrielEntrant` à partir de la vue NEUTRALISÉE (`isolation.vue_pour_agent`) : l'agent, le registre et le bus ne
voient jamais le texte brut. M1 (`m1_front_office.courriel_outils.recevoir_courriel_connecteur`) est le seul à écrire.

Identité sans doublon : `cle_signal` est le même pour un message donné quel que soit le compte, le dossier, le nouvel
amorçage ou le chemin qui le livre (le `Message-ID` seul ; à défaut, compte + référence du fournisseur). M1 en tire le
signal `courriel:<cle>` : la réception est idempotente, et un courriel déjà reçu par l'autre voie (l'outil
`m1_recevoir_message_canal` avec cette même clé) n'est pas reçu une seconde fois.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .isolation import VueAgent
from .modele import MessageNormalise

TEXTE_MAX_OCTETS = 19_000  # sous le plafond de 20 000 octets du pipeline de M1 (`reception.TAILLE_MAX_TEXTE`)
OBJET_MAX = 300
TEXTE_VIDE = "(message sans texte)"
_ID_MESSAGE = re.compile(r"^[^\s<>\x00-\x1f\x7f]{1,255}$")


def cle_signal(compte_id: str, message: MessageNormalise) -> str:
    """Clé stable (64 hexadécimaux) du message pour M1."""
    base = f"mid:{message.message_id}" if message.message_id else f"ref:{compte_id}|{message.id}"
    return hashlib.sha256(("opsys:courriel:m1:v1|" + base).encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class CourrielEntrant:
    """Un courriel prêt pour M1. `objet` et `corps` sont la vue neutralisée ; `expediteur` est l'adresse de l'en-tête
    From (non vérifiée : `authentification` dit seulement ce que le serveur de réception a rapporté)."""

    compte_id: str
    fournisseur: str
    cle: str
    expediteur: str
    recu_le: str
    objet: str = dataclasses.field(repr=False)
    corps: str = dataclasses.field(repr=False)
    signaux: tuple[str, ...]
    neutralise: bool
    empreinte: str
    dossier: str
    nb_pieces: int
    authentification: dict[str, Any]
    reference_reponse: str | None = None  # `Message-ID` du courriel, pour que la réponse s'enfile dans le même fil


Recepteur = Callable[[CourrielEntrant], dict[str, Any]]


def _tronquer_octets(texte: str, maximum: int) -> str:
    brut = texte.encode("utf-8")
    return texte if len(brut) <= maximum else brut[:maximum].decode("utf-8", errors="ignore")


def _instant(valeur: str | None) -> str | None:
    if not valeur:
        return None
    try:
        analyse = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError:
        return None
    if analyse.tzinfo is None:
        analyse = analyse.replace(tzinfo=UTC)
    return analyse.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def construire(message: MessageNormalise, vue: VueAgent, *, compte_id: str, fournisseur: str,
               recu_brut: str | None) -> tuple[CourrielEntrant | None, str | None]:
    """`(colis, None)` ou `(None, raison)` quand le message n'est pas transmissible à M1 : sans expéditeur ou sans date
    de réception. Aucune date n'est inventée (elle entre dans l'identité de la réception : une horloge la changerait à
    chaque rejeu)."""
    if message.expediteur is None or not message.expediteur.courriel:
        return None, "sans_expediteur"
    recu = _instant(message.date_utc) or _instant(recu_brut)
    if recu is None:
        return None, "sans_date"
    corps = _tronquer_octets(vue.corps.strip(), TEXTE_MAX_OCTETS) or TEXTE_VIDE
    objet = " ".join(vue.objet.split())[:OBJET_MAX]
    auth = dict(vue.authentification)
    return CourrielEntrant(
        compte_id=compte_id, fournisseur=fournisseur, cle=cle_signal(compte_id, message),
        expediteur=message.expediteur.courriel, recu_le=recu, objet=objet, corps=corps, signaux=vue.signaux,
        neutralise=vue.neutralise, empreinte=message.empreinte, dossier=message.dossier[:64],
        nb_pieces=len(message.pieces_jointes),
        authentification={k: auth.get(k) for k in ("spf", "dkim", "dmarc", "serveur", "fiable")},
        reference_reponse=message.message_id if message.message_id and _ID_MESSAGE.fullmatch(message.message_id)
        else None,
    ), None
