"""Clé locale de l'observabilité : une seule graine par instance, des sous-clés dérivées par usage.

Servent trois usages, séparés par dérivation (HMAC-SHA256 avec un nom d'usage distinct) pour qu'aucun jeton ne puisse
être rejoué d'un usage à l'autre :
- `pii/v1` : jetons stables du masquage des renseignements personnels (`pii`) ;
- `traces/chaine/v1` : chaîne d'intégrité du journal de traces (`traces`) ;
- `mcp/registre/v1` : sceau HMAC du registre MCP (`opsys.registre_mcp`).

La graine vit HORS de la base et hors du dépôt : `<OPSYS_HOME>/observabilite/cle-locale` (mode 0600, dossier 0700),
ou le fichier désigné par `OPSYS_OBS_CLE_FICHIER`. Elle est créée une seule fois (`O_EXCL`), jamais journalisée, jamais
rendue par un `repr`. Perdre la graine ne perd aucune donnée métier : les jetons changent (la corrélation avec
l'historique est rompue) et la chaîne du journal ne se vérifie plus (`REJ-OBS-JOURNAL-ALTERE`).

Limite : un processus qui lit ce fichier (même compte système) peut forger un jeton ou un sceau. Ce n'est pas un
coffre : pour une séparation des privilèges, mettre le sceau du registre sous une clé que l'agent ne lit pas.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import stat
from pathlib import Path

from .erreurs import ErreurObservabilite

ENV_CLE_FICHIER = "OPSYS_OBS_CLE_FICHIER"
TAILLE_GRAINE = 32
_TAILLE_FICHIER_MAX = 256
USAGES = ("pii/v1", "traces/chaine/v1", "mcp/registre/v1")


def chemin_par_defaut() -> Path:
    from ..stockage.moteur import dossier_opsys

    env = os.environ.get(ENV_CLE_FICHIER, "").strip()
    return Path(env) if env else dossier_opsys() / "observabilite" / "cle-locale"


def _lire(chemin: Path) -> bytes:
    try:
        descripteur = os.open(chemin, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        raise ErreurObservabilite("REJ-OBS-CLE-ABSENTE", "clé locale d'observabilité introuvable") from None
    except OSError:
        raise ErreurObservabilite("REJ-OBS-CLE-INVALIDE", "clé locale illisible ou lien symbolique") from None
    try:
        etat = os.fstat(descripteur)
        if not stat.S_ISREG(etat.st_mode) or etat.st_size > _TAILLE_FICHIER_MAX:
            raise ErreurObservabilite("REJ-OBS-CLE-INVALIDE", "clé locale : fichier ordinaire attendu")
        if os.name != "nt" and (etat.st_uid != os.geteuid() or stat.S_IMODE(etat.st_mode) != 0o600):
            raise ErreurObservabilite("REJ-OBS-CLE-PERMISSIONS",
                                      "clé locale : propriétaire courant et mode 0600 requis")
        brut = os.read(descripteur, _TAILLE_FICHIER_MAX + 1)
    finally:
        os.close(descripteur)
    try:
        graine = base64.b64decode(brut.strip(), validate=True)
    except (binascii.Error, ValueError):
        graine = b""
    if len(graine) != TAILLE_GRAINE:
        raise ErreurObservabilite("REJ-OBS-CLE-INVALIDE", "clé locale : 32 octets en base64 attendus")
    return graine


def charger(chemin: Path | None = None, *, creer: bool = False) -> bytes:
    """Rend la graine. Avec `creer`, la crée si le fichier est absent (jamais d'écrasement, jamais de lien suivi)."""
    chemin = Path(chemin) if chemin is not None else chemin_par_defaut()
    try:
        return _lire(chemin)
    except ErreurObservabilite as exc:
        if exc.code != "REJ-OBS-CLE-ABSENTE" or not creer:
            raise
    chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    contenu = base64.b64encode(secrets.token_bytes(TAILLE_GRAINE)) + b"\n"
    try:
        descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:  # course avec un autre processus : on relit la graine gagnante
        return _lire(chemin)
    try:
        os.write(descripteur, contenu)
    finally:
        os.close(descripteur)
    return _lire(chemin)


def deriver(graine: bytes, usage: str) -> bytes:
    """Sous-clé de 32 octets pour un usage nommé (catalogue fermé `USAGES`)."""
    if usage not in USAGES:
        raise ErreurObservabilite("REJ-OBS-ARGUMENT-INVALIDE", f"usage de clé inconnu (attendu : {', '.join(USAGES)})")
    if not isinstance(graine, bytes) or len(graine) != TAILLE_GRAINE:
        raise ErreurObservabilite("REJ-OBS-CLE-INVALIDE", "graine invalide : 32 octets attendus")
    return hmac.new(graine, b"opsys-observabilite/" + usage.encode("ascii"), hashlib.sha256).digest()
