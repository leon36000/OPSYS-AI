"""Fixtures des tests de bout en bout de T1.5 : le moteur réel (base temporaire, dix départements,
application HTTP MCP sur un vrai uvicorn), une horloge de test, et les deux personnes du scénario."""

from __future__ import annotations

import contextlib

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from harnais_e2e import Horloge, Moteur
from harnais_e2e_chantier import debut_de_journee
from memoire.doubles import postgres_ephemere, raison_sans_docker

from opsys import stockage
from opsys.serveur_mcp import ENV_REPARTITEUR

_SANS_DOCKER = raison_sans_docker()


@contextlib.contextmanager
def _url_de_base(tmp_path, moteur_sql: str):
    if moteur_sql == "sqlite":
        yield f"sqlite:///{tmp_path / 'opsys-e2e.db'}"
        return
    with postgres_ephemere() as url_pg:
        yield url_pg.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(params=[
    "sqlite",
    pytest.param("postgresql", marks=pytest.mark.skipif(
        _SANS_DOCKER is not None, reason=f"PostgreSQL réel indisponible : {_SANS_DOCKER}")),
])
def moteur(request, tmp_path, monkeypatch):
    """Le moteur réel sur SQLite, et sur PostgreSQL quand docker répond (sinon sauté, jamais un faux vert).

    Le répartiteur de fond du serveur est éteint : les tests livrent le bus eux-mêmes, sans sommeil."""
    monkeypatch.setenv(ENV_REPARTITEUR, "0")
    with _url_de_base(tmp_path, request.param) as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        m2_outils.utiliser_stockage_durable()
        m5_outils.utiliser_stockage_durable()
        horloge = Horloge(debut_de_journee(15))
        horloge.installer(monkeypatch)
        instance = Moteur(tmp_path, url)
        instance.horloge = horloge
        instance.demarrer()
        try:
            yield instance
        finally:
            instance.arreter()
            m2_outils.reinitialiser_registre()
            stockage.liberer()


@pytest.fixture
def equipe(moteur, monkeypatch):
    """Nathan (propriétaire, appareil `admin`) et Étienne (employé, appareil `employee`), créés et appairés
    par les commandes réelles du socle."""
    moteur.creer_personne("nathan", "Nathan St-Louis (fictif)", ["nathan_owner", "admin"], monkeypatch)
    moteur.creer_personne("etienne", "Étienne Bouchard (fictif)", ["employee"], monkeypatch)
    return {
        "admin": moteur.appairer("nathan", "admin"),
        "employe": moteur.appairer("etienne", "employee"),
    }
