"""Chiffrement au repos des contenus d'onboarding (AES-256-GCM), avec la clé externe du pilote Fusion.

Réutilise tel quel le protocole de clé de `opsys.fusion_csv` (variable `OPSYS_INGESTION_CLE`, ou le nom référencé
par `OPSYS_INGESTION_CLE_REFERENCE`, ou le fichier privé `OPSYS_INGESTION_ENV_FILE`) : aucune clé n'est créée ni
conservée en base, seule la RÉFÉRENCE de la clé est retenue par le lot. L'AAD lie chaque chiffré à sa nature, à son
identifiant et à l'empreinte de sa source : un chiffré déplacé d'une ligne à une autre ne se déchiffre pas.
"""

from __future__ import annotations

import base64
import json
import secrets
from typing import Any

from .. import fusion_csv
from .codes import IngestionErreur

VERSION_FORMAT = 1
_PREFIXE = "opsys-ingestion-onboarding"


def reference_cle() -> str:
    """La référence de la clé active ; refus typé si la configuration de clé est invalide."""
    try:
        reference = fusion_csv._reference_cle()
        fusion_csv._cle(reference)
    except fusion_csv.FusionErreur as exc:
        raise IngestionErreur("REJ-ING-CLE-INDISPONIBLE", f"clé de chiffrement d'ingestion indisponible ({exc.code}) "
                              ": fournir OPSYS_INGESTION_CLE (32 octets en base64) côté serveur", 503) from None
    return reference


def _cle(reference: str) -> bytes:
    try:
        return fusion_csv._cle(reference)
    except fusion_csv.FusionErreur as exc:
        raise IngestionErreur("REJ-ING-CLE-INDISPONIBLE", f"clé {reference} indisponible ({exc.code})", 503) from None


def _aesgcm():
    try:
        return fusion_csv._aesgcm()
    except fusion_csv.FusionErreur:
        raise IngestionErreur("REJ-ING-CHIFFREMENT-INDISPONIBLE", "installer l'extra OPSYS « ingestion » "
                              "(cryptography) pour chiffrer les contenus", 503) from None


def _aad(nature: str, identifiant: str, empreinte: str) -> bytes:
    return f"{_PREFIXE}:v{VERSION_FORMAT}:{nature}:{identifiant}:{empreinte}".encode("ascii")


def sceller(reference: str, nature: str, identifiant: str, empreinte: str, contenu: bytes) -> tuple[str, str]:
    nonce = secrets.token_bytes(12)
    chiffre = _aesgcm()(_cle(reference)).encrypt(nonce, contenu, _aad(nature, identifiant, empreinte))
    return base64.b64encode(nonce).decode("ascii"), base64.b64encode(chiffre).decode("ascii")


def ouvrir(reference: str, nature: str, identifiant: str, empreinte: str, nonce: str, chiffre: str) -> bytes:
    aesgcm = _aesgcm()
    try:
        from cryptography.exceptions import InvalidTag
    except ImportError:
        raise IngestionErreur("REJ-ING-CHIFFREMENT-INDISPONIBLE", "primitive de déchiffrement indisponible",
                              503) from None
    try:
        return aesgcm(_cle(reference)).decrypt(base64.b64decode(nonce, validate=True),
                                               base64.b64decode(chiffre, validate=True),
                                               _aad(nature, identifiant, empreinte))
    except (InvalidTag, ValueError, TypeError):
        raise IngestionErreur("REJ-ING-CONTENU-CORROMPU", f"contenu chiffré ({nature}) corrompu ou clé différente : "
                              "lecture refusée", 409) from None


def json_canonique(valeur: Any) -> bytes:
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sceller_json(reference: str, nature: str, identifiant: str, empreinte: str, valeur: Any) -> tuple[str, str]:
    return sceller(reference, nature, identifiant, empreinte, json_canonique(valeur))


def ouvrir_json(reference: str, nature: str, identifiant: str, empreinte: str, nonce: str, chiffre: str) -> Any:
    return json.loads(ouvrir(reference, nature, identifiant, empreinte, nonce, chiffre).decode("utf-8"))


__all__ = ["VERSION_FORMAT", "json_canonique", "ouvrir", "ouvrir_json", "reference_cle", "sceller", "sceller_json"]
