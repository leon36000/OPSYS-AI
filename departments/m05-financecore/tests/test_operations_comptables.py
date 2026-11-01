"""Opérations comptables (noyau pur) : relances, notes de crédit, dépenses d'employés, pièces, paiements préparés,
jugements. Registres en mémoire, taux versionnés réels, données fictives."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer as ap
from m5_financecore import (
    facturation,
    grand_livre,
    plan_comptable,
    taux_fiscaux,
    verdicts_operations,
)
from m5_financecore import (
    operations_comptables as oc,
)
from m5_financecore import (
    operations_registre as ore,
)
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
_M5 = Path(__file__).resolve().parents[1]
H = "2026-10-15T10:00:00-04:00"
HUMAIN = {"par": "comptable", "role": "finance", "voie": "approbation"}
POLITIQUE = {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]}


@pytest.fixture
def plan():
    base, refus = plan_comptable.charger_plan(_M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None, refus
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


@pytest.fixture
def reg_factures():
    return registre_module.Registre()


def etat(ops):
    resultat = ore.etat_operations(ops.lire())
    assert resultat["anomalies"] == []
    return resultat


def code(couple):
    resultat, refus = couple
    assert resultat is None and refus is not None, resultat
    assert refus["code"] in verdicts_operations.CODES_OPERATIONS or refus["code"].startswith(("REJ-GL-", "REJ-TAUX"))
    return refus["code"]


def accepte(couple):
    resultat, refus = couple
    assert refus is None, refus
    return resultat


def facture_client(reg, taux, facture_id="F-1", prix="600.00", envoi="2026-09-01", payer=False):
    lignes = [
        {
            "description": "travaux (fictif)",
            "quantite": "1",
            "unite": "u",
            "prix_unitaire": prix,
            "reference_ligne_devis": "L1",
        }
    ]
    assert (
        facturation.creer_facture_brouillon(
            facture_id, "CH-1", f"D-{facture_id}", "client-1", lignes, f"{envoi}T09:00:00-04:00", taux, reg
        )[1]
        is None
    )
    assert facturation.envoyer_facture(facture_id, f"{envoi}T10:00:00-04:00", reg)[1] is None
    if payer:
        total = facturation.facture_active_pour_devis(reg, f"D-{facture_id}")["montant_apres_taxes"]
        assert (
            facturation.enregistrer_paiement_facture(
                facture_id, str(total), "nathan", "2026-09-20T09:00:00-04:00", reg
            )[1]
            is None
        )
    return facturation.facture_active_pour_devis(reg, f"D-{facture_id}")


def facture_fournisseur(
    reg_ap, taux, numero="C-4001", montant="100.00", categorie="carburant", date_facture="2026-10-01"
):
    ap.saisir_facture_sans_po(
        fournisseur_id="Pétro-Nord (fictif)",
        categorie=categorie,
        numero_facture=numero,
        date_facture=date_facture,
        montant_avant_taxes=montant,
        total_facture=None,
        saisi_par="comptable",
        voie="appareil",
        horodatage="2026-10-08T10:00:00-04:00",
        dictionnaire_taux=taux,
        categories_configurees=["carburant", "outils"],
        registre_cible=reg_ap,
    )
    return ap.factures_saisies(reg_ap)[-1]


# ====================================================================================== politique et relances
def test_la_politique_de_relance_absente_ou_mal_formee_dit_quoi_declarer():
    for brut in (
        None,
        {},
        {"delai_echeance_jours": 30},
        {"delai_echeance_jours": -1, "paliers_jours_apres_echeance": [7]},
        {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [21, 7]},
        {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [1, 2, 3, 4, 5]},
        {"delai_echeance_jours": True, "paliers_jours_apres_echeance": [7]},
        {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7.5]},
    ):
        politique, refus = oc.lire_politique_relances(brut)
        assert politique is None and refus["code"] == "REJ-OPS-CONFIGURATION-A-DECLARER"
        assert "delai_echeance_jours" in refus["detail"]
    politique, refus = oc.lire_politique_relances(POLITIQUE)
    assert refus is None and politique == POLITIQUE


def test_relance_du_niveau_courant_seulement_idempotente_et_jamais_envoyee(ops, reg_factures, taux):
    facture_client(reg_factures, taux, "F-1", envoi="2026-09-01")  # échéance 2026-10-01
    factures = list(facturation.factures_par_statut(reg_factures, "ENVOYEE"))
    for aujourd_hui, niveau in (("2026-10-05", None), ("2026-10-08", 1), ("2026-10-22", 2), ("2026-11-20", 3)):
        r = accepte(oc.preparer_relances(ops, etat(ops), factures, POLITIQUE, aujourd_hui, H))
        if niveau is None:
            assert r["creees"] == [] and r["sans_retard"] == 1
        else:
            assert [c["niveau"] for c in r["creees"]] == [niveau] and r["evenements"][0]["niveau"] == niveau
    deux = accepte(oc.preparer_relances(ops, etat(ops), factures, POLITIQUE, "2026-11-20", H))
    assert deux["creees"] == [] and deux["deja"] == 1 and deux["evenements"] == []
    relance = list(etat(ops)["par_type"]["op_relance_preparee"].values())[-1]
    assert relance["statut"] == "BROUILLON" and "non_envoye" in relance["envoi"]
    assert "689,85 $" in relance["texte"] and "F-1" in relance["texte"]
    assert len(etat(ops)["par_type"]["op_relance_preparee"]) == 3  # niveaux 1, 2 et 3, un seul par niveau


def test_une_facture_payee_ou_soldee_par_notes_de_credit_n_est_pas_relancee(ops, gl, plan, reg_factures, taux):
    payee = facture_client(reg_factures, taux, "F-2", envoi="2026-08-01", payer=True)
    assert payee["statut"] == "PAYEE"
    facture = facture_client(reg_factures, taux, "F-3", prix="100.00", envoi="2026-08-01")
    accepte(
        oc.proposer_note_credit(
            ops,
            etat(ops),
            gl,
            plan,
            taux,
            genre="client",
            facture=facture,
            reference="NC-1",
            montant_avant_taxes="100.00",
            date_effet="2026-09-10",
            motif="annulation",
            horodatage=H,
        )
    )
    factures = list(facturation.factures_par_statut(reg_factures, "ENVOYEE"))
    r = accepte(oc.preparer_relances(ops, etat(ops), factures, POLITIQUE, "2026-12-31", H))
    assert r["creees"] == [] and r["soldees"] == 1


def test_relance_refuse_une_date_invalide_et_ignore_une_facture_illisible(ops):
    assert code(oc.preparer_relances(ops, etat(ops), [], POLITIQUE, "2026-02-30", H)) == "REJ-OPS-DATE-INVALIDE"
    assert code(oc.preparer_relances(ops, etat(ops), [], POLITIQUE, "2026-10-01", "hier")) == "REJ-OPS-ENTREE-INVALIDE"
    r = accepte(
        oc.preparer_relances(ops, etat(ops), [{"facture_id": "F-X", "statut": "ENVOYEE"}], POLITIQUE, "2026-10-01", H)
    )
    assert r["creees"] == [] and r["ignorees"][0]["facture_id"] == "F-X"


def test_texte_de_relance_sans_nom_ni_menace_et_formate_en_quebecois():
    assert oc.formater_cad(D("1234567.8")) == "1 234 567,80 $"
    for niveau in (1, 2, 3):
        texte = oc.texte_relance(niveau, "F-9", D("100"), "2026-10-01", 40)
        assert "F-9" in texte and "100,00 $" in texte
        assert not any(mot in texte.lower() for mot in ("avocat", "poursuite", "huissier", "tribunal"))


# ====================================================================================================== notes de crédit
def test_note_de_credit_client_partielle_puis_finale_reprend_exactement_les_taxes(ops, gl, plan, reg_factures, taux):
    facture = facture_client(reg_factures, taux, "F-1", prix="600.00")  # TPS 30.00, TVQ 59.85, total 689.85
    n1 = accepte(
        oc.proposer_note_credit(
            ops,
            etat(ops),
            gl,
            plan,
            taux,
            genre="client",
            facture=facture,
            reference="NC-1",
            montant_avant_taxes="100.00",
            date_effet="2026-10-02",
            motif="rabais accordé",
            horodatage=H,
        )
    )
    assert (n1["taxes"], n1["montant_apres_taxes"], n1["statut"]) == (
        {"tps_a_percevoir": "5.00", "tvq_a_percevoir": "9.98"},
        "114.98",
        "proposee",
    )
    n2 = accepte(
        oc.proposer_note_credit(
            ops,
            etat(ops),
            gl,
            plan,
            taux,
            genre="client",
            facture=facture,
            reference="NC-2",
            montant_avant_taxes="500.00",
            date_effet="2026-10-03",
            motif="solde",
            horodatage=H,
        )
    )
    assert n2["taxes"] == {"tps_a_percevoir": "25.00", "tvq_a_percevoir": "49.87"}  # 59.85 − 9.98, pas 49.88
    total = D(n1["montant_apres_taxes"]) + D(n2["montant_apres_taxes"])
    assert total == D("689.85")
    brouillons = [e for e in grand_livre.etat_grand_livre(gl.lire())["ecritures"].values()]
    assert len(brouillons) == 2 and all(
        e["statut"] == "BROUILLON" and e["piece"]["type"] == "note_credit" for e in brouillons
    )
    ligne_clients = [ligne for ligne in brouillons[0]["lignes"] if ligne["compte"] == "1100"][0]
    assert ligne_clients["credit"] == D("114.98")


def test_note_de_credit_ne_depasse_jamais_la_facture_et_est_idempotente(ops, gl, plan, reg_factures, taux):
    facture = facture_client(reg_factures, taux, "F-1", prix="600.00")
    args = {
        "genre": "client",
        "facture": facture,
        "reference": "NC-1",
        "date_effet": "2026-10-02",
        "motif": "rabais",
        "horodatage": H,
    }
    premiere = accepte(oc.proposer_note_credit(ops, etat(ops), gl, plan, taux, montant_avant_taxes="400.00", **args))
    rejeu = accepte(oc.proposer_note_credit(ops, etat(ops), gl, plan, taux, montant_avant_taxes="400.00", **args))
    assert rejeu["statut"] == "deja_proposee" and rejeu["note_id"] == premiere["note_id"]
    assert len(grand_livre.etat_grand_livre(gl.lire())["ecritures"]) == 1
    assert (
        code(
            oc.proposer_note_credit(
                ops, etat(ops), gl, plan, taux, montant_avant_taxes="500.00", **{**args, "reference": "NC-2"}
            )
        )
        == "REJ-OPS-NOTE-CREDIT-EXCEDE"
    )  # 400 + 500 > 600
    assert code(oc.proposer_note_credit(ops, etat(ops), gl, plan, taux, montant_avant_taxes="300.00", **args)) == (
        "REJ-OPS-DOUBLON"
    )  # même clé, autre montant
    assert len(grand_livre.etat_grand_livre(gl.lire())["ecritures"]) == 1


def test_note_de_credit_refus_nommes(ops, gl, plan, reg_factures, taux):
    facture = facture_client(reg_factures, taux, "F-1", prix="600.00")
    base = {
        "genre": "client",
        "facture": facture,
        "reference": "NC-1",
        "date_effet": "2026-10-02",
        "motif": "rabais",
        "montant_avant_taxes": "10.00",
        "horodatage": H,
    }

    def essai(**changes):
        return code(oc.proposer_note_credit(ops, etat(ops), gl, plan, taux, **{**base, **changes}))

    assert essai(facture=None) == "REJ-OPS-FACTURE-INTROUVABLE"
    assert essai(facture={**facture, "statut": "BROUILLON"}) == "REJ-OPS-FACTURE-NON-EMISE"
    assert essai(date_effet="2026-08-31") == "REJ-OPS-DATE-INVALIDE"  # avant sa facture
    assert essai(montant_avant_taxes=10) == "REJ-OPS-MONTANT-INVALIDE"
    assert essai(montant_avant_taxes="0.00") == "REJ-OPS-MONTANT-INVALIDE"
    assert essai(montant_avant_taxes="-5.00") == "REJ-OPS-MONTANT-INVALIDE"
    assert essai(montant_avant_taxes="1.005") == "REJ-OPS-MONTANT-INVALIDE"
    assert essai(motif="  ") == "REJ-OPS-ENTREE-INVALIDE"
    assert essai(motif="a\nb") == "REJ-OPS-ENTREE-INVALIDE"
    assert essai(reference="../x") == "REJ-OPS-ENTREE-INVALIDE"
    assert essai(genre="autre") == "REJ-OPS-ENTREE-INVALIDE"
    assert essai(facture={**facture, "total_taxes": D("1.00")}) == "REJ-OPS-ENTREE-INVALIDE"  # pièce incohérente
    assert grand_livre.etat_grand_livre(gl.lire())["ecritures"] == {}


def test_note_de_credit_dans_une_periode_close_est_refusee_sans_rien_ecrire(ops, gl, plan, reg_factures, taux):
    facture = facture_client(reg_factures, taux, "F-1", prix="600.00")
    assert grand_livre.clore_periode(gl, periode="2026-10", humain=HUMAIN, horodatage=H)[1] is None
    c = code(
        oc.proposer_note_credit(
            ops,
            etat(ops),
            gl,
            plan,
            taux,
            genre="client",
            facture=facture,
            reference="NC-1",
            montant_avant_taxes="10.00",
            date_effet="2026-10-02",
            motif="rabais",
            horodatage=H,
        )
    )
    assert c == "REJ-GL-PERIODE-CLOSE" and ops.taille() == 0


def test_note_de_credit_sur_facture_payee_dit_que_le_remboursement_est_humain(ops, gl, plan, reg_factures, taux):
    facture = facture_client(reg_factures, taux, "F-1", prix="600.00", payer=True)
    n = accepte(
        oc.proposer_note_credit(
            ops,
            etat(ops),
            gl,
            plan,
            taux,
            genre="client",
            facture=facture,
            reference="NC-1",
            montant_avant_taxes="10.00",
            date_effet="2026-10-02",
            motif="rabais",
            horodatage=H,
        )
    )
    assert n["facture_payee"] is True and "remboursement" in n["a_faire"]


def test_note_de_credit_fournisseur_inverse_la_facture_et_refuse_une_annulee(ops, gl, plan, taux):
    reg_ap = registre_module.Registre()
    f = facture_fournisseur(reg_ap, taux)  # 100.00 + TPS 5.00 + TVQ 9.98 = 114.98
    n = accepte(
        oc.proposer_note_credit(
            ops,
            etat(ops),
            gl,
            plan,
            taux,
            genre="fournisseur",
            facture=f,
            reference="NCF-1",
            montant_avant_taxes="100.00",
            date_effet="2026-10-05",
            motif="retour",
            horodatage=H,
        )
    )
    assert n["montant_apres_taxes"] == "114.98" and n["taxes"] == {"tps_cti": "5.00", "tvq_rti": "9.98"}
    ecriture = list(grand_livre.etat_grand_livre(gl.lire())["ecritures"].values())[0]
    par_compte = {ligne["compte"]: (ligne["debit"], ligne["credit"]) for ligne in ecriture["lignes"]}
    assert par_compte["2100"] == (D("114.98"), D("0.00")) and par_compte["5400"] == (D("0.00"), D("100.00"))
    assert (
        code(
            oc.proposer_note_credit(
                ops,
                etat(ops),
                gl,
                plan,
                taux,
                genre="fournisseur",
                facture={**f, "statut": "ANNULEE"},
                reference="NCF-2",
                montant_avant_taxes="1.00",
                date_effet="2026-10-05",
                motif="x",
                horodatage=H,
            )
        )
        == "REJ-OPS-FACTURE-ANNULEE"
    )


# ====================================================================================== dépenses d'employés
def depense(ops, gl, plan, taux, **changes):
    args = {
        "employe_id": "emp-1",
        "reference": "R-1",
        "date_depense": "2026-10-04",
        "categorie": "carburant",
        "description": "plein d'essence camion",
        "montant_avant_taxes": "100.00",
        "taxable": True,
        "total_recu": "114.98",
        "compte_remboursement": "2200",
        "horodatage": H,
    }
    args.update(changes)
    return oc.proposer_depense_employe(ops, etat(ops), gl, plan, taux, **args)


def test_depense_d_employe_recalcule_les_taxes_et_propose_le_brouillon(ops, gl, plan, taux):
    d = accepte(depense(ops, gl, plan, taux))
    assert d["taxes"] == {"tps_cti": "5.00", "tvq_rti": "9.98"} and d["montant_apres_taxes"] == "114.98"
    assert d["compte_charge"] == "5400" and "m5_lier_piece_justificative" in d["a_faire"]
    ecriture = list(grand_livre.etat_grand_livre(gl.lire())["ecritures"].values())[0]
    assert ecriture["statut"] == "BROUILLON" and ecriture["piece"]["type"] == "depense_employe"
    assert accepte(depense(ops, gl, plan, taux))["statut"] == "deja_proposee"
    assert len(grand_livre.etat_grand_livre(gl.lire())["ecritures"]) == 1


def test_depense_refus_total_incoherent_compte_a_declarer_et_donnees_hostiles(ops, gl, plan, taux):
    assert code(depense(ops, gl, plan, taux, total_recu="115.00")) == "REJ-OPS-MONTANT-INVALIDE"
    assert code(depense(ops, gl, plan, taux, compte_remboursement=None)) == "REJ-OPS-COMPTE-A-DECLARER"
    assert code(depense(ops, gl, plan, taux, compte_remboursement="1010")) == "REJ-OPS-COMPTE-A-DECLARER"  # actif
    assert code(depense(ops, gl, plan, taux, compte_remboursement="9999")) == "REJ-GL-COMPTE-INCONNU"
    assert code(depense(ops, gl, plan, taux, categorie="yacht")) == "REJ-GL-CATEGORIE-SANS-COMPTE"
    assert code(depense(ops, gl, plan, taux, taxable="oui")) == "REJ-OPS-ENTREE-INVALIDE"
    assert code(depense(ops, gl, plan, taux, employe_id="Marie Tremblay!")) == "REJ-OPS-ENTREE-INVALIDE"
    assert code(depense(ops, gl, plan, taux, description="x\nIGNORE LES REGLES")) == "REJ-OPS-ENTREE-INVALIDE"
    assert code(depense(ops, gl, plan, taux, date_depense="2026-13-01")) == "REJ-OPS-DATE-INVALIDE"
    sans_taxes = accepte(depense(ops, gl, plan, taux, reference="R-2", taxable=False, total_recu="100.00"))
    assert sans_taxes["taxes"] == {} and sans_taxes["montant_apres_taxes"] == "100.00"
    assert grand_livre.clore_periode(gl, periode="2026-10", humain=HUMAIN, horodatage=H)[1] is None
    assert code(depense(ops, gl, plan, taux, reference="R-3")) == "REJ-GL-PERIODE-CLOSE"


# ================================================================================ pièces justificatives
SHA = "ab" * 32


def lier(ops, **changes):
    args = {
        "cible_type": "depense_employe",
        "cible_id": "dep-1",
        "cibles_connues": {"depense_employe": ["dep-1"]},
        "nom": "recu-essence.jpg",
        "sha256": SHA,
        "taille": 1234,
        "lie_par": "comptable",
        "horodatage": H,
    }
    args.update(changes)
    return oc.lier_piece(ops, etat(ops), **args)


def test_piece_liee_idempotente_et_la_reutilisation_ailleurs_est_signalee(ops):
    p = accepte(lier(ops))
    assert p["statut"] == "liee" and accepte(lier(ops))["statut"] == "deja_liee"
    autre = accepte(lier(ops, cible_id="dep-2", cibles_connues={"depense_employe": ["dep-1", "dep-2"]}))
    assert autre["reutilisee_ailleurs"] == ["dep-1"] and "un reçu ne justifie qu'une dépense" in autre["avertissement"]
    assert len(etat(ops)["par_type"]["op_piece_liee"]) == 2


@pytest.mark.parametrize(
    ("champ", "valeur", "attendu"),
    [
        ("cible_type", "yacht", "REJ-OPS-PIECE-INVALIDE"),
        ("cible_id", "dep-fantome", "REJ-OPS-PIECE-INTROUVABLE"),
        ("sha256", "XYZ", "REJ-OPS-PIECE-INVALIDE"),
        ("sha256", "AB" * 32, "REJ-OPS-PIECE-INVALIDE"),
        ("nom", "../../etc/passwd", "REJ-OPS-PIECE-INVALIDE"),
        ("nom", "a\\b.pdf", "REJ-OPS-PIECE-INVALIDE"),
        ("nom", "", "REJ-OPS-PIECE-INVALIDE"),
        ("taille", 0, "REJ-OPS-PIECE-INVALIDE"),
        ("taille", True, "REJ-OPS-PIECE-INVALIDE"),
        ("lie_par", " ", "REJ-OPS-PIECE-INVALIDE"),
        ("horodatage", "demain", "REJ-OPS-ENTREE-INVALIDE"),
    ],
)
def test_piece_justificative_refus(ops, champ, valeur, attendu):
    assert code(lier(ops, **{champ: valeur})) == attendu
    assert ops.taille() == 0


# ======================================================================================= paiements préparés
def preparer(ops, facture, rapprochement=None, **changes):
    args = {
        "facture": facture,
        "rapprochement": rapprochement,
        "date_prevue": "2026-11-15",
        "derogation_motif": None,
        "humain": HUMAIN,
        "horodatage": H,
    }
    args.update(changes)
    return oc.preparer_paiement(ops, etat(ops), **args)


def test_paiement_prepare_net_des_notes_de_credit_une_seule_fois_et_jamais_execute(ops, gl, plan, taux):
    reg_ap = registre_module.Registre()
    f = facture_fournisseur(reg_ap, taux)
    accepte(
        oc.proposer_note_credit(
            ops,
            etat(ops),
            gl,
            plan,
            taux,
            genre="fournisseur",
            facture=f,
            reference="NCF-1",
            montant_avant_taxes="20.00",
            date_effet="2026-10-05",
            motif="retour partiel",
            horodatage=H,
        )
    )
    p = accepte(preparer(ops, f))
    assert p["montant"] == "91.98" and p["rapprochement"] == "SANS_PO" and "hors_opsys" in p["execution"]
    assert code(preparer(ops, f)) == "REJ-OPS-PAIEMENT-DEJA-PREPARE"
    enregistre = list(etat(ops)["par_type"]["op_paiement_prepare"].values())[0]
    assert enregistre["statut"] == "PREPARE" and enregistre["prepare_par"] == "comptable"


def test_paiement_refuse_si_rapprochement_po_non_concordant_sauf_derogation_humaine_motivee(ops, taux):
    reg_ap = registre_module.Registre()
    f = {**facture_fournisseur(reg_ap, taux), "po_id": "PO-7"}
    ecart = {"verdict": "ECART"}
    assert code(preparer(ops, f, ecart)) == "REJ-OPS-PAIEMENT-RAPPROCHEMENT"
    assert code(preparer(ops, f, ecart, derogation_motif="ok")) == "REJ-OPS-PAIEMENT-RAPPROCHEMENT"
    assert code(preparer(ops, f, None)) == "REJ-OPS-PAIEMENT-RAPPROCHEMENT"
    p = accepte(preparer(ops, f, ecart, derogation_motif="écart de livraison accepté par le chef d'équipe"))
    assert p["derogation"] is True and p["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    f2 = {**f, "facture_fournisseur_id": "ff-2"}
    assert accepte(preparer(ops, f2, {"verdict": "CONCORDANT"}))["derogation"] is False


def test_paiement_refus_facture_annulee_soldee_date_invalide(ops, taux):
    reg_ap = registre_module.Registre()
    f = facture_fournisseur(reg_ap, taux)
    assert code(preparer(ops, None)) == "REJ-OPS-FACTURE-INTROUVABLE"
    assert code(preparer(ops, {**f, "statut": "ANNULEE"})) == "REJ-OPS-FACTURE-ANNULEE"
    assert code(preparer(ops, f, date_prevue="2026-02-30")) == "REJ-OPS-DATE-INVALIDE"
    assert code(preparer(ops, {**f, "montant_apres_taxes": D("0")})) == "REJ-OPS-PAIEMENT-INVALIDE"
    assert ops.taille() == 0


# =================================================================================== jugements et estimations
def juger(ops, **changes):
    args = {
        "genre": "estimation",
        "periode": "2026-10",
        "sujet": "Provision pour créances douteuses",
        "description": "Provision de 2 % des créances de plus de 90 jours",
        "montant": "250.00",
        "hypotheses": ["les clients de plus de 90 jours paient à 50 %"],
        "base": "historique de 2025",
        "humain": HUMAIN,
        "horodatage": H,
    }
    args.update(changes)
    return oc.enregistrer_jugement(ops, etat(ops), **args)


def test_jugement_consigne_idempotent_avec_personne_et_base(ops):
    j = accepte(juger(ops))
    assert j["statut"] == "consigne" and accepte(juger(ops))["statut"] == "deja_consigne"
    enregistre = list(etat(ops)["par_type"]["op_jugement_enregistre"].values())[0]
    assert enregistre["par"] == "comptable" and enregistre["montant"] == "250.00" and enregistre["hypotheses"]


@pytest.mark.parametrize(
    ("changes", "attendu"),
    [
        ({"genre": "opinion"}, "REJ-OPS-JUGEMENT-INVALIDE"),
        ({"periode": "2026-13"}, "REJ-OPS-PERIODE-INVALIDE"),
        ({"sujet": ""}, "REJ-OPS-JUGEMENT-INVALIDE"),
        ({"hypotheses": []}, "REJ-OPS-JUGEMENT-INVALIDE"),
        ({"hypotheses": ["a\nb"]}, "REJ-OPS-JUGEMENT-INVALIDE"),
        ({"base": "x" * 301}, "REJ-OPS-JUGEMENT-INVALIDE"),
        ({"montant": 250}, "REJ-OPS-MONTANT-INVALIDE"),
        ({"montant": "-1.00"}, "REJ-OPS-MONTANT-INVALIDE"),
    ],
)
def test_jugement_refus(ops, changes, attendu):
    assert code(juger(ops, **changes)) == attendu
    assert ops.taille() == 0


def test_jugement_sans_montant_est_permis():
    ops = registre_module.Registre()
    assert accepte(juger(ops, montant=None, genre="jugement"))["montant"] is None


# ============================================================================================== le registre
def test_le_registre_refuse_un_contenu_altere_un_identifiant_incoherent_et_un_maillon_etranger(ops):
    accepte(juger(ops))
    original = ops.lire()[0]
    truque = {**original, "montant": "999.00"}
    assert "contenu altéré" in ore.etat_operations([truque])["anomalies"][0]
    faux_id = {**original, "jugement_id": "jug-pirate"}
    assert "incohérent" in ore.etat_operations([faux_id])["anomalies"][0]
    assert ore.etat_operations([{"type_entree": "mouvement_enregistre"}])["anomalies"]
    double = ore.etat_operations([original, original])
    assert (
        double["anomalies"] == []
        and len(double["doublons"]) == 1
        and len(double["ordre"]["op_jugement_enregistre"]) == 1
    )


def test_les_types_d_operation_sont_acceptes_par_le_registre_hash_chaine(ops):
    accepte(juger(ops))
    assert ops.valider_chaine() == (True, "")
    assert ops.lire()[0]["type_entree"] == "op_jugement_enregistre"
