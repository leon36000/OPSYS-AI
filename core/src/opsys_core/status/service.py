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
import re

from .model import CapabilityState, CapabilityStatus

_EVIDENCE_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class TransitionRecord:
    capability_id: str
    depuis: CapabilityState
    vers: CapabilityState
    reasons: tuple[str, ...]
    evidence_hash: str | None


@dataclass
class CapabilityTransitionLog:
    """Journal en mémoire des promotions/déclassements RÉUSSIS
    (append-only) — une transition REFUSÉE n'est pas un changement d'état
    réel, elle n'est jamais journalisée ici."""

    entries: list[TransitionRecord] = field(default_factory=list)

    def enregistrer(self, record: TransitionRecord) -> None:
        self.entries.append(record)


def _evidence_hash_valide(evidence_hash: object) -> bool:
    """Vérifie la forme canonique d'une preuve de promotion.

    Une annotation de type ne protège pas la frontière runtime : une
    opération externe peut retourner n'importe quel objet. La promotion
    vers ACTIVE accepte donc uniquement une référence SHA-256 complète,
    jamais une valeur simplement truthy.
    """
    return isinstance(evidence_hash, str) and _EVIDENCE_HASH_RE.fullmatch(evidence_hash) is not None


def transitionner(
    actuel: CapabilityStatus,
    nouvel_etat: CapabilityState,
    *,
    reasons: tuple[str, ...],
    evidence_hash: str | None = None,
    journal: CapabilityTransitionLog | None = None,
) -> CapabilityStatus:
    """Calcule le nouveau CapabilityStatus.

    Une promotion vers ACTIVE exige une référence exactement formée
    ``sha256:<64 hex minuscules>``. Une valeur absente, mal formée ou
    d'un type inattendu est refusée fermé : l'état courant est conservé,
    une raison sûre est ajoutée et aucun journal de promotion n'est créé.
    Toute transition non-ACTIVE reste acceptée directement.
    """
    if nouvel_etat == CapabilityState.ACTIVE and not _evidence_hash_valide(evidence_hash):
        return CapabilityStatus(
            capability_id=actuel.capability_id,
            state=actuel.state,
            reasons=(*actuel.reasons, "promotion vers ACTIVE refusée: preuve hashée absente ou invalide (evidence_hash)"),
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
    """Exécute ``operation`` et calcule le CapabilityStatus résultant.

    Un succès réel retourne une preuve au format ``sha256:<64 hex
    minuscules>``. Toute exception — y compris TimeoutError — ne devient
    jamais ACTIVE : elle est QUARANTINED avec son seul type comme raison.
    Une valeur de retour invalide est ensuite refusée fermé par
    ``transitionner``.
    """
    try:
        evidence_hash = operation()
    except Exception as exc:  # noqa: BLE001 - capturé intentionnellement, jamais laissé s'échapper
        # CORRECTIF sécurité (revue TRIAD_CONSENSUS clôture C03,
        # DeepSeek-V4-Pro, objection CRITIQUE confirmée) : le message brut
        # de l'exception (`{exc}`) peut porter un secret/PII — seul le NOM
        # DE TYPE est une raison sûre, même discipline que
        # opsys_core.errors.mapper_exception (C03-004) pour safe_message.
        return CapabilityStatus(
            capability_id=capability_id,
            state=CapabilityState.QUARANTINED,
            reasons=(f"{type(exc).__name__}",),
        )

    depart = CapabilityStatus(
        capability_id=capability_id,
        state=CapabilityState.UNKNOWN,
        reasons=("évaluation initiale",),
    )
    return transitionner(depart, CapabilityState.ACTIVE, reasons=(), evidence_hash=evidence_hash, journal=journal)
