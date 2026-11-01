"""Rejeu PostgreSQL : obligations M5 préparées par un administrateur d'appareil (validation au départ), dont les deux
appels simultanés qui visent le même plafond (défaut L11 : le perdant recevait `EcritureConcurrente` au lieu du refus)."""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_obligations_preparees_appareil_atomiques.py",
)
