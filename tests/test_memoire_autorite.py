"""Autorité de lecture mémoire : fixtures fictives, aucun service externe."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from agents_base_qa import provisionner_base_qa
from memoire.autorite import emettre_ticket as _ticket
from memoire.autorite import lier_affaire as _lier

from opsys import contexte, stockage
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste, racine_departements
from opsys.memoire import autorite, outils


@pytest.fixture
def base_memoire_autorite(tmp_path, monkeypatch):
    stockage.liberer()
    monkeypatch.setenv("OPSYS_BASE_URL", "sqlite:///" + str(tmp_path / "canon-fictif.db"))
    stockage.migrer()
    dep = lire_manifeste(racine_departements() / "m01-front-office")
    cap = Capacites({dep.id: dep}, stockage.transaction, appelant=dep.id)
    policy = {"version": 1, "departements": {dep.id: "client_session"},
              "agents": {dep.id: {"departement": dep.id, "mode": "client_session"}},
              "procedures_globales": ["procedures"]}
    # La composition HTTP pose ces deux valeurs côté serveur, jamais depuis les arguments MCP.
    cap._memoire_politique = lambda: policy
    cap._memoire_versionnee = True
    appels = []
    class MemoireFictive:
        def rechercher(self, requete, embedding, k, filtres, *, embedding_profile_sha256=None):
            assert embedding_profile_sha256 is None
            appels.append(filtres)
            ligne = SimpleNamespace(fragment_id=2, texte="Fictif: préférence du client B", source="fictif:B",
                portee="signaux", departement=dep.id, cree_le=dt.datetime.now(dt.UTC), score=.1,
                citations_verifiees=(), titre=None, sujets=("client:C-FICTIF-B",), sensibilite="personnelle")
            return SimpleNamespace(mode="plein_texte", resultats=(ligne,))
    monkeypatch.setattr(outils, "_memoire", MemoireFictive)
    monkeypatch.setattr(outils, "_embeddings", lambda: (None, "fictif sans provider"))
    yield cap, policy, appels
    stockage.liberer()


def test_client_sans_ticket_refuse_avant_recherche(base_memoire_autorite):
    cap, _, appels = base_memoire_autorite
    rep = cap.appeler("opsys_memoire_rechercher", {"requete": "préférence", "sujet": "client:C-FICTIF-B"})
    assert rep["ok"] is False
    assert appels == []


def test_ancienne_route_client_ne_devient_pas_globale(base_memoire_autorite):
    cap, _, appels = base_memoire_autorite
    cap._memoire_versionnee = False
    rep = cap.appeler("opsys_memoire_rechercher", {"requete": "préférence"})
    assert rep["ok"] is False
    assert appels == []


def test_projection_absente_ne_devient_pas_globale(base_memoire_autorite):
    cap, _, appels = base_memoire_autorite
    def indisponible():
        raise ValueError("classification absente")
    cap._memoire_politique = indisponible
    rep = cap.appeler("opsys_memoire_rechercher", {"requete": "préférence"})
    assert rep["ok"] is False
    assert appels == []


def test_appareil_memoire_reste_ferme(base_memoire_autorite):
    cap, policy, appels = base_memoire_autorite
    policy["departements"]["m01-front-office"] = "global"
    policy["agents"]["m01-front-office"]["mode"] = "global"
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin_fictif", "admin")):
        rep = cap.appeler("opsys_memoire_rechercher", {"requete": "préférence"})
    assert rep["ok"] is False
    assert appels == []


def test_global_departement_autorise_conserve_sa_lecture(base_memoire_autorite):
    cap, policy, appels = base_memoire_autorite
    policy["departements"]["m01-front-office"] = "global"
    policy["agents"]["m01-front-office"]["mode"] = "global"
    rep = cap.appeler("opsys_memoire_rechercher", {"requete": "préférence", "sujet": "client:C-FICTIF-B"})
    assert rep["ok"] is True
    assert appels == [{"portee": ["signaux"], "sujet": "client:C-FICTIF-B"}]


def test_omission_force_le_client_m2_sans_inventer_client_lead(base_memoire_autorite):
    cap, policy, appels = base_memoire_autorite
    session, client, _ = _lier()
    args = {"requete": "préférence"}
    ticket = _ticket(policy, session, args)
    rep = cap.appeler(autorite.NOM_OUTIL, args, ticket_memoire=ticket)
    assert rep["ok"] is True
    assert appels == [{"portee": ["signaux"], "sujets_autorises": ["client:" + client],
                       "portees_globales": ["procedures"]}]
    assert "LEAD-FICTIF-A" not in str(appels)
    # Un rejeu ne sert jamais une réponse personnelle précédemment mise en cache.
    assert cap.appeler(autorite.NOM_OUTIL, args, ticket_memoire=ticket)["ok"] is False
    assert len(appels) == 1


def test_autre_client_et_arguments_changes_refusent_avant_embedding(base_memoire_autorite):
    cap, policy, appels = base_memoire_autorite
    session, _, _ = _lier()
    with pytest.raises(ValueError, match="SUJET-HORS-AUTORITE"):
        _ticket(policy, session, {"requete": "préférence", "sujet": "client:B"})
    args = {"requete": "préférence"}
    ticket = _ticket(policy, session, args)
    assert cap.appeler(autorite.NOM_OUTIL, {**args, "sujet": "client:B"}, ticket_memoire=ticket)["ok"] is False
    assert appels == []


def test_reference_client_absente_refuse_sans_ticket(base_memoire_autorite):
    from sqlalchemy import select

    from opsys.stockage.schema import LIAISONS_TICKETS
    _, policy, _ = base_memoire_autorite
    session, _, _ = _lier(associer=False)
    with pytest.raises(ValueError, match="REFERENCE-CLIENT-ABSENTE"):
        _ticket(policy, session, {"requete": "préférence"})
    with stockage.transaction() as cnx:
        assert cnx.execute(select(LIAISONS_TICKETS)).all() == []


@pytest.mark.parametrize("pendant", [False, True])
def test_retrait_liaison_avant_ou_pendant_lecture_ne_retourne_pas_resultat(base_memoire_autorite, monkeypatch, pendant):
    from m10_memoire import liaison
    from m10_memoire import registre as m10
    cap, policy, appels = base_memoire_autorite
    session, _, lien = _lier()
    args = {"requete": "préférence"}
    ticket = _ticket(policy, session, args)
    def retirer():
        with stockage.transaction():
            journal = m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
            assert liaison.revoquer_session_affaire(session, lien["ligne_id"], "owner_fictif", "admin", "appareil",
                "retrait fictif", "2026-10-02T10:01:00+00:00", journal)[1] is None
    if pendant:
        original = outils._memoire()
        class RetraitPendantLecture:
            def rechercher(self, *args, embedding_profile_sha256=None):
                assert embedding_profile_sha256 is None
                resultat = original.rechercher(*args, embedding_profile_sha256=embedding_profile_sha256)
                retirer()
                return resultat
        monkeypatch.setattr(outils, "_memoire", RetraitPendantLecture)
    else:
        retirer()
    rep = cap.appeler(autorite.NOM_OUTIL, args, ticket_memoire=ticket)
    assert rep["ok"] is False
    assert "resultat" not in rep
    assert len(appels) == int(pendant)


def test_liaison_remplacee_et_classification_modifiee_annulent_ticket(base_memoire_autorite):
    cap, policy, appels = base_memoire_autorite
    session, _, _ = _lier()
    args = {"requete": "préférence"}
    ticket = _ticket(policy, session, args)
    _lier("LEAD-FICTIF-B", session)
    assert cap.appeler(autorite.NOM_OUTIL, args, ticket_memoire=ticket)["ok"] is False
    nouveau = _ticket(policy, session, args)
    policy["agents"]["m01-front-office"]["mode"] = "global"
    policy["departements"]["m01-front-office"] = "global"
    assert cap.appeler(autorite.NOM_OUTIL, args, ticket_memoire=nouveau)["ok"] is False
    assert appels == []


def test_ticket_expire_refuse_avant_embedding(base_memoire_autorite):
    from sqlalchemy import update

    from opsys.stockage.schema import LIAISONS_TICKETS
    cap, policy, appels = base_memoire_autorite
    session, _, _ = _lier()
    args = {"requete": "préférence"}
    ticket = _ticket(policy, session, args)
    with stockage.transaction() as cnx:
        cnx.execute(update(LIAISONS_TICKETS).values(
            expire_le=(dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)).isoformat()))
    rep = cap.appeler(autorite.NOM_OUTIL, args, ticket_memoire=ticket)
    assert rep["ok"] is False and "resultat" not in rep
    assert appels == []


def test_revalidation_emission_retire_ticket_si_classification_change(base_memoire_autorite):
    from sqlalchemy import select

    from opsys.stockage.schema import LIAISONS_TICKETS
    _, policy, _ = base_memoire_autorite
    session, _, _ = _lier()
    lectures = 0
    def lire():
        nonlocal lectures
        lectures += 1
        if lectures == 2:
            raise ValueError("fragment supprimé pendant émission")
        return policy
    outil = autorite.outil_emission(stockage.transaction, "m01-front-office", lire)
    with pytest.raises(ValueError, match="fragment supprimé"):
        outil.fonction("m01-front-office", session, {"requete": "préférence"})
    assert lectures == 2
    with stockage.transaction() as cnx:
        assert cnx.execute(select(LIAISONS_TICKETS)).all() == []


def test_procedures_globales_seules_bornees_sans_affaire(tmp_path, monkeypatch):
    stockage.liberer()
    monkeypatch.setenv("OPSYS_BASE_URL", "sqlite:///" + str(tmp_path / "canon-procedures-fictif.db"))
    stockage.migrer()
    dep = lire_manifeste(racine_departements() / "m03-estimation")
    policy = {"version": 1, "departements": {dep.id: "client_session"},
        "agents": {dep.id: {"departement": dep.id, "mode": "client_session"}}, "procedures_globales": ["procedures"]}
    appels = []
    class MemoireProcedures:
        def rechercher(self, requete, embedding, k, filtres, *, embedding_profile_sha256=None):
            assert embedding is None and embedding_profile_sha256 is None
            appels.append(filtres)
            return SimpleNamespace(mode="plein_texte", resultats=())
    monkeypatch.setattr(outils, "_memoire", MemoireProcedures)
    monkeypatch.setattr(outils, "_embeddings", lambda: (None, "provider fictif indisponible"))
    cap = Capacites({dep.id: dep}, stockage.transaction, appelant=dep.id,
        memoire_politique=lambda: policy, memoire_versionnee=True)
    try:
        reponse = cap.appeler(autorite.NOM_OUTIL, {"requete": "procédure", "portees": ["procedures"]})
        assert reponse["ok"] is True and reponse["resultat"]["mode"] == "plein_texte"
        assert "provider fictif indisponible" in reponse["resultat"]["avertissement"]
        assert appels == [{"portee": ["procedures"], "sujets_autorises": [], "portees_globales": ["procedures"]}]
    finally:
        stockage.liberer()


def test_http_ancien_et_v1_refusent_client_sans_ticket_et_issuer_est_prive(base_memoire_autorite, monkeypatch):
    import asyncio
    import json

    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from opsys.serveur_mcp import application_http_departements
    cap, policy, appels = base_memoire_autorite
    m10 = lire_manifeste(racine_departements() / "m10-memoire")
    dep = lire_manifeste(racine_departements() / "m01-front-office")
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    public, prive = "jeton-public-fictif-0123456789", "jeton-prive-fictif-0123456789"
    app = application_http_departements({dep.id: dep, m10.id: m10}, stockage.transaction, public,
        jeton_contexte=prive, memoire_politique=lambda: policy)
    session, client, _ = _lier()
    args = {"requete": "préférence fictive"}
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://opsys.test",
                headers={"Authorization": "Bearer " + public}) as http, \
                app._application.router.lifespan_context(app._application):
            for route in ("/mcp/m01-front-office", "/mcp/v1/m01-front-office"):
                async with streamable_http_client("http://opsys.test" + route, http_client=http) as (read, write), \
                        ClientSession(read, write) as business:
                    await business.initialize()
                    catalogue = await business.list_tools()
                    assert autorite.NOM_EMISSION not in {o.name for o in catalogue.tools}
                    refus = await business.call_tool(autorite.NOM_OUTIL, args)
                    assert refus.is_error is True
                    assert json.loads(refus.content[0].text)["ok"] is False
            refus = await http.post("/mcp/contexte/m01-front-office", json={})
            assert refus.status_code == 401
            http.headers["Authorization"] = "Bearer " + prive
            async with streamable_http_client(
                    "http://opsys.test/mcp/contexte/m01-front-office", http_client=http) as (read, write), \
                    ClientSession(read, write) as interne:
                await interne.initialize()
                issued = await interne.call_tool(autorite.NOM_EMISSION,
                    {"agent_id": dep.id, "cle_session": session, "arguments": args})
                assert issued.is_error is not True
                ticket = json.loads(issued.content[0].text)["resultat"]["ticket"]
            http.headers["Authorization"] = "Bearer " + public
            async with streamable_http_client(
                    "http://opsys.test/mcp/v1/m01-front-office", http_client=http) as (read, write), \
                    ClientSession(read, write) as business:
                await business.initialize()
                rep = await business.call_tool(autorite.NOM_OUTIL, args, meta={autorite.META: ticket})
                assert rep.is_error is not True
                replay = await business.call_tool(autorite.NOM_OUTIL, args, meta={autorite.META: ticket})
                assert replay.is_error is True
    asyncio.run(scenario())
    assert len(appels) == 1
    assert appels[0]["sujets_autorises"] == ["client:" + client]


def test_fragment_relu_borne_et_malforme_refuse(tmp_path):
    import json
    dossier = tmp_path / "opsys"
    dossier.mkdir()
    fichier = dossier / autorite.FICHIER
    with pytest.raises(ValueError, match="ABSENTE"):
        autorite.lire_politique(tmp_path)
    fichier.write_text(json.dumps({"version": 1, "departements": {"m01-front-office": []},
        "agents": {}, "procedures_globales": ["procedures"]}))
    with pytest.raises(ValueError, match="INVALIDE"):
        autorite.lire_politique(tmp_path)
    fichier.write_bytes(b" " * 131073)
    with pytest.raises(ValueError, match="volumineux"):
        autorite.lire_politique(tmp_path)


def test_generateur_classe_client_session_et_departement_global_explicitement(tmp_path, session):
    import json

    from opsys import openclaw
    from opsys.departements import charger_departements
    deps = charger_departements()
    paliers = {"rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
        "fort": {"provider": "anthropic", "model": "claude-sonnet-5"},
        "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"}}
    provisionner_base_qa(session, deps)
    fichiers = openclaw.generer(deps, tmp_path, paliers,
        environ={"OPSYS_EMBEDDINGS_URL": "http://embeddings-fictif:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"},
        contexte_entreprise={"m01-front-office": [], "m03-estimation": ["m3_estimer_projet"]},
        affaire_par_session=["m01-front-office"], cnx_factory=session)
    policy = autorite.lire_politique(tmp_path)
    assert policy["departements"]["m01-front-office"] == "client_session"
    assert policy["departements"]["m03-estimation"] == "global"
    assert policy["agents"]["m01-front-office"] == {"departement": "m01-front-office", "mode": "client_session"}
    assert policy["agents"]["m03-estimation"] == {"departement": "m03-estimation", "mode": "global"}
    servers = json.loads(fichiers["mcp"].read_text())["servers"]
    assert servers["opsys_m1"]["url"] == "http://opsys:8765/mcp/v1/m01-front-office"
    assert servers["opsys_m3"]["url"] == "http://opsys:8765/mcp/v1/m03-estimation"
    assert servers["opsys_context_m01-front-office"]["headers"] == {
        "Authorization": "Bearer ${OPSYS_CONTEXT_MCP_JETON}"}
