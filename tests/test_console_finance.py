"""Parcours console CFO sur les outils M5 et les registres durables (données de test fictives)."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_M5_SRC = Path(__file__).resolve().parents[1] / "departments" / "m05-financecore" / "src"
if str(_M5_SRC) not in sys.path:
    sys.path.insert(0, str(_M5_SRC))

import m5_financecore.outils as m5_outils  # noqa: E402

from opsys import contexte, identite, stockage  # noqa: E402
from opsys.console import application, metier  # noqa: E402
from opsys.console.securite import Configuration  # noqa: E402
from opsys.departements import charger_departements  # noqa: E402

SECRET = "secret-finance-console-test-" + "x" * 32
PREFIXE = "/opsys"
NOM = "nathan.fictif"
MOT_DE_PASSE = "mot-de-passe-finance-fictif-123"


def _horloge_serveur_utc(monkeypatch):
    maintenant = datetime(2026, 10, 8, 0, 0, 1, tzinfo=UTC)

    class Horloge(datetime):
        @classmethod
        def now(cls, tz=None):
            return maintenant.astimezone(tz) if tz is not None else maintenant.replace(tzinfo=None)

    monkeypatch.setattr(metier, "datetime", Horloge)
    return maintenant


@pytest.fixture
def client_finance(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'console-finance.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, NOM, "Nathan fictif", MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "employe.fictif", "Employé fictif", MOT_DE_PASSE, ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Administrateur fictif", MOT_DE_PASSE, ["admin"])
    app = application.creer_application(Configuration(SECRET), charger_departements(), stockage.transaction)
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client
    stockage.liberer()


def _connecter(client, utilisateur=NOM):
    retour = client.post(
        "/connexion", data={"identifiant": utilisateur, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False
    )
    assert retour.status_code == 303
    return client


def _csrf(client):
    return client.get("/api/session").json()["csrf"]


def _commande(**overrides):
    demain = date.today() + timedelta(days=15)
    resultat = {
        "actif": "Camion de service",
        "prix": "95000.00",
        "source_prix": "Offre C-95 fictive",
        "prix_valide_jusqua": demain.isoformat(),
        "mutation_id": "decision-camion-95-fictif",
        "offre_financement": {
            "source": "Offre F-95 fictive",
            "mise_de_fonds": "5000.00",
            "paiement_mensuel": "1600.00",
            "mois": 60,
        },
        "offre_location": {
            "source": "Offre L-95 fictive",
            "mise_de_fonds": "3000.00",
            "paiement_mensuel": "1800.00",
            "mois": 48,
        },
    }
    resultat.update(overrides)
    return resultat


def test_finance_get_lit_projection_et_authentifie_sans_trace_metier(client_finance):
    assert client_finance.get("/finance", follow_redirects=False).status_code == 303
    client = _connecter(client_finance)
    with stockage.transaction():
        avant = stockage.maillons("m05-financecore", "constats_cash_libre")
    page = client.get("/finance")
    api = client.get("/api/finance/cash-libre")
    with stockage.transaction():
        apres = stockage.maillons("m05-financecore", "constats_cash_libre")
    assert page.status_code == 200 and "Cash libre réel" in page.text
    assert "Non calculable" in page.text and "paies" in page.text
    assert api.status_code == 200
    assert api.json()["cash_libre"]["calculable"] is False
    assert len(avant) == len(apres) == 0
    assert "script-src 'self'" in page.headers["content-security-policy"]


def test_finance_calendrier_utilise_la_date_serveur_et_garde_les_manques(client_finance, monkeypatch):
    maintenant = _horloge_serveur_utc(monkeypatch)
    client = _connecter(client_finance)
    with stockage.transaction():
        avant = list(stockage.maillons("m05-financecore", "principal"))
    retour = client.get("/api/finance/obligations")
    assert retour.status_code == 200, retour.text
    calendrier = retour.json()["etat"]["resultat"]
    assert calendrier["aujourd_hui"] == maintenant.date().isoformat()
    assert {ligne["id"] for ligne in calendrier["obligations"]} == {"paies", "das", "dettes"}
    assert all(ligne["statut"] == "INCOMPLETE" for ligne in calendrier["obligations"])
    assert all(ligne["montant_utilisable"] is None for ligne in calendrier["obligations"])
    assert client.get("/api/finance/obligations?aujourd_hui=2020-01-01").status_code == 400
    page = client.get("/finance")
    assert page.status_code == 200 and "Échéances et obligations" in page.text
    assert "Déductions à la source" in page.text
    assert "Données incomplètes" in page.text and "Validation" in page.text
    assert "TPS/TVQ préparatoires" in page.text
    with stockage.transaction():
        assert list(stockage.maillons("m05-financecore", "principal")) == avant


def test_finance_calendrier_revalide_la_personne_apres_ouverture(client_finance):
    client = _connecter(client_finance)
    assert client.get("/finance").status_code == 200
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, NOM, "nathan_owner")
    assert client.get("/api/finance/obligations").status_code == 403


def test_finance_refuse_csrf_role_employe_et_injection_acteur_date(client_finance):
    client = _connecter(client_finance)
    commande = _commande()
    assert client.post("/api/finance/decision", json=commande).status_code == 403
    headers = {"x-csrf-token": _csrf(client)}
    assert client.post("/api/finance/decision", json={**commande, "role": "admin"}, headers=headers).status_code == 400
    assert (
        client.post(
            "/api/finance/decision", json={**commande, "aujourd_hui": "2000-01-01"}, headers=headers
        ).status_code
        == 400
    )
    employe = _connecter(client, "employe.fictif")
    assert employe.get("/finance").status_code == 403
    assert employe.get("/api/finance/cash-libre").status_code == 403
    assert (
        employe.post("/api/finance/decision", json=commande, headers={"x-csrf-token": _csrf(employe)}).status_code
        == 403
    )
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante(NOM, "nathan_owner", source="appareil")),
    ):
        proprietaire_appareil = m5_outils.etat_tresorerie(autorise_couts=True)
    assert proprietaire_appareil["accepte"] is False
    assert proprietaire_appareil["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_finance_decision_canonique_echoue_fermee_quand_obligations_manquent(client_finance):
    client = _connecter(client_finance)
    retour = client.post("/api/finance/decision", json=_commande(), headers={"x-csrf-token": _csrf(client)})
    assert retour.status_code == 200
    corps = retour.json()["resultat"]
    assert corps["accepte"] is False
    assert "REJ-CAPITAL-CASH-LIBRE-NON-CALCULABLE" in corps["verdict"]["code"]
    assert any(item.get("composante") == "paies" for item in corps["verdict"].get("manque", []))
    page = client.post(
        "/finance/decision",
        data={
            "csrf": _csrf(client),
            "mutation_id": "decision-camion-form-fictif",
            "actif": "Camion",
            "prix": "95000.00",
            "source_prix": "Offre fictive",
            "prix_valide_jusqua": (date.today() + timedelta(days=15)).isoformat(),
            "offre_financement_source": "Offre F fictive",
            "offre_financement_mise_de_fonds": "5000.00",
            "offre_financement_paiement_mensuel": "1600.00",
            "offre_financement_mois": "60",
            "offre_location_source": "Offre L fictive",
            "offre_location_mise_de_fonds": "3000.00",
            "offre_location_paiement_mensuel": "1800.00",
            "offre_location_mois": "48",
        },
    )
    assert page.status_code == 200 and "Décision non calculable" in page.text


def test_finance_decision_compare_scenarios_depuis_meme_registre_m5(client_finance, monkeypatch):
    aujourd_hui = _horloge_serveur_utc(monkeypatch).date()
    monkeypatch.setattr(
        m5_outils,
        "_configuration_manifeste",
        lambda: {
            "fiscal": {
                "frequence_tps_tvq": "trimestrielle",
                "mois_fin_exercice": 12,
                "taxes_remises_jusqu_au": "2026-06-30",
            },
            "obligations_declarees": {
                cle: {
                    "montant": "0.00",
                    "source": f"Déclaration fictive vérifiable {cle}",
                    "au": aujourd_hui.isoformat(),
                }
                for cle in ("paies", "das", "dettes")
            },
        },
    )
    mouvement = m5_outils.enregistrer_mouvement(
        "200000.00",
        "ENCAISSEMENT",
        f"{aujourd_hui.isoformat()}T12:00:00+00:00",
        "STANDARD",
        "Relevé bancaire fictif vérifié",
    )
    assert mouvement["accepte"] is True
    reserve = m5_outils.enregistrer_mouvement(
        "20000.00", "PROVISION", f"{aujourd_hui.isoformat()}T12:05:00+00:00", "STANDARD", "Réserve fictive déclarée"
    )
    assert reserve["accepte"] is True
    client = _connecter(client_finance)
    commande = _commande(mutation_id="decision-camion-95-complete-fictif",
                         prix_valide_jusqua=(aujourd_hui + timedelta(days=15)).isoformat())
    retour = client.post("/api/finance/decision", json=commande, headers={"x-csrf-token": _csrf(client)})
    assert retour.status_code == 200, retour.text
    corps = retour.json()["resultat"]
    assert corps.get("accepte") is True, retour.json()
    rapport = corps["resultat"]
    assert rapport["date_reference"] == aujourd_hui.isoformat()
    assert set(rapport["scenarios"]) == {"achat_comptant", "financement", "location"}
    assert rapport["scenarios"]["achat_comptant"]["cash_libre_apres"] == "85000.00"
    assert rapport["action_proposee"] == "DEMANDER_APPROBATION_HUMAINE"
    assert rapport["contexte_financier"]["provenance_des_offres"]["statut"] == "REFERENCE_MANUELLE_NON_VERIFIEE"
    assert "analyse préparatoire" in rapport["mention"].lower()
    form = {
        "csrf": _csrf(client),
        "mutation_id": "decision-camion-html-fictif",
        "actif": "Camion de service",
        "prix": "95000.00",
        "source_prix": "Offre C-95 fictive",
        "prix_valide_jusqua": (aujourd_hui + timedelta(days=15)).isoformat(),
        "offre_financement_source": "Offre F-95 fictive",
        "offre_financement_mise_de_fonds": "5000.00",
        "offre_financement_paiement_mensuel": "1600.00",
        "offre_financement_mois": "60",
        "offre_location_source": "Offre L-95 fictive",
        "offre_location_mise_de_fonds": "3000.00",
        "offre_location_paiement_mensuel": "1800.00",
        "offre_location_mois": "48",
    }
    html_decision = client.post("/finance/decision", data=form)
    assert html_decision.status_code == 200
    assert all(nom in html_decision.text for nom in ("Comptant", "Financement", "Location"))
    assert "REFERENCE_MANUELLE_NON_VERIFIEE" in html_decision.text
    assert "Aucune commande, signature, déclaration ou paiement" in html_decision.text
    page = client.get("/finance")
    assert "Cash libre réel" in page.text and "180000.00" in page.text
