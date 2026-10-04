"""Parcours HTTP du tableau de performance M7, sur la vérité durable canonique."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from opsys import evenements, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements

SECRET = "secret-performance-console-fictif-2026-" + "x" * 32
PREFIXE = "/opsys"
MOT_DE_PASSE = "mot-de-passe-performance-fictif-1234"
PROPRIETAIRE = "nathan.performance.fictif"


@pytest.fixture
def client_performance(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'console-performance.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, PROPRIETAIRE, "Nathan fictif", MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "admin.performance.fictif", "Admin fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "employe.performance.fictif", "Employé fictif", MOT_DE_PASSE, ["employee"])
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), charger_departements(), stockage.transaction
    )
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client
    stockage.liberer()


def _connecter(client: TestClient, utilisateur: str = PROPRIETAIRE) -> str:
    reponse = client.post(
        "/connexion", data={"identifiant": utilisateur, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False
    )
    assert reponse.status_code == 303, reponse.text
    return client.get("/api/session").json()["csrf"]


def test_performance_authentifie_admin_et_proprietaire_et_refuse_employe(client_performance):
    assert client_performance.get("/marketing/performance", follow_redirects=False).status_code == 303
    assert client_performance.get("/api/marketing/performance").status_code == 401

    _connecter(client_performance, "employe.performance.fictif")
    assert client_performance.get("/marketing/performance", follow_redirects=False).status_code == 403
    assert client_performance.get("/api/marketing/performance").status_code == 403


def test_performance_admin_console_actif_lit_sans_ecrire(client_performance):
    _connecter(client_performance, "admin.performance.fictif")
    with stockage.transaction():
        avant = list(stockage.maillons("m07-marketing", "performance_campagnes"))

    page = client_performance.get("/marketing/performance")
    api = client_performance.get("/api/marketing/performance")

    with stockage.transaction():
        apres = list(stockage.maillons("m07-marketing", "performance_campagnes"))
    assert page.status_code == 200, page.text
    assert api.status_code == 200, api.text
    assert api.json()["resultat"]["couverture"] == "INCONNUE"
    assert avant == apres == []


@pytest.mark.parametrize(
    "query",
    [
        "debut=2026-09-01",
        "debut=2026-09-01&fin=2026-10-01&acteur=admin",
        "debut=2026-09-01&fin=2026-10-01&role=admin",
        "debut=2026-09-01&fin=2026-10-01&cout=0",
        "debut=2026-09-01&fin=2026-10-01&debut=2026-09-02",
        "debut=2026-02-30&fin=2026-03-01",
        "debut=2026-09-02&fin=2026-09-01",
        "debut=2025-09-29&fin=2026-09-30",
    ],
)
def test_performance_refuse_query_noncanonique(client_performance, query):
    _connecter(client_performance)
    reponse = client_performance.get(f"/api/marketing/performance?{query}")
    assert reponse.status_code == 400, reponse.text


def test_performance_session_desactivee_est_revalidee_avant_lecture(client_performance):
    _connecter(client_performance)
    assert client_performance.get("/marketing/performance").status_code == 200
    with stockage.transaction() as cnx:
        identite.activer(cnx, PROPRIETAIRE, False)
    assert client_performance.get("/api/marketing/performance").status_code == 401


def test_performance_role_retire_est_revalide_avant_lecture(client_performance):
    _connecter(client_performance)
    assert client_performance.get("/marketing/performance").status_code == 200
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, PROPRIETAIRE, "nathan_owner")
    assert client_performance.get("/api/marketing/performance").status_code == 403


def _publier_faits_performance(deps, *, campagne: str = "automne", suffixe: str = "01") -> None:
    from datetime import date

    jour = date.today().isoformat()
    lead_id = f"lead-performance-opaque-fictif-{suffixe}"
    devis_id = f"devis-performance-fictif-{suffixe}"
    chantier_id = f"chantier-performance-opaque-fictif-{suffixe}"
    wct_id = f"wct-performance-fictif-{suffixe}"
    evenements.publier(
        "m2.client_associe",
        "m02-revenue-crm",
        {
            "lead_id": lead_id,
            "client_id": f"client-performance-opaque-fictif-{suffixe}",
            "horodatage_association": f"{jour}T12:00:00Z",
            "utm": {"utm_source": "google", "utm_campaign": campagne},
        },
        evenement_id=f"m2-performance-client-fictif-{suffixe}",
    )
    evenements.publier(
        "m3.devis_accepte",
        "m03-estimation",
        {
            "devis_id": devis_id,
            "lead_id": lead_id,
            "chantier_id": chantier_id,
            "lignes": [{
                "reference_ligne": f"{devis_id}-L0",
                "description": "Gouttières",
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": "2000.00",
                "prix_ligne": "2000.00",
                "reference_besoin_materiau": None,
            }],
            "cout_total": "1000.00",
            "prix_total": "2000.00",
            "taux_marge": "1.00",
            "horodatage_acceptation": f"{jour}T13:00:00Z",
        },
        evenement_id=f"m3-performance-devis-fictif-{suffixe}",
    )
    evenements.publier(
        "m5.rentabilite_chantier",
        "m05-financecore",
        {
            "evenement_id": f"m5-performance-rentabilite-fictif-{suffixe}",
            "devis_id": devis_id,
            "chantier_id": chantier_id,
            "wct_id": wct_id,
            "sequence": 1,
            "version_entrees": "a" * 64,
            "horodatage_completion": f"{jour}T14:00:00Z",
            "verdict": "CALCULEE",
            "devise": "CAD",
            "cout_reel_complet": True,
            "cout_reel_cad": "800.00",
            "cout_connu_cad": "800.00",
            "marge_reelle_cad": "1200.00",
            "marge_prevue_cad": "1000.00",
            "ecart_marge_cad": "200.00",
            "manque": [],
        },
        evenement_id=f"m5-performance-rentabilite-publie-fictif-{suffixe}",
    )
    livraisons = evenements.repartir(
        {"m07-marketing": deps["m07-marketing"]}, maintenant=f"{jour}T23:59:00+00:00"
    )
    assert livraisons["traites"] == 3, livraisons
    assert livraisons["echecs"] == 0 and livraisons["quarantaines"] == 0, livraisons


def test_performance_lit_evenements_canoniques_et_n_invente_pas_couts_ou_roi(client_performance):
    csrf = _connecter(client_performance)
    vide = client_performance.get("/api/marketing/performance?debut=2026-09-01&fin=2026-09-30")
    assert vide.status_code == 200, vide.text
    assert vide.json()["resultat"]["couverture"] == "INCONNUE"
    assert vide.json()["resultat"]["campagnes"] == []

    from opsys.departements import charger_departements

    _publier_faits_performance(charger_departements())
    from datetime import date

    jour = date.today().isoformat()
    api = client_performance.get(f"/api/marketing/performance?debut={jour}&fin={jour}")
    assert api.status_code == 200, api.text
    rapport = api.json()["resultat"]
    assert rapport["couverture"] == "PARTIELLE"
    campagne = rapport["campagnes"][0]
    assert campagne["source"] == "google" and campagne["campagne"] == "automne"
    assert campagne["leads_associes_observes"] == 1
    assert campagne["devis_acceptes"] == 1
    assert campagne["chantiers_marge_constatee"] == 1
    assert campagne["marge_constatee_M5_cad"] == "1200.00"
    assert campagne["cout_ads_cad"] is None and campagne["cout_par_lead_cad"] is None
    assert campagne["roi"] is None and campagne["statut_financier"] == "INCONNU"

    page = client_performance.get(f"/marketing/performance?debut={jour}&fin={jour}")
    assert page.status_code == 200
    assert "Leads associés observés M2" in page.text
    assert "marge constatée M5" in page.text
    assert "sans preuve d’encaissement" in page.text
    assert "Coûts publicitaires" in page.text and "Inconnu" in page.text
    assert "ROI" in page.text and "1200.00" in page.text
    assert csrf


def test_performance_echappe_les_valeurs_utm_canoniques(client_performance):
    from opsys.departements import charger_departements

    _connecter(client_performance)
    _publier_faits_performance(charger_departements(), campagne='<img src=x onerror="alert(1)">')
    from datetime import date

    jour = date.today().isoformat()
    page = client_performance.get(f"/marketing/performance?debut={jour}&fin={jour}")
    assert page.status_code == 200
    assert '<img src=x onerror="alert(1)">' not in page.text
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in page.text


def test_performance_html_ferme_un_seul_tableau_pour_plusieurs_campagnes(client_performance):
    from datetime import date

    from opsys.departements import charger_departements

    _connecter(client_performance)
    deps = charger_departements()
    _publier_faits_performance(deps, campagne="printemps", suffixe="multi-a")
    _publier_faits_performance(deps, campagne="automne", suffixe="multi-b")
    jour = date.today().isoformat()
    page = client_performance.get(f"/marketing/performance?debut={jour}&fin={jour}")

    assert page.status_code == 200, page.text
    assert page.text.count("<table>") == page.text.count("</table>") == 1
    assert page.text.count("<tbody>") == page.text.count("</tbody>") == 1
    assert page.text.count("<tr>") == 3  # en-tête et deux campagnes
    assert "printemps" in page.text and "automne" in page.text
    assert page.text.count("PARTIELLE") >= 2


def test_performance_rendu_echappe_exclusions_et_references_et_ferme_les_donnees_invalides():
    from opsys.console.marketing_performance_ui import _contenu

    page = _contenu({
        "periode": {"debut": "2026-09-01", "fin": "2026-09-30"},
        "couverture": "PARTIELLE",
        "manque": ["COUTS_ABSENTS"],
        "exclusions": {"<script>source</script>": 1},
        "source_refs": [{"type": "m2.client_associe", "reference": "<ref>&"}],
        "campagnes": [
            {
                "source": "google",
                "campagne": "printemps",
                "leads_associes_observes": 1,
                "devis_acceptes": 1,
                "chantiers_marge_constatee": 0,
                "marge_constatee_M5_cad": None,
                "statut_financier": "INCONNU",
                "couverture": "PARTIELLE",
                "manque": ["MARGE_ABSENTE"],
                "source_refs": [],
            },
            {
                "source": None,
                "campagne": None,
                "leads_associes_observes": 1,
                "devis_acceptes": 0,
                "chantiers_marge_constatee": 0,
                "marge_constatee_M5_cad": None,
                "statut_financier": "INCONNU",
                "couverture": "INCONNUE",
                "manque": ["ATTRIBUTION_ABSENTE"],
                "source_refs": [],
            },
        ],
    })
    assert page.count("</tbody></table>") == 1
    assert "INCONNUE" in page and "PARTIELLE" in page
    assert "&lt;script&gt;source&lt;/script&gt;" in page
    assert "&lt;ref&gt;&amp;" in page
    assert "<script>source</script>" not in page

    malformed = _contenu({"campagnes": [None, {"source": {"pii": "secret"}, "leads_associes_observes": {}}]})
    assert "observations sont mal formées" in malformed
    assert "{'pii': 'secret'}" not in malformed
    assert "secret" not in malformed
