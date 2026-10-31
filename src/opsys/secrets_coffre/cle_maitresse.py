"""Clé maîtresse du coffre : HORS de la base, jamais commitée, jamais journalisée.

Sources (exactement une, sinon refus explicite) :
- `OPSYS_COFFRE_CLE_FICHIER` : chemin ABSOLU d'un fichier ordinaire (pas un lien), propriété du compte courant,
  mode 0600, dossier parent non accessible en écriture aux autres, hors de tout dépôt Git ; contenu : la clé de
  32 octets en base64 (une ligne) ;
- `OPSYS_COFFRE_CLE` : la même clé en base64 dans l'environnement du serveur (jamais celui des agents).

`generer_fichier(chemin)` crée un tel fichier (O_EXCL, 0600) pour l'opérateur. L'empreinte publiée est un HMAC
de la clé : elle identifie la clé utilisée pour envelopper une version, sans rien révéler de la clé.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import hmac
import os
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path

from .erreurs import CoffreErreur

ENV_FICHIER = "OPSYS_COFFRE_CLE_FICHIER"
ENV_CLE = "OPSYS_COFFRE_CLE"
TAILLE_CLE = 32
_TAILLE_FICHIER_MAX = 256


@dataclasses.dataclass(frozen=True)
class CleMaitresse:
    empreinte: str
    kek: bytes = dataclasses.field(repr=False)

    def __repr__(self) -> str:  # jamais la clé, même en débogage
        return f"CleMaitresse(empreinte={self.empreinte!r})"


def _derivee(brute: bytes) -> CleMaitresse:
    """KEK séparée de la clé brute (HKDF-SHA256 à un bloc, RFC 5869) et empreinte publique HMAC."""
    prk = hmac.new(b"opsys-coffre/sel/v1", brute, hashlib.sha256).digest()
    kek = hmac.new(prk, b"opsys-coffre/kek/v1\x01", hashlib.sha256).digest()
    empreinte = hmac.new(brute, b"opsys-coffre/empreinte/v1", hashlib.sha256).hexdigest()[:32]
    return CleMaitresse(empreinte=empreinte, kek=kek)


def decoder(valeur: str) -> CleMaitresse:
    try:
        brute = base64.b64decode(valeur.strip().encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        brute = b""
    if len(brute) != TAILLE_CLE:
        raise CoffreErreur("COFFRE_CLE_MAITRESSE_INVALIDE", "clé maîtresse invalide : 32 octets en base64 attendus")
    return _derivee(brute)


def _dans_depot(chemin: Path) -> bool:
    return any((parent / ".git").exists() for parent in chemin.parents)


def _lire_fichier(nom: str) -> str:
    chemin = Path(nom)
    if not chemin.is_absolute() or "\n" in nom:
        raise CoffreErreur("COFFRE_FICHIER_CLE_INVALIDE", "OPSYS_COFFRE_CLE_FICHIER : chemin absolu requis")
    if _dans_depot(chemin):
        raise CoffreErreur("COFFRE_CLE_DANS_DEPOT", "fichier de clé maîtresse dans un dépôt Git : refusé")
    try:
        descripteur = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        raise CoffreErreur("COFFRE_CLE_MAITRESSE_ABSENTE", "fichier de clé maîtresse introuvable") from None
    except OSError:
        raise CoffreErreur("COFFRE_FICHIER_CLE_INVALIDE", "fichier de clé maîtresse illisible ou lien") from None
    try:
        etat = os.fstat(descripteur)
        if not stat.S_ISREG(etat.st_mode) or etat.st_size > _TAILLE_FICHIER_MAX:
            raise CoffreErreur("COFFRE_FICHIER_CLE_INVALIDE", "fichier de clé maîtresse : fichier ordinaire attendu")
        if os.name != "nt":
            parent = chemin.parent.stat()
            if (etat.st_uid != os.geteuid() or stat.S_IMODE(etat.st_mode) != 0o600
                    or stat.S_IMODE(parent.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)):
                raise CoffreErreur("COFFRE_FICHIER_CLE_PERMISSIONS",
                                   "fichier de clé maîtresse : propriétaire courant, mode 0600 et dossier privé requis")
        return os.read(descripteur, _TAILLE_FICHIER_MAX + 1).decode("ascii")
    except UnicodeDecodeError:
        raise CoffreErreur("COFFRE_CLE_MAITRESSE_INVALIDE", "clé maîtresse invalide") from None
    finally:
        os.close(descripteur)


def charger(environ: Mapping[str, str] | None = None) -> CleMaitresse:
    env = os.environ if environ is None else environ
    fichier, valeur = env.get(ENV_FICHIER, ""), env.get(ENV_CLE, "")
    if fichier and valeur:
        raise CoffreErreur("COFFRE_CLE_CONFLIT", "OPSYS_COFFRE_CLE_FICHIER et OPSYS_COFFRE_CLE : une seule source")
    if not fichier and not valeur:
        raise CoffreErreur("COFFRE_CLE_MAITRESSE_ABSENTE",
                           "clé maîtresse absente : définir OPSYS_COFFRE_CLE_FICHIER (recommandé) ou OPSYS_COFFRE_CLE")
    return decoder(_lire_fichier(fichier) if fichier else valeur)


def generer_fichier(chemin: Path) -> CleMaitresse:
    """Crée un fichier de clé neuve (jamais d'écrasement) et rend seulement son empreinte."""
    chemin = Path(chemin)
    if not chemin.is_absolute():
        raise CoffreErreur("COFFRE_FICHIER_CLE_INVALIDE", "chemin absolu requis")
    if _dans_depot(chemin):
        raise CoffreErreur("COFFRE_CLE_DANS_DEPOT", "fichier de clé maîtresse dans un dépôt Git : refusé")
    contenu = base64.b64encode(secrets.token_bytes(TAILLE_CLE))
    try:
        descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        raise CoffreErreur("COFFRE_FICHIER_CLE_EXISTE", "le fichier existe déjà : aucun écrasement") from None
    try:
        os.write(descripteur, contenu + b"\n")
    finally:
        os.close(descripteur)
    return decoder(contenu.decode("ascii"))
