"""Rapport de période FICTIF : vraie console, approbations, bus M8 et SQLite ; aucun effet terrain."""
from __future__ import annotations

import html
import importlib.util
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from opsys import identite, stockage

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_console_rapport_bilan", Path(__file__).with_name("test_console_bilan_suivis_m9.py")
)
p = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p)
_spec_m8 = importlib.util.spec_from_file_location(
    "_console_rapport_m8", RACINE / "departments/m09-strategic-intelligence/tests/test_rapport_periode.py"
)
w = importlib.util.module_from_spec(_spec_m8)
_spec_m8.loader.exec_module(w)
c, b = p.c, p.b
installation = p.installation
ROUTE = "/strategie/rapport"


def test_http_rapport_apres_3_plans_2_clotures_et_vraie_alerte_m8(installation, monkeypatch):
    cap, _, _, _ = p._historique(installation, monkeypatch)
    alerte = w._recevoir_alerte_fictive(installation, "2026-10-06T12:00:00Z", "-rapport-http")
    natif = w._rapport(cap)
    assert natif["suivis"]["compteurs"] == p.COMPTEURS
    assert natif["alertes_periode"]["alertes"] == [alerte]
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        r = client.get(ROUTE, params={"debut": p.DEBUT, "fin": p.FIN})
        assert r.status_code == 200, "M9_RAPPORT_HTTP_ABSENT_APRES_3_PLANS_2_CLOTURES_ET_M8_REELS: " + r.text
        texte = html.unescape(r.text)
        assert "Synthèse de période" in texte
        assert natif["suivis"]["total"] == 2
        assert p.Rendu(r.text).compteurs == p.COMPTEURS | {"suivis_total": 2, "alertes_total": 1}
        assert alerte["evenement_id"] in texte and alerte["preuve"]["wct_id"] in texte
        assert alerte["horodatage_reference"] in texte
        assert "connues à la lecture" in texte and "NON_COUVERT" in texte
        visible = " ".join(HorsDetails(r.text).textes)
        assert "NON_VALIDE" in visible and "NON_EVALUEE" in visible
        for manque in natif["manques"]:
            assert manque["constat"] in visible and manque["verifie"] in visible
        assert p.FUTUR not in texte
        assert b._tables() == avant
        assert r.headers["cache-control"] == "no-store"
        assert "default-src 'none'" in r.headers["content-security-policy"]


class Alertes(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.courante = None
        self.alertes = {}
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        valeurs = dict(attrs)
        if tag == "article" and "data-evenement-id" in valeurs:
            self.courante = valeurs["data-evenement-id"]
            assert self.courante not in self.alertes
            self.alertes[self.courante] = {"metric_id": valeurs.get("data-metric-id"), "textes": []}

    def handle_data(self, data):
        if self.courante is not None:
            self.alertes[self.courante]["textes"].append(data)

    def handle_endtag(self, tag):
        if tag == "article":
            self.courante = None



class HorsDetails(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.details = 0
        self.textes = []
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.details += 1

    def handle_endtag(self, tag):
        if tag == "details":
            self.details -= 1

    def handle_data(self, data):
        if self.details == 0:
            self.textes.append(data)

def _suivants(texte):
    return [lien for lien in c._liens(texte, ROUTE) if "depart" in parse_qs(urlsplit(lien).query)]


def _alertes_reelles(installation, nombre=8):
    return [w._recevoir_alerte_fictive(installation, f"2026-10-06T12:00:{i:02d}Z", "-http-page-" + str(i))
            for i in range(nombre)]


def test_pagination_huit_alertes_preuve_du_bon_chantier_et_compteurs_globaux(installation, monkeypatch):
    cap, _, _, _ = p._historique(installation, monkeypatch)
    alertes = _alertes_reelles(installation)
    import m9_strategic_intelligence.outils as outils
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 3800)
    natif = w._rapport(cap)
    assert natif["suivis"]["total"] == 2 and natif["alertes_periode"]["total"] == 8
    assert natif["alertes_periode"]["prochain_depart"] is not None
    attendues = {a["evenement_id"]: a for a in alertes}
    assert len({a["preuve"]["wct_id"] for a in alertes}) == 8
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        r = client.get(ROUTE, params={"debut": p.DEBUT, "fin": p.FIN})
        ids, visites, pages = [], set(), 0
        while True:
            assert r.status_code == 200, r.text
            pages += 1
            assert p.Rendu(r.text).compteurs == p.COMPTEURS | {"suivis_total": 2, "alertes_total": 8}
            assert not p.Rendu(r.text).ids
            blocs = Alertes(r.text).alertes
            ids.extend(blocs)
            for ident, bloc in blocs.items():
                attendu = attendues[ident]
                texte = " ".join(bloc["textes"])
                assert bloc["metric_id"] == attendu["metric_id"]
                for valeur in [ident, attendu["metric_id"], attendu["horodatage_reference"],
                               attendu["preuve"]["wct_id"], attendu["preuve"]["valeur"]]:
                    assert valeur in texte
                assert all(a["preuve"]["wct_id"] not in texte for a in alertes if a["evenement_id"] != ident)
            suivant = _suivants(r.text)
            assert len(suivant) <= 1 and not c._liens(r.text, "/strategie/suivi")
            assert p.FUTUR not in r.text and "NON_COUVERT" in r.text
            if not suivant:
                break
            assert suivant[0] not in visites
            visites.add(suivant[0])
            args = parse_qs(urlsplit(suivant[0]).query)
            assert args["debut"] == [p.DEBUT] and args["fin"] == [p.FIN]
            assert int(args["depart"][0]) == len(ids)
            r = client.get("https://testserver" + suivant[0])
        assert pages >= 2 and len(ids) == len(set(ids)) == 8
        assert ids == [a["evenement_id"] for a in reversed(alertes)]
        assert b._tables() == avant


@pytest.mark.parametrize("mutation", ["cloture", "alerte_tardive"])
def test_reprise_perimee_refusee_et_redemarrage_meme_periode(installation, monkeypatch, mutation):
    p._date(monkeypatch, "2026-10-06T09:00:00Z")
    cap, ids, alerte = p.s._preparer(installation, 2)
    _alertes_reelles(installation, 8)
    import m9_strategic_intelligence.outils as outils
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 3800)
    with c._client(installation) as client:
        c._connecter(client)
        premier = client.get(ROUTE, params={"debut": p.DEBUT, "fin": p.FIN})
        assert premier.status_code == 200
        [suivant] = _suivants(premier.text)
        if mutation == "cloture":
            p._date(monkeypatch, "2026-10-08T12:00:00Z")
            p._clore(cap, ids[0], alerte, "Revue humaine fictive dans la période, sans action terrain")
        else:
            w._recevoir_alerte_fictive(installation, "2026-10-07T11:00:00Z", "-http-tardive")
        avant = b._tables()
        r = client.get("https://testserver" + suivant)
        assert r.status_code == 409 and not Alertes(r.text).alertes and not p.Rendu(r.text).compteurs
        assert "REJ-RAPPORT-VUE-PERIMEE" in r.text
        liens = c._liens(r.text, ROUTE)
        assert len(liens) == 1 and parse_qs(urlsplit(liens[0]).query) == {"debut": [p.DEBUT], "fin": [p.FIN]}
        repris = client.get("https://testserver" + liens[0])
        assert repris.status_code == 200
        compteurs = p.Rendu(repris.text).compteurs
        assert compteurs["alertes_total"] == (9 if mutation == "alerte_tardive" else 8)
        assert compteurs["clotures_periode"] == (1 if mutation == "cloture" else 0)
        assert b._tables() == avant


def test_bornes_mixtes_fraction_et_plus_conservees_dans_reprise(installation, monkeypatch):
    _alertes_reelles(installation)
    import m9_strategic_intelligence.outils as outils
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 2600)
    debut, fin = "2026-10-05T00:00:00.500000+02:00", "2026-10-12T00:00:00-04:00"
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        r = client.get(ROUTE, params={"debut": debut, "fin": fin})
        assert r.status_code == 200, r.text
        [suivant] = _suivants(r.text)
        assert "%2B02%3A00" in suivant
        args = parse_qs(urlsplit(suivant).query)
        assert args["debut"] == [debut] and args["fin"] == [fin]
        r = client.get("https://testserver" + suivant)
        assert r.status_code == 200, r.text
        assert p.Rendu(r.text).inputs["debut"] == debut and p.Rendu(r.text).inputs["fin"] == fin
        assert b._tables() == avant


@pytest.mark.parametrize("roles", ["admin_seul", "owner_seul", "admin_retire_apres_cookie"])
def test_role_sql_courant_avant_formulaire_et_lecture(installation, monkeypatch, roles):
    p._date(monkeypatch, p.DEBUT)
    p.s._preparer(installation, 1)
    with c._client(installation) as client:
        if roles != "owner_seul":
            c._connecter(client)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, b.PROPRIO.personne, "nathan_owner" if roles == "admin_seul" else "admin")
        if roles == "owner_seul":
            c._connecter(client)
        avant = b._tables()
        if roles != "admin_seul":
            def interdit(*args, **kwargs):
                raise AssertionError("LECTURE_PRIVEE_AVANT_GARDE_ADMIN_FICTIF")
            monkeypatch.setattr(stockage, "maillons", interdit)
        for params in [{}, {"debut": p.DEBUT, "fin": p.FIN}]:
            r = client.get(ROUTE, params=params)
            assert r.status_code == (200 if roles == "admin_seul" else 403), r.text
            if roles != "admin_seul":
                assert not p.Rendu(r.text).compteurs and not Alertes(r.text).alertes
        assert b._tables() == avant


def test_formulaire_vide_anonyme_et_navigation_sans_horloge(installation, monkeypatch):
    p._date(monkeypatch, p.DEBUT)
    p.s._preparer(installation, 1)
    with c._client(installation) as client:
        avant = b._tables()
        r = client.get(ROUTE, params={"depart": "invalide", "inconnu": "x"}, follow_redirects=False)
        assert r.status_code == 303 and "/connexion" in r.headers["location"]
        c._connecter(client)
        r = client.get(ROUTE)
        assert r.status_code == 200 and not Alertes(r.text).alertes and not p.Rendu(r.text).compteurs
        assert p.Rendu(r.text).inputs["debut"] == p.Rendu(r.text).inputs["fin"] == ""
        assert p.DEBUT not in r.text and p.FIN not in r.text
        assert c._liens(client.get("/strategie").text, ROUTE)
        assert b._tables() == avant


@pytest.mark.parametrize("params", [
    {"debut": p.DEBUT}, {"fin": p.FIN}, {"debut": "2026-10-05", "fin": p.FIN},
    {"debut": p.DEBUT, "fin": "2026-10-12T00:00:00"},
    {"debut": "2026-10-12T00:00:00+00:00", "fin": "2026-10-11T20:00:00-04:00"},
    {"debut": p.FIN, "fin": p.DEBUT}, {"debut": p.DEBUT, "fin": p.FIN, "inconnu": "x"},
    [("debut", p.DEBUT), ("debut", p.DEBUT), ("fin", p.FIN)],
    {"debut": p.DEBUT, "fin": p.FIN, "depart": "-1"},
    {"debut": p.DEBUT, "fin": p.FIN, "depart": "true"},
    {"debut": p.DEBUT, "fin": p.FIN, "depart": "1"},
    {"debut": p.DEBUT, "fin": p.FIN, "depart": "1", "vue_attendue": '\"><script>x</script>'},
])
def test_requete_invalide_et_aucun_post_ni_effet(installation, monkeypatch, params):
    p._date(monkeypatch, p.DEBUT)
    p.s._preparer(installation, 1)
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        r = client.get(ROUTE, params=params)
        assert r.status_code in {400, 409}, r.text
        assert not Alertes(r.text).alertes and not p.Rendu(r.text).compteurs
        assert "<script>" not in r.text
        assert client.post(ROUTE, data={"debut": p.DEBUT, "fin": p.FIN}).status_code in {404, 405}
        assert b._tables() == avant


def test_alerte_reelle_echappee_et_bornes_aux_instants(installation):
    suffixe = '-<script>alert("chantier-fictif")</script>'
    debut, fin = "2026-10-05T00:00:00-04:00", "2026-10-12T00:00:00-04:00"
    incluse = w._recevoir_alerte_fictive(installation, "2026-10-05T04:00:00Z", suffixe)
    exclue = w._recevoir_alerte_fictive(installation, "2026-10-12T04:00:00Z", "-fin-exclusive-http")
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        r = client.get(ROUTE, params={"debut": debut, "fin": fin})
        assert r.status_code == 200, r.text
        assert set(Alertes(r.text).alertes) == {incluse["evenement_id"]}
        assert exclue["evenement_id"] not in r.text
        assert "<script>" not in r.text and "&lt;script&gt;" in r.text
        assert incluse["preuve"]["wct_id"] in html.unescape(r.text)
        assert b._tables() == avant
