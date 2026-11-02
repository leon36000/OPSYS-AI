"""Exclusions, hypothèses, délai et validité de la soumission, tirés de données DÉCLARÉES (M3-C2).

Pur, horloge injectée : la validité part de la date DU DEVIS, jamais de l'heure courante. Données fictives.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from html import unescape
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
from m3_estimation import conditions_soumission, soumission, soumission_pdf  # noqa: E402

HORODATAGE_DEVIS = "2026-11-03T14:30:00-05:00"


def _contexte(*, soumission_declaree=None, **mesure):
    journal_b, journal_m = [], []
    declare = cb.SOUMISSION if soumission_declaree is None else soumission_declaree
    version = cb.declarer_ok(journal_b, soumission=deepcopy(declare))
    return version, cb.mesurer_ok(journal_m, **mesure)


def _composer(duree="3000.00", horodatage=HORODATAGE_DEVIS, **kwargs):
    version, mesure = _contexte(**kwargs)
    return conditions_soumission.composer(
        version_bareme=version, mesure=mesure, duree_estimee_minutes=duree, horodatage_devis=horodatage)


def _devis(conditions=None):
    devis = {
        "devis_id": "M3-DEVIS-cond-001", "lead_id": cb.LEAD, "statut": "brouillon", "horodatage": HORODATAGE_DEVIS,
        "prix_total": "1200.00",
        "lignes": [{"reference_ligne": "L1", "description": "Revêtement", "quantite": "100", "unite": "pi2",
                    "prix_unitaire": "12.00", "prix_ligne": "1200.00", "cout_unitaire": "9.00",
                    "cout_ligne": "900.00"}],
        "cout_total": "900.00", "taux_marge": "0.25",
    }
    if conditions is not None:
        devis["conditions_soumission"] = conditions
    return devis


# ------------------------------------------------------------------------------------------------ composition
def test_les_quatre_sections_viennent_des_donnees_declarees():
    conditions, verdict = _composer()
    assert verdict is None
    assert conditions["exclusions"] == cb.SOUMISSION["exclusions"]
    assert conditions["hypotheses"][0] == cb.SOUMISSION["hypotheses"][0]
    assert conditions["hypotheses"][1] == (
        "Quantité retenue : 1200 pi2 (surface de revêtement), établie par un relevé sur place le 2 novembre 2026.")
    assert len(conditions["hypotheses"]) == 2  # mesure ponctuelle : aucune phrase de plage
    assert conditions["delai"]["duree_main_oeuvre_heures"] == "50"          # 3000 min = 50 h
    assert "environ 50 heures de main-d'œuvre" in conditions["delai"]["texte"]
    assert conditions["validite"] == {
        "jours": 30, "jusqu_au": "2026-12-03", "texte": "Cette soumission est valide jusqu'au 3 décembre 2026."}


def test_une_mesure_a_bornes_ajoute_la_plage_aux_hypotheses():
    conditions, _ = _composer(valeur="120.5", borne_basse="118", borne_haute="125.25", methode="plan")
    assert conditions["hypotheses"][1].startswith("Quantité retenue : 120,5 pi2")
    assert "établie par un plan le 2 novembre 2026" in conditions["hypotheses"][1]
    assert conditions["hypotheses"][2] == (
        "La quantité est une plage de 118 à 125,25 pi2 ; la valeur retenue est 120,5 pi2.")


def test_le_delai_est_une_duree_et_jamais_une_date_ni_une_promesse():
    conditions, _ = _composer(duree="95.00")
    assert conditions["delai"]["duree_main_oeuvre_heures"] == "1,6"        # 95 min = 1,58 h arrondi au dixième
    texte = conditions["delai"]["texte"]
    assert "Aucune date de début ni de fin n'est promise" in texte
    assert not any(mot in texte.lower() for mot in ("garanti", "livraison", "terminé le", "débutera"))
    assert conditions["delai"]["duree_main_oeuvre_heures"] != "1,5"   # arrondi à la moitié supérieure (HALF_UP)


def test_les_heures_s_arrondissent_au_dixieme_superieur_a_la_moitie_pile():
    assert _composer(duree="87")[0]["delai"]["duree_main_oeuvre_heures"] == "1,5"    # 1,45 h : ROUND_HALF_UP
    assert _composer(duree="93")[0]["delai"]["duree_main_oeuvre_heures"] == "1,6"    # 1,55 h
    assert _composer(duree="60")[0]["delai"]["duree_main_oeuvre_heures"] == "1"      # 1,0 h : zéro inutile retiré


def test_sans_duree_declaree_il_n_y_a_pas_de_delai_et_sans_validite_pas_de_validite():
    conditions, _ = _composer(duree=None, soumission_declaree={"exclusions": ["Texte fictif."]})
    assert conditions["delai"] is None and conditions["validite"] is None
    assert conditions["exclusions"] == ["Texte fictif."]
    assert len(conditions["hypotheses"]) == 1  # seulement la quantité retenue : aucune hypothèse inventée


def test_sans_exclusion_declaree_la_section_est_vide_et_rien_n_est_invente():
    conditions, _ = _composer(soumission_declaree={})
    assert conditions["exclusions"] == []
    texte_total = " ".join(conditions["hypotheses"]).lower()
    assert "garantie" not in texte_total and "garantit" not in texte_total


def test_aucune_garantie_n_est_ecrite_par_le_code_seulement_celles_que_l_entreprise_declare():
    conditions, _ = _composer()
    tout = " ".join([*conditions["exclusions"], *conditions["hypotheses"], conditions["delai"]["texte"],
                     conditions["validite"]["texte"]]).lower()
    assert "garantie" not in tout and "garanti" not in tout
    declaree, _ = _composer(
        soumission_declaree={"hypotheses": ["Garantie du fabricant : 25 ans (texte fictif déclaré)."]})
    assert "Garantie du fabricant" in declaree["hypotheses"][0]


def test_la_validite_part_de_la_date_du_devis_et_traverse_les_fins_de_mois_et_d_annee():
    conditions, _ = _composer(horodatage="2026-12-15T23:59:00-05:00")
    assert conditions["validite"]["jusqu_au"] == "2027-01-14"
    assert conditions["validite"]["texte"] == "Cette soumission est valide jusqu'au 14 janvier 2027."
    conditions, _ = _composer(horodatage="2028-02-01T10:00:00+00:00")
    assert conditions["validite"]["jusqu_au"] == "2028-03-02"       # 2028 est bissextile


def test_les_composants_incoherents_donnent_un_verdict_nomme():
    version, mesure = _contexte()
    for kwargs in ({"horodatage_devis": "pas une date"}, {"duree_estimee_minutes": "abc"}):
        arguments = {"version_bareme": version, "mesure": mesure, "duree_estimee_minutes": "10",
                     "horodatage_devis": HORODATAGE_DEVIS, **kwargs}
        conditions, verdict = conditions_soumission.composer(**arguments)
        assert conditions is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"
    mauvais = {**mesure, "methode": "devinette"}
    _, verdict = conditions_soumission.composer(
        version_bareme=version, mesure=mauvais, duree_estimee_minutes="10", horodatage_devis=HORODATAGE_DEVIS)
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


@pytest.mark.parametrize("modification", [
    lambda c: c.pop("delai"), lambda c: c.update(extra=1), lambda c: c.update(version="autre"),
    lambda c: c.update(exclusions="texte"), lambda c: c["exclusions"].append(""), lambda c: c["hypotheses"].append(5),
    lambda c: c.update(delai={"texte": "x"}),
    lambda c: c.update(validite={"jours": "30", "jusqu_au": "x", "texte": "x"}),
    lambda c: c["exclusions"].extend(["x"] * 41), lambda c: c["hypotheses"].append("é" * 601),
])
def test_la_forme_des_sections_est_fermee(modification):
    conditions, _ = _composer()
    modification(conditions)
    _, verdict = conditions_soumission.valider(conditions)
    assert verdict is not None and verdict["code"] == "REJ-CONTRAT-INVALIDE"


# ----------------------------------------------------------------------------------------- document client
def test_le_document_html_porte_les_sections_et_jamais_un_cout_ni_une_marge():
    conditions, _ = _composer()
    brut, verdict = soumission.generer_brouillon_html(_devis(conditions))
    assert verdict is None
    html = unescape(brut)
    for attendu in ("Exclusions", "Hypothèses", "Délai", "Validité", cb.SOUMISSION["exclusions"][0],
                    "Cette soumission est valide jusqu'au 3 décembre 2026.", "taxes (TPS/TVQ) en sus"):
        assert attendu in html, attendu
    for interdit in ("900.00", "0.25", "cout_", "taux_marge", "Feuille de prix", "bareme-fictif", "proprio.fictif",
                     "admin.fictif"):
        assert interdit not in html, interdit


def test_sans_conditions_le_document_est_identique_a_celui_d_avant():
    html, _ = soumission.generer_brouillon_html(_devis())
    assert "conditions-soumission" not in html and "<h3>Délai</h3>" not in html
    contenu, _ = soumission.contenu_client(_devis())
    assert "conditions_soumission" not in contenu


def test_le_texte_declare_est_echappe_dans_le_html():
    conditions, _ = _composer(soumission_declaree={"exclusions": ["<script>alert(1)</script> & <b>gras</b>"]})
    html, _ = soumission.generer_brouillon_html(_devis(conditions))
    assert "<script>" not in html and "&lt;script&gt;" in html and "&amp;" in html


def test_des_conditions_mal_formees_dans_le_devis_sont_refusees_par_le_document():
    conditions, _ = _composer()
    conditions["extra"] = "clé hors contrat"
    html, verdict = soumission.generer_brouillon_html(_devis(conditions))
    assert html is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"
    octets, verdict = soumission_pdf.generer_brouillon_pdf(_devis(conditions))
    assert octets is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_le_pdf_porte_les_memes_sections_et_aucun_cout():
    pytest.importorskip("reportlab")
    ok, _ = soumission_pdf.pdf_installe()
    if not ok:
        pytest.skip("brique PDF absente ou d'une autre version")
    pypdf = pytest.importorskip("pypdf")
    import io

    conditions, _ = _composer()
    octets, verdict = soumission_pdf.generer_brouillon_pdf(_devis(conditions))
    assert verdict is None
    texte = " ".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(octets)).pages)
    texte = " ".join(texte.split())
    for attendu in ("Exclusions", "Hypothèses", "Délai", "Validité",
                    "Cette soumission est valide jusqu'au 3 décembre 2026."):
        assert attendu in texte, attendu
    assert "900,00" not in texte and "taux_marge" not in texte
    sans, _ = soumission_pdf.generer_brouillon_pdf(_devis())
    assert "Validité" not in " ".join(
        " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(sans)).pages).split())
    # mêmes entrées, mêmes octets
    encore, _ = soumission_pdf.generer_brouillon_pdf(_devis(conditions))
    assert encore == octets
