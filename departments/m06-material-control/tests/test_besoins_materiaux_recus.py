"""Validation du RÉCEPTEUR du contrat `BesoinsMateriauxM3` (PLAN T2.3-e), indépendante de celle de
l'émetteur : M6 ne fait pas confiance au contrat parce qu'il vient de M3.

Chaque code de rejet du module est exercé ici, la première faute gagne dans un ordre épinglé,
aucune exception ne s'échappe d'une entrée hostile, et aucun prix ni coût n'est accepté. Fixtures
fictives.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
from m6_material_control import besoins_materiaux_recus as recus

HASH_A = "a" * 64


def _ligne_avec_perte():
    return {
        "materiau": "Revêtement vinyle (fictif)", "sku": "SKU-FICTIF-VINYLE",
        "quantite_estimee": "13.32", "unite": "carton", "facteur_perte": "0.10",
    }


def _ligne_sans_perte():
    return {"materiau": "Clous (fictif)", "quantite_estimee": "600", "unite": "boite"}


def _charge(**surcharges):
    charge = {
        "devis_id": "M3-DEVIS-0123456789abcdef",
        "lead_id": "lead-fictif-001",
        "estimation_id": HASH_A,
        "rang_registre": 0,
        "bareme_version": "2026.1",
        "niveau_confiance": 0.9,
        "lignes": [_ligne_avec_perte(), _ligne_sans_perte()],
        "facteurs_perte_absents": ["Clous (fictif)"],
    }
    charge.update(surcharges)
    return charge


def _code(charge):
    ok, code = recus.valider(charge)
    assert ok is False
    assert code is not None and code.startswith("REJ-BESOINS-MATERIAUX-")
    return code


# ------------------------------------------------------------------------------------------ nominal
def test_contrat_nominal_est_accepte():
    assert recus.valider(_charge()) == (True, None)


def test_contrat_sans_aucune_perte_absente_est_accepte_avec_liste_vide():
    assert recus.valider(_charge(lignes=[_ligne_avec_perte()], facteurs_perte_absents=[])) == (True, None)


def test_validation_ne_modifie_pas_le_contrat():
    charge = _charge()
    avant = copy.deepcopy(charge)
    recus.valider(charge)
    assert charge == avant


def test_niveau_confiance_strictement_entre_zero_et_un_est_admissible():
    assert recus.valider(_charge(niveau_confiance=0.95)) == (True, None)


# ---------------------------------------------------------------------------- STRUCTURE-INVALIDE
@pytest.mark.parametrize("charge", [None, [], "texte", 3, ()])
def test_ce_qui_nest_pas_un_objet_est_refuse(charge):
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-STRUCTURE-INVALIDE"


def test_cle_manquante_est_refusee():
    for cle in recus.CHAMPS_BESOINS_MATERIAUX_RECUS:
        charge = _charge()
        del charge[cle]
        assert _code(charge) == "REJ-BESOINS-MATERIAUX-STRUCTURE-INVALIDE", cle


def test_cle_inconnue_est_refusee():
    assert _code(_charge(surprise=1)) == "REJ-BESOINS-MATERIAUX-STRUCTURE-INVALIDE"


# ------------------------------------------------------------------------------- FRONTIERE-VIOLEE
@pytest.mark.parametrize(
    "cle",
    [
        "prix_unitaire", "prix_total", "prix_recommande", "cout_unitaire", "cout_total", "montant",
        "marge", "taux_marge", "intervalle_confiance", "borne_basse", "borne_haute", "plancher_rentable",
        "prix_vente", "date_execution", "creneau", "duree", "statut_paiement",
    ],
)
def test_aucun_prix_cout_ni_date_nest_accepte_au_premier_niveau(cle):
    assert _code(_charge(**{cle: "1.00"})) == "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE"


@pytest.mark.parametrize("cle", ["prix_unitaire", "prix_ligne", "cout_unitaire", "cout_ligne", "montant"])
def test_aucun_prix_ni_cout_nest_accepte_dans_une_ligne(cle):
    charge = _charge()
    charge["lignes"][0][cle] = "12.00"
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE"


def test_la_frontiere_passe_avant_la_structure_meme_sur_un_contrat_par_ailleurs_incomplet():
    assert _code({"prix_total": "1.00"}) == "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE"


def test_casse_et_espaces_ne_contournent_pas_la_frontiere():
    charge = _charge()
    charge["lignes"][1][" Prix_Unitaire "] = "3.00"
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE"


def test_un_prix_cache_dans_une_liste_imbriquee_est_trouve():
    charge = _charge()
    charge["lignes"].append([{"profond": {"cout_total": "1"}}])
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE"


# ------------------------------------------------------------------------ IDENTIFIANT-INVALIDE
@pytest.mark.parametrize("champ", ["devis_id", "lead_id", "bareme_version"])
@pytest.mark.parametrize("valeur", ["", "  ", None, 3, ["x"]])
def test_identifiant_texte_vide_ou_non_texte_est_refuse(champ, valeur):
    assert _code(_charge(**{champ: valeur})) == "REJ-BESOINS-MATERIAUX-IDENTIFIANT-INVALIDE"


@pytest.mark.parametrize("valeur", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, None, 3, HASH_A + "\n"])
def test_estimation_id_doit_etre_une_empreinte_sha256_en_minuscules(valeur):
    assert _code(_charge(estimation_id=valeur)) == "REJ-BESOINS-MATERIAUX-IDENTIFIANT-INVALIDE"


@pytest.mark.parametrize("valeur", [-1, 1.5, "0", None, True, False])
def test_rang_registre_doit_etre_un_entier_non_negatif(valeur):
    assert _code(_charge(rang_registre=valeur)) == "REJ-BESOINS-MATERIAUX-IDENTIFIANT-INVALIDE"


# --------------------------------------------------------------------------- CONFIANCE-INVALIDE
@pytest.mark.parametrize("valeur", [0, 1, -0.1, 1.01, 2, "0.9", "MULTI_VUES", None, True, [0.9]])
def test_niveau_confiance_doit_etre_un_nombre_strictement_entre_zero_et_un(valeur):
    assert _code(_charge(niveau_confiance=valeur)) == "REJ-BESOINS-MATERIAUX-CONFIANCE-INVALIDE"


def test_niveau_confiance_nan_est_refuse():
    assert _code(_charge(niveau_confiance=float("nan"))) == "REJ-BESOINS-MATERIAUX-CONFIANCE-INVALIDE"


# ------------------------------------------------------------------------------ LIGNES-VIDES
@pytest.mark.parametrize("lignes", [[], None, "texte", {"materiau": "M"}, 3])
def test_lignes_doit_etre_une_liste_non_vide(lignes):
    assert _code(_charge(lignes=lignes, facteurs_perte_absents=[])) == "REJ-BESOINS-MATERIAUX-LIGNES-VIDES"


# ---------------------------------------------------------------------------- LIGNE-INVALIDE
@pytest.mark.parametrize("ligne", ["M", 3, None, [], {}, {"materiau": "M"}, {"materiau": "M", "unite": "u"}])
def test_ligne_mal_formee_est_refusee(ligne):
    assert _code(_charge(lignes=[ligne], facteurs_perte_absents=[])) == "REJ-BESOINS-MATERIAUX-LIGNE-INVALIDE"


def test_ligne_avec_cle_inconnue_est_refusee():
    charge = _charge()
    charge["lignes"][0]["couleur"] = "blanc"
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-LIGNE-INVALIDE"


@pytest.mark.parametrize("champ", ["materiau", "unite", "sku"])
@pytest.mark.parametrize("valeur", ["", "  ", None, 3])
def test_texte_de_ligne_vide_ou_non_texte_est_refuse(champ, valeur):
    charge = _charge()
    charge["lignes"][0][champ] = valeur
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-LIGNE-INVALIDE"


# ------------------------------------------------------------------------- QUANTITE-INVALIDE
@pytest.mark.parametrize(
    "valeur",
    ["0", "0.0", "-1", "+1", "1e3", " 1", "1 ", "1_0", "1,5", "1.", ".5", "٣", "NaN", "Infinity", "",
     13.32, 13, None, True, "1" * 41],
)
def test_quantite_estimee_doit_etre_un_texte_decimal_ascii_strictement_positif(valeur):
    charge = _charge()
    charge["lignes"][0]["quantite_estimee"] = valeur
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-QUANTITE-INVALIDE"


# --------------------------------------------------------------------- FACTEUR-PERTE-INVALIDE
@pytest.mark.parametrize("valeur", ["1", "1.0", "2", "10", "-0.1", "1e-1", "abc", "", 0.1, 0, None, True])
def test_facteur_perte_doit_etre_une_fraction_decimale_sous_un(valeur):
    charge = _charge()
    charge["lignes"][0]["facteur_perte"] = valeur
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-FACTEUR-PERTE-INVALIDE"


def test_facteur_perte_zero_est_une_valeur_fournie_pas_une_absence():
    charge = _charge(lignes=[{**_ligne_sans_perte(), "facteur_perte": "0"}], facteurs_perte_absents=[])
    assert recus.valider(charge) == (True, None)


# ----------------------------------------------------------------------------------- DUPLIQUE
def test_deux_lignes_du_meme_materiau_sont_refusees_au_lieu_dagreger_en_silence():
    charge = _charge()
    charge["lignes"].append(_ligne_sans_perte())
    charge["facteurs_perte_absents"] = ["Clous (fictif)", "Clous (fictif)"]
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-DUPLIQUE"


def test_deux_lignes_du_meme_sku_sont_refusees():
    charge = _charge()
    charge["lignes"].append({**_ligne_avec_perte(), "materiau": "Autre désignation"})
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-DUPLIQUE"


def test_le_sku_dune_ligne_ne_peut_pas_etre_la_designation_dune_autre():
    charge = _charge(
        lignes=[
            {**_ligne_avec_perte(), "sku": "SKU-1", "materiau": "Vinyle"},
            {"materiau": "SKU-1", "quantite_estimee": "2", "unite": "u"},
        ],
        facteurs_perte_absents=["SKU-1"],
    )
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-DUPLIQUE"


# --------------------------------------------------------------------------- PERTE-NON-SIGNALEE
def test_une_perte_absente_mais_non_signalee_est_refusee():
    assert _code(_charge(facteurs_perte_absents=[])) == "REJ-BESOINS-MATERIAUX-PERTE-NON-SIGNALEE"


def test_un_signal_pour_une_ligne_qui_porte_un_facteur_est_refuse():
    charge = _charge(facteurs_perte_absents=["Clous (fictif)", "Revêtement vinyle (fictif)"])
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-PERTE-NON-SIGNALEE"


def test_un_signal_dans_un_autre_ordre_est_refuse():
    charge = _charge()
    charge["lignes"].append({"materiau": "Vis (fictif)", "quantite_estimee": "2", "unite": "boite"})
    charge["facteurs_perte_absents"] = ["Vis (fictif)", "Clous (fictif)"]
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-PERTE-NON-SIGNALEE"


@pytest.mark.parametrize("valeur", [None, "Clous (fictif)", [3], ["Clous (fictif)", None], ("Clous (fictif)",), {}])
def test_facteurs_perte_absents_doit_etre_la_liste_exacte_des_lignes_sans_facteur(valeur):
    assert _code(_charge(facteurs_perte_absents=valeur)) == "REJ-BESOINS-MATERIAUX-PERTE-NON-SIGNALEE"


# ---------------------------------------------------------------- ordre de la première faute
def test_la_premiere_faute_gagne_dans_un_ordre_epingle():
    charge = _charge(devis_id="", niveau_confiance=7, lignes=[])
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-IDENTIFIANT-INVALIDE"
    charge = _charge(niveau_confiance=7, lignes=[])
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-CONFIANCE-INVALIDE"
    charge = _charge(lignes=[{"materiau": "M", "quantite_estimee": "0", "unite": "u", "facteur_perte": "5"}],
                     facteurs_perte_absents=[])
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-QUANTITE-INVALIDE"


# ------------------------------------------------------------------ aucune exception ne s'échappe
@pytest.mark.parametrize(
    "hostile",
    [
        {"devis_id": object()},
        {cle: None for cle in recus.CHAMPS_BESOINS_MATERIAUX_RECUS},
        {cle: [] for cle in recus.CHAMPS_BESOINS_MATERIAUX_RECUS},
        {cle: {} for cle in recus.CHAMPS_BESOINS_MATERIAUX_RECUS},
        {1: "x"},
        {"lignes": [[[[]]]]},
    ],
)
def test_une_entree_hostile_est_un_refus_nomme_jamais_une_exception(hostile):
    ok, code = recus.valider(hostile)
    assert ok is False
    assert code.startswith("REJ-BESOINS-MATERIAUX-")


def test_une_cle_non_textuelle_dans_une_ligne_est_un_refus_nomme():
    charge = _charge()
    charge["lignes"][0][7] = "x"
    assert _code(charge) == "REJ-BESOINS-MATERIAUX-LIGNE-INVALIDE"


# ---------------------------------------------------------------------- dérivation du prévu
def test_identite_du_materiau_est_le_sku_quand_il_est_connu_sinon_la_designation():
    assert recus.identite_materiau(_ligne_avec_perte()) == "SKU-FICTIF-VINYLE"
    assert recus.identite_materiau(_ligne_sans_perte()) == "Clous (fictif)"


def test_lignes_prevues_au_format_interne_de_m6():
    assert recus.lignes_prevues(_charge()) == [
        {"materiau_id": "SKU-FICTIF-VINYLE", "quantite_estimee": 13.32, "unite": "carton"},
        {"materiau_id": "Clous (fictif)", "quantite_estimee": 600.0, "unite": "boite"},
    ]


def test_lignes_detaillees_gardent_les_textes_exacts_et_le_facteur_de_perte():
    assert recus.lignes_detaillees(_charge()) == [
        {"materiau_id": "SKU-FICTIF-VINYLE", **_ligne_avec_perte()},
        {"materiau_id": "Clous (fictif)", **_ligne_sans_perte()},
    ]


def test_la_derivation_ne_partage_rien_de_mutable_avec_le_contrat():
    charge = _charge()
    detail = recus.lignes_detaillees(charge)
    detail[0]["quantite_estimee"] = "999"
    assert charge["lignes"][0]["quantite_estimee"] == "13.32"


# --------------------------------------------------------------- tous les codes sont exercés
def test_chaque_code_de_rejet_du_module_est_exerce_par_ce_fichier():
    source = (Path(recus.__file__)).read_text(encoding="utf-8")
    codes_du_module = set(re.findall(r'"(REJ-BESOINS-MATERIAUX-[A-Z-]+)"', source))
    exerces = {
        "REJ-BESOINS-MATERIAUX-STRUCTURE-INVALIDE": _code(None),
        "REJ-BESOINS-MATERIAUX-FRONTIERE-VIOLEE": _code(_charge(prix_total="1")),
        "REJ-BESOINS-MATERIAUX-IDENTIFIANT-INVALIDE": _code(_charge(devis_id="")),
        "REJ-BESOINS-MATERIAUX-CONFIANCE-INVALIDE": _code(_charge(niveau_confiance=2)),
        "REJ-BESOINS-MATERIAUX-LIGNES-VIDES": _code(_charge(lignes=[], facteurs_perte_absents=[])),
        "REJ-BESOINS-MATERIAUX-LIGNE-INVALIDE": _code(_charge(lignes=[3], facteurs_perte_absents=[])),
        "REJ-BESOINS-MATERIAUX-QUANTITE-INVALIDE": _code(
            _charge(lignes=[{**_ligne_sans_perte(), "quantite_estimee": "0"}])
        ),
        "REJ-BESOINS-MATERIAUX-FACTEUR-PERTE-INVALIDE": _code(
            _charge(lignes=[{**_ligne_sans_perte(), "facteur_perte": "1"}], facteurs_perte_absents=[])
        ),
        "REJ-BESOINS-MATERIAUX-DUPLIQUE": _code(
            _charge(lignes=[_ligne_sans_perte(), _ligne_sans_perte()], facteurs_perte_absents=["Clous (fictif)"] * 2)
        ),
        "REJ-BESOINS-MATERIAUX-PERTE-NON-SIGNALEE": _code(_charge(facteurs_perte_absents=[])),
    }
    assert codes_du_module == set(exerces)
    assert all(code == attendu for attendu, code in exerces.items())
