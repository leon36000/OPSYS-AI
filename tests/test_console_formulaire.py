"""Pont serveur M1 dans la vraie console, avec demandes et clés fictives."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from m1_front_office import outils as outils_m1
from m2_revenue_crm import outils as outils_m2
from sqlalchemy import func, select

from opsys import evenements, stockage, taxonomie
from opsys.console.application import creer_application
from opsys.console.securite import Configuration, ouvrir_session, signer_session
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_SORTANTS

RACINE = Path(__file__).resolve().parents[1]
SITE = "site-console-fictif"
CLE_PONT = b"cle-pont-formulaire-fictive-" + b"z" * 32
CONFIG = Configuration("cle-console-formulaire-fictive-" + "x" * 32, cookie_securise=False)
CHEMIN = "/interne/m1/formulaire"


@pytest.fixture
def instance(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    url = f"sqlite:///{tmp_path / 'opsys-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval"])
    outils_m1.utiliser_stockage_durable()
    outils_m2.utiliser_stockage_durable()
    departements = charger_departements(RACINE / "departments")
    yield departements
    outils_m1.reinitialiser_registre()
    outils_m2.reinitialiser_registre()
    stockage.liberer()


def _client(deps, **kwargs):
    return TestClient(creer_application(CONFIG, deps, stockage.transaction, **kwargs))


def _requete(**champs):
    corps = {"courriel": "client.fictif@example.test", "message": "Mes gouttières fuient à Laval."}
    corps.update(champs)
    donnees = json.dumps(corps, ensure_ascii=False, separators=(",", ":")).encode()
    date = str(int(time.time()))
    nonce = "nonce-console-fictif-0001"
    contenu_signe = f"v1\nPOST\n{CHEMIN}\n{SITE}\n{date}\n{nonce}\n".encode() + donnees
    signature = hmac.new(CLE_PONT, contenu_signe, hashlib.sha256).hexdigest()
    return donnees, {
        "content-type": "application/json", "x-m1-site": SITE, "x-m1-timestamp": date,
        "x-m1-nonce": nonce, "x-m1-signature": signature,
    }


def _nombre_evenements():
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one()


def test_pont_console_desactive_par_defaut_sans_evenement(instance):
    corps, entetes = _requete()
    reponse = _client(instance).post(CHEMIN, content=corps, headers=entetes)
    assert reponse.status_code == 503
    assert reponse.json() == {"ok": False, "error": "unavailable"}
    assert _nombre_evenements() == 0


def test_pont_console_signe_rejoint_registres_m1_et_m2_sans_envoi_client(instance):
    client = _client(instance, site_formulaire=SITE, secret_formulaire=CLE_PONT)
    corps, entetes = _requete(utm_source="campagne-fictive", utm_medium="site")
    for _ in range(2):
        reponse = client.post(CHEMIN, content=corps, headers=entetes)
        assert reponse.status_code == 202
        assert reponse.json() == {"ok": True, "received": True}
    assert _nombre_evenements() == 1
    dep = instance["m02-revenue-crm"]
    resultat = evenements.repartir({dep.id: dep})
    assert resultat["livres"] == resultat["traites"] == 1
    assert resultat["echecs"] == resultat["quarantaines"] == 0
    with stockage.transaction():
        reception = outils_m1._obtenir_registre().lire()
        crm = outils_m2._obtenir_registre().lire()
    assert len([ligne for ligne in reception if ligne["type_entree"] == "signal"]) == 1
    leads = [ligne for ligne in crm if "contrat" in ligne]
    assert len(leads) == 1
    assert leads[0]["contrat"]["contact"] == {"courriel": "client.fictif@example.test"}
    assert leads[0]["contrat"]["utm"] == {"utm_source": "campagne-fictive", "utm_medium": "site"}
    with stockage.transaction() as cnx:
        types = cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement)).scalars().all()
    assert sorted(types) == ["m1.lead_qualifie", "m2.client_associe"]


def test_pont_console_cookie_humain_ne_remplace_pas_signature_serveur(instance):
    client = _client(instance, site_formulaire=SITE, secret_formulaire=CLE_PONT)
    session = ouvrir_session("administrateur.fictif", ["admin"])
    client.cookies.set("opsys_session", signer_session(session, CONFIG.secret))
    corps, _ = _requete()
    reponse = client.post(CHEMIN, content=corps, headers={"content-type": "application/json"})
    assert reponse.status_code == 403
    assert "client.fictif" not in reponse.text
    assert _nombre_evenements() == 0


def test_pont_console_sans_m1_installe_reste_indisponible(instance):
    client = _client({}, site_formulaire=SITE, secret_formulaire=CLE_PONT)
    corps, entetes = _requete()
    reponse = client.post(CHEMIN, content=corps, headers=entetes)
    assert reponse.status_code == 503
    assert reponse.json() == {"ok": False, "error": "unavailable"}
    assert _nombre_evenements() == 0


def test_cle_cookie_ne_peut_pas_servir_de_cle_du_pont(instance):
    with pytest.raises(ValueError, match="clé dédiée"):
        _client(instance, site_formulaire=SITE, secret_formulaire=CONFIG.secret.encode())
    assert _nombre_evenements() == 0


def test_pont_console_refuse_outil_choisi_par_le_corps(instance):
    client = _client(instance, site_formulaire=SITE, secret_formulaire=CLE_PONT)
    corps, entetes = _requete(outil="m5_action_fictive")
    reponse = client.post(CHEMIN, content=corps, headers=entetes)
    assert reponse.status_code == 400
    assert "m5_action_fictive" not in reponse.text
    assert _nombre_evenements() == 0
