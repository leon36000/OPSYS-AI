"""Rejeu PostgreSQL : grants CFO des agents (verrous de ligne), liaison de cibles M10 et CLI de révocation."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_agent_cfo_grants.py",
    "test_console_agent_cfo_grants.py",
    "test_liaison_cibles.py",
)
