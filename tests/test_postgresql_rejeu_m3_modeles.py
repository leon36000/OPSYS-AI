"""Rejeu PostgreSQL : modèles de soumission M3 et devis préremplis de la console (écritures humaines)."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_modeles_soumission.py",
    "test_console_devis_modele.py",
    "test_console_prefill_ports.py",
)
