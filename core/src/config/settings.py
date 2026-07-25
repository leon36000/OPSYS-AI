from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from redaction import safe_traceback
from vault import SecretProvider, SecretRef

logger = logging.getLogger(__name__)

# Patterns typiques de secrets inline (pour rejet immédiat)
_INLINE_PATTERNS = ("sk-", "Bearer ", "eyJ", "x-api-key", "Authorization:")


class SettingsError(Exception):
    """Exception levée pour les erreurs de configuration avec message expurgé."""


class Settings:
    """Conteneur de configuration non sensible. Les champs sensibles sont
    stockés sous forme de SecretRef (jamais en clair dans les logs / json).
    """

    __slots__ = ("mode", "endpoint", "timeout", "litellm_key")

    def __init__(
        self,
        mode: str,
        endpoint: str,
        timeout: int,
        litellm_key: Any,  # SecretRef
    ) -> None:
        self.mode = mode
        self.endpoint = endpoint
        self.timeout = timeout
        self.litellm_key = litellm_key

    def __repr__(self) -> str:
        return (
            f"Settings(mode={self.mode!r}, endpoint={self.endpoint!r}, "
            f"timeout={self.timeout!r}, litellm_key=***REDIGE***)"
        )


def load_settings(yaml_path: Path, provider: SecretProvider) -> Settings:
    """Charge la configuration depuis un fichier YAML (valeurs non sensibles).
    Les noms de secrets sont résolus via le provider.
    Détecte et rejette toute valeur inline suspecte (T5/A3).
    Fail-closed : erreur si un secret requis est absent.
    En cas d'exception, rédige automatiquement la traceback (A4).
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"Settings file not found: {yaml_path}")

    try:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        if not isinstance(raw, dict):
            raise ValueError("Settings YAML must be a dictionary")

        # --- champs non sensibles avec valeurs par défaut raisonnables ---
        mode = raw.get("mode", "dev")
        endpoint = raw.get("endpoint", "http://localhost:8000")
        timeout = raw.get("timeout", 30)

        # --- résolution du secret litellm_key ---
        secret_name = raw.get("litellm_key")
        if secret_name is None:
            raise ValueError("Missing required secret: litellm_key")  # proof:allow — fixture/message de test, aucun secret reel

        if not isinstance(secret_name, str):
            raise TypeError("litellm_key must be a string (secret name)")

        # Rejet des valeurs inline suspectes
        lowered = secret_name.lower()
        if any(lowered.startswith(pattern.lower()) for pattern in _INLINE_PATTERNS):
            raise ValueError(
                "Inline secret value detected for litellm_key; "
                "provide a secret name, not the actual value."
            )
        # Heuristique supplémentaire : chaîne très longue → probablement une clé
        if len(secret_name) > 40:
            raise ValueError(
                "Inline secret value detected for litellm_key (too long); "
                "provide a secret name."
            )

        secret_ref = provider.get_secret(secret_name)
        if secret_ref is None:
            raise RuntimeError(
                f"Secret '{secret_name}' not found through provider; fail-closed."
            )

        settings = Settings(
            mode=mode,
            endpoint=endpoint,
            timeout=timeout,
            litellm_key=secret_ref,
        )
        logger.info("Settings loaded successfully from %s", yaml_path)
        return settings

    except SettingsError:
        raise  # already processed
    except Exception as exc:
        # A4: redact traceback and re-raise
        if hasattr(provider, "known_secret_values"):
            known = provider.known_secret_values()  # type: ignore[union-attr]
        else:
            known = []
        tb_text = safe_traceback(exc, secrets=known)
        raise SettingsError(tb_text) from exc
