"""Échéances de destruction de clés : enregistrer à l'écriture, détruire à l'échéance, jamais autre chose.

La liste des PORTÉES permises est fermée : le planificateur ne peut détruire que la clé d'un enregistrement vocal ou
d'une adresse de courriel reçue par M1. La rétention GPS de M4 (N5, attestation du professionnel) et toute autre clé
restent hors de portée de ce module, quoi qu'on lui demande.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from .. import cles_chiffrement
from ..stockage.schema import RETENTION_ECHEANCES

PORTEE_VOIX = "avatars-voix/enregistrement"
PORTEE_M1_COURRIEL = "m01-front-office/courriel"
DOMAINES: dict[str, str] = {"voix": PORTEE_VOIX, "m1_courriel": PORTEE_M1_COURRIEL}
_REF = re.compile(r"^[A-Za-z0-9:._-]{8,160}$")
_ESPACE = uuid.UUID("5f0c3f0e-2f7a-4b46-9a53-0b8f6f1d7c11")


class RetentionRefusee(ValueError):
    """Refus typé (`code` stable), aucun contenu."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def instant(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.UTC).isoformat(timespec="seconds")


def enregistrer(cnx: Connection, domaine: str, ref: str, identifiant: str, echeance_epoch: int, cree_le: str) -> None:
    """Inscrit (dans la transaction de l'écriture chiffrée) la date où la clé de `identifiant` doit être détruite."""
    if domaine not in DOMAINES:
        raise RetentionRefusee("REJ-RETENTION-DOMAINE-INCONNU")
    if not _REF.fullmatch(ref) or not identifiant or len(identifiant) > 128 or type(echeance_epoch) is not int \
            or echeance_epoch <= 0:
        raise RetentionRefusee("REJ-RETENTION-ARGUMENT-INVALIDE")
    cnx.execute(insert(RETENTION_ECHEANCES).values(
        domaine=domaine, ref=ref, portee=DOMAINES[domaine], identifiant=identifiant, echeance_epoch=echeance_epoch,
        cree_le=cree_le, statut="en_attente"))


def dues(cnx: Connection, domaine: str, maintenant: int, limite: int = 1000) -> list[dict[str, Any]]:
    if domaine not in DOMAINES:
        raise RetentionRefusee("REJ-RETENTION-DOMAINE-INCONNU")
    lignes = cnx.execute(select(RETENTION_ECHEANCES).where(
        RETENTION_ECHEANCES.c.domaine == domaine, RETENTION_ECHEANCES.c.statut == "en_attente",
        RETENTION_ECHEANCES.c.echeance_epoch <= maintenant).order_by(
        RETENTION_ECHEANCES.c.echeance_epoch, RETENTION_ECHEANCES.c.ref).limit(limite)).mappings().all()
    return [dict(ligne) for ligne in lignes]


def compter(cnx: Connection, domaine: str) -> dict[str, int]:
    sortie = dict.fromkeys(("en_attente", "purgee"), 0)
    for statut, n in cnx.execute(select(RETENTION_ECHEANCES.c.statut, func.count()).where(
            RETENTION_ECHEANCES.c.domaine == domaine).group_by(RETENTION_ECHEANCES.c.statut)):
        sortie[statut] = n
    return sortie


def detruire(cnx: Connection, echeance: dict[str, Any], quand: str) -> str:
    """Détruit la clé de l'échéance (effacement autorisé par la politique approuvée) et marque la ligne purgée.

    Rejeu sûr : le `purge_id` est déterministe ; une échéance dont l'effacement existe déjà est seulement marquée.
    Rend le `purge_id`. Refuse toute portée hors de la liste fermée, même si la ligne la porte."""
    if DOMAINES.get(echeance["domaine"]) != echeance["portee"]:
        raise RetentionRefusee("REJ-RETENTION-PORTEE-INTERDITE")
    purge_id = uuid.uuid5(_ESPACE, f"{echeance['domaine']}|{echeance['ref']}").hex
    if cles_chiffrement.lire_effacement(cnx, purge_id) is None:
        cles_chiffrement.demander_effacement(cnx, echeance["portee"], echeance["identifiant"], quand,
                                             purge_id=purge_id)
    cnx.execute(update(RETENTION_ECHEANCES).where(
        RETENTION_ECHEANCES.c.domaine == echeance["domaine"], RETENTION_ECHEANCES.c.ref == echeance["ref"],
        RETENTION_ECHEANCES.c.statut == "en_attente").values(statut="purgee", purge_le=quand))
    return purge_id
