"""Conservation chiffrée d'un enregistrement vocal ou de sa transcription, avec rétention de 1 à 90 jours.

Le contrat de session (`opsys.avatars_voix.session`) ne conserve rien : il dit seulement `conservation()` (audio,
transcription, durée, purge demandée) et le worker futur devra l'exécuter. Ce module est cette exécution, prête pour le
worker : AUCUN enregistrement n'existe tant qu'aucun worker n'appelle `conserver` (aucun n'est livré).

- une clé AES-256-GCM PAR session et par portée (`audio`, `transcription`), dans `cles_chiffrement` ;
- le chiffré vit dans un fichier privé (0600) sous `<OPSYS_HOME>/voix/` ; son nom est un pseudonyme ;
- l'échéance est inscrite dans `retention_echeances` ; à l'échéance, l'exécuteur `retention.cles` du planificateur
  détruit la clé (crypto-effacement) et le fichier ;
- le retrait du consentement (`retirer`) est un droit de la personne, IMMÉDIAT : il détruit la clé et le fichier tout de
  suite, sans attendre le planificateur.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from sqlalchemy import Connection

from .. import cles_chiffrement, stockage
from . import echeances

PORTEES = ("audio", "transcription")
RETENTION_MIN_JOURS, RETENTION_MAX_JOURS = 1, 90
OCTETS_MAX = 64 * 1024 * 1024
_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{5,63}$")
_VERSION = b"OPSYSVX1"


def dossier() -> Path:
    return stockage.dossier_opsys() / "voix"


def _identifiant(session_id: str, portee: str) -> str:
    if not isinstance(session_id, str) or not _SESSION.fullmatch(session_id) or portee not in PORTEES:
        raise echeances.RetentionRefusee("REJ-VOIX-ARGUMENT-INVALIDE", "session et portée (audio, transcription)")
    return f"{session_id}/{portee}"


def reference(session_id: str, portee: str) -> str:
    """Le pseudonyme (ref d'échéance et nom de fichier) : jamais l'identifiant de session lui-même."""
    return hashlib.sha256(_identifiant(session_id, portee).encode()).hexdigest()[:40]


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise echeances.RetentionRefusee("REJ-VOIX-CHIFFREMENT-INDISPONIBLE", "extra « ingestion » requis") from None
    return AESGCM


def _aad(identifiant: str) -> bytes:
    return b"opsys-voix:v1:" + identifiant.encode()


def chemin(session_id: str, portee: str, racine: Path | None = None) -> Path:
    return (racine or dossier()) / f"{reference(session_id, portee)}.enc"


def conserver(cnx: Connection, *, session_id: str, portee: str, octets: bytes, retention_jours: int,
              maintenant_epoch: int, racine: Path | None = None) -> dict[str, object]:
    """Chiffre et conserve, inscrit l'échéance. Refus typés : consentement d'enregistrement non valide (rétention hors
    1 à 90 jours), contenu vide ou trop gros, déjà conservé (jamais d'écrasement)."""
    identifiant = _identifiant(session_id, portee)
    if type(retention_jours) is not int or not RETENTION_MIN_JOURS <= retention_jours <= RETENTION_MAX_JOURS:
        raise echeances.RetentionRefusee("REJ-VOIX-RETENTION-INVALIDE", "rétention de 1 à 90 jours")
    if not isinstance(octets, bytes) or not 0 < len(octets) <= OCTETS_MAX:
        raise echeances.RetentionRefusee("REJ-VOIX-CONTENU-INVALIDE", "octets non vides, 64 Mio au plus")
    cible = chemin(session_id, portee, racine)
    if cible.exists():
        raise echeances.RetentionRefusee("REJ-VOIX-DEJA-CONSERVE", "cet enregistrement existe déjà")
    quand = echeances.instant(maintenant_epoch)
    cle = cles_chiffrement.obtenir_ou_creer(cnx, echeances.PORTEE_VOIX, identifiant, quand)
    nonce = os.urandom(12)
    chiffre = _aesgcm()(cle).encrypt(nonce, octets, _aad(identifiant))
    cible.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descripteur = os.open(cible, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descripteur, "wb") as flux:
        flux.write(_VERSION + nonce + chiffre)
        flux.flush()
        os.fsync(flux.fileno())
    echeances.enregistrer(cnx, "voix", reference(session_id, portee), identifiant,
                          maintenant_epoch + retention_jours * 86400, quand)
    return {"ref": reference(session_id, portee), "echeance_epoch": maintenant_epoch + retention_jours * 86400}


def lire(cnx: Connection, *, session_id: str, portee: str, racine: Path | None = None) -> bytes:
    identifiant = _identifiant(session_id, portee)
    cle = cles_chiffrement.lire(cnx, echeances.PORTEE_VOIX, identifiant)
    if cle is None:
        raise echeances.RetentionRefusee("REJ-VOIX-ENREGISTREMENT-PURGE", "la clé a été détruite : contenu illisible")
    brut = chemin(session_id, portee, racine).read_bytes()
    if not brut.startswith(_VERSION) or len(brut) < len(_VERSION) + 12 + 16:
        raise echeances.RetentionRefusee("REJ-VOIX-ENREGISTREMENT-ALTERE", "format inattendu")
    nonce, chiffre = brut[len(_VERSION):len(_VERSION) + 12], brut[len(_VERSION) + 12:]
    try:
        return _aesgcm()(cle).decrypt(nonce, chiffre, _aad(identifiant))
    except Exception:  # noqa: BLE001 — InvalidTag : altéré ou déplacé
        raise echeances.RetentionRefusee("REJ-VOIX-ENREGISTREMENT-ALTERE", "authentification échouée") from None


def effacer_fichier(session_id: str, portee: str, racine: Path | None = None) -> bool:
    """Écrase puis retire le fichier chiffré (le chiffré n'a de sens qu'avec la clé, déjà détruite : défense en
    profondeur). Rend vrai si un fichier existait."""
    cible = chemin(session_id, portee, racine)
    if not cible.is_file() or cible.is_symlink():
        return False
    taille = cible.stat().st_size
    with cible.open("r+b") as flux:
        flux.write(b"\0" * taille)
        flux.flush()
        os.fsync(flux.fileno())
    cible.unlink()
    return True


def retirer(cnx: Connection, *, session_id: str, portee: str, maintenant_epoch: int,
            racine: Path | None = None) -> dict[str, object]:
    """Retrait du consentement d'enregistrement : la clé et le fichier sont détruits tout de suite. Rejouable."""
    ref = reference(session_id, portee)  # valide aussi session et portée
    quand = echeances.instant(maintenant_epoch)
    from sqlalchemy import select

    from ..stockage.schema import RETENTION_ECHEANCES

    ligne = cnx.execute(select(RETENTION_ECHEANCES).where(
        RETENTION_ECHEANCES.c.domaine == "voix", RETENTION_ECHEANCES.c.ref == ref)).mappings().first()
    if ligne is None:
        raise echeances.RetentionRefusee("REJ-VOIX-INCONNU", "aucun enregistrement conservé pour cette session")
    purge_id = echeances.detruire(cnx, dict(ligne), quand) if ligne["statut"] == "en_attente" else None
    existait = effacer_fichier(session_id, portee, racine)
    return {"ref": ref, "purge_id": purge_id, "fichier_efface": existait}


__all__ = ["PORTEES", "chemin", "conserver", "dossier", "effacer_fichier", "lire", "reference", "retirer"]
