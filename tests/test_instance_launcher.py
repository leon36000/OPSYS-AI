"""Sélection explicite du lanceur possédé par l'installateur, sans ouverture SQL."""
import sys
from pathlib import Path

import pytest

from opsys import cli


@pytest.fixture
def lanceur(tmp_path):
    path = tmp_path / "python privé fictif"
    path.write_text("#!/bin/bash\n# fictif: true\nexit 0\n")
    path.chmod(0o700)
    return path


def test_reinitialisation_conserve_l_identite_du_wrapper(monkeypatch, lanceur):
    monkeypatch.setenv("OPSYS_PYTHON_LAUNCHER", str(lanceur))
    assert cli._interpreteur_instance(None) == lanceur
    assert cli._interpreteur_instance(str(lanceur)) == lanceur


def test_selection_explicite_sans_profil_prive(monkeypatch, lanceur):
    monkeypatch.delenv("OPSYS_PYTHON_LAUNCHER", raising=False)
    assert cli._interpreteur_instance(str(lanceur)) == lanceur
    assert cli._interpreteur_instance(None) == Path(sys.executable)


@pytest.mark.parametrize("valeur", ["", "relatif", "/absent/fictif/python"])
def test_profil_declare_invalide_ne_retombe_pas_sur_sys_executable(monkeypatch, valeur):
    monkeypatch.setenv("OPSYS_PYTHON_LAUNCHER", valeur)
    with pytest.raises(ValueError, match="aucun repli"):
        cli._interpreteur_instance(None)


def test_selection_contradictoire_refusee(monkeypatch, lanceur):
    monkeypatch.setenv("OPSYS_PYTHON_LAUNCHER", str(lanceur))
    with pytest.raises(ValueError, match="diffère"):
        cli._interpreteur_instance(sys.executable)


def test_profil_non_executable_refuse(monkeypatch, lanceur):
    lanceur.chmod(0o600)
    monkeypatch.setenv("OPSYS_PYTHON_LAUNCHER", str(lanceur))
    with pytest.raises(ValueError, match="aucun repli"):
        cli._interpreteur_instance(None)
