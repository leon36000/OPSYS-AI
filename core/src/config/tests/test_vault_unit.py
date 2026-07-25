import json
import logging
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


# ---------------------------------------------------------------------------
# Tests existants (adaptés aux nouvelles signatures)
# ---------------------------------------------------------------------------

def test_secret_ref_str_repr_fstring_json_redacted(cfg):
    ref = cfg.vault.SecretRef("api_key", "shhh-12345")
    assert str(ref) == "***REDIGE***"
    assert repr(ref) == "***REDIGE***"
    assert f"{ref}" == "***REDIGE***"
    assert "%s" % ref == "***REDIGE***"
    assert json.dumps(ref, default=str) == '"***REDIGE***"'


def test_secret_ref_copy_pickle_yaml_blocked_or_redacted(cfg):
    import copy
    import pickle
    import yaml

    ref = cfg.vault.SecretRef("api_key", "shhh-12345")

    for name, op in (("copy", lambda: copy.copy(ref)), ("deepcopy", lambda: copy.deepcopy(ref))):
        try:
            result = op()
        except TypeError:
            continue
        assert str(result) == "***REDIGE***", f"{name} leaked the secret value"

    try:
        pickled = pickle.dumps(ref)
    except TypeError:
        pass
    else:
        assert b"shhh-12345" not in pickled

    try:
        dumped = yaml.dump(ref)
    except TypeError:
        pass
    else:
        assert "shhh-12345" not in dumped


def test_secret_ref_reveal_audits_without_value(cfg, caplog):
    caplog.set_level(logging.INFO)
    ref = cfg.vault.SecretRef("api_key", "shhh-12345")
    # Contexte obligatoire (A2)
    assert ref.reveal("audit-context") == "shhh-12345"
    log_text = caplog.text.lower()
    assert "reveal" in log_text or "acces_secret" in log_text
    assert "shhh-12345" not in caplog.text


def test_secret_ref_uses_slots_and_rejects_vars(cfg):
    ref = cfg.vault.SecretRef("api_key", "shhh-12345")
    assert getattr(type(ref), "__slots__", None) is not None
    with pytest.raises(TypeError):
        vars(ref)


def test_env_secret_provider_respects_prefix_and_absence(cfg, monkeypatch):
    monkeypatch.setenv("OPSYS_LITELLM_KEY", "env-secret-value")
    monkeypatch.setenv("OTHER_SECRET", "other-secret-value")
    monkeypatch.delenv("OPSYS_MISSING", raising=False)

    provider = cfg.vault.EnvSecretProvider(prefix="OPSYS_")
    ref = provider.get_secret("litellm_key")
    assert isinstance(ref, cfg.vault.SecretRef)
    # Contexte obligatoire ajouté
    assert ref.reveal("test-context") == "env-secret-value"
    assert provider.get_secret("missing") is None
    assert provider.get_secret("OTHER_SECRET") is None

    # Aucune exposition d'os.environ
    if hasattr(provider, "environ"):
        assert provider.environ is not os.environ


def test_settings_loads_secret_names_and_resolves_via_provider(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("OPSYS_LITELLM_KEY", "real-litellm-secret")
    yaml_path = tmp_path / "valid_settings.yaml"
    yaml_path.write_text(
        "mode: dev\n"
        "endpoint: http://localhost:8000\n"
        "timeout: 30\n"
        "litellm_key: litellm_key\n"
    )

    provider = cfg.vault.EnvSecretProvider()
    settings = cfg.settings.load_settings(yaml_path, provider)

    assert isinstance(settings, cfg.settings.Settings)
    assert settings.mode == "dev"
    assert settings.endpoint == "http://localhost:8000"
    assert settings.timeout == 30
    assert isinstance(settings.litellm_key, cfg.vault.SecretRef)
    assert settings.litellm_key.reveal("test-context") == "real-litellm-secret"


def test_settings_fail_closed_when_required_secret_missing(cfg, monkeypatch, tmp_path):
    monkeypatch.delenv("OPSYS_LITELLM_KEY", raising=False)
    yaml_path = tmp_path / "missing_secret.yaml"
    yaml_path.write_text(
        "mode: dev\n"
        "endpoint: http://localhost:8000\n"
        "timeout: 30\n"
        "litellm_key: litellm_key\n"
    )

    provider = cfg.vault.EnvSecretProvider()
    with pytest.raises(Exception):
        cfg.settings.load_settings(yaml_path, provider)


def test_settings_rejects_or_redacts_inline_secret_values(cfg, monkeypatch, tmp_path):
    monkeypatch.delenv("OPSYS_LITELLM_KEY", raising=False)
    yaml_path = tmp_path / "inline_secret.yaml"
    yaml_path.write_text(
        "mode: dev\n"
        "endpoint: http://localhost:8000\n"
        "timeout: 30\n"
        "litellm_key: sk-live-inline-secret\n"
    )

    provider = cfg.vault.EnvSecretProvider()
    leaked = False
    settings = None
    try:
        settings = cfg.settings.load_settings(yaml_path, provider)
    except Exception:
        pass

    if settings is not None:
        raw = json.dumps(settings, default=str)
        if "sk-live-inline-secret" in raw:
            leaked = True
        value = getattr(settings, "litellm_key", None)
        if isinstance(value, str) and "sk-live" in value:
            leaked = True
        if isinstance(value, cfg.vault.SecretRef):
            revealed = value.reveal("test-context")
            if revealed == "sk-live-inline-secret":
                leaked = True

    assert not leaked


def test_redaction_masks_known_secrets_patterns_and_partial_leaks(cfg):
    secrets = ["known-secret", "abcdef"]
    text = (
        "use known-secret and sk-ABCDEF0123456789 "
        "with Bearer xyz.jwt.token and abcdef"
    )
    result = cfg.redaction.redact(text, secrets=secrets)

    assert "known-secret" not in result
    assert "sk-ABCDEF0123456789" not in result
    assert "xyz.jwt.token" not in result
    assert "abcdef" not in result
    assert "***REDIGE***" in result


def test_redaction_handles_empty_and_unchanged_text(cfg):
    assert cfg.redaction.redact("", secrets=["x"]) == ""
    assert cfg.redaction.redact(None, secrets=["x"]) in (None, "")
    assert cfg.redaction.redact("plain text without secrets", secrets=["x"]) == "plain text without secrets"


def test_settings_no_secret_leak_in_json_or_logs(cfg, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("OPSYS_LITELLM_KEY", "real-litellm-secret")
    yaml_path = tmp_path / "valid_settings.yaml"
    yaml_path.write_text(
        "mode: dev\n"
        "endpoint: http://localhost:8000\n"
        "timeout: 30\n"
        "litellm_key: litellm_key\n"
    )

    caplog.set_level(logging.DEBUG)
    provider = cfg.vault.EnvSecretProvider()
    settings = cfg.settings.load_settings(yaml_path, provider)
    provider.get_secret("litellm_key")

    raw = json.dumps(settings, default=str)
    assert "real-litellm-secret" not in raw
    assert "real-litellm-secret" not in caplog.text


# ---------------------------------------------------------------------------
# Nouveaux tests (A2, A3, A4)
# ---------------------------------------------------------------------------

def test_reveal_requires_non_empty_context(cfg):
    ref = cfg.vault.SecretRef("key", "val")
    with pytest.raises(ValueError, match="contexte d'accès obligatoire"):
        ref.reveal("")
    with pytest.raises(ValueError, match="contexte d'accès obligatoire"):
        ref.reveal("   ")


def test_redact_auto_collects_secrets_from_provider(cfg, monkeypatch):
    monkeypatch.setenv("OPSYS_SECRET1", "alpha-beta-gamma")
    provider = cfg.vault.EnvSecretProvider()
    # Charge le secret dans le cache du provider
    ref = provider.get_secret("secret1")
    assert ref is not None
    text_with_secret = "this is alpha-beta-gamma token"  # proof:allow — fixture/message de test
    result = cfg.redaction.redact(text_with_secret, provider=provider)
    assert "alpha-beta-gamma" not in result
    assert "***REDIGE***" in result


def test_exception_in_load_settings_redacts_secrets_in_message(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("OPSYS_LITELLM_KEY", "super-secret-value")
    yaml_path = tmp_path / "valid.yaml"
    yaml_path.write_text(
        "mode: dev\n"
        "endpoint: http://localhost:8000\n"
        "timeout: 30\n"
        "litellm_key: litellm_key\n"
    )

    provider = cfg.vault.EnvSecretProvider()

    # Patch Settings.__init__ pour qu'il lève une exception contenant la valeur
    original_init = cfg.settings.Settings.__init__
    def leaking_init(self, *args, **kwargs):
        # La valeur est déjà dans le cache du provider
        leaked = provider.known_secret_values()[0]  # "super-secret-value"
        raise ValueError(leaked)

    monkeypatch.setattr(cfg.settings.Settings, "__init__", leaking_init)

    with pytest.raises(cfg.settings.SettingsError) as exc_info:
        cfg.settings.load_settings(yaml_path, provider)

    assert "super-secret-value" not in str(exc_info.value)
    # Confirmation que la redaction a bien eu lieu
    assert "***REDIGE***" in str(exc_info.value)
