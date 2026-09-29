"""PLAN T4.15-c : corriger ou annuler une facture fournisseur saisie, en pur, sur un registre en mémoire.

Ce que ces tests fixent, à la cent près :
- la facture d'origine n'est JAMAIS modifiée : une correction et une annulation sont des pièces de plus, chaînées au
  registre (la chaîne reste valide), avec le motif, la personne, son rôle, la voie, l'avant et l'après ;
- l'état courant d'une facture (`SAISIE`, `CORRIGEE`, `ANNULEE`) est celui que ses pièces disent, et c'est de cet
  état que partent le facturé, l'« à payer », le rapprochement, le doublon et les crédits de taxes du cash libre ;
- un REJEU n'a aucun effet : une correction déjà appliquée (rien ne change) et une annulation déjà faite sont refusées,
  sans écrire une pièce de plus ;
- un registre incohérent (une pièce qui vise une facture absente ou annulée) LÈVE : jamais un chiffre à demi lu.

Le cas fictif de référence est celui de `test_comptes_a_payer.py` : PO-1 chez Gentek, 300.00 $ reçus (60 gouttières à
5.00 $), facture F-1001 de 300.00 $ avant taxes (TPS 15.00 $, TVQ 29.925 $ qui monte à 29.93 $ : 44.93 $ de taxes,
344.93 $ au total). Corrigée à 310.00 $ : TPS 15.50 $, TVQ 30.9225 $ qui descend à 30.92 $, 46.42 $ de taxes, 356.42 $.
Identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import cash_libre, encodage, registre, taux_fiscaux
from m5_financecore import comptes_a_payer as ap

FICTIF = True
_CHEMIN_TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
LIVRAISON = "2026-09-29T09:15:00-04:00"
SAISIE = "2026-10-08T10:00:00-04:00"
CORRECTION = "2026-10-09T10:00:00-04:00"
ANNULATION = "2026-10-10T10:00:00-04:00"
GRAND = 6000
D = Decimal


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX)
    assert erreurs == []
    return dictionnaire


def _ligne(materiau, demandee, recue, prix):
    return {
        "materiau_id": materiau, "quantite_demandee": demandee, "quantite_recue": recue, "prix_unitaire_prevu": prix,
        "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE", "prix_unitaire_reception": None,
        "verdict_prix_reception": "INDETERMINE", "ecart_prix_critique": None,
    }


def _recevoir(reg, evenement_id="evt-1", po_id="PO-1", gouttiere="60", vis="0", fournisseur="gentek"):
    charge = {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": fournisseur, "chantier_id": "CH-1",
        "horodatage_reception": LIVRAISON, "verdict_reception": "RECEPTION_INFERIEURE",
        "statut_po": "partially_received", "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [_ligne("gouttiere-5po", "60", gouttiere, "5.00"), _ligne("vis-inox", "40", vis, "0.50")],
    }
    entree, verdict = ap.construire_reception(charge)
    assert verdict is None, verdict
    resultat, verdict = ap.enregistrer_reception(entree, reg)
    assert verdict is None, verdict


def _facturer(reg, taux, numero="F-1001", montant="300.00", po="PO-1", fournisseur="gentek"):
    resultat, verdict = ap.saisir_facture_fournisseur(
        po_id=po, fournisseur_id=fournisseur, numero_facture=numero, date_facture="2026-10-01",
        montant_avant_taxes=montant, total_facture=None, saisi_par="admin.fictif", voie="appareil",
        horodatage=SAISIE, dictionnaire_taux=taux, registre_cible=reg)
    assert verdict is None, verdict
    return resultat["facture"]["facture_fournisseur_id"]


def _corriger(reg, taux, ident, *, motif="Faute de frappe sur le montant (fictif)", numero=None, date_facture=None,
              montant=None, total=None, par="nathan", role="nathan_owner", voie="approbation", horodatage=CORRECTION):
    return ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ident, motif=motif, numero_facture=numero, date_facture=date_facture,
        montant_avant_taxes=montant, total_facture=total, corrige_par=par, role=role, voie=voie,
        horodatage=horodatage, dictionnaire_taux=taux, registre_cible=reg)


def _corriger_ok(reg, taux, ident, **kwargs):
    resultat, verdict = _corriger(reg, taux, ident, **kwargs)
    assert verdict is None, verdict
    return resultat


def _annuler(reg, ident, *, motif="Facture saisie sous le mauvais PO (fictif)", par="nathan", role="nathan_owner",
             voie="approbation", horodatage=ANNULATION):
    return ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ident, motif=motif, annule_par=par, role=role, voie=voie, horodatage=horodatage,
        registre_cible=reg)


def _annuler_ok(reg, ident, **kwargs):
    resultat, verdict = _annuler(reg, ident, **kwargs)
    assert verdict is None, verdict
    return resultat


def _po(reg, taux, po_id="PO-1"):
    page, verdict = ap.lister(reg, taux, budget_caracteres=GRAND, po_id=po_id)
    assert verdict is None, verdict
    (ligne,) = page["comptes"]
    return ligne


def _code(resultat_verdict):
    resultat, verdict = resultat_verdict
    assert resultat is None and verdict is not None, resultat
    return verdict["code"]


@pytest.fixture
def reg(taux):
    registre_ap = registre.Registre()
    _recevoir(registre_ap)
    return registre_ap


# ====================================================================================== la correction
def test_une_correction_recalcule_les_taxes_et_le_rapprochement_lit_le_nouvel_etat(reg, taux):
    ident = _facturer(reg, taux)

    resultat = _corriger_ok(reg, taux, ident, montant="310.00")

    facture = resultat["facture"]
    assert facture["statut"] == "CORRIGEE" and facture["corrections"] == 1
    assert (facture["montant_avant_taxes"], facture["total_taxes"], facture["montant_apres_taxes"]) == (
        D("310.00"), D("46.42"), D("356.42"))
    assert [t["montant"] for t in facture["taxes"]] == [D("15.50"), D("30.92")], "30.9225 -> 30.92, ROUND_HALF_UP"
    ligne = _po(reg, taux)
    assert ligne["factures"] == {"nombre": 1, "avant_taxes": "310.00", "taxes": "46.42", "apres_taxes": "356.42"}
    rapprochement = ligne["rapprochement"]
    assert rapprochement["verdict"] == "ECART" and rapprochement["sens"] == "FACTURE_SUPERIEURE_AU_RECU"
    assert rapprochement["facture_moins_recu"] == "10.00"
    assert ligne["a_payer_apres_taxes"] == "356.42", "facturé 356.42, rien de reçu non facturé"


def test_la_facture_d_origine_n_est_jamais_modifiee_la_chaine_reste_valide(reg, taux):
    ident = _facturer(reg, taux)
    avant = copy.deepcopy(reg.lire())
    origine = avant[-1]

    _corriger_ok(reg, taux, ident, montant="310.00")
    _annuler_ok(reg, ident)

    apres = reg.lire()
    assert apres[: len(avant)] == avant, "aucun maillon d'avant n'a bougé"
    assert apres[-3] == origine and origine["statut"] == "SAISIE" and origine["montant_avant_taxes"] == D("300.00")
    assert reg.valider_chaine() == (True, "")
    correction, annulation = apres[-2], apres[-1]
    assert correction["precedent_ligne_id"] == origine["ligne_id"], "la correction est chaînée à la facture"
    assert annulation["precedent_ligne_id"] == correction["ligne_id"]
    assert (correction["type_entree"], annulation["type_entree"]) == (
        "correction_facture_fournisseur", "annulation_facture_fournisseur")


def test_la_piece_de_correction_porte_le_motif_la_personne_l_avant_et_l_apres(reg, taux):
    ident = _facturer(reg, taux)

    _corriger_ok(reg, taux, ident, montant="310.00", numero="F-1001-A", date_facture="2026-10-02")

    piece = reg.lire()[-1]
    assert piece["motif"] == "Faute de frappe sur le montant (fictif)"
    assert (piece["corrige_par"], piece["role"], piece["voie"]) == ("nathan", "nathan_owner", "approbation")
    assert piece["horodatage"] == CORRECTION and piece["facture_fournisseur_id"] == ident
    assert piece["avant"] == {
        "numero_facture": "F-1001", "date_facture": "2026-10-01", "montant_avant_taxes": D("300.00"),
        "total_taxes": D("44.93"), "montant_apres_taxes": D("344.93")}
    assert (piece["apres"]["numero_facture"], piece["apres"]["date_facture"]) == ("F-1001-A", "2026-10-02")
    assert (piece["apres"]["montant_avant_taxes"], piece["apres"]["montant_apres_taxes"]) == (D("310.00"), D("356.42"))
    assert piece["modification_id"] == "apm-" + encodage.empreinte(ident, 1)[:20], "déterministe : facture, rang"


def test_corriger_le_numero_et_la_date_ne_change_pas_le_montant_ni_les_taxes(reg, taux):
    ident = _facturer(reg, taux)

    facture = _corriger_ok(reg, taux, ident, numero="F-1001-A", date_facture="2026-10-02")["facture"]

    assert (facture["numero_facture"], facture["date_facture"]) == ("F-1001-A", "2026-10-02")
    assert (facture["montant_avant_taxes"], facture["montant_apres_taxes"]) == (D("300.00"), D("344.93"))
    assert facture["po_id"] == "PO-1" and facture["fournisseur_id"] == "gentek", "ni le PO ni le fournisseur ne bougent"
    vue = ap.vue_facture(facture)
    assert vue["statut"] == "CORRIGEE" and vue["corrections"] == 1
    assert vue["derniere_modification"]["type"] == "CORRECTION" and vue["derniere_modification"]["par"] == "nathan"
    assert "modifications" not in vue and "ligne_id" not in vue, "la vue ne montre pas les empreintes du registre"


def test_des_corrections_en_chaine_l_etat_est_la_derniere_et_l_historique_reste(reg, taux):
    ident = _facturer(reg, taux)

    _corriger_ok(reg, taux, ident, montant="310.00", motif="premier motif")
    facture = _corriger_ok(reg, taux, ident, montant="320.00", motif="second motif")["facture"]

    assert facture["corrections"] == 2 and facture["montant_apres_taxes"] == D("367.92"), "320 + 16.00 + 31.92 taxes"
    assert reg.lire()[-1]["avant"]["montant_avant_taxes"] == D("310.00"), "l'avant d'une correction est l'état courant"
    assert [m["motif"] for m in facture["modifications"]] == ["premier motif", "second motif"]
    ligne = _po(reg, taux)
    assert ligne["factures_saisies"][0]["derniere_modification"]["motif"] == "second motif"
    assert ligne["factures_saisies"][0]["corrections"] == 2


def test_le_total_imprime_sert_de_controle_a_la_correction_comme_a_la_saisie(reg, taux):
    ident = _facturer(reg, taux)
    avant = len(reg.lire())

    faux = _corriger(reg, taux, ident, montant="310.00", total="356.41")
    assert _code(faux) == "REJ-AP-FACTURE-TOTAL-INCOHERENT"
    assert "356.41" in faux[1]["detail"] and "356.42" in faux[1]["detail"]
    assert len(reg.lire()) == avant

    juste = _corriger_ok(reg, taux, ident, montant="310.00", total="356.42")
    assert juste["facture"]["montant_apres_taxes"] == D("356.42")


@pytest.mark.parametrize("motif", [None, "", "   ", "\t", "a\nb", "x" * 301, 12, ["motif"]],
                         ids=["nul", "vide", "espaces", "tabulation", "deux_lignes", "trop_long", "nombre", "liste"])
def test_le_motif_est_obligatoire_une_ligne_de_300_caracteres_au_plus(reg, taux, motif):
    ident = _facturer(reg, taux)
    avant = reg.lire()

    assert _code(_corriger(reg, taux, ident, montant="310.00", motif=motif)) == "REJ-AP-MOTIF-REQUIS"
    assert _code(_annuler(reg, ident, motif=motif)) == "REJ-AP-MOTIF-REQUIS"
    assert reg.lire() == avant, "rien n'est écrit sans motif"


def test_un_motif_de_300_caracteres_passe_avec_ses_espaces_de_bout_retires(reg, taux):
    ident = _facturer(reg, taux)

    _corriger_ok(reg, taux, ident, montant="310.00", motif="  " + "m" * 300 + "  ")

    assert reg.lire()[-1]["motif"] == "m" * 300


@pytest.mark.parametrize("par, voie, role", [
    ("nathan", "agent", "nathan_owner"), ("nathan", None, "nathan_owner"), ("nathan", "appareil ", "nathan_owner"),
    ("", "approbation", "nathan_owner"), (None, "approbation", "nathan_owner"), ("  ", "approbation", "nathan_owner"),
    ("nathan", "approbation", ""), ("nathan", "approbation", None), (7, "approbation", "nathan_owner"),
], ids=["voie_agent", "voie_nulle", "voie_espace", "personne_vide", "personne_nulle", "personne_espaces", "role_vide",
        "role_nul", "personne_nombre"])
def test_sans_humain_identifie_la_correction_et_l_annulation_sont_refusees(reg, taux, par, voie, role):
    ident = _facturer(reg, taux)
    avant = reg.lire()

    assert _code(_corriger(reg, taux, ident, montant="310.00", par=par, voie=voie, role=role)) == (
        "REJ-AP-HUMAIN-REQUIS")
    assert _code(_annuler(reg, ident, par=par, voie=voie, role=role)) == "REJ-AP-HUMAIN-REQUIS"
    assert reg.lire() == avant


def test_une_facture_inconnue_ou_un_identifiant_vide_est_refuse(reg, taux):
    avant = reg.lire()

    assert _code(_corriger(reg, taux, "apf-inconnue", montant="310.00")) == "REJ-AP-FACTURE-INCONNUE"
    assert _code(_annuler(reg, "apf-inconnue")) == "REJ-AP-FACTURE-INCONNUE"
    for vide in (None, "", "  ", 5):
        assert _code(_corriger(reg, taux, vide, montant="310.00")) == "REJ-AP-FACTURE-CHAMP-INVALIDE"
        assert _code(_annuler(reg, vide)) == "REJ-AP-FACTURE-CHAMP-INVALIDE"
    assert reg.lire() == avant


def test_l_identifiant_se_lit_sans_ses_espaces_de_bout(reg, taux):
    ident = _facturer(reg, taux)

    assert _corriger_ok(reg, taux, f"  {ident} ", montant="310.00")["facture"]["facture_fournisseur_id"] == ident


def test_un_rejeu_d_une_correction_deja_appliquee_ne_change_rien_et_n_ecrit_rien(reg, taux):
    ident = _facturer(reg, taux)
    _corriger_ok(reg, taux, ident, montant="310.00")
    apres_une_fois = reg.lire()

    rejeu = _corriger(reg, taux, ident, montant="310.00")

    assert _code(rejeu) == "REJ-AP-CORRECTION-SANS-CHANGEMENT"
    assert reg.lire() == apres_une_fois, "aucune pièce de plus"
    assert _code(_corriger(reg, taux, ident, montant="310.0")) == "REJ-AP-CORRECTION-SANS-CHANGEMENT", (
        "310.0 et 310.00 sont le même montant")


def test_une_correction_qui_ne_dit_rien_ou_qui_redit_l_etat_est_refusee(reg, taux):
    ident = _facturer(reg, taux)
    avant = reg.lire()

    assert _code(_corriger(reg, taux, ident)) == "REJ-AP-CORRECTION-SANS-CHANGEMENT", "rien à corriger"
    assert _code(_corriger(reg, taux, ident, numero="F-1001", date_facture="2026-10-01", montant="300")) == (
        "REJ-AP-CORRECTION-SANS-CHANGEMENT")
    assert reg.lire() == avant


def test_une_correction_qui_ne_fournit_aucun_champ_dit_quoi_fournir_avant_meme_de_chercher_la_facture(reg, taux):
    ident = _facturer(reg, taux)

    refus = _corriger(reg, taux, ident, total="344.93")
    inconnue = _corriger(reg, taux, "apf-inconnue")

    for verdict in (refus[1], inconnue[1]):
        assert verdict["code"] == "REJ-AP-CORRECTION-SANS-CHANGEMENT", "même inconnue : rien à corriger"
        assert "au moins un de numero_facture, date_facture, montant_avant_taxes" in verdict["detail"]


def test_seule_la_casse_du_numero_suffit_a_corriger(reg, taux):
    """`f-1001` et `F-1001` sont le même numéro pour le doublon, mais pas pour ce qui est imprimé : corriger la casse
    est un changement."""
    ident = _facturer(reg, taux, numero="f-1001")

    facture = _corriger_ok(reg, taux, ident, numero="F-1001")["facture"]

    assert facture["numero_facture"] == "F-1001" and facture["statut"] == "CORRIGEE"


@pytest.mark.parametrize("champ, valeur, code", [
    ("numero", "", "REJ-AP-FACTURE-CHAMP-INVALIDE"), ("numero", "   ", "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ("numero", "N" * 65, "REJ-AP-FACTURE-CHAMP-INVALIDE"), ("numero", "a\tb", "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ("numero", 12, "REJ-AP-FACTURE-CHAMP-INVALIDE"),
    ("date_facture", "2026-13-01", "REJ-AP-FACTURE-DATE-INVALIDE"),
    ("date_facture", "1er octobre", "REJ-AP-FACTURE-DATE-INVALIDE"),
    ("date_facture", "2026-10-10", "REJ-AP-FACTURE-DATE-FUTURE"),
    ("montant", "0", "REJ-AP-FACTURE-MONTANT-INVALIDE"), ("montant", "-5.00", "REJ-AP-FACTURE-MONTANT-INVALIDE"),
    ("montant", "310.005", "REJ-AP-FACTURE-MONTANT-INVALIDE"), ("montant", "1e3", "REJ-AP-FACTURE-MONTANT-INVALIDE"),
    ("montant", 310, "REJ-AP-FACTURE-MONTANT-INVALIDE"), ("total", "abc", "REJ-AP-FACTURE-MONTANT-INVALIDE"),
    ("horodatage", "2026-10-09T10:00:00", "REJ-AP-FACTURE-HORODATAGE-INVALIDE"),
    ("horodatage", "hier", "REJ-AP-FACTURE-HORODATAGE-INVALIDE"),
    ("horodatage", None, "REJ-AP-FACTURE-HORODATAGE-INVALIDE"),
])
def test_les_refus_de_format_de_la_saisie_valent_pour_la_correction(reg, taux, champ, valeur, code):
    ident = _facturer(reg, taux)
    avant = reg.lire()
    kwargs = {"montant": "310.00"}
    kwargs["horodatage" if champ == "horodatage" else champ] = valeur

    assert _code(_corriger(reg, taux, ident, **kwargs)) == code
    assert reg.lire() == avant


def test_la_date_du_jour_de_la_correction_passe_le_lendemain_est_future(reg, taux):
    ident = _facturer(reg, taux)

    assert _code(_corriger(reg, taux, ident, date_facture="2026-10-10")) == "REJ-AP-FACTURE-DATE-FUTURE"
    assert _corriger_ok(reg, taux, ident, date_facture="2026-10-09")["facture"]["date_facture"] == "2026-10-09"


def test_une_correction_qui_ferait_un_doublon_est_refusee_sans_rien_ecrire(reg, taux):
    _facturer(reg, taux, numero="F-1001", montant="300.00")
    seconde = _facturer(reg, taux, numero="F-1002", montant="300.00")
    avant = reg.lire()

    refus = _corriger(reg, taux, seconde, numero="F-1001")

    assert _code(refus) == "REJ-AP-FACTURE-DOUBLON" and "F-1001" in refus[1]["detail"]
    assert reg.lire() == avant
    assert _code(_corriger(reg, taux, seconde, numero=" f-1001 ")) == "REJ-AP-FACTURE-DOUBLON", "casse et espaces"


def test_le_numero_repete_avec_un_autre_montant_passe_avec_un_avertissement_sur_les_deux(reg, taux):
    premiere = _facturer(reg, taux, numero="F-1001", montant="300.00")
    seconde = _facturer(reg, taux, numero="F-1002", montant="20.00")

    resultat = _corriger_ok(reg, taux, seconde, numero="F-1001")

    assert resultat["avertissements"] == ["REJ-AP-FACTURE-NUMERO-REPETE"]
    factures = {f["facture_fournisseur_id"]: f for f in _po(reg, taux)["factures_saisies"]}
    assert factures[premiere]["avertissements"] == ["REJ-AP-FACTURE-NUMERO-REPETE"], "la première le voit aussi"
    assert factures[seconde]["avertissements"] == ["REJ-AP-FACTURE-NUMERO-REPETE"]
    assert "REJ-AP-FACTURE-NUMERO-REPETE" in _po(reg, taux)["rapprochement"]["reserves"]


def test_corriger_ou_annuler_l_une_des_deux_leve_l_avertissement_de_l_autre(reg, taux):
    premiere = _facturer(reg, taux, numero="F-1001", montant="300.00")
    seconde = _facturer(reg, taux, numero="F-1001", montant="20.00")
    assert _po(reg, taux)["rapprochement"]["reserves"][-1] == "REJ-AP-FACTURE-NUMERO-REPETE"

    _corriger_ok(reg, taux, seconde, numero="F-1002")
    assert _po(reg, taux)["rapprochement"]["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    _corriger_ok(reg, taux, seconde, numero="F-1001", motif="retour au numéro imprimé")
    assert _po(reg, taux)["rapprochement"]["reserves"][-1] == "REJ-AP-FACTURE-NUMERO-REPETE"

    _annuler_ok(reg, premiere)
    ligne = _po(reg, taux)
    assert ligne["rapprochement"]["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert [f["avertissements"] for f in ligne["factures_saisies"] if f["statut"] != "ANNULEE"] == [[]]


def test_corriger_un_montant_pour_retrouver_un_ancien_ne_fait_pas_un_doublon_de_l_ancien_etat(reg, taux):
    """F-1001 passe de 300.00 à 310.00 : ressaisir F-1001 à 300.00 n'est plus un doublon (la première ne vaut plus
    300.00), et son identifiant ne heurte pas celui de la première (déterministe de l'ORIGINE)."""
    premiere = _facturer(reg, taux, numero="F-1001", montant="300.00")
    _corriger_ok(reg, taux, premiere, montant="310.00")

    autre = _facturer(reg, taux, numero="F-1001", montant="300.00")

    assert autre != premiere
    factures = [m for m in reg.lire() if m.get("type_entree") == "facture_fournisseur_saisie"]
    assert len({m["facture_fournisseur_id"] for m in factures}) == 2
    assert _po(reg, taux)["factures"]["nombre"] == 2


# ====================================================================================== l'annulation
def test_une_annulation_retire_la_facture_du_facture_de_l_a_payer_et_du_rapprochement(reg, taux):
    ident = _facturer(reg, taux)
    assert _po(reg, taux)["rapprochement"]["verdict"] == "CONCORDANT"

    facture = _annuler_ok(reg, ident)["facture"]

    assert facture["statut"] == "ANNULEE" and facture["modifications"][-1]["type"] == "ANNULATION"
    ligne = _po(reg, taux)
    assert ligne["factures"] == {"nombre": 0, "avant_taxes": "0.00", "taxes": "0.00", "apres_taxes": "0.00"}
    assert ligne["rapprochement"]["verdict"] == "SANS_FACTURE" and ligne["rapprochement"]["facture_avant_taxes"] is None
    assert ligne["a_payer_apres_taxes"] == "344.93", "la dette n'a pas disparu : le reçu redevient un attendu à payer"
    assert ligne["attendu_non_facture_apres_taxes"] is not None
    assert ligne["factures_annulees"] == 1


def test_la_piece_d_annulation_porte_le_motif_la_personne_et_l_etat_annule(reg, taux):
    ident = _facturer(reg, taux)

    _annuler_ok(reg, ident, motif="Doublon d'une facture déjà payée (fictif)", par="compta", role="finance")

    piece = reg.lire()[-1]
    assert piece["type_entree"] == "annulation_facture_fournisseur" and piece["facture_fournisseur_id"] == ident
    assert (piece["motif"], piece["annule_par"], piece["role"], piece["voie"]) == (
        "Doublon d'une facture déjà payée (fictif)", "compta", "finance", "approbation")
    assert piece["avant"]["montant_apres_taxes"] == D("344.93")
    assert piece["modification_id"] == "apm-" + encodage.empreinte(ident, 1)[:20]


def test_le_detail_du_po_montre_la_facture_annulee_avec_son_motif_sans_la_compter(reg, taux):
    annulee = _facturer(reg, taux, numero="F-1001", montant="300.00")
    bonne = _facturer(reg, taux, numero="F-1002", montant="20.00")
    _annuler_ok(reg, annulee, motif="mauvais PO")

    ligne = _po(reg, taux)

    assert ligne["factures"]["nombre"] == 1 and ligne["factures"]["avant_taxes"] == "20.00"
    par_id = {f["facture_fournisseur_id"]: f for f in ligne["factures_saisies"]}
    assert set(par_id) == {annulee, bonne}
    assert par_id[annulee]["statut"] == "ANNULEE" and par_id[annulee]["derniere_modification"]["motif"] == "mauvais PO"
    assert par_id[bonne]["statut"] == "SAISIE" and "derniere_modification" not in par_id[bonne]


def test_un_rejeu_de_l_annulation_ne_change_rien_et_n_ecrit_rien(reg, taux):
    ident = _facturer(reg, taux)
    _annuler_ok(reg, ident)
    apres_une_fois = reg.lire()

    assert _code(_annuler(reg, ident)) == "REJ-AP-FACTURE-DEJA-ANNULEE"
    assert reg.lire() == apres_une_fois


def test_une_annulee_ne_se_corrige_plus(reg, taux):
    ident = _facturer(reg, taux)
    _annuler_ok(reg, ident)
    apres = reg.lire()

    assert _code(_corriger(reg, taux, ident, montant="310.00")) == "REJ-AP-FACTURE-ANNULEE"
    assert reg.lire() == apres


def test_une_annulee_ne_bloque_pas_la_ressaisie_de_la_meme_facture_et_l_identifiant_est_distinct(reg, taux):
    """Le geste juste après une erreur d'annulation : ressaisir. Le doublon ne compte que les factures vivantes ; un
    identifiant est unique au registre (le rang suivant, toujours le même pour le même état)."""
    premiere = _facturer(reg, taux)
    _annuler_ok(reg, premiere)

    deuxieme = _facturer(reg, taux)
    _annuler_ok(reg, deuxieme)
    troisieme = _facturer(reg, taux)

    assert len({premiere, deuxieme, troisieme}) == 3
    assert premiere == "apf-" + encodage.empreinte("gentek", "f-1001", "300.00")[:20], "le premier : la forme d'avant"
    ligne = _po(reg, taux)
    assert ligne["factures"]["nombre"] == 1 and ligne["factures_annulees"] == 2
    assert ligne["factures"]["apres_taxes"] == "344.93"


def test_les_factures_saisies_pour_le_cash_libre_sont_l_etat_courant_sans_les_annulees(reg, taux):
    _recevoir(reg, evenement_id="evt-2", po_id="PO-2", gouttiere="60", vis="0", fournisseur="gentek")
    corrigee = _facturer(reg, taux, numero="F-1001", montant="300.00")
    annulee = _facturer(reg, taux, numero="F-1002", montant="100.00", po="PO-2")
    _facturer(reg, taux, numero="F-1003", montant="50.00", po="PO-2")
    _corriger_ok(reg, taux, corrigee, montant="310.00")
    _annuler_ok(reg, annulee)

    factures = ap.factures_saisies(reg)

    assert [f["numero_facture"] for f in factures] == ["F-1001", "F-1003"]
    assert [f["montant_avant_taxes"] for f in factures] == [D("310.00"), D("50.00")]
    assert {f["type_entree"] for f in factures} == {"facture_fournisseur_saisie"}
    credits = cash_libre.calculer_taxes_nettes([], factures, apres=date(2026, 6, 30))
    assert credits["credits"]["tps_federale"] == D("15.50") + D("2.50")
    assert credits["credits"]["tvq_quebec"] == D("30.92") + D("4.99"), "50.00 x 9.975 % = 4.9875 -> 4.99"
    assert credits["factures_fournisseurs"] == 2


def test_le_resume_a_payer_suit_les_corrections_et_les_annulations_et_dit_sa_tete(reg, taux):
    ident = _facturer(reg, taux)
    assert ap.resume_a_payer(reg, taux)[0]["a_payer_apres_taxes"] == D("344.93")

    _corriger_ok(reg, taux, ident, montant="310.00")
    corrige, verdict = ap.resume_a_payer(reg, taux)
    assert verdict is None and corrige["a_payer_apres_taxes"] == D("356.42")
    assert corrige["pieces"] == 3 and corrige["tete"] == reg.lire()[-1]["ligne_id"], "la correction est la tête"
    assert corrige["derniere_piece"] == CORRECTION

    _annuler_ok(reg, ident)
    annule, verdict = ap.resume_a_payer(reg, taux)
    assert verdict is None and annule["a_payer_apres_taxes"] == D("344.93")
    assert annule["pieces"] == 4 and annule["derniere_piece"] == ANNULATION


def test_l_annulation_d_une_facture_de_plus_que_le_recu_ramene_l_a_payer_au_recu(reg, taux):
    """Facturé 400.00 pour 300.00 reçus : l'à payer est le facturé (dette ferme). Annulée, il retombe au reçu."""
    ident = _facturer(reg, taux, montant="400.00")
    assert _po(reg, taux)["a_payer_apres_taxes"] == "459.90", "400.00 + 20.00 + 39.90 (39.9 sans fraction)"

    _annuler_ok(reg, ident)

    assert _po(reg, taux)["a_payer_apres_taxes"] == "344.93"


def test_les_totaux_de_la_liste_ne_comptent_pas_les_annulees(reg, taux):
    _recevoir(reg, evenement_id="evt-2", po_id="PO-2", gouttiere="60", vis="0")
    _facturer(reg, taux, numero="F-1001", montant="300.00", po="PO-1")
    annulee = _facturer(reg, taux, numero="F-2001", montant="300.00", po="PO-2")
    _annuler_ok(reg, annulee)

    page, verdict = ap.lister(reg, taux, budget_caracteres=GRAND)

    assert verdict is None
    assert page["totaux"]["facture_apres_taxes"] == "344.93", "seule la première compte"
    assert page["totaux"]["a_payer_apres_taxes"] == "689.86", "344.93 facturé + 344.93 attendu de PO-2 non facturé"
    par_po = {c["po_id"]: c for c in page["comptes"]}
    assert par_po["PO-2"]["factures"]["nombre"] == 0 and par_po["PO-2"]["factures_annulees"] == 1
    assert "factures_annulees" not in par_po["PO-1"]


# ======================================================================== un registre qui ne tient pas debout
def _piece_orpheline(type_entree="correction_facture_fournisseur", ident="apf-fantome"):
    piece = {"type_entree": type_entree, "modification_id": "apm-x", "facture_fournisseur_id": ident,
             "motif": "orpheline (fictif)", "role": "nathan_owner", "voie": "approbation", "horodatage": CORRECTION}
    if type_entree == "correction_facture_fournisseur":
        piece.update(corrige_par="nathan", avant={}, apres={})
    else:
        piece.update(annule_par="nathan", avant={})
    return piece


@pytest.mark.parametrize("type_entree", ["correction_facture_fournisseur", "annulation_facture_fournisseur"])
def test_une_piece_qui_vise_une_facture_absente_leve_partout_jamais_un_chiffre_a_demi_lu(reg, taux, type_entree):
    reg.ajouter(_piece_orpheline(type_entree))

    with pytest.raises(RuntimeError, match="incohérent"):
        ap.lister(reg, taux, budget_caracteres=GRAND)
    with pytest.raises(RuntimeError, match="incohérent"):
        ap.resume_a_payer(reg, taux)
    with pytest.raises(RuntimeError, match="incohérent"):
        ap.factures_saisies(reg)
    with pytest.raises(RuntimeError, match="incohérent"):
        ap.proposer_rapprochement(reg, taux, "PO-1")
    with pytest.raises(RuntimeError, match="incohérent"):
        _corriger(reg, taux, "apf-fantome", montant="1.00")


def test_une_piece_apres_l_annulation_leve_aussi(reg, taux):
    ident = _facturer(reg, taux)
    _annuler_ok(reg, ident)
    reg.ajouter(_piece_orpheline("annulation_facture_fournisseur", ident))

    with pytest.raises(RuntimeError, match="déjà annulée"):
        ap.resume_a_payer(reg, taux)


def test_une_facture_ecrite_deux_fois_avec_le_meme_identifiant_leve(reg, taux):
    _facturer(reg, taux)
    doublee = next(m for m in reg.lire() if m.get("type_entree") == "facture_fournisseur_saisie")
    reg.ajouter({cle: valeur for cle, valeur in doublee.items() if cle not in ("ligne_id", "precedent_ligne_id")})

    with pytest.raises(RuntimeError, match="écrite deux fois"):
        ap.lister(reg, taux, budget_caracteres=GRAND)
