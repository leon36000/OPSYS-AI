"""Fraîcheur d'une source : à jour, périmée, jamais lue, ou en échec — jamais un zéro à la place d'une absence.

La fraîcheur n'est PAS l'âge d'un fait (un fait de la semaine dernière peut être parfaitement à jour) : c'est l'âge de
la
dernière LECTURE RÉUSSIE de la source, comparé à la fenêtre que M7 déclare pour elle (`modele.SourceDecl.fraicheur_h`).
M8 applique la règle « la plus stricte entre l'appelant et le producteur » sur cette fenêtre (DECISIONS-ARCHITECTE §3).

Module pur : l'horloge est un argument.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import modele
from .curseurs import EtatIngestion

STATUT_A_JOUR = "a_jour"
STATUT_PERIME = "perime"
STATUT_JAMAIS = "jamais_ingere"
STATUT_ECHEC = "en_echec"
STATUTS = (STATUT_A_JOUR, STATUT_PERIME, STATUT_JAMAIS, STATUT_ECHEC)


def evaluer(
    source: str, etats: Iterable[EtatIngestion], maintenant: datetime, fenetre_h: int | None = None
) -> dict[str, Any]:
    """Fraîcheur du COMPTE (tous ses flux) : on retient le flux le plus en retard. `fenetre_h` plus strict que le
    défaut de
    la source est respecté ; plus lâche, il est ignoré (la plus stricte s'applique)."""
    decl = modele.SOURCES[source]
    fenetre = decl.fraicheur_h if fenetre_h is None else min(decl.fraicheur_h, fenetre_h)
    etats = list(etats)
    lectures = [
        (modele.instant_rfc3339(e.derniere_lecture_reussie_le), e) for e in etats if e.derniere_lecture_reussie_le
    ]
    echecs = [e for e in etats if e.dernier_echec]
    base: dict[str, Any] = {"fenetre_h": fenetre, "retard_donnees_jours": decl.retard_donnees_jours}
    if not lectures or len(lectures) < len(etats):
        return {
            **base,
            "statut": STATUT_ECHEC if echecs else STATUT_JAMAIS,
            "derniere_lecture_reussie_le": None,
            "donnees_jusqu_au": None,
            "age_h": None,
            "dernier_echec": echecs[0].echec() if echecs else None,
        }
    plus_ancienne, flux_retard = min(lectures, key=lambda t: t[0])
    age_h = Decimal((maintenant - plus_ancienne).total_seconds()) / Decimal(3600)
    jusqu = [e.donnees_jusqu_au for e in etats if e.donnees_jusqu_au]
    statut = STATUT_A_JOUR if age_h <= fenetre else STATUT_PERIME
    dernier_echec = None
    for e in echecs:
        echec = e.echec()
        if echec and modele.instant_rfc3339(echec["le"]) >= plus_ancienne:
            dernier_echec = echec
            if statut == STATUT_PERIME:
                statut = STATUT_ECHEC
            break
    return {
        **base,
        "statut": statut,
        "derniere_lecture_reussie_le": flux_retard.derniere_lecture_reussie_le,
        "donnees_jusqu_au": min(jusqu) if jusqu else None,
        "age_h": format(age_h.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f"),
        "dernier_echec": dernier_echec,
    }


__all__ = ["STATUTS", "STATUT_A_JOUR", "STATUT_ECHEC", "STATUT_JAMAIS", "STATUT_PERIME", "evaluer"]
