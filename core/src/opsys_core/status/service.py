"""Service de transition de statut de capacité (C03-003).

Une PROMOTION (transition vers ACTIVE) exige une preuve hashée
(evidence_hash) — sans preuve, jamais de promotion silencieuse, le statut
reste dans son état actuel avec une raison explicite ajoutée. Une
exception levée pendant l'évaluation d'une capacité (y compris
TimeoutError) ne devient JAMAIS ACTIVE — toujours QUARANTINED avec la
raison exacte.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .model import CapabilityState, CapabilityStatus


@dataclass(frozen=True)
class TransitionRecord:
    capability_id: str
    depuis: CapabilityState
    vers: CapabilityState
    reasons: list[str]
    evidence_hash: str | None


@dataclass
class CapabilityTransitionLog:
    """Journal en mémoire des promotions/déclassements RÉUSSIS
    (append-only) — une transition REFUSÉE n'est pas un changement d'état
    réel, elle n'est jamais journalisée ici."""

    entries: list[TransitionRecord] = field(default_factory=list)

    def enregistrer(self, record: TransitionRecord) -> None:
        self.entries.append(record)


def transitionner(
    actuel: CapabilityStatus,
    nouvel_etat: CapabilityState,
    *,
    reasons: list[str],
    evidence_hash: str | None = None,
    journal: CapabilityTransitionLog | None = None,
) -> CapabilityStatus:
    """Calcule le nouveau CapabilityStatus. Une promotion (vers ACTIVE)
    SANS evidence_hash est REFUSÉE — reste dans l'état actuel, avec une
    raison explicite ajoutée à la liste existante. Toute autre transition
    (y compris vers un état non-ACTIVE) est acceptée directement."""
    if nouvel_etat == CapabilityState.ACTIVE and not evidence_hash:
        return CapabilityStatus(
            capability_id=actuel.capability_id,
            state=actuel.state,
            reasons=[*actuel.reasons, "promotion vers ACTIVE refusée: aucune preuve hashée (evidence_hash)"],
        )

    nouveau = CapabilityStatus(
        capability_id=actuel.capability_id,
        state=nouvel_etat,
        reasons=reasons,
    )
    if journal is not None:
        journal.enregistrer(TransitionRecord(
            capability_id=actuel.capability_id,
            depuis=actuel.state,
            vers=nouvel_etat,
            reasons=reasons,
            evidence_hash=evidence_hash,
        ))
    return nouveau


def evaluer_capacite(
    capability_id: str,
    operation: Callable[[], str],
    *,
    journal: CapabilityTransitionLog | None = None,
) -> CapabilityStatus:
    """Exécute `operation` (doit retourner un evidence_hash — une chaîne —
    en cas de succès réel) et calcule le CapabilityStatus résultant. Toute
    EXCEPTION levée par `operation` — y compris TimeoutError — ne devient
    JAMAIS ACTIVE : toujours QUARANTINED avec le type et le message de
    l'exception comme raison."""
    try:
        evidence_hash = operation()
    except Exception as exc:  # noqa: BLE001 - capturé intentionnellement, jamais laissé s'échapper
        return CapabilityStatus(
            capability_id=capability_id,
            state=CapabilityState.QUARANTINED,
            reasons=[f"{type(exc).__name__}: {exc}"],
        )

    depart = CapabilityStatus(
        capability_id=capability_id,
        state=CapabilityState.UNKNOWN,
        reasons=["évaluation initiale"],
    )
    return transitionner(depart, CapabilityState.ACTIVE, reasons=[], evidence_hash=evidence_hash, journal=journal)
