"""Fixtures des tests du sas de publication sociale."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fabriques_sociales import JETON  # noqa: E402
from m7_marketing.sas_social import doubles, politique, reseaux  # noqa: E402

FICTIF = True
COMPTE = "page-horizon-fictive"


@pytest.fixture
def declarations():
    return reseaux.declarations_par_defaut()


@pytest.fixture
def politique_sas():
    return politique.PolitiqueSas()


@pytest.fixture
def comptes_actifs():
    return {(reseau, COMPTE) for reseau in reseaux.RESEAUX}


@pytest.fixture
def journal():
    return []


@pytest.fixture
def proprietaire():
    return {"par": "nathan", "role": "nathan_owner", "source": "approbation"}


@contextlib.contextmanager
def _jeton_de_test():
    yield JETON


@pytest.fixture
def fournisseur():
    return _jeton_de_test


@pytest.fixture
def adaptateurs():
    """Un double par réseau, qui attend le jeton de test."""
    return {reseau: classe(jeton_attendu=JETON) for reseau, classe in doubles.DOUBLES.items()}
