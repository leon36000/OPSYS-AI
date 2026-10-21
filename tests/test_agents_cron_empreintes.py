"""Cas prévus pour le contrat sha256:base64url de la révision Core."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from opsys import agents, stockage
from opsys import agents_declencheurs as intentions
from opsys.departements import charger_departements
from opsys.stockage.schema import AGENTS_DECLENCHEURS_INTENTIONS as INTENTIONS
from opsys.stockage.schema import AGENTS_DECLENCHEURS_REMISES as REMISES

CAP_A = "15" * 32
CAP_B = "26" * 32
HASH_A = hashlib.sha256(bytes.fromhex(CAP_A)).hexdigest()
HASH_B = hashlib.sha256(bytes.fromhex(CAP_B)).hexdigest()
REV_A = "sha256:" + "A" * 43
REV_B = "sha256:" + "B" * 42 + "A"


@pytest.fixture
def mandat_core_revision(session, nathan, opsys_home, monkeypatch):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(opsys_home / "core"))
    deps = charger_departements()
    with session() as cnx:
        agents.creer(cnx, deps, {
            "id": "cron-revision-fictif", "departement": "m03-estimation",
            "responsabilite": "Lire des devis fictifs sans envoi",
            "palier_modele": "standard", "outils": ["m3_lire_devis"],
            "budget_jour": 1000, "budget_mois": 10000, "limite_tours": 8,
            "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}],
        }, par=nathan, mutation_id="creation-cron-revision-fictif")
        agents.definir_actif(cnx, "cron-revision-fictif", deps, True, par=nathan,
                             mutation_id="activation-cron-revision-fictif", revision_attendue=1)
    policy = {"version": 1, "departements": {"m03-estimation": "global"},
              "agents": {"opsys-agent-cron-revision-fictif": {"departement": "m03-estimation", "mode": "global"}},
              "procedures_globales": ["procedures"]}
    fichier = opsys_home / "core" / "opsys" / "memoire-autorites.json"
    fichier.parent.mkdir(parents=True)
    fichier.write_text(json.dumps(policy))
    demande = intentions.demander(deps, "cron-revision-fictif", par=nathan, revision_attendue=2,
                                  fuseau="America/Toronto", mutation_id="mandat-cron-revision-fictif")
    ident = demande["intentions"][0]
    declaration = intentions.projeter(deps, ident, par=nathan)["native"]["params"]
    module = importlib.import_module("opsys.agents_cron_autorite")
    owner = module.ProprietaireCron(deps, "cron-revision-fictif")
    return module, owner, ident, declaration


def prepare(mandat, *, cap=CAP_A, revision=REV_A):
    _, owner, ident, decl = mandat
    return owner.preparer(ident, empreinte_capacite=hashlib.sha256(bytes.fromhex(cap)).hexdigest(),
                          declaration=decl, epoch_attendue=0,
                          revision_native_attendue=revision)


def ack(mandat, plan, *, cap=CAP_A, revision=REV_B):
    _, owner, ident, decl = mandat
    return owner.accuser(ident, capabilite=cap, epoch=plan["epoch"],
                         lease_epoch=plan["lease_epoch"], job_id="job-revision-fictif",
                         config_revision=revision, declaration=decl)


def test_format_exact_hash_core_et_entiers_legacy_distincts(mandat_core_revision):
    module, *_ = mandat_core_revision
    assert module._revision_native(REV_A) == ("sha256", REV_A)
    assert module._revision_native(1) == ("int", 1)
    for invalid in (
        True, 0, "sha256:" + "A" * 42, "sha256:" + "+" * 43,
        "sha256:" + "A" * 20 + "+" + "A" * 22, "a" * 64,
    ):
        with pytest.raises(module.DeclencheurRefuse):
            module._revision_native(invalid)


def test_ddl_postgresql_offline_des_revisions_est_portable():
    ddl = str(CreateTable(REMISES).compile(dialect=postgresql.dialect()))
    migration = importlib.import_module(
        "opsys.stockage.migrations.versions.0022_agents_cron_revision_sha256"
    )
    assert "GLOB" not in ddl.upper()
    assert "GLOB" not in migration._definition_sha256("native_config_fingerprint").upper()
    assert "native_expected_fingerprint" in ddl
    assert "native_config_fingerprint" in ddl


def test_preimage_et_ack_hash_distincts_rejeu_exact_et_valider(mandat_core_revision, session):
    module, owner, ident, decl = mandat_core_revision
    plan = prepare(mandat_core_revision, revision=REV_A)
    resultat = ack(mandat_core_revision, plan, revision=REV_B)
    assert resultat["config_revision"] == REV_B
    assert owner.accuser(ident, capabilite=CAP_A, epoch=plan["epoch"],
                         lease_epoch=plan["lease_epoch"], job_id="job-revision-fictif",
                         config_revision=REV_B, declaration=decl) == resultat
    with pytest.raises(module.DeclencheurRefuse, match="ACK-CONFLIT"):
        owner.accuser(ident, capabilite=CAP_A, epoch=plan["epoch"],
                      lease_epoch=plan["lease_epoch"], job_id="job-revision-fictif",
                      config_revision=8, declaration=decl)
    assert owner.valider(ident, capabilite=CAP_A, epoch=1, job_id="job-revision-fictif",
                         config_revision=REV_B, declaration=decl) is None
    with pytest.raises(module.DeclencheurRefuse, match="JOB-PERIME"):
        owner.valider(ident, capabilite=CAP_A, epoch=1, job_id="job-revision-fictif",
                      config_revision=REV_A, declaration=decl)
    with session() as cnx:
        row = cnx.execute(select(module.REMISES)).mappings().one()
        assert row["native_expected_revision"] is None
        assert row["native_expected_fingerprint"] == REV_A
        assert row["native_config_revision"] is None
        assert row["native_config_fingerprint"] == REV_B


def test_type_legacy_vers_hash_refuse_sans_rotation_puis_rotation_explicite(mandat_core_revision):
    module, owner, ident, decl = mandat_core_revision
    owner.preparer(ident, empreinte_capacite=HASH_A, declaration=decl,
                   epoch_attendue=0, revision_native_attendue=7)
    with pytest.raises(module.DeclencheurRefuse, match="ACK-CONFLIT"):
        owner.accuser(ident, capabilite=CAP_A, epoch=1, lease_epoch=1,
                      job_id="job-revision-fictif", config_revision=REV_B, declaration=decl)
    owner.accuser(ident, capabilite=CAP_A, epoch=1, lease_epoch=1,
                  job_id="job-revision-fictif", config_revision=8, declaration=decl)
    with pytest.raises(module.DeclencheurRefuse, match="REVISION-NATIVE-INVALIDE"):
        owner.tourner(ident, capabilite=CAP_A, epoch=1, nouvelle_empreinte=HASH_B,
                      declaration=decl, revision_native_attendue=None)
    rotation = owner.tourner(ident, capabilite=CAP_A, epoch=1,
                             nouvelle_empreinte=HASH_B, declaration=decl,
                             revision_native_attendue=REV_A)
    assert rotation["revision_native_attendue"] == REV_A
    resultat = owner.accuser(ident, capabilite=CAP_B, epoch=2, lease_epoch=2,
                             job_id="job-revision-fictif", config_revision=REV_B,
                             declaration=decl)
    assert resultat["config_revision"] == REV_B


def test_migration_0022_preserve_entiers_et_downgrade_refuse_hash(tmp_path):
    url = f"sqlite:///{tmp_path / 'revision-cron-fictive.db'}"
    _upgrade(url, "0021")
    with stockage.moteur(url).begin() as cnx:
        cnx.execute(INTENTIONS.insert().values(
            id="a" * 64, instance_id="00000000-0000-0000-0000-000000000001",
            agent_id="ancien-fictif", profile_revision=1, profile_hash="b" * 64,
            trigger_hash="c" * 64, memory_policy_hash="d" * 64, fuseau="UTC",
            declaration_key="opsys-profile:" + "a" * 64, statut="a_declarer",
            demande_par="humain-fictif", demande_role="admin", cree_le="fictif", modifie_le="fictif",
        ))
        cnx.exec_driver_sql(
            "INSERT INTO agents_declencheurs_remises VALUES "
            "('" + "a" * 64 + "', 1, '" + HASH_A + "', '" + "c" * 64 + "', "
            "7, 'job-legacy', 8, 'remise', 1, '2099-01-01T00:00:00+00:00', 30, 1, 't0', 't1')"
        )
    _upgrade(url, "0022")
    with stockage.moteur(url).begin() as cnx:
        row_legacy = dict(cnx.execute(text("SELECT * FROM agents_declencheurs_remises")).mappings().one())
        assert row_legacy["native_expected_revision"] == 7
        assert row_legacy["native_config_revision"] == 8
        assert row_legacy["native_expected_fingerprint"] is None
        assert row_legacy["native_config_fingerprint"] is None
        assert cnx.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    _downgrade(url, "0021")
    with stockage.moteur(url).begin() as cnx:
        legacy_after_down = dict(cnx.execute(text("SELECT * FROM agents_declencheurs_remises")).mappings().one())
        assert legacy_after_down == {key: value for key, value in row_legacy.items()
                                     if key not in {"native_expected_fingerprint", "native_config_fingerprint"}}
    _upgrade(url, "0022")
    with stockage.moteur(url).begin() as cnx:
        cnx.execute(text(
            "UPDATE agents_declencheurs_remises SET native_expected_revision=NULL, "
            "native_expected_fingerprint=:preimage, native_config_revision=NULL, "
            "native_config_fingerprint=:target WHERE intention_id=:ident"
        ), {"preimage": REV_A, "target": REV_B, "ident": "a" * 64})
        before = dict(cnx.execute(text("SELECT * FROM agents_declencheurs_remises")).mappings().one())
    with pytest.raises(RuntimeError, match="supprimerait des empreintes"):
        _downgrade(url, "0021")
    assert stockage.revision_courante(url) == "0022"
    with stockage.moteur(url).begin() as cnx:
        assert dict(cnx.execute(text("SELECT * FROM agents_declencheurs_remises")).mappings().one()) == before
        assert cnx.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def _configuration(url):
    from alembic.config import Config

    conf = Config()
    conf.set_main_option("script_location", str(Path(__file__).parents[1] / "src/opsys/stockage/migrations"))
    conf.set_main_option("sqlalchemy.url", url)
    return conf


def _upgrade(url, revision):
    with stockage.moteur(url).begin() as cnx:
        conf = _configuration(url)
        conf.attributes["connection"] = cnx
        command.upgrade(conf, revision)


def _downgrade(url, revision):
    with stockage.moteur(url).begin() as cnx:
        conf = _configuration(url)
        conf.attributes["connection"] = cnx
        command.downgrade(conf, revision)
