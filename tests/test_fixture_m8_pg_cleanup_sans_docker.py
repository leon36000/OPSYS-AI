"""Régressions du teardown PG, avec doubles : aucun appel à Docker ni PostgreSQL."""

from __future__ import annotations

import contextlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from memoire import doubles

FICHIER_FIXTURE = Path(__file__).with_name("test_postgresql_rejeu_m8_cycle_multijours.py")


def _charger_fixture(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # Le module de test cible calcule son marqueur au chargement. Neutraliser cette sonde évite
    # tout appel à `docker info`; le gestionnaire PG est doublé lui aussi dans chaque scénario.
    monkeypatch.setattr(doubles, "raison_sans_docker", lambda: "Docker volontairement indisponible")
    spec = importlib.util.spec_from_file_location("fixture_pg_m8_cleanup_under_test", FICHIER_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Resultat:
    def scalar_one(self) -> int:
        return 170005


class _Connexion:
    def __enter__(self) -> _Connexion:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, _requete: Any) -> _Resultat:
        return _Resultat()


class _Moteur:
    def __init__(self, appels: list[tuple[Any, ...]]) -> None:
        self.appels = appels

    def connect(self) -> _Connexion:
        return _Connexion()

    def dispose(self) -> None:
        self.appels.append(("dispose",))


@pytest.mark.parametrize("phase", ["montage", "semis"])
def test_teardown_libere_moteur_et_monde_si_initialisation_echoue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    module = _charger_fixture(monkeypatch)
    appels: list[tuple[Any, ...]] = []
    url = "postgresql+psycopg://fictif@127.0.0.1:55432/postgres"

    @contextlib.contextmanager
    def faux_postgres_ephemere(*, stockage_en_memoire: bool):
        assert stockage_en_memoire is True
        appels.append(("pg_enter",))
        try:
            yield "postgresql://fictif@127.0.0.1:55432/postgres"
        finally:
            appels.append(("pg_exit",))

    monkeypatch.setattr(module, "postgres_ephemere", faux_postgres_ephemere)
    monkeypatch.setattr(module.stockage, "migrer", lambda cible: appels.append(("migrer", cible)))
    monkeypatch.setattr(module.stockage, "liberer", lambda cible=None: appels.append(("liberer", cible)))
    moteur = _Moteur(appels)
    monkeypatch.setattr(module, "create_engine", lambda cible: (appels.append(("engine", cible)), moteur)[1])

    def monter(*_args: Any, **_kwargs: Any) -> object:
        appels.append(("monter",))
        if phase == "montage":
            raise RuntimeError("montage fictif en échec")
        return object()

    def semer(*_args: Any) -> None:
        appels.append(("semer",))
        raise RuntimeError("semis fictif en échec")

    monkeypatch.setattr(module.pm, "monter", monter)
    monkeypatch.setattr(module.pm, "lire_yaml", lambda _path: {"fictif": True})
    monkeypatch.setattr(module.pm, "semer_tout", semer)
    demonter_reel = module.pm.demonter

    def demonter_observe() -> None:
        appels.append(("demonter",))
        demonter_reel()

    monkeypatch.setattr(module.pm, "demonter", demonter_observe)

    with pytest.raises(RuntimeError, match=f"{phase} fictif en échec"):
        next(module.monde_postgres._fixture_function(tmp_path, monkeypatch, lambda: None))

    assert ("pg_exit",) in appels
    assert ("dispose",) in appels
    assert ("liberer", url) in appels
    assert appels.count(("demonter",)) == 1
    assert appels.count(("liberer", None)) == 1
    assert appels.index(("demonter",)) < appels.index(("liberer", url))
    assert ("semer",) not in appels if phase == "montage" else ("semer",) in appels
