"""Rejeu PostgreSQL : fusion opérationnelle CSV (la partie qui ne dépend pas du worker PDF isolé, absent de certaines
machines).
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_fusion_operationnelle.py",
    "test_fusion_preparateur.py",
)
