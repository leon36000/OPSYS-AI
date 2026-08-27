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

_EVIDENCE_HASH_VALIDE = "sha256:" + ("a" * 64)


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
    resultat = evaluer_capacite("cap-z", lambda: _EVIDENCE_HASH_VALIDE)
    assert resultat.state == CapabilityState.ACTIVE
    assert resultat.reasons == ()


def test_evaluer_capacite_ne_fuite_pas_le_message_brut_de_l_exception():
    """Cas RED sécurité (revue TRIAD_CONSENSUS clôture C03, DeepSeek-V4-Pro,
    CRITIQUE, confirmée par lecture directe de la source) : le message brut
    d'une exception peut porter un secret/PII (ex. une clé rejetée par un
    appel externe). reasons ne doit JAMAIS contenir ce message en clair —
    seul le NOM DE TYPE de l'exception est une raison sûre (même discipline
    que opsys_core.errors.mapper_exception, C03-004, qui ne préserve que
    type(exc).__name__ dans son safe_message)."""
    secret = "hunter2-mot-de-passe-utilisateur"  # proof:allow — secret synthétique de test, jamais réel

    def _operation_qui_fuite():
        raise ValueError(f"authentification refusée avec la clé {secret}")

    resultat = evaluer_capacite("cap-secret", _operation_qui_fuite)
    assert resultat.state == CapabilityState.QUARANTINED
    assert not any(secret in r for r in resultat.reasons), (
        "FUITE: le secret de l'exception est présent en clair dans reasons"
    )
    assert any("ValueError" in r for r in resultat.reasons), (
        "le type de l'exception doit rester visible pour le diagnostic"
    )


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
    assert statut.reasons == ()


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
    resultat = transitionner(depart, CapabilityState.ACTIVE, reasons=[], evidence_hash=_EVIDENCE_HASH_VALIDE)
    assert resultat.state == CapabilityState.ACTIVE


@pytest.mark.parametrize(
    "evidence_hash_invalide",
    (
        "not-a-hash",
        "sha256:deadbeef",
        "sha256:" + ("A" * 64),
        object(),
    ),
)
def test_promotion_vers_active_avec_preuve_invalide_est_refusee_sans_journalisation(
    evidence_hash_invalide: object,
):
    """Une valeur truthy mais non vérifiable ne doit jamais devenir ACTIVE.

    Le test couvre les deux frontières d'exécution réelles : un appelant
    peut fournir une chaîne arbitraire et une opération typée peut livrer
    un objet inattendu au runtime. Aucun de ces cas ne doit enregistrer
    une promotion ou divulguer la valeur invalide dans la raison."""
    depart = CapabilityStatus(
        capability_id="cap-evidence-invalide",
        state=CapabilityState.DEGRADED,
        reasons=("dégradation initiale",),
    )
    journal = CapabilityTransitionLog()

    resultat = transitionner(
        depart,
        CapabilityState.ACTIVE,
        reasons=(),
        evidence_hash=evidence_hash_invalide,  # type: ignore[arg-type]
        journal=journal,
    )

    assert resultat.state == CapabilityState.DEGRADED
    assert any("invalide" in raison for raison in resultat.reasons)
    assert all(str(evidence_hash_invalide) not in raison for raison in resultat.reasons)
    assert journal.entries == []


def test_evaluer_capacite_avec_preuve_invalide_ne_devient_pas_active():
    """La vérification doit protéger le chemin public evaluer_capacite()."""
    journal = CapabilityTransitionLog()

    resultat = evaluer_capacite(
        "cap-evaluation-invalide",
        lambda: "evidence-not-sha256",
        journal=journal,
    )

    assert resultat.state == CapabilityState.UNKNOWN
    assert any("invalide" in raison for raison in resultat.reasons)
    assert journal.entries == []


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
    transitionner(depart, CapabilityState.ACTIVE, reasons=[], evidence_hash=_EVIDENCE_HASH_VALIDE, journal=journal)
    assert len(journal.entries) == 1
    entree = journal.entries[0]
    assert entree.capability_id == "cap-g"
    assert entree.depuis == CapabilityState.DEGRADED
    assert entree.vers == CapabilityState.ACTIVE
    assert entree.evidence_hash == _EVIDENCE_HASH_VALIDE


def test_journal_n_enregistre_pas_une_promotion_refusee():
    """Une promotion REFUSÉE (pas de preuve) n'est pas un changement d'état
    réel — elle ne doit pas polluer le journal des transitions RÉUSSIES."""
    journal = CapabilityTransitionLog()
    depart = CapabilityStatus(capability_id="cap-h", state=CapabilityState.DEGRADED, reasons=["dégradation initiale"])
    transitionner(depart, CapabilityState.ACTIVE, reasons=[], evidence_hash=None, journal=journal)
    assert journal.entries == []


def test_evaluer_capacite_avec_succes_journalise_la_transition():
    journal = CapabilityTransitionLog()
    evaluer_capacite("cap-i", lambda: _EVIDENCE_HASH_VALIDE, journal=journal)
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


def test_capability_status_reasons_est_immuable_en_profondeur():
    """Cas RED sécurité (revue TRIAD_CONSENSUS clôture C03, Qwen3.7-Max,
    MAJEURE, confirmée par lecture directe de la source) :
    @dataclass(frozen=True) empêche seulement la RÉASSIGNATION d'un
    attribut (test_capability_status_est_gele ci-dessus vérifie EXACTEMENT
    ça) — mais PAS la mutation du CONTENU d'un attribut mutable. Avant
    correction, `reasons: list[str]` restait modifiable via `.append(...)`
    sur une instance prétendument « gelée ». reasons doit être un tuple :
    les tuples n'ont pas de .append, la mutation lève AttributeError."""
    statut = CapabilityStatus(capability_id="cap-l", state=CapabilityState.ACTIVE, reasons=[])
    with pytest.raises(AttributeError):
        statut.reasons.append("mutation silencieuse d'un objet gelé")
