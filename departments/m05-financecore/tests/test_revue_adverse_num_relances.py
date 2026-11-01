"""Revue adverse (num) : la préparation quotidienne des relances (`operations_comptables.preparer_relances`).

Défaut trouvé : la clé d'idempotence est (facture, niveau) mais le corps comparé portait aussi `jours_retard`,
`date_reference`, `montant_du` et `texte`, qui changent chaque jour. Le lendemain d'une première relance, la même
facture au même niveau était un « autre contenu » : `REJ-OPS-DOUBLON` refusait TOUT le lot (aucune relance préparée pour
aucune autre facture) tant que le niveau ne montait pas. Données fictives.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m5_financecore import facturation, plan_comptable, taux_fiscaux
from m5_financecore import operations_comptables as oc
from m5_financecore import operations_registre as ore
from m5_financecore import registre as registre_module

FICTIF = True
_M5 = Path(__file__).resolve().parents[1]
H = "2026-10-15T10:00:00-04:00"
POLITIQUE = {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]}


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_M5 / "contracts" / "taux_fiscaux.v1.yaml")
    assert erreurs == []
    return dictionnaire


def _facture_envoyee(registre, taux, facture_id, envoi, prix="600.00"):
    lignes = [{"description": "travaux (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": prix,
               "reference_ligne_devis": "L1"}]
    assert facturation.creer_facture_brouillon(
        facture_id, "CH-1", f"D-{facture_id}", "client-1", lignes, f"{envoi}T09:00:00-04:00", taux, registre)[1] is None
    assert facturation.envoyer_facture(facture_id, f"{envoi}T10:00:00-04:00", registre)[1] is None


def _preparer(ops, factures, aujourd_hui):
    etat = ore.etat_operations(ops.lire())
    assert etat["anomalies"] == []
    return oc.preparer_relances(ops, etat, list(factures), POLITIQUE, aujourd_hui, H)


def test_la_relance_du_lendemain_au_meme_niveau_ne_bloque_pas_le_lot(taux):
    reg_factures, ops = registre_module.Registre(), registre_module.Registre()
    _facture_envoyee(reg_factures, taux, "F-1", "2026-09-01")  # échéance 2026-10-01
    _facture_envoyee(reg_factures, taux, "F-2", "2026-09-08")  # échéance 2026-10-08
    factures = facturation.factures_par_statut(reg_factures, "ENVOYEE")

    premier, refus = _preparer(ops, factures, "2026-10-08")  # F-1 : 7 jours de retard, niveau 1 ; F-2 : pas en retard
    assert refus is None and [c["facture_id"] for c in premier["creees"]] == ["F-1"]

    # Le jour suivant le niveau de F-1 n'a pas bougé (8 jours de retard) : rien à refaire pour elle, mais le lot
    # ne doit pas être refusé.
    lendemain, refus = _preparer(ops, factures, "2026-10-09")
    assert refus is None, refus
    assert lendemain["creees"] == [] and lendemain["deja"] == 1 and lendemain["sans_retard"] == 1

    # Une semaine plus tard, F-2 atteint son niveau 1 : elle est préparée malgré la relance déjà existante de F-1.
    semaine = _preparer(ops, factures, "2026-10-15")
    resultat, refus = semaine
    assert refus is None, refus
    assert [c["facture_id"] for c in resultat["creees"]] == ["F-2"] and resultat["deja"] == 1
    assert len(ore.etat_operations(ops.lire())["par_type"]["op_relance_preparee"]) == 2


def test_un_credit_partiel_entre_deux_passages_est_signale_sans_bloquer_le_lot(taux):
    plan, refus = plan_comptable.charger_plan(_M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None
    reg_factures, ops, gl = registre_module.Registre(), registre_module.Registre(), registre_module.Registre()
    _facture_envoyee(reg_factures, taux, "F-1", "2026-09-01")
    _facture_envoyee(reg_factures, taux, "F-2", "2026-09-08")
    assert _preparer(ops, facturation.factures_par_statut(reg_factures, "ENVOYEE"), "2026-10-08")[1] is None
    facture = facturation.facture_active_pour_devis(reg_factures, "D-F-1")
    note, refus = oc.proposer_note_credit(
        ops, ore.etat_operations(ops.lire()), gl, plan, taux, genre="client", facture=facture, reference="NC-1",
        montant_avant_taxes="100.00", date_effet="2026-10-09", motif="rabais convenu", horodatage=H)
    assert refus is None, refus
    resultat, refus = _preparer(ops, facturation.factures_par_statut(reg_factures, "ENVOYEE"), "2026-10-15")
    assert refus is None, refus  # F-1 : montant dû changé ; F-2 : niveau 1 atteint aujourd'hui
    assert [c["facture_id"] for c in resultat["creees"]] == ["F-2"]
    assert [(i["facture_id"], i["code"]) for i in resultat["ignorees"]] == [("F-1", "REJ-OPS-DOUBLON")]
    assert len(ore.etat_operations(ops.lire())["par_type"]["op_relance_preparee"]) == 2


def test_le_niveau_suivant_cree_toujours_une_nouvelle_relance(taux):
    reg_factures, ops = registre_module.Registre(), registre_module.Registre()
    _facture_envoyee(reg_factures, taux, "F-1", "2026-09-01")
    factures = facturation.factures_par_statut(reg_factures, "ENVOYEE")
    assert _preparer(ops, factures, "2026-10-08")[1] is None  # niveau 1
    resultat, refus = _preparer(ops, factures, "2026-10-22")  # 21 jours de retard : niveau 2
    assert refus is None and [(c["facture_id"], c["niveau"]) for c in resultat["creees"]] == [("F-1", 2)]
    assert len(ore.etat_operations(ops.lire())["par_type"]["op_relance_preparee"]) == 2
    # Le texte du niveau 2 cite les jours de retard : le lendemain, il a changé, la relance reste la même.
    lendemain, refus = _preparer(ops, factures, "2026-10-23")
    assert refus is None and lendemain["creees"] == [] and lendemain["deja"] == 1


def test_une_autre_echeance_pour_la_meme_cle_n_est_jamais_recrite(taux):
    """L'identité d'une relance reste (facture, niveau, échéance, montant dû) : un autre contenu n'écrase rien."""
    reg_factures, ops = registre_module.Registre(), registre_module.Registre()
    _facture_envoyee(reg_factures, taux, "F-1", "2026-09-01")
    factures = facturation.factures_par_statut(reg_factures, "ENVOYEE")
    assert _preparer(ops, factures, "2026-10-08")[1] is None
    autre = {"delai_echeance_jours": 31, "paliers_jours_apres_echeance": [7, 21, 45]}  # échéance 2026-10-02
    etat = ore.etat_operations(ops.lire())
    resultat, refus = oc.preparer_relances(ops, etat, list(factures), autre, "2026-10-09", H)
    assert refus is None and resultat["creees"] == []
    assert [i["code"] for i in resultat["ignorees"]] == ["REJ-OPS-DOUBLON"]
    assert len(ore.etat_operations(ops.lire())["par_type"]["op_relance_preparee"]) == 1
