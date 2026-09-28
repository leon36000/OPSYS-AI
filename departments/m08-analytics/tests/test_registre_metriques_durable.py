"""Branchement du registre des définitions de métriques (T3.1) sur le stockage durable de
l'instance (ADR-0009) — même preuve que `test_registre_durable.py` pour le registre de
snapshots : un enregistrement survit à une nouvelle instance Python (aucun cache, la preuve
qu'un redémarrage du processus ne perd rien), et l'idempotence tient contre le VRAI backend
durable (`MaillonsDurables`), pas seulement contre une liste Python en mémoire.

Aucune garde AST du département ne porte sur ce fichier : toutes scannent `src/m8_analytics`,
jamais `tests/` (voir test_conformite.py) — aucune adaptation n'a donc été nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics import registre_metriques  # noqa: E402

from opsys import stockage  # noqa: E402

DEPARTEMENT = "m08-analytics"
REGISTRE_NOM = "definitions_metriques"

_DEFINITION = {
    "metric_id": "m4_duree_reelle_minutes",
    "departement_proprietaire": "m04-field-ops",
    "unite": "min",
    "source": "Module M4 — WCT",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": 0, "plage_max": None},
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire, isolée de ~/.opsys et de toute autre suite (OPSYS_BASE_URL)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def test_adaptateur_branche_le_registre_de_production_sur_stockage_maillons():
    """Preuve statique, même patron que `test_registre_durable.py` pour les snapshots :
    `outils()` sans argument — utilisé par `charger_outils()` en production — adosse le registre
    des définitions à `stockage.maillons("m08-analytics", "definitions_metriques")`."""
    texte = (_SRC / "m8_analytics" / "outils.py").read_text(encoding="utf-8")
    assert 'stockage.maillons("m08-analytics", "definitions_metriques")' in texte


def test_definition_enregistree_survit_a_une_nouvelle_instance(base_durable):
    with stockage.transaction():
        cible = stockage.maillons(DEPARTEMENT, REGISTRE_NOM)
        reponse = registre_metriques.enregistrer_definition(_DEFINITION, cible)
        assert reponse == {"enregistree": True, "deja_a_jour": False, "verdict": None}

    # Nouvelle instance de MaillonsDurables, comme après un redémarrage du processus MCP :
    # reconstruit son état entièrement depuis la base, sans rien connaître de `cible` ci-dessus.
    relue = stockage.maillons(DEPARTEMENT, REGISTRE_NOM)
    assert len(relue) == 1
    assert registre_metriques.resoudre("m4_duree_reelle_minutes", relue) == _DEFINITION


def test_idempotence_tient_contre_le_vrai_backend_durable(base_durable):
    """La preuve en mémoire (test_registre_metriques.py) utilise une liste Python, qui accepte
    trivialement `reversed(list(...))` et `append`. Cette preuve rejoue le même scénario contre
    `MaillonsDurables` (SQLite réel) pour vérifier qu'aucune hypothèse de la liste en mémoire ne
    manque à l'implémentation durable."""
    with stockage.transaction():
        cible = stockage.maillons(DEPARTEMENT, REGISTRE_NOM)
        registre_metriques.enregistrer_definition(_DEFINITION, cible)
        reponse = registre_metriques.enregistrer_definition(_DEFINITION, cible)
        assert reponse["deja_a_jour"] is True

    relue = stockage.maillons(DEPARTEMENT, REGISTRE_NOM)
    assert len(relue) == 1  # jamais deux lignes pour le même enregistrement rejoué


def test_nouvelle_version_durable_ajoute_un_maillon_et_resoudre_prend_la_derniere(base_durable):
    with stockage.transaction():
        cible = stockage.maillons(DEPARTEMENT, REGISTRE_NOM)
        registre_metriques.enregistrer_definition(_DEFINITION, cible)
        modifiee = {**_DEFINITION, "fraicheur_attendue_jours": 5}
        reponse = registre_metriques.enregistrer_definition(modifiee, cible)
        assert reponse == {"enregistree": True, "deja_a_jour": False, "verdict": None}

    relue = stockage.maillons(DEPARTEMENT, REGISTRE_NOM)
    assert len(relue) == 2
    assert registre_metriques.resoudre("m4_duree_reelle_minutes", relue)["fraicheur_attendue_jours"] == 5
