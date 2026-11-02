"""Échéance PROPRE d'une facture : statut « en retard » calculé à une date injectée, comptes à recevoir et relances de
créance (M5-FACT-1). Module pur, registres en mémoire, aucune horloge, données fictives.

Ces tests n'utilisent que des fonctions qui existaient avant le chantier (`facturation.comptes_a_recevoir`,
`operations_comptables.preparer_relances`) et un maillon d'envoi écrit à la main : ils sont ROUGES sur la ligne d'avant
(assertions, pas des erreurs d'import) et verts après.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from m5_financecore import facturation, operations_comptables, operations_registre, taux_fiscaux
from m5_financecore import registre as registre_module

FICTIF = True
H = "2026-11-02T10:00:00-05:00"
TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
LIGNE = [
    {
        "description": "Travaux (fictif)",
        "quantite": "1",
        "unite": "forfait",
        "prix_unitaire": "600.00",
        "reference_ligne_devis": "L1",
    }
]
POLITIQUE = {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]}


def _taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(TAUX)
    assert erreurs == []
    return dictionnaire


def _envoyee(facture_id="F-1", *, echeance=None, numero=None, envoi=H):
    """Une facture ENVOYEE dont le maillon d'envoi porte (ou non) l'échéance et le numéro fixés à l'émission."""
    registre = registre_module.Registre()
    _, verdict = facturation.creer_facture_brouillon(
        facture_id, "CH-1", f"D-{facture_id}", "client-1", LIGNE, H, _taux(), registre
    )
    assert verdict is None
    entree = {
        "type_entree": "transition_facture",
        "facture_id": facture_id,
        "statut": "ENVOYEE",
        "date_envoi": envoi,
        "horodatage": envoi,
    }
    if echeance is not None:
        entree["echeance"] = echeance
    if numero is not None:
        entree["numero_facture"] = numero
    registre.ajouter(entree)
    return registre


def _a_recevoir(registre, aujourd_hui):
    resultat, verdict = facturation.comptes_a_recevoir(registre, aujourd_hui)
    assert verdict is None
    return resultat


def test_une_facture_est_en_retard_seulement_apres_son_echeance_a_la_date_injectee():
    registre = _envoyee(echeance="2026-12-02", numero="F-01000")
    veille = _a_recevoir(registre, "2026-12-02")
    assert veille["factures"][0]["statut_effectif"] == "ENVOYEE" and veille["en_retard"]["nombre"] == 0
    assert veille["factures"][0]["numero_facture"] == "F-01000" and veille["factures"][0]["echeance"] == "2026-12-02"
    lendemain = _a_recevoir(registre, "2026-12-03")
    [facture] = lendemain["factures"]
    assert (facture["statut_effectif"], facture["jours_de_retard"]) == ("EN_RETARD", 1)
    assert lendemain["en_retard"] == {"nombre": 1, "total": Decimal("689.85")}
    assert facturation.etats_des_factures(registre)[0]["statut"] == "ENVOYEE"  # le statut enregistré ne bouge pas


def test_sans_date_injectee_le_retard_n_est_pas_calcule_et_sans_echeance_il_n_est_pas_calculable():
    avec = _a_recevoir(_envoyee(echeance="2026-12-02"), None)
    assert avec["en_retard"] is None and avec["factures"][0]["statut_effectif"] == "ENVOYEE"
    sans = _a_recevoir(_envoyee(), "2030-01-01")
    assert sans["factures"][0]["statut_effectif"] == "ENVOYEE" and sans["factures"][0]["retard_calculable"] is False
    assert sans["en_retard"] == {"nombre": 0, "total": Decimal("0")}


def _relances(factures, aujourd_hui):
    registre_ops = registre_module.Registre()
    etat = operations_registre.etat_operations([])
    resultat, refus = operations_comptables.preparer_relances(registre_ops, etat, factures, POLITIQUE, aujourd_hui, H)
    assert refus is None, refus
    return resultat, registre_ops


def _etat_envoye(**plus):
    return {
        "facture_id": "F-1",
        "statut": "ENVOYEE",
        "client_id": "client-1",
        "date_envoi": "2026-11-02T10:00:00-05:00",
        "montant_apres_taxes": Decimal("689.85"),
        **plus,
    }


def test_la_relance_suit_l_echeance_propre_de_la_facture_pas_le_delai_general():
    # échéance propre : le jour même de l'émission ; 8 jours de retard le 10 novembre, palier 7 atteint.
    resultat, _ = _relances([_etat_envoye(echeance="2026-11-02")], "2026-11-10")
    [creee] = resultat["creees"]
    assert (creee["niveau"], creee["jours_retard"], creee["echeance"]) == (1, 8, "2026-11-02")
    # sans échéance propre : le délai général de la politique (30 jours) s'applique comme avant
    resultat, _ = _relances([_etat_envoye()], "2026-11-10")
    assert resultat["creees"] == [] and resultat["sans_retard"] == 1
    resultat, _ = _relances([_etat_envoye()], "2026-12-10")
    assert [c["echeance"] for c in resultat["creees"]] == ["2026-12-02"]


def test_la_relance_cite_le_numero_de_facture_quand_il_existe():
    resultat, registre_ops = _relances([_etat_envoye(echeance="2026-11-02", numero_facture="F-01000")], "2026-11-10")
    texte = registre_ops.lire()[0]["texte"]
    assert "F-01000" in texte and "F-1 " not in texte
    resultat, registre_ops = _relances([_etat_envoye(echeance="2026-11-02")], "2026-11-10")
    assert "facture F-1 " in registre_ops.lire()[0]["texte"]


def test_une_echeance_illisible_de_la_facture_retombe_sur_la_politique_jamais_sur_une_date_inventee():
    for illisible in ("pas une date", "2026-13-45", 20261102, ""):
        resultat, _ = _relances([_etat_envoye(echeance=illisible)], "2026-11-10")
        assert resultat["creees"] == [], illisible
