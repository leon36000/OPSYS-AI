"""Rapport CMO privé sur vraie SQLite ; fixtures métier fictives, aucun provider."""

import pytest
from fastapi.testclient import TestClient
from m7_marketing import performance_campagnes
from sqlalchemy import select

from opsys import contexte, identite, outils, stockage
from opsys.console import application, marketing_rapport
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import REGISTRES

_MOT_DE_PASSE = "mot-de-passe-rapport-fictif-123"
_PERIODE = {"debut": "2026-09-01", "fin": "2026-09-30"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'rapport-fictif.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-fictif"))
    stockage.migrer()
    with stockage.transaction() as cnx:
        for personne, roles in (("owner.fictif", ["nathan_owner"]), ("admin.fictif", ["admin"]),
                                ("double.fictif", ["admin", "nathan_owner"]), ("employe.fictif", ["employee"])):
            identite.creer_personne(cnx, personne, personne, _MOT_DE_PASSE, roles)
    app = application.creer_application(
        Configuration("rapport-secret-fictif-" + "x" * 64, cookie_securise=False, prefixe="/opsys"),
        charger_departements(), stockage.transaction,
    )
    with TestClient(app, base_url="https://testserver/opsys") as navigateur:
        yield navigateur
    stockage.liberer()


def _connecter(client, personne="owner.fictif"):
    response = client.post("/connexion", data={"identifiant": personne, "mot_de_passe": _MOT_DE_PASSE},
                           follow_redirects=False)
    assert response.status_code == 303, response.text


def _faits(n=1, campagne="campagne-fictive"):
    for i in range(n):
        performance_campagnes.enregistrer_fait("m2.client_associe", {
            "lead_id": f"lead-fictif-{i}", "client_id": f"client-fictif-{i}",
            "source": "source-fictive", "campagne": campagne + str(i),
            "horodatage_association": "2026-09-10T12:00:00Z",
        })
        performance_campagnes.enregistrer_fait("m3.devis_accepte", {
            "devis_id": f"devis-fictif-{i}", "lead_id": f"lead-fictif-{i}", "chantier_id": None,
            "horodatage_acceptation": "2026-09-11T12:00:00Z",
        })


def test_route_reelle_authentification_et_roles_avant_lecture(client):
    assert client.get("/api/marketing/cmo/rapport", params=_PERIODE).status_code == 401
    assert client.get("/marketing/cmo/rapport", params=_PERIODE, follow_redirects=False).status_code == 303
    _connecter(client, "employe.fictif")
    assert client.get("/api/marketing/cmo/rapport", params=_PERIODE).status_code == 403


@pytest.mark.parametrize("query", [
    {}, {"debut": "2026-09-01"}, {**_PERIODE, "role": "admin"},
    {**_PERIODE, "autorise_couts": "true"}, {**_PERIODE, "outil": "m5_etat_tresorerie"},
    {"debut": "2026-10-01", "fin": "2026-09-01"}, {"debut": "2020-01-01", "fin": "2026-09-30"},
    {"debut": "2026-9-1", "fin": "2026-09-30"}, {"debut": "2026-02-30", "fin": "2026-09-30"},
])
def test_entrees_http_fermees(client, query):
    _connecter(client)
    assert client.get("/api/marketing/cmo/rapport", params=query).status_code == 400


def test_dates_dupliquees_refusees(client):
    _connecter(client)
    assert client.get("/api/marketing/cmo/rapport?debut=2026-09-01&fin=2026-09-30&fin=2026-09-29").status_code == 400


def test_owner_seul_ne_forge_pas_admin_et_sdk_reel_sans_ecriture(client, monkeypatch):
    _connecter(client)
    _faits()
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(REGISTRES)).all()
    original, appels = outils.executer_atomique, []

    def observer(outil, arguments):
        appels.append((outil.nom, contexte.identite_appelante(), dict(arguments)))
        return original(outil, arguments)

    monkeypatch.setattr(outils, "executer_atomique", observer)
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 200, response.text
    rapport = response.json()["resultat"]
    assert rapport["crm_courant"]["statut"] == rapport["contenus_cumules"]["statut"] == "NON_AUTORISEE"
    assert [nom for nom, _, _ in appels] == ["m7_lire_performance_campagnes", "m5_lire_rentabilite_chantier"]
    assert all(id_.personne == "owner.fictif" and id_.role == "nathan_owner" and id_.source == "console"
               for _, id_, _ in appels)
    assert all("role" not in args and "autorise_couts" not in args for _, _, args in appels)
    assert rapport["campagnes"][0]["marge_constatee_M5_cad"] is None
    assert rapport["campagnes"][0]["roi"] is None
    assert rapport["finance_courante"]["lignes"][0]["statut"] == "INCONNU_SOURCE"
    assert rapport["observation_source"]["integrite"] == "historique_non_scelle"
    assert response.headers["cache-control"] == "no-store"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(REGISTRES)).all() == avant


@pytest.mark.parametrize("personne", ["admin.fictif", "double.fictif"])
def test_admin_db_reel_lit_sources_publiques(client, personne, monkeypatch):
    _connecter(client, personne)
    original, roles = outils.executer_atomique, []

    def observer(outil, arguments):
        roles.append((outil.nom, contexte.identite_appelante().role))
        return original(outil, arguments)

    monkeypatch.setattr(outils, "executer_atomique", observer)
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 200, response.text
    assert roles == [("m7_lire_performance_campagnes", "admin"), ("m2_lister_leads", "admin"),
                     ("m8_lire_mesures_contenus", "admin")]
    rapport = response.json()["resultat"]
    assert rapport["contenus_cumules"]["statut"] == "PAGES_LUES"
    assert rapport["crm_courant"]["lignes"] == []
    assert rapport["campagnes"] == []


def test_role_retire_au_milieu_refuse_sans_montant(client, monkeypatch):
    _connecter(client, "admin.fictif")
    _faits()
    original = outils.executer_atomique

    def retirer(outil, arguments):
        resultat = original(outil, arguments)
        if outil.nom == "m7_lire_performance_campagnes":
            identite.retirer_role(stockage.connexion_courante(), "admin.fictif", "admin")
        return resultat

    monkeypatch.setattr(outils, "executer_atomique", retirer)
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 403, response.text
    assert "marge" not in response.text and "campagnes" not in response.text


def test_recheck_final_apres_rendu_et_pas_cache(client, monkeypatch):
    _connecter(client)
    original = marketing_rapport._borner_sortie

    def retirer(resultat):
        original(resultat)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "owner.fictif", "nathan_owner")

    monkeypatch.setattr(marketing_rapport, "_borner_sortie", retirer)
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 403 and "observation_source" not in response.text


def test_faits_invalides_refusent_sans_charge_brute(client):
    _connecter(client)
    with stockage.transaction() as cnx:
        cnx.execute(REGISTRES.insert().values(departement="m07-marketing", registre="performance_campagnes",
                                              rang=0, maillon='{"secret_fictif":"ne-pas-afficher"}'))
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 409
    assert "ne-pas-afficher" not in response.text


def test_html_echappe_les_champs_et_presente_inconnues(client):
    _connecter(client)
    _faits(campagne='<script>alert("fictif")</script>')
    response = client.get("/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 200, response.text
    assert '<script>alert("fictif")</script>' not in response.text
    assert "&lt;script&gt;" in response.text and "Historique non scellé" in response.text
    assert "inconnus" in response.text and response.headers["cache-control"] == "no-store"
    assert client.get("/marketing/cmo").text.count("Rapport d’acquisition observée") == 1


def test_quota_campagnes_references_et_octets_indique_omissions_exactes(client):
    _connecter(client)
    _faits(60, campagne="é" * 500)
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 200, response.text
    rapport = response.json()["resultat"]
    assert len(response.content) <= 32 * 1024
    assert len(rapport["campagnes"]) <= 50 and len(rapport["references"]) <= 100
    assert rapport["omissions"]["campagnes"] == 60 - len(rapport["campagnes"])
    assert rapport["omissions"]["references"] == 120 - len(rapport["references"])
    assert rapport["finance_courante"]["devis_non_lus"] == 56
    assert rapport["budget"]["appels_effectues"] == 5


@pytest.mark.parametrize("suivant", [True, 0, 1])
def test_page_cursor_invalide_ne_reboucle_pas(client, monkeypatch, suivant):
    _connecter(client, "admin.fictif")
    original, appels = outils.executer_atomique, []

    def page_invalide(outil, arguments):
        appels.append(outil.nom)
        if outil.nom == "m2_lister_leads":
            return {"ok": True, "resultat": {"accepte": True, "resultat": {
                "leads": [], "decalage": 0, "total": 1, "affichees": 0, "reste": 1, "suivant": suivant,
            }}}
        return original(outil, arguments)

    monkeypatch.setattr(outils, "executer_atomique", page_invalide)
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 200, response.text
    assert response.json()["resultat"]["crm_courant"]["statut"] == "INDISPONIBLE_OU_INVALIDE"
    assert appels.count("m2_lister_leads") == 1


def test_aucun_post_ni_mcp_nouveau(client):
    _connecter(client)
    assert client.post("/api/marketing/cmo/rapport", json=_PERIODE).status_code == 405
    assert not any(o.nom == "m7_rapport_acquisition" for o in charger_departements()["m07-marketing"].charger_outils())


def test_neuf_appels_maximum_et_pages_non_exhaustives_explicitement(client, monkeypatch):
    _connecter(client, "admin.fictif")
    _faits(6)
    original, appels = outils.executer_atomique, []

    def sources_fictives(outil, arguments):
        appels.append((outil.nom, dict(arguments)))
        if outil.nom == "m2_lister_leads":
            depart = arguments["decalage"]
            lignes = [{"lead_id": f"lead-fictif-{i}", "statut": "QUALIFIE", "contact_fictif": "ne-pas-afficher"}
                      for i in range(depart, depart + 20)]
            charge = {"leads": lignes, "decalage": depart, "total": 60, "affichees": 20,
                      "reste": 40 - depart, "suivant": depart + 20}
            return {"ok": True, "resultat": {"accepte": True, "resultat": charge}}
        if outil.nom == "m8_lire_mesures_contenus":
            depart = arguments["depart"]
            charge = {"contenus": [{"utm_content": f"contenu-fictif-{depart}", "canal": "facebook",
                                     "exporte_le": None, "suivi": "sans_lien", "leads": None,
                                     "devis_envoyes": None, "devis_acceptes": None}],
                      "sources": [], "affichage": {"depart": depart, "n_contenus": 3,
                      "affiches": 1, "reste": 2 - depart, "prochain_depart": depart + 1}}
            return {"ok": True, "resultat": charge}
        return original(outil, arguments)

    monkeypatch.setattr(outils, "executer_atomique", sources_fictives)
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 200, response.text
    rapport = response.json()["resultat"]
    assert len(appels) == rapport["budget"]["appels_effectues"] == 9
    assert rapport["crm_courant"]["statut"] == rapport["contenus_cumules"]["statut"] == "PARTIELLE"
    assert rapport["crm_courant"]["reste_source"] == 20
    assert rapport["contenus_cumules"]["reste_source"] == 1
    assert len(rapport["crm_courant"]["lignes"]) == 6 and rapport["finance_courante"]["devis_non_lus"] == 2
    assert "ne-pas-afficher" not in response.text


def test_finance_courante_zero_connu_prix_provisoire_et_trace_perimee(client, monkeypatch):
    _connecter(client)
    _faits()
    original = outils.executer_atomique

    def finance_fictive(outil, arguments):
        if outil.nom != "m5_lire_rentabilite_chantier":
            return original(outil, arguments)
        return {"ok": True, "resultat": {"accepte": True, "resultat": {"chantiers": [{
            "devis_id": "devis-fictif-0", "statut": "calculee",
            "rentabilite": {"verdict": "PARTIELLE", "prix_facture": "2000.00", "marge_reelle": "0.00",
                             "prix_definitif": False, "cout_reel": {"complet": False, "cout_total": None,
                             "cout_total_connu": "0.00"}, "manque": [{"code": "PIECE_FICTIVE_MANQUANTE"}]},
            "trace": {"version_entrees": "b" * 64, "a_jour": False},
        }]}}}

    monkeypatch.setattr(outils, "executer_atomique", finance_fictive)
    response = client.get("/api/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 200, response.text
    rapport = response.json()["resultat"]
    finance = rapport["finance_courante"]["lignes"][0]
    assert finance["marge_reelle"] == "0.00" and finance["cout_reel"]["cout_total"] is None
    assert finance["prix_definitif"] is False and finance["trace"]["a_jour"] is False
    assert finance["manque"] == ["PIECE_FICTIVE_MANQUANTE"]
    assert rapport["campagnes"][0]["marge_constatee_M5_cad"] is None
    html = client.get("/marketing/cmo/rapport", params=_PERIODE).text
    assert "prix provisoire" in html and "trace non à jour" in html


def test_html_echappe_trop_grand_refuse_sans_sortie_metier(client):
    _connecter(client)
    _faits(30, campagne="&" * 500)
    response = client.get("/marketing/cmo/rapport", params=_PERIODE)
    assert response.status_code == 409 and len(response.content) < 32 * 1024
    assert "campagne-fictive" not in response.text and "marge_constatee" not in response.text
