"""PLAN T4.15-c : les factures fournisseur SANS PO (carburant, outils), en pur, sur un registre en mémoire.

Une dépense que M6 n'a pas commandée n'a ni PO ni réception : la facture est une dette ferme dès qu'un humain la saisit.
Ce que ces tests fixent, à la cent près :
- la catégorie de dépense est de la liste FERMÉE que le propriétaire déclare ; vide ou absente : « catégories à
  configurer », jamais une catégorie supposée ; hors liste : refus qui donne la liste ;
- taxes et total RECALCULÉS (100.00 $ : TPS 5.00 $, TVQ 9.975 $ qui monte à 9.98 $, 14.98 $ de taxes, 114.98 $),
  total imprimé en contrôle, doublon refusé sur (fournisseur, numéro, montant) parmi toutes les factures vivantes,
  PO ou non ;
- elles entrent EN ENTIER dans les totaux et le résumé des comptes à payer (donc dans le cash libre) et dans les
  crédits de taxes ; corrigées ou annulées, c'est leur état courant qui compte ;
- `lister_sans_po` les rend une par une, avec l'identifiant que la correction demande, par pages sous une borne.

Identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import cash_libre, registre, taux_fiscaux
from m5_financecore import comptes_a_payer as ap

FICTIF = True
_CHEMIN_TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
LIVRAISON = "2026-09-29T09:15:00-04:00"
SAISIE = "2026-10-08T10:00:00-04:00"
CORRECTION = "2026-10-09T10:00:00-04:00"
GRAND = 6000
CATEGORIES = ["carburant", "outils"]
D = Decimal


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX)
    assert erreurs == []
    return dictionnaire


def _sans_po(reg, taux, *, fournisseur="Pétro-Nord (fictif)", categorie="carburant", numero="C-4001", montant="100.00",
             total=None, date_facture="2026-10-01", par="admin.fictif", voie="appareil", horodatage=SAISIE,
             categories=CATEGORIES):
    return ap.saisir_facture_sans_po(
        fournisseur_id=fournisseur, categorie=categorie, numero_facture=numero, date_facture=date_facture,
        montant_avant_taxes=montant, total_facture=total, saisi_par=par, voie=voie, horodatage=horodatage,
        dictionnaire_taux=taux, categories_configurees=categories, registre_cible=reg)


def _sans_po_ok(reg, taux, **kwargs):
    resultat, verdict = _sans_po(reg, taux, **kwargs)
    assert verdict is None, verdict
    return resultat


def _code(resultat_verdict):
    resultat, verdict = resultat_verdict
    assert resultat is None and verdict is not None, resultat
    return verdict["code"]


def _recevoir(reg, evenement_id="evt-1", po_id="PO-1", prix="5.00"):
    ligne = {
        "materiau_id": "gouttiere-5po", "quantite_demandee": "60", "quantite_recue": "60", "prix_unitaire_prevu": prix,
        "devise_prevue": "CAD" if prix is not None else None, "verdict_prix_po": "PRIX_LIVRE",
        "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE", "ecart_prix_critique": None,
    }
    charge = {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": LIVRAISON, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": None, "lignes": [ligne],
    }
    entree, verdict = ap.construire_reception(charge)
    assert verdict is None, verdict
    assert ap.enregistrer_reception(entree, reg)[1] is None


def _facture_de_po(reg, taux, numero="F-1001", montant="300.00", po="PO-1"):
    resultat, verdict = ap.saisir_facture_fournisseur(
        po_id=po, fournisseur_id="gentek", numero_facture=numero, date_facture="2026-10-01",
        montant_avant_taxes=montant, total_facture=None, saisi_par="admin.fictif", voie="appareil",
        horodatage=SAISIE, dictionnaire_taux=taux, registre_cible=reg)
    assert verdict is None, verdict
    return resultat["facture"]["facture_fournisseur_id"]


# ==================================================================== les catégories : une liste fermée, lue
@pytest.mark.parametrize("brut", [None, [], ()], ids=["absente", "liste_vide", "tuple_vide"])
def test_sans_categorie_configuree_la_saisie_dit_categories_a_configurer_et_rien_n_est_suppose(taux, brut):
    reg = registre.Registre()

    categories, verdict = ap.lire_categories_depense(brut)

    assert categories is None and verdict["code"] == "REJ-AP-CATEGORIES-A-CONFIGURER"
    assert "catégories à configurer" in verdict["detail"] and "categories_depense_sans_po" in verdict["detail"]
    refus = _sans_po(reg, taux, categories=brut)
    assert _code(refus) == "REJ-AP-CATEGORIES-A-CONFIGURER"
    assert reg.lire() == [], "rien n'est écrit"


@pytest.mark.parametrize("brut", [
    "carburant", {"carburant": 1}, 5, ["Carburant"], ["carburant", ""], ["c"], ["carburant", "carburant"],
    ["petit outil"], ["outils", 3], ["a" * 33], ["1carburant"], ["carb-urant"], [None],
], ids=["texte", "objet", "nombre", "majuscule", "nom_vide", "un_caractere", "repetee", "espace", "nombre_dans_liste",
        "trop_longue", "chiffre_en_tete", "tiret", "nulle"])
def test_une_liste_de_categories_illisible_est_refusee_jamais_lue_a_moitie(taux, brut):
    categories, verdict = ap.lire_categories_depense(brut)

    assert categories is None and verdict["code"] == "REJ-AP-CATEGORIES-INVALIDES"
    reg = registre.Registre()
    assert _code(_sans_po(reg, taux, categories=brut)) == "REJ-AP-CATEGORIES-INVALIDES"
    assert reg.lire() == []


def test_une_liste_valide_garde_son_ordre_et_accepte_les_accents_et_les_soulignes():
    categories, verdict = ap.lire_categories_depense(["outils", "carburant", "équipement_lourd", "a" * 32, "ab"])

    assert verdict is None
    assert categories == ("outils", "carburant", "équipement_lourd", "a" * 32, "ab")


def test_une_categorie_hors_liste_est_refusee_avec_la_liste(taux):
    reg = registre.Registre()

    refus = _sans_po(reg, taux, categorie="divertissement")

    assert _code(refus) == "REJ-AP-CATEGORIE-INCONNUE"
    assert "carburant, outils" in refus[1]["detail"] and "divertissement" in refus[1]["detail"]
    assert reg.lire() == []
    assert _code(_sans_po(reg, taux, categorie="Carburant")) == "REJ-AP-CATEGORIE-INCONNUE", "la casse compte"
    assert _sans_po_ok(reg, taux, categorie="  outils  ")["facture"]["categorie_depense"] == "outils"


# ============================================================================================ la saisie
def test_une_facture_sans_po_est_recalculee_a_la_cent_pres_et_porte_sa_categorie(taux):
    reg = registre.Registre()

    resultat = _sans_po_ok(reg, taux, total="114.98")

    facture = resultat["facture"]
    assert facture["po_id"] is None and facture["categorie_depense"] == "carburant"
    assert facture["fournisseur_id"] == "Pétro-Nord (fictif)" and facture["numero_facture"] == "C-4001"
    assert (facture["montant_avant_taxes"], facture["total_taxes"], facture["montant_apres_taxes"]) == (
        D("100.00"), D("14.98"), D("114.98"))
    assert [t["montant"] for t in facture["taxes"]] == [D("5.00"), D("9.98")], "9.975 -> 9.98, ROUND_HALF_UP"
    assert (facture["statut"], facture["saisi_par"], facture["voie"]) == ("SAISIE", "admin.fictif", "appareil")
    assert resultat["avertissements"] == []
    (maillon,) = reg.lire()
    assert maillon["type_entree"] == "facture_fournisseur_saisie" and maillon["po_id"] is None
    assert reg.valider_chaine() == (True, "")


def test_la_vue_d_une_facture_sans_po_porte_la_categorie_pas_les_empreintes(taux):
    reg = registre.Registre()
    facture = _sans_po_ok(reg, taux)["facture"]

    vue = ap.vue_facture(facture)

    assert vue["categorie_depense"] == "carburant" and vue["po_id"] is None and "ligne_id" not in vue
    assert "corrections" not in vue and "derniere_modification" not in vue, "jamais touchée"


def test_le_total_imprime_sert_de_controle_et_le_taux_manquant_refuse(taux):
    reg = registre.Registre()

    incoherent = _sans_po(reg, taux, total="114.97")
    assert _code(incoherent) == "REJ-AP-FACTURE-TOTAL-INCOHERENT"
    assert "114.97" in incoherent[1]["detail"] and "114.98" in incoherent[1]["detail"]
    sans_taux = {cle: valeur for cle, valeur in taux.items() if cle != "tvq_quebec"}
    assert _code(_sans_po(reg, sans_taux)) == "REJ-TAUX-INCONNU"
    assert reg.lire() == []


@pytest.mark.parametrize("par, voie", [("nathan", "agent"), ("nathan", None), ("", "approbation"), (None, "appareil")],
                         ids=["voie_agent", "voie_nulle", "personne_vide", "personne_nulle"])
def test_sans_humain_identifie_aucune_facture_sans_po_n_est_saisie(taux, par, voie):
    reg = registre.Registre()

    assert _code(_sans_po(reg, taux, par=par, voie=voie)) == "REJ-AP-HUMAIN-REQUIS"
    assert reg.lire() == []


@pytest.mark.parametrize("surcharge, code", [
    ({"fournisseur": ""}, "REJ-AP-FACTURE-CHAMP-INVALIDE"), ({"fournisseur": "  "}, "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ({"fournisseur": "F" * 65}, "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ({"fournisseur": "a\nb"}, "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ({"fournisseur": None}, "REJ-AP-FACTURE-CHAMP-INVALIDE"), ({"categorie": ""}, "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ({"categorie": None}, "REJ-AP-FACTURE-CHAMP-INVALIDE"), ({"numero": ""}, "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ({"numero": "N" * 65}, "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ({"montant": "0"}, "REJ-AP-FACTURE-MONTANT-INVALIDE"), ({"montant": "-1.00"}, "REJ-AP-FACTURE-MONTANT-INVALIDE"),
    ({"montant": "12.345"}, "REJ-AP-FACTURE-MONTANT-INVALIDE"), ({"montant": 100}, "REJ-AP-FACTURE-MONTANT-INVALIDE"),
    ({"date_facture": "2026-02-30"}, "REJ-AP-FACTURE-DATE-INVALIDE"),
    ({"date_facture": "2026-10-09"}, "REJ-AP-FACTURE-DATE-FUTURE"),
    ({"horodatage": "2026-10-08T10:00:00"}, "REJ-AP-FACTURE-HORODATAGE-INVALIDE"),
])
def test_les_refus_de_format_de_la_saisie_valent_sans_po(taux, surcharge, code):
    reg = registre.Registre()

    assert _code(_sans_po(reg, taux, **surcharge)) == code
    assert reg.lire() == []


def test_le_fournisseur_passe_a_64_caracteres_et_pas_a_65(taux):
    reg = registre.Registre()

    assert _sans_po_ok(reg, taux, fournisseur="F" * 64, numero="C-1")["facture"]["fournisseur_id"] == "F" * 64
    assert _code(_sans_po(reg, taux, fournisseur="F" * 65, numero="C-2")) == "REJ-AP-FACTURE-CHAMP-INVALIDE"


# ======================================================================================== le doublon
def test_le_doublon_est_refuse_meme_si_le_fournisseur_change_de_casse_ou_d_espaces(taux):
    reg = registre.Registre()
    premiere = _sans_po_ok(reg, taux, fournisseur="Pétro-Nord (fictif)", numero="C-4001")["facture"]

    refus = _sans_po(reg, taux, fournisseur="  pétro-nord   (FICTIF) ", numero=" c-4001 ", montant="100.0")

    assert _code(refus) == "REJ-AP-FACTURE-DOUBLON"
    assert premiere["facture_fournisseur_id"] in refus[1]["detail"] and "sans PO" in refus[1]["detail"]
    assert len(reg.lire()) == 1


def test_meme_numero_avec_un_autre_montant_passe_avec_un_avertissement(taux):
    reg = registre.Registre()
    _sans_po_ok(reg, taux, numero="C-4001", montant="100.00")

    resultat = _sans_po_ok(reg, taux, numero="C-4001", montant="80.00")

    assert resultat["avertissements"] == ["REJ-AP-FACTURE-NUMERO-REPETE"]


def test_meme_montant_avec_un_autre_numero_ou_un_autre_fournisseur_n_est_pas_un_doublon(taux):
    reg = registre.Registre()
    _sans_po_ok(reg, taux, numero="C-4001")

    autre_numero = _sans_po_ok(reg, taux, numero="C-4002")
    autre_fournisseur = _sans_po_ok(reg, taux, fournisseur="Quincaillerie (fictive)", numero="C-4001")

    assert autre_numero["avertissements"] == [] and autre_fournisseur["avertissements"] == []


def test_le_doublon_se_compare_a_toutes_les_factures_vivantes_avec_ou_sans_po(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facture_de_po(reg, taux, numero="F-1001", montant="300.00")

    refus = _sans_po(reg, taux, fournisseur="gentek", numero="F-1001", montant="300.00")

    assert _code(refus) == "REJ-AP-FACTURE-DOUBLON" and "PO 'PO-1'" in refus[1]["detail"]
    # et l'inverse : une facture sans PO bloque la même facture saisie contre un PO
    autre = registre.Registre()
    _recevoir(autre)
    _sans_po_ok(autre, taux, fournisseur="gentek", numero="F-1001", montant="300.00")
    _, verdict = ap.saisir_facture_fournisseur(
        po_id="PO-1", fournisseur_id="gentek", numero_facture="F-1001", date_facture="2026-10-01",
        montant_avant_taxes="300.00", total_facture=None, saisi_par="admin.fictif", voie="appareil",
        horodatage=SAISIE, dictionnaire_taux=taux, registre_cible=autre)
    assert verdict["code"] == "REJ-AP-FACTURE-DOUBLON" and "sans PO" in verdict["detail"]


# ============================================================ elles entrent dans les comptes à payer, en entier
def test_une_facture_sans_po_entre_en_entier_dans_les_totaux_avec_le_bloc_sans_po(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _sans_po_ok(reg, taux, categorie="carburant", numero="C-1", montant="100.00")
    _sans_po_ok(reg, taux, categorie="outils", numero="O-1", montant="84.50")
    _sans_po_ok(reg, taux, categorie="carburant", numero="C-2", montant="50.00")

    page, verdict = ap.lister(reg, taux, budget_caracteres=GRAND)

    assert verdict is None
    # PO-1 : 300.00 reçus, rien de facturé : 344.93 attendu. Sans PO : 114.98 + 97.16 + 57.49 = 269.63
    assert page["totaux"]["a_payer_apres_taxes"] == "614.56" and page["totaux"]["complet"] is True
    assert page["totaux"]["sans_po"] == {
        "nombre": 3, "avant_taxes": "234.50", "taxes": "35.13", "apres_taxes": "269.63",
        "par_categorie": {"carburant": {"nombre": 2, "apres_taxes": "172.47"},
                          "outils": {"nombre": 1, "apres_taxes": "97.16"}}}
    assert page["totaux"]["facture_apres_taxes"] == "0.00", "le facturé des PO ne compte que les PO"
    assert page["total"] == 1 and len(page["comptes"]) == 1, "une facture sans PO n'est la ligne d'aucun PO"
    assert any("sans PO" in h for h in page["hypotheses"]) and any("GATE NATHAN" in h for h in page["hypotheses"])


def test_sans_facture_sans_po_le_bloc_et_l_hypothese_ne_paraissent_pas(taux):
    reg = registre.Registre()
    _recevoir(reg)

    page, verdict = ap.lister(reg, taux, budget_caracteres=GRAND)

    assert verdict is None and "sans_po" not in page["totaux"] and len(page["hypotheses"]) == 2


def test_le_detail_d_un_po_ne_compte_aucune_facture_sans_po(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _sans_po_ok(reg, taux)

    page, verdict = ap.lister(reg, taux, budget_caracteres=GRAND, po_id="PO-1")

    assert verdict is None and page["totaux"]["a_payer_apres_taxes"] == "344.93"
    assert "sans_po" not in page["totaux"]


def test_le_resume_a_payer_pour_le_cash_libre_compte_les_factures_sans_po(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _sans_po_ok(reg, taux, montant="100.00")

    resume, verdict = ap.resume_a_payer(reg, taux)

    assert verdict is None and resume["complet"] is True
    assert resume["a_payer_apres_taxes"] == D("459.91"), "344.93 attendu du PO + 114.98 sans PO"
    assert resume["a_payer_connu_apres_taxes"] == D("459.91")
    assert resume["sans_po"]["nombre"] == 1 and resume["sans_po"]["apres_taxes"] == D("114.98")
    assert resume["pieces"] == 2 and resume["tete"] == reg.lire()[-1]["ligne_id"]


def test_seules_des_factures_sans_po_sans_aucune_reception_un_total_lu_pas_suppose(taux):
    reg = registre.Registre()
    _sans_po_ok(reg, taux, montant="100.00")

    resume, verdict = ap.resume_a_payer(reg, taux)
    page, _ = ap.lister(reg, taux, budget_caracteres=GRAND)

    assert verdict is None and resume["nombre_po"] == 0 and resume["complet"] is True
    assert resume["a_payer_apres_taxes"] == D("114.98") and resume["reserves"] == [], "aucune unité de prix en jeu"
    assert page["total"] == 0 and page["comptes"] == [] and page["totaux"]["a_payer_apres_taxes"] == "114.98"


def test_un_po_non_calculable_garde_un_plancher_qui_contient_les_factures_sans_po(taux):
    reg = registre.Registre()
    _recevoir(reg, prix=None)
    _sans_po_ok(reg, taux, montant="100.00")

    resume, verdict = ap.resume_a_payer(reg, taux)

    assert verdict is None and resume["complet"] is False and resume["a_payer_apres_taxes"] is None
    assert resume["a_payer_connu_apres_taxes"] == D("114.98"), "une dette ferme reste un plancher, jamais zéro"


def test_le_cash_libre_le_dit_dans_la_composante_des_comptes_a_payer(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _sans_po_ok(reg, taux, montant="100.00")
    resume, _ = ap.resume_a_payer(reg, taux)

    composante = cash_libre.composante_comptes_a_payer(resume, None, [])

    assert composante["montant"] == D("459.91")
    assert composante["detail"]["factures_sans_po"] == {"nombre": 1, "apres_taxes": "114.98"}
    sans = cash_libre.composante_comptes_a_payer({**resume, "sans_po": None}, None, [])
    assert "factures_sans_po" not in sans["detail"], "sans bloc, rien n'est dit"


def test_les_credits_de_taxes_du_cash_libre_viennent_de_l_etat_courant_des_factures_sans_po(taux):
    reg = registre.Registre()
    ident = _sans_po_ok(reg, taux, montant="100.00")["facture"]["facture_fournisseur_id"]
    depuis = date(2026, 6, 30)

    def credits():
        return cash_libre.calculer_taxes_nettes([], ap.factures_saisies(reg), apres=depuis)

    saisie = credits()
    assert (saisie["credits"]["tps_federale"], saisie["credits"]["tvq_quebec"]) == (D("5.00"), D("9.98"))
    assert saisie["factures_fournisseurs"] == 1

    _, verdict = ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ident, motif="montant tapé de travers (fictif)", numero_facture=None,
        date_facture=None, montant_avant_taxes="200.00", total_facture=None, corrige_par="nathan",
        role="nathan_owner", voie="approbation", horodatage=CORRECTION, dictionnaire_taux=taux, registre_cible=reg)
    assert verdict is None
    corrigee = credits()
    assert (corrigee["credits"]["tps_federale"], corrigee["credits"]["tvq_quebec"]) == (D("10.00"), D("19.95"))

    _, verdict = ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ident, motif="dépense personnelle (fictif)", annule_par="nathan", role="nathan_owner",
        voie="approbation", horodatage=CORRECTION, registre_cible=reg)
    assert verdict is None
    annulee = credits()
    assert (annulee["credits"]["tps_federale"], annulee["credits"]["tvq_quebec"]) == (D("0"), D("0"))
    assert annulee["factures_fournisseurs"] == 0


def test_corrigee_ou_annulee_une_facture_sans_po_suit_les_totaux(taux):
    reg = registre.Registre()
    ident = _sans_po_ok(reg, taux, montant="100.00")["facture"]["facture_fournisseur_id"]
    _sans_po_ok(reg, taux, numero="C-2", montant="50.00", categorie="outils")

    def totaux():
        return ap.lister(reg, taux, budget_caracteres=GRAND)[0]["totaux"]["sans_po"]

    assert totaux()["apres_taxes"] == "172.47"
    resultat, verdict = ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ident, motif="montant tapé de travers (fictif)", numero_facture=None,
        date_facture=None, montant_avant_taxes="200.00", total_facture=None, corrige_par="nathan",
        role="nathan_owner", voie="approbation", horodatage=CORRECTION, dictionnaire_taux=taux, registre_cible=reg)
    assert verdict is None and resultat["facture"]["categorie_depense"] == "carburant", "la catégorie ne bouge pas"
    assert totaux()["apres_taxes"] == "287.44", "229.95 + 57.49"
    assert totaux()["par_categorie"]["carburant"] == {"nombre": 1, "apres_taxes": "229.95"}
    _, verdict = ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ident, motif="dépense personnelle (fictif)", annule_par="nathan", role="nathan_owner",
        voie="approbation", horodatage=CORRECTION, registre_cible=reg)
    assert verdict is None
    assert totaux()["nombre"] == 1 and totaux()["apres_taxes"] == "57.49"
    assert list(totaux()["par_categorie"]) == ["outils"]


def test_annulee_puis_toutes_les_factures_sans_po_le_bloc_disparait_du_total_et_reste_a_zero_dans_le_resume(taux):
    reg = registre.Registre()
    ident = _sans_po_ok(reg, taux, montant="100.00")["facture"]["facture_fournisseur_id"]
    ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ident, motif="erreur (fictif)", annule_par="nathan", role="nathan_owner",
        voie="approbation", horodatage=CORRECTION, registre_cible=reg)

    page, _ = ap.lister(reg, taux, budget_caracteres=GRAND)
    resume, _ = ap.resume_a_payer(reg, taux)

    assert "sans_po" not in page["totaux"] and page["totaux"]["a_payer_apres_taxes"] == "0.00"
    assert resume["sans_po"]["nombre"] == 0 and resume["a_payer_apres_taxes"] == D("0.00")


# ========================================================================== la liste des factures sans PO
def test_lister_sans_po_rend_une_ligne_par_facture_avec_l_identifiant_et_l_etat(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facture_de_po(reg, taux)
    a = _sans_po_ok(reg, taux, numero="C-1", montant="100.00")["facture"]["facture_fournisseur_id"]
    b = _sans_po_ok(reg, taux, numero="O-1", montant="84.50", categorie="outils")["facture"]["facture_fournisseur_id"]
    ap.annuler_facture_fournisseur(
        facture_fournisseur_id=b, motif="mauvais fournisseur (fictif)", annule_par="nathan", role="nathan_owner",
        voie="approbation", horodatage=CORRECTION, registre_cible=reg)

    page, verdict = ap.lister_sans_po(reg, budget_caracteres=GRAND)

    assert verdict is None and page["type"] == "COMPTES_A_PAYER_SANS_PO" and page["total"] == 2
    assert page["mention"] == ap.analyse.MENTION_ANALYSE_PREPARATOIRE and page["prochain_depart"] is None
    lignes = page["factures"]
    assert [ligne["facture_fournisseur_id"] for ligne in lignes] == [a, b], "l'ordre de saisie, annulée comprise"
    assert [ligne["statut"] for ligne in lignes] == ["SAISIE", "ANNULEE"]
    assert lignes[0]["categorie_depense"] == "carburant" and lignes[0]["fournisseur_id"] == "Pétro-Nord (fictif)"
    assert (lignes[0]["avant_taxes"], lignes[0]["taxes"], lignes[0]["apres_taxes"]) == ("100.00", "14.98", "114.98")
    assert lignes[1]["derniere_modification"]["motif"] == "mauvais fournisseur (fictif)"
    assert page["totaux"]["nombre"] == 1 and page["totaux"]["apres_taxes"] == "114.98", "l'annulée ne compte pas"


def test_lister_sans_po_pagine_sous_la_borne_sans_perdre_ni_repeter_une_facture(taux):
    reg = registre.Registre()
    for numero in range(1, 13):
        _sans_po_ok(reg, taux, numero=f"C-{numero:02d}", montant=f"{numero}0.00")
    identifiants, depart, pages = [], 0, 0

    while depart is not None:
        page, verdict = ap.lister_sans_po(reg, depart=depart, budget_caracteres=2600)
        assert verdict is None
        assert page["total"] == 12 and page["totaux"]["nombre"] == 12
        assert page["affichees"] == len(page["factures"]) >= 1
        assert len(json.dumps(page, ensure_ascii=False)) <= 2600, "mesuré, jamais estimé"
        identifiants.extend(f["facture_fournisseur_id"] for f in page["factures"])
        depart, pages = page["prochain_depart"], pages + 1
        assert pages <= 12

    assert pages > 1 and len(identifiants) == 12 and len(set(identifiants)) == 12


def test_lister_sans_po_refuse_un_depart_invalide_ou_au_dela_de_la_fin_et_une_ligne_trop_grosse(taux):
    reg = registre.Registre()
    _sans_po_ok(reg, taux)

    for depart in (-1, "0", 1.5, True, None):
        assert _code(ap.lister_sans_po(reg, depart=depart, budget_caracteres=GRAND)) == "REJ-AP-LISTE-DEPART-INVALIDE"
    assert _code(ap.lister_sans_po(reg, depart=2, budget_caracteres=GRAND)) == "REJ-AP-LISTE-DEPART-INVALIDE"
    fin, verdict = ap.lister_sans_po(reg, depart=1, budget_caracteres=GRAND)
    assert verdict is None and fin["factures"] == [] and fin["prochain_depart"] is None, "à la fin : une page vide"
    assert _code(ap.lister_sans_po(reg, budget_caracteres=10)) == "REJ-AP-LISTE-LIGNE-TROP-GROSSE"


def test_lister_sans_po_sans_aucune_facture_est_une_page_vide_avec_des_zeros_lus(taux):
    page, verdict = ap.lister_sans_po(registre.Registre(), budget_caracteres=GRAND)

    assert verdict is None and page["total"] == 0 and page["factures"] == []
    assert page["totaux"] == {"nombre": 0, "avant_taxes": "0.00", "taxes": "0.00", "apres_taxes": "0.00",
                              "par_categorie": {}}
