"""Rejeu PostgreSQL : suivi des rappels de l'appareil M1 (prise en charge, un seul preneur à la fois)."""

from pathlib import Path

from pg_rejeu import installer

RACINE = Path(__file__).resolve().parents[1]

INJECTES = installer(
    globals(),
    str(RACINE / "departments/m01-front-office/tests/test_rappels_appareil.py"),
    "test_rappels_appareil_atomique.py",
    rediriger_sqlite=True,
)
