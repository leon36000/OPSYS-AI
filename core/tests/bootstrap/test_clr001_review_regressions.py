"""Régressions RED issues de la revue de CLR-001 / PR #526.

Ces tests verrouillent uniquement les findings encore actuels au HEAD de la PR :
- pack-validation doit échouer fermé si le contrat qualité ne produit aucune racine
  ou si son chargement échoue ;
- la normalisation SARIF CodeQL ne doit jamais faire collisionner core/scripts/
  avec scripts/.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "core" / "scripts"))

import run_codeql_scan as codeql  # noqa: E402
import run_pack_validation as pack  # noqa: E402


def _succes_structure(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="STRUCTURE_LINT: VERT", stderr="")


def test_pack_validation_refuse_zero_racine_qualite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pack, "charger_racines_qualite", lambda: ())
    monkeypatch.setattr(pack.subprocess, "run", _succes_structure)

    ok, rapport = pack.verifier_structure()

    assert ok is False
    assert "ROUGE" in rapport
    assert "racine" in rapport.lower()


@pytest.mark.parametrize(
    "erreur",
    [
        OSError("quality-scopes.toml illisible"),
        tomllib.TOMLDecodeError("quality-scopes.toml invalide"),
        RuntimeError("python_roots invalide"),
    ],
)
def test_pack_validation_convertit_erreur_contrat_en_rouge(
    monkeypatch: pytest.MonkeyPatch, erreur: Exception
) -> None:
    def _echec_chargement() -> tuple[Path, ...]:
        raise erreur

    monkeypatch.setattr(pack, "charger_racines_qualite", _echec_chargement)
    try:
        ok, rapport = pack.verifier_structure()
    except Exception as exc:  # pragma: no cover - message RED explicite si régression
        pytest.fail(f"verifier_structure a propagé {type(exc).__name__}: {exc}")

    assert ok is False
    assert "ROUGE" in rapport
    assert "quality-scopes" in rapport


@pytest.mark.parametrize(
    ("chemin", "attendu"),
    [
        ("core/src/opsys_core/ports/contracts.py", "src/opsys_core/ports/contracts.py"),
        ("core/scripts/run_pack_validation.py", "core/scripts/run_pack_validation.py"),
        ("scripts/run_pack_validation.py", "scripts/run_pack_validation.py"),
    ],
)
def test_codeql_normalise_uniquement_core_src_sans_collision(chemin: str, attendu: str) -> None:
    assert codeql._normaliser_chemin_sarif(chemin) == attendu
