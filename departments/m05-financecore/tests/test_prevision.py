"""PLAN T4.16-d : la prévision de trésorerie des flux CONNUS et DATÉS (M5.7) : `prevision.py`, calcul pur, chiffré à la
cent près, sur les vrais registres en mémoire (jamais sur le code qu'il éprouve : les attendus sont des constantes).

Le cas de référence (fictif, AGENTS.md) est calculé ici À LA MAIN. Aujourd'hui : mardi 2026-09-29 ; six semaines de 7
jours (la semaine 1 va du 29 septembre au 5 octobre) ; délai de paiement des fournisseurs et d'encaissement des
clients : 30 jours (déclarés par le propriétaire : aucune échéance n'est enregistrée sur les factures).

    solde                      25000.00 - 5000.00 (réserve de 1000.00 : mouvement à part, hors solde)      = 20000.00
    factures clientes          C-1 4000.00 envoyée le 09-14 (4599.00 avec taxes) -> due le 10-14 (semaine 3)
                               C-2 2000.00 envoyée le 09-20 (2299.50)            -> due le 10-20 (semaine 4)
                               C-3 1000.00 envoyée le 08-20 (1149.75)            -> due le 09-19 : ÉCHUE, non comptée
                               C-4 brouillon, C-5 payée (300.00, sa taxe compte) -> aucun encaissement
    factures fournisseurs      F-1001 (PO-1) 344.93, du 09-14  -> due le 10-14 (semaine 3)
                               F-2001 (PO-2) 114.98, du 06-20  -> due le 07-20 : ÉCHUE, semaine 1
    attendu non facturé        PO-3 500.00 + 74.88 de taxes = 574.88, reçu le 09-17 -> 10-17 (semaine 3)
    taxes du trimestre         TPS 200.00 + 100.00 + 50.00 + 15.00 - 15.00 (crédit de F-1001)               = 350.00
    du 07-01 au 09-30          TVQ 399.00 + 199.50 + 99.75 + 29.93 - 29.93                                 = 698.25
    limite de paiement 11-02 (semaine 5), période non terminée                                              = 1048.25
    paies 4200.00 le 10-09 (semaine 2) ; DAS 1350.75 le 10-15 (semaine 3) ; dettes 800.00 le 10-31 (semaine 5)

    semaine 1 : sorties 114.98                                        20000.00 - 114.98            = 19885.02
    semaine 2 : sorties 4200.00                                       19885.02 - 4200.00           = 15685.02
    semaine 3 : entrées 4599.00, sorties 344.93 + 1350.75 + 574.88    15685.02 + 4599.00 - 2270.56 = 18013.46
    semaine 4 : entrées 2299.50                                       18013.46 + 2299.50           = 20312.96
    semaine 5 : sorties 800.00 + 1048.25                              20312.96 - 1848.25           = 18464.71
    semaine 6 : rien                                                                               = 18464.71

    cash libre d'aujourd'hui (T4.16)   20000.00 - (1048.25 + 4200.00 + 1350.75 + 1034.79 + 800.00 + 1000.00) = 10566.21
    cash libre prévu = cash libre + encaissements tombés : 10566.21 (semaines 1 et 2), 15165.21 (3), 17464.71 (4 à 6)

Ce qui est éprouvé : les soldes semaine par semaine, l'alerte contre un seuil fourni, « non calculable à partir de la
semaine X, manque Y » (jamais zéro, jamais une moyenne), la prudence des encaissements, le déterminisme et la forme JSON
de la réponse. Le branchement sur les vrais registres durables est dans test_prevision_outils.py.
"""

from __future__ import annotations

import copy
import json
import random
import re
from datetime import date, timedelta
from decimal import Decimal, Inexact, Rounded, localcontext
from pathlib import Path

import pytest
from m5_financecore import (
    calendrier_fiscal,
    cash_libre,
    facturation,
    prevision,
    registre,
    soldes,
    taux_fiscaux,
    validation,
)
from m5_financecore import comptes_a_payer as cap
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION

FICTIF = True
D = Decimal
_RACINE_M5 = Path(__file__).resolve().parents[1]
AUJOURD_HUI = date(2026, 9, 29)
FISCAL = {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"}
DECLARATIONS = {
    "paies": {"montant": "4200.00", "source": "brouillon de paie du 2026-09-25 (fictif)", "au": "2026-09-25"},
    "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
    "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
}
ECHEANCES = {"paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"}
SEUIL = {"montant": "16000.00", "source": "décision de Nathan (fictive)", "au": "2026-09-25"}
_CODE_DELAI_CLIENTS = "REJ-PREVISION-DELAI-CLIENTS-A-DECLARER"
_CODE_DELAI_FOURNISSEURS = "REJ-PREVISION-DELAI-FOURNISSEURS-A-DECLARER"


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_RACINE_M5 / "contracts" / "taux_fiscaux.v1.yaml")
    assert erreurs == []
    return dictionnaire


@pytest.fixture(scope="module")
def calendrier():
    donnees, erreurs = calendrier_fiscal.charger_calendrier_fiscal(
        _RACINE_M5 / "contracts" / "calendrier_fiscal.v1.yaml")
    assert erreurs == []
    return donnees


# ---------------------------------------------------------------------------------------- les registres fictifs
def _mouvements():
    reg = registre.Registre()
    for montant, type_mouvement, horodatage in (
        ("25000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00"),
        ("-5000.00", "DECAISSEMENT", "2026-08-15T12:00:00-04:00"),
        ("1000.00", "PROVISION", "2026-09-10T12:00:00-04:00"),
    ):
        registre.enregistrer_mouvement({"montant": D(montant), "type_mouvement": type_mouvement,
                                        "horodatage": horodatage, "classe_retention": "STANDARD",
                                        "source": "test"}, reg)
    return reg


def _factures(taux, lignes=None):
    reg = registre.Registre()
    lignes = lignes if lignes is not None else (
        ("C-1", "D-1", "4000.00", "2026-09-14", "ENVOYEE"),
        ("C-2", "D-2", "2000.00", "2026-09-20", "ENVOYEE"),
        ("C-3", "D-3", "1000.00", "2026-08-20", "ENVOYEE"),   # échue : due le 2026-09-19
        ("C-4", "D-4", "500.00", "2026-09-01", "BROUILLON"),  # jamais envoyée : ni taxe ni encaissement
        ("C-5", "D-5", "300.00", "2026-08-01", "PAYEE"),      # payée : sa taxe compte, pas de créance
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
            assert facturation.marquer_facture_payee(facture_id, "nathan", "2026-08-20T09:00:00-04:00", reg)[1] is None
    return reg


def _charge(evenement_id, po_id, quantite, horodatage, prix="5.00"):
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": horodatage, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": quantite, "quantite_recue": quantite,
                    "prix_unitaire_prevu": prix, "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": prix, "verdict_prix_reception": "PRIX_CATALOGUE",
                    "ecart_prix_critique": False}],
    }


def _a_payer(taux, receptions=None, factures=None):
    """PO-1 : 300.00 reçus et facturés (344.93). PO-2 : 100.00, facture du 2026-06-20 (114.98). PO-3 : 500.00 reçus,
    pas encore facturés (attendu 574.88)."""
    reg = registre.Registre()
    receptions = receptions if receptions is not None else (
        ("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),
        ("e-2", "PO-2", "20", "2026-09-16T09:00:00-04:00"),
        ("e-3", "PO-3", "100", "2026-09-17T09:00:00-04:00"),
    )
    for evenement, po, quantite, horodatage in receptions:
        entree, verdict = cap.construire_reception(_charge(evenement, po, quantite, horodatage))
        assert verdict is None, verdict
        assert cap.enregistrer_reception(entree, reg)[1] is None
    factures = factures if factures is not None else (
        ("PO-1", "F-1001", "2026-09-14", "300.00"), ("PO-2", "F-2001", "2026-06-20", "100.00"))
    for po, numero, jour, montant in factures:
        _, verdict = cap.saisir_facture_fournisseur(
            po_id=po, fournisseur_id="gentek", numero_facture=numero, date_facture=jour, montant_avant_taxes=montant,
            total_facture=None, saisi_par="nathan", voie="appareil", horodatage="2026-09-20T10:00:00-04:00",
            dictionnaire_taux=taux, registre_cible=reg)
        assert verdict is None, verdict
    return reg


def _cash_libre(taux, mouvements, factures, a_payer, declarees=DECLARATIONS, remises=date(2026, 6, 30)):
    """Ce que `outils._resultat_cash_libre` fait, avec des registres en mémoire."""
    solde = soldes.calculer_solde(mouvements)
    decrit = soldes.decrire_mouvements(mouvements)
    provisions, nombre, derniere = soldes.calculer_provisions(mouvements)
    clients = _clients(factures)
    resume, verdict_ap = cap.resume_a_payer(a_payer, taux)
    registres = [cash_libre.registre_lu("factures", factures.lire()),
                 cash_libre.registre_lu("comptes_a_payer", a_payer.lire())]
    return cash_libre.calculer_cash_libre(
        cash_libre.composante_solde(solde, decrit),
        [
            cash_libre.composante_taxes(clients, cap.factures_saisies(a_payer), remises, None, registres),
            cash_libre.composante_declaree("paies", declarees.get("paies")),
            cash_libre.composante_declaree("das", declarees.get("das")),
            cash_libre.composante_comptes_a_payer(resume, verdict_ap, registres[1:]),
            cash_libre.composante_declaree("dettes", declarees.get("dettes")),
            cash_libre.composante_reserves(provisions, nombre, derniere, decrit, None),
        ],
    )


def _clients(factures):
    return [*facturation.factures_par_statut(factures, "ENVOYEE"), *facturation.factures_par_statut(factures, "PAYEE")]


def _prevoir(taux, calendrier, *, horizon=6, delai_clients=30, delai_fournisseurs=30, echeances=ECHEANCES,
             declarees=DECLARATIONS, fiscal=FISCAL, seuil=SEUIL, mouvements=None, factures=None, a_payer=None,
             aujourd_hui=AUJOURD_HUI, melanger=None, flux_en_plus=()):
    """Ce que `outils._prevision` fait : les quatre familles de flux, puis l'assemblage. `melanger` : une graine qui
    change l'ordre d'entrée des flux (le résultat n'en dépend pas)."""
    mouvements = _mouvements() if mouvements is None else mouvements
    factures = _factures(taux) if factures is None else factures
    a_payer = _a_payer(taux) if a_payer is None else a_payer
    cash = _cash_libre(taux, mouvements, factures, a_payer, declarees)
    delai_c, verdict_c = prevision.lire_delai(delai_clients, "delai_encaissement_clients_jours", _CODE_DELAI_CLIENTS)
    delai_f, verdict_f = prevision.lire_delai(delai_fournisseurs, "delai_paiement_fournisseurs_jours",
                                              _CODE_DELAI_FOURNISSEURS)
    dettes, verdict_dettes = cap.dettes_datables(a_payer, taux)
    flux = [
        *prevision.flux_clients(facturation.factures_par_statut(factures, "ENVOYEE"), delai_c, verdict_c),
        *prevision.flux_fournisseurs(dettes, delai_f, verdict_f, verdict_dettes),
        *prevision.flux_taxes(_clients(factures), cap.factures_saisies(a_payer), calendrier, None, fiscal,
                              aujourd_hui),
        *prevision.flux_obligations({c["id"]: c for c in cash["composantes"]},
                                    prevision.lire_echeances_obligations(echeances)),
        *flux_en_plus,
    ]
    if melanger is not None:
        random.Random(melanger).shuffle(flux)
    seuil_lu, verdict_seuil = prevision.lire_seuil(seuil)
    return prevision.assembler(aujourd_hui, horizon, cash["solde"], flux, seuil=seuil_lu, verdict_seuil=verdict_seuil,
                               cash_libre_resultat=cash)


def _semaines(resultat):
    return {s["semaine"]: s for s in resultat["semaines"]}


def _soldes(resultat):
    return [s["solde_fin"] for s in resultat["semaines"]]


def _codes(resultat):
    return {g["code"]: g for g in resultat["manque"]}


# ======================================================================================= 1. le cas fictif chiffré
def test_le_cas_fictif_est_chiffre_a_la_cent_pres_semaine_par_semaine(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    assert resultat["calculable"] is True and resultat["non_calculable_a_partir_de"] is None
    assert resultat["manque"] == []
    assert resultat["solde"]["montant"] == D("20000.00")
    assert [(s["semaine"], s["statut"]) for s in resultat["semaines"]] == [(k, "CALCULE") for k in range(1, 7)]
    assert [(s["entrees"], s["sorties"], s["solde_fin"]) for s in resultat["semaines"]] == [
        (D("0.00"), D("114.98"), D("19885.02")),
        (D("0.00"), D("4200.00"), D("15685.02")),
        (D("4599.00"), D("2270.56"), D("18013.46")),
        (D("2299.50"), D("0.00"), D("20312.96")),
        (D("0.00"), D("1848.25"), D("18464.71")),
        (D("0.00"), D("0.00"), D("18464.71")),
    ]
    # les soldes de début s'enchaînent : la fin d'une semaine est le début de la suivante
    assert [s["solde_debut"] for s in resultat["semaines"]] == [D("20000.00"), *_soldes(resultat)[:-1]]
    # refait à la main, sans le code : 20000.00 - 114.98 - 4200.00 + 4599.00 - 2270.56 + 2299.50 - 1848.25
    assert D("20000.00") - D("114.98") - D("4200.00") + D("4599.00") - D("2270.56") + D("2299.50") - D("1848.25") == (
        D("18464.71"))


def test_chaque_semaine_a_ses_dates_de_sept_jours_a_partir_d_aujourd_hui(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    assert (resultat["aujourd_hui"], resultat["horizon_semaines"], resultat["fin_horizon"]) == (
        date(2026, 9, 29), 6, date(2026, 11, 9))
    assert [(s["debut"], s["fin"]) for s in resultat["semaines"]] == [
        (date(2026, 9, 29), date(2026, 10, 5)), (date(2026, 10, 6), date(2026, 10, 12)),
        (date(2026, 10, 13), date(2026, 10, 19)), (date(2026, 10, 20), date(2026, 10, 26)),
        (date(2026, 10, 27), date(2026, 11, 2)), (date(2026, 11, 3), date(2026, 11, 9))]


def test_l_alerte_du_cas_fictif_est_en_semaine_2_seulement(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    alerte = resultat["alerte"]
    assert alerte["statut"] == "ALERTE" and alerte["semaines"] == [2] and alerte["premiere_semaine"] == 2
    assert alerte["seuil"] == D("16000.00") and alerte["manque"] is None
    assert alerte["source_du_seuil"] == {"source": "décision de Nathan (fictive)", "au": date(2026, 9, 25)}
    assert alerte["non_evaluee_a_partir_de"] is None
    assert [s["sous_seuil"] for s in resultat["semaines"]] == [False, True, False, False, False, False]
    assert resultat["plus_bas"] == {"semaine": 2, "solde": D("15685.02")}
    assert resultat["premiere_semaine_en_deficit"] is None
    assert [s["en_deficit"] for s in resultat["semaines"]] == [False] * 6


def test_le_cash_libre_prevu_part_du_cash_libre_de_t4_16_et_n_ajoute_que_les_encaissements(taux, calendrier):
    """Les obligations sont DÉJÀ retranchées du cash libre : les retrancher encore à leur échéance les compterait deux
    fois. `cash_libre_prevu` = cash libre d'aujourd'hui + encaissements tombés."""
    resultat = _prevoir(taux, calendrier)

    assert resultat["cash_libre"]["montant"] == D("10566.21") and resultat["cash_libre"]["manque"] == []
    assert [s["cash_libre_prevu"] for s in resultat["semaines"]] == [
        D("10566.21"), D("10566.21"), D("15165.21"), D("17464.71"), D("17464.71"), D("17464.71")]
    # refait à la main : 10566.21 + 4599.00 = 15165.21 ; + 2299.50 = 17464.71
    assert D("10566.21") + D("4599.00") == D("15165.21") and D("15165.21") + D("2299.50") == D("17464.71")


def test_toutes_les_obligations_sorties_le_solde_moins_les_reserves_est_le_cash_libre_prevu(taux, calendrier):
    """La preuve que rien n'est compté deux fois : en semaine 5, tout ce qui était retranché du cash libre (taxes,
    paies, DAS, comptes à payer, dettes) est sorti du compte. Ne reste que la réserve de 1000.00, qui ne sort jamais :
    solde 18464.71 - réserves 1000.00 = cash libre prévu 17464.71."""
    resultat = _prevoir(taux, calendrier)

    dernier = resultat["semaines"][-1]
    assert dernier["solde_fin"] - D("1000.00") == dernier["cash_libre_prevu"] == D("17464.71")


def test_les_lignes_de_chaque_semaine_portent_leur_source_leur_date_et_la_regle_de_cette_date(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    assert {k: len(s["lignes"]) for k, s in _semaines(resultat).items()} == {1: 1, 2: 1, 3: 4, 4: 1, 5: 2, 6: 0}
    for semaine in resultat["semaines"]:
        for ligne in semaine["lignes"]:
            assert ligne["source"] and ligne["regle_de_date"], ligne["id"]
            assert semaine["debut"] <= ligne["date"] <= semaine["fin"] or ligne["echu"], ligne["id"]
    encaissement = next(f for f in _semaines(resultat)[3]["lignes"] if f["id"] == "client:C-1")
    assert (encaissement["sens"], encaissement["nature"], encaissement["montant"], encaissement["date"]) == (
        "ENTREE", "facture_client", D("4599.00"), date(2026, 10, 14))
    assert encaissement["source"] == "facture client C-1 envoyée le 2026-09-14"
    assert encaissement["regle_de_date"] == "envoi du 2026-09-14 + 30 jours (délai déclaré par le propriétaire)"


def test_les_dates_viennent_de_leur_source_ni_devinees_ni_uniformes(taux, calendrier):
    resultat = _prevoir(taux, calendrier)
    lignes = {f["id"]: f for s in resultat["semaines"] for f in s["lignes"]}
    apf = {f["source"]: f for f in lignes.values() if f["nature"] == "facture_fournisseur"}

    assert lignes["client:C-1"]["date"] == date(2026, 10, 14) and lignes["client:C-2"]["date"] == date(2026, 10, 20)
    assert apf["facture fournisseur gentek n° F-1001 du 2026-09-14"]["date"] == date(2026, 10, 14)
    assert apf["facture fournisseur gentek n° F-2001 du 2026-06-20"]["date"] == date(2026, 7, 20)
    assert lignes["attendu:PO-3"]["date"] == date(2026, 10, 17)
    assert lignes["attendu:PO-3"]["source"] == "attendu non facturé du PO PO-3, première réception le 2026-09-17"
    assert lignes["obligation:paies"]["date"] == date(2026, 10, 9)
    assert lignes["obligation:das"]["date"] == date(2026, 10, 15)
    assert lignes["obligation:dettes"]["date"] == date(2026, 10, 31)
    taxes = lignes["taxes:2026-07-01:2026-09-30"]
    assert (taxes["montant"], taxes["date"]) == (D("1048.25"), date(2026, 11, 2))
    assert taxes["regle_de_date"] == "limite de paiement du calendrier fiscal 2026-v1 (à valider par le CPA)"
    assert taxes["source"].startswith(
        "TPS/TVQ nette de la période du 2026-07-01 au 2026-09-30 : TPS 350.00 + TVQ 698.25")
    assert "période non terminée" in taxes["source"] and taxes["partielle"] is True
    assert lignes["obligation:paies"]["source"].startswith("déclaration du propriétaire")


def test_une_facture_echue_tombe_en_semaine_1_et_le_dit(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    echue = next(f for f in _semaines(resultat)[1]["lignes"] if f["nature"] == "facture_fournisseur")
    assert echue["echu"] is True and echue["montant"] == D("114.98") and echue["date"] == date(2026, 7, 20)
    a_venir = [f for s in resultat["semaines"] for f in s["lignes"] if f["nature"] == "facture_fournisseur"
               and f["id"] != echue["id"]]
    assert [f["echu"] for f in a_venir] == [False]


def test_l_attendu_non_facture_porte_la_reserve_de_l_unite_des_prix_et_pas_la_facture_saisie(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    lignes = {f["id"]: f for s in resultat["semaines"] for f in s["lignes"]}
    assert lignes["attendu:PO-3"]["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert all(f["reserves"] == [] for i, f in lignes.items() if i != "attendu:PO-3")
    assert resultat["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]


def test_un_encaissement_echu_n_est_pas_compte_et_est_dit_avec_son_montant(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    assert resultat["encaissements_non_comptes"] == [{
        "code": "REJ-PREVISION-ENCAISSEMENT-ECHU", "nombre": 1, "montant_connu": D("1149.75"), "flux": ["client:C-3"]}]
    assert all(f["id"] != "client:C-3" for s in resultat["semaines"] for f in s["lignes"])


def test_seule_une_facture_cliente_envoyee_est_une_creance(taux, calendrier):
    """C-4 (brouillon) n'est pas due ; C-5 (payée) ne l'est plus : ni l'une ni l'autre n'est un encaissement, même si la
    taxe de la seconde compte au cash libre."""
    resultat = _prevoir(taux, calendrier)

    ids = {f["id"] for s in resultat["semaines"] for f in s["lignes"]}
    ids |= {i for g in resultat["encaissements_non_comptes"] for i in g["flux"]}
    assert {i for i in ids if i.startswith("client:")} == {"client:C-1", "client:C-2", "client:C-3"}


def test_au_dela_de_l_horizon_les_flux_ne_sont_qu_agreges(taux, calendrier):
    """Sur quatre semaines, les dettes (10-31) et les taxes (11-02) tombent après l'horizon (fin le 10-26) : elles ne
    sont pas placées, ni comptées dans un solde, mais dites."""
    resultat = _prevoir(taux, calendrier, horizon=4)

    assert resultat["fin_horizon"] == date(2026, 10, 26)
    assert _soldes(resultat) == [D("19885.02"), D("15685.02"), D("18013.46"), D("20312.96")]
    assert resultat["au_dela_de_l_horizon"]["sorties"] == {"nombre": 2, "total": D("1848.25"), "non_chiffres": 0}
    assert resultat["au_dela_de_l_horizon"]["entrees"] == {"nombre": 0, "total": D("0.00"), "non_chiffres": 0}
    assert resultat["calculable"] is True


def test_un_encaissement_au_dela_de_l_horizon_est_agrege_pas_place(taux, calendrier):
    factures = _factures(taux, (("C-9", "D-9", "1000.00", "2026-10-15", "ENVOYEE"),))

    resultat = _prevoir(taux, calendrier, horizon=4, factures=factures)

    # envoyée le 10-15 + 30 jours = 11-14 : après la fin de l'horizon (10-26)
    assert resultat["au_dela_de_l_horizon"]["entrees"] == {"nombre": 1, "total": D("1149.75"), "non_chiffres": 0}
    assert all(s["entrees"] == D("0.00") for s in resultat["semaines"])


# ================================================================================ 2. les semaines : les jours-limites
def _flux(identifiant, sens, montant, jour, nature="autre"):
    return {"id": identifiant, "sens": sens, "nature": nature, "montant": D(montant), "date": jour,
            "regle_de_date": "test", "source": "test", "manque": [], "reserves": []}


def _solde(montant="1000.00"):
    return {"id": "solde", "montant": D(montant), "manque": [], "source": {"description": "test", "registres": []},
            "fraicheur": {"derniere_piece": None, "pieces": 0}}


def _assembler(flux, *, horizon=3, seuil=None, verdict_seuil=None, solde=None, cash=None):
    if seuil is None and verdict_seuil is None:
        verdict_seuil = validation.construire_verdict("REJ-PREVISION-SEUIL-A-CONFIGURER", "test")
    return prevision.assembler(AUJOURD_HUI, horizon, solde or _solde(), flux, seuil=seuil, verdict_seuil=verdict_seuil,
                               cash_libre_resultat=cash)


@pytest.mark.parametrize("jour, semaine", [
    (AUJOURD_HUI, 1), (AUJOURD_HUI + timedelta(days=6), 1), (AUJOURD_HUI + timedelta(days=7), 2),
    (AUJOURD_HUI + timedelta(days=13), 2), (AUJOURD_HUI + timedelta(days=14), 3),
    (AUJOURD_HUI + timedelta(days=20), 3),
])
def test_une_sortie_tombe_dans_la_semaine_de_sept_jours_qui_contient_sa_date(jour, semaine):
    resultat = _assembler([_flux("x", prevision.SORTIE, "10.00", jour)])

    placees = {s["semaine"] for s in resultat["semaines"] if s["lignes"]}
    assert placees == {semaine}
    assert resultat["semaines"][semaine - 1]["sorties"] == D("10.00")


def test_prevision_preserve_les_cents_sous_contexte_decimal_externe_restrictif():
    with localcontext() as contexte:
        contexte.prec = 8
        contexte.traps[Inexact] = True
        contexte.traps[Rounded] = True
        resultat = _assembler(
            [_flux("sortie-collision", prevision.SORTIE, "100000000.00", AUJOURD_HUI)],
            solde=_solde("100000000.01"),
        )

    assert resultat["semaines"][0]["solde_fin"] == D("0.01")


def test_le_lendemain_de_la_derniere_semaine_est_au_dela_de_l_horizon_et_la_veille_d_aujourd_hui_est_echue():
    derniere = AUJOURD_HUI + timedelta(days=20)
    resultat = _assembler([
        _flux("dedans", prevision.SORTIE, "1.00", derniere), _flux("dehors", prevision.SORTIE, "2.00",
                                                                  derniere + timedelta(days=1)),
        _flux("hier", prevision.SORTIE, "4.00", AUJOURD_HUI - timedelta(days=1)),
    ])

    assert resultat["semaines"][2]["sorties"] == D("1.00")
    assert resultat["au_dela_de_l_horizon"]["sorties"]["total"] == D("2.00")
    assert resultat["semaines"][0]["sorties"] == D("4.00")
    assert resultat["semaines"][0]["lignes"][0]["echu"] is True
    assert not any(f["echu"] for s in resultat["semaines"][1:] for f in s["lignes"])


def test_une_entree_du_jour_meme_est_comptee_en_semaine_1_celle_d_hier_ne_l_est_pas():
    resultat = _assembler([
        _flux("auj", prevision.ENTREE, "10.00", AUJOURD_HUI), _flux("hier", prevision.ENTREE, "20.00",
                                                                  AUJOURD_HUI - timedelta(days=1)),
    ])

    assert resultat["semaines"][0]["entrees"] == D("10.00")
    assert [g["code"] for g in resultat["encaissements_non_comptes"]] == ["REJ-PREVISION-ENCAISSEMENT-ECHU"]
    assert resultat["encaissements_non_comptes"][0]["montant_connu"] == D("20.00")


def test_une_entree_et_une_sortie_de_la_meme_semaine_se_compensent_dans_le_solde_de_fin_de_semaine():
    resultat = _assembler([
        _flux("e", prevision.ENTREE, "300.00", AUJOURD_HUI + timedelta(days=5)),
        _flux("s", prevision.SORTIE, "1200.00", AUJOURD_HUI + timedelta(days=1)),
    ])

    assert resultat["semaines"][0]["solde_fin"] == D("100.00")
    assert resultat["semaines"][0]["entrees"] == D("300.00") and resultat["semaines"][0]["sorties"] == D("1200.00")


# ========================================================================================= 3. l'alerte, déterministe
@pytest.mark.parametrize("seuil, alerte", [
    ("15685.01", False), ("15685.02", False),   # égal : le solde ne passe pas SOUS le seuil
    ("15685.03", True), ("16000.00", True),
])
def test_l_alerte_est_strictement_sous_le_seuil_au_cent_pres(taux, calendrier, seuil, alerte):
    resultat = _prevoir(taux, calendrier, seuil={**SEUIL, "montant": seuil})

    assert (resultat["semaines"][1]["sous_seuil"], 2 in resultat["alerte"]["semaines"]) == (alerte, alerte)
    assert resultat["alerte"]["statut"] == ("ALERTE" if alerte else "AUCUNE")


def test_un_seuil_de_zero_declare_est_un_seuil_connu_qui_n_alerte_que_sous_zero(taux, calendrier):
    resultat = _prevoir(taux, calendrier, seuil={**SEUIL, "montant": "0.00"})

    assert resultat["alerte"]["statut"] == "AUCUNE" and resultat["alerte"]["seuil"] == D("0.00")
    assert [s["sous_seuil"] for s in resultat["semaines"]] == [False] * 6


def test_un_seuil_haut_alerte_chaque_semaine_sous_le_seuil_et_les_liste_dans_l_ordre(taux, calendrier):
    resultat = _prevoir(taux, calendrier, seuil={**SEUIL, "montant": "19000.00"})

    # 19885.02, 15685.02, 18013.46, 20312.96, 18464.71, 18464.71 : sous 19000.00 aux semaines 2, 3, 5 et 6
    assert resultat["alerte"]["semaines"] == [2, 3, 5, 6] and resultat["alerte"]["premiere_semaine"] == 2


@pytest.mark.parametrize("seuil, code", [
    (None, "REJ-PREVISION-SEUIL-A-CONFIGURER"),
    ({"montant": "1000", "source": "x"}, "REJ-PREVISION-SEUIL-INVALIDE"),
])
def test_sans_seuil_l_alerte_dit_seuil_a_configurer_et_n_en_invente_aucun(taux, calendrier, seuil, code):
    resultat = _prevoir(taux, calendrier, seuil=seuil)

    alerte = resultat["alerte"]
    assert alerte["statut"] == "SEUIL_A_CONFIGURER" and alerte["seuil"] is None and alerte["semaines"] == []
    assert alerte["premiere_semaine"] is None and alerte["manque"]["code"] == code
    assert all(s["sous_seuil"] is None for s in resultat["semaines"]), "aucune semaine n'est jugée sans seuil"
    assert _soldes(resultat)[1] == D("15685.02"), "le calcul des soldes n'en dépend pas"


def test_un_solde_negatif_est_rendu_tel_quel_c_est_un_fait_pas_une_alerte(taux, calendrier):
    petit = registre.Registre()
    registre.enregistrer_mouvement({"montant": D("1000.00"), "type_mouvement": "ENCAISSEMENT",
                                    "horodatage": "2026-08-01T12:00:00-04:00", "classe_retention": "STANDARD",
                                    "source": "test"}, petit)
    resultat = _prevoir(taux, calendrier, seuil=None, mouvements=petit)

    # 1000.00 - 114.98 = 885.02 ; - 4200.00 = -3314.98 (déficit dès la semaine 2) ; + 2328.44 = -986.54
    assert resultat["semaines"][1]["solde_fin"] == D("-3314.98") and resultat["semaines"][1]["en_deficit"] is True
    assert resultat["semaines"][0]["en_deficit"] is False
    assert resultat["premiere_semaine_en_deficit"] == 2
    assert resultat["semaines"][2]["solde_fin"] == D("-986.54")
    assert resultat["plus_bas"] == {"semaine": 2, "solde": D("-3314.98")}
    assert resultat["alerte"]["statut"] == "SEUIL_A_CONFIGURER", "le déficit n'a pas besoin d'un seuil, l'alerte si"


def test_le_plus_bas_solde_prend_la_premiere_semaine_en_cas_d_egalite():
    resultat = _assembler([_flux("s", prevision.SORTIE, "100.00", AUJOURD_HUI)], horizon=3)

    assert _soldes(resultat) == [D("900.00")] * 3
    assert resultat["plus_bas"] == {"semaine": 1, "solde": D("900.00")}


# ===================================== 4. une donnée inconnue : non calculable à partir de la semaine X, manque Y
def test_des_dettes_non_declarees_bloquent_a_partir_de_leur_semaine_les_precedentes_restent_exactes(
        taux, calendrier):
    """Le montant des dettes n'est pas déclaré, leur date l'est (10-31 : semaine 5) : les semaines 1 à 4 sont celles du
    cas fictif, à la cent près ; la semaine 5 et la suivante sont non calculables. Jamais zéro."""
    declarees = {k: v for k, v in DECLARATIONS.items() if k != "dettes"}

    resultat = _prevoir(taux, calendrier, declarees=declarees)

    assert resultat["calculable"] is False and resultat["non_calculable_a_partir_de"] == 5
    assert _soldes(resultat)[:4] == [D("19885.02"), D("15685.02"), D("18013.46"), D("20312.96")]
    for semaine in (5, 6):
        ligne = _semaines(resultat)[semaine]
        assert ligne["statut"] == "NON_CALCULABLE"
        assert (ligne["solde_debut"], ligne["entrees"], ligne["sorties"], ligne["solde_fin"],
                ligne["cash_libre_prevu"], ligne["sous_seuil"], ligne["en_deficit"]) == (None,) * 7
    assert list(_codes(resultat)) == ["REJ-CASH-DETTES-A-DECLARER"]
    assert _codes(resultat)["REJ-CASH-DETTES-A-DECLARER"]["a_partir_de_semaine"] == 5
    assert _codes(resultat)["REJ-CASH-DETTES-A-DECLARER"]["flux"] == ["obligation:dettes"]
    assert resultat["plus_bas"] == {"semaine": 2, "solde": D("15685.02")}
    assert resultat["alerte"]["statut"] == "ALERTE" and resultat["alerte"]["semaines"] == [2]
    assert resultat["alerte"]["non_evaluee_a_partir_de"] == 5


def test_le_cash_libre_non_calculable_ne_donne_aucun_cash_libre_prevu_mais_pas_de_solde_inconnu(taux, calendrier):
    declarees = {k: v for k, v in DECLARATIONS.items() if k != "das"}

    resultat = _prevoir(taux, calendrier, declarees=declarees)

    assert resultat["cash_libre"]["montant"] is None
    assert resultat["cash_libre"]["manque"] == [{"composante": "das", "code": "REJ-CASH-DAS-A-DECLARER"}]
    # le DAS est daté du 10-15 (semaine 3), mais son montant est inconnu : les semaines 1 et 2 sont exactes et donnent
    # un solde, sans cash libre prévu (le cash libre est inconnu)
    assert resultat["non_calculable_a_partir_de"] == 3
    assert [s["solde_fin"] for s in resultat["semaines"][:2]] == [D("19885.02"), D("15685.02")]
    assert [s["cash_libre_prevu"] for s in resultat["semaines"][:2]] == [None, None]


def test_sans_delai_fournisseurs_toute_la_prevision_est_non_calculable_des_la_semaine_1(taux, calendrier):
    resultat = _prevoir(taux, calendrier, delai_fournisseurs=None)

    assert resultat["non_calculable_a_partir_de"] == 1 and resultat["calculable"] is False
    assert all(s["statut"] == "NON_CALCULABLE" and s["solde_fin"] is None for s in resultat["semaines"])
    groupe = _codes(resultat)[_CODE_DELAI_FOURNISSEURS]
    assert groupe["a_partir_de_semaine"] == 1
    # les trois dettes : deux factures et l'attendu du PO-3, aucune date n'est inventée
    assert sorted(groupe["flux"]) == ["attendu:PO-3", "fournisseur:apf-5d6572e6e42f26fe12c4",
                                      "fournisseur:apf-e16a52130c0e36cefd4a"]
    assert "configuration.prevision.delai_paiement_fournisseurs_jours" in groupe["detail"]
    assert resultat["plus_bas"] is None and resultat["alerte"]["statut"] == "NON_EVALUEE"
    assert resultat["alerte"]["non_evaluee_a_partir_de"] == 1


def test_sans_date_de_derniere_remise_les_taxes_sont_inconnues_des_la_semaine_1(taux, calendrier):
    fiscal = {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12}

    resultat = _prevoir(taux, calendrier, fiscal=fiscal)

    assert resultat["non_calculable_a_partir_de"] == 1
    assert _codes(resultat)["REJ-FISCAL-REMISE-A-DECLARER"]["flux"] == ["taxes:remise"]


@pytest.mark.parametrize("fiscal, code, flux", [
    (None, "REJ-FISCAL-FREQUENCE-A-DECLARER", "taxes:configuration"),
    ({"frequence_tps_tvq": "trimestrielle"}, "REJ-FISCAL-FIN-EXERCICE-A-DECLARER", "taxes:configuration"),
    ({"frequence_tps_tvq": "bimensuelle"}, "REJ-FISCAL-CONFIGURATION-INVALIDE", "taxes:configuration"),
    ({**FISCAL, "taxes_remises_jusqu_au": "2026-08-31"}, "REJ-FISCAL-REMISE-HORS-PERIODE", "taxes:remise"),
    ({**FISCAL, "taxes_remises_jusqu_au": "2026-09-30"}, "REJ-FISCAL-CONFIGURATION-INVALIDE", "taxes:remise"),
    ({**FISCAL, "taxes_remises_jusqu_au": "2024-03-31"}, "REJ-CALENDRIER-ANNEE-NON-DECLAREE", "taxes:remise"),
])
def test_une_configuration_fiscale_absente_ou_illisible_bloque_avec_le_verdict_de_t4_16(
        taux, calendrier, fiscal, code, flux):
    resultat = _prevoir(taux, calendrier, fiscal=fiscal)

    assert resultat["non_calculable_a_partir_de"] == 1
    assert _codes(resultat)[code]["flux"] == [flux]
    assert all(s["solde_fin"] is None for s in resultat["semaines"])


def test_un_calendrier_illisible_bloque_les_taxes(taux):
    flux = prevision.flux_taxes([], [], None, validation.construire_verdict("REJ-CALENDRIER-INVALIDE", "x"), FISCAL,
                                AUJOURD_HUI)

    assert [(f["id"], f["montant"], f["date"], [m["code"] for m in f["manque"]]) for f in flux] == [
        ("taxes:calendrier", None, None, ["REJ-CALENDRIER-INVALIDE"])]
    assert prevision.flux_taxes([], [], None, None, FISCAL, AUJOURD_HUI)[0]["manque"][0]["code"] == (
        "REJ-CALENDRIER-INVALIDE"), "sans verdict fourni, le code dit quand même pourquoi"


def test_une_date_de_sortie_absente_bloque_des_la_semaine_1_meme_si_le_montant_est_connu(taux, calendrier):
    resultat = _prevoir(taux, calendrier, echeances={"das": "2026-10-15", "dettes": "2026-10-31"})

    assert resultat["non_calculable_a_partir_de"] == 1
    groupe = _codes(resultat)["REJ-PREVISION-ECHEANCE-A-DECLARER"]
    assert groupe["flux"] == ["obligation:paies"] and groupe["a_partir_de_semaine"] == 1
    assert "echeances_obligations.paies" in groupe["detail"]


def test_une_taxe_illisible_bloque_a_la_limite_de_paiement_de_sa_periode(calendrier):
    clients = [{"facture_id": "F-X", "date_envoi": "2026-08-01T09:00:00-04:00", "statut": "ENVOYEE",
                "taxes": [{"id": "tps_federale", "montant": D("10.00")}]}]  # la TVQ manque : illisible
    flux = prevision.flux_taxes(clients, [], calendrier, None, FISCAL, AUJOURD_HUI)

    assert [(f["id"], f["montant"], f["date"]) for f in flux] == [("taxes:2026-07-01:2026-09-30", None,
                                                                    date(2026, 11, 2))]
    assert flux[0]["manque"][0]["code"] == "REJ-CASH-FACTURE-ILLISIBLE" and "F-X" in flux[0]["manque"][0]["detail"]
    resultat = prevision.assembler(AUJOURD_HUI, 6, _solde(), flux, verdict_seuil=validation.construire_verdict(
        "REJ-PREVISION-SEUIL-A-CONFIGURER", "test"))
    assert resultat["non_calculable_a_partir_de"] == 5, "la limite du 2 novembre tombe en semaine 5"
    assert [s["statut"] for s in resultat["semaines"]] == ["CALCULE"] * 4 + ["NON_CALCULABLE"] * 2


def test_un_attendu_dont_le_prix_manque_bloque_a_sa_semaine_avec_son_code(taux, calendrier):
    """PO-4 : reçu, mais son prix n'est pas au PO. L'attendu est inconnu (jamais zéro) ; sa date (réception 09-18 + 30
    jours = 10-18) tombe en semaine 3."""
    a_payer = _a_payer(taux)
    charge = _charge("e-4", "PO-4", "10", "2026-09-18T09:00:00-04:00")
    charge["lignes"][0]["prix_unitaire_prevu"] = None
    entree, verdict = cap.construire_reception(charge)
    assert verdict is None and cap.enregistrer_reception(entree, a_payer)[1] is None

    resultat = _prevoir(taux, calendrier, a_payer=a_payer)

    assert resultat["non_calculable_a_partir_de"] == 3
    assert _soldes(resultat)[:2] == [D("19885.02"), D("15685.02")]
    groupe = _codes(resultat)["REJ-AP-PRIX-PO-ABSENT"]
    assert groupe["a_partir_de_semaine"] == 3 and groupe["flux"] == ["attendu:PO-4"]


def test_un_solde_inconnu_bloque_tout_le_reste_est_sans_objet(taux, calendrier):
    resultat = _prevoir(taux, calendrier, mouvements=registre.Registre())

    assert resultat["non_calculable_a_partir_de"] == 1 and resultat["solde"]["montant"] is None
    assert _codes(resultat)["REJ-CASH-SOLDE-ABSENT"]["flux"] == ["solde"]
    assert resultat["plus_bas"] is None and all(s["solde_fin"] is None for s in resultat["semaines"])


def test_un_manque_est_dit_une_fois_par_code_avec_les_semaines_les_plus_precoces(taux, calendrier):
    """Deux manques de codes différents : une ligne chacun, triés par semaine puis code."""
    declarees = {k: v for k, v in DECLARATIONS.items() if k not in ("dettes", "das")}

    resultat = _prevoir(taux, calendrier, declarees=declarees, echeances={"paies": "2026-10-09", "das": "2026-10-15",
                                                                          "dettes": "2026-10-31"})

    assert [(g["code"], g["a_partir_de_semaine"]) for g in resultat["manque"]] == [
        ("REJ-CASH-DAS-A-DECLARER", 3), ("REJ-CASH-DETTES-A-DECLARER", 5)]
    assert resultat["non_calculable_a_partir_de"] == 3


def test_les_factures_sans_delai_du_meme_code_font_une_seule_ligne_de_manque(taux, calendrier):
    resultat = _prevoir(taux, calendrier, delai_fournisseurs=None)

    assert len([g for g in resultat["manque"] if g["code"] == _CODE_DELAI_FOURNISSEURS]) == 1
    assert len(_codes(resultat)[_CODE_DELAI_FOURNISSEURS]["flux"]) == 3


# ====================================== 5. les encaissements inconnus ne sont jamais comptés (prudent) et sont dits
def test_sans_delai_client_les_creances_ne_sont_pas_comptees_et_la_prevision_reste_calculable(taux, calendrier):
    resultat = _prevoir(taux, calendrier, delai_clients=None)

    assert resultat["calculable"] is True
    assert [(s["entrees"], s["solde_fin"]) for s in resultat["semaines"][2:4]] == [
        (D("0.00"), D("13414.46")), (D("0.00"), D("13414.46"))]
    groupe = next(g for g in resultat["encaissements_non_comptes"] if g["code"] == _CODE_DELAI_CLIENTS)
    assert groupe["nombre"] == 3 and groupe["montant_connu"] == D("8048.25")
    assert groupe["flux"] == ["client:C-1", "client:C-2", "client:C-3"]
    # 15685.02 - 2270.56 : sans le 4599.00 de C-1 ni le 2299.50 de C-2 ; jamais un encaissement espéré
    assert D("15685.02") - D("2270.56") == D("13414.46")


def test_un_montant_de_facture_illisible_n_est_jamais_compte_ni_arrondi():
    flux = prevision.flux_clients([
        {"facture_id": "F-A", "montant_apres_taxes": D("10.005"), "date_envoi": "2026-09-20T09:00:00-04:00"},
        {"facture_id": "F-B", "montant_apres_taxes": "12.00", "date_envoi": "2026-09-20T09:00:00-04:00"},
        {"facture_id": "F-C", "montant_apres_taxes": D("-5.00"), "date_envoi": "2026-09-20T09:00:00-04:00"},
        {"facture_id": "F-D", "montant_apres_taxes": D("NaN"), "date_envoi": "2026-09-20T09:00:00-04:00"},
    ], 30, None)

    assert [f["montant"] for f in flux] == [None] * 4
    assert all([m["code"] for m in f["manque"]] == ["REJ-CREANCES-MONTANT-ILLISIBLE"] for f in flux)
    assert all(f["date"] == date(2026, 10, 20) for f in flux)


def test_une_date_d_envoi_illisible_donne_une_creance_sans_date_jamais_placee():
    flux = prevision.flux_clients([
        {"facture_id": "F-A", "montant_apres_taxes": D("10.00"), "date_envoi": "pas une date"},
        {"facture_id": "F-B", "montant_apres_taxes": D("10.00")},
    ], 30, None)

    assert [f["date"] for f in flux] == [None, None]
    assert [[m["code"] for m in f["manque"]] for f in flux] == [["REJ-CREANCES-DATE-ENVOI-INVALIDE"]] * 2
    resultat = _assembler(flux)
    assert resultat["calculable"] is True and _soldes(resultat) == [D("1000.00")] * 3
    assert resultat["encaissements_non_comptes"][0]["code"] == "REJ-CREANCES-DATE-ENVOI-INVALIDE"


def test_une_facture_cliente_de_zero_n_est_pas_un_flux():
    assert prevision.flux_clients([
        {"facture_id": "F-0", "montant_apres_taxes": D("0.00"), "date_envoi": "2026-09-20T09:00:00-04:00"}], 30, None
    ) == []


def test_le_jour_d_envoi_est_celui_qui_est_ecrit_pas_celui_d_un_autre_fuseau():
    flux = prevision.flux_clients([
        {"facture_id": "F-A", "montant_apres_taxes": D("10.00"), "date_envoi": "2026-09-20T23:30:00-04:00"}], 0, None)

    assert flux[0]["date"] == date(2026, 9, 20)


def test_un_delai_de_zero_jour_place_l_encaissement_le_jour_de_l_envoi():
    flux = prevision.flux_clients([
        {"facture_id": "F-A", "montant_apres_taxes": D("10.00"), "date_envoi": "2026-09-29T09:00:00-04:00"}], 0, None)

    assert flux[0]["date"] == date(2026, 9, 29)
    assert prevision.flux_clients([
        {"facture_id": "F-A", "montant_apres_taxes": D("10.00"), "date_envoi": "2026-09-29T09:00:00-04:00"}], 1, None
    )[0]["date"] == date(2026, 9, 30)


def test_un_delai_absent_sans_verdict_est_une_erreur_d_assemblage_du_code():
    with pytest.raises(ValueError):
        prevision.flux_clients([], None, None)
    with pytest.raises(ValueError):
        prevision.flux_fournisseurs([], None, None)
    with pytest.raises(ValueError):
        prevision.flux_fournisseurs(None, 30, None, None)


# ===================================================================================== 6. les fournisseurs, les taxes
def test_les_dettes_datables_se_somment_au_total_de_t4_15_a_la_cent_pres(taux):
    """Une seule règle : les dettes séparées sont celles de `resume_a_payer`. 344.93 + 114.98 + 574.88 = 1034.79."""
    a_payer = _a_payer(taux)

    dettes, verdict = cap.dettes_datables(a_payer, taux)
    resume, _ = cap.resume_a_payer(a_payer, taux)

    assert verdict is None
    assert sum((d["montant"] for d in dettes), D("0")) == resume["a_payer_apres_taxes"] == D("1034.79")
    assert [(d["type"], d["montant"], d["date_base"]) for d in dettes] == [
        ("FACTURE", D("344.93"), "2026-09-14"), ("FACTURE", D("114.98"), "2026-06-20"),
        ("ATTENDU", D("574.88"), "2026-09-17T09:00:00-04:00")]
    assert [d["po_id"] for d in dettes] == ["PO-1", "PO-2", "PO-3"]
    assert dettes[2]["id"] == "PO-3" and dettes[2]["numero_facture"] is None
    assert dettes[2]["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"] and dettes[0]["reserves"] == []
    assert all(d["manque"] == [] for d in dettes)


def test_un_po_completement_facture_n_a_pas_d_attendu(taux):
    a_payer = _a_payer(taux, receptions=(("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),),
                       factures=(("PO-1", "F-1001", "2026-09-14", "300.00"),))

    dettes, _ = cap.dettes_datables(a_payer, taux)

    assert [d["type"] for d in dettes] == ["FACTURE"]


def test_un_po_partiellement_facture_garde_le_reste_comme_attendu_avec_ses_taxes(taux):
    """PO reçu pour 500.00, facturé 200.00 (229.95) : reste 300.00 non facturé, taxes recalculées sur ce reste
    (15.00 + 29.93) = 344.93."""
    a_payer = _a_payer(taux, receptions=(("e-1", "PO-1", "100", "2026-09-15T09:00:00-04:00"),),
                       factures=(("PO-1", "F-1", "2026-09-14", "200.00"),))

    dettes, _ = cap.dettes_datables(a_payer, taux)

    assert [(d["type"], d["montant"]) for d in dettes] == [("FACTURE", D("229.95")), ("ATTENDU", D("344.93"))]


def test_une_facture_annulee_n_est_plus_une_dette_et_l_attendu_revient(taux):
    a_payer = _a_payer(taux, receptions=(("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),),
                       factures=(("PO-1", "F-1001", "2026-09-14", "300.00"),))
    (lue,) = cap.factures_saisies(a_payer)
    _, verdict = cap.annuler_facture_fournisseur(
        facture_fournisseur_id=lue["facture_fournisseur_id"], motif="saisie sous le mauvais PO (fictif)",
        annule_par="nathan", role="nathan_owner", voie="approbation", horodatage="2026-09-21T10:00:00-04:00",
        registre_cible=a_payer, revision_attendue=lue["corrections"])
    assert verdict is None, verdict

    dettes, _ = cap.dettes_datables(a_payer, taux)
    resume, _ = cap.resume_a_payer(a_payer, taux)

    assert [(d["type"], d["montant"]) for d in dettes] == [("ATTENDU", D("344.93"))], "annuler n'efface pas la dette"
    assert sum((d["montant"] for d in dettes), D("0")) == resume["a_payer_apres_taxes"]


def test_une_facture_corrigee_vaut_sa_correction(taux):
    a_payer = _a_payer(taux, receptions=(("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),),
                       factures=(("PO-1", "F-1001", "2026-09-14", "300.00"),))
    (lue,) = cap.factures_saisies(a_payer)
    _, verdict = cap.corriger_facture_fournisseur(
        facture_fournisseur_id=lue["facture_fournisseur_id"], motif="date tapée de travers (fictif)",
        numero_facture=None, date_facture="2026-09-10", montant_avant_taxes=None, total_facture=None,
        corrige_par="nathan", role="nathan_owner", voie="approbation", horodatage="2026-09-21T10:00:00-04:00",
        dictionnaire_taux=taux, registre_cible=a_payer, revision_attendue=lue["corrections"])
    assert verdict is None, verdict

    dettes, _ = cap.dettes_datables(a_payer, taux)

    assert [(d["type"], d["montant"], d["date_base"]) for d in dettes] == [("FACTURE", D("344.93"), "2026-09-10")]


def test_une_facture_sans_po_est_une_dette_comptee_en_entier_apres_celles_des_po(taux):
    a_payer = _a_payer(taux, receptions=(("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),),
                       factures=(("PO-1", "F-1001", "2026-09-14", "300.00"),))
    _, verdict = cap.saisir_facture_sans_po(
        fournisseur_id="Pétro-Nord (fictif)", categorie="carburant", numero_facture="C-1", date_facture="2026-09-25",
        montant_avant_taxes="100.00", total_facture=None, saisi_par="nathan", voie="appareil",
        horodatage="2026-09-26T10:00:00-04:00", dictionnaire_taux=taux, categories_configurees=("carburant",),
        registre_cible=a_payer)
    assert verdict is None, verdict

    dettes, _ = cap.dettes_datables(a_payer, taux)
    resume, _ = cap.resume_a_payer(a_payer, taux)

    assert [(d["type"], d["po_id"], d["montant"], d["date_base"]) for d in dettes] == [
        ("FACTURE", "PO-1", D("344.93"), "2026-09-14"), ("FACTURE", None, D("114.98"), "2026-09-25")]
    assert sum((d["montant"] for d in dettes), D("0")) == resume["a_payer_apres_taxes"] == D("459.91")


def test_un_attendu_non_calculable_a_un_montant_nul_et_ses_codes_jamais_zero(taux):
    a_payer = registre.Registre()
    charge = _charge("e-1", "PO-1", "10", "2026-09-15T09:00:00-04:00")
    charge["lignes"][0]["prix_unitaire_prevu"] = None
    entree, _ = cap.construire_reception(charge)
    cap.enregistrer_reception(entree, a_payer)

    dettes, verdict = cap.dettes_datables(a_payer, taux)

    assert verdict is None
    assert [(d["type"], d["montant"], d["manque"]) for d in dettes] == [("ATTENDU", None, ["REJ-AP-PRIX-PO-ABSENT"])]
    flux = prevision.flux_fournisseurs(dettes, 30, None)
    assert flux[0]["montant"] is None and [m["code"] for m in flux[0]["manque"]] == ["REJ-AP-PRIX-PO-ABSENT"]
    assert flux[0]["date"] == date(2026, 10, 15)


def test_un_registre_sans_dette_donne_une_liste_vide_et_un_taux_manquant_un_verdict(taux):
    assert cap.dettes_datables(registre.Registre(), taux) == ([], None)
    a_payer = _a_payer(taux)

    dettes, verdict = cap.dettes_datables(a_payer, {})

    assert dettes is None and verdict["code"] == "REJ-TAUX-INCONNU"
    flux = prevision.flux_fournisseurs(None, 30, None, verdict)
    assert len(flux) == 1 and flux[0]["montant"] is None and flux[0]["date"] is None
    assert [m["code"] for m in flux[0]["manque"]] == ["REJ-TAUX-INCONNU"]


def test_les_dettes_sont_dans_l_ordre_des_po_par_premiere_reception_puis_leurs_factures_puis_l_attendu(taux):
    a_payer = _a_payer(
        taux, receptions=(("e-2", "PO-B", "20", "2026-09-16T09:00:00-04:00"),
                          ("e-1", "PO-A", "20", "2026-09-15T09:00:00-04:00")),
        factures=(("PO-B", "F-B", "2026-09-16", "10.00"), ("PO-A", "F-A", "2026-09-15", "10.00")))

    dettes, _ = cap.dettes_datables(a_payer, taux)

    assert [(d["type"], d["po_id"]) for d in dettes] == [
        ("FACTURE", "PO-A"), ("ATTENDU", "PO-A"), ("FACTURE", "PO-B"), ("ATTENDU", "PO-B")]


def test_les_periodes_de_taxes_sont_chacune_a_leur_limite_de_paiement_et_le_remboursement_n_est_jamais_de_l_argent(
        calendrier):
    """Mensuelle, dernière remise le 2026-07-31 : trois périodes. Août : TPS 100.00 (encaissée en août). Septembre : un
    crédit sur intrants plus grand que la taxe collectée (remboursement) : aucune sortie."""
    clients = [{"facture_id": "F-1", "date_envoi": "2026-08-10T09:00:00-04:00", "statut": "ENVOYEE", "taxes": [
                    {"id": "tps_federale", "montant": D("100.00")}, {"id": "tvq_quebec", "montant": D("199.50")}]}]
    fournisseurs = [{"facture_fournisseur_id": "apf-1", "date_facture": "2026-09-10", "taxes": [
                        {"id": "tps_federale", "montant": D("30.00")}, {"id": "tvq_quebec", "montant": D("59.85")}]}]
    fiscal = {"frequence_tps_tvq": "mensuelle", "taxes_remises_jusqu_au": "2026-07-31"}

    flux = prevision.flux_taxes(clients, fournisseurs, calendrier, None, fiscal, AUJOURD_HUI)

    assert [(f["id"], f["montant"], f["date"]) for f in flux] == [
        ("taxes:2026-08-01:2026-08-31", D("299.50"), date(2026, 10, 1))]
    assert flux[0]["partielle"] is False, "août est terminé"
    assert "TPS 100.00 + TVQ 199.50" in flux[0]["source"] and "période non terminée" not in flux[0]["source"]


def test_les_taxes_de_deux_periodes_sont_deux_sorties_a_deux_dates(calendrier):
    clients = [
        {"facture_id": "F-1", "date_envoi": "2026-08-10T09:00:00-04:00", "statut": "ENVOYEE", "taxes": [
            {"id": "tps_federale", "montant": D("100.00")}, {"id": "tvq_quebec", "montant": D("199.50")}]},
        {"facture_id": "F-2", "date_envoi": "2026-09-10T09:00:00-04:00", "statut": "ENVOYEE", "taxes": [
            {"id": "tps_federale", "montant": D("50.00")}, {"id": "tvq_quebec", "montant": D("99.75")}]},
    ]
    fiscal = {"frequence_tps_tvq": "mensuelle", "taxes_remises_jusqu_au": "2026-07-31"}

    flux = prevision.flux_taxes(clients, [], calendrier, None, fiscal, AUJOURD_HUI)

    assert [(f["id"], f["montant"], f["date"], f["partielle"]) for f in flux] == [
        ("taxes:2026-08-01:2026-08-31", D("299.50"), date(2026, 10, 1), False),
        ("taxes:2026-09-01:2026-09-30", D("149.75"), date(2026, 11, 2), True)]


def test_une_remise_qui_a_fini_avant_aujourd_hui_seulement_les_periodes_suivantes_comptent(calendrier):
    clients = [{"facture_id": "F-1", "date_envoi": "2026-05-10T09:00:00-04:00", "statut": "ENVOYEE", "taxes": [
        {"id": "tps_federale", "montant": D("100.00")}, {"id": "tvq_quebec", "montant": D("199.50")}]}]

    # remise jusqu'au 2026-06-30 : la facture du 05-10 est déjà dans une déclaration remise
    assert prevision.flux_taxes(clients, [], calendrier, None, FISCAL, AUJOURD_HUI) == []
    # remise jusqu'au 2026-03-31 : la période du 2e trimestre (limite 07-31, échue) est due
    fiscal = {**FISCAL, "taxes_remises_jusqu_au": "2026-03-31"}
    flux = prevision.flux_taxes(clients, [], calendrier, None, fiscal, AUJOURD_HUI)
    assert [(f["id"], f["montant"], f["date"]) for f in flux] == [
        ("taxes:2026-04-01:2026-06-30", D("299.50"), date(2026, 7, 31))]


def test_des_factures_apres_la_fin_du_calendrier_connu_bloquent_leur_echeance_est_inconnue(calendrier):
    clients = [{"facture_id": "F-1", "date_envoi": "2027-02-10T09:00:00-05:00", "statut": "ENVOYEE", "taxes": [
        {"id": "tps_federale", "montant": D("100.00")}, {"id": "tvq_quebec", "montant": D("199.50")}]}]
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": False,
              "taxes_remises_jusqu_au": "2025-12-31"}

    flux = prevision.flux_taxes(clients, [], calendrier, None, fiscal, date(2027, 3, 1))

    assert "taxes:couverture" in {f["id"] for f in flux}
    couverture = next(f for f in flux if f["id"] == "taxes:couverture")
    assert (couverture["montant"], couverture["date"]) == (None, None)
    assert couverture["manque"][0]["code"] == "REJ-CALENDRIER-ANNEE-NON-DECLAREE"
    assert "2026-12-31" in couverture["manque"][0]["detail"]


def test_sans_facture_apres_le_calendrier_connu_rien_ne_bloque(calendrier):
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": False,
              "taxes_remises_jusqu_au": "2025-12-31"}

    flux = prevision.flux_taxes([], [], calendrier, None, fiscal, date(2027, 3, 1))

    assert flux == [], "aucune taxe accumulée : ni sortie ni manque"


def test_une_annuelle_dont_la_limite_tombe_apres_l_horizon_n_est_qu_agregee(taux, calendrier):
    """Annuelle au 31 décembre (non particulier) : toute l'année 2026 est due le 2027-03-31, après un horizon de six
    semaines : aucune baisse de solde, mais la taxe est dite hors horizon."""
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": False,
              "taxes_remises_jusqu_au": "2025-12-31"}

    resultat = _prevoir(taux, calendrier, fiscal=fiscal)

    # depuis le 2025-12-31, les crédits de F-2001 (5.00 et 9.98, facture du 2026-06-20) comptent aussi :
    # TPS 365.00 - 15.00 - 5.00 = 345.00 ; TVQ 728.18 - 29.93 - 9.98 = 688.27 ; total 1033.27
    assert resultat["au_dela_de_l_horizon"]["sorties"] == {"nombre": 1, "total": D("1033.27"), "non_chiffres": 0}
    assert _soldes(resultat)[4] == D("20312.96") - D("800.00") == D("19512.96")


# ========================================================================================= 7. le déterminisme
@pytest.mark.parametrize("graine", [1, 2, 3, 4, 5])
def test_le_resultat_ne_depend_pas_de_l_ordre_des_flux(taux, calendrier, graine):
    de_reference = _prevoir(taux, calendrier)

    melange = _prevoir(taux, calendrier, melanger=graine)

    assert melange == de_reference and melange["prevision_id"] == de_reference["prevision_id"]


def test_les_memes_entrees_donnent_la_meme_empreinte_et_un_cent_de_plus_la_change(taux, calendrier):
    premiere = _prevoir(taux, calendrier)
    deuxieme = _prevoir(taux, calendrier)
    autre = _prevoir(taux, calendrier, declarees={**DECLARATIONS, "paies": {**DECLARATIONS["paies"],
                                                                              "montant": "4200.01"}})

    assert premiere["prevision_id"] == deuxieme["prevision_id"] and len(premiere["prevision_id"]) == 64
    assert autre["prevision_id"] != premiere["prevision_id"]
    assert _soldes(autre)[1] == D("15685.01"), "4200.01 de paies : un cent de moins que 15685.02"


def test_la_prevision_ne_modifie_pas_ses_entrees(taux, calendrier):
    flux = [_flux("s", prevision.SORTIE, "10.00", AUJOURD_HUI)]
    avant = json.dumps(flux, default=str, sort_keys=True)

    _assembler(flux)

    assert json.dumps(flux, default=str, sort_keys=True) == avant


# ===================================================================================== 8. les erreurs d'assemblage
@pytest.mark.parametrize("modifier", [
    lambda f: {**f, "sens": "SORTIE-ENTREE"},
    lambda f: {k: v for k, v in f.items() if k != "source"},
    lambda f: {**f, "montant": D("-1.00")},
    lambda f: {**f, "montant": D("NaN")},
    lambda f: {**f, "montant": 10.0},
    lambda f: {**f, "date": "2026-10-01"},
    lambda f: {**f, "date": None},                    # date inconnue sans dire ce qui manque
    lambda f: {**f, "montant": None},                 # montant inconnu sans dire ce qui manque
])
def test_un_flux_mal_forme_ou_inconnu_sans_manque_est_une_erreur_du_code(modifier):
    flux = modifier(_flux("x", prevision.SORTIE, "10.00", AUJOURD_HUI))

    with pytest.raises(ValueError):
        _assembler([flux])


def test_deux_flux_de_meme_identifiant_sont_une_erreur_du_code():
    with pytest.raises(ValueError):
        _assembler([_flux("x", prevision.SORTIE, "1.00", AUJOURD_HUI),
                    _flux("x", prevision.ENTREE, "1.00", AUJOURD_HUI)])


@pytest.mark.parametrize("horizon", [0, -1, 27, 3.0, "3", True, None])
def test_un_horizon_hors_bornes_est_une_erreur_du_code(horizon):
    with pytest.raises(ValueError):
        prevision.assembler(AUJOURD_HUI, horizon, _solde(), [], verdict_seuil=validation.construire_verdict(
            "REJ-PREVISION-SEUIL-A-CONFIGURER", "test"))


@pytest.mark.parametrize("jour", ["2026-09-29", None])
def test_aujourd_hui_doit_etre_une_date(jour):
    with pytest.raises(ValueError):
        prevision.assembler(jour, 3, _solde(), [], verdict_seuil=validation.construire_verdict(
            "REJ-PREVISION-SEUIL-A-CONFIGURER", "test"))


def test_aujourd_hui_n_est_pas_un_horodatage():
    from datetime import datetime
    with pytest.raises(ValueError):
        prevision.assembler(datetime(2026, 9, 29, 12, 0), 3, _solde(), [], verdict_seuil=validation.construire_verdict(
            "REJ-PREVISION-SEUIL-A-CONFIGURER", "test"))


def test_un_solde_mal_forme_ou_inconnu_sans_manque_est_une_erreur_du_code():
    verdict = validation.construire_verdict("REJ-PREVISION-SEUIL-A-CONFIGURER", "test")
    for solde in ({"montant": D("1.00")}, {"montant": None, "manque": []}, {"montant": 1.5, "manque": []},
                  {"montant": D("Infinity"), "manque": []}, "1000.00"):
        with pytest.raises(ValueError):
            prevision.assembler(AUJOURD_HUI, 3, solde, [], verdict_seuil=verdict)


def test_un_seuil_absent_sans_verdict_ou_negatif_est_une_erreur_du_code():
    with pytest.raises(ValueError):
        prevision.assembler(AUJOURD_HUI, 3, _solde(), [])
    with pytest.raises(ValueError):
        prevision.assembler(AUJOURD_HUI, 3, _solde(), [], seuil={"montant": D("-1.00"), "source": "x",
                                                                 "au": date(2026, 1, 1)})


# ================================================================================ 9. ce que le propriétaire décide
@pytest.mark.parametrize("brut, attendu", [(1, 1), (13, 13), (26, 26)])
def test_un_horizon_de_1_a_26_semaines_est_accepte(brut, attendu):
    assert prevision.lire_horizon(brut) == (attendu, None)


def test_un_horizon_absent_est_a_configurer_jamais_suppose():
    horizon, verdict = prevision.lire_horizon(None)

    assert horizon is None and verdict["code"] == "REJ-PREVISION-HORIZON-A-CONFIGURER"
    assert "GATE NATHAN" in verdict["detail"] and "aucun horizon n'est supposé" in verdict["detail"]


@pytest.mark.parametrize("brut", [0, -3, 27, 100, 13.0, "13", True, False, [13], {"a": 1}])
def test_un_horizon_illisible_ou_hors_bornes_est_refuse(brut):
    horizon, verdict = prevision.lire_horizon(brut)

    assert horizon is None and verdict["code"] == "REJ-PREVISION-HORIZON-INVALIDE"


def test_aujourd_hui_lu_est_une_date_ou_un_refus():
    assert prevision.lire_jour("2026-09-29") == (date(2026, 9, 29), None)
    for brut in (None, "", "2026-9-29", "29/09/2026", "2026-02-30", "2026-09-29T12:00:00", 20260929, date(2026, 9, 29)):
        jour, verdict = prevision.lire_jour(brut)
        assert jour is None and verdict["code"] == "REJ-PREVISION-DATE-INVALIDE", brut


def test_le_seuil_declare_se_lit_avec_sa_source_et_sa_date():
    seuil, verdict = prevision.lire_seuil({"montant": " 1".strip() + "0000.5", "source": "  décision de Nathan  ",
                                           "au": "2026-09-25"})

    assert verdict is None
    assert seuil == {"montant": D("10000.50"), "source": "décision de Nathan", "au": date(2026, 9, 25)}


def test_un_seuil_absent_est_a_configurer():
    seuil, verdict = prevision.lire_seuil(None)

    assert seuil is None and verdict["code"] == "REJ-PREVISION-SEUIL-A-CONFIGURER"
    assert "seuil à configurer" in verdict["detail"] and "aucun seuil n'est supposé" in verdict["detail"]


@pytest.mark.parametrize("brut", [
    "10000.00", 10000, [], {}, {"montant": "10000.00"}, {"montant": "10000.00", "source": "x"},
    {"montant": "10000.00", "source": "x", "au": "2026-09-25", "autre": 1},
    {"montant": 10000.0, "source": "x", "au": "2026-09-25"},
    {"montant": "-1.00", "source": "x", "au": "2026-09-25"},
    {"montant": "10000.001", "source": "x", "au": "2026-09-25"},
    {"montant": "1e4", "source": "x", "au": "2026-09-25"},
    {"montant": "", "source": "x", "au": "2026-09-25"},
    {"montant": "10000.00", "source": "", "au": "2026-09-25"},
    {"montant": "10000.00", "source": "   ", "au": "2026-09-25"},
    {"montant": "10000.00", "source": 7, "au": "2026-09-25"},
    {"montant": "10000.00", "source": "x" * 121, "au": "2026-09-25"},
    {"montant": "10000.00", "source": "x", "au": "2026-9-25"},
    {"montant": "10000.00", "source": "x", "au": date(2026, 9, 25)},
])
def test_un_seuil_illisible_est_refuse_jamais_corrige(brut):
    seuil, verdict = prevision.lire_seuil(brut)

    assert seuil is None and verdict["code"] == "REJ-PREVISION-SEUIL-INVALIDE"


def test_un_seuil_de_120_caracteres_de_source_est_accepte_et_zero_est_un_seuil_connu():
    assert prevision.lire_seuil({"montant": "0.00", "source": "x" * 120, "au": "2026-09-25"})[1] is None
    assert prevision.lire_seuil({"montant": "0", "source": "x", "au": "2026-09-25"})[0]["montant"] == D("0.00")


@pytest.mark.parametrize("brut", [0, 1, 30, 365])
def test_un_delai_de_0_a_365_jours_est_accepte(brut):
    assert prevision.lire_delai(brut, "delai_x", "REJ-PREVISION-DELAI-CLIENTS-A-DECLARER") == (brut, None)


def test_un_delai_absent_dit_quoi_declarer_avec_le_code_de_l_appelant():
    jours, verdict = prevision.lire_delai(None, "delai_paiement_fournisseurs_jours", _CODE_DELAI_FOURNISSEURS)

    assert jours is None and verdict["code"] == _CODE_DELAI_FOURNISSEURS
    assert "configuration.prevision.delai_paiement_fournisseurs_jours" in verdict["detail"]
    assert "aucun délai n'est supposé" in verdict["detail"]


@pytest.mark.parametrize("brut", [-1, 366, 30.0, "30", True, False, [], {}])
def test_un_delai_illisible_est_refuse(brut):
    jours, verdict = prevision.lire_delai(brut, "delai_x", _CODE_DELAI_CLIENTS)

    assert jours is None and verdict["code"] == "REJ-PREVISION-DELAI-INVALIDE"


def test_les_echeances_des_obligations_se_lisent_une_par_une():
    lues = prevision.lire_echeances_obligations({"paies": "2026-10-09", "das": "2026-10-15"})

    assert lues["paies"] == (date(2026, 10, 9), None) and lues["das"] == (date(2026, 10, 15), None)
    assert lues["dettes"][0] is None and lues["dettes"][1]["code"] == "REJ-PREVISION-ECHEANCE-A-DECLARER"
    assert "echeances_obligations.dettes" in lues["dettes"][1]["detail"]
    assert set(lues) == {"paies", "das", "dettes"}


def test_sans_aucune_echeance_declaree_les_trois_sont_a_declarer():
    for brut in (None, {}):
        lues = prevision.lire_echeances_obligations(brut)
        assert {c: v[1]["code"] for c, v in lues.items()} == {c: "REJ-PREVISION-ECHEANCE-A-DECLARER" for c in lues}


@pytest.mark.parametrize("brut", ["2026-10-09", [], 7, {"paies": "2026-10-09", "salaires": "2026-10-09"}])
def test_des_echeances_illisibles_sont_refusees_pour_les_trois_jamais_a_moitie_lues(brut):
    lues = prevision.lire_echeances_obligations(brut)

    assert {c: (v[0], v[1]["code"]) for c, v in lues.items()} == {
        c: (None, "REJ-PREVISION-ECHEANCE-INVALIDE") for c in ("paies", "das", "dettes")}


@pytest.mark.parametrize("valeur", ["2026-10-9", "10-09-2026", "2026-13-01", "2026-02-30", 20261009, date(2026, 10, 9)])
def test_une_date_d_echeance_illisible_est_refusee_pour_cette_obligation_seulement(valeur):
    lues = prevision.lire_echeances_obligations({"paies": valeur, "das": "2026-10-15"})

    assert lues["paies"][0] is None and lues["paies"][1]["code"] == "REJ-PREVISION-ECHEANCE-INVALIDE"
    assert lues["das"] == (date(2026, 10, 15), None)


def test_les_reglages_absents_sont_vides_pas_supposes():
    assert prevision.lire_reglages(None) == ({}, None)
    assert prevision.lire_reglages({}) == ({}, None)


def test_les_reglages_lus_sont_ceux_du_proprietaire():
    brut = {"horizon_semaines": 13, "seuil_alerte": SEUIL, "delai_encaissement_clients_jours": 30,
            "delai_paiement_fournisseurs_jours": 30, "echeances_obligations": ECHEANCES}

    reglages, verdict = prevision.lire_reglages(brut)

    assert verdict is None and reglages == brut and reglages is not brut


@pytest.mark.parametrize("brut", [[], "13", 13, {"horizon": 13}, {"horizon_semaines": 13, "seuil": 1}])
def test_des_reglages_illisibles_ou_avec_une_cle_inconnue_sont_refuses(brut):
    reglages, verdict = prevision.lire_reglages(brut)

    assert reglages == {} and verdict["code"] == "REJ-PREVISION-CONFIGURATION-INVALIDE"


def test_une_cle_inconnue_est_nommee_dans_le_refus():
    _, verdict = prevision.lire_reglages({"horizon_semaine": 13})

    assert "horizon_semaine" in verdict["detail"] and "horizon_semaines" in verdict["detail"]


# ====================================================================================================== 10. les vues
def _vue(resultat, **kwargs):
    kwargs.setdefault("budget_caracteres", 5700)
    page, verdict = prevision.vue_prevision(resultat, **kwargs)
    assert verdict is None, verdict
    return page


def test_la_vue_est_du_json_sur_montants_en_texte_dates_iso_et_porte_la_mention(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    page = _vue(resultat)
    texte = json.dumps(page, ensure_ascii=False)

    assert json.loads(texte) == page, "ni Decimal, ni date, ni ensemble : tout passe par le JSON"
    assert page["mention"] == MENTION and page["type"] == "PREVISION_TRESORERIE"
    assert page["aujourd_hui"] == "2026-09-29" and page["fin_horizon"] == "2026-11-09"
    assert page["prevision_id"] == resultat["prevision_id"]
    assert [s["solde_fin"] for s in page["semaines"]] == [
        "19885.02", "15685.02", "18013.46", "20312.96", "18464.71", "18464.71"]
    assert page["semaines"][1] == {
        "semaine": 2, "du": "2026-10-06", "statut": "CALCULE", "entrees": "0.00", "sorties": "4200.00",
        "solde_fin": "15685.02", "cash_libre_prevu": "10566.21", "sous_seuil": True, "lignes": 1}
    assert page["semaines"][0] == {
        "semaine": 1, "du": "2026-09-29", "statut": "CALCULE", "entrees": "0.00", "sorties": "114.98",
        "solde_fin": "19885.02", "cash_libre_prevu": "10566.21", "lignes": 1}, "les indicateurs faux sont absents"


def test_la_lecture_dit_les_faits_du_resultat(taux, calendrier):
    page = _vue(_prevoir(taux, calendrier))

    assert page["lecture"] == (
        "Solde prévu : 20000.00 $ aujourd'hui, 18464.71 $ à la fin de la semaine 6 ; le plus bas : 15685.02 $ (semaine "
        "2). Alerte : sous le seuil de 16000.00 $ en semaine(s) 2.")
    assert page["alerte"] == {"statut": "ALERTE", "seuil": "16000.00", "source_du_seuil": {
        "source": "décision de Nathan (fictive)", "au": "2026-09-25"}, "semaines": [2]}
    assert page["plus_bas"] == {"semaine": 2, "solde": "15685.02"}
    assert page["cash_libre_aujourd_hui"] == {"montant": "10566.21", "manque": []}
    assert page["solde_initial"]["montant"] == "20000.00" and page["solde_initial"]["fraicheur"] == {
        "derniere_piece": "2026-09-10T12:00:00-04:00", "pieces": 3}
    assert page["encaissements_non_comptes"] == [{
        "code": "REJ-PREVISION-ENCAISSEMENT-ECHU", "nombre": 1, "montant_connu": "1149.75", "exemples": ["client:C-3"]}]
    assert page["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"] and page["limites"] == prevision.limites()


def test_la_lecture_d_une_prevision_non_calculable_dit_a_partir_de_quelle_semaine(taux, calendrier):
    declarees = {k: v for k, v in DECLARATIONS.items() if k != "dettes"}

    page = _vue(_prevoir(taux, calendrier, declarees=declarees))

    assert page["lecture"] == (
        "Prévision non calculable à partir de la semaine 5 (voir manque) : les semaines 1 à 4 sont calculées. Alerte : "
        "sous le seuil de 16000.00 $ en semaine(s) 2.")
    assert page["calculable"] is False and page["non_calculable_a_partir_de"] == 5
    assert page["manque"] == [{
        "code": "REJ-CASH-DETTES-A-DECLARER", "a_partir_de_semaine": 5, "nombre": 1,
        "exemples": ["obligation:dettes"], "detail": page["manque"][0]["detail"]}]
    assert page["semaines"][4] == {"semaine": 5, "du": "2026-10-27", "statut": "NON_CALCULABLE", "lignes": 2}, (
        "une semaine non calculable ne montre aucun chiffre")
    assert page["alerte"]["non_evaluee_a_partir_de"] == 5


def test_la_lecture_dit_des_la_semaine_1_quand_tout_est_non_calculable(taux, calendrier):
    page = _vue(_prevoir(taux, calendrier, delai_fournisseurs=None))

    assert page["lecture"].startswith("Prévision non calculable dès la semaine 1 : aucun chiffre n'est donné")
    assert page["alerte"]["statut"] == "NON_EVALUEE" and "Aucune alerte parmi les semaines calculées" in page["lecture"]
    assert "à partir de la semaine 1, elle n'est pas évaluée" in page["lecture"]


def test_la_lecture_dit_seuil_a_configurer_et_le_deficit(taux, calendrier):
    petit = registre.Registre()
    registre.enregistrer_mouvement({"montant": D("1000.00"), "type_mouvement": "ENCAISSEMENT",
                                    "horodatage": "2026-08-01T12:00:00-04:00", "classe_retention": "STANDARD",
                                    "source": "test"}, petit)

    page = _vue(_prevoir(taux, calendrier, seuil=None, mouvements=petit))

    assert "Seuil à configurer : aucune alerte n'est évaluée." in page["lecture"]
    assert "Solde prévu négatif dès la semaine 2." in page["lecture"]
    assert page["alerte"]["statut"] == "SEUIL_A_CONFIGURER" and page["alerte"]["seuil"] is None
    assert page["alerte"]["manque"]["code"] == "REJ-PREVISION-SEUIL-A-CONFIGURER"
    # 1000.00 - 114.98 = 885.02 ; -3314.98 ; -986.54 ; +2299.50 = 1312.96 (remonte) ; -1848.25 = -535.29 ; -535.29
    assert [s.get("en_deficit") for s in page["semaines"]] == [None, True, True, None, True, True]
    assert page["premiere_semaine_en_deficit"] == 2


def test_la_vue_d_une_alerte_evaluee_et_d_une_semaine_sans_alerte(taux, calendrier):
    page = _vue(_prevoir(taux, calendrier, seuil={**SEUIL, "montant": "100.00"}))

    assert page["alerte"] == {"statut": "AUCUNE", "seuil": "100.00", "source_du_seuil": {
        "source": "décision de Nathan (fictive)", "au": "2026-09-25"}}
    assert "Alerte" not in page["lecture"] and all("sous_seuil" not in s for s in page["semaines"])


def test_au_dela_de_l_horizon_la_vue_dit_le_nombre_et_le_total(taux, calendrier):
    page = _vue(_prevoir(taux, calendrier, horizon=4))

    assert page["au_dela_de_l_horizon"] == {"entrees": {"nombre": 0, "total": "0.00"},
                                            "sorties": {"nombre": 2, "total": "1848.25"}}


def test_les_semaines_se_lisent_page_par_page_sous_le_budget_jamais_tronquees(taux, calendrier):
    resultat = _prevoir(taux, calendrier, horizon=26)
    budget = 3300

    vues = []
    depart = 0
    while depart is not None:
        page = _vue(resultat, depart=depart, budget_caracteres=budget)
        assert prevision._taille(page) <= budget
        assert page["depart"] == depart and page["total"] == 26
        vues.extend(page["semaines"])
        assert page["affichees"] == len(page["semaines"]) and page["reste"] == 26 - depart - page["affichees"]
        depart = page["prochain_depart"]
        assert (page["message"] is None) == (depart is None)
    assert [s["semaine"] for s in vues] == list(range(1, 27))


def test_les_semaines_apres_le_dernier_flux_restent_au_solde_final(taux, calendrier):
    page = _vue(_prevoir(taux, calendrier, horizon=26), budget_caracteres=100000)

    assert {s["solde_fin"] for s in page["semaines"][5:]} == {"18464.71"}
    assert page["fin_horizon"] == "2027-03-29" and page["affichees"] == 26


def test_un_horizon_de_13_semaines_tient_dans_la_limite_du_socle_sans_pagination(taux, calendrier):
    page = _vue(_prevoir(taux, calendrier, horizon=13))

    assert page["affichees"] == 13 and page["prochain_depart"] is None
    assert prevision._taille(page) <= 5700


def test_sous_un_budget_serre_la_vue_perd_d_abord_ses_limites_et_le_dit(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    genres = []
    for budget in range(1000, 4200, 20):
        page, verdict = prevision.vue_prevision(resultat, depart=0, budget_caracteres=budget)
        if verdict is not None:
            genres.append("refus")
            assert verdict["code"] == "REJ-PREVISION-REPONSE-TROP-GROSSE" and page is None
        elif "limites" in page:
            genres.append("avec")
            assert page["limites"] == prevision.limites() and "limites_omises" not in page
        else:
            genres.append("sans")
            assert page["limites_omises"] == len(prevision.limites())
        if page is not None:
            assert prevision._taille(page) <= budget and page["mention"] == MENTION
    assert genres[0] == "refus" and genres[-1] == "avec" and "sans" in genres
    assert genres == sorted(genres, key=["refus", "sans", "avec"].index), "de plus en plus complet avec le budget"


@pytest.mark.parametrize("depart", [-1, 6, 7, 1.0, "0", True, None])
def test_un_rang_de_depart_hors_de_la_serie_est_refuse(taux, calendrier, depart):
    page, verdict = prevision.vue_prevision(_prevoir(taux, calendrier), depart=depart, budget_caracteres=5700)

    assert page is None and verdict["code"] == "REJ-PREVISION-DEPART-INVALIDE"


# ------------------------------------------------------------------------------------------ les lignes d'une semaine
def _semaine(resultat, semaine, **kwargs):
    kwargs.setdefault("budget_caracteres", 5700)
    page, verdict = prevision.vue_semaine(resultat, semaine, **kwargs)
    assert verdict is None, verdict
    return page


def test_la_semaine_3_se_lit_ligne_par_ligne_avec_la_source_et_la_regle_de_chaque_date(taux, calendrier):
    page = _semaine(_prevoir(taux, calendrier), 3)

    assert (page["semaine"], page["du"], page["au"], page["statut"]) == (3, "2026-10-13", "2026-10-19", "CALCULE")
    assert (page["entrees"], page["sorties"], page["solde_fin"]) == ("4599.00", "2270.56", "18013.46")
    assert page["mention"] == MENTION and page["total"] == 4 and page["reste"] == 0
    assert [(ligne["date"], ligne["sens"], ligne["montant"], ligne["id"]) for ligne in page["lignes"]] == [
        ("2026-10-14", "SORTIE", "344.93", page["lignes"][0]["id"]),
        ("2026-10-14", "ENTREE", "4599.00", "client:C-1"),
        ("2026-10-15", "SORTIE", "1350.75", "obligation:das"),
        ("2026-10-17", "SORTIE", "574.88", "attendu:PO-3"),
    ]
    attendu = page["lignes"][3]
    assert attendu["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"] and "echu" not in attendu
    assert attendu["regle_de_date"] == "première réception du 2026-09-17 + 30 jours (délai déclaré par le propriétaire)"
    assert page["lignes"][2]["regle_de_date"].startswith("date de sortie déclarée par le propriétaire")
    assert all(ligne["source"] and ligne["regle_de_date"] for ligne in page["lignes"])


def test_la_semaine_1_dit_qu_une_ligne_est_echue_et_la_semaine_5_qu_une_taxe_est_partielle(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    premiere = _semaine(resultat, 1)["lignes"][0]
    cinquieme = {ligne["id"]: ligne for ligne in _semaine(resultat, 5)["lignes"]}

    assert premiere["echu"] is True and premiere["date"] == "2026-07-20"
    assert cinquieme["taxes:2026-07-01:2026-09-30"]["partielle"] is True
    assert "partielle" not in cinquieme["obligation:dettes"] and "echu" not in cinquieme["obligation:dettes"]


def test_une_semaine_sans_ligne_est_vide_et_repond(taux, calendrier):
    page = _semaine(_prevoir(taux, calendrier), 6)

    assert page["lignes"] == [] and page["total"] == 0 and page["affichees"] == 0 and page["prochain_depart"] is None
    assert page["solde_fin"] == "18464.71"


def test_une_semaine_non_calculable_montre_ses_lignes_connues_sans_aucun_solde(taux, calendrier):
    declarees = {k: v for k, v in DECLARATIONS.items() if k != "dettes"}

    page = _semaine(_prevoir(taux, calendrier, declarees=declarees), 5)

    assert page["statut"] == "NON_CALCULABLE" and page["non_calculable_a_partir_de"] == 5
    assert "solde_fin" not in page and "entrees" not in page and "sorties" not in page
    lignes = {ligne["id"]: ligne for ligne in page["lignes"]}
    assert lignes["obligation:dettes"]["montant"] is None and lignes["obligation:dettes"]["manque"] == [
        "REJ-CASH-DETTES-A-DECLARER"]
    assert lignes["taxes:2026-07-01:2026-09-30"]["montant"] == "1048.25"


def test_les_lignes_d_une_semaine_se_lisent_page_par_page(taux, calendrier):
    resultat = _prevoir(taux, calendrier)
    budget = 1300

    lignes = []
    depart = 0
    while depart is not None:
        page = _semaine(resultat, 3, depart=depart, budget_caracteres=budget)
        assert prevision._taille(page) <= budget
        lignes.extend(page["lignes"])
        depart = page["prochain_depart"]
    assert len(lignes) == 4 and len({ligne["id"] for ligne in lignes}) == 4


@pytest.mark.parametrize("semaine", [0, -1, 7, 1.0, "3", True, None])
def test_une_semaine_hors_de_l_horizon_est_refusee(taux, calendrier, semaine):
    page, verdict = prevision.vue_semaine(_prevoir(taux, calendrier), semaine, budget_caracteres=5700)

    assert page is None and verdict["code"] == "REJ-PREVISION-SEMAINE-INVALIDE"


@pytest.mark.parametrize("depart", [-1, 4, 9, 1.0, "0", True, None])
def test_un_rang_de_ligne_hors_de_la_semaine_est_refuse(taux, calendrier, depart):
    page, verdict = prevision.vue_semaine(_prevoir(taux, calendrier), 3, depart=depart, budget_caracteres=5700)

    assert page is None and verdict["code"] == "REJ-PREVISION-DEPART-INVALIDE"


def test_une_semaine_vide_n_accepte_que_le_rang_zero(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    assert prevision.vue_semaine(resultat, 6, depart=1, budget_caracteres=5700)[1]["code"] == (
        "REJ-PREVISION-DEPART-INVALIDE")


def test_une_ligne_plus_grosse_que_le_budget_est_un_refus_nomme_jamais_une_page_tronquee(taux, calendrier):
    page, verdict = prevision.vue_semaine(_prevoir(taux, calendrier), 3, budget_caracteres=300)

    assert page is None and verdict["code"] == "REJ-PREVISION-REPONSE-TROP-GROSSE"


def test_les_limites_disent_ce_que_la_prevision_ne_sait_pas():
    textes = " ".join(prevision.limites())

    for morceau in ("aucune vente, dépense, paie ni taxe future", "aucune projection statistique",
                    "registre des mouvements", "sans retard de paiement du client", "décaissement échu",
                    "aucune échéance n'est enregistrée", "période non terminée", "à valider par le CPA",
                    "un creux au milieu d'une semaine"):
        assert morceau in textes, morceau
    prevision.limites().append("x")
    assert "x" not in prevision.limites(), "une copie : personne ne modifie les limites du module"


# ================================= 12. les bornes que la mutation ciblée a montrées (chaque test tient une frontière)
def _flux_inconnu(identifiant, jour, codes, *, montant=None, sens=prevision.SORTIE, detail="ce qui manque (fictif)"):
    """Un flux dont le montant (ou la date) n'est pas connu : il porte les codes de ce qui manque."""
    return {"id": identifiant, "sens": sens, "nature": "autre", "montant": None if montant is None else D(montant),
            "date": jour, "regle_de_date": None if jour is None else "test", "source": "test",
            "manque": [validation.construire_verdict(code, detail=detail) for code in codes], "reserves": []}


def _taxes(tps, tvq):
    return [{"id": "tps_federale", "montant": D(tps)}, {"id": "tvq_quebec", "montant": D(tvq)}]


# ---------------------------------------------------------------------------------- l'arrondi et le texte d'un montant
def test_un_montant_a_trois_decimales_est_arrondi_au_cent_demi_superieur_par_semaine():
    resultat = _assembler([
        _flux("a", prevision.SORTIE, "0.005", AUJOURD_HUI),
        _flux("b", prevision.SORTIE, "0.025", AUJOURD_HUI + timedelta(days=7)),
    ], solde=_solde("10.00"))

    assert [s["sorties"] for s in resultat["semaines"][:2]] == [D("0.01"), D("0.03")]
    assert _soldes(resultat)[:2] == [D("9.99"), D("9.96")]


def test_un_montant_sans_decimales_est_rendu_au_cent_dans_la_vue():
    resultat = _assembler([_flux("a", prevision.SORTIE, "5", AUJOURD_HUI)])

    page = _semaine(resultat, 1)

    assert page["lignes"][0]["montant"] == "5.00"


@pytest.mark.parametrize("montant, lisible", [
    ("999999999999.99", True), ("1000000000000.00", False), ("1E+12", False), ("1E+20", False)])
def test_un_montant_de_douze_chiffres_est_lisible_un_de_treize_ne_l_est_pas(montant, lisible):
    flux = prevision.flux_clients(
        [{"facture_id": "F-G", "montant_apres_taxes": D(montant), "date_envoi": "2026-09-20T09:00:00-04:00"}], 30, None)

    assert len(flux) == 1 and (flux[0]["montant"] is not None) == lisible
    assert [m["code"] for m in flux[0]["manque"]] == ([] if lisible else ["REJ-CREANCES-MONTANT-ILLISIBLE"])


def test_un_seuil_de_douze_chiffres_est_lu_un_de_treize_est_refuse():
    seuil, verdict = prevision.lire_seuil({**SEUIL, "montant": "999999999999.99"})
    assert verdict is None and seuil["montant"] == D("999999999999.99")

    seuil, verdict = prevision.lire_seuil({**SEUIL, "montant": "1000000000000.00"})

    assert seuil is None and verdict["code"] == "REJ-PREVISION-SEUIL-INVALIDE"


def test_un_seuil_ne_se_lit_que_tel_qu_ecrit_sans_retour_a_la_ligne_et_toujours_au_cent():
    seuil, verdict = prevision.lire_seuil({**SEUIL, "montant": "10.00\n"})
    assert seuil is None and verdict["code"] == "REJ-PREVISION-SEUIL-INVALIDE"

    for texte, attendu in (("10", "10.00"), ("16000.5", "16000.50"), ("0", "0.00")):
        seuil, verdict = prevision.lire_seuil({**SEUIL, "montant": texte})
        assert verdict is None and format(seuil["montant"], "f") == attendu
        assert seuil["montant"].as_tuple().exponent == -2


# ---------------------------------------------------------------------------------------- ce que la réponse abrège
def test_un_identifiant_de_quarante_caracteres_est_dit_tel_quel_un_de_quarante_et_un_est_abrege():
    quarante, quarante_et_un = "a" * 40, "b" * 41
    resultat = _assembler([
        _flux_inconnu(quarante, AUJOURD_HUI + timedelta(days=1), ["REJ-CASH-FACTURE-ILLISIBLE"]),
        _flux_inconnu(quarante_et_un, AUJOURD_HUI + timedelta(days=2), ["REJ-CASH-FACTURE-ILLISIBLE"]),
    ])

    groupe = _vue(resultat)["manque"][0]

    assert groupe["nombre"] == 2 and groupe["exemples"] == [quarante, "b" * 39 + "…"]
    assert len(groupe["exemples"][1]) == 40


def test_le_detail_d_un_manque_est_abrege_a_deux_cents_caracteres_pas_avant():
    resultat = _assembler([
        _flux_inconnu("a", AUJOURD_HUI + timedelta(days=1), ["REJ-CASH-FACTURE-ILLISIBLE"], detail="d" * 200),
        _flux_inconnu("b", AUJOURD_HUI + timedelta(days=2), ["REJ-AP-MONTANT-ILLISIBLE"], detail="e" * 201),
    ])

    manque = {g["code"]: g["detail"] for g in _vue(resultat)["manque"]}

    assert manque["REJ-CASH-FACTURE-ILLISIBLE"] == "d" * 200
    assert manque["REJ-AP-MONTANT-ILLISIBLE"] == "e" * 199 + "…"


@pytest.mark.parametrize("longueur, attendu", [(160, "s" * 160), (161, "s" * 159 + "…")])
def test_le_detail_du_manque_de_l_alerte_est_abrege_a_cent_soixante_caracteres(longueur, attendu):
    verdict = validation.construire_verdict("REJ-PREVISION-SEUIL-A-CONFIGURER", "s" * longueur)

    page = _vue(_assembler([], verdict_seuil=verdict))

    assert page["alerte"]["manque"] == {"code": "REJ-PREVISION-SEUIL-A-CONFIGURER", "detail": attendu}


def test_un_manque_ne_cite_que_trois_exemples_mais_compte_tous_ses_flux():
    flux = [_flux_inconnu(f"f-{k}", AUJOURD_HUI + timedelta(days=k), ["REJ-CASH-FACTURE-ILLISIBLE"])
            for k in range(1, 6)]

    groupe = _vue(_assembler(flux))["manque"][0]

    assert groupe["nombre"] == 5 and groupe["exemples"] == ["f-1", "f-2", "f-3"]


def test_les_encaissements_non_comptes_ne_citent_que_trois_exemples_mais_les_comptent_tous():
    flux = [_flux(f"e-{k}", prevision.ENTREE, "1.00", AUJOURD_HUI - timedelta(days=k)) for k in range(1, 6)]

    groupe = _vue(_assembler(flux))["encaissements_non_comptes"][0]

    assert groupe["nombre"] == 5 and groupe["montant_connu"] == "5.00"
    assert groupe["exemples"] == ["e-5", "e-4", "e-3"], "les plus anciens d'abord"


def test_la_tete_du_registre_du_solde_est_abregee_a_seize_caracteres(taux, calendrier):
    resultat = _prevoir(taux, calendrier)

    tete = resultat["solde"]["source"]["registres"][0]["tete"]
    vue = _vue(resultat)["solde_initial"]["registres"][0]

    assert len(tete) == 64 and vue["tete"] == tete[:16] and len(vue["tete"]) == 16


def test_la_taille_mesuree_est_celle_du_socle_un_accent_compte_pour_un_caractere():
    objet = {"mention": "Analyse préparatoire IA — validation", "n": [1, 2]}

    assert prevision._taille(objet) == len(json.dumps(objet, ensure_ascii=False))
    assert prevision._taille(objet) < len(json.dumps(objet))


def test_une_page_qui_tient_exactement_dans_le_budget_est_rendue_la_precedente_ne_l_est_pas(taux, calendrier):
    resultat = _prevoir(taux, calendrier)
    complete = _vue(resultat, budget_caracteres=100000)
    exacte = len(json.dumps(complete, ensure_ascii=False))

    juste = _vue(resultat, budget_caracteres=exacte)
    un_de_moins = _vue(resultat, budget_caracteres=exacte - 1)

    assert juste == complete and juste["affichees"] == 6 and juste["prochain_depart"] is None
    assert un_de_moins["affichees"] == 5 and un_de_moins["prochain_depart"] == 5


def test_les_lignes_d_une_semaine_qui_tiennent_exactement_dans_le_budget_sont_rendues_toutes(taux, calendrier):
    resultat = _prevoir(taux, calendrier)
    complete = _semaine(resultat, 3, budget_caracteres=100000)
    exacte = len(json.dumps(complete, ensure_ascii=False))

    assert _semaine(resultat, 3, budget_caracteres=exacte)["affichees"] == complete["affichees"] == 4
    assert _semaine(resultat, 3, budget_caracteres=exacte - 1)["affichees"] == 3


# ------------------------------------------------------------------------------------------ l'assemblage, aux bornes
def test_le_cash_libre_prevu_est_absent_sans_le_resultat_du_cash_libre():
    resultat = _assembler([_flux("a", prevision.ENTREE, "10.00", AUJOURD_HUI)])

    assert resultat["cash_libre"] == {"montant": None, "manque": []}
    assert [s["cash_libre_prevu"] for s in resultat["semaines"]] == [None, None, None]


def test_un_solde_de_fin_de_semaine_a_zero_n_est_pas_un_deficit_un_cent_de_moins_l_est():
    resultat = _assembler([_flux("a", prevision.SORTIE, "1000.00", AUJOURD_HUI)])

    assert resultat["semaines"][0]["solde_fin"] == D("0.00") and resultat["semaines"][0]["en_deficit"] is False
    assert resultat["premiere_semaine_en_deficit"] is None

    resultat = _assembler([_flux("a", prevision.SORTIE, "1000.01", AUJOURD_HUI)])

    assert resultat["semaines"][0]["en_deficit"] is True and resultat["premiere_semaine_en_deficit"] == 1


def test_un_flux_de_zero_est_accepte_et_ne_change_pas_le_solde():
    resultat = _assembler([_flux("z", prevision.SORTIE, "0.00", AUJOURD_HUI)])

    assert resultat["semaines"][0]["sorties"] == D("0.00") and _soldes(resultat) == [D("1000.00")] * 3
    assert [ligne["id"] for ligne in resultat["semaines"][0]["lignes"]] == ["z"]


def test_seule_une_sortie_datee_avant_aujourd_hui_est_echue_une_entree_ne_l_est_jamais():
    resultat = _assembler([
        _flux("auj", prevision.SORTIE, "1.00", AUJOURD_HUI),
        _flux("demain", prevision.SORTIE, "1.00", AUJOURD_HUI + timedelta(days=1)),
        _flux("hier", prevision.SORTIE, "1.00", AUJOURD_HUI - timedelta(days=1)),
        _flux("entree", prevision.ENTREE, "1.00", AUJOURD_HUI + timedelta(days=2)),
    ])

    assert {ligne["id"]: ligne["echu"] for ligne in resultat["semaines"][0]["lignes"]} == {
        "hier": True, "auj": False, "demain": False, "entree": False}


def test_un_encaissement_dont_le_montant_est_inconnu_n_est_pas_compte_meme_avec_sa_date():
    resultat = _assembler([_flux_inconnu(
        "e-1", AUJOURD_HUI + timedelta(days=1), ["REJ-CREANCES-MONTANT-ILLISIBLE"], sens=prevision.ENTREE)])

    assert resultat["calculable"] is True and resultat["semaines"][0]["entrees"] == D("0.00")
    assert [(g["code"], g["nombre"], g["montant_connu"]) for g in resultat["encaissements_non_comptes"]] == [
        ("REJ-CREANCES-MONTANT-ILLISIBLE", 1, D("0.00"))]


def test_les_encaissements_non_comptes_sont_groupes_par_code_dans_l_ordre_des_codes_sous_leur_premier_manque():
    resultat = _assembler([
        _flux("e-echu-1", prevision.ENTREE, "20.00", AUJOURD_HUI - timedelta(days=3)),
        _flux("e-echu-2", prevision.ENTREE, "5.00", AUJOURD_HUI - timedelta(days=1)),
        _flux_inconnu("e-illisible", AUJOURD_HUI + timedelta(days=1),
                      ["REJ-CREANCES-MONTANT-ILLISIBLE", "REJ-CREANCES-DATE-ENVOI-INVALIDE"], sens=prevision.ENTREE),
    ])

    assert [(g["code"], g["nombre"], g["montant_connu"], g["flux"]) for g in resultat["encaissements_non_comptes"]] == [
        ("REJ-CREANCES-MONTANT-ILLISIBLE", 1, D("0.00"), ["e-illisible"]),
        ("REJ-PREVISION-ENCAISSEMENT-ECHU", 2, D("25.00"), ["e-echu-1", "e-echu-2"])]


def test_un_flux_a_deux_manques_les_dit_tous_les_deux_une_seule_fois_par_flux():
    resultat = _assembler([_flux_inconnu(
        "x", AUJOURD_HUI + timedelta(days=8),
        ["REJ-CASH-FACTURE-ILLISIBLE", "REJ-AP-MONTANT-ILLISIBLE", "REJ-AP-MONTANT-ILLISIBLE"])])

    assert [(g["code"], g["a_partir_de_semaine"], g["flux"]) for g in resultat["manque"]] == [
        ("REJ-AP-MONTANT-ILLISIBLE", 2, ["x"]), ("REJ-CASH-FACTURE-ILLISIBLE", 2, ["x"])]


def test_un_manque_dit_sa_semaine_la_plus_precoce_et_les_manques_se_suivent_par_semaine_puis_par_code():
    """Le flux sans date est traité en dernier (les dates inconnues sont à la fin) et bloque dès la semaine 1 : la
    semaine d'un code est la plus précoce, pas la première vue ; deux codes de la même semaine se suivent par code."""
    resultat = _assembler([
        _flux_inconnu("a", AUJOURD_HUI + timedelta(days=15), ["REJ-CASH-DAS-A-DECLARER"]),
        _flux_inconnu("b", None, ["REJ-CASH-DAS-A-DECLARER"], montant="5.00"),
        _flux_inconnu("c", AUJOURD_HUI + timedelta(days=16), ["REJ-AP-MONTANT-ILLISIBLE"]),
        _flux_inconnu("d", AUJOURD_HUI + timedelta(days=1), ["REJ-CASH-FACTURE-ILLISIBLE"]),
    ])

    assert [(g["code"], g["a_partir_de_semaine"], g["flux"]) for g in resultat["manque"]] == [
        ("REJ-CASH-DAS-A-DECLARER", 1, ["a", "b"]), ("REJ-CASH-FACTURE-ILLISIBLE", 1, ["d"]),
        ("REJ-AP-MONTANT-ILLISIBLE", 3, ["c"])]
    assert resultat["non_calculable_a_partir_de"] == 1


def test_un_flux_inconnu_apres_l_horizon_est_compte_a_part_et_ne_bloque_pas():
    apres = AUJOURD_HUI + timedelta(days=21)
    resultat = _assembler([
        _flux("connu", prevision.SORTIE, "5.00", apres),
        _flux_inconnu("inconnu", apres, ["REJ-CASH-FACTURE-ILLISIBLE"]),
        _flux("entree", prevision.ENTREE, "7.00", apres),
    ])

    assert resultat["calculable"] is True and resultat["manque"] == []
    assert resultat["au_dela_de_l_horizon"]["sorties"] == {"nombre": 2, "total": D("5.00"), "non_chiffres": 1}
    assert resultat["au_dela_de_l_horizon"]["entrees"] == {"nombre": 1, "total": D("7.00"), "non_chiffres": 0}
    assert _vue(resultat)["au_dela_de_l_horizon"] == {
        "entrees": {"nombre": 1, "total": "7.00"}, "sorties": {"nombre": 2, "total": "5.00", "non_chiffres": 1}}


def test_l_en_tete_dit_ce_qui_manque_au_cash_libre_d_aujourd_hui(taux, calendrier):
    declarees = {k: v for k, v in DECLARATIONS.items() if k != "das"}

    page = _vue(_prevoir(taux, calendrier, declarees=declarees))

    assert page["cash_libre_aujourd_hui"] == {"montant": None, "manque": ["das : REJ-CASH-DAS-A-DECLARER"]}


def test_l_empreinte_change_quand_seule_la_source_d_une_ligne_change():
    def avec(source):
        flux = _flux("a", prevision.SORTIE, "10.00", AUJOURD_HUI + timedelta(days=9))
        flux["source"] = source
        return _assembler([flux])["prevision_id"]

    assert avec("facture du fournisseur X") == avec("facture du fournisseur X")
    assert avec("facture du fournisseur X") != avec("facture du fournisseur Y")


def test_un_flux_qui_n_est_pas_un_objet_est_une_erreur_du_code_meme_avec_toutes_les_cles():
    with pytest.raises(ValueError, match="flux mal formé"):
        _assembler([sorted(prevision._CLES_FLUX)])


def test_les_reserves_d_un_flux_sont_uniques_et_triees():
    dette = {"type": "FACTURE", "id": "apf-1", "po_id": "PO-1", "fournisseur_id": "gentek", "numero_facture": "F-1",
             "date_base": "2026-09-14", "montant": D("10.00"), "manque": [], "reserves": ["REJ-Z", "REJ-A", "REJ-Z"]}

    assert prevision.flux_fournisseurs([dette], 30, None)[0]["reserves"] == ["REJ-A", "REJ-Z"]


def test_une_dette_dont_la_date_ou_le_montant_est_illisible_est_un_flux_inconnu_qui_dit_pourquoi():
    base = {"type": "FACTURE", "po_id": "PO-1", "fournisseur_id": "gentek", "numero_facture": "F-1", "manque": [],
            "reserves": []}

    sans_date = prevision.flux_fournisseurs(
        [{**base, "id": "apf-1", "date_base": "pas une date", "montant": D("10.00")}], 30, None)[0]
    sans_montant = prevision.flux_fournisseurs(
        [{**base, "id": "apf-2", "date_base": "2026-09-14", "montant": D("10.005")}], 30, None)[0]

    assert (sans_date["date"], sans_date["montant"]) == (None, D("10.00"))
    assert [m["code"] for m in sans_date["manque"]] == ["REJ-CASH-FACTURE-ILLISIBLE"]
    assert (sans_montant["date"], sans_montant["montant"]) == (date(2026, 10, 14), None)
    assert [m["code"] for m in sans_montant["manque"]] == ["REJ-AP-MONTANT-ILLISIBLE"]


def test_une_obligation_declaree_a_zero_ne_sort_pas_et_n_exige_aucune_date():
    declaree = {"montant": "0.00", "source": "déclaration fictive", "au": "2026-09-25"}
    composantes = {cle: cash_libre.composante_declaree(cle, declaree) for cle in ("paies", "das", "dettes")}

    assert prevision.flux_obligations(composantes, prevision.lire_echeances_obligations(None)) == []


# ----------------------------------------------------------------------------- les taxes, aux bornes de leurs périodes
def test_le_verdict_d_un_calendrier_illisible_est_celui_que_l_appelant_donne():
    verdict = validation.construire_verdict("REJ-CALENDRIER-ANNEE-NON-DECLAREE", "année 2027 absente (fictif)")

    flux = prevision.flux_taxes([], [], None, verdict, FISCAL, AUJOURD_HUI)

    assert [(f["id"], f["manque"]) for f in flux] == [("taxes:calendrier", [verdict])]


def test_une_remise_qui_finit_aujourd_hui_est_refusee_le_lendemain_elle_est_admise(calendrier):
    flux = prevision.flux_taxes([], [], calendrier, None, FISCAL, date(2026, 6, 30))

    assert [f["id"] for f in flux] == ["taxes:remise"]
    assert flux[0]["manque"][0]["code"] == "REJ-FISCAL-CONFIGURATION-INVALIDE"
    assert prevision.flux_taxes([], [], calendrier, None, FISCAL, date(2026, 7, 1)) == []


def test_la_taxe_d_un_particulier_en_affaires_est_due_au_30_avril_pas_au_15_juin(calendrier):
    clients = [{"facture_id": "F-1", "date_envoi": "2026-08-10T09:00:00-04:00", "statut": "ENVOYEE",
                "taxes": _taxes("100.00", "199.50")}]
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": True,
              "taxes_remises_jusqu_au": "2025-12-31"}

    flux = prevision.flux_taxes(clients, [], calendrier, None, fiscal, AUJOURD_HUI)

    assert [(f["id"], f["montant"], f["date"]) for f in flux] == [
        ("taxes:2026-01-01:2026-12-31", D("299.50"), date(2027, 4, 30))]


def test_une_periode_a_cheval_sur_deux_annees_compte_sa_premiere_journee_et_cite_la_version_de_son_annee_de_fin(
        calendrier):
    """Trimestrielle avec un exercice qui finit en janvier : la période du 2025-11-01 au 2026-01-31 (limite de paiement
    le 2026-03-02) est au calendrier de 2026, pas de 2025. La facture du 2025-11-01, le lendemain de la remise, y
    compte. Le 2026-01-31 la période finit aujourd'hui : elle n'est pas terminée."""
    fiscal = {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 1, "taxes_remises_jusqu_au": "2025-10-31"}
    clients = [{"facture_id": "F-1", "date_envoi": "2025-11-01T09:00:00-05:00", "statut": "ENVOYEE",
                "taxes": _taxes("100.00", "199.50")}]

    flux = prevision.flux_taxes(clients, [], calendrier, None, fiscal, date(2026, 1, 31))

    assert [(f["id"], f["montant"], f["date"], f["partielle"]) for f in flux] == [
        ("taxes:2025-11-01:2026-01-31", D("299.50"), date(2026, 3, 2), True)]
    assert "2026-v1" in flux[0]["regle_de_date"] and "2025-v1" not in flux[0]["regle_de_date"]
    assert "période non terminée" in flux[0]["source"]
    assert prevision.flux_taxes(clients, [], calendrier, None, fiscal, date(2026, 2, 1))[0]["partielle"] is False


def test_des_factures_fournisseurs_apres_la_fin_du_calendrier_connu_bloquent_aussi(calendrier):
    fournisseurs = [
        {"facture_fournisseur_id": "apf-1", "date_facture": "2027-02-10", "taxes": _taxes("30.00", "59.85")}]
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": False,
              "taxes_remises_jusqu_au": "2025-12-31"}

    flux = prevision.flux_taxes([], fournisseurs, calendrier, None, fiscal, date(2027, 3, 1))

    assert [f["id"] for f in flux] == ["taxes:couverture"]
    assert flux[0]["manque"][0]["code"] == "REJ-CALENDRIER-ANNEE-NON-DECLAREE"


def test_un_trou_dans_le_calendrier_arrete_la_couverture_et_rien_apres_lui_n_est_date(calendrier):
    """Le trimestre du 2026-07-01 au 2026-09-30 manque au calendrier alors que celui d'après y est : la couverture
    s'arrête à la remise, le trimestre suivant n'est pas daté (sa taxe serait comptée à côté de ce qui manque)."""
    trou = copy.deepcopy(calendrier)
    trou[2026]["periodes"]["trimestrielle"] = [
        p for p in trou[2026]["periodes"]["trimestrielle"] if p["fin"] != date(2026, 9, 30)]
    clients = [
        {"facture_id": "F-1", "date_envoi": "2026-08-10T09:00:00-04:00", "statut": "ENVOYEE",
         "taxes": _taxes("100.00", "199.50")},
        {"facture_id": "F-2", "date_envoi": "2026-11-10T09:00:00-05:00", "statut": "ENVOYEE",
         "taxes": _taxes("50.00", "99.75")},
    ]

    flux = prevision.flux_taxes(clients, [], trou, None, FISCAL, AUJOURD_HUI)

    assert [f["id"] for f in flux] == ["taxes:couverture"]
    assert "2026-06-30" in flux[0]["manque"][0]["detail"]


def test_la_couverture_du_calendrier_ne_continue_que_par_une_periode_qui_commence_le_lendemain():
    def periode(debut, fin):
        return {"debut": debut, "fin": fin}

    remises = date(2026, 6, 30)
    contigues = [periode(date(2026, 7, 1), date(2026, 9, 30)), periode(date(2026, 10, 1), date(2026, 12, 31))]

    assert prevision._couvert_jusqu_au(contigues, remises) == date(2026, 12, 31)
    assert prevision._couvert_jusqu_au([periode(date(2026, 6, 1), date(2026, 8, 31))], remises) == remises, (
        "une période qui chevauche la remise ne prouve rien")
    assert prevision._couvert_jusqu_au(
        [contigues[0], periode(date(2026, 11, 1), date(2026, 12, 31))], remises) == date(2026, 9, 30)
    assert prevision._couvert_jusqu_au([], remises) == remises


# ------------------------------------------------------------------------------------- les dettes, dans leur ordre
def test_l_attendu_d_un_po_recu_en_deux_fois_est_date_de_sa_premiere_reception(taux):
    a_payer = _a_payer(taux, receptions=(("e-1", "PO-1", "30", "2026-09-15T09:00:00-04:00"),
                                         ("e-2", "PO-1", "30", "2026-09-20T09:00:00-04:00")), factures=())

    dettes, verdict = cap.dettes_datables(a_payer, taux)

    assert verdict is None
    assert [(d["type"], d["montant"], d["date_base"]) for d in dettes] == [
        ("ATTENDU", D("344.93"), "2026-09-15T09:00:00-04:00")], "la plus prudente : la première, pas la dernière"


def test_les_po_se_suivent_par_premiere_reception_puis_par_identifiant_a_egalite(taux):
    a_payer = _a_payer(taux, receptions=(("e-1", "PO-A", "20", "2026-09-16T09:00:00-04:00"),
                                         ("e-2", "PO-B", "20", "2026-09-15T09:00:00-04:00"),
                                         ("e-3", "PO-D", "20", "2026-09-17T09:00:00-04:00"),
                                         ("e-4", "PO-C", "20", "2026-09-17T09:00:00-04:00")), factures=())

    dettes, _ = cap.dettes_datables(a_payer, taux)

    assert [d["po_id"] for d in dettes] == ["PO-B", "PO-A", "PO-C", "PO-D"]


def test_une_facture_sans_po_annulee_n_est_plus_une_dette(taux):
    a_payer = _a_payer(taux, receptions=(), factures=())
    _, verdict = cap.saisir_facture_sans_po(
        fournisseur_id="Pétro-Nord (fictif)", categorie="carburant", numero_facture="C-1", date_facture="2026-09-25",
        montant_avant_taxes="100.00", total_facture=None, saisi_par="nathan", voie="appareil",
        horodatage="2026-09-26T10:00:00-04:00", dictionnaire_taux=taux, categories_configurees=("carburant",),
        registre_cible=a_payer)
    assert verdict is None, verdict
    assert [d["montant"] for d in cap.dettes_datables(a_payer, taux)[0]] == [D("114.98")]
    (lue,) = cap.factures_saisies(a_payer)
    _, verdict = cap.annuler_facture_fournisseur(
        facture_fournisseur_id=lue["facture_fournisseur_id"], motif="saisie en double (fictif)", annule_par="nathan",
        role="nathan_owner", voie="approbation", horodatage="2026-09-27T10:00:00-04:00", registre_cible=a_payer,
        revision_attendue=lue["corrections"])
    assert verdict is None, verdict

    dettes, _ = cap.dettes_datables(a_payer, taux)
    resume, _ = cap.resume_a_payer(a_payer, taux)

    assert dettes == [] and resume["a_payer_apres_taxes"] == D("0.00")


def test_tout_code_de_verdict_du_module_est_au_catalogue_ferme_de_m5():
    """Un code que le module emmène dans une réponse sans passer par `construire_verdict` (l'encaissement échu) doit
    quand même être au catalogue fermé : sinon aucun consommateur ne le connaît."""
    source = (_RACINE_M5 / "src" / "m5_financecore" / "prevision.py").read_text(encoding="utf-8")
    codes = set(re.findall(r"REJ-[A-Z0-9]+(?:-[A-Z0-9]+)*", source))

    assert codes and codes <= set(validation.CODES_M5_LIST), sorted(codes - set(validation.CODES_M5_LIST))
    assert prevision._CODE_ECHU in codes
