"""Result[T] — succès ou échec explicite, jamais une exception qui
s'échappe silencieusement en un succès implicite (C03-004)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from .errors import CoreError, ErrorCode, mapper_exception

T = TypeVar("T")


@dataclass(frozen=True)
class Result(Generic[T]):
    value: T | None
    error: CoreError | None

    def __post_init__(self) -> None:
        if self.value is not None and self.error is not None:
            raise ValueError("Result ne peut pas porter à la fois une valeur ET une erreur")

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @staticmethod
    def ok(value: T) -> "Result[T]":
        return Result(value=value, error=None)

    @staticmethod
    def fail(error: CoreError) -> "Result[T]":
        return Result(value=None, error=error)


def executer(
    operation: Callable[[], T],
    *,
    code: str = ErrorCode.UNKNOWN_FAILURE.value,
    retryable: bool = False,
) -> "Result[T]":
    """Exécute `operation` et retourne un Result. Toute exception NON
    explicitement mappée par l'appelant devient UNKNOWN_FAILURE si `code`
    n'est pas fourni ou n'est pas dans la taxonomie — jamais un
    Result.ok() accidentel, jamais une exception qui s'échappe."""
    try:
        valeur = operation()
    except Exception as exc:
        return Result.fail(mapper_exception(exc, code=code, retryable=retryable))
    return Result.ok(valeur)
