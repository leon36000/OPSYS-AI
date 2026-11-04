"""Cycle de constats M8 sur PostgreSQL réel, avec plusieurs jours simulés et des jeux fictifs.

Le conteneur PostgreSQL 17 et la base sont fournis par `pg_parite`; l'horloge du vrai planificateur
est avancée explicitement, sans attente murale ni service tiers. Ce scénario complète les rejeux
unitaires PostgreSQL qui testent déjà les grands sauts et reprises.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import planif_m8_monde as pm
import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import create_engine, text

from opsys import horloge, stockage

_RAISON_SANS_DOCKER = raison_sans_docker()
pytestmark = pytest.mark.skipif(_RAISON_SANS_DOCKER is not None, reason=str(_RAISON_SANS_DOCKER))

JOUR = 24 * 60 * 60
_SOURCE_TEST = Path(__file__).with_name("test_entrepot_m8_planifie.py")
_SPEC = importlib.util.spec_from_file_location("m8_entrepot_attentes", _SOURCE_TEST)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE_ATTENDU = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE_ATTENDU)
ATTENDU = _MODULE_ATTENDU.ATTENDU


@pytest.fixture
def monde_postgres(tmp_path, monkeypatch, declarer_services):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        base_pg = url.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, base_pg)
        monde = None
        montage_tente = False
        try:
            stockage.migrer(base_pg)

            moteur = create_engine(base_pg)
            try:
                with moteur.connect() as cnx:
                    version = int(cnx.execute(text("SELECT current_setting('server_version_num')")).scalar_one())
                assert version // 10000 == 17
            finally:
                moteur.dispose()

            montage_tente = True
            monde = pm.monter(tmp_path, monkeypatch, declarer_services, url=base_pg)
            corpus = pm.lire_yaml(pm.RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml")
            pm.semer_tout(monde, corpus)
            yield monde
        finally:
            try:
                if montage_tente:
                    pm.demonter()
            finally:
                stockage.liberer(base_pg)


def _compte_faits_m8(monde, nom: str) -> int:
    with stockage.transaction():
        return len(stockage.maillons(pm.M8, nom))


def test_cycle_planifie_sur_trois_jours_locaux_postgresql(monde_postgres):
    monde = monde_postgres
    monde.activer("actif")

    horodatages_locaux: list[str] = []
    nombre_evenements_cash: list[int] = []
    faits_m8_apres_rejeu: list[int] = []

    for jour in range(3):
        resume = monde.tour(1 if jour == 0 else JOUR)
        assert set(resume) == set(pm.CONSTATS)
        assert all(v["statut"] == "ok" for v in resume.values()), resume

        local = dt.datetime.fromtimestamp(monde.horloge(), dt.UTC).astimezone(ZoneInfo(horloge.FUSEAU_ENTREPRISE))
        horodatages_locaux.append(local.date().isoformat())
        assert len(set(horodatages_locaux)) == jour + 1

        monde.propager(pm.M8, pm.M9, pm.M10)
        mesures = monde.mesures()
        for metric_id, valeur in ATTENDU.items():
            assert mesures[metric_id]["statut"] == "calculee", (jour, metric_id, mesures[metric_id])
            assert mesures[metric_id]["valeur"] == valeur, (jour, metric_id, mesures[metric_id])

        sortants = monde.publies()
        ids = [e["evenement_id"] for e in sortants]
        assert len(ids) == len(set(ids)), (jour, "identifiants sortants dupliqués")
        charges_constats = [e["charge"] for e in sortants if e["type_evenement"] in pm.CONSTATS.values()]
        charges = json.dumps(charges_constats, ensure_ascii=False, sort_keys=True)
        assert all(terme not in charges for terme in pm.PERSONNEL), (jour, "charge de constat nominative")
        nombre_evenements_cash.append(monde.nombre_publie().get("m5.cash_libre_constate", 0))
        assert nombre_evenements_cash[-1] == jour + 1

        faits_apres_passage = _compte_faits_m8(monde, "faits_cash_libre")
        monde.propager(pm.M8, pm.M9, pm.M10)
        faits_m8_apres_rejeu.append(_compte_faits_m8(monde, "faits_cash_libre"))
        assert faits_m8_apres_rejeu[-1] == faits_apres_passage == jour + 1

        with stockage.transaction() as cnx:
            lignes = {n: pm.etat.ligne(cnx, n) for n in pm.CONSTATS}
        assert all(ligne["prochain_passage"] > int(monde.horloge()) for ligne in lignes.values()), lignes

    assert horodatages_locaux == sorted(set(horodatages_locaux))
    assert nombre_evenements_cash == [1, 2, 3]
    assert faits_m8_apres_rejeu == [1, 2, 3]
