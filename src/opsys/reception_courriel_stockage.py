"""Originaux internes chiffrés; transaction possédée avant réponse, aucune surface Host.

Les callbacks privés obligatoires apportent l'autorité vivante et les clés externes.
Leur injection ne constitue pas une permission de canal déjà raccordée ou un fait M1.
"""
import json
import re
import secrets
from datetime import UTC, datetime
from types import MappingProxyType

from sqlalchemy import func, select

from . import etat, stockage
from .reception_courriel_contrat import COORDONNEES, identifier_source, valider_original
from .stockage.schema import OPSYS_INSTANCE
from .stockage.schema import RECEPTIONS_COURRIEL as RECEPTIONS

MAX_LIGNES = 4096
MAX_TOTAL = 128 * 1048576
_MAX_META = 16384
_MAX_CHIFFRE = 1048576 + _MAX_META + 4 + 16
_AAD = ("identite_id", "recu_id", "source_sha256", "taille_octets", "version_format",
        "enregistre_le", "cle_reference")


class Refus(ValueError):
    """Refus fermé interne, code sans contenu, coordonnées ou clé."""


def _coords(arguments):
    if type(arguments) is not dict:
        raise Refus("COORDONNEES-INVALIDES")
    captured = dict(arguments)
    identity = identifier_source(captured)
    return MappingProxyType(captured), identity


def _autoriser(cnx, coords, operation, callback):
    if (cnx is not stockage.connexion_courante() or cnx.dialect.name != "sqlite"
            or not cnx.in_transaction() or not callable(callback)):
        raise PermissionError("COURRIEL-AUTORITE-REFUSEE")
    try:
        result = callback(cnx, coords, operation)
    except Exception:
        raise PermissionError("COURRIEL-AUTORITE-REFUSEE") from None
    if (type(result) is not tuple or len(result) != 2 or any(type(x) is not str for x in result)
            or re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", result[0]) is None
            or re.fullmatch("[0-9a-f]{64}", result[1]) is None):
        raise PermissionError("COURRIEL-AUTORITE-REFUSEE")
    return result


def _instance(cnx, coords):
    current = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    if current != coords["instance_id"]:
        raise Refus("COURRIEL-INSTANCE-INCOHERENTE")


def _cle(provider, reference):
    try:
        value = provider(reference) if callable(provider) else None
    except Exception:
        raise Refus("COURRIEL-CLE-INDISPONIBLE") from None
    if (type(value) is not tuple or len(value) != 2 or type(value[0]) is not str
            or re.fullmatch("[0-9a-f]{32}", value[0]) is None
            or type(value[1]) is not bytes or len(value[1]) != 32
            or (reference is not None and value[0] != reference)):
        raise Refus("COURRIEL-CLE-INDISPONIBLE")
    return value


def _aes(cle):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise Refus("COURRIEL-CHIFFREMENT-INDISPONIBLE") from None
    return AESGCM(cle)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _aad(row):
    return b"opsys:m1:courriel:original:v1:" + _json({k: row[k] for k in _AAD})


def _quota(cnx):
    count, total, maximum = cnx.execute(select(func.count(), func.sum(func.length(RECEPTIONS.c.chiffre)),
                                              func.max(func.length(RECEPTIONS.c.chiffre)))).one()
    if count > MAX_LIGNES or (total or 0) > MAX_TOTAL or (maximum or 0) > _MAX_CHIFFRE:
        raise Refus("COURRIEL-QUOTA")
    return count, total or 0


def _ouvrir(row, provider):
    try:
        from cryptography.exceptions import InvalidTag
    except ImportError:
        raise Refus("COURRIEL-CHIFFREMENT-INDISPONIBLE") from None
    for name, pattern in (("identite_id", "[0-9a-f]{64}"), ("recu_id", "[0-9a-f]{32}"),
                          ("source_sha256", "[0-9a-f]{64}"), ("cle_reference", "[0-9a-f]{32}")):
        if type(row[name]) is not str or re.fullmatch(pattern, row[name]) is None:
            raise Refus("COURRIEL-ORIGINAL-CORROMPU")
    if (type(row["version_format"]) is not int or row["version_format"] != 1
            or type(row["taille_octets"]) is not int or not 1 <= row["taille_octets"] <= 1048576
            or type(row["enregistre_le"]) is not str or len(row["enregistre_le"]) != 24
            or type(row["nonce"]) is not bytes or len(row["nonce"]) != 12
            or type(row["chiffre"]) is not bytes or not 16 < len(row["chiffre"]) <= _MAX_CHIFFRE):
        raise Refus("COURRIEL-ORIGINAL-CORROMPU")
    _, cle = _cle(provider, row["cle_reference"])
    try:
        clear = _aes(cle).decrypt(row["nonce"], row["chiffre"], _aad(row))
        size = int.from_bytes(clear[:4], "big")
        if not 1 <= size <= _MAX_META or len(clear) != 4 + size + row["taille_octets"]:
            raise ValueError("frame")
        metadata = clear[4:4 + size]
        args = json.loads(metadata.decode("utf-8"))
        if _json(args) != metadata:
            raise ValueError("canonical")
        original = valider_original(args, source=clear[4 + size:])
        if (original.identite_id != row["identite_id"] or original.source_sha256 != row["source_sha256"]
                or original.source_octets != row["taille_octets"]):
            raise ValueError("binding")
    except (InvalidTag, ValueError, TypeError, UnicodeError, OverflowError):
        raise Refus("COURRIEL-ORIGINAL-CORROMPU") from None
    return original, cle


def _receipt(row):
    return dict(recu_id=row["recu_id"], identite_id=row["identite_id"], source_sha256=row["source_sha256"],
                taille_octets=row["taille_octets"], enregistre_le=row["enregistre_le"],
                statut="ORIGINAL_STOCKE_INTERNE")


def _finir(cnx, coords, operation, callback, expected, row, provider, cle, *, nouveau=False):
    reference, current_key = _cle(provider, None if nouveau else row["cle_reference"])
    if reference != row["cle_reference"] or not secrets.compare_digest(current_key, cle):
        raise Refus("COURRIEL-CLE-CHANGEE")
    if _autoriser(cnx, coords, operation, callback) != expected:
        raise PermissionError("COURRIEL-AUTORITE-CHANGEE")
    _instance(cnx, coords)
    # Bind the reply to actual persisted SQL, including trigger/callback effects.
    current = cnx.execute(select(RECEPTIONS).where(
        RECEPTIONS.c.identite_id == row["identite_id"])).mappings().one_or_none()
    if current is None or dict(current) != dict(row):
        raise Refus("COURRIEL-ORIGINAL-CORROMPU")
    _quota(cnx)


def recevoir(arguments: dict, *, source: bytes, autoriser, obtenir_cle) -> dict:
    """ACK interne après vrai commit; reçu historique seulement après autorité/déchiffrement."""
    if stockage.connexion_courante() is not None:
        raise Refus("COURRIEL-TRANSACTION-AMBIANTE")
    original = valider_original(arguments, source=source)
    coords, identity = _coords({k: original.arguments[k] for k in COORDONNEES})
    with stockage.transaction() as cnx:
        authority = _autoriser(cnx, coords, "recevoir", autoriser)
        _instance(cnx, coords)
        count, total = _quota(cnx)
        row = cnx.execute(select(RECEPTIONS).where(RECEPTIONS.c.identite_id == identity)).mappings().one_or_none()
        nouveau = row is None
        if row is not None:
            old, cle = _ouvrir(row, obtenir_cle)
            if old.source != original.source:
                raise Refus("COURRIEL-SOURCE-CONFLIT")
        else:
            reference, cle = _cle(obtenir_cle, None)
            metadata = _json(dict(original.arguments))
            if len(metadata) > _MAX_META:
                raise Refus("COURRIEL-METADONNEES-INVALIDE")
            clear = len(metadata).to_bytes(4, "big") + metadata + original.source
            row = dict(identite_id=identity, recu_id=secrets.token_hex(16), source_sha256=original.source_sha256,
                       taille_octets=original.source_octets, version_format=1,
                       enregistre_le=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                       cle_reference=reference, nonce=secrets.token_bytes(12))
            row["chiffre"] = _aes(cle).encrypt(row["nonce"], clear, _aad(row))
            if count >= MAX_LIGNES or total + len(row["chiffre"]) > MAX_TOTAL:
                raise Refus("COURRIEL-QUOTA")
            cnx.execute(RECEPTIONS.insert().values(**row))
            etat.journaliser(cnx, authority[0], "m1.original_courriel.stocker", row["recu_id"],
                            {"identite_id": identity, "source_sha256": original.source_sha256})
        receipt = _receipt(row)
        _finir(cnx, coords, "recevoir", autoriser, authority, row, obtenir_cle, cle, nouveau=nouveau)
    return receipt


def lire(coordonnees: dict, *, autoriser, obtenir_cle):
    """Lecture privée auditée; le futur Host doit fournir une autorité liée à ces coordonnées."""
    if stockage.connexion_courante() is not None:
        raise Refus("COURRIEL-TRANSACTION-AMBIANTE")
    coords, identity = _coords(coordonnees)
    with stockage.transaction() as cnx:
        authority = _autoriser(cnx, coords, "lire", autoriser)
        _instance(cnx, coords)
        _quota(cnx)
        row = cnx.execute(select(RECEPTIONS).where(RECEPTIONS.c.identite_id == identity)).mappings().one_or_none()
        if row is None:
            raise Refus("COURRIEL-INTROUVABLE")
        original, cle = _ouvrir(row, obtenir_cle)
        receipt = _receipt(row)
        etat.journaliser(cnx, authority[0], "m1.original_courriel.lire", row["recu_id"])
        _finir(cnx, coords, "lire", autoriser, authority, row, obtenir_cle, cle)
    return receipt, original
