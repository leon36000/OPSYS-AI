"""Contrôleur de pré-audit (M5-PRE-AUDIT), noyau pur : dix règles déterministes sur un dossier NORMALISÉ.

Méthode : un dossier PROPRE (zéro constat, toutes les règles évaluées), puis une anomalie injectée à la fois ; le
contrôleur
doit sortir EXACTEMENT cette anomalie, avec sa règle, sa raison, ses sources et une action proposée jamais exécutée. Cas
négatifs (aucune fausse alerte : facture pas encore échue, reçu lié, taxes concordantes), seuils absents (règle non
évaluée,
jamais zéro), grand livre altéré, rejeu du reçu. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import copy
import json

import pytest
from m5_financecore import constat_preaudit, recu_calcul
from m5_financecore import controleur_preaudit as c

FICTIF = True
TYPES = {
    "1010": "actif",
    "1100": "actif",
    "1400": "actif",
    "1410": "actif",
    "2100": "passif",
    "2300": "passif",
    "2310": "passif",
    "4100": "produits",
    "5100": "charges",
    "5300": "charges",
    "5600": "charges",
    "5990": "charges",
}


def lignes(*triplets):
    return c.normaliser_lignes([{"compte": cpt, "debit": d, "credit": cr} for cpt, d, cr in triplets])


def ecriture(
    ident, cle, jour, piece_type, piece_ref, triplets, statut="DEFINITIVE", contre_passe=None, contre_passee_par=None
):
    return {
        "id": ident,
        "statut": statut,
        "date_effet": jour,
        "cle": cle,
        "piece_type": piece_type,
        "piece_ref": piece_ref,
        "nature": "x",
        "contre_passe": contre_passe,
        "contre_passee_par": contre_passee_par,
        "lignes": lignes(*triplets),
    }


VENTE = (("1100", "1149.75", None), ("4100", None, "1000.00"), ("2300", None, "50.00"), ("2310", None, "99.75"))
ACHAT = (("5100", "400.00", None), ("1400", "20.00", None), ("1410", "39.90", None), ("2100", None, "459.90"))
PAIEMENT = (("1010", "1149.75", None), ("1100", None, "1149.75"))


def dossier_propre():
    """F1 payée (émission, paiement) ; F2 émise, échéance le 2026-04-10 (pas encore échue au 2026-03-31) ;
    fournisseurs A1 et A2
    (comptes 5100), chacun avec sa pièce justificative et son écriture. Aucune règle ne doit rien dire."""
    ecritures = [
        ecriture("gle-1", "auto:facture_client:F1:emission", "2026-02-10", "facture_client", "F1", VENTE),
        ecriture("gle-2", "auto:facture_client:F1:paiement", "2026-02-20", "facture_client", "F1", PAIEMENT),
        ecriture("gle-3", "auto:facture_client:F2:emission", "2026-03-10", "facture_client", "F2", VENTE),
        ecriture("gle-4", "auto:facture_fournisseur:A1:saisie", "2026-02-12", "facture_fournisseur", "A1", ACHAT),
        ecriture("gle-5", "auto:facture_fournisseur:A2:saisie", "2026-03-12", "facture_fournisseur", "A2", ACHAT),
    ]
    return {
        "aujourd_hui": "2026-03-31",
        "gl_utilisable": True,
        "anomalies_gl": [],
        "plan": {"banque": "1010", "comptes_clients": "1100", "comptes_fournisseurs": "2100", "types": dict(TYPES)},
        "ecritures": ecritures,
        "factures_clients": [
            {
                "facture_id": "F1",
                "statut": "PAYEE",
                "numero": "F-1001",
                "date_envoi": "2026-02-10",
                "echeance": "2026-03-12",
                "montant_avant_taxes": "1000.00",
                "montant_apres_taxes": "1149.75",
            },
            {
                "facture_id": "F2",
                "statut": "ENVOYEE",
                "numero": "F-1002",
                "date_envoi": "2026-03-10",
                "echeance": "2026-04-10",
                "montant_avant_taxes": "1000.00",
                "montant_apres_taxes": "1149.75",
            },
        ],
        "factures_fournisseurs": [
            {
                "id": "A1",
                "fournisseur_id": "four-1",
                "numero": "N-1",
                "date_facture": "2026-02-12",
                "montant_avant_taxes": "400.00",
                "statut": "SAISIE",
                "compte_charge": "5100",
            },
            {
                "id": "A2",
                "fournisseur_id": "four-1",
                "numero": "N-2",
                "date_facture": "2026-03-12",
                "montant_avant_taxes": "700.00",
                "statut": "SAISIE",
                "compte_charge": "5100",
            },
        ],
        "depenses_employes": [],
        "notes_credit": [],
        "pieces_liees": [["facture_fournisseur", "A1"], ["facture_fournisseur", "A2"]],
        "attendues": [
            {"cle": "auto:facture_client:F1:emission", "lignes": lignes(*VENTE)},
            {"cle": "auto:facture_client:F1:paiement", "lignes": lignes(*PAIEMENT)},
            {"cle": "auto:facture_client:F2:emission", "lignes": lignes(*VENTE)},
            {"cle": "auto:facture_fournisseur:A1:saisie", "lignes": lignes(*ACHAT)},
            {"cle": "auto:facture_fournisseur:A2:saisie", "lignes": lignes(*ACHAT)},
        ],
        "pieces_illisibles": [],
        "taxes": {"disponible": True, "raison": "", "ecarts": [], "illisibles": 0},
        "chaines": [
            {"registre": r, "ok": True, "detail": ""}
            for r in ("grand_livre", "factures", "comptes_a_payer", "operations_comptables", "numerotation_factures")
        ],
        "numerotation": {"ok": True, "defauts": []},
        "seuils": {
            "transaction_hors_norme_cad": "5000.00",
            "jours_fenetre_doublon": 3,
            "historique_changement_compte": 2,
        },
        "seuils_problemes": [],
    }


def controler(dossier):
    return c.controler(copy.deepcopy(dossier))


def ajouter_fournisseur(d, ident, numero, jour, montant="400.00", fournisseur="four-1", compte="5100", recu=True):
    """Une facture fournisseur COMPLÈTE (pièce justificative, écriture automatique et écriture attendue) : seule
    l'anomalie
    voulue la distingue d'une facture saine."""
    d["factures_fournisseurs"].append(facture_fournisseur(ident, numero, jour, montant, fournisseur, compte))
    cle = f"auto:facture_fournisseur:{ident}:saisie"
    d["ecritures"].append(ecriture(f"gle-{ident}", cle, jour, "facture_fournisseur", ident, ACHAT))
    d["attendues"].append({"cle": cle, "lignes": lignes(*ACHAT)})
    if recu:
        d["pieces_liees"].append(["facture_fournisseur", ident])


def regles_avec_constats(rapport):
    return sorted({k.regle if hasattr(k, "regle") else k["regle"] for k in rapport["constats"]})


def un_seul(rapport, regle):
    trouves = [k for k in rapport["constats"] if k["regle"] == regle]
    assert len(trouves) == 1, trouves
    assert regles_avec_constats(rapport) == [regle], rapport["constats"]
    return trouves[0]


# ============================================================================================ le dossier propre
def test_un_dossier_propre_ne_sort_aucune_fausse_alerte_et_toutes_les_regles_sont_evaluees():
    r = controler(dossier_propre())
    assert r["constats"] == [] and r["total"] == 0
    assert [x["etat"] for x in r["regles"]] == ["EVALUEE"] * 10 and all(n == 0 for n in r["par_regle"].values())
    assert [x["regle"] for x in r["regles"]] == list(c.REGLES) and r["par_gravite"] == {
        "haute": 0,
        "moyenne": 0,
        "faible": 0,
    }


def test_le_controle_est_deterministe_et_ne_modifie_pas_le_dossier():
    d = dossier_propre()
    avant = copy.deepcopy(d)
    a, b = c.controler(d), c.controler(d)
    assert d == avant and a["recu"]["empreinte"] == b["recu"]["empreinte"] and a["constats"] == b["constats"]


# =========================================================================================== FACTURE_SANS_PAIEMENT
def test_facture_sans_paiement_apres_l_echeance_stricte_et_pas_le_jour_meme():
    d = dossier_propre()
    d["factures_clients"][1]["echeance"] = "2026-03-30"
    k = un_seul(controler(d), "FACTURE_SANS_PAIEMENT")
    assert k["sources"] == [{"registre": "factures", "reference": "F2"}] and "1 jour(s)" in k["raison"]
    assert k["montant_cad"] == "1149.75" and k["gravite"] == "moyenne" and k["action_executee"] is False
    assert k["outil_suggere"] == "m5_preparer_relances_clients" and "relance" in k["action_proposee"]
    d["factures_clients"][1]["echeance"] = "2026-03-31"  # le jour même : pas encore en retard
    assert controler(d)["constats"] == []


def test_facture_payee_ou_brouillon_n_est_jamais_sans_paiement_et_sans_echeance_la_regle_est_partielle():
    d = dossier_propre()
    d["factures_clients"][0]["echeance"] = "2020-01-01"  # F1 est payée
    d["factures_clients"].append(
        {
            "facture_id": "F3",
            "statut": "BROUILLON",
            "numero": None,
            "date_envoi": None,
            "echeance": "2020-01-01",
            "montant_avant_taxes": "1.00",
            "montant_apres_taxes": "1.00",
        }
    )
    assert controler(d)["constats"] == []
    d["factures_clients"][1]["echeance"] = None
    r = controler(d)
    regle = next(x for x in r["regles"] if x["regle"] == "FACTURE_SANS_PAIEMENT")
    assert r["constats"] == [] and regle["etat"] == "PARTIELLE" and "sans échéance lisible" in regle["manque"][0]
    assert (
        r["par_regle"]["FACTURE_SANS_PAIEMENT"] == 0
        and "FACTURE_SANS_PAIEMENT" in r["recu"]["resultat"]["regles_partielles"]
    )


# =========================================================================================== PAIEMENT_SANS_FACTURE
def test_encaissement_client_sans_facture_derriere():
    d = dossier_propre()
    d["ecritures"].append(ecriture("gle-9", "saisie:recu:R1", "2026-03-05", "releve_bancaire", "R-1", PAIEMENT))
    k = un_seul(controler(d), "PAIEMENT_SANS_FACTURE")
    assert k["sources"] == [{"registre": "grand_livre", "reference": "gle-9"}] and k["gravite"] == "haute"
    assert k["montant_cad"] == "1149.75" and "encaisse" in k["raison"]


def test_paiement_d_une_facture_qui_n_est_pas_payee_ou_inconnue_est_signale():
    d = dossier_propre()
    d["ecritures"].append(
        ecriture("gle-9", "auto:facture_client:F2:paiement", "2026-03-20", "facture_client", "F2", PAIEMENT)
    )
    k = un_seul(controler(d), "PAIEMENT_SANS_FACTURE")
    assert "facture_client:F2" in k["raison"]
    d = dossier_propre()
    d["ecritures"].append(
        ecriture("gle-9", "auto:facture_client:F9:paiement", "2026-03-20", "facture_client", "F9", PAIEMENT)
    )
    d["factures_clients"] = d["factures_clients"][:2]
    assert len([x for x in controler(d)["constats"] if x["regle"] == "PAIEMENT_SANS_FACTURE"]) == 1


def test_decaissement_fournisseur_sans_facture_vivante():
    d = dossier_propre()
    reglement = (("2100", "459.90", None), ("1010", None, "459.90"))
    d["ecritures"].append(ecriture("gle-9", "saisie:manuelle:P1", "2026-03-15", "manuelle", "P-1", reglement))
    d["pieces_liees"].append(["ecriture", "gle-9"])
    k = un_seul(controler(d), "PAIEMENT_SANS_FACTURE")
    assert "fournisseurs" in k["raison"] and k["montant_cad"] == "459.90"
    d = dossier_propre()  # un règlement visant une facture fournisseur vivante est normal
    d["ecritures"].append(
        ecriture("gle-9", "saisie:fournisseur:P1", "2026-03-15", "facture_fournisseur", "A1", reglement)
    )
    assert controler(d)["constats"] == []
    d["factures_fournisseurs"][0]["statut"] = "ANNULEE"  # annulée : plus de dette derrière
    assert len([x for x in controler(d)["constats"] if x["regle"] == "PAIEMENT_SANS_FACTURE"]) == 1


def test_une_contre_passation_de_paiement_n_est_pas_un_paiement_sans_facture():
    d = dossier_propre()
    d["ecritures"].append(
        ecriture(
            "gle-9",
            "contre:gle-2",
            "2026-03-21",
            "facture_client",
            "F1",
            (("1100", "1149.75", None), ("1010", None, "1149.75")),
            contre_passe="gle-2",
        )
    )
    d["ecritures"][1]["contre_passee_par"] = "gle-9"
    assert controler(d)["constats"] == []


# ============================================================================================ DEPENSE_SANS_RECU
def test_facture_fournisseur_sans_piece_justificative():
    d = dossier_propre()
    d["pieces_liees"] = [["facture_fournisseur", "A1"]]
    k = un_seul(controler(d), "DEPENSE_SANS_RECU")
    assert k["sources"] == [{"registre": "comptes_a_payer", "reference": "A2"}] and k["montant_cad"] == "700.00"
    assert k["outil_suggere"] == "m5_lier_piece_justificative" and "N-2" in k["raison"]


def test_une_piece_liee_a_une_autre_cible_ne_justifie_pas_la_depense():
    d = dossier_propre()
    d["pieces_liees"] = [["facture_fournisseur", "A1"], ["ecriture", "A2"], ["facture_client", "A2"]]
    assert un_seul(controler(d), "DEPENSE_SANS_RECU")["sources"][0]["reference"] == "A2"


def test_depense_d_employe_et_ecriture_de_charge_manuelle_sans_recu():
    d = dossier_propre()
    d["depenses_employes"] = [{"id": "dep-1", "date": "2026-03-02", "montant": "35.00"}]
    d["ecritures"].append(
        ecriture(
            "gle-8", "saisie:recu:Z", "2026-03-03", "recu", "Z-1", (("5990", "25.00", None), ("1010", None, "25.00"))
        )
    )
    r = controler(d)
    assert sorted(k["sources"][0]["reference"] for k in r["constats"]) == ["dep-1", "gle-8"]
    assert regles_avec_constats(r) == ["DEPENSE_SANS_RECU"]
    d["pieces_liees"] += [["depense_employe", "dep-1"], ["ecriture", "gle-8"]]
    assert controler(d)["constats"] == []


def test_une_facture_fournisseur_annulee_n_a_plus_besoin_de_recu():
    d = dossier_propre()
    d["pieces_liees"] = [["facture_fournisseur", "A1"]]
    d["factures_fournisseurs"][1]["statut"] = "ANNULEE"
    assert [k for k in controler(d)["constats"] if k["regle"] == "DEPENSE_SANS_RECU"] == []


# ============================================================================================ TAXE_INCOHERENTE
def test_taxe_incoherente_vient_du_rapprochement_au_moteur_fiscal_versionne():
    d = dossier_propre()
    d["taxes"]["ecarts"] = [
        {
            "cote": "clients",
            "role": "tps_a_percevoir",
            "reference": "F2",
            "raison": "montant différent",
            "attendu": "50.00",
            "au_grand_livre": "75.00",
        },
        {
            "cote": "clients",
            "role": "tvq_a_percevoir",
            "reference": "F2",
            "raison": "montant différent",
            "attendu": "99.75",
            "au_grand_livre": "0.00",
        },
    ]
    k = un_seul(controler(d), "TAXE_INCOHERENTE")
    assert (
        k["sources"] == [{"registre": "factures", "reference": "F2"}]
        and "attendu 50.00, au grand livre 75.00" in k["raison"]
    )
    assert "tps_a_percevoir" in k["raison"] and "tvq_a_percevoir" in k["raison"] and k["gravite"] == "haute"


def test_taxe_sur_intrants_et_ecriture_non_rattachee():
    d = dossier_propre()
    d["taxes"]["ecarts"] = [
        {
            "cote": "intrants",
            "role": "tps_cti",
            "reference": "A1",
            "raison": "sans écriture définitive",
            "attendu": "20.00",
            "au_grand_livre": "0.00",
        },
        {
            "cote": "clients",
            "role": "tps_a_percevoir",
            "reference": None,
            "raison": "mouvement d'une écriture non rattachée",
            "au_grand_livre": "12.00",
        },
    ]
    r = controler(d)
    assert len([k for k in r["constats"] if k["regle"] == "TAXE_INCOHERENTE"]) == 2
    assert {k["sources"][0]["reference"] for k in r["constats"]} == {"A1", "ecritures-non-rattachees"}


def test_une_piece_sans_ecriture_definitive_n_a_pas_de_taxe_incoherente_elle_n_a_pas_d_ecriture():
    d = dossier_propre()
    d["taxes"]["ecarts"] = [
        {
            "cote": "intrants",
            "role": "tps_cti",
            "reference": "A2",
            "raison": "sans écriture définitive",
            "attendu": "20.00",
            "au_grand_livre": "0.00",
            "sans_ecriture": True,
        },
        {
            "cote": "clients",
            "role": "tps_a_percevoir",
            "reference": "F2",
            "raison": "montant différent",
            "attendu": "50.00",
            "au_grand_livre": "75.00",
            "sans_ecriture": False,
        },
    ]
    k = un_seul(controler(d), "TAXE_INCOHERENTE")
    assert k["sources"] == [{"registre": "factures", "reference": "F2"}] and "A2" not in k["raison"]


def test_taxes_non_comparables_la_regle_est_non_evaluee_et_dit_pourquoi():
    d = dossier_propre()
    d["taxes"] = {
        "disponible": False,
        "raison": "taux fiscaux illisibles (REJ-TAUX-FICHIER-INVALIDE)",
        "ecarts": [],
        "illisibles": 0,
    }
    r = controler(d)
    regle = next(x for x in r["regles"] if x["regle"] == "TAXE_INCOHERENTE")
    assert (
        regle["etat"] == "NON_EVALUEE"
        and r["par_regle"]["TAXE_INCOHERENTE"] is None
        and "illisibles" in regle["manque"][0]
    )


def test_des_pieces_aux_taxes_illisibles_rendent_la_regle_partielle():
    d = dossier_propre()
    d["taxes"]["illisibles"] = 2
    regle = next(x for x in controler(d)["regles"] if x["regle"] == "TAXE_INCOHERENTE")
    assert regle["etat"] == "PARTIELLE" and "2 pièce(s)" in regle["manque"][0]


# ============================================================================================ DOUBLON_PROBABLE
def facture_fournisseur(ident, numero, jour, montant="400.00", fournisseur="four-1", compte="5100"):
    return {
        "id": ident,
        "fournisseur_id": fournisseur,
        "numero": numero,
        "date_facture": jour,
        "montant_avant_taxes": montant,
        "statut": "SAISIE",
        "compte_charge": compte,
    }


def test_doublon_meme_fournisseur_meme_montant_a_moins_de_la_fenetre():
    d = dossier_propre()
    ajouter_fournisseur(d, "A3", "N-1B", "2026-02-14")  # A1 : 400,00 le 02-12, deux jours plus tôt
    k = un_seul(controler(d), "DOUBLON_PROBABLE")
    assert (
        {s["reference"] for s in k["sources"]} == {"A1", "A3"}
        and k["montant_cad"] == "400.00"
        and k["gravite"] == "haute"
    )
    assert "N-1" in k["raison"] and "N-1B" in k["raison"]


def test_doublon_hors_fenetre_autre_montant_autre_fournisseur_ne_sont_pas_des_doublons():
    d = dossier_propre()
    ajouter_fournisseur(d, "A3", "N-3", "2026-02-16")  # 4 jours : hors fenêtre de 3
    ajouter_fournisseur(d, "A4", "N-4", "2026-02-12", montant="400.01")
    ajouter_fournisseur(d, "A5", "N-5", "2026-02-12", fournisseur="four-2")
    assert [k for k in controler(d)["constats"] if k["regle"] == "DOUBLON_PROBABLE"] == []


def test_la_fenetre_est_exacte_trois_jours_pile_est_un_doublon_quatre_non():
    for ecart, attendu in ((3, 1), (4, 0)):
        d = dossier_propre()
        ajouter_fournisseur(d, "A3", "N-3", f"2026-02-{12 + ecart}")
        assert len([k for k in controler(d)["constats"] if k["regle"] == "DOUBLON_PROBABLE"]) == attendu


def test_fenetre_non_declaree_seul_le_meme_jour_est_evalue_la_regle_est_partielle_et_le_dit():
    d = dossier_propre()
    d["seuils"]["jours_fenetre_doublon"] = None
    ajouter_fournisseur(d, "A3", "N-3", "2026-02-13")
    r = controler(d)
    regle = next(x for x in r["regles"] if x["regle"] == "DOUBLON_PROBABLE")
    assert r["constats"] == [] and regle["etat"] == "PARTIELLE" and "MÊME date" in regle["manque"][0]
    d["factures_fournisseurs"][-1]["date_facture"] = "2026-02-12"
    d["ecritures"][-1]["date_effet"] = "2026-02-12"
    assert len([k for k in controler(d)["constats"] if k["regle"] == "DOUBLON_PROBABLE"]) == 1


def test_une_facture_fournisseur_annulee_n_est_pas_un_doublon():
    d = dossier_propre()
    ajouter_fournisseur(d, "A3", "N-3", "2026-02-12")
    d["factures_fournisseurs"][-1]["statut"] = "ANNULEE"
    d["ecritures"][-1]["contre_passee_par"] = "gle-contre"
    assert controler(d)["constats"] == []


def test_ecritures_manuelles_identiques_le_meme_jour_sont_un_doublon_mais_pas_les_ecritures_automatiques():
    d = dossier_propre()
    frais = (("5990", "25.00", None), ("1010", None, "25.00"))
    d["ecritures"] += [
        ecriture("gle-7", "saisie:manuelle:1", "2026-03-04", "manuelle", "M-1", frais),
        ecriture("gle-8", "saisie:manuelle:2", "2026-03-04", "manuelle", "M-2", frais),
    ]
    d["pieces_liees"] += [["ecriture", "gle-7"], ["ecriture", "gle-8"]]
    k = un_seul(controler(d), "DOUBLON_PROBABLE")
    assert {s["reference"] for s in k["sources"]} == {"gle-7", "gle-8"}
    d["ecritures"][-1]["date_effet"] = "2026-03-05"
    assert controler(d)["constats"] == []


# ======================================================================================== TRANSACTION_HORS_NORME
def test_transaction_hors_norme_au_seuil_declare_inclusif_et_une_fois_par_piece():
    d = dossier_propre()
    d["seuils"]["transaction_hors_norme_cad"] = "1149.75"
    r = controler(d)
    ks = [k for k in r["constats"] if k["regle"] == "TRANSACTION_HORS_NORME"]
    # la pièce F1 (émission + paiement, 1 149,75 chacune) = UN constat ; F2 (émission) = un autre
    assert (
        sorted(tuple(s_["reference"] for s_ in k["sources"]) for k in ks) == [("gle-1", "gle-2"), ("gle-3",)]
        and len(ks) == 2
    )
    assert all(k["gravite"] == "faible" and k["montant_cad"] == "1149.75" for k in ks)
    d["seuils"]["transaction_hors_norme_cad"] = "1149.76"
    assert [k for k in controler(d)["constats"] if k["regle"] == "TRANSACTION_HORS_NORME"] == []


def test_sans_seuil_declare_la_regle_est_non_evaluee_jamais_zero_et_dit_quoi_declarer():
    d = dossier_propre()
    d["seuils"]["transaction_hors_norme_cad"] = None
    d["ecritures"].append(
        ecriture(
            "gle-9",
            "saisie:manuelle:G",
            "2026-03-04",
            "manuelle",
            "G-1",
            (("5600", "9999999.00", None), ("1010", None, "9999999.00")),
        )
    )
    d["pieces_liees"].append(["ecriture", "gle-9"])
    r = controler(d)
    regle = next(x for x in r["regles"] if x["regle"] == "TRANSACTION_HORS_NORME")
    assert regle["etat"] == "NON_EVALUEE" and r["par_regle"]["TRANSACTION_HORS_NORME"] is None
    assert "m5.seuil_transaction_hors_norme_cad" in regle["manque"][0] and r["total"] == 0
    assert "TRANSACTION_HORS_NORME" in r["recu"]["resultat"]["regles_non_evaluees"]


def test_les_contre_passations_ne_sont_pas_des_transactions_hors_norme():
    d = dossier_propre()
    d["seuils"]["transaction_hors_norme_cad"] = "1000.00"
    d["ecritures"] = [e for e in d["ecritures"] if e["id"] in ("gle-4", "gle-5")]
    d["ecritures"][0]["contre_passe"] = "gle-x"
    d["ecritures"][1]["contre_passe"] = "gle-y"
    assert [k for k in controler(d)["constats"] if k["regle"] == "TRANSACTION_HORS_NORME"] == []


# ============================================================================================ FACTURE_MODIFIEE
def test_facture_fournisseur_corrigee_apres_comptabilisation():
    d = dossier_propre()
    d["factures_fournisseurs"][1].update(statut="CORRIGEE", montant_avant_taxes="650.00")
    corrigee = (("5100", "650.00", None), ("1400", "32.50", None), ("1410", "64.84", None), ("2100", None, "747.34"))
    d["attendues"][4] = {"cle": "auto:facture_fournisseur:A2:saisie", "lignes": lignes(*corrigee)}
    k = un_seul(controler(d), "FACTURE_MODIFIEE")
    assert (
        {s["reference"] for s in k["sources"]} == {"A2", "gle-5"}
        and "corrigée" in k["raison"]
        and k["gravite"] == "haute"
    )


def test_facture_corrigee_dont_l_ecriture_correspond_deja_n_est_pas_signalee():
    d = dossier_propre()
    d["factures_fournisseurs"][1]["statut"] = "CORRIGEE"
    assert controler(d)["constats"] == []


def test_facture_annulee_dont_l_ecriture_n_est_pas_contre_passee_est_signalee_sinon_non():
    d = dossier_propre()
    d["factures_fournisseurs"][1]["statut"] = "ANNULEE"
    d["pieces_liees"] = [["facture_fournisseur", "A1"]]
    k = un_seul(controler(d), "FACTURE_MODIFIEE")
    assert "annulée" in k["raison"]
    d["ecritures"][4]["contre_passee_par"] = "gle-10"
    assert controler(d)["constats"] == []


def test_ecriture_client_qui_ne_correspond_plus_a_la_facture_courante():
    d = dossier_propre()
    d["attendues"][2] = {
        "cle": "auto:facture_client:F2:emission",
        "lignes": lignes(
            ("1100", "1264.73", None), ("4100", None, "1100.00"), ("2300", None, "55.00"), ("2310", None, "109.73")
        ),
    }
    k = un_seul(controler(d), "FACTURE_MODIFIEE")
    assert {s["reference"] for s in k["sources"]} == {"F2", "gle-3"} and "F-1002" in k["raison"]


# ================================================================================= CHANGEMENT_COMPTE_INHABITUEL
def test_un_fournisseur_dont_les_deux_dernieres_factures_allaient_au_meme_compte_change_de_compte():
    d = dossier_propre()
    ajouter_fournisseur(d, "A3", "N-3", "2026-03-20", montant="90.00", compte="5990")
    k = un_seul(controler(d), "CHANGEMENT_COMPTE_INHABITUEL")
    assert (
        k["sources"] == [{"registre": "comptes_a_payer", "reference": "A3"}]
        and "5990" in k["raison"]
        and "5100" in k["raison"]
    )


def test_historique_trop_court_ou_deja_varie_ou_compte_inconnu_ne_declenche_rien():
    d = dossier_propre()
    ajouter_fournisseur(d, "A3", "N-3", "2026-03-20", montant="90.00", compte="5990")
    d["seuils"]["historique_changement_compte"] = 3  # deux factures de suite seulement : pas assez d'historique
    assert controler(d)["constats"] == []
    d["seuils"]["historique_changement_compte"] = 2
    d["factures_fournisseurs"][0]["compte_charge"] = "5600"  # l'historique n'était pas constant
    assert controler(d)["constats"] == []
    d["factures_fournisseurs"][0]["compte_charge"] = "5100"
    d["factures_fournisseurs"][2]["compte_charge"] = None  # compte de la facture inconnu : jamais deviné
    assert controler(d)["constats"] == []


def test_sans_historique_declare_la_regle_est_non_evaluee():
    d = dossier_propre()
    d["seuils"]["historique_changement_compte"] = None
    regle = next(x for x in controler(d)["regles"] if x["regle"] == "CHANGEMENT_COMPTE_INHABITUEL")
    assert (
        regle["etat"] == "NON_EVALUEE"
        and regle["constats"] is None
        and "m5.historique_changement_compte" in regle["manque"][0]
    )


# ========================================================================================== PISTE_AUDIT_INCOMPLETE
def test_chaine_alteree_numero_manquant_et_anomalie_du_grand_livre():
    d = dossier_propre()
    d["chaines"][2] = {"registre": "comptes_a_payer", "ok": False, "detail": "maillon invalide : x"}
    d["numerotation"] = {"ok": False, "defauts": ["trou dans la suite : 1002"]}
    r = controler(d)
    assert regles_avec_constats(r) == ["PISTE_AUDIT_INCOMPLETE"] and len(r["constats"]) == 2
    assert {k["sources"][0]["registre"] for k in r["constats"]} == {"comptes_a_payer", "numerotation_factures"}
    assert all(k["gravite"] == "haute" for k in r["constats"])


def test_grand_livre_altere_rend_non_evaluees_les_regles_qui_en_dependent_jamais_aucun_constat():
    d = dossier_propre()
    d.update(gl_utilisable=False, anomalies_gl=["écriture gle-1 : contenu altéré ou déséquilibré"], ecritures=[])
    d["chaines"][0] = {"registre": "grand_livre", "ok": False, "detail": "x"}
    r = controler(d)
    non_evaluees = {x["regle"] for x in r["regles"] if x["etat"] == "NON_EVALUEE"}
    assert non_evaluees == {
        "PAIEMENT_SANS_FACTURE",
        "TAXE_INCOHERENTE",
        "TRANSACTION_HORS_NORME",
        "FACTURE_MODIFIEE",
        "DOCUMENT_MANQUANT",
    }
    assert all(r["par_regle"][n] is None for n in non_evaluees)
    assert [k["regle"] for k in r["constats"]] == ["PISTE_AUDIT_INCOMPLETE"] * 2  # la chaîne ET l'anomalie
    assert r["total"] == 2  # la somme des seules règles évaluées


# ============================================================================================== DOCUMENT_MANQUANT
def test_facture_emise_et_paiement_sans_ecriture_ni_brouillon():
    d = dossier_propre()
    d["ecritures"] = [e for e in d["ecritures"] if e["id"] not in ("gle-2", "gle-3")]
    r = controler(d)
    assert regles_avec_constats(r) == ["DOCUMENT_MANQUANT"] and len(r["constats"]) == 2
    assert {k["sources"][0]["reference"] for k in r["constats"]} == {"F1", "F2"}
    assert any("paiement" in k["raison"] for k in r["constats"])


def test_facture_fournisseur_sans_ecriture_et_ecriture_dont_la_piece_est_introuvable():
    d = dossier_propre()
    d["ecritures"] = [e for e in d["ecritures"] if e["id"] != "gle-5"]
    assert un_seul(controler(d), "DOCUMENT_MANQUANT")["sources"] == [{"registre": "comptes_a_payer", "reference": "A2"}]
    d = dossier_propre()
    d["ecritures"].append(
        ecriture("gle-9", "auto:facture_client:F7:emission", "2026-03-01", "facture_client", "F7", VENTE)
    )
    k = [x for x in controler(d)["constats"] if x["regle"] == "DOCUMENT_MANQUANT"]
    assert len(k) == 1 and "facture_client:F7" in k[0]["raison"]


def test_une_piece_declaree_non_verifiee_n_est_pas_un_document_manquant():
    d = dossier_propre()
    d["ecritures"].append(
        ecriture(
            "gle-9",
            "saisie:manuelle:Q",
            "2026-03-01",
            "manuelle",
            "Q-1",
            (("5990", "3.00", None), ("1010", None, "3.00")),
        )
    )
    d["pieces_liees"].append(["ecriture", "gle-9"])
    assert controler(d)["constats"] == []


def test_une_piece_illisible_pour_la_comptabilite_est_un_document_manquant_qui_garde_son_code():
    d = dossier_propre()
    d["pieces_illisibles"] = [{"registre": "factures", "reference": "F5", "code": "REJ-GL-SOURCE-ILLISIBLE"}]
    k = un_seul(controler(d), "DOCUMENT_MANQUANT")
    assert "REJ-GL-SOURCE-ILLISIBLE" in k["raison"] and k["sources"] == [{"registre": "factures", "reference": "F5"}]


# ===================================================================================== le scénario des trois anomalies
def test_trois_anomalies_injectees_sortent_exactement_sans_fausse_alerte():
    d = dossier_propre()
    d["factures_clients"][1]["echeance"] = "2026-03-15"  # (1) une facture sans paiement
    d["pieces_liees"] = [["facture_fournisseur", "A1"]]  # (2) une dépense sans reçu (A2)
    ajouter_fournisseur(d, "A3", "N-1B", "2026-02-12")  # (3) un doublon d'A1
    r = controler(d)
    assert [(k["regle"], tuple(s["reference"] for s in k["sources"])) for k in r["constats"]] == [
        ("DOUBLON_PROBABLE", ("A1", "A3")),
        ("FACTURE_SANS_PAIEMENT", ("F2",)),
        ("DEPENSE_SANS_RECU", ("A2",)),
    ]
    assert r["total"] == 3 and r["par_gravite"] == {"haute": 1, "moyenne": 2, "faible": 0}
    assert sum(r["par_regle"].values()) == 3 and len({k["cle"] for k in r["constats"]}) == 3


def test_les_cles_de_constat_sont_stables_et_independantes_de_l_ordre_des_sources():
    d = dossier_propre()
    d["pieces_liees"] = []
    cles = [k["cle"] for k in controler(d)["constats"]]
    d["factures_fournisseurs"].reverse()
    assert [k["cle"] for k in controler(d)["constats"]] == cles and all(k.startswith("pa-") for k in cles)


# ============================================================================================ seuils et reçu
def test_seuils_lus_de_la_couche_de_reglages_bornes_et_jamais_devines():
    assert c.seuils_depuis({}) == (
        {"transaction_hors_norme_cad": None, "jours_fenetre_doublon": None, "historique_changement_compte": None},
        [],
    )
    s, p = c.seuils_depuis(
        {"seuil_transaction_hors_norme_cad": "5000", "jours_fenetre_doublon": 7, "historique_changement_compte": 3}
    )
    assert (
        s == {"transaction_hors_norme_cad": "5000.00", "jours_fenetre_doublon": 7, "historique_changement_compte": 3}
        and p == []
    )
    for mauvais in (
        {"seuil_transaction_hors_norme_cad": "-1"},
        {"seuil_transaction_hors_norme_cad": "abc"},
        {"seuil_transaction_hors_norme_cad": 0},
        {"seuil_transaction_hors_norme_cad": True},
        {"jours_fenetre_doublon": 0},
        {"jours_fenetre_doublon": 367},
        {"jours_fenetre_doublon": "3"},
        {"jours_fenetre_doublon": True},
        {"historique_changement_compte": 51},
        {"historique_changement_compte": 2.5},
    ):
        s, p = c.seuils_depuis(mauvais)
        assert p and all(v is None for v in s.values()), (
            mauvais
        )  # un seuil mal formé est nommé et la règle reste non évaluée


def test_le_recu_du_controle_se_rejoue_et_une_retouche_est_refusee():
    d = dossier_propre()
    d["pieces_liees"] = []
    r = controler(d)
    recu = json.loads(json.dumps(r["recu"], ensure_ascii=False))
    assert recu_calcul.verifier(recu) == (True, "") and c.rejouer(recu) == (True, "")
    retouche = copy.deepcopy(recu)
    retouche["entrees"]["dossier"]["pieces_liees"] = [["facture_fournisseur", "A1"], ["facture_fournisseur", "A2"]]
    assert c.rejouer(retouche)[0] is False
    retouche = copy.deepcopy(recu)
    retouche["resultat"]["total"] = 0
    assert c.rejouer(retouche)[0] is False
    assert c.rejouer(recu_calcul.compacter(recu))[0] is False


def test_le_dossier_et_les_constats_ne_portent_que_des_types_json():
    d = dossier_propre()
    d["pieces_liees"] = []
    json.dumps(controler(d), ensure_ascii=False, default=lambda o: pytest.fail(f"type non JSON {type(o)}"))


# ================================================================================================ le constat pour M8
def test_la_charge_de_l_evenement_ne_porte_que_des_comptes():
    d = dossier_propre()
    d["pieces_liees"] = []
    d["seuils"]["transaction_hors_norme_cad"] = None
    charge = constat_preaudit.charge_preaudit(controler(d), "2026-03-31", "2026-03-31T12:00:00-04:00")
    assert (
        charge["constats_par_regle"]["DEPENSE_SANS_RECU"] == 2
        and charge["constats_par_regle"]["TRANSACTION_HORS_NORME"] is None
    )
    assert charge["constats_total"] == 2 and charge["constats_par_gravite"] == {"haute": 0, "moyenne": 2, "faible": 0}
    assert charge["regles_non_evaluees"] == ["TRANSACTION_HORS_NORME"] and charge["regles_partielles"] == []
    texte = json.dumps(charge, ensure_ascii=False)
    for interdit in ("A1", "A2", "F1", "four-1", "N-1", "gle-", "1149", "400.00", "raison"):
        assert interdit not in texte, interdit


def test_aucune_regle_evaluee_donne_un_total_nul_jamais_zero():
    d = dossier_propre()
    d.update(gl_utilisable=False, ecritures=[])
    d["seuils"] = {
        "transaction_hors_norme_cad": None,
        "jours_fenetre_doublon": None,
        "historique_changement_compte": None,
    }
    d["factures_clients"], d["factures_fournisseurs"], d["chaines"], d["numerotation"] = [], [], [], None
    r = controler(d)
    assert [x for x in r["regles"] if x["etat"] != "NON_EVALUEE"]  # d'autres règles restent évaluées (vides)
    charge = constat_preaudit.charge_preaudit(r, "2026-03-31", "2026-03-31T12:00:00-04:00")
    assert charge["constats_total"] == 0
    r["par_regle"] = {k: None for k in r["par_regle"]}
    assert constat_preaudit.charge_preaudit(r, "2026-03-31", "2026-03-31T12:00:00-04:00")["constats_total"] is None


def test_l_identifiant_depend_de_l_instant_et_la_version_seulement_des_donnees():
    d = dossier_propre()
    a = constat_preaudit.charge_preaudit(controler(d), "2026-03-31", "2026-03-31T12:00:00-04:00")
    b = constat_preaudit.charge_preaudit(controler(d), "2026-03-31", "2026-03-31T12:00:00-04:00")
    autre_instant = constat_preaudit.charge_preaudit(controler(d), "2026-03-31", "2026-03-31T18:00:00-04:00")
    assert (
        a == b
        and a["version_donnees"] == autre_instant["version_donnees"]
        and a["evenement_id"] != autre_instant["evenement_id"]
    )
    d["pieces_liees"] = []
    autre_donnee = constat_preaudit.charge_preaudit(controler(d), "2026-03-31", "2026-03-31T12:00:00-04:00")
    assert autre_donnee["version_donnees"] != a["version_donnees"]
