"""Le préflight doit rendre visible l'incomplétude de son analyse d'impact jointe.

Fixtures locales fictives : aucun dépôt ni secret réel n'est lu.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from m10_memoire import developpement as memoire_dev
from m10_memoire import impact_code

from opsys import contexte, identite, stockage

ADMIN = contexte.IdentiteAppelante("admin.dev", "admin")
HORODATAGE = "2026-09-30T15:00:00+00:00"


@pytest.fixture
def base_dev(tmp_path, monkeypatch):
    opsys_home = tmp_path / "opsys-home"
    opsys_home.mkdir()
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv("OPSYS_HOME", str(opsys_home))
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "admin.dev", "Admin développement", "mot-de-passe-admin-dev-123", ["admin"]
        )
    try:
        yield tmp_path
    finally:
        stockage.liberer()


def _depot_git(path: Path, fichiers: dict[str, str]) -> Path:
    path.mkdir()
    for nom, texte in fichiers.items():
        destination = path / nom
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(texte, encoding="utf-8")
    for arguments in (
        ["init", "-q"],
        ["config", "user.email", "fixture@example.test"],
        ["config", "user.name", "Fixture"],
        ["add", "."],
        ["commit", "-qm", "fixture fictive"],
    ):
        subprocess.run(["git", "-C", str(path), *arguments], check=True)
    return path


def test_preflight_signale_une_analyse_impact_tronquee(base_dev, monkeypatch):
    depot = _depot_git(
        base_dev / "depot-impact",
        {
            "target.py": "def cible():\n    return 1\n",
            "a.py": "valeur = 1\n",
            "b.py": "valeur = 2\n",
            "c.py": "valeur = 3\n",
        },
    )
    monkeypatch.setattr(impact_code, "MAX_FICHIERS", 1)

    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "p-impact",
            "impact tronqué",
            version=1,
            module="M10",
            objectif="impact tronqué",
            horodatage=HORODATAGE,
        )
        paquet = memoire_dev.preflight(
            "M10", "impact tronqué", files=["target.py"], repository=depot
        )

    assert paquet["status"] == "available"
    assert paquet["code_impact"]["truncated"] is True
    assert paquet["code_impact"]["counts"]["files_omitted"] > 0
    assert paquet["truncated"] is True
    assert any(
        "analyse d'impact statique incomplète" in limitation
        for limitation in paquet["limitations"]
    )


def test_preflight_signale_une_analyse_impact_indisponible(base_dev):
    depot = base_dev / "pas-un-depot"
    depot.mkdir()
    (depot / "suivi.py").write_text("valeur = 1\n", encoding="utf-8")

    with contexte.appele_par_appareil(ADMIN):
        paquet = memoire_dev.preflight(
            "M10", "impact indisponible", files=["suivi.py"], repository=depot
        )

    assert paquet["code_impact"]["status"] == "unavailable"
    assert paquet["truncated"] is True
    assert any(
        "analyse d'impact statique indisponible" in limitation
        for limitation in paquet["limitations"]
    )
