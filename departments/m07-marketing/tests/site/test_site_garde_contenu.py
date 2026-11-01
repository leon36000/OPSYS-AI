"""Garde-fous de contenu d'un site : le site fictif passe ; chaque refus typé est déclenché, puis levé par sa cause."""

from __future__ import annotations

import pytest
from m7_marketing.brand.profil_client import PLACEHOLDER_NOM
from m7_marketing.site import garde_contenu as G
from m7_marketing.site import service

FICTIF = True


def _codes(schema, **options):
    return [r["code"] for r in G.controler_contenu(schema, **options)]


def _faq(schema, texte_fr, texte_en="Plain answer.", **extra):
    schema["faq"].append({
        "id": "faq-essai", "question": {"fr-CA": "Question d'essai ?", "en-CA": "Test question?"},
        "reponse": {"fr-CA": texte_fr, "en-CA": texte_en}, **extra,
    })


def test_le_site_fictif_passe_tous_les_garde_fous(schema):
    concurrents, refus = service.textes_concurrents(["fort", "faible", "casse"])
    assert refus == []
    assert G.controler_contenu(schema, textes_concurrents=concurrents) == []


@pytest.mark.parametrize("texte", [
    "Nos bureaux sont au 1250 boulevard des Laurentides.",   # adresse
    "Écrivez à jean.client@courriel.example pour un suivi.",  # courriel
    "Appelez Jean au 514 555 0199.",                          # téléphone
    "Merci à la famille Tremblay pour sa confiance.",         # nom de client
    "Chantier WCT-2026-0042 terminé.",                        # identifiant interne
])
def test_donnee_personnelle_dans_un_texte_libre_refusee(schema, texte):
    _faq(schema, texte)
    refus = G.controler_contenu(schema)
    assert [r["code"] for r in refus] == [G.REJ_DONNEE_PERSONNELLE]
    assert refus[0]["chemin"] == f"$.faq[{len(schema['faq']) - 1}].reponse.fr-CA"


def test_donnee_personnelle_jamais_levee_par_une_source(schema):
    _faq(schema, "Merci à la famille Tremblay.", source="src-contrat-type")
    assert _codes(schema) == [G.REJ_DONNEE_PERSONNELLE]


def test_identifiant_interne_fourni_refuse(schema):
    _faq(schema, "Le dossier A7K2-QX9 est fermé.")
    assert _codes(schema) == []
    assert _codes(schema, identifiants_interdits=["A7K2-QX9"]) == [G.REJ_DONNEE_PERSONNELLE]


def test_nom_de_client_reel_connu_refuse_meme_sans_civilite(schema):
    schema["temoignages"][0]["texte"]["fr-CA"] = "Gaétane Bérubé recommande l'équipe."
    assert _codes(schema) == []
    assert _codes(schema, noms_interdits=["Gaétane Bérubé"]) == [G.REJ_DONNEE_PERSONNELLE]


@pytest.mark.parametrize(("fr", "en"), [
    ("Soumission à partir de 4 500 $.", "Plain answer."),
    ("Les travaux durent 3 jours.", "Plain answer."),
    ("Travaux garantis sans conditions.", "Plain answer."),
    ("Nous commençons demain.", "Plain answer."),
    ("Réponse simple.", "Free estimate for every home."),
    ("Réponse simple.", "Work guaranteed for 10 years."),
])
def test_promesse_chiffree_sans_source_refusee(schema, fr, en):
    _faq(schema, fr, en)
    assert _codes(schema) == [G.REJ_PROMESSE_NON_SOURCEE]


def test_promesse_chiffree_avec_source_declaree_acceptee(schema):
    _faq(schema, "La garantie de main-d'œuvre est de 10 ans.", "The workmanship guarantee lasts 10 years.",
         source="src-contrat-type")
    assert _codes(schema) == []


def test_la_faq_garantie_du_site_fictif_est_acceptee_par_sa_source_et_refusee_sans(schema):
    assert schema["faq"][2]["source"] == "src-contrat-type"
    del schema["faq"][2]["source"]
    assert _codes(schema) == [G.REJ_PROMESSE_NON_SOURCEE] * 4  # question et réponse, en français et en anglais


@pytest.mark.parametrize(("fr", "en"), [
    ("Selon la loi, vous avez droit à un recours.", "Plain answer."),
    ("Réponse simple.", "Our terms of use apply."),
])
def test_texte_legal_sans_source_juridique_refuse(schema, fr, en):
    _faq(schema, fr, en)
    assert _codes(schema) == [G.REJ_TEXTE_LEGAL_NON_SOURCE]
    schema["faq"][-1]["source"] = "src-contrat-type"  # une source, mais pas juridique
    assert _codes(schema) == [G.REJ_TEXTE_LEGAL_NON_SOURCE]
    schema["faq"][-1]["source"] = "src-juridique"
    assert _codes(schema) == []


def test_section_legale_exige_une_source_juridique(schema):
    page = next(p for p in schema["pages"] if p["id"] == "confidentialite")
    page["sections"][0]["source"] = "src-rbq"  # registre officiel : pas juridique
    codes = _codes(schema)
    assert set(codes) == {G.REJ_TEXTE_LEGAL_NON_SOURCE}
    assert len(codes) >= 4  # chaque paragraphe, dans chaque langue


@pytest.mark.parametrize(("fr", "en"), [
    ("Le meilleur couvreur de Laval.", "Plain answer."),
    ("Réponse simple.", "The best siding crew in town."),
])
def test_exageration_refusee_meme_avec_source(schema, fr, en):
    _faq(schema, fr, en, source="src-contrat-type")
    assert _codes(schema) == [G.REJ_EXAGERATION]


def test_lien_dans_un_texte_libre_refuse(schema):
    _faq(schema, "Voyez nos réalisations sur www.galerie-fictive.com.")
    assert _codes(schema) == [G.REJ_LIEN_DANS_TEXTE]


@pytest.mark.parametrize(("cle", "valeur"), [("statut", "demande"), ("preuve", " "), ("date", "")])
def test_temoignage_non_consenti_refuse(schema, cle, valeur):
    schema["temoignages"][1]["consentement"][cle] = valeur
    refus = G.controler_contenu(schema)
    assert [r["code"] for r in refus] == [G.REJ_TEMOIGNAGE_NON_CONSENTI]
    assert refus[0]["chemin"] == "$.temoignages[1].consentement"


def test_copie_d_un_concurrent_refusee(schema):
    concurrents, _ = service.textes_concurrents(["fort"])
    extrait = " ".join(concurrents["fort"].split()[10:22])
    schema["services"][0]["description"]["fr-CA"].append(extrait)
    refus = [r for r in G.controler_contenu(schema, textes_concurrents=concurrents)
             if r["code"] == G.REJ_COPIE_CONCURRENT]
    assert len(refus) == 1 and "'fort'" in refus[0]["detail"]
    assert G.controler_contenu(schema, textes_concurrents={}) == [
        r for r in G.controler_contenu(schema) if r["code"] != G.REJ_COPIE_CONCURRENT
    ]


def test_sept_mots_communs_ne_sont_pas_une_copie(schema):
    concurrents = {"essai": "un deux trois quatre cinq six sept huit neuf"}
    schema["services"][0]["description"]["fr-CA"].append("Un deux trois quatre cinq six sept.")
    assert _codes(schema, textes_concurrents=concurrents) == []
    schema["services"][0]["description"]["fr-CA"].append("Un deux trois quatre cinq six sept huit.")
    assert _codes(schema, textes_concurrents=concurrents) == [G.REJ_COPIE_CONCURRENT]


def test_traceur_non_essentiel_refuse_loi_25(schema):
    schema["legal"]["traceurs_non_essentiels"] = True
    assert _codes(schema) == [G.REJ_TRACEUR]


def test_gabarit_de_marque_non_configure_refuse(schema):
    schema["entreprise"]["nom"] = PLACEHOLDER_NOM
    assert G.REJ_MARQUE in _codes(schema)


def test_le_nom_de_marque_ne_declenche_pas_les_regles(schema):
    schema["entreprise"]["nom"] = "Meilleures Gouttières Garanties (fictif)"
    schema["services"][1]["resume"]["fr-CA"] = "Meilleures Gouttières Garanties (fictif) pose des gouttières."
    assert _codes(schema) == []


def test_snapshot_concurrent_illisible_refuse():
    textes, refus = service.textes_concurrents(["../../etc"])
    assert textes == {}
    assert [r["code"] for r in refus] == [service.REJ_CONCURRENT]
