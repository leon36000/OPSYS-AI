import os
import pytest
from types import SimpleNamespace


def _import_config_modules():
    import importlib
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.abspath(os.path.join(here, ".."))
    sys.path.insert(0, config_dir)
    try:
        vault = importlib.import_module("vault")
        settings = importlib.import_module("settings")
        redaction = importlib.import_module("redaction")
    finally:
        sys.path.remove(config_dir)
    return vault, settings, redaction


@pytest.fixture
def cfg():
    vault, settings, redaction = _import_config_modules()
    return SimpleNamespace(vault=vault, settings=settings, redaction=redaction)


def test_safe_traceback_purges_secret_value(cfg):
    secret = "super-secret-token"  # proof:allow — fixture/message de test, aucun secret reel
    try:
        raise ValueError("failure", secret)
    except ValueError as exc:
        tb_text = cfg.redaction.safe_traceback(exc, secrets=[secret])

    assert "super-secret-token" not in tb_text
    assert "ValueError" in tb_text


def test_safe_traceback_purges_secret_ref_value(cfg):
    ref = cfg.vault.SecretRef("api_key", "ref-secret-value")
    try:
        raise RuntimeError("failure", ref)
    except RuntimeError as exc:
        tb_text = cfg.redaction.safe_traceback(exc, secrets=[ref.reveal("test-context")])

    assert "ref-secret-value" not in tb_text
    assert "RuntimeError" in tb_text
