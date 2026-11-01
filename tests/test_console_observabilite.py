"""Console « Observabilité » et commandes `traces` : lecture seule, rôle relu en base, aucun contenu, coûts estimés."""

from __future__ import annotations

import argparse
import datetime as dt
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from opsys import identite
from opsys.console import observabilite_ui
from opsys.console.securite import Session
from opsys.observabilite import cle_locale
from opsys.observabilite import cli as cli_traces
from opsys.observabilite.pii import MasqueurMotifs
from opsys.observabilite.traces import JournalTraces, Span, Tarif, Traceur
from opsys.secrets_coffre import masquage

FICTIF = True
MOT_DE_PASSE = "mot-de-passe-console-obs-fictif-2026"


def _garnir(dossier, *, maintenant=None):
    from decimal import Decimal

    maintenant = maintenant or (lambda: dt.datetime.now(dt.UTC))
    journal = JournalTraces(dossier, b"c" * 32, maintenant=maintenant)
    t = Traceur(journal, MasqueurMotifs(b"p" * 32), maintenant=maintenant,
                tarifs={"palier-fictif": Tarif("palier-fictif", Decimal("3"), Decimal("15"))})
    for i in range(4):
        with t.appel_outil(outil="m1_filtrer_provenance", departement="m01-front-office", agent="agent-m1",
                           niveau="N0") as s:
            s.attribut("note", "client jean@example.test")
            s.conclure("refus" if i == 0 else "ok", code="REJ-MCP-RULE-OF-TWO" if i == 0 else None)
    with t.tour_agent(departement="m05-financecore", agent="agent-m5") as s:
        s.jetons(2000, 500, modele="palier-fictif")
    return journal


@pytest.fixture
def monde(session, opsys_home):
    with session() as cnx:
        identite.creer_personne(cnx, "proprio_fictif", "Propriétaire fictif", MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "employe_fictif", "Employé fictif", MOT_DE_PASSE, ["employee"])
    _garnir(opsys_home / "traces")
    return opsys_home / "traces"


def _client(dossier, utilisateur="proprio_fictif"):
    from opsys import stockage

    session = Session(utilisateur=utilisateur, roles=frozenset({"nathan_owner"}), csrf="c" * 32, expire=2**40)

    def session_page(_request, **_):
        return session

    app = FastAPI()
    app.include_router(observabilite_ui.creer_router(
        session_page=session_page, session_api=session_page, cnx_factory=stockage.transaction, prefixe="",
        dossier_traces=lambda: dossier))
    return TestClient(app)


def test_la_page_montre_cout_latence_et_refus_par_departement_sans_contenu(monde):
    client = _client(monde)
    page = client.get("/observabilite")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    for attendu in ("m01-front-office", "m05-financecore", "REJ-MCP-RULE-OF-TWO", "estimations", "0.013500"):
        assert attendu in page.text, attendu
    assert "jean@example.test" not in page.text  # aucun contenu, pas même masqué
    assert "<form" not in page.text.split("<main>")[1]  # aucun formulaire dans le contenu : lecture seule
    api = client.get("/api/observabilite?jours=30").json()
    assert api["ok"] and api["jours"] == 30
    m1 = next(d for d in api["departements"] if d["departement"] == "m01-front-office")
    assert (m1["appels_outils"], m1["refus"], m1["taux_refus"]) == (4, 1, "25.0 %")
    assert api["refus_par_code"] == [{"code": "REJ-MCP-RULE-OF-TWO", "n": 1}]
    assert "jean@example.test" not in json.dumps(api)


def test_les_traces_hors_periode_sont_exclues(monde):
    ancien = dt.datetime.now(dt.UTC) - dt.timedelta(days=20)
    _garnir(monde.parent / "autres", maintenant=lambda: ancien)
    texte = _client(monde.parent / "autres").get("/api/observabilite?jours=7").json()
    assert texte["departements"] == []
    assert len(_client(monde.parent / "autres").get("/api/observabilite?jours=30").json()["departements"]) == 2


def test_periode_invalide_refusee_et_bornee(monde):
    client = _client(monde)
    assert client.get("/observabilite?jours=abc").status_code == 422
    assert client.get("/api/observabilite?jours=-5").json()["jours"] == 1
    assert client.get("/api/observabilite?jours=99999").json()["jours"] == 90


def test_un_non_administrateur_relu_en_base_est_refuse(monde):
    client = _client(monde, "employe_fictif")  # la session prétend « nathan_owner » ; la base dit « employee »
    for url in ("/observabilite", "/api/observabilite"):
        assert client.get(url).status_code == 403, url
    assert _client(monde, "inconnu").get("/observabilite").status_code == 403


def test_la_page_est_sous_garde_de_session(monde):
    def refuse(_request, **_):
        raise HTTPException(401, "session requise")

    from opsys import stockage

    app = FastAPI()
    app.include_router(observabilite_ui.creer_router(session_page=refuse, session_api=refuse,
                                                     cnx_factory=stockage.transaction, prefixe="",
                                                     dossier_traces=lambda: monde))
    assert TestClient(app).get("/observabilite").status_code == 401
    assert TestClient(app).get("/api/observabilite").status_code == 401


def test_un_secret_detecte_dans_la_page_donne_une_erreur_500(monde):
    masquage.enregistrer("m05-financecore")
    try:
        assert _client(monde).get("/observabilite").status_code == 500
    finally:
        masquage.oublier("m05-financecore")


def test_la_page_ne_peut_ni_ecrire_ni_purger(monde):
    client = _client(monde)
    avant = sorted(p.name for p in monde.rglob("*"))
    assert client.post("/observabilite", data={"x": "1"}).status_code == 405
    assert client.delete("/api/observabilite").status_code == 405
    assert sorted(p.name for p in monde.rglob("*")) == avant


def test_l_application_reelle_sert_la_page_aux_administrateurs_seulement(monde):
    from opsys import stockage
    from opsys.console import application
    from opsys.console.securite import Configuration
    from opsys.departements import charger_departements

    app = application.creer_application(Configuration("secret-session-obs-fictif-" + "x" * 32), charger_departements(),
                                        stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        assert client.get("/observabilite", follow_redirects=False).status_code in {303, 401, 403}
        assert client.post("/connexion", data={"identifiant": "proprio_fictif", "mot_de_passe": MOT_DE_PASSE},
                           follow_redirects=False).status_code == 303
        page = client.get("/observabilite")
        assert page.status_code == 200 and "m05-financecore" in page.text and "Observabilité" in page.text
    with TestClient(app, base_url="https://testserver/opsys") as client:
        client.post("/connexion", data={"identifiant": "employe_fictif", "mot_de_passe": MOT_DE_PASSE},
                    follow_redirects=False)
        assert client.get("/api/observabilite").status_code in {401, 403}


# -- commandes `traces` ---------------------------------------------------------------------------------------------
def _commande(argv):
    parseur = argparse.ArgumentParser()
    cli_traces.ajouter_commandes(parseur.add_subparsers(dest="commande", required=True))
    return cli_traces.executer(parseur.parse_args(argv))


@pytest.fixture
def cli_monde(opsys_home):
    graine = cle_locale.charger(creer=True)
    journal = JournalTraces(opsys_home / "traces", cle_locale.deriver(graine, "traces/chaine/v1"))
    t = Traceur(journal, MasqueurMotifs(cle_locale.deriver(graine, "pii/v1")))
    with t.appel_outil(outil="m1_filtrer_provenance", departement="m01-front-office", agent="agent-m1",
                       niveau="N0") as s:
        s.attribut("note", "jean@example.test")
        s.conclure("refus", code="REJ-MCP-OUTIL-INCONNU")
    return journal


def test_cli_tableau_texte_et_json(cli_monde, capsys):
    assert _commande(["traces", "tableau"]) == 0
    texte = capsys.readouterr().out
    assert "m01-front-office" in texte and "REJ-MCP-OUTIL-INCONNU" in texte and "pas la facture" in texte
    assert _commande(["traces", "tableau", "--json", "--jours", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["departements"][0]["refus"] == 1


def test_cli_tableau_sans_trace(opsys_home, capsys):
    assert _commande(["traces", "tableau"]) == 0
    assert "Aucune trace" in capsys.readouterr().out


def test_cli_verifier_detecte_l_alteration(cli_monde, capsys):
    assert _commande(["traces", "verifier"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    chemin = cli_monde.segments()[0]
    chemin.write_text(chemin.read_text().replace('"issue":"refus"', '"issue":"ok"'))
    assert _commande(["traces", "verifier"]) == 1
    assert json.loads(capsys.readouterr().out)["problemes"]


def test_cli_verifier_sans_cle_refuse_en_2(opsys_home, capsys):
    assert _commande(["traces", "verifier"]) == 2
    assert "REJ-OBS-CLE-ABSENTE" in capsys.readouterr().err


def test_cli_purger_est_a_blanc_sans_confirmation(cli_monde, capsys):
    assert _commande(["traces", "purger"]) == 0
    assert json.loads(capsys.readouterr().out) == {"confirme": False, "segments": []}
    assert cli_monde.segments()


def test_cli_exporter_langfuse_refuse_sans_transport_et_compte_a_blanc(cli_monde, capsys):
    assert _commande(["traces", "exporter", "--destination", "langfuse"]) == 2
    assert "REJ-OBS-DESTINATION-NON-CONFIGUREE" in capsys.readouterr().err
    assert _commande(["traces", "exporter", "--destination", "langfuse", "--a-blanc"]) == 0
    assert json.loads(capsys.readouterr().out) == {"destination": "langfuse", "a_envoyer": 1, "retenus_pii": 0}
    cli_monde.ajouter(Span(trace_id="a" * 32, span_id="b" * 16, type="appel_outil", debut="2026-11-01T12:00:00.000Z",
                           duree_ms=1, departement="m01-front-office", agent="agent-m1", issue="ok",
                           attributs={"note": "jean@example.test"}))  # hors traceur : la garde de sortie le retient
    assert _commande(["traces", "exporter", "--destination", "langfuse", "--a-blanc"]) == 1
    assert json.loads(capsys.readouterr().out)["retenus_pii"] == 1


def test_cli_masquer_et_mesurer(opsys_home, capsys):
    assert _commande(["traces", "masquer", "--texte", "écrire à jean@example.test"]) == 0
    sortie = capsys.readouterr().out
    assert "jean@example.test" not in sortie and "[[COURRIEL:" in sortie
    assert _commande(["traces", "masquer", "--mesurer"]) == 0
    mesure = json.loads(capsys.readouterr().out)
    assert mesure["global"]["precision"] >= 0.95 and mesure["limites_confirmees"]


def test_cli_dossier_explicite(tmp_path, capsys):
    assert _commande(["traces", "--dossier", str(tmp_path / "vide"), "tableau"]) == 0
    assert "Aucune trace" in capsys.readouterr().out
