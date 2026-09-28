"""Sécurité de la console : configuration, mot de passe, session signée, jeton CSRF.

Bibliothèque standard uniquement (hmac, hashlib, secrets) : chaque règle se teste sans serveur.

- Un mot de passe administrateur (OPSYS_CONSOLE_MOT_DE_PASSE), comparé à temps constant.
- Une session sans état côté serveur : cookie `charge.signature`, signé HMAC-SHA256 avec
  OPSYS_CONSOLE_SECRET. Il porte le nom du signataire, un jeton CSRF et une échéance. Changer le
  secret ferme toutes les sessions.
- Le nom saisi à la connexion signe chaque écriture : décisions, modes, paliers.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Mapping

NOM_COOKIE = "opsys_session"
DUREE_SESSION = 8 * 3600  # secondes : une journée de travail, puis reconnexion
PREFIXE_DEFAUT = "/opsys"  # chemin de la console derrière Caddy (voir docs/architecture/ARCHITECTURE.md)
LONGUEUR_MIN_MOT_DE_PASSE = 12
LONGUEUR_MIN_SECRET = 32
LONGUEUR_MAX_NOM = 80
_CONTEXTE = b"opsys-console/session/v1:"
_PREFIXE = re.compile(r"^(/[A-Za-z0-9_-]+)*$")


@dataclasses.dataclass(frozen=True)
class Configuration:
    """Réglages de la console. Sans secrets solides, elle refuse de démarrer (ValueError)."""

    mot_de_passe: str = dataclasses.field(repr=False)
    secret: str = dataclasses.field(repr=False)
    cookie_securise: bool = True
    prefixe: str = PREFIXE_DEFAUT
    duree_session: int = DUREE_SESSION

    def __post_init__(self) -> None:
        if len(self.mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
            raise ValueError(f"OPSYS_CONSOLE_MOT_DE_PASSE requis : {LONGUEUR_MIN_MOT_DE_PASSE} caractères minimum")
        if len(self.secret) < LONGUEUR_MIN_SECRET:
            raise ValueError(
                f"OPSYS_CONSOLE_SECRET requis : {LONGUEUR_MIN_SECRET} caractères minimum "
                '(par exemple : python -c "import secrets; print(secrets.token_hex(32))")'
            )
        if self.secret == self.mot_de_passe:
            raise ValueError("OPSYS_CONSOLE_SECRET doit différer du mot de passe")
        if not _PREFIXE.match(self.prefixe):
            raise ValueError(f"OPSYS_CONSOLE_PREFIXE invalide {self.prefixe!r} : vide, ou un chemin comme /opsys")
        if self.duree_session <= 0:
            raise ValueError("la durée de session doit être positive")

    @classmethod
    def depuis_environnement(cls, environ: Mapping[str, str]) -> Configuration:
        securise = environ.get("OPSYS_CONSOLE_COOKIE_SECURISE", "1").strip()
        if securise not in ("0", "1"):
            raise ValueError(
                "OPSYS_CONSOLE_COOKIE_SECURISE vaut 1 (défaut, derrière TLS) ou 0 (poste local sans TLS)"
            )
        return cls(
            mot_de_passe=environ.get("OPSYS_CONSOLE_MOT_DE_PASSE", ""),
            secret=environ.get("OPSYS_CONSOLE_SECRET", ""),
            cookie_securise=securise == "1",
            prefixe=environ.get("OPSYS_CONSOLE_PREFIXE", PREFIXE_DEFAUT).strip().rstrip("/"),
        )


@dataclasses.dataclass(frozen=True)
class Session:
    utilisateur: str
    csrf: str = dataclasses.field(repr=False)
    expire: int


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def _signature(donnees: str, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), _CONTEXTE + donnees.encode("utf-8"), hashlib.sha256).digest()


def _empreinte(texte: str) -> bytes:
    return hashlib.sha256(texte.encode("utf-8")).digest()


def mot_de_passe_valide(fourni: str, attendu: str) -> bool:
    """Compare les empreintes à temps constant : ni le contenu ni la longueur ne fuient."""
    return hmac.compare_digest(_empreinte(fourni), _empreinte(attendu))


def valider_nom(nom: str) -> str:
    """Nom du signataire : espaces normalisés, non vide, court, sans caractère de contrôle."""
    propre = " ".join(str(nom).split())
    if not propre:
        raise ValueError("indiquez votre nom : il signe chaque décision")
    if len(propre) > LONGUEUR_MAX_NOM:
        raise ValueError(f"nom trop long ({LONGUEUR_MAX_NOM} caractères maximum)")
    if not propre.isprintable():
        raise ValueError("nom invalide : caractères de contrôle interdits")
    return propre


def ouvrir_session(utilisateur: str, duree: int = DUREE_SESSION, maintenant: float | None = None) -> Session:
    instant = int(time.time() if maintenant is None else maintenant)
    return Session(utilisateur=valider_nom(utilisateur), csrf=secrets.token_urlsafe(32), expire=instant + duree)


def signer_session(session: Session, secret: str) -> str:
    charge = json.dumps(
        {"u": session.utilisateur, "c": session.csrf, "x": session.expire}, ensure_ascii=False, separators=(",", ":")
    )
    donnees = _b64(charge.encode("utf-8"))
    return f"{donnees}.{_b64(_signature(donnees, secret))}"


def lire_session(valeur: str | None, secret: str, maintenant: float | None = None) -> Session | None:
    """Session portée par le cookie ; None s'il est absent, falsifié, mal formé ou expiré."""
    if not valeur or valeur.count(".") != 1:
        return None
    donnees, signature = valeur.split(".")
    if not hmac.compare_digest(_b64(_signature(donnees, secret)).encode("ascii"), signature.encode("utf-8")):
        return None
    try:
        charge = json.loads(base64.urlsafe_b64decode(donnees + "=" * (-len(donnees) % 4)))
    except ValueError:
        return None
    if not isinstance(charge, dict):
        return None
    utilisateur, csrf, expire = charge.get("u"), charge.get("c"), charge.get("x")
    if not (isinstance(utilisateur, str) and utilisateur and isinstance(csrf, str) and csrf
            and isinstance(expire, int) and not isinstance(expire, bool)):
        return None
    if expire <= (time.time() if maintenant is None else maintenant):
        return None
    return Session(utilisateur=utilisateur, csrf=csrf, expire=expire)


def csrf_valide(fourni: str | None, session: Session) -> bool:
    """Jeton du formulaire (ou de l'en-tête X-CSRF-Token) égal à celui de la session."""
    return bool(fourni) and hmac.compare_digest(fourni.encode("utf-8"), session.csrf.encode("utf-8"))
