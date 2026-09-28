import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.frontieres as frontieres_mod

# --- CHAMPS_INTERDITS ---
def test_champs_interdits_epingle():
    expected = frozenset({
        "prix", "montant", "date_ferme", "date_ferme_imposee",
        "engagement", "engagement_financier",
    })
    assert frontieres_mod.CHAMPS_INTERDITS == expected

# --- scanner_frontieres ---
def test_scanner_cle_premier_niveau():
    obj = {"prix": 100, "nom": "test"}
    result = frontieres_mod.scanner_frontieres(obj)
    assert result == ["prix"]

def test_scanner_cle_imbriquee():
    obj = {"contact": {"engagement": "oui"}}
    result = frontieres_mod.scanner_frontieres(obj)
    assert result == ["contact.engagement"]

def test_scanner_dict_dans_liste():
    obj = {"lignes": [{"ok": 1}, {"montant": 5}]}
    result = frontieres_mod.scanner_frontieres(obj)
    assert result == ["lignes[1].montant"]

def test_scanner_variantes_casse_accents():
    obj = {
        "PRIX": 10,
        "date ferme": "2025",
        "date-ferme": "2025b",
        "ENGAGEMENT_FINANCIER": "non",
        "Date Ferme Imposée": "2026",
    }
    result = frontieres_mod.scanner_frontieres(obj)
    # Tous ces champs, après normalisation, correspondent à des interdits.
    # "prix", "date_ferme", "engagement_financier", "date_ferme_imposee"
    # Ordre trié : "date_ferme" (normalisé à partir de "date ferme"),
    # "date_ferme_imposee" ("Date Ferme Imposée"),
    # "engagement_financier", "prix"
    # "date ferme" et "date-ferme" normalisent TOUTES DEUX en "date_ferme"
    # (espace et tiret -> underscore) : deux occurrences distinctes au scan.
    expected_sorted = sorted(["prix", "date_ferme", "date_ferme", "engagement_financier", "date_ferme_imposee"])
    assert result == expected_sorted

def test_scanner_valeur_contenant_mot_interdit_ignored():
    obj = {"note": "le prix sera discuté"}
    result = frontieres_mod.scanner_frontieres(obj)
    assert result == []

def test_scanner_cle_non_interdite_proche():
    obj = {"prixel": 1, "montante": 2}
    result = frontieres_mod.scanner_frontieres(obj)
    assert result == []

def test_scanner_plusieurs_violations_triees():
    obj = {
        "a": {"montant": 5},
        "b": {"engagement": "x"},
        "c": [{"date_ferme": "y"}],
    }
    result = frontieres_mod.scanner_frontieres(obj)
    expected = ["a.montant", "b.engagement", "c[0].date_ferme"]  # tri alphabétique
    assert result == expected

def test_scanner_deterministe():
    obj = {"lignes": [{"ok": 1}, {"montant": 5}]}
    result1 = frontieres_mod.scanner_frontieres(obj)
    result2 = frontieres_mod.scanner_frontieres(obj)
    assert result1 == result2
    assert result1 is not result2  # pas de cache mutable

# --- verifier_frontieres ---
def test_verifier_frontieres_violation():
    obj = {"prix": 10, "nom": "test"}
    ok, verdict = frontieres_mod.verifier_frontieres(obj)
    assert ok is False
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"
    assert verdict["detail"] == "prix"

def test_verifier_frontieres_pas_violation():
    obj = {"nom": "test", "description": "le montant est inconnu"}
    ok, verdict = frontieres_mod.verifier_frontieres(obj)
    assert ok is True
    assert verdict is None

def test_verifier_frontieres_violations_multiples_detail_joint():
    obj = {"montant": 1, "engagement": "oui"}
    ok, verdict = frontieres_mod.verifier_frontieres(obj)
    assert ok is False
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"
    # Détail : "engagement, montant"
    assert verdict["detail"] == "engagement, montant"
