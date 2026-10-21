"""Sources locales M7 pour affectations privées M5 ; SQLite et campagnes fictives."""

from urllib.parse import parse_qs, urlsplit

import pytest
from m7_marketing import local
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage.schema import REGISTRES


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'campagnes-fictives.db'}")
    stockage.liberer()
    stockage.migrer()
    resultat = local.proposer("flyer-fictif", "flyer", "Flyers <fictifs>", "2026-09-01", "2026-09-30", 100,
                              "https://exemple.invalid/flyers", "site", "referral")
    assert resultat["statut"] == "brouillon_propose"
    yield
    stockage.liberer()


def test_reader_public_fournit_reference_recalculee_et_utm_exact(source):
    lu = local.lire("flyer-fictif")
    source_couts = lu["source_couts"]
    lien = parse_qs(urlsplit(lu["lien_utm"]).query)
    assert source_couts["campagne_id"] == "flyer-fictif"
    assert source_couts["empreinte"] == lu["campagne"]["empreinte"]
    assert source_couts["utm_campaign"] == lien["utm_campaign"][0]
    assert source_couts["utm_source"] == "site"
    assert source_couts["utm_campaign"] != source_couts["campagne_id"]


def test_tamper_source_hors_campagne_recherchee_refuse(source):
    local.proposer("autre-fictive", "flyer", "Autre", "2026-09-01", "2026-09-30", 10,
                   "https://exemple.invalid/autre", "site", "referral")
    with stockage.transaction() as cnx:
        brut = cnx.execute(select(REGISTRES.c.maillon).where(REGISTRES.c.registre == "local_campaigns",
                                                            REGISTRES.c.rang == 1)).scalar_one()
        cnx.execute(update(REGISTRES).where(REGISTRES.c.registre == "local_campaigns", REGISTRES.c.rang == 1)
                    .values(maillon=brut.replace('"nom":"Autre"', '"nom":"Modifie"')))
    with pytest.raises(ValueError, match="LOCAL"):
        local.lire("flyer-fictif")


def test_borne_sql_avant_decodage(source):
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(REGISTRES.c.registre == "local_campaigns")
                    .values(maillon='{"non_decode":"' + "é" * 40_000 + '"}'))
    with pytest.raises(ValueError, match="LOCAL-BORNE"):
        local.lire("flyer-fictif")


def test_nombre_exposant_non_fini_refuse_avant_derivation(source, monkeypatch):
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(REGISTRES.c.registre == "local_campaigns")
                    .values(maillon='{"type":"campagne_locale","nombre":1e999}'))
    monkeypatch.setattr(local, "_source_couts", lambda _: pytest.fail("objet dérivé avant contrôle nombre fini"))
    with pytest.raises(ValueError, match="LOCAL-REGISTRE"):
        local.lire("flyer-fictif")
