"""Rapport d'activité fictif, bus/approbations et HTTP natifs, sans effet terrain."""
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from opsys import approbations, contexte, evenements, identite, stockage


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

RACINE = Path(__file__).resolve().parents[1]
a = _charger(
    "_console_activite_api",
    RACINE / "departments/m09-strategic-intelligence/tests/test_rapport_activite_periode.py",
)
c = _charger("_console_activite_sessions", Path(__file__).with_name("test_console_suivis_m9.py"))
installation = a.installation
ROUTE = "/strategie/activite"


def test_http_activite_apres_trois_flux_natifs_approuves(installation, monkeypatch):
    cap, ids = a._jeu(installation, monkeypatch)
    natif = a._lire(cap)
    assert natif["compteurs"] == {"observations": 3, "alertes": 3, "suivis": 2,
                                  "ouverts_periode": 1, "clotures_periode": 1, "ouverts_fin": 1}
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        r = client.get(ROUTE, params={"debut": a.DEBUT, "fin": a.FIN})
        assert r.status_code == 200, "M9_ACTIVITE_HTTP_ABSENT_APRES_3FLUX_NATIFS: " + r.text
        assert "Rapport d’activité" in r.text or "Rapport d'activité" in r.text
        assert a.w.b._tables() == avant



class Rendu(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.compteurs, self.articles, self.inputs = {}, [], {}
        self.courant = None
        self.pre = False
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
        if tag == "article" and "data-ligne-rang" in attrs:
            assert attrs["data-ligne-rang"].isascii() and attrs["data-ligne-rang"].isdecimal()
            self.courant = {"section": attrs.get("data-section"),
                            "rang": int(attrs["data-ligne-rang"]), "preuves": [], "visibles": []}
            self.articles.append(self.courant)
        if tag == "pre" and self.courant is not None:
            assert attrs.get("data-preuve") == "originale", attrs
            self.courant["preuves"].append("")
            self.pre = True

    def handle_data(self, data):
        if not self.details:
            self.visibles.append(data)
            if self.courant is not None:
                self.courant["visibles"].append(data)
        if self.pre and self.courant is not None:
            self.courant["preuves"][-1] += data

    def handle_endtag(self, tag):
        if tag == "details":
            self.details -= 1
        if tag == "pre":
            self.pre = False
        if tag == "article":
            self.courant = None


def _get(client, **args):
    return client.get(ROUTE, params={"debut": a.DEBUT, "fin": a.FIN} | args)


def _suivants(texte):
    return [lien for lien in c._liens(texte, ROUTE) if "depart" in parse_qs(urlsplit(lien).query)]


def _aucun_fragment(r):
    rendu = Rendu(r.text)
    assert not rendu.articles and not rendu.compteurs
    assert "SECRET_FICTIF" not in r.text
    assert len(r.content) <= 128 * 1024


def test_toutes_pages_trois_flux_preuves_compteurs_et_appel_unique(installation, monkeypatch):
    cap, _ = a._jeu(installation, monkeypatch)
    a.o._ajouter_t1(cap, {"module_source": "generique-fictif", "horodatage": "1999-01-01T00:00:00Z",
                         "valeurs": {"etat": "fictif"}})
    debut, fin = "2026-10-04T20:00:00.000000-04:00", "2026-10-12T02:00:00+02:00"
    premiere, attendues = a._collecter(lambda **kw: a._lire(cap, debut=debut, fin=fin, **kw))
    from opsys.console import metier
    original = metier.executer
    reponses = []
    def compter(*args, **kwargs):
        resultat = original(*args, **kwargs)
        reponses.append(deepcopy(resultat["resultat"]))
        return resultat
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        monkeypatch.setattr(metier, "executer", compter)
        r = _get(client, debut=debut, fin=fin)
        lignes, vus, pages = [], set(), 0
        for _ in range(30):
            assert r.status_code == 200, r.text
            pages += 1
            assert len(reponses) == pages
            natif = reponses[-1]
            assert len(json.dumps(natif, ensure_ascii=False, allow_nan=False)) <= 5900
            assert len(r.content) <= 128 * 1024
            rendu = Rendu(r.text)
            assert rendu.compteurs == natif["compteurs"] | {
                "generiques_non_couverts": 1, "total": natif["total"], "affichees": natif["affichees"]}
            assert [bloc["rang"] for bloc in rendu.articles] == list(
                range(natif["depart"], natif["depart"] + natif["affichees"])
            )
            for bloc, ligne in zip(rendu.articles, natif["lignes"], strict=True):
                assert bloc["section"] == ligne["section"] and len(bloc["preuves"]) == 1
                preuve = json.loads(bloc["preuves"][0])
                assert preuve == ligne["preuve"]
                lignes.append({"section": bloc["section"], "preuve": preuve})
            visible = " ".join(rendu.visibles)
            for statut in ("NON_VALIDE", "NON_EVALUEE"):
                assert statut in visible
            for base in natif["bases_temporelles"].values():
                assert base in visible
            for manque in natif["manques"]:
                assert manque["constat"] in visible and manque["verifie"] in visible
            assert r.headers["cache-control"] == "no-store"
            assert "default-src 'none'" in r.headers["content-security-policy"]
            suivants = _suivants(r.text)
            assert len(suivants) <= 1
            if natif["prochain_depart"] is None:
                assert not suivants
                break
            [lien] = suivants
            assert lien not in vus
            vus.add(lien)
            params = parse_qs(urlsplit(lien).query)
            assert params == {"debut": [debut], "fin": [fin], "depart": [str(natif["prochain_depart"])],
                              "vue_attendue": [natif["vue"]]}
            r = client.get("https://testserver" + lien)
        else:
            pytest.fail("Pagination HTTP sans terminaison sur fixture finie")
        assert pages >= 2 and lignes == attendues
        assert client.post(ROUTE, data={"debut": debut, "fin": fin}).status_code == 405
        assert a.w.b._tables() == avant
        assert a._lire(cap, debut=debut, fin=fin) == premiere


@pytest.mark.parametrize("mutation", ["arrivee_tardive", "generique_hors_periode", "cloture_a_fin"])
def test_vue_perimee_et_cloture_a_fin_absente_du_rapport(installation, monkeypatch, mutation):
    if mutation == "cloture_a_fin":
        monkeypatch.setattr(approbations, "_maintenant", lambda: "2026-10-06T09:00:00Z")
        cap, ids, alerte = a.w.p.s._preparer(installation, 1)
    else:
        cap, _ = a._jeu(installation, monkeypatch)
    with c._client(installation) as client:
        c._connecter(client)
        initial = a._lire(cap)
        premier = _get(client)
        assert premier.status_code == 200, premier.text
        if mutation == "arrivee_tardive":
            a.w._recevoir_alerte_fictive(installation, "2026-10-07T12:00:00Z", "-http-activite-tardive")
        elif mutation == "generique_hors_periode":
            a.o._ajouter_t1(cap, {"module_source": "generique-fictif", "horodatage": "1999-01-01T00:00:00Z",
                                 "valeurs": {"etat": "fictif"}})
        else:
            monkeypatch.setattr(approbations, "_maintenant", lambda: a.FIN)
            a.w.p.s._clore(cap, ids[0], alerte)
        avant = a.w.b._tables()
        r = _get(client, vue_attendue=initial["vue"])
        assert r.status_code == 409, r.text
        _aucun_fragment(r)
        reprises = [lien for lien in c._liens(r.text, ROUTE) if "debut" in parse_qs(urlsplit(lien).query)]
        assert len(reprises) == 1
        assert parse_qs(urlsplit(reprises[0]).query) == {"debut": [a.DEBUT], "fin": [a.FIN]}
        reprise = client.get("https://testserver" + reprises[0])
        assert reprise.status_code == 200, reprise.text
        if mutation == "cloture_a_fin":
            apres, lignes = a._collecter(lambda **kw: a._lire(cap, **kw))
            assert apres["compteurs"]["ouverts_fin"] == initial["compteurs"]["ouverts_fin"]
            [suivi] = [ligne["preuve"] for ligne in lignes if ligne["section"] == "suivis"]
            assert "cloture" not in suivi and suivi["ouvert_fin"] is True
            [bloc] = [bloc for bloc in Rendu(reprise.text).articles if bloc["section"] == "suivis"]
            preuve_http = json.loads(bloc["preuves"][0])
            assert preuve_http == suivi and "cloture" not in preuve_http
        assert a.w.b._tables() == avant


@pytest.mark.parametrize("params", [
    {"debut": a.DEBUT}, {"fin": a.FIN},
    {"debut": a.DEBUT, "fin": a.FIN, "inconnu": "x"},
    [("debut", a.DEBUT), ("debut", a.DEBUT), ("fin", a.FIN)],
    {"debut": a.DEBUT, "fin": a.FIN, "depart": "true"},
    {"debut": a.DEBUT, "fin": a.FIN, "depart": "+1"},
    {"debut": "x" * 20000, "fin": a.FIN},
])
def test_parametres_http_refuses_sans_preuve(installation, params):
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        r = client.get(ROUTE, params=params)
        assert r.status_code == 400, r.text
        _aucun_fragment(r)
        assert a.w.b._tables() == avant


@pytest.mark.parametrize("cause", ["employee", "owner_seul", "admin_revoque", "inactif"])
def test_role_sql_courant_avant_lecture_et_formulaire(installation, monkeypatch, cause):
    from opsys.console import metier
    with c._client(installation) as client:
        if cause in {"admin_revoque", "inactif"}:
            c._connecter(client)
        with stockage.transaction() as cnx:
            if cause == "inactif":
                identite.activer(cnx, a.w.b.PROPRIO.personne, False)
            else:
                identite.retirer_role(cnx, a.w.b.PROPRIO.personne, "admin")
                if cause == "employee":
                    identite.retirer_role(cnx, a.w.b.PROPRIO.personne, "nathan_owner")
                    identite.ajouter_role(cnx, a.w.b.PROPRIO.personne, "employee")
        if cause in {"employee", "owner_seul"}:
            c._connecter(client)
        def interdit(*args, **kwargs):
            pytest.fail("Lecture métier/bus avant contrôle SQL de session")
        monkeypatch.setattr(metier, "executer", interdit)
        monkeypatch.setattr(stockage, "maillons", interdit)
        monkeypatch.setattr(evenements, "charge_publiee", interdit)
        avant = a.w.b._tables()
        for params in ({}, {"debut": a.DEBUT, "fin": a.FIN}, {"inconnu": "x"}):
            r = client.get(ROUTE, params=params, follow_redirects=False)
            if cause == "inactif":
                assert r.status_code == 303 and "/connexion" in r.headers["location"]
            else:
                assert r.status_code == 403, r.text
            _aucun_fragment(r)
        assert a.w.b._tables() == avant


def test_anonyme_et_formulaire_vide_sans_date_ni_appel_metier(installation, monkeypatch):
    from opsys.console import metier
    with c._client(installation) as client:
        avant = a.w.b._tables()
        r = client.get(ROUTE, params={"inconnu": "x"}, follow_redirects=False)
        assert r.status_code == 303 and "/connexion" in r.headers["location"]
        c._connecter(client)
        assert c._liens(client.get("/strategie").text, ROUTE)
        def interdit(*args, **kwargs):
            pytest.fail("Le formulaire vide ne doit effectuer aucune lecture métier")
        monkeypatch.setattr(metier, "executer", interdit)
        r = client.get(ROUTE)
        assert r.status_code == 200, r.text
        rendu = Rendu(r.text)
        assert rendu.inputs["debut"] == rendu.inputs["fin"] == ""
        assert a.DEBUT not in r.text and a.FIN not in r.text
        assert not rendu.articles and not rendu.compteurs
        assert a.w.b._tables() == avant


def test_xss_chantier_echappe_sans_modifier_preuve_originale(installation):
    hostile = '</pre><script>alert("fictif")</script><img src=x onerror=alert(1)>'
    a.o._recevoir(installation, instant="2026-10-06T12:00:00Z", type_travaux=hostile)
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        r = _get(client)
        assert r.status_code == 200, r.text
        assert "<script>" not in r.text and "<img src=x" not in r.text and "&lt;script&gt;" in r.text
        [bloc] = Rendu(r.text).articles
        preuve = json.loads(bloc["preuves"][0])
        assert preuve["publication"]["snapshot"]["valeurs"]["m4_type_travaux"] == hostile
        assert a.w.b._tables() == avant


@pytest.mark.parametrize("cause", [
    "prochain_absent", "type", "compteur_bool", "section_inconnue", "preuve_none",
    "bases_absentes", "nan", "compteurs_discordants", "fin_discordante", "json_trop_grand",
])
def test_reponse_native_malformee_refuse_toute_page_y_compris_terminale(installation, monkeypatch, cause):
    a.o._recevoir(installation, instant="2026-10-06T12:00:00Z")
    from opsys.console import metier
    original = metier.executer
    appels = []
    def corrompre(*args, **kwargs):
        reponse = deepcopy(original(*args, **kwargs))
        payload = reponse["resultat"]
        assert payload["prochain_depart"] is None and payload["lignes"]
        appels.append(1)
        if cause == "prochain_absent":
            del payload["prochain_depart"]
        elif cause == "type":
            payload["type"] = "SECRET_FICTIF_TYPE"
        elif cause == "compteur_bool":
            payload["compteurs"]["observations"] = True
        elif cause == "section_inconnue":
            payload["lignes"][-1]["section"] = "SECRET_FICTIF_SECTION"
        elif cause == "preuve_none":
            payload["lignes"][-1]["preuve"] = None
        elif cause == "bases_absentes":
            del payload["bases_temporelles"]
        elif cause == "nan":
            payload["lignes"][-1]["preuve"]["SECRET_FICTIF_NAN"] = float("nan")
        elif cause == "compteurs_discordants":
            payload["compteurs"]["observations"] += 1
        elif cause == "json_trop_grand":
            payload["ordre"] = "SECRET_FICTIF" + "x" * 6000
        else:
            payload["fin"] = "2026-10-13T00:00:00Z"
        return reponse
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        monkeypatch.setattr(metier, "executer", corrompre)
        r = _get(client)
        assert r.status_code == 409 and len(appels) == 1, r.text
        _aucun_fragment(r)
        assert a.w.b._tables() == avant


def test_preuve_native_trop_grande_refuse_sans_fragment(installation):
    a.o._recevoir(installation, instant="2026-10-06T12:00:00Z", type_travaux="preuve-fictive-" * 700)
    cap = a.w.b._capacites(installation)
    with contexte.appele_par_appareil(a.w.b.PROPRIO):
        natif = cap.appeler(a.NOM, {"debut": a.DEBUT, "fin": a.FIN})
    assert natif["ok"] is False and "REJ-OBSERVATIONS-BORNE" in json.dumps(natif)
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        r = _get(client)
        assert r.status_code == 409, r.text
        _aucun_fragment(r)
        assert a.w.b._tables() == avant


def test_defense_html128k_isolee_ne_releve_pas_budget_metier(installation, monkeypatch):
    # Défense de rendu isolée : sources et budget natifs inchangés, seul le gabarit est gonflé.
    a.o._recevoir(installation, instant="2026-10-06T12:00:00Z")
    from opsys.console import pages
    original = pages.gabarit
    appels = []
    def gonfler(*args, **kwargs):
        rendu = original(*args, **kwargs)
        if "data-ligne-rang" in rendu:
            appels.append(1)
            return rendu + "<!--SECRET_FICTIF_FRAGMENT-->" + "x" * (140 * 1024)
        return rendu
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        monkeypatch.setattr(pages, "gabarit", gonfler)
        r = _get(client)
        assert r.status_code == 409 and appels == [1], r.text
        _aucun_fragment(r)
        assert a.w.b._tables() == avant


@pytest.mark.parametrize("message", [
    "REJ-ACTIVITE-SOURCE : SECRET_FICTIF" + "x" * 5000,
    "backend SECRET_FICTIF <script>fictif</script>",
])
def test_erreur_sans_secret_uniquement_code_rej_borne(installation, monkeypatch, caplog, message):
    from opsys.console import metier
    def lever(*args, **kwargs):
        raise ValueError(message)
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        monkeypatch.setattr(metier, "executer", lever)
        r = _get(client)
        assert r.status_code in {400, 409} and "REJ-" in r.text
        _aucun_fragment(r)
        assert "SECRET_FICTIF" not in caplog.text and "<script>" not in r.text
        assert a.w.b._tables() == avant


@pytest.mark.parametrize("rang", [0, 1])
def test_symphony794_section_valide_au_mauvais_rang_global_refuse(installation, monkeypatch, rang):
    cap = a.w.b._capacites(installation)
    a.w._recevoir_alerte_fictive(installation, "2026-10-06T12:00:00Z", "-frontiere-section-http")
    native, lignes = a._collecter(lambda **kw: a._lire(cap, **kw))
    assert native["compteurs"] == {"observations": 1, "alertes": 1, "suivis": 0,
                                   "ouverts_periode": 0, "clotures_periode": 0, "ouverts_fin": 0}
    assert [ligne["section"] for ligne in lignes] == ["observations", "alertes"]
    from opsys.console import metier
    original = metier.executer
    appels = []
    def corrompre(*args, **kwargs):
        reponse = deepcopy(original(*args, **kwargs))
        payload = reponse["resultat"]
        appels.append(1)
        # Une preuve native complète de section valide, déplacée dans l'autre intervalle global.
        payload["lignes"] = [deepcopy(lignes[1 - rang])]
        payload["affichees"] = 1
        payload["reste"] = 1 - rang
        payload["prochain_depart"] = 1 if rang == 0 else None
        assert payload["depart"] == rang and payload["total"] == 2
        assert len(json.dumps(payload, ensure_ascii=False, allow_nan=False)) <= 5900
        return reponse
    with c._client(installation) as client:
        c._connecter(client)
        avant = a.w.b._tables()
        monkeypatch.setattr(metier, "executer", corrompre)
        r = _get(client, depart=rang, vue_attendue=native["vue"])
        assert r.status_code == 409 and len(appels) == 1, r.text
        _aucun_fragment(r)
        assert a.w.b._tables() == avant
