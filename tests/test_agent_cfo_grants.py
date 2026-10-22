from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agents_base_qa import provisionner_base_qa

from opsys import agent_cfo_grants, agents, contexte, departements, identite

OWNER = "owner.cfo.fictif"
TOOLS = sorted(agent_cfo_grants.OUTILS)


def _spec():
    return {
        "id": "m5-cfo-agent",
        "departement": "m05-financecore",
        "responsabilite": "Préparer un état CFO fictif.",
        "palier_modele": "rapide",
        "outils": TOOLS,
        "budget_jour": 10000,
        "budget_mois": 100000,
        "limite_tours": 8,
        "limite_reessais": 1,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }


@pytest.fixture
def finance_profile(session, monkeypatch):
    deps = departements.charger_departements()
    with session() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", "mot-de-passe-fictif-1234", ["nathan_owner"])
        profile = agents.creer(cnx, deps, _spec(), par=OWNER, mutation_id="create-cfo-0001")
        active = agents.definir_actif(
            cnx, profile["id"], deps, True, par=OWNER, mutation_id="activate-cfo-0001", revision_attendue=1
        )
    with session() as cnx:
        active["instance_id"] = agent_cfo_grants.instance_id(cnx)
    return active


def _as_owner():
    return contexte.appele_par_appareil(contexte.IdentiteAppelante(OWNER, "nathan_owner", source="console"))


def _grant(session, profile):
    with _as_owner(), session() as cnx:
        current = agent_cfo_grants.lire(cnx, profile["id"], instance_id=profile["instance_id"])
        return agent_cfo_grants.accorder(
            cnx,
            profile["id"],
            par=OWNER,
            instance_id=profile["instance_id"],
            revision_attendue=profile["revision"],
            version_attendue=current["version"] if current else 0,
            date_debut_rapport="2026-10-01",
            date_fin_rapport="2026-10-31",
        )


def _issue(session, profile, tool, args, revision=None):
    with session() as cnx:
        return agent_cfo_grants.emettre(
            cnx,
            profile["id"],
            tool,
            args,
            instance_id=profile["instance_id"],
            revision_profil=profile["revision"] if revision is None else revision,
        )


def _consume(session, ticket, tool, args, instance):
    with session() as cnx:
        agent_cfo_grants.consommer(cnx, ticket, tool, args, instance_id=instance)


def test_owner_grant_route_bound_ticket_and_one_use(finance_profile, session):
    args = {"aujourd_hui": "2026-10-01", "question_posee": "Faut-il prévoir?"}
    grant = _grant(session, finance_profile)
    assert grant["active"] and grant["profile_revision"] == finance_profile["revision"]
    assert set(grant["tools"]) == agent_cfo_grants.OUTILS
    issued = _issue(session, finance_profile, "m5_preparer_dossier_decision_cfo", args)
    _consume(session, issued["ticket"], "m5_preparer_dossier_decision_cfo", args, finance_profile["instance_id"])
    with pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="réutilisé"):
        _consume(session, issued["ticket"], "m5_preparer_dossier_decision_cfo", args, finance_profile["instance_id"])


def test_absence_mauvais_tool_instance_et_arguments_refusent(finance_profile, session):
    args = {"aujourd_hui": "2026-10-01", "question_posee": "Fictif"}
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="absent"):
        agent_cfo_grants.emettre(
            cnx,
            finance_profile["id"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=finance_profile["instance_id"],
            revision_profil=finance_profile["revision"],
        )
    _grant(session, finance_profile)
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        agent_cfo_grants.emettre(
            cnx,
            finance_profile["id"],
            "m5_enregistrer_paiement_facture",
            args,
            instance_id=finance_profile["instance_id"],
            revision_profil=finance_profile["revision"],
        )
    issued = _issue(session, finance_profile, "m5_preparer_dossier_decision_cfo", args)
    with pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        _consume(
            session,
            issued["ticket"],
            "m5_preparer_dossier_decision_cfo",
            {**args, "question_posee": "Altéré"},
            finance_profile["instance_id"],
        )
    with pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        _consume(session, issued["ticket"], "m5_preparer_dossier_decision_cfo", args, "autre-instance")


def test_grant_empty_allowlist_stale_version_and_dates_are_closed(finance_profile, session):
    _grant(session, finance_profile)
    with _as_owner(), session() as cnx:
        current = agent_cfo_grants.lire(cnx, finance_profile["id"], instance_id=finance_profile["instance_id"])
        with pytest.raises(ValueError, match="seuls les deux outils"):
            agent_cfo_grants.accorder(
                cnx,
                finance_profile["id"],
                par=OWNER,
                instance_id=finance_profile["instance_id"],
                revision_attendue=finance_profile["revision"],
                version_attendue=current["version"],
                date_debut_rapport="2026-10-01",
                date_fin_rapport="2026-10-31",
                outils=[],
            )
        with pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="version de grant périmée"):
            agent_cfo_grants.accorder(
                cnx,
                finance_profile["id"],
                par=OWNER,
                instance_id=finance_profile["instance_id"],
                revision_attendue=finance_profile["revision"],
                version_attendue=current["version"] - 1,
                date_debut_rapport="2026-10-01",
                date_fin_rapport="2026-10-31",
            )


def test_ticket_does_not_outlive_grant(finance_profile, session, monkeypatch):
    start = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(agent_cfo_grants, "_now", lambda: start)
    with _as_owner(), session() as cnx:
        agent_cfo_grants.accorder(
            cnx,
            finance_profile["id"],
            par=OWNER,
            instance_id=finance_profile["instance_id"],
            revision_attendue=finance_profile["revision"],
            version_attendue=0,
            date_debut_rapport="2026-10-01",
            date_fin_rapport="2026-10-31",
            expire_le=(start + timedelta(seconds=1)).isoformat(),
        )
    args = {"aujourd_hui": "2026-10-01", "question_posee": "Rapport avant échéance"}
    issued = _issue(session, finance_profile, "m5_preparer_dossier_decision_cfo", args)
    monkeypatch.setattr(agent_cfo_grants, "_now", lambda: start + timedelta(seconds=2))
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        agent_cfo_grants.consommer(
            cnx,
            issued["ticket"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=finance_profile["instance_id"],
        )


def test_ticket_refuse_si_le_createur_du_grant_est_inactif(finance_profile, session, monkeypatch):
    args = {"aujourd_hui": "2026-10-01", "question_posee": "Rapport fictif"}
    _grant(session, finance_profile)
    issued = _issue(session, finance_profile, "m5_preparer_dossier_decision_cfo", args)
    with session() as cnx:
        identite.activer(cnx, OWNER, False)
    from m5_financecore import outils as m5_outils

    m5_outils.utiliser_stockage_durable()
    tool = next(item for item in m5_outils.outils() if item.nom == "m5_preparer_dossier_decision_cfo")
    reads = 0
    original = m5_outils._lectures_finance

    def count_read(*call_args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*call_args, **kwargs)

    monkeypatch.setattr(m5_outils, "_lectures_finance", count_read)
    with contexte.appele_avec_ticket_agent_cfo(issued["ticket"], args), pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        tool.fonction(**args)
    assert reads == 0
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="autorité invalidée"):
        agent_cfo_grants.consommer(
            cnx,
            issued["ticket"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=finance_profile["instance_id"],
        )


def test_revisions_profil_perimee_refuse_avant_lecture_financiere(finance_profile, session, monkeypatch):
    from m5_financecore import outils as m5_outils

    args = {"aujourd_hui": "2026-10-01", "question_posee": "Rapport fictif"}
    _grant(session, finance_profile)
    issued = _issue(session, finance_profile, "m5_preparer_dossier_decision_cfo", args)
    with _as_owner(), session() as cnx:
        agents.modifier(
            cnx,
            finance_profile["id"],
            departements.charger_departements(),
            _spec(),
            par=OWNER,
            mutation_id="modify-cfo-after-ticket-0001",
            revision_attendue=finance_profile["revision"],
        )
    m5_outils.utiliser_stockage_durable()
    tool = next(item for item in m5_outils.outils() if item.nom == "m5_preparer_dossier_decision_cfo")
    reads = 0
    original = m5_outils._lectures_finance

    def count_read(*call_args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*call_args, **kwargs)

    monkeypatch.setattr(m5_outils, "_lectures_finance", count_read)
    with contexte.appele_avec_ticket_agent_cfo(issued["ticket"], args), pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        tool.fonction(**args)
    assert reads == 0


def test_revocation_profile_revision_and_grantor_role_revocation_kill_ticket(finance_profile, session):
    args = {"aujourd_hui": "2026-10-01", "question_posee": "Fictif"}
    _grant(session, finance_profile)
    issued = _issue(session, finance_profile, "m5_preparer_dossier_decision_cfo", args)
    with _as_owner(), session() as cnx:
        agent_cfo_grants.revoquer(
            cnx,
            finance_profile["id"],
            par=OWNER,
            instance_id=finance_profile["instance_id"],
            version_attendue=1,
        )
    with pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        _consume(session, issued["ticket"], "m5_preparer_dossier_decision_cfo", args, finance_profile["instance_id"])

    # A regrant is bound to current persisted profile revision; old generated revisions cannot mint.
    with _as_owner(), session() as cnx:
        new_profile = agents.modifier(
            cnx,
            finance_profile["id"],
            departements.charger_departements(),
            _spec(),
            par=OWNER,
            mutation_id="modify-cfo-0001",
            revision_attendue=finance_profile["revision"],
        )
    new_profile["instance_id"] = finance_profile["instance_id"]
    _grant(session, new_profile)
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="révision"):
        agent_cfo_grants.emettre(
            cnx,
            new_profile["id"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=finance_profile["instance_id"],
            revision_profil=finance_profile["revision"],
        )
    issued_after_regrant = _issue(session, new_profile, "m5_preparer_dossier_decision_cfo", args)

    # A grant is only as good as the human who issued it: role and active state are rechecked on use.
    with session() as cnx:
        identite.retirer_role(cnx, OWNER, "nathan_owner")
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="autorité humaine révoquée"):
        agent_cfo_grants.emettre(
            cnx,
            new_profile["id"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=finance_profile["instance_id"],
            revision_profil=new_profile["revision"],
        )
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="invalidée"):
        agent_cfo_grants.consommer(
            cnx,
            issued_after_regrant["ticket"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=finance_profile["instance_id"],
        )


def test_expiry_quota_and_allowed_report_date_are_independent(finance_profile, session, monkeypatch):
    with _as_owner(), session() as cnx:
        agent_cfo_grants.accorder(
            cnx,
            finance_profile["id"],
            par=OWNER,
            instance_id=finance_profile["instance_id"],
            version_attendue=0,
            revision_attendue=finance_profile["revision"],
            date_debut_rapport="2026-10-01",
            date_fin_rapport="2026-10-31",
            rapports_par_jour=1,
            expire_le=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        )
    args = {"aujourd_hui": "2026-10-12", "question_posee": "Fictif"}
    _issue(session, finance_profile, "m5_preparer_dossier_decision_cfo", args)
    outside_range = {**args, "aujourd_hui": "1999-01-01"}
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="intervalle autorisé"):
        agent_cfo_grants.emettre(
            cnx,
            finance_profile["id"],
            "m5_preparer_dossier_decision_cfo",
            outside_range,
            instance_id=finance_profile["instance_id"],
            revision_profil=finance_profile["revision"],
        )
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="quota"):
        agent_cfo_grants.emettre(
            cnx,
            finance_profile["id"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=finance_profile["instance_id"],
            revision_profil=finance_profile["revision"],
        )
    monkeypatch.setattr(agent_cfo_grants, "_now", lambda: datetime.now(UTC) + timedelta(days=2))
    with session() as cnx, pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="expiré"):
        agent_cfo_grants.emettre(
            cnx,
            finance_profile["id"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=finance_profile["instance_id"],
            revision_profil=finance_profile["revision"],
        )


def test_cfo_handler_requires_ticket_before_snapshot_and_reads_with_valid_ticket(finance_profile, session, monkeypatch):
    from m5_financecore import outils as m5_outils

    m5_outils.utiliser_stockage_durable()
    tool = next(item for item in m5_outils.outils() if item.nom == "m5_preparer_dossier_decision_cfo")
    args = {"aujourd_hui": "2026-10-01", "question_posee": "Rapport fictif"}
    _grant(session, finance_profile)
    issued = _issue(session, finance_profile, tool.nom, args)
    reads = 0
    original = m5_outils._lectures_finance

    def count_read(*call_args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*call_args, **kwargs)

    monkeypatch.setattr(m5_outils, "_lectures_finance", count_read)
    with contexte.appele_avec_ticket_agent_cfo("x" * 48, args), pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        tool.fonction(**args)
    assert reads == 0
    with contexte.appele_avec_ticket_agent_cfo(issued["ticket"], args):
        result = tool.fonction(**args)
    assert result["accepte"] is True
    assert reads == 1
    inspect = __import__("inspect")
    parameters = inspect.signature(tool.fonction).parameters
    assert list(parameters) == ["aujourd_hui", "question_posee", "volet"]
    assert parameters["aujourd_hui"].default is inspect.Parameter.empty
    assert parameters["question_posee"].default is inspect.Parameter.empty
    assert parameters["volet"].default is None
    assert parameters["volet"].kind is inspect.Parameter.KEYWORD_ONLY


def test_agent_capital_read_reuses_cfo_chain_validation_before_calculation(
    finance_profile, session, monkeypatch, tmp_path
):
    import importlib.util

    from m5_financecore import outils as m5_outils

    helper_path = Path(__file__).resolve().parents[1] / "departments/m05-financecore/tests/test_dossier_decision_cfo.py"
    spec = importlib.util.spec_from_file_location("cfo_test_helpers", helper_path)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    _corrompre_maillon = helpers._corrompre_maillon
    _declarer_configuration = helpers._declarer_configuration
    _peupler_snapshot_connu = helpers._peupler_snapshot_connu

    m5_outils.utiliser_stockage_durable()
    _declarer_configuration(tmp_path, monkeypatch)
    _peupler_snapshot_connu()
    args = {
        "actif": "camion fictif",
        "prix": "10000.00",
        "source_prix": "offre fictive",
        "prix_valide_jusqua": "2026-10-31",
        "aujourd_hui": "2026-10-01",
        "offre_financement": {
            "source": "banque fictive",
            "mise_de_fonds": "1000.00",
            "paiement_mensuel": "500.00",
            "mois": 24,
        },
        "offre_location": {
            "source": "locateur fictif",
            "mise_de_fonds": "0.00",
            "paiement_mensuel": "600.00",
            "mois": 24,
        },
    }
    _grant(session, finance_profile)
    issued = _issue(session, finance_profile, "m5_preparer_decision_capital", args)
    _corrompre_maillon("principal", 1, "montant", "999999.99")
    calculations = 0
    original = m5_outils.decision_capital.preparer

    def count_calculation(*call_args, **kwargs):
        nonlocal calculations
        calculations += 1
        return original(*call_args, **kwargs)

    monkeypatch.setattr(m5_outils.decision_capital, "preparer", count_calculation)
    tool = next(item for item in m5_outils.outils() if item.nom == "m5_preparer_decision_capital")
    with contexte.appele_avec_ticket_agent_cfo(issued["ticket"], args):
        result = tool.fonction(**args)
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-CFO-CHAINE-INVALIDE"
    assert calculations == 0


def test_mcp_http_private_issuer_and_business_ticket_transport(finance_profile, session, monkeypatch):
    import asyncio
    import json
    from pathlib import Path

    import httpx
    from m5_financecore import outils as m5_outils
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from opsys import serveur_mcp

    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    root = Path(__file__).parents[1] / "departments"
    deps = departements.charger_departements(root)
    m5_outils.utiliser_stockage_durable()
    reads = 0
    original_read = m5_outils._lectures_finance

    def count_finance_read(*call_args, **kwargs):
        nonlocal reads
        reads += 1
        return original_read(*call_args, **kwargs)

    monkeypatch.setattr(m5_outils, "_lectures_finance", count_finance_read)
    public = "public-token-fictif-0123456789"
    private = "runtime-token-fictif-0123456789"
    app = serveur_mcp.application_http_departements(deps, session, public, jeton_contexte=private)
    args = {"aujourd_hui": "2026-10-01", "question_posee": "Rapport HTTP fictif"}
    _grant(session, finance_profile)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://opsys.test") as http:
            missing_auth = await http.get(f"/mcp/runtime/{finance_profile['id']}")
            assert missing_auth.status_code == 401
            async with app._application.router.lifespan_context(app._application):
                async with streamable_http_client(
                    f"http://opsys.test/mcp/runtime/{finance_profile['id']}",
                    http_client=http,
                ) as (read, write):
                    http.headers["Authorization"] = f"Bearer {private}"
                    async with ClientSession(read, write) as runtime:
                        await runtime.initialize()
                        issued = await runtime.call_tool(
                            "opsys_runtime_cfo_ticket",
                            {
                                "outil": "m5_preparer_dossier_decision_cfo",
                                "arguments": args,
                                "revision_profil": finance_profile["revision"],
                            },
                        )
                        grant = json.loads(issued.content[0].text)
                        assert grant["ok"] is True, grant
                        ticket = grant["resultat"]["ticket"]
                        assert len(ticket) >= 32
                        # The profile revision comes from the host config and must be current.
                        stale = await runtime.call_tool(
                            "opsys_runtime_cfo_ticket",
                            {
                                "outil": "m5_preparer_dossier_decision_cfo",
                                "arguments": args,
                                "revision_profil": finance_profile["revision"] + 1,
                            },
                        )
                        assert stale.is_error is True
                        invalid_schema = await runtime.call_tool(
                            "opsys_runtime_cfo_ticket",
                            {
                                "outil": "m5_preparer_dossier_decision_cfo",
                                "arguments": {**args, "champ_inconnu": "ne doit pas passer"},
                                "revision_profil": finance_profile["revision"],
                            },
                        )
                        assert invalid_schema.is_error is True

                async with streamable_http_client("http://opsys.test/mcp/m05-financecore", http_client=http) as (
                    read,
                    write,
                ):
                    http.headers["Authorization"] = f"Bearer {public}"
                    async with ClientSession(read, write) as business:
                        await business.initialize()
                        capital_args = {
                            "actif": "véhicule fictif",
                            "prix": "10000.00",
                            "source_prix": "offre fictive",
                            "prix_valide_jusqua": "2026-10-31",
                            "aujourd_hui": "2026-10-01",
                            "offre_financement": {
                                "source": "banque fictive",
                                "mise_de_fonds": "1000.00",
                                "paiement_mensuel": "500.00",
                                "mois": 24,
                            },
                            "offre_location": {
                                "source": "locateur fictif",
                                "mise_de_fonds": "0.00",
                                "paiement_mensuel": "600.00",
                                "mois": 24,
                            },
                            "autorise_couts": True,
                            "role": "nathan_owner",
                        }
                        no_ticket = await business.call_tool("m5_preparer_decision_capital", capital_args)
                        assert json.loads(no_ticket.content[0].text) == {
                            "ok": False,
                            "erreur": "autorisation_cfo_requise",
                        }
                        assert reads == 0
                        accepted = await business.call_tool(
                            "m5_preparer_dossier_decision_cfo",
                            args,
                            meta={"opsys/cfoGrantTicket": ticket},
                        )
                        accepted_response = json.loads(accepted.content[0].text)
                        assert accepted_response["ok"] is True, accepted.content[0].text
                        assert accepted_response["resultat"]["accepte"] is True, accepted.content[0].text
                        assert reads > 0
                        mixed = await business.call_tool(
                            "m5_preparer_dossier_decision_cfo",
                            args,
                            meta={
                                "opsys/cfoGrantTicket": ticket,
                                "opsys/personne": OWNER,
                                "opsys/role": "nathan_owner",
                            },
                        )
                        assert json.loads(mixed.content[0].text)["erreur"] == "ticket_cfo_hors_portee"

    asyncio.run(run())


def test_generated_runtime_profile_includes_persisted_revision(finance_profile, session, tmp_path):
    import json

    from opsys import openclaw

    deps = departements.charger_departements(Path(__file__).parents[1] / "departments")
    provisionner_base_qa(session, deps)
    files = openclaw.generer(
        deps,
        tmp_path / "core-config",
        {
            "rapide": {"provider": "fixture", "model": "synthetic-fast"},
            "standard": {"provider": "fixture", "model": "synthetic-standard"},
            "local": {"provider": "custom", "model": "synthetic-local", "base_url": "http://127.0.0.1:1/v1"},
            "fort": {"provider": "fixture", "model": "synthetic-strong"},
        },
        environ={
            "OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:1/v1",
            "OPSYS_EMBEDDINGS_MODELE": "synthetic-embedding-fixture",
        },
        cnx_factory=session,
    )
    agents_config = json.loads(files["agents"].read_text(encoding="utf-8"))
    admission = agents_config["entries"][f"opsys-agent-{finance_profile['id']}"]["opsysRuntimeAdmission"]
    assert admission == {"profileId": finance_profile["id"], "profileRevision": finance_profile["revision"]}


def test_migration_depuis_0013_est_idempotente_et_instance_survit_au_restart_restore(tmp_path):
    import shutil

    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import select

    from opsys import stockage
    from opsys.stockage.schema import OPSYS_INSTANCE

    old_path = tmp_path / "ancienne-instance.db"
    old_url = f"sqlite:///{old_path}"
    config = stockage._config()
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    with stockage.moteur(old_url).begin() as cnx:
        config.attributes["connection"] = cnx
        command.upgrade(config, "0013")
    stockage.migrer(url=old_url)
    with stockage.transaction(url=old_url) as cnx:
        first_instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
    assert stockage.revision_courante(url=old_url) == head

    # Restart and idempotent migration must retain the persisted instance identity.
    stockage.moteur(old_url).dispose()
    stockage.migrer(url=old_url)
    assert stockage.revision_courante(url=old_url) == head
    with stockage.transaction(url=old_url) as cnx:
        assert cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one() == first_instance

    stockage.moteur(old_url).dispose()
    restored_path = tmp_path / "restauree.db"
    shutil.copy2(old_path, restored_path)
    restored_url = f"sqlite:///{restored_path}"
    stockage.migrer(url=restored_url)
    assert stockage.revision_courante(url=restored_url) == head
    with stockage.transaction(url=restored_url) as cnx:
        assert cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one() == first_instance


def test_restore_preserves_live_cfo_grant_ticket_and_history(tmp_path):
    """A restored database upgraded from 0013 to 0015 keeps grants and outstanding tickets."""
    import shutil

    from alembic import command
    from sqlalchemy import select

    from opsys import stockage
    from opsys.stockage.schema import (
        AGENTS_GRANTS_CFO,
        AGENTS_GRANTS_CFO_HISTORIQUE,
        AGENTS_TICKETS_CFO,
        OPSYS_INSTANCE,
    )

    old_path = tmp_path / "ancienne-instance-avec-grant.db"
    old_url = f"sqlite:///{old_path}"
    config = stockage._config()
    with stockage.moteur(old_url).begin() as cnx:
        config.attributes["connection"] = cnx
        command.upgrade(config, "0013")
    stockage.migrer(url=old_url)

    def old_session():
        return stockage.transaction(url=old_url)

    deps = departements.charger_departements()
    with old_session() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", "mot-de-passe-fictif-1234", ["nathan_owner"])
        profile = agents.creer(cnx, deps, _spec(), par=OWNER, mutation_id="restore-create-cfo")
        profile = agents.definir_actif(
            cnx, profile["id"], deps, True, par=OWNER, mutation_id="restore-activate-cfo", revision_attendue=1
        )
        instance = agent_cfo_grants.instance_id(cnx)
    profile["instance_id"] = instance
    _grant(old_session, profile)
    arguments = {"aujourd_hui": "2026-10-01", "question_posee": "Rapport fictif restauré"}
    issued = _issue(old_session, profile, "m5_preparer_dossier_decision_cfo", arguments)

    tracked_tables = (AGENTS_GRANTS_CFO, AGENTS_GRANTS_CFO_HISTORIQUE, AGENTS_TICKETS_CFO)

    def snapshot(url):
        with stockage.transaction(url=url) as cnx:
            return {
                "instance_id": cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one(),
                **{
                    table.name: [dict(row) for row in cnx.execute(select(table)).mappings().all()]
                    for table in tracked_tables
                },
            }

    original = snapshot(old_url)
    assert original["agents_grants_cfo"][0]["active"] is True
    assert original["agents_grants_cfo_historique"][0]["event"] == "grant"
    assert original["agents_tickets_cfo"][0]["status"] == "available"
    assert original["instance_id"] == instance

    stockage.moteur(old_url).dispose()
    restored_path = tmp_path / "restauree-avec-grant.db"
    shutil.copy2(old_path, restored_path)
    restored_url = f"sqlite:///{restored_path}"
    stockage.migrer(url=restored_url)
    assert snapshot(restored_url) == original

    def restored_session():
        return stockage.transaction(url=restored_url)

    _consume(
        restored_session,
        issued["ticket"],
        "m5_preparer_dossier_decision_cfo",
        arguments,
        instance,
    )
    restored_state = snapshot(restored_url)
    assert restored_state["agents_grants_cfo"] == original["agents_grants_cfo"]
    assert restored_state["agents_grants_cfo_historique"] == original["agents_grants_cfo_historique"]
    assert restored_state["agents_tickets_cfo"][0]["status"] == "consumed"


def test_backend_non_sqlite_refuse_les_grants_et_linterface_explique_la_limite():
    from types import SimpleNamespace

    from opsys.console import agents_ui

    with pytest.raises(agent_cfo_grants.GrantCfoRefuse, match="hors SQLite"):
        agent_cfo_grants._sqlite_uniquement(SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    html = agents_ui.grant_cfo(
        {"id": "m5-cfo-agent", "departement": "m05-financecore", "revision": 3},
        None,
        prefixe="/console",
        csrf="csrf-fictif",
        instance_configuree=False,
    )
    assert "stockage SQLite configuré" in html
    grant_html = agents_ui.grant_cfo(
        {"id": "m5-cfo-agent", "departement": "m05-financecore", "revision": 3},
        {
            "version": 7,
            "active": True,
            "tools": ["m5_preparer_dossier_decision_cfo"],
            "reports_per_day": 1,
            "expires_at": "2030-01-02T03:04:05+00:00",
            "report_date_start": "2030-01-01",
            "report_date_end": "2030-01-03",
        },
        prefixe="/console",
        csrf="csrf-fictif",
        instance_configuree=True,
    )
    assert ">m5_preparer_dossier_decision_cfo</textarea>" in grant_html
    assert 'value="1"' in grant_html
    assert 'value="2030-01-02T03:04:05+00:00"' in grant_html
    assert 'value="2030-01-01"' in grant_html and 'value="2030-01-03"' in grant_html
