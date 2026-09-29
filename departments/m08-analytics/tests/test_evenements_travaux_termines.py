"""Consommateur `m4.travaux_termines` de M8 (ADR-0009 §3, PLAN T1.2-c, partie 2) : bout en bout
sur le bus d'événements réel (`opsys.evenements.repartir`), les manifestes réels du dépôt
(`opsys.departements.charger_departements`, pas les départements de démonstration du socle) et
une base SQLite temporaire migrée — jamais une simulation en mémoire.

M8 n'a ici aucune donnée de coût ni de marge (mission `department.yaml`, DEFINITION-PRODUIT.md
§7 M8 : « M8 ne fait pas la comptabilité »). Il enregistre seulement les faits mesurables portés
par le WCT — durée réelle, et type de travaux quand il est présent — au registre des snapshots
déjà existant (même table que `m8_rapport_metriques`, voir `outils.py::_recevoir_travaux_termines`).

Les charges publiées ici sont des WCT synthétiques (fictifs, jamais une donnée réelle de client),
même patron que `tests/test_evenements.py::_wct_exemple` du socle.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m8_analytics import registre as m8_registre

from opsys import evenements, stockage
from opsys.departements import charger_departements

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_MODULE_SOURCE_TRAVAUX = "m04-field-ops"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, isolée de ~/.opsys et de toute autre suite (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements():
    """Manifestes réels de `departments/` (pas une fixture de démonstration) : preuve que
    `department.yaml:evenements.consomme` et `m8_analytics.outils.consommateurs()` s'accordent
    pour de vrai, exactement comme `opsys-metier verifier` et `opsys-metier evenements repartir` en production."""
    # Seul ce département reçoit les événements : les autres consommateurs (M2, M10…) ont
    # leurs propres préconditions et leurs propres tests.
    tous = charger_departements(_RACINE_DEPARTEMENTS)
    return {"m08-analytics": tous["m08-analytics"]}


def _wct_travaux_termines(**overrides):
    base = {
        "wct_id": "wct-m8-nominal",
        "intervention_id": "int-1",
        "lead_id": "lead-1",
        "technicien_id": "tech-1",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 245,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
        "devis_id": "devis-1",
        "statut": "completed_verified",
    }
    base.update(overrides)
    return base


def _snapshots_travaux() -> list[dict]:
    cible = m8_registre.RegistreSnapshots(maillons=stockage.maillons("m08-analytics", "snapshots"))
    return [m for m in cible.lire() if m["module_source"] == _MODULE_SOURCE_TRAVAUX]


# ---------------------------------------------------------------------------
# Nominal : durée réelle + type de travaux enregistrés, rien d'autre
# ---------------------------------------------------------------------------
def test_nominal_enregistre_duree_et_type_travaux_sans_cout_ni_marge(base_durable, departements):
    charge = _wct_travaux_termines(wct_id="wct-m8-nominal", duree_reelle_minutes=245, type_travaux="gouttières")
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    # M7 ET M8 sont tous deux abonnés à m4.travaux_termines (T1.2-c) : les deux sont traités.
    assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

    snapshots = _snapshots_travaux()
    assert len(snapshots) == 1
    maillon = snapshots[0]
    assert maillon["horodatage"] == "2026-09-28T14:00:00-04:00"
    # Exactement ces clés : aucun coût, aucune marge, rien d'inventé au-delà du WCT.
    assert maillon["valeurs"] == {
        "m4_wct_id": "wct-m8-nominal",
        "m4_intervention_id": "int-1",
        "m4_duree_reelle_minutes": "245",
        "m4_type_travaux": "gouttières",
    }


def test_type_travaux_absent_du_wct_nest_jamais_invente(base_durable, departements):
    charge = _wct_travaux_termines(wct_id="wct-m8-sans-type", duree_reelle_minutes=90)
    assert "type_travaux" not in charge

    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    snapshots = _snapshots_travaux()
    assert len(snapshots) == 1
    assert snapshots[0]["valeurs"] == {
        "m4_wct_id": "wct-m8-sans-type",
        "m4_intervention_id": "int-1",
        "m4_duree_reelle_minutes": "90",
    }
    assert "m4_type_travaux" not in snapshots[0]["valeurs"]


# ---------------------------------------------------------------------------
# Idempotence : une relivraison du même fait (même wct_id) ne crée jamais un second maillon
# ---------------------------------------------------------------------------
def test_relivraison_est_idempotente_un_seul_maillon(base_durable, departements):
    charge = _wct_travaux_termines(wct_id="wct-m8-relivraison", duree_reelle_minutes=180)

    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-m8-1")
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert len(_snapshots_travaux()) == 1

    # Relivraison : le même fait (même wct_id), publié une seconde fois sous un NOUVEL
    # evenement_id — un evenement_id identique serait déjà un no-op au niveau de l'outbox
    # elle-même (ADR-0009 §3) ; ceci teste l'idempotence du CONSOMMATEUR, une garantie plus forte
    # (ex. producteur qui rejoue l'émission après une panne réseau sans réutiliser l'id).
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-m8-2")
    resume2 = evenements.repartir(departements, maintenant="2026-09-28T18:05:00+00:00")
    assert resume2 == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

    snapshots = _snapshots_travaux()
    assert len(snapshots) == 1  # jamais un second maillon pour le même wct_id
    assert snapshots[0]["valeurs"]["m4_duree_reelle_minutes"] == "180"

    # `repartir()` lui-même ne rejoue jamais un événement déjà traité pour ce consommateur.
    resume3 = evenements.repartir(departements, maintenant="2026-09-28T18:10:00+00:00")
    assert resume3 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(_snapshots_travaux()) == 1
