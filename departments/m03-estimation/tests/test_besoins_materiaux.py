"""Contrat `BesoinsMateriauxM3` v1 (PLAN T2.3-e), module pur `besoins_materiaux.py` : calcul des
lignes depuis le barème, validation stricte côté émetteur, identifiant d'événement.

Les quantités viennent du CODE (Decimal, texte) ; un `facteur_perte` que le barème ne fournit pas
reste absent et signalé ; aucun prix ni coût ne traverse ce contrat. Les fixtures portent des
matériaux fictifs. Les codes de rejet du catalogue sont tous exercés ici (une garde jamais exercée
n'est pas tenue).
"""

from __future__ import annotations

import copy
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import besoins_materiaux, verdicts  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64

MATERIAU_AVEC_PERTE = {
    "materiau": "Revêtement vinyle (fictif)",
    "sku": "SKU-FICTIF-VINYLE",
    "quantite_par_unite": "0.0111",
    "unite": "carton",
    "facteur_perte": "0.10",
}
MATERIAU_SANS_PERTE = {"materiau": "Clous (fictif)", "quantite_par_unite": "0.5", "unite": "boite"}


def _bareme(materiaux=None, poste="ravalement", **poste_extra):
    corps = {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, **poste_extra}
    if materiaux is not None:
        corps["materiaux"] = materiaux
    return {"version": "2026.1", "unite": "pi2", "postes": {poste: corps}}


def _lignes(materiaux, quantite=1200):
    resultat, verdict = besoins_materiaux.calculer_lignes(_bareme(materiaux), "ravalement", quantite)
    assert verdict is None, verdict
    return resultat


def _contrat(**surcharges):
    contrat = {
        "devis_id": "M3-DEVIS-0123456789abcdef",
        "lead_id": "lead-fictif-001",
        "estimation_id": HASH_A,
        "rang_registre": 0,
        "bareme_version": "2026.1",
        "niveau_confiance": 0.9,
        "lignes": [
            {
                "materiau": "Revêtement vinyle (fictif)",
                "sku": "SKU-FICTIF-VINYLE",
                "quantite_estimee": "13.32",
                "unite": "carton",
                "facteur_perte": "0.10",
            },
            {"materiau": "Clous (fictif)", "quantite_estimee": "600", "unite": "boite"},
        ],
        "facteurs_perte_absents": ["Clous (fictif)"],
    }
    contrat.update(surcharges)
    return contrat


def _refuse(materiaux=None, *, bareme=None, quantite=1200):
    """Verdict rendu par `calculer_lignes`, après avoir vérifié que rien n'est calculé."""
    bareme = bareme if bareme is not None else _bareme(materiaux)
    lignes, verdict = besoins_materiaux.calculer_lignes(bareme, "ravalement", quantite)
    assert lignes is None
    assert verdict is not None
    assert verdict["code"] == "REJ-BESOINS-MATERIAUX-INVALIDE"
    assert verdict["detail"], "le rejet doit dire quoi corriger"
    return verdict


def _refuse_contrat(charge):
    contrat, verdict = besoins_materiaux.valider_besoins_materiaux(charge)
    assert contrat is None
    assert verdict is not None
    assert verdict["code"] == "REJ-BESOINS-MATERIAUX-INVALIDE"
    return verdict


# ------------------------------------------------------------------------ calculer_lignes : nominal
def test_lignes_calculees_par_le_code_en_texte_decimal_exact():
    resultat = _lignes([MATERIAU_AVEC_PERTE, MATERIAU_SANS_PERTE])
    # 1200 x 0.0111 = 13.32 exactement (jamais 13.319999999999999) ; 1200 x 0.5 = 600, sans « .0 ».
    assert resultat["lignes"] == [
        {
            "materiau": "Revêtement vinyle (fictif)",
            "sku": "SKU-FICTIF-VINYLE",
            "quantite_estimee": "13.32",
            "unite": "carton",
            "facteur_perte": "0.10",
        },
        {"materiau": "Clous (fictif)", "quantite_estimee": "600", "unite": "boite"},
    ]


def test_un_flottant_de_quantite_ne_laisse_aucun_artefact_binaire():
    # 0.1 x 3 vaut 0.3 en décimal ; en binaire, 0.30000000000000004.
    resultat = _lignes([{"materiau": "M", "quantite_par_unite": "3", "unite": "u"}], quantite=0.1)
    assert resultat["lignes"][0]["quantite_estimee"] == "0.3"


def test_la_quantite_de_louvrage_peut_etre_entiere_ou_decimale():
    assert _lignes([MATERIAU_SANS_PERTE], quantite=10)["lignes"][0]["quantite_estimee"] == "5"
    assert _lignes([MATERIAU_SANS_PERTE], quantite=10.5)["lignes"][0]["quantite_estimee"] == "5.25"


def test_facteur_perte_absent_du_bareme_reste_absent_de_la_ligne_et_est_signale():
    resultat = _lignes([MATERIAU_AVEC_PERTE, MATERIAU_SANS_PERTE])
    ligne_sans = resultat["lignes"][1]
    assert "facteur_perte" not in ligne_sans, "jamais mis à zéro ni inventé"
    assert resultat["facteurs_perte_absents"] == ["Clous (fictif)"]


def test_facteur_perte_zero_fourni_est_conserve_et_nest_pas_un_absent():
    resultat = _lignes([{**MATERIAU_SANS_PERTE, "facteur_perte": "0"}])
    assert resultat["lignes"][0]["facteur_perte"] == "0"
    assert resultat["facteurs_perte_absents"] == []


def test_sku_absent_du_bareme_reste_absent_de_la_ligne():
    resultat = _lignes([MATERIAU_SANS_PERTE])
    assert "sku" not in resultat["lignes"][0], "un SKU inconnu n'est jamais deviné"


def test_poste_sans_materiaux_ne_produit_aucun_besoin():
    assert besoins_materiaux.calculer_lignes(_bareme(None), "ravalement", 1200) == (None, None)


@pytest.mark.parametrize(
    "bareme",
    [None, "texte", {}, {"postes": None}, {"postes": {"autre": {}}}, {"postes": {"ravalement": 3}}],
)
def test_bareme_inexploitable_ne_produit_aucun_besoin_sans_exception(bareme):
    assert besoins_materiaux.calculer_lignes(bareme, "ravalement", 1200) == (None, None)


def test_les_lignes_rendues_ne_portent_ni_prix_ni_cout():
    resultat = _lignes([MATERIAU_AVEC_PERTE, MATERIAU_SANS_PERTE])
    cles = {cle for ligne in resultat["lignes"] for cle in ligne}
    assert cles <= set(besoins_materiaux.CHAMPS_LIGNE_BESOINS_REQUIS) | set(
        besoins_materiaux.CHAMPS_LIGNE_BESOINS_OPTIONNELS
    )
    assert not cles & besoins_materiaux.CLES_PRIX_ET_COUT_INTERDITES


def test_le_calcul_ne_modifie_pas_le_bareme_de_lappelant():
    bareme = _bareme([copy.deepcopy(MATERIAU_AVEC_PERTE), copy.deepcopy(MATERIAU_SANS_PERTE)])
    avant = copy.deepcopy(bareme)
    besoins_materiaux.calculer_lignes(bareme, "ravalement", 1200)
    assert bareme == avant


def test_meme_entree_meme_resultat():
    assert _lignes([MATERIAU_AVEC_PERTE]) == _lignes([MATERIAU_AVEC_PERTE])


# ------------------------------------------------------------------- calculer_lignes : refus nommés
@pytest.mark.parametrize("materiaux", [[], "texte", {"materiau": "M"}, 3, None])
def test_bloc_materiaux_qui_nest_pas_une_liste_non_vide_est_refuse(materiaux):
    bareme = _bareme(None)
    bareme["postes"]["ravalement"]["materiaux"] = materiaux
    _refuse(bareme=bareme)


@pytest.mark.parametrize("entree", ["M", 3, None, ["M"]])
def test_entree_qui_nest_pas_un_objet_est_refusee(entree):
    _refuse([entree])


def test_cle_requise_manquante_est_nommee_dans_le_rejet():
    for cle in ("materiau", "quantite_par_unite", "unite"):
        entree = {k: v for k, v in MATERIAU_SANS_PERTE.items() if k != cle}
        assert cle in _refuse([entree])["detail"]


def test_cle_inconnue_est_refusee_dont_un_prix():
    verdict = _refuse([{**MATERIAU_SANS_PERTE, "prix_unitaire": "12.00"}])
    assert "prix_unitaire" in verdict["detail"]


@pytest.mark.parametrize("champ", ["materiau", "unite", "sku"])
@pytest.mark.parametrize("valeur", ["", "   ", None, 3, ["x"]])
def test_texte_obligatoire_vide_ou_non_texte_est_refuse(champ, valeur):
    _refuse([{**MATERIAU_AVEC_PERTE, champ: valeur}])


@pytest.mark.parametrize(
    "valeur",
    [
        0.5,          # nombre JSON : la précision de lecture varie d'un consommateur à l'autre
        3,
        "0",          # strictement positif
        "-1",
        "+1",
        "1e3",        # pas d'exposant
        " 1",
        "1 ",
        "1_0",
        "1,5",
        ".5",
        "5.",
        "٣",          # chiffre non ASCII que Decimal() accepterait
        "NaN",
        "Infinity",
        "",
        None,
        True,
        "1" * 41,     # longueur bornée
    ],
)
def test_quantite_par_unite_doit_etre_un_texte_decimal_ascii_strictement_positif(valeur):
    _refuse([{**MATERIAU_SANS_PERTE, "quantite_par_unite": valeur}])


@pytest.mark.parametrize("valeur", ["1", "1.0", "10", "1.5", "-0.1", "0.1e1", "abc", "", 0.1, 0, None, True])
def test_facteur_perte_fourni_doit_etre_une_fraction_decimale_sous_un(valeur):
    verdict = _refuse([{**MATERIAU_SANS_PERTE, "facteur_perte": valeur}])
    assert "facteur_perte" in verdict["detail"]


def test_facteur_perte_de_dix_au_lieu_de_zero_dix_est_refuse_explicitement():
    # Un pourcentage écrit en entier ferait commander onze fois la quantité nette.
    assert "10 %" in _refuse([{**MATERIAU_SANS_PERTE, "facteur_perte": "10"}])["detail"]


def test_materiau_en_double_est_refuse_au_lieu_dagreger_en_silence():
    _refuse([MATERIAU_SANS_PERTE, dict(MATERIAU_SANS_PERTE)])


def test_sku_en_double_est_refuse():
    _refuse(
        [
            {**MATERIAU_AVEC_PERTE, "materiau": "Vinyle A"},
            {**MATERIAU_AVEC_PERTE, "materiau": "Vinyle B"},
        ]
    )


def test_le_sku_dune_ligne_ne_peut_pas_etre_la_designation_dune_autre():
    # Même identité pour M6 (sku, sinon désignation) : ce serait deux lignes pour un seul matériau.
    _refuse(
        [
            {**MATERIAU_AVEC_PERTE, "sku": "SKU-1", "materiau": "Vinyle"},
            {"materiau": "SKU-1", "quantite_par_unite": "1", "unite": "u"},
        ]
    )


@pytest.mark.parametrize("quantite", [0, -1, -0.5, float("nan"), float("inf"), "12", None, True, [1]])
def test_quantite_de_louvrage_inexploitable_est_un_rejet_nomme(quantite):
    _refuse([MATERIAU_SANS_PERTE], quantite=quantite)


def test_un_produit_qui_ne_tiendrait_pas_exactement_est_refuse_au_lieu_detre_tronque():
    # 30 chiffres x 39 chiffres : 69 chiffres significatifs, au-delà des 60 du contexte exact.
    grand = "9" * 20 + "." + "9" * 19
    _refuse(
        [{"materiau": "M", "quantite_par_unite": grand, "unite": "u"}],
        quantite=Decimal("9" * 30),
    )


# ------------------------------------------------------------- valider_besoins_materiaux : nominal
def test_contrat_nominal_est_valide_et_rendu_tel_quel():
    contrat = _contrat()
    valide, verdict = besoins_materiaux.valider_besoins_materiaux(contrat)
    assert verdict is None
    assert valide == contrat


def test_contrat_sans_aucune_perte_absente_est_valide_avec_liste_vide():
    contrat = _contrat(
        lignes=[_contrat()["lignes"][0]],
        facteurs_perte_absents=[],
    )
    assert besoins_materiaux.valider_besoins_materiaux(contrat)[1] is None


def test_les_cles_du_contrat_sont_exactement_celles_annoncees():
    assert set(_contrat()) == set(besoins_materiaux.CHAMPS_BESOINS_MATERIAUX_V1)
    assert len(besoins_materiaux.CHAMPS_BESOINS_MATERIAUX_V1) == len(set(besoins_materiaux.CHAMPS_BESOINS_MATERIAUX_V1))


# --------------------------------------------------------- valider_besoins_materiaux : refus nommés
@pytest.mark.parametrize("charge", [None, [], "texte", 3])
def test_contrat_qui_nest_pas_un_objet_est_refuse(charge):
    _refuse_contrat(charge)


def test_cle_manquante_ou_inconnue_est_refusee():
    for cle in besoins_materiaux.CHAMPS_BESOINS_MATERIAUX_V1:
        contrat = _contrat()
        del contrat[cle]
        assert cle in _refuse_contrat(contrat)["detail"]
    assert "surprise" in _refuse_contrat(_contrat(surprise=1))["detail"]


@pytest.mark.parametrize(
    "cle",
    [
        "prix_unitaire", "prix_total", "prix_recommande", "cout_unitaire", "cout_total", "montant",
        "marge", "taux_marge", "intervalle_confiance", "borne_basse", "plancher_rentable",
        "date_execution", "creneau", "duree",
    ],
)
def test_aucune_cle_de_prix_de_cout_ou_de_date_nest_admise_au_premier_niveau(cle):
    verdict = _refuse_contrat(_contrat(**{cle: "1.00"}))
    assert cle in verdict["detail"]
    assert "ni prix, ni coût" in verdict["detail"]


def test_une_cle_de_prix_dans_une_ligne_est_refusee_a_toute_profondeur():
    contrat = _contrat()
    contrat["lignes"][0]["prix_unitaire"] = "12.00"
    assert "prix_unitaire" in _refuse_contrat(contrat)["detail"]


def test_la_casse_et_les_espaces_ne_contournent_pas_linterdiction():
    contrat = _contrat()
    contrat["lignes"][1][" Cout_Unitaire "] = "8.00"
    assert "Cout_Unitaire" in _refuse_contrat(contrat)["detail"]


@pytest.mark.parametrize("champ", ["devis_id", "lead_id", "bareme_version"])
@pytest.mark.parametrize("valeur", ["", "  ", None, 3, ["x"]])
def test_identifiant_texte_vide_ou_non_texte_est_refuse(champ, valeur):
    _refuse_contrat(_contrat(**{champ: valeur}))


@pytest.mark.parametrize("valeur", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, None, 3, HASH_A + "\n"])
def test_estimation_id_doit_etre_une_empreinte_sha256_en_minuscules(valeur):
    _refuse_contrat(_contrat(estimation_id=valeur))


@pytest.mark.parametrize("valeur", [-1, 1.5, "0", None, True, False])
def test_rang_registre_doit_etre_un_entier_non_negatif(valeur):
    _refuse_contrat(_contrat(rang_registre=valeur))


@pytest.mark.parametrize("valeur", [0, 1, -0.1, 1.01, 2, "0.9", None, True, [0.9]])
def test_niveau_confiance_doit_etre_un_nombre_strictement_entre_zero_et_un(valeur):
    _refuse_contrat(_contrat(niveau_confiance=valeur))


def test_niveau_confiance_reprend_la_forme_du_code_pas_la_chaine_du_prd():
    # Question ouverte (PLAN T2.3) : le code porte un nombre, le PRD une chaîne. Le contrat suit
    # le code ; la chaîne du PRD est donc refusée, jamais silencieusement acceptée.
    _refuse_contrat(_contrat(niveau_confiance="MULTI_VUES"))
    assert besoins_materiaux.valider_besoins_materiaux(_contrat(niveau_confiance=0.95))[1] is None


@pytest.mark.parametrize("lignes", [[], None, "texte", {"materiau": "M"}, 3])
def test_lignes_doit_etre_une_liste_non_vide(lignes):
    _refuse_contrat(_contrat(lignes=lignes, facteurs_perte_absents=[]))


@pytest.mark.parametrize("ligne", ["M", 3, None, [], {}, {"materiau": "M"}, {"materiau": "M", "unite": "u"}])
def test_ligne_mal_formee_est_refusee(ligne):
    _refuse_contrat(_contrat(lignes=[ligne], facteurs_perte_absents=[]))


def test_ligne_avec_cle_inconnue_est_refusee():
    contrat = _contrat()
    contrat["lignes"][0]["couleur"] = "blanc"
    assert "lignes[0]" in _refuse_contrat(contrat)["detail"]


@pytest.mark.parametrize("champ", ["materiau", "unite", "sku"])
@pytest.mark.parametrize("valeur", ["", "  ", None, 3])
def test_texte_de_ligne_vide_ou_non_texte_est_refuse(champ, valeur):
    contrat = _contrat()
    contrat["lignes"][0][champ] = valeur
    if champ == "materiau":
        contrat["facteurs_perte_absents"] = ["Clous (fictif)"]
    _refuse_contrat(contrat)


@pytest.mark.parametrize(
    "valeur", ["0", "0.0", "-1", "1e3", " 1", "1.", ".5", "٣", "NaN", "", 13.32, 13, None, True, "1" * 41]
)
def test_quantite_estimee_doit_etre_un_texte_decimal_strictement_positif(valeur):
    contrat = _contrat()
    contrat["lignes"][0]["quantite_estimee"] = valeur
    assert "quantite_estimee" in _refuse_contrat(contrat)["detail"]


@pytest.mark.parametrize("valeur", ["1", "1.0", "2", "-0.1", "1e-1", "", 0.1, None, True])
def test_facteur_perte_de_ligne_doit_etre_une_fraction_sous_un(valeur):
    contrat = _contrat()
    contrat["lignes"][0]["facteur_perte"] = valeur
    assert "facteur_perte" in _refuse_contrat(contrat)["detail"]


def test_deux_lignes_du_meme_materiau_sont_refusees():
    contrat = _contrat()
    contrat["lignes"].append(dict(contrat["lignes"][1]))
    contrat["facteurs_perte_absents"] = ["Clous (fictif)", "Clous (fictif)"]
    assert "en double" in _refuse_contrat(contrat)["detail"]


def test_deux_lignes_du_meme_sku_sont_refusees():
    contrat = _contrat()
    contrat["lignes"].append({**contrat["lignes"][0], "materiau": "Autre libellé"})
    assert "en double" in _refuse_contrat(contrat)["detail"]


def test_absence_de_perte_non_signalee_est_refusee():
    _refuse_contrat(_contrat(facteurs_perte_absents=[]))


def test_signal_de_perte_pour_une_ligne_qui_en_porte_un_est_refuse():
    _refuse_contrat(_contrat(facteurs_perte_absents=["Clous (fictif)", "Revêtement vinyle (fictif)"]))


def test_signal_de_perte_dans_un_autre_ordre_est_refuse():
    contrat = _contrat()
    contrat["lignes"] = [contrat["lignes"][1], contrat["lignes"][0]]
    contrat["lignes"].append({"materiau": "Vis (fictif)", "quantite_estimee": "2", "unite": "boite"})
    contrat["facteurs_perte_absents"] = ["Vis (fictif)", "Clous (fictif)"]
    _refuse_contrat(contrat)


@pytest.mark.parametrize("valeur", [None, "Clous (fictif)", [3], ["Clous (fictif)", None]])
def test_facteurs_perte_absents_doit_etre_une_liste_de_textes(valeur):
    _refuse_contrat(_contrat(facteurs_perte_absents=valeur))


# ----------------------------------------------------------------------- assembler_besoins_materiaux
def test_assemblage_rend_un_contrat_valide_et_independant_des_entrees_de_lappelant():
    resultat = _lignes([MATERIAU_AVEC_PERTE, MATERIAU_SANS_PERTE])
    contrat, verdict = besoins_materiaux.assembler_besoins_materiaux(
        "M3-DEVIS-0123456789abcdef", "lead-fictif-001", HASH_A, 3, "2026.1", 0.9,
        resultat["lignes"], resultat["facteurs_perte_absents"],
    )
    assert verdict is None
    assert tuple(contrat) == besoins_materiaux.CHAMPS_BESOINS_MATERIAUX_V1
    contrat["lignes"][0]["quantite_estimee"] = "999"
    contrat["facteurs_perte_absents"].append("x")
    assert resultat["lignes"][0]["quantite_estimee"] == "13.32"
    assert resultat["facteurs_perte_absents"] == ["Clous (fictif)"]


def test_assemblage_refuse_une_entree_invalide_sans_exception():
    contrat, verdict = besoins_materiaux.assembler_besoins_materiaux(
        "", "lead", HASH_A, 0, "2026.1", 0.9, "pas une liste", "pas une liste"
    )
    assert contrat is None
    assert verdict["code"] == "REJ-BESOINS-MATERIAUX-INVALIDE"


# ---------------------------------------------------------------------------- identifiant_evenement
def test_identifiant_evenement_est_deterministe_par_devis_et_version():
    contrat = _contrat()
    identifiant = besoins_materiaux.identifiant_evenement(contrat)
    assert identifiant == "m3-besoins-materiaux-M3-DEVIS-0123456789abcdef-" + "a" * 16
    assert besoins_materiaux.identifiant_evenement(copy.deepcopy(contrat)) == identifiant
    assert besoins_materiaux.identifiant_evenement(_contrat(estimation_id=HASH_B)) != identifiant
    assert besoins_materiaux.identifiant_evenement(_contrat(devis_id="M3-DEVIS-autre")) != identifiant
    assert len(identifiant) < 128, "colonne evenement_id : 128 signes"


# ------------------------------------------------------------------------------------ le catalogue
def test_le_code_du_contrat_est_au_catalogue_et_exerce_par_ce_fichier():
    codes = {code for code in verdicts.CODES_M3_LIST if code.startswith("REJ-BESOINS-MATERIAUX-")}
    assert codes == {"REJ-BESOINS-MATERIAUX-INVALIDE"}
    # Les deux voies de rejet (bloc du barème, contrat de sortie) rendent ce code, avec un détail.
    assert _refuse([])["code"] in codes
    assert _refuse_contrat(None)["code"] in codes
    assert verdicts.est_verdict("REJ-BESOINS-MATERIAUX-INVALIDE")
