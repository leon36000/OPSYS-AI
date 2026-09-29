"""PLAN T4.16 : le cash libre réel (M5.5, M5.14) : `cash_libre.py`, calcul pur, chiffré à la cent près.

    cash libre = solde - TPS/TVQ à remettre - paies - DAS - comptes à payer - dettes - réserves critiques

Le cas de référence (fictif, AGENTS.md) est calculé ici À LA MAIN, en constantes, jamais avec le code qu'il éprouve :

    solde                  50000.00 - 12345.67                                   = 37654.33
    TPS/TVQ à remettre     depuis la remise du 2026-06-30 (cinq factures clients envoyées, une à la limite de la
                           fenêtre, deux fournisseurs dont un avant la remise) :
                           TPS 676.67 - 15.00 = 661.67 ; TVQ 1349.95 - 29.93 = 1320.02     = 1981.69
    paies (déclarées)                                                                       = 4200.00
    DAS (déclarés)                                                                          = 1350.75
    comptes à payer        PO-1 344.93 + PO-2 114.98                                        =  459.91
    dettes (déclarées)                                                                      =  800.00
    réserves               un mouvement de réserve                                          = 1000.00
    cash libre             37654.33 - 9792.35                                               = 27861.98

Ce qui est éprouvé : chaque composante porte sa source et sa fraîcheur ; une composante inconnue est « non calculable,
manque X », jamais zéro (`cash_libre` est alors `None`, avec un `au_plus` qui n'est pas un cash disponible) ; les
fenêtres de dates, le plancher à zéro d'une taxe nette négative, l'arrondi `ROUND_HALF_UP` du résultat, un déficit
rendu tel quel, et la forme JSON de la réponse. Le branchement sur les vrais registres est dans
test_cash_libre_outils.py.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import cash_libre, facturation, registre, soldes, taux_fiscaux, validation
from m5_financecore import comptes_a_payer as cap
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION

FICTIF = True
CHEMIN_TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
REMISES = date(2026, 6, 30)
D = Decimal

DECLARATIONS = {
    "paies": {"montant": "4200.00", "source": "brouillon de paie du 2026-09-25 (fictif)", "au": "2026-09-25"},
    "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
    "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
}


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(CHEMIN_TAUX)
    assert erreurs == []
    return dictionnaire


# --------------------------------------------------------------------------------------- le cas fictif
def _mouvements():
    reg = registre.Registre()
    for montant, type_mouvement, horodatage in (
        ("50000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00"),
        ("-12345.67", "DECAISSEMENT", "2026-08-15T12:00:00-04:00"),
        ("1000.00", "PROVISION", "2026-09-10T12:00:00-04:00"),
    ):
        registre.enregistrer_mouvement({"montant": D(montant), "type_mouvement": type_mouvement,
                                        "horodatage": horodatage, "classe_retention": "STANDARD",
                                        "source": "test"}, reg)
    return reg


def _factures(taux, extras=()):
    reg = registre.Registre()
    lignes = (
        ("F-1", "D-1", "10000.00", "2026-07-15", "ENVOYEE"),
        ("F-2", "D-2", "3333.33", "2026-08-20", "PAYEE"),
        ("F-3", "D-3", "1000.00", "2026-06-10", "ENVOYEE"),   # avant la remise : déjà remise
        ("F-4", "D-4", "500.00", "2026-09-01", "BROUILLON"),   # jamais envoyée : aucune taxe collectée
        ("F-5", "D-5", "200.00", "2026-07-01", "ENVOYEE"),    # le lendemain de la remise : incluse
        ("F-6", "D-6", "100.00", "2026-06-30", "ENVOYEE"),    # le jour même de la remise : exclue
        *extras,
    )
    for facture_id, devis, prix, jour, statut in lignes:
        facture, verdict = facturation.creer_facture_brouillon(
            facture_id, "CH-1", devis, "C-1",
            [{"description": "travaux (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": prix,
              "reference_ligne_devis": "L-1"}], f"{jour}T09:00:00-04:00", taux, reg)
        assert verdict is None, verdict
        if statut in ("ENVOYEE", "PAYEE"):
            assert facturation.envoyer_facture(facture_id, f"{jour}T09:30:00-04:00", reg)[1] is None
        if statut == "PAYEE":
            assert facturation.marquer_facture_payee(facture_id, "nathan", "2026-09-05T09:00:00-04:00", reg)[1] is None
    return reg


def _charge(evenement_id, po_id, quantite, horodatage):
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": horodatage, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": quantite, "quantite_recue": quantite,
                    "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": "5.00", "verdict_prix_reception": "PRIX_CATALOGUE",
                    "ecart_prix_critique": False}],
    }


def _a_payer(taux):
    """PO-1 : 60 x 5.00 = 300.00 reçus et facturés (344.93 avec taxes). PO-2 : 20 x 5.00 = 100.00, facture du
    2026-06-20 (114.98 avec taxes), datée AVANT la remise : elle est à payer, mais son crédit de taxe est déjà
    pris."""
    reg = registre.Registre()
    for evenement, po, quantite, horodatage in (("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),
                                                ("e-2", "PO-2", "20", "2026-09-16T09:00:00-04:00")):
        entree, verdict = cap.construire_reception(_charge(evenement, po, quantite, horodatage))
        assert verdict is None, verdict
        assert cap.enregistrer_reception(entree, reg)[1] is None
    for po, numero, jour, montant in (("PO-1", "F-1001", "2026-09-14", "300.00"),
                                      ("PO-2", "F-2001", "2026-06-20", "100.00")):
        resultat, verdict = cap.saisir_facture_fournisseur(
            po_id=po, fournisseur_id="gentek", numero_facture=numero, date_facture=jour, montant_avant_taxes=montant,
            total_facture=None, saisi_par="nathan", voie="appareil", horodatage="2026-09-20T10:00:00-04:00",
            dictionnaire_taux=taux, registre_cible=reg)
        assert verdict is None, verdict
    return reg


def _assembler(taux, *, mouvements=None, factures=None, a_payer=None, remises=REMISES, verdict_remise=None,
               declarees=DECLARATIONS, reserves_declarees=None):
    """Ce que `outils._cash_libre` fait, avec des registres en mémoire : l'assemblage des sept composantes."""
    mouvements = _mouvements() if mouvements is None else mouvements
    factures = _factures(taux) if factures is None else factures
    a_payer = _a_payer(taux) if a_payer is None else a_payer
    solde = soldes.calculer_solde(mouvements)
    decrit = soldes.decrire_mouvements(mouvements)
    provisions, nombre, derniere = soldes.calculer_provisions(mouvements)
    clients = _envoyees_et_payees(factures)
    fournisseurs = cap.factures_saisies(a_payer)
    resume, verdict_ap = cap.resume_a_payer(a_payer, taux)
    registres = [cash_libre.registre_lu("factures", factures.lire()),
                 cash_libre.registre_lu("comptes_a_payer", a_payer.lire())]
    return cash_libre.calculer_cash_libre(
        cash_libre.composante_solde(solde, decrit),
        [
            cash_libre.composante_taxes(clients, fournisseurs, remises, verdict_remise, registres),
            cash_libre.composante_declaree("paies", declarees.get("paies")),
            cash_libre.composante_declaree("das", declarees.get("das")),
            cash_libre.composante_comptes_a_payer(resume, verdict_ap, registres[1:]),
            cash_libre.composante_declaree("dettes", declarees.get("dettes")),
            cash_libre.composante_reserves(provisions, nombre, derniere, decrit, reserves_declarees),
        ],
    )


def _envoyees_et_payees(factures):
    return [*facturation.factures_par_statut(factures, "ENVOYEE"), *facturation.factures_par_statut(factures, "PAYEE")]


def _par_id(resultat):
    return {c["id"]: c for c in resultat["composantes"]}


def test_le_cas_fictif_est_chiffre_a_la_cent_pres(taux):
    resultat = _assembler(taux)

    assert resultat["solde"]["montant"] == D("37654.33")
    montants = {cid: c["montant"] for cid, c in _par_id(resultat).items()}
    assert montants == {
        "taxes_a_remettre": D("1981.69"), "paies": D("4200.00"), "das": D("1350.75"),
        "comptes_a_payer": D("459.91"), "dettes": D("800.00"), "reserves": D("1000.00"),
    }
    assert resultat["calculable"] is True and resultat["au_plus"] is None and resultat["manque"] == []
    assert resultat["cash_libre"] == D("27861.98")
    # la somme des composantes retranchées, refaite à la main : 9792.35
    assert D("37654.33") - D("9792.35") == resultat["cash_libre"]


def test_les_taxes_du_cas_fictif_sont_detaillees_par_taxe_a_la_cent_pres(taux):
    detail = _par_id(_assembler(taux))["taxes_a_remettre"]["detail"]

    assert detail["depuis"] == "2026-07-01"
    assert detail["tps"] == {"collectee": "676.67", "credits_intrants": "15.00", "nette": "661.67",
                             "a_remettre": "661.67"}
    assert detail["tvq"] == {"collectee": "1349.95", "credits_intrants": "29.93", "nette": "1320.02",
                             "a_remettre": "1320.02"}
    assert (detail["factures_clients"], detail["factures_fournisseurs"]) == (3, 1)
    assert detail["a_remettre"] == "1981.69"


def test_la_fenetre_de_taxes_commence_le_lendemain_de_la_remise(taux):
    """Le 30 juin (jour de la remise) est exclu, le 1er juillet inclus : une facture du 30 juin est déjà dans la
    déclaration remise."""
    factures = _factures(taux)
    clients = _envoyees_et_payees(factures)

    avant = cash_libre.calculer_taxes_nettes(clients, [], apres=date(2026, 6, 29))
    apres = cash_libre.calculer_taxes_nettes(clients, [], apres=REMISES)
    apres_tout = cash_libre.calculer_taxes_nettes(clients, [], apres=date(2026, 8, 20))

    assert avant["factures_clients"] == 4 and apres["factures_clients"] == 3 and apres_tout["factures_clients"] == 0
    assert apres["collectee"]["tps_federale"] == D("676.67")
    assert apres_tout["total_a_remettre"] == D("0.00")


def test_la_fenetre_de_taxes_a_aussi_une_borne_haute(taux):
    factures = _factures(taux)
    clients = _envoyees_et_payees(factures)

    juillet = cash_libre.calculer_taxes_nettes(clients, [], apres=REMISES, jusqu_a=date(2026, 7, 31))

    assert juillet["factures_clients"] == 2  # F-1 (15 juillet) et F-5 (1er juillet)
    assert juillet["collectee"]["tps_federale"] == D("510.00") and juillet["collectee"]["tvq_quebec"] == D("1017.45")


def test_seuls_les_statuts_envoyee_et_payee_comptent_l_adaptateur_le_garantit_ici_le_brouillon_est_exclu(taux):
    factures = _factures(taux)
    tous = [*facturation.factures_par_statut(factures, "ENVOYEE"), *facturation.factures_par_statut(factures, "PAYEE")]

    assert {f["facture_id"] for f in tous} == {"F-1", "F-2", "F-3", "F-5", "F-6"}
    assert facturation.factures_par_statut(factures, "BROUILLON")[0]["facture_id"] == "F-4"


def test_une_taxe_nette_negative_n_est_jamais_de_l_argent_et_les_deux_taxes_ne_se_compensent_pas(taux):
    """Crédits supérieurs à la taxe collectée : un remboursement à venir, jamais de l'argent disponible. Prudent : la
    TPS négative ne réduit pas la TVQ positive."""
    a_payer = _a_payer(taux)
    clients = [{"facture_id": "F-X", "date_envoi": "2026-08-01T09:00:00-04:00", "statut": "ENVOYEE", "taxes": [
        {"id": "tps_federale", "montant": D("10.00")}, {"id": "tvq_quebec", "montant": D("500.00")}]}]

    taxes_nettes = cash_libre.calculer_taxes_nettes(clients, cap.factures_saisies(a_payer), apres=REMISES)

    # crédits de PO-1 (15.00 et 29.93) : TPS 10.00 - 15.00 = -5.00 ; TVQ 500.00 - 29.93 = 470.07
    assert taxes_nettes["nette"] == {"tps_federale": D("-5.00"), "tvq_quebec": D("470.07")}
    assert taxes_nettes["a_remettre"] == {"tps_federale": D("0"), "tvq_quebec": D("470.07")}
    assert taxes_nettes["total_a_remettre"] == D("470.07"), "5.00 de remboursement n'est pas soustrait de 470.07"


def test_un_attendu_non_facture_ne_donne_aucun_credit_de_taxe(taux):
    """Un crédit de taxe sur intrants exige la facture fournisseur : la marchandise reçue mais pas encore facturée
    (PO-3) est un compte à payer, jamais un crédit."""
    a_payer = _a_payer(taux)
    entree, _ = cap.construire_reception(_charge("e-3", "PO-3", "100", "2026-09-17T09:00:00-04:00"))
    cap.enregistrer_reception(entree, a_payer)

    credits = cash_libre.calculer_taxes_nettes([], cap.factures_saisies(a_payer), apres=REMISES)["credits"]

    assert credits == {"tps_federale": D("15.00"), "tvq_quebec": D("29.93")}
    resume, _ = cap.resume_a_payer(a_payer, taux)
    assert resume["a_payer_apres_taxes"] == D("459.91") + D("574.88"), "PO-3 : 500.00 + 74.88 de taxes"


# ---------------------------------------------------------- une composante inconnue : non calculable, jamais zéro
@pytest.mark.parametrize("cle, code, au_plus", [
    # solde 37654.33 moins tout ce qui est connu (les autres composantes) : jamais zéro à la place de l'inconnu
    ("paies", "REJ-CASH-PAIE-A-DECLARER", "32061.98"),
    ("das", "REJ-CASH-DAS-A-DECLARER", "29212.73"),
    ("dettes", "REJ-CASH-DETTES-A-DECLARER", "28661.98"),
])
def test_paies_das_dettes_non_declares_donnent_non_calculable_jamais_zero(taux, cle, code, au_plus):
    declarees = {k: v for k, v in DECLARATIONS.items() if k != cle}

    resultat = _assembler(taux, declarees=declarees)

    composante = _par_id(resultat)[cle]
    assert composante["statut"] == "NON_CALCULABLE" and composante["montant"] is None
    assert [m["code"] for m in composante["manque"]] == [code]
    assert f"configuration.obligations_declarees.{cle}" in composante["manque"][0]["detail"]
    assert resultat["calculable"] is False and resultat["cash_libre"] is None
    assert resultat["au_plus"] == D(au_plus), "le solde moins ce qui est connu ; ce qui manque ne peut que le réduire"
    assert {"composante": cle, "code": code} in resultat["manque"]


def test_sans_aucune_reserve_posee_ni_declaree_les_reserves_sont_a_declarer(taux):
    mouvements = registre.Registre()
    registre.enregistrer_mouvement({"montant": D("50000.00"), "type_mouvement": "ENCAISSEMENT",
                                    "horodatage": "2026-08-01T12:00:00-04:00", "classe_retention": "STANDARD",
                                    "source": "test"}, mouvements)

    resultat = _assembler(taux, mouvements=mouvements)

    reserves = _par_id(resultat)["reserves"]
    assert reserves["montant"] is None and reserves["statut"] == "NON_CALCULABLE"
    assert reserves["manque"][0]["code"] == "REJ-CASH-RESERVES-A-DECLARER"
    assert "GATE NATHAN" in reserves["manque"][0]["detail"]
    assert resultat["cash_libre"] is None


def test_un_zero_declare_est_un_zero_connu_avec_sa_source_et_sa_date(taux):
    """Aucune réserve voulue : seule une déclaration explicite écrit ce zéro, avec sa source et sa date."""
    mouvements = registre.Registre()
    registre.enregistrer_mouvement({"montant": D("50000.00"), "type_mouvement": "ENCAISSEMENT",
                                    "horodatage": "2026-08-01T12:00:00-04:00", "classe_retention": "STANDARD",
                                    "source": "test"}, mouvements)
    declaration = {"montant": "0.00", "source": "décision de Nathan : aucune réserve (fictif)", "au": "2026-09-28"}

    resultat = _assembler(taux, mouvements=mouvements, reserves_declarees=declaration)

    reserves = _par_id(resultat)["reserves"]
    assert reserves["montant"] == D("0.00") and reserves["statut"] == "CALCULE"
    assert reserves["fraicheur"] == {"derniere_piece": "2026-09-28", "pieces": 1}
    assert "décision de Nathan" in reserves["source"]["description"]
    assert resultat["cash_libre"] == (
        D("50000.00") - D("1981.69") - D("4200.00") - D("1350.75") - D("459.91") - D("800.00"))


def test_une_reserve_posee_l_emporte_sur_une_declaration(taux):
    declaration = {"montant": "99999.00", "source": "ignorée : des réserves sont déjà posées", "au": "2026-09-28"}

    reserves = _par_id(_assembler(taux, reserves_declarees=declaration))["reserves"]

    assert reserves["montant"] == D("1000.00") and "mouvements" in reserves["source"]["description"]


def test_sans_date_de_derniere_remise_les_taxes_sont_non_calculables_avec_le_verdict_qui_dit_quoi_declarer(taux):
    verdict = validation.construire_verdict("REJ-FISCAL-REMISE-A-DECLARER", detail="déclarer la dernière remise")

    resultat = _assembler(taux, remises=None, verdict_remise=verdict)

    taxes = _par_id(resultat)["taxes_a_remettre"]
    assert taxes["montant"] is None and taxes["manque"] == [verdict] and taxes["detail"] is None
    assert resultat["cash_libre"] is None
    # 37654.33 - 4200.00 - 1350.75 - 459.91 - 800.00 - 1000.00 : les taxes inconnues ne sont pas comptées comme zéro
    assert resultat["au_plus"] == D("29843.67")


def test_une_facture_illisible_rend_les_taxes_non_calculables_sans_les_ignorer(taux):
    factures = _factures(taux)
    clients = [*facturation.factures_par_statut(factures, "ENVOYEE"), {"facture_id": "F-CASSEE",
               "date_envoi": "2026-08-01T09:00:00-04:00", "statut": "ENVOYEE", "taxes": "illisible"}]
    composante = cash_libre.composante_taxes(clients, [], REMISES, None, [])

    assert composante["montant"] is None and composante["statut"] == "NON_CALCULABLE"
    assert composante["manque"][0]["code"] == "REJ-CASH-FACTURE-ILLISIBLE"
    assert "F-CASSEE" in composante["manque"][0]["detail"]


@pytest.mark.parametrize("facture", [
    {"facture_id": "F-A", "date_envoi": "hier", "taxes": [{"id": "tps_federale", "montant": D("1")},
                                                            {"id": "tvq_quebec", "montant": D("1")}]},
    {"facture_id": "F-B", "taxes": [
        {"id": "tps_federale", "montant": D("1")}, {"id": "tvq_quebec", "montant": D("1")}]},
    {"facture_id": "F-C", "date_envoi": "2026-08-01T09:00:00-04:00", "taxes": [
        {"id": "tps_federale", "montant": D("1")}]},
    {"facture_id": "F-D", "date_envoi": "2026-08-01T09:00:00-04:00", "taxes": [
        {"id": "tps_federale", "montant": D("-1")}, {"id": "tvq_quebec", "montant": D("1")}]},
    {"facture_id": "F-E", "date_envoi": "2026-08-01T09:00:00-04:00", "taxes": [
        {"id": "tps_federale", "montant": 1.0}, {"id": "tvq_quebec", "montant": D("1")}]},
    {"facture_id": "F-F", "date_envoi": "2026-08-01T09:00:00-04:00", "taxes": [
        {"id": "tps_federale", "montant": D("NaN")}, {"id": "tvq_quebec", "montant": D("1")}]},
    {"facture_id": "F-G", "date_envoi": "2026-08-01T09:00:00-04:00", "taxes": [
        {"id": "tps_federale", "montant": D("1")}, {"id": "tps_federale", "montant": D("1")}]},
    {"facture_id": "F-H", "date_envoi": "2026-08-01T09:00:00-04:00", "taxes": [
        {"id": "gst_inconnue", "montant": D("1")}, {"id": "tvq_quebec", "montant": D("1")}]},
    {"facture_id": "F-I", "date_envoi": "2026-08-01T09:00:00-04:00"},
    {"facture_id": "F-J", "date_envoi": "2026-08-01T09:00:00-04:00", "taxes": [
        {"id": "tps_federale", "montant": D("1")}, {"id": "tvq_quebec", "montant": D("1")},
        {"id": "tps_federale", "montant": D("1")}]},
])
def test_une_facture_dont_la_date_ou_la_taxe_est_illisible_est_listee_et_jamais_comptee(facture):
    taxes = cash_libre.calculer_taxes_nettes([facture], [], apres=REMISES)

    assert taxes["illisibles"] == [facture["facture_id"]]
    assert taxes["factures_clients"] == 0 and taxes["total_a_remettre"] == D("0.00")


def test_une_facture_ancienne_dont_la_taxe_est_illisible_n_alerte_pas(taux):
    """Datée avant la remise, elle est hors fenêtre : sa taxe est déjà remise, illisible ou non."""
    ancienne = {"facture_id": "F-ANCIENNE", "date_envoi": "2026-05-01T09:00:00-04:00", "taxes": "illisible"}

    assert cash_libre.calculer_taxes_nettes([ancienne], [], apres=REMISES)["illisibles"] == []


def test_un_po_dont_le_prix_manque_rend_les_comptes_a_payer_non_calculables_avec_le_plancher_connu(taux):
    a_payer = _a_payer(taux)
    charge = _charge("e-9", "PO-9", "10", "2026-09-18T09:00:00-04:00")
    charge["lignes"][0]["prix_unitaire_prevu"] = None
    entree, verdict = cap.construire_reception(charge)
    assert verdict is None and "REJ-AP-PRIX-PO-ABSENT" in entree["manque"]
    cap.enregistrer_reception(entree, a_payer)

    resultat = _assembler(taux, a_payer=a_payer)

    ap = _par_id(resultat)["comptes_a_payer"]
    assert ap["montant"] is None and ap["statut"] == "NON_CALCULABLE"
    assert ap["plancher"] == D("459.91"), "les factures saisies sont une dette ferme : le plancher"
    assert ap["manque"][0]["code"] == "REJ-CASH-COMPTES-A-PAYER-INCOMPLETS"
    assert ap["detail"]["po_non_calculables"] == [{"po_id": "PO-9", "manque": ["REJ-AP-PRIX-PO-ABSENT"]}]
    assert resultat["cash_libre"] is None
    # 37654.33 - 1981.69 - 4200.00 - 1350.75 - 459.91 (plancher) - 800.00 - 1000.00
    assert resultat["au_plus"] == D("27861.98")


def test_un_taux_fiscal_manquant_rend_les_comptes_a_payer_non_calculables(taux):
    composante = cash_libre.composante_comptes_a_payer(
        None, validation.construire_verdict("REJ-TAUX-INCONNU", detail="tps_federale absent"), [])

    assert composante["montant"] is None and composante["manque"][0]["code"] == "REJ-TAUX-INCONNU"


def test_les_comptes_a_payer_portent_la_reserve_de_l_unite_des_prix_des_qu_un_po_existe(taux):
    resultat = _assembler(taux)

    assert _par_id(resultat)["comptes_a_payer"]["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert resultat["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    sans_po = _assembler(taux, a_payer=registre.Registre())
    assert _par_id(sans_po)["comptes_a_payer"]["reserves"] == [] and sans_po["reserves"] == []
    assert _par_id(sans_po)["comptes_a_payer"]["montant"] == D("0.00"), "aucune réception connue : rien à payer connu"


def test_sans_aucun_mouvement_le_solde_n_est_pas_connu_et_aucun_chiffre_n_est_donne(taux):
    resultat = _assembler(taux, mouvements=registre.Registre())

    assert resultat["solde"]["montant"] is None and resultat["solde"]["statut"] == "NON_CALCULABLE"
    assert resultat["solde"]["manque"][0]["code"] == "REJ-CASH-SOLDE-ABSENT"
    assert resultat["cash_libre"] is None and resultat["au_plus"] is None
    assert "Aucun chiffre" in cash_libre.vue_cash_libre(resultat)["lecture"]


def test_un_deficit_est_rendu_tel_quel_jamais_ramene_a_zero(taux):
    mouvements = registre.Registre()
    registre.enregistrer_mouvement({"montant": D("5000.00"), "type_mouvement": "ENCAISSEMENT",
                                    "horodatage": "2026-08-01T12:00:00-04:00", "classe_retention": "STANDARD",
                                    "source": "test"}, mouvements)
    registre.enregistrer_mouvement({"montant": D("100.00"), "type_mouvement": "PROVISION",
                                    "horodatage": "2026-08-02T12:00:00-04:00", "classe_retention": "STANDARD",
                                    "source": "test"}, mouvements)

    resultat = _assembler(taux, mouvements=mouvements)

    # 5000.00 - 1981.69 - 4200.00 - 1350.75 - 459.91 - 800.00 - 100.00 = -3892.35
    assert resultat["cash_libre"] == D("-3892.35")
    vue = cash_libre.vue_cash_libre(resultat)
    assert vue["cash_libre"] == "-3892.35" and vue["en_deficit"] is True and "déficit" in vue["lecture"]


def test_le_resultat_est_arrondi_une_fois_au_demi_cent_superieur(taux):
    """`ROUND_HALF_UP` (règle des taxes, taxes.py) et non l'arrondi du banquier : 100.005 donne 100.01."""
    mouvements = registre.Registre()
    registre.enregistrer_mouvement({"montant": D("100.005"), "type_mouvement": "ENCAISSEMENT",
                                    "horodatage": "2026-08-01T12:00:00-04:00", "classe_retention": "STANDARD",
                                    "source": "test"}, mouvements)
    declarees = {cle: {"montant": "0.00", "source": "aucune (fictif)", "au": "2026-09-01"} for cle in DECLARATIONS}

    resultat = _assembler(taux, mouvements=mouvements, factures=registre.Registre(), a_payer=registre.Registre(),
                          declarees=declarees, reserves_declarees=declarees["paies"])

    assert resultat["cash_libre"] == D("100.01")


# --------------------------------------------------------------------------- source, fraîcheur, forme
def test_chaque_composante_porte_sa_source_et_sa_fraicheur(taux):
    resultat = _assembler(taux)

    for composante in [resultat["solde"], *resultat["composantes"]]:
        assert composante["source"]["description"], composante["id"]
        assert set(composante["fraicheur"]) == {"derniere_piece", "pieces"}
        assert composante["fraicheur"]["pieces"] >= 1 and composante["fraicheur"]["derniere_piece"]
    par_id = _par_id(resultat)
    assert resultat["solde"]["fraicheur"] == {"derniere_piece": "2026-09-10T12:00:00-04:00", "pieces": 3}
    assert par_id["taxes_a_remettre"]["fraicheur"] == {"derniere_piece": "2026-09-14", "pieces": 4}
    assert par_id["paies"]["fraicheur"] == {"derniere_piece": "2026-09-25", "pieces": 1}
    assert par_id["comptes_a_payer"]["fraicheur"] == {"derniere_piece": "2026-09-20T10:00:00-04:00", "pieces": 4}
    assert par_id["reserves"]["fraicheur"] == {"derniere_piece": "2026-09-10T12:00:00-04:00", "pieces": 1}
    assert "déclaration du propriétaire" in par_id["paies"]["source"]["description"]
    assert "brouillon de paie" in par_id["paies"]["source"]["description"]


def test_la_source_d_un_registre_dit_sa_taille_et_la_tete_de_sa_chaine(taux):
    mouvements = _mouvements()
    resultat = _assembler(taux, mouvements=mouvements)

    (source,) = resultat["solde"]["source"]["registres"]

    assert source == {"registre": "mouvements", "taille": 3, "tete": mouvements.tete()}
    registres = {r["registre"]: r for r in _par_id(resultat)["taxes_a_remettre"]["source"]["registres"]}
    assert set(registres) == {"factures", "comptes_a_payer"} and registres["factures"]["taille"] == 12


def test_les_composantes_sont_dans_l_ordre_de_la_definition_produit(taux):
    assert [c["id"] for c in _assembler(taux)["composantes"]] == [
        "taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves"]


def test_l_empreinte_est_deterministe_et_change_avec_le_moindre_chiffre(taux):
    premiere, seconde = _assembler(taux), _assembler(taux)
    autre = _assembler(taux, declarees={**DECLARATIONS, "dettes": {**DECLARATIONS["dettes"], "montant": "800.01"}})

    assert premiere["cash_libre_id"] == seconde["cash_libre_id"] and len(premiere["cash_libre_id"]) == 64
    assert autre["cash_libre_id"] != premiere["cash_libre_id"] and autre["cash_libre"] == D("27861.97")


def test_les_hypotheses_voyagent_avec_la_reponse_et_la_mention_est_portee(taux):
    vue = cash_libre.vue_cash_libre(_assembler(taux))

    assert vue["mention"] == MENTION
    assert len(vue["hypotheses"]) == 6 and vue["hypotheses"] == cash_libre.hypotheses()
    assert any("100 %" in h and "CPA" in h for h in vue["hypotheses"]), "crédits de taxes sur intrants"
    assert any("comptes à recevoir" in h for h in vue["hypotheses"])
    assert any("fournisseur payé" in h for h in vue["hypotheses"])


def _sans_decimal(valeur):
    if isinstance(valeur, dict):
        return all(isinstance(k, str) and _sans_decimal(v) for k, v in valeur.items())
    if isinstance(valeur, list):
        return all(_sans_decimal(v) for v in valeur)
    return valeur is None or isinstance(valeur, (str, bool, int))


def test_la_vue_est_du_json_pur_avec_les_montants_en_texte(taux):
    vue = cash_libre.vue_cash_libre(_assembler(taux))

    assert _sans_decimal(vue), "aucun Decimal, aucun float : les montants sont du texte"
    assert json.loads(json.dumps(vue, ensure_ascii=False)) == vue
    assert vue["cash_libre"] == "27861.98" and vue["calculable"] is True and vue["en_deficit"] is False
    assert vue["solde"]["montant"] == "37654.33"
    assert [c["montant"] for c in vue["composantes"]] == [
        "1981.69", "4200.00", "1350.75", "459.91", "800.00", "1000.00"]
    assert vue["lecture"].startswith("Cash libre : 27861.98 $")
    for composante in [vue["solde"], *vue["composantes"]]:
        for registre_vu in composante["source"].get("registres", []):
            assert len(registre_vu["tete"]) == 16, "la tête est abrégée ; l'empreinte du cash libre porte le reste"


def test_une_reponse_non_calculable_ne_donne_jamais_le_au_plus_pour_un_cash_disponible(taux):
    vue = cash_libre.vue_cash_libre(_assembler(taux, declarees={}))

    assert vue["cash_libre"] is None and vue["calculable"] is False and vue["en_deficit"] is None
    assert vue["au_plus"] is not None
    assert "PAS de l'argent disponible" in vue["lecture"] and "manque" in vue["lecture"]
    assert vue["manque"] == [
        "paies : REJ-CASH-PAIE-A-DECLARER", "das : REJ-CASH-DAS-A-DECLARER", "dettes : REJ-CASH-DETTES-A-DECLARER"]


# ---------------------------------------------------------------------- les déclarations du propriétaire
@pytest.mark.parametrize("declaration", [
    "1250.00",
    {"montant": "1250.00"},
    {"montant": "1250.00", "source": "relevé", "au": "2026-09-01", "surprise": 1},
    {"montant": 1250.0, "source": "relevé", "au": "2026-09-01"},
    {"montant": "-5.00", "source": "relevé", "au": "2026-09-01"},
    {"montant": "1250.005", "source": "relevé", "au": "2026-09-01"},
    {"montant": "1e3", "source": "relevé", "au": "2026-09-01"},
    {"montant": "1 250.00", "source": "relevé", "au": "2026-09-01"},
    {"montant": "", "source": "relevé", "au": "2026-09-01"},
    {"montant": "1250.00", "source": "", "au": "2026-09-01"},
    {"montant": "1250.00", "source": "   ", "au": "2026-09-01"},
    {"montant": "1250.00", "source": "x" * 201, "au": "2026-09-01"},
    {"montant": "1250.00", "source": 5, "au": "2026-09-01"},
    {"montant": "1250.00", "source": "relevé", "au": "2026-13-01"},
    {"montant": "1250.00", "source": "relevé", "au": date(2026, 9, 1)},
    {"montant": "1250.00", "source": "relevé", "au": "septembre"},
    {"montant": "1250.00", "source": "relevé"},
    [],
])
def test_une_declaration_illisible_est_refusee_jamais_corrigee_en_silence(declaration):
    composante = cash_libre.composante_declaree("dettes", declaration)

    assert composante["montant"] is None and composante["statut"] == "NON_CALCULABLE"
    assert composante["manque"][0]["code"] == "REJ-CASH-DECLARATION-INVALIDE"
    assert composante["manque"][0]["code"] in validation.CODES_M5


def test_une_declaration_lisible_donne_un_montant_au_cent_avec_sa_source_et_sa_date():
    composante = cash_libre.composante_declaree(
        "paies", {"montant": "1250", "source": "  relevé de la paie (fictif)  ", "au": "2026-09-01"})

    assert composante["montant"] == D("1250.00") and composante["statut"] == "CALCULE"
    assert composante["source"]["description"].endswith("relevé de la paie (fictif)")
    assert composante["fraicheur"] == {"derniere_piece": "2026-09-01", "pieces": 1}


@pytest.mark.parametrize("cle, code", [
    ("paies", "REJ-CASH-PAIE-A-DECLARER"), ("das", "REJ-CASH-DAS-A-DECLARER"),
    ("dettes", "REJ-CASH-DETTES-A-DECLARER"), ("reserves", "REJ-CASH-RESERVES-A-DECLARER"),
])
def test_une_declaration_absente_dit_quoi_declarer_et_ou(cle, code):
    composante = cash_libre.composante_declaree(cle, None)

    assert composante["montant"] is None and composante["manque"][0]["code"] == code
    assert f"configuration.obligations_declarees.{cle}" in composante["manque"][0]["detail"]
    assert composante["source"]["description"] == "aucune source"


# --------------------------------------------------------------------------------- l'assemblage refuse
def test_l_assemblage_refuse_des_composantes_manquantes_ou_dans_le_desordre(taux):
    resultat = _assembler(taux)
    composantes = resultat["composantes"]

    with pytest.raises(ValueError, match="dans l'ordre"):
        cash_libre.calculer_cash_libre(resultat["solde"], composantes[:-1])
    with pytest.raises(ValueError, match="dans l'ordre"):
        cash_libre.calculer_cash_libre(resultat["solde"], list(reversed(composantes)))


@pytest.mark.parametrize("montant", [D("-0.01"), D("NaN"), D("Infinity"), 5.0, "5.00"])
def test_l_assemblage_refuse_une_obligation_negative_ou_non_finie(taux, montant):
    """Une obligation négative gonflerait le cash libre : c'est un défaut du code, jamais une donnée à accepter."""
    resultat = _assembler(taux)
    composantes = [dict(c) for c in resultat["composantes"]]
    composantes[1]["montant"] = montant

    with pytest.raises(ValueError, match="paies"):
        cash_libre.calculer_cash_libre(resultat["solde"], composantes)


def test_l_assemblage_refuse_un_solde_non_fini(taux):
    resultat = _assembler(taux)

    with pytest.raises(ValueError, match="solde"):
        cash_libre.calculer_cash_libre({**resultat["solde"], "montant": D("NaN")}, resultat["composantes"])


def test_un_code_de_manque_hors_de_la_liste_de_m5_est_refuse_a_la_construction():
    with pytest.raises(validation.CodeVerdictInconnu):
        validation.construire_verdict("REJ-CASH-INVENTE")


def test_tous_les_codes_de_manque_du_cash_libre_sont_des_verdicts_de_m5(taux):
    resultat = _assembler(taux, declarees={}, remises=None,
                          verdict_remise=validation.construire_verdict("REJ-FISCAL-REMISE-A-DECLARER"),
                          mouvements=registre.Registre())

    codes = {m["code"] for c in [resultat["solde"], *resultat["composantes"]] for m in c["manque"]}
    assert codes >= {"REJ-CASH-SOLDE-ABSENT", "REJ-CASH-PAIE-A-DECLARER", "REJ-CASH-DAS-A-DECLARER",
                     "REJ-CASH-DETTES-A-DECLARER", "REJ-CASH-RESERVES-A-DECLARER", "REJ-FISCAL-REMISE-A-DECLARER"}
    assert codes <= validation.CODES_M5


# ------------------------------------------------------------------------------------- cas limites
def _client(facture_id, date_envoi, tps="10.00", tvq="19.95"):
    return {"facture_id": facture_id, "date_envoi": date_envoi, "statut": "ENVOYEE", "taxes": [
        {"id": "tps_federale", "montant": D(tps)}, {"id": "tvq_quebec", "montant": D(tvq)}]}


def test_la_date_d_une_facture_est_celle_de_son_envoi_a_l_heure_locale_du_quebec():
    """Une facture envoyée à 21 h le 30 juin (heure de l'Est) est celle du 30 juin, même si l'heure universelle est
    déjà le 1er juillet : elle est dans la déclaration remise."""
    tard = _client("F-TARD", "2026-06-30T21:00:00-04:00")
    lendemain = _client("F-LENDEMAIN", "2026-07-01T00:30:00-04:00")

    taxes = cash_libre.calculer_taxes_nettes([tard, lendemain], [], apres=REMISES)

    assert taxes["factures_clients"] == 1 and taxes["derniere_piece"] == "2026-07-01"


def test_une_facture_sans_taxe_a_cause_de_l_arrondi_est_lisible_et_comptee():
    """Un montant minuscule donne 0.00 de TPS et de TVQ : c'est une facture valide, pas une facture illisible."""
    minuscule = _client("F-MINUSCULE", "2026-08-01T09:00:00-04:00", tps="0.00", tvq="0.00")

    taxes = cash_libre.calculer_taxes_nettes([minuscule], [], apres=REMISES)

    assert taxes["illisibles"] == [] and taxes["factures_clients"] == 1
    assert taxes["total_a_remettre"] == D("0.00")


def test_un_identifiant_trop_long_est_abrege_dans_les_messages(taux):
    long = "PO-" + "X" * 80
    composante = cash_libre.composante_comptes_a_payer(
        {"nombre_po": 1, "complet": False, "a_payer_apres_taxes": None, "a_payer_connu_apres_taxes": D("0.00"),
         "non_calculables_po": [{"po_id": long, "manque": ["REJ-AP-PRIX-PO-ABSENT"]}], "non_calculables": 1,
         "reserves": [], "pieces": 1, "derniere_piece": "2026-09-15T09:00:00-04:00", "tete": "a" * 64}, None, [])
    facture_cassee = {"facture_id": long, "date_envoi": "hier", "taxes": []}
    illisible = cash_libre.composante_taxes([facture_cassee], [], REMISES, None, [])

    affiche = composante["detail"]["po_non_calculables"][0]["po_id"]
    assert len(affiche) == 40 and affiche.endswith("…") and affiche.startswith("PO-XXX")
    assert long not in illisible["manque"][0]["detail"] and "…" in illisible["manque"][0]["detail"]


def test_a_la_limite_de_120_caracteres_la_source_declaree_est_acceptee_a_121_elle_est_refusee():
    exacte = {"montant": "1.00", "source": "s" * 120, "au": "2026-09-01"}
    trop_longue = {"montant": "1.00", "source": "s" * 121, "au": "2026-09-01"}

    assert cash_libre.composante_declaree("dettes", exacte)["statut"] == "CALCULE"
    assert cash_libre.composante_declaree("dettes", trop_longue)["manque"][0]["code"] == "REJ-CASH-DECLARATION-INVALIDE"


def test_un_montant_declare_est_rendu_au_cent_dans_la_vue(taux):
    declarees = {**DECLARATIONS, "dettes": {"montant": "800", "source": "relevé (fictif)", "au": "2026-09-01"}}

    vue = cash_libre.vue_cash_libre(_assembler(taux, declarees=declarees))

    assert [c["montant"] for c in vue["composantes"]][4] == "800.00"
    assert vue["cash_libre"] == "27861.98"


def test_le_manque_de_l_ensemble_nomme_aussi_le_solde_absent(taux):
    resultat = _assembler(taux, mouvements=registre.Registre())

    assert {"composante": "solde", "code": "REJ-CASH-SOLDE-ABSENT"} in resultat["manque"]
    assert cash_libre.vue_cash_libre(resultat)["manque"][0] == "solde : REJ-CASH-SOLDE-ABSENT"


def test_un_cash_libre_de_zero_n_est_pas_un_deficit(taux):
    mouvements = registre.Registre()
    registre.enregistrer_mouvement({"montant": D("1000.00"), "type_mouvement": "ENCAISSEMENT",
                                    "horodatage": "2026-08-01T12:00:00-04:00", "classe_retention": "STANDARD",
                                    "source": "test"}, mouvements)
    zero = {"montant": "0.00", "source": "aucune (fictif)", "au": "2026-09-01"}
    declarees = {"paies": {**zero, "montant": "1000.00"}, "das": zero, "dettes": zero}

    resultat = _assembler(taux, mouvements=mouvements, factures=registre.Registre(), a_payer=registre.Registre(),
                          declarees=declarees, reserves_declarees=zero)
    vue = cash_libre.vue_cash_libre(resultat)

    assert resultat["cash_libre"] == D("0.00") and resultat["calculable"] is True
    assert vue["cash_libre"] == "0.00" and vue["en_deficit"] is False and "déficit" not in vue["lecture"]


def test_la_fraicheur_des_reserves_est_celle_de_la_plus_recente_meme_ecrite_dans_le_desordre(taux):
    mouvements = registre.Registre()
    for montant, type_mouvement, horodatage in (
        ("5000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00"),
        ("100.00", "PROVISION", "2026-09-20T12:00:00-04:00"),
        ("50.00", "PROVISION", "2026-09-05T12:00:00-04:00"),   # écrite après, mais plus ancienne
    ):
        registre.enregistrer_mouvement({"montant": D(montant), "type_mouvement": type_mouvement,
                                        "horodatage": horodatage, "classe_retention": "STANDARD",
                                        "source": "test"}, mouvements)

    reserves = _par_id(_assembler(taux, mouvements=mouvements))["reserves"]

    assert reserves["montant"] == D("150.00")
    assert reserves["fraicheur"] == {"derniere_piece": "2026-09-20T12:00:00-04:00", "pieces": 2}


@pytest.mark.parametrize("facture", [
    {"facture_fournisseur_id": "apf-a", "date_facture": "hier", "taxes": [
        {"id": "tps_federale", "montant": D("1")}, {"id": "tvq_quebec", "montant": D("1")}]},
    {"facture_fournisseur_id": "apf-b", "taxes": [
        {"id": "tps_federale", "montant": D("1")}, {"id": "tvq_quebec", "montant": D("1")}]},
    {"facture_fournisseur_id": "apf-c", "date_facture": "2026-08-01", "taxes": "illisible"},
    {"facture_fournisseur_id": "apf-d", "date_facture": "2026-08-01", "taxes": [
        {"id": "tps_federale", "montant": D("-1")}, {"id": "tvq_quebec", "montant": D("1")}]},
])
def test_une_facture_fournisseur_illisible_est_listee_et_aucun_credit_n_est_invente(facture):
    taxes = cash_libre.calculer_taxes_nettes([], [facture], apres=REMISES)

    assert taxes["illisibles"] == [facture["facture_fournisseur_id"]]
    assert taxes["factures_fournisseurs"] == 0 and taxes["credits"] == {"tps_federale": D("0"), "tvq_quebec": D("0")}


def test_une_facture_fournisseur_ancienne_dont_la_taxe_est_illisible_n_alerte_pas():
    ancienne = {"facture_fournisseur_id": "apf-vieille", "date_facture": "2026-05-01", "taxes": "illisible"}

    assert cash_libre.calculer_taxes_nettes([], [ancienne], apres=REMISES)["illisibles"] == []


def test_le_credit_d_une_facture_fournisseur_de_la_fenetre_reduit_la_taxe_et_compte_une_piece():
    fournisseur = {"facture_fournisseur_id": "apf-1", "date_facture": "2026-08-15", "taxes": [
        {"id": "tps_federale", "montant": D("15.00")}, {"id": "tvq_quebec", "montant": D("29.93")}]}
    client = _client("F-X", "2026-08-01T09:00:00-04:00", tps="50.00", tvq="99.75")

    taxes = cash_libre.calculer_taxes_nettes([client], [fournisseur], apres=REMISES)

    assert taxes["credits"] == {"tps_federale": D("15.00"), "tvq_quebec": D("29.93")}
    assert taxes["nette"] == {"tps_federale": D("35.00"), "tvq_quebec": D("69.82")}
    assert (taxes["factures_clients"], taxes["factures_fournisseurs"], taxes["total_a_remettre"]) == (1, 1, D("104.82"))
    assert taxes["derniere_piece"] == "2026-08-15"


def test_un_solde_inconnu_rend_tout_non_calculable_meme_quand_toutes_les_obligations_sont_connues(taux):
    """Toutes les composantes retranchées sont calculées (réserves déclarées comprises), mais aucun mouvement n'a jamais
    été enregistré : sans point de départ, ni cash libre ni `au_plus`."""
    reserves = {"montant": "0.00", "source": "décision de Nathan (fictif)", "au": "2026-09-01"}

    resultat = _assembler(taux, mouvements=registre.Registre(), reserves_declarees=reserves)

    assert all(c["statut"] == "CALCULE" for c in resultat["composantes"])
    assert resultat["solde"]["statut"] == "NON_CALCULABLE"
    assert resultat["calculable"] is False and resultat["cash_libre"] is None and resultat["au_plus"] is None
    assert resultat["manque"] == [{"composante": "solde", "code": "REJ-CASH-SOLDE-ABSENT"}]


def test_le_resume_des_comptes_a_payer_ne_donne_un_total_que_s_il_est_complet(taux):
    a_payer = _a_payer(taux)
    complet, verdict = cap.resume_a_payer(a_payer, taux)
    assert verdict is None and complet["complet"] is True
    assert complet["a_payer_apres_taxes"] == complet["a_payer_connu_apres_taxes"] == D("459.91")
    assert (complet["nombre_po"], complet["non_calculables"], complet["pieces"]) == (2, 0, 4)
    assert complet["derniere_piece"] == "2026-09-20T10:00:00-04:00" and complet["reserves"] == [
        "REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert complet["tete"] == a_payer.lire()[-1]["ligne_id"], "la tête de la chaîne : d'où vient le chiffre"
    assert complet["tete"] is not None

    charge = _charge("e-9", "PO-9", "10", "2026-09-18T09:00:00-04:00")
    charge["lignes"][0]["prix_unitaire_prevu"] = None
    cap.enregistrer_reception(cap.construire_reception(charge)[0], a_payer)
    incomplet, verdict = cap.resume_a_payer(a_payer, taux)

    assert verdict is None and incomplet["complet"] is False
    assert incomplet["a_payer_apres_taxes"] is None, "jamais un total quand un PO n'est pas calculable"
    assert incomplet["a_payer_connu_apres_taxes"] == D("459.91") and incomplet["non_calculables"] == 1
    assert incomplet["non_calculables_po"] == [{"po_id": "PO-9", "manque": ["REJ-AP-PRIX-PO-ABSENT"]}]


def test_le_resume_des_comptes_a_payer_sans_aucune_reception_est_un_zero_lu_pas_un_zero_suppose(taux):
    vide, verdict = cap.resume_a_payer(registre.Registre(), taux)

    assert verdict is None and vide["complet"] is True and vide["a_payer_apres_taxes"] == D("0.00")
    assert (vide["nombre_po"], vide["pieces"], vide["derniere_piece"], vide["tete"], vide["reserves"]) == (
        0, 0, None, None, [])


def test_les_factures_saisies_ne_sont_que_les_factures_pas_les_receptions(taux):
    a_payer = _a_payer(taux)

    factures = cap.factures_saisies(a_payer)

    assert [f["numero_facture"] for f in factures] == ["F-1001", "F-2001"]
    assert {f["type_entree"] for f in factures} == {"facture_fournisseur_saisie"}
