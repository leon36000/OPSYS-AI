"""Vérification préparatoire des factures fournisseur, sans aucune écriture au registre."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer as ap
from m5_financecore import registre, taux_fiscaux

FICTIF = True
_CHEMIN_TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
SAISIE = "2026-10-08T10:00:00-04:00"


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX)
    assert erreurs == []
    return dictionnaire


def _recevoir(reg):
    charge = {
        "evenement_id": "evt-ap-verification",
        "po_id": "PO-VERIFICATION",
        "fournisseur_id": "fournisseur-fictif",
        "chantier_id": "CH-VERIFICATION",
        "horodatage_reception": "2026-10-07T10:00:00-04:00",
        "verdict_reception": "RECEPTION_INFERIEURE",
        "statut_po": "partially_received",
        "hash_maillon": "a" * 64,
        "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{
            "materiau_id": "article-fictif",
            "quantite_demandee": "20",
            "quantite_recue": "10",
            "prix_unitaire_prevu": "30.00",
            "devise_prevue": "CAD",
            "verdict_prix_po": "PRIX_LIVRE",
            "prix_unitaire_reception": "30.00",
            "verdict_prix_reception": "PRIX_CATALOGUE",
            "ecart_prix_critique": False,
        }],
    }
    entree, verdict = ap.construire_reception(charge)
    assert verdict is None, verdict
    resultat, verdict = ap.enregistrer_reception(entree, reg)
    assert verdict is None, verdict
    return resultat


def _saisir(reg, taux, *, numero="F-VERIF-1", montant="300.00", fournisseur="fournisseur-fictif"):
    return ap.saisir_facture_fournisseur(
        po_id="PO-VERIFICATION",
        fournisseur_id=fournisseur,
        numero_facture=numero,
        date_facture="2026-10-07",
        montant_avant_taxes=montant,
        total_facture=None,
        saisi_par="proprietaire-fictif",
        voie="appareil",
        horodatage=SAISIE,
        dictionnaire_taux=taux,
        registre_cible=reg,
    )


def _verifier(maillons, taux, *, numero="F-VERIF-1", montant="300.00", fournisseur="fournisseur-fictif",
              total=None):
    return ap.verifier_facture_fournisseur(
        po_id="PO-VERIFICATION",
        fournisseur_id=fournisseur,
        numero_facture=numero,
        date_facture="2026-10-07",
        montant_avant_taxes=montant,
        total_facture=total,
        saisi_par="proprietaire-fictif",
        voie="appareil",
        horodatage=SAISIE,
        dictionnaire_taux=taux,
        maillons=maillons,
    )


def test_verifier_prepare_les_memes_montants_et_ne_laisse_aucune_piece(taux):
    reg = registre.Registre()
    _recevoir(reg)
    avant = reg.lire()

    resultat, verdict = _verifier(avant, taux, numero=" F-VERIF-1 ", total="344.93")

    assert verdict is None
    assert resultat == {
        "po_id": "PO-VERIFICATION",
        "fournisseur_id": "fournisseur-fictif",
        "numero_facture": "F-VERIF-1",
        "date_facture": "2026-10-07",
        "montant_avant_taxes": Decimal("300.00"),
        "taxes": [
            {
                "id": "tps_federale",
                "nom": "Taxe sur les produits et services (fédérale)",
                "version": "2026-v1",
                "taux": "0.05",
                "montant": Decimal("15.00"),
            },
            {
                "id": "tvq_quebec",
                "nom": "Taxe de vente du Québec",
                "version": "2026-v1",
                "taux": "0.09975",
                "montant": Decimal("29.93"),
            },
        ],
        "total_taxes": Decimal("44.93"),
        "montant_apres_taxes": Decimal("344.93"),
        "avertissements": [],
    }
    assert reg.lire() == avant, "la vérification n'écrit rien, même avec un total concordant"


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"total": "344.92"}, "REJ-AP-FACTURE-TOTAL-INCOHERENT"),
        ({"po": "PO-ABSENT"}, "REJ-AP-FACTURE-PO-SANS-RECEPTION"),
        ({"fournisseur": "autre-fournisseur"}, "REJ-AP-FACTURE-FOURNISSEUR-DIFFERENT-DU-PO"),
    ],
)
def test_verifier_refuse_total_po_ou_fournisseur_incoherent_sans_ecriture(taux, options, code):
    reg = registre.Registre()
    _recevoir(reg)
    avant = reg.lire()
    total = options.get("total")
    resultat, verdict = ap.verifier_facture_fournisseur(
        po_id=options.get("po", "PO-VERIFICATION"),
        fournisseur_id=options.get("fournisseur", "fournisseur-fictif"),
        numero_facture="F-VERIF-1",
        date_facture="2026-10-07",
        montant_avant_taxes="300.00",
        total_facture=total,
        saisi_par="proprietaire-fictif",
        voie="appareil",
        horodatage=SAISIE,
        dictionnaire_taux=taux,
        maillons=avant,
    )

    assert resultat is None and verdict["code"] == code
    assert reg.lire() == avant


def test_verifier_detecte_doublon_et_numero_repris_a_un_autre_montant(taux):
    reg = registre.Registre()
    _recevoir(reg)
    _saisir(reg, taux)
    avant = reg.lire()

    resultat, verdict = _verifier(avant, taux)
    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON"
    assert reg.lire() == avant

    resultat, verdict = _verifier(avant, taux, montant="301.00")
    assert verdict is None and resultat["avertissements"] == [ap.CODE_NUMERO_REPETE]
    assert reg.lire() == avant


def test_snapshot_iterable_est_materialise_une_seule_fois_pour_les_doublons(taux):
    reg = registre.Registre()
    _recevoir(reg)
    assert _saisir(reg, taux)[1] is None
    avant = reg.lire()
    resultat, verdict = _verifier((row for row in avant), taux)
    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON"
    assert reg.lire() == avant


def test_verifier_evalue_doublons_sur_correction_et_annulation_a_leur_etat_courant(taux):
    reg = registre.Registre()
    _recevoir(reg)
    facture = _saisir(reg, taux)[0]["facture"]
    correction, verdict = ap.corriger_facture_fournisseur(
        facture_fournisseur_id=facture["facture_fournisseur_id"],
        motif="montant saisi à corriger",
        numero_facture=None,
        date_facture=None,
        montant_avant_taxes="301.00",
        total_facture=None,
        corrige_par="proprietaire-fictif",
        role="admin",
        voie="appareil",
        horodatage=SAISIE,
        dictionnaire_taux=taux,
        registre_cible=reg,
        revision_attendue=facture["corrections"],
    )
    assert verdict is None and correction["facture"]["statut"] == "CORRIGEE"

    maillons = reg.lire()
    resultat, verdict = _verifier(maillons, taux, montant="300.00")
    assert verdict is None and resultat["avertissements"] == [ap.CODE_NUMERO_REPETE]
    resultat, verdict = _verifier(maillons, taux, montant="301.00")
    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON"
    assert reg.lire() == maillons

    annulee, verdict = ap.annuler_facture_fournisseur(
        facture_fournisseur_id=facture["facture_fournisseur_id"],
        motif="annulation fictive pour vérification",
        annule_par="proprietaire-fictif",
        role="admin",
        voie="appareil",
        horodatage=SAISIE,
        registre_cible=reg,
        revision_attendue=correction["facture"]["corrections"],
    )
    assert verdict is None and annulee["facture"]["statut"] == "ANNULEE"
    maillons_annules = reg.lire()
    resultat, verdict = _verifier(maillons_annules, taux, montant="301.00")
    assert verdict is None and resultat["avertissements"] == []
    assert reg.lire() == maillons_annules
