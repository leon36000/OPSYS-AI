"""Tests — ingestion des avis depuis les fixtures S008a (lecture seule D-043).

TDD RED capturé : ces tests ont été écrits AVANT l'implémentation de ingestion.py.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

_M7 = Path(__file__).resolve().parents[2]
_REPUTATION = _M7 / "src" / "m7_marketing" / "reputation"

from m7_marketing.reputation import ingestion


# ---------------------------------------------------------------------------
# Fixture YAML minimale utilisée par plusieurs tests
# ---------------------------------------------------------------------------
_FIXTURE_MINI_YAML = """\
schema_version: 1
module: M7-marketing
avis:
  - id: test-001
    fictif: true
    note: 5
    plateforme: google
    date: "2026-01-01"
    texte: "Excellent service."
  - id: test-002
    fictif: true
    note: 2
    plateforme: facebook
    date: "2026-02-01"
    texte: "Déçu par la prestation."
"""


def _fixture_tmp(contenu: str) -> Path:
    """Écrit une fixture YAML temporaire et retourne son chemin."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    tmp.write(contenu)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_charger_avis_retourne_liste():
    """charger_avis() retourne une list."""
    path = _fixture_tmp(_FIXTURE_MINI_YAML)
    avis = ingestion.charger_avis(chemin=path)
    assert isinstance(avis, list)


def test_charger_avis_nombre_correct():
    """charger_avis() retourne le bon nombre d'avis."""
    path = _fixture_tmp(_FIXTURE_MINI_YAML)
    avis = ingestion.charger_avis(chemin=path)
    assert len(avis) == 2


def test_charger_avis_champs_presents():
    """Chaque avis porte id, note, plateforme, date et texte."""
    path = _fixture_tmp(_FIXTURE_MINI_YAML)
    avis = ingestion.charger_avis(chemin=path)
    for a in avis:
        assert "id" in a
        assert "note" in a
        assert "plateforme" in a
        assert "date" in a
        assert "texte" in a


def test_charger_avis_note_est_entier():
    """La note de chaque avis est un entier."""
    path = _fixture_tmp(_FIXTURE_MINI_YAML)
    avis = ingestion.charger_avis(chemin=path)
    for a in avis:
        assert isinstance(a["note"], int)


def test_charger_avis_fixture_reelle():
    """charger_avis() charge correctement la fixture réelle S008a."""
    avis = ingestion.charger_avis()
    assert isinstance(avis, list)
    assert len(avis) > 0
    for a in avis:
        assert "id" in a
        assert isinstance(a.get("note"), int)


def test_charger_avis_fichier_absent_leve_erreur():
    """FileNotFoundError si le chemin n'existe pas."""
    with pytest.raises(FileNotFoundError):
        ingestion.charger_avis(chemin=Path("/inexistant/fixture.yaml"))


def test_charger_avis_yaml_invalide_leve_erreur():
    """ValueError si le YAML ne contient pas un dict."""
    path = _fixture_tmp("- juste une liste\n- sans clé avis\n")
    with pytest.raises(ValueError):
        ingestion.charger_avis(chemin=path)


def test_charger_avis_fixture_immuable():
    """La fixture originale n'est pas modifiée après chargement (lecture seule D-043)."""
    fixture_path = ingestion._FIXTURE_DEFAULT
    if not fixture_path.exists():
        pytest.skip("Fixture réelle absente de l'environnement.")
    contenu_avant = fixture_path.read_bytes()
    ingestion.charger_avis()
    contenu_apres = fixture_path.read_bytes()
    assert contenu_avant == contenu_apres, "La fixture a été modifiée (interdit D-043)"


def test_ingestion_zero_reseau():
    """Le module ingestion.py n'importe pas urllib ni socket (zéro réseau)."""
    import ast as _ast

    source = (_REPUTATION / "ingestion.py").read_text(encoding="utf-8")
    tree = _ast.parse(source)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert "urllib" not in alias.name, "import urllib interdit"
                assert "socket" not in alias.name, "import socket interdit"
        elif isinstance(node, _ast.ImportFrom):
            module = node.module or ""
            assert "urllib" not in module, "import urllib interdit"
            assert "socket" not in module, "import socket interdit"
