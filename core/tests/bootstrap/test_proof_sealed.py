"""Tests pour core/scripts/verify_proof_sealed.py (chantier CI-hardening,
remplace le placeholder BLOCKED du job CI `proof-sealed`, C02-005).

Fixtures SYNTHÉTIQUES (tmp_path) — jamais le vrai evidence/tasks/ du
dépôt pour la logique de détection elle-même (celle-ci est prouvée sur
des cas construits, positifs ET négatifs) ; la preuve d'intégration
réelle (au moins une tâche réellement scellée committée) est distincte
et arrive avec la première tâche qui traverse effectivement ce
mécanisme (chantier CI-hardening lui-même, cf. Evidence Bundle).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import verify_proof_sealed as vps  # noqa: E402


def _verdict(*, vendor: str, verdict: str, prompt_sha256: str, objections: list | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "vendor": vendor,
        "verdict": verdict,
        "prompt_sha256": prompt_sha256,
        "objections": objections or [],
    }


def _ecrire_task(root: Path, task_id: str, *, evidence_json: dict | None, verdicts: list[dict]) -> Path:
    dossier = root / "evidence" / "tasks" / task_id
    dossier.mkdir(parents=True)
    if evidence_json is not None:
        (dossier / "evidence.json").write_text(json.dumps(evidence_json), encoding="utf-8")
    if verdicts:
        (dossier / "reviews").mkdir()
        for i, v in enumerate(verdicts):
            (dossier / "reviews" / f"{v['vendor']}.json").write_text(json.dumps(v), encoding="utf-8")
    return dossier


def _avec_racine(tmp_path, monkeypatch):
    monkeypatch.setattr(vps, "_EVIDENCE_ROOT", tmp_path / "evidence" / "tasks")


# ---------------------------------------------------------------------------
# verifier_task — cas positifs et négatifs
# ---------------------------------------------------------------------------


def test_verifier_task_ok_avec_sceau_coherent_et_un_vendor_approve(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-001",
        evidence_json={"task_id": "T-001", "evidence_sha256": "abc123"},
        verdicts=[_verdict(vendor="deepseek", verdict="APPROVE", prompt_sha256="sha-x")],
    )
    ok, rapport = vps.verifier_task("T-001")
    assert ok, rapport


def test_verifier_task_echoue_si_evidence_json_absent(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    (tmp_path / "evidence" / "tasks" / "T-002").mkdir(parents=True)
    ok, rapport = vps.verifier_task("T-002")
    assert not ok
    assert "evidence.json absent" in rapport


def test_verifier_task_echoue_si_aucun_verdict(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(tmp_path, "T-003", evidence_json={"task_id": "T-003"}, verdicts=[])
    ok, rapport = vps.verifier_task("T-003")
    assert not ok
    assert "aucun verdict" in rapport


def test_verifier_task_echoue_si_sceau_prompt_sha256_incoherent(tmp_path, monkeypatch):
    """Cas RED central : 2 verdicts prétendant approuver la MÊME tâche
    mais avec des prompt_sha256 DIFFÉRENTS — preuve qu'ils n'ont PAS vu
    le même pack byte-identique, sceau rompu."""
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-004",
        evidence_json={"task_id": "T-004"},
        verdicts=[
            _verdict(vendor="deepseek", verdict="APPROVE", prompt_sha256="sha-a"),
            _verdict(vendor="gemini", verdict="APPROVE", prompt_sha256="sha-b"),
        ],
    )
    ok, rapport = vps.verifier_task("T-004")
    assert not ok
    assert "INCOHÉRENT" in rapport


def test_verifier_task_echoue_si_objection_critical_open_presente(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-005",
        evidence_json={"task_id": "T-005"},
        verdicts=[
            _verdict(
                vendor="deepseek",
                verdict="REJECT",
                prompt_sha256="sha-x",
                objections=[{"status": "OPEN", "severity": "CRITICAL", "text": "faille réelle"}],
            )
        ],
    )
    ok, rapport = vps.verifier_task("T-005")
    assert not ok
    assert "CRITICAL/OPEN" in rapport


def test_verifier_task_objection_resolved_ne_bloque_pas(tmp_path, monkeypatch):
    """Une objection CRITICAL mais RESOLVED (déjà traitée par un tour
    suivant) ne doit PAS bloquer — seule OPEN+CRITICAL bloque."""
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-006",
        evidence_json={"task_id": "T-006"},
        verdicts=[
            _verdict(
                vendor="deepseek",
                verdict="APPROVE",
                prompt_sha256="sha-x",
                objections=[{"status": "RESOLVED", "severity": "CRITICAL", "text": "corrigée au tour suivant"}],
            )
        ],
    )
    ok, rapport = vps.verifier_task("T-006")
    assert ok, rapport


def test_verifier_task_echoue_si_zero_vendor_approve(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-007",
        evidence_json={"task_id": "T-007"},
        verdicts=[_verdict(vendor="deepseek", verdict="REJECT", prompt_sha256="sha-x")],
    )
    ok, rapport = vps.verifier_task("T-007")
    assert not ok
    assert "insuffisant" in rapport


# ---------------------------------------------------------------------------
# main() — sélection des cibles (--task répétable) et code retour
# ---------------------------------------------------------------------------


def test_main_avec_task_explicite_ne_verifie_que_celle_la(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path, "T-OK",
        evidence_json={"task_id": "T-OK"},
        verdicts=[_verdict(vendor="deepseek", verdict="APPROVE", prompt_sha256="sha-x")],
    )
    _ecrire_task(tmp_path, "T-CASSEE", evidence_json=None, verdicts=[])
    # T-CASSEE existe et est invalide, mais --task T-OK ne doit PAS la toucher.
    rc = vps.main(["--task", "T-OK"])
    assert rc == 0


def test_main_sans_argument_verifie_tout_et_echoue_si_une_tache_cassee(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path, "T-OK2",
        evidence_json={"task_id": "T-OK2"},
        verdicts=[_verdict(vendor="deepseek", verdict="APPROVE", prompt_sha256="sha-x")],
    )
    _ecrire_task(tmp_path, "T-CASSEE2", evidence_json=None, verdicts=[])
    rc = vps.main([])
    assert rc == 1


def test_main_task_id_absent_du_disque_echoue_explicitement(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    (tmp_path / "evidence" / "tasks").mkdir(parents=True)
    rc = vps.main(["--task", "T-FANTOME"])
    assert rc == 1


def test_main_evidence_root_absent_echoue_explicitement(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    rc = vps.main([])
    assert rc == 1
