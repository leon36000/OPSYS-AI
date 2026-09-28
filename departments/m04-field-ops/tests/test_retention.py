"""Tests unitaires purs du module retention.py (PLAN T4.2, POLITIQUE-geolocalisation.md §5).

Trois familles : le chiffrement/déchiffrement (crypto-shredding), l'arithmétique d'échéance
(+12 mois), et l'évaluation d'éligibilité à la purge (fail-closed sans fin_contrat_travail).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from m4_field_ops import registre as registre_mod
from m4_field_ops import retention as retention_mod

CLE_A = b"\x01" * 32
CLE_B = b"\x02" * 32


def _registre():
    return registre_mod.Registre()


# ------------------------------------------------------------------ chiffrement (crypto-shredding)
def test_chiffrer_puis_dechiffrer_meme_cle_meme_nonce_round_trip_exact():
    nonce = retention_mod.nonce_position("I1", "T1", "arrivee", "2025-06-02T09:00:00+00:00")
    chiffre = retention_mod.chiffrer_position(CLE_A, nonce, 45.5088, -73.5878)
    lat, lon = retention_mod.dechiffrer_position(CLE_A, nonce, chiffre)
    assert (lat, lon) == (45.5088, -73.5878)


def test_position_chiffree_ne_contient_jamais_les_coordonnees_en_clair():
    nonce = retention_mod.nonce_position("I1", "T1", "arrivee", "2025-06-02T09:00:00+00:00")
    chiffre = retention_mod.chiffrer_position(CLE_A, nonce, 45.5088, -73.5878)
    assert "45.5088" not in chiffre
    assert "73.5878" not in chiffre


def test_dechiffrer_avec_mauvaise_cle_ne_rend_jamais_la_bonne_position():
    """La destruction d'une clé (opsys.cles_chiffrement.detruire) doit rendre le fix
    irrécupérable : une clé DIFFÉRENTE (jamais la bonne) ne doit jamais, même par accident,
    retomber sur les coordonnées d'origine."""
    nonce = retention_mod.nonce_position("I1", "T1", "arrivee", "2025-06-02T09:00:00+00:00")
    chiffre = retention_mod.chiffrer_position(CLE_A, nonce, 45.5088, -73.5878)
    with pytest.raises(ValueError):
        retention_mod.dechiffrer_position(CLE_B, nonce, chiffre)


def test_nonce_different_par_pointage_meme_technicien():
    n1 = retention_mod.nonce_position("I1", "T1", "arrivee", "2025-06-02T09:00:00+00:00")
    n2 = retention_mod.nonce_position("I1", "T1", "depart", "2025-06-02T11:30:00+00:00")
    assert n1 != n2


def test_nonce_deterministe_reproductible():
    n1 = retention_mod.nonce_position("I1", "T1", "arrivee", "2025-06-02T09:00:00+00:00")
    n2 = retention_mod.nonce_position("I1", "T1", "arrivee", "2025-06-02T09:00:00+00:00")
    assert n1 == n2


def test_chiffrement_deterministe_reproductible():
    """Module pur (aucun aléa ambiant) : le même appel produit TOUJOURS le même chiffré."""
    nonce = retention_mod.nonce_position("I1", "T1", "arrivee", "2025-06-02T09:00:00+00:00")
    c1 = retention_mod.chiffrer_position(CLE_A, nonce, 45.5088, -73.5878)
    c2 = retention_mod.chiffrer_position(CLE_A, nonce, 45.5088, -73.5878)
    assert c1 == c2


def test_chiffrer_position_accepte_entiers():
    """fix_gps peut légitimement porter des int (pointage.py les accepte aussi) : le round-trip
    passe par repr()/float(), la valeur revient en float mais numériquement identique."""
    nonce = retention_mod.nonce_position("I1", "T1", "arrivee", "2025-06-02T09:00:00+00:00")
    chiffre = retention_mod.chiffrer_position(CLE_A, nonce, 45, -73)
    lat, lon = retention_mod.dechiffrer_position(CLE_A, nonce, chiffre)
    assert (lat, lon) == (45.0, -73.0)


# ------------------------------------------------------------------ ajouter_12_mois
def test_ajouter_12_mois_jour_pour_jour():
    dt = datetime(2025, 6, 2, 9, 0, 0, tzinfo=UTC)
    assert retention_mod.ajouter_12_mois(dt) == datetime(2026, 6, 2, 9, 0, 0, tzinfo=UTC)


def test_ajouter_12_mois_29_fevrier_bissextile_vers_non_bissextile():
    dt = datetime(2024, 2, 29, 12, 0, 0, tzinfo=UTC)  # 2024 est bissextile
    resultat = retention_mod.ajouter_12_mois(dt)
    assert resultat == datetime(2025, 2, 28, 12, 0, 0, tzinfo=UTC)  # 2025 ne l'est pas


# ------------------------------------------------------------------ dernier_pointage_technicien
def test_dernier_pointage_technicien_absent_none():
    reg = _registre()
    assert retention_mod.dernier_pointage_technicien(reg, "T1") is None


def test_dernier_pointage_technicien_choisit_le_plus_recent_par_valeur():
    """Deux interventions distinctes : l'ordre d'écriture n'est PAS forcément l'ordre chronologique
    entre elles (seul CA-M4-07, par intervention, le garantit) — la comparaison doit porter sur la
    VALEUR de l'horodatage, jamais sur la position dans le registre."""
    reg = _registre()
    reg.ajouter({"type_entree": "pointage", "intervention_id": "I2", "technicien_id": "T1",
                 "action": "arrivee", "horodatage": "2025-06-05T09:00:00+00:00"})
    reg.ajouter({"type_entree": "pointage", "intervention_id": "I1", "technicien_id": "T1",
                 "action": "depart", "horodatage": "2025-06-01T09:00:00+00:00"})
    assert retention_mod.dernier_pointage_technicien(reg, "T1") == "2025-06-05T09:00:00+00:00"


# ------------------------------------------------------------------ evaluer_eligibilite_purge
def test_eligibilite_fin_contrat_manquante_refuse_donnee_manquante():
    reg = _registre()
    accuse, verdict = retention_mod.evaluer_eligibilite_purge(
        reg, "T1", None, "2026-01-01T00:00:00+00:00")
    assert accuse is None
    assert verdict["code"] == "REJ-RETENTION-DONNEE-MANQUANTE"


def test_eligibilite_echeance_non_atteinte_refuse():
    reg = _registre()
    accuse, verdict = retention_mod.evaluer_eligibilite_purge(
        reg, "T1", "2025-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00")  # < 12 mois après
    assert accuse is None
    assert verdict["code"] == "REJ-RETENTION-NON-ECHUE"


def test_eligibilite_echeance_atteinte_accepte():
    reg = _registre()
    accuse, verdict = retention_mod.evaluer_eligibilite_purge(
        reg, "T1", "2025-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00")  # >= 12 mois après
    assert accuse is not None, f"refusé : {verdict}"
    assert accuse["reference_retenue"] == "2025-01-01T00:00:00+00:00"
    assert accuse["date_echeance"] == "2026-01-01T00:00:00+00:00"


def test_eligibilite_retient_le_dernier_punch_si_plus_tardif_que_fin_contrat():
    """§5 : « selon la plus longue des deux périodes » — un dernier punch après la fin du contrat
    (ex. fin de contrat mal enregistrée) repousse l'échéance d'autant."""
    reg = _registre()
    reg.ajouter({"type_entree": "pointage", "intervention_id": "I1", "technicien_id": "T1",
                 "action": "depart", "horodatage": "2025-06-01T09:00:00+00:00"})
    accuse, verdict = retention_mod.evaluer_eligibilite_purge(
        reg, "T1", "2025-01-01T00:00:00+00:00", "2026-06-01T09:00:01+00:00")
    assert accuse is not None, f"refusé : {verdict}"
    assert accuse["reference_retenue"] == "2025-06-01T09:00:00+00:00"  # pas fin_contrat_travail
    assert accuse["date_echeance"] == "2026-06-01T09:00:00+00:00"


def test_eligibilite_technicien_id_vide_refuse():
    reg = _registre()
    accuse, verdict = retention_mod.evaluer_eligibilite_purge(
        reg, "", "2025-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00")
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_eligibilite_horodatage_actuel_invalide_refuse():
    reg = _registre()
    accuse, verdict = retention_mod.evaluer_eligibilite_purge(
        reg, "T1", "2025-01-01T00:00:00+00:00", "pas-une-date")
    assert accuse is None
    assert verdict["code"] == "REJ-HORODATAGE-INVALIDE"


def test_eligibilite_ne_modifie_jamais_le_registre():
    """Pure : aucune écriture, même quand la purge serait permise (outils.py orchestre l'écriture,
    jamais ce module)."""
    reg = _registre()
    retention_mod.evaluer_eligibilite_purge(
        reg, "T1", "2025-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00")
    assert reg.taille() == 0
