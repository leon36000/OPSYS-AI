"""Migration 0055 : approbations d'activation irréversible (append-only) et échéances de rétention. Montée, descente,
refus de descente avec données, remontée, immuabilité, contraintes ; SQLite et PostgreSQL éphémère (Docker) si
présent."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import DBAPIError, IntegrityError

from opsys import stockage

FICTIF = True
TABLES = {"planificateur_approbations", "retention_echeances"}
APPROBATION = ("INSERT INTO planificateur_approbations (executeur, revision, apercu_empreinte, nb_elements, "
               "approuve_par, "
               "approuve_le, expire_le) VALUES ('retention.courriel', 2, '{}', 3, 'nathan', 't', 99)")
ECHEANCE = ("INSERT INTO retention_echeances (domaine, ref, portee, identifiant, echeance_epoch, cree_le, statut{}) "
            "VALUES ('voix', 'r1', 'avatars-voix/enregistrement', 's/audio', 10, 't', '{}'{})")


def _noms(cnx, motif):
    return {r[0] for r in cnx.exec_driver_sql(f"SELECT name FROM sqlite_master WHERE name LIKE '{motif}'")}


def test_0055_succede_a_0052_et_la_chaine_n_a_qu_une_tete():
    script = ScriptDirectory.from_config(stockage._config())
    assert script.get_revision("0055").down_revision == "0052"
    assert len(script.get_heads()) == 1


def test_montee_descente_et_remontee_sur_sqlite(tmp_path):
    cfg = stockage._config()
    with stockage.moteur("sqlite:///" + str(tmp_path / "m.db")).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0055")
        assert _noms(cnx, "%") >= TABLES
        assert {"planificateur_approbations_no_update", "planificateur_approbations_no_delete"} <= _noms(cnx, "%no_%")
        cnx.exec_driver_sql(APPROBATION.format("a" * 64))
        with pytest.raises(Exception, match="immuables"):
            cnx.exec_driver_sql("UPDATE planificateur_approbations SET nb_elements = 1")
        with pytest.raises(Exception, match="immuables"):
            cnx.exec_driver_sql("DELETE FROM planificateur_approbations")
        with pytest.raises(IntegrityError):  # une révision < 1 est refusée
            cnx.exec_driver_sql(APPROBATION.format("b" * 64).replace(" 2, ", " 0, "))
        with pytest.raises(IntegrityError):  # statut fermé
            cnx.exec_driver_sql(ECHEANCE.format("", "inconnu", ""))
        with pytest.raises(IntegrityError):  # « purgée » exige la date de purge, « en attente » l'interdit
            cnx.exec_driver_sql(ECHEANCE.format("", "purgee", ""))
        cnx.exec_driver_sql(ECHEANCE.format("", "en_attente", ""))
        cnx.exec_driver_sql("UPDATE retention_echeances SET statut = 'purgee', purge_le = 'quand'")  # seul état mutable
        cnx.exec_driver_sql("DELETE FROM retention_echeances")
        with pytest.raises(RuntimeError, match="rétrogradation refusée"):
            command.downgrade(cfg, "0052")  # l'approbation existe : jamais effacée
    with stockage.moteur("sqlite:///" + str(tmp_path / "v.db")).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0055")
        command.downgrade(cfg, "0052")
        assert not (TABLES & _noms(cnx, "%")) and not _noms(cnx, "planificateur_approbations_no_%")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0052"
        command.upgrade(cfg, "0055")  # remontable


def test_la_descente_est_refusee_des_qu_une_echeance_existe(tmp_path):
    cfg = stockage._config()
    with stockage.moteur("sqlite:///" + str(tmp_path / "e.db")).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0055")
        cnx.exec_driver_sql(ECHEANCE.format("", "en_attente", ""))
        with pytest.raises(RuntimeError, match="retention_echeances"):
            command.downgrade(cfg, "0052")


def _raison_sans_docker():
    try:
        from memoire.doubles import raison_sans_docker
    except ImportError as exc:  # pragma: no cover
        return str(exc)
    return raison_sans_docker()


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_migration_0055_sur_postgresql(monkeypatch):
    from memoire.doubles import postgres_ephemere

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            assert stockage.revision_courante(url) == ScriptDirectory.from_config(stockage._config()).get_current_head()
            with stockage.transaction() as cnx:
                cnx.exec_driver_sql(APPROBATION.format("a" * 64))
            for requete in ("UPDATE planificateur_approbations SET nb_elements = 1",
                            "DELETE FROM planificateur_approbations"):
                with pytest.raises(DBAPIError, match="approbations du planificateur immuables"), \
                        stockage.transaction() as cnx:
                    cnx.exec_driver_sql(requete)
            with pytest.raises(DBAPIError), stockage.transaction() as cnx:
                cnx.exec_driver_sql(ECHEANCE.format("", "purgee", ""))
            cfg = stockage._config()
            with pytest.raises(RuntimeError, match="rétrogradation refusée"), stockage.moteur(url).begin() as cnx:
                cfg.attributes["connection"] = cnx
                command.downgrade(cfg, "0052")
        finally:
            stockage.liberer()
