"""Bilan périodique humain M9 : HTTP réel, SQLite/M8 fictifs, aucune action terrain.

Ce fichier est destiné à tests/test_console_bilan_suivis_m9.py après admission Root.
Les dates sont fixées dans approbations._maintenant AVANT les demandes/décisions.
Aucune réécriture de registre SQL ne fabrique la chronologie ou les empreintes.
"""

from __future__ import annotations

import html
import importlib.util
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from opsys import approbations, identite, stockage

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_console_bilan_console_base", Path(__file__).with_name("test_console_suivis_m9.py")
)
c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c)
_spec_period = importlib.util.spec_from_file_location(
    "_console_bilan_api_base",
    RACINE / "departments/m09-strategic-intelligence/tests/test_bilan_suivis.py",
)
p = importlib.util.module_from_spec(_spec_period)
_spec_period.loader.exec_module(p)
s, b = c.h, c.b
h = s.h
installation = c.installation
DEBUT, FIN = p.DEBUT, p.FIN
ROUTE = "/strategie/bilan"
FUTUR = "FUTURE_CLOTURE_FICTIVE"
COMPTEURS = {"ouverts_periode": 1, "clotures_periode": 1, "ouverts_fin": 1}


class Rendu(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.compteurs = {}
        self.ids = []
        self.inputs = {}
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        valeurs = dict(attrs)
        if "data-compteur" in valeurs:
            nom = valeurs["data-compteur"]
            assert nom not in self.compteurs, "Un compteur global ne doit pas être dupliqué"
            chiffre = valeurs.get("data-valeur", "")
            assert chiffre.isascii() and chiffre.isdecimal(), valeurs
            self.compteurs[nom] = int(chiffre)
        if "data-suivi-id" in valeurs:
            self.ids.append(valeurs["data-suivi-id"])
        if tag == "input" and "name" in valeurs:
            self.inputs[valeurs["name"]] = valeurs.get("value", "")


def _date(monkeypatch, instant):
    monkeypatch.setattr(approbations, "_maintenant", lambda: instant)


def _clore(cap, ident, alerte, bilan):
    prep = b._lire(cap, h.PREPARER, {"suivi_id": ident, "evenement_id": alerte["evenement_id"]})
    demande = cap.appeler(h.CLORE, {
        "suivi_id": ident, "evenement_id": alerte["evenement_id"],
        "empreinte_suivi": prep["empreinte_suivi"],
        "empreinte_preuve": prep["preuve"]["empreinte_source"], "bilan": bilan,
    })
    assert demande["statut"] == "en_attente_approbation", demande
    decision = b._decider(cap, demande["demande_id"], "clore-bilan-http-" + ident)
    assert decision["resultat"]["resultat"]["statut"] == "executee", decision
    return demande["demande_id"]


def _historique(installation, monkeypatch):
    _date(monkeypatch, "2026-10-01T12:00:00+00:00")
    cap, ids, alerte = s._preparer(installation, 1)
    plan = b._suivis()[0]
    args = {k: plan[k] for k in ("action", "responsable_id", "echeance")}
    args |= {"evenement_id": alerte["evenement_id"], "empreinte_source": b.empreinte(alerte)}
    for suffixe, instant in [("B", "2026-10-06T12:00:00Z"), ("C", FIN)]:
        _date(monkeypatch, instant)
        prop = cap.appeler(b.OUVRIR, args | {"action": "Revue périodique fictive " + suffixe})
        assert prop["statut"] == "en_attente_approbation", prop
        ident = prop["demande_id"]
        assert b._decider(cap, ident, "ouvrir-bilan-http-" + ident)["resultat"]["resultat"]["statut"] == "executee"
        ids.append(ident)
    _date(monkeypatch, "2026-10-08T12:00:00Z")
    _clore(cap, ids[1], alerte, "Revue humaine fictive réalisée pendant la période.")
    _date(monkeypatch, "2026-10-13T12:00:00Z")
    future_id = _clore(cap, ids[0], alerte, FUTUR + " : revue ultérieure, sans action terrain attestée.")
    assert len(b._suivis()) == 3 and len(h._clotures()) == 2
    assert p._lire(cap)["compteurs"] == COMPTEURS
    return cap, ids, alerte, future_id


def _obtenir(client, **args):
    return client.get(ROUTE, params={"debut": DEBUT, "fin": FIN} | args)


def _reprises(texte):
    return [x for x in c._liens(texte, ROUTE) if "depart" in parse_qs(urlsplit(x).query)]


def test_http_bilan_reel_n_expose_pas_la_cloture_future_du_detail_courant(installation, monkeypatch):
    cap, ids, alerte, future_id = _historique(installation, monkeypatch)
    with c._client(installation) as client:
        c._connecter(client)
        courant = client.get("/strategie/suivi", params={"suivi_id": ids[0]})
        assert courant.status_code == 200 and FUTUR in courant.text and future_id in courant.text
        avant = b._tables()
        reponse = _obtenir(client)
        assert reponse.status_code == 200, "M9_BILAN_HTTP_ROUTE_ABSENTE_APRES_3_PLANS_2_CLOTURES_REELS: " + reponse.text
        assert "Bilan historique des suivis" in reponse.text
        rendus, lignes, visitees = [], [], set()
        while True:
            rendu = Rendu(reponse.text)
            assert rendu.compteurs == COMPTEURS
            assert not c._liens(reponse.text, "/strategie/suivi")
            assert FUTUR not in reponse.text and future_id not in reponse.text
            assert ids[2] not in reponse.text
            assert DEBUT in html.unescape(reponse.text) and FIN in html.unescape(reponse.text)
            rendus.append(reponse.text)
            lignes.extend(rendu.ids)
            suivant = _reprises(reponse.text)
            assert len(suivant) <= 1
            if not suivant:
                break
            assert suivant[0] not in visitees
            visitees.add(suivant[0])
            reponse = client.get("https://testserver" + suivant[0])
            assert reponse.status_code == 200, reponse.text
        assert lignes == ids[:2]
        texte = html.unescape("".join(rendus))
        assert alerte["evenement_id"] in texte and b.RESPONSABLE in texte
        for plan in b._suivis()[:2]:
            assert plan["action"] in texte and plan["echeance"] in texte
            assert b.empreinte(plan) in texte
        assert b._tables() == avant
        assert reponse.headers["cache-control"] == "no-store"
        assert "default-src 'none'" in reponse.headers["content-security-policy"]
        assert p._lire(cap)["compteurs"] == COMPTEURS


def test_formulaire_vide_et_liens_depuis_echeancier_sans_dates_implicites(installation, monkeypatch):
    _date(monkeypatch, DEBUT)
    s._preparer(installation, 1)
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        r = client.get(ROUTE)
        assert r.status_code == 200, r.text
        assert Rendu(r.text).inputs.get("debut") == ""
        assert Rendu(r.text).inputs.get("fin") == ""
        assert DEBUT not in r.text and FIN not in r.text
        assert not Rendu(r.text).ids and not Rendu(r.text).compteurs
        for reponse in [client.get("/strategie"), c._obtenir(client)]:
            assert reponse.status_code == 200
            assert c._liens(reponse.text, ROUTE)
        assert b._tables() == avant


def test_pagination_http_huit_approbations_compteurs_globaux_et_reprise_perimee(installation, monkeypatch):
    _date(monkeypatch, "2026-10-06T12:00:00Z")
    cap, ids, alerte = s._preparer(installation, 8)
    import m9_strategic_intelligence.outils as outils
    monkeypatch.setattr(outils, "BUDGET_SORTIE", 3800)
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        reponse = _obtenir(client)
        lus, urls, premiere_reprise, pages = [], set(), None, 0
        while True:
            assert reponse.status_code == 200, reponse.text
            pages += 1
            rendu = Rendu(reponse.text)
            assert rendu.compteurs == {"ouverts_periode": 8, "clotures_periode": 0, "ouverts_fin": 8}
            assert rendu.ids and not set(rendu.ids).intersection(lus)
            lus.extend(rendu.ids)
            liens = _reprises(reponse.text)
            assert len(liens) <= 1
            if not liens:
                break
            lien = liens[0]
            params = parse_qs(urlsplit(lien).query)
            assert params["debut"] == [DEBUT] and params["fin"] == [FIN]
            assert len(params["vue_attendue"][0]) == 64
            assert int(params["depart"][0]) == len(lus)
            assert lien not in urls
            urls.add(lien)
            premiere_reprise = premiere_reprise or lien
            reponse = client.get("https://testserver" + lien)
        assert pages >= 3 and len(lus) == len(set(lus)) == 8
        assert set(lus) == set(ids) and b._tables() == avant
        # La clôture réelle change la vue sans changer le nombre de suivis pertinents.
        _date(monkeypatch, "2026-10-08T12:00:00Z")
        _clore(cap, ids[-1], alerte, "Nouvelle revue humaine fictive après la première lecture.")
        avant = b._tables()
        perimee = client.get("https://testserver" + premiere_reprise)
        assert perimee.status_code == 409, perimee.text
        assert not Rendu(perimee.text).ids
        redemarrages = [x for x in c._liens(perimee.text, ROUTE)
                        if parse_qs(urlsplit(x).query).get("debut") == [DEBUT]]
        assert redemarrages
        for lien in redemarrages:
            params = parse_qs(urlsplit(lien).query)
            assert params == {"debut": [DEBUT], "fin": [FIN]}
        frais = client.get("https://testserver" + redemarrages[0])
        assert frais.status_code == 200
        assert Rendu(frais.text).compteurs == {"ouverts_periode": 8, "clotures_periode": 1, "ouverts_fin": 7}
        assert b._tables() == avant


@pytest.mark.parametrize("roles", ["ancien_cookie", "owner_seul", "admin_seul"])
def test_admin_sql_courant_indispensable_meme_avec_cookie_signe(installation, monkeypatch, roles):
    _date(monkeypatch, DEBUT)
    s._preparer(installation, 1)
    with c._client(installation) as client:
        if roles == "ancien_cookie":
            c._connecter(client)
            assert _obtenir(client).status_code == 200
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, b.PROPRIO.personne, "nathan_owner" if roles == "admin_seul" else "admin")
        if roles != "ancien_cookie":
            c._connecter(client)
        avant = b._tables()
        for rep in [_obtenir(client), client.get(ROUTE)]:
            assert rep.status_code == (200 if roles == "admin_seul" else 403), rep.text
        assert b._tables() == avant


@pytest.mark.parametrize("suffixe", ["", "?depart=invalide&inconnu=fictif"])
def test_anonyme_redirige_avant_analyse_des_parametres(installation, suffixe):
    avant = b._tables()
    with c._client(installation) as client:
        r = client.get(ROUTE + suffixe, follow_redirects=False)
        assert r.status_code == 303 and "/connexion" in r.headers["location"], r.text
    assert b._tables() == avant


@pytest.mark.parametrize("params", [
    {"debut": DEBUT}, {"fin": FIN}, {"debut": "2026-10-05", "fin": FIN},
    {"debut": DEBUT, "fin": "2026-10-12T00:00:00"}, {"debut": FIN, "fin": DEBUT},
    {"debut": FIN, "fin": FIN}, {"debut": DEBUT, "fin": FIN, "inconnu": "fictif"},
    [("debut", DEBUT), ("debut", DEBUT), ("fin", FIN)],
    {"debut": DEBUT, "fin": FIN, "depart": "-1"},
    {"debut": DEBUT, "fin": FIN, "depart": "true"},
    {"debut": DEBUT, "fin": FIN, "depart": "1"},
    {"debut": DEBUT, "fin": FIN, "depart": "1", "vue_attendue": "0" * 64},
])
def test_requete_invalide_refusee_sans_effet(installation, monkeypatch, params):
    _date(monkeypatch, DEBUT)
    s._preparer(installation, 1)
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        r = client.get(ROUTE, params=params)
        assert r.status_code in {400, 409}, r.text
        assert not Rendu(r.text).ids and b._tables() == avant


def test_textes_metier_echappes_et_aucun_post_ni_effet(installation, monkeypatch):
    _date(monkeypatch, DEBUT)
    action = 'Revue fictive <script>alert("periode")</script>'
    cap, _, ident, _ = b._proposer(installation, action=action)
    assert b._decider(cap, ident, "ouvrir-xss-bilan-fictif")["resultat"]["resultat"]["statut"] == "executee"
    with c._client(installation) as client:
        c._connecter(client)
        avant = b._tables()
        r = _obtenir(client)
        assert r.status_code == 200, r.text
        assert "<script>" not in r.text and "&lt;script&gt;" in r.text
        assert action in html.unescape(r.text) and Rendu(r.text).ids == [ident]
        assert not c._liens(r.text, "/strategie/suivi")
        refus = client.post(ROUTE, data={"debut": DEBUT, "fin": FIN})
        assert refus.status_code in {404, 405}, refus.text
        assert b._tables() == avant


def test_statuts_visibles_de_chaque_suivi_sans_etre_masques_par_les_details(installation, monkeypatch):
    import re

    class Resumes(HTMLParser):
        def __init__(self, texte):
            super().__init__()
            self.courant = None
            self.details = 0
            self.textes = {}
            self.feed(texte)

        def handle_starttag(self, tag, attrs):
            valeurs = dict(attrs)
            if tag == "article" and "data-suivi-id" in valeurs:
                self.courant = valeurs["data-suivi-id"]
                assert self.courant not in self.textes
                self.textes[self.courant] = []
            if tag == "details":
                self.details += 1

        def handle_endtag(self, tag):
            if tag == "details":
                self.details -= 1
            if tag == "article":
                self.courant = None

        def handle_data(self, data):
            if self.courant is not None and self.details == 0:
                self.textes[self.courant].append(data)

    _, ids, _, _ = _historique(installation, monkeypatch)
    obtenus = {}
    motif = re.compile(
        r"Ouvert pendant la période : (vrai|faux) .*?"
        r"Clos pendant la période : (vrai|faux) .*?"
        r"Ouvert juste avant la fin : (vrai|faux)"
    )
    with c._client(installation) as client:
        c._connecter(client)
        reponse = _obtenir(client)
        while True:
            assert reponse.status_code == 200
            for ident, fragments in Resumes(reponse.text).textes.items():
                assert ident not in obtenus
                resume_visible = " ".join(" ".join(fragments).split())
                trouve = motif.search(resume_visible)
                assert trouve is not None, resume_visible
                obtenus[ident] = tuple(v == "vrai" for v in trouve.groups())
            suivant = _reprises(reponse.text)
            if not suivant:
                break
            assert len(suivant) == 1
            reponse = client.get("https://testserver" + suivant[0])
    # Attendus tirés des dates des décisions réelles de la fixture, indépendants des détails rendus.
    assert obtenus == {ids[0]: (False, False, True), ids[1]: (True, True, False)}
