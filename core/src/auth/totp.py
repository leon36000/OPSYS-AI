#!/usr/bin/env python3
"""Implémentation minimale TOTP compatible RFC 6238."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import time
from typing import Optional, Tuple


def _decoder_secret(secret_b32: str) -> bytes:
    """Décode un secret Base32 en refusant les valeurs invalides."""
    try:
        return base64.b32decode(secret_b32.upper(), casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Secret TOTP Base32 invalide") from exc


def generer_totp(secret_b32: str, timestep: Optional[int] = None, digits: int = 6) -> str:
    """Génère un code TOTP pour un pas de temps donné."""
    if timestep is None:
        timestep = int(time.time()) // 30

    secret = _decoder_secret(secret_b32)  # proof:allow — nom de variable locale (résultat du décodage), aucun secret littéral
    message = struct.pack(">Q", timestep)
    digest = hmac.new(secret, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    valeur = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(valeur % (10**digits)).zfill(digits)


def verify_totp(secret_b32: str, code: str, window: int = 1) -> Tuple[bool, Optional[int]]:
    """Vérifie un code TOTP et retourne le pas consommable si valide."""
    if not code.isdigit() or len(code) != 6:
        return False, None

    timestep_courant = int(time.time()) // 30
    for decalage in range(-window, window + 1):
        timestep = timestep_courant + decalage
        attendu = generer_totp(secret_b32, timestep)
        if hmac.compare_digest(attendu, code):
            return True, timestep
    return False, None
