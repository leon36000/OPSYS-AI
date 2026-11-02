"""Migration 0086 : rôles de modèles. Montée, descente, refus de descente avec données, journal immuable, remontée."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory

from opsys import stockage
from opsys.stockage.schema import META, MODELES_TABLES

FICTIF = True
TABLES = {"modeles_roles", "modeles_reglages", "modeles_historique", "modeles_usage"}


def _tables(cnx):
    return {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}


def test_0086_succede_a_0058_et_la_chaine_a_une_seule_tete():
    script = ScriptDirectory.from_config(stockage._config())
    assert len(script.get_heads()) == 1
    assert script.get_revision("0086").down_revision == "0058"
    assert {t.name for t in MODELES_TABLES} == TABLES <= set(META.tables)


def test_montee_descente_refus_avec_donnees_et_remontee(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "m.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0058")
        assert not TABLES & _tables(cnx)
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0086")
        assert _tables(cnx) >= TABLES
        cnx.exec_driver_sql(
            "INSERT INTO modeles_historique (quand, cible, action, acteur, niveau) "
            "VALUES ('t', 'passerelle', 'x', 'a', 'N3')"
        )
        with pytest.raises(Exception, match="immuable"):
            cnx.exec_driver_sql("UPDATE modeles_historique SET acteur = 'b'")
        with pytest.raises(Exception, match="immuable"):
            cnx.exec_driver_sql("DELETE FROM modeles_historique")
        with pytest.raises(Exception, match="rétrogradation refusée"):
            command.downgrade(cfg, "0058")  # une ligne d'historique existe : aucune suppression
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0086"
        cnx.exec_driver_sql("DROP TRIGGER modeles_historique_no_delete")
        cnx.exec_driver_sql("DELETE FROM modeles_historique")
        cnx.exec_driver_sql(
            "CREATE TRIGGER modeles_historique_no_delete BEFORE DELETE ON modeles_historique "
            "BEGIN SELECT RAISE(ABORT,'historique des modèles immuable'); END"
        )
        command.downgrade(cfg, "0058")
        assert not TABLES & _tables(cnx)
        assert not [
            r
            for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")
            if r[0].startswith("modeles_")
        ]
        command.upgrade(cfg, "0086")  # remontable
        assert _tables(cnx) >= TABLES
        assert cnx.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"


def test_contraintes_de_roles_et_d_usage(session):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), session() as cnx:
        cnx.exec_driver_sql("INSERT INTO modeles_reglages VALUES ('inconnue', '{}', 1, 't', 'a')")
    with pytest.raises(IntegrityError), session() as cnx:
        cnx.exec_driver_sql("INSERT INTO modeles_usage VALUES ('llm_fort', '2026-11-02', -1, 0, 0, 0, 0)")
    # un rôle inconnu ne peut pas être affecté, même par écriture directe
    with pytest.raises(IntegrityError), session() as cnx:
        cnx.exec_driver_sql(
            "INSERT INTO modeles_roles (role, fournisseur_id, modele_appel, replis, revision, "
            "modifie_le, modifie_par) VALUES ('llm_geant', 'x', 'm', '[]', 1, 't', 'a')"
        )
