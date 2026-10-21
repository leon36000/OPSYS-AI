"""Contexte Python : règles de secrets et projection runtime sans Core ni captures.

La copie de qualification utilise les sources Python de l'hôte. Elle ne produit
pas un contexte Docker et ne qualifie ni une image ni ses namespaces.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
EXCLUSIONS_PYTHON = (
    "core", "core/**", "docs/research", "docs/research/**",
    "**/.artifacts", "**/.artifacts/**",
)
FICHIERS_RUNTIME = (
    "pyproject.toml",
    "README.md",
    "requirements-runtime.lock.txt",
    "requirements-ingestion-pdf.lock.txt",
    "src/opsys/cli.py",
    "src/opsys/openclaw.py",
    "src/opsys/stockage/migrations/env.py",
    "src/opsys/memoire/schema.sql",
    "deploy/entrypoint.sh",
    "deploy/permissions.py",
    "deploy/readiness.py",
    "deploy/readiness_pdf.py",
    "docs/compliance/politiques/POLITIQUE-photos-non-contractuelles.md",
    "departments/m07-marketing/contracts/brand-contract.v1.yaml",
    "departments/m07-marketing/docs/seo-knowledge.v1.yaml",
    "departments/m07-marketing/src/m7_marketing/content/templates/post_social.yaml",
)


def _exclusions_supplementaires():
    globales = (RACINE / ".dockerignore").read_bytes()
    specifiques = (RACINE / "deploy/Dockerfile.dockerignore").read_bytes()
    # Le fichier spécifique a priorité sur le global : conserver TOUTES ses
    # règles, dans leur ordre, y compris les exceptions pour .env.example.
    assert specifiques.startswith(globales)
    return tuple(
        ligne.strip()
        for ligne in specifiques[len(globales):].decode().splitlines()
        if ligne.strip() and not ligne.lstrip().startswith("#")
    )


def test_ignore_specifique_conserve_toutes_les_regles_globales():
    _exclusions_supplementaires()


def test_exclusions_supplementaires_limitees_au_python_autonome():
    assert _exclusions_supplementaires() == EXCLUSIONS_PYTHON


@pytest.mark.parametrize("relatif", FICHIERS_RUNTIME)
def test_fichiers_runtime_restent_hors_exclusions_supplementaires(relatif):
    assert _exclusions_supplementaires() == EXCLUSIONS_PYTHON
    assert (RACINE / relatif).is_file()
    parties = Path(relatif).parts
    assert parties[0] != "core"
    assert parties[:2] != ("docs", "research")
    assert ".artifacts" not in parties


def test_cli_et_ressources_depuis_projection_sans_core(tmp_path):
    """Vrais imports, manifestes, migration SQLite et ressources, sans Docker."""
    assert _exclusions_supplementaires() == EXCLUSIONS_PYTHON
    copie = tmp_path / "projection-python"
    copie.mkdir()
    ignorer = shutil.ignore_patterns("__pycache__", "*.pyc", ".artifacts", "tests")
    for dossier in ("src", "departments", "docs/compliance"):
        shutil.copytree(RACINE / dossier, copie / dossier, ignore=ignorer)
    for fichier in ("pyproject.toml", "README.md"):
        shutil.copyfile(RACINE / fichier, copie / fichier)
    projet = tomllib.loads((copie / "pyproject.toml").read_text())
    modules = projet["tool"]["setuptools"]["package-dir"]
    pythonpath = sorted({str(copie / relatif) for relatif in (
        "src", *(str(Path(p).parent) for p in modules.values())
    )})
    home = tmp_path / "etat-fictif"
    home.mkdir()
    sonde = '''
import argparse,hashlib,importlib,json
from pathlib import Path
import opsys
from opsys import cli,stockage
from opsys.departements import charger_departements
from opsys.profils import rendre_soul
from m1_front_office import outils as m1
from m3_estimation import outils as m3
from m7_marketing.content.factory import build_content_item
r=Path.cwd().resolve()
assert Path(opsys.__file__).resolve().is_relative_to(r)
assert cli._source_du_logiciel(None)==r
deps=charger_departements()
assert len(deps)==10
assert all(d.racine.is_relative_to(r) for d in deps.values())
stockage.migrer()
assert cli.cmd_verifier(argparse.Namespace(config_dir=None,paliers=False))==0
for dep in deps.values():
 assert Path(importlib.import_module(dep.module_outils).__file__).resolve().is_relative_to(r)
 assert rendre_soul(dep,[])
 assert all((dep.racine/'skills'/skill).is_dir() for skill in dep.skills)
politique=r/'docs/compliance/politiques/POLITIQUE-photos-non-contractuelles.md'
assert m1._CHEMIN_POLITIQUE_PHOTOS==politique==m3._CHEMIN_POLITIQUE_PHOTOS
assert politique.read_text()
m7=r/'departments/m07-marketing'
item=build_content_item(
 {'name':'Marque QA fictive','tagline':'QA','tone':'sobre','colors':['gris'],'langue':'fr'},
 'google_aio','post_social',{'titre':'Titre QA','description':'Fictif','mots_cles':[]},
 '2026-10-02T00:00:00Z')
assert item['brand_ref']==hashlib.sha256((m7/'contracts/brand-contract.v1.yaml').read_bytes()).hexdigest()
assert item['seo_knowledge_ref']==hashlib.sha256((m7/'docs/seo-knowledge.v1.yaml').read_bytes()).hexdigest()
assert not (r/'core').exists() and not (r/'docs/research').exists()
print(json.dumps({'departements':len(deps),'projection':str(r),'sqlite':True,'m7_ressources':True}))
'''
    env = {
        "PATH": os.defpath,
        "HOME": str(home),
        "OPSYS_HOME": str(home),
        "TMPDIR": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(pythonpath),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    retour = subprocess.run(
        [sys.executable, "-B", "-c", sonde], cwd=copie, env=env,
        capture_output=True, text=True, timeout=20,
    )
    assert retour.returncode == 0, retour.stderr
    preuve = json.loads(retour.stdout.splitlines()[-1])
    assert preuve == {
        "departements": 10, "projection": str(copie), "sqlite": True, "m7_ressources": True,
    }
    assert (home / "opsys.db").is_file()
