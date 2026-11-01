"""Le module pur `constats_pour_m8` : la dépense publicitaire COMPTABILISÉE (D1) et les factures ÉMISES (D3) que M5
publie pour M8.

Sans base ni bus : un état du grand livre et des états de facture FICTIFS. Prouve : seules les écritures DÉFINITIVES
d'un relevé de
M7 (pièce `m7:…`) comptent, au solde net sur le compte de charge, à leur date d'effet (bornes incluses) ; l'origine et
sa
contre-passation s'annulent ; un brouillon est compté à part ; une écriture d'une autre origine ou d'un autre compte ne
compte
pas ; une période inversée ou de plus de 366 jours est refusée ; une facture BROUILLON ou annulée sans envoi n'est
jamais
publiée, et une charge de facture est exacte au cent, sans client. Données fictives.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from m5_financecore import constats_pour_m8 as c

FICTIF = True
COMPTE = "5950"


def _ecriture(statut, jour, montant, reference="m7:releve-1:r1", compte=COMPTE, sens="debit"):
    debit, credit = (montant, "0.00") if sens == "debit" else ("0.00", montant)
    return {
        "statut": statut,
        "date_effet": jour,
        "piece": {"reference": reference},
        "lignes": [
            {"compte": compte, "debit": debit, "credit": credit},
            {"compte": "2100", "debit": credit, "credit": debit},
        ],
    }


def _etat(*ecritures):
    return {
        "ordre": [f"e{i}" for i in range(len(ecritures))],
        "ecritures": {f"e{i}": e for i, e in enumerate(ecritures)},
    }


def _mesure(*ecritures, debut="2026-10-01", fin="2026-10-31"):
    mesure, raison = c.depense_publicitaire_comptabilisee(_etat(*ecritures), COMPTE, debut, fin)
    assert raison is None, raison
    return mesure


def test_seules_les_ecritures_definitives_d_un_releve_de_m7_comptent_au_solde_net():
    m = _mesure(
        _ecriture("DEFINITIVE", "2026-10-10", "100.00"),
        _ecriture("DEFINITIVE", "2026-10-11", "50.25", reference="m7:releve-2:r1"),
        _ecriture("BROUILLON", "2026-10-12", "75.00", reference="m7:releve-3:r1"),
        _ecriture("DEFINITIVE", "2026-10-13", "999.00", reference="manuel:facture-fournisseur-1"),
        _ecriture("DEFINITIVE", "2026-10-14", "888.00", compte="5800"),
    )
    assert m["comptabilise"] == Decimal("150.25") and m["ecritures_definitives"] == 2
    assert m["brouillons_en_attente"] == 1 and m["brouillons_en_attente_cad"] == Decimal("75.00")


def test_l_origine_et_sa_contre_passation_s_annulent_et_une_ecriture_hors_releve_ne_compte_jamais():
    origine = _ecriture("DEFINITIVE", "2026-10-10", "100.00")
    contre = _ecriture("DEFINITIVE", "2026-10-20", "100.00", sens="credit")
    assert _mesure(origine, contre)["comptabilise"] == Decimal("0.00")
    sans_releve = _mesure(_ecriture("DEFINITIVE", "2026-10-10", "100.00", reference="auto:autre-chose"))
    assert sans_releve["comptabilise"] == Decimal("0.00") and sans_releve["ecritures_definitives"] == 0
    brouillon_hors_releve = _mesure(_ecriture("BROUILLON", "2026-10-10", "10.00", reference="manuel:x"))
    assert brouillon_hors_releve["brouillons_en_attente"] == 0


def test_les_bornes_de_la_periode_sont_incluses_et_hors_periode_n_est_pas_compte():
    jours = ("2026-09-30", "2026-10-01", "2026-10-31", "2026-11-01")
    m = _mesure(*[_ecriture("DEFINITIVE", j, "10.00", reference=f"m7:r-{j}:r1") for j in jours])
    assert m["ecritures_definitives"] == 2 and m["comptabilise"] == Decimal("20.00")
    sans_date = _mesure(_ecriture("DEFINITIVE", None, "10.00"))
    assert sans_date["ecritures_definitives"] == 0


@pytest.mark.parametrize(
    ("debut", "fin"),
    [
        ("2026-10-31", "2026-10-01"),
        ("2026-02-30", "2026-03-01"),
        ("2025-01-01", "2026-12-31"),
        ("hier", "demain"),
        (None, None),
    ],
)
def test_une_periode_illisible_inversee_ou_trop_longue_est_refusee(debut, fin):
    mesure, raison = c.depense_publicitaire_comptabilisee(_etat(), COMPTE, debut, fin)
    assert mesure is None and raison


def test_une_periode_de_366_jours_est_permise_et_celle_de_367_refusee():
    assert c.depense_publicitaire_comptabilisee(_etat(), COMPTE, "2026-01-01", "2026-12-31")[0] is not None  # 365 jours
    assert (
        c.depense_publicitaire_comptabilisee(_etat(), COMPTE, "2024-01-01", "2024-12-31")[0] is not None
    )  # 366 (bissextile)
    assert c.depense_publicitaire_comptabilisee(_etat(), COMPTE, "2024-01-01", "2025-01-01")[0] is None  # 367


def test_la_charge_de_la_depense_est_la_forme_fermee_du_catalogue_et_la_version_suit_les_donnees():
    mesure = _mesure(
        _ecriture("DEFINITIVE", "2026-10-10", "100.00"),
        _ecriture("BROUILLON", "2026-10-12", "75.5", reference="m7:r2:r1"),
    )
    version = c.version_depense(mesure, "2026-10-01", "2026-10-31")
    charge = c.charge_depense_publicitaire(
        mesure, debut="2026-10-01", fin="2026-10-31", date_reference="2026-11-02", sequence=3, version_donnees=version
    )
    assert charge["comptabilise_cad"] == "100.00" and charge["brouillons_en_attente_cad"] == "75.50"
    assert charge["evenement_id"] == f"m5-depense-pub-3-2026-10-01-2026-10-31-{version}"
    assert charge["devise"] == "CAD" and charge["base_taxes"] == "HORS_TAXES" and len(version) == 16
    autre = _mesure(_ecriture("DEFINITIVE", "2026-10-10", "100.01"))
    assert c.version_depense(autre, "2026-10-01", "2026-10-31") != version
    assert c.version_depense(mesure, "2026-10-01", "2026-10-30") != version


def _facture(statut="ENVOYEE", **plus):
    etat = {
        "facture_id": "facture-1",
        "statut": statut,
        "date_envoi": "2026-10-29T14:00:00-04:00",
        "montant_avant_taxes": "1000",
        "total_taxes": "149.75",
        "montant_apres_taxes": "1149.75",
        "client_id": "client-fictif-1",
    }
    etat.update(plus)
    return etat


@pytest.mark.parametrize("statut", ["ENVOYEE", "PAYEE", "ANNULEE"])
def test_une_facture_envoyee_payee_ou_annulee_apres_envoi_est_publiee_sans_client(statut):
    charge = c.charge_facture_emise(_facture(statut))
    assert charge is not None and charge["statut"] == statut and charge["emise_le"] == "2026-10-29"
    assert charge["evenement_id"] == f"m5-facture-emise-facture-1-{statut}"
    assert (charge["montant_avant_taxes_cad"], charge["total_taxes_cad"], charge["montant_apres_taxes_cad"]) == (
        "1000.00",
        "149.75",
        "1149.75",
    )
    assert "client" not in str(charge)


def test_un_brouillon_n_est_jamais_publie_meme_avec_un_jour_d_envoi():
    assert c.charge_facture_emise(_facture("BROUILLON")) is None


def test_une_facture_annulee_qui_n_a_jamais_ete_envoyee_n_est_pas_emise():
    assert c.charge_facture_emise(_facture("ANNULEE", date_envoi=None)) is None
    assert c.charge_facture_emise(_facture("ENVOYEE", date_envoi="")) is None
    assert c.charge_facture_emise(_facture("ENVOYEE", date_envoi="pas-une-date")) is None


@pytest.mark.parametrize(
    "plus", [{"facture_id": ""}, {"facture_id": None}, {"montant_avant_taxes": "beaucoup"}, {"total_taxes": None}]
)
def test_une_facture_illisible_n_est_pas_publiee(plus):
    assert c.charge_facture_emise(_facture(**plus)) is None
