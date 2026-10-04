"""Parcours CMO sur SQLite/HTTP réels; Synergy et statistiques entièrement fictives."""
from __future__ import annotations

import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from m7_marketing import cmo_strategie, growth
from sqlalchemy import func, select, update

from opsys import idempotence, identite, stockage
from opsys.console import application, metier, securite
from opsys.console.securite import Configuration, Session
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_SORTANTS, MUTATIONS_APPLIQUEES, REGISTRES

PREFIXE = "/synergy-fictive"
SECRET = "secret-cmo-strategie-fictif-" + "x" * 32
MDP = "mot-de-passe-cmo-fictif-2026"
DATES = {"date_depart": "2026-10-01", "debut": "2026-09-01", "fin": "2026-09-30"}


def _expirer_session_metier(client, monkeypatch):
    session = securite.lire_session(client.cookies.get(securite.NOM_COOKIE), SECRET)
    assert session is not None

    class HorlogeExpiree(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(session.expire, UTC).astimezone(tz)

    monkeypatch.setattr(metier, "datetime", HorlogeExpiree)


@pytest.fixture
def console(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'synergy-cmo.sqlite3'}")
    stockage.liberer()
    stockage.migrer()
    with stockage.transaction() as cnx:
        for personne, roles in (("owner", ["nathan_owner"]), ("admin", ["admin"]),
                                 ("ouvrier", ["employee"]), ("client", ["client"])):
            identite.creer_personne(cnx, personne, "Personne Synergy FICTIVE " + personne, MDP, roles)
        growth.enregistrer_observation("obs-fictive-avis", "demandes_avis", 12, "demande", "2026-09-01",
                                      "2026-09-30", "manuel", "synergy-fictive-automne", "journal FICTIF",
                                      "preuve-fictive-avis-septembre", 0.4)
    app = application.creer_application(Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE),
                                       None, stockage.transaction)
    with TestClient(app, base_url="https://testserver" + PREFIXE) as client:
        csrf = _login(client)
        yield app, client, csrf
    stockage.liberer()


def _login(client, personne="owner"):
    r = client.post("/connexion", data={"identifiant": personne, "mot_de_passe": MDP}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client.get("/api/session").json()["csrf"]


def _contexte(client):
    r = client.get("/api/marketing/cmo/strategies/contexte", params=DATES)
    assert r.status_code == 200, r.text
    return r.json()["resultat"]


def _proposition(courant, *, programme="automne-synergy-fictif", baseline=True):
    o = courant["observations"][0]
    return {"programme_id": programme, "revision_attendue": 0, "empreinte_revision_attendue": None,
            "tete": courant["tete"], "growth_tete": courant["growth_tete"], "parametres": dict(DATES),
            "projection_attendue": courant["projection_attendue"], "titre": "Avis Synergy FICTIF automne",
            "hypothese": "Les paquets chantier consentis pourraient soutenir les demandes d’avis; non vérifié.",
            "objectifs": [{"objectif_id": "avis-consentis", "intitule": "Demandes d’avis consenties FICTIVES",
                           "metrique": "demandes_avis", "unite": "demande", "cible": 20,
                           "baseline": {k: o[k] for k in ("observation_id", "empreinte")} if baseline else None}],
            "actions": [{"action_id": "paquets-chantier", "objectif_id": "avis-consentis", "fenetre": "J1-30",
                         "livrable": "Préparer quatre paquets chantier fictifs à revoir humainement",
                         "responsable": "ouvrier",
                         "capacite_declaree": "Deux heures déclarées, disponibilité M4 inconnue"}]}


def _post(client, csrf, action, a, mutation):
    chemin = "/api/marketing/cmo/strategies"
    if action != "proposer":
        chemin += "/" + a["programme_id"] + ("/decisions" if action == "decider" else "/revues")
    return client.post(chemin, json={"mutation_id": mutation, "arguments": a}, headers={"x-csrf-token": csrf})


def _evenement(r):
    assert r.status_code == 200, r.text
    return r.json()["resultat"]["evenement"]


def _decision(courant, e):
    return {"programme_id": e["charge"]["programme_id"], "revision": e["charge"]["revision"],
            "empreinte_revision": e["empreinte"], "tete": courant["tete"], "growth_tete": courant["growth_tete"],
            "projection_attendue": courant["projection_attendue"], "decision": "approuver",
            "motif": "Nathan FICTIF approuve ce programme interne sans autoriser de publication."}


def _comptes():
    with stockage.transaction() as cnx:
        return tuple(cnx.execute(select(func.count()).select_from(t)).scalar_one()
                     for t in (REGISTRES, MUTATIONS_APPLIQUEES, EVENEMENTS_SORTANTS))


def test_cycle_synergy_fictif_http_rouverture_baseline_decision_revue(console):
    _, client, csrf = console
    avant_bus = _comptes()[2]
    with stockage.transaction():
        growth_avant = list(stockage.maillons("m07-marketing", "growth"))
    e = _evenement(_post(client, csrf, "proposer", _proposition(_contexte(client)), "proposition-fictive"))
    assert e["charge"]["baselines"]["avis-consentis"]["valeur"] == 12
    assert e["auteur"] == {"personne": "owner", "role": "nathan_owner", "source": "console"}
    assert e["charge"]["projection"]["fenetres"] == [
        {"id": "J1-30", "debut": "2026-10-01", "fin": "2026-10-30"},
        {"id": "J31-60", "debut": "2026-10-31", "fin": "2026-11-29"},
        {"id": "J61-90", "debut": "2026-11-30", "fin": "2026-12-29"},
    ]
    d = _evenement(_post(client, csrf, "decider", _decision(_contexte(client), e), "decision-fictive"))
    assert d["charge"]["empreinte_revision"] == e["empreinte"]
    courant = _contexte(client)
    r = {k: v for k, v in _decision(courant, e).items() if k not in {"decision", "motif", "projection_attendue"}}
    r.update(debut=DATES["debut"], fin=DATES["fin"], conclusion="Résultat FICTIF déclaré, causalité inconnue.",
             observations=[{k: courant["observations"][0][k] for k in ("observation_id", "empreinte")}])
    revue = _evenement(_post(client, csrf, "revoir", r, "revue-fictive"))
    assert revue["charge"]["observations"][0]["valeur"] == 12
    stockage.liberer()
    historique = client.get("/api/marketing/cmo/strategies")
    assert historique.status_code == 200
    v = historique.json()["resultat"]["programmes"][e["charge"]["programme_id"]][0]
    assert v["proposition"] == e and v["decision"] == d and v["revues"] == [revue]
    with stockage.transaction() as cnx:
        assert list(stockage.maillons("m07-marketing", "growth")) == growth_avant
        assert identite.personne_active(cnx, "ouvrier").roles == frozenset({"employee"})
    assert _comptes()[2] == avant_bus
    page = client.get("/marketing/cmo")
    assert page.status_code == 200 and "baseline déclarée 12" in page.text
    assert "Résultat FICTIF déclaré" in page.text and page.headers["cache-control"] == "no-store"


def test_unknown_ne_devient_pas_zero_et_cible_reste_declaration(console):
    _, client, csrf = console
    a = _proposition(_contexte(client), baseline=False)
    e = _evenement(_post(client, csrf, "proposer", a, "baseline-inconnue"))
    assert e["charge"]["baselines"] == {"avis-consentis": None}
    assert e["charge"]["objectifs"][0]["cible"] == 20
    assert "baseline déclarée inconnue" in client.get("/marketing/cmo").text


def test_rejeu_exact_ne_refait_pas_cas_ni_timestamp_et_conflit_refuse(console):
    _, client, csrf = console
    a = _proposition(_contexte(client))
    e = _evenement(_post(client, csrf, "proposer", a, "rejeu-fictif"))
    compte = _comptes()
    stockage.liberer()
    r = _post(client, csrf, "proposer", a, "rejeu-fictif")
    assert _evenement(r) == e and r.json()["resultat"]["rejoue"] is True
    a["titre"] = "charge différente FICTIVE"
    assert _post(client, csrf, "proposer", a, "rejeu-fictif").status_code == 409
    assert _comptes() == compte


def test_admin_propose_owner_decide_et_revocation_interdit_rejeu(console):
    _, client, _ = console
    csrf_admin = _login(client, "admin")
    a = _proposition(_contexte(client))
    e = _evenement(_post(client, csrf_admin, "proposer", a, "admin-fictif"))
    d = _decision(_contexte(client), e)
    avant = _comptes()
    assert _post(client, csrf_admin, "decider", d, "admin-decide-fictif").status_code == 403
    assert _comptes() == avant
    csrf_owner = _login(client)
    _evenement(_post(client, csrf_owner, "decider", d, "owner-decide-fictif"))
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "owner", "nathan_owner")
    assert _post(client, csrf_owner, "decider", d, "owner-decide-fictif").status_code in {401, 403}


def test_revision_ne_reprend_jamais_approbation_et_hash_exact_requis(console):
    _, client, csrf = console
    e = _evenement(_post(client, csrf, "proposer", _proposition(_contexte(client)), "v1"))
    _evenement(_post(client, csrf, "decider", _decision(_contexte(client), e), "approuve-v1"))
    a = _proposition(_contexte(client))
    a.update(revision_attendue=1, empreinte_revision_attendue=e["empreinte"], titre="Version deux FICTIVE")
    v2 = _evenement(_post(client, csrf, "proposer", a, "v2"))
    h = client.get("/api/marketing/cmo/strategies").json()["resultat"]["programmes"][a["programme_id"]]
    assert h[0]["decision"]["charge"]["decision"] == "approuver" and h[1]["decision"] is None
    d = _decision(_contexte(client), v2)
    d["empreinte_revision"] = e["empreinte"]
    avant = _comptes()
    assert _post(client, csrf, "decider", d, "faux-hash-v2").status_code == 409
    assert _comptes() == avant


def test_historique_approuve_reste_lisible_apres_corruption_growth(console):
    _, client, csrf = console
    e = _evenement(_post(client, csrf, "proposer", _proposition(_contexte(client)), "avant-corruption"))
    _evenement(_post(client, csrf, "decider", _decision(_contexte(client), e), "approuve-avant-corruption"))
    avant = client.get("/api/marketing/cmo/strategies").json()
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m07-marketing", REGISTRES.c.registre == "growth",
        )
                    .values(maillon="{corruption FICTIVE"))
    assert client.get("/api/marketing/cmo/strategies").json() == avant
    assert client.get("/marketing/cmo").status_code == 200
    assert client.get("/api/marketing/cmo/strategies/contexte", params=DATES).status_code == 409


@pytest.mark.parametrize("changement", ["hash", "id", "unite", "responsable", "client", "auteur", "nan"])
def test_refus_reference_unite_role_et_provenance_sans_effet(console, changement):
    _, client, csrf = console
    a = _proposition(_contexte(client))
    if changement == "hash":
        a["objectifs"][0]["baseline"]["empreinte"] = "0" * 64
    elif changement == "id":
        a["objectifs"][0]["baseline"]["observation_id"] = "source-imaginaire-fictive"
    elif changement == "unite":
        a["objectifs"][0]["unite"] = "vente"
    elif changement in {"responsable", "client"}:
        a["actions"][0]["responsable"] = "absent" if changement == "responsable" else "client"
    elif changement == "auteur":
        a["auteur"] = "nathan-faux"
    else:
        a["objectifs"][0]["cible"] = True  # bool n'est jamais un nombre métier
    avant = _comptes()
    assert _post(client, csrf, "proposer", a, "refus-" + changement).status_code in {400, 409}
    assert _comptes() == avant


def test_rollback_apres_append_annule_recu_et_journal(console, monkeypatch):
    _, client, csrf = console
    a = _proposition(_contexte(client))
    avant = _comptes()
    def interrompre(*_a, **_kw):
        raise ValueError("panne FICTIVE après append")
    monkeypatch.setattr(idempotence, "finaliser", interrompre)
    assert _post(client, csrf, "proposer", a, "rollback-fictif").status_code == 409
    assert _comptes() == avant


def test_post_metier_dans_threadpool_et_json_profond_rejete(console, monkeypatch):
    _, client, csrf = console
    original = cmo_strategie.executer
    observations = []
    def verifier_thread(*args, **kwargs):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        observations.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(cmo_strategie, "executer", verifier_thread)
    _evenement(_post(client, csrf, "proposer", _proposition(_contexte(client)), "threadpool"))
    assert observations == [True]
    assert client.post("/api/marketing/cmo/strategies", content='{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}',
                       headers={"x-csrf-token": csrf, "content-type": "application/json"}).status_code == 400


def test_csrf_corps_borne_doublons_et_rendu_xss(console):
    _, client, csrf = console
    a = _proposition(_contexte(client))
    a["titre"] = '<script>alert("FICTIF")</script>'
    assert _post(client, "incorrect", "proposer", a, "sans-csrf").status_code == 403
    assert client.post("/api/marketing/cmo/strategies", content="x" * (32 * 1024 + 1),
                       headers={"x-csrf-token": csrf}).status_code == 413
    assert client.post("/api/marketing/cmo/strategies", content='{"mutation_id":"a","mutation_id":"b","arguments":{}}',
                       headers={"x-csrf-token": csrf}).status_code == 400
    _evenement(_post(client, csrf, "proposer", a, "xss-fictif"))
    page = client.get("/marketing/cmo")
    assert '<script>alert("FICTIF")</script>' not in page.text and "&lt;script&gt;" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert PREFIXE + "/marketing/cmo/strategies/" in page.text


def test_socle_concurrence_meme_tete_un_seul_append(console):
    _, client, _ = console
    courant = _contexte(client)
    a = _proposition(courant, programme="programme-a-fictif")
    b = _proposition(courant, programme="programme-b-fictif")
    deps = charger_departements()
    session = Session("owner", frozenset({"nathan_owner"}), "csrf-fictif", 9999999999)
    def tenter(charge, mutation):
        try:
            with stockage.transaction() as cnx:
                metier.executer(cnx, deps, session, "m7_proposer_strategie_humaine", charge, mutation_id=mutation)
            return "accepte"
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(lambda t: tenter(*t), [(a, "concurrent-a"), (b, "concurrent-b")]))
    assert resultats.count("accepte") == 1
    assert any("CMO-TETE-PERIMEE" in r for r in resultats)
    assert len(client.get("/api/marketing/cmo/strategies").json()["resultat"]["programmes"]) == 1


@pytest.mark.parametrize("depart", ["9999-12-31", "9999-12-01", "9999-10-04"])
def test_transport_horizon_90_jours_deborde_refus_400_sans_effet(console, depart):
    _, client, csrf = console
    a = _proposition(_contexte(client))
    a["parametres"]["date_depart"] = depart
    avant = _comptes()
    assert _post(client, csrf, "proposer", a, "overflow-" + depart).status_code == 400
    assert _comptes() == avant


def test_source_growth_changee_decision_sans_rebase_refusee(console):
    from opsys.stockage import codec

    _, client, csrf = console
    e = _evenement(_post(client, csrf, "proposer", _proposition(_contexte(client)), "avant-changement"))
    with stockage.transaction() as cnx:
        filtre = (REGISTRES.c.departement == "m07-marketing") & (REGISTRES.c.registre == "growth")
        m = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        m["valeur"] = 99  # correction FICTIVE de l'administrateur DB, valide mais référence différente
        m["empreinte"] = growth._empreinte({k: v for k, v in m.items() if k not in {"type", "empreinte"}})
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(m)))
    courant = _contexte(client)
    assert courant["observations"][0]["valeur"] == 99
    avant = _comptes()
    assert _post(client, csrf, "decider", _decision(courant, e), "rebase-interdite").status_code == 409
    assert _comptes() == avant
    h = client.get("/api/marketing/cmo/strategies").json()["resultat"]["programmes"][e["charge"]["programme_id"]][0]
    assert h["proposition"]["charge"]["baselines"]["avis-consentis"]["valeur"] == 12
    assert h["decision"] is None


def test_retrait_role_entre_append_et_finalisation_annule_tout(console, monkeypatch):
    _, client, csrf = console
    with stockage.transaction() as cnx:
        identite.ajouter_role(cnx, "owner", "admin")
    a = _proposition(_contexte(client))
    original = cmo_strategie.executer
    def retirer_apres_append(cnx, *args, **kwargs):
        reponse = original(cnx, *args, **kwargs)
        identite.retirer_role(cnx, "owner", "nathan_owner")
        return reponse
    monkeypatch.setattr(cmo_strategie, "executer", retirer_apres_append)
    avant = _comptes()
    assert _post(client, csrf, "proposer", a, "role-retire-finalisation").status_code == 403
    assert _comptes() == avant


def test_formulaire_humain_sur_prefixe_reel_et_csrf(console):
    import html
    import re

    _, client, csrf = console
    page = client.get("/marketing/cmo", params=DATES)
    assert page.status_code == 200, page.text
    bloc = re.search(r'<form method="post" action="' + re.escape(PREFIXE) + r'/marketing/cmo/strategies">(.*?)</form>',
                     page.text, re.S).group(1)
    motif = r'<input type="hidden" name="([^"]+)" value="([^"]*)">'
    champs = {nom: html.unescape(valeur) for nom, valeur in re.findall(motif, bloc)}
    champs.update(titre="Programme humain FICTIF", hypothese="Avis consentis FICTIFS sans publication",
                  intitule="Demandes FICTIVES", metrique="demandes_avis", unite="demande", cible="20", baseline="",
                  livrable="Quatre paquets fictifs", responsable="ouvrier", capacite_declaree="Deux heures déclarées",
                  fenetre="J1-30")
    assert champs["csrf"] == csrf
    incorrects = copy.deepcopy(champs)
    incorrects["csrf"] = "faux"
    avant = _comptes()
    assert client.post("/marketing/cmo/strategies", data=incorrects).status_code == 403
    assert _comptes() == avant
    r = client.post("/marketing/cmo/strategies", data=champs, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == PREFIXE + "/marketing/cmo"
    h = client.get("/api/marketing/cmo/strategies").json()["resultat"]
    v = next(iter(h["programmes"].values()))[0]
    assert v["proposition"]["auteur"]["personne"] == "owner"
    assert v["proposition"]["charge"]["baselines"]["objectif-principal"] is None


def test_revue_non_approuvee_refusee_et_affectation_ne_donne_pas_acces(console):
    _, client, csrf = console
    e = _evenement(_post(client, csrf, "proposer", _proposition(_contexte(client)), "non-approuvee"))
    courant = _contexte(client)
    a = {k: v for k, v in _decision(courant, e).items() if k not in {"decision", "motif", "projection_attendue"}}
    a.update(debut=DATES["debut"], fin=DATES["fin"], conclusion="Conclusion FICTIVE prématurée", observations=[])
    avant = _comptes()
    assert _post(client, csrf, "revoir", a, "revue-sans-approbation").status_code == 409
    assert _comptes() == avant
    csrf_ouvrier = _login(client, "ouvrier")
    assert client.get("/api/marketing/cmo/strategies").status_code == 403
    assert _post(client, csrf_ouvrier, "revoir", a, "ouvrier-sans-droits").status_code == 403
    assert _comptes() == avant


@pytest.mark.parametrize("phase", ["apres_corps", "apres_append"])
def test_expiration_session_pendant_post_annule_toute_ecriture(console, monkeypatch, phase):
    from opsys.console import marketing_cmo_ui

    _, client, csrf = console
    arguments = _proposition(_contexte(client))
    avant = _comptes()
    if phase == "apres_corps":
        original = marketing_cmo_ui._corps_borne

        async def lire_et_expirer(request):
            brut = await original(request)
            _expirer_session_metier(client, monkeypatch)
            return brut

        monkeypatch.setattr(marketing_cmo_ui, "_corps_borne", lire_et_expirer)
    else:
        original = cmo_strategie.executer

        def ajouter_et_expirer(*args, **kwargs):
            resultat = original(*args, **kwargs)
            _expirer_session_metier(client, monkeypatch)
            return resultat

        monkeypatch.setattr(cmo_strategie, "executer", ajouter_et_expirer)
    response = _post(client, csrf, "proposer", arguments, "expiry-" + phase)
    assert response.status_code == 403, response.text
    assert _comptes() == avant


def test_session_expiree_interdit_rejeu_et_lecture_historique(console, monkeypatch):
    _, client, csrf = console
    arguments = _proposition(_contexte(client))
    _evenement(_post(client, csrf, "proposer", arguments, "expiry-replay"))
    avant = _comptes()
    _expirer_session_metier(client, monkeypatch)
    assert _post(client, csrf, "proposer", arguments, "expiry-replay").status_code == 403
    assert client.get("/api/marketing/cmo/strategies").status_code == 403
    assert _comptes() == avant


@pytest.mark.parametrize("retrait", ["expiration", "role"])
def test_lecture_historique_revalide_avant_retour_prive(console, monkeypatch, retrait):
    _, client, csrf = console
    _evenement(_post(client, csrf, "proposer", _proposition(_contexte(client)), "read-boundary"))
    avant = _comptes()
    original = cmo_strategie.lire

    def lire_puis_retirer(cnx):
        resultat = original(cnx)
        if retrait == "expiration":
            _expirer_session_metier(client, monkeypatch)
        else:
            identite.retirer_role(cnx, "owner", "nathan_owner")
        return resultat

    monkeypatch.setattr(cmo_strategie, "lire", lire_puis_retirer)
    response = client.get("/api/marketing/cmo/strategies")
    assert response.status_code == 403
    assert "Avis Synergy FICTIF" not in response.text
    assert _comptes() == avant
