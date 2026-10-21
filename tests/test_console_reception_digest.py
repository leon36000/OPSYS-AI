"""Oracle HTTP initiale du digest de réception M1 : propriétaire réel, date explicite."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select

from opsys import identite
from opsys.console import reception_digest_ui
from opsys.stockage.schema import META, REGISTRES

_BASE_PATH = Path(__file__).with_name("test_console_metier.py")
_BASE_SPEC = importlib.util.spec_from_file_location("_console_metier_reception_digest_base", _BASE_PATH)
assert _BASE_SPEC is not None and _BASE_SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_BASE_SPEC)
sys.modules[_BASE_SPEC.name] = _BASE
_BASE_SPEC.loader.exec_module(_BASE)


@pytest.fixture
def client_reception_digest(session, monkeypatch):
    yield from _BASE.client_console.__wrapped__(session, monkeypatch)


def test_digest_reception_http_initial_oracle_proprietaire_et_date(client_reception_digest):
    _BASE._connecter(client_reception_digest)

    response = client_reception_digest.get("/reception/digest?date_reference=2026-10-04")

    assert response.status_code == 200, response.text


def _instantane_base(session):
    with session() as cnx:
        return tuple(
            (table.name, tuple(tuple(ligne) for ligne in cnx.execute(select(table)).all()))
            for table in META.sorted_tables
        )


def test_digest_prive_json_compteurs_sans_ecriture_ni_payload(client_reception_digest, session):
    client = client_reception_digest
    csrf = _BASE._connecter(client)
    importe = client.post(
        "/api/reception/appels",
        json={
            **_BASE.APPEL_MANQUE,
            "recu_le": "2026-10-04T09:15:00-04:00",
            "mutation_id": "digest-sans-ecriture-source",
        },
        headers=_BASE._headers(csrf),
    )
    assert importe.status_code == 200, importe.text
    before = _instantane_base(session)

    page = client.get("/reception/digest?date_reference=2026-10-04")
    api = client.get("/api/reception/digest?date_reference=2026-10-04")

    assert page.status_code == api.status_code == 200
    assert page.headers["cache-control"] == api.headers["cache-control"] == "no-store"
    charge = api.json()
    assert charge["ok"] is True
    assert charge["date_reference"] == "2026-10-04"
    assert len(charge["digest"]["grille"]) == 20
    assert "pas des clients uniques" in page.text
    assert 'type="date" name="date_reference"' in page.text
    assert "état historique uniforme" in page.text
    assert "m1_produire_digest" not in page.text + api.text
    assert _instantane_base(session) == before


def test_digest_dates_distinctes_utilisent_appels_m1_durables(client_reception_digest):
    client = client_reception_digest
    csrf = _BASE._connecter(client)
    for jour, suffix in (("2026-10-04", "aujourdhui"), ("2026-10-03", "hier")):
        resultat = client.post(
            "/api/reception/appels",
            json={
                **_BASE.APPEL_MANQUE,
                "source": f"Journal fictif {suffix}",
                "evenement_id": f"event-digest-{suffix}",
                "appel_id": f"appel-digest-{suffix}",
                "recu_le": f"{jour}T09:15:00-04:00",
                "mutation_id": f"mutation-digest-{suffix}",
            },
            headers=_BASE._headers(csrf),
        )
        assert resultat.status_code == 200, resultat.text

    aujourdhui = client.get("/api/reception/digest?date_reference=2026-10-04").json()
    hier = client.get("/api/reception/digest?date_reference=2026-10-03").json()
    jour_sans_evenement = client.get("/api/reception/digest?date_reference=2026-10-02").json()
    assert aujourdhui["digest"]["appels"] == {"manque": 1}
    assert hier["digest"]["appels"] == {"manque": 1}
    assert jour_sans_evenement["digest"]["appels"] == {}
    assert all(ligne["nombre"] == 0 for ligne in jour_sans_evenement["digest"]["grille"])
    assert (
        "aucune activité enregistrée pour la date"
        not in client.get("/reception/digest?date_reference=2026-10-02").text.lower()
    )
    assert "Journal fictif" not in client.get("/reception/digest?date_reference=2026-10-04").text


@pytest.mark.parametrize(
    "query",
    [
        "?date_reference=2026-02-30",
        "?date_reference=2026-10-04&date_reference=2026-10-04",
        "?date_reference=2026-10-04&extra=1",
        "?extra=1",
        "?date_reference=%32%30%32%36-10-04",
        "?date_reference=2026-10-04" + "x" * 240,
    ],
)
def test_digest_refuse_query_invalide(client_reception_digest, query):
    client = client_reception_digest
    _BASE._connecter(client)
    response = client.get("/reception/digest" + query)
    assert response.status_code == 400
    assert "résumé temporairement" not in response.text


def test_digest_date_utc_par_defaut_est_exposee(client_reception_digest):
    client = client_reception_digest
    _BASE._connecter(client)
    response = client.get("/api/reception/digest")
    assert response.status_code == 200
    assert response.json()["date_reference"] == datetime.now(UTC).date().isoformat()


def test_digest_accepte_jour_bissextile_valide(client_reception_digest):
    client = client_reception_digest
    _BASE._connecter(client)
    response = client.get("/api/reception/digest?date_reference=2024-02-29")
    assert response.status_code == 200, response.text
    assert response.json()["date_reference"] == "2024-02-29"


def test_digest_refuse_anonyme_employe_et_admin_sans_fuite(client_reception_digest, session):
    client = client_reception_digest
    assert client.get("/reception/digest", follow_redirects=False).status_code == 303
    assert client.get("/api/reception/digest").status_code == 401
    _BASE._connecter(client, "employe")
    assert client.get("/reception/digest").status_code == 403
    assert client.get("/api/reception/digest").status_code == 403

    with session() as cnx:
        identite.creer_personne(cnx, "admin-digest", "Admin fictif", "mot-de-passe-admin-fictif", ["admin"])
    client.cookies.clear()
    client.post(
        "/connexion",
        data={
            "identifiant": "admin-digest",
            "mot_de_passe": "mot-de-passe-admin-fictif",
        },
        follow_redirects=False,
    )
    response = client.get("/api/reception/digest?date_reference=2026-10-04")
    assert response.status_code == 200, response.text
    assert response.json()["digest"]["registre_non_vide"] is False


@pytest.mark.parametrize("voie,appel", [("html", 5), ("html", 6), ("json", 5), ("json", 6)])
@pytest.mark.parametrize("retrait", ["role", "desactivation"])
def test_digest_revoque_role_pendant_calcul_ou_rendu_sans_corps(
    client_reception_digest, monkeypatch, voie, appel, retrait
):
    client = client_reception_digest
    _BASE._connecter(client)
    original = identite.personne_active
    nombre = 0

    def personne_revoquee(cnx, identifiant):
        nonlocal nombre
        personne = original(cnx, identifiant)
        nombre += 1
        if personne is not None and nombre >= appel and retrait == "role":
            return replace(personne, roles=frozenset({"employee"}))
        if nombre >= appel and retrait == "desactivation":
            return None
        return personne

    monkeypatch.setattr(reception_digest_ui.identite, "personne_active", personne_revoquee)
    url = (
        "/reception/digest?date_reference=2026-10-04"
        if voie == "html"
        else "/api/reception/digest?date_reference=2026-10-04"
    )
    response = client.get(url)
    assert response.status_code == (401 if retrait == "desactivation" else 403)
    assert "DIGEST" not in response.text and "grille" not in response.text


@pytest.mark.parametrize("voie,appel", [("html", 2), ("html", 3), ("json", 2), ("json", 3)])
def test_digest_revalide_expiration_apres_calcul_et_rendu(client_reception_digest, monkeypatch, voie, appel):
    client = client_reception_digest
    _BASE._connecter(client)
    nombre = 0
    maintenant = int(datetime.now(UTC).timestamp())

    def heure_courante():
        nonlocal nombre
        nombre += 1
        return maintenant if nombre < appel else maintenant + 10_000_000

    monkeypatch.setattr(reception_digest_ui, "time", SimpleNamespace(time=heure_courante))
    url = (
        "/reception/digest?date_reference=2026-10-04"
        if voie == "html"
        else "/api/reception/digest?date_reference=2026-10-04"
    )
    response = client.get(url)
    assert response.status_code == 401
    assert "DIGEST" not in response.text and "registre_non_vide" not in response.text


@pytest.mark.parametrize(
    "reponse_metier",
    [
        {"ok": False, "erreur": "secret", "details": "Téléphone 5145550142"},
        {"ok": True, "resultat": "DIGEST - Période de référence : 2026-10-04\n<PII> téléphone 5145550142"},
        {"ok": True, "resultat": "x" * 32_769},
        {"ok": True, "resultat": {"texte": "valeur inattendue"}},
    ],
)
def test_digest_ferme_reponses_metier_malfomees_et_trop_grandes(client_reception_digest, monkeypatch, reponse_metier):
    client = client_reception_digest
    csrf = _BASE._connecter(client)
    importe = client.post(
        "/api/reception/appels",
        json={
            **_BASE.APPEL_MANQUE,
            "recu_le": "2026-10-04T09:15:00-04:00",
            "mutation_id": "digest-malformed-source",
        },
        headers=_BASE._headers(csrf),
    )
    assert importe.status_code == 200, importe.text
    monkeypatch.setattr(reception_digest_ui.metier, "executer", lambda *args, **kwargs: reponse_metier)
    response = client.get("/api/reception/digest?date_reference=2026-10-04")
    assert response.status_code == 503
    assert "téléphone" not in response.text and "valeur inattendue" not in response.text
    assert "secret" not in response.text and "5145550142" not in response.text


def _inserer_maillons_bruts(session, nombre, maillon):
    with session() as cnx:
        cnx.execute(
            insert(REGISTRES),
            [
                {"departement": "m01-front-office", "registre": "principal", "rang": rang, "maillon": maillon}
                for rang in range(nombre)
            ],
        )


@pytest.mark.parametrize(
    "nombre,maillon",
    [
        (10_001, "x"),
        (1, "x" * 65_537),  # Limite par maillon + un octet.
        (1, "é" * 32_769),  # 65 538 octets UTF-8, au-delà de la borne par maillon.
        (129, "é" * 32_768),  # 129 × 65 536 octets, au-delà du total de 8 Mio.
    ],
)
def test_digest_preflight_sql_reel_refuse_avant_port_et_decodeur(
    client_reception_digest, session, monkeypatch, nombre, maillon
):
    client = client_reception_digest
    _BASE._connecter(client)
    _inserer_maillons_bruts(session, nombre, maillon)

    def ne_pas_appeler(*args, **kwargs):
        pytest.fail("le port canonique ne doit pas lire après dépassement SQL")

    from opsys.stockage import codec

    monkeypatch.setattr(reception_digest_ui.metier, "executer", ne_pas_appeler)
    monkeypatch.setattr(codec, "decoder", ne_pas_appeler)
    response = client.get("/api/reception/digest?date_reference=2026-10-04")
    assert response.status_code == 503
    assert "le port canonique" not in response.text


def test_digest_preflight_sql_reel_accepte_bornes_octets_inclusives(session):
    _inserer_maillons_bruts(session, 128, "é" * 32_768)
    with session() as cnx:
        assert reception_digest_ui._preflight(cnx) == 128


def test_digest_preflight_sql_reel_accepte_borne_nombre_inclusive(session):
    _inserer_maillons_bruts(session, 10_000, "x")
    with session() as cnx:
        assert reception_digest_ui._preflight(cnx) == 10_000


def test_digest_suivi_courant_sur_date_ancienne_et_transfert_canonique(client_reception_digest, session):
    from m1_front_office import outils as outils_m1

    from opsys import taxonomie

    client = client_reception_digest
    csrf = _BASE._connecter(client)
    taxonomie.enregistrer_fenetre_conversation(30)
    with session():
        ouverture = outils_m1.recevoir_message_canal(
            canal="sms",
            expediteur="+15145550149",
            message_id="digest-suivi-fictif",
            recu_le="2026-10-03T23:50:00-04:00",
            texte="Mes gouttières fuient.",
        )
    assert ouverture["prochaine_action"] is not None
    importe = client.post(
        "/api/reception/appels",
        json={
            **_BASE.APPEL_MANQUE,
            "recu_le": "2026-10-03T20:00:00-04:00",
            "mutation_id": "digest-transfert-fictif",
        },
        headers=_BASE._headers(csrf),
    )
    assert importe.status_code == 200, importe.text
    url = "/api/reception/digest?date_reference=2026-10-03"
    avant = client.get(url)
    assert avant.status_code == 200, avant.text
    original = avant.json()["digest"]
    # Le SMS incomplet et l'appel manqué créent chacun une conversation à suivre.
    assert original["suivi"][0]["nombre"] == 2
    assert original["transferts"]["Transferts à un humain ouverts"] == 1
    with session():
        outils_m1.recevoir_message_canal(
            canal="sms",
            expediteur="+15145550149",
            message_id="digest-stop-fictif",
            recu_le="2026-10-04T00:01:00-04:00",
            texte="STOP",
        )
    avant_lecture = _instantane_base(session)
    apres = client.get(url)
    assert apres.status_code == 200, apres.text
    courant = apres.json()["digest"]
    assert courant["suivi"][0]["nombre"] == 1
    assert courant["grille"] == original["grille"]
    assert courant["transferts"] == original["transferts"]
    assert _instantane_base(session) == avant_lecture
    assert "5145550149" not in apres.text


def test_digest_autre_jour_dans_registre_non_vide_ne_devient_pas_absence(client_reception_digest):
    client = client_reception_digest
    csrf = _BASE._connecter(client)
    source = client.post(
        "/api/reception/appels",
        json={
            **_BASE.APPEL_MANQUE,
            "recu_le": "2026-10-04T09:15:00-04:00",
            "mutation_id": "digest-autre-jour-fictif",
        },
        headers=_BASE._headers(csrf),
    )
    assert source.status_code == 200, source.text
    response = client.get("/api/reception/digest?date_reference=2026-10-03")
    assert response.status_code == 200, response.text
    digest = response.json()["digest"]
    assert digest["registre_non_vide"] is True
    assert all(ligne["nombre"] == 0 for ligne in digest["grille"])
    assert digest["appels"] == {}
    assert "ne contient aucun événement" not in client.get("/reception/digest?date_reference=2026-10-03").text


def test_digest_maillon_json_corrompu_refuse_sans_fuite(client_reception_digest, session):
    _BASE._connecter(client_reception_digest)
    _inserer_maillons_bruts(session, 1, "source corrompue fictive 5145550149")
    response = client_reception_digest.get("/api/reception/digest?date_reference=2026-10-04")
    assert response.status_code == 503
    assert "5145550149" not in response.text and "source corrompue" not in response.text


def test_digest_erreur_backend_refuse_sans_fuite(client_reception_digest, monkeypatch):
    _BASE._connecter(client_reception_digest)

    def panne(*args, **kwargs):
        raise RuntimeError("source privée fictive 5145550149")

    monkeypatch.setattr(reception_digest_ui.metier, "executer", panne)
    response = client_reception_digest.get("/api/reception/digest?date_reference=2026-10-04")
    assert response.status_code == 503
    assert "5145550149" not in response.text and "source privée" not in response.text


def test_digest_total_sql_reel_plus_un_octet_refuse_avant_decode(client_reception_digest, session, monkeypatch):
    _BASE._connecter(client_reception_digest)
    _inserer_maillons_bruts(session, 128, "x" * 65_536)
    with session() as cnx:
        cnx.execute(
            insert(REGISTRES).values(departement="m01-front-office", registre="principal", rang=128, maillon="x")
        )

    def ne_pas_decodage(*args, **kwargs):
        pytest.fail("décodage interdit après dépassement d'un octet")

    from opsys.stockage import codec

    monkeypatch.setattr(codec, "decoder", ne_pas_decodage)
    response = client_reception_digest.get("/api/reception/digest?date_reference=2026-10-04")
    assert response.status_code == 503


@pytest.mark.parametrize("retrait", ["role", "desactivation"])
def test_digest_retrait_reel_en_base_apres_rendu_refuse_corps(client_reception_digest, session, monkeypatch, retrait):
    _BASE._connecter(client_reception_digest)
    original = reception_digest_ui.pages.gabarit

    def rendu_avec_retrait(*args, **kwargs):
        html = original(*args, **kwargs)
        with session() as cnx:
            if retrait == "role":
                identite.retirer_role(cnx, "nathan", "nathan_owner")
            else:
                identite.activer(cnx, "nathan", False)
        return html

    monkeypatch.setattr(reception_digest_ui.pages, "gabarit", rendu_avec_retrait)
    response = client_reception_digest.get("/reception/digest?date_reference=2026-10-04")
    assert response.status_code == (403 if retrait == "role" else 401)
    assert "Résumé de réception" not in response.text and "Événements enregistrés" not in response.text
    with session() as cnx:
        personne = identite.personne_active(cnx, "nathan")
        assert personne is None if retrait == "desactivation" else "nathan_owner" not in personne.roles
