#!/usr/bin/env python3
"""Prépare, SANS RÉSEAU, les dépendances de l'image de qualification (install/qualification/Dockerfile).

Pourquoi : `deploy/Dockerfile` installe `requirements-runtime.lock.txt` avec `pip install --require-hashes`, donc avec le
réseau. Sur une machine sans réseau (ou quand on refuse de s'en servir), ce script copie, depuis un environnement Python
DÉJÀ installé (par défaut le venv de développement du dépôt), les seules distributions que le verrou nomme, et dit
franchement :
- celles du verrou qui manquent dans cet environnement (jamais substituées, jamais inventées) ;
- celles dont la version diffère du verrou ;
- que les empreintes (`--hash`) du verrou ne sont PAS vérifiées par cette voie (rien n'est téléchargé).

Le résultat est un dossier `site-packages` + `deps.json`, passé à `docker build --build-context deps=<dossier>`.
Ce n'est pas l'installation de production : c'est le substitut honnête quand pip n'a pas le droit de sortir.

Usage : preparer_contexte.py --venv <venv> --sortie <dossier> [--verrou requirements-runtime.lock.txt]
Bibliothèque standard + `packaging` (présent dans le venv du dépôt). Code de sortie : 0 prêt, 1 distribution requise
absente de l'extra « console »/« postgres » (le cœur ne démarrerait pas), 2 usage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

# Distributions SANS lesquelles ni le moteur, ni le serveur MCP, ni la console ne démarrent (extras postgres/console).
# `pyvrp` (extra « tournées ») et ses dépendances numériques ne sont volontairement pas dans cette liste : leur absence
# est un écart documenté (M4 se replie sur son solveur exact), pas un échec du banc.
INDISPENSABLES = (
    "alembic", "sqlalchemy", "pyyaml", "mcp", "jsonschema", "fastapi", "uvicorn", "starlette", "pydantic",
    "cryptography", "psycopg", "psycopg-binary", "reportlab", "anyio", "httpx2",
)
FACULTATIVES_CONNUES = ("pyvrp", "numpy", "matplotlib", "contourpy", "cycler", "fonttools", "kiwisolver", "pyparsing",
                        "python-dateutil", "six", "vrplib", "tqdm", "pillow")

_LIGNE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)\s*(?:;\s*(.*?))?\s*\\?$")


def _normaliser(nom: str) -> str:
    return re.sub(r"[-_.]+", "-", nom).lower()


def lire_verrou(chemin: Path) -> list[tuple[str, str, str | None]]:
    """Entrées `nom==version ; marqueur` du verrou (les lignes --hash et # via sont ignorées)."""
    entrees: list[tuple[str, str, str | None]] = []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if not ligne or ligne[0] in " #\t":
            continue
        trouve = _LIGNE.match(ligne)
        if trouve:
            entrees.append((_normaliser(trouve.group(1)), trouve.group(2), trouve.group(3)))
    return entrees


def marqueur_vrai(marqueur: str | None, python_cible: str) -> bool:
    if not marqueur:
        return True
    from packaging.markers import Marker

    environnement = {"python_full_version": python_cible, "python_version": ".".join(python_cible.split(".")[:2]),
                     "sys_platform": "linux", "platform_system": "Linux", "platform_python_implementation": "CPython",
                     "os_name": "posix", "implementation_name": "cpython"}
    return Marker(marqueur).evaluate(environnement)


def distributions_installees(site: Path) -> dict[str, tuple[str, Path]]:
    trouvees: dict[str, tuple[str, Path]] = {}
    for dossier in site.glob("*.dist-info"):
        meta = dossier / "METADATA"
        if not meta.is_file():
            continue
        nom = version = None
        for ligne in meta.read_text(encoding="utf-8", errors="replace").splitlines():
            if ligne.startswith("Name:") and nom is None:
                nom = ligne.split(":", 1)[1].strip()
            elif ligne.startswith("Version:") and version is None:
                version = ligne.split(":", 1)[1].strip()
            if nom and version:
                break
        if nom and version:
            trouvees[_normaliser(nom)] = (version, dossier)
    return trouvees


def copier_distribution(site: Path, dossier_meta: Path, sortie: Path) -> int:
    """Copie les fichiers listés par RECORD (jamais les .pyc ni les chemins qui sortent de site-packages)."""
    copies = 0
    with (dossier_meta / "RECORD").open(encoding="utf-8", newline="") as flux:
        for ligne in csv.reader(flux):
            if not ligne:
                continue
            relatif = ligne[0]
            if relatif.endswith(".pyc") or "__pycache__" in relatif or relatif.startswith(("..", "/")):
                continue
            source = site / relatif
            if not source.is_file():
                continue
            cible = sortie / relatif
            cible.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, cible)
            copies += 1
    return copies


def preparer(venv: Path, sortie: Path, verrou: Path, python_cible: str) -> dict:
    sites = sorted((venv / "lib").glob("python3*/site-packages"))
    if not sites:
        raise SystemExit(f"aucun site-packages dans {venv}")
    site = sites[0]
    installees = distributions_installees(site)
    if sortie.exists():
        shutil.rmtree(sortie)
    (sortie / "site-packages").mkdir(parents=True)
    rapport: dict = {"verrou": str(verrou.name), "sha256_verrou": hashlib.sha256(verrou.read_bytes()).hexdigest(),
                     "python_cible": python_cible, "source": "environnement local déjà installé, aucun réseau",
                     "empreintes_verrou_verifiees": False, "copiees": [], "versions_differentes": [],
                     "absentes_du_venv": [], "marqueur_faux": []}
    for nom, version, marqueur in lire_verrou(verrou):
        if not marqueur_vrai(marqueur, python_cible):
            rapport["marqueur_faux"].append(f"{nom}=={version}")
            continue
        trouve = installees.get(nom)
        if trouve is None:
            rapport["absentes_du_venv"].append(f"{nom}=={version}")
            continue
        version_locale, meta = trouve
        if version_locale != version:
            rapport["versions_differentes"].append({"nom": nom, "verrou": version, "installee": version_locale})
        copier_distribution(site, meta, sortie / "site-packages")
        rapport["copiees"].append(f"{nom}=={version_locale}")
    # setuptools sert au `pip install --no-build-isolation` du paquet du dépôt (le verrou le nomme : groupe « build »).
    absentes = {_normaliser(x.split("==")[0]) for x in rapport["absentes_du_venv"]}
    rapport["indispensables_absentes"] = sorted(a for a in INDISPENSABLES if a in absentes)
    rapport["extras_facultatifs_absents"] = sorted(a for a in absentes if a in FACULTATIVES_CONNUES)
    (sortie / "deps.json").write_text(json.dumps(rapport, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return rapport


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--venv", required=True, type=Path)
    p.add_argument("--sortie", required=True, type=Path)
    p.add_argument("--verrou", type=Path, default=Path("requirements-runtime.lock.txt"))
    p.add_argument("--python-cible", default="3.12.15", help="version de l'interpréteur de l'image (marqueurs du verrou)")
    args = p.parse_args(argv)
    if not args.verrou.is_file() or not args.venv.is_dir():
        print("verrou ou venv introuvable", file=sys.stderr)
        return 2
    rapport = preparer(args.venv, args.sortie, args.verrou, args.python_cible)
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in rapport.items()
                      if k not in ("source",)}, ensure_ascii=False))
    for ligne in rapport["versions_differentes"]:
        print(f"ÉCART de version : {ligne}", file=sys.stderr)
    if rapport["indispensables_absentes"]:
        print(f"ÉCHEC : distributions indispensables absentes : {rapport['indispensables_absentes']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
