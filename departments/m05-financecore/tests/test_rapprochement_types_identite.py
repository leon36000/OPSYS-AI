"""Régression fictive : le rapprochement identifie une pièce par type et référence."""

from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import grand_livre, plan_comptable, registre, taux_fiscaux

_M5 = Path(__file__).resolve().parents[1]
_H = "2026-10-15T10:00:00-04:00"
_HUMAIN = {"par": "comptable", "role": "finance", "voie": "approbation"}


@pytest.fixture
def contexte():
    plan, refus = plan_comptable.charger_plan(_M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None, refus
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(_M5 / "contracts" / "taux_fiscaux.v1.yaml")
    assert erreurs == []
    return plan, taux, registre.Registre()


def _ecriture_note(reg, plan, reference, *, fournisseur):
    if fournisseur:
        lignes = [
            {"compte": "2100", "debit": "14.98", "credit": None},
            {"compte": "1400", "debit": None, "credit": "5.00"},
            {"compte": "1410", "debit": None, "credit": "9.98"},
        ]
    else:
        lignes = [
            {"compte": "2300", "debit": "5.00", "credit": None},
            {"compte": "2310", "debit": "9.98", "credit": None},
            {"compte": "1100", "debit": None, "credit": "14.98"},
        ]
    proposee, refus = grand_livre.proposer_ecriture(
        reg,
        plan,
        cle_piece=f"auto:note_credit:fictive:{reference}",
        piece={"type": "note_credit", "reference": reference},
        nature="note_credit_fournisseur" if fournisseur else "note_credit_client",
        date_effet="2026-10-15",
        libelle="Note de crédit fictive",
        lignes_brutes=lignes,
        horodatage=_H,
        origine="operations_comptables",
    )
    assert refus is None, refus
    _, refus = grand_livre.valider_ecriture(
        reg,
        plan,
        ecriture_id=proposee["ecriture"]["ecriture_id"],
        humain=_HUMAIN,
        horodatage=_H,
    )
    assert refus is None, refus


@pytest.mark.parametrize(
    ("fournisseur", "role_tps", "role_tvq", "attendu_tps", "attendu_tvq"),
    [
        (False, "tps_a_percevoir", "tvq_a_percevoir", "5.00", "9.98"),
        (True, "tps_cti", "tvq_rti", "5.00", "9.98"),
    ],
)
def test_collision_facture_note_ne_masque_pas_facture_sans_ecriture(
    contexte, fournisseur, role_tps, role_tvq, attendu_tps, attendu_tvq
):
    plan, taux, reg = contexte
    reference = "ncr-collision-fictive"
    _ecriture_note(reg, plan, reference, fournisseur=fournisseur)
    facture = (
        {
            "facture_fournisseur_id": reference,
            "statut": "SAISIE",
            "date_facture": "2026-10-15",
            "montant_avant_taxes": Decimal("100.00"),
            "total_taxes": Decimal("14.98"),
            "montant_apres_taxes": Decimal("114.98"),
            "taxes": [
                {"id": "tps_federale", "montant": Decimal("5.00")},
                {"id": "tvq_quebec", "montant": Decimal("9.98")},
            ],
        }
        if fournisseur
        else {
            "facture_id": reference,
            "statut": "ENVOYEE",
            "date_envoi": "2026-10-15",
            "montant_avant_taxes": Decimal("100.00"),
        }
    )
    role_taxes = (
        {"tps_cti": Decimal("-5.00"), "tvq_rti": Decimal("-9.98")}
        if fournisseur
        else {"tps_a_percevoir": Decimal("-5.00"), "tvq_a_percevoir": Decimal("-9.98")}
    )
    autres = [
        {
            "piece_type": "note_credit",
            "reference": reference,
            "date_effet": "2026-10-15",
            "taxes": role_taxes,
        }
    ]
    resultat, refus = grand_livre.rapprocher(
        grand_livre.etat_grand_livre(reg.lire()),
        plan,
        [] if fournisseur else [facture],
        taux,
        debut="2026-10-01",
        fin="2026-10-31",
        factures_fournisseurs=[facture] if fournisseur else (),
        autres_pieces_taxees=autres,
    )
    assert refus is None, refus
    assert resultat["verdict"] == "ECART"
    taxes = resultat["intrants"] if fournisseur else resultat["taxes"]
    for role, attendu in ((role_tps, attendu_tps), (role_tvq, attendu_tvq)):
        rapprochement = taxes[role]
        assert rapprochement["attendu_factures_fournisseurs" if fournisseur else "attendu_taxes_py"] == "0.00"
        assert rapprochement["verdict"] == "ECART"
        assert rapprochement["ecarts"] == [
            {
                "facture_fournisseur_id" if fournisseur else "facture_id": reference,
                "piece_type": "facture_fournisseur" if fournisseur else "facture_client",
                "attendu_facture" if fournisseur else "attendu_taxes": attendu,
                "au_grand_livre": "0.00",
                "raison": "sans écriture définitive",
            }
        ]


def test_collision_facture_fournisseur_depense_employe_garde_les_deux_attendus(contexte):
    plan, taux, reg = contexte
    reference = "dep-collision-fictive"
    lignes = [
        {"compte": "5400", "debit": "100.00", "credit": None},
        {"compte": "1400", "debit": "5.00", "credit": None},
        {"compte": "1410", "debit": "9.98", "credit": None},
        {"compte": "2100", "debit": None, "credit": "114.98"},
    ]
    proposition, refus = grand_livre.proposer_ecriture(
        reg,
        plan,
        cle_piece=f"auto:depense_employe:fictive:{reference}",
        piece={"type": "depense_employe", "reference": reference},
        nature="depense_employe",
        date_effet="2026-10-15",
        libelle="Dépense employé fictive",
        lignes_brutes=lignes,
        horodatage=_H,
        origine="operations_comptables",
    )
    assert refus is None, refus
    _, refus = grand_livre.valider_ecriture(
        reg,
        plan,
        ecriture_id=proposition["ecriture"]["ecriture_id"],
        humain=_HUMAIN,
        horodatage=_H,
    )
    assert refus is None, refus
    facture = {
        "facture_fournisseur_id": reference,
        "statut": "SAISIE",
        "date_facture": "2026-10-15",
        "montant_avant_taxes": Decimal("100.00"),
        "total_taxes": Decimal("14.98"),
        "montant_apres_taxes": Decimal("114.98"),
        "taxes": [
            {"id": "tps_federale", "montant": Decimal("5.00")},
            {"id": "tvq_quebec", "montant": Decimal("9.98")},
        ],
    }
    resultat, refus = grand_livre.rapprocher(
        grand_livre.etat_grand_livre(reg.lire()),
        plan,
        [],
        taux,
        debut="2026-10-01",
        fin="2026-10-31",
        factures_fournisseurs=[facture],
        autres_pieces_taxees=[
            {
                "piece_type": "depense_employe",
                "reference": reference,
                "date_effet": "2026-10-15",
                "taxes": {"tps_cti": Decimal("5.00"), "tvq_rti": Decimal("9.98")},
            }
        ],
    )
    assert refus is None, refus
    for role, attendu in (("tps_cti", "5.00"), ("tvq_rti", "9.98")):
        rapprochement = resultat["intrants"][role]
        attendu_total = "10.00" if role == "tps_cti" else "19.96"
        assert rapprochement["attendu_factures_fournisseurs"] == attendu_total
        assert rapprochement["verdict"] == "ECART"
        assert rapprochement["ecarts"] == [
            {
                "facture_fournisseur_id": reference,
                "piece_type": "facture_fournisseur",
                "attendu_facture": attendu,
                "au_grand_livre": "0.00",
                "raison": "sans écriture définitive",
            }
        ]


def test_ordre_des_ecarts_reste_trie_par_reference_entre_types(contexte):
    plan, taux, reg = contexte
    factures = [
        {
            "facture_id": ident,
            "statut": "ENVOYEE",
            "date_envoi": "2026-10-15",
            "montant_avant_taxes": Decimal("100.00"),
        }
        for ident in ("a-facture", "z-facture")
    ]
    resultat, refus = grand_livre.rapprocher(
        grand_livre.etat_grand_livre(reg.lire()),
        plan,
        factures,
        taux,
        debut="2026-10-01",
        fin="2026-10-31",
        autres_pieces_taxees=[
            {
                "piece_type": "note_credit",
                "reference": "m-note",
                "date_effet": "2026-10-15",
                "taxes": {"tps_a_percevoir": Decimal("-5.00"), "tvq_a_percevoir": Decimal("-9.98")},
            }
        ],
    )
    assert refus is None, refus
    assert [
        ecart["facture_id"] for ecart in resultat["taxes"]["tps_a_percevoir"]["ecarts"]
    ] == ["a-facture", "m-note", "z-facture"]
