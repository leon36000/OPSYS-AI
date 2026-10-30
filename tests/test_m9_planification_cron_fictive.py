"""M9.5 — planification quotidienne du briefing : raccord au propriétaire cron existant, base fictive isolée.

Ce que ce test qualifie (SQLite fictive, aucun grant réel, aucun hôte opérateur, aucun transport, aucun Core) :
autorisation (préparer, acquitter, valider), révocation, exécution répétée du travail planifié, reprise après lease
échue, absence de double effet. Ce qu'il ne qualifie PAS : l'ordonnanceur natif de Core, l'admission runtime d'un
déclenchement réel, une base PostgreSQL, un hôte opérateur. La ligne M9.5 reste PARTIEL tant que cela n'est pas fait.

Le travail planifié est le briefing du matin historique (``m9_produire_briefing_matin`` et sa suite) : ces deux outils
gardent la voie agent. Les outils de la salle de guerre ``outils_*`` exigent un admin authentifié : un job
planifié sans identité d'admin est refusé à l'appel (testé ci-dessous).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json

import pytest
from sqlalchemy import delete, select

from opsys import agents, stockage
from opsys import agents_declencheurs as intentions
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL, ROLES_PERSONNES

FICTIF = True
M9 = "m09-strategic-intelligence"
PROFIL = "cron-m9-fictif"
OUTILS_PLANIFIES = ["m9_produire_briefing_matin", "m9_lire_suite_briefing"]
CAPACITE = "3a" * 32
HASH_CAPACITE = hashlib.sha256(bytes.fromhex(CAPACITE)).hexdigest()
INSTANT_PLANIFIE = "2026-10-29T07:00:00-04:00"


def _creer_profil(cnx, deps, nathan, outils, mutation):
    agents.creer(
        cnx,
        deps,
        {
            "id": PROFIL,
            "departement": M9,
            "responsabilite": "Produire le briefing du matin à l'heure planifiée, sans rien écrire",
            "palier_modele": "standard",
            "outils": outils,
            "budget_jour": 1000,
            "budget_mois": 10000,
            "limite_tours": 8,
            "limite_reessais": 2,
            "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}],
        },
        par=nathan,
        mutation_id=mutation,
    )


@pytest.fixture
def mandat(session, nathan, opsys_home, monkeypatch):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(opsys_home / "core"))
    deps = charger_departements()
    with session() as cnx:
        _creer_profil(cnx, deps, nathan, OUTILS_PLANIFIES, "creation-profil-cron-m9")
        agents.definir_actif(
            cnx, PROFIL, deps, True, par=nathan, mutation_id="activation-profil-cron-m9", revision_attendue=1
        )
    politique = {
        "version": 1,
        "departements": {M9: "global"},
        "agents": {f"opsys-agent-{PROFIL}": {"departement": M9, "mode": "global"}},
        "procedures_globales": ["procedures"],
    }
    fichier = opsys_home / "core" / "opsys" / "memoire-autorites.json"
    fichier.parent.mkdir(parents=True)
    fichier.write_text(json.dumps(politique))
    demande = intentions.demander(
        deps, PROFIL, par=nathan, revision_attendue=2, fuseau="America/Toronto", mutation_id="mandat-cron-m9"
    )
    ident = demande["intentions"][0]
    declaration = intentions.projeter(deps, ident, par=nathan)["native"]["params"]
    module = importlib.import_module("opsys.agents_cron_autorite")
    return deps, ident, declaration, module, module.ProprietaireCron(deps, PROFIL)


def _preparer(mandat, **kwargs):
    deps, ident, declaration, _, owner = mandat
    return owner.preparer(ident, empreinte_capacite=HASH_CAPACITE, declaration=declaration, epoch_attendue=0, **kwargs)


def _acquitter(mandat, plan, **kwargs):
    deps, ident, declaration, _, owner = mandat
    params = {
        "capabilite": CAPACITE,
        "epoch": plan["epoch"],
        "lease_epoch": plan["lease_epoch"],
        "job_id": "job-m9-fictif",
        "config_revision": 1,
        "declaration": declaration,
    }
    return owner.accuser(ident, **(params | kwargs))


def _valider(mandat, **kwargs):
    deps, ident, declaration, _, owner = mandat
    params = {
        "capabilite": CAPACITE,
        "epoch": 1,
        "job_id": "job-m9-fictif",
        "config_revision": 1,
        "declaration": declaration,
    }
    return owner.valider(ident, **(params | kwargs))


def test_le_mandat_ne_confie_que_le_briefing_en_lecture_sans_outil_d_ecriture_ni_de_salle_de_guerre(mandat):
    declaration = mandat[2]
    assert declaration["payload"]["toolsAllow"] == sorted(f"opsys_m9__{nom}" for nom in OUTILS_PLANIFIES)
    assert declaration["schedule"]["expr"] == "0 7 * * 1-5" and declaration["schedule"]["tz"] == "America/Toronto"
    plan = _preparer(mandat)
    assert plan["execute"] is False and plan["native"]["method"] == "cron.add"


@pytest.fixture
def capacites_m9(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'execution.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield Capacites(charger_departements(), stockage.transaction, filtre={M9}, memoire=False)
    stockage.liberer()


def test_la_salle_de_guerre_admin_est_refusee_a_l_appel_sans_identite_d_admin(capacites_m9):
    """Un profil peut nommer un outil ``outils_*`` à la création, mais l'appel d'un job planifié (sans admin
    authentifié) est refusé à l'exécution : la planification ne contourne pas l'identité."""
    reponse = capacites_m9.appeler("m9_salle_de_guerre", {"reference": INSTANT_PLANIFIE})
    assert reponse["ok"] is False or reponse.get("resultat", {}).get("accepte") is False
    assert "REJ-IDENTITE-APPAREIL-INVALIDE" in json.dumps(reponse)


def test_autorisation_prepare_acquitte_valide_et_rejeu_sans_nouveau_journal(mandat, session):
    module = mandat[3]
    plan = _preparer(mandat)
    assert _preparer(mandat) == plan  # rejeu exact : même lease, non prolongée
    with pytest.raises(module.DeclencheurRefuse, match="NON-ACQUITTEE"):
        _valider(mandat)
    acquittement = _acquitter(mandat, plan)
    assert acquittement["etat"] == "remise" and acquittement["execute"] is False
    with session() as cnx:
        journal = cnx.execute(select(JOURNAL)).all()
    assert _acquitter(mandat, plan) == acquittement
    assert _valider(mandat) is None and _valider(mandat) is None  # une validation n'écrit rien
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == journal
    assert CAPACITE not in json.dumps([plan, acquittement, journal], default=str)


def test_revocation_durable_refuse_la_validation_et_le_rejeu_ne_change_rien(mandat, session):
    module, owner = mandat[3], mandat[4]
    _acquitter(mandat, _preparer(mandat))
    assert _valider(mandat) is None
    revocation = owner.revoquer(mandat[1], capabilite=CAPACITE, epoch=1)
    assert revocation["etat"] == "revoquee" and revocation["execute"] is False
    with session() as cnx:
        journal = cnx.execute(select(JOURNAL)).all()
    assert owner.revoquer(mandat[1], capabilite=CAPACITE, epoch=1) == revocation
    with pytest.raises(module.DeclencheurRefuse, match="REVOQUEE"):
        _valider(mandat)
    with session() as cnx:
        assert cnx.execute(select(JOURNAL)).all() == journal


def test_retrait_du_mandant_refuse_la_validation_sans_rien_ecrire(mandat, session):
    _acquitter(mandat, _preparer(mandat))
    with session() as cnx:
        cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == "nathan"))
    with pytest.raises(PermissionError, match="administration active requise"):
        _valider(mandat)


def test_reprise_apres_lease_echue_bornee_a_trois_prises_et_ack_perime_refuse(mandat, session, monkeypatch):
    module, owner = mandat[3], mandat[4]
    horloge = [dt.datetime(2026, 10, 29, 12, tzinfo=dt.UTC)]
    monkeypatch.setattr(module, "_maintenant", lambda: horloge[0])
    plan = _preparer(mandat, lease_secondes=10)
    horloge[0] += dt.timedelta(seconds=11)
    with pytest.raises(module.DeclencheurRefuse, match="LEASE-PERIMEE"):
        _acquitter(mandat, plan)
    reprise = owner.renouveler(
        mandat[1],
        capabilite=CAPACITE,
        epoch=1,
        lease_epoch=plan["lease_epoch"],
        declaration=mandat[2],
        lease_secondes=10,
    )
    assert reprise["lease_epoch"] == 2
    assert (
        owner.renouveler(
            mandat[1], capabilite=CAPACITE, epoch=1, lease_epoch=plan["lease_epoch"], declaration=mandat[2],
            lease_secondes=10,
        )
        == reprise
    )  # fmt: skip
    with pytest.raises(module.DeclencheurRefuse, match="LEASE-PERIMEE"):
        _acquitter(mandat, plan)  # l'ancienne lease est fencée
    assert _acquitter(mandat, reprise)["etat"] == "remise"
    assert _valider(mandat) is None


def test_reprises_bornees_a_trois_prises_par_epoque(mandat, monkeypatch):
    """Borne de reprise : préparation initiale comprise, trois prises au plus ; la quatrième est refusée."""
    module, owner = mandat[3], mandat[4]
    horloge = [dt.datetime(2026, 10, 29, 12, tzinfo=dt.UTC)]
    monkeypatch.setattr(module, "_maintenant", lambda: horloge[0])
    plan = _preparer(mandat, lease_secondes=10)
    for attendue in (2, 3):
        horloge[0] += dt.timedelta(seconds=11)
        plan = owner.renouveler(
            mandat[1], capabilite=CAPACITE, epoch=1, lease_epoch=plan["lease_epoch"], declaration=mandat[2],
            lease_secondes=10,
        )  # fmt: skip
        assert plan["lease_epoch"] == attendue
    horloge[0] += dt.timedelta(seconds=11)
    with pytest.raises(module.DeclencheurRefuse, match="TENTATIVES-EPUISEES"):
        owner.renouveler(
            mandat[1], capabilite=CAPACITE, epoch=1, lease_epoch=plan["lease_epoch"], declaration=mandat[2],
            lease_secondes=10,
        )  # fmt: skip


def _etat_registres():
    """Empreinte de TOUS les registres durables et de la file d'approbation : ce qu'un double effet modifierait."""
    from opsys.stockage.schema import APPROBATIONS, REGISTRES

    with stockage.transaction() as cnx:
        registres = [tuple(ligne) for ligne in cnx.execute(select(REGISTRES)).all()]
        approbations = [tuple(ligne) for ligne in cnx.execute(select(APPROBATIONS)).all()]
    return hashlib.sha256(json.dumps([registres, approbations], default=str, sort_keys=True).encode()).hexdigest()


def test_execution_repetee_du_travail_planifie_est_identique_et_n_ecrit_rien(capacites_m9):
    """Le déclencheur peut tirer deux fois (reprise, rejeu) : même instant planifié → même réponse, aucune écriture."""
    avant = _etat_registres()
    reponses = [
        capacites_m9.appeler("m9_produire_briefing_matin", {"maintenant": INSTANT_PLANIFIE}) for _ in range(3)
    ]
    assert all(r["ok"] is True for r in reponses), reponses
    assert reponses[0] == reponses[1] == reponses[2]
    assert _etat_registres() == avant  # ni registre, ni demande d'approbation créés par le travail planifié
    capacites_m9.appeler(
        "m9_lire_suite_briefing", {"maintenant": INSTANT_PLANIFIE, "section": "decisions", "depart": 0}
    )
    assert _etat_registres() == avant  # la lecture de la suite n'écrit rien non plus, qu'elle soit servie ou refusée
