"""Rejeu PostgreSQL : suivi des rappels de l'appareil M1 (prise en charge, un seul preneur à la fois)."""

from pathlib import Path

import pytest
from pg_rejeu import installer, verrou_tenu

from opsys import stockage

RACINE = Path(__file__).resolve().parents[1]

INJECTES = installer(
    globals(),
    str(RACINE / "departments/m01-front-office/tests/test_rappels_appareil.py"),
    "test_rappels_appareil_atomique.py",
    rediriger_sqlite=True,
)


@pytest.fixture(autouse=True)
def _verrou_nomme_tenu_apres_l_admission_d_une_prise(monkeypatch):
    """Une prise en charge admise tient le verrou nommé `m1-suivi-rappel` (PostgreSQL) : lire la chaîne puis y ajouter
    n'est atomique que sous SQLite ; sans lui, deux prises simultanées échouaient en erreur de chaîne."""
    from m1_front_office import rappels_appareil as domaine

    original = domaine.admettre
    journal = {"appels": 0, "sans_verrou": 0}

    def admettre(arguments, *, nom):
        admission = original(arguments, nom=nom)
        if nom == domaine.PRISE:
            journal["appels"] += 1
            cnx = stockage.connexion_courante()
            if cnx is None or not verrou_tenu(cnx, "m1-suivi-rappel"):
                journal["sans_verrou"] += 1
        return admission

    monkeypatch.setattr(domaine, "admettre", admettre)
    yield journal
    assert journal["sans_verrou"] == 0, f"prise de rappel admise sans verrou nommé : {journal}"
