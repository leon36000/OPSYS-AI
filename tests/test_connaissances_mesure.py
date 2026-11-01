"""Harnais de mesure de la recherche (recall@k, MRR) : corpus fictif en français québécois, jugements écrits à la main.

Ces chiffres valident le HARNAIS et la fusion avec le double déterministe d'embeddings ; ils ne mesurent PAS la qualité
d'un vrai modèle (le double ne comprend aucun sens). Ils sont épinglés pour détecter une régression de la plomberie.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opsys import stockage
from opsys.connaissances import doubles, mesure, recherche
from opsys.connaissances.codes import ErreurConnaissances

FICTIF = True
CORPUS = Path(__file__).resolve().parents[1] / "departments/m10-memoire/evals/connaissances-recherche.v1.yaml"


@pytest.fixture(scope="module")
def corpus():
    return mesure.charger_corpus(CORPUS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rapport(corpus, tmp_path_factory):
    url = "sqlite:///" + str(tmp_path_factory.mktemp("mesure") / "mesure.db")
    stockage.migrer(url)
    try:
        with stockage.moteur(url).begin() as cnx:
            return mesure.executer(cnx, corpus, embeddeur=doubles.EmbeddingsDeterministe())
    finally:
        stockage.moteur(url).dispose()


def test_le_corpus_est_fictif_complet_et_ses_jugements_visent_des_sections_qui_existent(corpus):
    assert corpus["fictif"] is True and len(corpus["sources"]) == 10 and len(corpus["requetes"]) == 28
    titres = {}
    for s in corpus["sources"]:
        titres[s["cle"]] = {ligne[3:].strip() for ligne in s["contenu"].splitlines() if ligne.startswith("## ")}
    for q in corpus["requetes"]:
        for jugement in q["pertinents"]:
            cle, section = jugement.split("#", 1)
            assert section in titres[cle], (q["id"], jugement)  # un jugement ne vise jamais une section inventée
    types = {q["type"] for q in corpus["requetes"]}
    assert types == {"exacte", "variante", "reformulation", "sans_reponse"}
    assert all(not q["pertinents"] for q in corpus["requetes"] if q["type"] == "sans_reponse")


def test_le_corpus_ne_contient_aucun_chiffre_ou_nom_reel(corpus):
    texte = CORPUS.read_text(encoding="utf-8")
    for reel in ("TPS", "TVQ", "9,975", "Revenu Québec", "ARC", "CNESST", "RBQ", "Loi 25"):
        assert reel not in texte
    assert "Valdoré" in texte and "fictif" in texte.lower()


def test_le_rapport_declare_ses_limites_et_son_double(rapport):
    assert rapport["schema"] == "opsys.connaissances.mesure/v1" and rapport["corpus"]["fictif"] is True
    assert rapport["embeddings"]["fournisseur_id"] == "embeddings.double-test"
    assert "pas la qualité d'un vrai modèle" in rapport["avertissement"]
    assert set(rapport["modes"]) == {"lexical", "vectoriel", "hybride"}


def test_chaque_mode_rejoue_les_28_questions(rapport):
    for mode, bloc in rapport["modes"].items():
        assert len(bloc["details"]) == 28, mode
        assert bloc["global"]["questions"] == 25 and bloc["global"]["questions_sans_reponse"] == 3


def test_resultats_epingles_du_double_lexical_vectoriel_hybride(rapport):
    """Valeurs exactes, déterministes : une dérive de la plomberie (normalisation, FTS, RRF, seuils) les fait bouger."""
    g = {m: b["global"] for m, b in rapport["modes"].items()}
    assert g["lexical"] == {"questions": 25, "recall@1": 0.76, "recall@3": 0.84, "recall@5": 0.84, "mrr@10": 0.7933,
                            "faux_aucune_source": 4, "questions_sans_reponse": 3, "abstentions_correctes": 3}
    assert g["vectoriel"] == {"questions": 25, "recall@1": 0.76, "recall@3": 0.8, "recall@5": 0.8, "mrr@10": 0.78,
                              "faux_aucune_source": 4, "questions_sans_reponse": 3, "abstentions_correctes": 3}
    assert g["hybride"] == {"questions": 25, "recall@1": 0.8, "recall@3": 0.84, "recall@5": 0.84, "mrr@10": 0.8133,
                            "faux_aucune_source": 3, "questions_sans_reponse": 3, "abstentions_correctes": 3}


def test_ce_que_le_double_sait_et_ne_sait_pas_faire_par_type_de_question(rapport):
    par_type = {m: b["par_type"] for m, b in rapport["modes"].items()}
    # Les questions écrites avec les mots de la source sont retrouvées par les trois modes...
    for mode in ("lexical", "vectoriel", "hybride"):
        assert par_type[mode]["exacte"]["recall@5"] == 1.0
        assert par_type[mode]["variante"]["recall@5"] == 1.0
    # ... le vectoriel seul ne rattrape RIEN des reformulations (le double ne comprend aucun sens)...
    assert par_type["vectoriel"]["reformulation"]["recall@5"] == 0.0
    # ... et l'hybride n'invente pas de rappel que ses deux voies n'ont pas : 1 reformulation sur 5 est retrouvée (par
    # le
    # lexical), pas plus.
    assert par_type["hybride"]["reformulation"]["recall@5"] == 0.2 == par_type["lexical"]["reformulation"]["recall@5"]
    assert par_type["hybride"]["exacte"]["mrr@10"] >= max(par_type["lexical"]["exacte"]["mrr@10"],
                                                         par_type["vectoriel"]["exacte"]["mrr@10"])


def test_les_questions_sans_reponse_obtiennent_aucune_source_dans_les_trois_modes(rapport):
    for mode, bloc in rapport["modes"].items():
        sans = [d for d in bloc["details"] if d["type"] == "sans_reponse"]
        assert [d["statut"] for d in sans] == ["aucune_source"] * 3, mode
        assert all(d["abstention_correcte"] for d in sans)


def test_les_questions_reformulees_donnent_parfois_aucune_source_plutot_qu_un_mauvais_fragment(rapport):
    """Honnêteté : sur ces questions, le moteur préfère se taire que de remplir (4 « aucune source » en lexical)."""
    lexical = {d["id"]: d for d in rapport["modes"]["lexical"]["details"]}
    assert [i for i, d in lexical.items() if d["statut"] == "aucune_source" and d["type"] == "reformulation"] == [
        "q21", "q22", "q23", "q25"]


def test_deux_executions_independantes_donnent_exactement_le_meme_rapport_identifiants_compris(corpus, tmp_path):
    """Régression : des identifiants aléatoires départageaient les égalités de score au hasard (0,7933 ou 0,8133)."""
    rapports = []
    for nom in ("un", "deux"):
        url = "sqlite:///" + str(tmp_path / f"{nom}.db")
        stockage.migrer(url)
        with stockage.moteur(url).begin() as cnx:
            rapports.append(mesure.executer(cnx, corpus, embeddeur=doubles.EmbeddingsDeterministe()))
    assert rapports[0] == rapports[1]


def test_le_harnais_est_reproductible_et_ne_depend_pas_de_l_ordre_des_modes(corpus, tmp_path):
    url = "sqlite:///" + str(tmp_path / "r.db")
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        seul = mesure.executer(cnx, corpus, embeddeur=doubles.EmbeddingsDeterministe(), modes=("hybride",))
    assert list(seul["modes"]) == ["hybride"]
    assert seul["modes"]["hybride"]["global"]["mrr@10"] == 0.8133


def test_le_reranker_double_se_branche_sans_changer_la_couverture(corpus, tmp_path):
    url = "sqlite:///" + str(tmp_path / "rr.db")
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        avec = mesure.executer(cnx, corpus, embeddeur=doubles.EmbeddingsDeterministe(),
                               reranker=doubles.RerankerDeterministe(), modes=("hybride",))
    g = avec["modes"]["hybride"]["global"]
    assert avec["reranker"] == "double-couverture-v1" and g["recall@5"] == 0.84  # il réordonne, il ne retire rien


def test_seuils_rigoureux_changent_les_abstentions(corpus, tmp_path):
    url = "sqlite:///" + str(tmp_path / "sv.db")
    stockage.migrer(url)
    with stockage.moteur(url).begin() as cnx:
        strict = mesure.executer(cnx, corpus, embeddeur=doubles.EmbeddingsDeterministe(), modes=("vectoriel",),
                                 reglages=recherche.Reglages(seuil_vectoriel=0.95))
    g = strict["modes"]["vectoriel"]["global"]
    assert g["recall@5"] < 0.8 and g["abstentions_correctes"] == 3  # tout devient « aucune source »


@pytest.mark.parametrize("mauvais", [
    {"schema": "autre", "fictif": True, "sources": [], "requetes": [], "date_reference": "2026-01-01"},
    {"schema": mesure.SCHEMA_CORPUS, "fictif": False, "sources": [], "requetes": [], "date_reference": "2026-01-01"},
    {"schema": mesure.SCHEMA_CORPUS, "fictif": True, "sources": [], "requetes": [], "date_reference": "demain"},
    {"schema": mesure.SCHEMA_CORPUS, "fictif": True, "sources": [], "date_reference": "2026-01-01"},
])
def test_un_corpus_non_fictif_ou_mal_forme_est_refuse(mauvais):
    with pytest.raises(ErreurConnaissances):
        mesure.charger_corpus(mauvais)


def test_un_jugement_mal_forme_ou_une_requete_en_double_est_refuse():
    base = {"schema": mesure.SCHEMA_CORPUS, "fictif": True, "sources": [], "date_reference": "2026-01-01"}
    with pytest.raises(ErreurConnaissances):
        mesure.charger_corpus({**base, "requetes": [{"id": "q", "type": "exacte", "texte": "x",
            "pertinents": ["sans-dieze"]}]})
    with pytest.raises(ErreurConnaissances):
        mesure.charger_corpus({**base, "requetes": [{"id": "q", "type": "exacte", "texte": "x", "pertinents": []},
                                                   {"id": "q", "type": "exacte", "texte": "y", "pertinents": []}]})
