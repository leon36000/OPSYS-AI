"""Sauvegarde / restauration d'une base OPSYS sur un vrai PostgreSQL 17 : `pg_dump -Fc` puis `pg_restore` (binaires de
l'image, exécutés DANS le conteneur éphémère), contenu comparé table par table, gardes (déclencheurs append-only,
colonne `tsvector` générée) et recherche lexicale vérifiées sur la base restaurée.

Ce que cela prouve : le format personnalisé `pg_dump` d'une instance réelle (schéma migré jusqu'à la tête, données
fictives de plusieurs départements) se restaure à l'identique sur une base vide, y compris les déclencheurs
d'immuabilité et l'index lexical (la colonne générée est recalculée, jamais copiée). Ce que cela NE prouve PAS : la
restauration d'un cluster physique (`pgdata`), la sauvegarde à chaud sous charge, le chiffrement de l'archive, la
copie hors site ni la restauration sur une autre version majeure ; les scripts `deploy/backup.sh` et
`deploy/restore.sh` ont leurs propres bancs (`tests/test_deploy_backup_restore.py`,
`tests/e2e/test_deploy_postgresql_restore.py`).
"""

from __future__ import annotations

import pytest
from connaissances_aide import MAINTENANT, TAXES, ingerer_et_publier
from pg_parite import base_pg, serveur_pg  # noqa: F401  (fixtures pytest)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from opsys import approbations, etat, identite, stockage
from opsys.connaissances import doubles, recherche
from opsys.outils import Niveau
from opsys.stockage.schema import META

FICTIF = True
DOUBLE = doubles.EmbeddingsDeterministe()


def _empreintes(url: str) -> dict[str, tuple[int, str]]:
    """Par table (schéma public) : nombre de lignes et md5 de leur rendu texte trié (contenu complet)."""
    resultat: dict[str, tuple[int, str]] = {}
    with stockage.moteur(url).connect() as cnx:
        tables = [r[0] for r in cnx.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"))]
        for table in tables:
            n, h = cnx.execute(text(
                f"SELECT count(*), coalesce(md5(string_agg(t::text, '|' ORDER BY t::text)), '') FROM {table} t")).one()
            resultat[table] = (n, h)
    stockage.liberer(url)
    return resultat


def _objets(url: str) -> tuple[set[str], set[str], set[str]]:
    with stockage.moteur(url).connect() as cnx:
        declencheurs = {f"{r[0]}.{r[1]}" for r in cnx.execute(text(
            "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal"))}
        fonctions = {r[0] for r in cnx.execute(text(
            "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public'"))}
        generees = {f"{r[0]}.{r[1]}" for r in cnx.execute(text(
            "SELECT c.relname, a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "WHERE a.attgenerated <> '' AND c.relnamespace = 'public'::regnamespace"))}
    stockage.liberer(url)
    return declencheurs, fonctions, generees


@pytest.fixture
def base_garnie(base_pg):  # noqa: F811
    """Une base migrée portant des données fictives de plusieurs domaines : identité, journal, approbation, registre
    chaîné, base de connaissances publiée (index lexical compris)."""
    with stockage.transaction(base_pg) as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-fictif-1234", ["nathan_owner"])
        approbations.creer_demande(cnx, "m09-demo", "m9_compte", {"x": 1}, niveau=Niveau.N4)
        etat.journaliser(cnx, "nathan", "essai.sauvegarde", "cible-fictive", {"k": "v"})
        ingerer_et_publier(cnx, embeddeur=DOUBLE)
        ingerer_et_publier(cnx, embeddeur=DOUBLE, departement="m03-estimation", cle="norme", domaine="technique",
                           contenu=TAXES.replace("taxe", "norme").replace("Taxes", "Normes"))
    stockage.liberer(base_pg)
    return base_pg


def test_pg_dump_puis_pg_restore_redonnent_la_meme_base_gardes_et_recherche_comprises(serveur_pg, base_garnie):  # noqa: F811
    nom_source = base_garnie.rsplit("/", 1)[1]
    avant = _empreintes(base_garnie)
    # la base est garnie : 4 fragments indexés, 2 versions
    assert avant["connaissances_lexique"][0] == 4 and avant["connaissances_versions"][0] == 2
    assert avant["alembic_version"][0] == 1 and avant["personnes"][0] == 1
    # toutes les tables du schéma déclaré, plus l'index lexical dérivé, sont comparées
    assert set(META.tables) | {"alembic_version", "connaissances_lexique"} <= set(avant)

    archive = "/tmp/opsys-qualif.dump"
    dump = serveur_pg.docker_exec("pg_dump", "-U", "postgres", "-Fc", "-d", nom_source, "-f", archive)
    assert dump.returncode == 0, dump.stderr.decode()[-400:]
    liste = serveur_pg.docker_exec("pg_restore", "-l", archive)
    assert liste.returncode == 0 and b"connaissances_lexique" in liste.stdout  # l'archive lit et contient l'index

    nom_cible = "restauree_" + nom_source
    cree = serveur_pg.docker_exec("createdb", "-U", "postgres", nom_cible)
    assert cree.returncode == 0, cree.stderr.decode()
    try:
        restauration = serveur_pg.docker_exec("pg_restore", "-U", "postgres", "-d", nom_cible, "--no-owner",
                                              "--exit-on-error", archive)
        assert restauration.returncode == 0, restauration.stderr.decode()[-600:]
        url = serveur_pg.url(nom_cible)

        # 1. mêmes lignes, mêmes contenus, sur TOUTES les tables (la colonne générée tsv est recalculée à l'identique)
        assert _empreintes(url) == avant
        # 2. mêmes déclencheurs, fonctions plpgsql et colonnes générées
        assert _objets(url) == _objets(base_garnie)
        # 3. la base restaurée est à la tête des migrations : rien à rejouer, rien à perdre
        assert stockage.migrer(url) == stockage.revision_courante(url) == stockage.revision_courante(base_garnie)
        # 4. les gardes d'immuabilité fonctionnent encore après restauration
        with stockage.moteur(url).connect() as cnx:
            for instruction in ("UPDATE connaissances_versions SET texte = 'x'", "DELETE FROM connaissances_etats",
                                "DELETE FROM connaissances_lexique"):
                with pytest.raises(DBAPIError, match="immuable"), cnx.begin():
                    cnx.execute(text(instruction))
        # 5. les séquences d'identifiants reprennent APRÈS les valeurs restaurées : une écriture neuve ne
        # collisionne pas (le journal et les événements d'état utilisent des colonnes auto-incrémentées)
        with stockage.transaction(url) as cnx:
            ancien_max = cnx.execute(text("SELECT max(id) FROM journal")).scalar_one()
            etat.journaliser(cnx, "nathan", "essai.apres.restauration", "cible-fictive", {})
            assert cnx.execute(text("SELECT max(id) FROM journal")).scalar_one() > ancien_max
        stockage.liberer(url)
        # 6. la recherche lexicale rend les mêmes résultats avant et après
        def chercher(u):
            with stockage.transaction(u) as cnx:
                rep = recherche.rechercher(cnx, requete="taux de la taxe de vente", departements=["m05-financecore"],
                                           maintenant=MAINTENANT, mode="lexical", k=5)
            return [(r["chunk_id"], r["scores"]["lexical"]) for r in rep["resultats"]]

        resultats = chercher(url)
        assert resultats and resultats == chercher(base_garnie)
    finally:
        stockage.liberer(nom_cible)
        serveur_pg.supprimer(nom_cible)
        serveur_pg.docker_exec("rm", "-f", archive)


def test_une_archive_tronquee_ou_alteree_est_refusee_sans_rien_restaurer(serveur_pg, base_garnie):  # noqa: F811
    nom_source = base_garnie.rsplit("/", 1)[1]
    archive = "/tmp/opsys-qualif-alteree.dump"
    assert serveur_pg.docker_exec("pg_dump", "-U", "postgres", "-Fc", "-d", nom_source, "-f", archive).returncode == 0
    nom_cible = "alteree_" + nom_source
    assert serveur_pg.docker_exec("createdb", "-U", "postgres", nom_cible).returncode == 0
    try:
        # on tronque l'archive à la moitié de sa taille : pg_restore doit échouer, jamais restaurer à moitié en silence
        coupe = serveur_pg.docker_exec("sh", "-c", f"head -c $(( $(wc -c < {archive}) / 2 )) {archive} > {archive}.cut")
        assert coupe.returncode == 0
        restauration = serveur_pg.docker_exec("pg_restore", "-U", "postgres", "-d", nom_cible, "--no-owner",
                                              "--exit-on-error", f"{archive}.cut")
        assert restauration.returncode != 0
    finally:
        serveur_pg.supprimer(nom_cible)
        serveur_pg.docker_exec("rm", "-f", archive, f"{archive}.cut")
