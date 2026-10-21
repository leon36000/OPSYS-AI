"""Cleanup privé SQLite fictif ; HTTP réel, preuve de suppression native simulée explicitement.

Ces tests ne prouvent pas le DELETE Core : le test natif compagnon protège ce propriétaire.
"""

from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64encode

import pytest
from alembic import command, op
from sqlalchemy import delete, select, update
from starlette.testclient import TestClient

from opsys import agents, agents_cron_autorite, agents_cron_retraits, stockage
from opsys import agents_declencheurs as intentions
from opsys.departements import charger_departements
from opsys.serveur_mcp import application_http_departements
from opsys.stockage.schema import AGENTS_CRON_RETRAITS as RETRAITS
from opsys.stockage.schema import AGENTS_DECLENCHEURS_INTENTIONS as INTENTIONS
from opsys.stockage.schema import AGENTS_DECLENCHEURS_REMISES as REMISES
from opsys.stockage.schema import JOURNAL, ROLES_PERSONNES

PUBLIC = "public-cron-retrait-fictif-abcdefghijklmnopqrstuvwxyz"
CONTEXTE = "contexte-cron-retrait-fictif-abcdefghijklmnopqrstuvwxyz"
OPERATEUR = "operateur-cron-retrait-fictif-abcdefghijklmnopqrstuvwxyz"
CAPACITE = "42" * 32
CAP_HASH = hashlib.sha256(bytes.fromhex(CAPACITE)).hexdigest()
REVISION = "sha256:" + urlsafe_b64encode(hashlib.sha256(b"job-desactive-fictif").digest()).decode().rstrip("=")


@pytest.fixture
def retrait(session, nathan, opsys_home, monkeypatch, request):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(opsys_home / "core"))
    monkeypatch.setenv("OPSYS_CRON_OPERATEUR_JETON", OPERATEUR)
    deps = charger_departements()
    with session() as cnx:
        agents.creer(cnx, deps, {
            "id": "cleanup-fictif", "departement": "m03-estimation",
            "responsabilite": "Lire un devis fictif sans envoi",
            "palier_modele": "standard", "outils": ["m3_lire_devis"],
            "budget_jour": 1000, "budget_mois": 10000, "limite_tours": 8,
            "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}],
        }, par=nathan, mutation_id="creation-cleanup-fictif")
        agents.definir_actif(cnx, "cleanup-fictif", deps, True, par=nathan,
                             mutation_id="activation-cleanup-fictif", revision_attendue=1)
    policy = {"version": 1, "departements": {"m03-estimation": "global"},
              "agents": {"opsys-agent-cleanup-fictif": {"departement": "m03-estimation", "mode": "global"}},
              "procedures_globales": ["procedures"]}
    fichier = opsys_home / "core" / "opsys" / "memoire-autorites.json"
    fichier.parent.mkdir(parents=True)
    fichier.write_text(json.dumps(policy))
    resultat = intentions.demander(deps, "cleanup-fictif", par=nathan, revision_attendue=2,
                                  fuseau="UTC", mutation_id="demande-cleanup-fictif")
    ident = resultat["intentions"][0]
    declaration = intentions.projeter(deps, ident, par=nathan)["native"]["params"]
    owner = agents_cron_autorite.ProprietaireCron(deps, "cleanup-fictif")
    plan = owner.preparer(ident, empreinte_capacite=CAP_HASH, epoch_attendue=0, declaration=declaration)
    if getattr(request, "param", "ack") != "sans_ack":
        owner.accuser(ident, capabilite=CAPACITE, epoch=1, lease_epoch=plan["lease_epoch"],
                      declaration=declaration, job_id="job-cleanup-fictif", config_revision=1)
    intentions.retirer(deps, "cleanup-fictif", par=nathan, revision_attendue=2,
                       mutation_id="retrait-cleanup-fictif")
    app = application_http_departements(deps, session, PUBLIC, jeton_contexte=CONTEXTE)
    with TestClient(app) as client:
        yield client, deps, ident, declaration, session


def _headers(token=OPERATEUR):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _corps(retrait):
    return {"intention_id": retrait[2], "capabilite": CAPACITE, "epoch": 1,
            "declaration": retrait[3], "job_id": "job-cleanup-fictif", "native_revision": REVISION}


def _appel(retrait, phase, corps, token=OPERATEUR):
    return retrait[0].post(f"/cron-operateur/v1/cleanup-fictif/{phase}-retrait",
                           headers=_headers(token), json=corps)


def _snapshot(session):
    with session() as cnx:
        return [cnx.execute(select(table)).all() for table in (INTENTIONS, REMISES, RETRAITS, JOURNAL)]


@pytest.mark.parametrize("inactif", ["role", "profil"])
def test_cleanup_apres_depart_role_ou_profil_rejeu_exact_journal_conserve(retrait, inactif):
    _, deps, ident, _, session = retrait
    with session() as cnx:
        grant_avant = dict(cnx.execute(select(REMISES)).mappings().one())
        if inactif == "role":
            cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == "nathan"))
        else:
            agents.definir_actif(cnx, "cleanup-fictif", deps, False, par="nathan",
                                 mutation_id="profil-cleanup-inactif", revision_attendue=2)
    corps = _corps(retrait)
    prepare = _appel(retrait, "preparer", corps)
    assert prepare.status_code == 200 and prepare.json()["resultat"]["execute"] is False
    preuve = prepare.json()["resultat"]
    assert CAPACITE not in prepare.text and CAP_HASH not in prepare.text
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.statut)) == "a_retirer"
        assert cnx.scalar(select(REMISES.c.etat)) == "revoquee"
        assert cnx.execute(select(RETRAITS)).all() == []
    # Explicit simulated host proof: native DELETE is covered by the companion Core test.
    ack = {**corps, "source_hash": preuve["source_hash"], "receipt_id": preuve["receipt_id"]}
    reponse = _appel(retrait, "accuser", ack)
    assert reponse.status_code == 200 and reponse.json()["resultat"]["etat"] == "retiree"
    assert reponse.headers["cache-control"] == "no-store"
    assert CAPACITE not in reponse.text and CAP_HASH not in reponse.text
    avant_rejeu = _snapshot(session)
    stockage.liberer()
    rejoue = _appel(retrait, "accuser", ack)
    assert rejoue.status_code == 200 and rejoue.json() == reponse.json()
    assert _snapshot(session) == avant_rejeu
    with session() as cnx:
        grant = dict(cnx.execute(select(REMISES)).mappings().one())
        for champ in ("epoch", "capability_hash", "declaration_hash", "native_job_id",
                      "native_config_revision", "native_config_fingerprint"):
            assert grant[champ] == grant_avant[champ]
        actions = list(cnx.scalars(select(JOURNAL.c.action)))
        assert actions.count("agents.cron.retrait_acquitte") == 1
        assert "agents.cron.retrait_demande" in actions
        assert cnx.scalar(select(INTENTIONS.c.id)) == ident


@pytest.mark.parametrize("champ,valeur", [
    ("capabilite", "43" * 32), ("epoch", 2), ("job_id", "autre-job-fictif"),
    ("source_hash", "a" * 64), ("receipt_id", "b" * 64),
])
def test_ack_conflit_refuse_sans_effet_ni_secret(retrait, champ, valeur):
    corps = _corps(retrait)
    prepare = _appel(retrait, "preparer", corps)
    assert prepare.status_code == 200
    preuve = prepare.json()["resultat"]
    ack = {**corps, "source_hash": preuve["source_hash"], "receipt_id": preuve["receipt_id"], champ: valeur}
    avant = _snapshot(retrait[4])
    refus = _appel(retrait, "accuser", ack)
    assert refus.status_code == 409 and CAPACITE not in refus.text
    assert _snapshot(retrait[4]) == avant


def test_ancien_etat_sans_source_humaine_ne_devient_pas_cleanup(retrait):
    with retrait[4]() as cnx:
        cnx.execute(update(INTENTIONS).values(retrait_par=None))
    avant = _snapshot(retrait[4])
    refus = _appel(retrait, "preparer", _corps(retrait))
    assert refus.status_code == 409 and _snapshot(retrait[4]) == avant


@pytest.mark.parametrize("audience", [PUBLIC, CONTEXTE, "absent-fictif"])
def test_audiences_publiques_ne_peuvent_pas_acquitter(retrait, audience):
    avant = _snapshot(retrait[4])
    response = _appel(retrait, "preparer", _corps(retrait), audience)
    assert response.status_code == 401 and _snapshot(retrait[4]) == avant


@pytest.mark.parametrize("phase", ["preparer", "accuser"])
def test_operateur_change_avant_commit_rollback_intention_receipt_journal(retrait, monkeypatch, phase):
    corps = _corps(retrait)
    if phase == "accuser":
        prepare = _appel(retrait, "preparer", corps)
        preuve = prepare.json()["resultat"]
        corps.update(source_hash=preuve["source_hash"], receipt_id=preuve["receipt_id"])
    avant = _snapshot(retrait[4])
    original = agents_cron_retraits.journaliser

    def retirer_operateur(cnx, *args):
        original(cnx, *args)
        monkeypatch.setenv("OPSYS_CRON_OPERATEUR_JETON", "rotation-operateur-fictive-abcdefghijklmnopqrstuvwxyz")

    monkeypatch.setattr(agents_cron_retraits, "journaliser", retirer_operateur)
    refus = _appel(retrait, phase, corps)
    assert refus.status_code == 409 and _snapshot(retrait[4]) == avant


@pytest.mark.parametrize("retrait", ["sans_ack"], indirect=True)
def test_grant_capture_avant_ack_execution_nettoyable_sans_inventer_ack(retrait):
    corps = _corps(retrait)
    preuve = _appel(retrait, "preparer", corps).json()["resultat"]
    ack = {**corps, "source_hash": preuve["source_hash"], "receipt_id": preuve["receipt_id"]}
    assert _appel(retrait, "accuser", ack).status_code == 200
    with retrait[4]() as cnx:
        grant = cnx.execute(select(REMISES)).mappings().one()
        assert grant["native_job_id"] is None and grant["native_config_revision"] is None
        assert grant["etat"] == "revoquee" and cnx.scalar(select(INTENTIONS.c.statut)) == "retiree"


def test_ack_source_changee_apres_preparation_refuse_sans_pretendre_retire(retrait):
    corps = _corps(retrait)
    preuve = _appel(retrait, "preparer", corps).json()["resultat"]
    intentions.retirer(retrait[1], "cleanup-fictif", par="nathan", revision_attendue=2,
                       mutation_id="nouveau-retrait-cleanup-fictif")
    avant = _snapshot(retrait[4])
    ack = {**corps, "source_hash": preuve["source_hash"], "receipt_id": preuve["receipt_id"]}
    assert _appel(retrait, "accuser", ack).status_code == 409
    assert _snapshot(retrait[4]) == avant


def _upgrade(url, cible):
    config = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        config.attributes["connection"] = cnx
        command.upgrade(config, cible)


def _tables_historiques(cnx):
    return {nom: cnx.exec_driver_sql(f"SELECT * FROM {nom}").all() for nom in (
        "agents_declencheurs_intentions", "agents_declencheurs_remises", "agents_declencheurs_commandes",
        "fusion_ap_brouillons", "fusion_ap_commandes", "journal",
    )}


def test_migration_reelle_0022_0023_preserve_tables_et_head(tmp_path):
    url = "sqlite:///" + str(tmp_path / "cleanup-migration-fictive.sqlite")
    _upgrade(url, "0022")
    with stockage.moteur(url).begin() as cnx:
        cnx.execute(INTENTIONS.insert().values(
            id="a" * 64, instance_id="00000000-0000-0000-0000-000000000001", agent_id="fictif",
            profile_revision=1, profile_hash="b" * 64, trigger_hash="c" * 64, memory_policy_hash="d" * 64,
            fuseau="UTC", declaration_key="opsys-profile:" + "a" * 64, statut="a_retirer",
            demande_par="humain-fictif", demande_role="admin", cree_le="fictif", modifie_le="fictif",
        ))
        cnx.execute(REMISES.insert().values(
            intention_id="a" * 64, epoch=1, capability_hash=CAP_HASH, declaration_hash="e" * 64,
            native_job_id="job-historique-fictif", native_config_fingerprint=REVISION, etat="revoquee",
            lease_epoch=1, lease_until="2026-10-03T00:00:00+00:00", lease_seconds=30, attempts=1,
            cree_le="fictif", modifie_le="fictif",
        ))
        avant = _tables_historiques(cnx)
    _upgrade(url, "0023")
    assert stockage.revision_courante(url) == "0023"
    with stockage.moteur(url).begin() as cnx:
        assert _tables_historiques(cnx) == avant
        assert cnx.execute(select(RETRAITS)).all() == []


def test_erreur_migration_0023_rollback_revision_et_table(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "cleanup-migration-rollback-fictive.sqlite")
    _upgrade(url, "0022")
    with stockage.moteur(url).begin() as cnx:
        avant = _tables_historiques(cnx)
    original = op.create_table

    def panne(*args, **kwargs):
        table = original(*args, **kwargs)
        if args[0] == "agents_cron_retraits":
            raise RuntimeError("panne migration fictive")
        return table

    monkeypatch.setattr(op, "create_table", panne)
    with pytest.raises(RuntimeError, match="panne migration fictive"):
        _upgrade(url, "0023")
    assert stockage.revision_courante(url) == "0022"
    with stockage.moteur(url).begin() as cnx:
        assert _tables_historiques(cnx) == avant
        assert cnx.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agents_cron_retraits'"
        ).all() == []
