"""Console réelle (TestClient, CSRF, parser, rendu) pour `canal sms <compte_id> <account_sid>`. Fictif."""
from __future__ import annotations

import html
import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.test_agents_sms_configuration import PROFILE_TABLES, snapshot_sql, verifier_fenetre

from opsys import agents, departements, identite
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage.schema import AGENTS_DECLENCHEURS_COMMANDES, AGENTS_DECLENCHEURS_INTENTIONS

FICTIF = True
OWNER, PASSWORD = "owner.sms.console.fictif", "mot-de-passe-sms-console-fictif-123"
SID_A = "AC" + "0123456789abcdef" * 2
SID_B = "AC" + "fedcba9876543210" * 2
TOOL = "m1_recevoir_message_canal"  # HYPOTHESE: présent dans le catalogue M1 réel
LIGNE_A = f"canal sms cabinet-1 {SID_A}"
CANAL_A = {"type": "canal", "version": 1, "canal": "sms", "compte_id": "cabinet-1", "account_sid": SID_A}


@pytest.fixture
def ctx(session, opsys_home, monkeypatch):
    deps = departements.charger_departements()
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(opsys_home / "core"))
    with session() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", PASSWORD, ["nathan_owner"])
    politique = {"version": 1, "departements": {"m01-front-office": "global"}, "procedures_globales": ["procedures"],
                 "agents": {"opsys-agent-m01-sms-ui": {"departement": "m01-front-office", "mode": "global"}}}
    dossier = opsys_home / "core" / "opsys"
    dossier.mkdir(parents=True)
    (dossier / "memoire-autorites.json").write_text(json.dumps(politique), encoding="utf-8")
    app = application.creer_application(Configuration("secret-sms-console-fictif-" + "x" * 32), deps, session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        login = {"identifiant": OWNER, "mot_de_passe": PASSWORD}
        reponse_post = client.post("/connexion", data=login, follow_redirects=False)
        assert reponse_post.status_code == 303
        yield client, client.get("/api/session").json()["csrf"], deps


def form(csrf, ident, declencheurs, mutation, **autres):
    return {
        "csrf": csrf, "mutation_id": mutation, "id": ident, "departement": "m01-front-office",
        "responsabilite": "Accueil SMS fictif.", "palier_modele": "rapide", "outils": TOOL,
        "budget_jour": "1000", "budget_mois": "10000", "limite_tours": "8", "limite_reessais": "1",
        "limite_concurrence": "1", "declencheurs": declencheurs, **autres,
    }


def textarea(page):
    motif = r'<textarea id="agent-declencheurs" name="declencheurs" required>(.*?)</textarea>'
    m = re.search(motif, page.text, re.S)
    assert m is not None
    return html.unescape(m.group(1))


def etat(session):
    with session() as cnx:
        return snapshot_sql(cnx)


def profils(session):
    with session() as cnx:
        return agents.lister(cnx, inclure_inactifs=True, inclure_supprimes=True)


def test_post_csrf_roundtrip_parser_rendu_et_echappement(ctx, session):
    client, csrf, _ = ctx
    avant = etat(session)
    champs = form(csrf, "m01-sms-ui", LIGNE_A, "creer-sms-ui-0001")
    for invalide in ({**champs, "csrf": "csrf-invalide-fictif"}, {k: v for k, v in champs.items() if k != "csrf"}):
        reponse_post = client.post("/agents", data=invalide, follow_redirects=False)
        assert reponse_post.status_code == 403
    assert profils(session) == []
    verifier_fenetre(avant, etat(session))
    champs = form(csrf, "m01-sms-ui", LIGNE_A, "creer-sms-ui-0002", responsabilite='<script>alert("sms")</script>')
    reponse_post = client.post("/agents", data=champs, follow_redirects=False)
    assert reponse_post.status_code == 303
    page = client.get("/agents/m01-sms-ui")
    assert page.status_code == 200 and textarea(page) == LIGNE_A
    echappe = "&lt;script&gt;" in page.text and '<script>alert("sms")' not in page.text
    assert echappe
    rendu = form(csrf, "m01-sms-deux", textarea(page), "creer-sms-ui-0003")
    reponse_post = client.post("/agents", data=rendu, follow_redirects=False)
    assert reponse_post.status_code == 303
    assert textarea(client.get("/agents/m01-sms-deux")) == LIGNE_A
    assert [(p["actif"], p["declencheurs"]) for p in profils(session)] == [(False, [CANAL_A])] * 2
    verifier_fenetre(avant, etat(session), autorises=PROFILE_TABLES)


@pytest.mark.parametrize("ligne", [
    "canal sms cabinet-1", f"canal sms cabinet-1 {SID_A} extra", f"canal voice cabinet-1 {SID_A}",
    f"canal sms Cabinet-1 {SID_A}", f"canal sms cabinet-1 {SID_A[:-1]}", "canal sms cabinet-1 AC<script>0000",
])
def test_parser_refuse_sans_ecriture_ni_html_brut(ctx, session, ligne):
    client, csrf, _ = ctx
    avant = etat(session)
    reponse = client.post("/agents", data=form(csrf, "m01-sms-ui", ligne, "refus-sms-ui-0001"), follow_redirects=False)
    assert reponse.status_code == 400
    echappe = "<script>0" not in reponse.text
    assert echappe
    assert profils(session) == []
    verifier_fenetre(avant, etat(session))


def test_json_natif_transporte_la_variante_et_refuse_le_second_actif(ctx, session):
    client, csrf, _ = ctx
    en_tete = {"x-csrf-token": csrf}
    for n, (ident, sid) in enumerate((("m01-sms-ui", SID_A), ("m01-sms-deux", SID_B)), 1):
        spec = {"id": ident, "departement": "m01-front-office", "responsabilite": "Accueil SMS fictif.",
                "palier_modele": "rapide", "outils": [TOOL], "budget_jour": 1000, "budget_mois": 10000,
                "limite_tours": 8, "limite_reessais": 1, "limite_concurrence": 1,
                "declencheurs": [{**CANAL_A, "account_sid": sid}]}
        corps = {"spec": spec, "mutation_id": f"json-sms-ui-{n:04d}"}
        reponse = client.post("/api/agents", json=corps, headers=en_tete)
        assert reponse.status_code == 200 and reponse.json()["agent"]["actif"] is False

    def activer(ident, n):
        commande = {"actif": True, "mutation_id": f"active-sms-ui-{n:04d}", "revision_attendue": 1}
        return client.post(f"/api/agents/{ident}/activation", json=commande, headers=en_tete)

    assert activer("m01-sms-ui", 1).status_code == 200
    avant = etat(session)
    assert activer("m01-sms-deux", 2).status_code == 400
    with session() as cnx:
        assert agents.obtenir(cnx, "m01-sms-deux")["actif"] is False
        assert len(agents.historique(cnx, "m01-sms-deux")) == 1
    verifier_fenetre(avant, etat(session))


def test_rendu_legacy_manuel_cron_evenement_inchange(ctx):
    client, csrf, deps = ctx
    dep = next(d for d in deps.values() if d.evenements_consomme)  # HYPOTHESE: un département consomme un événement
    lignes_legacy = f"manuel\nhoraire 0 7 * * 1-5\nevenement {dep.evenements_consomme[0]}"
    champs = form(csrf, "legacy-ui-fictif", lignes_legacy, "legacy-ui-0001", departement=dep.id, outils="")
    reponse_post = client.post("/agents", data=champs, follow_redirects=False)
    assert reponse_post.status_code == 303
    assert textarea(client.get("/agents/legacy-ui-fictif")) == lignes_legacy


def test_profil_sms_ne_produit_aucune_intention_cron(ctx, session):
    client, csrf, _ = ctx
    champs = form(csrf, "m01-sms-ui", LIGNE_A, "creer-sms-ui-0009")
    reponse_post = client.post("/agents", data=champs, follow_redirects=False)
    assert reponse_post.status_code == 303
    commande = {"actif": True, "mutation_id": "active-sms-ui-0009", "revision_attendue": 1}
    activation = client.post("/api/agents/m01-sms-ui/activation", json=commande, headers={"x-csrf-token": csrf})
    assert activation.status_code == 200
    avant = etat(session)
    page = client.get("/agents/m01-sms-ui")
    assert "Aucun déclencheur cron" in page.text and "Préparer la demande cron" not in page.text
    demande = {"csrf": csrf, "mutation_id": "cron-sms-ui-0009", "revision_attendue": "2",
               "fuseau": "America/Toronto", "confirme": "oui"}
    reponse_post = client.post("/agents/m01-sms-ui/declencheurs/cron/demander", data=demande)
    assert reponse_post.status_code == 400
    with session() as cnx:
        assert cnx.execute(select(AGENTS_DECLENCHEURS_INTENTIONS)).first() is None
        assert cnx.execute(select(AGENTS_DECLENCHEURS_COMMANDES)).first() is None
    verifier_fenetre(avant, etat(session))


@pytest.mark.parametrize("ligne", [
    f"canal  sms   cabinet-1  {SID_A}", f"canal\tsms\tcabinet-1\t{SID_A}",
    f"canal\u00a0sms\u00a0cabinet-1\u00a0{SID_A}",
])
def test_separateurs_whitespace_rendu_canonique_sans_changer_identifiants(ctx, session, ligne):
    client, csrf, _ = ctx
    avant = etat(session)
    donnees = form(csrf, "m01-sms-ui", ligne, "whitespace-sms-ui-0001")
    reponse_post = client.post("/agents", data=donnees, follow_redirects=False)
    assert reponse_post.status_code == 303
    assert textarea(client.get("/agents/m01-sms-ui")) == LIGNE_A
    assert profils(session)[0]["declencheurs"] == [CANAL_A]
    verifier_fenetre(avant, etat(session), autorises=PROFILE_TABLES)
