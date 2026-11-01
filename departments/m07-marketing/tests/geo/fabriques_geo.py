"""Fabriques communes aux tests GEO/SEO : horloge, sentinelle de jeton. Données FICTIVES."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

MAINTENANT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
JETON = "jeton-fictif-SENTINELLE-geo-41c7"


class Horloge:
    def __init__(self, depart: datetime = MAINTENANT) -> None:
        self.t = depart

    def __call__(self) -> datetime:
        return self.t

    def avancer(self, **kw) -> None:
        self.t += timedelta(**kw)
