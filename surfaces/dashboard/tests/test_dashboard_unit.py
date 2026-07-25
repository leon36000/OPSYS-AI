"""Tests unitaires pour dashboard_server (P0-5a)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers

DASHBOARD = _helpers.import_dashboard_server()


def test_mode_default_sans_config(tmp_path):
    config_path = tmp_path / "inexistant.yaml"
    mode, source = DASHBOARD.load_mode(config_path)
    assert mode == "horaire"
    assert source == "default"


def test_mode_override_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_MODE", "temps-reel")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mode: horaire\n", encoding="utf-8")
    mode, source = DASHBOARD.load_mode(config_path)
    assert mode == "temps-reel"
    assert source == "env"


def test_mode_lu_depuis_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mode: temps-reel\n", encoding="utf-8")
    mode, source = DASHBOARD.load_mode(config_path)
    assert mode == "temps-reel"
    assert source == "config"


def test_mode_invalide_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mode: inconnu\n", encoding="utf-8")
    mode, source = DASHBOARD.load_mode(config_path)
    assert mode == "horaire"
    assert source == "config"


def test_mode_invalide_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_MODE", "invalide")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mode: temps-reel\n", encoding="utf-8")
    mode, source = DASHBOARD.load_mode(config_path)
    assert mode == "horaire"
    assert source == "env"


def test_modules_valide(tmp_path):
    modules_path = tmp_path / "modules.yaml"
    data = [
        {"nom": "module-a", "statut": "ok"},
        {"nom": "module-b"},
    ]
    modules_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    modules, lisible = DASHBOARD.load_modules(modules_path)
    assert lisible is True
    assert len(modules) == 2
    assert modules[0]["nom"] == "module-a"
    assert modules[1]["nom"] == "module-b"


def test_modules_absent(tmp_path):
    modules_path = tmp_path / "modules.yaml"
    modules, lisible = DASHBOARD.load_modules(modules_path)
    assert lisible is False
    assert modules == []


def test_modules_yaml_casse(tmp_path):
    modules_path = tmp_path / "modules.yaml"
    modules_path.write_text("[ pas valide", encoding="utf-8")
    modules, lisible = DASHBOARD.load_modules(modules_path)
    assert lisible is False
    assert modules == []


def test_modules_structure_invalide(tmp_path):
    modules_path = tmp_path / "modules.yaml"
    modules_path.write_text("nom: module-a\n", encoding="utf-8")
    modules, lisible = DASHBOARD.load_modules(modules_path)
    assert lisible is False
    assert modules == []
