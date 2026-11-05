"""Régression UI : distinguer les claims homonymes provenant de modules différents."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CANDIDATE = Path(__file__).resolve().parents[1]
_UI_PATH = _CANDIDATE / "src" / "opsys" / "console" / "memoire_ui.py"


def _ui():
    name = "opsys.console.memoire_ui_candidate"
    spec = importlib.util.spec_from_file_location(name, _UI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _paquet(contradictions):
    return {
        "status": "available",
        "limitations": [],
        "must_know": [],
        "evidence": [],
        "contradictions": contradictions,
    }


def _rendre(contradictions):
    return _ui().contenu(
        {"status": "ok", "verified": 0},
        _paquet(contradictions),
        prefixe="/console",
        csrf="fictif",
        module="M7",
        task="test fictif",
        files="",
    )


def test_claims_homonymes_sont_distingues_par_module():
    html = _rendre(
        [
            {"module": "M7", "claim_key": "claim-fictif", "evidence": []},
            {"module": "PROJET", "claim_key": "claim-fictif", "evidence": []},
        ]
    )

    assert "<h3>M7 · claim-fictif</h3>" in html
    assert "<h3>PROJET · claim-fictif</h3>" in html
    assert "<h3>claim-fictif</h3>" not in html


def test_ancien_paquet_sans_module_reste_affiche():
    html = _rendre([{"claim_key": "claim-ancien", "evidence": []}])

    assert "<h3>claim-ancien</h3>" in html
