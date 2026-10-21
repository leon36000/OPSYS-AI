"""PLAN T4.15 (M5.2 « comptes à payer », M6.16) : `comptes_a_payer.py`, en pur, sur un registre en mémoire.

Ce que ces tests fixent, à la cent près :
- la réception reçue de M6 devient un « à payer ATTENDU » (quantité reçue x prix du PO, `ROUND_HALF_UP` par ligne,
  taxes recalculées avec les taux versionnés), cumulé sur les livraisons d'un PO ; une pièce absente rend le montant
  « non calculable » (`None`) avec son manque, jamais zéro ;
- la facture fournisseur SAISIE : taxes et total RECALCULÉS, total imprimé en contrôle, doublon refusé, PO déjà reçu,
  fournisseur du PO, humain identifié ;
- le rapprochement PO, réception, facture PROPOSÉ avec ses écarts, jamais stocké ni appliqué ;
- la liste par pages sous une borne de caractères, ses totaux sur TOUS les PO.

Le cas fictif de référence (`PO-1`, Gentek) : 60 gouttières à 5.00 $ (300.00 $) et 40 vis à 0.50 $ (20.00 $), PO de
320.00 $. Reçu en deux livraisons : 300.00 $ puis 20.00 $. Sur 300.00 $, la TVQ vaut 29.925 $ : ROUND_HALF_UP la
monte à 29.93 $ (ROUND_HALF_EVEN, le mode par défaut de `decimal`, la laisserait à 29.92 $). Identifiants et
montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer as ap
from m5_financecore import registre, taux_fiscaux, validation

FICTIF = True
_CHEMIN_TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
LIVRAISON_1 = "2026-09-29T09:15:00-04:00"
LIVRAISON_2 = "2026-10-06T14:30:00-04:00"
SAISIE = "2026-10-08T10:00:00-04:00"
GRAND = 6000


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX)
    assert erreurs == []
    return dictionnaire


def _ligne(materiau, demandee, recue, prix="5.00", devise="CAD", reception="5.00", ecart=False,
           verdict_po="PRIX_LIVRE"):
    return {
        "materiau_id": materiau, "quantite_demandee": demandee, "quantite_recue": recue,
        "prix_unitaire_prevu": prix, "devise_prevue": devise if prix is not None else None,
        "verdict_prix_po": verdict_po if prix is not None else "INDETERMINE",
        "prix_unitaire_reception": reception,
        "verdict_prix_reception": "PRIX_CATALOGUE" if reception is not None else "INDETERMINE",
        "ecart_prix_critique": ecart if reception is not None and prix is not None else None,
    }


def _charge(evenement_id="evt-1", po_id="PO-1", gouttiere="60", vis="0", horodatage=LIVRAISON_1, fournisseur="gentek",
            chantier="CH-1", verdict="RECEPTION_INFERIEURE", statut="partially_received", **surcharges):
    charge = {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": fournisseur, "chantier_id": chantier,
        "horodatage_reception": horodatage, "verdict_reception": verdict, "statut_po": statut,
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [_ligne("gouttiere-5po", "60", gouttiere),
                   _ligne("vis-inox", "40", vis, prix="0.50", reception=None)],
    }
    charge.update(surcharges)
    return charge


def _recevoir(reg, **kwargs):
    entree, verdict = ap.construire_reception(_charge(**kwargs))
    assert verdict is None, verdict
    resultat, verdict = ap.enregistrer_reception(entree, reg)
    assert verdict is None, verdict
    return resultat


def _facturer(reg, taux, numero="F-1001", montant="300.00", po="PO-1", fournisseur="gentek", date="2026-10-01",
              total=None, par="admin.fictif", voie="appareil", horodatage=SAISIE):
    return ap.saisir_facture_fournisseur(
        po_id=po, fournisseur_id=fournisseur, numero_facture=numero, date_facture=date, montant_avant_taxes=montant,
        total_facture=total, saisi_par=par, voie=voie, horodatage=horodatage, dictionnaire_taux=taux,
        registre_cible=reg)


def _facturer_ok(reg, taux, **kwargs):
    resultat, verdict = _facturer(reg, taux, **kwargs)
    assert verdict is None, verdict
    return resultat


def _po(reg, taux, po_id="PO-1"):
    page, verdict = ap.lister(reg, taux, budget_caracteres=GRAND, po_id=po_id)
    assert verdict is None, verdict
    (ligne,) = page["comptes"]
    return ligne


# ===================================================================== réception reçue : l'attendu chiffré
def test_une_reception_partielle_donne_un_attendu_partiel_a_la_cent_pres(taux):
    reg = registre.Registre()
    _recevoir(reg, gouttiere="60", vis="0")

    ligne = _po(reg, taux)

    assert ligne["attendu"] == {"avant_taxes": "300.00", "taxes": "44.93", "apres_taxes": "344.93"}
    assert ligne["a_payer_apres_taxes"] == "344.93", "rien n'est facturé : tout l'attendu est à payer"
    assert ligne["receptions"] == 1 and ligne["statut_po"] == "partially_received"
    # commandé : 320.00 ; reçu : 300.00 ; il reste 40 vis à recevoir
    rapprochement = ligne["rapprochement"]
    assert rapprochement["commande_avant_taxes"] == "320.00" and rapprochement["recu_avant_taxes"] == "300.00"
    assert rapprochement["recu_moins_commande"] == "-20.00"
    assert rapprochement["reste_a_recevoir"] == [{"materiau_id": "vis-inox", "quantite": "40"}]


def test_l_arrondi_de_la_taxe_est_round_half_up_pas_le_mode_du_banquier(taux):
    """300.00 x 9.975 % = 29.925 : ROUND_HALF_UP -> 29.93. ROUND_HALF_EVEN (le défaut de `decimal`) donnerait 29.92."""
    reg = registre.Registre()
    _recevoir(reg, gouttiere="60", vis="0")

    (facture,) = [_facturer_ok(reg, taux, montant="300.00")["facture"]]

    tps, tvq = facture["taxes"]
    assert (tps["id"], tps["montant"]) == ("tps_federale", Decimal("15.00"))
    assert (tvq["id"], tvq["montant"]) == ("tvq_quebec", Decimal("29.93"))
    assert (tps["version"], tvq["version"]) == ("2026-v1", "2026-v1"), "la version du taux voyage avec la facture"
    assert facture["total_taxes"] == Decimal("44.93") and facture["montant_apres_taxes"] == Decimal("344.93")


def test_deux_livraisons_se_cumulent_et_le_reste_a_recevoir_tombe_a_zero(taux):
    reg = registre.Registre()
    _recevoir(reg, evenement_id="evt-1", gouttiere="60", vis="0", horodatage=LIVRAISON_1)
    _recevoir(reg, evenement_id="evt-2", gouttiere="0", vis="40", horodatage=LIVRAISON_2,
              verdict="RECEPTION_INFERIEURE")

    ligne = _po(reg, taux)

    assert ligne["receptions"] == 2 and ligne["derniere_reception"] == LIVRAISON_2
    assert ligne["attendu"] == {"avant_taxes": "320.00", "taxes": "47.92", "apres_taxes": "367.92"}
    assert "reste_a_recevoir" not in ligne["rapprochement"], "tout est arrivé : 60 et 40"
    assert ligne["rapprochement"]["recu_moins_commande"] == "0.00"


def test_une_livraison_qui_depasse_la_commande_est_un_exces_pas_une_erreur(taux):
    reg = registre.Registre()
    _recevoir(reg, gouttiere="65", vis="40")  # 5 gouttières de trop

    rapprochement = _po(reg, taux)["rapprochement"]

    assert rapprochement["en_excedent"] == [{"materiau_id": "gouttiere-5po", "quantite": "5"}]
    assert rapprochement["recu_avant_taxes"] == "345.00" and rapprochement["recu_moins_commande"] == "25.00"


def test_arrondi_par_ligne_demi_cent_monte(taux):
    """2.5 x 0.01 = 0.025 : ROUND_HALF_UP -> 0.03 (ROUND_HALF_EVEN : 0.02)."""
    charge = _charge()
    charge["lignes"] = [_ligne("clou", "2.5", "2.5", prix="0.01", reception=None)]

    entree, verdict = ap.construire_reception(charge)

    assert verdict is None
    assert entree["lignes"][0]["montant_attendu"] == Decimal("0.03")
    assert entree["montant_avant_taxes"] == Decimal("0.03")


def test_le_total_est_la_somme_des_lignes_arrondies_pas_l_arrondi_de_la_somme(taux):
    """Deux lignes de 0.025 : chacune monte à 0.03, le total vaut 0.06 (l'arrondi de la somme, 0.05, serait faux)."""
    charge = _charge()
    charge["lignes"] = [_ligne("a", "2.5", "2.5", prix="0.01", reception=None),
                        _ligne("b", "2.5", "2.5", prix="0.01", reception=None)]

    entree, _ = ap.construire_reception(charge)

    assert entree["montant_avant_taxes"] == Decimal("0.06")


def test_le_produit_n_est_pas_arrondi_avant_l_arrondi_au_cent(taux):
    """Une quantité juste sous le demi-cent : 0.0049999999999999999999999999999 x 1 vaut 0.00 au cent. Avec la
    précision par défaut de `decimal` (28 chiffres), le produit serait d'abord arrondi à 0.005 puis monterait à 0.01."""
    charge = _charge()
    charge["lignes"] = [_ligne("micro", "1", "0.0049999999999999999999999999999", prix="1", reception=None)]

    entree, verdict = ap.construire_reception(charge)

    assert verdict is None
    assert entree["lignes"][0]["montant_attendu"] == Decimal("0.00")


def test_une_ligne_pas_encore_livree_vaut_zero_cent_pas_un_manque(taux):
    entree, _ = ap.construire_reception(_charge(gouttiere="60", vis="0"))

    vis = entree["lignes"][1]

    assert vis["quantite_recue"] == Decimal("0") and vis["montant_attendu"] == Decimal("0.00")
    assert entree["manque"] == [] and entree["montant_avant_taxes"] == Decimal("300.00")


def test_un_prix_de_po_absent_rend_l_attendu_non_calculable_jamais_zero(taux):
    reg = registre.Registre()
    charge = _charge()
    charge["lignes"][1] = _ligne("vis-inox", "40", "10", prix=None, reception=None)
    entree, verdict = ap.construire_reception(charge)
    assert verdict is None
    assert entree["montant_avant_taxes"] is None and entree["manque"] == ["REJ-AP-PRIX-PO-ABSENT"]
    assert entree["lignes"][1]["montant_attendu"] is None
    ap.enregistrer_reception(entree, reg)

    ligne = _po(reg, taux)

    assert ligne["attendu"] == {"avant_taxes": None, "taxes": None, "apres_taxes": None}
    assert ligne["a_payer_apres_taxes"] is None and ligne["manque"] == ["REJ-AP-PRIX-PO-ABSENT"]
    assert ligne["rapprochement"]["verdict"] == "INCOMPLET"
    assert ligne["rapprochement"]["recu_avant_taxes"] is None and ligne["rapprochement"]["facture_moins_recu"] is None


@pytest.mark.parametrize("devise", ["USD", "EUR", "", "cad-x"])
def test_une_devise_autre_que_cad_n_est_jamais_convertie(taux, devise):
    charge = _charge()
    charge["lignes"][0]["devise_prevue"] = devise

    entree, verdict = ap.construire_reception(charge)

    assert verdict is None and entree["montant_avant_taxes"] is None
    assert "REJ-AP-DEVISE-NON-CAD" in entree["manque"] and entree["lignes"][0]["montant_attendu"] is None


def test_la_devise_cad_s_ecrit_sans_egard_a_la_casse_et_aux_espaces(taux):
    charge = _charge()
    charge["lignes"][0]["devise_prevue"] = " cad "

    entree, _ = ap.construire_reception(charge)

    assert entree["manque"] == [] and entree["montant_avant_taxes"] == Decimal("300.00")


def test_un_montant_hors_plafond_est_illisible_pas_une_exception(taux):
    charge = _charge()
    charge["lignes"][0]["quantite_recue"] = "1000000000000"  # 10^12 unités : hors du plafond de lecture

    entree, verdict = ap.construire_reception(charge)

    assert verdict is None and entree["montant_avant_taxes"] is None
    assert entree["manque"] == ["REJ-AP-MONTANT-ILLISIBLE"]


def test_l_ecart_de_prix_est_garde_pour_l_audit_sans_changer_l_attendu(taux):
    """L'attendu vient du prix du PO. L'écart avec le prix de la réception est une information, en dollars exacts."""
    charge = _charge()
    charge["lignes"][0].update({"prix_unitaire_reception": "6.25", "ecart_prix_critique": True})

    entree, _ = ap.construire_reception(charge)

    gouttiere = entree["lignes"][0]
    assert gouttiere["ecart_prix_unitaire"] == Decimal("1.25") and gouttiere["ecart_prix_critique"] is True
    assert gouttiere["montant_attendu"] == Decimal("300.00"), "toujours 60 x 5.00 : le prix du PO"


# ---------------------------------------------------------------- réception : refus de ce qui ne tient pas debout
@pytest.mark.parametrize("charge", [None, "texte", [], 42])
def test_une_charge_qui_n_est_pas_un_objet_est_refusee(charge):
    entree, verdict = ap.construire_reception(charge)

    assert entree is None and verdict["code"] == "REJ-AP-RECEPTION-INVALIDE"


@pytest.mark.parametrize("champ", ["evenement_id", "po_id", "fournisseur_id", "chantier_id", "hash_maillon"])
@pytest.mark.parametrize("valeur", [None, "", "   ", 12])
def test_un_identifiant_absent_ou_vide_est_refuse(champ, valeur):
    charge = _charge()
    charge[champ] = valeur

    entree, verdict = ap.construire_reception(charge)

    assert entree is None and verdict["code"] == "REJ-AP-RECEPTION-INVALIDE" and champ in verdict["detail"]


@pytest.mark.parametrize("horodatage", ["2026-09-29", "2026-09-29T09:15:00", "hier", "", None, 20260929])
def test_un_horodatage_sans_fuseau_est_refuse(horodatage):
    entree, verdict = ap.construire_reception(_charge(horodatage=horodatage))

    assert entree is None and verdict["code"] == "REJ-AP-RECEPTION-INVALIDE"


@pytest.mark.parametrize("surcharge", [{"verdict": "INDETERMINE"}, {"verdict": "N'IMPORTE QUOI"},
                                       {"statut": "approved"}, {"statut": None}])
def test_un_verdict_ou_un_statut_inconnu_est_refuse(surcharge):
    entree, verdict = ap.construire_reception(_charge(**surcharge))

    assert entree is None and verdict["code"] == "REJ-AP-RECEPTION-INVALIDE"


@pytest.mark.parametrize("lignes", [None, [], "texte", {}])
def test_sans_ligne_la_reception_est_refusee(lignes):
    entree, verdict = ap.construire_reception(_charge(lignes=lignes))

    assert entree is None and verdict["code"] == "REJ-AP-RECEPTION-INVALIDE"


@pytest.mark.parametrize("modification", [
    ("quantite_recue", 40.0),                                  # un nombre JSON, jamais du texte
    ("quantite_recue", "-1"),                                  # négative
    ("quantite_recue", "1e3"),                                 # notation scientifique
    ("quantite_recue", "40 pi"),                               # une unité collée : on ne l'interprète pas
    ("quantite_recue", ""),
    ("quantite_recue", "1" * 41),                              # au-delà de 40 caractères
    ("quantite_demandee", None),
    ("prix_unitaire_prevu", 5.0),                              # un prix en nombre
    ("prix_unitaire_prevu", "0"),                              # un prix nul n'est pas un prix
    ("prix_unitaire_prevu", "-5.00"),
    ("prix_unitaire_reception", "0"),
    ("prix_unitaire_reception", 5.0),
    ("devise_prevue", 7),
    ("ecart_prix_critique", "oui"),
    ("materiau_id", ""),
    ("verdict_prix_po", None),
])
def test_une_ligne_qui_ne_tient_pas_debout_est_refusee_et_nommee(modification):
    champ, valeur = modification
    charge = _charge()
    charge["lignes"][0][champ] = valeur

    entree, verdict = ap.construire_reception(charge)

    assert entree is None and verdict["code"] == "REJ-AP-RECEPTION-INVALIDE" and "ligne 0" in verdict["detail"]


def test_une_ligne_qui_n_est_pas_un_objet_est_refusee():
    charge = _charge()
    charge["lignes"][1] = "pas un objet"

    entree, verdict = ap.construire_reception(charge)

    assert entree is None and "ligne 1" in verdict["detail"]


# ---------------------------------------------------------------------------- enregistrer_reception
def test_une_redelivrance_ne_double_jamais_l_attendu(taux):
    reg = registre.Registre()
    premier, deja = _recevoir(reg, evenement_id="evt-1")
    assert deja is False and reg.taille() == 1

    rejoue, deja = _recevoir(reg, evenement_id="evt-1")

    assert deja is True and reg.taille() == 1 and rejoue["ligne_id"] == premier["ligne_id"]
    assert _po(reg, taux)["attendu"]["avant_taxes"] == "300.00"


def test_deux_evenements_distincts_sont_deux_livraisons(taux):
    reg = registre.Registre()
    _recevoir(reg, evenement_id="evt-1")
    _recevoir(reg, evenement_id="evt-2")

    assert reg.taille() == 2
    assert _po(reg, taux)["attendu"]["avant_taxes"] == "600.00", "deux livraisons de 300.00 $ : elles se cumulent"


@pytest.mark.parametrize("surcharge", [{"fournisseur": "royal"}, {"chantier": "CH-AUTRE"}])
def test_un_po_connu_sous_un_autre_fournisseur_ou_chantier_est_refuse(surcharge):
    reg = registre.Registre()
    _recevoir(reg, evenement_id="evt-1")
    entree, _ = ap.construire_reception(_charge(evenement_id="evt-2", **surcharge))

    resultat, verdict = ap.enregistrer_reception(entree, reg)

    assert resultat is None and verdict["code"] == "REJ-AP-PO-INCOHERENT"
    assert reg.taille() == 1, "rien n'est écrit : on ne doit pas d'argent à deux fournisseurs pour un même PO"


def test_le_registre_de_reception_porte_des_types_de_comptes_a_payer_seulement(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux)

    assert {m["type_entree"] for m in reg.lire()} == {"reception_recue", "facture_fournisseur_saisie"}
    assert reg.valider_chaine() == (True, "")


# ========================================================================== facture fournisseur saisie
def test_la_facture_saisie_est_recalculee_et_rangee_au_statut_saisie(taux):
    reg = registre.Registre()
    _recevoir(reg)

    resultat = _facturer_ok(reg, taux, numero="F-1001", montant="300.00", total="344.93")

    facture = resultat["facture"]
    assert facture["statut"] == "SAISIE" and resultat["avertissements"] == []
    assert facture["montant_avant_taxes"] == Decimal("300.00")
    assert facture["montant_apres_taxes"] == Decimal("344.93")
    assert (facture["saisi_par"], facture["voie"], facture["horodatage"]) == ("admin.fictif", "appareil", SAISIE)
    assert (facture["po_id"], facture["fournisseur_id"], facture["date_facture"]) == ("PO-1", "gentek", "2026-10-01")
    assert facture["facture_fournisseur_id"].startswith("apf-") and len(facture["facture_fournisseur_id"]) == 24
    vue = ap.vue_facture(facture)
    assert "ligne_id" not in vue and "precedent_ligne_id" not in vue and vue["statut"] == "SAISIE"


def test_l_identifiant_de_facture_est_deterministe_et_ne_depend_que_de_fournisseur_numero_montant(taux):
    reg_a, reg_b = registre.Registre(), registre.Registre()
    for reg in (reg_a, reg_b):
        _recevoir(reg)
    a = _facturer_ok(reg_a, taux, numero="F-1001", montant="300.00")["facture"]
    b = _facturer_ok(reg_b, taux, numero="  f-1001 ", montant="300", date="2026-09-30", par="autre.personne")["facture"]

    assert a["facture_fournisseur_id"] == b["facture_fournisseur_id"], "même fournisseur, numéro, montant"


def test_le_montant_avant_taxes_est_ce_qu_un_humain_tape_les_taxes_sont_recalculees(taux):
    reg = registre.Registre()
    _recevoir(reg)

    facture = _facturer_ok(reg, taux, montant="1234.50")["facture"]

    # 1234.50 x 5 % = 61.725 -> 61.73 (ROUND_HALF_UP ; ROUND_HALF_EVEN donnerait 61.72)
    assert facture["taxes"][0]["montant"] == Decimal("61.73")
    # 1234.50 x 9,975 % = 123.141375 -> 123.14
    assert facture["taxes"][1]["montant"] == Decimal("123.14")
    assert facture["total_taxes"] == Decimal("184.87")
    assert facture["montant_apres_taxes"] == Decimal("1419.37")


@pytest.mark.parametrize("total", ["344.92", "344.94", "300.00", "0.01"])
def test_un_total_imprime_qui_ne_concorde_pas_au_cent_pres_refuse_la_saisie(taux, total):
    reg = registre.Registre()
    _recevoir(reg)
    avant = reg.lire()

    resultat, verdict = _facturer(reg, taux, montant="300.00", total=total)

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-TOTAL-INCOHERENT"
    assert total in verdict["detail"] and "344.93" in verdict["detail"], "le détail donne les deux chiffres"
    assert reg.lire() == avant, "rien n'est écrit"


def test_un_total_imprime_qui_concorde_est_accepte_sans_total(taux):
    reg = registre.Registre()
    _recevoir(reg)

    assert _facturer_ok(reg, taux, montant="300.00", total="344.93", numero="A")["facture"]
    assert _facturer_ok(reg, taux, montant="300.00", total=None, numero="B")["facture"]


@pytest.mark.parametrize("montant", ["12,50", "-5.00", "0", "0.00", "12.505", "1e3", "", " 12.50", "12.50 $", "abc",
                                     12.5, None, True, "1234567890123", "١٢"])
def test_un_montant_avant_taxes_mal_forme_est_refuse(taux, montant):
    reg = registre.Registre()
    _recevoir(reg)
    avant = reg.lire()

    resultat, verdict = _facturer(reg, taux, montant=montant)

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-MONTANT-INVALIDE"
    assert reg.lire() == avant


@pytest.mark.parametrize("total", ["12,50", "-5.00", "0", "12.505", 344.93, True, ""])
def test_un_total_imprime_mal_forme_est_refuse(taux, total):
    reg = registre.Registre()
    _recevoir(reg)

    resultat, verdict = _facturer(reg, taux, montant="300.00", total=total)

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-MONTANT-INVALIDE"


@pytest.mark.parametrize("champ, valeur", [("po", ""), ("po", "   "), ("po", None), ("fournisseur", ""),
                                            ("fournisseur", None), ("numero", ""), ("numero", "  "), ("numero", None),
                                            ("numero", "x" * 65), ("numero", "F-1\n2")])
def test_un_champ_texte_vide_ou_illisible_est_refuse(taux, champ, valeur):
    reg = registre.Registre()
    _recevoir(reg)

    resultat, verdict = _facturer(reg, taux, **{champ: valeur})

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-CHAMP-INVALIDE"


@pytest.mark.parametrize("date", ["2026-13-01", "2026-02-30", "01-10-2026", "20261001", "2026-10-1", "hier", "", None,
                                  20261001, "2026-W40-4"])
def test_une_date_de_facture_invalide_est_refusee(taux, date):
    reg = registre.Registre()
    _recevoir(reg)

    resultat, verdict = _facturer(reg, taux, date=date)

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DATE-INVALIDE"


def test_une_facture_datee_apres_sa_saisie_est_refusee_le_jour_meme_est_permis(taux):
    reg = registre.Registre()
    _recevoir(reg)

    futur, verdict = _facturer(reg, taux, date="2026-10-09", horodatage="2026-10-08T23:59:00-04:00")
    assert futur is None and verdict["code"] == "REJ-AP-FACTURE-DATE-FUTURE"

    assert _facturer_ok(reg, taux, date="2026-10-08", horodatage="2026-10-08T00:00:01-04:00")["facture"]


@pytest.mark.parametrize("horodatage", ["2026-10-08", "2026-10-08T10:00:00", "hier", "", None, 5])
def test_un_horodatage_de_saisie_sans_fuseau_est_refuse(taux, horodatage):
    reg = registre.Registre()
    _recevoir(reg)

    resultat, verdict = _facturer(reg, taux, horodatage=horodatage)

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-HORODATAGE-INVALIDE"


@pytest.mark.parametrize("voie, par", [("agent", "admin.fictif"), (None, "admin.fictif"), ("", "admin.fictif"),
                                       ("appareil", ""), ("appareil", None), ("approbation", "   ")])
def test_sans_humain_identifie_la_saisie_est_refusee(taux, voie, par):
    reg = registre.Registre()
    _recevoir(reg)
    avant = reg.lire()

    resultat, verdict = _facturer(reg, taux, voie=voie, par=par)

    assert resultat is None and verdict["code"] == "REJ-AP-HUMAIN-REQUIS"
    assert reg.lire() == avant


def test_les_deux_voies_humaines_sont_acceptees(taux):
    reg = registre.Registre()
    _recevoir(reg)

    par_appareil = _facturer_ok(reg, taux, numero="A", voie="appareil")["facture"]
    par_approbation = _facturer_ok(reg, taux, numero="B", voie="approbation", par="finance.fictive")["facture"]

    assert (par_appareil["voie"], par_approbation["voie"], par_approbation["saisi_par"]) == (
        "appareil", "approbation", "finance.fictive")


def test_une_facture_pour_un_po_jamais_recu_est_refusee_avec_ce_qu_il_faut_faire(taux):
    reg = registre.Registre()
    _recevoir(reg)

    resultat, verdict = _facturer(reg, taux, po="PO-INCONNU")

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-PO-SANS-RECEPTION"
    assert "PO-INCONNU" in verdict["detail"] and "M6" in verdict["detail"]


def test_une_facture_d_un_autre_fournisseur_que_celui_du_po_est_refusee(taux):
    reg = registre.Registre()
    _recevoir(reg)

    resultat, verdict = _facturer(reg, taux, fournisseur="royal")

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-FOURNISSEUR-DIFFERENT-DU-PO"
    assert "gentek" in verdict["detail"] and "royal" in verdict["detail"]


def test_un_taux_fiscal_manquant_bloque_la_saisie_sans_rien_ecrire(taux):
    reg = registre.Registre()
    _recevoir(reg)
    sans_tvq = {cle: valeur for cle, valeur in taux.items() if cle != "tvq_quebec"}
    avant = reg.lire()

    resultat, verdict = _facturer(reg, sans_tvq)

    assert resultat is None and verdict["code"] == "REJ-TAUX-INCONNU"
    assert reg.lire() == avant


# ------------------------------------------------------------------------------------------- doublons
def test_le_doublon_fournisseur_numero_montant_est_refuse_et_rien_n_est_ecrit(taux):
    reg = registre.Registre()
    _recevoir(reg)
    premiere = _facturer_ok(reg, taux, numero="F-1001", montant="300.00")["facture"]
    taille = reg.taille()

    resultat, verdict = _facturer(reg, taux, numero="F-1001", montant="300.00", date="2026-10-02")

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON"
    assert premiere["facture_fournisseur_id"] in verdict["detail"] and "F-1001" in verdict["detail"]
    assert reg.taille() == taille


@pytest.mark.parametrize("numero", ["F-1001", "f-1001", "F-1001 ", "  F-1001", " f-1001  ", "F-1001\t"])
def test_le_doublon_ignore_la_casse_et_les_espaces_autour_du_numero(taux, numero):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1001", montant="300.00")

    resultat, verdict = _facturer(reg, taux, numero=numero, montant="300.00")

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON"


@pytest.mark.parametrize("numero", ["F 1001", "f  1001", "  F   1001 "])
def test_le_doublon_reduit_les_espaces_internes(taux, numero):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F 1001", montant="300.00")

    resultat, verdict = _facturer(reg, taux, numero=numero, montant="300.00")

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON"


def test_le_doublon_ne_confond_pas_zeros_de_tete_ni_ponctuation(taux):
    """`00123` et `123`, `F-1001` et `F1001` sont deux numéros : deviner qu'ils sont le même serait inventer."""
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="00123", montant="300.00")

    assert _facturer(reg, taux, numero="123", montant="300.00")[1] is None
    assert _facturer(reg, taux, numero="0-0123", montant="300.00")[1] is None


def test_le_doublon_compare_le_montant_et_non_son_ecriture(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1", montant="300.5")

    resultat, verdict = _facturer(reg, taux, numero="F-1", montant="300.50")

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON", "300.5 et 300.50 sont le même montant"


def test_le_doublon_est_refuse_meme_pour_un_autre_po_du_meme_fournisseur(taux):
    reg = registre.Registre()
    _recevoir(reg, po_id="PO-1", evenement_id="e1")
    _recevoir(reg, po_id="PO-2", evenement_id="e2")
    _facturer_ok(reg, taux, po="PO-1", numero="F-1001", montant="300.00")

    resultat, verdict = _facturer(reg, taux, po="PO-2", numero="F-1001", montant="300.00")

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON"
    assert "PO-1" in verdict["detail"], "le détail dit où la première est rangée"


def test_meme_numero_avec_un_autre_montant_passe_avec_un_avertissement(taux):
    """Refuser bloquerait la bonne facture : l'écart est montré, et la correction ou l'annulation de l'une des deux
    (T4.15-c, `test_correction_facture.py`) lève l'avertissement."""
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1001", montant="300.00")

    resultat = _facturer_ok(reg, taux, numero="F-1001", montant="320.00")

    assert resultat["avertissements"] == ["REJ-AP-FACTURE-NUMERO-REPETE"]
    assert resultat["facture"]["avertissements"] == ["REJ-AP-FACTURE-NUMERO-REPETE"]
    assert _po(reg, taux)["rapprochement"]["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE",
                                                           "REJ-AP-FACTURE-NUMERO-REPETE"]


def test_meme_montant_avec_un_autre_numero_ou_un_autre_fournisseur_n_est_pas_un_doublon(taux):
    reg = registre.Registre()
    _recevoir(reg, po_id="PO-1", evenement_id="e1", fournisseur="gentek")
    _recevoir(reg, po_id="PO-2", evenement_id="e2", fournisseur="royal")
    _facturer_ok(reg, taux, po="PO-1", numero="F-1001", montant="300.00")

    autre_numero = _facturer_ok(reg, taux, po="PO-1", numero="F-1002", montant="300.00")
    autre_fournisseur = _facturer_ok(reg, taux, po="PO-2", fournisseur="royal", numero="F-1001", montant="300.00")

    assert autre_numero["avertissements"] == [] and autre_fournisseur["avertissements"] == []


# ===================================================== rapprochement PO, réception, facture : PROPOSÉ
def test_le_rapprochement_suit_le_cas_de_reference_de_bout_en_bout(taux):
    reg = registre.Registre()
    _recevoir(reg, evenement_id="evt-1", gouttiere="60", vis="0", horodatage=LIVRAISON_1)

    sans_facture = _po(reg, taux)
    assert sans_facture["rapprochement"]["verdict"] == "SANS_FACTURE"
    assert sans_facture["a_payer_apres_taxes"] == "344.93"

    _facturer_ok(reg, taux, numero="F-1001", montant="300.00")
    concordant = _po(reg, taux)
    assert concordant["rapprochement"]["verdict"] == "CONCORDANT"
    assert concordant["rapprochement"]["facture_moins_recu"] == "0.00" and "sens" not in concordant["rapprochement"]
    assert concordant["factures"] == {"nombre": 1, "avant_taxes": "300.00", "taxes": "44.93", "apres_taxes": "344.93"}
    assert concordant["a_payer_apres_taxes"] == "344.93", "la facture couvre tout ce qui est arrivé"

    _recevoir(reg, evenement_id="evt-2", gouttiere="0", vis="40", horodatage=LIVRAISON_2)
    a_facturer = _po(reg, taux)
    rapprochement = a_facturer["rapprochement"]
    assert rapprochement["verdict"] == "ECART" and rapprochement["sens"] == "FACTURE_INFERIEURE_AU_RECU"
    assert rapprochement["recu_avant_taxes"] == "320.00" and rapprochement["facture_avant_taxes"] == "300.00"
    assert rapprochement["facture_moins_recu"] == "-20.00"
    # à payer = la facture (344.93) + le reçu non facturé (20.00 + TPS 1.00 + TVQ 2.00) = 367.93
    assert a_facturer["a_payer_apres_taxes"] == "367.93"

    _facturer_ok(reg, taux, numero="F-1002", montant="20.00")
    complet = _po(reg, taux)
    assert complet["rapprochement"]["verdict"] == "CONCORDANT"
    assert complet["factures"]["apres_taxes"] == "367.93" and complet["a_payer_apres_taxes"] == "367.93"
    # l'attendu, lui, est taxé une seule fois sur 320.00 (367.92) : le cent de différence vient des deux
    # arrondis de TVQ des deux factures, et n'est PAS un écart (le verdict se juge avant taxes)
    assert complet["attendu"]["apres_taxes"] == "367.92"


def test_une_facture_superieure_au_recu_est_un_ecart_dans_le_bon_sens(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1", montant="350.00")

    ligne = _po(reg, taux)

    assert ligne["rapprochement"]["verdict"] == "ECART"
    assert ligne["rapprochement"]["sens"] == "FACTURE_SUPERIEURE_AU_RECU"
    assert ligne["rapprochement"]["facture_moins_recu"] == "50.00"
    assert ligne["a_payer_apres_taxes"] == ligne["factures"]["apres_taxes"] == "402.41", (
        "facturé plus que reçu : on doit ce qui est facturé, aucun reçu non facturé ne s'ajoute")


def test_un_ecart_d_un_cent_est_un_ecart_aucune_tolerance_n_est_inventee(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1", montant="300.01")

    rapprochement = _po(reg, taux)["rapprochement"]

    assert rapprochement["verdict"] == "ECART" and rapprochement["facture_moins_recu"] == "0.01"


def test_plusieurs_factures_d_un_po_se_totalisent(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1", montant="100.00")
    _facturer_ok(reg, taux, numero="F-2", montant="200.00")

    ligne = _po(reg, taux)

    assert ligne["factures"]["nombre"] == 2 and ligne["factures"]["avant_taxes"] == "300.00"
    assert ligne["rapprochement"]["verdict"] == "CONCORDANT"


def test_la_reserve_d_unite_est_sur_tout_rapprochement_meme_concordant(taux):
    """GATE NATHAN : l'unité des prix du livre de prix n'est pas déclarée. Le verdict le dit toujours."""
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1", montant="300.00")

    ligne = _po(reg, taux)

    assert ligne["rapprochement"]["verdict"] == "CONCORDANT"
    assert ap.CODE_UNITE_PRIX in ligne["rapprochement"]["reserves"]
    page, _ = ap.lister(reg, taux, budget_caracteres=GRAND)
    assert any("unité des prix" in h and "GATE NATHAN" in h and "sans aucune conversion" in h
               for h in page["hypotheses"])
    assert validation.est_verdict(ap.CODE_UNITE_PRIX)


def test_aucune_conversion_d_unite_les_quantites_restent_celles_de_m6(taux):
    """Un PO en « boîtes » dont le prix serait « au pied » : M5 ne le sait pas et ne le corrige pas. Les quantités
    et les prix sont multipliés tels quels ; seule la réserve le signale."""
    charge = _charge()
    charge["lignes"] = [_ligne("soffite", "10", "10", prix="40.00", reception=None)]

    entree, _ = ap.construire_reception(charge)

    assert entree["lignes"][0]["montant_attendu"] == Decimal("400.00")
    assert "unite" not in json.dumps(entree, default=str)


def test_le_rapprochement_est_une_proposition_jamais_stockee_ni_appliquee(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1", montant="350.00")
    avant = reg.lire()

    proposition, verdict = ap.proposer_rapprochement(reg, taux, "PO-1")
    ap.lister(reg, taux, budget_caracteres=GRAND)

    assert verdict is None and proposition["statut"] == "PROPOSE"
    assert reg.lire() == avant, "lire ou proposer n'écrit rien"
    assert {m["type_entree"] for m in reg.lire()} == {"reception_recue", "facture_fournisseur_saisie"}
    assert all("rapproch" not in json.dumps(m, default=str).lower() for m in reg.lire()), "aucun état « rapproché »"
    factures = [m for m in reg.lire() if m["type_entree"] == "facture_fournisseur_saisie"]
    assert factures and all(m["statut"] == "SAISIE" for m in factures)


def test_proposer_le_rapprochement_d_un_po_inconnu_est_refuse(taux):
    proposition, verdict = ap.proposer_rapprochement(registre.Registre(), taux, "PO-FANTOME")

    assert proposition is None and verdict["code"] == "REJ-AP-PO-INCONNU"


# ============================================================================================ la liste
def _garnir(reg, nombre, prix="5.00"):
    """`nombre` PO de 1 ligne, reçus un par jour, dans le désordre des identifiants."""
    for i in range(nombre):
        rang = nombre - i  # les identifiants décroissent quand les dates croissent
        charge = _charge(evenement_id=f"evt-{rang}", po_id=f"PO-{rang:03d}",
                         horodatage=f"2026-09-{1 + i:02d}T09:00:00-04:00")
        charge["lignes"] = [_ligne("gouttiere-5po", "10", "10", prix=prix, reception=None)]
        entree, verdict = ap.construire_reception(charge)
        assert verdict is None
        ap.enregistrer_reception(entree, reg)


def test_l_ordre_est_la_premiere_reception_puis_l_identifiant(taux):
    reg = registre.Registre()
    _garnir(reg, 5)

    page, verdict = ap.lister(reg, taux, budget_caracteres=100_000)

    assert verdict is None
    assert [c["po_id"] for c in page["comptes"]] == ["PO-005", "PO-004", "PO-003", "PO-002", "PO-001"]
    assert page["ordre"].startswith("première réception croissante")


def test_a_instant_egal_l_identifiant_croissant_departage(taux):
    reg = registre.Registre()
    for po in ("PO-B", "PO-A", "PO-C"):
        _recevoir(reg, po_id=po, evenement_id=f"evt-{po}", horodatage=LIVRAISON_1)

    page, _ = ap.lister(reg, taux, budget_caracteres=100_000)

    assert [c["po_id"] for c in page["comptes"]] == ["PO-A", "PO-B", "PO-C"]


def test_l_instant_est_compare_avec_son_fuseau_pas_comme_un_texte(taux):
    """08:00-04:00 est 12:00 UTC ; 09:00+00:00 est 09:00 UTC, donc plus tôt, alors que le TEXTE « 08... » vient
    avant."""
    reg = registre.Registre()
    _recevoir(reg, po_id="PO-TARD", evenement_id="e1", horodatage="2026-09-29T08:00:00-04:00")
    _recevoir(reg, po_id="PO-TOT", evenement_id="e2", horodatage="2026-09-29T09:00:00+00:00")

    page, _ = ap.lister(reg, taux, budget_caracteres=100_000)

    assert [c["po_id"] for c in page["comptes"]] == ["PO-TOT", "PO-TARD"]


def test_les_pages_couvrent_chaque_po_une_seule_fois_sous_la_borne(taux):
    reg = registre.Registre()
    _garnir(reg, 30)
    borne = 3000
    vus, depart, pages = [], 0, 0

    while depart is not None:
        page, verdict = ap.lister(reg, taux, depart=depart, budget_caracteres=borne)
        assert verdict is None
        assert len(json.dumps(page, ensure_ascii=False)) <= borne, "la page est mesurée sur ce que le modèle reçoit"
        assert page["total"] == 30 and page["depart"] == depart and page["affichees"] == len(page["comptes"]) >= 1
        assert page["reste"] == 30 - depart - page["affichees"]
        vus.extend(c["po_id"] for c in page["comptes"])
        depart, pages = page["prochain_depart"], pages + 1
        assert pages < 40, "la lecture doit progresser"

    assert pages > 1, "la borne est assez basse pour forcer la pagination"
    assert vus == [f"PO-{n:03d}" for n in range(30, 0, -1)] and len(set(vus)) == 30


def test_la_derniere_page_dit_qu_il_n_y_a_plus_rien(taux):
    reg = registre.Registre()
    _garnir(reg, 3)

    page, _ = ap.lister(reg, taux, budget_caracteres=100_000)

    assert (page["affichees"], page["reste"], page["prochain_depart"], page["message"]) == (3, 0, None, None)


def test_une_page_tronquee_annonce_la_suite(taux):
    reg = registre.Registre()
    _garnir(reg, 10)

    page, _ = ap.lister(reg, taux, budget_caracteres=2600)

    assert page["reste"] > 0 and page["prochain_depart"] == page["affichees"]
    assert f"depart={page['prochain_depart']}" in page["message"]


def test_depart_egal_au_total_rend_une_page_vide_pas_une_erreur(taux):
    reg = registre.Registre()
    _garnir(reg, 3)

    page, verdict = ap.lister(reg, taux, depart=3, budget_caracteres=100_000)

    assert verdict is None and page["comptes"] == [] and page["affichees"] == 0 and page["prochain_depart"] is None


@pytest.mark.parametrize("depart", [-1, 4, 1.5, "0", True, None])
def test_un_depart_invalide_ou_au_dela_de_la_fin_est_refuse(taux, depart):
    reg = registre.Registre()
    _garnir(reg, 3)

    page, verdict = ap.lister(reg, taux, depart=depart, budget_caracteres=100_000)

    assert page is None and verdict["code"] == "REJ-AP-LISTE-DEPART-INVALIDE"


def test_un_po_plus_gros_que_la_borne_est_un_refus_nomme(taux):
    reg = registre.Registre()
    _recevoir(reg)

    page, verdict = ap.lister(reg, taux, budget_caracteres=500)

    assert page is None and verdict["code"] == "REJ-AP-LISTE-LIGNE-TROP-GROSSE" and "PO-1" in verdict["detail"]


def test_le_detail_d_un_po_porte_quantites_factures_et_livraisons(taux):
    reg = registre.Registre()
    _recevoir(reg, evenement_id="evt-1", gouttiere="60", vis="0", horodatage=LIVRAISON_1)
    charge = _charge(evenement_id="evt-2", gouttiere="0", vis="10", horodatage=LIVRAISON_2)
    charge["lignes"][0].update({"prix_unitaire_reception": "6.25", "ecart_prix_critique": True})
    entree, _ = ap.construire_reception(charge)
    ap.enregistrer_reception(entree, reg)
    _facturer_ok(reg, taux, numero="F-1001", montant="300.00")
    autre, _ = ap.construire_reception(_charge(po_id="PO-2", evenement_id="evt-3"))
    ap.enregistrer_reception(autre, reg)

    page, verdict = ap.lister(reg, taux, budget_caracteres=GRAND, po_id="PO-1")

    assert verdict is None and page["total"] == 1, "un seul PO : le filtre"
    (ligne,) = page["comptes"]
    assert ligne["quantites"] == [
        {"materiau_id": "gouttiere-5po", "commandee": "60", "recue": "60", "ecart": "0"},
        {"materiau_id": "vis-inox", "commandee": "40", "recue": "10", "ecart": "-30"},
    ]
    assert [f["numero_facture"] for f in ligne["factures_saisies"]] == ["F-1001"]
    assert ligne["factures_saisies"][0]["saisi_par"] == "admin.fictif"
    assert [(v["evenement_id"], v["avant_taxes"]) for v in ligne["livraisons"]] == [("evt-1", "300.00"),
                                                                                     ("evt-2", "5.00")]
    assert ligne["livraisons"][1]["lignes_avec_ecart_de_prix"] == [
        {"materiau_id": "gouttiere-5po", "ecart_prix_unitaire": "1.25"}]
    assert ligne["commande_avant_taxes"] == "320.00" and ligne["premiere_reception"] == LIVRAISON_1


def test_un_po_inconnu_est_un_refus_nomme(taux):
    reg = registre.Registre()
    _recevoir(reg)

    for po in ("PO-FANTOME", "", "   ", 7):
        page, verdict = ap.lister(reg, taux, budget_caracteres=GRAND, po_id=po)
        assert page is None and verdict["code"] == "REJ-AP-PO-INCONNU"


# ------------------------------------------------------------------------------------------- totaux
def test_les_totaux_portent_sur_tous_les_po_pas_sur_la_page(taux):
    reg = registre.Registre()
    _garnir(reg, 12)  # 12 PO de 10 x 5.00 = 50.00 avant taxes, 57.49 après taxes (2.50 + 4.99 de taxes)

    page, _ = ap.lister(reg, taux, depart=0, budget_caracteres=2600)

    assert page["affichees"] < 12, "la page ne montre pas tout"
    assert page["totaux"]["nombre_po"] == 12
    assert page["totaux"]["attendu_apres_taxes"] == page["totaux"]["a_payer_apres_taxes"] == "689.88"  # 12 x 57.49
    assert page["totaux"]["complet"] is True and page["totaux"]["non_calculables"] == 0


def test_un_po_non_calculable_ne_compte_jamais_pour_zero(taux):
    reg = registre.Registre()
    _garnir(reg, 2)  # 2 x 57.49 = 114.98
    charge = _charge(po_id="PO-SANS-PRIX", evenement_id="evt-sp")
    charge["lignes"][0]["prix_unitaire_prevu"] = None
    charge["lignes"][0]["devise_prevue"] = None
    charge["lignes"][0]["verdict_prix_po"] = "INDETERMINE"
    entree, _ = ap.construire_reception(charge)
    ap.enregistrer_reception(entree, reg)

    totaux = ap.lister(reg, taux, budget_caracteres=100_000)[0]["totaux"]

    assert totaux["complet"] is False and totaux["non_calculables"] == 1
    assert totaux["a_payer_apres_taxes"] is None, "jamais un total partiel"
    assert totaux["attendu_apres_taxes"] is None
    assert totaux["a_payer_connu_apres_taxes"] == "114.98", "un plancher, nommé comme tel"
    assert totaux["non_calculables_po"] == [{"po_id": "PO-SANS-PRIX", "manque": ["REJ-AP-PRIX-PO-ABSENT"]}]


def test_le_plancher_compte_le_deja_facture_d_un_po_non_calculable(taux):
    """Un PO dont le prix manque n'est pas chiffrable, mais une facture SAISIE contre lui est une dette ferme : le
    plancher la compte (200.00 $ + TPS 10.00 $ + TVQ 19.95 $ = 229.95 $), jamais zéro, sans jamais la présenter comme
    le total."""
    reg = registre.Registre()
    _garnir(reg, 2)  # 2 x 57.49 = 114.98
    charge = _charge(po_id="PO-SANS-PRIX", evenement_id="evt-sp")
    charge["lignes"][0]["prix_unitaire_prevu"] = None
    charge["lignes"][0]["devise_prevue"] = None
    charge["lignes"][0]["verdict_prix_po"] = "INDETERMINE"
    entree, _ = ap.construire_reception(charge)
    ap.enregistrer_reception(entree, reg)
    _facturer_ok(reg, taux, po="PO-SANS-PRIX", numero="F-9", montant="200.00")

    totaux = ap.lister(reg, taux, budget_caracteres=100_000)[0]["totaux"]

    assert totaux["a_payer_apres_taxes"] is None and totaux["complet"] is False
    assert totaux["a_payer_connu_apres_taxes"] == "344.93", "114.98 + 229.95"
    assert totaux["facture_apres_taxes"] == "229.95"


def test_les_totaux_comptent_le_facture_et_le_recu_non_facture(taux):
    reg = registre.Registre()
    _recevoir(reg, evenement_id="e1", po_id="PO-1", gouttiere="60", vis="0", horodatage=LIVRAISON_1)
    _recevoir(reg, evenement_id="e2", po_id="PO-2", gouttiere="60", vis="0", horodatage=LIVRAISON_2)
    _facturer_ok(reg, taux, po="PO-1", numero="F-1", montant="300.00")

    totaux = ap.lister(reg, taux, budget_caracteres=GRAND)[0]["totaux"]

    assert totaux["facture_apres_taxes"] == "344.93"
    assert totaux["a_payer_apres_taxes"] == "689.86", "344.93 facturé (PO-1) + 344.93 attendu non facturé (PO-2)"


def test_la_liste_vide_est_un_zero_honnete(taux):
    page, verdict = ap.lister(registre.Registre(), taux, budget_caracteres=GRAND)

    assert verdict is None and page["total"] == 0 and page["comptes"] == []
    assert page["totaux"]["a_payer_apres_taxes"] == "0.00" and page["totaux"]["complet"] is True


def test_les_versions_de_taux_sont_dites_avec_la_liste(taux):
    reg = registre.Registre()
    _recevoir(reg)

    page, _ = ap.lister(reg, taux, budget_caracteres=GRAND)

    assert page["taxes_versions"] == {"tps_federale": "2026-v1", "tvq_quebec": "2026-v1"}


def test_un_taux_manquant_refuse_la_liste_entiere(taux):
    reg = registre.Registre()
    _recevoir(reg)

    page, verdict = ap.lister(reg, {"tps_federale": taux["tps_federale"]}, budget_caracteres=GRAND)

    assert page is None and verdict["code"] == "REJ-TAUX-INCONNU"


def test_toutes_les_valeurs_de_la_page_sont_du_texte_jamais_un_nombre_json(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1", montant="350.00")

    page, _ = ap.lister(reg, taux, budget_caracteres=GRAND, po_id="PO-1")

    def nombres(valeur, chemin=""):
        if isinstance(valeur, bool) or valeur is None or isinstance(valeur, str):
            return []
        if isinstance(valeur, (int, float, Decimal)):
            return [chemin]
        if isinstance(valeur, dict):
            return [n for cle, v in valeur.items() for n in nombres(v, f"{chemin}.{cle}")]
        return [n for i, v in enumerate(valeur) for n in nombres(v, f"{chemin}[{i}]")]

    # seuls des COMPTES (livraisons, factures) sont des entiers ; aucun montant ni aucune quantité
    assert set(nombres(page["comptes"])) == {"[0].receptions", "[0].factures.nombre"}
    json.dumps(page)  # sérialisable tel quel


def test_lire_ne_modifie_aucune_entree_du_registre(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _facturer_ok(reg, taux, numero="F-1", montant="300.00")
    avant = copy.deepcopy(reg.lire())

    ap.lister(reg, taux, budget_caracteres=GRAND)
    ap.lister(reg, taux, budget_caracteres=GRAND, po_id="PO-1")

    assert reg.lire() == avant and reg.valider_chaine() == (True, "")
