"""Capacités d'agent de M5 : contrat des outils et chaîne financière composée."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from m5_financecore.outils import outils

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer

HORODATAGE = "2026-08-03T12:00:00+00:00"


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m5_etat_tresorerie"
    assert all(nom.startswith("m5_") for nom in noms)
    assert dep.mode == "ombre"
    assert "m06-material-control" in dep.dependances
    assert "m04-field-ops" in dep.dependances


def test_autonomie_respecte_la_regle_finance():
    """RÈGLE FINANCE : écriture financière et décision d'approbation = T3,
    lecture/calcul = T0, création d'une demande (registre interne) = T1."""
    assert _outil("m5_etat_tresorerie").autonomie == Autonomie.T0
    assert _outil("m5_calculer_taxes_tps_tvq").autonomie == Autonomie.T0
    assert _outil("m5_enregistrer_mouvement").autonomie == Autonomie.T3
    assert _outil("m5_creer_demande_approbation").autonomie == Autonomie.T1
    assert _outil("m5_decider_approbation").autonomie == Autonomie.T3


# --- m5_etat_tresorerie : composé, fail-closed ------------------------------


def test_etat_tresorerie_refuse_par_defaut_sans_permission_explicite():
    reponse = executer(_outil("m5_etat_tresorerie"), {"role": "employe", "autorise_couts": False})

    assert reponse["ok"] is True
    assert reponse["resultat"]["solde"] is None
    assert reponse["resultat"]["argent_disponible"] is None
    assert reponse["resultat"]["taux_utilises"] == []


def test_etat_tresorerie_expose_solde_et_argent_disponible_quand_autorise():
    enregistrer = _outil("m5_enregistrer_mouvement")
    r1 = executer(
        enregistrer,
        {
            "montant": "500.00",
            "type_mouvement": "ENCAISSEMENT",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "test",
        },
    )
    historique = r1["resultat"]["mouvements_historique"]
    r2 = executer(
        enregistrer,
        {
            "montant": "80.00",
            "type_mouvement": "PROVISION",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "test",
            "mouvements_historique": historique,
        },
    )
    historique = r2["resultat"]["mouvements_historique"]

    reponse = executer(
        _outil("m5_etat_tresorerie"),
        {
            "role": "gestionnaire",
            "autorise_couts": True,
            "mouvements_historique": historique,
        },
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["solde"] == "500.00"
    assert reponse["resultat"]["argent_disponible"] == "420.00"


def test_etat_tresorerie_parametre_requis_manquant_est_un_refus_de_schema():
    reponse = executer(_outil("m5_etat_tresorerie"), {"role": "employe"})

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


# --- m5_calculer_taxes_tps_tvq ----------------------------------------------


def test_calculer_taxes_tps_tvq_sur_le_fichier_versionne_reel():
    reponse = executer(_outil("m5_calculer_taxes_tps_tvq"), {"montant_avant_taxes": "100.00"})

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["total_taxes"] == "14.98"
    assert reponse["resultat"]["resultat"]["montant_apres_taxes"] == "114.98"


def test_calculer_taxes_rejette_un_montant_non_decimal_par_le_schema():
    reponse = executer(_outil("m5_calculer_taxes_tps_tvq"), {"montant_avant_taxes": 100.0})

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


# --- m5_enregistrer_mouvement : nominal, refus, blocage ---------------------


def test_enregistrer_mouvement_nominal_ecrit_au_registre():
    reponse = executer(
        _outil("m5_enregistrer_mouvement"),
        {
            "montant": "42.00",
            "type_mouvement": "ENCAISSEMENT",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "test",
        },
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    assert Decimal(reponse["resultat"]["resultat"]["montant"]) == Decimal("42.00")


def test_enregistrer_mouvement_refuse_un_decaissement_positif():
    """Bug NEW-PROD corrigé : un DECAISSEMENT positif ne doit jamais atteindre le
    registre en passant par l'outil agent, exactement comme via le code métier."""
    reponse = executer(
        _outil("m5_enregistrer_mouvement"),
        {
            "montant": "100.00",
            "type_mouvement": "DECAISSEMENT",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "test",
        },
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-MOUVEMENT-SIGNE-INCOHERENT"


def test_enregistrer_mouvement_bloque_un_montant_non_texte_au_niveau_schema():
    reponse = executer(
        _outil("m5_enregistrer_mouvement"),
        {
            "montant": 100.0,
            "type_mouvement": "ENCAISSEMENT",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "test",
        },
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


# --- m5_creer_demande_approbation / m5_decider_approbation -------------------


def test_cycle_approbation_f6_nominal_avec_preuve_structuree():
    creer = _outil("m5_creer_demande_approbation")
    decider = _outil("m5_decider_approbation")

    r1 = executer(
        creer,
        {"demande_id": "DEM-100", "palier": "F6", "action": "Virement 5000$", "horodatage": HORODATAGE},
    )
    historique = r1["resultat"]["approbations_historique"]

    preuve = json.dumps(
        {"methode": "MFA_TOTP", "horodatage": HORODATAGE, "identifiant_approbateur": "EMP-042"}
    )
    r2 = executer(
        decider,
        {
            "demande_id": "DEM-100",
            "decision": "APPROUVE",
            "approbateur": "Nathan",
            "horodatage": HORODATAGE,
            "preuve": preuve,
            "approbations_historique": historique,
        },
    )

    assert r2["resultat"]["accepte"] is True
    assert r2["resultat"]["resultat"]["statut"] == "APPROUVE"


def test_decider_approbation_f6_refuse_une_preuve_en_chaine_libre():
    creer = _outil("m5_creer_demande_approbation")
    decider = _outil("m5_decider_approbation")

    r1 = executer(
        creer,
        {"demande_id": "DEM-101", "palier": "F6", "action": "Virement 5000$", "horodatage": HORODATAGE},
    )
    historique = r1["resultat"]["approbations_historique"]

    r2 = executer(
        decider,
        {
            "demande_id": "DEM-101",
            "decision": "APPROUVE",
            "approbateur": "Nathan",
            "horodatage": HORODATAGE,
            "preuve": "PV-COMITE-F6-001",
            "approbations_historique": historique,
        },
    )

    assert r2["resultat"]["accepte"] is False
    assert r2["resultat"]["verdict"]["code"] == "REJ-PREUVE-STRUCTURE-INVALIDE"


def test_creer_demande_approbation_refuse_un_palier_hors_enumeration_par_le_schema():
    reponse = executer(
        _outil("m5_creer_demande_approbation"),
        {"demande_id": "DEM-102", "palier": "F9", "action": "test", "horodatage": HORODATAGE},
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_decider_approbation_decision_hors_enum_est_bloquee_par_le_schema():
    """La valeur enum du schéma est la première ligne de défense (arguments
    invalides), avant même d'atteindre le code métier."""
    creer = _outil("m5_creer_demande_approbation")
    decider = _outil("m5_decider_approbation")

    r1 = executer(
        creer, {"demande_id": "DEM-103", "palier": "F0", "action": "test", "horodatage": HORODATAGE}
    )
    historique = r1["resultat"]["approbations_historique"]

    reponse = executer(
        decider,
        {
            "demande_id": "DEM-103",
            "decision": "PEUT-ETRE",
            "approbateur": "Nathan",
            "horodatage": HORODATAGE,
            "approbations_historique": historique,
        },
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_decider_approbation_fonction_refuse_une_decision_inconnue_en_defense_en_profondeur():
    """La fonction métier reste elle-même fail-closed (REJ-DECISION-INVALIDE),
    indépendamment du schéma JSON qui la protège déjà — défense en profondeur,
    pas un chemin mort : un appel direct au module (hors MCP) doit rester sûr."""
    from m5_financecore import outils as outils_module

    reponse = outils_module.decider_approbation(
        demande_id="DEM-104",
        decision="PEUT-ETRE",
        approbateur="Nathan",
        horodatage=HORODATAGE,
    )

    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-DECISION-INVALIDE"
