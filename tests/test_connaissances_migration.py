"""Migration 0041 des bases de connaissances : montée, descente, refus avec données, immuabilité (SQLite ; PostgreSQL
éphémère si Docker est disponible)."""

from __future__ import annotations

import sqlite3

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from opsys import stockage
from opsys.stockage.schema import META

FICTIF = True
TABLES = ("connaissances_espaces", "connaissances_bases", "connaissances_sources", "connaissances_versions",
          "connaissances_etats", "connaissances_fragments", "connaissances_vecteurs", "connaissances_indexations")
T = "2026-11-01T12:00:00+00:00"


def _inserer_chaine(cnx, *, vrai="1"):
    """Une base, une source, une version, un état, un fragment, un espace, un vecteur (valeurs fictives)."""
    sha = "a" * 64
    cnx.execute(text("INSERT INTO connaissances_espaces VALUES ('esp', 'f', 'm', 2, :s, '{}', :t)"), {"s": sha, "t": T})
    cnx.execute(text("INSERT INTO connaissances_bases VALUES ('m05-financecore', :t, 'p', NULL, :t)"), {"t": T})
    cnx.execute(text("INSERT INTO connaissances_sources VALUES ('src', 'm05-financecore', 'cle-source', 'T', "
                     "'general', :t, 'p')"), {"t": T})
    cnx.execute(text(
        "INSERT INTO connaissances_versions (version_id, source_id, numero, type_source, editeur, type_autorite, "
        "reference, date_consultation, licence_reutilisation, sha256, sha256_octets, empreinte_meta, texte, nb_pages, "
        f"nb_fragments, suspect, signaux, cree_le, cree_par) VALUES ('ver', 'src', 1, 'texte', 'E', 'fictive', 'r', "
        f"'2026-11-01', 'interne', :s, :s, :s, 'texte', 1, 1, {'1' if vrai == '1' else 'true'}, '[]', :t, 'p')"),
        {"s": sha, "t": T})
    cnx.execute(text("INSERT INTO connaissances_etats (version_id, etat, par, mode, quand) "
                     "VALUES ('ver', 'brouillon', 'p', 'agent', :t)"), {"t": T})
    cnx.execute(text("INSERT INTO connaissances_fragments VALUES ('chk', 'ver', 0, 'texte', :s, 1, NULL, 0, 5)"),
        {"s": sha})
    cnx.execute(text("INSERT INTO connaissances_vecteurs VALUES ('chk', 'esp', 2, :v)"), {"v": b"\x00" * 8})
    cnx.execute(text("INSERT INTO connaissances_indexations (quand, departement, genre, nb_fragments, par) "
                     "VALUES (:t, 'm05-financecore', 'lexical', 1, 'p')"), {"t": T})


def test_0041_succede_a_0040_et_la_chaine_n_a_qu_une_tete():
    cfg = stockage._config()
    scripts = ScriptDirectory.from_config(cfg)
    assert len(scripts.get_heads()) == 1  # les migrations suivantes se chaînent après 0041
    assert scripts.get_revision("0041").down_revision == "0040"


def test_migration_0041_montee_descendue_remontee(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "m.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0041")
        noms = {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master")}
        assert set(TABLES) | {"connaissances_fts"} <= noms
        assert {f"{t}_no_update" for t in TABLES if t != "connaissances_bases"} <= noms
        assert "connaissances_bases_no_update" not in noms  # la ligne de base porte l'espace actif : elle se met à jour
    vide = "sqlite:///" + str(tmp_path / "vide.db")
    with stockage.moteur(vide).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0041")
        command.downgrade(cfg, "0040")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0040"
        restes = {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE name LIKE 'connaissances%'")}
        assert restes == set()  # tables, déclencheurs et table virtuelle FTS5 partis
        command.upgrade(cfg, "0041")  # remontable


def test_le_schema_declare_et_le_schema_migre_ont_les_memes_tables_connaissances(tmp_path):
    url = "sqlite:///" + str(tmp_path / "s.db")
    stockage.migrer(url)
    attendues = {t for t in META.tables if t.startswith("connaissances_")}
    assert attendues == set(TABLES)
    reelles = {r[0] for r in sqlite3.connect(str(tmp_path / "s.db")).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'connaissances_%' "
        "AND name NOT LIKE 'connaissances_fts%'")}
    assert reelles == attendues


@pytest.mark.parametrize(("insertion", "table"), [
    ("INSERT INTO connaissances_espaces VALUES ('esp', 'f', 'm', 2, 'h', '{}', 't')", "connaissances_espaces"),
    ("INSERT INTO connaissances_bases VALUES ('m05-financecore', 't', 'p', NULL, 't')", "connaissances_bases"),
])
def test_descente_refusee_des_qu_une_table_contient_une_ligne(tmp_path, insertion, table):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / f"{table}.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0041")
        cnx.execute(text(insertion))
        with pytest.raises(RuntimeError, match=f"rétrogradation refusée : {table} contient des données"):
            command.downgrade(cfg, "0040")


def test_la_descente_refusee_ne_detruit_rien(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "r.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0041")
        _inserer_chaine(cnx)
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        with pytest.raises(RuntimeError, match="rétrogradation refusée"):
            command.downgrade(cfg, "0040")
    with stockage.moteur(url).begin() as cnx:
        assert cnx.execute(text("SELECT count(*) FROM connaissances_versions")).scalar_one() == 1
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0041"


@pytest.mark.parametrize(("instruction", "motif"), [
    ("UPDATE connaissances_versions SET texte = 'autre'", "immuable"),
    ("DELETE FROM connaissances_versions", "immuable"),
    ("UPDATE connaissances_etats SET etat = 'publie'", "immuable"),
    ("DELETE FROM connaissances_etats", "immuable"),
    ("UPDATE connaissances_fragments SET texte = 'autre'", "immuable"),
    ("UPDATE connaissances_vecteurs SET dimension = 2", "immuable"),
    ("UPDATE connaissances_espaces SET modele = 'autre'", "immuable"),
    ("UPDATE connaissances_sources SET domaine = 'general'", "immuable"),
    ("DELETE FROM connaissances_indexations", "immuable"),
])
def test_les_tables_sont_append_only_sur_sqlite(tmp_path, instruction, motif):
    url = "sqlite:///" + str(tmp_path / "ao.db")
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        _inserer_chaine(cnx)
    with pytest.raises(DBAPIError, match=motif), stockage.moteur(url).begin() as cnx:
        cnx.execute(text(instruction))


@pytest.mark.parametrize("instruction", [
    # état hors énuméré, retrait sans raison, humain sans rôle, mode inconnu
    "INSERT INTO connaissances_etats (version_id, etat, par, mode, quand) VALUES ('ver', 'archive', 'p', 'agent', 't')",
    "INSERT INTO connaissances_etats (version_id, etat, par, mode, quand) VALUES ('ver', 'retire', 'p', 'agent', 't')",
    "INSERT INTO connaissances_etats (version_id, etat, par, mode, raison, quand) VALUES ('ver', 'retire', 'p', "
    "'agent', "
    "'court', 't')",
    "INSERT INTO connaissances_etats (version_id, etat, par, mode, quand) VALUES ('ver', 'publie', 'p', 'humain', 't')",
    "INSERT INTO connaissances_etats (version_id, etat, par, mode, quand) VALUES ('ver', 'publie', 'p', 'robot', 't')",
    # version : domaine, autorité, licence, type hors énuméré ; numéro nul
    "INSERT INTO connaissances_sources VALUES ('s2', 'm05-financecore', 'autre-cle', 'T', 'astrologie', 't', 'p')",
    "INSERT INTO connaissances_vecteurs VALUES ('chk', 'esp', 3, X'0000')",
    "INSERT INTO connaissances_fragments VALUES ('c2', 'ver', 1, 'x', 'h', 1, NULL, 5, 5)",
    "INSERT INTO connaissances_indexations (quand, departement, genre, nb_fragments, par) VALUES ('t', 'd', "
    "'magie', 1, 'p')",
    "INSERT INTO connaissances_espaces VALUES ('e2', 'f', 'm', 1, 'h', '{}', 't')",
])
def test_les_contraintes_check_refusent_les_etats_et_les_formes_invalides(tmp_path, instruction):
    url = "sqlite:///" + str(tmp_path / "ck.db")
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        _inserer_chaine(cnx)
    with pytest.raises(IntegrityError), stockage.moteur(url).begin() as cnx:
        cnx.execute(text(instruction))


def test_unicite_d_une_cle_de_source_par_base_et_d_un_numero_par_source(tmp_path):
    url = "sqlite:///" + str(tmp_path / "u.db")
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        _inserer_chaine(cnx)
    with pytest.raises(IntegrityError), stockage.moteur(url).begin() as cnx:
        cnx.execute(text("INSERT INTO connaissances_sources VALUES ('s2', 'm05-financecore', 'cle-source', 'T', "
                         "'general', 't', 'p')"))
    with pytest.raises(IntegrityError), stockage.moteur(url).begin() as cnx:
        cnx.execute(text(
            "INSERT INTO connaissances_versions (version_id, source_id, numero, type_source, editeur, type_autorite, "
            "reference, date_consultation, licence_reutilisation, sha256, sha256_octets, empreinte_meta, texte, "
            "nb_pages, nb_fragments, suspect, signaux, cree_le, cree_par) VALUES ('v2', 'src', 1, 'texte', 'E', "
            "'fictive', 'r', '2026-11-01', 'interne', 'h', 'h', 'h', 't', 1, 1, 0, '[]', 't', 'p')"))


def _raison_sans_docker():
    try:
        from memoire.doubles import raison_sans_docker
    except ImportError as exc:  # pragma: no cover
        return str(exc)
    return raison_sans_docker()


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_migration_0041_sur_postgresql(monkeypatch):
    from memoire.doubles import postgres_ephemere

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            tete = ScriptDirectory.from_config(stockage._config()).get_current_head()
            assert stockage.moteur(url).dialect.name == "postgresql" and stockage.revision_courante(url) == tete
            with stockage.transaction() as cnx:
                # pas de FTS5 hors SQLite ; + `connaissances_lexique`, l'index lexical tsvector (migration 0053)
                assert cnx.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_name LIKE "
                                        "'connaissances_%'")).scalar_one() == len(TABLES) + 1
                _inserer_chaine(cnx, vrai="true")
            for instruction in ("UPDATE connaissances_versions SET texte = 'autre'", "DELETE FROM connaissances_etats",
                                "UPDATE connaissances_fragments SET texte = 'x'", "DELETE FROM connaissances_vecteurs"):
                with pytest.raises(DBAPIError, match="immuable"), stockage.transaction() as cnx:
                    cnx.execute(text(instruction))
            with pytest.raises(DBAPIError), stockage.transaction() as cnx:
                cnx.execute(text("INSERT INTO connaissances_etats (version_id, etat, par, mode, quand) "
                                 "VALUES ('ver', 'retire', 'p', 'agent', 't')"))
            cfg = stockage._config()
            with pytest.raises(RuntimeError, match="rétrogradation refusée"), stockage.moteur(url).begin() as cnx:
                cfg.attributes["connection"] = cnx
                command.downgrade(cfg, "0040")
        finally:
            stockage.liberer()
