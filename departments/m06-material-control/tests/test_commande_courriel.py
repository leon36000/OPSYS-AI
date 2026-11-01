"""M6.6 : règles pures de la commande par courriel via M1. Rapprochement par identifiant exact, jamais flou."""

from __future__ import annotations

import copy

import pytest
from m6_material_control import bons_commande
from m6_material_control import commande_courriel as cc

FOURNISSEUR = {
    "fournisseur_id": "f-1",
    "nom": "Matériaux Fictifs",
    "courriel_commande": "Commandes@Fournisseur.example.test",
}
AUTRE = {"fournisseur_id": "f-2", "nom": "Autre", "courriel_commande": "ventes@autre.example.test"}
EMPREINTE = cc.empreinte_expediteur("commandes@fournisseur.example.test")


def _charge(**modif):
    base = {
        "signal_id": "courriel:abc",
        "compte_id": "c1",
        "classe": "commande_materiaux",
        "confiance": "0.80",
        "aiguillage": "m06",
        "revue_humaine": False,
        "motifs_revue": [],
        "regles": ["cm-commander"],
        "version_regles": "v1",
        "canari": False,
        "nb_pieces": 0,
        "recu_le": "2026-11-02T10:00:00-05:00",
        "jetons_reference": [],
        "references_po": [],
        "lignes": [],
        "etat_annonce": [],
        "dates_annoncees": [],
        "expediteur_empreinte": "0" * 64,
        "authentification_complete": True,
    }
    return {**base, **modif}


BESOINS = [
    {
        "devis_id": "D-1",
        "chantier_id": "CH-1",
        "lignes": [
            {"materiau_id": "ciment", "quantite_estimee": 20.0, "unite": "sacs"},
            {"materiau_id": "blocs", "quantite_estimee": 6.0, "unite": "palettes"},
        ],
    }
]
WCT = [{"wct_id": "W-1", "devis_id": "D-1", "horodatage_completion": "2026-11-01T10:00:00-05:00"}]
BONS = [{"po_id": "PO-2026-014", "fournisseur_id": "f-1", "statut": "sent_to_supplier"}]


def test_l_empreinte_ne_depend_ni_de_la_casse_ni_des_blancs():
    assert cc.empreinte_expediteur(" X@Y.example.test ") == cc.empreinte_expediteur("x@y.example.test")


def test_le_fournisseur_se_reconnait_par_l_empreinte_de_sa_boite_de_commande():
    assert cc.identifier_fournisseur(EMPREINTE, [FOURNISSEUR, AUTRE]) == "f-1"
    assert cc.identifier_fournisseur("1" * 64, [FOURNISSEUR, AUTRE]) is None
    double = [FOURNISSEUR, {**AUTRE, "courriel_commande": FOURNISSEUR["courriel_commande"]}]
    assert cc.identifier_fournisseur(EMPREINTE, double) is None, "ambigu : jamais deviné"
    assert cc.identifier_fournisseur(EMPREINTE, [{"fournisseur_id": "f-3", "courriel_commande": None}]) is None


def test_rapprochement_par_devis_cite_prevu_demande_et_wct():
    r = cc.rapprocher(
        _charge(
            jetons_reference=["D-1"],
            lignes=[
                {"designation": "ciment", "quantite": "25", "unite": "sacs"},
                {"designation": "blocs", "quantite": "6", "unite": "palettes"},
                {"designation": "tuyaux", "quantite": "3", "unite": None},
            ],
        ),
        BESOINS,
        WCT,
        BONS,
    )
    assert r["devis"] == ["D-1"] and not r["sans_rapprochement"]
    par = {lg["designation"]: lg for lg in r["lignes"]}
    assert par["ciment"]["ecart_a_prevu"] == "au_dessus_du_prevu" and par["ciment"]["quantite_prevue"] == "20.0"
    assert par["blocs"]["ecart_a_prevu"] == "egal_au_prevu"
    assert par["tuyaux"]["materiau_id"] is None and par["tuyaux"]["ecart_a_prevu"] == "inconnu"
    assert r["wct"] == [{"wct_id": "W-1", "horodatage_completion": "2026-11-01T10:00:00-05:00"}]


def test_un_chantier_cite_donne_son_devis_seulement_s_il_est_unique():
    assert cc.rapprocher(_charge(jetons_reference=["CH-1"]), BESOINS, [], [])["devis"] == ["D-1"]
    deux = BESOINS + [{"devis_id": "D-2", "chantier_id": "CH-1", "lignes": []}]
    assert cc.rapprocher(_charge(jetons_reference=["CH-1"]), deux, [], [])["devis"] == []


def test_aucun_rapprochement_par_ressemblance_ni_identifiant_inconnu():
    r = cc.rapprocher(
        _charge(jetons_reference=["D-9"], lignes=[{"designation": "Ciment gris", "quantite": "5", "unite": "sacs"}]),
        BESOINS,
        WCT,
        BONS,
    )
    assert r["sans_rapprochement"] and r["devis"] == [] and r["wct"] == []
    assert r["lignes"][0]["materiau_id"] is None


def test_unite_differente_et_casse_des_identifiants():
    r = cc.rapprocher(
        _charge(jetons_reference=["d-1"], lignes=[{"designation": "ciment", "quantite": "20", "unite": "palettes"}]),
        BESOINS,
        [],
        [],
    )
    assert r["devis"] == ["D-1"] and r["lignes"][0]["ecart_a_prevu"] == "unite_differente"


def test_le_maillon_de_commande_porte_la_provenance_et_aucun_texte():
    c = _charge(jetons_reference=["D-1"])
    r = cc.rapprocher(c, BESOINS, WCT, BONS)
    m = cc.maillon_commande(c, "f-1", r)
    assert m["statut"] == "a_traiter" and m["commande_id"] == cc.identifiant_commande("courriel:abc")
    assert m["provenance"]["classe"] == "commande_materiaux" and m["provenance"]["version_regles"] == "v1"
    assert m["suggestion"]["outil"] == "m6_creer_po_brouillon" and m["suggestion"]["devis_id"] == "D-1"
    assert cc.suggestion({"devis": []})["outil"] is None


def _conf(**modif):
    base = {
        "classe": "confirmation_fournisseur",
        "references_po": ["PO-2026-014"],
        "jetons_reference": ["PO-2026-014"],
        "etat_annonce": ["confirmee"],
        "dates_annoncees": ["2026-11-12"],
        "expediteur_empreinte": EMPREINTE,
    }
    return _charge(**{**base, **modif})


def test_une_confirmation_n_est_appliquee_que_si_tout_tient():
    e = cc.evaluer_confirmation(_conf(), BONS, [FOURNISSEUR])
    assert e["decision"] == "appliquer" and e["po_id"] == "PO-2026-014" and e["raisons"] == []


@pytest.mark.parametrize(
    "modif,bons,fiches,raison",
    [
        ({"authentification_complete": False}, BONS, [FOURNISSEUR], "authentification_incomplete"),
        ({"revue_humaine": True}, BONS, [FOURNISSEUR], "revue_humaine_exigee_par_le_tri"),
        ({"expediteur_empreinte": "1" * 64}, BONS, [FOURNISSEUR], "expediteur_different_du_fournisseur_du_po"),
        ({"etat_annonce": ["confirmee", "rupture"]}, BONS, [FOURNISSEUR], "anomalie_signalee:rupture"),
        (
            {"etat_annonce": ["confirmee", "report", "substitution"]},
            BONS,
            [FOURNISSEUR],
            "anomalie_signalee:report,substitution",
        ),
        ({"etat_annonce": []}, BONS, [FOURNISSEUR], "aucune_confirmation_explicite"),
        ({}, [{**BONS[0], "statut": "email_ready"}], [FOURNISSEUR], "po_au_statut_email_ready"),
        ({}, [{**BONS[0], "statut": "received"}], [FOURNISSEUR], "po_au_statut_received"),
        ({}, [{**BONS[0], "fournisseur_id": "f-2"}], [FOURNISSEUR, AUTRE], "expediteur_different_du_fournisseur_du_po"),
        ({}, BONS, [], "expediteur_different_du_fournisseur_du_po"),
    ],
)
def test_chaque_condition_manquante_renvoie_a_une_personne(modif, bons, fiches, raison):
    e = cc.evaluer_confirmation(_conf(**modif), bons, fiches)
    assert e["decision"] == "a_valider" and any(r.startswith(raison.split(":")[0]) for r in e["raisons"]), e


def test_po_inconnu_non_rapproche_et_po_ambigus_a_valider():
    e = cc.evaluer_confirmation(_conf(references_po=["PO-X"], jetons_reference=["PO-X"]), BONS, [FOURNISSEUR])
    assert e["decision"] == "non_rapprochee" and e["po_id"] is None
    deux = BONS + [{**BONS[0], "po_id": "PO-2026-015"}]
    e2 = cc.evaluer_confirmation(
        _conf(references_po=["PO-2026-014", "PO-2026-015"], jetons_reference=["PO-2026-014", "PO-2026-015"]),
        deux,
        [FOURNISSEUR],
    )
    assert e2["decision"] == "a_valider" and e2["po_id"] is None and "plusieurs_po_nommes" in e2["raisons"]


def test_la_casse_de_la_reference_du_po_ne_change_rien():
    e = cc.evaluer_confirmation(_conf(references_po=["po-2026-014"], jetons_reference=[]), BONS, [FOURNISSEUR])
    assert e["decision"] == "appliquer"


def test_la_transition_supplier_confirmed_n_existe_que_depuis_sent_to_supplier():
    registre: list = []
    registre.append(
        {
            "type_entree": "po_cree",
            "po_id": "P1",
            "statut": "draft",
            "chantier_id": "c",
            "fournisseur_id": "f-1",
            "lignes": [],
            "montant_total_prevu": None,
            "horodatage": "t",
        }
    )
    po, verdict = bons_commande.confirmer_fournisseur("P1", "t2", registre, {"signal_id": "s"})
    assert po is None and verdict["code"] == "REJ-PO-TRANSITION-ILLEGALE"
    registre2 = copy.deepcopy(registre)
    for statut in ("approved", "email_ready", "sent_to_supplier"):
        registre2.append({"type_entree": "transition_po", "po_id": "P1", "statut": statut, "horodatage": "t"})
    po, verdict = bons_commande.confirmer_fournisseur("P1", "t3", registre2, {"signal_id": "s", "mode": "x"})
    assert verdict is None and po["statut"] == "supplier_confirmed" and po["confirmation_courriel"]["signal_id"] == "s"
    po2, verdict2 = bons_commande.confirmer_fournisseur("P1", "t4", registre2, {"signal_id": "s"})
    assert po2 is None and verdict2["code"] == "REJ-PO-TRANSITION-ILLEGALE", "pas deux fois"
    inconnu, v3 = bons_commande.confirmer_fournisseur("nope", "t", registre2, {})
    assert inconnu is None and v3["code"] == "REJ-PO-INTROUVABLE"
