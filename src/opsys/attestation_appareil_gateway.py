"""Attestation privée QA : génération locale, cache anti-rejeu et aucune écriture SQL."""

import base64
import dataclasses
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

_HEX = re.compile(r"[0-9a-f]{32}\Z")
_SAFE = re.compile(r"[A-Za-z0-9_.:@/+-]{1,256}\Z")
_ENV = "OPSYS_MCP_DEVICE_ATTESTATION_SECRET"
_CHEMIN = "/internal/opsys-device-generation"
_BORNE = 10000
_PID = None
_GENERATION = None
_ANCRE_MUR = None
_ANCRE_MONO = None
_VUS = {}
_BLOQUEES = set()
_LOCK = threading.Lock()


@dataclasses.dataclass(frozen=True)
class Attestation:
    appareil: str
    personne: str
    role: str
    outil: str
    wct_id: str
    nonce: str
    expire_epoch: float
    expire_mono: float
    generation: str
    cle_sha256: str


def _generation_sous_verrou():
    global _PID, _GENERATION, _ANCRE_MUR, _ANCRE_MONO, _VUS
    pid, mur, mono = os.getpid(), time.time(), time.monotonic()
    # Ancre fixe pour toute la génération : une dérive lente cumulée ne doit
    # pas contourner la détection d'un retour ou d'une avance murale.
    if (
        pid != _PID
        or _ANCRE_MUR is None
        or _ANCRE_MONO is None
        or mono < _ANCRE_MONO
        or abs((mur - _ANCRE_MUR) - (mono - _ANCRE_MONO)) > 2
    ):
        _PID, _GENERATION, _ANCRE_MUR, _ANCRE_MONO, _VUS = pid, secrets.token_hex(16), mur, mono, {}
    return _GENERATION


def generation():
    with _LOCK:
        return _generation_sous_verrou()


def _reinitialiser_apres_fork():
    global _PID, _GENERATION, _ANCRE_MUR, _ANCRE_MONO, _VUS, _LOCK
    _PID, _GENERATION, _ANCRE_MUR, _ANCRE_MONO, _VUS, _LOCK = None, None, None, None, {}, threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reinitialiser_apres_fork)


def interdire_secret(secret):
    if type(secret) is str and secret:
        _BLOQUEES.add(hashlib.sha256(secret.encode()).hexdigest())


def _cle():
    secret = os.environ.get(_ENV, "")
    if (
        type(secret) is not str
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret)
        or hashlib.sha256(secret.encode()).hexdigest() in _BLOQUEES
    ):
        return None
    return secret


def cle_est_valide(preuve):
    secret = _cle()
    return (
        type(preuve) is Attestation
        and secret is not None
        and hmac.compare_digest(preuve.cle_sha256, hashlib.sha256(secret.encode()).hexdigest())
        and preuve.generation == generation()
        and time.time() < preuve.expire_epoch
        and time.monotonic() < preuve.expire_mono
    )


def autoriser_generation(entete):
    secret = _cle()
    if secret is None or type(entete) is not str:
        return False
    attendu = hmac.new(secret.encode(), b"opsys.device.generation.v1", hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, entete)


def verifier(meta, outil, identite, arguments):
    """Admet une fois la preuve signée, liée au worker et au corps métier exact."""
    secret = _cle()
    if secret is None or type(meta) is not dict or identite is None or type(arguments) is not dict:
        return None
    if set(arguments) != {"wct_id", "coupure_utc"}:
        return None
    wct, coupure = arguments["wct_id"], arguments["coupure_utc"]
    if (
        type(wct) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", wct)
        or type(coupure) is not str
        or not _SAFE.fullmatch(coupure)
    ):
        return None
    valeur = meta.get("opsys/attestationAppareil")
    if type(valeur) is not str or len(valeur) > 2048 or valeur.count(".") != 1:
        return None
    contenu, signature = valeur.split(".")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", contenu) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return None
    attendu = hmac.new(secret.encode(), contenu.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(attendu, signature):
        return None
    try:
        raw = base64.b64decode(contenu + "=" * (-len(contenu) % 4), altchars=b"-_", validate=True)
        champs = json.loads(raw)
        if type(champs) is not list or len(champs) != 9:
            return None
        version, gen, appareil, personne, role, nom_outil, args_hash, emis_ms, nonce = champs
        corps = json.dumps([wct, coupure], ensure_ascii=False, separators=(",", ":")).encode()
        corps_hash = hashlib.sha256(corps).hexdigest()
        now_ms = int(time.time() * 1000)
        if (
            type(version) is not int
            or version != 1
            or type(gen) is not str
            or not _HEX.fullmatch(gen)
            or any(type(v) is not str or not _SAFE.fullmatch(v) for v in (appareil, personne, role, nom_outil))
            or type(emis_ms) is not int
            or type(nonce) is not str
            or not _HEX.fullmatch(nonce)
            or type(args_hash) is not str
            or not hmac.compare_digest(args_hash, corps_hash)
            or role != "admin"
            or personne != identite.personne
            or role != identite.role
            or nom_outil != outil
            or outil != "m3_lire_apprentissage_chantier"
            or emis_ms > now_ms + 2000
            or now_ms - emis_ms > 20000
        ):
            return None
        with _LOCK:
            if gen != _generation_sous_verrou():
                return None
            maintenant = time.monotonic()
            expires = [key for key, fin in _VUS.items() if fin <= maintenant]
            for key in expires:
                del _VUS[key]
            if nonce in _VUS or len(_VUS) >= _BORNE:
                return None
            _VUS[nonce] = maintenant + 22
            restant = min(20.0, max(0.0, (emis_ms + 20000 - now_ms) / 1000))
            if restant <= 0:
                return None
            expire_mono = maintenant + restant
        return Attestation(
            appareil,
            personne,
            role,
            nom_outil,
            wct,
            nonce,
            (emis_ms + 20000) / 1000,
            expire_mono,
            gen,
            hashlib.sha256(secret.encode()).hexdigest(),
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return None
