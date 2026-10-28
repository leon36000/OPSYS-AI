"""Prépare le profil SQLite privé qualifié Linux ARM64, sans charger sa bibliothèque.

Entrée interne de install.sh, exécutée avec -I -S. Aucun téléchargement, remplacement
système ou modification de Node. Ce profil borné refuse toute autre construction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import stat
import sys
import tempfile
from pathlib import Path

LIBRARY_SHA256 = "f7e6347a5a1fa56185cd1a9d98d7e6927adc55fa97d5e9060664163aa9d8e69f"
PYTHON_SHA256 = "c86f21d0da9290ece2d7d49a3f7ed52aed59cb029abdf0ea25c79634f6cbe960"
LIBRARY_BYTES = 1686968
PYTHON_BYTES = 7845048
LIBRARY_NAME = "libsqlite3.so.0.8.6"
LICENSE = """The author disclaims copyright to this source code.  In place of
 a legal notice, here is a blessing:

  *   May you do good and not evil.
  *   May you find forgiveness for yourself and forgive others.
  *   May you share freely, never taking more than you give.
""".replace("\n a legal", "\na legal")
PROFILE = "ubuntu-24.04-aarch64-cpython-3.12-sqlite-3.45.1-wal-backport"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def absolute_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or any(c in value for c in "\r\n:\\"):
        raise ValueError("chemin absolu requis, sans séparateur de chargeur ni retour de ligne")
    return path


def profile_supported(python: Path) -> None:
    if sys.platform != "linux" or platform.machine() != "aarch64":
        raise ValueError("ce profil SQLite privé est qualifié uniquement sous Linux ARM64")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise ValueError("ce profil SQLite privé exige Ubuntu 24.04")
    with python.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != PYTHON_BYTES:
            raise ValueError("interpréteur différent du profil CPython qualifié : refus avant tout accès métier")
        data = stream.read(PYTHON_BYTES + 1)
    if digest(data) != PYTHON_SHA256 or not os.access(python, os.X_OK):
        raise ValueError("interpréteur différent du profil CPython qualifié : refus avant tout accès métier")
    if not Path("/usr/bin/sha256sum").is_file():
        raise ValueError("sha256sum requis pour revalider le profil à chaque démarrage")


def trusted_path(path: Path, *, ancestors: bool = False) -> None:
    """Propriétaire local/root et aucune écriture par groupe/autres ; /tmp sticky est admis."""
    targets = [path, *path.parents] if ancestors else [path]
    for target in targets:
        if not target.exists() and not target.is_symlink():
            continue
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid not in (0, os.getuid()):
            raise ValueError("profil privé : lien ou propriétaire étranger refusé")
        sticky_root_directory = (stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                                 and bool(info.st_mode & stat.S_ISVTX))
        if info.st_mode & 0o022 and not sticky_root_directory:
            raise ValueError("profil privé réinscriptible par groupe/autres : refus")


def read_library(path: Path) -> bytes:
    # Pas de lien opérateur suivi entre validation et copie, ni de lecture non bornée.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != LIBRARY_BYTES:
            raise ValueError("artefact SQLite privé invalide (type ou taille)")
        data = stream.read(LIBRARY_BYTES + 1)
    if len(data) != LIBRARY_BYTES or digest(data) != LIBRARY_SHA256:
        raise ValueError("empreinte SQLite privée différente de la construction qualifiée")
    # L'empreinte lie également ELF AArch64/SONAME/dépendances/licence déjà qualifiés.
    return data


def wrapper(root: Path, python: Path) -> bytes:
    library = root / LIBRARY_NAME
    text = (
        f'''#!/bin/bash
# OPSYS-SQLITE-PRIVEE : lanceur métier géré par install.sh ; aucun repli système.
set -euo pipefail
PY={shlex.quote(str(python))}
LIB={shlex.quote(str(library))}
unset LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH
export OPSYS_PYTHON_LAUNCHER={shlex.quote(str(root / "python"))}
refus() {{ echo "OPSYS : profil SQLite privé absent ou modifié ; démarrage métier refusé." >&2; exit 126; }}
[ -x "$PY" ] && [ -f "$LIB" ] && [ ! -L "$LIB" ] || refus
printf '%s  %s\\n' {PYTHON_SHA256} "$PY" | /usr/bin/sha256sum --check --status || refus
printf '%s  %s\\n' {LIBRARY_SHA256} "$LIB" | /usr/bin/sha256sum --check --status || refus
[ -L {shlex.quote(str(root / 'libsqlite3.so.0'))} ] && '''
        f'''[ "$(/usr/bin/readlink {shlex.quote(str(root / 'libsqlite3.so.0'))})" = {LIBRARY_NAME} ] || refus
export LD_LIBRARY_PATH={shlex.quote(str(root))}
exec "$PY" "$@"
'''
    )
    return text.encode()


def prepare(root: Path, python: Path, source: Path | None) -> Path:
    profile_supported(python)
    trusted_path(root, ancestors=True)
    launcher = root / "python"
    wanted = wrapper(root, python)
    manifest = {"profile": PROFILE, "library_sha256": LIBRARY_SHA256,
                "python": str(python), "python_sha256": PYTHON_SHA256,
                "launcher_sha256": digest(wanted), "license_sha256": digest(LICENSE.encode())}
    if root.exists() or root.is_symlink():
        if root.is_symlink() or not root.is_dir():
            raise ValueError("destination SQLite privée étrangère : aucun remplacement")
        expected_names = {LIBRARY_NAME, "libsqlite3.so.0", "python", "manifest.json", "LICENSE"}
        if {p.name for p in root.iterdir()} != expected_names:
            raise ValueError("inventaire du profil privé différent : préserver et réconcilier")
        for name in expected_names - {"libsqlite3.so.0"}:
            trusted_path(root / name)
        if source is not None:
            read_library(source)  # Une nouvelle sélection erronée n'est jamais ignorée.
        read_library(root / LIBRARY_NAME)
        alias = root / "libsqlite3.so.0"
        if not alias.is_symlink() or os.readlink(alias) != LIBRARY_NAME:
            raise ValueError("alias SONAME privé invalide")
        if (root / "manifest.json").is_symlink() or json.loads((root / "manifest.json").read_text()) != manifest:
            raise ValueError("profil installé différent : préserver puis réconcilier, sans remplacement implicite")
        if launcher.is_symlink() or launcher.read_bytes() != wanted or not os.access(launcher, os.X_OK):
            raise ValueError("lanceur SQLite privé modifié")
        if (root / "LICENSE").is_symlink() or (root / "LICENSE").read_bytes() != LICENSE.encode():
            raise ValueError("licence SQLite privée modifiée")
        return launcher
    if source is None:
        raise ValueError("artefact SQLite privé requis pour la première préparation")
    data = read_library(source)  # Toutes les préconditions avant la première écriture.
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix=".sqlite-privee-", dir=root.parent))
    try:
        for name, content, mode in ((LIBRARY_NAME, data, 0o444), ("python", wanted, 0o555),
                                    ("LICENSE", LICENSE.encode(), 0o444),
                                    ("manifest.json", (json.dumps(manifest, sort_keys=True) + "\n").encode(), 0o444)):
            path = stage / name
            with path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(mode)
        (stage / "libsqlite3.so.0").symlink_to(LIBRARY_NAME)
        stage_fd = os.open(stage, os.O_DIRECTORY)
        try:
            os.fsync(stage_fd)
        finally:
            os.close(stage_fd)
        # mkdir réserve atomiquement le nom : aucun dossier étranger même vide n'est remplacé.
        # Une interruption à cette frontière laisse une destination vide à réconcilier, jamais un profil actif.
        root.mkdir(mode=0o700)
        stage.rename(root)
        parent_fd = os.open(root.parent, os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return launcher


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=absolute_path)
    parser.add_argument("--python", required=True, type=absolute_path)
    parser.add_argument("--library", type=absolute_path)
    args = parser.parse_args()
    try:
        print(prepare(args.root, args.python, args.library))
    except (OSError, ValueError) as error:
        print(f"OPSYS : SQLite privée refusée : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
