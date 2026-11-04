"""Qualification M10-11 statique; toutes les sources sont des fixtures locales jetables."""

import subprocess
from pathlib import Path

from m10_memoire import developpement, impact_code


def _repo(path: Path, files: dict[str, str], symlinks: dict[str, str] | None = None) -> Path:
    for name, text in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for name, target_name in (symlinks or {}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(target_name)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "fixture@example.test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return path


def _analyse(path: Path, targets: list[str]) -> dict:
    return impact_code.analyser(
        path,
        targets,
        lire=developpement._lire_fichier_borne,
        chemin_interdit=developpement._chemin_interdit,
    )


def test_symlink_et_chemin_clients_interdit_ne_deviennent_pas_importeurs(tmp_path):
    repo = _repo(
        tmp_path / "repo",
        {
            "app/target.py": "def target(): return 1\n",
            "app/real.py": "from app.target import target\n",
            "clients/private.py": "from app.target import target\n# PRIVATE_CANARY\n",
        },
        {"app/linked.py": "real.py"},
    )
    result = _analyse(repo, ["app/target.py"])
    paths = {item["path"] for item in result["importers"]}
    assert "app/real.py" in paths
    assert "app/linked.py" not in paths
    assert "clients/private.py" not in paths
    assert any(item["path"] == "app/linked.py" for item in result["errors"])
    assert result["truncated"] is True


def test_importeurs_transitifs_sont_lies_avec_distance_et_collision_reste_inconnue(
    tmp_path,
):
    repo = _repo(
        tmp_path / "repo",
        {
            "pkg/target.py": "def target(): return 1\n",
            "pkg/middle.py": "from pkg.target import target\n",
            "pkg/outer.py": "from pkg.middle import target\n",
            "pkg/collision_user.py": "import pkg.target\n",
        },
    )
    result = _analyse(repo, ["pkg/target.py"])
    paths = {item["path"]: item["distance"] for item in result["importers"]}
    assert paths.get("pkg/middle.py") == 1
    assert paths.get("pkg/outer.py") == 2


def test_collision_module_est_signalee_sans_choisir_un_fichier(tmp_path):
    repo = _repo(
        tmp_path / "repo",
        {
            "pkg/target.py": "def target(): return 1\n",
            "src/pkg/target.py": "def duplicate(): return 2\n",
            "pkg/collision_user.py": "import pkg.target\n",
        },
    )
    result = _analyse(repo, ["pkg/target.py"])
    assert "pkg/collision_user.py" not in {item["path"] for item in result["importers"]}
    assert any(
        item["path"] == "pkg/collision_user.py" and item["module"] == "pkg.target"
        for item in result["ambiguous_imports"]
    )


def test_plafond_fichiers_signale_les_omissions_et_priorise_la_cible(tmp_path, monkeypatch):
    repo = _repo(
        tmp_path / "repo",
        {
            "a.py": "def a(): pass\n",
            "b.py": "def b(): pass\n",
            "z_target.py": "def target(): pass\n",
            "z_consumer.py": "from z_target import target\n",
            "department.yaml": "schema: opsys.departement/v1\n",
        },
    )
    monkeypatch.setattr(impact_code, "MAX_FICHIERS", 3)
    result = _analyse(repo, ["z_target.py"])
    assert result["targets"][0]["status"] == "parsed"
    assert result["counts"]["files_omitted"] == 2
    assert result["truncated"] is True
    assert "z_consumer.py" not in {item["path"] for item in result["importers"]}


def test_plafond_octets_et_limite_sortie_sont_visibles(tmp_path, monkeypatch):
    repo = _repo(
        tmp_path / "repo",
        {
            "target.py": "x = 1\n",
            "large.py": "# " + "x" * 50 + "\n",
            **{f"tests/test_{i:02}.py": "import target\n" for i in range(25)},
        },
    )
    monkeypatch.setattr(impact_code, "MAX_OCTETS_FICHIER", 18)
    monkeypatch.setattr(impact_code, "MAX_ITEMS", 5)
    result = _analyse(repo, ["target.py"])
    assert result["counts"]["files_examined"] <= 500
    assert result["limits"]["items"] == 5
    assert result["counts"]["importers_omitted"] > 0
    assert result["counts"]["importer_traversal_truncated"] is True
    assert result["truncated"] is True
    assert result["errors"]


def test_plafonds_cibles_symboles_et_sortie_dynamic_sont_signales(tmp_path, monkeypatch):
    files = {f"mod{i:02}.py": "".join(f"def f{j:02}(): pass\n" for j in range(12)) for i in range(12)}
    files.update({f"dyn{i:02}.py": "import importlib\nimportlib.import_module('x')\n" for i in range(12)})
    repo = _repo(tmp_path / "repo", files)
    monkeypatch.setattr(impact_code, "MAX_TARGETS", 10)
    monkeypatch.setattr(impact_code, "MAX_SYMBOLS_PAR_CIBLE", 10)
    monkeypatch.setattr(impact_code, "MAX_ITEMS", 5)
    result = _analyse(repo, [f"mod{i:02}.py" for i in range(12)])
    assert len(result["targets"]) == 10
    assert result["counts"]["targets_omitted"] == 2
    assert result["targets"][0]["symbols_omitted"] == 2
    assert len(result["targets"][0]["symbols"]) == 10
    assert len(result["dynamic_imports"]) == 5
    assert result["counts"]["dynamic_imports"] == 12
    assert result["truncated"] is True


def test_toutes_les_troncatures_de_chemins_et_noms_sont_signalees(tmp_path):
    parts = [
        "segmentalpha_longpkg",
        "segmentbravo_longpkg",
        "segmentcharlie_longpkg",
        "segmentdelta_longpkg",
    ]
    package = "/".join(parts)
    module = ".".join(parts)
    route_name = "m7_route_" + "n" * 56
    handler = "handler_" + "h" * 56
    files = {
        f"src/{package}/target.py": (f"from .helpers import helper\ndef {'symbol_' + 's' * 56}(): return helper()\n"),
        f"src/{package}/helpers.py": "def helper(): return 1\n",
        f"src/{package}/routes.py": (
            f"from . import target\ndef {handler}(): return target.helper()\n"
            f"def routes(): return (Outil(nom={route_name!r}, fonction={handler}),)\n"
        ),
        f"tests/{package}/test_target.py": (
            f"import importlib\nfrom {module}.target import helper\n"
            "def test_target(): return helper()\nimportlib.import_module('runtime.route')\n"
        ),
        f"errors/{package}/broken.py": "this is not valid Python !\n",
        f"src/{package}/dupe.py": "value = 1\n",
        f"{package}/dupe.py": "value = 2\n",
        f"{package}/ambiguous_user.py": f"import {module}.dupe\n",
        f"docs/{package}/department.yaml": f"schema: opsys.departement/v1\noutils: {module}.routes\n",
        f"docs/configuration_longue/{package}/department.yaml": (
            "schema: opsys.departement/v1\noutils: " + "missing." + ".".join(parts) + "\n"
        ),
    }
    repo = _repo(tmp_path / "repo", files)
    target = f"src/{package}/target.py"
    result = _analyse(repo, [target])

    assert result["targets"][0]["path_truncated"] is True
    assert result["targets"][0]["symbols"][0]["name_truncated"] is True
    assert result["targets"][0]["imports"][0]["path_truncated"] is True
    assert any(item["path_truncated"] for item in result["importers"])
    assert any(item["path_truncated"] for item in result["tests"])
    assert any(item["path_truncated"] for item in result["dynamic_imports"])
    assert any(item["path_truncated"] for item in result["errors"])
    assert any(item["path_truncated"] and item["module_truncated"] for item in result["ambiguous_imports"])
    route = next(item for item in result["routes"] if item["name"].startswith("m7_route_"))
    assert route["name_truncated"] is True
    assert route["handler_truncated"] is True
    assert route["manifest_truncated"] is True
    assert route["provider_truncated"] is True
    gap = next(item for item in result["manifest_gaps"] if item["provider"].startswith("missing."))
    assert gap["manifest_truncated"] is True
    assert gap["provider_truncated"] is True


def test_files_examined_compte_les_lectures_reelles_sous_budget_global(tmp_path, monkeypatch):
    files = {f"src/module_{index:03}.py": "x" for index in range(500)}
    files["src/target.py"] = "x"
    repo = _repo(tmp_path / "repo", files)
    monkeypatch.setattr(impact_code, "MAX_OCTETS_TOTAL", 1)
    lus = []

    def lire(repository, relative, limite):
        lus.append(relative.as_posix())
        return developpement._lire_fichier_borne(repository, relative, limite)

    result = impact_code.analyser(
        repo,
        ["src/target.py"],
        lire=lire,
        chemin_interdit=developpement._chemin_interdit,
    )

    assert lus == ["src/target.py"]
    assert result["counts"]["files_examined"] == 1
    assert result["counts"]["files_selected"] == 500
    assert result["counts"]["files_omitted"] == 500
