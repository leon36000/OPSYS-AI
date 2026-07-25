from __future__ import annotations

import os
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class SecretRef:
    """Wrapper immuable autour d'un secret, ne révèle jamais la valeur
    automatiquement (repr, str, format, sérialisation).
    """

    __slots__ = ("_name", "_value")

    def __init__(self, name: str, value: str) -> None:
        self._name = name
        self._value = value

    def __repr__(self) -> str:
        return "***REDIGE***"

    def __str__(self) -> str:
        return "***REDIGE***"

    def __format__(self, format_spec: str) -> str:
        return "***REDIGE***"

    def reveal(self, context: str = "") -> str:
        """Retourne la valeur secrète après journalisation d'audit (sans la valeur)."""
        logger.info(
            "SecretRef.reveal() called for '%s' with context '%s'",
            self._name,
            context,
        )
        return self._value

    # -- Bloque la sérialisation (A1) --
    def __reduce__(self):
        raise TypeError("Secrets cannot be pickled")

    def __copy__(self):
        raise TypeError("Secrets cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("Secrets cannot be deepcopied")

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretRef):
            return self._name == other._name and self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._name, self._value))


class SecretProvider(ABC):
    """Interface abstraite de fournisseur de secrets (fail-closed)."""

    @abstractmethod
    def get_secret(self, name: str) -> SecretRef | None:
        """Retourne un SecretRef ou None si le secret est introuvable."""
        ...


class EnvSecretProvider(SecretProvider):
    """Fournisseur lisant les secrets depuis des variables d'environnement
    préfixées. N'expose jamais l'intégralité d'os.environ.
    """

    def __init__(self, prefix: str = "OPSYS_") -> None:
        self._prefix = prefix

    def get_secret(self, name: str) -> SecretRef | None:
        env_var = f"{self._prefix}{name.upper()}"
        value = os.environ.get(env_var)
        if value is None:
            return None
        return SecretRef(name, value)
