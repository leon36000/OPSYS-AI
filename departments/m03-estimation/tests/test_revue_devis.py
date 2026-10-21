"""Tests de la revue d'un devis avant son envoi (PLAN T4.7, revue_devis.py, DEFINITION-PRODUIT §7 M3.14).

Module pur : aucune base, aucun bus. Chaque motif cite sa donnée et sa source ; un seuil vide donne « seuil à
configurer », jamais une valeur inventée ; un fait absent est « non évaluable », jamais « rien à signaler » ; sous le
minimum rentable, l'alerte est rouge. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import ast
import copy
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, hierarchie_echelle, revue_devis, verdicts  # noqa: E402

FICTIF = True

NIVEAUX = hierarchie_echelle.NIVEAUX_CONFIANCE  # REFERENCE_ECHELLE, MULTI_VUES, MONO_VUE_BORNES_LARGES, INDETERMINE
CONFIANCE_OK = NIVEAUX[0]
CONFIANCE_MULTI = NIVEAUX[1]
CONFIANCE_MONO = NIVEAUX[2]
CONFIANCE_INDETERMINEE = NIVEAUX[3]
VERDICT_PHOTOS = contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE
VERDICT_SANS_BLOCAGE = contrats.VERDICT_AUCUN_BLOCAGE

SEUILS = {
    "confiance_minimale": CONFIANCE_MULTI,
    "montant_maximal_cad": 10000,
    "marge_minimale": 0.25,
    "distance_maximale_km": 50,
    "minimum_rentable_cad": 2500,
}
CONTEXTE_SAIN = {
    "niveau_confiance_hierarchie": CONFIANCE_OK,
    "verdict_estimation": VERDICT_SANS_BLOCAGE,
    "alerte_plancher": False,
    "service_complexe": False,
    "client_a_risque": False,
    "distance_km": "12.5",
    "donnees_fournisseur_completes": True,
}
CHAMPS_SEUILS_A_CONFIGURER = {
    revue_devis.PRIX_SOUS_MINIMUM_RENTABLE: "minimum_rentable_cad",
    revue_devis.CONFIANCE_SOUS_SEUIL: "confiance_minimale",
    revue_devis.MONTANT_AU_DESSUS_SEUIL: "montant_maximal_cad",
    revue_devis.MARGE_SOUS_SEUIL: "marge_minimale",
    revue_devis.CHANTIER_ELOIGNE: "distance_maximale_km",
}


def _devis(prix="4000.00", marge="0.30", devis_id="M3-DEVIS-revue-001"):
    return {"devis_id": devis_id, "prix_total": Decimal(prix), "taux_marge": Decimal(marge)}


def _revue(devis=None, contexte=CONTEXTE_SAIN, seuils=SEUILS):
    revue, verdict = revue_devis.evaluer_revue(devis if devis is not None else _devis(), contexte, seuils)
    assert verdict is None, verdict
    return revue


def _codes(revue):
    return [m["code"] for m in revue["motifs"]]


def _non_evaluables(revue):
    return {n["code"]: n for n in revue["non_evaluables"]}


def _refus(devis, contexte, seuils, code):
    revue, verdict = revue_devis.evaluer_revue(devis, contexte, seuils)
    assert revue is None
    assert verdict["code"] == code, verdict
    assert verdict["code"] in verdicts.CODES_M3_LIST
    return verdict


# =========================================================================================
# 1. Un devis sans aucun motif : SEULEMENT si tout est jugé
# =========================================================================================
def test_un_devis_dont_tout_est_juge_et_rien_ne_s_applique_n_a_aucun_motif():
    revue = _revue()

    assert revue["motifs"] == [] and revue["non_evaluables"] == []
    assert revue["aucun_motif"] is True and revue["alerte_rouge"] is False
    assert revue["devis_id"] == "M3-DEVIS-revue-001"


def test_un_devis_dont_des_criteres_ne_sont_pas_juges_n_est_jamais_sans_motif():
    revue = _revue(contexte={"niveau_confiance_hierarchie": CONFIANCE_OK})

    assert revue["motifs"] == []
    assert revue["aucun_motif"] is False  # le silence des faits absents n'est pas « rien à signaler »
    assert {n["code"] for n in revue["non_evaluables"]} >= {
        revue_devis.PHOTOS_INSUFFISANTES, revue_devis.SERVICE_COMPLEXE, revue_devis.CLIENT_A_RISQUE,
        revue_devis.CHANTIER_ELOIGNE, revue_devis.DONNEE_FOURNISSEUR_ABSENTE, revue_devis.PLANCHER_ESTIMATION_FRANCHI,
    }


# =========================================================================================
# 2. Seuils vides : « seuil à configurer », jamais une valeur inventée
# =========================================================================================
@pytest.mark.parametrize(
    "seuils", [None, {}, {cle: None for cle in revue_devis.CHAMPS_SEUILS}], ids=["absent", "vide", "nuls"]
)
def test_des_seuils_vides_rendent_chaque_critere_a_seuil_non_evaluable_et_ne_declenchent_rien(seuils):
    # Un devis qui déclencherait tout si les seuils existaient : 1 $ (sous n'importe quel minimum), marge nulle.
    devis = _devis(prix="1.00", marge="0")
    contexte = {**CONTEXTE_SAIN, "niveau_confiance_hierarchie": CONFIANCE_MULTI, "distance_km": "9999"}

    revue = _revue(devis, contexte, seuils)

    a_configurer = _non_evaluables(revue)
    assert set(a_configurer) == set(CHAMPS_SEUILS_A_CONFIGURER)
    for code, cle in CHAMPS_SEUILS_A_CONFIGURER.items():
        assert f"{revue_devis.SEUIL_A_CONFIGURER} : {cle}" in a_configurer[code]["manque"]
        assert any(cle in geste and "department.yaml" in geste for geste in a_configurer[code]["a_faire"])
    assert revue["motifs"] == [] and revue["alerte_rouge"] is False and revue["aucun_motif"] is False


def test_le_texte_d_un_seuil_vide_est_exactement_seuil_a_configurer():
    assert revue_devis.SEUIL_A_CONFIGURER == "seuil à configurer"


@pytest.mark.parametrize(
    "seuils", [[], "illisible", 12, ["minimum_rentable_cad"]], ids=["liste", "texte", "nombre", "cles"]
)
def test_une_configuration_illisible_n_est_pas_lue_comme_des_seuils(seuils):
    revue = _revue(_devis(prix="1.00", marge="0"), CONTEXTE_SAIN, seuils)

    a_configurer = _non_evaluables(revue)
    assert set(a_configurer) == set(CHAMPS_SEUILS_A_CONFIGURER)
    assert all("illisible" in a_configurer[code]["manque"][0] for code in a_configurer)
    assert revue["motifs"] == []


@pytest.mark.parametrize(("cle", "mauvaise_valeur"), [
    ("montant_maximal_cad", 0), ("montant_maximal_cad", -5), ("montant_maximal_cad", "abc"),
    ("montant_maximal_cad", True),
    ("montant_maximal_cad", float("nan")), ("montant_maximal_cad", [1]),
    ("marge_minimale", -0.1), ("marge_minimale", "beaucoup"), ("marge_minimale", False),
    ("distance_maximale_km", 0), ("distance_maximale_km", "loin"),
    ("minimum_rentable_cad", 0), ("minimum_rentable_cad", -100), ("minimum_rentable_cad", "peu"),
    ("confiance_minimale", CONFIANCE_INDETERMINEE), ("confiance_minimale", "EXCELLENTE"), ("confiance_minimale", 2),
])
def test_un_seuil_invalide_est_nomme_invalide_et_jamais_remplace(cle, mauvaise_valeur):
    revue = _revue(_devis(prix="1.00", marge="0"), CONTEXTE_SAIN, {**SEUILS, cle: mauvaise_valeur})

    code = next(code for code, cle_du_code in CHAMPS_SEUILS_A_CONFIGURER.items() if cle_du_code == cle)
    assert code not in _codes(revue)
    assert any("seuil invalide" in ligne and cle in ligne for ligne in _non_evaluables(revue)[code]["manque"])


def test_un_seuil_de_marge_a_zero_est_valide_et_un_devis_a_marge_nulle_n_est_pas_sous_zero():
    revue = _revue(_devis(marge="0"), CONTEXTE_SAIN, {**SEUILS, "marge_minimale": 0})

    assert revue_devis.MARGE_SOUS_SEUIL not in _codes(revue)
    assert revue_devis.MARGE_SOUS_SEUIL not in _non_evaluables(revue)


@pytest.mark.parametrize("valeur", [10000, 10000.0, "10000", Decimal("10000"), "10000.00"])
def test_un_seuil_se_lit_tel_qu_ecrit_entier_flottant_texte_ou_decimal(valeur):
    seuils = {**SEUILS, "montant_maximal_cad": valeur}

    assert revue_devis.MONTANT_AU_DESSUS_SEUIL not in _codes(_revue(_devis(prix="10000.00"), seuils=seuils))
    assert revue_devis.MONTANT_AU_DESSUS_SEUIL in _codes(_revue(_devis(prix="10000.01"), seuils=seuils))


def test_une_cle_de_seuil_inconnue_est_sans_effet_et_ne_masque_pas_le_seuil_absent():
    seuils = {"marge_minimal": 0.25}  # faute de frappe : le vrai seuil reste « à configurer », visible

    revue = _revue(_devis(marge="0"), CONTEXTE_SAIN, seuils)

    assert revue_devis.MARGE_SOUS_SEUIL not in _codes(revue)
    assert "seuil à configurer : marge_minimale" in _non_evaluables(revue)[revue_devis.MARGE_SOUS_SEUIL]["manque"]


# =========================================================================================
# 3. Chaque critère à seuil : comparaison STRICTE, donnée et seuil cités
# =========================================================================================
@pytest.mark.parametrize(("code", "pile", "franchi", "donnee", "seuil"), [
    (revue_devis.MONTANT_AU_DESSUS_SEUIL, {"prix": "10000.00"}, {"prix": "10000.01"},
     ("prix_total", "10000.01", "devis"), ("montant_maximal_cad", "10000")),
    (revue_devis.MARGE_SOUS_SEUIL, {"marge": "0.25"}, {"marge": "0.24"},
     ("taux_marge", "0.24", "devis"), ("marge_minimale", "0.25")),
    (revue_devis.CHANTIER_ELOIGNE, {"distance_km": "50"}, {"distance_km": "50.1"},
     ("distance_km", "50.1", "contexte_revue"), ("distance_maximale_km", "50")),
    (revue_devis.PRIX_SOUS_MINIMUM_RENTABLE, {"prix": "2500.00"}, {"prix": "2499.99"},
     ("prix_total", "2499.99", "devis"), ("minimum_rentable_cad", "2500")),
])
def test_un_devis_exactement_au_seuil_ne_declenche_rien_un_cent_de_plus_declenche_et_cite_sa_donnee(
    code, pile, franchi, donnee, seuil,
):
    def revue_pour(valeurs):
        devis = _devis(**{cle: valeur for cle, valeur in valeurs.items() if cle in ("prix", "marge")})
        contexte = {**CONTEXTE_SAIN, **{cle: valeur for cle, valeur in valeurs.items() if cle == "distance_km"}}
        return _revue(devis, contexte)

    assert code not in _codes(revue_pour(pile))
    motif = next(m for m in revue_pour(franchi)["motifs"] if m["code"] == code)
    assert motif["donnee"] == {"nom": donnee[0], "valeur": donnee[1], "source": donnee[2]}
    assert motif["seuil"] == {"nom": seuil[0], "valeur": seuil[1], "source": "configuration"}
    assert donnee[1] in motif["explication"] and seuil[1] in motif["explication"]


@pytest.mark.parametrize("niveau", NIVEAUX)
@pytest.mark.parametrize("minimum", NIVEAUX[:3])
def test_la_confiance_est_sous_le_seuil_quand_son_rang_est_plus_bas_que_celui_du_minimum(niveau, minimum):
    revue = _revue(contexte={**CONTEXTE_SAIN, "niveau_confiance_hierarchie": niveau},
                   seuils={**SEUILS, "confiance_minimale": minimum})

    assert (revue_devis.CONFIANCE_SOUS_SEUIL in _codes(revue)) == (NIVEAUX.index(niveau) > NIVEAUX.index(minimum))


def test_le_motif_de_confiance_cite_le_libelle_de_la_hierarchie_et_le_seuil():
    revue = _revue(contexte={**CONTEXTE_SAIN, "niveau_confiance_hierarchie": CONFIANCE_MONO})

    motif = next(m for m in revue["motifs"] if m["code"] == revue_devis.CONFIANCE_SOUS_SEUIL)
    assert motif["donnee"] == {
        "nom": "niveau_confiance_hierarchie", "valeur": CONFIANCE_MONO, "source": "contexte_revue"}
    assert motif["seuil"] == {"nom": "confiance_minimale", "valeur": CONFIANCE_MULTI, "source": "configuration"}
    assert motif["gravite"] == revue_devis.GRAVITE_REVUE


@pytest.mark.parametrize("niveau", NIVEAUX)
def test_la_mesure_est_incertaine_pour_une_photo_sans_echelle_et_pour_l_indetermine_sans_aucun_seuil(niveau):
    revue = _revue(contexte={**CONTEXTE_SAIN, "niveau_confiance_hierarchie": niveau}, seuils=None)

    assert (revue_devis.MESURE_INCERTAINE in _codes(revue)) == (niveau in (CONFIANCE_MONO, CONFIANCE_INDETERMINEE))
    if revue_devis.MESURE_INCERTAINE in _codes(revue):
        motif = next(m for m in revue["motifs"] if m["code"] == revue_devis.MESURE_INCERTAINE)
        assert motif["seuil"] is None and motif["donnee"]["valeur"] == niveau


# =========================================================================================
# 4. Critères sans seuil : les faits fournis
# =========================================================================================
@pytest.mark.parametrize(("code", "cle", "valeur_qui_declenche", "valeur_qui_ne_declenche_pas"), [
    (revue_devis.PLANCHER_ESTIMATION_FRANCHI, "alerte_plancher", True, False),
    (revue_devis.SERVICE_COMPLEXE, "service_complexe", True, False),
    (revue_devis.CLIENT_A_RISQUE, "client_a_risque", True, False),
    (revue_devis.DONNEE_FOURNISSEUR_ABSENTE, "donnees_fournisseur_completes", False, True),
])
def test_un_fait_booleen_declenche_dans_un_seul_sens_cite_sa_source_et_absent_il_est_non_evaluable(
    code, cle, valeur_qui_declenche, valeur_qui_ne_declenche_pas,
):
    declenche = _revue(contexte={**CONTEXTE_SAIN, cle: valeur_qui_declenche})
    calme = _revue(contexte={**CONTEXTE_SAIN, cle: valeur_qui_ne_declenche_pas})
    absent = _revue(contexte={c: v for c, v in CONTEXTE_SAIN.items() if c != cle})

    motif = next(m for m in declenche["motifs"] if m["code"] == code)
    assert motif["donnee"] == {
        "nom": cle, "valeur": "vrai" if valeur_qui_declenche else "faux", "source": "contexte_revue"}
    assert motif["seuil"] is None
    assert code not in _codes(calme) and code not in _non_evaluables(calme)
    assert code not in _codes(absent)
    assert f"donnée à fournir : {cle}" in _non_evaluables(absent)[code]["manque"]
    assert any(cle in geste and "contexte_revue" in geste for geste in _non_evaluables(absent)[code]["a_faire"])


@pytest.mark.parametrize(("verdict_estimation", "declenche"), [
    (contrats.VERDICTS_ESTIMATION[i], contrats.VERDICTS_ESTIMATION[i] == VERDICT_PHOTOS)
    for i in range(len(contrats.VERDICTS_ESTIMATION))
])
def test_les_photos_sont_insuffisantes_seulement_quand_l_estimation_le_dit(verdict_estimation, declenche):
    revue = _revue(contexte={**CONTEXTE_SAIN, "verdict_estimation": verdict_estimation})

    assert (revue_devis.PHOTOS_INSUFFISANTES in _codes(revue)) is declenche
    if declenche:
        motif = next(m for m in revue["motifs"] if m["code"] == revue_devis.PHOTOS_INSUFFISANTES)
        assert motif["donnee"] == {"nom": "verdict_estimation", "valeur": VERDICT_PHOTOS, "source": "contexte_revue"}


def test_un_fait_nul_est_un_fait_absent_jamais_un_fait_faux():
    revue = _revue(contexte={**CONTEXTE_SAIN, "service_complexe": None, "distance_km": None})

    assert revue_devis.SERVICE_COMPLEXE in _non_evaluables(revue)
    assert revue_devis.CHANTIER_ELOIGNE in _non_evaluables(revue)
    assert revue["motifs"] == []


def test_sans_contexte_du_tout_chaque_critere_qui_veut_un_fait_le_demande():
    revue = _revue(contexte=None)

    non_evaluables = _non_evaluables(revue)
    assert set(non_evaluables) == set(revue_devis.CODES_MOTIFS) - {
        revue_devis.PRIX_SOUS_MINIMUM_RENTABLE, revue_devis.MONTANT_AU_DESSUS_SEUIL, revue_devis.MARGE_SOUS_SEUIL}
    assert revue["motifs"] == []  # rien n'est déduit du silence


# =========================================================================================
# 5. L'alerte rouge : sous le minimum rentable, et l'alerte de plancher de l'estimation
# =========================================================================================
def test_sous_le_minimum_rentable_l_alerte_est_rouge_et_passe_devant_les_autres_motifs():
    revue = _revue(_devis(prix="2000.00", marge="0.10"), {**CONTEXTE_SAIN, "service_complexe": True})

    assert revue["alerte_rouge"] is True
    assert _codes(revue) == [
        revue_devis.PRIX_SOUS_MINIMUM_RENTABLE, revue_devis.MARGE_SOUS_SEUIL, revue_devis.SERVICE_COMPLEXE]
    assert revue["motifs"][0]["gravite"] == revue_devis.GRAVITE_ROUGE
    assert [m["gravite"] for m in revue["motifs"][1:]] == [revue_devis.GRAVITE_REVUE] * 2


def test_l_alerte_de_plancher_de_l_estimation_est_rouge_meme_quand_le_prix_du_devis_est_bon():
    revue = _revue(contexte={**CONTEXTE_SAIN, "alerte_plancher": True})

    assert revue_devis.PRIX_SOUS_MINIMUM_RENTABLE not in _codes(revue)
    assert revue["alerte_rouge"] is True
    motif = next(m for m in revue["motifs"] if m["code"] == revue_devis.PLANCHER_ESTIMATION_FRANCHI)
    assert motif["gravite"] == "rouge"


def test_seuls_ces_deux_motifs_sont_rouges_les_neuf_autres_demandent_une_revue():
    revue = _revue(
        _devis(prix="1.00", marge="0.01"),
        {
            "niveau_confiance_hierarchie": CONFIANCE_INDETERMINEE, "verdict_estimation": VERDICT_PHOTOS,
            "alerte_plancher": True, "service_complexe": True, "client_a_risque": True, "distance_km": "500",
            "donnees_fournisseur_completes": False,
        },
        {**SEUILS, "montant_maximal_cad": 0.5},
    )

    assert set(_codes(revue)) == set(revue_devis.CODES_MOTIFS)  # les onze s'appliquent
    rouges = {m["code"] for m in revue["motifs"] if m["gravite"] == revue_devis.GRAVITE_ROUGE}
    assert rouges == {revue_devis.PRIX_SOUS_MINIMUM_RENTABLE, revue_devis.PLANCHER_ESTIMATION_FRANCHI}
    assert {m["gravite"] for m in revue["motifs"] if m["code"] not in rouges} == {revue_devis.GRAVITE_REVUE}
    # Les rouges d'abord, puis l'ordre déclaré des motifs.
    attendu = [c for c in revue_devis.CODES_MOTIFS if c in rouges] + [
        c for c in revue_devis.CODES_MOTIFS if c not in rouges]
    assert _codes(revue) == attendu


def test_un_devis_au_prix_sain_sans_alerte_de_plancher_n_a_pas_d_alerte_rouge():
    assert _revue(contexte={**CONTEXTE_SAIN, "service_complexe": True})["alerte_rouge"] is False


# =========================================================================================
# 6. Fail-closed : un devis ou un contexte inexploitable refuse toute la revue
# =========================================================================================
@pytest.mark.parametrize("devis", [
    None, [], "M3-DEVIS", {}, {"devis_id": ""}, {"devis_id": "  ", "prix_total": "1", "taux_marge": "0.2"},
    {"devis_id": 12, "prix_total": "1", "taux_marge": "0.2"},
    {"devis_id": "D", "taux_marge": "0.2"}, {"devis_id": "D", "prix_total": "1"},
    {"devis_id": "D", "prix_total": "abc", "taux_marge": "0.2"},
    {"devis_id": "D", "prix_total": True, "taux_marge": "0.2"},
    {"devis_id": "D", "prix_total": "1", "taux_marge": float("nan")},
    {"devis_id": "D", "prix_total": None, "taux_marge": "0"},
])
def test_un_devis_inexploitable_est_refuse_avec_un_verdict_nomme(devis):
    _refus(devis, CONTEXTE_SAIN, SEUILS, "REJ-REVUE-DEVIS-INVALIDE")


@pytest.mark.parametrize(("contexte", "morceau"), [
    ("oui", "objet"), ([], "objet"),
    ({"climat": "froid"}, "climat"),
    ({"niveau_confiance_hierarchie": "EXCELLENT"}, "niveau_confiance_hierarchie"),
    ({"verdict_estimation": "OK"}, "verdict_estimation"),
    ({"alerte_plancher": 1}, "alerte_plancher"), ({"service_complexe": "oui"}, "service_complexe"),
    ({"client_a_risque": 0}, "client_a_risque"),
    ({"donnees_fournisseur_completes": "non"}, "donnees_fournisseur_completes"),
    ({"distance_km": -1}, "distance_km"), ({"distance_km": "loin"}, "distance_km"),
    ({"distance_km": True}, "distance_km"),
    ({"distance_km": float("inf")}, "distance_km"), ({"distance_km": [50]}, "distance_km"),
])
def test_un_contexte_fourni_de_travers_est_refuse_jamais_ignore(contexte, morceau):
    verdict = _refus(_devis(), contexte, SEUILS, "REJ-REVUE-CONTEXTE-INVALIDE")

    assert morceau in verdict["detail"]


def test_toutes_les_fautes_du_contexte_sont_nommees_en_un_seul_refus():
    verdict = _refus(_devis(), {"climat": 1, "service_complexe": "oui", "distance_km": -3}, SEUILS,
                     "REJ-REVUE-CONTEXTE-INVALIDE")

    assert all(morceau in verdict["detail"] for morceau in ("climat", "service_complexe", "distance_km"))


def test_la_distance_zero_est_valide_et_peut_etre_un_nombre_ou_un_texte():
    for distance in (0, "0", 0.0, Decimal("0")):
        revue = _revue(contexte={**CONTEXTE_SAIN, "distance_km": distance})
        assert revue_devis.CHANTIER_ELOIGNE not in _codes(revue)
        assert revue_devis.CHANTIER_ELOIGNE not in _non_evaluables(revue)


def test_un_montant_en_virgule_flottante_n_introduit_aucun_artefact_binaire():
    # 0.1 + 0.2 != 0.3 en flottant ; lu tel qu'écrit, un seuil 0.35 égal au taux 0.35 ne déclenche pas.
    revue = _revue(_devis(marge="0.35"), seuils={**SEUILS, "marge_minimale": 0.35})

    assert revue_devis.MARGE_SOUS_SEUIL not in _codes(revue)


# =========================================================================================
# 7. Synthèse, résumé de l'attente, pureté
# =========================================================================================
def test_la_synthese_garde_l_alerte_et_les_codes_jamais_les_valeurs():
    revue = _revue(_devis(prix="2000.00", marge="0.10"), {**CONTEXTE_SAIN, "distance_km": "77"})

    synthese = revue_devis.synthese(revue)

    assert synthese == {
        "alerte_rouge": True,
        "motifs": [revue_devis.PRIX_SOUS_MINIMUM_RENTABLE, revue_devis.MARGE_SOUS_SEUIL, revue_devis.CHANTIER_ELOIGNE],
        "non_evaluables": [],
    }
    assert "2000" not in str(synthese) and "0.10" not in str(synthese) and "77" not in str(synthese)


def test_la_synthese_d_une_revue_sans_rouge_n_a_pas_d_alerte():
    synthese = revue_devis.synthese(_revue(_devis(prix="4000.00", marge="0.10")))

    assert synthese == {"alerte_rouge": False, "motifs": [revue_devis.MARGE_SOUS_SEUIL], "non_evaluables": []}


def test_le_resume_d_un_devis_sans_motif_le_dit_sans_pretendre_plus():
    assert revue_devis.resume_attente(_revue()) == (
        "Envoi du devis M3-DEVIS-revue-001 à approuver : aucun motif de revue."
    )


def test_le_resume_dit_l_alerte_rouge_d_abord_puis_les_motifs_puis_ce_qui_n_est_pas_evalue():
    revue = _revue(_devis(prix="2000.00", marge="0.10"), {"niveau_confiance_hierarchie": CONFIANCE_OK})

    resume = revue_devis.resume_attente(revue)

    debut = (
        "Envoi du devis M3-DEVIS-revue-001 à approuver : "
        "ALERTE ROUGE : prix 2000.00 $ sous le minimum rentable 2500 $"
    )
    assert resume.startswith(debut)
    assert resume.index("marge 0.10 sous 0.25") > resume.index("ALERTE ROUGE")
    assert "critères non évaluables (seuil à configurer ou donnée à fournir)" in resume
    assert len(resume) <= revue_devis.LIMITE_RESUME


def test_un_seul_critere_non_evalue_est_dit_au_singulier():
    revue = _revue(contexte={c: v for c, v in CONTEXTE_SAIN.items() if c != "service_complexe"})

    assert "1 critère non évaluable (" in revue_devis.resume_attente(revue)


def test_le_resume_ne_depasse_jamais_la_limite_et_compte_ce_qu_il_ne_montre_pas():
    revue = _revue(
        _devis(prix="1.00", marge="0.00", devis_id="M3-DEVIS-un-identifiant-particulierement-long-0001"),
        {
            "niveau_confiance_hierarchie": CONFIANCE_INDETERMINEE, "verdict_estimation": VERDICT_PHOTOS,
            "alerte_plancher": True, "service_complexe": True, "client_a_risque": True, "distance_km": "500",
            "donnees_fournisseur_completes": False,
        },
        {**SEUILS, "montant_maximal_cad": 0.5},
    )

    resume = revue_devis.resume_attente(revue)

    assert len(resume) <= revue_devis.LIMITE_RESUME
    assert "ALERTE ROUGE" in resume  # l'essentiel reste dit
    assert "; + " in resume and resume.endswith(("autres", "autre"))  # le reste est compté, pas coupé
    petit = revue_devis.resume_attente(revue, limite=60)
    assert len(petit) <= 60 and petit.endswith("…")  # même à la limite, jamais un texte plus long


def test_le_resume_est_borne_a_ce_que_l_app_du_proprietaire_montre():
    from opsys import approbations_appareil

    assert revue_devis.LIMITE_RESUME == approbations_appareil.LIMITE_RESUME_ATTENTE


@pytest.mark.parametrize(("texte", "limite", "attendu"), [
    ("court", 10, "court"), ("exactement10", 12, "exactement10"), ("un texte assez long", 10, "un texte…"),
])
def test_abreger_coupe_avec_une_ellipse_et_ne_touche_pas_ce_qui_tient(texte, limite, attendu):
    assert revue_devis.abreger(texte, limite) == attendu
    assert len(revue_devis.abreger(texte, limite)) <= limite


def test_la_revue_ne_modifie_aucune_de_ses_entrees_et_rend_le_meme_resultat():
    devis, contexte, seuils = _devis(prix="2000.00"), dict(CONTEXTE_SAIN), dict(SEUILS)
    avant = copy.deepcopy((devis, contexte, seuils))

    premiere = revue_devis.evaluer_revue(devis, contexte, seuils)
    seconde = revue_devis.evaluer_revue(devis, contexte, seuils)

    assert (devis, contexte, seuils) == avant
    assert premiere == seconde and premiere[1] is None


def test_le_prix_et_la_marge_sont_lus_tels_quels_du_devis_jamais_recalcules():
    # Un devis dont le total ne « colle » à aucune ligne : la revue lit prix_total, elle ne le refait pas.
    devis = {**_devis(prix="2000.00"), "lignes": [{"prix_ligne": Decimal("9999.99")}], "cout_total": Decimal("1")}

    revue = _revue(devis)

    assert next(m for m in revue["motifs"] if m["code"] == revue_devis.PRIX_SOUS_MINIMUM_RENTABLE)[
        "donnee"]["valeur"] == "2000.00"


def test_le_module_est_pur_ni_opsys_ni_horloge_ni_reseau():
    arbre = ast.parse((_SRC / "m3_estimation" / "revue_devis.py").read_text(encoding="utf-8"))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes |= {alias.name.split(".")[0] for alias in noeud.names}
        elif isinstance(noeud, ast.ImportFrom):
            importes.add((noeud.module or "").split(".")[0] if noeud.level == 0 else "(relatif)")
    assert importes, "extracteur vide : aucun import trouvé, le test ne prouverait rien"
    assert importes.isdisjoint({"opsys", "datetime", "time", "random", "socket", "urllib", "requests", "yaml"})


def test_les_onze_motifs_du_produit_sont_tous_juges():
    """§7 M3 : dix motifs de validation humaine, dont « prix sous le minimum rentable » (rouge) ; la revue y
    ajoute l'alerte de plancher que l'estimation a déjà levée. Aucun code n'est orphelin ni oublié."""
    assert len(revue_devis.CODES_MOTIFS) == len(set(revue_devis.CODES_MOTIFS)) == 11
    revue = _revue(contexte=None, seuils=None)
    juges = set(_codes(revue)) | set(_non_evaluables(revue))
    assert juges == set(revue_devis.CODES_MOTIFS)
