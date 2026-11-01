"""Rejeu PostgreSQL : coût certifié M4 -> M5 (portée de livraison, politiques, relecture courante) — sans recalcul
isolé.
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_qa_m4_core_m5.py",
    "test_reconciliateur_cout_certifie.py",
)
