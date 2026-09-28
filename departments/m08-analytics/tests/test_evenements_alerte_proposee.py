"""Producteur `m8.alerte_proposee` de M8 (ADR-0009 §3, PLAN T3.2) : bout en bout sur la base
durable réelle (`opsys.stockage`), à travers `opsys.outils.executer_atomique` — jamais une
simulation en mémoire — pour prouver que `m8_evaluer_qualite_metrique` publie effectivement
l'événement en production, sans changer sa réponse ni son autonomie T0
(`test_paliers_t3_1_coherents_avec_departements_md`, déjà vert, verrouille ce dernier point).

M9 n'est pas chargé ici : ce fichier ne prouve que le côté PRODUCTEUR (M8 seul, dans son propre
appel pytest). Le côté consommateur (M9) et la livraison par `evenements.repartir` sont prouvés
séparément par `departments/m09-strategic-intelligence/tests/
test_evenements_alerte_proposee_m8.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics.outils import outils  # noqa: E402

from opsys import stockage  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import EVENEMENTS_SORTANTS  # noqa: E402

_DEFINITION_M4 = {
    "metric_id": "m4_duree_reelle_minutes",
    "departement_proprietaire": "m04-field-ops",
    "unite": "min",
    "source": "Module M4 — WCT",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": None, "plage_max": None},
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire, isolée de ~/.opsys et de toute autre suite (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _evenements_publies(type_evenement: str) -> list[dict]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
            .order_by(EVENEMENTS_SORTANTS.c.cree_le)
        ).all()
    return [{"evenement_id": ligne.evenement_id, "charge": codec.decoder(ligne.charge)} for ligne in lignes]


def test_alerte_donnee_perimee_est_publiee_en_production(base_durable):
    par_nom = {o.nom: o for o in outils()}  # registre_cible=None => durable, comme en production

    executer_atomique(par_nom["m8_enregistrer_definition_metrique"], {"definition": _DEFINITION_M4})
    executer_atomique(
        par_nom["m8_rapport_metriques"],
        {
            "dictionnaire": {"m04-field-ops": {"m4_duree_reelle_minutes": {}}},
            "snapshot": {
                "module_source": "m04-field-ops",
                "horodatage": "2026-01-01T00:00:00Z",
                "valeurs": {"m4_duree_reelle_minutes": "42"},
            },
            "metric_ids": ["m4_duree_reelle_minutes"],
            "horodatage_reference": "2026-01-01T00:00:00Z",
            "n_minimal": 1,
        },
    )

    reponse = executer_atomique(
        par_nom["m8_evaluer_qualite_metrique"],
        # fraicheur_attendue_jours=2 ; écart réel de 10 jours (même scénario que
        # test_evaluer_qualite_metrique_donnee_perimee_propose_une_alerte, rejoué en durable).
        {"metric_id": "m4_duree_reelle_minutes", "horodatage_reference": "2026-01-11T00:00:00Z"},
    )

    # La réponse de l'outil ne change pas : une seule alerte proposée, jamais exécutée.
    assert reponse["ok"] is True
    alertes = reponse["resultat"]["alertes_proposees"]
    assert len(alertes) == 1 and alertes[0]["type_alerte"] == "REJ-QUALITE-DONNEE-PERIMEE"

    publies = _evenements_publies("m8.alerte_proposee")
    assert len(publies) == 1
    charge = publies[0]["charge"]
    assert charge["evenement_id"] == publies[0]["evenement_id"]
    assert charge["metric_id"] == "m4_duree_reelle_minutes"
    assert charge["type_alerte"] == "REJ-QUALITE-DONNEE-PERIMEE"
    assert charge["a_qui"] == "m04-field-ops"
    assert charge["horodatage_reference"] == "2026-01-11T00:00:00Z"
    assert charge["preuve"] == {
        "metric_id": "m4_duree_reelle_minutes", "fraicheur_jours": 10.0, "fraicheur_attendue_jours": 2,
    }


def test_reevaluation_identique_ne_republie_pas_un_second_evenement(base_durable):
    """Idempotence PRODUCTEUR : même métrique, même horodatage_reference (donc même verdict) —
    l'outbox garde un seul évenement_id (ADR-0009 §3, on_conflict_do_nothing)."""
    par_nom = {o.nom: o for o in outils()}
    executer_atomique(par_nom["m8_enregistrer_definition_metrique"], {"definition": _DEFINITION_M4})

    for _ in range(2):
        executer_atomique(
            par_nom["m8_evaluer_qualite_metrique"],
            {"metric_id": "m4_duree_reelle_minutes", "horodatage_reference": "2026-01-04T00:00:00Z"},
        )

    publies = _evenements_publies("m8.alerte_proposee")
    assert len(publies) == 1  # REJ-QUALITE-DONNEE-ABSENTE, republié deux fois sous le même id


def test_evaluer_qualite_metrique_sans_transaction_ne_publie_rien(base_durable):
    """Garde `connexion_courante` : un appel via `opsys.outils.executer` nu (comme
    `test_outils_agent.py` de ce département) ne touche jamais l'outbox, même avec une base
    durable montée à côté."""
    from opsys.outils import executer

    par_nom = {o.nom: o for o in outils()}
    executer_atomique(par_nom["m8_enregistrer_definition_metrique"], {"definition": _DEFINITION_M4})

    reponse = executer(
        par_nom["m8_evaluer_qualite_metrique"],
        {"metric_id": "m4_duree_reelle_minutes", "horodatage_reference": "2026-01-04T00:00:00Z"},
    )

    assert reponse["ok"] is True
    assert len(reponse["resultat"]["alertes_proposees"]) == 1  # l'évaluation elle-même fonctionne
    assert _evenements_publies("m8.alerte_proposee") == []  # mais rien n'est publié hors transaction
