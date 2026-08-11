"""Tests pour core/src/opsys_core/status (C03-003) — états de capacité.

Couvre les 3 cas RED obligatoires de tasks/C03-003.md :
  1. états autorisés incluent ACTIVE, DEGRADED, BLOCKED_MISSING_PREREQUISITE,
     BLOCKED_QUALITY_THRESHOLD, BLOCKED_POLICY, UNKNOWN, QUARANTINED
  2. exception ou timeout ne devient jamais ACTIVE
  3. raison obligatoire pour tout état non ACTIVE

Décision de conception tranchée par revue d'architecture AVANT code
(GPT-5.6-Terra-Pro, appel direct --difficulty difficile) : `CapabilityState`
est un TYPE DISTINCT de `kernel.CoreStatus` (C03-001, déjà sur main), pas
une réexportation — les deux partagent le VOCABULAIRE canon (CANON §12 :
« every capability exposes explicit states ») par convention, pas par
identité de type. Les sources ne tranchent pas explicitement l'identité de
type ; la lecture retenue (recommandée par l'architecte comme la plus sûre)
évite un couplage status/ -> kernel.py non demandé par le spec de C03-003
(« Sorties exactes » liste un fichier NEUF, aucune mention de réutiliser
kernel.CoreStatus dans « Implémentation strictement bornée »).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from opsys_core.status.model import CapabilityState, CapabilityStatus  # noqa: E402
from opsys_core.status.service import (  # noqa: E402
    CapabilityTransitionLog,
    evaluer_capacite,
    transitionner,
)


# ---------------------------------------------------------------------------
# Cas RED 1 — états autorisés
# ---------------------------------------------------------------------------


def test_impl_menter_les_tats_de_capacit_et_de_d_gradation_1():
    """Cas RED #1 — CapabilityState est EXACTEMENT le vocabulaire canon
    (7 états), jamais un état inventé, jamais un état canon manquant."""
    attendu = {
        "ACTIVE", "DEGRADED", "BLOCKED_MISSING_PREREQUISITE",
        "BLOCKED_QUALITY_THRESHOLD", "BLOCKED_POLICY", "UNKNOWN", "QUARANTINED",
    }
    assert {s.name for s in CapabilityState} == attendu


# ---------------------------------------------------------------------------
# Cas RED 2 — exception ou timeout ne devient jamais ACTIVE
# ---------------------------------------------------------------------------


def test_impl_menter_les_tats_de_capacit_et_de_d_gradation_2():
    """Cas RED #2 — une exception levée pendant l'évaluation d'une
    capacité ne doit JAMAIS produire un statut ACTIVE."""
    def _operation_qui_plante():
        raise RuntimeError("panne simulée")

    resultat = evaluer_capacite("cap-x", _operation_qui_plante)
    assert resultat.state != CapabilityState.ACTIVE, (
        "GARDE RETIRÉE : une exception ne doit jamais produire ACTIVE"
    )
    assert resultat.state == CapabilityState.QUARANTINED
    assert resultat.reasons, "une exception doit toujours produire une raison explicite"


def test_timeout_ne_devient_jamais_active():
    """Cas RED #2 (variante nommée « timeout ») — TimeoutError (stdlib) est
    une exception comme une autre pour ce contrat : jamais ACTIVE."""
    def _operation_qui_timeout():
        raise TimeoutError("dépassement simulé")

    resultat = evaluer_capacite("cap-y", _operation_qui_timeout)
    assert resultat.state != CapabilityState.ACTIVE
    assert resultat.state == CapabilityState.QUARANTINED
    assert "TimeoutError" in resultat.reasons[0]


def test_operation_reussie_avec_preuve_devient_active():
    """Contrôle symétrique : une opération qui RÉUSSIT et retourne une
    preuve hashée devient ACTIVE — jamais un faux blocage sur un état sain."""
    resultat = evaluer_capacite("cap-z", lambda: "sha256:abc123")
    assert resultat.state == CapabilityState.ACTIVE
    assert resultat.reasons == []


# ---------------------------------------------------------------------------
# Cas RED 3 — raison obligatoire pour tout état non ACTIVE
# ---------------------------------------------------------------------------


def test_impl_menter_les_tats_de_capacit_et_de_d_gradation_3():
    """Cas RED #3 — construire un CapabilityStatus non-ACTIVE SANS raison
    doit être refusé (jamais un état bloqué muet)."""
    with pytest.raises(ValueError):
        CapabilityStatus(capability_id="cap-a", state=CapabilityState.DEGRADED, reasons=[])


def test_active_n_exige_pas_de_raison():
    """Contrôle symétrique : ACTIVE n'exige PAS de raison — sinon tout
    état sain serait artificiellement forcé à en inventer une."""
    statut = CapabilityStatus(capability_id="cap-b", state=CapabilityState.ACTIVE, reasons=[])
    assert statut.reasons == []


def test_tous_les_etats_non_active_exigent_une_raison():
    """Balayage exhaustif : CHAQUE état non-ACTIVE (pas seulement DEGRADED)
    exige une raison — pas seulement le cas testé isolément."""
    for etat in CapabilityState:
        if etat == CapabilityState.ACTIVE:
            continue
        with pytest.raises(ValueError):
            CapabilityStatus(capability_id="cap-c", state=etat, reasons=[])


# ---------------------------------------------------------------------------
# Promotion sans preuve hashée — interdite
# ---------------------------------------------------------------------------


def test_promotion_vers_active_sans_preuve_hashee_est_refusee():
    depart = CapabilityStatus(capability_id="cap-d", state=CapabilityState.DEGRADED, reasons=["dégradation initiale"])
    resultat = transitionner(depart, CapabilityState.ACTIVE, reasons=[], evidence_hash=None)
    assert resultat.state != CapabilityState.ACTIVE, (
        "GARDE RETIRÉE : une promotion sans preuve hashée doit être refusée"
    )
    assert resultat.state == CapabilityState.DEGRADED, "reste dans l'état actuel, jamais une promotion silencieuse"
    assert any("preuve" in r for r in resultat.reasons)


def test_promotion_vers_active_avec_preuve_hashee_est_acceptee():
    depart = CapabilityStatus(capability_id="cap-e", state=CapabilityState.DEGRADED, reasons=["dégradation initiale"])
    resultat = transitionner(depart, CapabilityState.ACTIVE, reasons=[], evidence_hash="sha256:deadbeef")
    assert resultat.state == CapabilityState.ACTIVE


def test_transition_vers_non_active_n_exige_pas_de_preuve():
    """Seule une promotion VERS ACTIVE exige une preuve — un déclassement
    (ex. DEGRADED -> QUARANTINED) n'a pas besoin d'evidence_hash."""
    depart = CapabilityStatus(capability_id="cap-f", state=CapabilityState.DEGRADED, reasons=["dégradation initiale"])
    resultat = transitionner(depart, CapabilityState.QUARANTINED, reasons=["nouvelle panne détectée"])
    assert resultat.state == CapabilityState.QUARANTINED


# ---------------------------------------------------------------------------
# Journal des promotions/déclassements
# ---------------------------------------------------------------------------


def test_journal_enregistre_une_transition_reussie():
    journal = CapabilityTransitionLog()
    depart = CapabilityStatus(capability_id="cap-g", state=CapabilityState.DEGRADED, reasons=["dégradation initiale"])
    transitionner(depart, CapabilityState.ACTIVE, reasons=[], evidence_hash="sha256:cafe", journal=journal)
    assert len(journal.entries) == 1
    entree = journal.entries[0]
    assert entree.capability_id == "cap-g"
    assert entree.depuis == CapabilityState.DEGRADED
    assert entree.vers == CapabilityState.ACTIVE
    assert entree.evidence_hash == "sha256:cafe"


def test_journal_n_enregistre_pas_une_promotion_refusee():
    """Une promotion REFUSÉE (pas de preuve) n'est pas un changement d'état
    réel — elle ne doit pas polluer le journal des transitions RÉUSSIES."""
    journal = CapabilityTransitionLog()
    depart = CapabilityStatus(capability_id="cap-h", state=CapabilityState.DEGRADED, reasons=["dégradation initiale"])
    transitionner(depart, CapabilityState.ACTIVE, reasons=[], evidence_hash=None, journal=journal)
    assert journal.entries == []


def test_evaluer_capacite_avec_succes_journalise_la_transition():
    journal = CapabilityTransitionLog()
    evaluer_capacite("cap-i", lambda: "sha256:1234", journal=journal)
    assert len(journal.entries) == 1
    assert journal.entries[0].vers == CapabilityState.ACTIVE


def test_evaluer_capacite_avec_echec_ne_journalise_rien():
    journal = CapabilityTransitionLog()

    def _plante():
        raise RuntimeError("panne")

    evaluer_capacite("cap-j", _plante, journal=journal)
    assert journal.entries == []


# ---------------------------------------------------------------------------
# Robustesse structurelle
# ---------------------------------------------------------------------------


def test_capability_status_est_gele():
    statut = CapabilityStatus(capability_id="cap-k", state=CapabilityState.ACTIVE, reasons=[])
    with pytest.raises(Exception):
        statut.state = CapabilityState.DEGRADED  # type: ignore[misc]
