"""Premier oracle HTTP rouge : un CAS périmé ne doit rien inscrire au registre M1."""

from __future__ import annotations

import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update

from opsys import contexte, identite, stockage
from opsys.console import frontoffice_marketing
from opsys.stockage.schema import META, REGISTRES

_BASE_PATH = Path(__file__).with_name("test_console_metier.py")
_BASE_SPEC = importlib.util.spec_from_file_location("_console_metier_suivi_rappel_base", _BASE_PATH)
assert _BASE_SPEC is not None and _BASE_SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_BASE_SPEC)
sys.modules[_BASE_SPEC.name] = _BASE
_BASE_SPEC.loader.exec_module(_BASE)


@pytest.fixture
def client_console(session, monkeypatch):
    yield from _BASE.client_console.__wrapped__(session, monkeypatch)


def _instantane_base(session):
    with session() as cnx:
        return tuple(
            (table.name, tuple(tuple(ligne) for ligne in cnx.execute(select(table)).all()))
            for table in META.sorted_tables
        )


def test_cas_perime_refuse_prise_en_charge_sans_effet(client_console, session):
    client = client_console
    csrf = _BASE._connecter(client)
    appel = client.post(
        "/api/reception/appels",
        json={**_BASE.APPEL_MANQUE, "mutation_id": f"appel-manque-rappel-{uuid4()}"},
        headers=_BASE._headers(csrf),
    )
    assert appel.status_code == 200, appel.text
    transfert_id = appel.json()["resultat"]["tache_rappel"]["transfert_id"]

    avant = _instantane_base(session)
    response = client.post(
        f"/api/reception/transferts/{transfert_id}/suivi-rappel",
        json={
            "action": "prise_en_charge",
            "snapshot_attendu": "0" * 64,
            "mutation_id": str(uuid4()),
        },
        headers=_BASE._headers(csrf),
    )

    assert response.status_code == 409, response.text
    assert _instantane_base(session) == avant


def _importer_rappel(client, csrf):
    response = client.post(
        "/api/reception/appels",
        json={**_BASE.APPEL_MANQUE, "mutation_id": str(uuid4())},
        headers=_BASE._headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["resultat"]["tache_rappel"]["transfert_id"]


def _lire(client, transfert_id):
    response = client.get("/api/reception/transferts", params={"transfert_id": transfert_id})
    assert response.status_code == 200, response.text
    return response.json()["resultat"]


def _prise(client, transfert_id):
    return {
        "action": "prise_en_charge",
        "snapshot_attendu": _lire(client, transfert_id)["suivi_rappel"]["snapshot_suivi"],
        "mutation_id": str(uuid4()),
    }


def _post(client, csrf, transfert_id, corps, transport="api"):
    if transport == "formulaire":
        return client.post(
            f"/reception/transferts/{transfert_id}/suivi-rappel",
            data={**corps, "csrf": csrf}, follow_redirects=False,
        )
    return client.post(
        f"/api/reception/transferts/{transfert_id}/suivi-rappel",
        json=corps, headers=_BASE._headers(csrf),
    )


@pytest.mark.parametrize("transport", ["api", "formulaire"])
def test_prise_tentative_file_ouverte_cloture_distincte_et_rejeu(client_console, session, transport):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    avant_digest = client.get("/api/reception/digest?date_reference=2026-09-30").json()["digest"]
    page = client.get(f"/reception/transferts/{transfert_id}")
    assert "Prendre ce rappel en charge" in page.text
    assert "Motif de clôture" in page.text
    assert "Note de prise en charge" not in page.text

    commande = _prise(client, transfert_id)
    prise = _post(client, csrf, transfert_id, commande, transport)
    assert prise.status_code == (200 if transport == "api" else 303), prise.text
    assert prise.headers["cache-control"] == "no-store"
    donnees = _lire(client, transfert_id)
    suivi = donnees["suivi_rappel"]
    assert donnees["statut"] == "ouvert"
    assert suivi["responsable"] == "nathan" and suivi["role"] == "nathan_owner"
    assert suivi["pris_en_charge_le"] is not None
    assert suivi["tentatives_sans_contact"] == 0
    avant_rejeu = _instantane_base(session)
    assert _post(client, csrf, transfert_id, commande, transport).status_code == prise.status_code
    assert _instantane_base(session) == avant_rejeu

    tentative = {
        "action": "tentative_sans_contact", "snapshot_attendu": suivi["snapshot_suivi"],
        "prochaine_tentative_le": "2099-10-04T09:15:00-04:00", "mutation_id": str(uuid4()),
    }
    response = _post(client, csrf, transfert_id, tentative, transport)
    assert response.status_code == prise.status_code, response.text
    donnees = _lire(client, transfert_id)
    suivi = donnees["suivi_rappel"]
    assert donnees["statut"] == "ouvert" and suivi["tentatives_sans_contact"] == 1
    assert suivi["prochaine_tentative_le"] == "2099-10-04T13:15:00.000000+00:00"
    assert suivi["derniere_tentative_le"] is not None
    assert transfert_id in client.get("/reception").text
    page = client.get(f"/reception/transferts/{transfert_id}")
    assert "Consigner une tentative sans contact" in page.text
    assert "ne certifient ni un appel téléphonique ni un contact établi" in page.text
    assert "Prochaine tentative prévue" in page.text
    assert client.get("/api/reception/digest?date_reference=2026-09-30").json()["digest"] == avant_digest

    cloture = client.post(
        "/api/reception/transferts",
        json={"transfert_id": transfert_id, "motif": "Rappel fictif terminé après contact humain.",
              "mutation_id": str(uuid4())}, headers=_BASE._headers(csrf),
    )
    assert cloture.status_code == 200, cloture.text
    assert _lire(client, transfert_id)["statut"] == "clos"
    apres_cloture = _instantane_base(session)
    rejoue = _post(client, csrf, transfert_id, tentative, transport)
    assert rejoue.status_code == prise.status_code, rejoue.text
    assert _instantane_base(session) == apres_cloture
    nouvelle = _post(client, csrf, transfert_id, {**tentative, "mutation_id": str(uuid4())}, transport)
    assert nouvelle.status_code == 409 and _instantane_base(session) == apres_cloture
    assert "Consigner une tentative sans contact" not in client.get(f"/reception/transferts/{transfert_id}").text


def test_reprise_exacte_et_conflit_cle_cas_sans_ajout(client_console, session):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    initial = _post(client, csrf, transfert_id, commande)
    assert initial.status_code == 200, initial.text
    avant = _instantane_base(session)
    rejoue = _post(client, csrf, transfert_id, commande)
    assert rejoue.status_code == 200 and rejoue.json()["rejoue"] is True
    assert rejoue.json()["resultat"] == initial.json()["resultat"]
    assert _instantane_base(session) == avant
    contradiction = _post(client, csrf, transfert_id, {**commande, "snapshot_attendu": "f" * 64})
    assert contradiction.status_code == 409 and _instantane_base(session) == avant
    obsolete = _post(client, csrf, transfert_id, {**commande, "mutation_id": str(uuid4())})
    assert obsolete.status_code == 409 and _instantane_base(session) == avant


@pytest.mark.parametrize("transport", ["api", "formulaire"])
@pytest.mark.parametrize("extra", ["par", "role", "horodatage", "transfert_id", "texte"])
def test_rejette_champs_forges_avant_toute_ecriture(client_console, session, transport, extra):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = {**_prise(client, transfert_id), extra: "valeur-fictive"}
    avant = _instantane_base(session)
    response = _post(client, csrf, transfert_id, commande, transport)
    assert response.status_code == 400 and _instantane_base(session) == avant
    assert "valeur-fictive" not in response.text


@pytest.mark.parametrize("prochaine", [
    None, True, "2026-10-04", "2099-10-04T09:15:00", "2099-02-30T09:00:00+00:00",
    "2099-10-04T09:15:00.1234567+00:00", "9999-12-31T23:59:59-01:00", "2000-01-01T00:00:00+00:00",
])
def test_echeance_invalide_ou_passee_refuse_sans_claim(client_console, session, prochaine):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    prise = _post(client, csrf, transfert_id, _prise(client, transfert_id))
    assert prise.status_code == 200, prise.text
    commande = {
        "action": "tentative_sans_contact",
        "snapshot_attendu": _lire(client, transfert_id)["suivi_rappel"]["snapshot_suivi"],
        "mutation_id": str(uuid4()), "prochaine_tentative_le": prochaine,
    }
    avant = _instantane_base(session)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == 400 and _instantane_base(session) == avant


def test_admin_actif_attribution_a_soi_seul_et_autre_operateur_refuse(client_console, session):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    with session() as cnx:
        identite.creer_personne(cnx, "admin-rappel", "Admin FICTIF", "mot-de-passe-admin-fictif", ["admin"])
    client.cookies.clear()
    connexion = client.post("/connexion", data={
        "identifiant": "admin-rappel", "mot_de_passe": "mot-de-passe-admin-fictif",
    }, follow_redirects=False)
    assert connexion.status_code == 303
    csrf = client.get("/api/session").json()["csrf"]
    response = _post(client, csrf, transfert_id, _prise(client, transfert_id))
    assert response.status_code == 200, response.text
    suivi = response.json()["resultat"]["suivi_rappel"]
    assert suivi["responsable"] == "admin-rappel" and suivi["role"] == "admin"
    _BASE._connecter(client)
    csrf = client.get("/api/session").json()["csrf"]
    avant = _instantane_base(session)
    tentative = _post(client, csrf, transfert_id, {
        "action": "tentative_sans_contact", "snapshot_attendu": suivi["snapshot_suivi"],
        "mutation_id": str(uuid4()), "prochaine_tentative_le": "2099-10-04T09:15:00-04:00",
    })
    assert tentative.status_code == 409 and _instantane_base(session) == avant
    assert "Consigner une tentative sans contact" not in client.get(f"/reception/transferts/{transfert_id}").text


@pytest.mark.parametrize("retrait", ["role", "desactivation"])
def test_retrait_reel_refuse_aussi_rejeu_sans_ecriture(client_console, session, retrait):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    assert _post(client, csrf, transfert_id, commande).status_code == 200
    with session() as cnx:
        if retrait == "role":
            identite.retirer_role(cnx, "nathan", "nathan_owner")
        else:
            identite.activer(cnx, "nathan", False)
    avant = _instantane_base(session)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == (403 if retrait == "role" else 401)
    assert _instantane_base(session) == avant
    assert "snapshot_suivi" not in response.text
    lecture = client.get("/api/reception/transferts", params={"transfert_id": transfert_id})
    assert lecture.status_code == (403 if retrait == "role" else 401)
    assert "15145550142" not in lecture.text and "suivi_rappel" not in lecture.text
    fiche = client.get(f"/reception/transferts/{transfert_id}", follow_redirects=False)
    assert fiche.status_code == (403 if retrait == "role" else 303)
    assert "15145550142" not in fiche.text and "Suivi du rappel" not in fiche.text
    assert _instantane_base(session) == avant


@pytest.mark.parametrize("point", ["metier", "rendu"])
@pytest.mark.parametrize("retrait", ["role", "expiration"])
def test_refus_apres_effet_ou_rendu_rollback_toutes_tables(
    client_console, session, monkeypatch, point, retrait,
):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    avant = _instantane_base(session)

    def retirer():
        if retrait == "role":
            identite.retirer_role(stockage.connexion_courante(), "nathan", "nathan_owner")
        else:
            monkeypatch.setattr(frontoffice_marketing, "time", SimpleNamespace(time=lambda: 9_999_999_999))

    if point == "metier":
        original = frontoffice_marketing.metier.executer

        def effet_puis_retrait(*args, **kwargs):
            response = original(*args, **kwargs)
            retirer()
            return response

        monkeypatch.setattr(frontoffice_marketing.metier, "executer", effet_puis_retrait)
    else:
        original = frontoffice_marketing.JSONResponse

        def rendu_puis_retrait(*args, **kwargs):
            response = original(*args, **kwargs)
            retirer()
            return response

        monkeypatch.setattr(frontoffice_marketing, "JSONResponse", rendu_puis_retrait)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == (403 if retrait == "role" else 401), response.text
    assert _instantane_base(session) == avant
    assert "snapshot_suivi" not in response.text


@pytest.mark.parametrize("transport", ["api", "formulaire"])
def test_csrf_et_employe_refuses_sans_effet(client_console, session, transport):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    avant = _instantane_base(session)
    response = _post(client, "mauvais-csrf-fictif", transfert_id, commande, transport)
    assert response.status_code == 403 and _instantane_base(session) == avant
    _BASE._connecter(client, "employe")
    csrf = client.get("/api/session").json()["csrf"]
    avant = _instantane_base(session)
    response = _post(client, csrf, transfert_id, commande, transport)
    assert response.status_code == 403 and _instantane_base(session) == avant


@pytest.mark.parametrize("voie", ["html", "json", "mutation"])
def test_borne_source_reelle_avant_decodeur_sur_fiche_alias_et_commande(
    client_console, session, monkeypatch, voie,
):
    client = client_console
    csrf = _BASE._connecter(client)
    with session() as cnx:
        cnx.execute(insert(REGISTRES).values(
            departement="m01-front-office", registre="principal", rang=0, maillon="é" * 32_769,
        ))
    avant = _instantane_base(session)
    from opsys.stockage import codec

    appels_decodeur = []

    def ne_pas_decoder(*args):
        appels_decodeur.append(True)
        raise AssertionError("quota devait refuser avant décodage")

    monkeypatch.setattr(codec, "decoder", ne_pas_decoder)
    if voie == "html":
        response = client.get("/reception/transferts/transfert-fictif")
    elif voie == "json":
        response = client.get("/api/reception/transferts", params={"transfert_id": "transfert-fictif"})
    else:
        response = _post(client, csrf, "transfert-fictif", {
            "action": "prise_en_charge", "snapshot_attendu": "0" * 64, "mutation_id": str(uuid4()),
        })
    assert response.status_code == 503 and _instantane_base(session) == avant
    assert appels_decodeur == []


def test_reponse_malformee_apres_effet_est_fermee_et_annulee(client_console, session, monkeypatch):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    avant = _instantane_base(session)
    original = frontoffice_marketing.metier.executer

    def effet_puis_corruption(*args, **kwargs):
        original(*args, **kwargs)
        return {"ok": True, "resultat": {"suivi_rappel": {"secret": "+15145550142"}}}

    monkeypatch.setattr(frontoffice_marketing.metier, "executer", effet_puis_corruption)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == 503 and _instantane_base(session) == avant
    assert "secret" not in response.text and "15145550142" not in response.text


@pytest.mark.parametrize("incident", ["refus_sans_code", "role_retire"])
def test_port_metier_refuse_apres_outil_sans_finaliser_receipt(client_console, session, monkeypatch, incident):
    metier = frontoffice_marketing.metier
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    avant = _instantane_base(session)
    original = metier.executer_atomique

    def effet_puis_incident(outil, charge):
        reponse = original(outil, charge)
        if incident == "role_retire":
            identite.retirer_role(stockage.connexion_courante(), "nathan", "nathan_owner")
            return reponse
        return {"ok": True, "resultat": {"accepte": False, "verdict": {}}}

    monkeypatch.setattr(metier, "executer_atomique", effet_puis_incident)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == (403 if incident == "role_retire" else 503), response.text
    assert _instantane_base(session) == avant


def test_deux_requetes_sur_meme_snapshot_une_seule_prise(client_console, session, monkeypatch):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    barriere = Barrier(2)
    original = frontoffice_marketing._arguments_suivi_rappel

    def avant_transaction(*args, **kwargs):
        resultat = original(*args, **kwargs)
        barriere.wait(timeout=5)
        return resultat

    monkeypatch.setattr(frontoffice_marketing, "_arguments_suivi_rappel", avant_transaction)

    def requete_independante():
        # Deux portals permettent deux requêtes simultanées sans bloquer la même boucle async.
        with TestClient(client.app, base_url=str(client.base_url), cookies=dict(client.cookies)) as concurrent:
            return _post(concurrent, csrf, transfert_id, {**commande, "mutation_id": str(uuid4())})

    with ThreadPoolExecutor(max_workers=2) as pool:
        reponses = [pool.submit(requete_independante) for _ in range(2)]
        codes = [response.result(timeout=15).status_code for response in reponses]
    assert sorted(codes) == [200, 409]
    with session():
        prises = [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                  if ligne.get("transfert_id") == transfert_id and ligne.get("evenement") == "prise_en_charge"]
    assert len(prises) == 1


def test_ventes_ordinaire_sans_source_rappel_ne_recoit_pas_de_suivi(client_console, session):
    from m1_front_office import outils, transferts

    client = client_console
    csrf = _BASE._connecter(client)
    with session():
        ligne, verdict = transferts.preparer_ouverture(
            [], type_transfert="ventes", categories=(), termes={}, declenche_par=transferts.DECLENCHE_PAR_REGLES,
            canal="texte", source="sms", conversation_id="sms-fictif-sans-appel",
            message_courant={"signal_id": "sms:fictif-sans-appel", "horodatage": _BASE.HEURE_SOURCE,
                             "contenu_filtre": "Demande de rappel FICTIF."},
            contact={"telephone": "+15145550142"}, contact_source="canal", destinataire="ventes",
            verdict_destinataire=None,
        )
        assert verdict is None and ligne is not None
        outils._obtenir_registre().ajouter(ligne)
        transfert_id = ligne["transfert_id"]
    charge = _lire(client, transfert_id)
    assert "suivi_rappel" not in charge
    assert "Prendre ce rappel en charge" not in client.get(f"/reception/transferts/{transfert_id}").text
    avant = _instantane_base(session)
    response = _post(client, csrf, transfert_id, {
        "action": "prise_en_charge", "snapshot_attendu": "0" * 64, "mutation_id": str(uuid4()),
    })
    assert response.status_code == 409 and _instantane_base(session) == avant


@pytest.mark.parametrize("voie", ["html", "json", "mutation"])
def test_source_en_memoire_refusee_sans_fallback(client_console, session, monkeypatch, voie):
    from m1_front_office import outils

    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    avant = _instantane_base(session)
    monkeypatch.setattr(outils, "_stockage_durable_actif", False)
    if voie == "html":
        response = client.get(f"/reception/transferts/{transfert_id}")
    elif voie == "json":
        response = client.get("/api/reception/transferts", params={"transfert_id": transfert_id})
    else:
        response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == 503 and _instantane_base(session) == avant


def test_get_dossier_inconnu_conserve_statuts_anciens_sans_echo(client_console, session):
    client = client_console
    _BASE._connecter(client)
    identifiant = "dossier-inconnu-fictif-15145550142"
    avant = _instantane_base(session)
    fiche = client.get(f"/reception/transferts/{identifiant}")
    api = client.get("/api/reception/transferts", params={"transfert_id": identifiant})
    assert fiche.status_code == 404 and api.status_code == 400
    assert api.json() == {
        "ok": False, "erreur": {"code": "REJ-TRANSFERT-INCONNU", "message": "dossier indisponible"},
    }
    assert identifiant not in fiche.text + api.text and "15145550142" not in fiche.text + api.text
    assert _instantane_base(session) == avant


@pytest.mark.parametrize("incoherence", [
    {"responsable": "autre-proprietaire-fictif"},
    {"responsable": None, "role": None},
    {"pris_en_charge_le": None},
    {"derniere_tentative_le": "2099-10-04T09:00:00+00:00"},
    {"tentatives_sans_contact": 1, "derniere_tentative_le": None, "prochaine_tentative_le": None},
    {"tentatives_sans_contact": 1, "derniere_tentative_le": "2000-10-04T09:00:00+00:00",
     "prochaine_tentative_le": "2099-10-04T09:00:00+00:00"},
    {"tentatives_sans_contact": 1, "derniere_tentative_le": "2099-10-04T09:00:00+00:00",
     "prochaine_tentative_le": "2099-10-04T08:00:00+00:00"},
])
def test_projection_champs_valides_mais_etat_incoherent_rollback(
    client_console, session, monkeypatch, incoherence,
):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    avant = _instantane_base(session)
    original = frontoffice_marketing.metier.executer

    def effet_puis_incoherence(*args, **kwargs):
        response = original(*args, **kwargs)
        projection = response["resultat"]["resultat"]["suivi_rappel"]
        return {"ok": True, "resultat": {"accepte": True, "resultat": {
            "suivi_rappel": {**projection, **incoherence},
        }}}

    monkeypatch.setattr(frontoffice_marketing.metier, "executer", effet_puis_incoherence)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == 503, response.text
    assert "snapshot_suivi" not in response.text
    assert _instantane_base(session) == avant


@pytest.mark.parametrize("borne", ["maillon", "lignes", "total"])
def test_outil_direct_borne_sql_avant_decodeur_sans_passer_par_ui(
    client_console, session, monkeypatch, borne,
):
    from datetime import UTC, datetime

    from m1_front_office import outils

    from opsys.stockage import codec

    _BASE._connecter(client_console)
    if borne == "maillon":
        valeurs = ["é" * 32_769]
    elif borne == "lignes":
        valeurs = ["{}"] * 10_001
    else:
        valeurs = ["a" * 65_536] * 129
    with session() as cnx:
        cnx.execute(insert(REGISTRES), [
            {"departement": "m01-front-office", "registre": "principal", "rang": i, "maillon": texte}
            for i, texte in enumerate(valeurs)
        ])
    avant = _instantane_base(session)
    appels_decodeur = []

    def ne_pas_decoder(*args):
        appels_decodeur.append(True)
        raise AssertionError("quota devait refuser avant décodage")

    monkeypatch.setattr(codec, "decoder", ne_pas_decoder)
    with (
        pytest.raises(RuntimeError, match="source non qualifiée"),
        session(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "nathan_owner", source="console")),
    ):
        outils.consigner_suivi_rappel(
            "transfert-fictif", "prise_en_charge", "0" * 64, datetime.now(UTC).isoformat(),
        )
    assert appels_decodeur == []
    assert _instantane_base(session) == avant


def test_chaine_reelle_alteree_refuse_mutation_sans_receipt_ni_append(client_console, session):
    from opsys.stockage import codec

    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    with session() as cnx:
        rows = cnx.execute(select(REGISTRES).where(
            REGISTRES.c.departement == "m01-front-office", REGISTRES.c.registre == "principal",
        )).all()
        for row in rows:
            ligne = codec.decoder(row.maillon)
            if ligne.get("transfert_id") == transfert_id and ligne.get("evenement") == "ouvert":
                ligne["resume"] = "Résumé FICTIF altéré sans recalcul de chaîne."
                cnx.execute(update(REGISTRES).where(
                    REGISTRES.c.departement == "m01-front-office", REGISTRES.c.registre == "principal",
                    REGISTRES.c.rang == row.rang,
                ).values(maillon=codec.encoder(ligne)))
                break
        else:
            pytest.fail("ouverture canonique absente")
    avant = _instantane_base(session)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == 503, response.text
    assert "Résumé FICTIF" not in response.text
    assert _instantane_base(session) == avant


@pytest.mark.parametrize("meme_dossier", [True, False])
def test_source_tardive_invalide_seul_le_dossier_concerne(client_console, session, meme_dossier):
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    nouvelle = {
        **_BASE.APPEL_MANQUE, "evenement_id": "event-tardif-fictif", "appel_id": "appel-tardif-fictif",
        "mutation_id": str(uuid4()),
    }
    if not meme_dossier:
        nouvelle["telephone"] = "+15145550199"
    importe = client.post("/api/reception/appels", json=nouvelle, headers=_BASE._headers(csrf))
    assert importe.status_code == 200, importe.text
    autre_id = importe.json()["resultat"]["tache_rappel"]["transfert_id"]
    assert (autre_id == transfert_id) is meme_dossier
    avant = _instantane_base(session)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == (409 if meme_dossier else 200), response.text
    if meme_dossier:
        assert _instantane_base(session) == avant
    else:
        assert _lire(client, transfert_id)["suivi_rappel"]["responsable"] == "nathan"
        assert _lire(client, autre_id)["suivi_rappel"]["responsable"] is None


@pytest.mark.parametrize("incident", ["expiration_initiale", "role_retiré_pendant_rejeu"])
def test_port_metier_direct_revalide_session_et_recu(client_console, session, monkeypatch, incident):
    from datetime import UTC, datetime

    from opsys.console.securite import Session
    from opsys.departements import charger_departements

    metier = frontoffice_marketing.metier
    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    assert _post(client, csrf, transfert_id, commande).status_code == 200
    avant = _instantane_base(session)
    vraie_reclamation = metier.idempotence.reclamer

    def reclamation_puis_retrait(cnx, *args, **kwargs):
        resultat = vraie_reclamation(cnx, *args, **kwargs)
        assert resultat.rejouee
        identite.retirer_role(cnx, "nathan", "nathan_owner")
        return resultat

    if incident == "role_retiré_pendant_rejeu":
        monkeypatch.setattr(metier.idempotence, "reclamer", reclamation_puis_retrait)
    humaine = Session("nathan", frozenset({"nathan_owner"}), csrf,
                      0 if incident == "expiration_initiale" else int(datetime.now(UTC).timestamp()) + 300)
    with pytest.raises(PermissionError), session() as cnx:
        metier.executer(
            cnx, charger_departements(), humaine, "m1_consigner_suivi_rappel",
            {"transfert_id": transfert_id, "action": commande["action"],
             "snapshot_attendu": commande["snapshot_attendu"]}, mutation_id=commande["mutation_id"],
        )
    assert _instantane_base(session) == avant


def test_ajout_a_la_borne_inclusive_refuse_avant_second_decode_et_rollback(client_console, session, monkeypatch):
    from m1_front_office import outils
    from m1_front_office.registre import Registre

    from opsys.stockage import codec

    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    with session() as cnx:
        initiales = outils._obtenir_registre().lire()
        nombre_initial = len(initiales)
        memoire = Registre(initiales)
        for index in range(10_000 - nombre_initial):
            memoire.ajouter({"type_entree": "alerte", "horodatage": _BASE.HEURE_SOURCE,
                            "fictif": True, "index_fictif": index})
        cnx.execute(insert(REGISTRES), [
            {"departement": "m01-front-office", "registre": "principal", "rang": rang,
             "maillon": codec.encoder(ligne)}
            for rang, ligne in enumerate(memoire.lire()[nombre_initial:], start=nombre_initial)
        ])
    commande = _prise(client, transfert_id)
    avant = _instantane_base(session)
    reg = outils._obtenir_registre()
    ajouter_original = reg.ajouter
    decoder_original = codec.decoder
    apres_ajout = False
    decodages_apres = []

    def ajouter_puis_marquer(ligne):
        nonlocal apres_ajout
        resultat = ajouter_original(ligne)
        apres_ajout = True
        return resultat

    def decoder_observe(*args, **kwargs):
        if apres_ajout:
            decodages_apres.append(True)
        return decoder_original(*args, **kwargs)

    monkeypatch.setattr(reg, "ajouter", ajouter_puis_marquer)
    monkeypatch.setattr(codec, "decoder", decoder_observe)
    response = _post(client, csrf, transfert_id, commande)
    assert response.status_code == 503, response.text
    assert apres_ajout and decodages_apres == []
    assert _instantane_base(session) == avant


@pytest.mark.parametrize("role", ["nathan_owner", "admin"])
def test_nouveau_suivi_appareil_est_refuse_meme_pour_humain_actif(client_console, session, role):
    from m1_front_office import outils

    client = client_console
    csrf = _BASE._connecter(client)
    transfert_id = _importer_rappel(client, csrf)
    commande = _prise(client, transfert_id)
    if role == "admin":
        with session() as cnx:
            identite.ajouter_role(cnx, "nathan", "admin")
    avant = _instantane_base(session)
    with session(), contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", role, source="appareil")):
        reponse = outils.consigner_suivi_rappel(
            transfert_id, commande["action"], commande["snapshot_attendu"], _BASE.HEURE_SOURCE,
        )
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-SUIVI-RAPPEL-HUMAIN-REQUIS"
    assert _instantane_base(session) == avant
