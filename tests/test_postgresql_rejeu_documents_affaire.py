"""Rejeu PostgreSQL des documents d'affaire M10 (transactions, lecture appareil), dont les bases SQLite fichier que les
tests bâtissent eux-mêmes sont remplacées par des bases PostgreSQL vides (`rediriger_sqlite`).

Défaut corrigé au passage : le plafond `2**63 - 1` lié à une colonne INTEGER débordait sur PostgreSQL (« integer out of
range ») ; deux corrections simultanées d'un même document passent désormais par un verrou nommé."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_documents_affaire_transactions.py",
    "test_documents_affaire_lecture_appareil.py",
    rediriger_sqlite=True,
)
