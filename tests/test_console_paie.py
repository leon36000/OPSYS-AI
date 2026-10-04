"""Parcours de la console owner vers le calcul préparatoire M5/M4 (données synthétiques)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
for chemin in (ROOT / "departments/m04-field-ops/src", ROOT / "departments/m05-financecore/src"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from opsys import identite, stockage  # noqa: E402
from opsys.console import application  # noqa: E402
from opsys.console.securite import Configuration  # noqa: E402
from test_pont_heures_paie import _amorcer_donnees_reelles  # noqa: E402

SECRET = "secret-console-paie-test-" + "x" * 32
PREFIXE = "/opsys"
OWNER = "owner-paie-fictif"
EMPLOYEE = "employe-paie-fictif"
PASSWORD = "owner-paie-fictif-password"


@pytest.fixture
def client_paie(session):
    import m5_financecore.outils as m5_outils

    m5_outils.utiliser_stockage_durable()
    deps, owner, employee = _amorcer_donnees_reelles(session)
    assert (owner, employee) == (OWNER, EMPLOYEE)
    with session() as cnx:
        personne_owner = identite.personne_active(cnx, owner)
        assert personne_owner is not None and {"nathan_owner", "admin"} <= personne_owner.roles
        identite.creer_personne(cnx, "admin-paie-fictif", "Admin fictif", "admin-paie-password", ["admin"])
        identite.creer_personne(cnx, "manager-paie-fictif", "Manager fictif", "manager-paie-password", ["manager"])
    app = application.creer_application(Configuration(SECRET, cookie_securise=False), deps, session)
    with TestClient(app, base_url=f"http://testserver{PREFIXE}") as client:
        yield client


def _connecter(client: TestClient, username: str = OWNER, password: str = PASSWORD) -> TestClient:
    retour = client.post("/connexion", data={"identifiant": username, "mot_de_passe": password}, follow_redirects=False)
    assert retour.status_code == 303
    return client


def _csrf(client: TestClient) -> str:
    return client.get("/api/session").json()["csrf"]


def _arguments(**overrides):
    args = {
        "employee_person_id": EMPLOYEE,
        "debut": "2026-09-14",
        "fin": "2026-09-14",
        "fuseau": "America/Montreal",
        "politique_arrondi": "centime_demi_superieur",
        "hypothese_arrondi": "Hypothèse fictive, non vérifiée pour ce test.",
        "sources_attendues": None,
    }
    args.update(overrides)
    return args


def _tailles_registres_metier():
    return {
        ("m04-field-ops", "principal"): len(stockage.maillons("m04-field-ops", "principal")),
        ("m05-financecore", "principal"): len(stockage.maillons("m05-financecore", "principal")),
        ("m05-financecore", "contrats_salaries_horaires"): len(
            stockage.maillons("m05-financecore", "contrats_salaries_horaires")
        ),
    }


def test_page_et_formulaire_affichent_un_brouillon_reel_sans_creer_de_paie(client_paie):
    client = _connecter(client_paie)
    page_vide = client.get("/finance/paie")
    assert page_vide.status_code == 200
    assert "Aucun montant calculé" not in page_vide.text
    assert 'name="politique_arrondi" required' in page_vide.text
    assert 'value="" disabled selected' in page_vide.text
    assert "31.25" not in page_vide.text
    assert "no-store" in page_vide.headers["cache-control"]

    avant = _tailles_registres_metier()
    retour = client.post(
        "/finance/paie",
        data={
            **_arguments(hypothese_arrondi='Hypothèse <script>alert("x")</script>'),
            "csrf": _csrf(client),
            "action": "lire_courant",
            "sources_attendues": "",
        },
    )
    assert retour.status_code == 200, retour.text
    assert _tailles_registres_metier() == avant
    assert "Brut régulier arrondi : <strong>62.50 CAD</strong>" in retour.text
    assert "Fraction exacte avant arrondi : 375000 centimes / 60" in retour.text
    assert "minutes régulières : 120" in retour.text
    assert "validation humaine requise" in retour.text
    assert "Retenues, cotisations, DAS, net et paiement ne sont pas calculés" in retour.text
    assert "Recalculer ce snapshot" in retour.text
    assert "Lire les sources courantes" in retour.text
    assert "Préparer le dossier WebRAS" in retour.text
    assert 'action="/opsys/finance/paie/webras"' in retour.text
    assert 'value="" disabled selected>Choisir une fréquence' in retour.text
    assert retour.text.count('id="employee_person_id"') == 1
    assert retour.text.count('name="employee_person_id"') == 3
    assert retour.text.count("Lire les sources courantes") == 1
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in retour.text
    assert '<script>alert("x")</script>' not in retour.text
    assert "31.25" not in retour.text


def test_api_privee_exige_owner_csrf_et_snapshot_epingle(client_paie):
    client = _connecter(client_paie)
    args = _arguments()
    assert client.post("/api/finance/paie/brut", json=args).status_code == 403
    headers = {"x-csrf-token": _csrf(client)}
    assert (
        client.post("/api/finance/paie/brut", json={**args, "role": "nathan_owner"}, headers=headers).status_code == 400
    )

    avant_api = _tailles_registres_metier()
    bon = client.post("/api/finance/paie/brut", json=args, headers=headers)
    assert bon.status_code == 200
    assert _tailles_registres_metier() == avant_api
    avant_refus = _tailles_registres_metier()
    body = bon.json()
    resultat = body.get("resultat", {})
    assert resultat.get("accepte") is True, body
    sources = resultat["resultat"]["sources"]
    snapshot = {
        "heures_m4": {cle: sources["heures_m4"][cle] for cle in ("ligne_id", "revision", "empreinte_sources")},
        "contrat_m5": {cle: sources["contrat_m5"][cle] for cle in ("contrat_id", "revision", "ligne_id")},
    }
    assert resultat["resultat"]["brut_brouillon"] == "62.50"
    assert resultat["resultat"]["brut_exact_fraction"] == {
        "numerateur_centimes": 375000,
        "denominateur": 60,
    }

    stale = {
        **args,
        "sources_attendues": {
            **snapshot,
            "heures_m4": {**snapshot["heures_m4"], "revision": snapshot["heures_m4"]["revision"] + 1},
        },
    }
    refuse = client.post("/api/finance/paie/brut", json=stale, headers=headers)
    assert refuse.status_code == 200, refuse.text
    assert _tailles_registres_metier() == avant_refus
    assert refuse.json()["resultat"]["verdict"]["code"] == "REJ-SALAIRE-REVISION-PERIMEE"
    form_refus = client.post(
        "/finance/paie",
        data={
            **stale,
            "csrf": headers["x-csrf-token"],
            "action": "recalculer_epingle",
            "sources_attendues": json.dumps(stale["sources_attendues"]),
        },
    )
    assert form_refus.status_code == 200
    assert _tailles_registres_metier() == avant_refus
    assert "REJ-SALAIRE-REVISION-PERIMEE" in form_refus.text
    assert "Brut régulier arrondi" not in form_refus.text


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin-paie-fictif", "admin-paie-password"),
        ("manager-paie-fictif", "manager-paie-password"),
        (EMPLOYEE, "employe-paie-fictif-password"),
    ],
)
def test_page_et_api_refusent_admin_manager_et_salarie(client_paie, username, password):
    client = _connecter(client_paie, username, password)
    assert client.get("/finance/paie").status_code == 403
    response = client.post(
        "/api/finance/paie/brut",
        json=_arguments(),
        headers={"x-csrf-token": _csrf(client)},
    )
    assert response.status_code == 403
    assert "62.50" not in response.text


def test_role_owner_revoque_apres_connexion_refuse_avant_calcul(client_paie, session):
    client = _connecter(client_paie)
    with session() as cnx:
        identite.retirer_role(cnx, OWNER, "nathan_owner")
    response = client.post(
        "/api/finance/paie/brut",
        json=_arguments(),
        headers={"x-csrf-token": _csrf(client)},
    )
    assert response.status_code == 403
    assert "62.50" not in response.text


def test_formulaire_refuse_periode_inversee_et_action_epinglee_sans_snapshot(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    base = {**_arguments(), "csrf": csrf, "sources_attendues": ""}
    invalid = client.post("/finance/paie", data={**base, "debut": "2026-09-15", "action": "lire_courant"})
    assert invalid.status_code == 400
    pinned = client.post("/finance/paie", data={**base, "action": "recalculer_epingle"})
    assert pinned.status_code == 400


def _snapshot_depuis_brut(reponse):
    brut = reponse["resultat"]["resultat"]
    sources = brut["sources"]
    return {
        "heures_m4": {cle: sources["heures_m4"][cle] for cle in ("ligne_id", "revision", "empreinte_sources")},
        "contrat_m5": {cle: sources["contrat_m5"][cle] for cle in ("contrat_id", "revision", "ligne_id")},
    }


def _arguments_dossier_webras(sources_attendues, *, assiette=True):
    return {
        **_arguments(sources_attendues=sources_attendues),
        "date_paie": "2026-09-18",
        "periodes_annuelles": 26,
        "revenu_imposable_cad": "62.50" if assiette else None,
        "reference_revenu_imposable": "Base fictive de période ASS-001" if assiette else None,
    }


def test_export_webras_est_un_json_prive_source_sans_montants_fiscaux_ni_ecriture(client_paie):
    client = _connecter(client_paie)
    headers = {"x-csrf-token": _csrf(client)}
    brut = client.post("/api/finance/paie/brut", json=_arguments(), headers=headers)
    assert brut.status_code == 200, brut.text
    assert brut.json()["resultat"]["accepte"] is True
    sources = _snapshot_depuis_brut(brut.json())
    avant = _tailles_registres_metier()

    export = client.post(
        "/api/finance/paie/webras",
        json=_arguments_dossier_webras(sources),
        headers=headers,
    )

    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("application/json")
    assert "no-store" in export.headers["cache-control"]
    assert "attachment;" in export.headers["content-disposition"]
    dossier = export.json()
    assert dossier["schema"] == "opsys.dossier-webras-preparatoire/v1"
    assert dossier["known_info"]["employee_person_id"] == EMPLOYEE
    assert dossier["known_info"]["revenu_imposable_declare"]["montant_cad"] == "62.50"
    assert dossier["known_info"]["revenu_imposable_declare"]["rapprochee_au_brut_m5"] is False
    assert dossier["known_info"]["brut_regulier_m5"]["montant_cad"] == "62.50"
    assert dossier["source_catalogue"]["statut"] == "PARTIEL"
    references = dossier["source_catalogue"]["references_declarees"]
    assert references and all(reference["statut"] == "NON_QUALIFIEE" for reference in references)
    assert all(len(reference["sha256"]) == 64 for reference in references)
    assert dossier["montants_fiscaux"] == {
        "impot_federal": "UNKNOWN",
        "impot_quebec": "UNKNOWN",
        "rrq_employe": "UNKNOWN",
        "rqap_employe": "UNKNOWN",
        "ae_employe": "UNKNOWN",
        "retenues_totales": "UNKNOWN",
        "net": "UNKNOWN",
        "rrq_employeur": "UNKNOWN",
        "rqap_employeur": "UNKNOWN",
        "fss": "UNKNOWN",
        "cnesst": "UNKNOWN",
        "das": "UNKNOWN",
    }
    assert dossier["actions_officielles_bloquees"] is True
    assert dossier["requires_human_calculation"] is True
    assert any(m.get("id") == "TP1015_3_CODE" for m in dossier["champs_fiscaux_manquants"])
    assert any(link["id"] == "webras" for link in dossier["liens_officiels"])
    assert _tailles_registres_metier() == avant

    sans_assiette = client.post(
        "/api/finance/paie/webras",
        json=_arguments_dossier_webras(sources, assiette=False),
        headers=headers,
    )
    assert sans_assiette.status_code == 200, sans_assiette.text
    assert sans_assiette.json()["known_info"]["revenu_imposable_declare"]["montant_cad"] == "UNKNOWN"
    assert sans_assiette.json()["known_info"]["brut_regulier_m5"]["montant_cad"] == "62.50"
    assert _tailles_registres_metier() == avant


@pytest.mark.parametrize(
    ("username", "password"),
    [("admin-paie-fictif", "admin-paie-password"), (EMPLOYEE, "employe-paie-fictif-password")],
)
def test_export_webras_refuse_admin_et_salarie_avant_donner_un_dossier(client_paie, username, password):
    client = _connecter(client_paie, username, password)
    response = client.post(
        "/api/finance/paie/webras",
        json=_arguments_dossier_webras(None),
        headers={"x-csrf-token": _csrf(client)},
    )
    assert response.status_code == 403
    assert "assiette_brute" not in response.text
    assert "brut_regulier_m5" not in response.text


def test_export_webras_refuse_sources_null_et_champs_incomplets(client_paie):
    client = _connecter(client_paie)
    headers = {"x-csrf-token": _csrf(client)}
    body = _arguments_dossier_webras(None)
    refuse_snapshot = client.post("/api/finance/paie/webras", json=body, headers=headers)
    assert refuse_snapshot.status_code == 409
    assert refuse_snapshot.json()["resultat"]["verdict"]["code"] == "REJ-PAIE-SNAPSHOT-REQUIS"
    brut = client.post("/api/finance/paie/brut", json=_arguments(), headers=headers)
    sources = _snapshot_depuis_brut(brut.json())
    incomplet = client.post(
        "/api/finance/paie/webras",
        json={key: value for key, value in _arguments_dossier_webras(sources).items() if key != "date_paie"},
        headers=headers,
    )
    assert incomplet.status_code == 400
    assert "champs" in incomplet.text.lower()
    stale = json.loads(json.dumps(sources))
    stale["heures_m4"]["revision"] += 1
    refuse_perime = client.post(
        "/api/finance/paie/webras",
        json=_arguments_dossier_webras(stale),
        headers=headers,
    )
    assert refuse_perime.status_code == 409
    assert refuse_perime.json()["resultat"]["verdict"]["code"] == "REJ-SALAIRE-REVISION-PERIMEE"


def test_formulaire_webras_genere_le_json_epingle_sans_ecriture(client_paie):
    client = _connecter(client_paie)
    headers = {"x-csrf-token": _csrf(client)}
    brut = client.post("/api/finance/paie/brut", json=_arguments(), headers=headers)
    sources = _snapshot_depuis_brut(brut.json())
    avant = _tailles_registres_metier()
    export = client.post(
        "/finance/paie/webras",
        data={
            **_arguments(sources_attendues=json.dumps(sources)),
            "date_paie": "2026-09-18",
            "periodes_annuelles": "26",
            "revenu_imposable_cad": "",
            "reference_revenu_imposable": "",
            "csrf": headers["x-csrf-token"],
        },
    )
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("application/json")
    assert "attachment;" in export.headers["content-disposition"]
    assert "no-store" in export.headers["cache-control"]
    dossier = export.json()
    assert dossier["known_info"]["revenu_imposable_declare"]["montant_cad"] == "UNKNOWN"
    assert dossier["known_info"]["brut_regulier_m5"]["montant_cad"] == "62.50"
    assert _tailles_registres_metier() == avant


@pytest.mark.parametrize("frequence", ["9" * 3000, "٢٦"])
def test_formulaire_webras_refuse_les_frequences_malformees_avant_lecture_financiere(
    client_paie, monkeypatch, frequence
):
    import m5_financecore.outils as m5_outils

    client = _connecter(client_paie)
    headers = {"x-csrf-token": _csrf(client)}
    brut = client.post("/api/finance/paie/brut", json=_arguments(), headers=headers)
    sources = _snapshot_depuis_brut(brut.json())

    def lecture_interdite():
        pytest.fail("la fréquence invalide ne doit pas atteindre la lecture du registre salarial")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", lecture_interdite)
    response = client.post(
        "/finance/paie/webras",
        data={
            **_arguments(sources_attendues=json.dumps(sources)),
            "date_paie": "2026-09-18",
            "periodes_annuelles": frequence,
            "revenu_imposable_cad": "",
            "reference_revenu_imposable": "",
            "csrf": headers["x-csrf-token"],
        },
    )
    assert response.status_code == 400
