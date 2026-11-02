"""Recommandations : règles lisibles, chacune liée à une donnée ou marquée hypothèse, priorisées, sans tactique
interdite."""

from __future__ import annotations

import copy

import pytest
from m7_marketing.rapport_hebdo import composition, croissance, recommandations

FICTIF = True
LUNDI = "2026-10-26"


def ids(rapport):
    return [r["id"] for r in rapport["recommandations"]]


def composer(entrees):
    return composition.composer(entrees, LUNDI)


def test_chaque_recommandation_est_liee_a_une_donnee_existante_ou_marquee_hypothese(entrees):
    r = composer(entrees)
    assert r["recommandations"] and recommandations.verifier_liaison(r) == []
    for rec in r["recommandations"]:
        assert rec["sources"] or rec["hypothese"], rec["id"]
        for s in rec["sources"]:
            assert s["ref"] in r["references"][s["type"]]


def test_les_recommandations_attendues_naissent_des_donnees(entrees):
    r = composer(entrees)
    attendues = {
        "avis_negatifs_sans_reponse",
        "contenus_sans_lien_de_suivi",
        "contenu_gagnant:facebook-aaaa",
        "contenu_gagnant:instagram-bbbb",
        "calendrier_vide",
        "contenus_en_attente",
        "contenu_faible:fiche_google-cccc",
        "leads_sans_canal",
        "croissance_en_baisse:instagram:abonnes",
        "action_organique:facebook:format:reel",
    }
    assert attendues <= set(ids(r)), set(ids(r))
    faible = next(x for x in r["recommandations"] if x["id"] == "contenu_faible:fiche_google-cccc")
    assert faible["hypothese"] is True  # la cause d'un contenu sans lead est inconnue
    baisse = next(x for x in r["recommandations"] if x["id"].startswith("croissance_en_baisse"))
    assert baisse["hypothese"] is True and len(baisse["sources"]) == 2


def test_la_priorite_est_impact_fois_facilite_et_l_ordre_est_deterministe(entrees):
    r = composer(entrees)
    for rec in r["recommandations"]:
        assert rec["priorite"] == rec["impact"] * rec["facilite"] and 1 <= rec["priorite"] <= 25
    ordre = [(-x["priorite"], x["regle"], x["id"]) for x in r["recommandations"]]
    assert ordre == sorted(ordre)
    assert r["recommandations"][0]["regle"] in ("avis_negatifs_sans_reponse", "contenus_sans_lien_de_suivi")
    entrees["m8_contenus"].reverse()
    assert ids(composer(entrees)) == ids(r)


def test_au_plus_cinq_taches_et_ce_sont_les_mieux_classees(entrees):
    recs = composer(entrees)["recommandations"]
    taches = [r for r in recs if r["tache"]]
    assert 1 <= len(taches) <= recommandations.TACHES_MAX
    assert taches == [r for r in recs if r["tache"]][: len(taches)]
    premiers = recs[: len(taches)]
    assert all(r["tache"] or r["regle"] == "mesures_m8_perimees" for r in premiers)


def test_au_plus_douze_recommandations(entrees):
    assert len(composer(entrees)["recommandations"]) <= recommandations.RECOMMANDATIONS_MAX


def test_une_recommandation_sans_source_et_sans_hypothese_est_refusee_a_la_construction():
    with pytest.raises(ValueError, match="sans source"):
        recommandations._rec("x", "", "Faire quelque chose", 3, 3, [])  # noqa: SLF001
    assert recommandations._rec("x", "", "Faire quelque chose", 3, 3, [], hypothese=True)["hypothese"]  # noqa: SLF001


def test_impact_et_facilite_sont_bornes():
    for impact, facilite in ((0, 3), (3, 6), (6, 1)):
        with pytest.raises(ValueError):
            recommandations._rec("x", "", "ok", impact, facilite, [], hypothese=True)  # noqa: SLF001


def test_verifier_liaison_voit_une_source_absente_des_references(entrees):
    r = composer(entrees)
    r["recommandations"][0]["sources"] = [{"type": "contenu_m8", "ref": "inconnu-9999", "valeur": None}]
    assert any("absente des références" in p for p in recommandations.verifier_liaison(r))
    r["recommandations"][0]["sources"] = []
    r["recommandations"][0]["hypothese"] = False
    assert any("ni source ni hypothèse" in p for p in recommandations.verifier_liaison(r))
    r["recommandations"][0]["hypothese"] = True
    r["recommandations"][0]["sources"] = [{"type": "invente", "ref": "x", "valeur": None}]
    assert any("type de source inconnu" in p for p in recommandations.verifier_liaison(r))


def test_aucune_recommandation_ne_propose_une_tactique_interdite(entrees):
    for e in (entrees, {}):
        for rec in composer(e)["recommandations"]:
            assert croissance.verifier_legitimite(rec["action"])


def test_une_tactique_interdite_est_refusee_dans_une_recommandation():
    with pytest.raises(ValueError, match="non légitime"):
        recommandations._rec("x", "", "Pour grandir, acheter des abonnés", 3, 3, [], hypothese=True)  # noqa: SLF001


def test_sans_aucune_donnee_le_rapport_ne_recommande_que_de_la_collecte_en_hypothese():
    r = composer({})
    assert all(rec["hypothese"] for rec in r["recommandations"] if not rec["sources"])
    assert "entrepot_m8_absent" in ids(r) and "donnees_croissance_manquantes" not in ids(r)  # pas d'observation du tout


def test_les_mesures_perimees_de_m8_sont_une_recommandation_sourcee_non_tache(entrees, fab):
    seules = {"m8_mesures": [fab.mesure("m8_visites_site", "10", fraicheur="perime", unite="visites")]}
    rec = next(x for x in composer(seules)["recommandations"] if x["regle"] == "mesures_m8_perimees")
    assert (
        rec["sources"] == [{"type": "mesure_m8", "ref": "m8_visites_site", "valeur": "perime"}]
        and rec["tache"] is False
    )


def test_cout_par_lead_non_calculable_devient_une_recommandation_liee_a_la_mesure(entrees, fab):
    entrees["m8_mesures"] = [
        fab.mesure("m8_cout_par_lead_pub_cad", None, statut="non_calculable", fraicheur="manquant")
    ]
    rec = next(x for x in composer(entrees)["recommandations"] if x["regle"] == "cout_par_lead_non_calculable")
    assert rec["sources"][0]["ref"] == "m8_cout_par_lead_pub_cad" and rec["hypothese"] is False


def test_les_avis_sans_reponse_positifs_ne_remplacent_pas_les_negatifs(entrees):
    entrees["reputation"]["negatifs_sans_reponse"] = 0
    regles = {x["regle"] for x in composer(entrees)["recommandations"]}
    assert "avis_sans_reponse" in regles and "avis_negatifs_sans_reponse" not in regles
    entrees["reputation"]["sans_reponse"] = 0
    regles = {x["regle"] for x in composer(entrees)["recommandations"]}
    assert not regles & {"avis_sans_reponse", "avis_negatifs_sans_reponse"}


def test_la_baisse_de_croissance_a_un_seuil(entrees, fab):
    entrees["croissance"] = entrees["croissance"][-2:]  # la seule série d'abonnés d'Instagram
    entrees["croissance"][-1] = fab.observation(
        "obs-ig-abonnes-2", "instagram", "croissance", 95, fin="2026-10-25", metrique="abonnes", unite="abonnés"
    )  # -21 % : signalé
    assert any(x["regle"] == "croissance_en_baisse" for x in composer(entrees)["recommandations"])
    entrees["croissance"][-1] = fab.observation(
        "obs-ig-abonnes-2", "instagram", "croissance", 115, fin="2026-10-25", metrique="abonnes", unite="abonnés"
    )  # -4 % : bruit
    assert not any(x["regle"] == "croissance_en_baisse" for x in composer(entrees)["recommandations"])


def test_le_calendrier_vide_n_est_dit_que_sans_creneau_ni_export(entrees):
    entrees["calendrier"]["exportes_semaine"] = 1
    assert "calendrier_vide" not in ids(composer(entrees))
    entrees["calendrier"]["exportes_semaine"] = 0
    entrees["calendrier"]["creneaux_semaine"] = 2
    assert "calendrier_vide" not in ids(composer(entrees))


def test_les_entrees_ne_sont_pas_modifiees(entrees):
    avant = copy.deepcopy(entrees)
    composer(entrees)
    assert entrees == avant
