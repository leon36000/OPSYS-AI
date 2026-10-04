"""Évaluation du retrieval contre le vrai PostgreSQL + pgvector et qrels fictifs indépendants.

Le mode ``double`` utilise explicitement le vecteur déterministe de tests existant; il ne qualifie
aucun modèle ni la qualité sémantique.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from memoire.doubles import jeu_or, plonger, postgres_ephemere, raison_sans_docker, vider

from opsys.memoire import MemoireEntreprise
from opsys.memoire.evaluation import evaluer

RACINE = Path(__file__).resolve().parents[1]
QRELS_PATH = RACINE / "tests/fixtures/memoire/evaluation-v1.json"
CORPUS_PATH = RACINE / "tests/fixtures/memoire/jeu_or_fr.json"
CORPUS_SHA256_ORACLE = "d3720fe1b3d66b4c93fd48271b59d595fb760d50d3db4324f80b973fe325165c"
TOUTES = ["baremes", "chantiers", "clients", "estimations", "procedures"]
RAISON_SANS_DOCKER = raison_sans_docker()
avec_postgres = pytest.mark.skipif(RAISON_SANS_DOCKER is not None, reason=str(RAISON_SANS_DOCKER))


@pytest.fixture(scope="module")
def url_pg():
    if RAISON_SANS_DOCKER is not None:
        pytest.skip(RAISON_SANS_DOCKER)
    with postgres_ephemere(stockage_en_memoire=True) as url:
        memoire = MemoireEntreprise(url)
        memoire.migrer()
        yield url


@pytest.fixture
def memoire(url_pg):
    vider(url_pg)
    return MemoireEntreprise(url_pg)


def _qrels():
    return json.loads(QRELS_PATH.read_text(encoding="utf-8"))


def _meta(fragment):
    return {
        "departement": fragment["departement"],
        "portee": fragment["portee"],
        "source": fragment["source"],
        "sensibilite": "interne",
        "sujets": fragment.get("sujets", []),
    }


@avec_postgres
def test_retriever_pg_mesure_lexical_et_double_sans_qualifier_un_modele(memoire, record_property):
    qrels = _qrels()
    chemin_declare = (RACINE / qrels["corpus"]["chemin"]).resolve(strict=True)
    assert chemin_declare == CORPUS_PATH.resolve(strict=True)
    hash_corpus = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()
    assert hash_corpus == qrels["corpus"]["sha256"] == CORPUS_SHA256_ORACLE
    corpus = jeu_or()
    ids_par_fragment = {}
    for fragment in corpus["fragments"]:
        identifiant = memoire.ajouter(fragment["texte"], _meta(fragment), plonger(fragment["texte"]))
        ids_par_fragment[identifiant] = fragment["cle"]

    assert qrels["fictif"] is True
    assert qrels["corpus"]["sha256"] == hash_corpus
    assert set(qrels["sources"]) == {fragment["cle"] for fragment in corpus["fragments"]}
    assert len(qrels["questions"]) == 9  # smoke set : pas une mesure de qualité produit

    rapports = {}
    for mode in ("lexical", "double"):
        classements = {}
        modes_store = set()
        for question in qrels["questions"]:
            vecteur = plonger(question["question"]) if mode == "double" else None
            recherche = memoire.rechercher(question["question"], vecteur, 10, {"portee": TOUTES})
            modes_store.add(recherche.mode)
            classements[question["qid"]] = [ids_par_fragment[item.fragment_id] for item in recherche.resultats]
        attendu_mode = "plein_texte" if mode == "lexical" else "hybride"
        assert modes_store == {attendu_mode}
        rapport = evaluer(qrels, classements, mode=mode)
        assert rapport["question_count"] == 9
        assert rapport["corpus_sha256"] == qrels["corpus"]["sha256"]
        assert set(rapport["forbidden_hits_by_qid"]) == {q["qid"] for q in qrels["questions"]}
        for mesure in rapport["metrics"]["all"].values():
            assert 0.0 <= mesure <= 1.0
        record_property(f"retrieval_{mode}", json.dumps(rapport, ensure_ascii=False, sort_keys=True))
        rapports[mode] = rapport

    assert rapports["lexical"]["qrels_sha256"] == rapports["double"]["qrels_sha256"]
    assert rapports["lexical"]["classements_sha256"] != ""
    assert rapports["double"]["classements_sha256"] != ""


@avec_postgres
def test_citations_provenance_version_active_et_oubli_de_la_serie(memoire):
    service = memoire.procedures()
    brut_v1 = "# Contrôle des solins\n\nVérifier les solins en cuivre chaque automne.\n".encode()
    v1 = service.admettre(brut_v1, "Contrôle toiture", auteur="admin:r31-test",
                          cle_admission="r31-eval-citation-v1")
    service.indexer(v1.document_id, v1.sha256)
    service.activer(v1.document_id, v1.sha256, attendu_sha256=None, auteur="admin:r31-test")
    uri_v1 = f"opsys-document://{v1.document_id}/{v1.sha256}"

    trouve_v1 = memoire.rechercher("solins cuivre automne", None, 5, {"portee": "procedures"})
    assert [item.source for item in trouve_v1.resultats] == [uri_v1]
    citation_v1 = trouve_v1.resultats[0].citations_verifiees[0]
    assert citation_v1.sha256 == v1.sha256
    assert citation_v1.extracteur == "procedures-1"
    position_v1 = citation_v1.positions[0]
    assert brut_v1[position_v1.debut_octets:position_v1.fin_octets].decode("utf-8") == (
        "Vérifier les solins en cuivre chaque automne."
    )

    brut_v2 = "# Réparation des joints\n\nRemplacer les joints du fascia au printemps.\n".encode()
    v2 = service.admettre(brut_v2, "Contrôle toiture", auteur="admin:r31-test",
                          cle_admission="r31-eval-citation-v2", document_id=v1.document_id)
    service.indexer(v2.document_id, v2.sha256)
    # L’indexation d’une version candidate ne rend pas l’ancienne citation obsolète.
    toujours_v1 = memoire.rechercher("solins cuivre automne", None, 5, {"portee": "procedures"})
    assert [item.source for item in toujours_v1.resultats] == [uri_v1]
    service.activer(v2.document_id, v2.sha256, attendu_sha256=v1.sha256, auteur="admin:r31-test")
    uri_v2 = f"opsys-document://{v2.document_id}/{v2.sha256}"

    obsolete = memoire.rechercher("solins cuivre automne", None, 5, {"portee": "procedures"})
    assert obsolete.resultats == ()
    actuel = memoire.rechercher("fascia printemps", None, 5, {"portee": "procedures"})
    assert [item.source for item in actuel.resultats] == [uri_v2]
    assert actuel.resultats[0].citations_verifiees[0].sha256 == v2.sha256

    assert service.oublier(v2.document_id, demandeur="admin:r31-test", motif="oubli de fixture") >= 1
    assert service.lire_etat(v2.document_id, absent_ok=True) is None
    apres_oubli = memoire.rechercher("fascia printemps", None, 5, {"portee": "procedures"})
    assert apres_oubli.resultats == ()


@avec_postgres
def test_filtres_departements_sur_le_retriever_pg_sont_effectifs(memoire):
    fragments = [
        {
            "departement": "m02-revenue-crm",
            "portee": "clients",
            "source": "fictif:r31:client",
            "sensibilite": "interne",
            "sujets": ["client:C-9901"],
            "texte": "Fictif client C-9901 : inspecter les solins du toit avant la visite.",
        },
        {
            "departement": "m04-field-ops",
            "portee": "chantiers",
            "source": "fictif:r31:chantier",
            "sensibilite": "interne",
            "sujets": ["chantier:CH-9901"],
            "texte": "Fictif chantier CH-9901 : inspecter les solins du toit avant la visite.",
        },
        {
            "departement": "m03-estimation",
            "portee": "estimations",
            "source": "fictif:r31:estimation",
            "sensibilite": "interne",
            "sujets": ["chantier:CH-9901"],
            "texte": "Fictif estimation E-9901 : inspecter les solins du toit avant la visite.",
        },
    ]
    for fragment in fragments:
        memoire.ajouter(fragment["texte"], _meta(fragment), plonger(fragment["texte"]))

    resultat = memoire.rechercher(
        "inspecter solins toit visite", plonger("inspecter solins toit visite"), 10,
        {"portee": TOUTES, "departement": "m03-estimation"},
    )
    assert {item.source for item in resultat.resultats} == {"fictif:r31:estimation"}
    assert {item.departement for item in resultat.resultats} == {"m03-estimation"}
    # Le filtre sujet reste une contrainte de retrieval libre; ce test ne prouve aucune autorité client.
