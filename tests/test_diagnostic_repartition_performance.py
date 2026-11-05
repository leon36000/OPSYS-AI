from __future__ import annotations

import os
from pathlib import Path

import pytest
from m7_marketing import outils
from m7_marketing import performance_campagnes as performance
from sqlalchemy import text, update
from sqlalchemy.dialects import sqlite

from opsys import contexte, evenements, identite, stockage
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'm7-saturation-fictif.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin fictif", "mot-de-passe-fictif-123", ["admin"])
    yield
    stockage.liberer()


def _charge():
    return {
        "lead_id": "lead-fictif-repartition",
        "client_id": "a" * 64,
        "horodatage_association": "2026-09-10T12:00:00Z",
        "utm": {"utm_source": "source-fictive", "utm_campaign": "campagne-fictive"},
    }


def _publier(evenement_id="m2-client-associe-fictif-saturation", lead_id="lead-fictif-repartition"):
    evenements.publier(
        "m2.client_associe", "m02-revenue-crm", {**_charge(), "lead_id": lead_id},
        evenement_id=evenement_id,
    )


def _departement_m7():
    racine_env = os.environ.get("OPSYS_TEST_DEPARTMENTS_ROOT")
    racine = Path(racine_env) if racine_env else next(
        parent / "departments"
        for parent in Path(__file__).resolve().parents
        if (parent / "departments" / "m07-marketing" / "department.yaml").is_file()
    )
    tous = charger_departements(racine)
    return {"m07-marketing": tous["m07-marketing"]}


def _lecture():
    with stockage.transaction(), contexte.appele_par_appareil(
        contexte.IdentiteAppelante("admin.fictif", "admin", "console")
    ):
        return outils.lire_performance_campagnes("2026-09-01", "2026-09-30")


def test_recu_traite_est_visible_sans_charge_ni_couverture_certifiee(base):
    with stockage.transaction():
        _publier()
    resultat = evenements.repartir(_departement_m7(), maintenant="2026-09-11T12:00:00+00:00")
    assert resultat["traites"] == 1

    diagnostic = _lecture()["observation_source"]["repartition_sources"]
    assert diagnostic["couverture"] == "NON_CERTIFIEE"
    m2 = diagnostic["par_type_echantillonne"]["m2.client_associe"]
    assert m2 == {
        "publications": 1, "traite": 1, "echec": 0, "quarantaine": 0, "sans_recu": 0,
        "refus_saturation_lignes": 0, "refus_saturation_octets": 0,
    }
    assert "lead-fictif-repartition" not in repr(diagnostic)
    assert "campagne-fictive" not in repr(diagnostic)


@pytest.mark.parametrize(
    ("borne", "compteur"),
    [
        ("lignes", "refus_saturation_lignes"),
        ("octets", "refus_saturation_octets"),
    ],
)
def test_recu_echec_de_saturation_est_visible_sans_afficher_erreur_libre(base, monkeypatch, borne, compteur):
    with stockage.transaction():
        if borne == "lignes":
            monkeypatch.setattr(performance, "MAX_LIGNES", 1)
            _publier("m2-client-associe-fictif-a", "lead-fictif-a")
            _publier("m2-client-associe-fictif-b", "lead-fictif-b")
            cnx = stockage.connexion_courante()
            cnx.execute(
                update(EVENEMENTS_SORTANTS)
                .where(EVENEMENTS_SORTANTS.c.evenement_id == "m2-client-associe-fictif-a")
                .values(cree_le="2026-09-10T12:00:00+00:00")
            )
            cnx.execute(
                update(EVENEMENTS_SORTANTS)
                .where(EVENEMENTS_SORTANTS.c.evenement_id == "m2-client-associe-fictif-b")
                .values(cree_le="2026-09-10T12:00:01+00:00")
            )
        else:
            monkeypatch.setattr(performance, "MAX_OCTETS_TOTAL", 0)
            _publier()
    resultat = evenements.repartir(_departement_m7(), maintenant="2026-09-11T12:00:00+00:00")
    assert resultat["echecs"] == 1

    diagnostic = _lecture()["observation_source"]["repartition_sources"]
    m2 = diagnostic["par_type_echantillonne"]["m2.client_associe"]
    assert diagnostic["couverture"] == "NON_CERTIFIEE"
    assert m2["echec"] == 1
    assert m2[compteur] == 1
    autre_compteur = "refus_saturation_octets" if compteur == "refus_saturation_lignes" else "refus_saturation_lignes"
    assert m2[autre_compteur] == 0
    assert "PERFORMANCE_BORNE_LIGNES" not in repr(diagnostic)


def test_publication_sans_recu_est_distincte_de_la_liste_vide(base):
    with stockage.transaction():
        _publier()

    diagnostic = _lecture()["observation_source"]["repartition_sources"]
    m2 = diagnostic["par_type_echantillonne"]["m2.client_associe"]
    assert m2["publications"] == 1
    assert m2["sans_recu"] == 1
    assert m2["traite"] == 0
    assert diagnostic["couverture"] == "NON_CERTIFIEE"


def test_registre_a_la_borne_est_visible_sans_modifier_les_calculs(base, monkeypatch):
    monkeypatch.setattr(performance, "MAX_LIGNES", 1)
    with stockage.transaction():
        performance.enregistrer_fait(
            "m2.client_associe",
            {
                "lead_id": "lead-fictif-borne", "client_id": "b" * 64,
                "horodatage_association": "2026-09-10T12:00:00Z",
                "utm": {"utm_source": "source-fictive", "utm_campaign": "campagne-fictive"},
            },
        )

    observation = _lecture()["observation_source"]
    assert observation["capacite_registre"]["lignes"] == 1
    assert observation["capacite_registre"]["limite_lignes"] == 1
    assert observation["capacite_registre"]["limite_atteinte"] is True
    assert observation["repartition_sources"]["couverture"] == "NON_CERTIFIEE"


def test_echantillon_sql_est_borne_et_signale_une_troncature(base, monkeypatch):
    monkeypatch.setattr(performance, "MAX_LIGNES", 2)
    with stockage.transaction():
        for suffixe in ("a", "b", "c"):
            evenements.publier(
                "m2.client_associe", "m02-revenue-crm",
                {**_charge(), "lead_id": f"lead-fictif-{suffixe}"},
                evenement_id=f"m2-client-associe-fictif-{suffixe}",
            )

    diagnostic = _lecture()["observation_source"]["repartition_sources"]
    assert diagnostic["echantillon_tronque"] is True
    assert diagnostic["limite_echantillon"] == 2
    assert diagnostic["publications_echantillonnees"] == 2
    m2 = diagnostic["par_type_echantillonne"]["m2.client_associe"]
    assert m2["publications"] == 2
    assert diagnostic["couverture"] == "NON_CERTIFIEE"


def test_suffixe_apres_code_de_saturation_n_est_pas_compte(base):
    with stockage.transaction():
        _publier()
        evenement_id = "m2-client-associe-fictif-saturation"
        stockage.connexion_courante().execute(
            EVENEMENTS_RECUS.insert().values(
                evenement_id=evenement_id,
                consommateur="m07-marketing",
                statut="echec",
                tentatives=1,
                prochaine_tentative=None,
                resultat=None,
                derniere_erreur="ValueError: PERFORMANCE_BORNE_LIGNES_suffixe-faux",
            )
        )

    diagnostic = _lecture()["observation_source"]["repartition_sources"]
    m2 = diagnostic["par_type_echantillonne"]["m2.client_associe"]
    assert m2["echec"] == 1
    assert m2["refus_saturation_lignes"] == 0


def test_plan_sqlite_echantillonne_par_index_type_date_et_limite(base, monkeypatch):
    monkeypatch.setattr(performance, "MAX_LIGNES", 2)
    sql = str(performance._requete_diagnostic_repartition().compile(
        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert "LIMIT 3" in sql
    with stockage.transaction() as cnx:
        plan = cnx.execute(text("EXPLAIN QUERY PLAN " + sql)).all()
    texte = " ".join(str(ligne) for ligne in plan)
    assert "ix_evenements_sortants_type" in texte
    assert "SEARCH evenements_sortants" in texte
