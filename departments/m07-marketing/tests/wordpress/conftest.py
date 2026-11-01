"""Fixtures communes des tests WordPress : le vérificateur de référence et les vecteurs partagés."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

FICTIF = True
_ICI = Path(__file__).resolve().parent
_M7 = _ICI.parents[1]
CHEMIN_VECTEURS = _M7 / "contracts" / "opsys-connect-vecteurs.v1.json"
RACINE_DEPOT = _M7.parents[1]
DOSSIER_PLUGIN = RACINE_DEPOT / "integrations" / "wordpress" / "opsys-connect"


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, _ICI / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def reference():
    return _charger("reference_verificateur")


@pytest.fixture(scope="session")
def vecteurs():
    return json.loads(CHEMIN_VECTEURS.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------------------------
# Environnement complet : un site simulé, un client signataire, un journal, une horloge pilotable
# ---------------------------------------------------------------------------------------------------------------------
import contextlib  # noqa: E402
import types  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

SECRET_TEST = "secret-de-test-fictif-pour-le-simulateur-0123456789"
SITE_ID = "horizon-fictif.example"
INSTANT_0 = 1767225600  # 2026-01-01T00:00:00Z


class Horloge:
    def __init__(self) -> None:
        self.t = INSTANT_0

    def __call__(self) -> int:
        return self.t

    def avancer(self, secondes: int) -> None:
        self.t += secondes

    def maintenant(self) -> datetime:
        return datetime.fromtimestamp(self.t, UTC)


@pytest.fixture
def env(reference):
    """`env.client`, `env.site`, `env.journal` (flux), `env.sites` (registre), `env.horloge`, `env.secret`."""
    from m7_marketing.wordpress import sites
    from m7_marketing.wordpress.client import ClientWordPress

    simule_module = _charger("site_simule")
    horloge = Horloge()
    site_simule = simule_module.SiteSimule(reference, SECRET_TEST, SITE_ID, horloge)
    registre: list = []
    resultat = sites.enregistrer(
        registre,
        SITE_ID,
        "https://horizon-fictif.example",
        {"nom": "wordpress.horizon-fictif", "cle_id": "default"},
        ["post", "page"],
        True,
        "nathan",
        "2026-01-01T00:00:00Z",
    )
    assert resultat["accepte"], resultat
    site = sites.actifs(registre)[SITE_ID]
    compteur = iter(range(1, 10_000_000))
    secrets_ouverts: list[str] = []

    @contextlib.contextmanager
    def fournisseur():
        secrets_ouverts.append(SECRET_TEST)
        yield SECRET_TEST

    client = ClientWordPress(
        site,
        fournisseur,
        site_simule,
        horloge,
        lambda: f"nonce-client-{next(compteur):012d}",
    )
    return types.SimpleNamespace(
        client=client,
        site=site_simule,
        journal=[],
        sites=registre,
        horloge=horloge,
        secret=SECRET_TEST,
        site_wp=site,
        ouvertures_secret=secrets_ouverts,
    )
