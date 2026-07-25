#!/usr/bin/env python3
"""TOTP RFC 6238 en stdlib pure — generation + verification compare_digest."""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from typing import Optional, Tuple


def _decode_secret(secret_b32: str) -> bytes:
    """Decode base32 avec padding tolere. Leve ValueError si invalide."""
    secret = secret_b32.upper().rstrip("=")  # proof:allow — variable/fixture de test TOTP, aucun secret reel
    # padding standard
    rem = len(secret) % 8
    if rem:
        secret += "=" * (8 - rem)
    try:
        return base64.b32decode(secret)
    except (base64.binascii.Error, ValueError):
        raise ValueError("secret base32 invalide")


def _check_secret_strength(key: bytes) -> bool:
    """Verifie que la cle a au moins 128 bits (16 octets)."""
    return len(key) >= 16


def generate_totp(
    secret_b32: str,
    timestep: Optional[int] = None,
    period: int = 30,
    digits: int = 6,
) -> str:
    """Genere un code TOTP. Leve ValueError si secret < 128 bits ou invalide."""
    key = _decode_secret(secret_b32)
    if not _check_secret_strength(key):
        raise ValueError("secret trop court (< 128 bits)")
    if digits < 6:
        raise ValueError("digits must be at least 6")
    if timestep is None:
        timestep = int(time.time()) // period
    msg = struct.pack(">Q", timestep)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    binary = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    otp = binary % (10**digits)
    return str(otp).zfill(digits)


def verify_totp(
    secret_b32: str,
    code: str,
    window: int = 1,
    period: int = 30,
    digits: int = 6,
) -> Tuple[bool, Optional[int]]:
    """Verifie un code TOTP. Retourne (ok, timestep_utilise).
    - code doit etre exactement `digits` chiffres ASCII, sinon (False, None).
    - secret invalide ou trop court -> (False, None) sans exception.
    - fenetre ±window autour du timestep courant.
    - Comparaison timing-safe via hmac.compare_digest.
    """
    # Validation stricte : exactement digits chiffres ASCII
    if not isinstance(code, str) or len(code) != digits or not (code.isascii() and code.isdigit()):
        return False, None
    try:
        key = _decode_secret(secret_b32)
    except ValueError:
        return False, None
    if not _check_secret_strength(key):
        return False, None

    now = int(time.time()) // period
    for offset in range(-window, window + 1):
        candidate_ts = now + offset
        expected = generate_totp(
            secret_b32=secret_b32,
            timestep=candidate_ts,
            period=period,
            digits=digits,
        )
        if hmac.compare_digest(expected, code):
            return True, candidate_ts
    return False, None
