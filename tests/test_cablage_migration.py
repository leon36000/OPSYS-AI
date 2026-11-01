"""Migration 0044 : tables du planificateur (exécuteurs, baux, journal append-only) et genre « courriel_contact ».

Montée, descente, refus de descente avec données, remontée ; SQLite et PostgreSQL éphémère (Docker) si disponible."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from opsys import stockage

FICTIF = True
TABLES = {"planificateur_executeurs", "planificateur_baux", "planificateur_journal"}
INSERT_BROUILLON = (
    "INSERT INTO ingestion_brouillons (brouillon_id, lot_id, document_id, genre, cle_metier, statut, raisons, cles, "
    "nonce, chiffre, revision, cree_le, modifie_le) VALUES ('b1', 'l', 'd', :genre, 'k', 'PRET', '[]', '[]', 'n', 'c', "
    "1, 't', 't')")


def _lot_et_document(cnx):
    """Un lot et un document : les clés étrangères d'un brouillon."""
    cnx.exec_driver_sql(
        "INSERT INTO ingestion_lots (lot_id, acteur, mutation_id, nom_source, source_sha256, type_source, statut, "
        "nb_documents, octets, cle_reference, version_format, cree_le, modifie_le) VALUES ('l', 'a', 'm', 'n', 'x', "
        "'zip', 'EN_COURS', 1, 1, 'K', 1, 't', 't')")
    cnx.exec_driver_sql(
        "INSERT INTO ingestion_documents (document_id, lot_id, rang, nom, taille, sha256, statut, cree_le, modifie_le) "
        "VALUES ('d', 'l', 1, 'n', 1, 'x', 'EN_ATTENTE', 't', 't')")


def _noms(cnx, motif):
    return {r[0] for r in cnx.exec_driver_sql(f"SELECT name FROM sqlite_master WHERE name LIKE '{motif}'")}


def test_la_tete_est_0044_et_succede_a_0041():
    script = ScriptDirectory.from_config(stockage._config())
    assert len(script.get_heads()) == 1  # les migrations suivantes (0049 : capacité « vision ») se chaînent après 0044
    assert script.get_revision("0044").down_revision == "0041"


def test_montee_descente_et_remontee_sur_sqlite(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "m.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0044")
        assert _noms(cnx, "planificateur_%") >= TABLES
        assert {"planificateur_journal_no_update", "planificateur_journal_no_delete"} <= _noms(cnx, "planificateur_%")
        _lot_et_document(cnx)
        cnx.execute(text(INSERT_BROUILLON), {"genre": "courriel_contact"})  # le nouveau genre est permis
        with pytest.raises(IntegrityError):
            cnx.execute(text(INSERT_BROUILLON.replace("'b1'", "'b2'")), {"genre": "inconnu"})
        with pytest.raises(IntegrityError):  # un exécuteur actif sans expiration est refusé
            cnx.exec_driver_sql(
                "INSERT INTO planificateur_executeurs (executeur, mode, intervalle_s, prochain_passage, revision, "
                "modifie_par, modifie_le, motif) VALUES ('x', 'actif', 60, 0, 1, 'a', 't', 'm')")
        cnx.exec_driver_sql("DELETE FROM ingestion_brouillons")
        cnx.exec_driver_sql("DELETE FROM ingestion_documents")
        cnx.exec_driver_sql("DELETE FROM ingestion_lots")
        command.downgrade(cfg, "0041")
        assert not (TABLES & _noms(cnx, "planificateur_%")) and not _noms(cnx, "planificateur_%")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0041"
        _lot_et_document(cnx)
        with pytest.raises(IntegrityError):  # la CHECK d'avant est rétablie
            cnx.execute(text(INSERT_BROUILLON), {"genre": "courriel_contact"})
        command.upgrade(cfg, "0044")  # remontable
        cnx.execute(text(INSERT_BROUILLON.replace("'b1'", "'b3'")), {"genre": "courriel_contact"})


@pytest.mark.parametrize("remplir", [
    "INSERT INTO planificateur_journal (quand, executeur, evenement, acteur, details) "
    "VALUES ('t', 'e', 'x', 'a', '{}')",
    "INSERT INTO planificateur_baux (ressource, porteur, jeton, acquis_epoch, expire_epoch) VALUES ('r', 'p', 1, 1, 2)",
    "INSERT INTO planificateur_executeurs (executeur, mode, intervalle_s, prochain_passage, revision, modifie_par, "
    "modifie_le, motif) VALUES ('x', 'inactif', 60, 0, 1, 'a', 't', 'm')",
])
def test_la_descente_est_refusee_des_qu_une_ligne_existe(tmp_path, remplir):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "j.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0044")
        cnx.exec_driver_sql(remplir)
        with pytest.raises(RuntimeError, match="rétrogradation refusée"):
            command.downgrade(cfg, "0041")


def test_la_descente_est_refusee_avec_un_brouillon_courriel_contact(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "b.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0044")
        _lot_et_document(cnx)
        cnx.execute(text(INSERT_BROUILLON), {"genre": "courriel_contact"})
        with pytest.raises(RuntimeError, match="courriel_contact"):
            command.downgrade(cfg, "0041")


def test_le_journal_du_planificateur_est_immuable_apres_migration(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "i.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0044")
        cnx.exec_driver_sql("INSERT INTO planificateur_journal (quand, executeur, evenement, acteur, details) "
                            "VALUES ('t', 'e', 'x', 'a', '{}')")
        for requete in ("UPDATE planificateur_journal SET code = 'x'", "DELETE FROM planificateur_journal"):
            with pytest.raises(Exception, match="immuable"):
                cnx.exec_driver_sql(requete)


def _raison_sans_docker():
    try:
        from memoire.doubles import raison_sans_docker
    except ImportError as exc:  # pragma: no cover
        return str(exc)
    return raison_sans_docker()


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_migration_0044_sur_postgresql(monkeypatch):
    from memoire.doubles import postgres_ephemere

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            assert stockage.revision_courante(url) == ScriptDirectory.from_config(stockage._config()).get_current_head()
            with stockage.transaction() as cnx:
                cnx.execute(text("INSERT INTO planificateur_journal (quand, executeur, evenement, acteur, details) "
                                 "VALUES ('t', 'e', 'x', 'a', '{}')"))
            for requete in ("UPDATE planificateur_journal SET code = 'x'", "DELETE FROM planificateur_journal"):
                attendu = pytest.raises(DBAPIError, match="journal du planificateur immuable")
                with attendu, stockage.transaction() as cnx:
                    cnx.execute(text(requete))
            # le nouveau genre est permis, un genre inconnu ne l'est pas (CHECK remplacée sur PostgreSQL)
            with stockage.transaction() as cnx:
                _lot_et_document(cnx)
                cnx.execute(text(INSERT_BROUILLON), {"genre": "courriel_contact"})
            with pytest.raises(DBAPIError), stockage.transaction() as cnx:
                cnx.execute(text(INSERT_BROUILLON.replace("'b1'", "'b2'")), {"genre": "inconnu"})
            cfg = stockage._config()
            with pytest.raises(RuntimeError, match="rétrogradation refusée"), stockage.moteur(url).begin() as cnx:
                cfg.attributes["connection"] = cnx
                command.downgrade(cfg, "0041")
        finally:
            stockage.liberer()
