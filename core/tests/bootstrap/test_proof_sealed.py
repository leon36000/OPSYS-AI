"""Tests pour core/scripts/verify_proof_sealed.py (chantier CI-hardening,
remplace le placeholder BLOCKED du job CI `proof-sealed`, C02-005).

Fixtures SYNTHÉTIQUES (tmp_path) — jamais le vrai evidence/tasks/ du
dépôt pour la logique de détection elle-même (celle-ci est prouvée sur
des cas construits, positifs ET négatifs) ; la preuve d'intégration
réelle (au moins une tâche réellement scellée committée) est distincte
et arrive avec la première tâche qui traverse effectivement ce
mécanisme (chantier CI-hardening lui-même, cf. Evidence Bundle).

SCHÉMA DES FIXTURES : aligné sur la sortie RÉELLE de civ_review.py
(reviewer_model, objections[].severite en français) — vérifié contre
~/proof-method/scripts/civ_review.py et
reviews/TEMPLATE-prompt-revue-neutre.md le 2026-08-11, PAS un schéma
inventé pour le test (cf. discipline « donnée de test aveugle ne prouve
rien » — un fixture qui invente son propre schéma valide un chemin qui
n'existe pas côté production).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import verify_proof_sealed as vps  # noqa: E402


def _verdict(
    *, reviewer_model: str, verdict: str, prompt_sha256: str, objections: list | None = None
) -> dict:
    return {
        "verdict": verdict,
        "objections": objections or [],
        "reviewer_model": reviewer_model,
        "modele_servi": reviewer_model,
        "prompt_sha256": prompt_sha256,
        "date_heure": "2026-08-11T00:00:00Z",
    }


def _ecrire_task(root: Path, task_id: str, *, evidence_json: dict | None, verdicts: list[dict]) -> Path:
    dossier = root / "evidence" / "tasks" / task_id
    dossier.mkdir(parents=True)
    if evidence_json is not None:
        (dossier / "evidence.json").write_text(json.dumps(evidence_json), encoding="utf-8")
    if verdicts:
        (dossier / "reviews").mkdir()
        for i, v in enumerate(verdicts):
            (dossier / "reviews" / f"{v['reviewer_model']}.json").write_text(json.dumps(v), encoding="utf-8")
    return dossier


def _avec_racine(tmp_path, monkeypatch):
    monkeypatch.setattr(vps, "_EVIDENCE_ROOT", tmp_path / "evidence" / "tasks")


# ---------------------------------------------------------------------------
# _vendor_of — dérivation vendor depuis reviewer_model
# ---------------------------------------------------------------------------


def test_vendor_of_modeles_connus():
    assert vps._vendor_of("gpt-5.6-terra-pro") == "openai"
    assert vps._vendor_of("qwen3.8-max") == "alibaba"
    assert vps._vendor_of("deepseek-v4-pro") == "deepseek"


def test_vendor_of_insensible_a_la_casse():
    assert vps._vendor_of("GPT-5.6-Terra-Pro") == vps._vendor_of("gpt-5.6-terra-pro")


def test_vendor_of_modele_inconnu_repli_sur_lui_meme():
    """Fail-closed sur l'inconnu : jamais fusionné à tort avec un vendor
    existant — un modèle absent du tableau reste son propre singleton."""
    assert vps._vendor_of("muse-spark-1.2") == "muse-spark-1.2"


# ---------------------------------------------------------------------------
# verifier_task — cas positifs et négatifs
# ---------------------------------------------------------------------------


def test_verifier_task_ok_avec_sceau_coherent_et_un_vendor_approve(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-001",
        evidence_json={"task_id": "T-001", "evidence_sha256": "abc123"},
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
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
            _verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-a"),
            _verdict(reviewer_model="gemini-3.1-pro", verdict="APPROVE", prompt_sha256="sha-b"),
        ],
    )
    ok, rapport = vps.verifier_task("T-004")
    assert not ok
    assert "INCOHÉRENT" in rapport


def test_verifier_task_echoue_si_objection_critique_presente(tmp_path, monkeypatch):
    """Champ réel : severite="critique" (français) — jamais un couple
    status/severity anglais qui n'existe pas dans le schéma civ_review."""
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-005",
        evidence_json={"task_id": "T-005"},
        verdicts=[
            _verdict(
                reviewer_model="deepseek-v4-pro",
                verdict="REJECT",
                prompt_sha256="sha-x",
                objections=[{"severite": "critique", "fichier": "x.py", "description": "faille réelle", "preuve": "L12"}],
            )
        ],
    )
    ok, rapport = vps.verifier_task("T-005")
    assert not ok
    assert "CRITIQUE" in rapport


def test_verifier_task_objection_mineure_ne_bloque_pas(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-006",
        evidence_json={"task_id": "T-006"},
        verdicts=[
            _verdict(
                reviewer_model="deepseek-v4-pro",
                verdict="APPROVE",
                prompt_sha256="sha-x",
                objections=[{"severite": "mineure", "fichier": "x.py", "description": "style", "preuve": "L1"}],
            )
        ],
    )
    ok, rapport = vps.verifier_task("T-006")
    assert ok, rapport


def test_verifier_task_objection_majeure_avertit_mais_ne_bloque_pas(tmp_path, monkeypatch):
    """« Majeure » est surfacée (visible dans le rapport) mais NON
    bloquante par ce script — la résolution cross-round est hors
    périmètre (cf. docstring module)."""
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-006B",
        evidence_json={"task_id": "T-006B"},
        verdicts=[
            _verdict(
                reviewer_model="deepseek-v4-pro",
                verdict="APPROVE",
                prompt_sha256="sha-x",
                objections=[{"severite": "majeure", "fichier": "x.py", "description": "à surveiller", "preuve": "L5"}],
            )
        ],
    )
    ok, rapport = vps.verifier_task("T-006B")
    assert ok, rapport
    assert "MAJEURE" in rapport


def test_verifier_task_echoue_si_un_seul_reject_meme_parmi_plusieurs_approve(tmp_path, monkeypatch):
    """Consensus = TOUS APPROVE (définition tally_reviews.py) — un seul
    REJECT parmi N verdicts bloque, même si les autres approuvent."""
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-007",
        evidence_json={"task_id": "T-007"},
        verdicts=[
            _verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x"),
            _verdict(reviewer_model="gpt-5.6-terra-pro", verdict="REJECT", prompt_sha256="sha-x"),
        ],
    )
    ok, rapport = vps.verifier_task("T-007")
    assert not ok
    assert "consensus non atteint" in rapport


def test_verifier_task_echoue_si_vendors_distincts_insuffisants(tmp_path, monkeypatch):
    """2 reviewer_model APPROVE mais MÊME vendor (xai) : décorrélation
    anti-Sybil insuffisante pour min_vendors_approve=2."""
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-008",
        evidence_json={"task_id": "T-008"},
        verdicts=[
            _verdict(reviewer_model="composer-2.5", verdict="APPROVE", prompt_sha256="sha-x"),
            _verdict(reviewer_model="grok-4.5", verdict="APPROVE", prompt_sha256="sha-x"),
        ],
    )
    ok, rapport = vps.verifier_task("T-008", min_vendors_approve=2)
    assert not ok
    assert "insuffisant" in rapport


# ---------------------------------------------------------------------------
# main() — sélection des cibles (--task répétable), --min-vendors, et code retour
# ---------------------------------------------------------------------------


def test_main_avec_task_explicite_ne_verifie_que_celle_la(tmp_path, monkeypatch):
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path, "T-OK",
        evidence_json={"task_id": "T-OK"},
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
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
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
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


def test_main_min_vendors_propage_a_verifier_task(tmp_path, monkeypatch):
    """--min-vendors 3 avec seulement 2 vendors distincts APPROVE doit
    échouer — preuve que le flag CLI atteint réellement verifier_task,
    pas seulement parsé et ignoré."""
    _avec_racine(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path, "T-MV",
        evidence_json={"task_id": "T-MV"},
        verdicts=[
            _verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x"),
            _verdict(reviewer_model="gpt-5.6-terra-pro", verdict="APPROVE", prompt_sha256="sha-x"),
        ],
    )
    rc = vps.main(["--task", "T-MV", "--min-vendors", "3"])
    assert rc == 1
