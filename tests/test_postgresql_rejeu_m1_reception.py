"""Rejeu PostgreSQL : suivi de rappel M1 (deux requêtes sur le même instantané) et réception SMS par le serveur MCP."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_console_suivi_rappel.py",
    "test_runtime_reception_sms_mcp.py",
)
