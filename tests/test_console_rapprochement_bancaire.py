"""Parcours console banque→AR isolé, avec registres et identités synthétiques."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from m5_financecore import encodage
from m5_financecore import registre as registre_m5
from sqlalchemy import MetaData, Table, func, inspect, select

from opsys import identite, stockage
from opsys.console import application, banque_metier
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL

SECRET = "secret-console-banque-test-fictif-" + "x" * 32
OWNER = "owner-banque-fictif"
PASSWORD = "owner-banque-fictif-password"
PREFIX = "/opsys"
CSV = "Date,Montant,Facture,Description\n2026-09-30,100.00,FAC-AR-001,CLIENT-SECRET-ALPHA\n"


@pytest.fixture
def client_banque(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys"))
    stockage.migrer()
    racine_m5 = tmp_path / "m05-financecore"
    racine_m5.mkdir()
    (racine_m5 / "department.yaml").write_text(
        "configuration:\n  banque_csv:\n    comptes_internes: [compte-fictif-01]\n", encoding="utf-8"
    )
    deps = dict(charger_departements())
    deps["m05-financecore"] = replace(deps["m05-financecore"], racine=racine_m5)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", PASSWORD, ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "admin-seul-fictif", "Admin fictif", PASSWORD, ["admin"])
        identite.creer_personne(cnx, "employe-banque-fictif", "Employé fictif", PASSWORD, ["employee"])
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False), deps, stockage.transaction
    )
    with TestClient(app, base_url=f"http://testserver{PREFIX}") as client:
        yield client
    stockage.liberer()


def _connecter(client: TestClient, utilisateur: str = OWNER) -> str:
    retour = client.post(
        "/connexion",
        data={"identifiant": utilisateur, "mot_de_passe": PASSWORD},
        follow_redirects=False,
    )
    assert retour.status_code == 303, retour.text
    return client.get("/api/session").json()["csrf"]


def _body(mutation_id: str = "import-fictif-01", **overrides):
    return {
        "mutation_id": mutation_id,
        "compte_interne_id": "compte-fictif-01",
        "devise": "CAD",
        "mapping_colonnes": {"date": "Date", "montant": "Montant", "reference_facture": "Facture"},
        "csv_utf8": CSV,
        **overrides,
    }


def _facture_envoyee():
    with stockage.transaction():
        registre = registre_m5.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
        for facture_id, montant in (("FAC-AR-001", "100.00"), ("FAC-AR-002", "200.00")):
            registre.ajouter(
                {
                    "type_entree": "facture_creee",
                    "facture_id": facture_id,
                    "statut": "BROUILLON",
                    "montant_apres_taxes": Decimal(montant),
                    "horodatage": "2026-09-29T12:00:00+00:00",
                }
            )
            registre.ajouter(
                {
                    "type_entree": "transition_facture",
                    "facture_id": facture_id,
                    "statut": "ENVOYEE",
                    "date_envoi": "2026-09-29T12:00:00+00:00",
                    "horodatage": "2026-09-29T12:00:00+00:00",
                }
            )


def test_api_csrf_replay_conflit_et_proposition_sans_effet_financier(client_banque):
    csrf = _connecter(client_banque)
    page = client_banque.get("/finance/rapprochement-bancaire")
    assert page.status_code == 200
    assert re.search(r'name="mutation_id" value="[0-9a-f-]{36}"', page.text)
    assert 'name="mutation_id" required' not in page.text
    assert client_banque.post("/api/finance/rapprochement-bancaire/proposer", json=_body()).status_code == 403
    _facture_envoyee()
    headers = {"x-csrf-token": csrf}
    injecte = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json={**_body(), "acteur": OWNER, "factures": ["FAC-AR-001"], "solde": "0.00"},
        headers=headers,
    )
    assert injecte.status_code == 400
    avant_principal = list(stockage.maillons("m05-financecore", "principal"))
    avant_factures = list(stockage.maillons("m05-financecore", "factures"))

    first = client_banque.post("/api/finance/rapprochement-bancaire/proposer", json=_body(), headers=headers)
    assert first.status_code == 200, first.text
    projection = first.json()["resultat"]["resultat"]
    assert projection["propositions"] == [
        {"ligne": 2, "facture_id": "FAC-AR-001", "montant": "100.00", "statut": "PROPOSE"}
    ]
    assert "CLIENT-SECRET-ALPHA" not in first.text
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 1
    assert "CLIENT-SECRET-ALPHA" not in repr(
        list(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes"))
    )
    assert registre_m5.Registre(
        maillons=stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")
    ).valider_chaine()[0] is True

    replay = client_banque.post("/api/finance/rapprochement-bancaire/proposer", json=_body(), headers=headers)
    assert replay.status_code == 200 and replay.json()["rejoue"] is True
    other_key = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body("import-fictif-02"), headers=headers
    )
    assert other_key.status_code == 200 and other_key.json()["rejoue"] is True
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 1

    conflit = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json=_body(csv_utf8=CSV.replace("100.00", "99.00")),
        headers=headers,
    )
    assert conflit.status_code == 409
    assert list(stockage.maillons("m05-financecore", "principal")) == avant_principal
    assert list(stockage.maillons("m05-financecore", "factures")) == avant_factures


def test_retrait_role_pendant_await_body_refuse_avant_factures_ou_idempotence(
    client_banque, monkeypatch
):
    csrf = _connecter(client_banque)
    original_previsualiser = banque_metier.previsualiser
    calls = {"factures": 0, "reclamer": 0}
    original_maillons = stockage.maillons
    original_reclamer = __import__("opsys.idempotence", fromlist=["reclamer"]).reclamer

    def wrapped_maillons(departement, registre="principal"):
        if departement == "m05-financecore":
            calls["factures"] += 1
        return original_maillons(departement, registre)

    def retirer_role_apres_corps(cnx_factory, deps, session, demande):
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, OWNER, "nathan_owner")
            identite.retirer_role(cnx, OWNER, "admin")
        return original_previsualiser(cnx_factory, deps, session, demande)

    def wrapped_reclamer(*args, **kwargs):
        calls["reclamer"] += 1
        return original_reclamer(*args, **kwargs)

    monkeypatch.setattr(banque_metier, "previsualiser", retirer_role_apres_corps)
    monkeypatch.setattr(stockage, "maillons", wrapped_maillons)
    monkeypatch.setattr("opsys.idempotence.reclamer", wrapped_reclamer)
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 403
    assert calls == {"factures": 0, "reclamer": 0}


def test_partiel_et_frais_sont_classes_hors_proposition(client_banque):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    csv = "Date,Montant,Facture\n2026-09-30,60.00,FAC-AR-001\n2026-09-30,210.00,FAC-AR-002\n"
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json=_body(csv_utf8=csv),
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 200, response.text
    resultat = response.json()["resultat"]["resultat"]
    assert [ligne["statut_rapprochement"] for ligne in resultat["lignes"]] == [
        "PAIEMENT_PARTIEL_NON_SUPPORTE",
        "FRAIS_OU_ECART_NON_SUPPORTE",
    ]
    assert resultat["propositions"] == []


def test_chaine_facture_invalide_refuse_avant_piste(client_banque):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    # Corruption du journal M5 existant : le lecteur refuse avant de produire une proposition.
    with stockage.transaction():
        stockage.maillons("m05-financecore", "factures").append(
            {"type_entree": "transition_facture", "ligne_id": "empreinte-fausse"}
        )
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 409
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 0


def test_page_echappe_compte_configure_et_limite_l_effet_a_la_piste(client_banque):
    csrf = _connecter(client_banque)
    page = client_banque.get("/finance")
    assert "rapprochement bancaire" in page.text.lower()
    before = len(stockage.maillons("m05-financecore", "principal"))
    response = client_banque.post(
        "/finance/rapprochement-bancaire/proposer",
        data={
            "csrf": csrf,
            "mutation_id": "import-form-fictif",
            "compte_interne_id": "compte-fictif-01",
            "devise": "CAD",
            "mapping_date": "Date",
            "mapping_montant": "Montant",
            "mapping_reference_facture": "Facture",
            "csv_utf8": "Date,Montant,Facture\n2026-09-30,1.00,INCONNUE\n",
        },
    )
    assert response.status_code == 200, response.text
    assert "Prévisualisation enregistrée" in response.text
    assert "Lot :" in response.text and "lot_id" not in response.text
    assert "INCONNUE" in response.text and "REFERENCE_FACTURE_INCONNUE" in response.text
    assert "Propositions de rapprochement : 0" in response.text
    assert len(stockage.maillons("m05-financecore", "principal")) == before
    assert "Cache-Control" in response.headers and "no-store" in response.headers["Cache-Control"]


def test_csv_malforme_est_affiche_comme_refus_ui(client_banque):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    body = _body(csv_utf8="Date,Montant,Facture\n2026-02-30,100.00,FAC-AR-001\n")
    api = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=body, headers={"x-csrf-token": csrf}
    )
    assert api.status_code == 409
    assert api.json()["resultat"]["accepte"] is False
    form = client_banque.post(
        "/finance/rapprochement-bancaire/proposer",
        data={
            "csrf": csrf, "mutation_id": body["mutation_id"], "compte_interne_id": body["compte_interne_id"],
            "devise": "CAD", "mapping_date": "Date", "mapping_montant": "Montant",
            "mapping_reference_facture": "Facture", "csv_utf8": body["csv_utf8"],
        },
    )
    assert form.status_code == 409
    assert "refusée" in form.text.lower() and "REJ-M53-CSV-DATE" in form.text


def test_admin_seul_autorise_et_employe_non_auth_refuses_avant_lecture(client_banque, monkeypatch):
    _facture_envoyee()
    original = stockage.maillons
    reads = {"factures": 0}

    def compter(departement, registre="principal"):
        if departement == "m05-financecore" and registre == "factures":
            reads["factures"] += 1
        return original(departement, registre)

    monkeypatch.setattr(stockage, "maillons", compter)
    admin_csrf = _connecter(client_banque, "admin-seul-fictif")
    accepted = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": admin_csrf}
    )
    assert accepted.status_code == 200 and accepted.json()["resultat"]["accepte"] is True
    reads["factures"] = 0

    employee_csrf = _connecter(client_banque, "employe-banque-fictif")
    assert client_banque.get("/finance/rapprochement-bancaire").status_code == 403
    assert reads["factures"] == 0
    denied = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json=_body("import-employe-fictif"), headers={"x-csrf-token": employee_csrf},
    )
    assert denied.status_code == 403
    assert reads["factures"] == 0

    client_banque.cookies.clear()
    anonymous = client_banque.post("/api/finance/rapprochement-bancaire/proposer", json=_body())
    assert anonymous.status_code in {401, 403}
    assert reads["factures"] == 0


def test_allowlist_compte_absente_ou_inconnue_refuse_avant_lecture(client_banque, monkeypatch):
    csrf = _connecter(client_banque)
    original = stockage.maillons
    reads = {"m5": 0}

    def compter(departement, registre="principal"):
        if departement == "m05-financecore":
            reads["m5"] += 1
        return original(departement, registre)

    monkeypatch.setattr(stockage, "maillons", compter)
    monkeypatch.setattr(banque_metier, "comptes_configures", lambda deps: ())
    missing = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert missing.status_code == 409
    assert missing.json()["resultat"]["verdict"]["code"] == "COMPTES_NON_CONFIGURES"
    assert reads["m5"] == 0

    monkeypatch.setattr(banque_metier, "comptes_configures", lambda deps: ("compte-fictif-01",))
    unknown = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json=_body(compte_interne_id="compte-inconnu-fictif"), headers={"x-csrf-token": csrf},
    )
    assert unknown.status_code == 409
    assert unknown.json()["resultat"]["verdict"]["code"] == "COMPTE_NON_CONFIGURE"
    assert reads["m5"] == 0


def test_corps_global_depasse_64k_refuse(client_banque):
    csrf = _connecter(client_banque)
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json=_body(csv_utf8="x" * (70 * 1024)), headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 413


def test_retrait_role_pendant_calcul_refuse_sans_ecriture(client_banque, monkeypatch):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    engine = __import__("m5_financecore.reconciliation_bancaire_csv", fromlist=["previsualiser_releve_csv"])
    original_engine = engine.previsualiser_releve_csv

    def calculer(*args, **kwargs):
        result = original_engine(*args, **kwargs)
        cnx = stockage.connexion_courante()
        assert cnx is not None
        identite.retirer_role(cnx, OWNER, "nathan_owner")
        identite.retirer_role(cnx, OWNER, "admin")
        return result

    monkeypatch.setattr(engine, "previsualiser_releve_csv", calculer)
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json=_body(), headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 403
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 0
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, OWNER)
    assert personne is not None and {"nathan_owner", "admin"}.issubset(personne.roles)


def test_tete_factures_modifiee_pendant_calcul_est_refusee(client_banque, monkeypatch):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    engine = __import__("m5_financecore.reconciliation_bancaire_csv", fromlist=["previsualiser_releve_csv"])
    original_engine = engine.previsualiser_releve_csv

    def calculer(*args, **kwargs):
        resultat = original_engine(*args, **kwargs)
        with stockage.transaction():
            registre = registre_m5.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
            registre.ajouter({"type_entree": "facture_creee", "facture_id": "FAC-AR-003",
                              "statut": "BROUILLON", "montant_apres_taxes": Decimal("300.00"),
                              "horodatage": "2026-09-29T12:00:00+00:00"})
        return resultat

    monkeypatch.setattr(engine, "previsualiser_releve_csv", calculer)
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 409
    assert response.json()["resultat"]["verdict"]["code"] == "SNAPSHOT_FACTURES_PERIME"
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 0


def test_chaine_propositions_structurellement_malformee_refuse(client_banque):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    with stockage.transaction():
        stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes").append({"nom": "maillon-incomplet"})
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 409
    assert response.json()["resultat"]["verdict"]["code"] == "CHAINE_PROPOSITIONS_INVALIDE"
    assert "maillon-incomplet" not in response.text


def test_html_affiche_lot_source_statut_et_echappe_contenu_non_mappe(client_banque):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    csv = "Date,Montant,Facture,Description\n2026-09-30,100.00,FAC-AR-001,<img src=x onerror=alert(1)>\n"
    response = client_banque.post(
        "/finance/rapprochement-bancaire/proposer",
        data={
            "csrf": csrf, "mutation_id": "import-html-fictif", "compte_interne_id": "compte-fictif-01",
            "devise": "CAD", "mapping_date": "Date", "mapping_montant": "Montant",
            "mapping_reference_facture": "Facture", "csv_utf8": csv,
        },
    )
    assert response.status_code == 200
    assert "Lot :" in response.text and "Source CSV SHA-256" in response.text
    assert (
        "FAC-AR-001" in response.text
        and "100.00" in response.text
        and "PROPOSITION_EXACTE" in response.text
        and "Montant dû" in response.text
        and "Snapshot factures version" in response.text
    )
    assert "<img" not in response.text and "onerror" not in response.text
    assert _cellules_banque(response.text)[0][-1] == "FAC-AR-001"
    assert len(re.findall(r"[0-9a-f]{64}", response.text)) >= 2
    replay = client_banque.post(
        "/finance/rapprochement-bancaire/proposer",
        data={
            "csrf": csrf, "mutation_id": "import-html-fictif", "compte_interne_id": "compte-fictif-01",
            "devise": "CAD", "mapping_date": "Date", "mapping_montant": "Montant",
            "mapping_reference_facture": "Facture", "csv_utf8": csv,
        },
    )
    assert replay.status_code == 200 and "Résultat archivé" in replay.text


def test_chaine_factures_structurellement_malformee_est_refusee(client_banque):
    csrf = _connecter(client_banque)
    with stockage.transaction():
        stockage.maillons("m05-financecore", "factures").append({"champ-inconnu": "donnée-fictive"})
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 409
    assert response.json()["resultat"]["verdict"]["code"] == "CHAINE_FACTURES_INVALIDE"
    assert "donnée-fictive" not in response.text


def test_vue_ar_non_mapping_refuse_sans_projection_partielle(client_banque, monkeypatch):
    csrf = _connecter(client_banque)
    called = {"engine": 0}
    from m5_financecore import facturation, reconciliation_bancaire_csv

    monkeypatch.setattr(
        facturation, "comptes_a_recevoir", lambda registre: ({"factures": [None], "total_complet": True}, None)
    )
    original = reconciliation_bancaire_csv.previsualiser_releve_csv

    def engine(*args, **kwargs):
        called["engine"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(reconciliation_bancaire_csv, "previsualiser_releve_csv", engine)
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 409
    assert response.json()["resultat"]["verdict"]["code"] == "VUE_FACTURES_INDISPONIBLE"
    assert called["engine"] == 0
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 0


def test_rang_concurrent_refuse_et_annule_registre_idempotence_journal(client_banque, monkeypatch):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    original_append = stockage.MaillonsDurables.append
    injected = {"value": False}

    def intercaler(self, maillon, *, rang_attendu=None):
        if (
            self.departement == "m05-financecore"
            and self.registre == "rapprochements_bancaires_proposes"
            and not injected["value"]
        ):
            injected["value"] = True
            corps = {"type_entree": "interleaving-fictif"}
            original_append(
                self, {**corps, "ligne_id": encodage.empreinte(corps, None), "precedent_ligne_id": None}
            )
        return original_append(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(stockage.MaillonsDurables, "append", intercaler)
    failed = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert failed.status_code == 409
    assert failed.json()["resultat"]["verdict"]["code"] == "CONFLIT_CONCURRENT"
    assert injected["value"] is True
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 0
    with stockage.transaction() as cnx:
        journal_count = cnx.execute(
            select(func.count()).select_from(JOURNAL).where(
                JOURNAL.c.action == "console.rapprochement_bancaire.propose"
            )
        ).scalar_one()
    assert journal_count == 0

    retry = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=_body(), headers={"x-csrf-token": csrf}
    )
    assert retry.status_code == 200 and retry.json()["resultat"]["accepte"] is True
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 1


@pytest.mark.parametrize(
    ("champ", "valeur", "statut", "code"),
    [
        ("csv_utf8", "Date,Montant,Facture\n\ud800", 409, "CSV_UTF8_INVALIDE"),
        (
            "mapping_colonnes",
            {"date": "Date", "montant": "Montant", "reference_facture": "\ud800"},
            400,
            None,
        ),
    ],
)
def test_surrogate_json_est_refuse_sans_500_ni_ecriture(client_banque, champ, valeur, statut, code):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    body = _body(**{champ: valeur})
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        content=json.dumps(body, ensure_ascii=True).encode("ascii"),
        headers={"x-csrf-token": csrf, "content-type": "application/json"},
    )
    assert response.status_code == statut
    if code is not None:
        assert response.json()["resultat"]["verdict"]["code"] == code
    else:
        assert response.json()["detail"] == "champs de rapprochement non UTF-8"
    assert "\ud800" not in response.text
    assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 0


def test_append_rang_attendu_rejette_bool_et_rang_invalide(client_banque):
    _connecter(client_banque)
    store = stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")
    with pytest.raises(ValueError):
        store.append({}, rang_attendu=True)
    with pytest.raises(ValueError):
        store.append({}, rang_attendu=-1)
    assert len(store) == 0


def _tables_banque():
    """Recense toutes les tables réelles, en conservant les octets SQL des archives."""
    with stockage.transaction() as cnx:
        meta = MetaData()
        return {
            nom: Counter(tuple(row) for row in cnx.execute(select(Table(nom, meta, autoload_with=cnx))))
            for nom in inspect(cnx).get_table_names()
        }


def _assert_effets_banque(avant, apres, *, proposition: bool, recu: bool):
    assert avant.keys() == apres.keys()
    changements = {nom for nom in avant if avant[nom] != apres[nom]}
    attendus = ({"registres_maillons", "journal"} if proposition else set())
    if recu:
        attendus.add("mutations_appliquees")
    assert changements == attendus
    for nom in changements:
        assert not (avant[nom] - apres[nom]), f"archive modifiée dans {nom}"
        assert sum((apres[nom] - avant[nom]).values()) == 1
    if proposition:
        with stockage.transaction() as cnx:
            meta = MetaData()
            table = Table("registres_maillons", meta, autoload_with=cnx)
            ligne = cnx.execute(select(table).where(
                table.c.departement == "m05-financecore",
                table.c.registre == "rapprochements_bancaires_proposes",
            ).order_by(table.c.rang.desc())).mappings().first()
            assert ligne is not None
            assert tuple(ligne.values()) in (apres["registres_maillons"] - avant["registres_maillons"])
            assert json.loads(ligne["maillon"])["type_entree"] == "rapprochement_bancaire_propose"
            journal = Table("journal", meta, autoload_with=cnx)
            audit = cnx.execute(select(journal).order_by(journal.c.id.desc())).mappings().first()
            assert tuple(audit.values()) in (apres["journal"] - avant["journal"])
            assert audit["action"] == "console.rapprochement_bancaire.propose"


def _form_partiel(csrf, body):
    return {
        "csrf": csrf, "mutation_id": body["mutation_id"],
        "compte_interne_id": body["compte_interne_id"], "devise": body["devise"],
        "mapping_date": "Date", "mapping_montant": "Montant", "mapping_reference_facture": "Facture",
        "csv_utf8": body["csv_utf8"],
    }


def _cellules_banque(html):
    return [
        cellules for ligne in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
        if (cellules := re.findall(r"<td>(.*?)</td>", ligne, re.DOTALL))
    ]


def test_html_non_propose_garde_reference_sans_facture_candidate(client_banque):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    body = _body("hors-proposition-html-fictif", csv_utf8=(
        "Date,Montant,Facture\n2026-09-30,60.00,FAC-AR-001\n2026-09-30,210.00,FAC-AR-002\n"
    ))
    retour = client_banque.post("/finance/rapprochement-bancaire/proposer", data=_form_partiel(csrf, body))
    assert retour.status_code == 200, retour.text
    lignes = _cellules_banque(retour.text)
    assert len(lignes) == 2 and all(len(ligne) == 7 for ligne in lignes)
    assert [ligne[4] for ligne in lignes] == ["FAC-AR-001", "FAC-AR-002"]
    assert [ligne[5] for ligne in lignes] == ["PAIEMENT_PARTIEL_NON_SUPPORTE", "FRAIS_OU_ECART_NON_SUPPORTE"]
    assert [ligne[6] for ligne in lignes] == ["", ""]
    assert "Propositions de rapprochement : 0" in retour.text


def test_partiel_api_formulaire_sans_effet_financier(client_banque):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    body = _body("partiel-api-fictif", csv_utf8=CSV.replace("100.00", "10.00"))
    avant = _tables_banque()
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=body, headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 200, response.text
    projection = response.json()["resultat"]["resultat"]
    assert projection["propositions"] == [
        {"ligne": 2, "facture_id": "FAC-AR-001", "montant": "10.00", "statut": "PROPOSE_PARTIEL"}
    ]
    assert projection["version_rapprochement"] == "m5.3-partiel-unique/v1"
    assert projection["lignes"][0]["montant_du"] == "100.00"
    assert "CLIENT-SECRET-ALPHA" not in response.text
    _assert_effets_banque(avant, _tables_banque(), proposition=True, recu=True)

    avant = _tables_banque()
    form = client_banque.post("/finance/rapprochement-bancaire/proposer", data=_form_partiel(csrf, body))
    assert form.status_code == 200, form.text
    assert "Propositions de rapprochement : 1" in form.text
    assert "Facture candidate" in form.text and "Partielle — à vérifier" in form.text
    assert _cellules_banque(form.text)[0][-1] == "FAC-AR-001"
    assert "Ce candidat ne confirme ni paiement, ni encaissement, ni frais" in form.text
    assert "ne distingue pas un acompte d’un montant net de frais" in form.text
    assert "Résultat archivé" in form.text and "ne vérifie pas l’état actuel" in form.text
    assert "CLIENT-SECRET-ALPHA" not in form.text
    assert "no-store" in form.headers["cache-control"]
    _assert_effets_banque(avant, _tables_banque(), proposition=False, recu=False)


def test_partiel_rejeu_ancien_resultat_sans_proposition_et_nouveau_lot(client_banque, monkeypatch):
    csrf = _connecter(client_banque)
    fixture = json.loads((Path(__file__).parent / "fixtures/m5-partiel-legacy-accepte.json").read_text())
    assert fixture["fictif"] is True
    with stockage.transaction() as cnx:
        for nom, lignes in fixture["native_sql_seed"].items():
            table = "registres_maillons" if nom == "factures_rows" else nom
            for ligne in lignes:
                # Capture SQLite native : conserver ses textes de dates et de maillons,
                # sans réencoder les archives par les processeurs SQLAlchemy DateTime.
                citer = cnx.dialect.identifier_preparer.quote
                colonnes = ",".join(citer(champ) for champ in ligne)
                marqueurs = ",".join("?" for _ in ligne)
                cnx.exec_driver_sql(
                    f"INSERT INTO {citer(table)} ({colonnes}) VALUES ({marqueurs})", tuple(ligne.values())
                )
    body = fixture["request_mapped_only"]
    legacy = fixture["http_first"]["json"]["resultat"]["resultat"]
    avant = _tables_banque()
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=body, headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 200 and response.json()["rejoue"] is True
    assert response.json()["resultat"]["accepte"] is True
    assert response.json()["resultat"]["resultat"] == legacy
    assert legacy["statut"] == "AUCUNE_PROPOSITION" and legacy["propositions"] == []
    historique_html = client_banque.post(
        "/finance/rapprochement-bancaire/proposer", data=_form_partiel(csrf, body)
    )
    assert historique_html.status_code == 200 and "Résultat archivé" in historique_html.text
    assert _cellules_banque(historique_html.text)[0][4:] == ["FAC-AR-001", "PAIEMENT_PARTIEL_NON_SUPPORTE", ""]
    _assert_effets_banque(avant, _tables_banque(), proposition=False, recu=False)

    # Panne réelle après append et audit, avant la finalisation du reçu : l'archive
    # legacy et toutes les tables doivent revenir à leur état initial.
    late = {"observe": False}

    def echouer_apres_audit(cnx, meta, reponse):
        assert reponse["resultat"]["resultat"]["propositions"][0]["statut"] == "PROPOSE_PARTIEL"
        assert len(stockage.maillons("m05-financecore", "rapprochements_bancaires_proposes")) == 2
        assert cnx.execute(select(func.count()).select_from(JOURNAL).where(
            JOURNAL.c.action == "console.rapprochement_bancaire.propose",
        )).scalar_one() == 2
        late["observe"] = True
        raise RuntimeError("panne finale bancaire fictive")

    with monkeypatch.context() as garde:
        garde.setattr("opsys.idempotence.finaliser", echouer_apres_audit)
        with pytest.raises(RuntimeError, match="panne finale bancaire fictive"):
            client_banque.post(
                "/api/finance/rapprochement-bancaire/proposer",
                json={**body, "mutation_id": "partiel-nouvelle-version-fictif"}, headers={"x-csrf-token": csrf},
            )
    assert late["observe"] is True
    _assert_effets_banque(avant, _tables_banque(), proposition=False, recu=False)

    nouveau = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json={**body, "mutation_id": "partiel-nouvelle-version-fictif"}, headers={"x-csrf-token": csrf},
    )
    assert nouveau.status_code == 200, nouveau.text
    projection = nouveau.json()["resultat"]["resultat"]
    assert projection["lot_id"] != legacy["lot_id"]
    assert projection["version_rapprochement"] == "m5.3-partiel-unique/v1"
    assert projection["propositions"][0]["statut"] == "PROPOSE_PARTIEL"
    _assert_effets_banque(avant, _tables_banque(), proposition=True, recu=True)
    avant = _tables_banque()
    autre = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json={**body, "mutation_id": "partiel-autre-cle-fictif"}, headers={"x-csrf-token": csrf},
    )
    assert autre.status_code == 200 and autre.json()["rejoue"] is True
    assert autre.json()["resultat"]["resultat"] == projection
    _assert_effets_banque(avant, _tables_banque(), proposition=False, recu=True)
    avant = _tables_banque()
    conflit = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer",
        json={**body, "csv_utf8": body["csv_utf8"].replace("10.00", "11.00")},
        headers={"x-csrf-token": csrf},
    )
    assert conflit.status_code == 409
    assert conflit.json()["resultat"]["verdict"]["code"] == "CONFLIT_MUTATION"
    _assert_effets_banque(avant, _tables_banque(), proposition=False, recu=False)
    # La première archive et son reçu gardent exactement leurs champs SQL natifs.
    with stockage.transaction() as cnx:
        for nom in ("registres_maillons", "journal", "mutations_appliquees"):
            citer = cnx.dialect.identifier_preparer.quote
            rows = [dict(row) for row in cnx.exec_driver_sql(f"SELECT * FROM {citer(nom)}").mappings()]
            for ancien in fixture["native_sql_seed"][nom]:
                assert ancien in rows


@pytest.mark.parametrize("phase", ["apres_corps", "calcul", "snapshot", "rang"])
def test_partiel_revoque_ou_snapshot_modifie_rollback(client_banque, monkeypatch, phase):
    from m5_financecore import reconciliation_bancaire_csv

    csrf = _connecter(client_banque)
    _facture_envoyee()
    body = _body("partiel-rollback-fictif", csv_utf8=CSV.replace("100.00", "10.00"))
    if phase == "apres_corps":
        original = banque_metier.previsualiser

        def revoquer(cnx_factory, deps, session, demande):
            with stockage.transaction() as cnx:
                identite.retirer_role(cnx, OWNER, "nathan_owner")
                identite.retirer_role(cnx, OWNER, "admin")
            return original(cnx_factory, deps, session, demande)

        monkeypatch.setattr(banque_metier, "previsualiser", revoquer)
    elif phase in {"calcul", "snapshot"}:
        original = reconciliation_bancaire_csv.previsualiser_releve_csv

        def calculer(*args, **kwargs):
            resultat = original(*args, **kwargs)
            if phase == "calcul":
                cnx = stockage.connexion_courante()
                identite.retirer_role(cnx, OWNER, "nathan_owner")
                identite.retirer_role(cnx, OWNER, "admin")
            else:
                registre = registre_m5.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
                registre.ajouter({"type_entree": "facture_creee", "facture_id": "FAC-ROLLBACK-FICTIVE",
                                  "statut": "BROUILLON", "montant_apres_taxes": Decimal("300.00"),
                                  "horodatage": "2026-09-29T12:00:00+00:00"})
            return resultat

        monkeypatch.setattr(reconciliation_bancaire_csv, "previsualiser_releve_csv", calculer)
    else:
        original = stockage.MaillonsDurables.append

        def intercaler(self, maillon, *, rang_attendu=None):
            if self.registre == "rapprochements_bancaires_proposes":
                corps = {"type_entree": "interleaving-partiel-fictif"}
                original(self, {**corps, "ligne_id": encodage.empreinte(corps, None),
                                "precedent_ligne_id": None})
            return original(self, maillon, rang_attendu=rang_attendu)

        monkeypatch.setattr(stockage.MaillonsDurables, "append", intercaler)
    avant = _tables_banque()
    response = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=body, headers={"x-csrf-token": csrf}
    )
    assert response.status_code == (403 if phase in {"apres_corps", "calcul"} else 409)
    apres = _tables_banque()
    if phase == "apres_corps":
        # Le retrait est une commande séparée avant la transaction bancaire : seuls
        # les rôles changent. Aucun reçu/proposition bancaire n'est autorisé.
        assert {nom for nom in avant if avant[nom] != apres[nom]} == {"roles"}
        with stockage.transaction() as cnx:
            assert identite.personne_active(cnx, OWNER).roles == frozenset()
        assert avant["registres_maillons"] == apres["registres_maillons"]
        assert avant["mutations_appliquees"] == apres["mutations_appliquees"]
    else:
        assert apres == avant


def test_partiel_rejeu_revoque_avant_factures_ou_recu(client_banque, monkeypatch):
    csrf = _connecter(client_banque)
    _facture_envoyee()
    body = _body("partiel-revoque-fictif", csv_utf8=CSV.replace("100.00", "10.00"))
    first = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=body, headers={"x-csrf-token": csrf}
    )
    assert first.status_code == 200
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, OWNER, "nathan_owner")
        identite.retirer_role(cnx, OWNER, "admin")
    calls = {"registre": 0, "recu": 0}
    original = stockage.maillons

    def compter(*args, **kwargs):
        calls["registre"] += 1
        return original(*args, **kwargs)

    def reclamer(*args, **kwargs):
        calls["recu"] += 1
        raise AssertionError("reçu consulté après révocation")

    monkeypatch.setattr(stockage, "maillons", compter)
    monkeypatch.setattr("opsys.idempotence.reclamer", reclamer)
    avant = _tables_banque()
    replay = client_banque.post(
        "/api/finance/rapprochement-bancaire/proposer", json=body, headers={"x-csrf-token": csrf}
    )
    assert replay.status_code == 403
    assert calls == {"registre": 0, "recu": 0}
    assert _tables_banque() == avant
