from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from m1_front_office import voicemail_stt
from sqlalchemy import select

from opsys import connecteurs, identite
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import CONNECTEURS_STT_DIAGNOSTICS, CONNECTEURS_STT_HISTORIQUE

_PASSWORD = "mot-de-passe-stt-fictif-2026"


@pytest.fixture
def client_stt(session):
    with session() as cnx:
        identite.creer_personne(cnx, "owner_stt", "Owner STT fictif", _PASSWORD, ["nathan_owner"])
        identite.creer_personne(cnx, "admin_stt", "Admin STT fictif", _PASSWORD, ["admin"])
        identite.creer_personne(cnx, "employee_stt", "Employé fictif", _PASSWORD, ["employee"])
    app = application.creer_application(
        Configuration("session-stt-fictive-" + "x" * 32), charger_departements(), session,
    )
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client


def _connexion(client, identifiant="owner_stt"):
    response = client.post(
        "/connexion", data={"identifiant": identifiant, "mot_de_passe": _PASSWORD}, follow_redirects=False,
    )
    assert response.status_code == 303


def _csrf(client):
    html = client.get("/connecteurs").text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _payload(revision=0, mutation="config-stt-0001", actif=True):
    return {
        "actif": actif,
        "references": {"url": "STT_URL_SECRET_REF", "modele": "STT_MODEL_REF", "cle": "STT_KEY_SECRET_REF"},
        "revision_attendue": revision,
        "mutation_id": mutation,
    }


def test_routes_configuration_absentes_avant_auth_et_csrf(client_stt):
    assert client_stt.put("/api/connecteurs/stt-m1/configuration", json=_payload()).status_code == 401
    _connexion(client_stt)
    assert client_stt.put("/api/connecteurs/stt-m1/configuration", json=_payload()).status_code == 403


def test_configuration_persistante_rejeu_conflit_historique_et_aucune_valeur(client_stt, session, monkeypatch):
    monkeypatch.setenv("STT_URL_SECRET_REF", "https://secret-host.example.test/v1")
    monkeypatch.setenv("STT_MODEL_REF", "modele-secret-fictif")
    monkeypatch.setenv("STT_KEY_SECRET_REF", "cle-secrete-fictive")
    _connexion(client_stt)
    csrf = _csrf(client_stt)
    headers = {"x-csrf-token": csrf}
    payload = _payload()
    response = client_stt.put("/api/connecteurs/stt-m1/configuration", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["configuration"]["revision"] == 1
    etat_api = client_stt.get("/api/connecteurs").json()["resultat"]
    ligne_stt = next(ligne for ligne in etat_api["connecteurs"] if ligne["id"] == "stt-m1")
    assert ligne_stt["requis"] == ["STT_URL_SECRET_REF", "STT_MODEL_REF"]
    assert ligne_stt["optionnels"] == ["STT_KEY_SECRET_REF"]
    assert ligne_stt["validation_locale"] == "valide"
    assert "https://secret-host.example.test/v1" not in str(etat_api)
    assert "cle-secrete-fictive" not in str(etat_api)
    rejoue = client_stt.put("/api/connecteurs/stt-m1/configuration", json=payload, headers=headers)
    assert rejoue.json() == response.json()
    conflit = client_stt.put(
        "/api/connecteurs/stt-m1/configuration", json=_payload(0, "config-stt-0002"), headers=headers,
    )
    assert conflit.status_code == 409
    assert "cle-secrete-fictive" not in response.text
    assert "secret-host.example.test" not in response.text
    with session() as cnx:
        assert len(cnx.execute(select(CONNECTEURS_STT_HISTORIQUE)).all()) == 1
        from opsys.etat import lire_journal
        audit = lire_journal(cnx)
        evenement = next(item for item in audit if item["action"] == "connecteur.stt.configuration")
        assert evenement["par"] == "owner_stt"
        assert evenement["details"]["references"] == ["cle", "modele", "url"]
        assert "secret-host.example.test" not in str(evenement)
    runtime = voicemail_stt.ConfigurationSTT.depuis_env()
    assert runtime is not None and runtime.base_url.endswith("/v1") and runtime.cle_api == "cle-secrete-fictive"
    assert "STT_KEY_SECRET_REF" not in repr(runtime)


@pytest.mark.parametrize("payload", [
    {**_payload(), "unknown": 1},
    {**_payload(), "references": {"url": "bad-name", "modele": "STT_MODEL"}},
    {**_payload(), "references": {"url": "STT_URL", "modele": "STT_MODEL", "extra": "X"}},
    {**_payload(), "actif": 1},
    {**_payload(), "revision_attendue": True},
])
def test_payloads_fermes_et_invalides(client_stt, payload):
    _connexion(client_stt)
    response = client_stt.put("/api/connecteurs/stt-m1/configuration", json=payload,
                              headers={"x-csrf-token": _csrf(client_stt)})
    assert response.status_code == 422


def test_role_retrait_et_configuration_desactivee_ne_replient_pas_sur_env(client_stt, session, monkeypatch):
    monkeypatch.setenv(voicemail_stt.ENV_URL, "https://historique.example.test")
    monkeypatch.setenv(voicemail_stt.ENV_MODELE, "modele-historique")
    _connexion(client_stt)
    headers = {"x-csrf-token": _csrf(client_stt)}
    response = client_stt.put("/api/connecteurs/stt-m1/configuration",
                              json=_payload(actif=False), headers=headers)
    assert response.status_code == 200
    assert voicemail_stt.ConfigurationSTT.depuis_env() is None
    with session() as cnx:
        identite.retirer_role(cnx, "owner_stt", "nathan_owner")
    assert client_stt.put("/api/connecteurs/stt-m1/configuration",
                          json=_payload(1, "config-stt-0002"), headers=headers).status_code == 403


def test_diagnostic_borne_sans_secret_rejeu_sans_second_appel(client_stt, monkeypatch):
    _connexion(client_stt)
    headers = {"x-csrf-token": _csrf(client_stt)}
    monkeypatch.setenv("STT_URL_SECRET_REF", "https://secret-host.example.test/v1")
    monkeypatch.setenv("STT_MODEL_REF", "modele-secret")
    monkeypatch.setenv("STT_KEY_SECRET_REF", "cle-secrete")
    assert client_stt.put("/api/connecteurs/stt-m1/configuration", json=_payload(), headers=headers).status_code == 200
    appels = []

    def faux_diagnostic(self):
        appels.append(self.delai_s)
        return {"statut": "endpoint_rejoignable", "modele": self.modele, "stt_verifie": False}

    monkeypatch.setattr(voicemail_stt.ConfigurationSTT, "verifier_connexion", faux_diagnostic)
    corps = {"revision": 1, "mutation_id": "diagnostic-stt-0001"}
    resultat = client_stt.post("/api/connecteurs/stt-m1/diagnostic", json=corps, headers=headers)
    assert resultat.status_code == 200
    assert resultat.json()["resultat"]["stt_verifie"] is False
    assert appels == [5.0]
    assert client_stt.post("/api/connecteurs/stt-m1/diagnostic", json=corps, headers=headers).json() == resultat.json()
    assert appels == [5.0]
    assert "secret-host.example.test" not in resultat.text and "cle-secrete" not in resultat.text


def test_diagnostic_revision_obsolete_refuse(client_stt):
    _connexion(client_stt)
    headers = {"x-csrf-token": _csrf(client_stt)}
    assert client_stt.put("/api/connecteurs/stt-m1/configuration", json=_payload(), headers=headers).status_code == 200
    response = client_stt.post("/api/connecteurs/stt-m1/diagnostic",
                              json={"revision": 2, "mutation_id": "diagnostic-stt-0002"}, headers=headers)
    assert response.status_code == 409


def test_diagnostic_concurrent_refus_et_reprise_apres_bail(session, monkeypatch):
    monkeypatch.setenv("STT_URL_SECRET_REF", "https://example.test")
    monkeypatch.setenv("STT_MODEL_REF", "modele-fictif")
    with session() as cnx:
        identite.creer_personne(cnx, "owner_stt_direct", "Owner", _PASSWORD, ["nathan_owner"])
        connecteurs.modifier(cnx, acteur="owner_stt_direct", payload=_payload())
    with session() as cnx:
        reservation = connecteurs.diagnostic_reserver(
            cnx, acteur="owner_stt_direct", revision=1, mutation_id="diagnostic-stt-0003",
        )
        assert reservation is not None
    with session() as cnx, pytest.raises(RuntimeError):
        connecteurs.diagnostic_reserver(
            cnx, acteur="owner_stt_direct", revision=1, mutation_id="diagnostic-stt-0004",
        )
    with session() as cnx:
        cnx.execute(
            CONNECTEURS_STT_DIAGNOSTICS.update().where(
                CONNECTEURS_STT_DIAGNOSTICS.c.mutation_id == "diagnostic-stt-0003",
            ).values(expire_le="2000-01-01T00:00:00+00:00")
        )
    with session() as cnx:
        reservation = connecteurs.diagnostic_reserver(
            cnx, acteur="owner_stt_direct", revision=1, mutation_id="diagnostic-stt-0003",
        )
        assert reservation is not None


@pytest.mark.parametrize("acteur,revision,erreur", [
    ("admin_stt_reprise", 1, PermissionError),
    ("owner_stt_reprise", 2, ValueError),
])
def test_reprise_expiree_relie_mutation_a_acteur_et_revision(session, acteur, revision, erreur):
    with session() as cnx:
        identite.creer_personne(cnx, "owner_stt_reprise", "Owner", _PASSWORD, ["nathan_owner"])
        identite.creer_personne(cnx, "admin_stt_reprise", "Admin", _PASSWORD, ["admin"])
        connecteurs.modifier(cnx, acteur="owner_stt_reprise", payload=_payload())
    with session() as cnx:
        connecteurs.diagnostic_reserver(
            cnx, acteur="owner_stt_reprise", revision=1, mutation_id="diagnostic-stt-reprise",
        )
    with session() as cnx:
        cnx.execute(
            CONNECTEURS_STT_DIAGNOSTICS.update().where(
                CONNECTEURS_STT_DIAGNOSTICS.c.mutation_id == "diagnostic-stt-reprise",
            ).values(expire_le="2000-01-01T00:00:00+00:00")
        )
    with session() as cnx, pytest.raises(erreur):
        connecteurs.diagnostic_reserver(
            cnx, acteur=acteur, revision=revision, mutation_id="diagnostic-stt-reprise",
        )


def test_observation_ancienne_revision_ne_peut_pas_clore_la_configuration(session, monkeypatch):
    with session() as cnx:
        identite.creer_personne(cnx, "owner_stt_revision", "Owner", _PASSWORD, ["nathan_owner"])
        connecteurs.modifier(cnx, acteur="owner_stt_revision", payload=_payload())
    with session() as cnx:
        reservation = connecteurs.diagnostic_reserver(
            cnx, acteur="owner_stt_revision", revision=1, mutation_id="diagnostic-stt-0005",
        )
        jeton = reservation["_jeton_reservation"]
    with session() as cnx:
        connecteurs.modifier(
            cnx, acteur="owner_stt_revision", payload=_payload(1, "config-stt-0002"),
        )
    with session() as cnx, pytest.raises(ValueError, match="remplacée"):
        connecteurs.diagnostic_terminer(
            cnx, acteur="owner_stt_revision", revision=1,
            mutation_id="diagnostic-stt-0005", jeton=jeton, statut="endpoint_rejoignable",
        )


def test_probe_refuse_adresse_locale_pour_endpoint_distant():
    config = voicemail_stt.ConfigurationSTT("https://127.0.0.1:9999", "modele-fictif", cle_api="cle")
    with pytest.raises(ValueError, match="adresse IP"):
        connecteurs.verifier_adresse_diagnostic(config)


def test_rejeu_mutation_configuration_autre_acteur_refuse(client_stt):
    _connexion(client_stt)
    payload = _payload()
    response = client_stt.put(
        "/api/connecteurs/stt-m1/configuration", json=payload,
        headers={"x-csrf-token": _csrf(client_stt)},
    )
    assert response.status_code == 200
    client_stt.post("/deconnexion")
    _connexion(client_stt, "admin_stt")
    response = client_stt.put(
        "/api/connecteurs/stt-m1/configuration", json=payload,
        headers={"x-csrf-token": _csrf(client_stt)},
    )
    assert response.status_code == 403


def test_formulaire_stt_borne_corps_et_rejette_reference_invalide(client_stt):
    _connexion(client_stt)
    csrf = _csrf(client_stt)
    trop_grand = client_stt.post(
        "/connecteurs/stt-m1/configuration",
        data={"csrf": csrf, "revision_attendue": "0", "ref_url": "X" * (17 * 1024)},
    )
    assert trop_grand.status_code == 413
    invalide = client_stt.post(
        "/connecteurs/stt-m1/configuration",
        data={"csrf": csrf, "revision_attendue": "0", "actif": "true",
              "ref_url": "bad-name", "ref_modele": "STT_MODEL_VALID"},
    )
    assert invalide.status_code == 422
    assert "bad-name" not in invalide.text
