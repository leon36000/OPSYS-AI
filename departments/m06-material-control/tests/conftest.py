from __future__ import annotations

import pytest

from opsys import stockage


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base SQLite fictive indépendante du runner privé de revue."""
    url = f"sqlite:///{tmp_path / 'm6-rebut-consumption-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()
