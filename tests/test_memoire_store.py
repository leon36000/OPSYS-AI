"""MemoireEntreprise contre un vrai PostgreSQL 17 + pgvector (conteneur docker éphémère).

Les embeddings viennent d'un double déterministe local : bge-m3 est un service externe. Sans démon
docker, ces tests sont SKIP avec la raison exacte, jamais un faux vert.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from memoire.doubles import jeu_or, plonger, plonger_lot, port_ferme, postgres_ephemere, raison_sans_docker, vider

from opsys.memoire import MemoireEntreprise, MemoireIndisponible

RAISON_SANS_DOCKER = raison_sans_docker()
avec_docker = pytest.mark.skipif(RAISON_SANS_DOCKER is not None, reason=str(RAISON_SANS_DOCKER))
TOUTES = ["clients", "chantiers", "estimations", "baremes", "procedures"]


def _dans(jours: int) -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(days=jours)


def _meta(**autres):
    meta = {"departement": "m03-estimation", "portee": "estimations", "source": "fictif:test",
            "sensibilite": "interne"}
    meta.update(autres)
    return meta


@pytest.fixture(scope="module")
def url_pg():
    if RAISON_SANS_DOCKER is not None:
        pytest.skip(RAISON_SANS_DOCKER)
    with postgres_ephemere() as url:
        MemoireEntreprise(url).migrer()
        yield url


@pytest.fixture
def memoire(url_pg):
    vider(url_pg)
    return MemoireEntreprise(url_pg)


def _sql(url, requete, *params):
    import psycopg

    with psycopg.connect(url) as cnx:
        return cnx.execute(requete, params).fetchall()


# -- schéma --------------------------------------------------------------------------------------------
@avec_docker
def test_migrer_est_idempotente_et_cree_index_hnsw_gin_et_plein_texte_francais(url_pg):
    MemoireEntreprise(url_pg).migrer()  # deuxième application : aucun effet ni erreur
    index = {nom: definition for nom, definition in _sql(
        url_pg, "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'memoire'")}
    assert any("USING hnsw" in d and "vector_cosine_ops" in d for d in index.values())
    assert any("USING gin (tsv)" in d for d in index.values())
    assert any("USING gin (sujets)" in d for d in index.values())
    # plein texte français insensible aux accents : l'utilisateur tape souvent sans accents
    (accent, sans_accent), = _sql(url_pg, "SELECT to_tsvector('memoire.francais', 'Réparations'),"
                                          " to_tsvector('memoire.francais', 'reparation')")
    assert accent == sans_accent
    (dimension,), = _sql(url_pg, "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'memoire.fragments'::regclass"
                                 " AND attname = 'embedding'")
    assert dimension == 1024


@avec_docker
def test_schema_absent_donne_une_erreur_qui_dit_quoi_faire(url_pg):
    import psycopg

    with psycopg.connect(url_pg, autocommit=True) as cnx:
        cnx.execute("DROP DATABASE IF EXISTS vierge")
        cnx.execute("CREATE DATABASE vierge")
    vierge = MemoireEntreprise(url_pg.rsplit("/", 1)[0] + "/vierge")
    with pytest.raises(MemoireIndisponible, match="migrer"):
        vierge.etat()


def test_base_injoignable_erreur_explicite_sans_fuite_du_mot_de_passe():
    memoire = MemoireEntreprise(f"postgresql://postgres:motdepasse-secret@127.0.0.1:{port_ferme()}/postgres")
    with pytest.raises(MemoireIndisponible, match="PostgreSQL injoignable") as erreur:
        memoire.etat()
    assert "motdepasse-secret" not in str(erreur.value)
    assert "motdepasse-secret" not in repr(memoire)


# -- recherche hybride --------------------------------------------------------------------------------
def _charger_jeu_or(memoire, avec_embeddings=True):
    donnees = jeu_or()
    ids = {}
    for fragment in donnees["fragments"]:
        meta = {"departement": fragment["departement"], "portee": fragment["portee"],
                "source": fragment["source"], "sensibilite": "interne", "sujets": fragment.get("sujets", [])}
        embedding = plonger(fragment["texte"]) if avec_embeddings else None
        ids[memoire.ajouter(fragment["texte"], meta, embedding)] = fragment["cle"]
    return donnees, ids


def _rappel(memoire, donnees, ids, hybride, k=3):
    trouves = 0
    for question in donnees["questions"]:
        embedding = plonger(question["question"]) if hybride else None
        recherche = memoire.rechercher(question["question"], embedding, k, {"portee": TOUTES})
        assert recherche.mode == ("hybride" if hybride else "plein_texte")
        trouves += question["attendu"] in [ids[r.fragment_id] for r in recherche.resultats]
    return trouves / len(donnees["questions"])


@avec_docker
def test_hybride_bat_le_plein_texte_seul_sur_le_jeu_d_or_francais(memoire):
    donnees, ids = _charger_jeu_or(memoire)
    rappel_hybride = _rappel(memoire, donnees, ids, hybride=True)
    rappel_plein_texte = _rappel(memoire, donnees, ids, hybride=False)
    assert rappel_hybride == 1.0
    assert rappel_plein_texte < rappel_hybride


@avec_docker
def test_resultat_porte_provenance_rangs_et_score_rrf(memoire):
    memoire.ajouter("Garantie de 10 ans sur la toiture.", _meta(portee="procedures", source="fictif:garanties",
                                                                   titre="Politique de garanties"),
                    plonger("Garantie de 10 ans sur la toiture."))
    recherche = memoire.rechercher("garantie toiture", plonger("garantie toiture"), 5, {"portee": ["procedures"]})
    (resultat,) = recherche.resultats
    assert (resultat.source, resultat.titre, resultat.portee) == ("fictif:garanties", "Politique de garanties",
                                                                   "procedures")
    assert (resultat.rang_lexical, resultat.rang_vectoriel) == (1, 1)
    assert resultat.score == pytest.approx(2 / 61)


@avec_docker
def test_mode_plein_texte_explicite_sans_embedding(memoire):
    memoire.ajouter("Dépôt de 15 % à la signature du contrat.", _meta(portee="procedures"))
    plein_texte = memoire.rechercher("depot signature", None, 5, {"portee": "procedures"})
    assert plein_texte.mode == "plein_texte"
    assert [(r.rang_lexical, r.rang_vectoriel) for r in plein_texte.resultats] == [(1, None)]
    # une requête vectorisée retrouve aussi un fragment non vectorisé, par la voie lexicale
    hybride = memoire.rechercher("depot signature", plonger("depot signature"), 5, {"portee": "procedures"})
    assert hybride.mode == "hybride" and len(hybride.resultats) == 1


# -- cloisonnement -----------------------------------------------------------------------------------
@avec_docker
def test_filtres_de_portee_de_sujet_et_de_departement_cloisonnent(memoire):
    textes = [
        ("Toiture à refaire chez le client, bardeaux usés.", "clients", "m02-revenue-crm", ["client:C-0001"]),
        ("Toiture à refaire, chantier de la rue des Érables.", "chantiers", "m04-field-ops", ["chantier:CH-1"]),
        ("Toiture : autre client, aucune urgence.", "clients", "m02-revenue-crm", ["client:C-0002"]),
        ("Toiture estimée entre 12 000 $ et 14 000 $.", "estimations", "m03-estimation", ["client:C-0001"]),
    ]
    for texte, portee, departement, sujets in textes:
        memoire.ajouter(texte, _meta(portee=portee, departement=departement, sujets=sujets,
                                     source=f"fictif:{portee}:{sujets[0]}"), plonger(texte))

    def portees(filtres):
        recherche = memoire.rechercher("toiture", plonger("toiture"), 10, filtres)
        return sorted((r.portee, r.sujets[0]) for r in recherche.resultats)

    assert portees({"portee": ["chantiers"]}) == [("chantiers", "chantier:CH-1")]
    assert portees({"portee": ["clients", "estimations"], "sujet": "client:C-0001"}) == [
        ("clients", "client:C-0001"), ("estimations", "client:C-0001")]
    assert portees({"portee": TOUTES, "departement": "m03-estimation"}) == [("estimations", "client:C-0001")]
    assert portees({"portee": TOUTES, "source": "fictif:chantiers:chantier:CH-1"}) == [("chantiers", "chantier:CH-1")]
    with pytest.raises(ValueError, match="portee"):
        memoire.rechercher("toiture", None, 5, {"sujet": "client:C-0001"})
    with pytest.raises(ValueError, match="filtre inconnu"):
        memoire.rechercher("toiture", None, 5, {"portee": "clients", "client": "C-0001"})
    with pytest.raises(ValueError, match="k"):
        memoire.rechercher("toiture", None, 0, {"portee": "clients"})


# -- Loi 25 : effacement, rétention -------------------------------------------------------------------
@avec_docker
def test_oublier_efface_en_cascade_et_journalise_sans_le_texte(memoire, url_pg):
    commun = "fictif:courriel-2026-09-12"
    memoire.ajouter("Mme Tremblay (C-0042) demande un rappel jeudi.",
                    _meta(portee="clients", source=commun, sensibilite="personnelle", sujets=["client:C-0042"],
                          expire_le=_dans(365)))
    memoire.ajouter("M. Gagnon (C-0043) confirme la visite.",
                    _meta(portee="clients", source=commun, sensibilite="personnelle", sujets=["client:C-0043"],
                          expire_le=_dans(365)))
    memoire.ajouter("Photos du sous-sol de C-0042 reçues.",
                    _meta(portee="chantiers", source="fictif:photos-C-0042", sensibilite="personnelle",
                          sujets=["client:C-0042", "chantier:CH-9"], expire_le=_dans(365)))
    memoire.ajouter("Estimation pour C-0042 : sous-sol.", _meta(source="fictif:estimation-C-0042",
                                                                sujets=["client:C-0042"]))

    effaces = memoire.oublier({"sujet": "client:C-0042"}, demandeur="M2 sur demande écrite du client",
                              motif="Loi 25 art. 28 : demande de suppression")
    assert effaces == 3
    restants = memoire.rechercher("C-0042 sous-sol rappel", None, 10,
                                  {"portee": TOUTES, "sujet": "client:C-0042"})
    assert restants.resultats == ()
    assert memoire.etat()["documents"] == 1  # documents orphelins supprimés, le courriel commun reste
    (journal,), = _sql(url_pg, "SELECT row_to_json(j) FROM memoire.journal_effacements j")
    assert (journal["fragments"], journal["documents"]) == (3, 2)
    assert journal["filtres"] == {"sujet": "client:C-0042"}
    assert "Tremblay" not in json.dumps(journal) and "sous-sol" not in json.dumps(journal)

    assert memoire.oublier({"source": commun}, demandeur="patron", motif="nettoyage") == 1
    assert memoire.etat()["fragments"] == 0
    with pytest.raises(ValueError, match="au moins un filtre"):
        memoire.oublier({}, demandeur="patron", motif="tout effacer")
    with pytest.raises(ValueError, match="demandeur"):
        memoire.oublier({"sujet": "client:C-1"}, demandeur=" ", motif="x")


@avec_docker
def test_fragment_echu_invisible_puis_purge_et_journalise(memoire, url_pg):
    ident = memoire.ajouter("Numéro de cellulaire de C-0099 pour le suivi.",
                            _meta(portee="clients", sensibilite="personnelle", sujets=["client:C-0099"],
                                  expire_le=_dans(30)))
    assert len(memoire.rechercher("cellulaire suivi", None, 5, {"portee": "clients"}).resultats) == 1
    # le temps passe : l'échéance est dépassée
    _sql(url_pg, "UPDATE memoire.fragments SET cree_le = now() - interval '40 days',"
                 " expire_le = now() - interval '1 second' WHERE id = %s RETURNING id", ident)
    assert memoire.rechercher("cellulaire suivi", None, 5, {"portee": "clients"}).resultats == ()
    assert memoire.etat()["echus_a_purger"] == 1
    assert memoire.purger_expires() == 1
    assert memoire.purger_expires() == 0
    motifs = _sql(url_pg, "SELECT demandeur, motif, fragments FROM memoire.journal_effacements")
    assert motifs == [("opsys:retention", "rétention échue (expire_le dépassée)", 1)]


# -- écriture ------------------------------------------------------------------------------------------
@avec_docker
@pytest.mark.parametrize(
    ("texte", "meta", "embedding", "motif"),
    [
        ("x", {"departement": "m03-estimation", "source": "s", "sensibilite": "interne"}, None, "portee"),
        ("x", _meta(expire="2030-01-01"), None, "clé inconnue"),
        ("x", _meta(sensibilite="secrete"), None, "sensibilite"),
        ("x", _meta(sensibilite="personnelle", sujets=["client:C-1"]), None, "expire_le"),
        ("x", _meta(sensibilite="personnelle", expire_le=_dans(10)), None, "sujets"),
        ("x", _meta(expire_le=_dans(-1)), None, "déjà passée"),
        ("x", _meta(expire_le=dt.datetime(2030, 1, 1)), None, "fuseau"),
        ("x", _meta(sujets=["Client C-1"]), None, "sujet"),
        ("x", _meta(departement="M3 Estimation"), None, "departement"),
        ("   ", _meta(), None, "texte vide"),
        ("x", _meta(), [0.1] * 1023, "1024"),
        ("x", _meta(), [float("nan")] + [0.1] * 1023, "fini"),
        ("x", _meta(), [0.0] * 1024, "nul"),
    ],
)
def test_ajouter_refuse_les_metadonnees_invalides(memoire, texte, meta, embedding, motif):
    with pytest.raises(ValueError, match=motif):
        memoire.ajouter(texte, meta, embedding)
    assert memoire.etat()["fragments"] == 0


@avec_docker
def test_ajouter_est_idempotent_et_complete_l_embedding_manquant(memoire):
    texte = "Accès au terrain par la ruelle."
    premier = memoire.ajouter(texte, _meta(portee="clients"))
    second = memoire.ajouter(texte, _meta(portee="clients"), plonger(texte))
    assert premier == second
    etat = memoire.etat()
    assert (etat["fragments"], etat["sans_embedding"]) == (1, 0)


@avec_docker
def test_texte_compose_ou_decompose_donne_le_meme_fragment(memoire):
    import unicodedata

    compose = "Réparation de la fenêtre du sous-sol."
    decompose = unicodedata.normalize("NFD", compose)
    assert compose != decompose
    assert memoire.ajouter(compose, _meta()) == memoire.ajouter(decompose, _meta())
    trouve = memoire.rechercher(unicodedata.normalize("NFD", "fenêtre réparation"), None, 5,
                                {"portee": "estimations"})
    assert [r.texte for r in trouve.resultats] == [compose]


@avec_docker
def test_completer_embeddings_rattrape_sans_toucher_aux_personnelles_par_defaut(memoire):
    memoire.ajouter("Barème peinture intérieure 2026.", _meta(portee="baremes"))
    memoire.ajouter("Téléphone de C-0100.", _meta(portee="clients", sensibilite="personnelle",
                                                  sujets=["client:C-0100"], expire_le=_dans(90)))
    assert memoire.completer_embeddings(plonger_lot, inclure_personnelles=False) == 1
    assert memoire.etat()["sans_embedding"] == 1
    assert memoire.completer_embeddings(plonger_lot, inclure_personnelles=True) == 1
    assert memoire.etat()["sans_embedding"] == 0
    recherche = memoire.rechercher("bareme peinture", plonger("bareme peinture"), 5, {"portee": "baremes"})
    assert recherche.resultats[0].rang_vectoriel == 1
