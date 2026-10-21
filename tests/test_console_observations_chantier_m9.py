"""Observations de chantier fictives : bus M8/M9 et HTTP natifs, sans effet terrain."""
from __future__ import annotations

import html
import importlib.util
import json
import re
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from opsys import identite, stockage

RACINE = Path(__file__).resolve().parents[1]

def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

o = _charger(
    "_console_observations_api",
    RACINE / "departments/m09-strategic-intelligence/tests/test_observations_chantier_periode.py",
)
c = _charger("_console_observations_sessions", Path(__file__).with_name("test_console_suivis_m9.py"))
installation = o.installation
ROUTE = "/strategie/observations"


def test_http_observations_apres_transport_wct_et_api_natife(installation):
    o._recevoir(installation)
    natif = o._lire(o.b._capacites(installation))
    assert natif["total"] == 1
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        r = client.get(ROUTE, params={"debut": o.DEBUT, "fin": o.FIN})
        assert r.status_code == 200, "M9_OBSERVATIONS_HTTP_ABSENT_APRES_WCT_BUS_ET_API_REELS: " + r.text
        texte = html.unescape(r.text)
        assert "Observations de chantier" in texte
        assert natif["observations"][0]["publication"]["evenement_id"] in texte
        assert "NON_PROUVEE" in texte and "source_bus_liee" in texte
        assert o.b._tables() == avant



class Rendu(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.compteurs, self.articles, self.inputs = {}, {}, {}
        self.courant = self.preuve = None
        self.details = 0
        self.visibles = []
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "details":
            self.details += 1
        if "data-compteur" in attrs:
            assert attrs["data-compteur"] not in self.compteurs
            valeur = attrs.get("data-valeur", "")
            assert valeur.isascii() and valeur.isdecimal(), attrs
            self.compteurs[attrs["data-compteur"]] = int(valeur)
        if tag == "input" and "name" in attrs:
            self.inputs[attrs["name"]] = attrs.get("value", "")
        if tag == "article" and "data-evenement-id" in attrs:
            self.courant = attrs["data-evenement-id"]
            assert self.courant not in self.articles
            self.articles[self.courant] = {"textes": [], "preuves": {}, "visibles": []}
        if tag == "pre" and self.courant is not None:
            self.preuve = attrs.get("data-preuve")
            assert self.preuve in {"maillon", "publication"}, attrs
            assert self.preuve not in self.articles[self.courant]["preuves"]
            self.articles[self.courant]["preuves"][self.preuve] = ""

    def handle_data(self, data):
        if not self.details:
            self.visibles.append(data)
        if self.courant is not None:
            self.articles[self.courant]["textes"].append(data)
            if not self.details:
                self.articles[self.courant]["visibles"].append(data)
            if self.preuve:
                self.articles[self.courant]["preuves"][self.preuve] += data

    def handle_endtag(self, tag):
        if tag == "details":
            self.details -= 1
        if tag == "pre":
            self.preuve = None
        if tag == "article":
            self.courant = None


def _get(client, **args):
    return client.get(ROUTE, params={"debut": o.DEBUT, "fin": o.FIN} | args)


def _suivants(texte):
    return [lien for lien in c._liens(texte, ROUTE) if "depart" in parse_qs(urlsplit(lien).query)]


def _plusieurs(installation, nombre=5):
    for n in range(nombre):
        o._recevoir(installation, suffixe="http-" + str(n), instant=f"2026-09-28T18:00:{n:02d}Z")


def test_originaux_complets_manques_visibles_securite_get_post_et_api_inchangee(installation, monkeypatch):
    o._recevoir(installation)
    cap = o.b._capacites(installation)
    o._ajouter_t1(cap, {"module_source": "generique-http-fictif", "horodatage": "1999-01-01T00:00:00Z",
                       "valeurs": {"etat": "fictif"}})
    natif = o._lire(cap)
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        from opsys.console import metier
        original = metier.executer
        appels = []
        def compter(*args, **kwargs):
            appels.append((args, kwargs))
            return original(*args, **kwargs)
        monkeypatch.setattr(metier, "executer", compter)
        r = _get(client)
        assert r.status_code == 200 and len(appels) == 1, r.text
        rendu = Rendu(r.text)
        assert rendu.compteurs == {"observations_total": 1, "generiques_non_couverts": 1,
                                   "observations_affichees": 1}
        [observation] = natif["observations"]
        bloc = rendu.articles[observation["publication"]["evenement_id"]]
        assert {k: json.loads(v) for k, v in bloc["preuves"].items()} == {
            "maillon": observation["maillon"], "publication": observation["publication"]}
        assert "source_bus_liee" in " ".join(bloc["visibles"])
        assert "NON_PROUVEE" in " ".join(bloc["visibles"])
        visible = " ".join(rendu.visibles)
        for mot in ("NON_VALIDE", "NON_EVALUEE", "NON_PROUVEE", "source_bus_liee"):
            assert mot in visible
        assert "connues à la lecture" in visible
        for manque in natif["manques"]:
            assert manque["constat"] in visible and manque["verifie"] in visible
        assert r.headers["cache-control"] == "no-store"
        assert "default-src 'none'" in r.headers["content-security-policy"]
        assert len(r.content) <= 128 * 1024
        assert client.post(ROUTE, data={"debut": o.DEBUT, "fin": o.FIN}).status_code == 405
        assert o.b._tables() == avant and o._lire(cap) == natif


def test_pages_plusieurs_wct_preuves_associees_bornes_et_vue_exactes(installation, monkeypatch):
    _plusieurs(installation)
    from m9_strategic_intelligence import outils
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 5000)
    debut, fin = "2026-09-27T20:00:00.000000-04:00", "2026-09-29T02:00:00+02:00"
    maillons, publications = o._sources()
    attendus = {m["valeurs"]["m8_snapshot_evenement_id"]: m for m in maillons}
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        r = _get(client, debut=debut, fin=fin)
        ids, liens_vus, vue, pages = [], set(), None, 0
        while True:
            assert r.status_code == 200, r.text
            pages += 1
            rendu = Rendu(r.text)
            assert rendu.compteurs == {"observations_total": 5, "generiques_non_couverts": 0,
                                       "observations_affichees": len(rendu.articles)}
            assert rendu.articles
            ids.extend(rendu.articles)
            for ident, bloc in rendu.articles.items():
                assert json.loads(bloc["preuves"]["maillon"]) == attendus[ident]
                assert json.loads(bloc["preuves"]["publication"]) == publications[ident]
            suivant = _suivants(r.text)
            assert len(suivant) <= 1
            if not suivant:
                break
            [lien] = suivant
            assert lien not in liens_vus
            liens_vus.add(lien)
            params = parse_qs(urlsplit(lien).query)
            assert params["debut"] == [debut] and params["fin"] == [fin]
            assert int(params["depart"][0]) == len(ids)
            assert re.fullmatch("[0-9a-f]{64}", params["vue_attendue"][0])
            vue = vue or params["vue_attendue"][0]
            assert params["vue_attendue"] == [vue]
            r = client.get("https://testserver" + lien)
        assert pages >= 2 and len(ids) == len(set(ids)) == 5
        assert set(ids) == set(attendus) and o.b._tables() == avant


@pytest.mark.parametrize("cause", ["arrivee_tardive", "generique_hors_periode"])
def test_vue_perimee_409_sans_ligne_et_redemarrage_meme_periode(installation, monkeypatch, cause):
    _plusieurs(installation)
    from m9_strategic_intelligence import outils
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 5000)
    with c._client(installation) as client:
        c._connecter(client)
        premier = _get(client)
        assert premier.status_code == 200, premier.text
        [suivant] = _suivants(premier.text)
        if cause == "arrivee_tardive":
            o._recevoir(installation, suffixe="http-tardif", instant="2026-09-28T12:00:00Z")
        else:
            o._ajouter_t1(o.b._capacites(installation), {
                "module_source": "generique-http-fictif", "horodatage": "1999-01-01T00:00:00Z",
                "valeurs": {"etat": "fictif"}})
        avant = o.b._tables()
        r = client.get("https://testserver" + suivant)
        assert r.status_code == 409 and not Rendu(r.text).articles
        assert not Rendu(r.text).compteurs
        reprises = [lien for lien in c._liens(r.text, ROUTE) if "debut" in parse_qs(urlsplit(lien).query)]
        assert len(reprises) == 1
        assert parse_qs(urlsplit(reprises[0]).query) == {"debut": [o.DEBUT], "fin": [o.FIN]}
        frais = client.get("https://testserver" + reprises[0])
        assert frais.status_code == 200, frais.text
        assert Rendu(frais.text).compteurs["observations_total"] == (6 if cause == "arrivee_tardive" else 5)
        assert o.b._tables() == avant


@pytest.mark.parametrize("params", [
    {"debut": o.DEBUT}, {"fin": o.FIN},
    {"debut": o.DEBUT, "fin": o.FIN, "inconnu": "x"},
    [("debut", o.DEBUT), ("debut", o.DEBUT), ("fin", o.FIN)],
    {"debut": o.DEBUT, "fin": o.FIN, "depart": "-1"},
    {"debut": o.DEBUT, "fin": o.FIN, "depart": "1.0"},
    {"debut": o.DEBUT, "fin": o.FIN, "depart": " 1"},
])
def test_requetes_invalides_400_sans_ligne_ni_mutation(installation, params):
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        r = client.get(ROUTE, params=params)
        assert r.status_code == 400, r.text
        assert not Rendu(r.text).articles and not Rendu(r.text).compteurs
        assert o.b._tables() == avant


@pytest.mark.parametrize("cause", ["employee", "owner_seul", "admin_revoque", "inactif"])
def test_session_sql_courante_avant_metier_meme_formulaire_vide(installation, monkeypatch, cause):
    from opsys.console import metier
    with c._client(installation) as client:
        if cause in {"admin_revoque", "inactif"}:
            c._connecter(client)
        with stockage.transaction() as cnx:
            if cause == "inactif":
                identite.activer(cnx, o.b.PROPRIO.personne, False)
            else:
                identite.retirer_role(cnx, o.b.PROPRIO.personne, "admin")
                if cause == "employee":
                    identite.retirer_role(cnx, o.b.PROPRIO.personne, "nathan_owner")
                    identite.ajouter_role(cnx, o.b.PROPRIO.personne, "employee")
        if cause in {"employee", "owner_seul"}:
            c._connecter(client)
        def interdit(*args, **kwargs):
            pytest.fail("Lecture métier ou registre avant contrôle de la session SQL courante")
        monkeypatch.setattr(metier, "executer", interdit)
        monkeypatch.setattr(stockage, "maillons", interdit)
        avant = o.b._tables()
        for params in ({}, {"debut": o.DEBUT, "fin": o.FIN}):
            r = client.get(ROUTE, params=params, follow_redirects=False)
            if cause == "inactif":
                assert r.status_code == 303 and "/connexion" in r.headers["location"]
            else:
                assert r.status_code == 403, r.text
            assert not Rendu(r.text).articles and not Rendu(r.text).compteurs
        assert o.b._tables() == avant


def test_anonyme_redirige_avant_parametres_invalides(installation):
    with c._client(installation) as client:
        avant = o.b._tables()
        r = client.get(ROUTE, params={"depart": "faux", "inconnu": "x"}, follow_redirects=False)
        assert r.status_code == 303 and "/connexion" in r.headers["location"]
        assert o.b._tables() == avant


def test_admin_sans_owner_peut_lire(installation):
    o._recevoir(installation)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, o.b.PROPRIO.personne, "nathan_owner")
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        assert _get(client).status_code == 200
        assert o.b._tables() == avant


def test_formulaire_vide_navigation_sans_date_ni_appel_metier(installation, monkeypatch):
    from opsys.console import metier
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        assert c._liens(client.get("/strategie").text, ROUTE)
        def interdit(*args, **kwargs):
            pytest.fail("Le formulaire vide ne doit ni lire les faits ni fabriquer une période")
        monkeypatch.setattr(metier, "executer", interdit)
        r = client.get(ROUTE)
        assert r.status_code == 200, r.text
        rendu = Rendu(r.text)
        assert rendu.inputs["debut"] == rendu.inputs["fin"] == ""
        assert not rendu.articles and not rendu.compteurs
        assert o.DEBUT not in r.text and o.FIN not in r.text and o.b._tables() == avant


def test_type_chantier_script_echappe_dans_texte_et_json(installation):
    hostile = '</pre><script>alert("chantier-fictif")</script><img src=x onerror=alert(1)>'
    o._recevoir(installation, type_travaux=hostile)
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        r = _get(client)
        assert r.status_code == 200, r.text
        assert "<script>" not in r.text and "<img src=x" not in r.text
        assert "&lt;script&gt;" in r.text
        [bloc] = Rendu(r.text).articles.values()
        assert json.loads(bloc["preuves"]["publication"])["snapshot"]["valeurs"]["m4_type_travaux"] == hostile
        assert o.b._tables() == avant


@pytest.mark.parametrize("cause", ["type", "compteur_bool", "ligne_incomplete", "prochain_absent"])
def test_reponse_native_malformee_409_aucune_ligne_partielle(installation, monkeypatch, cause):
    o._recevoir(installation)
    from opsys.console import metier
    original = metier.executer
    appels = []
    def corrompre(*args, **kwargs):
        appels.append((args, kwargs))
        reponse = deepcopy(original(*args, **kwargs))
        payload = reponse["resultat"]
        if cause == "type":
            payload["type"] = "FAUX_TYPE_FICTIF"
        elif cause == "compteur_bool":
            payload["total"] = True
        elif cause == "prochain_absent":
            del payload["prochain_depart"]
        else:
            payload["observations"].append({"nature": "source_bus_liee"})
        return reponse
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        monkeypatch.setattr(metier, "executer", corrompre)
        r = _get(client)
        assert r.status_code == 409 and len(appels) == 1, r.text
        assert not Rendu(r.text).articles and not Rendu(r.text).compteurs
        assert o.b._tables() == avant


@pytest.mark.parametrize("message", [
    "REJ-OBSERVATIONS-SOURCE : SECRET_FICTIF_NE_PAS_EXPOSER" + "x" * 5000,
    "backend-private SECRET_FICTIF_NE_PAS_EXPOSER <script>boom</script>",
])
def test_erreur_metier_n_expose_que_code_borne_sans_secret(installation, monkeypatch, caplog, message):
    from opsys.console import metier
    def lever(*args, **kwargs):
        raise ValueError(message)
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        monkeypatch.setattr(metier, "executer", lever)
        r = _get(client)
        assert r.status_code in {400, 409}, r.text
        assert "REJ-" in r.text and "SECRET_FICTIF_NE_PAS_EXPOSER" not in r.text
        assert "backend-private" not in r.text and "<script>" not in r.text
        assert "SECRET_FICTIF_NE_PAS_EXPOSER" not in caplog.text
        assert not Rendu(r.text).articles and not Rendu(r.text).compteurs
        assert len(r.content) <= 128 * 1024 and o.b._tables() == avant


def test_preuve_native_trop_grande_refuse_sans_ligne(installation):
    o._recevoir(installation, type_travaux="long-fictif-" * 600)
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        r = _get(client)
        assert r.status_code in {400, 409} and "REJ-OBSERVATIONS-BORNE" in r.text
        assert not Rendu(r.text).articles and not Rendu(r.text).compteurs
        assert o.b._tables() == avant


def test_html_entier_trop_grand_refuse_sans_troncature_ni_ligne(installation, monkeypatch):
    o._recevoir(installation)
    from opsys.console import metier
    original = metier.executer
    def agrandir(*args, **kwargs):
        # Défense du rendu isolée : le vrai lecteur refuse déjà cette taille de JSON.
        reponse = deepcopy(original(*args, **kwargs))
        [ligne] = reponse["resultat"]["observations"]
        for valeurs in (ligne["maillon"]["valeurs"], ligne["publication"]["snapshot"]["valeurs"]):
            valeurs["m4_type_travaux"] = "&" * 30_000
        return reponse
    with c._client(installation) as client:
        c._connecter(client)
        avant = o.b._tables()
        monkeypatch.setattr(metier, "executer", agrandir)
        r = _get(client)
        assert r.status_code == 409 and "aucune troncature" in r.text
        assert len(r.content) <= 128 * 1024
        assert not Rendu(r.text).articles and not Rendu(r.text).compteurs
        assert o.b._tables() == avant
