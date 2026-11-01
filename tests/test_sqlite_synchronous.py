"""Durabilité SQLite (revue adverse D-5) : FULL par défaut, NORMAL seulement sur demande, valeur inconnue refusée."""

from __future__ import annotations

import pytest

from opsys import stockage


def _synchrone(url: str) -> int:
    with stockage.moteur(url).connect() as cnx:
        return int(cnx.exec_driver_sql("PRAGMA synchronous").scalar_one())


def test_synchronous_est_full_par_defaut(tmp_path, monkeypatch):
    monkeypatch.delenv("OPSYS_SQLITE_SYNCHRONOUS", raising=False)
    assert _synchrone(f"sqlite:///{tmp_path / 'a.db'}") == 2  # 0 OFF, 1 NORMAL, 2 FULL, 3 EXTRA


def test_normal_et_extra_sont_acceptes_sur_demande(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_SQLITE_SYNCHRONOUS", "normal")
    assert _synchrone(f"sqlite:///{tmp_path / 'b.db'}") == 1
    monkeypatch.setenv("OPSYS_SQLITE_SYNCHRONOUS", "EXTRA")
    assert _synchrone(f"sqlite:///{tmp_path / 'c.db'}") == 3


@pytest.mark.parametrize("valeur", ["OFF", "0", "n'importe quoi", ""])
def test_une_valeur_dangereuse_ou_inconnue_est_refusee_sauf_vide_qui_vaut_full(tmp_path, monkeypatch, valeur):
    monkeypatch.setenv("OPSYS_SQLITE_SYNCHRONOUS", valeur)
    url = f"sqlite:///{tmp_path / 'd.db'}"
    if valeur == "":
        # une variable vide est traitée comme absente : FULL
        assert _synchrone(url) in {2}
        return
    with pytest.raises(RuntimeError):
        _synchrone(url)
