"""La politique du sas : fenêtre de publication, délais, plafonds de budget, reprises. Des valeurs explicites du client,
jamais devinées par un modèle ; les défauts ci-dessous sont des défauts de prudence, pas des faits sur une plateforme.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, time
from zoneinfo import ZoneInfo

from opsys import garde_fou_texte as socle

NIVEAU_ORGANIQUE = 3
NIVEAU_ANNONCE_PAYANTE = 4


@dataclasses.dataclass(frozen=True)
class FenetrePublication:
    """Heures locales où une publication publique peut partir (début inclus, fin exclue)."""

    fuseau: str = "America/Toronto"
    debut: time = time(7, 0)
    fin: time = time(21, 0)

    def contient(self, instant_utc: datetime) -> bool:
        local = instant_utc.astimezone(ZoneInfo(self.fuseau)).time()
        return self.debut <= local < self.fin


@dataclasses.dataclass(frozen=True)
class PolitiqueSas:
    """`delai_minimal_s` : une publication planifiée part au moins ce temps après l'approbation. `horizon_max_jours` :
    au plus loin. `tolerance_retard_s` : au-delà de ce retard sur l'heure approuvée, la publication n'a plus de sens
    (une
    promotion saisonnière en retard) et n'est pas publiée. `plafond_budget_quotidien_cents` : plafond DUR par réseau,
    codé côté OPSYS en plus de celui de la plateforme (R4 §7, principe 2). `quota_24h` : plafond par réseau plus bas que
    celui de l'adaptateur (le plus strict des deux s'applique)."""

    fenetre: FenetrePublication = FenetrePublication()
    delai_minimal_s: int = 300
    horizon_max_jours: int = 60
    tolerance_retard_s: int = 2 * 3600
    tentatives_max: int = 3
    plafond_budget_quotidien_cents: int = 5000
    plafond_budget_total_cents: int = 100000
    quota_24h: tuple[tuple[str, int], ...] = ()
    contexte_texte: socle.Contexte = socle.Contexte()
