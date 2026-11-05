from __future__ import annotations

import importlib
from datetime import date

import pytest
from m7_marketing import performance_campagnes as performance
from pg_parite import base_pg, serveur_pg  # noqa: F401
from sqlalchemy import text

from opsys import stockage
from opsys.stockage.schema import REGISTRES


@pytest.fixture(autouse=True)
def base(base_pg, monkeypatch):  # noqa: F811
    moteur = importlib.import_module("opsys.stockage.moteur")
    stockage.liberer()
    monkeypatch.setenv(stockage.ENV_URL, base_pg)
    monkeypatch.setattr(moteur, "url_base", lambda: base_pg)
    monkeypatch.setattr(stockage, "url_base", lambda: base_pg)
    yield
    stockage.liberer()


def test_plan_postgresql_applique_limit_aux_candidats_avant_lecture_des_recus(monkeypatch):
    monkeypatch.setattr(performance, "MAX_LIGNES", 7)
    requete = performance._requete_diagnostic_repartition()
    with stockage.transaction() as cnx:
        sql = str(requete.compile(dialect=cnx.dialect, compile_kwargs={"literal_binds": True}))
        assert sql.count("LIMIT 8") >= 4
        plan = cnx.execute(text("EXPLAIN " + sql)).scalars().all()

    texte = "\n".join(plan)
    assert "Limit" in texte
    assert "evenements_sortants" in texte
    assert "evenements_recus" in texte


def test_lecteur_postgresql_lit_un_prefixe_valide_et_refuse_apres_la_borne(monkeypatch):
    with stockage.transaction():
        for suffixe in ("a", "b"):
            performance.enregistrer_fait("m2.client_associe", {
                "lead_id": f"lead-fictif-{suffixe}",
                "client_id": "c" * 64,
                "source": "source-fictive",
                "campagne": "campagne-fictive",
                "horodatage_association": "2026-09-10T12:00:00Z",
            })
    resultat = performance.lire_performance(date(2026, 9, 1), date(2026, 9, 30))
    assert resultat["observation_source"]["lignes_lues"] == 2

    monkeypatch.setattr(performance, "MAX_LIGNES", 2)
    with stockage.transaction() as cnx:
        cnx.execute(REGISTRES.delete().where(
            (REGISTRES.c.departement == performance.REGISTRE[0])
            & (REGISTRES.c.registre == performance.REGISTRE[1])
        ))
        cnx.execute(REGISTRES.insert(), [
            {"departement": performance.REGISTRE[0], "registre": performance.REGISTRE[1],
             "rang": rang, "maillon": "charge-invalide-non-decodee"}
            for rang in range(3)
        ])
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_LIGNES"):
        performance.lire_performance(date(2026, 9, 1), date(2026, 9, 30))
