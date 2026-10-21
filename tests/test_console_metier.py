"""Parcours authentifiés des écrans M1 réception et M7 réputation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from m1_front_office import outils as outils_m1
from sqlalchemy import select

from opsys import identite, stockage, taxonomie
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES

SECRET = "secret-console-metier-fictif-" + "x" * 32
PREFIXE = "/opsys"
HEURE_SOURCE = "2026-09-30T09:15:00-04:00"
APPEL_MANQUE = {
    "source": "Journal d’appels FICTIF du 30 septembre",
    "evenement_id": "event-fictif-001",
    "appel_id": "appel-fictif-001",
    "recu_le": HEURE_SOURCE,
    "telephone": "+15145550142",
    "statut": "manque",
}


@pytest.fixture
def client_console(session, monkeypatch):
    # Les tests M1 rétablissent parfois le registre en mémoire à leur teardown; la console réelle
    # doit utiliser le registre durable de la base montée par ce fixture.
    outils_m1.utiliser_stockage_durable()
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_services(["gouttieres"])
    from m7_marketing.brand import profil_client

    monkeypatch.setattr(
        profil_client,
        "charger_profil_client",
        lambda: ({
            "name": "Entreprise FICTIF",
            "tagline": "Travaux extérieurs",
            "tone": "professionnel",
            "colors": ["#123456"],
            "langue": "fr",
        }, None),
    )

    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan FICTIF", "mot-de-passe-proprietaire-fictif",
                                ["nathan_owner"])
        identite.creer_personne(cnx, "employe", "Employé FICTIF", "mot-de-passe-employe-fictif", ["employee"])
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), None, session
    )
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def _connecter(client: TestClient, utilisateur: str = "nathan") -> str:
    mots_de_passe = {
        "nathan": "mot-de-passe-proprietaire-fictif",
        "employe": "mot-de-passe-employe-fictif",
    }
    reponse = client.post("/connexion", data={
        "identifiant": utilisateur,
        "mot_de_passe": mots_de_passe[utilisateur],
    }, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text
    return client.get("/api/session").json()["csrf"]


def _headers(csrf: str) -> dict[str, str]:
    return {"x-csrf-token": csrf}


def _avis(**overrides):
    return {
        "plateforme": "google_business_profile",
        "avis_source_id": "avis-fictif-001",
        "date_avis": "2026-09-28",
        "note": 5,
        "texte": "Excellent travail, équipe ponctuelle et soignée.",
        "source_url": "https://business.google.com/reviews/avis-fictif-001",
        **overrides,
    }


def _etat_persistance_console(session):
    with session() as cnx:
        approbations = [dict(ligne) for ligne in cnx.execute(select(APPROBATIONS)).mappings().all()]
        mutations = [dict(ligne) for ligne in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all()]
    appels = list(stockage.maillons("m01-front-office", "principal"))
    return appels, approbations, mutations


def test_reception_refuse_session_csrf_et_role_non_administrateur(client_console):
    client = client_console
    anonime = client.get("/reception", follow_redirects=False)
    assert anonime.status_code == 303 and anonime.headers["location"].endswith("/connexion")
    csrf = _connecter(client)
    assert client.post("/api/reception/appels", json=APPEL_MANQUE).status_code == 403
    assert client.post("/reception/appels", data=APPEL_MANQUE).status_code == 403

    _connecter(client, "employe")
    assert client.get("/reception").status_code == 403
    assert client.get("/api/marketing/avis").status_code == 403
    assert csrf


@pytest.mark.parametrize("transport", ["api", "formulaire"])
@pytest.mark.parametrize("retrait", ["role", "desactivation"])
def test_reception_revalide_l_acces_apres_affichage_sans_mutation(
    client_console, session, transport, retrait
):
    client = client_console
    csrf = _connecter(client)
    page = client.get("/reception")
    assert page.status_code == 200 and "Enregistrer l’import" in page.text
    avant = _etat_persistance_console(session)

    with session() as cnx:
        if retrait == "role":
            identite.retirer_role(cnx, "nathan", "nathan_owner")
        else:
            identite.activer(cnx, "nathan", False)

    commande = {**APPEL_MANQUE, "mutation_id": f"revocation-{transport}-{retrait}"}
    if transport == "api":
        retour = client.post("/api/reception/appels", json=commande, headers=_headers(csrf))
        assert retour.status_code == (403 if retrait == "role" else 401), retour.text
    else:
        retour = client.post(
            "/reception/appels", data={**commande, "csrf": csrf}, follow_redirects=False
        )
        assert retour.status_code == (403 if retrait == "role" else 303), retour.text

    assert _etat_persistance_console(session) == avant


def test_parcours_reception_import_rappel_rejeu_conflit_cloture_et_nouveau_rappel(client_console):
    client = client_console
    csrf = _connecter(client)

    premier = client.post("/api/reception/appels", json={**APPEL_MANQUE, "mutation_id": "appel-manque-1"},
                          headers=_headers(csrf))
    assert premier.status_code == 200, premier.text
    resultat = premier.json()["resultat"]
    assert resultat["envoi_automatique"] is False
    transfert_id = resultat["tache_rappel"]["transfert_id"]

    page = client.get("/reception")
    assert page.status_code == 200
    assert APPEL_MANQUE["source"] in page.text
    assert "Appels importés récemment" in page.text
    assert transfert_id in page.text
    appels = client.get("/api/reception/appels")
    assert appels.status_code == 200 and appels.json()["appels"][0]["source"] == APPEL_MANQUE["source"]

    formulaire = {
        **APPEL_MANQUE,
        "source": "Export manuel FICTIF formulaire",
        "evenement_id": "event-form-001",
        "appel_id": "appel-form-001",
        "mutation_id": "appel-form-001",
        "csrf": csrf,
    }
    importe_formulaire = client.post("/reception/appels", data=formulaire, follow_redirects=False)
    assert importe_formulaire.status_code == 303
    assert "Export manuel FICTIF formulaire" in client.get("/reception").text

    detail = client.get("/api/reception/transferts", params={"transfert_id": transfert_id})
    assert detail.status_code == 200 and detail.json()["resultat"]["statut"] == "ouvert"

    voicemail = {
        **APPEL_MANQUE,
        "evenement_id": "event-fictif-voicemail-002",
        "statut": "voicemail",
        "transcription": "Bonjour, mes gouttières fuient à Laval.",
        "consentement_enregistrement": "accorde",
        "mutation_id": "appel-voicemail-2",
    }
    importe = client.post("/api/reception/appels", json=voicemail, headers=_headers(csrf))
    assert importe.status_code == 200, importe.text
    rejoue = client.post("/api/reception/appels", json=voicemail, headers=_headers(csrf))
    assert rejoue.status_code == 200 and rejoue.json() == importe.json()

    conflit = client.post(
        "/api/reception/appels",
        json={**voicemail, "mutation_id": "appel-voicemail-contradictoire",
              "transcription": "Le client demande un remboursement."},
        headers=_headers(csrf),
    )
    assert conflit.status_code == 409
    assert conflit.json()["ok"] is False
    assert "REJ-APPEL-CONTRADICTOIRE" in conflit.json()["erreur"]["message"]

    clore = client.post("/api/reception/transferts", json={
        "transfert_id": transfert_id,
        "motif": "Rappel tenté et consigné au dossier.",
        "mutation_id": "clore-transfert-1",
    }, headers=_headers(csrf))
    assert clore.status_code == 200, clore.text
    assert clore.json()["ok"] is True
    assert client.get("/reception").status_code == 200
    assert transfert_id not in client.get("/reception").text

    nouvel_appel = {**APPEL_MANQUE, "appel_id": "appel-fictif-002", "evenement_id": "event-fictif-003",
                    "mutation_id": "appel-manque-3"}
    nouveau = client.post("/api/reception/appels", json=nouvel_appel, headers=_headers(csrf))
    assert nouveau.status_code == 200
    assert nouveau.json()["resultat"]["tache_rappel"]["transfert_id"] != transfert_id


def test_parcours_reputation_approbation_export_manuel_et_xss_prive(client_console):
    client = client_console
    csrf = _connecter(client)

    importe = client.post("/api/marketing/avis", json={**_avis(), "mutation_id": "avis-import-1"},
                          headers=_headers(csrf))
    assert importe.status_code == 200, importe.text
    avis_id = importe.json()["resultat"]["avis_id"]
    page = client.get("/marketing")
    assert "Excellent travail" in page.text
    assert "m7_importer_avis_manuel" not in page.text and "{\"" not in page.text

    approuve = client.post("/api/marketing/avis", json={
        "action": "approuver", "avis_id": avis_id, "mutation_id": "avis-approbation-1",
    }, headers=_headers(csrf))
    assert approuve.status_code == 200, approuve.text
    exporte = client.post("/api/marketing/avis", json={
        "action": "exporter", "avis_id": avis_id, "mutation_id": "avis-export-1",
    }, headers=_headers(csrf))
    assert exporte.status_code == 200, exporte.text
    assert exporte.json()["ok"] is True
    assert "copier manuellement" in str(exporte.json()).lower()
    assert "aucune publication" in str(exporte.json()).lower()

    plainte = _avis(
        avis_source_id="plainte-fictive-001", note=1,
        texte="Plainte urgente : demande de remboursement. <script>alert(2)</script>",
    )
    importe_plainte = client.post("/api/marketing/avis", json={**plainte, "mutation_id": "plainte-import-1"},
                                  headers=_headers(csrf))
    assert importe_plainte.status_code == 200
    plainte_id = importe_plainte.json()["resultat"]["avis_id"]
    page = client.get("/marketing")
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in page.text
    assert "<script>alert(2)</script>" not in page.text
    assert "Ce dossier reste privé" in page.text

    export_prive = client.post("/api/marketing/avis", json={
        "action": "exporter", "avis_id": plainte_id, "mutation_id": "plainte-export-1",
    }, headers=_headers(csrf))
    assert export_prive.status_code == 400
    assert export_prive.json()["ok"] is False


def test_refus_export_prive_est_rendu_et_ne_devient_pas_une_approbation_executee(
    client_console, session
):
    client = client_console
    csrf = _connecter(client)
    plainte = _avis(
        avis_source_id="plainte-ui-privee-001",
        note=1,
        texte="Plainte urgente : demande de remboursement.",
    )
    importe = client.post(
        "/api/marketing/avis",
        json={**plainte, "mutation_id": "plainte-ui-privee-import"},
        headers=_headers(csrf),
    )
    assert importe.status_code == 200, importe.text
    avis_id = importe.json()["resultat"]["avis_id"]
    assert list(stockage.maillons("m07-marketing", "reputation_exports")) == []
    assert list(stockage.maillons("m07-marketing", "reputation_decisions")) == []

    retour = client.post(
        "/marketing",
        data={
            "csrf": csrf,
            "action": "exporter",
            "avis_id": avis_id,
            "mutation_id": "plainte-ui-privee-export",
        },
        follow_redirects=False,
    )
    assert retour.status_code == 200
    assert 'role="alert"' in retour.text
    assert "les plaintes/urgences restent en traitement privé" in retour.text
    assert "Ce dossier reste privé" in retour.text
    assert "Paquet copié" not in retour.text
    assert list(stockage.maillons("m07-marketing", "reputation_exports")) == []
    assert list(stockage.maillons("m07-marketing", "reputation_decisions")) == []
    with session() as cnx:
        approbations = cnx.execute(select(APPROBATIONS)).mappings().all()
    assert len(approbations) == 1
    assert approbations[0]["outil"] == "m7_exporter_reponse_avis_manuel"
    assert approbations[0]["statut"] == "echec"
    assert '"accepte": false' in approbations[0]["resultat"]
