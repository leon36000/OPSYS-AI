#!/usr/bin/env python3
"""Vérifier le pack, ou restaurer hors de tout checkout existant; aucune opération réseau."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

BRANCHE = "reprise-infra-2026-10-05"
GITHUB = "https://github.com/leon36000/OPSYS-AI.git"


def empreinte(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloc in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def environnement_git() -> dict[str, str]:
    env = os.environ.copy()
    for nom in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        env.pop(nom, None)
    # Import local seulement : aucune configuration globale de filtre/hook n'est exécutée.
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"})
    return env


def git(*args: str) -> str:
    resultat = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                              "-c", "core.fsmonitor=false", *args],
                             env=environnement_git(), capture_output=True, text=True, check=True)
    return resultat.stdout.strip()


def verifier(racine: Path) -> tuple[dict, Path]:
    manifeste = json.loads((racine / "MANIFESTE-TRANSFERT.json").read_text(encoding="utf-8"))
    if (manifeste.get("format") != "opsys-transfert/1"
            or manifeste.get("transport_branch") != BRANCHE
            or not re.fullmatch(r"[0-9a-f]{40}", manifeste.get("snapshot_tree", ""))):
        raise ValueError("format, branche ou arbre de transfert invalide")
    for rel, attendu in manifeste["prepared_paths"].items():
        p = PurePosixPath(rel)
        if (not rel or p.is_absolute() or ".." in p.parts or "\\" in rel
                or "\n" in rel or not re.fullmatch(r"[0-9a-f]{64}", attendu)):
            raise ValueError("chemin préparé ou empreinte invalide")
    bundle = racine / "OPSYS-AI.bundle"
    attendu = manifeste["bundle"]
    if attendu["file"] != bundle.name or bundle.stat().st_size != attendu["bytes"]:
        raise ValueError("nom ou taille du bundle invalide")
    if empreinte(bundle) != attendu["sha256"]:
        raise ValueError("empreinte du bundle invalide; ne pas restaurer")
    for rel, attendu in manifeste["support_files"].items():
        p = PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts or "\\" in rel:
            raise ValueError("chemin de support invalide")
        if empreinte(racine / rel) != attendu:
            raise ValueError("fichier de support modifié : " + rel)
    with tempfile.TemporaryDirectory(prefix="opsys-bundle-verification-") as temp:
        depot = Path(temp) / "verification.git"
        template = Path(temp) / "template"
        template.mkdir()
        git("init", "--bare", "--template=" + str(template), str(depot))
        git("-C", str(depot), "bundle", "verify", str(bundle))
    return manifeste, bundle


def restaurer(racine: Path, destination: Path) -> dict:
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination déjà présente; choisir un dossier neuf")
    if not destination.parent.is_dir():
        raise ValueError("le dossier parent doit exister")
    manifeste, bundle = verifier(racine)
    with tempfile.TemporaryDirectory(prefix="opsys-clone-template-") as temp:
        git("clone", "--no-checkout", "--single-branch", "--branch", BRANCHE,
            "--template=" + temp, str(bundle), str(destination))
    if git("-C", str(destination), "rev-parse", "HEAD^{tree}") != manifeste["snapshot_tree"]:
        raise ValueError("arbre restauré différent du snapshot")
    git("-C", str(destination), "config", "core.autocrlf", "false")
    git("-C", str(destination), "checkout", BRANCHE)
    for rel, attendu in manifeste["prepared_paths"].items():
        if empreinte(destination / rel) != attendu:
            raise ValueError("source restaurée différente : " + rel)
    git("-C", str(destination), "remote", "rename", "origin", "transfert-local")
    git("-C", str(destination), "remote", "add", "origin", GITHUB)
    return {"restaure": True, "destination": str(destination), "tree": manifeste["snapshot_tree"],
            "prepared_paths_verified": len(manifeste["prepared_paths"]),
            "network_used": False, "push": False, "merge": False, "deploy": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["verifier", "restaurer"])
    parser.add_argument("--pack", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "restaurer":
            if args.destination is None:
                parser.error("--destination est requis")
            resultat = restaurer(args.pack.resolve(), args.destination)
        else:
            manifeste, _ = verifier(args.pack.resolve())
            resultat = {"integrite_ok": True, "bundle_autonome": True,
                        "snapshot_tree": manifeste["snapshot_tree"],
                        "prepared_paths": len(manifeste["prepared_paths"]), "network_used": False}
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, "Transfert refusé : " + str(exc) + "\n")
    print(json.dumps(resultat, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
