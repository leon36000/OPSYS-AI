"""PLAN T4.19-b : le constat du cash libre, tel que M5 le publie au bus (`m5.cash_libre_constate`).

Trois étages, sans base de données :

1. `constat_cash_libre.charge_evenement` (module pur) : chaque montant est celui que `calculer_cash_libre` rend, en
   texte décimal (jamais un flottant), chaque composante porte sa source et sa fraîcheur, le statut dit « calculé »
   ou « non calculable, manque X » (par code), et RIEN de libre ni de personnel ne sort (la source d'une déclaration
   du propriétaire est dite par son origine, pas par ses mots) ;
2. l'identifiant est déterministe : un constat par rang, date de référence et version des données ;
3. le schéma FERMÉ du catalogue refuse ce qu'un producteur fautif ne doit jamais dire (un flottant, un champ de plus
   ou de moins, un « calculé » qui porte un manque, un repère pour un solde inconnu, une composante hors ordre...).

Le cas de référence est celui de `test_cash_libre.py` (calculé à la main, fictif, AGENTS.md) :
solde 37654.33 ; TPS/TVQ 1981.69 ; paies 4200.00 ; DAS 1350.75 ; comptes à payer 459.91 ; dettes 800.00 ; réserves
1000.00 ; cash libre 37654.33 - 9792.35 = 27861.98. La publication par le vrai bus est dans
`test_constat_cash_libre_outils.py`, et M5 vers M8 dans `tests/test_cascade_cash_libre_m5_m8.py` (socle).
"""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import (
    analyse,
    cash_libre,
    constat_cash_libre,
    facturation,
    registre,
    soldes,
    taux_fiscaux,
    validation,
)
from m5_financecore import comptes_a_payer as cap

from opsys import evenements
from opsys.evenements.schemas import erreurs_charge

FICTIF = True
D = Decimal
TYPE = "m5.cash_libre_constate"
_RACINE_M5 = Path(__file__).resolve().parents[1]
_RACINE_DEPOT = _RACINE_M5.parents[1]
CHEMIN_TAUX = _RACINE_M5 / "contracts" / "taux_fiscaux.v1.yaml"
REMISES = date(2026, 6, 30)
JOUR = date(2026, 9, 29)

# Les mots du propriétaire dans `source` : un nom d'employé, ce que la charge ne doit JAMAIS porter.
DECLARATIONS = {
    "paies": {"montant": "4200.00", "source": "paie de Marc Tremblay et Luc Gagnon (fictifs)", "au": "2026-09-25"},
    "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
    "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
}

_CLES = {
    "evenement_id", "sequence", "date_reference", "version_donnees", "devise", "statut", "cash_libre_cad",
    "au_plus_cad", "en_deficit", "lecture", "solde", "composantes", "manque", "reserves", "hypotheses", "mention",
}
_CLES_COMPOSANTE = {"id", "libelle", "statut", "montant_cad", "plancher_cad", "source", "fraicheur"}
_ORDRE = ["taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves"]


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(CHEMIN_TAUX)
    assert erreurs == []
    return dictionnaire


# ------------------------------------------------------------------------------- le cas fictif, en mémoire
def _mouvements(mouvements=None):
    reg = registre.Registre()
    for montant, type_mouvement, horodatage in mouvements if mouvements is not None else (
        ("50000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00"),
        ("-12345.67", "DECAISSEMENT", "2026-08-15T12:00:00-04:00"),
        ("1000.00", "PROVISION", "2026-09-10T12:00:00-04:00"),
    ):
        registre.enregistrer_mouvement({"montant": D(montant), "type_mouvement": type_mouvement,
                                        "horodatage": horodatage, "classe_retention": "STANDARD",
                                        "source": "test"}, reg)
    return reg


def _factures(taux):
    reg = registre.Registre()
    lignes = (
        ("F-1", "D-1", "10000.00", "2026-07-15", "ENVOYEE"),
        ("F-2", "D-2", "3333.33", "2026-08-20", "PAYEE"),
        ("F-3", "D-3", "1000.00", "2026-06-10", "ENVOYEE"),   # avant la remise : déjà remise
        ("F-4", "D-4", "500.00", "2026-09-01", "BROUILLON"),   # jamais envoyée : aucune taxe collectée
        ("F-5", "D-5", "200.00", "2026-07-01", "ENVOYEE"),    # le lendemain de la remise : incluse
        ("F-6", "D-6", "100.00", "2026-06-30", "ENVOYEE"),    # le jour même de la remise : exclue
    )
    for facture_id, devis, prix, jour, statut in lignes:
        _, verdict = facturation.creer_facture_brouillon(
            facture_id, "CH-1", devis, "C-1",
            [{"description": "travaux (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": prix,
              "reference_ligne_devis": "L-1"}], f"{jour}T09:00:00-04:00", taux, reg)
        assert verdict is None, verdict
        if statut in ("ENVOYEE", "PAYEE"):
            assert facturation.envoyer_facture(facture_id, f"{jour}T09:30:00-04:00", reg)[1] is None
        if statut == "PAYEE":
            assert facturation.marquer_facture_payee(facture_id, "nathan", "2026-09-05T09:00:00-04:00", reg)[1] is None
    return reg


def _reception(evenement_id, po_id, quantite, horodatage, prix="5.00"):
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": horodatage, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": quantite, "quantite_recue": quantite,
                    "prix_unitaire_prevu": prix, "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": prix, "verdict_prix_reception": "PRIX_CATALOGUE",
                    "ecart_prix_critique": False}],
    }


def _a_payer(taux, prix_du_po_2="5.00"):
    """PO-1 : 60 x 5.00 = 300.00 reçus et facturés (344.93 avec taxes). PO-2 : 20 x `prix_du_po_2`, facture du
    2026-06-20 (114.98 avec taxes), datée AVANT la remise."""
    reg = registre.Registre()
    for evenement, po, quantite, horodatage, prix in (
        ("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00", "5.00"),
        ("e-2", "PO-2", "20", "2026-09-16T09:00:00-04:00", prix_du_po_2),
    ):
        entree, verdict = cap.construire_reception(_reception(evenement, po, quantite, horodatage, prix))
        assert verdict is None, verdict
        assert cap.enregistrer_reception(entree, reg)[1] is None
    for po, numero, jour, montant in (("PO-1", "F-1001", "2026-09-14", "300.00"),
                                      ("PO-2", "F-2001", "2026-06-20", "100.00")):
        _, verdict = cap.saisir_facture_fournisseur(
            po_id=po, fournisseur_id="gentek", numero_facture=numero, date_facture=jour, montant_avant_taxes=montant,
            total_facture=None, saisi_par="nathan", voie="appareil", horodatage="2026-09-20T10:00:00-04:00",
            dictionnaire_taux=taux, registre_cible=reg)
        assert verdict is None, verdict
    return reg


def _calculer(taux, *, mouvements=None, declarees=DECLARATIONS, a_payer=None, reserves_declarees=None):
    """Ce que `outils._resultat_cash_libre` fait, avec des registres en mémoire : les sept composantes."""
    mouvements = _mouvements() if mouvements is None else mouvements
    factures = _factures(taux)
    a_payer = _a_payer(taux) if a_payer is None else a_payer
    solde = soldes.calculer_solde(mouvements)
    decrit = soldes.decrire_mouvements(mouvements)
    provisions, nombre, derniere = soldes.calculer_provisions(mouvements)
    clients = [*facturation.factures_par_statut(factures, "ENVOYEE"),
               *facturation.factures_par_statut(factures, "PAYEE")]
    resume, verdict_ap = cap.resume_a_payer(a_payer, taux)
    registres = [cash_libre.registre_lu("factures", factures.lire()),
                 cash_libre.registre_lu("comptes_a_payer", a_payer.lire())]
    return cash_libre.calculer_cash_libre(
        cash_libre.composante_solde(solde, decrit),
        [
            cash_libre.composante_taxes(clients, cap.factures_saisies(a_payer), REMISES, None, registres),
            cash_libre.composante_declaree("paies", declarees.get("paies")),
            cash_libre.composante_declaree("das", declarees.get("das")),
            cash_libre.composante_comptes_a_payer(resume, verdict_ap, registres[1:]),
            cash_libre.composante_declaree("dettes", declarees.get("dettes")),
            cash_libre.composante_reserves(provisions, nombre, derniere, decrit, reserves_declarees),
        ],
    )


def _charge(taux, sequence=1, jour=JOUR, **options):
    return constat_cash_libre.charge_evenement(_calculer(taux, **options), jour, sequence)


def _par_id(charge):
    return {c["id"]: c for c in charge["composantes"]}


def _sans_flottant(valeur):
    """Aucun nombre flottant, nulle part dans la charge (un montant est un texte décimal)."""
    if isinstance(valeur, float):
        return False
    if isinstance(valeur, dict):
        return all(_sans_flottant(v) for v in valeur.values())
    if isinstance(valeur, list):
        return all(_sans_flottant(v) for v in valeur)
    return True


# =========================================================================================
# 1. La charge : chiffrée à la cent près, avec sa source et sa fraîcheur
# =========================================================================================
def test_le_cas_fictif_est_publie_chiffre_a_la_cent_pres_avec_tout_ce_qui_l_explique(taux):
    resultat = _calculer(taux)
    charge = constat_cash_libre.charge_evenement(resultat, JOUR, 1)

    assert set(charge) == _CLES
    assert charge["evenement_id"] == f"m5-cash-libre-1-2026-09-29-{resultat['cash_libre_id'][:16]}"
    assert (charge["sequence"], charge["date_reference"], charge["devise"]) == (1, "2026-09-29", "CAD")
    assert charge["version_donnees"] == resultat["cash_libre_id"] and len(charge["version_donnees"]) == 64
    assert charge["statut"] == "CALCULE" and charge["en_deficit"] is False
    assert charge["cash_libre_cad"] == "27861.98" and charge["au_plus_cad"] is None
    assert charge["solde"]["montant_cad"] == "37654.33"
    assert [c["id"] for c in charge["composantes"]] == _ORDRE
    assert {cid: c["montant_cad"] for cid, c in _par_id(charge).items()} == {
        "taxes_a_remettre": "1981.69", "paies": "4200.00", "das": "1350.75", "comptes_a_payer": "459.91",
        "dettes": "800.00", "reserves": "1000.00"}
    # la somme refaite à la main : 37654.33 - 9792.35 = 27861.98
    assert D("37654.33") - D("9792.35") == D(charge["cash_libre_cad"])
    assert charge["manque"] == [] and charge["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert charge["lecture"] == (
        "Cash libre : 27861.98 $ (solde moins toutes les obligations ci-dessous). "
        "Sous réserve : REJ-AP-UNITE-PRIX-NON-CONFIRMEE.")
    assert erreurs_charge(TYPE, charge) == []


def test_les_montants_du_constat_sont_ceux_de_calculer_cash_libre_jamais_un_second_calcul(taux):
    """Chaque texte est le `Decimal` du calcul, rendu tel quel : rien n'est arrondi, additionné ni corrigé."""
    resultat = _calculer(taux)
    charge = constat_cash_libre.charge_evenement(resultat, JOUR, 1)

    assert D(charge["cash_libre_cad"]) == resultat["cash_libre"]
    assert D(charge["solde"]["montant_cad"]) == resultat["solde"]["montant"]
    for calculee, publiee in zip(resultat["composantes"], charge["composantes"], strict=True):
        assert (calculee["id"], D(publiee["montant_cad"])) == (publiee["id"], calculee["montant"])
    assert not [c for c in charge["composantes"] if c["plancher_cad"] is not None]


def test_aucun_montant_n_est_un_nombre_flottant_ni_ne_porte_de_notation_scientifique(taux):
    charge = _charge(taux)

    assert _sans_flottant(charge)
    for montant in (charge["cash_libre_cad"], charge["solde"]["montant_cad"],
                    *(c["montant_cad"] for c in charge["composantes"])):
        assert isinstance(montant, str) and "E" not in montant and "e" not in montant, montant
        assert D(montant) == D(montant).quantize(D("0.01")), "deux décimales, au cent"


def test_chaque_composante_porte_sa_source_et_sa_fraicheur(taux):
    charge = _charge(taux)
    par_id = {"solde": charge["solde"], **_par_id(charge)}

    assert all(set(c) == _CLES_COMPOSANTE for c in par_id.values())
    assert {cid: c["source"]["origine"] for cid, c in par_id.items()} == {
        "solde": "REGISTRE", "taxes_a_remettre": "REGISTRE", "paies": "DECLARATION_PROPRIETAIRE",
        "das": "DECLARATION_PROPRIETAIRE", "comptes_a_payer": "REGISTRE", "dettes": "DECLARATION_PROPRIETAIRE",
        "reserves": "REGISTRE"}
    assert {cid: [(r["registre"], r["taille"]) for r in c["source"]["registres"]] for cid, c in par_id.items()} == {
        "solde": [("mouvements", 3)], "taxes_a_remettre": [("factures", 12), ("comptes_a_payer", 4)],
        "paies": [], "das": [], "comptes_a_payer": [("comptes_a_payer", 4)], "dettes": [],
        "reserves": [("mouvements", 3)]}
    assert {cid: c["fraicheur"] for cid, c in par_id.items()} == {
        "solde": {"derniere_piece": "2026-09-10T12:00:00-04:00", "pieces": 3},
        "taxes_a_remettre": {"derniere_piece": "2026-09-14", "pieces": 4},
        "paies": {"derniere_piece": "2026-09-25", "pieces": 1},
        "das": {"derniere_piece": "2026-09-25", "pieces": 1},
        "comptes_a_payer": {"derniere_piece": "2026-09-20T10:00:00-04:00", "pieces": 4},
        "dettes": {"derniere_piece": "2026-09-01", "pieces": 1},
        "reserves": {"derniere_piece": "2026-09-10T12:00:00-04:00", "pieces": 1}}
    for composante in par_id.values():
        for r in composante["source"]["registres"]:
            assert len(r["tete"]) == 16 and set(r) == {"registre", "taille", "tete"}


def test_les_libelles_sont_ceux_de_m5(taux):
    charge = _charge(taux)

    assert {c["id"]: c["libelle"] for c in charge["composantes"]} == {
        "taxes_a_remettre": "TPS/TVQ à remettre", "paies": "Paies", "das": "Déductions à la source (DAS)",
        "comptes_a_payer": "Comptes à payer", "dettes": "Dettes", "reserves": "Réserves critiques"}


def test_la_mention_les_hypotheses_et_les_reserves_suivent_la_donnee(taux):
    charge = _charge(taux)

    assert charge["mention"] == analyse.MENTION_ANALYSE_PREPARATOIRE
    assert charge["hypotheses"] == cash_libre.hypotheses() and len(charge["hypotheses"]) == 6


def test_un_deficit_est_publie_tel_quel_negatif_jamais_ramene_a_zero(taux):
    mouvements = _mouvements((("1000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00"),))
    zero_declare = {"montant": "0.00", "source": "aucune réserve voulue (fictif)", "au": "2026-09-25"}

    # 1000.00 - (1981.69 + 4200.00 + 1350.75 + 459.91 + 800.00 + réserves déclarées 0.00) = -7792.35
    charge = _charge(taux, mouvements=mouvements, reserves_declarees=zero_declare)

    assert charge["statut"] == "CALCULE" and charge["en_deficit"] is True
    assert charge["cash_libre_cad"] == "-7792.35"
    assert D("1000.00") - D("1981.69") - D("4200.00") - D("1350.75") - D("459.91") - D("800.00") == D("-7792.35")
    assert "C'est un déficit" in charge["lecture"]
    assert erreurs_charge(TYPE, charge) == []


# =========================================================================================
# 2. « Non calculable, manque X » : publié tel quel, jamais un zéro
# =========================================================================================
def test_sans_les_paies_le_constat_est_non_calculable_avec_son_manque_et_un_repere_qui_n_est_pas_de_l_argent(taux):
    sans_paies = {cle: valeur for cle, valeur in DECLARATIONS.items() if cle != "paies"}
    resultat = _calculer(taux, declarees=sans_paies)

    charge = constat_cash_libre.charge_evenement(resultat, JOUR, 1)

    assert charge["statut"] == "NON_CALCULABLE"
    assert charge["cash_libre_cad"] is None and charge["en_deficit"] is None
    assert charge["au_plus_cad"] == "32061.98", "37654.33 - 1981.69 - 1350.75 - 459.91 - 800.00 - 1000.00"
    assert D("37654.33") - D("1981.69") - D("1350.75") - D("459.91") - D("800.00") - D("1000.00") == D("32061.98")
    assert charge["manque"] == [{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}]
    paies = _par_id(charge)["paies"]
    assert (paies["statut"], paies["montant_cad"], paies["plancher_cad"]) == ("NON_CALCULABLE", None, None)
    assert paies["source"] == {"origine": "AUCUNE", "registres": []}
    assert paies["fraicheur"] == {"derniere_piece": None, "pieces": 0}
    assert "PAS de l'argent disponible" in charge["lecture"]
    assert erreurs_charge(TYPE, charge) == []


def test_sans_aucun_mouvement_le_solde_est_inconnu_et_aucun_repere_n_est_donne(taux):
    charge = _charge(taux, mouvements=registre.Registre())

    assert charge["statut"] == "NON_CALCULABLE" and charge["cash_libre_cad"] is None
    assert charge["au_plus_cad"] is None, "sans solde connu, aucun chiffre"
    assert (charge["solde"]["statut"], charge["solde"]["montant_cad"]) == ("NON_CALCULABLE", None)
    assert charge["manque"][0] == {"composante": "solde", "code": "REJ-CASH-SOLDE-ABSENT"}
    assert charge["lecture"] == (
        "Cash libre non calculable : le solde n'est pas connu (voir manque). Aucun chiffre n'est donné.")
    assert erreurs_charge(TYPE, charge) == []


def test_un_compte_a_payer_incomplet_publie_son_plancher_pas_un_total(taux):
    """Le PO-2 n'a aucun prix : l'attendu n'est pas calculable, le connu (les factures saisies) n'est qu'un
    plancher."""
    a_payer = _a_payer(taux, prix_du_po_2=None)
    resultat = _calculer(taux, a_payer=a_payer)

    charge = constat_cash_libre.charge_evenement(resultat, JOUR, 1)

    comptes = _par_id(charge)["comptes_a_payer"]
    assert comptes["statut"] == "NON_CALCULABLE" and comptes["montant_cad"] is None
    assert comptes["plancher_cad"] == "459.91", "les deux factures saisies (344.93 + 114.98) : un plancher"
    assert charge["statut"] == "NON_CALCULABLE" and charge["cash_libre_cad"] is None
    assert charge["manque"] == [{"composante": "comptes_a_payer", "code": "REJ-CASH-COMPTES-A-PAYER-INCOMPLETS"}]
    # le repère retranche le plancher : 37654.33 - 1981.69 - 4200.00 - 1350.75 - 459.91 - 800.00 - 1000.00
    assert charge["au_plus_cad"] == "27861.98"
    assert D("37654.33") - D("1981.69") - D("4200.00") - D("1350.75") - D("459.91") - D("800.00") - D("1000.00") \
        == D("27861.98")
    assert erreurs_charge(TYPE, charge) == []


def test_plusieurs_manques_sont_tous_publies_dans_l_ordre_de_la_definition(taux):
    charge = _charge(taux, declarees={})

    assert charge["statut"] == "NON_CALCULABLE"
    assert [(m["composante"], m["code"]) for m in charge["manque"]] == [
        ("paies", "REJ-CASH-PAIE-A-DECLARER"), ("das", "REJ-CASH-DAS-A-DECLARER"),
        ("dettes", "REJ-CASH-DETTES-A-DECLARER")]
    assert charge["au_plus_cad"] == "34212.73", "37654.33 - 1981.69 - 459.91 - 1000.00 : seul le connu est retranché"
    assert D("37654.33") - D("1981.69") - D("459.91") - D("1000.00") == D("34212.73")
    assert erreurs_charge(TYPE, charge) == []


def test_une_declaration_illisible_est_un_manque_par_code_sans_le_texte_qui_l_a_fait_refuser(taux):
    declarees = {**DECLARATIONS, "das": {"montant": "beaucoup", "source": "à Marc de le dire", "au": "2026-09-25"}}

    charge = _charge(taux, declarees=declarees)

    assert charge["manque"] == [{"composante": "das", "code": "REJ-CASH-DECLARATION-INVALIDE"}]
    texte = json.dumps(charge, ensure_ascii=False)
    assert "beaucoup" not in texte and "Marc" not in texte
    assert erreurs_charge(TYPE, charge) == []


# =========================================================================================
# 3. Rien de personnel ni de libre ne sort
# =========================================================================================
def test_le_texte_de_la_source_du_proprietaire_ne_sort_jamais_la_source_est_dite_par_son_origine(taux):
    charge = _charge(taux)
    texte = json.dumps(charge, ensure_ascii=False)

    for libre in ("Marc", "Tremblay", "Gagnon", "estimation du CPA", "prêt camion", "brouillon", "déclaration du"):
        assert libre not in texte, libre
    assert _par_id(charge)["paies"]["source"] == {"origine": "DECLARATION_PROPRIETAIRE", "registres": []}


def test_le_detail_d_une_composante_et_le_detail_d_un_verdict_ne_sortent_pas(taux):
    """Le détail des taxes (TPS, TVQ), les PO non calculables et le texte d'un verdict restent dans la lecture de
    `m5_etat_tresorerie`, réservée à l'admin."""
    for options in ({}, {"declarees": {}}, {"a_payer": _a_payer(taux, prix_du_po_2=None)}):
        charge = _charge(taux, **options)
        texte = json.dumps(charge, ensure_ascii=False)
        for interdit in ("detail", "depuis", "tps", "tvq", "po_non_calculables", "PO-1", "PO-2", "gentek", "F-1001",
                         "F-1", "C-1", "CH-1", "nathan", "Déclarer configuration", "aucun module de paie"):
            assert interdit not in texte, (interdit, options)
        for composante in [charge["solde"], *charge["composantes"]]:
            assert set(composante) == _CLES_COMPOSANTE and set(composante["source"]) == {"origine", "registres"}


def test_le_catalogue_refuse_un_texte_libre_dans_la_source_ou_un_champ_de_plus(taux):
    charge = _charge(taux)

    fautif = copy.deepcopy(charge)
    fautif["composantes"][1]["source"]["de"] = "déclaration du propriétaire : paie de Marc"
    assert erreurs_charge(TYPE, fautif)
    fautif = copy.deepcopy(charge)
    fautif["composantes"][0]["detail"] = {"tps": {"collectee": "676.67"}}
    assert erreurs_charge(TYPE, fautif)
    fautif = copy.deepcopy(charge)
    fautif["manque"] = [{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER", "detail": "Marc"}]
    assert erreurs_charge(TYPE, fautif)
    assert erreurs_charge(TYPE, {**charge, "client": "C-1"})


# =========================================================================================
# 4. L'identifiant et la trace
# =========================================================================================
def test_l_identifiant_est_deterministe_et_change_avec_le_rang_le_jour_et_la_version(taux):
    resultat = _calculer(taux)
    un = constat_cash_libre.charge_evenement(resultat, JOUR, 1)

    assert constat_cash_libre.charge_evenement(resultat, JOUR, 1)["evenement_id"] == un["evenement_id"]
    assert constat_cash_libre.charge_evenement(resultat, JOUR, 2)["evenement_id"] != un["evenement_id"]
    assert constat_cash_libre.charge_evenement(resultat, date(2026, 9, 30), 1)["evenement_id"] != un["evenement_id"]
    autre = _calculer(taux, declarees={**DECLARATIONS, "dettes": {**DECLARATIONS["dettes"], "montant": "801.00"}})
    assert constat_cash_libre.charge_evenement(autre, JOUR, 1)["evenement_id"] != un["evenement_id"]
    assert constat_cash_libre.identifiant(date(2026, 1, 5), 12, "ab" * 32) == (
        "m5-cash-libre-12-2026-01-05-abababababababab")


def test_la_meme_donnee_donne_la_meme_version_et_une_donnee_qui_change_une_autre(taux):
    version = _calculer(taux)["cash_libre_id"]

    assert _calculer(taux)["cash_libre_id"] == version
    assert _calculer(taux, declarees={**DECLARATIONS, "das": {**DECLARATIONS["das"], "au": "2026-09-26"}}
                     )["cash_libre_id"] != version, "la date d'une déclaration fait partie de la donnée"
    assert _calculer(taux, mouvements=_mouvements((("50000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00"),
                                                   ("1000.00", "PROVISION", "2026-09-10T12:00:00-04:00")))
                     )["cash_libre_id"] != version


def test_la_trace_ne_garde_que_l_en_tete_pas_un_montant(taux):
    charge = _charge(taux, sequence=3)

    trace = constat_cash_libre.construire_trace(charge)

    assert trace == {
        "type_entree": "cash_libre_constate", "sequence": 3, "date_reference": "2026-09-29",
        "version_donnees": charge["version_donnees"], "statut": "CALCULE", "evenement_id": charge["evenement_id"]}
    assert "27861.98" not in json.dumps(trace)


def test_le_resume_de_la_reponse_est_court_et_reprend_ce_qui_est_publie(taux):
    charge = _charge(taux, declarees={})

    resume = constat_cash_libre.resume(charge)

    assert set(resume) == {"evenement_id", "sequence", "date_reference", "version_donnees", "statut", "cash_libre_cad",
                           "au_plus_cad", "en_deficit", "lecture", "manque", "reserves"}
    assert all(resume[cle] == charge[cle] for cle in resume)
    assert resume["manque"] is not charge["manque"] and resume["reserves"] is not charge["reserves"]
    assert len(json.dumps(resume, ensure_ascii=False)) < 1500


# =========================================================================================
# 5. La date de référence : donnée par l'appelant, jamais devinée
# =========================================================================================
def test_la_date_de_reference_est_lue_strictement():
    assert constat_cash_libre.lire_jour("2026-09-29") == (date(2026, 9, 29), None)
    assert constat_cash_libre.lire_jour("2028-02-29") == (date(2028, 2, 29), None)


@pytest.mark.parametrize("brut", [
    "2026-9-29", "29/09/2026", "20260929", "2026-02-30", "2027-02-29", "2026-13-01", "2026-09-29T10:00:00-04:00",
    "2026-09-29 ", " 2026-09-29", "2026-09-29\n", "", "aujourd'hui", None, 20260929, 2026.0929, ["2026-09-29"],
    b"2026-09-29",
])
def test_une_date_qui_n_est_pas_exactement_aaaa_mm_jj_est_refusee_jamais_corrigee(brut):
    jour, verdict = constat_cash_libre.lire_jour(brut)

    assert jour is None and verdict["code"] == "REJ-CONSTAT-DATE-INVALIDE"
    assert verdict["code"] in validation.CODES_M5
    assert "AAAA-MM-JJ" in verdict["detail"]


def test_les_trois_codes_du_constat_sont_au_catalogue_des_verdicts_de_m5():
    assert {"REJ-CONSTAT-DATE-INVALIDE", "REJ-CONSTAT-COUTS-REQUIS", "REJ-CONSTAT-STOCKAGE-NON-DURABLE"} \
        <= set(validation.CODES_M5_LIST)


# =========================================================================================
# 6. Le catalogue : schéma fermé, versionné, qui impose lui-même les invariants
# =========================================================================================
def test_le_catalogue_du_socle_porte_le_type_et_son_schema_est_ferme_et_versionne():
    schema = evenements.schema(TYPE)

    assert schema["$id"] == f"opsys.evenement/v1/{TYPE}"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == _CLES
    composante = schema["$defs"]["composante"]
    assert composante["additionalProperties"] is False
    assert set(composante["required"]) == set(composante["properties"]) == _CLES_COMPOSANTE
    assert composante["properties"]["source"]["additionalProperties"] is False
    assert composante["properties"]["fraicheur"]["additionalProperties"] is False
    fichier = Path(evenements.schemas.__file__).parent / "catalogue" / f"{TYPE}.json"
    assert fichier.is_file() and TYPE in evenements.types_connus()


def test_la_mention_du_catalogue_est_celle_du_code_et_de_la_definition_produit():
    schema = evenements.schema(TYPE)
    definition = (_RACINE_DEPOT / "docs" / "produit" / "DEFINITION-PRODUIT.md").read_text(encoding="utf-8")

    assert schema["properties"]["mention"]["const"] == analyse.MENTION_ANALYSE_PREPARATOIRE
    assert f"*« {analyse.MENTION_ANALYSE_PREPARATOIRE} »*" in definition


def test_le_catalogue_est_ferme_et_refuse_un_champ_de_plus_ou_de_moins_ou_un_montant_json(taux):
    charge = _charge(taux)

    for champ in _CLES:
        sans = {cle: valeur for cle, valeur in charge.items() if cle != champ}
        assert erreurs_charge(TYPE, sans), champ
    for champ in _CLES_COMPOSANTE:
        fautif = copy.deepcopy(charge)
        del fautif["composantes"][2][champ]
        assert erreurs_charge(TYPE, fautif), champ
    assert erreurs_charge(TYPE, {**charge, "cash_libre_cad": 27861.98}), "un nombre JSON n'est pas un texte décimal"
    fautif = copy.deepcopy(charge)
    fautif["composantes"][1]["montant_cad"] = 4200.0
    assert erreurs_charge(TYPE, fautif)
    for texte in ("1e3", "1,000.00", " 12.00", "12.", ".5", "NaN", "Infinity", "12.00$", "", "--1"):
        assert erreurs_charge(TYPE, {**charge, "cash_libre_cad": texte}), texte
    assert erreurs_charge(TYPE, {**charge, "devise": "USD"})
    for sequence in (0, -1, "1", True, None):
        assert erreurs_charge(TYPE, {**charge, "sequence": sequence}), sequence
    assert erreurs_charge(TYPE, {**charge, "date_reference": "2026-9-29"})
    assert erreurs_charge(TYPE, {**charge, "version_donnees": "abc"})
    assert erreurs_charge(TYPE, {**charge, "evenement_id": "un-autre-identifiant"})
    assert erreurs_charge(TYPE, {**charge, "mention": "Analyse officielle."})
    assert erreurs_charge(TYPE, {**charge, "lecture": ""})
    assert erreurs_charge(TYPE, {**charge, "reserves": ["une phrase"]})
    assert erreurs_charge(TYPE, {**charge, "reserves": ["REJ-AP-X", "REJ-AP-X"]})


def test_le_catalogue_impose_l_ordre_et_le_nombre_des_six_composantes(taux):
    charge = _charge(taux)
    assert erreurs_charge(TYPE, charge) == []

    permutee = copy.deepcopy(charge)
    permutee["composantes"][0], permutee["composantes"][1] = permutee["composantes"][1], permutee["composantes"][0]
    assert erreurs_charge(TYPE, permutee)
    assert erreurs_charge(TYPE, {**charge, "composantes": charge["composantes"][:5]})
    assert erreurs_charge(TYPE, {**charge, "composantes": [*charge["composantes"], charge["composantes"][0]]})
    inconnue = copy.deepcopy(charge)
    inconnue["composantes"][3]["id"] = "impots_futurs"
    assert erreurs_charge(TYPE, inconnue)
    faux_solde = copy.deepcopy(charge)
    faux_solde["solde"]["id"] = "paies"
    assert erreurs_charge(TYPE, faux_solde), "le solde s'appelle solde"
    assert erreurs_charge(TYPE, {**charge, "solde": charge["composantes"][0]}), "le solde n'est pas une obligation"
    doublure = copy.deepcopy(charge)
    doublure["composantes"][2] = copy.deepcopy(doublure["composantes"][1])
    assert erreurs_charge(TYPE, doublure), "deux fois les paies, jamais les DAS"


def test_le_catalogue_refuse_un_calcule_qui_porte_un_manque_ou_une_composante_inconnue(taux):
    calcule = _charge(taux)
    assert erreurs_charge(TYPE, calcule) == []

    assert erreurs_charge(TYPE, {**calcule, "manque": [{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}]})
    assert erreurs_charge(TYPE, {**calcule, "cash_libre_cad": None}), "calculé sans cash libre"
    assert erreurs_charge(TYPE, {**calcule, "en_deficit": None})
    assert erreurs_charge(TYPE, {**calcule, "au_plus_cad": "100.00"}), "un repère n'existe que si c'est non calculable"
    fautif = copy.deepcopy(calcule)
    fautif["composantes"][1].update({"statut": "NON_CALCULABLE", "montant_cad": None})
    assert erreurs_charge(TYPE, fautif), "calculé alors qu'une composante ne l'est pas"
    fautif = copy.deepcopy(calcule)
    fautif["solde"].update({"statut": "NON_CALCULABLE", "montant_cad": None})
    assert erreurs_charge(TYPE, fautif), "calculé alors que le solde ne l'est pas"


def test_le_catalogue_refuse_un_non_calculable_qui_porte_un_cash_libre_ou_sans_manque(taux):
    sans_paies = {k: v for k, v in DECLARATIONS.items() if k != "paies"}
    non_calculable = _charge(taux, declarees=sans_paies)
    assert erreurs_charge(TYPE, non_calculable) == []

    assert erreurs_charge(TYPE, {**non_calculable, "cash_libre_cad": "27861.98"}), "un cash libre malgré le manque"
    assert erreurs_charge(TYPE, {**non_calculable, "en_deficit": False})
    assert erreurs_charge(TYPE, {**non_calculable, "manque": []}), "non calculable sans dire quoi demander"
    assert erreurs_charge(TYPE, {**non_calculable, "statut": "CALCULE"})
    assert erreurs_charge(TYPE, {**non_calculable, "au_plus_cad": None}), "le solde est connu : le repère aussi"
    fautif = copy.deepcopy(non_calculable)
    fautif["composantes"][1].update({"statut": "CALCULE", "montant_cad": "0.00"})
    assert erreurs_charge(TYPE, fautif), "non calculable alors que chaque composante est calculée"


def test_le_catalogue_refuse_un_repere_quand_le_solde_est_inconnu(taux):
    sans_solde = _charge(taux, mouvements=registre.Registre())
    assert erreurs_charge(TYPE, sans_solde) == []

    assert erreurs_charge(TYPE, {**sans_solde, "au_plus_cad": "100.00"})


def test_le_catalogue_impose_la_coherence_de_chaque_composante(taux):
    sans_paies = {k: v for k, v in DECLARATIONS.items() if k != "paies"}
    charge = _charge(taux, declarees=sans_paies)
    assert erreurs_charge(TYPE, charge) == []

    def fautif(index, modifier):
        copie = copy.deepcopy(charge)
        modifier(copie["composantes"][index])
        return erreurs_charge(TYPE, copie)

    assert fautif(1, lambda c: c.update({"montant_cad": "1.00"})), "non calculable avec un montant"
    assert fautif(0, lambda c: c.update({"montant_cad": None})), "calculé sans montant"
    assert fautif(0, lambda c: c.update({"plancher_cad": "1.00"})), "un plancher n'existe que sans montant"
    assert fautif(0, lambda c: c["source"].update({"origine": "DECLARATION_PROPRIETAIRE"})), "déclaration + registre"
    assert fautif(2, lambda c: c["source"].update({"origine": "REGISTRE"})), "un registre sans registre nommé"
    assert fautif(2, lambda c: c["source"].update({"origine": "AUCUNE"})), "aucune source mais un montant"
    assert fautif(1, lambda c: c["source"].update({"origine": "DECLARATION_PROPRIETAIRE"})), "déclaration sans montant"
    assert fautif(0, lambda c: c["source"].update({"origine": "VOISIN"}))
    assert fautif(0, lambda c: c["source"]["registres"][0].update({"tete": "zz"}))
    assert fautif(0, lambda c: c["source"]["registres"][0].update({"taille": -1}))
    assert fautif(0, lambda c: c["source"]["registres"][0].update({"registre": "Mouvements Principaux"}))
    assert fautif(0, lambda c: c["fraicheur"].update({"pieces": -1}))
    assert fautif(0, lambda c: c["fraicheur"].update({"derniere_piece": "x" * 41}))
    assert fautif(0, lambda c: c.update({"libelle": ""}))
    assert fautif(0, lambda c: c.update({"statut": "PEUT-ETRE"}))


def test_un_code_de_manque_est_un_code_de_verdict_jamais_une_phrase(taux):
    sans_paies = {k: v for k, v in DECLARATIONS.items() if k != "paies"}
    charge = _charge(taux, declarees=sans_paies)

    assert erreurs_charge(TYPE, {**charge, "manque": [{"composante": "paies", "code": "manque les paies"}]})
    assert erreurs_charge(TYPE, {**charge, "manque": [{"composante": "impots", "code": "REJ-CASH-PAIE-A-DECLARER"}]})
    doublon = {"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}
    assert erreurs_charge(TYPE, {**charge, "manque": [doublon, dict(doublon)]})
    assert {m["code"] for m in charge["manque"]} <= set(validation.CODES_M5)
