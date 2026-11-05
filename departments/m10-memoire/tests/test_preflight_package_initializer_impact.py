"""Régression API sur les imports de paquet; dépôt et données fictifs seulement."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from m10_memoire import developpement as memoire_dev

from opsys import contexte, identite, stockage

ADMIN = contexte.IdentiteAppelante("admin.fixture", "admin")


@pytest.fixture
def base_dev(tmp_path, monkeypatch):
    opsys_home = tmp_path / "opsys-home"
    opsys_home.mkdir()
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv("OPSYS_HOME", str(opsys_home))
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fixture", "Admin fictif", "fixture-password-123", ["admin"])
    try:
        yield tmp_path
    finally:
        stockage.liberer()


def _depot_git(path: Path, fichiers: dict[str, str] | None = None) -> Path:
    fichiers = fichiers or {
        "pkg/__init__.py": "from .service import run\n",
        "pkg/service.py": "def run():\n    return 1\n",
        "pkg/consumer.py": "import pkg.service\n\ndef execute():\n    return pkg.service.run()\n",
    }
    for name, text in fichiers.items():
        destination = path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["config", "user.email", "fixture@example.test"],
        ["config", "user.name", "Fixture"],
        ["add", "."],
        ["commit", "-qm", "fixture fictive"],
    ):
        subprocess.run(["git", "-C", str(path), *args], check=True)
    return path


def test_preflight_retourne_les_importeurs_du_package_initializer(base_dev):
    depot = _depot_git(base_dev / "depot-fictif")

    with contexte.appele_par_appareil(ADMIN):
        paquet = memoire_dev.preflight(
            "M10", "modifier le package", files=["pkg/__init__.py"], repository=depot
        )

    importeurs = {item["path"] for item in paquet["code_impact"]["importers"]}
    assert "pkg/consumer.py" in importeurs
    assert paquet["code_impact"]["truncated"] is False
    assert not any("racines d'import distinctes" in item for item in paquet["code_impact"]["limitations"])

    imports_cible = {item["path"] for item in paquet["code_impact"]["targets"][0]["imports"]}
    assert "pkg/service.py" in imports_cible
    assert "pkg/__init__.py" not in imports_cible


def test_preflight_relie_un_importeur_au_package_initializer_imbrique(base_dev):
    depot = _depot_git(
        base_dev / "depot-imbrique",
        {
            "pkg/__init__.py": "ROOT = True\n",
            "pkg/sub/__init__.py": "from .service import run\n",
            "pkg/sub/service.py": "def run():\n    return 1\n",
            "pkg/consumer.py": "import pkg.sub.service\n",
        },
    )

    with contexte.appele_par_appareil(ADMIN):
        paquet = memoire_dev.preflight(
            "M10", "modifier le sous-paquet", files=["pkg/sub/__init__.py"], repository=depot
        )

    impact = paquet["code_impact"]
    assert "pkg/consumer.py" in {item["path"] for item in impact["importers"]}
    imports_cible = {item["path"] for item in impact["targets"][0]["imports"]}
    assert "pkg/sub/service.py" in imports_cible
    assert "pkg/sub/__init__.py" not in imports_cible


def test_preflight_signale_une_collision_de_package_sans_choisir_initializer(base_dev):
    depot = _depot_git(
        base_dev / "depot-collision",
        {
            "pkg/__init__.py": "",
            "pkg/service.py": "",
            "src/pkg/__init__.py": "",
            "src/pkg/service.py": "",
            "consumer.py": "import pkg.service\n",
        },
    )

    with contexte.appele_par_appareil(ADMIN):
        paquet = memoire_dev.preflight(
            "M10", "modifier le package", files=["pkg/__init__.py"], repository=depot
        )

    impact = paquet["code_impact"]
    assert "consumer.py" not in {item["path"] for item in impact["importers"]}
    ambiguities = {(item["path"], item["module"]) for item in impact["ambiguous_imports"]}
    assert ("consumer.py", "pkg") in ambiguities
    assert ("consumer.py", "pkg.service") in ambiguities


def test_preflight_ne_lie_pas_des_racines_distinctes_et_garde_le_vrai_parent(base_dev):
    depot = _depot_git(
        base_dev / "depot-racines-distinctes",
        {
            "pkg/__init__.py": "ROOT = True\n",
            "src/pkg/sub/__init__.py": "from .service import run\n",
            "src/pkg/sub/service.py": "def run():\n    return 1\n",
            "consumer.py": "import pkg.sub.service\n",
        },
    )

    with contexte.appele_par_appareil(ADMIN):
        racine = memoire_dev.preflight(
            "M10", "modifier le package", files=["pkg/__init__.py"], repository=depot
        )
        sous_paquet = memoire_dev.preflight(
            "M10", "modifier le sous-paquet", files=["src/pkg/sub/__init__.py"], repository=depot
        )

    impact_racine = racine["code_impact"]
    assert "consumer.py" not in {item["path"] for item in impact_racine["importers"]}
    assert ("consumer.py", "pkg") in {
        (item["path"], item["module"]) for item in impact_racine["ambiguous_imports"]
    }
    assert any("racines d'import distinctes" in limitation for limitation in impact_racine["limitations"])
    assert impact_racine["truncated"] is True
    assert racine["truncated"] is True
    assert any("analyse d'impact statique incomplète" in item for item in racine["limitations"])
    assert "consumer.py" in {item["path"] for item in sous_paquet["code_impact"]["importers"]}
