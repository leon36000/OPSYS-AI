"""Validation déterministe d'une facture extraite à l'onboarding (`validation_facture_onboarding.py`).

Chaque contrôle a son cas positif et son cas négatif ; une incohérence n'est jamais corrigée, elle devient une raison
avec les deux chiffres. Factures, fournisseurs et numéros fictifs (AGENTS.md) ; les numéros TPS/TVQ n'ont que la forme.
"""

from __future__ import annotations

import copy
from datetime import date

import m5_financecore.outils as m5_outils
import pytest
from m5_financecore import taux_fiscaux, validation_facture_onboarding
from m5_financecore.validation_facture_onboarding import CODES_VALIDATION, valider

FICTIF = True
DEPOT = date(2026, 10, 31)
IDENTITE = {"nom_legal": "Gouttières Fictives Synergy inc.", "tps": "987654321 RT 0001", "tvq": "9876543210 TQ 0001"}


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    return dictionnaire


def _facture(**surcharges):
    facture = {
        "schema": "opsys.facture/v1",
        "emetteur": {"nom": "Quincaillerie Fictive Laval inc.", "no_tps": "123456789 RT 0001",
                     "no_tvq": "1234567890 TQ 0001"},
        "destinataire": {"nom": "Gouttières Fictives Synergy inc."},
        "numero": "QF-2026-0418", "date": "2026-09-15", "echeance": "2026-10-15", "devise": "CAD",
        "lignes": [{"description": "Gouttière 5 po", "quantite": "40", "prix_unitaire": "6.25", "montant": "250.00"},
                   {"description": "Coudes", "quantite": "12", "prix_unitaire": "4.50", "montant": "54.00"}],
        "sous_total": "304.00", "tps": "15.20", "tvq": "30.32", "total": "349.52",
    }
    for cle, valeur in surcharges.items():
        if "." in cle:
            bloc, sous = cle.split(".")
            facture[bloc] = {**facture[bloc], sous: valeur}
        else:
            facture[cle] = valeur
    return facture


def _codes(resultat):
    return sorted(r["code"] for r in resultat["raisons"])


def _valider(facture, taux, identite=IDENTITE):
    return valider(facture, dictionnaire_taux=taux, identite=identite, jour_depot=DEPOT)


def test_une_facture_coherente_est_prete_avec_ses_taxes_recalculees(taux):
    resultat = _valider(_facture(), taux)
    assert resultat["statut"] == "PRET" and resultat["raisons"] == [] and resultat["direction"] == "fournisseur"
    lecture = resultat["facture"]
    assert (lecture["tps_recalculee"], lecture["tvq_recalculee"], lecture["total_recalcule"]) == (
        "15.20", "30.32", "349.52")
    assert lecture["no_tps"] == "123456789 RT 0001" and lecture["no_tvq"] == "1234567890 TQ 0001"


def test_le_demi_cent_monte_toujours_round_half_up(taux):
    """100.50 : TPS 5.025 -> 5.03 (HALF_EVEN donnerait 5.02) ; 300.00 : TVQ 29.925 -> 29.93."""
    demi = _facture(lignes=[{"description": "Solin", "quantite": "3", "prix_unitaire": "33.50", "montant": "100.50"}],
                    sous_total="100.50", tps="5.03", tvq="10.02", total="115.55")
    assert _valider(demi, taux)["statut"] == "PRET"
    banquier = _facture(lignes=[{"description": "Location", "quantite": "2", "prix_unitaire": "150.00",
                                 "montant": "300.00"}], sous_total="300.00", tps="15.00", tvq="29.92", total="344.92")
    resultat = _valider(banquier, taux)
    assert _codes(resultat) == ["REJ-ING-FACTURE-TOTAL-ECART", "REJ-ING-FACTURE-TVQ-ECART"]
    detail = {r["code"]: r["detail"] for r in resultat["raisons"]}["REJ-ING-FACTURE-TVQ-ECART"]
    assert "29.92" in detail and "29.93" in detail


@pytest.mark.parametrize(("surcharges", "code"), [
    ({"tps": "15.21", "total": "349.53"}, "REJ-ING-FACTURE-TPS-ECART"),
    ({"tvq": "30.33", "total": "349.53"}, "REJ-ING-FACTURE-TVQ-ECART"),
    ({"total": "349.53"}, "REJ-ING-FACTURE-TOTAL-ECART"),
    ({"sous_total": "305.00", "tps": "15.25", "tvq": "30.42", "total": "350.67"}, "REJ-ING-FACTURE-SOMME-LIGNES"),
    ({"emetteur.no_tps": "12345678 RT 0001"}, "REJ-ING-FACTURE-NO-TPS-FORME"),
    ({"emetteur.no_tvq": "1234567890 RT 0001"}, "REJ-ING-FACTURE-NO-TVQ-FORME"),
    ({"emetteur.no_tps": None}, "REJ-ING-FACTURE-NO-TPS-ABSENT"),
    ({"emetteur.no_tvq": ""}, "REJ-ING-FACTURE-NO-TVQ-ABSENT"),
    ({"date": "2026-11-01"}, "REJ-ING-FACTURE-DATE-FUTURE"),
    ({"date": "2016-10-01"}, "REJ-ING-FACTURE-DATE-ANCIENNE"),
    ({"date": "2026-02-30"}, "REJ-ING-FACTURE-DATE-INVALIDE"),
    ({"echeance": "2026-09-01"}, "REJ-ING-FACTURE-ECHEANCE-AVANT-DATE"),
    ({"devise": "USD"}, "REJ-ING-FACTURE-DEVISE"),
    ({"emetteur.nom": " "}, "REJ-ING-FACTURE-FOURNISSEUR-NON-IDENTIFIABLE"),
    ({"numero": None}, "REJ-ING-FACTURE-NUMERO-INVALIDE"),
    ({"destinataire.nom": "Autre Entreprise Fictive"}, "REJ-ING-FACTURE-DESTINATAIRE-NON-RECONNU"),
])
def test_chaque_incoherence_est_une_raison_exacte_jamais_corrigee(taux, surcharges, code):
    facture = _facture(**surcharges)
    avant = copy.deepcopy(facture)
    resultat = _valider(facture, taux)
    assert resultat["statut"] == "A_VERIFIER" and code in _codes(resultat), _codes(resultat)
    assert facture == avant, "l'extraction n'est jamais modifiée"
    for champ in ("sous_total", "tps", "tvq", "total"):
        assert resultat["facture"][champ] == facture[champ], "le montant imprimé reste tel quel"


def test_une_ligne_dont_le_produit_differe_au_cent_est_signalee(taux):
    lignes = [{"description": "Gouttière", "quantite": "40", "prix_unitaire": "6.25", "montant": "250.01"},
              {"description": "Coudes", "quantite": "12", "prix_unitaire": "4.50", "montant": "53.99"}]
    resultat = _valider(_facture(lignes=lignes), taux)
    assert _codes(resultat) == ["REJ-ING-FACTURE-LIGNE-MONTANT", "REJ-ING-FACTURE-LIGNE-MONTANT"]
    assert "250.00" in resultat["raisons"][0]["detail"] and "250.01" in resultat["raisons"][0]["detail"]


def test_une_facture_emise_par_l_entreprise_n_est_pas_un_compte_a_payer(taux):
    facture = _facture(**{"emetteur.nom": "GOUTTIERES FICTIVES SYNERGY", "destinataire.nom": "Client Fictif"})
    resultat = _valider(facture, taux)
    assert resultat["direction"] == "client" and "REJ-ING-FACTURE-EMISE-PAR-L-ENTREPRISE" in _codes(resultat)
    par_numero = _facture(**{"emetteur.nom": "Autre nom", "emetteur.no_tps": "987654321RT0001",
                             "destinataire.nom": "Client Fictif"})
    assert _valider(par_numero, taux)["direction"] == "client"


def test_sans_identite_declaree_le_sens_n_est_jamais_suppose(taux):
    resultat = _valider(_facture(), taux, identite=None)
    assert resultat["direction"] == "indeterminee" and resultat["statut"] == "A_VERIFIER"
    assert _codes(resultat) == ["REJ-ING-FACTURE-DESTINATAIRE-NON-RECONNU"]
    destinataire_par_tps = _facture(destinataire={"nom": "Nom imprimé autrement", "no_tps": "987654321 RT 0001"})
    assert _valider(destinataire_par_tps, taux)["direction"] == "fournisseur"


@pytest.mark.parametrize("surcharges", [
    {"sous_total": 304.0},
    {"tps": "15,20"},
    {"schema": "opsys.facture/v0"},
    {"lignes": []},
    {"lignes": [{"description": "x", "quantite": "1", "prix_unitaire": "1", "montant": "1.00", "taxe": "0"}]},
    {"emetteur": {"nom": "X", "no_tps": None}},
    {"inconnu": "valeur"},
    {"date": None},
])
def test_un_schema_rompu_est_a_verifier_sans_lecture(taux, surcharges):
    resultat = _valider(_facture(**surcharges), taux)
    assert resultat == {"statut": "A_VERIFIER", "raisons": resultat["raisons"], "direction": "indeterminee",
                        "facture": None}
    assert _codes(resultat) == ["REJ-ING-FACTURE-SCHEMA"]


def test_une_note_de_credit_n_est_pas_un_compte_a_payer(taux):
    facture = _facture(lignes=[{"description": "Retour", "quantite": "-1", "prix_unitaire": "50.00",
                                "montant": "-50.00"}], sous_total="-50.00", tps="-2.50", tvq="-4.99", total="-57.49")
    assert "REJ-ING-FACTURE-MONTANT-NON-POSITIF" in _codes(_valider(facture, taux))


def test_taux_absents_raison_nommee(taux):
    resultat = valider(_facture(), dictionnaire_taux={}, identite=IDENTITE, jour_depot=DEPOT)
    assert "REJ-ING-FACTURE-TAUX-INDISPONIBLES" in _codes(resultat)


def test_formes_des_numeros_et_catalogue_ferme():
    assert validation_facture_onboarding.normaliser_no_tps("123456789rt0001") == "123456789 RT 0001"
    assert validation_facture_onboarding.normaliser_no_tps("123456789 RT 001") is None
    assert validation_facture_onboarding.normaliser_no_tvq("1234567890-TQ-0001") == "1234567890 TQ 0001"
    assert validation_facture_onboarding.normaliser_no_tvq("123456789 TQ 0001") is None
    assert len(set(CODES_VALIDATION)) == len(CODES_VALIDATION)
    with pytest.raises(ValueError):
        validation_facture_onboarding._raison("REJ-INVENTE", "x")
