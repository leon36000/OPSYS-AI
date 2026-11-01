"""Schéma de contenu opsys.site/v1 : structure valide du site fictif, et un refus typé pour chaque règle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m7_marketing.aeo.aeo_engine import TYPES_LOCALBUSINESS
from m7_marketing.site import schema_site as S

FICTIF = True
_CONTRAT = Path(__file__).resolve().parents[2] / "contracts" / "site-contenu.v1.schema.json"


def _codes(schema):
    return [r["code"] for r in S.valider_schema(schema)]


def test_le_site_fictif_complet_est_structurellement_valide(schema):
    assert S.valider_schema(schema) == []
    assert schema["fictif"] is True
    assert schema["langues"] == ["fr-CA", "en-CA"]
    types = {s["type"] for p in schema["pages"] for s in p["sections"]}
    assert types == set(S.TYPES_SECTION) - {"texte"}  # « texte » : couvert par les tests de contenu


def test_un_refus_dit_le_code_le_chemin_et_quoi_corriger(schema):
    del schema["entreprise"]["nap"]["telephone"]
    [refus] = S.valider_schema(schema)
    assert refus == {
        "code": S.REJ_SCHEMA_CHAMP, "chemin": "$.entreprise.nap.telephone", "detail": "champ requis absent",
    }


def test_version_de_schema_inconnue_refusee(schema):
    schema["schema"] = "opsys.site/v2"
    assert _codes(schema) == [S.REJ_SCHEMA_VERSION]
    assert _codes([]) == [S.REJ_SCHEMA_CHAMP]


def test_champ_inconnu_refuse(schema):
    schema["theme_astro"] = "minimal"
    schema["pages"][0]["sections"][0]["classe_css"] = "hero-xl"
    assert _codes(schema) == [S.REJ_SCHEMA_CHAMP_INCONNU, S.REJ_SCHEMA_CHAMP_INCONNU]


@pytest.mark.parametrize("langues", [["en-CA", "fr-CA"], ["fr-CA", "fr-CA"], ["fr-CA", "es-MX"], [], "fr-CA"])
def test_le_francais_vient_d_abord_et_seules_fr_ca_en_ca_sont_permises(schema, langues):
    schema["langues"] = langues
    assert _codes(schema) == [S.REJ_SCHEMA_LANGUE]


def _sans_anglais(noeud):
    if isinstance(noeud, dict):
        return {k: _sans_anglais(v) for k, v in noeud.items() if k != "en-CA"}
    if isinstance(noeud, list):
        return [_sans_anglais(v) for v in noeud]
    return noeud


def test_site_en_francais_seulement_accepte(schema):
    francais = _sans_anglais(schema)
    francais["langues"] = ["fr-CA"]
    assert S.valider_schema(francais) == []


def test_texte_dans_une_langue_non_declaree_refuse(schema):
    francais = _sans_anglais(schema)
    francais["langues"] = ["fr-CA"]
    francais["faq"][0]["question"]["en-CA"] = "Which cities do you serve?"
    assert _codes(francais) == [S.REJ_SCHEMA_LANGUE]


def test_traduction_manquante_refusee(schema):
    del schema["services"][0]["nom"]["en-CA"]
    assert _codes(schema) == [S.REJ_SCHEMA_TRADUCTION]


def test_francais_nettement_predominant(schema):
    schema["services"][0]["description"]["en-CA"].append("More English text. " * 200)
    schema["services"][0]["description"]["en-CA"][-1] = schema["services"][0]["description"]["en-CA"][-1][:1900]
    assert _codes(schema) == [S.REJ_FRANCAIS]


def test_type_de_section_inconnu_refuse(schema):
    schema["pages"][0]["sections"].append({"type": "carrousel"})
    assert _codes(schema) == [S.REJ_SCHEMA_SECTION]


@pytest.mark.parametrize(("chemin", "valeur"), [
    (("cta", 0, "cible", "page"), "page-absente"),
    (("temoignages", 0, "zone"), "montreal"),
    (("services", 0, "image"), "img-absente"),
    (("faq", 2, "source"), "src-absente"),
])
def test_reference_pendante_refusee(schema, chemin, valeur):
    noeud = schema
    for cle in chemin[:-1]:
        noeud = noeud[cle]
    noeud[chemin[-1]] = valeur
    assert _codes(schema) == [S.REJ_SCHEMA_REFERENCE]


def test_identifiant_en_double_ou_invalide_refuse(schema):
    schema["zones"].append({"id": "laval", "nom": "Laval-Ouest"})
    schema["faq"][0]["id"] = "FAQ Villes"
    assert _codes(schema) == [S.REJ_SCHEMA_IDENTIFIANT, S.REJ_SCHEMA_IDENTIFIANT]


def test_slug_invalide_ou_url_en_double_refuses(schema):
    schema["pages"][1]["slug"]["fr-CA"] = "Services Été"
    assert _codes(schema) == [S.REJ_SCHEMA_SLUG]
    schema["pages"][1]["slug"]["fr-CA"] = "contact"
    assert S.REJ_SCHEMA_SLUG in _codes(schema)


@pytest.mark.parametrize(("cle", "valeur"), [
    ("telephone", "450-555-0142"),
    ("courriel", "bonjour@autre-domaine.example"),
])
def test_nap_mal_formee_refusee(schema, cle, valeur):
    schema["entreprise"]["nap"][cle] = valeur
    assert _codes(schema) == [S.REJ_SCHEMA_NAP]


def test_code_postal_et_region_hors_quebec_refuses(schema):
    schema["entreprise"]["nap"]["adresse"]["code_postal"] = "90210"
    schema["entreprise"]["nap"]["adresse"]["region"] = "ON"
    assert _codes(schema) == [S.REJ_SCHEMA_NAP, S.REJ_SCHEMA_NAP]


def test_couleur_non_hexadecimale_refusee(schema):
    schema["charte"]["primaire"] = "navy"
    assert _codes(schema) == [S.REJ_SCHEMA_COULEUR]


def test_contraste_de_la_charte_calcule_et_refuse_sous_aa(schema):
    schema["charte"]["texte"] = "#9a9a9a"  # 2,8:1 sur blanc
    schema["charte"]["focus"] = "#ffd8a8"  # pâle : invisible sur blanc
    refus = S.valider_schema(schema)
    assert [r["code"] for r in refus] == [S.REJ_CONTRASTE, S.REJ_CONTRASTE]
    assert refus[0]["chemin"] == "$.charte.texte/fond"
    assert "4.5:1" in refus[0]["detail"]


def test_contrastes_charte_calcule_les_ratios_wcag(schema):
    paires = {p["paire"]: p for p in S.contrastes_charte(schema["charte"])}
    assert paires["texte/fond"]["ratio"] == pytest.approx(15.89, abs=0.01)
    assert paires["focus/primaire"]["seuil_aa"] == 3.0
    assert all(p["conforme_aa"] for p in paires.values())


@pytest.mark.parametrize(("cle", "valeur"), [("largeur", 0), ("hauteur", "600"), ("fichier", "../secret.svg")])
def test_image_sans_dimensions_ou_hors_dossier_images_refusee(schema, cle, valeur):
    schema["images"][0][cle] = valeur
    assert _codes(schema) == [S.REJ_SCHEMA_IMAGE]


def test_image_sans_texte_de_remplacement_refusee(schema):
    del schema["images"][1]["alt"]
    assert S.REJ_SCHEMA_IMAGE in _codes(schema)


def test_accueil_et_sections_legales_obligatoires(schema):
    schema["pages"] = [p for p in schema["pages"] if p["id"] not in ("accueil", "confidentialite")]
    schema["cta"] = [c for c in schema["cta"] if c["cible"] != {"page": "accueil"}]
    codes = _codes(schema)
    assert codes.count(S.REJ_SCHEMA_PAGES) == 2


def test_initiales_seulement_jamais_le_nom_complet_d_un_client(schema):
    schema["temoignages"][0]["initiales"] = "Marie Tremblay"
    refus = S.valider_schema(schema)
    assert [r["code"] for r in refus] == [S.REJ_SCHEMA_CHAMP]
    assert "jamais un nom complet" in refus[0]["detail"]


def test_site_fictif_jamais_sur_un_domaine_reel(schema):
    schema["domaine"] = "revetements-horizon.ca"
    schema["entreprise"]["nap"]["courriel"] = "bonjour@revetements-horizon.ca"
    schema["legal"]["responsable_rp"]["courriel"] = "confidentialite@revetements-horizon.ca"
    assert _codes(schema) == [S.REJ_FICTIF_DOMAINE]


def test_description_trop_courte_pour_le_seo_refusee(schema):
    schema["pages"][0]["description"]["fr-CA"] = "Trop court."
    assert _codes(schema) == [S.REJ_SCHEMA_CHAMP]


def test_chemin_page_url_propres_francais_a_la_racine():
    langues = ("fr-CA", "en-CA")
    assert S.chemin_page("", "fr-CA", langues) == "/"
    assert S.chemin_page("", "en-CA", langues) == "/en/"
    assert S.chemin_page("services/gouttieres", "fr-CA", langues) == "/services/gouttieres/"
    assert S.chemin_page("services/gutters", "en-CA", langues) == "/en/services/gutters/"


def test_le_contrat_json_schema_publie_suit_les_constantes_du_validateur():
    contrat = json.loads(_CONTRAT.read_text(encoding="utf-8"))
    proprietes = contrat["properties"]
    assert proprietes["schema"]["const"] == S.SCHEMA_VERSION
    assert set(contrat["required"]) == set(S.CHAMPS_RACINE)
    assert proprietes["langues"]["items"]["enum"] == list(S.LANGUES_PERMISES)
    assert proprietes["langues"]["prefixItems"][0]["const"] == S.LANGUE_DEFAUT
    sections = proprietes["pages"]["items"]["properties"]["sections"]["items"]["oneOf"]
    types = [v["properties"]["type"]["const"] for v in sections]
    assert types == list(S.TYPES_SECTION)
    assert proprietes["sources"]["items"]["properties"]["nature"]["enum"] == list(S.NATURES_SOURCE)
    assert proprietes["entreprise"]["properties"]["type_schema"]["enum"] == sorted(TYPES_LOCALBUSINESS)
    assert set(proprietes["charte"]["required"]) == set(S.COULEURS_CHARTE)
