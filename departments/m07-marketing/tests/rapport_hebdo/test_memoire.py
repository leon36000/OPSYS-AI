"""Observations d'apprentissage marketing : minimales, déterministes, sans rien de personnel (M7-MEMOIRE)."""

from __future__ import annotations

import json

import jsonschema
from m7_marketing.rapport_hebdo import composition, memoire

from opsys.evenements import schemas

FICTIF = True
LUNDI = "2026-10-26"


def observations(entrees):
    rapport = composition.composer(entrees, LUNDI)
    return rapport, memoire.observations(rapport)


def schema():
    return schemas.charger_schema(memoire.TYPE_EVENEMENT) if hasattr(schemas, "charger_schema") else None


def test_un_rapport_riche_produit_gagnants_faibles_objection_et_avis(entrees):
    rapport, obs = observations(entrees)
    genres = [(o["genre_observation"], o["canal"], o["cle_mesure"]) for o in obs]
    assert genres == [
        ("contenu_gagnant", "facebook", "facebook-aaaa"),
        ("contenu_gagnant", "instagram", "instagram-bbbb"),
        ("contenu_faible", "fiche_google", "fiche_google-cccc"),
        ("contenu_faible", "video_courte", "video_courte-dddd"),
        ("objection_frequente", "avis_clients", "urgence"),
        ("avis_constate", "avis_clients", "semaine"),
    ]
    gagnant = obs[0]
    assert gagnant["resultat"] == {
        "leads": 4,
        "devis_envoyes": 3,
        "devis_acceptes": 2,
        "occurrences": None,
        "avis_positifs": None,
        "avis_negatifs": None,
    }
    assert obs[-1]["resultat"] == {
        "leads": None,
        "devis_envoyes": None,
        "devis_acceptes": None,
        "occurrences": 4,
        "avis_positifs": 2,
        "avis_negatifs": 2,
    }
    assert all(o["rapport_empreinte"] == rapport["empreinte"] and o["semaine"] == LUNDI for o in obs)


def test_les_identifiants_sont_deterministes_et_distincts(entrees):
    _, a = observations(entrees)
    _, b = observations(entrees)
    assert [o["observation_id"] for o in a] == [o["observation_id"] for o in b]
    assert len({o["observation_id"] for o in a}) == len(a)
    assert all(o["observation_id"].startswith("m7-appr-") and len(o["observation_id"]) == 48 for o in a)
    assert memoire.identifiant(LUNDI, "contenu_gagnant", "facebook", "x") != memoire.identifiant(
        "2026-11-02", "contenu_gagnant", "facebook", "x"
    )


def test_rien_de_personnel_ne_sort_ni_texte_ni_coordonnee_ni_identifiant_interne(entrees):
    _, obs = observations(entrees)
    permis = {"observation_id", "semaine", "genre_observation", "canal", "cle_mesure", "resultat", "rapport_empreinte"}
    for o in obs:
        assert set(o) == permis
        texte = json.dumps(o).replace("avis_clients", "")  # le canal est une valeur fermée du catalogue
        assert "@" not in texte and "wct" not in texte and "lead_" not in texte and "client" not in texte


def test_chaque_observation_est_conforme_au_schema_du_catalogue(entrees):
    _, obs = observations(entrees)
    chemin = __import__("pathlib").Path(schemas.__file__).parent / "catalogue" / f"{memoire.TYPE_EVENEMENT}.json"
    sch = json.loads(chemin.read_text(encoding="utf-8"))
    for o in obs:
        jsonschema.validate(o, sch)


def test_sans_donnee_aucune_observation_n_est_inventee():
    _, obs = observations({})
    assert obs == []


def test_une_objection_exige_au_moins_deux_avis_de_la_meme_categorie(entrees):
    entrees["reputation"]["categories"] = {"eloge": 3, "urgence": 1, "litige": 0, "neutre": 0}
    entrees["reputation"]["avis_semaine"] = 4
    _, obs = observations(entrees)
    assert not [o for o in obs if o["genre_observation"] == "objection_frequente"]
    entrees["reputation"]["categories"] = {"eloge": 0, "urgence": 0, "litige": 2, "neutre": 2}
    _, obs = observations(entrees)
    (objection,) = [o for o in obs if o["genre_observation"] == "objection_frequente"]
    assert objection["cle_mesure"] == "litige" and objection["resultat"]["occurrences"] == 2


def test_pas_d_avis_pas_d_observation_d_avis(entrees):
    entrees["reputation"] = {
        "avis_semaine": 0,
        "note_moyenne_semaine": None,
        "categories": {},
        "sans_reponse": 0,
        "negatifs_sans_reponse": 0,
    }
    _, obs = observations(entrees)
    assert not [o for o in obs if o["canal"] == "avis_clients"]


def test_un_contenu_sans_cle_valide_ou_au_canal_inconnu_est_ecarte(entrees, fab):
    entrees["m8_contenus"][0]["utm_content"] = "Clé Invalide!"
    entrees["m8_contenus"][1]["canal"] = "tiktok"
    _, obs = observations(entrees)
    cles = [o["cle_mesure"] for o in obs if o["genre_observation"] in ("contenu_gagnant", "contenu_faible")]
    assert "Clé Invalide!" not in cles and "instagram-bbbb" not in cles and "fiche_google-cccc" in cles


def test_les_comptes_inconnus_restent_null_jamais_zero(entrees):
    entrees["m8_contenus"][0]["devis_envoyes"] = None
    entrees["m8_contenus"][0]["devis_acceptes"] = -3
    _, obs = observations(entrees)
    assert obs[0]["resultat"]["devis_envoyes"] is None and obs[0]["resultat"]["devis_acceptes"] is None
