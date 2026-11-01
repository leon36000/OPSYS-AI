"""Conformité d'un texte à publier : pas d'imitation de marque, pas de copie, la publicité comparative est signalée."""

from __future__ import annotations

import pytest
from fabriques_veille import ACCUEIL, declarer_horizon, masqueur
from m7_marketing.veille import conformite, doubles, observations, registre

T = "2026-11-01T12:00:00Z"
PAGE_CONCURRENT = ("Nous posons des gouttières sans joint pour les maisons de Laval avec une garantie de dix ans "
                   "sur la main-d'œuvre et un service de nettoyage chaque automne")


def _concurrents(**options):
    journal = []
    return list(declarer_horizon(journal, **options).values())


def _observations(texte=PAGE_CONCURRENT):
    html = doubles.page_html(titre="Gouttières sans joint à Laval", description=texte, h1=("Gouttières",))
    obs = observations.depuis_page(masqueur(), "horizon", ACCUEIL, "site_officiel", T, 200, html.decode(), html,
                                   ["horizon.example"], None)
    return [obs]


def _codes(resultat):
    return [r["code"] for r in resultat["refus"]]


@pytest.mark.parametrize(
    "texte",
    [
        "Nous sommes meilleurs que Revêtements Horizon",
        "Contrairement à REVETEMENTS HORIZON, nous livrons à temps",
        "Visitez horizon.example pour comparer",
        "Chez www.horizon.example c'est plus cher",
        "Mieux que « Revetements-Horizon » !",
        "revêtements   horizon est un nom connu",
    ],
)
def test_le_nom_ou_le_domaine_d_un_concurrent_est_refuse_quelles_que_soient_casse_accents_et_ponctuation(texte):
    r = conformite.controler_texte_propose(texte, _concurrents(), [])
    assert r["accepte"] is False and _codes(r) == ["REJ-VEILLE-MARQUE-CONCURRENT"]


def test_un_nom_commun_proche_n_est_pas_une_marque():
    r = conformite.controler_texte_propose("Un horizon dégagé pour votre toit ; revêtements neufs", _concurrents(), [])
    assert r["accepte"] is True and r["refus"] == []


def test_les_hotes_additionnels_sont_proteges_aussi():
    from fabriques_veille import AUTRE_HOTE, COMMUNIQUE
    c = _concurrents(sources=[{"url": ACCUEIL, "nature": "site_officiel"}, {"url": COMMUNIQUE, "nature": "communique"}],
                     additionnels=[AUTRE_HOTE])
    assert _codes(conformite.controler_texte_propose(f"Lisez {AUTRE_HOTE} ", c, [])) == ["REJ-VEILLE-MARQUE-CONCURRENT"]


def test_le_nom_d_un_concurrent_retire_reste_protege():
    journal = []
    declarer_horizon(journal)
    registre.retirer(journal, "horizon", "gestion", "x", T)
    r = conformite.controler_texte_propose("Mieux que Revêtements Horizon", list(registre.plier(journal).values()), [])
    assert _codes(r) == ["REJ-VEILLE-MARQUE-CONCURRENT"]


def test_copie_a_vingt_pour_cent_ou_plus_refusee():
    # 21 mots du texte observé repris tels quels dans un texte de 30 mots -> bien au-dessus de 20 %
    repris = ("Nous posons des gouttières sans joint pour les maisons de Laval avec une garantie de dix ans "
              "sur la main-d'œuvre")
    r = conformite.controler_texte_propose(repris + " et un prix honnête pour tous nos clients de la région", [],
        _observations())
    assert r["accepte"] is False and _codes(r) == ["REJ-VEILLE-COPIE"]
    assert float(r["recouvrement"]["horizon"]) >= conformite.SEUIL_COPIE


def test_texte_original_ou_partageant_peu_de_mots_est_accepte():
    r = conformite.controler_texte_propose(
        "Notre équipe installe des gouttières durables et nettoie vos descentes pluviales deux fois par année, "
        "avec photos avant et après pour chaque visite à domicile.", [], _observations())
    assert r["accepte"] is True and r["mentions"] == []
    assert float(r["recouvrement"]["horizon"]) < conformite.SEUIL_COPIE


def test_seuil_exact_a_vingt_pour_cent():
    obs = _observations("un deux trois quatre cinq six sept huit neuf dix")
    # texte de 9 mots -> 5 grammes ; 1 gramme commun = 20 % -> refusé ; zéro commun -> accepté
    commun = conformite.controler_texte_propose("un deux trois quatre cinq alpha bravo charlie delta", [], obs)
    assert float(commun["recouvrement"]["horizon"]) == pytest.approx(0.2) and _codes(commun) == ["REJ-VEILLE-COPIE"]
    aucun = conformite.controler_texte_propose("alpha bravo charlie delta echo foxtrot golf hotel india", [], obs)
    assert aucun["accepte"] is True and float(aucun["recouvrement"]["horizon"]) == 0.0


def test_un_texte_de_moins_de_cinq_mots_n_a_pas_de_recouvrement_mesurable():
    r = conformite.controler_texte_propose("Soumission rapide", [], _observations())
    assert r["accepte"] is True and r["recouvrement"] == {}


@pytest.mark.parametrize(
    "texte",
    ["Nous sommes meilleurs que les autres", "Contrairement à la concurrence, nous restons", "Plus cher que chez "
                                                                                             "nous ? Jamais",
     "Moins chère que le marché", "À la différence des autres", "Comparé à nos voisins, c'est mieux",
     "Better than the rest", "Mieux que partout ailleurs", "Plus lent que prévu pour les autres"],
)
def test_vocabulaire_comparatif_ajoute_la_mention_avocat_sans_refuser(texte):
    r = conformite.controler_texte_propose(texte, [], [])
    assert r["accepte"] is True and r["mentions"] == [conformite.MENTION_COMPARATIVE]
    assert "avocat" in conformite.MENTION_COMPARATIVE and "À valider" in conformite.MENTION_COMPARATIVE


def test_un_texte_neutre_n_a_pas_de_mention():
    assert conformite.controler_texte_propose("Gouttières sans joint à Laval", [], [])["mentions"] == []


def test_marque_et_comparaison_ensemble_refuse_et_mentionne():
    r = conformite.controler_texte_propose("Meilleur que Revêtements Horizon", _concurrents(), [])
    assert r["accepte"] is False and r["mentions"] == [conformite.MENTION_COMPARATIVE]


@pytest.mark.parametrize("texte", ["", "   ", None, 5, "x" * 20_001])
def test_texte_invalide_refuse(texte):
    r = conformite.controler_texte_propose(texte, [], [])
    assert r["accepte"] is False and _codes(r) == ["REJ-VEILLE-ARGUMENT-INVALIDE"]


def test_plusieurs_concurrents_recouvrement_par_concurrent():
    a = _observations("un deux trois quatre cinq six sept huit")
    b = [{**a[0], "concurrent_id": "autre", "titre": "zéro", "description_meta": "alpha bravo charlie delta echo "
                                                                                 "foxtrot",
          "h1": []}]
    r = conformite.controler_texte_propose("un deux trois quatre cinq six sept huit", [], [*a, *b])
    assert set(r["recouvrement"]) == {"horizon", "autre"} and _codes(r) == ["REJ-VEILLE-COPIE"]
    assert float(r["recouvrement"]["autre"]) == 0.0
