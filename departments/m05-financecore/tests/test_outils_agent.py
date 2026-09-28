"""Capacités d'agent de M5 : contrat des outils et chaîne financière composée."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import outils as module_outils
from m5_financecore.outils import outils

from opsys import stockage
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer

HORODATAGE = "2026-08-03T12:00:00+00:00"


@pytest.fixture(autouse=True)
def _base_durable_m5(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée par test : un appel sans historique écrit au registre durable
    de production (ADR-0009), jamais dans la base par défaut de l'hôte (~/.opsys)."""
    url = f"sqlite:///{tmp_path / 'm5-outils.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    module_outils.utiliser_stockage_durable()
    yield
    stockage.liberer()


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m5_etat_tresorerie"
    assert all(nom.startswith("m5_") for nom in noms)
    assert dep.mode == "ombre"
    assert "m02-revenue-crm" in dep.dependances  # M5.2 : la facture porte un client_id (M2)
    assert "m06-material-control" in dep.dependances
    assert "m04-field-ops" in dep.dependances


def test_autonomie_respecte_la_regle_finance():
    """RÈGLE FINANCE : écriture financière et décision d'approbation = T3,
    lecture/calcul = T0, création d'une demande (registre interne) = T1.
    Créer une facture BROUILLON est une écriture interne non finale, T1 elle aussi."""
    assert _outil("m5_etat_tresorerie").autonomie == Autonomie.T0
    assert _outil("m5_calculer_taxes_tps_tvq").autonomie == Autonomie.T0
    assert _outil("m5_enregistrer_mouvement").autonomie == Autonomie.T3
    assert _outil("m5_creer_facture_brouillon").autonomie == Autonomie.T1
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
    """Simulation en mémoire : l'appelant transporte l'historique d'un appel à l'autre."""
    enregistrer = _outil("m5_enregistrer_mouvement")
    r1 = executer(
        enregistrer,
        {
            "montant": "500.00",
            "type_mouvement": "ENCAISSEMENT",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "test",
            "mouvements_historique": [],
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


def test_en_production_le_registre_durable_porte_la_tresorerie_sans_historique_transmis():
    """Registre de production : aucun historique transporté, la réponse ne renvoie que la tête et
    la taille, et l'état de trésorerie se calcule depuis la base."""
    enregistrer = _outil("m5_enregistrer_mouvement")
    for montant, type_mouvement in (("500.00", "ENCAISSEMENT"), ("80.00", "PROVISION")):
        reponse = executer(enregistrer, {
            "montant": montant, "type_mouvement": type_mouvement, "horodatage": HORODATAGE,
            "classe_retention": "STANDARD", "source": "test",
        })
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert "mouvements_historique" not in reponse["resultat"]
    registre = reponse["resultat"]["registre_mouvements"]
    assert registre["taille"] == 2 and registre["tete"] == reponse["resultat"]["resultat"]["ligne_id"]

    etat = executer(_outil("m5_etat_tresorerie"), {"role": "gestionnaire", "autorise_couts": True})
    assert etat["ok"] is True
    assert etat["resultat"]["solde"] == "500.00"
    assert etat["resultat"]["argent_disponible"] == "420.00"


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


# --- m5_creer_facture_brouillon : registre dédié, T1, jamais les mouvements ------------------

_LIGNES_FACTURE = [
    {
        "description": "Gouttières 5po aluminium",
        "quantite": "40",
        "unite": "pi",
        "prix_unitaire": "8.50",
        "reference_ligne_devis": "L1",
    },
    {
        "description": "Main d'oeuvre installation",
        "quantite": "1",
        "unite": "forfait",
        "prix_unitaire": "260.00",
        "reference_ligne_devis": "L2",
    },
]

_ARGUMENTS_FACTURE = {
    "facture_id": "FACT-001",
    "chantier_id": "CHANTIER-001",
    "devis_id": "DEVIS-001",
    "client_id": "CLIENT-001",
    "lignes": _LIGNES_FACTURE,
    "horodatage": HORODATAGE,
}


def test_creer_facture_brouillon_nominal_via_historique_en_memoire():
    """Simulation en mémoire : l'appelant transporte l'historique d'un appel à l'autre, sans
    toucher au registre durable — même patron que m5_enregistrer_mouvement."""
    reponse = executer(
        _outil("m5_creer_facture_brouillon"),
        {**_ARGUMENTS_FACTURE, "factures_historique": []},
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["statut"] == "BROUILLON"
    assert resultat["montant_avant_taxes"] == "600.00"
    assert resultat["montant_apres_taxes"] == "689.85"
    assert reponse["resultat"]["factures_historique"] == [resultat]


def test_creer_facture_brouillon_en_production_le_registre_durable_porte_les_factures_sans_historique_transmis():
    """Registre de production (troisième registre, distinct de celui des mouvements) : aucun
    historique transporté, la réponse ne renvoie que la tête et la taille."""
    reponse = executer(_outil("m5_creer_facture_brouillon"), _ARGUMENTS_FACTURE)

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    assert "factures_historique" not in reponse["resultat"]
    registre_factures = reponse["resultat"]["registre_factures"]
    assert registre_factures["taille"] == 1
    assert registre_factures["tete"] == reponse["resultat"]["resultat"]["ligne_id"]

    # Un deuxième appel, sans historique non plus, enchaîne bien sur le premier : la continuité
    # vit dans la base, pas chez l'appelant (même preuve que pour les mouvements).
    deuxieme = executer(
        _outil("m5_creer_facture_brouillon"),
        {**_ARGUMENTS_FACTURE, "facture_id": "FACT-002", "devis_id": "DEVIS-002"},
    )
    assert deuxieme["resultat"]["registre_factures"]["taille"] == 2
    assert deuxieme["resultat"]["resultat"]["precedent_ligne_id"] == registre_factures["tete"]


def test_creer_facture_brouillon_ne_touche_jamais_le_registre_des_mouvements():
    """LE PIÈGE, au niveau outil et sur le stockage durable réel : créer une facture brouillon
    n'écrit jamais dans le registre des MOUVEMENTS (registre 'principal'), même quand les deux
    registres partagent la même base et le même interrupteur de durabilité."""
    reponse = executer(_outil("m5_creer_facture_brouillon"), _ARGUMENTS_FACTURE)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True

    etat = module_outils.etat_tresorerie(role="gestionnaire", autorise_couts=True)
    assert etat["solde"] == Decimal("0")
    assert etat["argent_disponible"] == Decimal("0")


def test_creer_facture_brouillon_est_idempotente_par_devis_id_via_l_outil():
    premier = executer(_outil("m5_creer_facture_brouillon"), _ARGUMENTS_FACTURE)
    assert premier["resultat"]["accepte"] is True

    second = executer(
        _outil("m5_creer_facture_brouillon"), {**_ARGUMENTS_FACTURE, "facture_id": "FACT-002"}
    )

    assert second["ok"] is True
    assert second["resultat"]["accepte"] is False
    assert second["resultat"]["verdict"]["code"] == "REJ-FACTURE-DEVIS-DEJA-FACTURE"


def test_creer_facture_brouillon_rejette_un_montant_avant_taxes_fourni_incoherent():
    reponse = executer(
        _outil("m5_creer_facture_brouillon"), {**_ARGUMENTS_FACTURE, "montant_avant_taxes": "1.00"}
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-FACTURE-MONTANT-INCOHERENT"


def test_creer_facture_brouillon_bloque_un_montant_avant_taxes_non_texte_au_niveau_schema():
    """Même garde qu'à `m5_enregistrer_mouvement` (mandat, tâche 3) : un float JSON pour le
    contrôle défensif `montant_avant_taxes` est bloqué avant même d'atteindre le code métier."""
    reponse = executer(
        _outil("m5_creer_facture_brouillon"), {**_ARGUMENTS_FACTURE, "montant_avant_taxes": 600.0}
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_creer_facture_brouillon_rejette_une_quantite_de_ligne_non_texte_en_defense_en_profondeur():
    """Le schéma JSON minimal (`opsys.outils.valider_arguments`) ne recurse pas dans les items
    d'un tableau : un float caché dans une ligne n'est donc bloqué QUE par le code métier — cette
    même garde que `m5_enregistrer_mouvement`, appliquée ici à chaque ligne, pas seulement au
    total. Appel direct de la fonction (hors `executer`) pour le prouver en défense en profondeur."""
    reponse = module_outils.creer_facture_brouillon(
        **{**_ARGUMENTS_FACTURE, "lignes": [{**_LIGNES_FACTURE[0], "quantite": 40.0}, _LIGNES_FACTURE[1]]}
    )

    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-FACTURE-LIGNE-INVALIDE"


def test_creer_facture_brouillon_parametre_requis_manquant_est_un_refus_de_schema():
    arguments_sans_lignes = {k: v for k, v in _ARGUMENTS_FACTURE.items() if k != "lignes"}

    reponse = executer(_outil("m5_creer_facture_brouillon"), arguments_sans_lignes)

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
