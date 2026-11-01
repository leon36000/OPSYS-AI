"""Sauvegarde chiffrée de l'instance locale : export + AES-256-GCM, clé HORS de la sauvegarde, restauration vérifiée.

Pourquoi : `opsys-metier instance exporter` écrit une archive en clair (0600). Elle contient les renseignements
personnels et les clés de chiffrement destructibles de la base (voir `opsys.exportation`) ; elle ne doit jamais
quitter le serveur sans être chiffrée. Ce module ajoute la couche manquante, avec des refus TYPÉS
(`REJ-SAUVEGARDE-…`, un code de sortie par refus) et sans jamais écrire un fichier final à moitié bon.

Politique de clé (docs/qualification/QUALIFICATION-CONTENEUR.md) :
- la clé (32 octets aléatoires, base64, une ligne) vit dans un fichier 0600, propriété du compte courant, dans un
  dossier privé, nommé par `OPSYS_SAUVEGARDE_CLE_FICHIER` ; elle est distincte de la clé maîtresse du coffre ;
- elle n'est JAMAIS dans la sauvegarde, ni dans le dossier des sauvegardes, ni dans le dossier de l'instance
  (refus nommés) ; la perdre rend les sauvegardes illisibles : la copier hors du serveur est une décision humaine (T3) ;
- l'empreinte publique de la clé (`cle_id`, HMAC tronqué) est écrite dans l'en-tête : une mauvaise clé est reconnue
  AVANT tout déchiffrement et se distingue d'une archive altérée.

Format `OPSYSBK1` : en-tête (magic, version, taille de bloc, cle_id, sel) puis des blocs AES-256-GCM indépendants.
Chaque bloc est authentifié avec l'en-tête et un drapeau « dernier bloc » ; le nonce porte le rang du bloc. Un bloc
retiré, ajouté, réordonné, une archive tronquée à une frontière de bloc ou un octet modifié sont donc refusés. Clé de
bloc dérivée de la clé et du sel (HKDF-SHA256, RFC 5869).

La restauration déchiffre vers un dossier privé 0700, ne passe à `exportation.restaurer` (empreintes, membres,
intégrité SQLite, révision de migration, rien écrasé sans `--remplacer`) qu'une archive entièrement authentifiée,
puis retire ses copies temporaires. La rétention ne SUPPRIME jamais : elle met de côté (`a-detruire/`) ; la
destruction est humaine.

CLI : `python -m opsys.sauvegarde_chiffree {generer-cle|sauvegarder|verifier|restaurer|retention}`.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import datetime as dt
import errno
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import struct
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from . import exportation

ENV_CLE_FICHIER = "OPSYS_SAUVEGARDE_CLE_FICHIER"
MAGIC = b"OPSYSBK1"
VERSION_FORMAT = 1
TAILLE_BLOC = 1024 * 1024
TAILLE_BLOC_MAX = 16 * 1024 * 1024
TAILLE_CLE = 32
_TAILLE_ENTETE = len(MAGIC) + 1 + 4 + 16 + 16
_ETIQUETTE = 16
_SUFFIXE = ".tar.gz.enc"
_NOM_SAUVEGARDE = re.compile(r"^opsys-sauvegarde-(\d{8}T\d{6}Z)-[0-9a-f]{4}\.tar\.gz\.enc$")
DOSSIER_A_DETRUIRE = "a-detruire"

# Un refus = un code stable = un code de sortie. 0 réussite, 1 erreur imprévue, 2 usage.
CODES_SORTIE: dict[str, int] = {
    "REJ-SAUVEGARDE-CLE-ABSENTE": 10,
    "REJ-SAUVEGARDE-CLE-INVALIDE": 11,
    "REJ-SAUVEGARDE-CLE-PERMISSIONS": 12,
    "REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE": 13,
    "REJ-SAUVEGARDE-MAUVAISE-CLE": 14,
    "REJ-SAUVEGARDE-ALTEREE": 15,
    "REJ-SAUVEGARDE-TRONQUEE": 16,
    "REJ-SAUVEGARDE-FORMAT": 17,
    "REJ-SAUVEGARDE-VERSION-FORMAT": 18,
    "REJ-SAUVEGARDE-DISQUE-PLEIN": 19,
    "REJ-SAUVEGARDE-DEPENDANCE": 20,
    "REJ-SAUVEGARDE-RETENTION": 21,
    "REJ-SAUVEGARDE-ES": 22,
    "REJ-SAUVEGARDE-EXPORT": 23,
    "REJ-SAUVEGARDE-RESTAURATION": 24,
    "REJ-SAUVEGARDE-VERSION-LOGICIEL": 25,
    "REJ-SAUVEGARDE-BASE-CORROMPUE": 26,
}


class ErreurSauvegarde(Exception):
    """Refus typé : `code` est stable (`REJ-SAUVEGARDE-…`), le message dit quoi faire."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code} : {self.message}"


# -- clé ----------------------------------------------------------------------------------------------------------

def _empreinte_cle(cle: bytes) -> bytes:
    return hmac.new(cle, b"opsys-sauvegarde/empreinte/v1", hashlib.sha256).digest()[:16]


def _cle_de_bloc(cle: bytes, sel: bytes) -> bytes:
    prk = hmac.new(sel, cle, hashlib.sha256).digest()
    return hmac.new(prk, b"opsys-sauvegarde/aes256gcm/v1\x01", hashlib.sha256).digest()


def generer_cle(chemin: Path) -> str:
    """Crée un fichier de clé neuf (O_EXCL, 0600, jamais d'écrasement) et rend seulement son `cle_id` hexadécimal."""
    chemin = Path(chemin)
    if not chemin.is_absolute():
        raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-INVALIDE", "chemin absolu requis pour le fichier de clé.")
    brute = secrets.token_bytes(TAILLE_CLE)
    try:
        descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-INVALIDE",
                               "le fichier de clé existe déjà : aucun écrasement.") from None
    except OSError as erreur:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-ES", f"fichier de clé non créé ({erreur.strerror}).") from None
    try:
        os.write(descripteur, base64.b64encode(brute) + b"\n")
    finally:
        os.close(descripteur)
    return _empreinte_cle(brute).hex()


def lire_cle(environ: Mapping[str, str] | None = None) -> bytes:
    """Clé de sauvegarde : fichier ordinaire (pas un lien), propriétaire courant, mode 0600, dossier privé."""
    env = os.environ if environ is None else environ
    nom = env.get(ENV_CLE_FICHIER, "")
    if not nom:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-ABSENTE",
                               f"clé de sauvegarde absente : définir {ENV_CLE_FICHIER} (générer-cle).")
    chemin = Path(nom)
    if not chemin.is_absolute() or "\n" in nom:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-INVALIDE", f"{ENV_CLE_FICHIER} : chemin absolu requis.")
    try:
        descripteur = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-ABSENTE", "fichier de clé de sauvegarde introuvable.") from None
    except OSError:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-INVALIDE", "fichier de clé illisible ou lien symbolique.") from None
    try:
        infos = os.fstat(descripteur)
        if not stat.S_ISREG(infos.st_mode) or infos.st_size > 256:
            raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-INVALIDE", "fichier de clé : fichier ordinaire court attendu.")
        parent = chemin.parent.stat()
        if (infos.st_uid != os.geteuid() or stat.S_IMODE(infos.st_mode) != 0o600
                or stat.S_IMODE(parent.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-PERMISSIONS",
                                   "fichier de clé : propriétaire courant, mode 0600 et dossier privé requis.")
        contenu = os.read(descripteur, 257)
    finally:
        os.close(descripteur)
    try:
        brute = base64.b64decode(contenu.strip(), validate=True)
    except (binascii.Error, ValueError):
        brute = b""
    if len(brute) != TAILLE_CLE:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-INVALIDE", "clé invalide : 32 octets en base64 attendus.")
    return brute


def _refuser_cle_mal_placee(environ: Mapping[str, str] | None, interdits: list[Path]) -> None:
    """La clé ne doit être ni dans le dossier des sauvegardes, ni dans le dossier de l'instance."""
    env = os.environ if environ is None else environ
    nom = env.get(ENV_CLE_FICHIER, "")
    if not nom:
        return
    chemin = Path(nom).resolve()
    for dossier in interdits:
        racine = dossier.resolve()
        if chemin == racine or racine in chemin.parents:
            raise ErreurSauvegarde("REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE",
                                   f"la clé de sauvegarde ne doit pas se trouver dans {racine} : "
                                   "une sauvegarde qui contient sa clé ne protège rien.")


def _aesgcm(cle: bytes):  # type: ignore[no-untyped-def]
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ModuleNotFoundError:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-DEPENDANCE",
                               "le paquet « cryptography » est requis (verrou requirements-runtime).") from None
    return AESGCM(cle)


# -- chiffrement par blocs ------------------------------------------------------------------------------------------

def _nonce(rang: int) -> bytes:
    return b"\x00\x00\x00\x00" + rang.to_bytes(8, "big")


def _erreur_es(erreur: OSError) -> ErreurSauvegarde:
    if erreur.errno in (errno.ENOSPC, errno.EDQUOT, errno.EFBIG):
        return ErreurSauvegarde("REJ-SAUVEGARDE-DISQUE-PLEIN",
                                "espace disque insuffisant : aucune sauvegarde partielle n'est conservée.")
    return ErreurSauvegarde("REJ-SAUVEGARDE-ES", f"erreur d'entrée-sortie ({erreur.strerror}).")


def _ouvrir_exclusif(chemin: Path) -> int:
    try:
        return os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-ES", f"{chemin.name} existe déjà : jamais d'écrasement.") from None
    except OSError as erreur:
        raise _erreur_es(erreur) from None


def chiffrer_fichier(source: Path, destination: Path, cle: bytes) -> dict[str, object]:
    """Chiffre `source` vers `destination` (jamais écrasée). Écrit un `.partiel` puis renomme ; l'échec le retire."""
    aes_cle = _cle_de_bloc(cle, sel := secrets.token_bytes(16))
    entete = MAGIC + bytes([VERSION_FORMAT]) + struct.pack(">I", TAILLE_BLOC) + _empreinte_cle(cle) + sel
    aes = _aesgcm(aes_cle)
    partiel = destination.with_name(destination.name + ".partiel")
    if destination.exists() or destination.is_symlink():
        raise ErreurSauvegarde("REJ-SAUVEGARDE-ES", f"{destination.name} existe déjà : jamais d'écrasement.")
    descripteur = _ouvrir_exclusif(partiel)
    clair = hashlib.sha256()
    taille_claire = 0
    try:
        with os.fdopen(descripteur, "wb") as sortie, source.open("rb") as entree:
            sortie.write(entete)
            rang = 0
            lu = entree.read(TAILLE_BLOC)
            while True:
                suivant = entree.read(TAILLE_BLOC) if len(lu) == TAILLE_BLOC else b""
                dernier = len(lu) < TAILLE_BLOC or not suivant
                clair.update(lu)
                taille_claire += len(lu)
                chiffre = aes.encrypt(_nonce(rang), lu, entete + (b"\x01" if dernier else b"\x00"))
                sortie.write(struct.pack(">I", len(chiffre)) + chiffre)
                if dernier:
                    break
                rang += 1
                lu = suivant
            sortie.flush()
            os.fsync(sortie.fileno())
        os.rename(partiel, destination)
    except OSError as erreur:
        with contextlib.suppress(OSError):
            partiel.unlink()
        raise _erreur_es(erreur) from None
    except BaseException:
        with contextlib.suppress(OSError):
            partiel.unlink()
        raise
    return {"sha256_clair": clair.hexdigest(), "octets_clairs": taille_claire,
            "octets_chiffres": destination.stat().st_size, "cle_id": _empreinte_cle(cle).hex()}


def _lire_exact(flux, n: int) -> bytes:  # type: ignore[no-untyped-def]
    morceau = flux.read(n)
    return morceau if morceau is not None else b""


def dechiffrer_flux(source: Path, cle: bytes, ecrire=None) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Authentifie TOUTE l'archive ; appelle `ecrire(bloc)` pour chaque bloc clair. Rend sha256 et taille du clair."""
    try:
        flux = source.open("rb")
    except FileNotFoundError:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-ES", f"{source.name} introuvable.") from None
    except OSError as erreur:
        raise _erreur_es(erreur) from None
    with flux:
        entete = _lire_exact(flux, _TAILLE_ENTETE)
        if len(entete) < len(MAGIC) or entete[: len(MAGIC)] != MAGIC:
            raise ErreurSauvegarde("REJ-SAUVEGARDE-FORMAT", "ce fichier n'est pas une sauvegarde OPSYS chiffrée.")
        if len(entete) < _TAILLE_ENTETE:
            raise ErreurSauvegarde("REJ-SAUVEGARDE-TRONQUEE", "en-tête incomplet : archive tronquée.")
        version = entete[len(MAGIC)]
        if version != VERSION_FORMAT:
            raise ErreurSauvegarde("REJ-SAUVEGARDE-VERSION-FORMAT",
                                   f"format de sauvegarde v{version} inconnu de ce logiciel (v{VERSION_FORMAT}) : "
                                   "mettre le logiciel à jour avant de restaurer.")
        (taille_bloc,) = struct.unpack(">I", entete[len(MAGIC) + 1: len(MAGIC) + 5])
        cle_id = entete[len(MAGIC) + 5: len(MAGIC) + 21]
        sel = entete[len(MAGIC) + 21:]
        if not 1 <= taille_bloc <= TAILLE_BLOC_MAX:
            raise ErreurSauvegarde("REJ-SAUVEGARDE-FORMAT", "taille de bloc hors bornes.")
        if not hmac.compare_digest(cle_id, _empreinte_cle(cle)):
            raise ErreurSauvegarde("REJ-SAUVEGARDE-MAUVAISE-CLE",
                                   "cette clé n'est pas celle qui a chiffré la sauvegarde ; rien n'a été déchiffré.")
        aes = _aesgcm(_cle_de_bloc(cle, sel))
        from cryptography.exceptions import InvalidTag

        clair = hashlib.sha256()
        total = 0
        rang = 0
        while True:
            taille_brute = _lire_exact(flux, 4)
            if len(taille_brute) < 4:
                raise ErreurSauvegarde("REJ-SAUVEGARDE-TRONQUEE", "dernier bloc absent : archive tronquée.")
            (taille,) = struct.unpack(">I", taille_brute)
            if not _ETIQUETTE <= taille <= taille_bloc + _ETIQUETTE:
                raise ErreurSauvegarde("REJ-SAUVEGARDE-ALTEREE", "longueur de bloc incohérente : archive altérée.")
            chiffre = _lire_exact(flux, taille)
            if len(chiffre) < taille:
                raise ErreurSauvegarde("REJ-SAUVEGARDE-TRONQUEE", "bloc incomplet : archive tronquée.")
            dernier = False
            try:
                bloc = aes.decrypt(_nonce(rang), chiffre, entete + b"\x00")
            except InvalidTag:
                try:
                    bloc = aes.decrypt(_nonce(rang), chiffre, entete + b"\x01")
                    dernier = True
                except InvalidTag:
                    raise ErreurSauvegarde("REJ-SAUVEGARDE-ALTEREE",
                                           f"le bloc {rang} échoue à l'authentification : archive altérée.") from None
            if dernier and flux.read(1):
                raise ErreurSauvegarde("REJ-SAUVEGARDE-ALTEREE", "octets après le dernier bloc : archive altérée.")
            clair.update(bloc)
            total += len(bloc)
            if ecrire is not None:
                ecrire(bloc)
            if dernier:
                return {"sha256_clair": clair.hexdigest(), "octets_clairs": total, "blocs": rang + 1,
                        "cle_id": cle_id.hex()}
            rang += 1


def dechiffrer_fichier(source: Path, destination: Path, cle: bytes) -> dict[str, object]:
    """Déchiffre vers `destination` (0600, jamais écrasée) ; le fichier n'existe sous son nom qu'APRÈS
authentification."""
    partiel = destination.with_name(destination.name + ".partiel")
    descripteur = _ouvrir_exclusif(partiel)
    try:
        with os.fdopen(descripteur, "wb") as sortie:
            resultat = dechiffrer_flux(source, cle, sortie.write)
            sortie.flush()
            os.fsync(sortie.fileno())
        if destination.exists() or destination.is_symlink():
            raise ErreurSauvegarde("REJ-SAUVEGARDE-ES", f"{destination.name} existe déjà : jamais d'écrasement.")
        os.rename(partiel, destination)
    except OSError as erreur:
        with contextlib.suppress(OSError):
            partiel.unlink()
        raise _erreur_es(erreur) from None
    except BaseException:
        with contextlib.suppress(OSError):
            partiel.unlink()
        raise
    return resultat


# -- sauvegarde / restauration de l'instance -----------------------------------------------------------------------

def _horodatage(maintenant: dt.datetime | None = None) -> str:
    return (maintenant or dt.datetime.now(dt.UTC)).strftime("%Y%m%dT%H%M%SZ")


def _nom_exportation(erreur: exportation.ErreurExportation) -> str:
    code = getattr(erreur, "code", None)
    return {
        "REJ-EXPORT-BASE-CORROMPUE": "REJ-SAUVEGARDE-BASE-CORROMPUE",
        "REJ-EXPORT-VERSION-INCOMPATIBLE": "REJ-SAUVEGARDE-VERSION-LOGICIEL",
        "REJ-EXPORT-DISQUE-PLEIN": "REJ-SAUVEGARDE-DISQUE-PLEIN",
    }.get(code or "", "REJ-SAUVEGARDE-EXPORT")


def sauvegarder(home: Path, dossier: Path, *, par: str, environ: Mapping[str, str] | None = None,
                maintenant: dt.datetime | None = None) -> dict[str, object]:
    """Export de l'instance, chiffrement, puis VÉRIFICATION par déchiffrement en flux. Rend le descriptif de la
sauvegarde."""
    _refuser_cle_mal_placee(environ, [dossier, home])
    cle = lire_cle(environ)
    dossier.mkdir(parents=True, exist_ok=True)
    nom = f"opsys-sauvegarde-{_horodatage(maintenant)}-{secrets.token_hex(2)}{_SUFFIXE}"
    destination = dossier / nom
    temporaire = Path(tempfile.mkdtemp(prefix="opsys-sauvegarde-", dir=str(dossier)))
    os.chmod(temporaire, 0o700)
    try:
        try:
            export = exportation.exporter(home, temporaire / "export.tar.gz", par=par)
        except exportation.ErreurExportation as erreur:
            raise ErreurSauvegarde(_nom_exportation(erreur), str(erreur)) from erreur
        except OSError as erreur:
            raise _erreur_es(erreur) from None
        chiffre = chiffrer_fichier(export.archive, destination, cle)
        verification = dechiffrer_flux(destination, cle)
        if verification["sha256_clair"] != export.sha256 or chiffre["sha256_clair"] != export.sha256:
            destination.unlink()
            raise ErreurSauvegarde("REJ-SAUVEGARDE-ALTEREE",
                                   "la vérification après chiffrement diverge : sauvegarde retirée.")
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)
    meta = {"fichier": nom, "revision_base": export.revision, "sha256_clair": export.sha256,
            "octets_chiffres": chiffre["octets_chiffres"], "cle_id": chiffre["cle_id"],
            "cree_le": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "note": "informatif, non authentifié : l'autorité est l'archive chiffrée elle-même"}
    (dossier / (nom + ".meta.json")).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    os.chmod(dossier / (nom + ".meta.json"), 0o600)
    return {**meta, "chemin": str(destination), "verifiee": True}


def verifier(archive: Path, *, environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Authentifie l'archive entière sans rien écrire sur disque (intégrité + bonne clé)."""
    resultat = dechiffrer_flux(archive, lire_cle(environ))
    return {**resultat, "chemin": str(archive), "verifiee": True}


def restaurer(archive: Path, home: Path, *, par: str, remplacer: bool = False,
              environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Déchiffre (tout authentifié d'abord) puis délègue à `exportation.restaurer`. Rien n'est écrit si un
refus survient."""
    _refuser_cle_mal_placee(environ, [archive.parent, home])
    cle = lire_cle(environ)
    temporaire = Path(tempfile.mkdtemp(prefix="opsys-restauration-"))
    os.chmod(temporaire, 0o700)
    try:
        clair = temporaire / "export.tar.gz"
        resultat = dechiffrer_fichier(archive, clair, cle)
        try:
            restauration = exportation.restaurer(clair, home, par=par, remplacer=remplacer,
                                                 empreinte=str(resultat["sha256_clair"]))
        except exportation.ErreurExportation as erreur:
            code = _nom_exportation(erreur)
            if code == "REJ-SAUVEGARDE-EXPORT":
                code = "REJ-SAUVEGARDE-RESTAURATION"
            raise ErreurSauvegarde(code, str(erreur)) from erreur
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)
    return {**restauration.en_json(), "sha256_clair": resultat["sha256_clair"], "cle_id": resultat["cle_id"]}


# -- rétention (met de côté, ne supprime jamais) -------------------------------------------------------------------

def plan_retention(
    dossier: Path, *, garder: int, jours: int, maintenant: dt.datetime | None = None
) -> dict[str, list[str]]:
    """Garde les `garder` plus récentes ET toute sauvegarde de moins de `jours` jours ; le reste est mis de côté."""
    if garder < 1 or jours < 0:
        raise ErreurSauvegarde("REJ-SAUVEGARDE-RETENTION",
                               "garder ≥ 1 et jours ≥ 0 : une politique ne vide jamais le dossier.")
    maintenant = maintenant or dt.datetime.now(dt.UTC)
    trouvees = []
    for chemin in dossier.iterdir() if dossier.is_dir() else []:
        correspond = _NOM_SAUVEGARDE.match(chemin.name)
        if correspond and chemin.is_file():
            date = dt.datetime.strptime(correspond.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
            trouvees.append((date, chemin.name))
    trouvees.sort(reverse=True)
    gardees, a_ecarter = [], []
    for rang, (date, nom) in enumerate(trouvees):
        recente = (maintenant - date) < dt.timedelta(days=jours)
        (gardees if rang < garder or recente else a_ecarter).append(nom)
    return {"gardees": gardees, "a_mettre_de_cote": a_ecarter}


def appliquer_retention(
    dossier: Path, *, garder: int, jours: int, maintenant: dt.datetime | None = None
) -> dict[str, object]:
    plan = plan_retention(dossier, garder=garder, jours=jours, maintenant=maintenant)
    cible = dossier / DOSSIER_A_DETRUIRE
    deplacees = []
    for nom in plan["a_mettre_de_cote"]:
        cible.mkdir(mode=0o700, exist_ok=True)
        for suffixe in ("", ".meta.json"):
            source = dossier / (nom + suffixe)
            if source.exists():
                os.rename(source, cible / (nom + suffixe))
        deplacees.append(nom)
    return {**plan, "mises_de_cote": deplacees, "dossier_a_detruire": str(cible),
            "rappel": "rien n'est supprimé : la destruction définitive est une décision humaine (T3)"}


# -- CLI -----------------------------------------------------------------------------------------------------------

def _afficher(objet: object) -> None:
    print(json.dumps(objet, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(prog="python -m opsys.sauvegarde_chiffree",
                                      description="Sauvegarde chiffrée de l'instance (clé hors de la sauvegarde)")
    sous = parseur.add_subparsers(dest="commande", required=True)
    cle = sous.add_parser("generer-cle", help="crée le fichier de clé (0600) et affiche son cle_id")
    cle.add_argument("chemin")
    sauv = sous.add_parser("sauvegarder", help="exporter, chiffrer, vérifier")
    sauv.add_argument("--dossier", required=True, help="dossier des sauvegardes (hors de la clé)")
    sauv.add_argument("--par")
    ver = sous.add_parser("verifier", help="authentifier une sauvegarde sans l'écrire")
    ver.add_argument("archive")
    res = sous.add_parser("restaurer", help="déchiffrer puis restaurer (exportation.restaurer)")
    res.add_argument("archive")
    res.add_argument("--remplacer", action="store_true")
    res.add_argument("--par")
    ret = sous.add_parser("retention", help="mettre de côté les sauvegardes hors politique (jamais de suppression)")
    ret.add_argument("--dossier", required=True)
    ret.add_argument("--garder", type=int, default=7)
    ret.add_argument("--jours", type=int, default=30)
    ret.add_argument("--appliquer", action="store_true", help="sans cela : plan seulement")
    args = parseur.parse_args(argv)
    from . import stockage

    try:
        if args.commande == "generer-cle":
            _afficher({"chemin": args.chemin, "cle_id": generer_cle(Path(args.chemin))})
        elif args.commande == "sauvegarder":
            home = stockage.dossier_opsys()
            _afficher(sauvegarder(home, Path(args.dossier), par=args.par or "poste:sauvegarde"))
        elif args.commande == "verifier":
            _afficher(verifier(Path(args.archive)))
        elif args.commande == "restaurer":
            _afficher(restaurer(Path(args.archive), stockage.dossier_opsys(), par=args.par or "poste:restauration",
                                remplacer=args.remplacer))
        else:
            dossier = Path(args.dossier)
            _afficher(appliquer_retention(dossier, garder=args.garder, jours=args.jours) if args.appliquer
                      else plan_retention(dossier, garder=args.garder, jours=args.jours))
    except ErreurSauvegarde as erreur:
        print(str(erreur), file=sys.stderr)
        return CODES_SORTIE.get(erreur.code, 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
