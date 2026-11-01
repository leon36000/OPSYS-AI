"""Recherche lexicale des connaissances sur PostgreSQL (tsvector + GIN) : parité de contrat avec SQLite (FTS5).

Un VRAI PostgreSQL 17 éphémère (Docker ; ignoré avec la raison exacte sinon). Données fictives, aucun réseau, double
déterministe d'embeddings. Ce que ces tests prouvent :

- la migration 0056 crée l'index lexical sur PostgreSQL seulement (SQLite : aucune opération), append-only, descente
  refusée avec données ;
- mêmes filtres, mêmes provenances, mêmes refus qu'en SQLite (publié seulement, date, périmé rétrogradé, base, requête
  hostile, terme « or », injection dans la source) ;
- sur le corpus de mesure fictif (`departments/m10-memoire/evals/connaissances-recherche.v1.yaml`), mêmes ensembles de
  résultats et mêmes métriques qu'en SQLite ; l'ORDRE peut différer (BM25 contre ts_rank_cd) : l'écart est borné ici.

Ce que ces tests ne prouvent PAS : la qualité sur un vrai corpus, la latence, le volume (index GIN à 100 000 fragments).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from alembic import command
from connaissances_aide import (
    HUMAIN,
    INJECTION,
    MAINTENANT,
    NORME,
    TAXES,
    ingerer,
    ingerer_et_publier,
    publier,
)
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from opsys import stockage
from opsys.connaissances import codes, cycle, doubles, lexical, mesure, recherche
from opsys.connaissances.codes import ErreurConnaissances
from opsys.stockage.schema import META

FICTIF = True
DOUBLE = doubles.EmbeddingsDeterministe()
CORPUS = Path(__file__).resolve().parents[1] / "departments/m10-memoire/evals/connaissances-recherche.v1.yaml"
BASE = ("m05-financecore",)
OR = """# Guide fictif du métal précieux

## Valeur de l'or
Le prix de l'or fictif de Valdoré est fixé chaque lundi matin par l'agence fictive.

## Entreposage
Le coffre fictif reste fermé en dehors des heures d'ouverture.
"""


def _chercher(cnx, requete, bases=BASE, **options):
    options.setdefault("maintenant", MAINTENANT)
    options.setdefault("embeddeur", DOUBLE)
    return recherche.rechercher(cnx, requete=requete, departements=list(bases), **options)


@pytest.fixture
def cnx_pg(base_pg):  # noqa: F811
    with stockage.transaction(base_pg) as cnx:
        yield cnx


# -- migration 0056 ----------------------------------------------------------------------------------------------------
def test_0056_succede_a_0055_et_la_chaine_n_a_qu_une_tete():
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(stockage._config())
    assert len(scripts.get_heads()) == 1
    assert scripts.get_revision("0056").down_revision == "0055"


def test_0056_sur_sqlite_ne_cree_rien_et_avance_la_revision(tmp_path):
    url = "sqlite:///" + str(tmp_path / "s.db")
    stockage.migrer(url)
    with stockage.moteur(url).connect() as cnx:
        noms = {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master")}
        assert not any("lexique" in n for n in noms) and "connaissances_fts" in noms
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() >= "0056"
    assert not any("lexique" in t for t in META.tables)  # SQLite n'a pas ce type : hors du schéma déclaré
    stockage.liberer(url)


def test_0056_sur_pg_cree_la_table_la_colonne_generee_l_index_gin_et_le_declencheur(cnx_pg):
    colonne = cnx_pg.execute(text(
        "SELECT a.attgenerated, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
        "WHERE a.attrelid = 'connaissances_lexique'::regclass AND a.attname = 'tsv'")).one()
    assert colonne == ("s", "tsvector")  # colonne GÉNÉRÉE, stockée : jamais écrite par l'application
    methode = cnx_pg.execute(text(
        "SELECT am.amname FROM pg_class c JOIN pg_am am ON am.oid = c.relam "
        "WHERE c.relname = 'ix_connaissances_lexique_tsv'")).scalar_one()
    assert methode == "gin"
    declencheurs = {r[0] for r in cnx_pg.execute(text(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'connaissances_lexique'::regclass AND NOT tgisinternal"))}
    # immuabilité de ligne (0056) + refus de TRUNCATE (0057, revue adverse rvi)
    assert declencheurs == {"connaissances_lexique_immuable", "connaissances_lexique_sans_truncate"}
    definition = cnx_pg.execute(text(
        "SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d "
        "WHERE d.adrelid = 'connaissances_lexique'::regclass"
    )).scalar_one()
    assert f"'{lexical.CONFIG_PG}'" in definition  # la configuration du code et celle de la colonne concordent


def test_0056_descente_refusee_avec_donnees_puis_permise_a_vide_et_remontable(serveur_pg):  # noqa: F811
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    cfg = stockage._config()
    try:
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "0056")
        with stockage.transaction(url) as t:
            ingerer(t)
            assert t.execute(text("SELECT count(*) FROM connaissances_lexique")).scalar_one() == 2
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            with pytest.raises(RuntimeError, match="rétrogradation refusée : connaissances_lexique contient"):
                command.downgrade(cfg, "0055")
        with stockage.moteur(url).begin() as cnx:
            lignes = cnx.exec_driver_sql("SELECT count(*) FROM connaissances_lexique").scalar_one()
            assert lignes == 2  # rien détruit
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    try:
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "0056")
            command.downgrade(cfg, "0055")
            assert cnx.exec_driver_sql("SELECT to_regclass('connaissances_lexique')").scalar_one() is None
            command.upgrade(cfg, "0056")
            assert cnx.exec_driver_sql("SELECT to_regclass('connaissances_lexique')").scalar_one() is not None
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)


@pytest.mark.parametrize("instruction", ["UPDATE connaissances_lexique SET terme = 'x'",
                                         "DELETE FROM connaissances_lexique"])
def test_l_index_lexical_postgresql_est_append_only(cnx_pg, instruction):
    ingerer(cnx_pg)
    with pytest.raises(DBAPIError, match="immuable"), cnx_pg.begin_nested():
        cnx_pg.execute(text(instruction))


def test_l_index_lexical_garde_une_ligne_par_fragment_avec_le_tsvector_des_termes_normalises(cnx_pg):
    r = ingerer(cnx_pg)
    lignes = cnx_pg.execute(text(
        "SELECT l.terme, l.tsv::text FROM connaissances_lexique l ORDER BY l.chunk_id")).all()
    assert len(lignes) == r["fragments"] == 2
    texte_taux = next(t for t, _ in lignes if "tau" in t.split())  # « taux » -> radical « tau » (normalisation Python)
    assert "valdor" in texte_taux.split() and "é" not in texte_taux  # accents repliés : même traitement que FTS5
    assert all("'tau'" in tsv for t, tsv in lignes if "tau" in t.split())


# -- adaptateur ----------------------------------------------------------------------------------------------------
def test_l_adaptateur_est_choisi_par_le_moteur_de_la_connexion(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        adaptateur = lexical.pour(cnx)
        attendu = ("postgresql-tsvector", "ts_rank_cd") if cnx.dialect.name == "postgresql" else ("sqlite-fts5", "bm25")
        assert (adaptateur.nom, adaptateur.mesure) == attendu


def test_un_autre_moteur_est_un_refus_type():
    class Faux:
        class dialect:  # noqa: N801
            name = "mysql"

    with pytest.raises(ErreurConnaissances, match=codes.BACKEND_NON_PRIS_EN_CHARGE):
        lexical.pour(Faux())


def test_la_valeur_rendue_est_dans_le_sens_naturel_et_jamais_un_zero_negatif():
    assert lexical.LexicalPostgresTsvector().valeur_rendue(-0.25) == 0.25
    rendu = lexical.LexicalPostgresTsvector().valeur_rendue(-0.0)
    assert rendu == 0.0 and str(rendu) == "0.0"
    assert lexical.LexicalSqliteFts5().valeur_rendue(-1.5) == -1.5  # bm25 : on ne touche pas à SQLite


# -- l'adaptateur seul : limite et termes hostiles --------------------------------------------------------------------
DENSE = """# Guide fictif dense

## Rappel
Valdoré taux taux taux taux.
"""
CLAIRSEME = """# Guide fictif clairsemé

## Longue section
Le taux apparaît une fois seulement dans un très long paragraphe fictif consacré à toute autre chose que le sujet, avec
beaucoup de mots supplémentaires pour diluer la densité : archives, étagères, dossiers, reliures, boîtes, classeurs,
index, registres, étiquettes, couloirs, escaliers, fenêtres, plafonniers, tapis, rideaux, lampes, bureaux, chaises.
"""


def test_la_limite_garde_les_meilleurs_candidats_sur_les_deux_moteurs(url_base):  # noqa: F811
    """`ORDER BY … LIMIT` : le tri du moteur décide QUI entre dans les candidats (l'appelant re-trie ensuite) ; avec une
    limite de 1, c'est le fragment le plus dense qui doit rester, jamais le pire."""
    with stockage.transaction(url_base) as cnx:
        # le clairsemé est ingéré EN PREMIER : sans tri, l'ordre d'insertion (celui du tas ou du rowid) le favoriserait
        ingerer_et_publier(cnx, embeddeur=DOUBLE, cle="clairseme", titre="Guide clairsemé", contenu=CLAIRSEME,
                           domaine="general")
        ingerer_et_publier(cnx, embeddeur=DOUBLE, cle="dense", titre="Guide dense", contenu=DENSE, domaine="general")
        versions = [r[0] for r in cnx.execute(text("SELECT version_id FROM connaissances_versions"))]
        adaptateur = lexical.pour(cnx)
        un = adaptateur.candidats(cnx, ["tau"], versions, 1)
        deux = adaptateur.candidats(cnx, ["tau"], versions, 5)
        assert len(deux) == 2 and un == deux[:1]  # le meilleur d'abord, et la limite garde le meilleur
        textes = {r[0]: r[1] for r in cnx.execute(text("SELECT chunk_id, texte FROM connaissances_fragments"))}
        assert "taux taux taux" in textes[un[0][0]]  # le fragment dense, pas le clairsemé


@pytest.mark.parametrize("terme_hostile",
                         ["-tau", '"tau', "tau:*", "tau&x", "tau | x", "(tau)", "TAU", "tau tau", "é", ""])
def test_l_adaptateur_n_interprete_aucun_terme_non_normalise(url_base, terme_hostile):  # noqa: F811
    """Défense en profondeur : même si un terme non normalisé arrivait à l'adaptateur, il ne devient jamais de la
    syntaxe de requête (FTS5 ou websearch) ; il est écarté, la requête rend alors moins de résultats, jamais plus."""
    with stockage.transaction(url_base) as cnx:
        ingerer_et_publier(cnx, embeddeur=DOUBLE, cle="dense", titre="Guide dense", contenu=DENSE, domaine="general")
        versions = [r[0] for r in cnx.execute(text("SELECT version_id FROM connaissances_versions"))]
        assert lexical.pour(cnx).candidats(cnx, [terme_hostile], versions, 5) == []


# -- parité de contrat -----------------------------------------------------------------------------------------------
def test_les_scores_lexicaux_portent_la_mesure_du_moteur(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        ingerer_et_publier(cnx, embeddeur=DOUBLE)
        rep = _chercher(cnx, "taux de la taxe de vente", mode="lexical")
        assert rep["statut"] == "ok" and rep["mode_effectif"] == "lexical"
        lexique = rep["resultats"][0]["scores"]["lexical"]
        cle = "ts_rank_cd" if cnx.dialect.name == "postgresql" else "bm25"
        assert set(lexique) == {"rang", cle} and lexique["rang"] == 1
        if cnx.dialect.name == "postgresql":
            assert lexique["ts_rank_cd"] > 0  # sens naturel : plus grand = meilleur


def test_un_brouillon_n_est_jamais_recherchable_sur_postgresql(cnx_pg):
    ingerer(cnx_pg, embeddeur=DOUBLE)
    assert _chercher(cnx_pg, "taux de la taxe de vente")["statut"] == "aucune_source"


def test_une_version_retiree_disparait_et_la_remplacante_se_trouve(cnx_pg):
    v1 = ingerer_et_publier(cnx_pg, embeddeur=DOUBLE)
    v2 = ingerer(cnx_pg, contenu=TAXES.replace("4,5", "5,5").replace("remboursement", "ristourne"), embeddeur=DOUBLE)
    publier(cnx_pg, v2["version_id"])
    rep = _chercher(cnx_pg, "ristourne de la taxe", mode="lexical")
    assert {r["source"]["version"] for r in rep["resultats"]} == {2}
    cycle.retirer(cnx_pg, departement="m05-financecore", source_id=v1["source_id"], raison="Remplacée par la version 2",
                  acteur=HUMAIN, maintenant=MAINTENANT)
    assert _chercher(cnx_pg, "taux de la taxe de vente", mode="lexical")["statut"] == "aucune_source"


def test_a_la_date_relit_la_base_telle_qu_elle_etait_publiee(cnx_pg):
    ingerer_et_publier(cnx_pg, embeddeur=DOUBLE, maintenant=dt.datetime(2026, 11, 1, 12, tzinfo=dt.UTC))
    avant = _chercher(cnx_pg, "taux de la taxe", mode="lexical", a_la_date="2026-10-15")
    apres = _chercher(cnx_pg, "taux de la taxe", mode="lexical", a_la_date="2026-11-01")
    assert avant["statut"] == "aucune_source" and apres["statut"] == "ok"
    with pytest.raises(ErreurConnaissances, match=codes.REQUETE_INVALIDE):
        _chercher(cnx_pg, "taux de la taxe", a_la_date="2999-01-01")


def test_une_source_perimee_passe_apres_une_source_a_jour_et_est_marquee(cnx_pg):
    ingerer_et_publier(cnx_pg, embeddeur=DOUBLE, cle="taxes-perimees", expire_le="2026-12-01")
    ingerer_et_publier(cnx_pg, embeddeur=DOUBLE, cle="taxes-a-jour", contenu=TAXES.replace("4,5", "4,6"),
                       expire_le="2027-06-01")
    rep = _chercher(cnx_pg, "taux de la taxe de vente", mode="lexical", k=5,
                    maintenant=dt.datetime(2027, 1, 15, 12, tzinfo=dt.UTC))
    sources = [(r["source"]["cle"], r["source"]["perime"]) for r in rep["resultats"]]
    assert sources[0] == ("taxes-a-jour", False) and ("taxes-perimees", True) in sources
    assert any(a["code"] == "SOURCE_PERIMEE" for a in rep["avertissements"])


def test_les_bases_sont_isolees_les_unes_des_autres(cnx_pg):
    ingerer_et_publier(cnx_pg, embeddeur=DOUBLE)
    ingerer_et_publier(cnx_pg, embeddeur=DOUBLE, departement="m03-estimation", cle="norme", contenu=NORME,
                       domaine="technique")
    taxes = _chercher(cnx_pg, "hauteur du garde-corps", bases=BASE, mode="lexical")
    norme = _chercher(cnx_pg, "hauteur du garde-corps", bases=("m03-estimation",), mode="lexical")
    assert taxes["statut"] == "aucune_source" and norme["statut"] == "ok"
    assert {r["source"]["departement"] for r in norme["resultats"]} == {"m03-estimation"}


def test_la_provenance_complete_et_la_mention_professionnelle_sont_rendues(cnx_pg):
    ingerer_et_publier(cnx_pg, embeddeur=DOUBLE)
    rep = _chercher(cnx_pg, "taux de la taxe de vente", mode="lexical")
    r = rep["resultats"][0]
    assert {"departement", "source_id", "cle", "titre", "version_id", "version", "etat", "editeur", "type_autorite",
            "reference", "date_consultation", "licence_reutilisation", "sha256", "perime"} <= set(r["source"])
    assert r["emplacement"]["fragment_sha256"] and r["fiabilite"] == "non_fiable"
    assert rep["mention_professionnelle"] and rep["mention_demonstration"]  # fiscalité + source fictive


@pytest.mark.parametrize("requete", [
    "'; DROP TABLE connaissances_lexique; --", 'taux & !taxe | (a) <-> b', '"guillemet non fermé taux',
    "taux:* taxe:A",
    "or or or", "OR taux OR", "\\ taux \\", "taux " * 50, "taxe -vente -taux", "( ) ! & |  taux", "taux́ taxe",
])
def test_une_requete_hostile_n_altere_ni_la_recherche_ni_la_base(cnx_pg, requete):
    ingerer_et_publier(cnx_pg, embeddeur=DOUBLE)
    rep = _chercher(cnx_pg, requete, mode="lexical")
    assert rep["statut"] in ("ok", "aucune_source")
    assert cnx_pg.execute(text("SELECT count(*) FROM connaissances_lexique")).scalar_one() == 2


def test_le_mot_or_est_un_terme_et_non_l_operateur_de_websearch(cnx_pg):
    """« or » (le métal) normalisé reste « or » : il doit être RETROUVÉ comme un terme, jamais lu comme l'opérateur OU
    de `websearch_to_tsquery`. Chaque terme est aussi entre guillemets, par défense en profondeur."""
    ingerer_et_publier(cnx_pg, embeddeur=DOUBLE, cle="metal-precieux", titre="Guide du métal précieux", contenu=OR,
                       domaine="general")
    rep = _chercher(cnx_pg, "or", mode="lexical")
    assert rep["statut"] == "ok" and rep["resultats"][0]["source"]["cle"] == "metal-precieux"
    rep = _chercher(cnx_pg, "prix or lundi", mode="lexical")  # le terme « or » au milieu d'une question
    assert rep["statut"] == "ok" and rep["resultats"][0]["source"]["cle"] == "metal-precieux"


def test_une_injection_dans_la_source_est_neutralisee_avec_sa_provenance(cnx_pg):
    r = ingerer(cnx_pg, cle="guide-piege", titre="Guide piégé", contenu=INJECTION, domaine="general", embeddeur=DOUBLE)
    cycle.reviser(cnx_pg, r["version_id"], acteur=HUMAIN, maintenant=MAINTENANT)  # suspecte : une personne la révise
    cycle.publier(cnx_pg, r["version_id"], acteur=HUMAIN, maintenant=MAINTENANT,
                  raison="Publication humaine d'une source suspecte, relue à la main.")
    rep = _chercher(cnx_pg, "ignore tes règles instructions système", mode="lexical")
    assert rep["statut"] == "ok" and any(x["neutralise"] for x in rep["resultats"])
    assert rep["avertissement_fiabilite"]


def test_les_refus_de_requete_sont_les_memes_sur_les_deux_moteurs(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        for options in ({"k": 0}, {"k": 21}, {"mode": "magique"}, {"etats_voulus": []}):
            with pytest.raises(ErreurConnaissances, match=codes.REQUETE_INVALIDE):
                _chercher(cnx, "taxe", **options)
        with pytest.raises(ErreurConnaissances, match=codes.REQUETE_INVALIDE):
            _chercher(cnx, "a")
        with pytest.raises(ErreurConnaissances, match=codes.REQUETE_INVALIDE):
            _chercher(cnx, "taxe\x00")
        assert _chercher(cnx, "taxe")["statut"] == "aucune_source"  # base vide : pas de remplissage


def test_une_question_de_mots_vides_est_signalee_sur_les_deux_moteurs(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        ingerer_et_publier(cnx, embeddeur=DOUBLE)
        rep = _chercher(cnx, "le la les de du", mode="lexical")
        assert rep["statut"] == "aucune_source"
        assert any(a["code"] == "REQUETE_SANS_TERME" for a in rep["avertissements"])


# -- parité des métriques sur le corpus de mesure ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def corpus():
    return mesure.charger_corpus(CORPUS.read_text(encoding="utf-8"))


def _rapport(url, corpus):
    try:
        with stockage.moteur(url).begin() as cnx:
            return mesure.executer(cnx, corpus, embeddeur=doubles.EmbeddingsDeterministe())
    finally:
        stockage.liberer(url)


def test_le_corpus_de_mesure_donne_les_memes_ensembles_et_les_memes_metriques_sur_pg_et_sqlite(
        corpus, tmp_path, base_pg):  # noqa: F811
    """Le harnais complet (ingestion, revue, publication, 28 questions x 3 modes) sur les deux moteurs.

    ÉCART DOCUMENTÉ : BM25 (SQLite) et ts_rank_cd (PostgreSQL) ordonnent différemment les fragments de score voisin.
    Sur ce corpus, les métriques sont identiques ; 3 questions sur 28 voient l'ORDRE de leur classement bouger (jamais
    l'ensemble des 10 premiers), et le rang 1 ne bouge qu'une fois (en lexical seul, une question dont la bonne
    réponse reste au rang 2 sur les deux moteurs)."""
    url_sqlite = "sqlite:///" + str(tmp_path / "mesure.db")
    stockage.migrer(url_sqlite)
    sqlite = _rapport(url_sqlite, corpus)
    pg = _rapport(base_pg, corpus)
    assert {m: b["global"] for m, b in pg["modes"].items()} == {m: b["global"] for m, b in sqlite["modes"].items()}
    for mode in ("lexical", "vectoriel", "hybride"):
        ordres_differents = rangs_1_differents = 0
        for a, b in zip(sqlite["modes"][mode]["details"], pg["modes"][mode]["details"], strict=True):
            assert a["id"] == b["id"] and a["statut"] == b["statut"], (mode, a["id"])
            assert set(a["classement"]) == set(b["classement"]), (mode, a["id"])
            ordres_differents += a["classement"] != b["classement"]
            rangs_1_differents += a["classement"][:1] != b["classement"][:1]
        assert ordres_differents <= (0 if mode == "vectoriel" else 4), (mode, ordres_differents)
        assert rangs_1_differents <= (0 if mode != "lexical" else 1), (mode, rangs_1_differents)
