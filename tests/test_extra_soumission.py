"""PLAN T2.3-f : l'extra `soumission` (ReportLab, PDF de la soumission brouillon de M3) est installé là où
le PDF doit se rendre et se tester : le job M3 de la CI, sinon les tests PDF seraient sautés ; l'image Docker,
sinon `m3_generer_soumission_brouillon` y refuserait le format pdf.

Ces gardes vivent au socle et non dans les tests de M3 : la copie jetable des outils de mutation de M3
(`departments/m03-estimation/tests/outils_preuve`) ne contient ni `.github/` ni `deploy/`."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from m3_estimation import soumission_pdf

RACINE = Path(__file__).resolve().parents[1]


def _ci() -> dict:
    return yaml.safe_load((RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _installation_departement() -> dict:
    etapes = [
        etape for etape in _ci()["jobs"]["departement"]["steps"]
        if "soumission" in etape.get("run", "")
    ]
    assert len(etapes) == 1
    return etapes[0]


@pytest.mark.skipif(not shutil.which("bash"), reason="le job Linux de CI exécute ce bloc dans bash")
@pytest.mark.parametrize("dossier", _ci()["jobs"]["departement"]["strategy"]["matrix"]["dossier"])
def test_le_job_de_m3_installe_l_extra_soumission_et_lui_seul(tmp_path, dossier):
    """Exécute la sélection réelle de la CI ; uv est enregistré sans installer de paquet."""
    etape = _installation_departement()
    assert etape["env"]["DOSSIER"] == "${{ matrix.dossier }}"
    assert "if" not in etape, "la synchronisation du socle est requise pour chaque département"
    faux_uv = tmp_path / "uv"
    faux_uv.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAUX_UV_APPELS"\n', encoding="utf-8")
    faux_uv.chmod(0o755)
    appels, chemin_ci = tmp_path / "appels", tmp_path / "github-path"
    resultat = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", etape["run"]], check=False, text=True, capture_output=True,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "DOSSIER": dossier,
             "FAUX_UV_APPELS": str(appels), "GITHUB_WORKSPACE": str(tmp_path), "GITHUB_PATH": str(chemin_ci)},
        timeout=10,
    )
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    extras = ["dev"]
    if dossier == "m04-field-ops":
        extras.append("tournees")
    if dossier == "m03-estimation":
        extras.append("soumission")
    commande = ["sync", "--locked", "--group", "build"]
    for extra in extras:
        commande.extend(["--extra", extra])
    commande.append("--no-build-isolation")
    assert [shlex.split(ligne) for ligne in appels.read_text(encoding="utf-8").splitlines()] == [
        [*commande, "--no-install-project"], commande,
    ]
    assert chemin_ci.read_text(encoding="utf-8") == f"{tmp_path}/.venv/bin\n"


def test_l_extra_est_installe_avant_les_tests_du_departement():
    noms = [etape.get("name", "") for etape in _ci()["jobs"]["departement"]["steps"]]
    installation = noms.index(_installation_departement()["name"])
    assert noms.index("uv (version verrouillée)") < installation
    assert installation < noms.index("Tests du département ${{ matrix.dossier }}")


def test_l_image_docker_installe_l_extra_soumission():
    dockerfile = (RACINE / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    verrou = (RACINE / "requirements-runtime.lock.txt").read_text(encoding="utf-8")
    commandes = re.findall(r"\bpip install\b(.*?)(?=;|&&|\n\n)", dockerfile, flags=re.DOTALL)
    assert len(commandes) == 3
    for commande in commandes[:2]:  # avec et sans certificat du proxy
        assert "--require-hashes" in commande
        assert "-r /opt/opsys/requirements-runtime.lock.txt" in commande
    assert "--no-deps" in commandes[2] and "--no-build-isolation -e /opt/opsys" in commandes[2]
    assert "--extra soumission" in verrou.splitlines()[1]
    reportlab = re.search(r"(?m)^reportlab==([^\s]+) \\\n((?:[ \t]+--hash=sha256:[0-9a-f]{64}[^\n]*\n)+)", verrou)
    assert reportlab is not None, "ReportLab doit être installé depuis une exigence hachée du lock d'image"
    assert reportlab.group(1) == soumission_pdf.VERSION_BRIQUE


def test_l_extra_epingle_la_version_que_le_module_verifie_a_l_execution():
    extras = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    assert extras["soumission"] == [f"{soumission_pdf.NOM_BRIQUE}=={soumission_pdf.VERSION_BRIQUE}"]
    assert any(exigence.startswith("pypdf==") for exigence in extras["dev"]), "pypdf relit les PDF des tests"
    assert not any("reportlab" in exigence for exigence in extras["dev"]), "ReportLab reste optionnel"
