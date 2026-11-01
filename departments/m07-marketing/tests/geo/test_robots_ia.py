"""Robots d'IA et robots.txt : liste fermée, politique obligatoire, constats exacts. Aucune donnée réelle."""

from __future__ import annotations

import pytest
from m7_marketing.geo import robots_ia
from m7_marketing.geo.robots_ia import ErreurGeo, analyser_robots_ia

TOUT_AUTORISER = {"recherche": "autoriser", "recuperation_a_la_demande": "autoriser", "entrainement": "autoriser"}
TOUT_BLOQUER = {c: "bloquer" for c in robots_ia.CATEGORIES}
ATTENDUS = {
    "OAI-SearchBot": "recherche", "ChatGPT-User": "recuperation_a_la_demande", "GPTBot": "entrainement",
    "PerplexityBot": "recherche", "Perplexity-User": "recuperation_a_la_demande", "ClaudeBot": "entrainement",
    "Claude-User": "recuperation_a_la_demande", "Claude-SearchBot": "recherche", "Google-Extended": "entrainement",
    "Applebot-Extended": "entrainement", "CCBot": "entrainement", "Bingbot": "recherche",
}


def _ligne(resultat, robot):
    return next(r for r in resultat["robots"] if r["robot"] == robot)


def test_la_liste_est_fermee_et_chaque_robot_a_sa_categorie_et_sa_source():
    assert {r.nom: r.categorie for r in robots_ia.ROBOTS_IA} == ATTENDUS
    assert len(robots_ia.ROBOTS_IA) == 12 and all(r.a_verifier for r in robots_ia.ROBOTS_IA)
    assert all(r.niveau_preuve in ("S", "H") for r in robots_ia.ROBOTS_IA)
    assert "R4 §4.2" in robots_ia.SOURCE_LISTE


@pytest.mark.parametrize("robot,categorie", sorted(ATTENDUS.items()))
def test_chaque_robot_bloque_nommement_est_detecte_dans_sa_categorie(robot, categorie):
    texte = f"User-agent: {robot}\nDisallow: /\n"
    r = analyser_robots_ia(texte, 200, TOUT_AUTORISER)
    ligne = _ligne(r, robot)
    assert ligne["categorie"] == categorie and ligne["autorise"] is False and ligne["conforme"] is False
    assert ligne["constat"] == "GEO-ROBOT-BLOQUE-CONTRE-POLITIQUE"
    # les onze autres robots, non nommés et sans groupe `*`, restent autorisés et conformes
    assert all(x["autorise"] and x["conforme"] for x in r["robots"] if x["robot"] != robot)
    assert r["lignes_recommandees"] == [f"User-agent: {robot}\nAllow: /"]


@pytest.mark.parametrize("categorie", robots_ia.CATEGORIES)
def test_la_politique_de_chaque_categorie_decide_seule(categorie):
    politique = {**TOUT_AUTORISER, categorie: "bloquer"}
    r = analyser_robots_ia("", 200, politique)  # fichier vide : tout est autorisé
    en_defaut = {x["robot"] for x in r["robots"] if not x["conforme"]}
    assert en_defaut == {n for n, c in ATTENDUS.items() if c == categorie}
    assert {c["code"] for c in r["constats"]} == {"GEO-ROBOT-AUTORISE-CONTRE-POLITIQUE"}
    assert all(ligne.endswith("Disallow: /") for ligne in r["lignes_recommandees"])


def test_tout_conforme_ne_recommande_rien():
    texte = "User-agent: *\nDisallow: /\n\nUser-agent: OAI-SearchBot\nAllow: /\n"
    politique = {"recherche": "bloquer", "recuperation_a_la_demande": "bloquer", "entrainement": "bloquer"}
    r = analyser_robots_ia(texte, 200, politique)
    assert _ligne(r, "OAI-SearchBot")["autorise"] is True and _ligne(r, "OAI-SearchBot")["conforme"] is False
    assert r["conformes"] == 11 and r["total"] == 12
    assert analyser_robots_ia(texte, 200, TOUT_BLOQUER)["lignes_recommandees"] == ["User-agent: "
                                                                                   "OAI-SearchBot\nDisallow: /"]


def test_politique_absente_ou_incomplete_est_un_refus_type_sans_valeur_par_defaut():
    for politique in (None, {}, {"recherche": "autoriser"}, {**TOUT_AUTORISER, "autre": "autoriser"}):
        with pytest.raises(ErreurGeo) as exc:
            analyser_robots_ia("", 200, politique)
        assert exc.value.code == "REJ-GEO-POLITIQUE-ABSENTE"
    with pytest.raises(ErreurGeo) as exc:
        analyser_robots_ia("", 200, {**TOUT_AUTORISER, "recherche": "peut-etre"})
    assert exc.value.code == "REJ-GEO-POLITIQUE-INVALIDE"


def test_robots_inaccessible_interdit_tout_et_ne_recommande_aucune_ligne():
    r = analyser_robots_ia(None, 503, TOUT_AUTORISER)
    assert r["etat_robots"] == "inaccessible" and not any(x["autorise"] for x in r["robots"])
    assert r["constats"][0]["code"] == "GEO-ROBOTS-INACCESSIBLE"
    assert r["lignes_recommandees"] == []


def test_robots_absent_autorise_tout_et_le_dit():
    r = analyser_robots_ia(None, 404, TOUT_AUTORISER)
    assert r["etat_robots"] == "absent" and all(x["autorise"] for x in r["robots"])
    assert r["constats"][0]["code"] == "GEO-ROBOTS-ABSENT"


def test_un_groupe_etoile_bloque_tout_sauf_les_robots_nommes():
    texte = "User-agent: *\nDisallow: /\n\nUser-agent: Claude-SearchBot\nUser-agent: PerplexityBot\nAllow: /\n"
    r = analyser_robots_ia(texte, 200, TOUT_AUTORISER)
    autorises = {x["robot"] for x in r["robots"] if x["autorise"]}
    assert autorises == {"Claude-SearchBot", "PerplexityBot"}


def test_les_avertissements_disent_rien_n_est_promis_et_llms_txt():
    r = analyser_robots_ia("", 200, TOUT_AUTORISER)
    texte = " ".join(r["avertissements"])
    assert "Aucune visibilité n'est promise" in texte and "llms.txt" in texte and "revérifier" in texte
    assert r["application"].startswith("RECOMMANDATION seulement")
    assert "Bingbot" in texte  # bloquer Bingbot retire aussi le site de Bing


def test_le_bloc_recommande_n_est_pas_ecrit_ailleurs_que_dans_la_reponse():
    texte = "User-agent: GPTBot\nDisallow: /\n"
    avant = texte
    analyser_robots_ia(texte, 200, TOUT_AUTORISER)
    assert texte == avant
