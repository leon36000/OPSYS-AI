"""Tests du devis durable de M3 (PLAN T2.3-a, devis_durable.py). Registre EN MÉMOIRE (une liste
Python) dans tout ce fichier — le branchement sur le stockage durable réel est éprouvé séparément
par ``test_devis_durable_stockage.py`` (même partition que ``registre.py``/``test_registre.py`` vs
``test_registre_durable.py``)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable, verdicts

_HORODATAGE = "2026-09-28T14:00:00-04:00"

# Tous les codes REJ-DEVIS-* que ce fichier exerce — déclaration STATIQUE (même patron que
# test_validation_entrees.py::_CODES_EXERCES_PAR_CE_FICHIER), jamais accumulée dynamiquement à
# l'exécution : une liste statique reste vraie quel que soit l'ordre de collecte des tests.
_CODES_EXERCES_PAR_CE_FICHIER = {
    "REJ-DEVIS-DEVIS-ID-VIDE",
    "REJ-DEVIS-LEAD-ID-VIDE",
    "REJ-DEVIS-CHANTIER-ID-INVALIDE",
    "REJ-DEVIS-HORODATAGE-VIDE",
    "REJ-DEVIS-LIGNES-VIDES",
    "REJ-DEVIS-LIGNE-INVALIDE",
    "REJ-DEVIS-TAUX-MARGE-MANQUANT",
    "REJ-DEVIS-TAUX-MARGE-INVALIDE",
    "REJ-DEVIS-TOTAL-INCOHERENT",
    "REJ-DEVIS-ID-DEJA-UTILISE",
    "REJ-DEVIS-INTROUVABLE",
    "REJ-DEVIS-TRANSITION-ILLEGALE",
    "REJ-DEVIS-APPROBATEUR-ABSENT",
    "REJ-DEVIS-ROLE-INCONNU",
}


def _verdict_attendu(reponse, code):
    assert code in _CODES_EXERCES_PAR_CE_FICHIER, f"{code} absent de _CODES_EXERCES_PAR_CE_FICHIER"
    assert reponse[1] is not None, f"rejet {code} attendu, obtenu {reponse}"
    assert reponse[0] is None
    assert reponse[1]["code"] == code, reponse[1]
    return reponse[1]


def _ligne(**surcharges):
    ligne = {
        "description": "Gouttière alu 5 po",
        "quantite": "30",
        "unite": "pi_lin",
        "cout_unitaire": "10.00",
        "reference_besoin_materiau": "besoin-goutt-001",
    }
    ligne.update(surcharges)
    return ligne


def _creer(registre, **surcharges):
    args = {
        "devis_id": "M3-DEVIS-durable-001",
        "lead_id": "lead-001",
        "chantier_id": None,
        "lignes": [_ligne()],
        "taux_marge": "0.20",
        "horodatage": _HORODATAGE,
        "registre_cible": registre,
    }
    args.update(surcharges)
    return devis_durable.creer_devis(**args)


# -- formule de prix et de totaux, arrondis --------------------------------------------------
def test_prix_calcule_cout_fois_quantite_fois_un_plus_taux_marge():
    """cout_ligne = cout_unitaire * quantite ; prix_ligne = cout_ligne * (1 + taux_marge)."""
    registre = []
    devis, verdict = _creer(registre, lignes=[_ligne(cout_unitaire="10.00", quantite="30")], taux_marge="0.20")
    assert verdict is None
    ligne = devis["lignes"][0]
    assert ligne["cout_ligne"] == Decimal("300.00")  # 10.00 * 30
    assert ligne["prix_ligne"] == Decimal("360.00")  # 300.00 * 1.20
    assert devis["cout_total"] == Decimal("300.00")
    assert devis["prix_total"] == Decimal("360.00")
    assert devis["taux_marge"] == Decimal("0.20")


def test_totaux_sont_la_somme_exacte_des_lignes_deux_lignes():
    registre = []
    lignes = [
        _ligne(description="Gouttière", cout_unitaire="10.00", quantite="30"),
        _ligne(description="Descente pluviale", cout_unitaire="15.50", quantite="4", unite="unite"),
    ]
    devis, verdict = _creer(registre, lignes=lignes, taux_marge="0.25")
    assert verdict is None
    # ligne 1 : cout 300.00, prix 375.00 (x1.25) ; ligne 2 : cout 62.00, prix 77.50
    assert devis["lignes"][0]["cout_ligne"] == Decimal("300.00")
    assert devis["lignes"][0]["prix_ligne"] == Decimal("375.00")
    assert devis["lignes"][1]["cout_ligne"] == Decimal("62.00")
    assert devis["lignes"][1]["prix_ligne"] == Decimal("77.50")
    assert devis["cout_total"] == Decimal("362.00")
    assert devis["prix_total"] == Decimal("452.50")


def test_arrondi_round_half_up_au_cent_explicite_pas_le_defaut_round_half_even():
    """0.125 x 1 est un cas limite : ROUND_HALF_UP (choisi ici) arrondit à 0.13 ; le mode par
    défaut du module decimal (ROUND_HALF_EVEN) arrondirait à 0.12. Verrouille le choix documenté
    dans devis_durable.py."""
    registre = []
    devis, verdict = _creer(
        registre, lignes=[_ligne(cout_unitaire="0.125", quantite="1")], taux_marge="0"
    )
    assert verdict is None
    assert devis["lignes"][0]["cout_ligne"] == Decimal("0.13")
    assert Decimal("0.125").quantize(Decimal("0.01")) == Decimal("0.12")  # confirme le contraste


def test_taux_marge_zero_prix_egal_au_cout():
    registre = []
    devis, verdict = _creer(registre, taux_marge="0")
    assert verdict is None
    assert devis["prix_total"] == devis["cout_total"]


def test_montants_sont_des_decimal_jamais_des_float():
    registre = []
    devis, verdict = _creer(registre)
    assert verdict is None
    for ligne in devis["lignes"]:
        assert isinstance(ligne["cout_unitaire"], Decimal)
        assert isinstance(ligne["quantite"], Decimal)
        assert isinstance(ligne["cout_ligne"], Decimal)
        assert isinstance(ligne["prix_ligne"], Decimal)
    assert isinstance(devis["cout_total"], Decimal)
    assert isinstance(devis["prix_total"], Decimal)
    assert isinstance(devis["taux_marge"], Decimal)


# -- marge absente ou invalide : rejet fail-closed --------------------------------------------
def test_taux_marge_absent_rejete():
    registre = []
    verdict = _verdict_attendu(_creer(registre, taux_marge=None), "REJ-DEVIS-TAUX-MARGE-MANQUANT")
    assert "taux_marge" in verdict["detail"]
    assert registre == []  # rien n'est écrit sur rejet


def test_taux_marge_texte_non_decimal_rejete():
    _verdict_attendu(_creer([], taux_marge="trente pourcent"), "REJ-DEVIS-TAUX-MARGE-INVALIDE")


def test_taux_marge_float_json_rejete_jamais_de_float_accepte():
    _verdict_attendu(_creer([], taux_marge=0.2), "REJ-DEVIS-TAUX-MARGE-INVALIDE")


def test_taux_marge_moins_un_ou_moins_rejete_prix_non_positif():
    _verdict_attendu(_creer([], taux_marge="-1"), "REJ-DEVIS-TAUX-MARGE-INVALIDE")
    _verdict_attendu(_creer([], taux_marge="-2"), "REJ-DEVIS-TAUX-MARGE-INVALIDE")


# -- total incohérent : rejet ------------------------------------------------------------------
def test_prix_total_fourni_coherent_accepte():
    registre = []
    devis, verdict = _creer(registre, prix_total_fourni="360.00")
    assert verdict is None
    assert devis["prix_total"] == Decimal("360.00")


def test_prix_total_fourni_divergent_rejete():
    registre = []
    verdict = _verdict_attendu(_creer(registre, prix_total_fourni="1.00"), "REJ-DEVIS-TOTAL-INCOHERENT")
    assert "360.00" in verdict["detail"] and "1.00" in verdict["detail"]
    assert registre == []


def test_prix_total_fourni_non_decimal_rejete():
    _verdict_attendu(_creer([], prix_total_fourni="pas un nombre"), "REJ-DEVIS-TOTAL-INCOHERENT")


# -- lignes invalides ---------------------------------------------------------------------------
def test_lignes_vides_rejete():
    _verdict_attendu(_creer([], lignes=[]), "REJ-DEVIS-LIGNES-VIDES")


def test_lignes_pas_une_liste_rejete():
    _verdict_attendu(_creer([], lignes="pas une liste"), "REJ-DEVIS-LIGNES-VIDES")


@pytest.mark.parametrize(
    "surcharge",
    [
        {"description": ""},
        {"unite": "  "},
        {"quantite": "0"},
        {"quantite": "-1"},
        {"quantite": 30},  # float/JSON number, jamais accepté
        {"quantite": "pas un nombre"},
        {"cout_unitaire": "-1"},
        {"cout_unitaire": 10.0},
    ],
)
def test_ligne_invalide_rejetee(surcharge):
    _verdict_attendu(_creer([], lignes=[_ligne(**surcharge)]), "REJ-DEVIS-LIGNE-INVALIDE")


def test_ligne_avec_cle_manquante_ou_en_trop_rejetee():
    ligne_incomplete = _ligne()
    del ligne_incomplete["reference_besoin_materiau"]
    _verdict_attendu(_creer([], lignes=[ligne_incomplete]), "REJ-DEVIS-LIGNE-INVALIDE")

    ligne_en_trop = _ligne(cle_inconnue="x")
    _verdict_attendu(_creer([], lignes=[ligne_en_trop]), "REJ-DEVIS-LIGNE-INVALIDE")


def test_reference_besoin_materiau_est_optionnelle_null_accepte():
    registre = []
    devis, verdict = _creer(registre, lignes=[_ligne(reference_besoin_materiau=None)])
    assert verdict is None
    assert devis["lignes"][0]["reference_besoin_materiau"] is None


def test_reference_besoin_materiau_chaine_vide_rejetee():
    _verdict_attendu(_creer([], lignes=[_ligne(reference_besoin_materiau="")]), "REJ-DEVIS-LIGNE-INVALIDE")


def test_deuxieme_ligne_invalide_bloque_tout_le_devis_rien_nest_ecrit():
    registre = []
    _verdict_attendu(
        _creer(registre, lignes=[_ligne(), _ligne(quantite="-5")]), "REJ-DEVIS-LIGNE-INVALIDE"
    )
    assert registre == []


# -- identifiants et horodatage ------------------------------------------------------------------
def test_devis_id_vide_rejete():
    _verdict_attendu(_creer([], devis_id=""), "REJ-DEVIS-DEVIS-ID-VIDE")


def test_lead_id_vide_rejete():
    _verdict_attendu(_creer([], lead_id="   "), "REJ-DEVIS-LEAD-ID-VIDE")


def test_horodatage_vide_rejete():
    _verdict_attendu(_creer([], horodatage=""), "REJ-DEVIS-HORODATAGE-VIDE")


def test_chantier_id_none_accepte():
    registre = []
    devis, verdict = _creer(registre, chantier_id=None)
    assert verdict is None
    assert devis["chantier_id"] is None


def test_chantier_id_fourni_conserve():
    registre = []
    devis, verdict = _creer(registre, chantier_id="chantier-042")
    assert verdict is None
    assert devis["chantier_id"] == "chantier-042"


def test_chantier_id_chaine_vide_rejetee():
    _verdict_attendu(_creer([], chantier_id=""), "REJ-DEVIS-CHANTIER-ID-INVALIDE")


# -- idempotence par devis_id --------------------------------------------------------------------
def test_meme_devis_id_meme_contenu_est_un_no_op_idempotent():
    registre = []
    premier, verdict1 = _creer(registre)
    assert verdict1 is None
    assert len(registre) == 1

    second, verdict2 = _creer(registre)  # rejoue EXACTEMENT le même appel
    assert verdict2 is None
    assert len(registre) == 1, "un rejeu identique ne doit écrire aucun second maillon"
    assert second == premier


def test_meme_devis_id_contenu_different_est_rejete():
    registre = []
    _creer(registre)
    assert len(registre) == 1

    verdict = _verdict_attendu(
        _creer(registre, lignes=[_ligne(cout_unitaire="999.00")]), "REJ-DEVIS-ID-DEJA-UTILISE"
    )
    assert "M3-DEVIS-durable-001" in verdict["detail"]
    assert len(registre) == 1, "un contenu divergent ne doit jamais écraser le devis existant"


def test_devis_id_distincts_coexistent():
    registre = []
    devis_1, verdict1 = _creer(registre, devis_id="D1")
    devis_2, verdict2 = _creer(registre, devis_id="D2", lead_id="lead-002")
    assert verdict1 is None and verdict2 is None
    assert devis_1["devis_id"] != devis_2["devis_id"]
    assert len(registre) == 2


# -- lecture ---------------------------------------------------------------------------------
def test_lire_devis_introuvable_rejete():
    _verdict_attendu(devis_durable.lire_devis([], "inconnu"), "REJ-DEVIS-INTROUVABLE")


def test_lire_devis_devis_id_vide_rejete():
    _verdict_attendu(devis_durable.lire_devis([], ""), "REJ-DEVIS-DEVIS-ID-VIDE")


def test_lire_devis_retourne_letat_courant():
    registre = []
    cree, _ = _creer(registre)
    lu, verdict = devis_durable.lire_devis(registre, "M3-DEVIS-durable-001")
    assert verdict is None
    assert lu == cree
    assert lu["statut"] == "brouillon"


# -- transitions de statut : gardées, rejets nommés ----------------------------------------------
def test_transition_brouillon_vers_envoye_vers_accepte():
    registre = []
    _creer(registre)

    envoye, verdict = devis_durable.marquer_devis_envoye("M3-DEVIS-durable-001", _HORODATAGE, registre)
    assert verdict is None
    assert envoye["statut"] == "envoye"
    assert envoye["lignes"], "les lignes posées à la création restent visibles après la transition"

    accepte, verdict = devis_durable.marquer_devis_accepte(
        "M3-DEVIS-durable-001", "nathan", _HORODATAGE, registre
    )
    assert verdict is None
    assert accepte["statut"] == "accepte"
    assert accepte["approbateur"] == "nathan"
    assert accepte["lignes"], "les lignes restent visibles après acceptation"
    assert accepte["prix_total"] == Decimal("360.00")


def test_transition_brouillon_directement_vers_accepte_permise():
    """L'envoi n'est pas exposé comme outil avant T1.3 : un humain peut constater l'acceptation
    d'un devis encore BROUILLON (cf. docstring du module)."""
    registre = []
    _creer(registre)
    accepte, verdict = devis_durable.marquer_devis_accepte(
        "M3-DEVIS-durable-001", "nathan", _HORODATAGE, registre
    )
    assert verdict is None
    assert accepte["statut"] == "accepte"


def test_envoyer_un_devis_deja_envoye_est_une_transition_illegale():
    registre = []
    _creer(registre)
    devis_durable.marquer_devis_envoye("M3-DEVIS-durable-001", _HORODATAGE, registre)
    verdict = _verdict_attendu(
        devis_durable.marquer_devis_envoye("M3-DEVIS-durable-001", _HORODATAGE, registre),
        "REJ-DEVIS-TRANSITION-ILLEGALE",
    )
    assert "envoye" in verdict["detail"]


def test_accepter_deux_fois_le_meme_devis_est_une_transition_illegale_pas_un_no_op():
    registre = []
    _creer(registre)
    devis_durable.marquer_devis_accepte("M3-DEVIS-durable-001", "nathan", _HORODATAGE, registre)
    taille_apres_premiere_acceptation = len(registre)

    verdict = _verdict_attendu(
        devis_durable.marquer_devis_accepte("M3-DEVIS-durable-001", "nathan", _HORODATAGE, registre),
        "REJ-DEVIS-TRANSITION-ILLEGALE",
    )
    assert "accepte" in verdict["detail"]
    assert len(registre) == taille_apres_premiere_acceptation, "un second accepte n'écrit rien"


def test_envoyer_un_devis_deja_accepte_est_une_transition_illegale():
    registre = []
    _creer(registre)
    devis_durable.marquer_devis_accepte("M3-DEVIS-durable-001", "nathan", _HORODATAGE, registre)
    _verdict_attendu(
        devis_durable.marquer_devis_envoye("M3-DEVIS-durable-001", _HORODATAGE, registre),
        "REJ-DEVIS-TRANSITION-ILLEGALE",
    )


def test_transition_sur_devis_introuvable_rejetee():
    _verdict_attendu(
        devis_durable.marquer_devis_accepte("inconnu", "nathan", _HORODATAGE, []), "REJ-DEVIS-INTROUVABLE"
    )
    _verdict_attendu(
        devis_durable.marquer_devis_envoye("inconnu", _HORODATAGE, []), "REJ-DEVIS-INTROUVABLE"
    )


def test_accepter_sans_approbateur_rejete_humain_requis():
    registre = []
    _creer(registre)
    verdict = _verdict_attendu(
        devis_durable.marquer_devis_accepte("M3-DEVIS-durable-001", "", _HORODATAGE, registre),
        "REJ-DEVIS-APPROBATEUR-ABSENT",
    )
    assert "humain" in verdict["detail"]
    assert len(registre) == 1, "aucune transition n'est écrite sans approbateur"


def test_accepter_horodatage_vide_rejete():
    registre = []
    _creer(registre)
    _verdict_attendu(
        devis_durable.marquer_devis_accepte("M3-DEVIS-durable-001", "nathan", "", registre),
        "REJ-DEVIS-HORODATAGE-VIDE",
    )


# -- projection par rôle : l'employé ne voit ni coût ni marge (ni prix) --------------------------
def test_projection_interne_est_la_vue_complete():
    registre = []
    devis, _ = _creer(registre)
    projection, verdict = devis_durable.projeter_devis(devis, "interne")
    assert verdict is None
    assert projection == devis


def test_projection_employe_retire_cout_marge_et_prix():
    registre = []
    devis, _ = _creer(registre)
    projection, verdict = devis_durable.projeter_devis(devis, "employe")
    assert verdict is None

    interdits_devis = {"taux_marge", "cout_total", "prix_total"}
    assert not (interdits_devis & set(projection)), projection

    for ligne in projection["lignes"]:
        interdits_ligne = {"cout_unitaire", "cout_ligne", "prix_ligne"}
        assert not (interdits_ligne & set(ligne)), ligne
        assert set(ligne) == {"description", "quantite", "unite", "reference_besoin_materiau"}


def test_projection_employe_garde_les_champs_operationnels():
    registre = []
    devis, _ = _creer(registre)
    projection, verdict = devis_durable.projeter_devis(devis, "employe")
    assert verdict is None
    assert projection["devis_id"] == devis["devis_id"]
    assert projection["statut"] == "brouillon"
    assert projection["lignes"][0]["description"] == devis["lignes"][0]["description"]
    assert projection["lignes"][0]["quantite"] == devis["lignes"][0]["quantite"]


def test_projection_role_inconnu_rejetee():
    registre = []
    devis, _ = _creer(registre)
    _verdict_attendu(devis_durable.projeter_devis(devis, "proprietaire"), "REJ-DEVIS-ROLE-INCONNU")


def test_projection_devis_absent_rejetee():
    _verdict_attendu(devis_durable.projeter_devis(None, "interne"), "REJ-DEVIS-INTROUVABLE")


# -- charge de l'événement m3.devis_accepte -------------------------------------------------------
def test_charge_evenement_devis_accepte_est_json_sur_decimales_en_texte():
    registre = []
    _creer(registre)
    accepte, verdict = devis_durable.marquer_devis_accepte(
        "M3-DEVIS-durable-001", "nathan", _HORODATAGE, registre
    )
    assert verdict is None
    charge = devis_durable.charge_evenement_devis_accepte(accepte)

    assert charge["devis_id"] == "M3-DEVIS-durable-001"
    assert charge["lead_id"] == "lead-001"
    assert charge["chantier_id"] is None
    assert charge["cout_total"] == "300.00" and isinstance(charge["cout_total"], str)
    assert charge["prix_total"] == "360.00" and isinstance(charge["prix_total"], str)
    assert charge["taux_marge"] == "0.20" and isinstance(charge["taux_marge"], str)
    assert charge["lignes"] == [
        {
            "description": "Gouttière alu 5 po",
            "quantite": "30",
            "unite": "pi_lin",
            "reference_besoin_materiau": "besoin-goutt-001",
        }
    ]
    # Aucun coût ni prix par ligne dans la charge de l'événement (M6 planifie des quantités).
    assert "cout_unitaire" not in charge["lignes"][0]
    assert "prix_ligne" not in charge["lignes"][0]


# -- catalogue fermé de verdicts ------------------------------------------------------------------
def test_tous_les_codes_exerces_par_ce_fichier_appartiennent_au_catalogue():
    assert set(verdicts.CODES_M3_LIST) >= _CODES_EXERCES_PAR_CE_FICHIER


def test_tous_les_codes_rej_devis_du_catalogue_sont_exerces_par_ce_fichier():
    """Un code déclaré mais jamais exercé serait un verdict orphelin (cf. verdicts.py, leçon des
    deux VERDICTS_ESTIMATION déjà orphelins ailleurs dans ce paquet) : la liste statique ci-dessus
    doit couvrir EXACTEMENT les codes REJ-DEVIS-* du catalogue, ni plus ni moins."""
    codes_devis_du_catalogue = {code for code in verdicts.CODES_M3_LIST if code.startswith("REJ-DEVIS-")}
    assert codes_devis_du_catalogue == _CODES_EXERCES_PAR_CE_FICHIER
