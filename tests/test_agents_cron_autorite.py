"""Grants/remises privés SQLite, données fictives, sans transport ni provider exécuté."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json

import pytest
from alembic import command, op
from sqlalchemy import delete, insert, inspect, select, update

from opsys import agents, identite, stockage
from opsys import agents_declencheurs as intentions
from opsys.departements import charger_departements
from opsys.stockage.schema import AGENTS_CONFIGURABLES as PROFILS
from opsys.stockage.schema import AGENTS_DECLENCHEURS_INTENTIONS as INTENTIONS
from opsys.stockage.schema import JOURNAL, ROLES_PERSONNES

CAPACITE_FICTIVE = "15" * 32
AUTRE_CAPACITE_FICTIVE = "26" * 32
HASH_FICTIF = hashlib.sha256(bytes.fromhex(CAPACITE_FICTIVE)).hexdigest()
AUTRE_HASH_FICTIF = hashlib.sha256(bytes.fromhex(AUTRE_CAPACITE_FICTIVE)).hexdigest()


@pytest.fixture
def mandat(session, nathan, opsys_home, monkeypatch, request):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(opsys_home / "core"))
    deps = charger_departements()
    with session() as cnx:
        agents.creer(cnx, deps, {
            "id": "cron-fictif", "departement": "m03-estimation",
            "responsabilite": "Lire des devis fictifs et proposer une calibration sans envoi",
            "palier_modele": "standard", "outils": ["m3_lire_devis", "m3_proposer_calibration_temps"],
            "budget_jour": 1000, "budget_mois": 10000, "limite_tours": 8,
            "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": ([{"type": "cron", "expression": f"0 {heure} * * 1-5"} for heure in range(16)]
                             if getattr(request, "param", 1) == 16
                             else [{"type": "cron", "expression": "0 7 * * 1-5"}]),
        }, par=nathan, mutation_id="creation-grant-cron-fictif")
        agents.definir_actif(cnx, "cron-fictif", deps, True, par=nathan,
                             mutation_id="activation-grant-cron-fictif", revision_attendue=1)
    policy = {"version": 1, "departements": {"m03-estimation": "global"},
              "agents": {"opsys-agent-cron-fictif": {"departement": "m03-estimation", "mode": "global"}},
              "procedures_globales": ["procedures"]}
    fichier = opsys_home / "core" / "opsys" / "memoire-autorites.json"
    fichier.parent.mkdir(parents=True)
    fichier.write_text(json.dumps(policy))
    demande = intentions.demander(deps, "cron-fictif", par=nathan, revision_attendue=2,
                                  fuseau="America/Toronto", mutation_id="mandat-grant-cron-fictif")
    ident = demande["intentions"][0]
    declaration = intentions.projeter(deps, ident, par=nathan)["native"]["params"]
    return deps, ident, declaration, fichier


def _owner(mandat, profil="cron-fictif"):
    module = importlib.import_module("opsys.agents_cron_autorite")
    return module, module.ProprietaireCron(mandat[0], profil)


def _preparer(owner, mandat, **kwargs):
    return owner.preparer(mandat[1], empreinte_capacite=HASH_FICTIF,
                          declaration=mandat[2], epoch_attendue=0, **kwargs)


def _ack(owner, mandat, plan, **kwargs):
    params = {"capabilite": CAPACITE_FICTIVE, "epoch": plan["epoch"],
              "lease_epoch": plan["lease_epoch"], "job_id": "job-fictif-1",
              "config_revision": 1, "declaration": mandat[2]}
    params.update(kwargs)
    return owner.accuser(mandat[1], **params)


def _valider(owner, mandat, **kwargs):
    params = {"capabilite": CAPACITE_FICTIVE, "epoch": 1, "job_id": "job-fictif-1",
              "config_revision": 1, "declaration": mandat[2]}
    params.update(kwargs)
    return owner.valider(mandat[1], **params)


def _table(module):
    return module.REMISES


def _remplir_metadata_fictives(session, intention_id, nombre, *, fuseau=None):
    """Lignes canoniquement identifiées pour tester la lecture, pas des mandats exécutables."""
    with session() as cnx:
        source = dict(cnx.execute(select(INTENTIONS).where(INTENTIONS.c.id == intention_id)).mappings().one())
        rows = []
        for offset in range(nombre - 1):
            zone = f"zone-fictive-{offset}" if fuseau is None else fuseau
            row = dict(source, fuseau=zone, trigger_hash=f"{offset:064x}")
            ident = intentions._hash({
                "instance": row["instance_id"], "profil": row["agent_id"],
                "revision": row["profile_revision"], "cron": row["trigger_hash"], "fuseau": row["fuseau"],
            })
            rows.append(dict(row, id=ident, declaration_key="opsys-profile:" + ident))
        if rows:
            cnx.execute(insert(INTENTIONS), rows)


@pytest.mark.parametrize("mandat", [16], indirect=True)
def test_lire_seize_mandats_reels_admis_et_projection_m3_autorisee(mandat, session):
    module, owner = _owner(mandat)
    with session() as cnx:
        avant_intentions = cnx.execute(select(INTENTIONS)).all()
        avant_remises = cnx.execute(select(_table(module))).all()
        avant_journal = cnx.execute(select(JOURNAL)).all()
    resultat = owner.lire()
    assert (resultat["total"], resultat["retournes"], resultat["omis"]) == (16, 16, 0)
    assert len({item["intention_id"] for item in resultat["items"]}) == 16
    for item in resultat["items"]:
        projection = owner.projeter(item["intention_id"])
        assert projection["execute"] is False
        assert projection["native"]["params"]["payload"]["toolsAllow"] == [
            "opsys_m3__m3_lire_devis", "opsys_m3__m3_proposer_calibration_temps",
        ]
    with session() as cnx:
        assert cnx.execute(select(INTENTIONS)).all() == avant_intentions
        assert cnx.execute(select(_table(module))).all() == avant_remises
        assert cnx.execute(select(JOURNAL)).all() == avant_journal


def test_lire_seize_intentions_metadata_exhaustives_sans_ecriture(mandat, session):
    module, owner = _owner(mandat)
    _remplir_metadata_fictives(session, mandat[1], 16, fuseau="é" * 32)
    with session() as cnx:
        avant_intentions = cnx.execute(select(INTENTIONS)).all()
        avant_remises = cnx.execute(select(_table(module))).all()
        avant_journal = cnx.execute(select(JOURNAL)).all()
    resultat = owner.lire()
    assert (resultat["total"], resultat["retournes"], resultat["omis"]) == (16, 16, 0)
    assert len({item["intention_id"] for item in resultat["items"]}) == 16
    assert len(intentions._json(resultat).encode("utf-8")) <= 16384
    assert all(set(item) == {"intention_id", "etat", "revision_profil", "fuseau"} for item in resultat["items"])
    with session() as cnx:
        assert cnx.execute(select(INTENTIONS)).all() == avant_intentions
        assert cnx.execute(select(_table(module))).all() == avant_remises
        assert cnx.execute(select(JOURNAL)).all() == avant_journal


@pytest.mark.parametrize("nombre,fuseau,diagnostic", [
    (17, None, "LECTURE-SATUREE"),
    (2, "é" * 33, "METADONNEES-EXCESSIVES"),
])
def test_lire_refuse_surplus_et_octets_avant_materialisation(
    mandat, session, monkeypatch, nombre, fuseau, diagnostic,
):
    module, owner = _owner(mandat)
    _remplir_metadata_fictives(session, mandat[1], nombre, fuseau=fuseau)
    controles = []
    original = intentions._identite_intention

    def observer(row):
        controles.append(row)
        return original(row)

    monkeypatch.setattr(intentions, "_identite_intention", observer)
    with session() as cnx:
        avant_intentions = cnx.execute(select(INTENTIONS)).all()
        avant_remises = cnx.execute(select(_table(module))).all()
        avant_journal = cnx.execute(select(JOURNAL)).all()
    with pytest.raises(module.DeclencheurRefuse, match=diagnostic):
        owner.lire()
    assert controles == []
    with session() as cnx:
        assert cnx.execute(select(INTENTIONS)).all() == avant_intentions
        assert cnx.execute(select(_table(module))).all() == avant_remises
        assert cnx.execute(select(JOURNAL)).all() == avant_journal


def test_m3_reel_declaration_ack_durable_et_secret_absent(mandat, session):
    module, owner = _owner(mandat)
    plan = _preparer(owner, mandat)
    assert plan["epoch"] == 1 and plan["lease_epoch"] == 1 and plan["execute"] is False
    assert plan["native"]["method"] == "cron.add"
    assert plan["native"]["params"] == mandat[2]
    assert plan["native"]["params"]["payload"]["toolsAllow"] == [
        "opsys_m3__m3_lire_devis", "opsys_m3__m3_proposer_calibration_temps",
    ]
    with pytest.raises(module.DeclencheurRefuse, match="NON-ACQUITTEE"):
        _valider(owner, mandat)
    ack = _ack(owner, mandat, plan)
    assert ack["etat"] == "remise" and ack["job_id"] == "job-fictif-1" and ack["execute"] is False
    stockage.liberer()  # Relecture par une autre façade, pas un cache mémoire.
    assert _valider(_owner(mandat)[1], mandat) is None
    with session() as cnx:
        row = dict(cnx.execute(select(_table(module))).mappings().one())
        audit = [dict(r) for r in cnx.execute(select(JOURNAL)).mappings()]
        intention = cnx.execute(select(INTENTIONS)).mappings().one()
    assert row["capability_hash"] == HASH_FICTIF and row["epoch"] == 1
    assert intention["statut"] == "a_declarer"  # ACK ne libère pas les plafonds du désir canonique.
    for value in (plan, ack, row, audit):
        assert CAPACITE_FICTIVE not in json.dumps(value)
    assert HASH_FICTIF not in json.dumps([plan, ack, audit])


def test_rejeu_preparation_et_ack_exact_sans_nouveau_journal(mandat, session):
    module, owner = _owner(mandat)
    first = _preparer(owner, mandat)
    assert _preparer(owner, mandat) == first
    ack = _ack(owner, mandat, first)
    with session() as cnx:
        before = cnx.execute(select(JOURNAL)).all()
    assert _ack(owner, mandat, first) == ack
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == before
        assert len(cnx.execute(select(_table(module))).all()) == 1


@pytest.mark.parametrize("changement", [
    {"capabilite": AUTRE_CAPACITE_FICTIVE}, {"epoch": 2}, {"lease_epoch": 2},
    {"job_id": ""}, {"config_revision": True}, {"config_revision": 0},
])
def test_ack_invalide_ne_cree_pas_grant_admis(mandat, session, changement):
    module, owner = _owner(mandat)
    plan = _preparer(owner, mandat)
    with session() as cnx:
        before = cnx.execute(select(_table(module))).all()
    with pytest.raises(module.DeclencheurRefuse):
        _ack(owner, mandat, plan, **changement)
    with session() as cnx:
        assert cnx.execute(select(_table(module))).all() == before


@pytest.mark.parametrize("changement", [
    {"job_id": "autre-job-fictif"}, {"config_revision": 2}, {"epoch": 2},
    {"capabilite": AUTRE_CAPACITE_FICTIVE},
])
def test_lecture_autorite_exige_job_revision_epoch_secret_exacts(mandat, changement):
    module, owner = _owner(mandat)
    plan = _preparer(owner, mandat)
    _ack(owner, mandat, plan)
    with pytest.raises(module.DeclencheurRefuse):
        _valider(owner, mandat, **changement)


def test_ack_rejoue_autre_job_conflit_sans_remplacement(mandat, session):
    module, owner = _owner(mandat)
    plan = _preparer(owner, mandat)
    _ack(owner, mandat, plan)
    with pytest.raises(module.DeclencheurRefuse, match="ACK-CONFLIT"):
        _ack(owner, mandat, plan, job_id="autre-job-fictif")
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.native_job_id)) == "job-fictif-1"


@pytest.mark.parametrize("phase", ["preparer", "ack", "valider", "rotation"])
def test_mandant_revoque_refuse_meme_rejeu(mandat, session, phase):
    module, owner = _owner(mandat)
    plan = _preparer(owner, mandat)
    if phase in {"valider", "rotation"}:
        _ack(owner, mandat, plan)
    with session() as cnx:
        cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == "nathan"))
        before = cnx.execute(select(_table(module))).all()
    with pytest.raises(PermissionError, match="administration active requise"):
        if phase == "preparer":
            _preparer(owner, mandat)
        elif phase == "ack":
            _ack(owner, mandat, plan)
        elif phase == "rotation":
            owner.tourner(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1,
                          nouvelle_empreinte=AUTRE_HASH_FICTIF, declaration=mandat[2])
        else:
            _valider(owner, mandat)
    with session() as cnx:
        assert cnx.execute(select(_table(module))).all() == before


@pytest.mark.parametrize("changement", ["revision", "profil", "retrait", "memoire", "instance"])
def test_sources_courantes_refusent_grant_deja_acquitte(mandat, session, changement):
    module, owner = _owner(mandat)
    plan = _preparer(owner, mandat)
    _ack(owner, mandat, plan)
    if changement == "memoire":
        policy = json.loads(mandat[3].read_text())
        policy["agents"]["opsys-agent-cron-fictif"]["mode"] = "client_session"
        mandat[3].write_text(json.dumps(policy))
    else:
        with session() as cnx:
            if changement == "revision":
                cnx.execute(update(PROFILS).values(revision=3))
            elif changement == "profil":
                cnx.execute(update(PROFILS).values(responsabilite="Mandat altéré fictif"))
            elif changement == "retrait":
                cnx.execute(update(INTENTIONS).values(statut="a_retirer"))
            else:
                cnx.execute(update(INTENTIONS).values(instance_id="00000000-0000-0000-0000-000000000001"))
    with pytest.raises(module.DeclencheurRefuse):
        _valider(owner, mandat)


def test_profil_lie_hors_arguments_refuse_intention_autre_profil(mandat, session):
    module, owner = _owner(mandat, "autre-profil-fictif")
    with pytest.raises(module.DeclencheurRefuse, match="PERIMETRE"):
        _preparer(owner, mandat)
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.intention_id)) is None


@pytest.mark.parametrize("changement", ["extra", "outils", "message", "tz", "type"])
def test_declaration_complete_refuse_ecarts_avant_preparation(mandat, session, changement):
    module, owner = _owner(mandat)
    declaration = json.loads(json.dumps(mandat[2]))
    if changement == "extra":
        declaration["enabled"] = True
    elif changement == "outils":
        declaration["payload"]["toolsAllow"] = []
    elif changement == "message":
        declaration["payload"]["message"] = "Autre mandat fictif"
    elif changement == "tz":
        declaration["schedule"]["tz"] = "UTC"
    else:
        declaration["payload"]["timeoutSeconds"] = 120.0
    with pytest.raises(module.DeclencheurRefuse, match="DECLARATION"):
        owner.preparer(mandat[1], empreinte_capacite=HASH_FICTIF,
                       declaration=declaration, epoch_attendue=0)
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.intention_id)) is None


def test_pg_refuse_avant_transaction(mandat, monkeypatch):
    module, owner = _owner(mandat)
    monkeypatch.setattr(stockage, "url_base", lambda: "postgresql://fictif.invalid/base")
    monkeypatch.setattr(stockage, "transaction", lambda: pytest.fail("aucune transaction PG autorisée"))
    with pytest.raises(module.DeclencheurRefuse, match="SQLITE-REQUIS"):
        _preparer(owner, mandat)


def test_lease_expiree_reprise_bornee_fence_et_rejeu(mandat, session, monkeypatch):
    module, owner = _owner(mandat)
    horloge = [dt.datetime(2026, 10, 2, 12, tzinfo=dt.UTC)]
    monkeypatch.setattr(module, "_maintenant", lambda: horloge[0])
    plan = _preparer(owner, mandat, lease_secondes=10)
    for tentative in (2, 3):
        horloge[0] += dt.timedelta(seconds=11)
        with pytest.raises(module.DeclencheurRefuse, match="LEASE-PERIMEE"):
            _ack(owner, mandat, plan)
        courant = owner.renouveler(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1,
                                   lease_epoch=plan["lease_epoch"], declaration=mandat[2], lease_secondes=10)
        assert courant["lease_epoch"] == tentative
        assert owner.renouveler(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1,
                               lease_epoch=plan["lease_epoch"], declaration=mandat[2], lease_secondes=10) == courant
        with pytest.raises(module.DeclencheurRefuse, match="LEASE-PERIMEE"):
            _ack(owner, mandat, plan)
        plan = courant
    horloge[0] += dt.timedelta(seconds=11)
    with pytest.raises(module.DeclencheurRefuse, match="TENTATIVES-EPUISEES"):
        owner.renouveler(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1,
                        lease_epoch=3, declaration=mandat[2], lease_secondes=10)
    with session() as cnx:
        row = cnx.execute(select(_table(module))).mappings().one()
        assert row["attempts"] == 3 and row["etat"] == "preparation"


def test_rotation_explicitement_separee_fence_ancien_secret_et_job(mandat, session):
    module, owner = _owner(mandat)
    plan = _preparer(owner, mandat)
    _ack(owner, mandat, plan)
    rotation = owner.tourner(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1,
                             nouvelle_empreinte=AUTRE_HASH_FICTIF, declaration=mandat[2])
    assert rotation["epoch"] == 2 and rotation["lease_epoch"] == 2 and rotation["etat"] == "preparation"
    assert rotation["revision_native_attendue"] == 1
    reconciliation = owner.preparer(mandat[1], empreinte_capacite=AUTRE_HASH_FICTIF,
                                    declaration=mandat[2], epoch_attendue=1, revision_native_attendue=1)
    assert reconciliation["epoch"] == 2 and reconciliation["lease_epoch"] == 2
    with pytest.raises(module.DeclencheurRefuse, match="CAPACITE-REFUSEE"):
        _valider(owner, mandat)
    with pytest.raises(module.DeclencheurRefuse, match="ACK-CONFLIT"):
        _ack(owner, mandat, rotation, capabilite=AUTRE_CAPACITE_FICTIVE, job_id="remplacant-fictif")
    _ack(owner, mandat, rotation, capabilite=AUTRE_CAPACITE_FICTIVE, config_revision=2)
    assert _valider(owner, mandat, capabilite=AUTRE_CAPACITE_FICTIVE, epoch=2, config_revision=2) is None
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.native_job_id)) == "job-fictif-1"


def test_capacite_perdue_pas_recuperation_ni_rearmement_implicite(mandat, session):
    module, owner = _owner(mandat)
    _preparer(owner, mandat)
    with pytest.raises(module.DeclencheurRefuse, match="PREPARATION-CONFLIT"):
        owner.preparer(mandat[1], empreinte_capacite=AUTRE_HASH_FICTIF, declaration=mandat[2], epoch_attendue=0)
    with pytest.raises(module.DeclencheurRefuse, match="CAPACITE-REFUSEE"):
        owner.tourner(mandat[1], capabilite=AUTRE_CAPACITE_FICTIVE, epoch=1,
                      nouvelle_empreinte=AUTRE_HASH_FICTIF, declaration=mandat[2])
    with session() as cnx:
        row = cnx.execute(select(_table(module))).mappings().one()
        assert row["epoch"] == 1 and row["capability_hash"] == HASH_FICTIF


def test_revoquer_durable_rejeu_apres_retrait_sans_effacement(mandat, session):
    module, owner = _owner(mandat)
    _ack(owner, mandat, _preparer(owner, mandat))
    with session() as cnx:
        cnx.execute(update(INTENTIONS).values(statut="a_retirer"))
    refus = owner.revoquer(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1)
    assert refus["etat"] == "revoquee" and refus["execute"] is False
    with session() as cnx:
        journal = cnx.execute(select(JOURNAL)).all()
    assert owner.revoquer(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1) == refus
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == journal
        assert cnx.scalar(select(INTENTIONS.c.statut)) == "a_retirer"
    with pytest.raises(module.DeclencheurRefuse, match="REVOQUEE"):
        _valider(owner, mandat)


@pytest.mark.parametrize("lease", [0, 121, True, 3.0])
def test_lease_bornee_refuse_avant_ecriture(mandat, session, lease):
    module, owner = _owner(mandat)
    with pytest.raises(module.DeclencheurRefuse, match="LEASE-INVALIDE"):
        _preparer(owner, mandat, lease_secondes=lease)
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.intention_id)) is None


@pytest.mark.parametrize("alteration", ["utf8", "profondeur", "nodes", "inf", "surrogate", "cycle"])
def test_declaration_bornee_avant_ecriture(mandat, session, alteration):
    module, owner = _owner(mandat)
    decl = json.loads(json.dumps(mandat[2]))
    if alteration == "utf8":
        decl["payload"]["message"] = "é" * 10000
    elif alteration == "profondeur":
        value = 0
        for _ in range(10):
            value = [value]
        decl["extra"] = value
    elif alteration == "nodes":
        decl["extra"] = [0] * 10000
    elif alteration == "inf":
        decl["extra"] = float("inf")
    elif alteration == "surrogate":
        decl["extra"] = "\ud800"
    else:
        decl["extra"] = decl
    with pytest.raises(module.DeclencheurRefuse, match="DECLARATION"):
        owner.preparer(mandat[1], empreinte_capacite=HASH_FICTIF, declaration=decl, epoch_attendue=0)
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.intention_id)) is None


@pytest.mark.parametrize("phase", ["preparer", "ack", "valider"])
def test_retrait_pendant_construction_refuse_et_rollback(mandat, session, monkeypatch, phase):
    module, owner = _owner(mandat)
    plan = None
    if phase != "preparer":
        plan = _preparer(owner, mandat)
    if phase == "valider":
        _ack(owner, mandat, plan)
    with session() as cnx:
        avant = cnx.execute(select(_table(module))).all()
        audit_avant = cnx.execute(select(JOURNAL)).all()
    construire = intentions._declaration

    def construire_et_retirer(*args):
        resultat = construire(*args)
        cnx = stockage.connexion_courante()
        assert cnx is not None
        cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == "nathan"))
        return resultat

    monkeypatch.setattr(intentions, "_declaration", construire_et_retirer)
    with pytest.raises(PermissionError, match="administration active requise"):
        if phase == "preparer":
            _preparer(owner, mandat)
        elif phase == "ack":
            _ack(owner, mandat, plan)
        else:
            _valider(owner, mandat)
    with session() as cnx:
        assert cnx.execute(select(_table(module))).all() == avant
        assert cnx.execute(select(JOURNAL)).all() == audit_avant
        assert identite.personne_active(cnx, "nathan").roles == {"nathan_owner"}


def test_expiration_pendant_ack_rollback_ack_et_journal(mandat, session, monkeypatch):
    module, owner = _owner(mandat)
    horloge = [dt.datetime(2026, 10, 2, 12, tzinfo=dt.UTC)]
    monkeypatch.setattr(module, "_maintenant", lambda: horloge[0])
    plan = _preparer(owner, mandat, lease_secondes=1)
    journaliser = module.journaliser

    def publier_puis_expirer(*args):
        journaliser(*args)
        horloge[0] += dt.timedelta(seconds=2)

    monkeypatch.setattr(module, "journaliser", publier_puis_expirer)
    with session() as cnx:
        avant = cnx.execute(select(JOURNAL)).all()
    with pytest.raises(module.DeclencheurRefuse, match="LEASE-PERIMEE"):
        _ack(owner, mandat, plan)
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.etat)) == "preparation"
        assert cnx.scalar(select(_table(module).c.native_job_id)) is None
        assert cnx.execute(select(JOURNAL)).all() == avant


@pytest.mark.parametrize("phase", ["preparer", "ack", "rotation", "renouveler", "revoquer"])
def test_retrait_apres_ecriture_refuse_et_rollback_grant_journal(mandat, session, monkeypatch, phase):
    module, owner = _owner(mandat)
    horloge = [dt.datetime(2026, 10, 2, 12, tzinfo=dt.UTC)]
    monkeypatch.setattr(module, "_maintenant", lambda: horloge[0])
    plan = None
    if phase != "preparer":
        plan = _preparer(owner, mandat, lease_secondes=10)
    if phase in {"rotation", "revoquer"}:
        _ack(owner, mandat, plan)
    if phase == "renouveler":
        horloge[0] += dt.timedelta(seconds=11)
    with session() as cnx:
        avant = cnx.execute(select(_table(module))).all()
        audit_avant = cnx.execute(select(JOURNAL)).all()
    publier = module.journaliser

    def publier_et_retirer(cnx, *args):
        publier(cnx, *args)
        cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == "nathan"))

    monkeypatch.setattr(module, "journaliser", publier_et_retirer)
    with pytest.raises(PermissionError, match="administration active requise"):
        if phase == "preparer":
            _preparer(owner, mandat)
        elif phase == "ack":
            _ack(owner, mandat, plan)
        elif phase == "rotation":
            owner.tourner(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1,
                          nouvelle_empreinte=AUTRE_HASH_FICTIF, declaration=mandat[2])
        elif phase == "renouveler":
            owner.renouveler(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1,
                            lease_epoch=1, declaration=mandat[2])
        else:
            owner.revoquer(mandat[1], capabilite=CAPACITE_FICTIVE, epoch=1)
    with session() as cnx:
        assert cnx.execute(select(_table(module))).all() == avant
        assert cnx.execute(select(JOURNAL)).all() == audit_avant
        assert identite.personne_active(cnx, "nathan").roles == {"nathan_owner"}


def test_fence_grant_change_pendant_controle_refuse_et_rollback(mandat, session, monkeypatch):
    module, owner = _owner(mandat)
    _ack(owner, mandat, _preparer(owner, mandat))
    construire = intentions._declaration

    def construire_et_changer_fence(*args):
        valeur = construire(*args)
        cnx = stockage.connexion_courante()
        cnx.execute(update(_table(module)).values(epoch=2))
        return valeur

    monkeypatch.setattr(intentions, "_declaration", construire_et_changer_fence)
    with pytest.raises(module.DeclencheurRefuse, match="FENCE-PERIME"):
        _valider(owner, mandat)
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.epoch)) == 1


def test_revision_modifiee_pendant_vrai_toolchecker_refuse_et_rollback(mandat, session, monkeypatch):
    module, owner = _owner(mandat)
    checker = intentions.admission_agents.verifier_outil_runtime

    def checker_puis_modifier(cnx, *args, **kwargs):
        resultat = checker(cnx, *args, **kwargs)
        cnx.execute(update(PROFILS).values(revision=3))
        return resultat

    monkeypatch.setattr(intentions.admission_agents, "verifier_outil_runtime", checker_puis_modifier)
    with pytest.raises(intentions.admission_agents.AdmissionRefusee, match="configuration de profil périmée"):
        _preparer(owner, mandat)
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.intention_id)) is None
        assert cnx.scalar(select(PROFILS.c.revision)) == 2


def test_preparation_meme_hash_lease_differente_conflit(mandat, session):
    module, owner = _owner(mandat)
    premier = _preparer(owner, mandat, lease_secondes=10)
    with pytest.raises(module.DeclencheurRefuse, match="PREPARATION-CONFLIT"):
        _preparer(owner, mandat, lease_secondes=20)
    assert _preparer(owner, mandat, lease_secondes=10) == premier
    with session() as cnx:
        assert cnx.scalar(select(_table(module).c.lease_seconds)) == 10


def _upgrade(url, revision):
    with stockage.moteur(url).begin() as cnx:
        conf = stockage._config()
        conf.attributes["connection"] = cnx
        command.upgrade(conf, revision)


def test_migration_reelle_0019_0020_0021_preserve_intentions_et_ap(tmp_path):
    from opsys.stockage.schema import FUSION_AP_BROUILLONS, FUSION_AP_COMMANDES, FUSION_PDF_LOTS

    url = f"sqlite:///{tmp_path / 'historique-fictif.db'}"
    _upgrade(url, "0019")
    with stockage.moteur(url).begin() as cnx:
        cnx.execute(INTENTIONS.insert().values(
            id="a" * 64, instance_id="00000000-0000-0000-0000-000000000001", agent_id="ancien-fictif",
            profile_revision=1, profile_hash="b" * 64, trigger_hash="c" * 64, memory_policy_hash="d" * 64,
            fuseau="UTC", declaration_key="opsys-profile:" + "a" * 64, statut="a_retirer", demande_par="humain-fictif",
            demande_role="admin", cree_le="fictif", modifie_le="fictif",
        ))
        ancien = cnx.execute(select(INTENTIONS)).all()
    _upgrade(url, "0020")
    with stockage.moteur(url).begin() as cnx:
        cnx.execute(FUSION_PDF_LOTS.insert().values(
            lot_id="pdf-fictif-migration", acteur="humain-fictif", mutation_id="pdf-fictif",
            empreinte_requete="1" * 64, cle_deduplication="2" * 64, type_source="pdf_natif", classe="FINANCIAL",
            extracteur="fictif", configuration_sha256="3" * 64, source_sha256="4" * 64,
            source_octets=1, source_nonce="nonce-fictif", source_cipher="cipher-fictif-conserve",
            source_cipher_octets=17, resultat_cipher_octets=0, cle_reference="CLE_FICTIVE",
            version_format=1, statut="RECU", revision=1, total_pages=0, cree_le="fictif", modifie_le="fictif",
        ))
        cnx.execute(FUSION_AP_BROUILLONS.insert().values(
            lot_id="pdf-fictif-migration", source_sha256="4" * 64, configuration_sha256="3" * 64,
            extracteur="fictif", revision_pdf=1, revision=2, statut="A_REVOIR", auteur="humain-fictif",
            modifie_par="humain-fictif", cle_reference="CLE_FICTIVE", version_format=1,
            proposition_nonce="n" * 16, proposition_cipher="cipher-ap-fictif-conserve", proposition_cipher_octets=17,
            cree_le="fictif", modifie_le="fictif",
        ))
        cnx.execute(FUSION_AP_COMMANDES.insert().values(
            lot_id="pdf-fictif-migration", acteur="humain-fictif", mutation_id="ap-fictif",
            empreinte_requete="5" * 64, revision_resultat=2, cree_le="fictif",
        ))
        ap = cnx.execute(select(FUSION_AP_BROUILLONS)).all()
        ap_receipt = cnx.execute(select(FUSION_AP_COMMANDES)).all()
        schema = cnx.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name LIKE 'fusion_ap_%' ORDER BY name").all()
    assert stockage.revision_courante(url) == "0020"
    _upgrade(url, "0021")
    assert stockage.revision_courante(url) == "0021"
    with stockage.moteur(url).begin() as cnx:
        assert cnx.execute(select(INTENTIONS)).all() == ancien
        assert cnx.execute(select(FUSION_AP_BROUILLONS)).all() == ap
        assert cnx.execute(select(FUSION_AP_COMMANDES)).all() == ap_receipt
        assert cnx.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name LIKE 'fusion_ap_%' ORDER BY name"
        ).all() == schema
        table = importlib.import_module("opsys.agents_cron_autorite").REMISES
        columns_at_0021 = {r["name"] for r in inspect(cnx).get_columns(table.name)}
        assert columns_at_0021 == set(table.c.keys()) - {
            "native_expected_fingerprint", "native_config_fingerprint",
        }
        assert cnx.exec_driver_sql("SELECT * FROM agents_declencheurs_remises").all() == []
    _upgrade(url, "head")
    assert stockage.revision_courante(url) == "0023"
    with stockage.moteur(url).begin() as cnx:
        assert {r["name"] for r in inspect(cnx).get_columns(table.name)} == set(table.c.keys())
        assert cnx.execute(select(INTENTIONS)).all() == ancien
        assert cnx.execute(select(FUSION_AP_BROUILLONS)).all() == ap
        assert cnx.execute(select(FUSION_AP_COMMANDES)).all() == ap_receipt


def test_panne_migration_apres_creation_rollback_revision_et_table(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'panne-fictive.db'}"
    _upgrade(url, "0020")
    creer = op.create_table

    def creer_puis_refuser(nom, *args, **kwargs):
        resultat = creer(nom, *args, **kwargs)
        if nom == "agents_declencheurs_remises":
            raise RuntimeError("panne fictive 0021 après création")
        return resultat

    with monkeypatch.context() as patch:
        patch.setattr(op, "create_table", creer_puis_refuser)
        with pytest.raises(RuntimeError, match="panne fictive 0021"):
            _upgrade(url, "0021")
    assert stockage.revision_courante(url) == "0020"
    with stockage.moteur(url).begin() as cnx:
        assert "agents_declencheurs_remises" not in inspect(cnx).get_table_names()
        assert "fusion_ap_brouillons" in inspect(cnx).get_table_names()
    _upgrade(url, "0021")
    assert stockage.revision_courante(url) == "0021"
