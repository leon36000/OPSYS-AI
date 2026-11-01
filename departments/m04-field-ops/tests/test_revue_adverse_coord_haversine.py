"""Revue adverse (coord-02) : la distance orthodromique ne plante pas sur des points antipodaux."""

from __future__ import annotations

import math
import random

from m4_field_ops import pointage

DEMI_CIRCONFERENCE_KM = math.pi * 6371.0


def test_points_antipodaux_connus_qui_levaient_une_erreur_de_domaine() -> None:
    for lat, lon, lat2, lon2 in (
        (69.51232454868148, 86.5812282599507, -69.51232454868148, -93.4187717400493),
        (-85.74577602624232, -40.83944228587086, 85.74577602624232, 139.16055771412914),
    ):
        assert math.isclose(pointage.distance_km(lat, lon, lat2, lon2), DEMI_CIRCONFERENCE_KM, rel_tol=1e-6)


def test_semis_antipodal_ne_leve_jamais() -> None:
    hasard = random.Random(2026)
    for _ in range(20000):
        lat, lon = hasard.uniform(-90, 90), hasard.uniform(-180, 180)
        lon2 = lon + 180 if lon < 0 else lon - 180
        assert math.isclose(pointage.distance_km(lat, lon, -lat, lon2), DEMI_CIRCONFERENCE_KM, rel_tol=1e-6)


def test_cas_negatifs_distances_ordinaires_inchangees() -> None:
    assert pointage.distance_km(45.5, -73.6, 45.5, -73.6) == 0.0
    montreal_quebec = pointage.distance_km(45.5017, -73.5673, 46.8139, -71.2080)
    assert 230 < montreal_quebec < 240
