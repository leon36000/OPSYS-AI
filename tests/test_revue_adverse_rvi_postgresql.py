"""Revue adverse rvi : l'immuabilité des journaux sur PostgreSQL ne se contourne pas par `TRUNCATE`.

Les déclencheurs de ligne (`BEFORE UPDATE OR DELETE FOR EACH ROW`) ne se réveillent jamais sur `TRUNCATE` : avant la
migration 0057, un journal « immuable » (coffre, courriel, planificateur, états de connaissances...) se vidait d'un
seul ordre sur PostgreSQL alors que SQLite refuse l'équivalent. Vrai PostgreSQL 17 jetable (Docker), données fictives.
"""

from __future__ import annotations

import pytest
from alembic import command
from pg_rvi import base_rvi, serveur_rvi  # noqa: F401  (fixtures pytest)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from opsys import stockage

FICTIF = True

_TABLES_AVEC_DECLENCHEUR_DE_LIGNE = """
SELECT DISTINCT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal AND (t.tgtype & 1) = 1 AND (t.tgtype & 2) = 2 AND (t.tgtype & (8 | 16)) <> 0
ORDER BY 1"""
_TABLES_AVEC_GARDE_TRUNCATE = """
SELECT DISTINCT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal AND (t.tgtype & 32) = 32 ORDER BY 1"""


def _noms(url, requete):
    with stockage.moteur(url).connect() as cnx:
        return [ligne[0] for ligne in cnx.execute(text(requete))]


def _poser_journal(url):
    """Une ligne de journal du coffre et un événement du bus, posés par le rôle d'administration."""
    with stockage.moteur(url).begin() as cnx:
        cnx.execute(text(
            "INSERT INTO coffre_acces (quand, nom, action, acteur, resultat) "
            "VALUES ('2026-11-01T10:00:00+00:00', 'cle-fictive', 'lecture', 'agent.fictif', 'ok')"))
        cnx.execute(text(
            "INSERT INTO evenements_sortants (evenement_id, type_evenement, producteur, charge, cree_le) "
            "VALUES ('e1', 'opsys.demo_complete', 'm01-front-office', '{}', '2026-11-01T10:00:00+00:00')"))


def _compte(url, table):
    with stockage.moteur(url).connect() as cnx:
        return cnx.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_aucune_table_immuable_ne_se_vide_par_truncate(base_rvi):  # noqa: F811
    tables = _noms(base_rvi, _TABLES_AVEC_DECLENCHEUR_DE_LIGNE)
    assert len(tables) >= 25
    acceptees = []
    for table in tables:
        try:
            with stockage.moteur(base_rvi).begin() as cnx:
                # CASCADE : PostgreSQL refuse déjà un TRUNCATE nu sur une table référencée par une clé étrangère ; c'est
                # la forme CASCADE (ou la liste complète des tables liées) qui contournait les déclencheurs de ligne.
                cnx.execute(text(f"TRUNCATE {table} CASCADE"))
            acceptees.append(table)
        except IntegrityError as erreur:
            assert "TRUNCATE interdit" in str(erreur) and table in str(erreur)
    assert acceptees == [], f"TRUNCATE accepté sur des tables immuables : {acceptees}"


def test_le_truncate_refuse_ne_detruit_rien_et_l_ecriture_legitime_reste_permise(base_rvi):  # noqa: F811
    _poser_journal(base_rvi)
    with pytest.raises(IntegrityError, match="TRUNCATE interdit"), stockage.moteur(base_rvi).begin() as cnx:
        cnx.execute(text("TRUNCATE coffre_acces, courriel_journal"))
    assert _compte(base_rvi, "coffre_acces") == 1
    with stockage.moteur(base_rvi).begin() as cnx:  # l'ajout au journal reste permis (append-only, pas gelé)
        cnx.execute(text(
            "INSERT INTO coffre_acces (quand, nom, action, acteur, resultat) "
            "VALUES ('2026-11-01T11:00:00+00:00', 'cle-fictive', 'lecture', 'agent.fictif', 'ok')"))
    assert _compte(base_rvi, "coffre_acces") == 2


def test_truncate_en_cascade_depuis_la_table_parente_est_refuse_aussi(base_rvi):  # noqa: F811
    _poser_journal(base_rvi)
    with pytest.raises(IntegrityError, match="TRUNCATE interdit"), stockage.moteur(base_rvi).begin() as cnx:
        cnx.execute(text("TRUNCATE evenements_sortants CASCADE"))
    assert _compte(base_rvi, "evenements_sortants") == 1


def test_une_table_ordinaire_reste_videable(base_rvi):  # noqa: F811
    """Négatif : la garde n'est pas un blocage général (une table sans déclencheur d'immuabilité se vide)."""
    with stockage.moteur(base_rvi).begin() as cnx:
        cnx.execute(text("CREATE TABLE brouillon_fictif (x integer)"))
        cnx.execute(text("INSERT INTO brouillon_fictif VALUES (1)"))
    with stockage.moteur(base_rvi).begin() as cnx:
        cnx.execute(text("TRUNCATE brouillon_fictif"))
    assert _compte(base_rvi, "brouillon_fictif") == 0


def test_toute_table_a_declencheur_de_ligne_a_sa_garde_truncate_pour_les_migrations_futures(base_rvi):  # noqa: F811
    avec_ligne = set(_noms(base_rvi, _TABLES_AVEC_DECLENCHEUR_DE_LIGNE))
    sans_garde = avec_ligne - set(_noms(base_rvi, _TABLES_AVEC_GARDE_TRUNCATE))
    assert sans_garde == set(), f"immuabilité de ligne sans garde TRUNCATE : {sorted(sans_garde)}"


def test_la_descente_retire_les_gardes_sans_toucher_aux_donnees_et_la_remontee_les_rend(base_rvi):  # noqa: F811
    _poser_journal(base_rvi)
    cfg = stockage._config()
    with stockage.moteur(base_rvi).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.downgrade(cfg, "0056")
    assert stockage.revision_courante(base_rvi) == "0056"
    assert _noms(base_rvi, _TABLES_AVEC_GARDE_TRUNCATE) == []
    with stockage.moteur(base_rvi).connect() as cnx:
        fonctions = cnx.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'opsys_truncate_interdit'")).scalar_one()
    assert fonctions == 0 and _compte(base_rvi, "coffre_acces") == 1
    with stockage.moteur(base_rvi).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "head")
    assert stockage.revision_courante(base_rvi) == "0057"
    with pytest.raises(IntegrityError, match="TRUNCATE interdit"), stockage.moteur(base_rvi).begin() as cnx:
        cnx.execute(text("TRUNCATE coffre_acces"))
    assert _compte(base_rvi, "coffre_acces") == 1


def test_la_migration_0057_ne_change_rien_sur_sqlite(tmp_path):
    url = "sqlite:///" + str(tmp_path / "rvi.db")
    try:
        assert stockage.migrer(url) == "0057"
        with stockage.moteur(url).connect() as cnx:
            declencheurs = cnx.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE '%truncate%'").scalar_one()
        assert declencheurs == 0
    finally:
        stockage.liberer(url)
