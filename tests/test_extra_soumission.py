"""PLAN T2.3-f : l'extra `soumission` (ReportLab, PDF de la soumission brouillon de M3) est installé là où
le PDF doit se rendre et se tester : le job M3 de la CI, sinon les tests PDF seraient sautés ; l'image Docker,
sinon `m3_generer_soumission_brouillon` y refuserait le format pdf.

Ces gardes vivent au socle et non dans les tests de M3 : la copie jetable des outils de mutation de M3
(`departments/m03-estimation/tests/outils_preuve`) ne contient ni `.github/` ni `deploy/`."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml
from m3_estimation import soumission_pdf

RACINE = Path(__file__).resolve().parents[1]


def _ci() -> dict:
    return yaml.safe_load((RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def test_le_job_de_m3_installe_l_extra_soumission_et_lui_seul():
    etapes = [
        etape for etape in _ci()["jobs"]["departement"]["steps"]
        if "soumission" in etape.get("run", "")
    ]
    assert len(etapes) == 1
    assert etapes[0]["run"] == 'python -m pip install --quiet -e ".[soumission]"'
    assert etapes[0]["if"] == "matrix.dossier == 'm03-estimation'"


def test_l_extra_est_installe_apres_le_socle_et_avant_les_tests_du_departement():
    noms = [etape.get("name", "") for etape in _ci()["jobs"]["departement"]["steps"]]
    installation = noms.index("Extra soumission (ReportLab) pour M3")
    assert noms.index("Installation (socle + départements)") < installation
    assert installation < noms.index("Tests du département ${{ matrix.dossier }}")


def test_l_image_docker_installe_l_extra_soumission():
    dockerfile = (RACINE / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    ligne = next(ligne for ligne in dockerfile.splitlines() if 'pip install' in ligne and '/opt/opsys[' in ligne)
    extras = ligne.split("/opt/opsys[")[1].split("]")[0].split(",")
    assert "soumission" in extras


def test_l_extra_epingle_la_version_que_le_module_verifie_a_l_execution():
    extras = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    assert extras["soumission"] == [f"{soumission_pdf.NOM_BRIQUE}=={soumission_pdf.VERSION_BRIQUE}"]
    assert any(exigence.startswith("pypdf==") for exigence in extras["dev"]), "pypdf relit les PDF des tests"
    assert not any("reportlab" in exigence for exigence in extras["dev"]), "ReportLab reste optionnel"
