"""Tests M5.4.c. Toutes les captures de ces fixtures sont des octets synthétiques, jamais des tables officielles."""
from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import sources_regles_paie

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique

FICTIF = True
DEPARTEMENT = "m05-financecore"
OWNER_CONSOLE = contexte.IdentiteAppelante("nathan", "nathan_owner", source="console")
ADMIN_APPAREIL = contexte.IdentiteAppelante("nathan", "admin")
EMPLOYEE_APPAREIL = contexte.IdentiteAppelante("employee.fictif", "employee")


def _query(**overrides):
    values = {
        "juridiction": "QC",
        "date_paie": "2026-06-30",
        "periode_debut": "2026-06-15",
        "periode_fin": "2026-06-28",
        "fuseau": "America/Montreal",
        "frequence": "bihebdomadaire",
    }
    values.update(overrides)
    return values


def _source(tmp_path: Path, identifiant: str, debut: str, fin: str | None, *, statut="QUALIFIEE", contenu=b"FICTIF"):
    relative = f"snapshots/{identifiant}.bin"
    cible = tmp_path / relative
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(contenu)
    return {
        "id": identifiant,
        "juridiction": "QC",
        "composant": "federal",
        "document": "Fixture synthétique, sans taux",
        "edition": identifiant,
        "applicable_du": debut,
        "applicable_au": fin,
        "url": "https://example.invalid/fixture",
        "capture_path": relative,
        "sha256": hashlib.sha256(contenu).hexdigest(),
        "statut": statut,
        "portee_statut": "Fixture synthétique uniquement; aucune certification fiscale.",
        "frequences": ["bihebdomadaire"],
    }


def _catalogue(sources):
    return {
        "schema_version": 1,
        "juridictions": {"QC": {"composants_requis": ["federal"]}},
        "sources": sources,
    }


def _evaluer(catalogue, tmp_path, **query):
    return sources_regles_paie.evaluer_sources(
        catalogue, racine=tmp_path, **_query(**query),
    )


def test_frontieres_de_date_selectionnent_une_seule_edition_avec_intervalle_inclusif(tmp_path):
    sources = [
        _source(tmp_path, "janvier", "2026-01-01", "2026-06-30"),
        _source(tmp_path, "juillet", "2026-07-01", "2026-12-31"),
    ]
    catalogue = _catalogue(sources)

    veille, refus_veille = _evaluer(catalogue, tmp_path, date_paie="2026-06-30")
    debut, refus_debut = _evaluer(catalogue, tmp_path, date_paie="2026-07-01")
    fin, refus_fin = _evaluer(catalogue, tmp_path, date_paie="2026-12-31")

    assert refus_veille is refus_debut is refus_fin is None
    assert veille["sources_verifiees"][0]["id"] == "janvier"
    assert debut["sources_verifiees"][0]["id"] == "juillet"
    assert fin["sources_verifiees"][0]["id"] == "juillet"
    assert veille["periode"] == {
        "debut": "2026-06-15", "fin": "2026-06-28", "fuseau": "America/Montreal",
    }


def test_chevauchement_est_refuse_avec_code_nomme(tmp_path):
    catalogue = _catalogue([
        _source(tmp_path, "a", "2026-01-01", "2026-12-31"),
        _source(tmp_path, "b", "2026-06-01", "2026-12-31"),
    ])
    resultat, refus = _evaluer(catalogue, tmp_path)
    assert resultat is None
    assert refus["code"] == "REJ-PAIE-SOURCE-AMBIGUE"


def test_formule_et_guide_complementaires_ne_sont_pas_des_editions_concurrentes(tmp_path):
    formule = _source(tmp_path, "formule", "2026-01-01", "2026-12-31")
    formule["composant"] = "quebec"
    guide = _source(tmp_path, "guide", "2026-01-01", "2026-12-31")
    guide["composant"] = "quebec_guide"
    catalogue = {"schema_version": 1, "juridictions": {"QC": {"composants_requis": ["quebec"]}},
                 "sources": [formule, guide]}

    resultat, refus = _evaluer(catalogue, tmp_path)

    assert refus is None
    assert [source["id"] for source in resultat["sources_verifiees"]] == ["formule"]
    assert {source["id"] for source in resultat["references_catalogue"]} == {"formule", "guide"}


def test_deux_editions_de_la_formule_f_qui_se_chevauchent_sont_ambigues(tmp_path):
    editions = [
        _source(tmp_path, "formule_ancienne", "2026-01-01", "2026-06-30"),
        _source(tmp_path, "formule_chevauchante", "2026-06-30", "2026-12-31"),
    ]
    for edition in editions:
        edition["composant"] = "quebec"
    catalogue = {"schema_version": 1, "juridictions": {"QC": {"composants_requis": ["quebec"]}},
                 "sources": editions}

    resultat, refus = _evaluer(catalogue, tmp_path, date_paie="2026-06-30")

    assert resultat is None
    assert refus["code"] == "REJ-PAIE-SOURCE-AMBIGUE"


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ({"date_paie": "2027-01-01"}, "REJ-PAIE-EDITION-ABSENTE"),
        ({"date_paie": "2026-06-30T00:00:00Z"}, "REJ-PAIE-DATE-INVALIDE"),
        ({"date_paie": "2026-6-30"}, "REJ-PAIE-DATE-INVALIDE"),
        ({"fuseau": "Mars/Olympus"}, "REJ-PAIE-FUSEAU-INVALIDE"),
        ({"fuseau": ""}, "REJ-PAIE-FUSEAU-INVALIDE"),
        ({"periode_debut": "2026-06-29"}, "REJ-PAIE-PERIODE-INVALIDE"),
        ({"periode_debut": "2026-05-01", "periode_fin": "2026-06-15"}, "REJ-PAIE-PERIODE-INVALIDE"),
        ({"juridiction": "ON"}, "REJ-PAIE-JURIDICTION-NON-COUVERTE"),
        ({"frequence": "chaque-fois"}, "REJ-PAIE-FREQUENCE-INVALIDE"),
    ],
)
def test_criteres_fermes_refusent_sans_table(query, code, tmp_path):
    catalogue = _catalogue([_source(tmp_path, "janvier", "2026-01-01", "2026-12-31")])
    resultat, refus = _evaluer(catalogue, tmp_path, **query)
    assert resultat is None
    assert refus["code"] == code


def test_source_partielle_reste_partielle_et_ne_devient_pas_resolue(tmp_path):
    catalogue = _catalogue([_source(tmp_path, "janvier", "2026-01-01", "2026-12-31", statut="NON_QUALIFIEE")])
    resultat, refus = _evaluer(catalogue, tmp_path)
    assert refus is None
    assert resultat["statut"] == "PARTIEL"
    assert resultat["sources_verifiees"] == []
    assert resultat["manques"][0]["code"] == "REJ-PAIE-SOURCE-NON-QUALIFIEE"
    assert "montant" not in resultat and "taux" not in resultat


def test_intervalle_edition_absent_est_refuse(tmp_path):
    catalogue = _catalogue([_source(tmp_path, "juillet", "2026-07-01", None)])
    resultat, refus = _evaluer(catalogue, tmp_path, date_paie="2026-07-01")
    assert refus is None
    assert resultat["statut"] == "PARTIEL"
    assert resultat["sources_verifiees"] == []
    assert resultat["manques"][0]["code"] == "REJ-PAIE-INTERVALLE-ABSENT"


def test_sha_divergent_est_refuse_apres_capture(tmp_path):
    source = _source(tmp_path, "janvier", "2026-01-01", "2026-12-31")
    (tmp_path / source["capture_path"]).write_bytes(b"modified")
    resultat, refus = _evaluer(_catalogue([source]), tmp_path)
    assert resultat is None
    assert refus["code"] == "REJ-PAIE-SHA-DIVERGENT"


def test_chemin_source_hors_racine_est_refuse(tmp_path):
    source = _source(tmp_path, "janvier", "2026-01-01", "2026-12-31")
    source["capture_path"] = "../../outside.bin"
    resultat, refus = _evaluer(_catalogue([source]), tmp_path)
    assert resultat is None
    assert refus["code"] == "REJ-PAIE-CHEMIN-INVALIDE"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda catalogue: catalogue.update(schema_version=1.0),
        lambda catalogue: catalogue["sources"][0].update(statut=[]),
        lambda catalogue: catalogue["sources"][0].update(frequences=[{}]),
        lambda catalogue: catalogue["sources"][0].update(capture_path=[]),
        lambda catalogue: catalogue["sources"][0].update(sha256=[]),
    ],
)
def test_catalogue_malforme_refuse_sans_exception(mutation, tmp_path):
    source = _source(tmp_path, "fictif", "2026-01-01", "2026-12-31")
    catalogue = _catalogue([source])
    mutation(catalogue)
    resultat, refus = _evaluer(catalogue, tmp_path)
    assert resultat is None
    assert refus["code"] == "REJ-PAIE-CATALOGUE-INVALIDE"


def test_capture_locale_trop_grosse_refuse_avec_limite_nouable(monkeypatch, tmp_path):
    source = _source(tmp_path, "fictif", "2026-01-01", "2026-12-31", contenu=b"1234")
    monkeypatch.setattr(sources_regles_paie, "_TAILLE_CAPTURE_MAX", 3)
    resultat, refus = _evaluer(_catalogue([source]), tmp_path)
    assert resultat is None
    assert refus["code"] == "REJ-PAIE-CAPTURE-TROP-GROSSE"


def test_catalogue_reel_ne_qualifie_aucune_reference_arc_ou_rq():
    racine = Path(__file__).resolve().parents[1] / "contracts"
    catalogue = yaml.safe_load((racine / "sources_regles_paie.v1.yaml").read_text(encoding="utf-8"))
    for date_paie in ("2026-06-30", "2026-07-01"):
        resultat, refus = sources_regles_paie.evaluer_sources(
            catalogue, racine=racine, **_query(date_paie=date_paie),
        )
        assert refus is None
        assert resultat["statut"] == "PARTIEL"
        assert resultat["sources_verifiees"] == []
        assert {source["statut"] for source in catalogue["sources"]} == {"NON_QUALIFIEE"}
        assert {source["id"] for source in resultat["references_catalogue"]} == {
            "arc_t4127_2026_122e_janvier", "arc_t4127_2026_123e_juillet", "rq_tp1015f_2026",
            "rq_tp1015g_2026", "rq_tp1015ti_2026", "rq_tp1015ti26_2026", "rq_tp1015tr_2026",
            "rq_tp1015tr26_2026", "rq_tp1015ta_2026",
        }
        assert resultat["manques"]
        assert "montant" not in resultat and "taux" not in resultat


@pytest.fixture
def base_sqlite(monkeypatch, tmp_path):
    url = f"sqlite:///{tmp_path / 'm5-sources.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "nathan-sources-fictif", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "employee.fictif", "Employé fictif", "employee-sources-fictif", ["employee"])
    yield
    stockage.liberer()


@contextlib.contextmanager
def _identity(actor):
    with contexte.appele_par_appareil(actor):
        yield


def _call(tool, actor, arguments):
    with _identity(actor):
        return executer_atomique(tool, arguments)


def test_t0_proprietaire_expose_catalogue_partiel_sans_montant_ni_effet(base_sqlite):
    tool = {o.nom: o for o in m5_outils.outils()}["m5_lire_sources_regles_paie"]
    avant = list(stockage.maillons(DEPARTEMENT, "principal"))
    result = _call(tool, OWNER_CONSOLE, _query())
    assert result["ok"] is True
    payload = result["resultat"]["resultat"]
    assert payload["statut"] == "PARTIEL"
    assert payload["sources_verifiees"] == []
    assert len(payload["references_catalogue"]) == 9
    assert "montant" not in payload and "taux" not in payload
    assert list(stockage.maillons(DEPARTEMENT, "principal")) == avant
    assert list(stockage.maillons(DEPARTEMENT, "sources_regles_paie")) == []


def test_refus_roles_avant_lecture_catalogue_et_aucun_droit_appareil(base_sqlite, monkeypatch):
    tool = {o.nom: o for o in m5_outils.outils()}["m5_lire_sources_regles_paie"]
    def forbidden(*args, **kwargs):
        raise AssertionError("catalogue lu avant autorisation")
    monkeypatch.setattr(m5_outils, "_charger_catalogue_sources_paie", forbidden)
    for actor in (ADMIN_APPAREIL, EMPLOYEE_APPAREIL):
        result = _call(tool, actor, _query())
        assert result["ok"] is True
        assert result["resultat"]["accepte"] is False
    assert tool.roles_appareil == frozenset()


def test_catalogue_malforme_ne_change_aucun_registre(base_sqlite, monkeypatch, tmp_path):
    tool = {o.nom: o for o in m5_outils.outils()}["m5_lire_sources_regles_paie"]
    monkeypatch.setattr(m5_outils, "_CHEMIN_SOURCES_REGLES_PAIE", tmp_path / "catalogue.yaml")
    (tmp_path / "catalogue.yaml").write_text("schema_version: 1.0\njuridictions: {}\nsources: []\n", encoding="utf-8")
    avant = list(stockage.maillons(DEPARTEMENT, "principal"))
    result = _call(tool, OWNER_CONSOLE, _query())
    assert result["ok"] is True
    assert result["resultat"]["accepte"] is False
    assert result["resultat"]["verdict"]["code"] == "REJ-PAIE-CATALOGUE-INVALIDE"
    assert list(stockage.maillons(DEPARTEMENT, "principal")) == avant
    assert list(stockage.maillons(DEPARTEMENT, "sources_regles_paie")) == []
