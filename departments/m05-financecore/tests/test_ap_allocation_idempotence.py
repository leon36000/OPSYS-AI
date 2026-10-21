"""Comptes à payer (PLAN T4.15, T4.15-c) : allocation sur plusieurs PO et idempotence de la réception, en pur.

Deux choses que ces tests fixent, à la cent près :
- ALLOCATION : réceptions partielles, deux PO, plusieurs factures, correction, annulation puis ressaisie ne doublent
  ni ne perdent la dette. À chaque geste, le total « à payer » est recalculé à la main (TPS 5 %, TVQ 9,975 %,
  `ROUND_HALF_UP` au cent, taxes de chaque facture et du reste non facturé arrondies séparément).
- IDEMPOTENCE : la même réception (`evenement_id`) redélivrée telle quelle n'écrit rien ; le même `evenement_id`
  avec une AUTRE charge est un conflit refusé sans écriture (contrat du bus : `ConflitPublication`), jamais une
  redélivrance silencieuse qui avalerait la nouvelle charge.

Montants calculés à la main :
- 300.00 : TPS 15.00, TVQ 29.925 -> 29.93, total 344.93
- 20.00 : TPS 1.00, TVQ 1.995 -> 2.00, total 23.00
- 290.00 : TPS 14.50, TVQ 28.9275 -> 28.93, total 333.43
- 10.00 : TPS 0.50, TVQ 0.9975 -> 1.00, total 11.50
Identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer as ap
from m5_financecore import registre

FICTIF = True
_spec = importlib.util.spec_from_file_location(
    "ap_pur_fictif", Path(__file__).resolve().parent / "test_comptes_a_payer.py"
)
_f = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_f)
taux = _f.taux
SAISIE = _f.SAISIE
LIVRAISON_1 = _f.LIVRAISON_1
LIVRAISON_2 = _f.LIVRAISON_2


def _total(reg, taux):
    resume, verdict = ap.resume_a_payer(reg, taux)
    assert verdict is None, verdict
    dettes, verdict = ap.dettes_datables(reg, taux)
    assert verdict is None, verdict
    assert resume["complet"] is True
    assert sum((d["montant"] for d in dettes), Decimal("0")) == resume["a_payer_apres_taxes"], (
        "les dettes datables et le résumé disent la même dette"
    )
    return resume["a_payer_apres_taxes"]


def _po(reg, taux, po_id):
    return _f._po(reg, taux, po_id=po_id)


def _revision_lue(reg, ident):
    """`corrections` de la facture lue juste avant le geste (absent au statut SAISIE : 0) ; inconnue : `KeyError`."""
    vue = ap.vue_facture(ap._etats_factures(reg.lire())[ident])
    if "corrections" not in vue:
        assert vue["statut"] == "SAISIE", vue
        return 0
    return vue["corrections"]


def _corriger(reg, taux, ident, montant):
    return ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ident, motif="avoir fournisseur fictif", numero_facture=None, date_facture=None,
        montant_avant_taxes=montant, total_facture=None, corrige_par="finance.fictive", role="finance",
        voie="approbation", horodatage=SAISIE, dictionnaire_taux=taux, registre_cible=reg,
        revision_attendue=_revision_lue(reg, ident))


def _annuler(reg, ident):
    return ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ident, motif="saisie sur la mauvaise pièce, fictif", annule_par="finance.fictive",
        role="finance", voie="approbation", horodatage=SAISIE, registre_cible=reg,
        revision_attendue=_revision_lue(reg, ident))


# ========================================================================= allocation : ni double ni perte
def test_deux_po_receptions_partielles_factures_correction_annulation_ressaisie_ni_double_ni_perte(taux):
    reg = registre.Registre()

    _f._recevoir(reg, evenement_id="evt-a1", po_id="PO-A", gouttiere="60", vis="0", horodatage=LIVRAISON_1)
    assert _total(reg, taux) == Decimal("344.93")
    _f._recevoir(reg, evenement_id="evt-b1", po_id="PO-B", gouttiere="60", vis="0", horodatage=LIVRAISON_1)
    assert _total(reg, taux) == Decimal("689.86"), "deux PO reçus : deux attendus"

    f1 = _f._facturer_ok(reg, taux, numero="F-1", montant="300.00", po="PO-A")["facture"]
    assert _total(reg, taux) == Decimal("689.86"), "la facture remplace l'attendu du PO-A, elle ne s'y ajoute pas"
    assert _po(reg, taux, "PO-B")["a_payer_apres_taxes"] == "344.93", "le PO-B n'est touché par aucune facture"

    _f._recevoir(reg, evenement_id="evt-a2", po_id="PO-A", gouttiere="0", vis="40", horodatage=LIVRAISON_2)
    po_a = _po(reg, taux, "PO-A")
    assert po_a["attendu_non_facture_apres_taxes"] == "23.00"
    assert po_a["a_payer_apres_taxes"] == "367.93", "344.93 facturé + 23.00 reçu non facturé, taxés séparément"
    assert _total(reg, taux) == Decimal("712.86")

    _f._facturer_ok(reg, taux, numero="F-2", montant="20.00", po="PO-A")
    assert _po(reg, taux, "PO-A")["rapprochement"]["verdict"] == "CONCORDANT"
    assert _total(reg, taux) == Decimal("712.86")

    resultat, verdict = _corriger(reg, taux, f1["facture_fournisseur_id"], "290.00")
    assert verdict is None, verdict
    po_a = _po(reg, taux, "PO-A")
    assert po_a["rapprochement"]["verdict"] == "ECART"
    assert po_a["attendu_non_facture_apres_taxes"] == "11.50"
    assert po_a["a_payer_apres_taxes"] == "367.93", "333.43 + 23.00 + 11.50 : l'avoir rouvre le reste attendu"
    assert _total(reg, taux) == Decimal("712.86")

    resultat, verdict = _annuler(reg, f1["facture_fournisseur_id"])
    assert verdict is None, verdict
    po_a = _po(reg, taux, "PO-A")
    assert po_a["attendu_non_facture_apres_taxes"] == "344.93" and po_a["factures_annulees"] == 1
    assert _total(reg, taux) == Decimal("712.86"), "annuler ne fait pas disparaître la dette : l'attendu revient"

    ressaisie = _f._facturer_ok(reg, taux, numero="F-1", montant="300.00", po="PO-A")["facture"]
    assert ressaisie["facture_fournisseur_id"] != f1["facture_fournisseur_id"]
    po_a = _po(reg, taux, "PO-A")
    assert po_a["rapprochement"]["verdict"] == "CONCORDANT" and po_a["factures"]["nombre"] == 2
    assert _total(reg, taux) == Decimal("712.86")

    _f._facturer_ok(reg, taux, numero="F-3", montant="300.00", po="PO-B")
    assert _total(reg, taux) == Decimal("712.86")
    vivantes = ap.factures_saisies(reg)
    assert sorted(f["numero_facture"] for f in vivantes) == ["F-1", "F-2", "F-3"]
    assert sum((f["montant_apres_taxes"] for f in vivantes), Decimal("0")) == Decimal("712.86")


@pytest.mark.parametrize("numero", ["F-1", " f-1 ", "F-1  ", "f-1"])
def test_meme_fournisseur_meme_numero_normalise_meme_montant_sur_l_autre_po_est_un_doublon_sans_ecriture(
    taux, numero
):
    reg = registre.Registre()
    _f._recevoir(reg, evenement_id="evt-a1", po_id="PO-A")
    _f._recevoir(reg, evenement_id="evt-b1", po_id="PO-B")
    _f._facturer_ok(reg, taux, numero="F-1", montant="300.00", po="PO-A")
    avant = reg.lire()

    resultat, verdict = _f._facturer(reg, taux, numero=numero, montant="300.00", po="PO-B")

    assert resultat is None and verdict["code"] == "REJ-AP-FACTURE-DOUBLON"
    assert reg.lire() == avant
    assert _total(reg, taux) == Decimal("689.86"), "le PO-B reste un attendu : la dette n'est pas perdue"


def test_meme_numero_autre_montant_sur_l_autre_po_passe_avec_l_avertissement_sur_les_deux(taux):
    reg = registre.Registre()
    _f._recevoir(reg, evenement_id="evt-a1", po_id="PO-A")
    _f._recevoir(reg, evenement_id="evt-b1", po_id="PO-B")
    _f._facturer_ok(reg, taux, numero="F-1", montant="300.00", po="PO-A")

    resultat = _f._facturer_ok(reg, taux, numero="f-1", montant="290.00", po="PO-B")

    assert resultat["avertissements"] == [ap.CODE_NUMERO_REPETE]
    assert all(f["avertissements"] == [ap.CODE_NUMERO_REPETE] for f in ap.factures_saisies(reg))
    assert _total(reg, taux) == Decimal("344.93") + Decimal("333.43") + Decimal("11.50")


# ================================================================= idempotence de la réception (même clé)
def test_la_meme_reception_redelivree_telle_quelle_n_ecrit_rien(taux):
    reg = registre.Registre()
    premier, deja = _f._recevoir(reg, evenement_id="evt-1")
    assert deja is False

    rejoue, deja = _f._recevoir(reg, evenement_id="evt-1")

    assert deja is True and rejoue == premier and reg.taille() == 1
    assert _total(reg, taux) == Decimal("344.93")


@pytest.mark.parametrize(
    "surcharge",
    [
        {"gouttiere": "59"},
        {"vis": "40"},
        {"po_id": "PO-2"},
        {"fournisseur": "royal"},
        {"chantier": "CH-AUTRE"},
        {"horodatage": LIVRAISON_2},
        {"hash_maillon": "b" * 64},
        {"verdict": "CONFORME", "statut": "received"},
    ],
)
def test_le_meme_evenement_avec_une_autre_charge_est_un_conflit_refuse_sans_ecriture(taux, surcharge):
    reg = registre.Registre()
    _f._recevoir(reg, evenement_id="evt-1")
    avant = reg.lire()
    entree, verdict = ap.construire_reception(_f._charge(evenement_id="evt-1", **surcharge))
    assert verdict is None, verdict

    resultat, verdict = ap.enregistrer_reception(entree, reg)

    assert resultat is None and verdict["code"] == "REJ-AP-RECEPTION-CONFLIT"
    assert "evt-1" in verdict["detail"]
    assert reg.lire() == avant
    assert _total(reg, taux) == Decimal("344.93")



def test_une_redelivrance_exacte_reste_deja_recue_meme_si_les_champs_derives_ont_change():
    """Ce que M5 DÉRIVE (montants, écarts, `manque`) peut changer d'une version du calcul à l'autre : seule la charge
    retenue de M6 décide du conflit, jamais un recalcul."""
    reg = registre.Registre()
    entree, verdict = ap.construire_reception(_f._charge(evenement_id="evt-1"))
    assert verdict is None
    lignes = [{**ligne, "montant_attendu": None, "ecart_prix_unitaire": None} for ligne in entree["lignes"]]
    ancienne = {**entree, "manque": ["REJ-AP-PRIX-PO-ABSENT"], "montant_avant_taxes": None, "lignes": lignes}
    reg.ajouter(ancienne)

    resultat, verdict = ap.enregistrer_reception(entree, reg)

    assert verdict is None and resultat[1] is True and reg.taille() == 1
