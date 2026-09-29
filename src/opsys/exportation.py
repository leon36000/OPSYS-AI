"""Export et restauration de l'instance locale (PLAN T0.11) : `opsys-metier instance exporter` et `restaurer`.

L'export sert à sauvegarder, à déménager l'instance et à sortir ses données avant une désinstallation. Il
n'écrit RIEN dans l'instance sauf une ligne du journal d'audit, et ne dépend d'aucun arrêt du moteur.

Liste blanche (jamais une liste noire : un fichier inconnu ne sort pas par accident). L'archive contient :
- `opsys.db` : copie cohérente de la base par l'API de sauvegarde de SQLite (le journal WAL est inclus),
  contrôlée par `PRAGMA integrity_check` ;
- `paliers.yaml` et `entreprise.yaml` de l'instance, s'ils existent ;
- `manifeste.json` : format, date, version du logiciel, révision de la base, SHA-256 et taille de chaque fichier,
  fichiers volontairement exclus et avertissements.

Ne sortent JAMAIS : l'état du core, qui est le dossier du profil `opsys` du core (`~/.opsys/core`, PLAN T0.11-b et
T0.7 lot 3 ; avant le lot 3, `~/.openclaw-opsys`, exclu lui aussi tant que Doctor ne l'a pas déplacé) avec son `.env`
(secrets en clair) et l'état du Gateway (jetons d'appareils, sessions), ni l'index public d'adresses (`rqa/`). Même avec
l'`OPSYS_HOME` par défaut, où l'état du core est dans le dossier de l'instance : la liste blanche ne nomme que
`opsys.db`, `paliers.yaml` et `entreprise.yaml`. L'installateur régénère les secrets et la configuration du core ;
les appareils sont à réappairer. L'archive est écrite 0600, sans jamais écraser un fichier ; son SHA-256 est aussi
écrit dans `<archive>.sha256` (format `sha256sum`), que la restauration exige.

Limite à connaître : la base contient les clés de chiffrement destructibles des données à effacement
cryptographique (`opsys.cles_chiffrement`). Sans elles, une restauration perdrait ces données ; avec elles,
l'archive est aussi sensible que la base. Elle se protège comme la base : chiffrée avant tout transfert.

La restauration est fail-closed : empreinte de l'archive, membres, SHA-256 de chaque fichier, intégrité de la
base et révision de migration sont vérifiés AVANT de toucher à l'instance ; rien n'est écrasé sans `--remplacer` ;
avec lui, les fichiers actuels sont mis de côté (suffixe `.avant-restauration-<horodatage>`), jamais supprimés
(suppression définitive : frontière humaine, T3).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import zlib
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from . import __version__, etat, instance, stockage

FORMAT = "opsys-export/1"
DOSSIER_ARCHIVE = "opsys-export"
NOM_MANIFESTE = "manifeste.json"
NOM_BASE = "opsys.db"
FICHIERS_REGLAGES = ("paliers.yaml", "entreprise.yaml")
TAILLE_MAX_MANIFESTE = 1_000_000
_BLOC = 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Chemins relatifs au dossier personnel (jamais absolus : aucun nom de compte du poste dans l'archive), sauf `rqa/`
# qui est relatif à `OPSYS_HOME`.
_ETAT_CORE = f"{instance.DOSSIER_INSTANCE}/{instance.SOUS_DOSSIER_CORE}"
EXCLUS = (
    {"chemin": f"~/{_ETAT_CORE}/.env",
     "raison": "secrets en clair (jetons, clés), dans l'état du core : l'installateur en génère de nouveaux"},
    {"chemin": f"~/{_ETAT_CORE}/",
     "raison": "état du core et du Gateway (jetons d'appareils, sessions) : configuration régénérée, "
               "appareils à réappairer"},
    {"chemin": f"~/{instance.ANCIEN_DOSSIER_PROFIL}/",
     "raison": "ancien emplacement de l'état du core (avant T0.7 lot 3), tant que Doctor ne l'a pas déplacé : "
               "mêmes secrets, même exclusion"},
    {"chemin": "rqa/", "raison": "index public d'adresses, à télécharger de nouveau"},
)
AVERTISSEMENTS = (
    "L'archive contient des renseignements personnels et les clés de chiffrement destructibles de la base : la "
    "protéger comme la base (la chiffrer avant tout transfert, la garder au Canada, Loi 25).",
    "Un effacement fait dans l'instance ne touche pas les archives déjà produites : les inventorier et les détruire "
    "aussi.",
)


class ErreurExportation(Exception):
    """Une exportation ou une restauration refusée ; le message dit quoi faire."""


@dataclasses.dataclass(frozen=True)
class ResultatExport:
    archive: Path
    empreinte: Path
    sha256: str
    octets: int
    fichiers: tuple[dict[str, Any], ...]
    revision: str

    def en_json(self) -> dict[str, Any]:
        return {
            "archive": str(self.archive), "empreinte": str(self.empreinte), "sha256": self.sha256,
            "octets": self.octets, "fichiers": [dict(f) for f in self.fichiers], "revision_base": self.revision,
            "exclus": [dict(e) for e in EXCLUS], "avertissements": list(AVERTISSEMENTS),
        }


@dataclasses.dataclass(frozen=True)
class ResultatRestauration:
    base: Path
    restaures: tuple[str, ...]
    mis_de_cote: tuple[str, ...]
    revision: str

    def en_json(self) -> dict[str, Any]:
        return {
            "base": str(self.base), "restaures": list(self.restaures), "mis_de_cote": list(self.mis_de_cote),
            "revision_base": self.revision,
            "suite": "redémarrer le service ; les appareils sont à réappairer (openclaw qr)",
        }


# -- outils ----------------------------------------------------------------------------------------------------------
def _sha256(chemin: Path) -> tuple[str, int]:
    empreinte = hashlib.sha256()
    octets = 0
    with chemin.open("rb") as fichier:
        while bloc := fichier.read(_BLOC):
            empreinte.update(bloc)
            octets += len(bloc)
    return empreinte.hexdigest(), octets


def horodatage() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _base_sqlite(url: str) -> Path:
    """Le fichier de la base, ou un refus : seule la base SQLite locale s'exporte par cette commande."""
    cible = make_url(url)
    if cible.get_backend_name() != "sqlite" or not cible.database or cible.database == ":memory:":
        raise ErreurExportation(
            "cette commande exporte la base SQLite de l'instance locale. Pour PostgreSQL (Docker Compose), "
            "utilisez deploy/backup.sh (docs/ops/EXPLOITATION.md)."
        )
    return Path(cible.database)


def _instantane_sqlite(base: Path, cible: Path) -> str:
    """Copie cohérente de `base` dans `cible` (un seul fichier), contrôlée. Rend la révision de migration."""
    if not base.is_file():
        raise ErreurExportation(f"aucune base à exporter : {base} n'existe pas (instance jamais initialisée ?).")
    source = sqlite3.connect(str(base), timeout=30)
    try:
        copie = sqlite3.connect(str(cible))
        try:
            source.backup(copie)
            copie.execute("PRAGMA journal_mode=DELETE")  # un seul fichier, sans -wal ni -shm
            controle = copie.execute("PRAGMA integrity_check").fetchall()
            if controle != [("ok",)]:
                raise ErreurExportation(f"la base {base} échoue à PRAGMA integrity_check : export refusé.")
            try:
                ligne = copie.execute("SELECT version_num FROM alembic_version").fetchone()
            except sqlite3.OperationalError:
                ligne = None
        finally:
            copie.close()
    except sqlite3.Error as erreur:
        raise ErreurExportation(f"copie de la base impossible : {erreur}") from erreur
    finally:
        source.close()
    if not ligne or not ligne[0]:
        raise ErreurExportation(
            f"la base {base} n'est pas migrée : `opsys-metier base migrer`, puis relancez l'export.")
    return str(ligne[0])


def _ajouter(tar: tarfile.TarFile, nom: str, chemin: Path) -> None:
    info = tarfile.TarInfo(f"{DOSSIER_ARCHIVE}/{nom}")
    info.size = chemin.stat().st_size
    info.mode = 0o600
    info.mtime = int(dt.datetime.now(dt.UTC).timestamp())
    info.uid = info.gid = 0  # aucun nom de compte du poste dans l'archive
    info.uname = info.gname = ""
    with chemin.open("rb") as fichier:
        tar.addfile(info, fichier)


def _ecrire_empreinte(chemin: Path, sha256: str, nom_archive: str) -> None:
    descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:  # fermé même si l'ACL est refusée (Windows)
        instance.restreindre_acces(chemin)  # 0600 ; sous Windows, `os.open` ne restreint rien : l'ACL est réduite ici
        fichier.write(f"{sha256}  {nom_archive}\n")


def _journaliser(url: str, par: str, action: str, cible: str, details: dict[str, Any]) -> None:
    try:
        with stockage.transaction(url) as cnx:
            etat.journaliser(cnx, par, action, cible, details)
    except SQLAlchemyError as erreur:
        raise ErreurExportation(
            f"journal d'audit indisponible ({type(erreur).__name__}) : opération annulée. `opsys-metier base migrer` ?"
        ) from erreur


# -- export ----------------------------------------------------------------------------------------------------------
def exporter(home: Path, sortie: Path, *, par: str) -> ResultatExport:
    """Archive l'instance de `home` dans `sortie` (`.tar.gz`, 0600) et écrit `sortie.sha256`. Voir l'en-tête."""
    url = stockage.url_base()
    base = _base_sqlite(url)
    sortie = Path(os.path.abspath(sortie))
    empreinte_chemin = sortie.with_name(sortie.name + ".sha256")
    for existant in (sortie, empreinte_chemin):
        if existant.exists():
            raise ErreurExportation(
                f"{existant} existe déjà : un export n'écrase jamais un fichier. Choisissez --sortie.")
    sortie.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".opsys-export-", dir=sortie.parent) as temporaire:
        membres: dict[str, Path] = {NOM_BASE: Path(temporaire) / NOM_BASE}
        revision = _instantane_sqlite(base, membres[NOM_BASE])
        for nom in FICHIERS_REGLAGES:
            if (home / nom).is_file():
                membres[nom] = Path(temporaire) / nom
                shutil.copyfile(home / nom, membres[nom])
        fichiers = []
        for nom, chemin in membres.items():
            sha256, octets = _sha256(chemin)
            fichiers.append({"chemin": nom, "sha256": sha256, "octets": octets})
        manifeste = {
            "format": FORMAT, "cree_le": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "opsys_version": __version__, "base": {"moteur": "sqlite", "revision": revision}, "fichiers": fichiers,
            "exclus": [dict(e) for e in EXCLUS], "avertissements": list(AVERTISSEMENTS),
        }
        chemin_manifeste = Path(temporaire) / NOM_MANIFESTE
        chemin_manifeste.write_text(json.dumps(manifeste, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        descripteur = os.open(sortie, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            # Fermé même si l'ACL est refusée (sous Windows, on ne supprime pas un fichier ouvert), et restreint avant
            # la première donnée : jamais, même un instant, lisible par un autre compte.
            with os.fdopen(descripteur, "wb") as brut:
                instance.restreindre_acces(sortie)
                with tarfile.open(fileobj=brut, mode="w:gz") as tar:
                    _ajouter(tar, NOM_MANIFESTE, chemin_manifeste)
                    for nom, chemin in membres.items():
                        _ajouter(tar, nom, chemin)
            sha256_archive, octets_archive = _sha256(sortie)
            _ecrire_empreinte(empreinte_chemin, sha256_archive, sortie.name)
            _journaliser(url, par, "instance.export", sortie.name, {
                "sha256": sha256_archive, "octets": octets_archive, "fichiers": [f["chemin"] for f in fichiers]})
        except BaseException:
            sortie.unlink(missing_ok=True)
            empreinte_chemin.unlink(missing_ok=True)
            raise
    return ResultatExport(sortie, empreinte_chemin, sha256_archive, octets_archive, tuple(fichiers), revision)


# -- restauration ------------------------------------------------------------------------------------------------------
def _empreinte_attendue(archive: Path, fournie: str | None) -> str:
    if fournie:
        attendue = fournie.strip().lower()
    else:
        fichier = archive.with_name(archive.name + ".sha256")
        if not fichier.is_file():
            raise ErreurExportation(
                f"aucune empreinte pour vérifier l'archive : placez {fichier.name} à côté d'elle, ou donnez "
                "--empreinte <SHA-256 noté à l'export>. Une archive non vérifiée n'est jamais restaurée."
            )
        contenu = fichier.read_text(encoding="utf-8").split()
        attendue = contenu[0].lower() if contenu else ""
    if not _SHA256.match(attendue):
        raise ErreurExportation("l'empreinte attendue n'est pas un SHA-256 (64 caractères hexadécimaux).")
    return attendue


def _extraire(archive: Path, destination: Path) -> dict[str, Any]:
    """Extrait les seuls membres permis, sous des noms que NOUS choisissons, et rend le manifeste vérifié."""
    permis = {f"{DOSSIER_ARCHIVE}/{nom}": nom for nom in (NOM_MANIFESTE, NOM_BASE, *FICHIERS_REGLAGES)}
    try:
        with tarfile.open(archive, "r:gz") as tar:
            membres = tar.getmembers()
            noms = [m.name for m in membres]
            if len(set(noms)) != len(noms):
                raise ErreurExportation("archive refusée : un membre apparaît deux fois.")
            for membre in membres:
                if membre.name not in permis or not membre.isfile():
                    raise ErreurExportation(f"archive refusée : membre inattendu {membre.name!r} (liste blanche).")
                if membre.name.endswith(NOM_MANIFESTE) and membre.size > TAILLE_MAX_MANIFESTE:
                    raise ErreurExportation("archive refusée : manifeste démesuré.")
            if f"{DOSSIER_ARCHIVE}/{NOM_MANIFESTE}" not in noms or f"{DOSSIER_ARCHIVE}/{NOM_BASE}" not in noms:
                raise ErreurExportation("archive refusée : manifeste ou base absents.")
            for membre in membres:
                source = tar.extractfile(membre)
                if source is None:
                    raise ErreurExportation(f"archive refusée : {membre.name!r} illisible.")
                with source, (destination / permis[membre.name]).open("xb") as sortie:
                    shutil.copyfileobj(source, sortie, _BLOC)
    except (tarfile.TarError, EOFError, zlib.error, OSError) as erreur:
        raise ErreurExportation(
            f"archive illisible ou extraction impossible ({type(erreur).__name__}) : {erreur}") from erreur

    try:
        manifeste = json.loads((destination / NOM_MANIFESTE).read_text(encoding="utf-8"))
    except ValueError as erreur:
        raise ErreurExportation("archive refusée : manifeste illisible.") from erreur
    if not isinstance(manifeste, dict) or manifeste.get("format") != FORMAT:
        trouve = manifeste.get("format") if isinstance(manifeste, dict) else None
        raise ErreurExportation(f"archive refusée : format {trouve!r}, {FORMAT!r} attendu.")
    declares = {f.get("chemin"): f for f in manifeste.get("fichiers", []) if isinstance(f, dict)}
    presents = {p.name for p in destination.iterdir()} - {NOM_MANIFESTE}
    if set(declares) != presents:
        raise ErreurExportation("archive refusée : les fichiers du manifeste et ceux de l'archive diffèrent.")
    for nom, declare in declares.items():
        sha256, octets = _sha256(destination / nom)
        if not hmac.compare_digest(sha256, str(declare.get("sha256"))) or octets != declare.get("octets"):
            raise ErreurExportation(f"archive refusée : {nom} ne correspond pas au SHA-256 du manifeste.")
    return manifeste


def _verifier_base(chemin: Path, manifeste: dict[str, Any]) -> str:
    try:
        connexion = sqlite3.connect(str(chemin))
        try:
            controle = connexion.execute("PRAGMA integrity_check").fetchall()
        finally:
            connexion.close()
    except sqlite3.Error as erreur:
        raise ErreurExportation(f"la base de l'archive est illisible : {erreur}") from erreur
    if controle != [("ok",)]:
        raise ErreurExportation("la base de l'archive échoue à PRAGMA integrity_check : restauration refusée.")
    base = manifeste.get("base")
    revision = base.get("revision") if isinstance(base, dict) else None
    if not isinstance(revision, str) or not stockage.revision_connue(revision):
        raise ErreurExportation(
            f"la révision de la base ({revision!r}) est inconnue de ce logiciel : l'archive vient d'une version plus "
            "récente. Mettez le logiciel à jour (relancez l'installateur) avant de restaurer."
        )
    return revision


def restaurer(archive: Path, home: Path, *, par: str, remplacer: bool = False, empreinte: str | None = None,
              ) -> ResultatRestauration:
    """Restaure `archive` dans l'instance de `home`. Voir l'en-tête : tout est vérifié avant la première écriture."""
    url = stockage.url_base()
    base = _base_sqlite(url)
    if not archive.is_file():
        raise ErreurExportation(f"{archive} introuvable.")
    attendue = _empreinte_attendue(archive, empreinte)
    reelle, _ = _sha256(archive)
    if not hmac.compare_digest(attendue, reelle):
        raise ErreurExportation("l'empreinte SHA-256 de l'archive diffère de celle attendue : archive altérée ou "
                                "incomplète. Rien n'est modifié.")

    home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".opsys-restauration-", dir=home) as temporaire:
        dossier = Path(temporaire)
        manifeste = _extraire(archive, dossier)
        revision = _verifier_base(dossier / NOM_BASE, manifeste)
        cibles = {NOM_BASE: base, **{nom: home / nom for nom in FICHIERS_REGLAGES if (dossier / nom).is_file()}}
        existants = [nom for nom, cible in cibles.items() if cible.exists()]
        if existants and not remplacer:
            raise ErreurExportation(
                f"{', '.join(existants)} existe déjà dans l'instance : rien n'est écrasé. `--remplacer` met les "
                "fichiers actuels de côté (suffixe .avant-restauration-<horodatage>), sans les supprimer. "
                "Arrêtez d'abord le service."
            )
        stockage.liberer()
        instant = horodatage()
        mis_de_cote: list[tuple[Path, Path]] = []
        try:
            for cible in cibles.values():
                for suffixe in ("", "-wal", "-shm"):
                    actuel = Path(str(cible) + suffixe)
                    if actuel.exists():
                        ecarte = Path(f"{actuel}.avant-restauration-{instant}")
                        os.replace(actuel, ecarte)
                        mis_de_cote.append((actuel, ecarte))
            for nom, cible in cibles.items():
                os.replace(dossier / nom, cible)
        except BaseException:
            for actuel, ecarte in reversed(mis_de_cote):
                if not actuel.exists():
                    os.replace(ecarte, actuel)
            raise
    revision_finale = stockage.migrer(url)
    _journaliser(url, par, "instance.restauration", archive.name,
                 {"sha256": reelle, "restaures": sorted(cibles), "mis_de_cote": [str(e) for _, e in mis_de_cote],
                  "revision_archive": revision})
    return ResultatRestauration(base, tuple(sorted(cibles)), tuple(str(e) for _, e in mis_de_cote), revision_finale)
