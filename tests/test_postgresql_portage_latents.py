"""Défauts LATENTS L2 à L6 du rapport de qualification PostgreSQL, corrigés puis prouvés sur SQLite ET sur un vrai
PostgreSQL 17 (docker, sinon ignorés avec la raison exacte).

- L6 : la révision d'un profil d'agent accepte jusqu'à 2**53 - 1 dans le code, mais cinq colonnes étaient des `INTEGER`
  (refusées au-delà de 2**31 - 1 par PostgreSQL, acceptées en silence par SQLite). Migration 0057 : `BIGINT` sur
  PostgreSQL seulement, descente qui REFUSE de perdre des données.
- Les `epoch` / `lease_epoch` du cron sont des COMPTEURS que le code borne à 2**31 - 1 : colonne et borne concordent
  (ce ne sont pas des secondes depuis 1970, il n'y a pas de débordement en 2038) ; le test le fige.
Données fictives, aucun réseau.
"""

from __future__ import annotations

import pytest
from alembic import command
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import BigInteger, Integer, insert, select, text
from sqlalchemy.exc import DBAPIError

from opsys import agents_cron_autorite, agents_declencheurs, stockage
from opsys.stockage.schema import (
    AGENTS_CONFIGURABLES,
    AGENTS_CONFIGURABLES_HISTORIQUE,
    AGENTS_DECLENCHEURS_INTENTIONS,
    AGENTS_DECLENCHEURS_REMISES,
    AGENTS_GRANTS_CFO,
    AGENTS_TICKETS_CFO,
    META,
)

FICTIF = True
MAX_53 = 2**53 - 1
COLONNES_64_BITS = (
    ("agents_configurables", "revision"),
    ("agents_configurables_historique", "revision"),
    ("agents_declencheurs_intentions", "profile_revision"),
    ("agents_grants_cfo", "profile_revision"),
    ("agents_tickets_cfo", "profile_revision"),
)


def test_le_schema_declare_les_cinq_colonnes_de_revision_en_64_bits():
    for table, colonne in COLONNES_64_BITS:
        assert isinstance(META.tables[table].c[colonne].type, BigInteger), (table, colonne)


def test_epoch_et_lease_epoch_restent_des_compteurs_bornes_par_le_code_a_31_bits():
    """Documenté dans la migration 0057 : même borne dans la colonne et dans le code, aucun débordement possible."""
    assert isinstance(AGENTS_DECLENCHEURS_REMISES.c.epoch.type, Integer)
    assert isinstance(AGENTS_DECLENCHEURS_REMISES.c.lease_epoch.type, Integer)
    assert agents_cron_autorite._positif(2**31 - 1) == 2**31 - 1
    with pytest.raises(agents_cron_autorite.DeclencheurRefuse, match="VERSION-INVALIDE"):
        agents_cron_autorite._positif(2**31)


def test_le_code_accepte_une_revision_de_2_puissance_53_moins_1():
    agents_declencheurs._arguments("agent-fictif", MAX_53, "mutation-fictive-1")
    with pytest.raises(agents_declencheurs.DeclencheurRefuse, match="REVISION-INVALIDE"):
        agents_declencheurs._arguments("agent-fictif", MAX_53 + 1, "mutation-fictive-1")


def _profil(revision: int) -> dict:
    return dict(
        id="agent-fictif", departement="m03-estimation", responsabilite="Essai FICTIF", palier_modele="local",
        outils="[]", budget_jour=1, budget_mois=1, limite_tours=1, limite_reessais=0, limite_concurrence=1,
        declencheurs="[]", actif=True, supprime=False, revision=revision, cree_le="2026-11-01T00:00:00+00:00",
        modifie_le="2026-11-01T00:00:00+00:00", modifie_par="admin.fictif", mutation_id="mutation-fictive-1",
        mutation_hash="0" * 64)


def test_une_revision_de_profil_de_2_puissance_53_est_stockee_et_relue_a_l_identique(url_base):  # noqa: F811
    """L6 : avant 0057, PostgreSQL refusait toute révision > 2**31 - 1 (« integer out of range »), pourtant admise."""
    with stockage.transaction(url_base) as cnx:
        cnx.execute(insert(AGENTS_CONFIGURABLES).values(**_profil(MAX_53)))
        cnx.execute(insert(AGENTS_CONFIGURABLES_HISTORIQUE).values(
            agent_id="agent-fictif", revision=MAX_53, instantane="{}", modifie_le="2026-11-01T00:00:00+00:00",
            modifie_par="admin.fictif", mutation_id="mutation-fictive-1"))
        cnx.execute(insert(AGENTS_DECLENCHEURS_INTENTIONS).values(
            id="i" * 64, instance_id="instance-fictive", agent_id="agent-fictif", profile_revision=MAX_53,
            profile_hash="0" * 64, trigger_hash="1" * 64, memory_policy_hash="2" * 64, fuseau="America/Montreal",
            declaration_key="opsys-profile:" + "i" * 64, statut="a_declarer", demande_par="admin.fictif",
            demande_role="admin", cree_le="2026-11-01T00:00:00+00:00", modifie_le="2026-11-01T00:00:00+00:00"))
        cnx.execute(insert(AGENTS_GRANTS_CFO).values(
            agent_id="agent-fictif", instance_id="instance-fictive", profile_revision=MAX_53, version=1, active=True,
            tools="[]", reports_per_day=1, expires_at="2031-01-01T00:00:00+00:00", report_date_start="2026-01-01",
            report_date_end="2026-12-31", granted_by="admin.fictif", granted_role="admin",
            created_at="2026-11-01T00:00:00+00:00", modified_at="2026-11-01T00:00:00+00:00",
            modified_by="admin.fictif", modified_role="admin"))
        cnx.execute(insert(AGENTS_TICKETS_CFO).values(
            ticket_hash="t" * 64, agent_id="agent-fictif", grant_version=1, profile_revision=MAX_53,
            instance_id="instance-fictive", tool="m5_preparer_dossier_decision_cfo", arguments_hash="a" * 64,
            created_at="2026-11-01T00:00:00+00:00", expires_at="2026-11-01T01:00:00+00:00"))
    with stockage.transaction(url_base) as cnx:
        assert cnx.execute(select(AGENTS_CONFIGURABLES.c.revision)).scalar_one() == MAX_53
        assert cnx.execute(select(AGENTS_CONFIGURABLES_HISTORIQUE.c.revision)).scalar_one() == MAX_53
        assert cnx.execute(select(AGENTS_DECLENCHEURS_INTENTIONS.c.profile_revision)).scalar_one() == MAX_53
        assert cnx.execute(select(AGENTS_GRANTS_CFO.c.profile_revision)).scalar_one() == MAX_53
        assert cnx.execute(select(AGENTS_TICKETS_CFO.c.profile_revision)).scalar_one() == MAX_53


def test_sur_postgresql_les_cinq_colonnes_sont_bigint_et_les_compteurs_cron_restent_integer(base_pg):  # noqa: F811
    with stockage.transaction(base_pg) as cnx:
        types = dict(cnx.execute(text(
            "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema()")).all())
    for table, colonne in COLONNES_64_BITS:
        assert types[f"{table}.{colonne}"] == "bigint", (table, colonne)
    assert types["agents_declencheurs_remises.epoch"] == "integer"
    assert types["agents_declencheurs_remises.lease_epoch"] == "integer"


def test_0057_succede_a_0056_et_la_chaine_n_a_qu_une_tete():
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(stockage._config())
    assert len(scripts.get_heads()) == 1
    assert scripts.get_revision("0057").down_revision == "0056"


def test_0057_sur_sqlite_ne_change_rien_et_avance_la_revision(tmp_path):
    url = "sqlite:///" + str(tmp_path / "s.db")
    stockage.migrer(url)
    with stockage.moteur(url).connect() as cnx:
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() >= "0057"
    stockage.liberer(url)


def test_0057_descente_refusee_avec_une_valeur_64_bits_puis_permise_sans_perte_et_remontable(serveur_pg):  # noqa: F811
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    cfg = stockage._config()
    try:
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "0057")
            cnx.execute(insert(AGENTS_CONFIGURABLES).values(**_profil(2**40)))
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            with pytest.raises(RuntimeError, match="rétrogradation refusée : agents_configurables.revision"):
                command.downgrade(cfg, "0056")
        with stockage.moteur(url).begin() as cnx:  # rien n'a été perdu ni converti
            assert cnx.exec_driver_sql("SELECT revision FROM agents_configurables").scalar_one() == 2**40
            cnx.exec_driver_sql("UPDATE agents_configurables SET revision = 7")
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.downgrade(cfg, "0056")
            assert cnx.exec_driver_sql(
                "SELECT data_type FROM information_schema.columns WHERE table_name = 'agents_configurables' "
                "AND column_name = 'revision'").scalar_one() == "integer"
            assert cnx.exec_driver_sql("SELECT revision FROM agents_configurables").scalar_one() == 7
            command.upgrade(cfg, "0057")
            assert cnx.exec_driver_sql(
                "SELECT data_type FROM information_schema.columns WHERE table_name = 'agents_configurables' "
                "AND column_name = 'revision'").scalar_one() == "bigint"
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)


def test_sans_la_migration_0057_postgresql_refuse_la_revision_que_le_code_accepte(serveur_pg):  # noqa: F811
    """Témoin du défaut d'origine : à 0056, une révision > 2**31 - 1 est une erreur de base, pas un refus typé."""
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    cfg = stockage._config()
    try:
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "0056")
        with pytest.raises(DBAPIError, match="out of range"), stockage.moteur(url).begin() as cnx:
            cnx.execute(insert(AGENTS_CONFIGURABLES).values(**_profil(MAX_53)))
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)
