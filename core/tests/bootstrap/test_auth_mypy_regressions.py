"""Régressions exécutables pour les deux corrections mypy de CLR-001."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "core" / "src"))
sys.path.insert(0, str(_REPO_ROOT / "core" / "src" / "auth"))
totp = importlib.import_module("totp")
admin_gate = importlib.import_module("admin_gate")


def test_admin_gate_refuse_un_timestep_absent_sans_ecrire_dans_le_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un résultat TOTP incohérent ne doit jamais consommer ``None``."""
    monkeypatch.setenv("OPSYS_ADMIN_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    monkeypatch.setattr(admin_gate.totp, "verify_totp", lambda *args, **kwargs: (True, None))

    gate = admin_gate.AdminGate()
    resultat = gate.verifier("123456", "127.0.0.1")

    assert resultat == {"autorise": False, "raison": "erreur_interne"}
    assert all(None not in timesteps for timesteps in gate._replay_state.values())


def test_totp_convertit_une_erreur_base32_en_resultat_invalide() -> None:
    """Une base32 invalide reste un échec contrôlé, jamais un AttributeError."""
    assert totp.verify_totp("not-base32!", "123456") == (False, None)
