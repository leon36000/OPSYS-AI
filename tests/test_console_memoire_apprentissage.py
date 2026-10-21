from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, insert

from opsys import identite, stockage
from opsys.console import application, memoire_apprentissage_ui
from opsys.console.securite import Configuration
from opsys.departements import lire_manifeste

SECRET = "secret-apprentissage-m10-test-" + "x" * 32
PASSWORD = "mot-de-passe-apprentissage-2026"


@pytest.fixture
def client_admin(departements_demo, session):
    with session() as cnx:
        identite.creer_personne(cnx, "m10-learning-admin", "Admin test", PASSWORD, ["admin"])
    racine = Path(__file__).resolve().parents[1]
    departement_m03 = lire_manifeste(racine / "departments" / "m03-estimation")
    deps = {**departements_demo, departement_m03.id: departement_m03}
    app = application.creer_application(Configuration(SECRET), deps, session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        connexion = client.post(
            "/connexion",
            data={"identifiant": "m10-learning-admin", "mot_de_passe": PASSWORD},
            follow_redirects=False,
        )
        assert connexion.status_code == 303, connexion.text
        yield client


def _ajouter_candidats(ids: tuple[str, ...] = ("lead-a", "lead-b", "lead-c")) -> None:
    from m10_memoire.registre import Registre

    journal = Registre(stockage.maillons("m10-memoire", "affaires"))
    for index, affaire in enumerate(ids):
        journal.ajouter({
            "type_entree": "fait_candidat", "horodatage": "2026-09-20T12:00:00+00:00",
            "affaire_id": affaire, "departement_source": "m03-estimation",
            "cle_depot": f"candidate-{index}", "outil": "m3_creer_devis", "resultat": "ok",
            "code": None, "statut": "candidat",
        })


def test_get_admin_est_borne_no_store_sans_affaires_ni_ecriture(client_admin, session):
    _ajouter_candidats()
    avant_affaires = len(stockage.maillons("m10-memoire", "affaires"))
    avant_evenements = len(stockage.maillons("m10-memoire", "evenements"))
    response = client_admin.get("/memoire/apprentissages-affaires")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "m3_creer_devis" in response.text and "3" in response.text
    assert "lead-a" not in response.text and "lead-b" not in response.text
    assert len(stockage.maillons("m10-memoire", "affaires")) == avant_affaires
    assert len(stockage.maillons("m10-memoire", "evenements")) == avant_evenements


def test_sans_session_ne_lit_aucune_donnee(client_admin, monkeypatch):
    client_admin.cookies.clear()
    monkeypatch.setattr(
        memoire_apprentissage_ui, "_lire_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("aucune lecture sans session")),
    )
    assert client_admin.get("/memoire/apprentissages-affaires", follow_redirects=False).status_code == 303


def test_head_change_pendant_aperçu_donne_409(client_admin, monkeypatch):
    _ajouter_candidats()
    original = memoire_apprentissage_ui._lire_tetes
    ajoute = False

    def changement():
        nonlocal ajoute
        if not ajoute:
            ajoute = True
            from m10_memoire.registre import Registre

            Registre(stockage.maillons("m10-memoire", "affaires")).ajouter({
                "type_entree": "fait_candidat", "horodatage": "2026-09-21T12:00:00+00:00",
                "affaire_id": "lead-d", "departement_source": "m03-estimation",
                "cle_depot": "candidate-late", "outil": "m3_creer_devis", "resultat": "ok",
                "code": None, "statut": "candidat",
            })
        return original()

    monkeypatch.setattr(memoire_apprentissage_ui, "_lire_tetes", changement)
    assert client_admin.get("/memoire/apprentissages-affaires").status_code == 409


def test_retrait_role_avant_rendu_refuse_la_reponse(client_admin, session, monkeypatch):
    _ajouter_candidats()
    original = memoire_apprentissage_ui._lire_tetes
    retire = False

    def retirer_role():
        nonlocal retire
        if not retire:
            retire = True
            with session() as cnx:
                identite.retirer_role(cnx, "m10-learning-admin", "admin")
        return original()

    monkeypatch.setattr(memoire_apprentissage_ui, "_lire_tetes", retirer_role)
    response = client_admin.get("/memoire/apprentissages-affaires")
    assert response.status_code == 403
    assert "lead-a" not in response.text


@pytest.mark.parametrize("texte", [
    '{"a":1,"a":2}',
    '{"x":1e999}',
    "[" * 65 + "0" + "]" * 65,
    '{"x": NaN}',
])
def test_json_m10_hostile_refuse_avant_decodeur(texte: str):
    with pytest.raises(ValueError):
        memoire_apprentissage_ui._valider_json_borne(texte)


def test_preflight_sql_refuse_maillon_trop_gros_avant_codec(session, monkeypatch):
    from opsys.stockage.schema import REGISTRES

    with session() as cnx:
        cnx.execute(insert(REGISTRES).values(
            departement="m10-memoire", registre="affaires", rang=0, maillon=" " * 65_537,
        ))
    monkeypatch.setattr(
        memoire_apprentissage_ui.codec, "decoder",
        lambda _texte: (_ for _ in ()).throw(AssertionError("codec ne doit pas être appelé")),
    )
    with pytest.raises(HTTPException) as erreur:
        memoire_apprentissage_ui._lire_snapshot()
    assert getattr(erreur.value, "status_code", None) == 413


def test_chaine_incomplete_est_refusee_sans_traceback(session):
    from opsys.stockage.schema import REGISTRES

    with session() as cnx:
        cnx.execute(insert(REGISTRES).values(
            departement="m10-memoire", registre="affaires", rang=0, maillon="{}",
        ))
    with pytest.raises(HTTPException) as erreur:
        memoire_apprentissage_ui._lire_snapshot()
    assert erreur.value.status_code == 409


def test_tete_geante_est_mesuree_sql_avant_selection_payload(session, monkeypatch):
    from opsys.stockage.schema import REGISTRES

    with session() as cnx:
        cnx.execute(insert(REGISTRES).values(
            departement="m10-memoire", registre="affaires", rang=0, maillon="x" * 65_537,
        ))
    moteur = stockage.moteur()
    requetes = []

    def tracer(_cnx, _curseur, sql, _params, _context, _many):
        if "registres_maillons" in sql:
            requetes.append(sql)

    event.listen(moteur, "before_cursor_execute", tracer)
    monkeypatch.setattr(
        memoire_apprentissage_ui.codec, "decoder",
        lambda _texte: (_ for _ in ()).throw(AssertionError("payload ne doit pas être lu/décodé")),
    )
    try:
        with pytest.raises(HTTPException) as erreur:
            memoire_apprentissage_ui._lire_tetes()
    finally:
        event.remove(moteur, "before_cursor_execute", tracer)
    assert erreur.value.status_code == 409
    assert len(requetes) == 1
    assert "length(CAST(maillon AS BLOB))" in requetes[0]
    assert "SELECT registres_maillons.maillon" not in requetes[0]


def test_html_borne_les_refs_par_groupe_et_compte_celles_omises():
    references = [f"{index:064x}" for index in range(25)]
    rapport = {"propositions": [{
        "outil": "m3_creer_devis", "resultat": "ok", "code": None,
        "affaires_distinctes": 25, "observations": 25,
        "premiere_observation_utc": "2026-01-01T00:00:00+00:00",
        "derniere_observation_utc": "2026-10-02T00:00:00+00:00",
        "sources_ligne_id": references,
    }], "propositions_omises": 0, "maillons_outil_hors_catalogue_omis": 0,
        "maillons_code_hors_catalogue_omis": 0, "cutoff_utc": "2026-10-02T00:00:00+00:00",
        "rapport_sha256": "f" * 64}
    rendu = memoire_apprentissage_ui._contenu(rapport, "/opsys")
    assert rendu.count("<code>") == 21  # 20 références et l'empreinte du rapport
    assert "+5 références omises" in rendu
    assert references[19] in rendu and references[20] not in rendu
    assert len(rendu.encode("utf-8")) < memoire_apprentissage_ui.MAX_REPONSE_OCTETS
