"""Console des suivis M9 : vraies routes, session SQL et preuves M8 fictives, sans effet métier."""
from __future__ import annotations

import html
import importlib.util
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from opsys import etat, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_console_suivis_m9_schedule",
    RACINE / "departments/m09-strategic-intelligence/tests/test_echeancier_suivis.py",
)
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)
b = h.b
installation = h.installation
REFERENCE = h.REFERENCE
SECRET = "signature-console-suivis-m9-fictive-" + "x" * 32
MOT_DE_PASSE = "mot-de-passe-suivi-fictif"


class Liens(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.hrefs = []
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs += [v for k, v in attrs if k == "href"]


def _liens(texte, chemin):
    return [x for x in Liens(texte).hrefs if urlsplit(x).path == "/opsys" + chemin]


def _client(installation):
    app = application.creer_application(Configuration(SECRET), installation, etat.session)
    return TestClient(app, base_url="https://testserver/opsys")


def _connecter(client):
    r = client.post("/connexion", data={"identifiant": b.PROPRIO.personne, "mot_de_passe": MOT_DE_PASSE},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    r = client.get("/api/session")
    assert r.status_code == 200 and r.json()["utilisateur"] == b.PROPRIO.personne


def _obtenir(client, **parametres):
    return client.get("/strategie", params={"horodatage_reference": REFERENCE} | parametres)


def test_console_liste_suivis_ouverts_et_detail_preuve_reelle_sans_effet(installation):
    cap, ids, alerte = h._preparer(installation, 3)
    h._clore(cap, ids[0], alerte)
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        r = _obtenir(client)
        assert r.status_code == 200, "M9_CONSOLE_SUIVIS_ROUTE_ABSENTE: " + r.text
        liens = _liens(r.text, "/strategie/suivi")
        assert [parse_qs(urlsplit(x).query)["suivi_id"][0] for x in liens] == [ids[1], ids[2]]
        assert "EN_RETARD" in r.text and "A_ECHEANCE" in r.text
        assert ids[0] not in r.text
        for ident in [ids[1], ids[2]]:
            detail = client.get("/strategie/suivi", params={"suivi_id": ident})
            assert detail.status_code == 200, detail.text
            texte = html.unescape(detail.text)
            assert ident in texte and alerte["evenement_id"] in texte
            plan = next(p for p in b._suivis() if p["suivi_id"] == ident)
            assert plan["action"] in texte and plan["echeance"] in texte
            assert b.RESPONSABLE in texte
        cloture = client.get("/strategie/suivi", params={"suivi_id": ids[0]})
        assert cloture.status_code == 200 and "cloturee_par_revue_humaine" in cloture.text
        assert b._tables() == avant
        assert r.headers["cache-control"] == "no-store"
        assert "default-src 'none'" in r.headers["content-security-policy"]


def test_formulaire_sans_reference_et_navigation_ne_fabriquent_aucune_date(installation):
    h._preparer(installation, 1)
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        r = client.get("/strategie")
        assert r.status_code == 200 and 'name="horodatage_reference"' in r.text
        assert REFERENCE not in r.text
        assert _liens(client.get("/departements").text, "/strategie")
        assert b._tables() == avant


def test_pagination_http_conserve_reference_vue_et_refuse_reprise_apres_cloture(installation, monkeypatch):
    cap, ids, alerte = h._preparer(installation, 4)
    import m9_strategic_intelligence.outils as outils
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 3800)
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        r = _obtenir(client)
        assert r.status_code == 200, r.text
        reprises = [x for x in _liens(r.text, "/strategie") if "depart=" in x]
        assert len(reprises) == 1
        params = parse_qs(urlsplit(reprises[0]).query)
        assert params["horodatage_reference"] == [REFERENCE]
        assert int(params["depart"][0]) > 0 and len(params["vue_attendue"][0]) == 64
        seconde = client.get("https://testserver" + reprises[0])
        assert seconde.status_code == 200, seconde.text
        premiers = {parse_qs(urlsplit(x).query)["suivi_id"][0] for x in _liens(r.text, "/strategie/suivi")}
        suivants = {parse_qs(urlsplit(x).query)["suivi_id"][0] for x in _liens(seconde.text, "/strategie/suivi")}
        assert premiers and suivants and not premiers.intersection(suivants)
        assert b._tables() == avant
        h._clore(cap, ids[-1], alerte)
        avant = b._tables()
        perimee = client.get("https://testserver" + reprises[0])
        assert perimee.status_code == 409, perimee.text
        recommencer = [x for x in _liens(perimee.text, "/strategie") if "horodatage_reference=" in x]
        assert recommencer and all("depart=" not in x and "vue_attendue=" not in x for x in recommencer)
        assert b._tables() == avant


@pytest.mark.parametrize("role_restant", ["nathan_owner", "employee", "aucun"])
def test_ancien_cookie_refuse_apres_retrait_sql_admin(installation, role_restant):
    _, ids, _ = h._preparer(installation, 1)
    with _client(installation) as client:
        _connecter(client)
        assert _obtenir(client).status_code == 200
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, b.PROPRIO.personne, "admin")
            if role_restant != "nathan_owner":
                identite.retirer_role(cnx, b.PROPRIO.personne, "nathan_owner")
            if role_restant == "employee":
                identite.ajouter_role(cnx, b.PROPRIO.personne, "employee")
        avant = b._tables()
        assert _obtenir(client).status_code == 403
        assert client.get("/strategie/suivi", params={"suivi_id": ids[0]}).status_code == 403
        assert b._tables() == avant


def test_admin_sans_role_proprietaire_peut_consulter(installation):
    h._preparer(installation, 1)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, b.PROPRIO.personne, "nathan_owner")
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        assert _obtenir(client).status_code == 200
        assert b._tables() == avant


@pytest.mark.parametrize("chemin", ["/strategie", "/strategie?depart=invalide", "/strategie/suivi?suivi_id=fictif"])
def test_absence_session_redirige_avant_lecture(installation, chemin):
    h._preparer(installation, 1)
    avant = b._tables()
    with _client(installation) as client:
        r = client.get(chemin, follow_redirects=False)
        assert r.status_code == 303 and "/connexion" in r.headers["location"], r.text
    assert b._tables() == avant


@pytest.mark.parametrize("parametres", [
    [("horodatage_reference", REFERENCE), ("horodatage_reference", REFERENCE)],
    [("horodatage_reference", REFERENCE), ("invente", "fictif")],
    {"horodatage_reference": "2026-10-20T13:00:00"},
    {"horodatage_reference": "illisible"},
    {"horodatage_reference": REFERENCE, "depart": "true"},
    {"horodatage_reference": REFERENCE, "depart": "-1"},
    {"horodatage_reference": REFERENCE, "depart": "1"},
    {"horodatage_reference": REFERENCE, "depart": "1", "vue_attendue": "0" * 64},
])
def test_parametres_refuses_sans_effet(installation, parametres):
    h._preparer(installation, 1)
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        r = client.get("/strategie", params=parametres)
        assert r.status_code in {400, 409}, r.text
        assert b._tables() == avant


def test_texte_metier_est_echappe_en_liste_et_detail(installation):
    action = 'Revue fictive <script>alert("fictif")</script>'
    cap, _, ident, _ = b._proposer(installation, action=action)
    assert b._decider(cap, ident, "ouvrir-xss-fictif")["resultat"]["resultat"]["statut"] == "executee"
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        for r in [_obtenir(client), client.get("/strategie/suivi", params={"suivi_id": ident})]:
            assert r.status_code == 200, r.text
            assert "<script>" not in r.text and "&lt;script&gt;" in r.text
            assert action in html.unescape(r.text)
        assert b._tables() == avant


def test_detail_absent_et_aucune_mutation_http(installation):
    h._preparer(installation, 1)
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        assert client.get("/strategie/suivi", params={"suivi_id": "suivi-fictif-absent"}).status_code == 404
        assert client.post("/strategie", data={"action": "ne pas executer"}).status_code == 405
        assert b._tables() == avant


def test_pagination_http_complete_sur_plus_de_deux_pages_sans_cycle(installation, monkeypatch):
    _, ids, _ = h._preparer(installation, 9)
    import m9_strategic_intelligence.outils as outils
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 3800)
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        r = _obtenir(client)
        tous, visites, vues = [], set(), set()
        pages_parcourues = 0
        while True:
            assert r.status_code == 200, r.text
            pages_parcourues += 1
            assert pages_parcourues <= len(ids)
            courants = [parse_qs(urlsplit(x).query)["suivi_id"][0]
                        for x in _liens(r.text, "/strategie/suivi")]
            assert courants and not set(courants).intersection(tous)
            tous.extend(courants)
            suites = [x for x in _liens(r.text, "/strategie") if "depart=" in x]
            if not suites:
                break
            assert len(suites) == 1 and suites[0] not in visites
            visites.add(suites[0])
            params = parse_qs(urlsplit(suites[0]).query)
            assert params["horodatage_reference"] == [REFERENCE]
            assert int(params["depart"][0]) == len(tous)
            vues.add(params["vue_attendue"][0])
            assert len(vues) == 1
            r = client.get("https://testserver" + suites[0])
        assert pages_parcourues >= 3
        assert len(tous) == len(set(tous)) == len(ids) and set(tous) == set(ids)
        assert b._tables() == avant


class Cellules(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.lignes, self.ligne, self.cellule = [], None, None
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.ligne = []
        elif tag in {"th", "td"} and self.ligne is not None:
            self.cellule = []

    def handle_data(self, data):
        if self.cellule is not None:
            self.cellule.append(data)

    def handle_endtag(self, tag):
        if tag in {"th", "td"} and self.cellule is not None:
            self.ligne.append("".join(self.cellule))
            self.cellule = None
        elif tag == "tr" and self.ligne is not None:
            self.lignes.append(self.ligne)
            self.ligne = None


@pytest.mark.parametrize("colonne,attendu", [(2, b.RESPONSABLE), (4, "EN_RETARD")])
def test_colonnes_nominales_responsable_et_statut_fournis_par_m9(installation, colonne, attendu):
    _, ids, _ = h._preparer(installation, 3)
    with _client(installation) as client:
        _connecter(client)
        avant = b._tables()
        r = _obtenir(client)
        assert r.status_code == 200, r.text
        ligne = next(row for row in Cellules(r.text).lignes if row[0] == ids[1])
        assert ligne[colonne] == attendu, "M9_CONSOLE_CHAMP_NOMINAL_ABSENT"
        assert b._tables() == avant
