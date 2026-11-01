"""Rejeu PostgreSQL : cron opérateur (intentions, remises, retraits, console HTTP) sous le verrou nommé."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_agents_declencheurs.py",
    "test_agents_cron_autorite.py",
    "test_agents_cron_retraits.py",
    "test_agents_cron_empreintes.py",
    "test_agents_base_declencheurs.py",
    "test_console_agents_declencheurs.py",
    "test_cron_operateur_http.py",
)
