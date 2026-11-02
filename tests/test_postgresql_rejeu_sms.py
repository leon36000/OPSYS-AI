"""Rejeu PostgreSQL : réception SMS hôte M1 (reçu idempotent, deux connexions fortes qui se disputent le même SMS)."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_reception_sms_receipt.py",
)
