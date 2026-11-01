"""Ouverture et préclôture de période, mesures et flux fournisseur (noyau pur). Données fictives."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer as ap
from m5_financecore import (
    facturation,
    grand_livre,
    plan_comptable,
    recu_calcul,
    taux_fiscaux,
)
from m5_financecore import (
    operations_comptables as oc,
)
from m5_financecore import (
    operations_periodes as op,
)
from m5_financecore import (
    operations_registre as ore,
)
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
_M5 = Path(__file__).resolve().parents[1]
H = "2026-11-02T10:00:00-04:00"
HUMAIN = {"par": "comptable", "role": "finance", "voie": "approbation"}


@pytest.fixture
def plan():
    base, refus = plan_comptable.charger_plan(_M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None
    return base


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_M5 / "contracts" / "taux_fiscaux.v1.yaml")
    assert erreurs == []
    return dictionnaire


@pytest.fixture
def gl():
    return registre_module.Registre()


@pytest.fixture
def ops():
    return registre_module.Registre()


def etat_gl(gl):
    return grand_livre.etat_grand_livre(gl.lire())


def etat_ops(ops):
    return ore.etat_operations(ops.lire())


def ecrire(gl, plan, ref, jour, montant="100.00", valider=True):
    resultat, refus = grand_livre.proposer_ecriture(
        gl,
        plan,
        cle_piece=f"saisie:manuelle:{ref}",
        piece={"type": "manuelle", "reference": ref},
        nature="saisie",
        date_effet=jour,
        libelle=f"Loyer {ref} (fictif)",
        lignes_brutes=[
            {"compte": "5600", "debit": montant, "credit": None},
            {"compte": "1010", "debit": None, "credit": montant},
        ],
        horodatage=H,
        origine="saisie",
    )
    assert refus is None, refus
    ident = resultat["ecriture"]["ecriture_id"]
    if valider:
        assert grand_livre.valider_ecriture(gl, plan, ecriture_id=ident, humain=HUMAIN, horodatage=H)[1] is None
    return ident


def preclore(ops, gl, periode="2026-10", clients=(), fournisseurs=(), taxes=None):
    return op.preclore_periode(
        ops,
        etat_ops(ops),
        etat_gl(gl),
        periode=periode,
        factures_clients=list(clients),
        factures_fournisseurs=list(fournisseurs),
        controle_taxes=taxes,
        horodatage=H,
    )


def par_controle(resultat):
    return {c["controle"]: c["statut"] for c in resultat["controles"]}


def test_ouverture_consigne_les_soldes_d_ouverture_et_dit_si_la_veille_est_close(ops, gl, plan):
    ecrire(gl, plan, "A", "2026-09-10", "300.00")
    r, refus = op.ouvrir_periode(ops, etat_ops(ops), etat_gl(gl), periode="2026-10", horodatage=H)
    assert refus is None and r["comptes"] == 2 and r["total_debiteur"] == r["total_crediteur"] == "300.00"
    assert r["precedente_close"] is False and "PROVISOIRES" in r["avertissements"][0]
    assert (
        op.ouvrir_periode(ops, etat_ops(ops), etat_gl(gl), periode="2026-10", horodatage=H)[0]["statut"]
        == "deja_consignee"
    )
    assert grand_livre.clore_periode(gl, periode="2026-09", humain=HUMAIN, horodatage=H)[1] is None
    r2, _ = op.ouvrir_periode(ops, etat_ops(ops), etat_gl(gl), periode="2026-10", horodatage=H)
    assert r2["precedente_close"] is True and r2["avertissements"] == []


def test_ouverture_changee_par_une_ecriture_anterieure_cree_une_nouvelle_ouverture(ops, gl, plan):
    ecrire(gl, plan, "A", "2026-09-10", "300.00")
    op.ouvrir_periode(ops, etat_ops(ops), etat_gl(gl), periode="2026-10", horodatage=H)
    ecrire(gl, plan, "B", "2026-09-12", "50.00")
    r, _ = op.ouvrir_periode(ops, etat_ops(ops), etat_gl(gl), periode="2026-10", horodatage=H)
    assert r["statut"] == "consignee" and len(etat_ops(ops)["par_type"]["op_periode_ouverte"]) == 2


def test_ouverture_et_preclôture_refusent_une_periode_close_ou_mal_formee(ops, gl, plan):
    ecrire(gl, plan, "A", "2026-09-10")
    assert grand_livre.clore_periode(gl, periode="2026-09", humain=HUMAIN, horodatage=H)[1] is None
    for fonction in (
        lambda p: op.ouvrir_periode(ops, etat_ops(ops), etat_gl(gl), periode=p, horodatage=H),
        lambda p: preclore(ops, gl, p),
    ):
        assert fonction("2026-09")[1]["code"] == "REJ-OPS-PERIODE-CLOSE"
        assert fonction("2026-9")[1]["code"] == "REJ-OPS-PERIODE-INVALIDE"
        assert fonction("2026-13")[1]["code"] == "REJ-OPS-PERIODE-INVALIDE"
    assert ops.taille() == 0


def test_preclôture_bloque_sur_brouillon_en_attente_et_dit_pourquoi(ops, gl, plan):
    ecrire(gl, plan, "A", "2026-10-05", valider=False)
    r, refus = preclore(ops, gl)
    assert refus is None and r["statut"] == "BLOQUE" and r["bloquants"] == 1
    assert par_controle(r)["brouillons_en_attente"] == "BLOQUANT"
    assert recu_calcul.verifier(r["recu"]) == (True, "")
    assert "N4" in r["a_faire"]


def test_preclôture_prete_avec_reserves_puis_prete_quand_tout_est_consigne(ops, gl, plan):
    ecrire(gl, plan, "A", "2026-10-05")
    r, _ = preclore(ops, gl)
    controles = par_controle(r)
    assert r["statut"] == "PRET_AVEC_RESERVES" and controles["brouillons_en_attente"] == "OK"
    assert controles["rapprochement_bancaire"] == "A_VERIFIER" and controles["jugements_et_estimations"] == "A_VERIFIER"
    assert controles["pieces_justificatives"] == "A_VERIFIER"  # une écriture manuelle sans pièce liée
    assert controles["taxes_rapprochees"] == "A_VERIFIER"
    ident = list(etat_gl(gl)["ecritures"])[0]
    oc.lier_piece(
        ops,
        etat_ops(ops),
        cible_type="ecriture",
        cible_id=ident,
        cibles_connues={"ecriture": [ident]},
        nom="bail.pdf",
        sha256="cd" * 32,
        taille=10,
        lie_par="comptable",
        horodatage=H,
    )
    oc.enregistrer_jugement(
        ops,
        etat_ops(ops),
        genre="estimation",
        periode="2026-10",
        sujet="Provision",
        description="x",
        montant="0.00",
        hypotheses=["aucune créance douteuse"],
        base="historique",
        humain=HUMAIN,
        horodatage=H,
    )
    op.ouvrir_periode(ops, etat_ops(ops), etat_gl(gl), periode="2026-10", horodatage=H)
    ops.ajouter({"type_entree": "op_rapprochement_prepare", "horodatage": H, "rapprochement_id": "x"})  # étranger
    assert ore.etat_operations(ops.lire())["anomalies"]  # l'état refuse un maillon mal formé


def test_preclôture_prete_a_clore_quand_rapprochement_confirme_et_taxes_concordantes(ops, gl, plan):
    ecrire(gl, plan, "A", "2026-10-05")
    ident = list(etat_gl(gl)["ecritures"])[0]
    oc.lier_piece(
        ops,
        etat_ops(ops),
        cible_type="ecriture",
        cible_id=ident,
        cibles_connues={"ecriture": [ident]},
        nom="bail.pdf",
        sha256="cd" * 32,
        taille=10,
        lie_par="comptable",
        horodatage=H,
    )
    oc.enregistrer_jugement(
        ops,
        etat_ops(ops),
        genre="estimation",
        periode="2026-10",
        sujet="Provision",
        description="x",
        montant="0.00",
        hypotheses=["aucune"],
        base="historique",
        humain=HUMAIN,
        horodatage=H,
    )
    op.ouvrir_periode(ops, etat_ops(ops), etat_gl(gl), periode="2026-10", horodatage=H)
    rap = ore.ajouter_operation(
        ops,
        etat_ops(ops),
        "op_rapprochement_prepare",
        "rapprochement:x",
        {"periode_debut": "2026-10-01", "periode_fin": "2026-10-31", "etat": "EQUILIBRE"},
        H,
    )[0]["operation"]
    ore.ajouter_operation(
        ops,
        etat_ops(ops),
        "op_rapprochement_confirme",
        f"confirme:{rap['rapprochement_id']}",
        {"rapprochement_vise": rap["rapprochement_id"], "par": "comptable"},
        H,
    )
    r, _ = preclore(ops, gl, taxes={"verdict": "CONCORDANT"})
    assert r["statut"] == "PRET_A_CLORE" and set(par_controle(r).values()) == {"OK"}
    assert set(par_controle(r)) == set(op.controles())


def test_rapprochement_a_ecart_non_confirme_bloque_la_preclôture(ops, gl, plan):
    ecrire(gl, plan, "A", "2026-10-05")
    ore.ajouter_operation(
        ops,
        etat_ops(ops),
        "op_rapprochement_prepare",
        "rapprochement:y",
        {"periode_debut": "2026-10-01", "periode_fin": "2026-10-31", "etat": "ECART"},
        H,
    )
    r, _ = preclore(ops, gl)
    assert par_controle(r)["rapprochement_bancaire"] == "BLOQUANT" and r["statut"] == "BLOQUE"


def test_factures_sans_ecriture_bloquent(ops, gl, plan, taux):
    reg = registre_module.Registre()
    facturation.creer_facture_brouillon(
        "F-1",
        "CH",
        "D-1",
        "c",
        [{"description": "x", "quantite": "1", "unite": "u", "prix_unitaire": "100.00", "reference_ligne_devis": "L"}],
        "2026-10-01T09:00:00-04:00",
        taux,
        reg,
    )
    facturation.envoyer_facture("F-1", "2026-10-02T10:00:00-04:00", reg)
    reg_ap = registre_module.Registre()
    ap.saisir_facture_sans_po(
        fournisseur_id="Pétro (fictif)",
        categorie="carburant",
        numero_facture="C-1",
        date_facture="2026-10-03",
        montant_avant_taxes="50.00",
        total_facture=None,
        saisi_par="c",
        voie="appareil",
        horodatage=H,
        dictionnaire_taux=taux,
        categories_configurees=["carburant"],
        registre_cible=reg_ap,
    )
    r, _ = preclore(
        ops, gl, clients=facturation.factures_par_statut(reg, "ENVOYEE"), fournisseurs=ap.factures_saisies(reg_ap)
    )
    controles = par_controle(r)
    assert controles["factures_clients_sans_ecriture"] == "BLOQUANT" == controles["factures_fournisseurs_sans_ecriture"]
    # une fois les brouillons générés, les contrôles passent (les brouillons bloquent autrement)
    propositions, _ = grand_livre.propositions_factures_clients(facturation.factures_par_statut(reg, "ENVOYEE"), plan)
    propositions_f, _ = grand_livre.propositions_factures_fournisseurs(ap.factures_saisies(reg_ap), plan)
    for p in [*propositions, *propositions_f]:
        assert grand_livre.proposer_ecriture(gl, plan, horodatage=H, origine="generation_automatique", **p)[1] is None
    r2, _ = preclore(
        ops, gl, clients=facturation.factures_par_statut(reg, "ENVOYEE"), fournisseurs=ap.factures_saisies(reg_ap)
    )
    controles2 = par_controle(r2)
    assert (
        controles2["factures_clients_sans_ecriture"] == "OK"
        and controles2["factures_fournisseurs_sans_ecriture"] == "OK"
    )
    assert controles2["brouillons_en_attente"] == "BLOQUANT"


def test_mesures_comptables_ne_portent_que_des_nombres_et_des_montants(ops, gl, plan):
    ecrire(gl, plan, "A", "2026-10-05", valider=False)
    ecrire(gl, plan, "B", "2026-10-06")
    mesures = op.mesures_comptables(
        etat_gl(gl),
        etat_ops(ops),
        creances={
            "nombre": 2,
            "total": "1379.70",
            "par_tranche": {"0-30": "689.85", "31-60": "689.85", "61-90": "0.00", "90+": "0.00"},
        },
        date_reference="2026-11-02",
    )
    assert mesures["brouillons_en_attente"] == 1 and mesures["ecritures_definitives"] == 1
    assert mesures["derniere_periode_close"] is None and mesures["creances"]["nombre"] == 2
    texte = repr(mesures)
    assert "Loyer" not in texte and "fictif" not in texte


def test_flux_fournisseur_dit_chaque_etape_et_la_suite(taux):
    reg_ap = registre_module.Registre()
    ap.saisir_facture_sans_po(
        fournisseur_id="Pétro (fictif)",
        categorie="carburant",
        numero_facture="C-1",
        date_facture="2026-10-03",
        montant_avant_taxes="50.00",
        total_facture=None,
        saisi_par="c",
        voie="appareil",
        horodatage=H,
        dictionnaire_taux=taux,
        categories_configurees=["carburant"],
        registre_cible=reg_ap,
    )
    f = ap.factures_saisies(reg_ap)[0]
    flux = op.flux_fournisseur(f, None, None, None, [])
    etapes = {e["etape"]: e["etat"] for e in flux["etapes"]}
    assert etapes == {
        "facture_recue": "SAISIE",
        "appariement_commande": "SANS_COMMANDE",
        "brouillon_ecriture": "ABSENT",
        "paiement_prepare": "ABSENT",
        "paiement_execute": "HORS_OPSYS",
    }
    assert "brouillon" in flux["prochaine_action"]
    avec = op.flux_fournisseur(
        {**f, "po_id": "PO-1"}, {"verdict": "ECART"}, {"statut": "DEFINITIVE", "ecriture_id": "e"}, None, []
    )
    assert "écart" in avec["prochaine_action"]
    pret = op.flux_fournisseur(f, None, {"statut": "DEFINITIVE", "ecriture_id": "e"}, None, [])
    assert "m5_preparer_paiement_fournisseur" in pret["prochaine_action"]
    fini = op.flux_fournisseur(
        f,
        None,
        {"statut": "DEFINITIVE", "ecriture_id": "e"},
        {"statut": "PREPARE", "montant": "57.49", "date_prevue": "2026-11-15"},
        [],
    )
    assert "hors d'OPSYS" in fini["prochaine_action"]
    assert "annulée" in op.flux_fournisseur({**f, "statut": "ANNULEE"}, None, None, None, [])["prochaine_action"]
