"""Coffre minimal de clés de chiffrement destructibles (PLAN T4.2, ADR-0009 §2 « tout dans la
même base »).

Un registre de département (`opsys.stockage.maillons`) est un journal append-only : sa table
(`registres_maillons`) n'offre qu'INSERT, jamais UPDATE ni DELETE, précisément pour que sa chaîne
de hash reste une preuve d'intégrité. Cette propriété est exactement ce qui rend une donnée
personnelle qu'on y écrit impossible à détruire directement (POLITIQUE-geolocalisation.md §5).

Ce module fait l'inverse : une table où chaque ligne PEUT être vraiment supprimée. Un consommateur
(ex. `m4_field_ops.pointage`, via `retention.chiffrer_position`) chiffre une donnée avant de
l'écrire dans un registre, avec une clé obtenue ici ; détruire la clé plus tard (`detruire`) rend
cette donnée déjà écrite irrécupérable, sans jamais toucher au registre ni à son empreinte — c'est
l'effacement cryptographique (crypto-shredding).

`portee` namespace l'usage (ex. ``"m04-field-ops/gps"``) : deux départements, ou deux finalités du
même département, n'entrent jamais en collision même avec le même ``identifiant``. Une seule clé
par ``(portee, identifiant)`` en v1 : aucune rotation, aucun historique de clés — une nouvelle clé
après destruction (``obtenir_ou_creer`` rappelé pour la même portée/identifiant) démarre une
période de rétention neuve, ce qui est le comportement voulu (ex. un employé réembauché).

Bibliothèque standard uniquement (``secrets``), comme le reste du socle (``console.securite``).
"""

from __future__ import annotations

import secrets

from sqlalchemy import Connection, delete, select

from .stockage.moteur import inserer
from .stockage.schema import CLES_CHIFFREMENT

LONGUEUR_CLE_OCTETS = 32

__all__ = ["LONGUEUR_CLE_OCTETS", "obtenir_ou_creer", "lire", "detruire"]


def lire(cnx: Connection, portee: str, identifiant: str) -> bytes | None:
    """Clé actuelle, ou ``None`` si elle n'a jamais existé OU si elle a été détruite (crypto-
    shredding, PLAN T4.2) : les deux cas sont indistinguables ici, exactement l'effet recherché —
    une fois détruite, une clé n'est pas différente d'une clé qui n'a jamais existé."""
    valeur = cnx.execute(
        select(CLES_CHIFFREMENT.c.cle).where(
            (CLES_CHIFFREMENT.c.portee == portee) & (CLES_CHIFFREMENT.c.identifiant == identifiant)
        )
    ).scalar_one_or_none()
    return bytes.fromhex(valeur) if valeur is not None else None


def obtenir_ou_creer(cnx: Connection, portee: str, identifiant: str, cree_le: str) -> bytes:
    """Clé existante pour ``(portee, identifiant)``, ou une NOUVELLE clé aléatoire (32 octets,
    ``secrets.token_bytes`` — jamais dans un module pur de département, toujours ici, à la
    frontière impure) si aucune n'existe encore. Idempotent et sûr en écriture concurrente :
    l'INSERT porte ``ON CONFLICT DO NOTHING`` sur la clé primaire, puis une lecture RESTITUE
    toujours la ligne qui a gagné (la nôtre, ou celle d'un autre appelant simultané) — jamais deux
    clés différentes pour la même (portee, identifiant)."""
    nouvelle = secrets.token_bytes(LONGUEUR_CLE_OCTETS)
    insertion = inserer(cnx)(CLES_CHIFFREMENT).values(
        portee=portee, identifiant=identifiant, cle=nouvelle.hex(), cree_le=cree_le,
    )
    cnx.execute(insertion.on_conflict_do_nothing(index_elements=["portee", "identifiant"]))
    cle = lire(cnx, portee, identifiant)
    assert cle is not None, "vient d'être insérée ou existait déjà : ne peut pas être absente ici"
    return cle


def detruire(cnx: Connection, portee: str, identifiant: str) -> bool:
    """DELETE réel (PLAN T4.2, contrairement à un registre append-only). Retourne ``True`` si une
    clé a effectivement été supprimée, ``False`` si elle n'existait déjà plus (purge rejouée sur un
    technicien déjà purgé, ou jamais géolocalisé : idempotent, jamais une erreur)."""
    resultat = cnx.execute(
        delete(CLES_CHIFFREMENT).where(
            (CLES_CHIFFREMENT.c.portee == portee) & (CLES_CHIFFREMENT.c.identifiant == identifiant)
        )
    )
    return resultat.rowcount > 0
