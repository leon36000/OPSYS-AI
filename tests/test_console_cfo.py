"""Dossier CFO dans la vraie console, avec sources et personnes fictives."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from opsys import identite, stockage
from opsys.console import application, cfo_ui
from opsys.console.securite import Configuration
from opsys.stockage import codec
from opsys.stockage.schema import META, REGISTRES

FICTIF = True
SECRET = "secret-console-dossier-cfo-fictif-" + "x" * 32
PREFIXE = "/opsys"
PASSWORD = "mot-de-passe-console-cfo-fictif-123"
QUESTION = "Quelles pièces faut-il vérifier avant de renouveler le camion?"


@pytest.fixture
def client_cfo(session):
    from m5_financecore import outils

    outils.utiliser_stockage_durable()
    with session() as cnx:
        for personne, roles in (
            ("owner.cfo.fictif", ["nathan_owner"]),
            ("admin.cfo.fictif", ["admin"]),
            ("employee.cfo.fictif", ["employee"]),
        ):
            identite.creer_personne(cnx, personne, "Personne fictive", PASSWORD, roles)
    app = application.creer_application(Configuration(SECRET), None, session)
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def _connecter(client, personne="owner.cfo.fictif"):
    retour = client.post(
        "/connexion", data={"identifiant": personne, "mot_de_passe": PASSWORD}, follow_redirects=False
    )
    assert retour.status_code == 303
    return client.get("/api/session").json()["csrf"]


def _etat():
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)))
            for nom, table in META.tables.items()
        }


@pytest.mark.parametrize("personne", ["owner.cfo.fictif", "admin.cfo.fictif"])
def test_rapport_cfo_lit_les_25_rubriques_sans_mutation_et_sans_inventer(client_cfo, personne):
    csrf = _connecter(client_cfo, personne)
    avant = _etat()
    retour = client_cfo.post(
        "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
    )
    assert retour.status_code == 200, retour.text
    rapport = retour.json()["resultat"]
    assert rapport["question_posee"] == QUESTION
    assert rapport["reference"]["aujourd_hui"] == datetime.now(UTC).date().isoformat()
    assert [section["numero"] for section in rapport["rubriques"]] == list(range(1, 26))
    assert rapport["rubriques"][2]["statut"] == "INCONNU"
    assert rapport["rubriques"][2]["contenu"] is None
    assert rapport["rubriques"][3]["statut"] == "INCONNU"
    assert _etat() == avant


def test_page_cfo_reliee_a_finance_et_affiche_les_faits_echappes(client_cfo):
    csrf = _connecter(client_cfo)
    finance = client_cfo.get("/finance")
    assert finance.status_code == 200
    assert f'href="{PREFIXE}/finance/cfo"' in finance.text
    page = client_cfo.get("/finance/cfo")
    assert page.status_code == 200 and "Préparer un dossier de décision" in page.text
    question = "<script>alert('question-fictive')</script>"
    avant = _etat()
    rapport = client_cfo.post("/finance/cfo", data={"csrf": csrf, "question_posee": question})
    assert rapport.status_code == 200, rapport.text
    assert "&lt;script&gt;" in rapport.text and "<script>" not in rapport.text
    assert "Cashflow 13 semaines" in rapport.text and "Validation requise" in rapport.text
    assert "Données manquantes" in rapport.text and "Sources" in rapport.text
    assert "script-src 'self'" in rapport.headers["content-security-policy"]
    assert _etat() == avant



def test_page_cfo_decode_obligations_compactes_sans_perdre_les_sources_ni_ecrire(
    client_cfo, monkeypatch
):
    from m5_financecore import outils

    aujourdhui = datetime.now(UTC).date().isoformat()
    configuration = {
        "obligations_declarees": {
            "paies": {"montant": "4200.00", "source": "<script>paies-fictives</script>", "au": aujourdhui},
            "das": {"montant": "1350.75", "source": "retenues DAS fictives", "au": aujourdhui},
        },
        "calendrier_obligations": {
            "paies": {
                "autorite": "Autorité fictive paie", "periode_debut": "2026-09-01",
                "periode_fin": "2026-09-30", "echeance_source": "<script>source-paie-fictive</script>",
                "source_consultee_le": aujourdhui, "source_applicable_du": "2026-01-01",
                "source_applicable_jusqu_au": "2026-12-31", "annee": 2026, "version": "édition fictive 2026-v2",
            },
            "das": {
                "autorite": "Autorité fictive DAS", "periode_debut": "2026-09-01",
                "periode_fin": "2026-09-30", "echeance_source": "Avis fictif DAS",
                "source_consultee_le": aujourdhui, "source_applicable_du": "2026-01-01",
                "source_applicable_jusqu_au": "2026-06-30", "annee": 2026, "version": "édition fictive H1",
            },
        },
        "prevision": {
            "horizon_semaines": 13,
            "seuil_alerte": {"montant": "10000.00", "source": "Décision fictive", "au": aujourdhui},
            "delai_encaissement_clients_jours": 30,
            "delai_paiement_fournisseurs_jours": 30,
            "echeances_obligations": {"paies": "2026-10-09", "das": "2026-10-15"},
        },
    }
    monkeypatch.setattr(outils, "_configuration_manifeste", lambda: configuration)
    csrf = _connecter(client_cfo)
    avant = _etat()

    retour = client_cfo.post("/finance/cfo", data={"csrf": csrf, "question_posee": QUESTION})

    assert retour.status_code == 200, retour.text
    assert "Paies" in retour.text and "Déductions à la source (DAS)" in retour.text
    assert "Montant déclaré (CAD)" in retour.text and "4200.00" in retour.text
    assert "1350.75" in retour.text and "Montant utilisable (CAD)" in retour.text
    assert "2026-09-01 au 2026-09-30" in retour.text
    assert "2026-10-09" in retour.text and "2026-10-15" in retour.text
    assert "Autorité fictive paie" in retour.text and "édition fictive 2026-v2" in retour.text
    assert "Source périmée" in retour.text and "Non disponible" in retour.text
    assert "&lt;script&gt;paies-fictives&lt;/script&gt;" in retour.text
    assert "&lt;script&gt;source-paie-fictive&lt;/script&gt;" in retour.text
    assert "<script>" not in retour.text
    assert "montant_utilisable_cad" not in retour.text
    assert "REJ-CALENDRIER-DAS-SOURCE-PERIMEE" not in retour.text
    assert _etat() == avant


def test_cfo_affichage_compact_refuse_les_codes_inconnus_et_garde_legacy():
    ligne_paie = ["d", "4200.00", "4200.00", "2026-10-09", "a"]
    ligne_das = ["x", "1350.75", None, "2026-10-15", "p"]
    compacte = ["pd", "sduet", [ligne_paie, ligne_das], 256]
    html = cfo_ui._donnee({"obligations_declarees": compacte})
    assert "Paies" in html and "Déductions à la source (DAS)" in html
    assert "4200.00" in html and "1350.75" in html and "Non disponible" in html
    assert "Source périmée" in html and "256" not in html

    code_inconnu = ["pd", "sduet", [ligne_paie, ["SOURCE_PRIVEE", None, None, "2026-10-15", "p"]], 0]
    html_inconnu = cfo_ui._donnee({"obligations_declarees": code_inconnu})
    assert "ne peuvent pas être affichées" in html_inconnu and "SOURCE_PRIVEE" not in html_inconnu

    etat_incoherent = ["p", "sduet", [["i", "4200.00", "4200.00", "2026-10-09", "a"]], 0]
    html_incoherent = cfo_ui._donnee({"obligations_declarees": etat_incoherent})
    assert "ne peuvent pas être affichées" in html_incoherent
    assert "4200.00" not in html_incoherent

    code_colonne_inconnu = ["p", "sduetz", [["d", "4200.00", "4200.00", "2026-10-09", "a", "CODE_PRIVÉ"]], 0]
    malformed = ["p", "sduet", [["d", "4200.00"]], 0]
    for valeur in (code_colonne_inconnu, malformed):
        html_refuse = cfo_ui._donnee({"obligations_declarees": valeur})
        assert "ne peuvent pas être affichées" in html_refuse
        assert "CODE_PRIVÉ" not in html_refuse

    legacy = cfo_ui._donnee({"obligations_declarees": {"paies_declarees": {"montant_cad": "4200.00"}}})
    assert "paies declarees" in legacy.lower() and "4200.00" in legacy


@pytest.mark.parametrize("surface", ["api", "formulaire"])
@pytest.mark.parametrize("defaut", ["rubrique", "rapport"])
def test_cfo_refuse_rapport_malforme_sans_500_ni_mutation(
    client_cfo, monkeypatch, surface, defaut
):
    rapport = {
        "question_posee": QUESTION,
        "mention": "Rapport fictif",
        "rubriques": [
            {"numero": numero, "titre": f"Rubrique {numero}", "statut": "INCONNU", "contenu": None}
            for numero in range(1, 26)
        ],
    }
    if defaut == "rubrique":
        rapport["rubriques"].append(None)
    else:
        rapport["donnee_non_json"] = object()
    monkeypatch.setattr(cfo_ui.metier, "executer", lambda *args, **kwargs: {
        "accepte": True, "resultat": rapport,
    })
    csrf = _connecter(client_cfo)
    avant = _etat()
    if surface == "api":
        retour = client_cfo.post(
            "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
        )
    else:
        retour = client_cfo.post(
            "/finance/cfo", data={"csrf": csrf, "question_posee": QUESTION}
        )
    assert retour.status_code == 409, retour.text
    assert _etat() == avant


@pytest.mark.parametrize("surface", ["api", "formulaire"])
def test_cfo_revalide_role_apres_lecture_et_ne_publie_pas_si_revoque(
    client_cfo, session, monkeypatch, surface
):
    rapport = {
        "question_posee": QUESTION,
        "mention": "FINANCIAL-SECRET-50000",
        "rubriques": [
            {
                "numero": numero, "titre": f"Rubrique {numero}", "statut": "INCONNU",
                "contenu": "FINANCIAL-SECRET-50000" if numero == 16 else None,
            }
            for numero in range(1, 26)
        ],
    }

    def executer(cnx, *args, **kwargs):
        identite.retirer_role(cnx, "owner.cfo.fictif", "nathan_owner")
        return {"accepte": True, "resultat": rapport}

    monkeypatch.setattr(cfo_ui.metier, "executer", executer)
    csrf = _connecter(client_cfo)
    avant = _etat()
    if surface == "api":
        retour = client_cfo.post(
            "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
        )
    else:
        retour = client_cfo.post(
            "/finance/cfo", data={"csrf": csrf, "question_posee": QUESTION}
        )
    assert retour.status_code == 403, retour.text
    assert "FINANCIAL-SECRET-50000" not in retour.text
    apres = _etat()
    assert apres["roles"] != avant["roles"]
    assert {k: v for k, v in apres.items() if k not in {"personnes", "roles"}} == {
        k: v for k, v in avant.items() if k not in {"personnes", "roles"}
    }

def test_rapport_cfo_reprend_le_cash_canonique_plutot_que_le_recalculer(client_cfo, monkeypatch):
    from m5_financecore import outils

    jour = datetime.now(UTC).date().isoformat()
    monkeypatch.setattr(outils, "_configuration_manifeste", lambda: {
        "fiscal": {
            "frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12,
            "taxes_remises_jusqu_au": "2026-06-30",
        },
        "obligations_declarees": {
            cle: {"montant": "0.00", "source": f"Déclaration fictive {cle}", "au": jour}
            for cle in ("paies", "das", "dettes")
        },
        "prevision": {
            "horizon_semaines": 13,
            "seuil_alerte": {"montant": "10000.00", "source": "Décision fictive", "au": jour},
            "delai_encaissement_clients_jours": 30,
            "delai_paiement_fournisseurs_jours": 30,
            "echeances_obligations": {cle: jour for cle in ("paies", "das", "dettes")},
        },
    })
    assert outils.enregistrer_mouvement(
        "200000.00", "ENCAISSEMENT", f"{jour}T12:00:00+00:00", "STANDARD", "Relevé fictif"
    )["accepte"] is True
    assert outils.enregistrer_mouvement(
        "20000.00", "PROVISION", f"{jour}T12:05:00+00:00", "STANDARD", "Réserve fictive"
    )["accepte"] is True
    csrf = _connecter(client_cfo)
    cash = client_cfo.get("/api/finance/cash-libre").json()["cash_libre"]
    avant = _etat()
    retour = client_cfo.post(
        "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
    )
    assert retour.status_code == 200, retour.text
    dossier = retour.json()["resultat"]
    resume = dossier["rubriques"][1]["contenu"]
    assert resume["cash_libre_cad"] == cash["cash_libre"]
    assert resume["cash_libre_calculable"] == cash["calculable"]
    semaines = dossier["rubriques"][10]["contenu"]
    assert semaines["semaines_couvertes"] == 13
    page = client_cfo.post("/finance/cfo", data={"csrf": csrf, "question_posee": QUESTION})
    assert page.status_code == 200, page.text
    assert "<th>Entrées (CAD)</th>" in page.text
    assert "L’effet de la décision envisagée" in page.text
    for index in range(13):
        debut = (datetime.now(UTC).date() + timedelta(days=7 * index)).isoformat()
        cellules = [str(index + 1), debut, "CALCULE", *[
            semaines[cle][index] for cle in ("entrees_cad", "sorties_cad", "solde_fin_cad")
        ]]
        assert "<tr>" + "".join(f"<td>{cellule}</td>" for cellule in cellules) + "</tr>" in page.text
    assert _etat() == avant


def test_cfo_refuse_csrf_employe_et_role_retire_sans_lire_les_chiffres(client_cfo, session):
    csrf = _connecter(client_cfo)
    avant = _etat()
    assert client_cfo.post("/api/finance/cfo", json={"question_posee": QUESTION}).status_code == 403
    assert client_cfo.post("/finance/cfo", data={"question_posee": QUESTION}).status_code == 403
    assert _etat() == avant
    with session() as cnx:
        identite.retirer_role(cnx, "owner.cfo.fictif", "nathan_owner")
    apres_retrait = _etat()
    assert client_cfo.get("/finance/cfo").status_code == 403
    assert client_cfo.post(
        "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
    ).status_code == 403
    assert _etat() == apres_retrait
    csrf = _connecter(client_cfo, "employee.cfo.fictif")
    assert client_cfo.get("/finance/cfo").status_code == 403
    assert client_cfo.post(
        "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
    ).status_code == 403


@pytest.mark.parametrize("commande", [
    {}, {"question_posee": ""}, {"question_posee": False}, {"question_posee": "q" * 1001},
    {"question_posee": QUESTION, "role": "admin"},
    {"question_posee": QUESTION, "aujourd_hui": "2026-01-01"},
    {"question_posee": QUESTION, "montant": "50000"},
])
def test_cfo_refuse_parametres_usurpes_et_question_hors_bornes(client_cfo, commande):
    csrf = _connecter(client_cfo)
    avant = _etat()
    retour = client_cfo.post("/api/finance/cfo", json=commande, headers={"x-csrf-token": csrf})
    assert retour.status_code == 400, retour.text
    assert _etat() == avant


def test_cfo_refuse_query_et_redirige_personne_non_connectee(client_cfo):
    retour = client_cfo.get("/finance/cfo", follow_redirects=False)
    assert retour.status_code == 303 and retour.headers["location"] == f"{PREFIXE}/connexion"
    _connecter(client_cfo)
    assert client_cfo.get("/finance/cfo?role=admin").status_code == 400


@pytest.mark.parametrize("surface", ["api", "formulaire"])
def test_cfo_refuse_registre_sql_altere_sans_rendre_ni_modifier_les_chiffres(client_cfo, surface):
    from m5_financecore import outils

    csrf = _connecter(client_cfo)
    assert outils.enregistrer_mouvement(
        "200000.00", "ENCAISSEMENT", "2026-09-30T12:00:00+00:00", "STANDARD", "Relevé fictif"
    )["accepte"] is True
    with stockage.transaction() as cnx:
        cible = (
            (REGISTRES.c.departement == "m05-financecore")
            & (REGISTRES.c.registre == "principal")
            & (REGISTRES.c.rang == 0)
        )
        maillon = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(cible)).scalar_one())
        maillon["montant"] = Decimal("999999.99")
        cnx.execute(update(REGISTRES).where(cible).values(maillon=codec.encoder(maillon)))
    avant = _etat()
    if surface == "api":
        retour = client_cfo.post(
            "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
        )
    else:
        retour = client_cfo.post("/finance/cfo", data={"csrf": csrf, "question_posee": QUESTION})
    assert retour.status_code == 409, retour.text
    assert "maillon invalide" in retour.text
    assert "999999.99" not in retour.text and "cash_libre_cad" not in retour.text
    assert _etat() == avant
