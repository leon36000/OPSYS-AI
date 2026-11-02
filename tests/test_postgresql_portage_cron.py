"""Cron opérateur sur PostgreSQL (défaut latent L7 du rapport de qualification) : identité de la base canonique sans
secret, verrou nommé qui sérialise les opérations cron, et N processus qui demandent la même déclaration.

Constat qui corrige le rapport : le cron opérateur n'utilisait PAS « une base SQLite fichier dédiée » ; ses tables
(`agents_declencheurs_*`, `agents_cron_*`) vivent dans la base de l'instance. Seuls l'identité de la base canonique
(`stockage.base_cron_operateur`) et l'exclusion d'écriture (`BEGIN IMMEDIATE`) étaient propres à SQLite.
Données fictives, aucun réseau.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest
from pg_concurrence import demander_cron, lancer
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import func, select

from opsys import agents, agents_declencheurs, identite, stockage
from opsys.departements import charger_departements
from opsys.stockage import base_cron_operateur
from opsys.stockage.schema import AGENTS_DECLENCHEURS_INTENTIONS as INTENTIONS
from opsys.stockage.schema import JOURNAL

FICTIF = True
N = 4


def test_l_identite_d_une_base_postgresql_ignore_le_compte_et_le_mot_de_passe_mais_pas_la_base():
    base = base_cron_operateur.identite_url_cron_operateur
    a = base("postgresql+psycopg://alice:secret-a@Serveur.Exemple:5432/opsys")
    assert a == base("postgresql+psycopg://bob:autre-secret@serveur.exemple/opsys")  # même serveur, port, base
    assert "secret" not in repr(a) and "alice" not in repr(a)
    assert a != base("postgresql+psycopg://alice:secret-a@serveur.exemple:5432/autre")
    assert a != base("postgresql+psycopg://alice:secret-a@serveur.exemple:5433/opsys")
    assert a != base("postgresql+psycopg://alice:secret-a@autre.exemple:5432/opsys")


@pytest.mark.parametrize("url", ["postgresql+psycopg://alice@/opsys", "postgresql+psycopg://alice@serveur.exemple",
                                 "mysql://a:b@h/opsys", "sqlite://", "sqlite:///:memory:"])
def test_une_identite_incomplete_ou_d_un_moteur_non_qualifie_est_refusee(url):
    with pytest.raises(ValueError, match="base non canonique"):
        base_cron_operateur.identite_url_cron_operateur(url)


def test_une_base_sqlite_garde_son_identite_de_fichier(tmp_path):
    identite_sqlite = base_cron_operateur.identite_url_cron_operateur(f"sqlite:///{tmp_path / 'o.db'}")
    assert identite_sqlite[1] == str((tmp_path / "o.db").resolve())


@pytest.fixture
def mandat(url_base, monkeypatch, tmp_path):  # noqa: F811
    """Profil d'agent actif avec un déclencheur cron, politique mémoire du cœur, personne propriétaire."""
    monkeypatch.setenv(stockage.ENV_URL, url_base)
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(tmp_path / "core"))
    deps = charger_departements()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-fictif-1234", ["nathan_owner"])
        agents.creer(cnx, deps, {
            "id": "dossiers-fictifs", "departement": "m03-estimation",
            "responsabilite": "Préparer les dossiers fictifs sans envoi externe",
            "palier_modele": "standard", "outils": [], "budget_jour": 1000, "budget_mois": 10000,
            "limite_tours": 8, "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}],
        }, par="nathan", mutation_id="creation-cron-fictive")
        agents.definir_actif(cnx, "dossiers-fictifs", deps, True, par="nathan",
                             mutation_id="activation-cron-fictive", revision_attendue=1)
    dossier = tmp_path / "core" / "opsys"
    dossier.mkdir(parents=True)
    (dossier / "memoire-autorites.json").write_text(json.dumps({
        "version": 1, "departements": {"m03-estimation": "global"},
        "agents": {"opsys-agent-dossiers-fictifs": {"departement": "m03-estimation", "mode": "global"}},
        "procedures_globales": ["procedures"]}), encoding="utf-8")
    yield deps
    stockage.liberer()


def test_la_demande_cron_s_execute_et_se_rejoue_sur_les_deux_moteurs(mandat):
    premiere = agents_declencheurs.demander(mandat, "dossiers-fictifs", par="nathan", revision_attendue=2,
                                            fuseau="America/Toronto", mutation_id="demande-cron-fictive")
    assert premiere["execute"] is False and len(premiere["intentions"]) == 1
    assert agents_declencheurs.demander(mandat, "dossiers-fictifs", par="nathan", revision_attendue=2,
                                        fuseau="America/Toronto", mutation_id="demande-cron-fictive") == premiere
    with pytest.raises(agents_declencheurs.DeclencheurRefuse, match="REVISION-PERIMEE"):
        agents_declencheurs.demander(mandat, "dossiers-fictifs", par="nathan", revision_attendue=1,
                                     fuseau="America/Toronto", mutation_id="autre-demande-cron")


def test_n_processus_demandent_la_meme_declaration_une_intention_un_audit_des_reponses_identiques(mandat):
    issues = lancer(demander_cron, [("demande-cron-concurrente", 2)] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"ok": N}, issues
    assert len({i[1] for i in issues}) == 1  # tous reçoivent la réponse du gagnant (rejeu exact)
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(INTENTIONS)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(JOURNAL).where(
            JOURNAL.c.action == "agents.cron.demande")).scalar_one() == 1


def test_n_processus_avec_des_mutations_differentes_n_ecrivent_qu_une_intention_sans_panne(mandat):
    """Mutations distinctes sur la même révision : la première crée l'intention ; les autres revalident la même
    intention (identité déterministe) sans en créer une seconde ni dupliquer la file."""
    issues = lancer(demander_cron, [(f"demande-cron-{i}", 2) for i in range(N)])
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"ok": N}, issues
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(INTENTIONS)).scalar_one() == 1
