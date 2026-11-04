"""Migration 0046 : entrepôt dérivé de M8 (sept tables `m8_ent_*`) et pont BI (jetons, journal d'accès append-only).

Montée, descente, refus de descente avec des données de pont BI, remontée ; contraintes de l'entrepôt ; journal
immuable ;
DDL compilé pour PostgreSQL ; PostgreSQL éphémère (Docker) si disponible. La `down_revision` est « 0044 » sur cette
branche
(la 0045 de M2 n'y existe pas) : l'architecte la réaligne à l'intégration.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

from opsys import stockage
from opsys.stockage import schema

FICTIF = True
TABLES_ENTREPOT = {
    "m8_ent_constructions",
    "m8_ent_mesures_courantes",
    "m8_ent_mesures_hist",
    "m8_ent_dim_chantier",
    "m8_ent_dim_lead",
    "m8_ent_fait_devis",
    "m8_ent_mart_contenus",
}
TABLES_PONT = {"pont_bi_jetons", "pont_bi_acces"}
CONSTRUCTION = (
    "INSERT INTO m8_ent_constructions (construction_id, version_schema, version_catalogue, "
    "empreinte_registres, construit_le, nb_mesures, comptes) VALUES ('c1', 1, 'v', 'e', 't', 1, '{}')"
)


def _noms(cnx, motif):
    return {r[0] for r in cnx.exec_driver_sql(f"SELECT name FROM sqlite_master WHERE name LIKE '{motif}'")}


def test_la_tete_est_0046_et_succede_a_0044():
    script = ScriptDirectory.from_config(stockage._config())
    assert len(script.get_heads()) == 1  # 0049 (capacité « vision ») se chaîne après 0046
    assert script.get_revision("0046").down_revision == "0044"


def test_montee_descente_et_remontee_sur_sqlite(tmp_path):
    cfg = stockage._config()
    with stockage.moteur("sqlite:///" + str(tmp_path / "m.db")).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0046")
        assert _noms(cnx, "%") >= (TABLES_ENTREPOT | TABLES_PONT)
        assert {"pont_bi_acces_no_update", "pont_bi_acces_no_delete"} <= _noms(cnx, "pont_bi_%")
        command.downgrade(cfg, "0044")  # sans donnée de pont BI : permis, l'entrepôt est dérivé
        assert not (TABLES_ENTREPOT | TABLES_PONT) & _noms(cnx, "%") and not _noms(cnx, "pont_bi_%")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0044"
        command.upgrade(cfg, "0046")  # remontable


def test_la_descente_detruit_l_entrepot_derive_sans_perte_de_verite(tmp_path):
    cfg = stockage._config()
    with stockage.moteur("sqlite:///" + str(tmp_path / "d.db")).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0046")
        cnx.exec_driver_sql(CONSTRUCTION)
        command.downgrade(cfg, "0044")  # les lignes d'entrepôt sont reconstructibles : aucune vérité perdue
        assert not _noms(cnx, "m8_ent_%")


@pytest.mark.parametrize(
    "remplir",
    [
        "INSERT INTO pont_bi_acces (quand, epoch, phase, statut) VALUES ('t', 1, 'debut', 'accepte')",
        "INSERT INTO pont_bi_jetons (jeton_id, libelle, secret_nom, jeux, financier, quota_requetes_heure, "
        "quota_lignes_jour, "
        "cree_le, cree_par, expire_epoch, revoque) VALUES ('j', 'l', 'pont-bi.j', '[]', 0, 1, 1, 't', 'a', 1, 0)",
    ],
)
def test_la_descente_est_refusee_des_qu_un_jeton_ou_un_acces_existe(tmp_path, remplir):
    cfg = stockage._config()
    with stockage.moteur("sqlite:///" + str(tmp_path / "r.db")).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0046")
        cnx.exec_driver_sql(remplir)
        with pytest.raises(RuntimeError, match="rétrogradation refusée"):
            command.downgrade(cfg, "0044")


def test_le_journal_d_acces_est_immuable_et_les_contraintes_tiennent(tmp_path):
    cfg = stockage._config()
    with stockage.moteur("sqlite:///" + str(tmp_path / "i.db")).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0046")
        cnx.exec_driver_sql(
            "INSERT INTO pont_bi_acces (quand, epoch, phase, statut) VALUES ('t', 1, 'debut', 'accepte')"
        )
        for requete in ("UPDATE pont_bi_acces SET code = 'x'", "DELETE FROM pont_bi_acces"):
            with pytest.raises(Exception, match="immuable"):
                cnx.exec_driver_sql(requete)
        for phase, statut in (("milieu", "accepte"), ("debut", "inconnu")):
            with pytest.raises(IntegrityError):
                cnx.exec_driver_sql(
                    f"INSERT INTO pont_bi_acces (quand, epoch, phase, statut) VALUES ('t', 1, '{phase}', '{statut}')"
                )
        cnx.exec_driver_sql(CONSTRUCTION)
        with pytest.raises(IntegrityError):  # une mesure « calculée » exige une valeur ; « non calculable » n'en a pas
            cnx.exec_driver_sql(
                "INSERT INTO m8_ent_mesures_courantes (metric_id, construction_id, nom, domaine, sens, sensibilite, "
                "proprietaire, unite, statut, source, version_definition, fraicheur_terminale) VALUES "
                "('m8_x', 'c1', 'n', 'ventes', 'neutre', 'agregat', 'm02', 'u', 'calculee', 's', 'v', 0)"
            )
        with pytest.raises(IntegrityError):
            cnx.exec_driver_sql(
                "INSERT INTO m8_ent_mesures_courantes (metric_id, construction_id, nom, domaine, sens, sensibilite, "
                "proprietaire, unite, statut, valeur, source, version_definition, fraicheur_terminale) VALUES "
                "('m8_y', 'c1', 'n', 'ventes', 'neutre', 'agregat', 'm02', 'u', 'non_calculable', '0', 's', 'v', 0)"
            )
        with pytest.raises(IntegrityError):  # clé étrangère vers une construction qui n'existe pas
            cnx.exec_driver_sql("INSERT INTO m8_ent_dim_lead (lead_id, construction_id) VALUES ('l', 'absente')")
        with pytest.raises(IntegrityError):
            cnx.exec_driver_sql(
                "INSERT INTO pont_bi_jetons (jeton_id, libelle, secret_nom, jeux, financier, quota_requetes_heure, "
                "quota_lignes_jour, cree_le, cree_par, expire_epoch, revoque) VALUES ('j', 'l', 'pont-bi.j', '[]', 0, "
                "0, 1, "
                "'t', 'a', 1, 0)"
            )


def test_le_schema_complet_se_compile_pour_postgresql():
    for table in (*schema.M8_ENTREPOT_TABLES, *schema.PONT_BI_TABLES):
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for index in table.indexes:
            assert "CREATE INDEX" in str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    # aucune colonne propre à SQLite : texte, entier, booléen seulement
    types = {type(c.type).__name__ for t in (*schema.M8_ENTREPOT_TABLES, *schema.PONT_BI_TABLES) for c in t.columns}
    assert types <= {"String", "Text", "Integer", "BigInteger", "Boolean"}


def _raison_sans_docker():
    try:
        from memoire.doubles import raison_sans_docker
    except ImportError as exc:  # pragma: no cover
        return str(exc)
    return raison_sans_docker()


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_migration_0046_sur_postgresql(monkeypatch):
    from memoire.doubles import postgres_ephemere
    from sqlalchemy import text

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        assert stockage.revision_courante(url) == ScriptDirectory.from_config(stockage._config()).get_current_head()
        with stockage.transaction() as cnx:
            cnx.execute(
                text("INSERT INTO pont_bi_acces (quand, epoch, phase, statut) VALUES ('t', 1, 'debut', 'accepte')")
            )
        for requete in ("UPDATE pont_bi_acces SET code = 'x'", "DELETE FROM pont_bi_acces"):
            with pytest.raises(DBAPIError, match="immuable"), stockage.transaction() as cnx:
                cnx.execute(text(requete))


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_migration_0087_remplit_un_historique_deja_stocke_sur_postgresql(monkeypatch):
    """Le chemin PostgreSQL de la colonne dérivée : ADD COLUMN, remplissage des lignes existantes, index."""
    from memoire.doubles import postgres_ephemere
    from sqlalchemy import text

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        cfg = stockage._config()
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "0086")
            # Simule une base réellement migrée avant 0087 : la colonne n'existait pas.
            cnx.exec_driver_sql("DROP INDEX IF EXISTS ix_m8_ent_mesures_hist_metrique_utc")
            cnx.exec_driver_sql("ALTER TABLE m8_ent_mesures_hist DROP COLUMN construit_le_utc")
            cnx.execute(
                text(
                    "INSERT INTO m8_ent_constructions (construction_id, version_schema, version_catalogue, "
                    "empreinte_registres, construit_le, nb_mesures, comptes) VALUES "
                    "(:cid, 1, 'v', 'e', :instant, 1, '{}')"
                ),
                [
                    {"cid": "c1", "instant": "2026-11-01T01:30:00-04:00"},
                    {"cid": "c2", "instant": "2026-11-01T01:15:00-05:00"},
                ],
            )
            cnx.execute(
                text(
                    "INSERT INTO m8_ent_mesures_hist (construction_id, metric_id, construit_le, statut, valeur, "
                    "version_definition, dernier_fait_le) VALUES "
                    "(:cid, 'm8_leads_recus', :instant, 'calculee', :valeur, 'v', NULL)"
                ),
                [
                    {"cid": "c1", "instant": "2026-11-01T01:30:00-04:00", "valeur": "1"},
                    {"cid": "c2", "instant": "2026-11-01T01:15:00-05:00", "valeur": "2"},
                ],
            )
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "head")
        with stockage.transaction() as cnx:
            lignes = cnx.execute(
                text(
                    "SELECT construction_id, construit_le, construit_le_utc FROM m8_ent_mesures_hist "
                    "ORDER BY construit_le_utc DESC"
                )
            ).all()
            index = cnx.execute(
                text("SELECT indexname FROM pg_indexes WHERE indexname = 'ix_m8_ent_mesures_hist_metrique_utc'")
            ).all()
            from m8_analytics import entrepot_stockage

            historique = entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 50)
        assert [tuple(ligne) for ligne in lignes] == [
            ("c2", "2026-11-01T01:15:00-05:00", "2026-11-01T06:15:00.000000000Z"),
            ("c1", "2026-11-01T01:30:00-04:00", "2026-11-01T05:30:00.000000000Z"),
        ]
        assert index == [("ix_m8_ent_mesures_hist_metrique_utc",)]
        assert [ligne["construction_id"] for ligne in historique] == ["c2", "c1"]
