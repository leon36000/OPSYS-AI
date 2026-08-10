"""Tests des schémas stricts tâches/preuves/revues/gates (C01-002).

Contrat exact (task spec `tasks/C01-002.md`) :
- `validate_task(dict) -> None`, `validate_evidence(dict) -> None`,
  `validate_review(dict) -> None`, `validate_gate(dict) -> None` — lèvent
  sur toute violation, retournent `None` (silencieusement) sur un objet
  valide.
- Validation SANS dépendance externe (stdlib uniquement — aucune lib
  `jsonschema`).
- `additionalProperties` interdit sur les objets de sécurité (evidence,
  review) — une clé EN TROP doit être rejetée, pas seulement une clé
  manquante.
- Schémas versionnés.

Écrit par l'Orchestrateur AVANT toute implémentation (RED d'abord, TDD) —
le crew implémente `tools/proof/schema_validation.py` (+ les 4
`tools/proof/schemas/*.schema.json`) CONTRE ce fichier.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.proof.schema_validation import (
    SchemaValidationError,
    validate_evidence,
    validate_gate,
    validate_review,
    validate_task,
)

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _tache_valide() -> dict:
    return {
        "schema_version": "1.0",
        "task_id": "C01-002",
        "title": "Définir les schémas stricts",
        "status": "IN_PROGRESS",
        "risk": "CRITICAL",
        "review_policy": "INDEPENDENT_REVIEW",
        "dependencies": ["C01-001"],
        "outputs": ["tools/proof/schema_validation.py"],
    }


def _preuve_valide() -> dict:
    return {
        "schema_version": "1.0",
        "task_id": "C01-002",
        "implementer_id": "claude-code-orchestrateur",
        "commit": "a" * 64,
        "tree": "b" * 64,
        "inputs_manifest": [{"path": "tasks/C01-002.md", "sha256": "c" * 64, "size": 100}],
        "outputs_manifest": [{"path": "tools/proof/schema_validation.py", "sha256": "d" * 64, "size": 200}],
        "commands": [
            {
                "argv": ["python3", "-m", "pytest", "-q", "tools/proof/tests/test_schemas.py"],
                "expected_returncode": 0,
                "actual_returncode": 0,
                "stdout_sha256": "e" * 64,
                "stderr_sha256": "f" * 64,
            }
        ],
    }


def _revue_valide() -> dict:
    return {
        "schema_version": "1.0",
        "subject_type": "TASK",
        "subject_id": "C01-002",
        "reviewer_id": "DeepSeek-V4-Pro",
        "vendor": "deepseek",
        "verdict": "APPROVE",
        "objections": [],
        "evidence_sha256": "1" * 64,
    }


def _gate_valide() -> dict:
    return {
        "schema_version": "1.0",
        "phase": "C01",
        "run_id": "2" * 32,
        "commit": "3" * 64,
        "tree": "4" * 64,
        "status": "MEASURED_PASS",
        "checks": [
            {
                "check_id": "C01-CHK-01",
                "argv": ["python3", "-m", "pytest", "-q", "tools/proof/tests"],
                "expected_returncode": 0,
                "actual_returncode": 0,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Les 4 noms minimaux, un par cas RED obligatoire de la spec.
# ---------------------------------------------------------------------------


def test_d_finir_les_sch_mas_stricts_des_t_ches_preuves_revues_et_gat_1():
    """Cas RED obligatoire : rejeter champ obligatoire absent — sur les 4
    validateurs, retirer un champ requis lève SchemaValidationError."""
    for constructeur, valider, champ in [
        (_tache_valide, validate_task, "task_id"),
        (_preuve_valide, validate_evidence, "commit"),
        (_revue_valide, validate_review, "verdict"),
        (_gate_valide, validate_gate, "status"),
    ]:
        objet = constructeur()
        # Référence : l'objet intact passe.
        valider(objet)
        mutile = copy.deepcopy(objet)
        del mutile[champ]
        with pytest.raises(SchemaValidationError):
            valider(mutile)


def test_d_finir_les_sch_mas_stricts_des_t_ches_preuves_revues_et_gat_2():
    """Cas RED obligatoire : rejeter statut inconnu — task.status,
    gate.status et review.verdict n'acceptent qu'un ensemble fermé de
    valeurs, jamais une chaîne arbitraire."""
    tache = _tache_valide()
    tache["status"] = "STATUT_INVENTE_INEXISTANT"
    with pytest.raises(SchemaValidationError):
        validate_task(tache)

    gate = _gate_valide()
    gate["status"] = "STATUT_INVENTE_INEXISTANT"
    with pytest.raises(SchemaValidationError):
        validate_gate(gate)

    revue = _revue_valide()
    revue["verdict"] = "VERDICT_INVENTE_INEXISTANT"
    with pytest.raises(SchemaValidationError):
        validate_review(revue)


def test_d_finir_les_sch_mas_stricts_des_t_ches_preuves_revues_et_gat_3():
    """Cas RED obligatoire : rejeter commande sans argv/returncode/stdout/
    stderr hashes — chaque champ requis d'une commande, retiré isolément,
    doit faire échouer validate_evidence."""
    for champ in ("argv", "expected_returncode", "actual_returncode", "stdout_sha256", "stderr_sha256"):
        preuve = _preuve_valide()
        del preuve["commands"][0][champ]
        with pytest.raises(SchemaValidationError):
            validate_evidence(preuve)


def test_d_finir_les_sch_mas_stricts_des_t_ches_preuves_revues_et_gat_4():
    """Cas RED obligatoire : rejeter preuve sans manifestes d'entrée et de
    sortie — les deux manifestes sont requis ET non vides."""
    preuve_sans_entrees = _preuve_valide()
    preuve_sans_entrees["inputs_manifest"] = []
    with pytest.raises(SchemaValidationError):
        validate_evidence(preuve_sans_entrees)

    preuve_sans_sorties = _preuve_valide()
    preuve_sans_sorties["outputs_manifest"] = []
    with pytest.raises(SchemaValidationError):
        validate_evidence(preuve_sans_sorties)

    preuve_sans_manifestes = _preuve_valide()
    del preuve_sans_manifestes["inputs_manifest"]
    del preuve_sans_manifestes["outputs_manifest"]
    with pytest.raises(SchemaValidationError):
        validate_evidence(preuve_sans_manifestes)


# ---------------------------------------------------------------------------
# Robustesse additionnelle.
# ---------------------------------------------------------------------------


def test_validateurs_acceptent_un_objet_valide_sans_lever():
    """Les 4 objets de référence, intacts, passent tous silencieusement
    (retour None, aucune exception)."""
    assert validate_task(_tache_valide()) is None
    assert validate_evidence(_preuve_valide()) is None
    assert validate_review(_revue_valide()) is None
    assert validate_gate(_gate_valide()) is None


def test_additional_properties_interdit_sur_evidence_et_review():
    """Objets de sécurité (evidence, review) : une clé SUPPLÉMENTAIRE non
    prévue par le schéma est rejetée, pas seulement une clé manquante —
    empêche l'injection silencieuse d'un champ non validé."""
    preuve = _preuve_valide()
    preuve["champ_invente_non_prevu"] = "valeur"
    with pytest.raises(SchemaValidationError):
        validate_evidence(preuve)

    revue = _revue_valide()
    revue["champ_invente_non_prevu"] = "valeur"
    with pytest.raises(SchemaValidationError):
        validate_review(revue)


def test_manifest_entry_champs_requis():
    """Une entrée de manifeste (inputs_manifest/outputs_manifest) sans
    path/sha256/size est rejetée — pas seulement la présence de la liste."""
    for champ in ("path", "sha256", "size"):
        preuve = _preuve_valide()
        del preuve["inputs_manifest"][0][champ]
        with pytest.raises(SchemaValidationError):
            validate_evidence(preuve)


def test_sha256_forme_invalide_rejete():
    """Un champ documenté comme SHA-256 (commit/tree/evidence_sha256/
    sha256 de manifeste) qui n'est pas 64 caractères hexadécimaux est
    rejeté — une chaîne quelconque ne doit jamais passer pour un hash."""
    preuve = _preuve_valide()
    preuve["commit"] = "pas-un-hash"
    with pytest.raises(SchemaValidationError):
        validate_evidence(preuve)

    revue = _revue_valide()
    revue["evidence_sha256"] = "trop-court"
    with pytest.raises(SchemaValidationError):
        validate_review(revue)


def test_les_4_fichiers_schema_json_existent_et_sont_versionnes():
    """Les 4 fichiers `.schema.json` déclarés en sortie existent, sont du
    JSON valide, et portent chacun un champ de version explicite."""
    noms = ["task.schema.json", "evidence.schema.json", "review.schema.json", "gate.schema.json"]
    for nom in noms:
        chemin = SCHEMAS_DIR / nom
        assert chemin.is_file(), f"{nom} absent"
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        assert "schema_version" in contenu or "$id" in contenu, (
            f"{nom} n'est pas versionné (ni schema_version ni $id)"
        )


def test_dependance_stdlib_uniquement():
    """Aucun import d'une bibliothèque tierce (ex. jsonschema) dans le
    module de validation — vérifié en lisant le code source, pas en
    espérant qu'un import échoue à l'exécution."""
    source = (SCHEMAS_DIR.parent / "schema_validation.py").read_text(encoding="utf-8")
    interdits = ["import jsonschema", "from jsonschema"]
    for motif in interdits:
        assert motif not in source, f"dépendance tierce détectée : {motif}"
