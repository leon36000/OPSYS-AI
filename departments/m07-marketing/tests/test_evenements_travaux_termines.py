"""Consommateur `m4.travaux_termines` de M7 (ADR-0009 §3, PLAN T1.2-c, partie 2) : bout en bout
sur le bus d'événements réel (`opsys.evenements.repartir`), les manifestes réels du dépôt
(`opsys.departements.charger_departements`, pas les départements de démonstration du socle) et
une base SQLite temporaire migrée — jamais une simulation en mémoire.

M7 prépare une demande d'avis EN BROUILLON (écriture interne au registre du département, jamais
un envoi) seulement si `consentement_marketing` est vrai ET que `client_satisfait` n'est pas
faux ; tout champ absent vaut refus, fail-closed (`reputation/demande_avis.py`, testé isolément
dans `tests/reputation/test_demande_avis.py`). Ce fichier prouve l'intégration réelle : bus,
manifeste, registre durable, idempotence.

Les charges publiées ici sont des WCT synthétiques (fictifs, jamais une donnée réelle de client),
même patron que `tests/test_evenements.py::_wct_exemple` du socle.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m7_marketing.reputation import demande_avis

from opsys import evenements, stockage
from opsys.departements import charger_departements

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]


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
    `department.yaml:evenements.consomme` et `m7_marketing.outils.consommateurs()` s'accordent
    pour de vrai, exactement comme `opsys verifier` et `opsys evenements repartir` en production."""
    return charger_departements(_RACINE_DEPARTEMENTS)


def _wct_travaux_termines(**overrides):
    base = {
        "wct_id": "wct-m7-nominal",
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


def _demandes_avis() -> list[dict]:
    return list(stockage.maillons("m07-marketing", "demandes_avis"))


# ---------------------------------------------------------------------------
# Autorisation : consentement vrai ET client satisfait -> brouillon déposé, jamais envoyé
# ---------------------------------------------------------------------------
def test_consentement_vrai_et_client_satisfait_depose_un_brouillon(base_durable, departements):
    charge = _wct_travaux_termines(
        wct_id="wct-m7-consentement-ok", ville="Repentigny", type_travaux="gouttières",
        consentement_marketing=True, client_satisfait=True,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    # M7 ET M8 sont tous deux abonnés à m4.travaux_termines (T1.2-c) : les deux sont traités.
    assert resume == {"livres": 2, "traites": 2, "echecs": 0, "quarantaines": 0, "ignores": 0}

    demandes = _demandes_avis()
    assert len(demandes) == 1
    brouillon = demandes[0]
    assert brouillon["wct_id"] == "wct-m7-consentement-ok"
    assert brouillon["approval_status"] == "PROPOSE"  # jamais un envoi
    assert brouillon["ville"] == "Repentigny"
    assert brouillon["type_travaux"] == "gouttières"


# ---------------------------------------------------------------------------
# Fail-closed : consentement absent, consentement faux, client insatisfait -> aucun brouillon
# ---------------------------------------------------------------------------
def test_consentement_absent_ne_depose_aucun_brouillon(base_durable, departements):
    charge = _wct_travaux_termines(wct_id="wct-m7-consentement-absent", client_satisfait=True)
    assert "consentement_marketing" not in charge
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert resume == {"livres": 2, "traites": 2, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert _demandes_avis() == []


def test_consentement_faux_et_client_insatisfait_ne_depose_aucun_brouillon(base_durable, departements):
    charge = _wct_travaux_termines(
        wct_id="wct-m7-refus", consentement_marketing=False, client_satisfait=False,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert resume == {"livres": 2, "traites": 2, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert _demandes_avis() == []


def test_client_insatisfait_seul_ne_depose_aucun_brouillon(base_durable, departements):
    """`consentement_marketing` vrai ne suffit pas : `client_satisfait = false` refuse aussi."""
    charge = _wct_travaux_termines(
        wct_id="wct-m7-client-insatisfait", consentement_marketing=True, client_satisfait=False,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert _demandes_avis() == []


# ---------------------------------------------------------------------------
# Idempotence : une relivraison du même fait (même wct_id) ne dépose jamais un second brouillon
# ---------------------------------------------------------------------------
def test_relivraison_est_idempotente_un_seul_brouillon(base_durable, departements):
    charge = _wct_travaux_termines(
        wct_id="wct-m7-relivraison", consentement_marketing=True, client_satisfait=True,
    )

    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-m7-1")
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    demandes_apres_1 = _demandes_avis()
    assert len(demandes_apres_1) == 1
    id_initial = demandes_apres_1[0]["id"]

    # Relivraison : le même fait (même wct_id), publié une seconde fois sous un NOUVEL
    # evenement_id — un evenement_id identique serait déjà un no-op au niveau de l'outbox
    # elle-même (ADR-0009 §3) ; ceci teste l'idempotence du CONSOMMATEUR, une garantie plus forte
    # (ex. producteur qui rejoue l'émission après une panne réseau sans réutiliser l'id).
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-m7-2")
    resume2 = evenements.repartir(departements, maintenant="2026-09-28T18:05:00+00:00")
    assert resume2 == {"livres": 2, "traites": 2, "echecs": 0, "quarantaines": 0, "ignores": 0}

    demandes_apres_2 = _demandes_avis()
    assert len(demandes_apres_2) == 1  # jamais un second brouillon pour le même wct_id
    assert demandes_apres_2[0]["id"] == id_initial

    # `repartir()` lui-même ne rejoue jamais un événement déjà traité pour ce consommateur.
    resume3 = evenements.repartir(departements, maintenant="2026-09-28T18:10:00+00:00")
    assert resume3 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(_demandes_avis()) == 1


# ---------------------------------------------------------------------------
# Aucun contenu public, aucune photo publiée (garde-fou documenté dans demande_avis.py)
# ---------------------------------------------------------------------------
def test_brouillon_ne_porte_jamais_de_photo(base_durable, departements):
    charge = _wct_travaux_termines(
        wct_id="wct-m7-photos", consentement_marketing=True, client_satisfait=True,
        photos=["chantier-avant.jpg", "chantier-apres.jpg"],
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    demandes = _demandes_avis()
    assert len(demandes) == 1
    assert "photos" not in demandes[0]
    assert set(demandes[0]) == {
        "id", "type", "wct_id", "intervention_id", "lead_id", "ville", "type_travaux", "texte",
        "approval_status",
    }


def test_module_pur_demande_avis_naimporte_jamais_opsys():
    """Modules purs (AGENTS.md/T1.2-c) : `reputation/demande_avis.py` ne connaît pas `opsys` —
    seul l'adaptateur `outils.py` sait où persister le brouillon."""
    source = Path(demande_avis.__file__).read_text(encoding="utf-8")
    assert "import opsys" not in source
    assert "from opsys" not in source
