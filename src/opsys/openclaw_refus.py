"""Refus de `openclaw configurer` rendus visibles à l'admin, une fois par état distinct.

Sur le VPS, `deploy/entrypoint.sh` rejoue `opsys-metier openclaw configurer` toutes les
`OPSYS_SYNC_INTERVAL_SECONDS` (300 s) et ignore son code de sortie : la configuration précédente
reste en place (`openclaw.generer` refuse avant toute écriture). Un `entreprise.yaml` dont les
surcharges `avatars` sont invalides échouerait donc en boucle, sans autre trace qu'un message
répété dans les journaux du conteneur.

Le refus est consigné dans le journal d'audit (`etat.journaliser`) sous l'action
`openclaw.configuration.refusee`, puis projeté dans la console (`/connecteurs`, réservée aux
admins). Déduplication : un refus dont l'empreinte est celle du dernier état consigné n'écrit
rien ; une génération réussie après un refus écrit une seule ligne
`openclaw.configuration.retablie`. Le journal ne porte ni le chemin ni le contenu du profil
fautif (même règle que `console.configuration_lecture._avatars`) : seulement une catégorie et
l'empreinte SHA-256 du message, dont le détail reste sur la sortie d'erreur de la commande et
dans `opsys-metier verifier`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Connection, select

from . import etat
from .stockage.schema import JOURNAL

ACTION_REFUS = "openclaw.configuration.refusee"
ACTION_RETABLIE = "openclaw.configuration.retablie"
CIBLE_AVATARS = "avatars"
AUTEUR = "openclaw-configurer"


def _dernier_etat(cnx: Connection, cible: str) -> dict[str, Any] | None:
    ligne = cnx.execute(
        select(JOURNAL.c.quand, JOURNAL.c.action, JOURNAL.c.details)
        .where(JOURNAL.c.cible == cible, JOURNAL.c.action.in_((ACTION_REFUS, ACTION_RETABLIE)))
        .order_by(JOURNAL.c.id.desc())
        .limit(1)
    ).mappings().first()
    if ligne is None:
        return None
    return {"quand": ligne["quand"], "action": ligne["action"], "details": json.loads(ligne["details"] or "{}")}


def consigner_refus(cnx: Connection, categorie: str, message: str, *, cible: str = CIBLE_AVATARS) -> bool:
    """Consigne un refus de génération ; rend `False` si cet état exact est déjà le dernier consigné."""
    empreinte = hashlib.sha256(message.encode("utf-8")).hexdigest()
    dernier = _dernier_etat(cnx, cible)
    if (
        dernier is not None
        and dernier["action"] == ACTION_REFUS
        and dernier["details"].get("empreinte") == empreinte
        and dernier["details"].get("categorie") == categorie
    ):
        return False
    etat.journaliser(cnx, AUTEUR, ACTION_REFUS, cible, {"categorie": categorie, "empreinte": empreinte})
    return True


def consigner_retablissement(cnx: Connection, *, cible: str = CIBLE_AVATARS) -> bool:
    """Après une génération réussie, clôt un refus en cours ; rend `False` s'il n'y en avait pas."""
    dernier = _dernier_etat(cnx, cible)
    if dernier is None or dernier["action"] != ACTION_REFUS:
        return False
    etat.journaliser(cnx, AUTEUR, ACTION_RETABLIE, cible, {"refus_depuis": dernier["quand"]})
    return True


def refus_en_cours(cnx: Connection, *, cible: str = CIBLE_AVATARS) -> dict[str, Any] | None:
    """Le refus non rétabli, s'il y en a un : `{"depuis", "categorie"}` (jamais le message brut)."""
    dernier = _dernier_etat(cnx, cible)
    if dernier is None or dernier["action"] != ACTION_REFUS:
        return None
    return {"depuis": dernier["quand"], "categorie": dernier["details"].get("categorie")}
