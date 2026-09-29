"""PLAN T4.15 (M6.16, pont finance vers M5) : la charge de `m6.reception_enregistree`, en pur.

`evenement_reception.py` construit la charge, `outils.py` la publie (voir
`test_evenements_reception_m6.py`, sur une base réelle). Ici : la conversion en texte décimal EXACTE des
quantités et des prix (jamais un nombre JSON, jamais la notation scientifique), ce qui est refusé AVANT
d'écrire, la charge nominale contre le schéma FERMÉ du catalogue du socle, et l'écart de prix (seuil et deux
prix connus, sinon `null`). Identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import copy
import math

import pytest
from m6_material_control import evenement_reception

from opsys import evenements
from opsys.evenements.schemas import erreurs_charge

FICTIF = True
HASH_A = "a" * 64
HASH_B = "b" * 64
HORODATAGE = "2026-09-29T09:15:00-04:00"


def _po(statut="partially_received"):
    return {
        "po_id": "PO-FICTIF-1",
        "chantier_id": "CH-FICTIF-1",
        "fournisseur_id": "gentek",
        "statut": statut,
        "lignes": [
            {"materiau_id": "gouttiere-5po", "quantite_demandee": 100.0, "verdict_prix": "PRIX_LIVRE",
             "prix_unitaire_prevu": 8.5, "devise_prevue": "CAD", "montant_ligne_prevu": 850.0},
            {"materiau_id": "vis-inox", "quantite_demandee": 20.0, "verdict_prix": "PRIX_LIVRE",
             "prix_unitaire_prevu": 0.35, "devise_prevue": "CAD", "montant_ligne_prevu": 7.0},
        ],
    }


def _accuse(verdict="RECEPTION_INFERIEURE", **surcharges):
    accuse = {
        "po_id": "PO-FICTIF-1",
        "chantier_id": "CH-FICTIF-1",
        "verdict_reception": verdict,
        "lignes": [
            {"materiau_id": "gouttiere-5po", "quantite_demandee": 100.0, "quantite_recue": 40.0, "ecart": -60.0,
             "verdict_resolution_prix": "PRIX_CATALOGUE", "cout_unitaire_resolu": 8.5, "montant_ligne": 340.0},
            {"materiau_id": "vis-inox", "quantite_demandee": 20.0, "quantite_recue": 0.0, "ecart": -20.0,
             "verdict_resolution_prix": "PRIX_CATALOGUE", "cout_unitaire_resolu": 0.35, "montant_ligne": 0.0},
        ],
        "montant_total_estime": 340.0,
        "bareme_version": "v1",
        "hash_maillon": HASH_A,
    }
    accuse.update(surcharges)
    return accuse


def _reception(horodatage=HORODATAGE):
    return {"po_id": "PO-FICTIF-1", "chantier_id": "CH-FICTIF-1", "horodatage": horodatage,
            "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": 40.0},
                              {"materiau_id": "vis-inox", "quantite_recue": 0.0}]}


def _charge(seuil=0.15, signaux=(), **surcharges):
    charge, verdict = evenement_reception.construire_charge(
        surcharges.pop("po", _po()), surcharges.pop("accuse", _accuse()), surcharges.pop("reception", _reception()),
        seuil, list(signaux))
    assert verdict is None, verdict
    return charge


# -- texte_decimal : la frontière float -> texte -------------------------------------------------------------
@pytest.mark.parametrize("valeur, attendu", [
    (20.0, "20.0"), (8.5, "8.5"), (0.35, "0.35"), (40, "40"), (0.1, "0.1"), (0.0, "0.0"),
    (1e-07, "0.0000001"), (1e16, "10000000000000000"), (123456789.125, "123456789.125"),
    (-2.5, "-2.5"),
])
def test_texte_decimal_est_exact_et_positionnel(valeur, attendu):
    assert evenement_reception.texte_decimal(valeur) == attendu


def test_texte_decimal_n_importe_pas_l_imprecision_binaire_du_float():
    """`Decimal(0.1)` vaudrait 0.1000000000000000055... ; `Decimal(str(0.1))` vaut 0.1."""
    assert evenement_reception.texte_decimal(0.1) == "0.1"
    assert evenement_reception.texte_decimal(0.1 + 0.2) == "0.30000000000000004"  # le float lui-même, pas pire


def test_un_zero_negatif_s_ecrit_sans_signe():
    """-0.0 s'écrirait « -0.0 », que le schéma refuse : un zéro n'a pas de signe."""
    assert evenement_reception.texte_decimal(-0.0) == "0.0"


@pytest.mark.parametrize("valeur", [True, False, None, "40", math.nan, math.inf, -math.inf, [1], {"a": 1}])
def test_texte_decimal_refuse_ce_qui_n_est_pas_un_nombre_fini(valeur):
    assert evenement_reception.texte_decimal(valeur) is None


# -- verifier_reception : refusé AVANT d'écrire ------------------------------------------------------------
def test_une_reception_normale_est_publiable_zero_compris():
    assert evenement_reception.verifier_reception(_reception()) is None  # la ligne à 0 : pas encore livrée


@pytest.mark.parametrize("quantite", [-1.0, -0.001, math.nan, math.inf, -math.inf, True, "40", None, [40]])
def test_une_quantite_recue_invalide_est_refusee(quantite):
    reception = _reception()
    reception["lignes_recues"][0]["quantite_recue"] = quantite

    verdict = evenement_reception.verifier_reception(reception)

    assert verdict["code"] == "REJ-RECEPTION-QUANTITE-INVALIDE"
    assert "ligne 0" in verdict["detail"]


@pytest.mark.parametrize("horodatage", ["2026-09-29", "2026-09-29T09:15:00", "hier", "", 20260929, None,
                                         "2026-09-29 09:15:00-04:00"])
def test_un_horodatage_sans_fuseau_ou_illisible_est_refuse(horodatage):
    verdict = evenement_reception.verifier_reception(_reception(horodatage=horodatage))

    assert verdict["code"] == "REJ-RECEPTION-HORODATAGE-INVALIDE"


@pytest.mark.parametrize("horodatage", ["2026-09-29T09:15:00Z", "2026-09-29T09:15:00.250-04:00",
                                         "2026-01-06T00:00:00+00:00"])
def test_les_horodatages_rfc_3339_sont_acceptes(horodatage):
    assert evenement_reception.verifier_reception(_reception(horodatage=horodatage)) is None


@pytest.mark.parametrize("reception", [
    None, "texte", [], {"po_id": "PO"},                                 # pas un objet complet
    {"horodatage": HORODATAGE, "lignes_recues": "pas une liste"},       # lignes de mauvaise forme
    {"horodatage": HORODATAGE, "lignes_recues": ["pas un objet", {"materiau_id": "x"}]},  # ligne sans quantité
])
def test_une_forme_invalide_est_laissee_a_la_validation_existante(reception):
    """La forme d'une réception est jugée par `validation.valider_reception_po`, avec ses propres codes : ici
    aucun verdict, pour ne pas en masquer un autre."""
    assert evenement_reception.verifier_reception(reception) is None


# -- evenement_id : déterministe ---------------------------------------------------------------------------
def test_evenement_id_est_deterministe_et_distingue_deux_livraisons_du_meme_po():
    premier = evenement_reception.evenement_id("PO-1", HASH_A)
    assert premier == evenement_reception.evenement_id("PO-1", HASH_A) == "m6-reception-PO-1-" + "a" * 16
    assert premier != evenement_reception.evenement_id("PO-1", HASH_B), "deux livraisons, deux identifiants"
    assert premier != evenement_reception.evenement_id("PO-2", HASH_A), "deux PO, deux identifiants"


# -- construire_charge : nominal, contre le schéma FERMÉ du socle ------------------------------------------
def test_la_charge_nominale_est_conforme_au_catalogue_et_porte_du_texte_decimal():
    charge = _charge()

    assert erreurs_charge("m6.reception_enregistree", charge) == []
    assert charge["evenement_id"] == "m6-reception-PO-FICTIF-1-" + "a" * 16
    assert (charge["po_id"], charge["fournisseur_id"], charge["chantier_id"]) == (
        "PO-FICTIF-1", "gentek", "CH-FICTIF-1")
    assert charge["horodatage_reception"] == HORODATAGE, "repris tel quel : M6 n'a pas d'horloge"
    assert (charge["verdict_reception"], charge["statut_po"]) == ("RECEPTION_INFERIEURE", "partially_received")
    assert charge["hash_maillon"] == HASH_A and charge["seuil_ecart_prix_pourcentage"] == 0.15
    gouttiere, vis = charge["lignes"]
    assert gouttiere == {
        "materiau_id": "gouttiere-5po", "quantite_demandee": "100.0", "quantite_recue": "40.0",
        "prix_unitaire_prevu": "8.5", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
        "prix_unitaire_reception": "8.5", "verdict_prix_reception": "PRIX_CATALOGUE", "ecart_prix_critique": False,
    }
    assert vis["quantite_recue"] == "0.0", "une ligne pas encore livrée reste dans la charge, à zéro"


def test_aucune_valeur_de_la_charge_n_est_un_nombre_json_sauf_le_seuil():
    """Quantités et prix : du TEXTE. Le seul nombre est le seuil de configuration, qui n'est pas de l'argent."""
    charge = _charge()

    def nombres(valeur, chemin=""):
        if isinstance(valeur, bool) or valeur is None or isinstance(valeur, str):
            return []
        if isinstance(valeur, (int, float)):
            return [chemin]
        if isinstance(valeur, dict):
            return [n for cle, v in valeur.items() for n in nombres(v, f"{chemin}.{cle}")]
        return [n for i, v in enumerate(valeur) for n in nombres(v, f"{chemin}[{i}]")]

    assert nombres(charge) == [".seuil_ecart_prix_pourcentage"]


def test_la_charge_ne_porte_aucun_montant_calcule():
    """P13 : M5 est la source de vérité de l'argent. M6 ne dit ni montant de ligne, ni total, ni taxe."""
    charge = _charge()
    cles = set(charge) | {cle for ligne in charge["lignes"] for cle in ligne}

    assert not {cle for cle in cles if "montant" in cle or "total" in cle or "taxe" in cle}


def test_le_schema_est_ferme_une_cle_de_plus_est_refusee():
    charge = _charge()
    charge["montant_total_estime"] = "340.00"

    assert erreurs_charge("m6.reception_enregistree", charge)
    ligne_en_trop = _charge()
    ligne_en_trop["lignes"][0]["montant_ligne"] = "340.00"
    assert erreurs_charge("m6.reception_enregistree", ligne_en_trop)


@pytest.mark.parametrize("chemin, valeur", [
    (("lignes", 0, "quantite_recue"), 40.0),          # un nombre JSON au lieu du texte
    (("lignes", 0, "quantite_recue"), "-1"),          # négative
    (("lignes", 0, "quantite_recue"), "1e-07"),       # notation scientifique
    (("lignes", 0, "prix_unitaire_prevu"), 8.5),      # un prix en nombre
    (("lignes", 0, "prix_unitaire_reception"), "-8.5"),
    (("horodatage_reception"), "2026-09-29"),         # sans heure ni fuseau
    (("verdict_reception"), "INDETERMINE"),           # rien reçu : jamais publié
    (("statut_po"), "approved"),                      # un PO non reçu
    (("hash_maillon"), "xyz"),
    (("lignes"), []),
])
def test_le_schema_refuse_ce_qui_n_est_pas_un_fait_publiable(chemin, valeur):
    charge = _charge()
    cible = charge
    chemin = chemin if isinstance(chemin, tuple) else (chemin,)
    for cle in chemin[:-1]:
        cible = cible[cle]
    cible[chemin[-1]] = valeur

    assert erreurs_charge("m6.reception_enregistree", charge), f"{chemin} = {valeur!r} aurait dû être refusé"


@pytest.mark.parametrize("cle", ["evenement_id", "po_id", "fournisseur_id", "chantier_id", "horodatage_reception",
                                  "verdict_reception", "statut_po", "hash_maillon",
                                  "seuil_ecart_prix_pourcentage", "lignes"])
def test_toutes_les_proprietes_sont_requises_meme_nulles(cle):
    charge = _charge()
    del charge[cle]

    assert erreurs_charge("m6.reception_enregistree", charge)


def test_publier_une_charge_invalide_leve_et_n_ecrit_rien(tmp_path, monkeypatch):
    from opsys import stockage

    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        charge = _charge()
        charge["lignes"][0]["quantite_recue"] = 40.0
        with pytest.raises(evenements.ChargeInvalide), stockage.transaction():
            evenements.publier("m6.reception_enregistree", "m06-material-control", charge)
        assert evenements.deja_publie(charge["evenement_id"]) is False
    finally:
        stockage.liberer()


# -- ce qui n'est PAS publié -------------------------------------------------------------------------------
def test_une_reception_indeterminee_ne_publie_rien_et_n_est_pas_une_erreur():
    accuse = _accuse(verdict="INDETERMINE", lignes=[])

    charge, verdict = evenement_reception.construire_charge(_po(), accuse, _reception(), 0.15, [])

    assert (charge, verdict) == (None, None)


def test_un_verdict_ou_un_statut_inconnus_sont_un_refus_nomme():
    charge, verdict = evenement_reception.construire_charge(
        _po(), _accuse(verdict="VERDICT-INVENTE"), _reception(), 0.15, [])
    assert charge is None and verdict["code"] == "REJ-RECEPTION-EVENEMENT-INCOHERENT"

    charge, verdict = evenement_reception.construire_charge(_po(statut="approved"), _accuse(), _reception(), 0.15, [])
    assert charge is None and verdict["code"] == "REJ-RECEPTION-EVENEMENT-INCOHERENT"
    assert "approved" in verdict["detail"]


@pytest.mark.parametrize("hash_maillon", ["", "abc", "Z" * 64, "A" * 64, None, 12])
def test_un_hash_de_maillon_illisible_est_un_refus_nomme(hash_maillon):
    charge, verdict = evenement_reception.construire_charge(
        _po(), _accuse(hash_maillon=hash_maillon), _reception(), 0.15, [])

    assert charge is None and verdict["code"] == "REJ-RECEPTION-EVENEMENT-INCOHERENT"


def test_un_materiau_recu_absent_du_po_est_un_refus_nomme():
    accuse = _accuse()
    accuse["lignes"][1]["materiau_id"] = "materiau-fantome"

    charge, verdict = evenement_reception.construire_charge(_po(), accuse, _reception(), 0.15, [])

    assert charge is None and verdict["code"] == "REJ-RECEPTION-EVENEMENT-INCOHERENT"
    assert "materiau-fantome" in verdict["detail"]


# -- prix : jamais inventés --------------------------------------------------------------------------------
def test_un_prix_de_po_indetermine_reste_null_avec_sa_devise():
    po = _po()
    po["lignes"][1].update({"verdict_prix": "INDETERMINE", "prix_unitaire_prevu": None, "devise_prevue": None,
                            "montant_ligne_prevu": None})

    charge = _charge(po=po)

    vis = charge["lignes"][1]
    assert (vis["prix_unitaire_prevu"], vis["devise_prevue"], vis["verdict_prix_po"]) == (None, None, "INDETERMINE")
    assert vis["ecart_prix_critique"] is None, "pas de prix prévu : aucun écart n'est inventé"
    assert erreurs_charge("m6.reception_enregistree", charge) == []


@pytest.mark.parametrize("prix", [0.0, -3.0, math.nan, math.inf, True, "8.5", None])
def test_un_prix_de_reception_nul_negatif_ou_illisible_devient_inconnu(prix):
    accuse = _accuse()
    accuse["lignes"][0]["cout_unitaire_resolu"] = prix
    accuse["lignes"][0]["verdict_resolution_prix"] = "PRIX_CATALOGUE"

    charge = _charge(accuse=accuse)

    assert charge["lignes"][0]["prix_unitaire_reception"] is None
    assert charge["lignes"][0]["ecart_prix_critique"] is None
    assert erreurs_charge("m6.reception_enregistree", charge) == []


def test_le_prix_historique_de_repli_garde_son_verdict():
    accuse = _accuse()
    accuse["lignes"][0]["verdict_resolution_prix"] = "PRIX_HISTORIQUE_FALLBACK"

    charge = _charge(accuse=accuse)

    assert charge["lignes"][0]["verdict_prix_reception"] == "PRIX_HISTORIQUE_FALLBACK"


# -- écart de prix : seuil et deux prix connus, sinon null -------------------------------------------------
def test_ecart_de_prix_critique_vient_des_signaux_de_m6_pas_d_un_nouveau_calcul():
    accuse = _accuse()
    accuse["lignes"][0]["cout_unitaire_resolu"] = 10.5  # +23,5 % contre 8.5
    signaux = [{"po_id": "PO-FICTIF-1", "materiau_id": "gouttiere-5po", "prix_prevu": 8.5, "prix_reel": 10.5,
                "ecart_pourcentage": 0.2353}]

    charge = _charge(accuse=accuse, signaux=signaux)

    gouttiere, vis = charge["lignes"]
    assert gouttiere["ecart_prix_critique"] is True and gouttiere["prix_unitaire_reception"] == "10.5"
    assert vis["ecart_prix_critique"] is False, "deux prix connus, aucun signal : pas d'écart critique"


def test_sans_seuil_configure_aucune_ligne_n_est_evaluee():
    charge = _charge(seuil=None)

    assert charge["seuil_ecart_prix_pourcentage"] is None
    assert [ligne["ecart_prix_critique"] for ligne in charge["lignes"]] == [None, None]
    assert erreurs_charge("m6.reception_enregistree", charge) == []


def test_la_construction_ne_modifie_aucune_entree():
    po, accuse, reception = _po(), _accuse(), _reception()
    avant = copy.deepcopy((po, accuse, reception))

    evenement_reception.construire_charge(po, accuse, reception, 0.15, [])

    assert (po, accuse, reception) == avant


# -- longueur : quarante caractères au plus (le schéma le dit, M5 multiplie deux de ces textes) ------------
def test_un_nombre_dont_l_ecriture_depasse_quarante_caracteres_n_est_pas_publiable():
    assert evenement_reception.texte_decimal(10**39) == "1" + "0" * 39, "40 caractères : permis"
    assert evenement_reception.texte_decimal(10**40) is None, "41 caractères : refusé"
    # 1.2345678901234567e-30 s'écrirait sur une cinquantaine de caractères
    assert evenement_reception.texte_decimal(1.2345678901234567e-30) is None


def test_une_quantite_recue_trop_longue_est_refusee_avant_d_ecrire():
    reception = _reception()
    reception["lignes_recues"][0]["quantite_recue"] = 1.2345678901234567e-30

    verdict = evenement_reception.verifier_reception(reception)

    assert verdict["code"] == "REJ-RECEPTION-QUANTITE-INVALIDE" and "40" in verdict["detail"]


def test_une_quantite_commandee_illisible_est_un_refus_nomme_pas_une_erreur_de_schema():
    po = _po()
    accuse = _accuse()
    accuse["lignes"][0]["quantite_demandee"] = 1.2345678901234567e-30

    charge, verdict = evenement_reception.construire_charge(po, accuse, _reception(), 0.15, [])

    assert charge is None and verdict["code"] == "REJ-RECEPTION-EVENEMENT-INCOHERENT"
    assert "gouttiere-5po" in verdict["detail"]


def test_un_prix_trop_long_devient_inconnu():
    accuse = _accuse()
    accuse["lignes"][0]["cout_unitaire_resolu"] = 1.2345678901234567e-30

    charge = _charge(accuse=accuse)

    assert charge["lignes"][0]["prix_unitaire_reception"] is None
    assert erreurs_charge("m6.reception_enregistree", charge) == []


def test_le_schema_borne_les_textes_decimaux_a_quarante_caracteres():
    for cle in ("quantite_demandee", "quantite_recue", "prix_unitaire_prevu", "prix_unitaire_reception"):
        charge = _charge()
        charge["lignes"][0][cle] = "1" * 41

        assert erreurs_charge("m6.reception_enregistree", charge), cle
