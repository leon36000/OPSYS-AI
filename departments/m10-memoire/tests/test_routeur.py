"""Contrat du noyau pur M10-07 (candidats fictifs; aucune autorisation n'est évaluée ici)."""

from __future__ import annotations

import copy
import json

import pytest
from m10_memoire import routeur

FICTIF = True


def _candidat(source="affaires", ref="registre://ligne/1", rang=1, **changes):
    valeur = {
        "domaine": "affaires",
        "source": source,
        "reference": ref,
        "rang": rang,
        "contenu": "Résumé fictif.",
        "citation": {"source": source, "reference": ref, "sha256": "a" * 64},
        "statut": "actif",
        "fraicheur": "courant",
        "autorite": "journal",
        "module": "m10-memoire",
    }
    valeur.update(changes)
    return valeur


def _fusion(listes, **kwargs):
    poids = kwargs.pop("poids_sources", {source: 1.0 for source in listes})
    return routeur.fusionner(
        domaine="affaires",
        listes=listes,
        k=kwargs.pop("k", 60),
        poids_sources=poids,
        limite=kwargs.pop("limite", 10),
        max_caracteres_extraits=kwargs.pop("max_caracteres_extraits", 2000),
        **kwargs,
    )


def test_rrf_applique_k_et_les_poids_explicites_et_trie_stablement():
    affaires = [_candidat("affaires", "r://a", 1), _candidat("affaires", "r://b", 2)]
    connaissances = [_candidat("connaissances", "r://b", 1), _candidat("connaissances", "r://a", 2)]
    resultat = _fusion({"affaires": affaires, "connaissances": connaissances}, k=1,
                       poids_sources={"affaires": 2.0, "connaissances": 1.0})
    scores = {item["reference"]: item["score"] for item in resultat["resultats"]}
    assert scores["r://a"] == pytest.approx(2 / 2 + 1 / 3)
    assert scores["r://b"] == pytest.approx(2 / 3 + 1 / 2)
    assert resultat["resultats"][0]["reference"] == "r://a"


def test_ordre_entree_ne_change_pas_la_fusion():
    un = {"affaires": [_candidat(ref="r://a"), _candidat(ref="r://b", rang=2)],
          "connaissances": [_candidat("connaissances", "r://b"), _candidat("connaissances", "r://a", 2)]}
    deux = {source: list(reversed(candidats)) for source, candidats in un.items()}
    assert _fusion(un) == _fusion(deux)


def test_dedoublonne_par_reference_et_cumule_les_contributions():
    resultat = _fusion({"affaires": [_candidat()], "connaissances": [
        _candidat("connaissances", "registre://ligne/1")
    ]})
    assert len(resultat["resultats"]) == 1
    assert resultat["resultats"][0]["score"] == pytest.approx(2 / 61)
    assert resultat["resultats"][0]["sources"] == ["affaires", "connaissances"]
    assert [citation["source"] for citation in resultat["resultats"][0]["citations"]] == [
        "affaires", "connaissances"
    ]


def test_refuse_rang_duplique_dans_une_meme_source():
    with pytest.raises(routeur.RefusRouteur, match="rang en double"):
        _fusion({"affaires": [_candidat(ref="r://a"), _candidat(ref="r://b")]})


def test_refuse_reference_dupliquee_dans_une_meme_source():
    assert len(_fusion({"affaires": [_candidat(ref="r://a", rang=1)]})["resultats"]) == 1
    with pytest.raises(routeur.RefusRouteur, match="reference en double"):
        _fusion({"affaires": [_candidat(ref="r://a", rang=1), _candidat(ref="r://a", rang=2)]})


@pytest.mark.parametrize("modifs", [
    {"rang": 0}, {"rang": True}, {"domaine": "developpement"}, {"source": "inconnue"},
    {"reference": ""}, {"reference": " ref "}, {"citation": {}},
    {"citation": {"source": "affaires", "reference": "autre://ref", "sha256": "a" * 64}},
    {"autorite": ""}, {"module": ""}, {"statut": None}, {"fraicheur": ""},
])
def test_refuse_candidat_ambigu_ou_incoherent(modifs):
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": [_candidat(**modifs)]}, poids_sources={"affaires": 1.0})


@pytest.mark.parametrize("kwargs", [
    {"k": 0}, {"k": True}, {"k": 1.5}, {"limite": 0}, {"limite": True},
    {"max_caracteres_extraits": 0}, {"poids_sources": {"affaires": -1.0}},
    {"poids_sources": {"affaires": float("nan")}}, {"poids_sources": {}},
])
def test_refuse_parametres_de_fusion_invalides(kwargs):
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": [_candidat()]}, **kwargs)


def test_refuse_nan_meme_si_une_autre_source_a_un_poids_positif():
    with pytest.raises(routeur.RefusRouteur):
        _fusion(
            {"affaires": [_candidat()], "connaissances": [_candidat("connaissances", "r://k")]},
            poids_sources={"affaires": 1.0, "connaissances": float("nan")},
        )


def test_zero_est_un_poids_valide_si_une_autre_source_est_active():
    resultat = _fusion(
        {"affaires": [_candidat()], "connaissances": [_candidat("connaissances", "r://k")]},
        poids_sources={"affaires": 1.0, "connaissances": 0.0},
    )
    assert [item["reference"] for item in resultat["resultats"]] == ["registre://ligne/1", "r://k"]
    assert resultat["resultats"][1]["score"] == 0.0


def test_refuse_poids_booleen_et_toutes_les_sources_a_zero():
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": [_candidat()]}, poids_sources={"affaires": True})
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": [_candidat()]}, poids_sources={"affaires": 0.0})


def test_refuse_poids_negatif_meme_si_une_autre_source_est_positive():
    with pytest.raises(routeur.RefusRouteur):
        _fusion(
            {"affaires": [_candidat()], "connaissances": [_candidat("connaissances", "r://k")]},
            poids_sources={"affaires": 1.0, "connaissances": -0.5},
        )


def test_refuse_entier_trop_grand_comme_poids_sans_exception_brute():
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": [_candidat()]}, poids_sources={"affaires": 10**400})


def test_refuse_somme_rrf_non_finie():
    sources = {f"voie_{i}": [_candidat(f"voie_{i}", "r://partage")] for i in range(4)}
    with pytest.raises(routeur.RefusRouteur, match="score RRF non fini"):
        _fusion(sources, k=1, poids_sources={source: 1e308 for source in sources})


def test_refuse_contribution_positive_sous_fluxee_au_lieu_de_fausser_le_tri():
    candidats = [_candidat(ref="r://z", rang=1), _candidat(ref="r://a", rang=2)]
    with pytest.raises(routeur.RefusRouteur, match="contribution RRF positive devenue nulle"):
        _fusion({"affaires": candidats}, poids_sources={"affaires": 5e-324})


def test_refuse_domaine_invalide_ou_liste_source_vide():
    with pytest.raises(routeur.RefusRouteur):
        routeur.fusionner(domaine="mixte", listes={}, k=60, poids_sources={}, limite=2,
                          max_caracteres_extraits=100)
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": []}, poids_sources={"affaires": 1.0})
    with pytest.raises(routeur.RefusRouteur):
        routeur.fusionner(domaine="affaires", listes=["affaires"], k=1,
                          poids_sources={"affaires": 1.0}, limite=1, max_caracteres_extraits=10)
    with pytest.raises(routeur.RefusRouteur):
        routeur.fusionner(domaine=[], listes={}, k=1, poids_sources={}, limite=1, max_caracteres_extraits=10)


def test_refuse_source_non_canonique_et_liste_non_sequence():
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"Affaires": [_candidat("Affaires")]}, poids_sources={"Affaires": 1.0})
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": iter([_candidat()])})


def test_refuse_citation_sans_ancre_declaree():
    candidat = _candidat(citation={"source": "affaires", "reference": "registre://ligne/1"})
    with pytest.raises(routeur.RefusRouteur, match="ancre déclarée"):
        _fusion({"affaires": [candidat]})


@pytest.mark.parametrize("citation", [
    None,
    ["citation non mappée"],
    {"source": "affaires", "reference": "registre://ligne/1", "sha256": "a" * 64, 1: "bad-key"},
    {"source": "affaires", "reference": "registre://ligne/1", "sha256": "a" * 64, "": "bad-key"},
    {"source": "affaires", "reference": "registre://ligne/1", "sha256": "a" * 64, "extra": ""},
])
def test_refuse_citation_de_type_ou_de_forme_invalide(citation):
    candidat = _candidat(citation=citation)
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": [candidat]})


@pytest.mark.parametrize("candidat", [None, ["pas", "un", "candidat"]])
def test_refuse_candidat_de_type_invalide(candidat):
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": [candidat]})


def test_refuse_collision_de_reference_avec_contenu_ou_citation_differents():
    divergent = _candidat("connaissances", contenu="Autre résumé")
    with pytest.raises(routeur.RefusRouteur):
        _fusion({"affaires": [_candidat()], "connaissances": [divergent]})


def test_borne_resultats_et_caracteres_et_signale_troncature():
    gros = _candidat(contenu="x" * 50)
    resultat = _fusion({"affaires": [gros, _candidat(ref="r://2", rang=2)]}, limite=1,
                        max_caracteres_extraits=8)
    assert len(resultat["resultats"]) == 1
    assert len(resultat["resultats"][0]["contenu"]) <= 8
    assert resultat["resultats"][0]["tronque"] is True
    assert resultat["tronque"] is True


def test_limite_exacte_nest_pas_signalee_comme_troncature():
    resultat = _fusion({"affaires": [_candidat()]}, limite=1)
    assert len(resultat["resultats"]) == 1
    assert resultat["tronque"] is False


def test_budget_caracteres_est_global_et_najoute_pas_de_resultat_vide():
    candidats = [
        _candidat(ref="r://a", contenu="123456"),
        _candidat(ref="r://b", rang=2, contenu="abcdef"),
    ]
    resultat = _fusion({"affaires": candidats}, limite=2, max_caracteres_extraits=10)
    assert [item["contenu"] for item in resultat["resultats"]] == ["123456", "abcd"]
    assert resultat["caracteres_extraits"] == 10
    assert resultat["tronque"] is True
    resultat_exact = _fusion({"affaires": [_candidat(ref="r://a", contenu="123456"),
                                             _candidat(ref="r://b", rang=2, contenu="abcd")]},
                             limite=2, max_caracteres_extraits=10)
    assert [item["contenu"] for item in resultat_exact["resultats"]] == ["123456", "abcd"]
    assert all(item["contenu"] for item in resultat_exact["resultats"])


def test_budget_exact_avec_resultat_suivant_omet_ce_resultat_et_signale_troncature():
    candidats = [_candidat(ref="r://a", contenu="123456"), _candidat(ref="r://b", rang=2, contenu="abcdef")]
    resultat = _fusion({"affaires": candidats}, limite=2, max_caracteres_extraits=6)
    assert [item["reference"] for item in resultat["resultats"]] == ["r://a"]
    assert resultat["tronque"] is True


def test_budget_restant_dun_caractere_est_utilise():
    candidats = [_candidat(ref="r://a", contenu="123456"), _candidat(ref="r://b", rang=2, contenu="abcdef")]
    resultat = _fusion({"affaires": candidats}, limite=2, max_caracteres_extraits=7)
    assert [item["contenu"] for item in resultat["resultats"]] == ["123456", "a"]


def test_budget_nommee_borne_les_extraits_pas_la_serialisation_totale():
    reference = "registre://" + "x" * 5000
    resultat = _fusion({"affaires": [_candidat(ref=reference)]}, max_caracteres_extraits=1)
    assert resultat["caracteres_extraits"] == 1
    assert resultat["resultats"][0]["contenu"] == "R"
    assert resultat["resultats"][0]["citation"]["reference"] == reference
    assert len(json.dumps(resultat, ensure_ascii=False)) > 15_000


def test_candidat_est_copie_et_resultat_indique_les_limites_dautorisation():
    original = _candidat()
    avant = copy.deepcopy(original)
    resultat = _fusion({"affaires": [original]})
    assert original == avant
    assert resultat["autorisation_verifiee"] is False
    assert resultat["profil_isole"] is False
    assert resultat["avertissement"]
