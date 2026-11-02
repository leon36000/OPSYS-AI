"""Garde commune à tous les tests du dépôt : le socle (`tests/`) et chaque département."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _instance_isolee(tmp_path, monkeypatch):
    """Aucun test n'ouvre l'état ni la base de l'hôte (`~/.opsys`).

    Chaque test reçoit un `OPSYS_HOME` temporaire et aucune URL de base héritée. Un test qui a
    besoin d'une base la migre lui-même (voir `tests/test_stockage.py`). Les moteurs ouverts
    pendant le test sont libérés à la fin, pour ne garder aucun fichier ouvert d'un test à l'autre.
    """
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    monkeypatch.delenv("OPSYS_BASE_URL", raising=False)
    # Les tests valident des dizaines de milliers de transactions : la durabilité (FULL) n'y apporte rien et les ralentirait.
    monkeypatch.setenv("OPSYS_SQLITE_SYNCHRONOUS", "NORMAL")
    yield
    from opsys import stockage

    stockage.liberer()


@pytest.fixture(autouse=True)
def _voie_libre_m3_essai(monkeypatch):
    """Voie d'ESSAI de M3 (M3-C1) : les tests historiques passent encore barème, quantité et plancher en arguments.

    Cette variable d'environnement du serveur, avec un appel qui ne vient pas du MCP, est la seule façon d'ouvrir cette
    voie (`m3_estimation.outils_bareme.voie_libre_autorisee`). Un test qui vérifie le refus d'un barème libre la retire
    (`monkeypatch.delenv("OPSYS_M3_VOIE_LIBRE")`). Jamais posée par l'installateur ni par le conteneur."""
    monkeypatch.setenv("OPSYS_M3_VOIE_LIBRE", "essai")


@pytest.fixture
def declarer_services():
    """Fabrique : écrit le profil d'entreprise de l'instance de test (`$OPSYS_HOME/entreprise.yaml`).

    Sans argument, déclare les quatre services du catalogue de référence (`opsys.taxonomie`) ;
    sinon, les services donnés (codes du catalogue, ou objets `{code, libelle}`). Sans cet appel,
    l'instance de test n'a aucun service déclaré et la taxonomie refuse tout (fail-closed).
    """

    def _declarer(*services):
        from opsys import taxonomie

        return taxonomie.enregistrer_services(services or taxonomie.codes_catalogue())

    return _declarer
