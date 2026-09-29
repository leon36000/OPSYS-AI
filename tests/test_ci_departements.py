"""La CI teste chaque département : la matrice du job `departement` de `.github/workflows/ci.yml`
doit nommer exactement les dossiers de `departments/`. Un département ajouté sans entrée dans la
matrice ne serait jamais testé par la CI.

Le lint (PLAN T5.1) est activé département par département : la liste `DEPARTEMENTS_LINT` du job ne
contient que des départements déjà propres selon `ruff`. Un département absent de la liste n'est
pas linté ; un département listé mais sale ferait échouer la CI, donc ce fichier le détecte avant."""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]
CONDITION_LINT = "contains(fromJSON(env.DEPARTEMENTS_LINT), matrix.dossier)"


def _ci() -> dict:
    return yaml.safe_load((RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _dossiers_departements() -> list[str]:
    return sorted(p.name for p in (RACINE / "departments").iterdir() if (p / "department.yaml").is_file())


def _departements_lintes() -> list[str]:
    return json.loads(_ci()["jobs"]["departement"]["env"]["DEPARTEMENTS_LINT"])


def _etape_lint() -> dict:
    etapes = [e for e in _ci()["jobs"]["departement"]["steps"] if e.get("name", "").startswith("Lint du département")]
    assert len(etapes) == 1
    return etapes[0]


def _commande_ruff() -> list[str] | None:
    """`ruff` du même environnement Python que les tests, sinon celui du PATH ; None s'il manque."""
    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    binaire = shutil.which("ruff")
    return [binaire] if binaire else None


def _ruff_check(*chemins: str | Path) -> subprocess.CompletedProcess:
    commande = _commande_ruff()
    if commande is None:
        pytest.skip("ruff n'est pas installé dans cet environnement (la CI l'installe via `.[dev]`)")
    return subprocess.run(
        [*commande, "check", "--no-cache", "--config", str(RACINE / "pyproject.toml"), *map(str, chemins)],
        cwd=RACINE,
        capture_output=True,
        text=True,
        check=False,
    )


def test_la_matrice_ci_couvre_exactement_les_departements():
    matrice = _ci()["jobs"]["departement"]["strategy"]["matrix"]["dossier"]
    assert sorted(matrice) == _dossiers_departements()
    assert len(matrice) == len(set(matrice))


def test_gates_exige_le_succes_de_chaque_job_requis():
    gates = _ci()["jobs"]["gates"]
    assert set(gates["needs"]) == {"socle", "departement", "m03-preuves"}
    assert gates["if"] == "always()"
    commandes = "\n".join(etape.get("run", "") for etape in gates["steps"])
    for job in gates["needs"]:
        assert f'needs.{job}.result }}}}" = "success"' in commandes


def test_la_liste_de_lint_nomme_des_departements_existants_de_la_matrice_sans_doublon():
    lintes = _departements_lintes()
    assert lintes, "la liste de lint ne peut pas être vide : T5.1 est amorcée avec M7 à M10"
    assert len(lintes) == len(set(lintes))
    matrice = _ci()["jobs"]["departement"]["strategy"]["matrix"]["dossier"]
    assert sorted(set(lintes) - set(_dossiers_departements())) == []
    assert sorted(set(lintes) - set(matrice)) == []


def test_l_etape_de_lint_ne_vise_que_le_departement_de_la_matrice_et_seulement_s_il_est_liste():
    etape = _etape_lint()
    assert etape["if"] == CONDITION_LINT
    assert etape["run"] == 'ruff check "departments/${{ matrix.dossier }}"'
    noms = [e.get("name", "") for e in _ci()["jobs"]["departement"]["steps"]]
    # Lint avant les tests : un avertissement échoue vite, sans attendre la suite du département.
    assert noms.index(etape["name"]) < noms.index("Tests du département ${{ matrix.dossier }}")


def test_aucune_autre_etape_ne_linte_un_departement():
    """Le socle lint `src tests` ; seul le pas conditionné ci-dessus lint un département."""
    autorisees = {"ruff check src tests", 'ruff check "departments/${{ matrix.dossier }}"'}
    for nom_job, job in _ci()["jobs"].items():
        for etape in job["steps"]:
            for ligne in etape.get("run", "").splitlines():
                if re.search(r"\bruff\b", ligne):
                    assert ligne.strip() in autorisees, (nom_job, ligne)


def test_le_job_socle_lint_toujours_le_socle():
    commandes = [e.get("run", "") for e in _ci()["jobs"]["socle"]["steps"]]
    assert "ruff check src tests" in commandes


def test_chaque_departement_de_la_liste_de_lint_est_propre_selon_ruff():
    for dossier in _departements_lintes():
        resultat = _ruff_check(RACINE / "departments" / dossier)
        assert resultat.returncode == 0, f"{dossier} n'est pas propre :\n{resultat.stdout}{resultat.stderr}"


def test_le_controle_ruff_detecte_un_avertissement(tmp_path):
    """Garde contre un faux vert : le même appel doit échouer sur un fichier qui viole la règle."""
    sale = tmp_path / "sale.py"
    sale.write_text("import os\n", encoding="utf-8")
    resultat = _ruff_check(sale)
    assert resultat.returncode != 0
    assert "F401" in resultat.stdout


def test_les_outils_de_preuve_de_m3_tournent_une_fois_et_une_seule():
    """Le job de M3 les écarte, `m03-preuves` les exécute : aucun des deux fichiers n'est oublié ni joué deux fois."""
    ci = _ci()
    parts = ci["jobs"]["m03-preuves"]["strategy"]["matrix"]["include"]
    fichiers = sorted({p["fichier"] for p in parts})
    assert fichiers == ["test_gardes_des_outils.py", "test_outils_de_preuve.py"]
    for fichier in fichiers:  # chaque part de 0 à parts-1 exactement une fois, un seul nombre de parts
        du_fichier = [p for p in parts if p["fichier"] == fichier]
        (total,) = {p["parts"] for p in du_fichier}
        assert sorted(p["part"] for p in du_fichier) == list(range(total))
    for fichier in fichiers:
        assert (RACINE / "departments" / "m03-estimation" / "tests" / fichier).is_file()
    nom = "Tests du département ${{ matrix.dossier }}"
    etape = next(e for e in ci["jobs"]["departement"]["steps"] if e.get("name") == nom)
    for fichier in fichiers:
        assert f"departments/m03-estimation/tests/{fichier}" in etape["run"]
    assert "matrix.dossier == 'm03-estimation'" in etape["run"]
