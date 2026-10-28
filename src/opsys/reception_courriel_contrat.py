"""Codec pur d'un original courriel : aucune preuve d'origine ou d'autorisation.

Ce résultat décrit les octets et les coordonnées fournis par l'appelant. Il n'est
ni un reçu durable, ni une capacité Host, ni une permission d'écriture ou d'envoi.
"""
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType
from uuid import UUID

_CHAMPS = frozenset({
    "version", "instance_id", "source_id", "compte_id", "boite", "uid_validity",
    "uid", "taille_annoncee", "recu_le", "date_interne", "message_id",
})
COORDONNEES = ("instance_id", "source_id", "compte_id", "boite", "uid_validity", "uid")
_MAX_SOURCE = 1_048_576
_UID_MAX = 4294967295
_ERREUR = "REJ-M1-COURRIEL-ORIGINAL-INVALIDE"


def _exiger(condition: bool) -> None:
    if not condition:
        raise ValueError(_ERREUR)


def _texte(value: object, maximum: int) -> None:
    _exiger(type(value) is str)
    _exiger(1 <= len(value) <= maximum)
    try:
        # Same UTF16 code-unit bound as the native JavaScript mailbox guard.
        length = len(value.encode("utf-16-le")) // 2
    except UnicodeError:
        raise ValueError(_ERREUR) from None
    _exiger(1 <= length <= maximum and not any(c in value for c in "\x00\r\n"))


def _date(value: object) -> None:
    _texte(value, 24)
    _exiger(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", value) is not None)
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(_ERREUR) from None


@dataclass(frozen=True, slots=True)
class OriginalCourriel:
    """Description immuable, expressément sans valeur d'autorité ou d'ACK."""

    arguments: Mapping[str, str | int | None] = field(repr=False)
    source: bytes = field(repr=False)
    identite_id: str
    source_sha256: str
    source_octets: int


def valider_original(arguments: dict, *, source: bytes) -> OriginalCourriel:
    """Refuse les formes ambiguës et calcule les empreintes sans IO ni normalisation."""
    _exiger(type(arguments) is dict and type(source) is bytes)
    _exiger(len(arguments) == len(_CHAMPS))
    # Snapshot once before validation/hash work can yield to another caller thread.
    arguments = dict(arguments)
    _exiger(len(arguments) == len(_CHAMPS))
    _exiger(all(type(key) is str for key in arguments))
    _exiger(set(arguments) == _CHAMPS)
    _exiger(type(arguments["version"]) is int and arguments["version"] == 1)
    _exiger(type(arguments["taille_annoncee"]) is int)
    _exiger(1 <= len(source) <= _MAX_SOURCE and arguments["taille_annoncee"] == len(source))
    identity_id = identifier_source({k: arguments[k] for k in COORDONNEES})
    _date(arguments["recu_le"])
    if arguments["date_interne"] is not None:
        _date(arguments["date_interne"])
    if arguments["message_id"] is not None:
        _texte(arguments["message_id"], 1024)

    return OriginalCourriel(
        arguments=MappingProxyType(arguments), source=source,
        identite_id=identity_id, source_sha256=sha256(source).hexdigest(), source_octets=len(source),
    )


def identifier_source(coordonnees: dict) -> str:
    """Identité seule pour une lecture privée; aucune permission ou origine induite."""
    _exiger(type(coordonnees) is dict and len(coordonnees) == len(COORDONNEES))
    arguments = dict(coordonnees)
    _exiger(len(arguments) == len(COORDONNEES) and all(type(k) is str for k in arguments))
    _exiger(set(arguments) == set(COORDONNEES))
    for key, maximum in (("instance_id", 36), ("source_id", 64), ("compte_id", 64),
                         ("boite", 1024), ("uid_validity", 10)):
        _texte(arguments[key], maximum)
    try:
        canonical_instance = str(UUID(arguments["instance_id"]))
    except ValueError:
        raise ValueError(_ERREUR) from None
    _exiger(canonical_instance == arguments["instance_id"])
    _exiger(re.fullmatch("[0-9a-f]{64}", arguments["source_id"]) is not None)
    _exiger(re.fullmatch("[a-z0-9][a-z0-9_-]{0,63}", arguments["compte_id"]) is not None)
    _exiger(arguments["compte_id"] not in {"__proto__", "prototype", "constructor"})
    _exiger(re.fullmatch("[1-9][0-9]{0,9}", arguments["uid_validity"]) is not None)
    _exiger(int(arguments["uid_validity"]) <= _UID_MAX)
    _exiger(type(arguments["uid"]) is int and 1 <= arguments["uid"] <= _UID_MAX)
    identity = sha256(b"opsys:m1:courriel:identite:v1:")
    for value in (arguments["instance_id"], arguments["source_id"], arguments["compte_id"],
                  arguments["boite"], arguments["uid_validity"], str(arguments["uid"])):
        encoded = value.encode("utf-8")
        identity.update(str(len(encoded)).encode("ascii") + b":" + encoded)
    return identity.hexdigest()
