"""Le stockage crée une nouvelle racine privée sans réparer les droits existants."""

from __future__ import annotations

import os
import stat

import pytest

from opsys import stockage

pytestmark = pytest.mark.skipif(os.name != "posix", reason="modes POSIX de la racine d'état")


def test_nouveau_home_est_prive_meme_avec_umask_partage(tmp_path, monkeypatch):
    home = tmp_path / "nouveau-home"
    monkeypatch.setenv("OPSYS_HOME", str(home))
    monkeypatch.delenv(stockage.ENV_URL, raising=False)
    ancien_umask = os.umask(0o002)
    try:
        url = stockage.url_base()
    finally:
        os.umask(ancien_umask)

    assert home.is_dir()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert url == f"sqlite:///{home / 'opsys.db'}"


@pytest.mark.parametrize("mode_existant", [0o700, 0o775])
def test_home_existant_conserve_ses_droits(tmp_path, monkeypatch, mode_existant):
    home = tmp_path / "home-existant"
    home.mkdir()
    home.chmod(mode_existant)
    monkeypatch.setenv("OPSYS_HOME", str(home))
    monkeypatch.delenv(stockage.ENV_URL, raising=False)

    assert stockage.url_base() == f"sqlite:///{home / 'opsys.db'}"
    assert stat.S_IMODE(home.stat().st_mode) == mode_existant
