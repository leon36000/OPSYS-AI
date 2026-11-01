"""La chaîne COMPLÈTE de migrations sur un vrai PostgreSQL 17 : montée jusqu'à la tête, descente jusqu'à la dernière
révision que le logiciel accepte de quitter à vide, remontée, puis comparaison du schéma (tables, colonnes et leur type,
contraintes, index, déclencheurs, fonctions) avec celui de la première montée. Données fictives.

Une migration qui n'a tourné que sur SQLite peut passer ici pour une descente impossible, un type différent ou un objet
oublié ; ce test les attrape. Il ne remplace pas les tests de chaque migration (données présentes, immuabilité).
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from pg_parite import serveur_pg  # noqa: F401  (fixture pytest)
from sqlalchemy import text

from opsys import stockage

FICTIF = True
# Le logiciel REFUSE de rétrograder au-delà : 0021 supprimerait des autorités cron conservées (décision de conception).
DERNIERE_DESCENDABLE = "0021"


def _empreinte_schema(url: str) -> dict[str, list]:
    requetes = {
        "colonnes": "SELECT table_schema, table_name, column_name, data_type, is_nullable, "
                    "coalesce(column_default, ''), coalesce(is_generated, '') FROM information_schema.columns "
                    "WHERE table_schema = 'public' ORDER BY 1, 2, 3",
        "contraintes": "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                       "WHERE connamespace IN ('public'::regnamespace) ORDER BY 1, 2",
        "index": "SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes "
                 "WHERE schemaname = 'public' ORDER BY 1, 2, 3",
        "declencheurs": "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t "
                        "JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT t.tgisinternal ORDER BY 1, 2",
        "fonctions": "SELECT p.proname, md5(p.prosrc) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace "
                     "ORDER BY 1",
    }
    with stockage.moteur(url).connect() as cnx:
        resultat = {nom: [tuple(ligne) for ligne in cnx.execute(text(sql))] for nom, sql in requetes.items()}
    stockage.liberer(url)
    return resultat


def test_toute_la_chaine_monte_descend_remonte_a_l_identique_sur_postgresql(serveur_pg):  # noqa: F811
    cfg = stockage._config()
    scripts = ScriptDirectory.from_config(cfg)
    assert len(scripts.get_heads()) == 1
    tete = scripts.get_current_head()
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    try:
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "head")
        premiere = _empreinte_schema(url)
        assert premiere["colonnes"] and premiere["declencheurs"] and premiere["fonctions"]
        assert stockage.revision_courante(url) == tete

        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.downgrade(cfg, DERNIERE_DESCENDABLE)
        stockage.liberer(url)
        assert stockage.revision_courante(url) == DERNIERE_DESCENDABLE
        descendue = _empreinte_schema(url)
        assert len(descendue["colonnes"]) < len(premiere["colonnes"])  # des objets sont réellement partis
        tables_descendues = {(s, t) for s, t, *_ in descendue["colonnes"]}
        assert ("public", "connaissances_bases") not in tables_descendues  # 0041 retirée
        assert ("public", "connaissances_lexique") not in tables_descendues  # 0053 retirée

        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "head")
        stockage.liberer(url)
        assert _empreinte_schema(url) == premiere  # remontée à l'identique : types, contraintes, index, déclencheurs
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)


def test_au_dela_de_la_derniere_revision_descendable_la_descente_est_refusee_sans_rien_casser(serveur_pg):  # noqa: F811
    cfg = stockage._config()
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    try:
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, DERNIERE_DESCENDABLE)
        avant = _empreinte_schema(url)
        with pytest.raises(RuntimeError, match="rétrogradation refusée"), stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.downgrade(cfg, "-1")
        assert stockage.revision_courante(url) == DERNIERE_DESCENDABLE and _empreinte_schema(url) == avant
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)


def test_la_chaine_s_installe_dans_deux_schemas_distincts_de_la_meme_base(serveur_pg):  # noqa: F811
    """Un déploiement « un schéma par client » installe la chaîne dans le `search_path` de chacun : rien ne doit être
    qualifié en dur (ni `public.…`, ni un schéma fixe), sinon la seconde installation se heurte à la première."""
    cfg = stockage._config()
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    moteur = stockage.moteur(url)
    try:
        for schema in ("client_a", "client_b"):
            with moteur.begin() as cnx:
                cnx.exec_driver_sql(f"CREATE SCHEMA {schema}")
            with moteur.connect() as cnx:
                cnx.exec_driver_sql(f"SET search_path TO {schema}")
                cnx.commit()
                cfg.attributes["connection"] = cnx
                command.upgrade(cfg, "head")
                cnx.commit()
        with moteur.connect() as cnx:
            for schema in ("client_a", "client_b"):
                tables = {r[0] for r in cnx.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = :s"), {"s": schema})}
                assert {"alembic_version", "connaissances_lexique", "connaissances_fragments", "personnes"} <= tables
                declencheur = cnx.execute(text(
                    "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "WHERE c.relname = 'connaissances_lexique' AND c.relnamespace = CAST(:s AS regnamespace) "
                    "AND NOT t.tgisinternal"), {"s": schema}).scalar_one()
                assert declencheur == 1  # chaque schéma porte son propre déclencheur d'immuabilité
            assert cnx.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")).scalar_one() == 0
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)
