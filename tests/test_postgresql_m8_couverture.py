"""Qualification PostgreSQL réelle de la migration M8 0088 (données entièrement fictives)."""

from __future__ import annotations

import pytest
from alembic import command
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import insert, inspect, text

from opsys import stockage
from opsys.stockage.schema import M8_ENT_CONSTRUCTIONS, M8_ENT_MESURES_COURANTES, M8_ENT_MESURES_HIST


@pytest.fixture
def postgres_m8(monkeypatch):
    with postgres_ephemere(stockage_en_memoire=True) as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            yield url
        finally:
            stockage.liberer(url)


@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
def test_migration_0088_postgresql_preserve_historique_et_garde_la_retrogradation(postgres_m8):
    """Un schéma 0087 réel est migré sans inférer les couvertures passées ni perdre de lignes."""
    from m8_analytics import entrepot_stockage

    url = postgres_m8
    cfg = stockage._config()
    instant_ancien = "2026-11-03T10:00:00-05:00"
    instant_nouveau = "2026-11-04T10:00:00-05:00"
    couverture = {
        "etat": "partielle",
        "couverts": 2,
        "attendus": 3,
        "manquants": 1,
        "raison": "un fait fictif manque",
    }

    # Partir de la vraie chaîne de migrations jusqu'à 0087, puis reproduire les deux
    # tables telles qu'elles existaient avant 0088.
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0087")
        cnx.exec_driver_sql("ALTER TABLE m8_ent_mesures_courantes DROP COLUMN couverture")
        cnx.exec_driver_sql("ALTER TABLE m8_ent_mesures_hist DROP COLUMN couverture")
        cnx.execute(
            insert(M8_ENT_CONSTRUCTIONS).values(
                construction_id="construction-ancienne-fictive",
                version_schema=1,
                version_catalogue="catalogue-fictif",
                empreinte_registres="empreinte-fictive",
                construit_le=instant_ancien,
                nb_mesures=1,
                comptes="{}",
            )
        )
        cnx.execute(
            text(
                "INSERT INTO m8_ent_mesures_courantes "
                "(metric_id, construction_id, nom, domaine, sens, sensibilite, proprietaire, unite, statut, "
                "valeur, detail, source, version_definition, dernier_fait_le, fraicheur_attendue_s, "
                "fraicheur_terminale) VALUES "
                "('m8_historique_fictif', 'construction-ancienne-fictive', 'Mesure fictive', 'operations', "
                "'croissant', 'normal', 'm08-analytics', 'compte', 'calculee', '7', 'détail conservé', "
                "'source fictive', 'definition-ancienne', :instant, 86400, false)"
            ),
            {"instant": instant_ancien},
        )
        cnx.execute(
            text(
                "INSERT INTO m8_ent_mesures_hist "
                "(construction_id, metric_id, construit_le, construit_le_utc, statut, valeur, "
                "version_definition, dernier_fait_le) VALUES "
                "('construction-ancienne-fictive', 'm8_historique_fictif', :instant, "
                "'2026-11-03T15:00:00.000000000Z', 'calculee', '7', 'definition-ancienne', :instant)"
            ),
            {"instant": instant_ancien},
        )

    # 0088 ajoute les colonnes sans remplir les anciennes lignes par une couverture supposée.
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0088")
        assert cnx.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0088"
        for table in ("m8_ent_mesures_courantes", "m8_ent_mesures_hist"):
            colonnes = {col["name"] for col in inspect(cnx).get_columns(table)}
            assert "couverture" in colonnes
        assert cnx.execute(
            text("SELECT couverture IS NULL FROM m8_ent_mesures_courantes "
                 "WHERE metric_id = 'm8_historique_fictif'")
        ).scalar_one() is True
        assert cnx.execute(
            text("SELECT couverture IS NULL FROM m8_ent_mesures_hist "
                 "WHERE construction_id = 'construction-ancienne-fictive'")
        ).scalar_one() is True

        ancienne_courante = cnx.execute(
            text(
                "SELECT construction_id, valeur, detail, source, version_definition, couverture "
                "FROM m8_ent_mesures_courantes WHERE metric_id = 'm8_historique_fictif'"
            )
        ).one()
        assert tuple(ancienne_courante) == (
            "construction-ancienne-fictive", "7", "détail conservé", "source fictive", "definition-ancienne", None
        )
        ancienne_historique = cnx.execute(
            text(
                "SELECT construction_id, metric_id, construit_le, construit_le_utc, statut, valeur, "
                "version_definition, dernier_fait_le, couverture FROM m8_ent_mesures_hist "
                "WHERE construction_id = 'construction-ancienne-fictive'"
            )
        ).one()
        assert tuple(ancienne_historique) == (
            "construction-ancienne-fictive",
            "m8_historique_fictif",
            instant_ancien,
            "2026-11-03T15:00:00.000000000Z",
            "calculee",
            "7",
            "definition-ancienne",
            instant_ancien,
            None,
        )

        cnx.execute(
            insert(M8_ENT_CONSTRUCTIONS).values(
                construction_id="construction-nouvelle-fictive",
                version_schema=2,
                version_catalogue="catalogue-fictif",
                empreinte_registres="empreinte-fictive-nouvelle",
                construit_le=instant_nouveau,
                nb_mesures=1,
                comptes="{}",
            )
        )
        cnx.execute(
            insert(M8_ENT_MESURES_COURANTES).values(
                metric_id="m8_couverture_fictive",
                construction_id="construction-nouvelle-fictive",
                nom="Mesure structurée fictive",
                domaine="operations",
                sens="croissant",
                sensibilite="normal",
                proprietaire="m08-analytics",
                unite="compte",
                statut="calculee",
                valeur="2",
                detail="couverture partielle fictive",
                source="source fictive",
                version_definition="definition-nouvelle",
                dernier_fait_le=instant_nouveau,
                fraicheur_attendue_s=86400,
                fraicheur_terminale=False,
                couverture=couverture,
            )
        )
        cnx.execute(
            insert(M8_ENT_MESURES_HIST).values(
                construction_id="construction-nouvelle-fictive",
                metric_id="m8_historique_fictif",
                construit_le=instant_nouveau,
                construit_le_utc="2026-11-04T15:00:00.000000000Z",
                statut="calculee",
                valeur="2",
                version_definition="definition-nouvelle",
                dernier_fait_le=instant_nouveau,
                couverture=couverture,
            )
        )

        # La lecture SQLAlchemy décode le JSON structuré et conserve aussi l'ancien NULL.
        courantes = {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}
        assert courantes["m8_couverture_fictive"]["couverture"] == couverture
        historique = entrepot_stockage.lire_historique(cnx, "m8_historique_fictif", limite=10)
        par_construction = {ligne["construction_id"]: ligne for ligne in historique}
        assert par_construction["construction-nouvelle-fictive"]["couverture"] == couverture
        assert par_construction["construction-ancienne-fictive"]["couverture"] is None
        assert len(historique) == 2

        # La rétrogradation doit refuser de supprimer les JSON désormais enregistrés.
        with pytest.raises(RuntimeError, match="rétrogradation refusée : couvertures M8 présentes"):
            command.downgrade(cfg, "0087")

    # Après le refus, le schéma 0088 et les données des deux constructions sont toujours présents.
    with stockage.moteur(url).begin() as cnx:
        assert cnx.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0088"
        assert cnx.execute(
            text("SELECT couverture FROM m8_ent_mesures_courantes WHERE metric_id = 'm8_couverture_fictive'")
        ).scalar_one() == couverture
        assert cnx.execute(
            text("SELECT valeur FROM m8_ent_mesures_hist WHERE construction_id = 'construction-ancienne-fictive'")
        ).scalar_one() == "7"
        assert cnx.execute(text("SELECT count(*) FROM m8_ent_mesures_hist")).scalar_one() == 2


@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
def test_migration_0088_postgresql_reprend_un_schema_partiellement_etendu(postgres_m8):
    cfg = stockage._config()
    with stockage.moteur(postgres_m8).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0087")
        # Le schéma courant peut déjà contenir une colonne sur une des deux tables.
        cnx.exec_driver_sql("ALTER TABLE m8_ent_mesures_hist DROP COLUMN couverture")
        command.upgrade(cfg, "0088")
        for table in ("m8_ent_mesures_courantes", "m8_ent_mesures_hist"):
            assert "couverture" in {col["name"] for col in inspect(cnx).get_columns(table)}
        command.upgrade(cfg, "0088")
        assert cnx.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0088"
