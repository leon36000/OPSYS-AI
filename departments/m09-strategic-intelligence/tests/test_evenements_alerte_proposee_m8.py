"""Consommateur `m8.alerte_proposee` de M9 (ADR-0009 §3, PLAN T3.2) : bout en bout sur le bus
d'événements réel (`opsys.evenements.repartir`), les manifestes réels du dépôt
(`opsys.departements.charger_departements`, pas les départements de démonstration du socle) et
une base SQLite temporaire migrée — jamais une simulation en mémoire. Même patron que
`departments/m08-analytics/tests/test_evenements_travaux_termines.py` (M8 consommant M4) et
`test_contrat_snapshot_m8_m9.py` (contrat M8↔M9), transposé au nouvel événement.

Le dernier test (`test_briefing_matin_de_bout_en_bout_...`) est la PREUVE de la tranche verticale
complète du PLAN T3.2 : une décision en attente (file du propriétaire), une alerte M8 livrée par
le bus, et un fait consolidé par M9 apparaissent ENSEMBLE dans `m9_produire_briefing_matin`, tous
sourcés, rien d'inventé.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m8_analytics.outils import outils as m8_outils
from m9_strategic_intelligence.outils import outils as m9_outils

from opsys import approbations, evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import Niveau, executer_atomique

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
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


@pytest.fixture
def departements():
    """Manifestes réels de `departments/` (pas une fixture de démonstration) : preuve que
    `department.yaml:evenements.consomme` et `m9_strategic_intelligence.outils.consommateurs()`
    s'accordent pour de vrai, exactement comme `opsys-metier verifier` et `opsys-metier evenements repartir` en
    production. M8 (producteur) et M9 (consommateur) seulement : les autres consommateurs
    (aucun autre département ne consomme m8.alerte_proposee) ont leurs propres tests."""
    tous = charger_departements(_RACINE_DEPARTEMENTS)
    return {"m08-analytics": tous["m08-analytics"], "m09-strategic-intelligence": tous["m09-strategic-intelligence"]}


def _alertes_m9() -> list[dict]:
    return list(stockage.maillons("m09-strategic-intelligence", "alertes_m8"))


def _publier_alerte_perimee(horodatage_reference: str) -> None:
    """Produit une AlerteProposee réelle côté M8 (même scénario que
    `m08-analytics/tests/test_evenements_alerte_proposee.py`) : donnée périmée sur
    m4_duree_reelle_minutes, publiée sur le bus par le chemin de production."""
    par_nom_m8 = {o.nom: o for o in m8_outils()}
    executer_atomique(par_nom_m8["m8_enregistrer_definition_metrique"], {"definition": _DEFINITION_M4})
    executer_atomique(
        par_nom_m8["m8_rapport_metriques"],
        {
            "dictionnaire": {"m04-field-ops": {"m4_duree_reelle_minutes": {}}},
            "snapshot": {
                "module_source": "m04-field-ops", "horodatage": "2026-01-01T00:00:00Z",
                "valeurs": {"m4_duree_reelle_minutes": "42"},
            },
            "metric_ids": ["m4_duree_reelle_minutes"], "horodatage_reference": "2026-01-01T00:00:00Z",
            "n_minimal": 1,
        },
    )
    executer_atomique(
        par_nom_m8["m8_evaluer_qualite_metrique"],
        {"metric_id": "m4_duree_reelle_minutes", "horodatage_reference": horodatage_reference},
    )


# ---------------------------------------------------------------------------
# Nominal : l'alerte publiée par M8 arrive, idempotente, au registre durable des alertes M9
# ---------------------------------------------------------------------------
def test_nominal_alerte_m8_livree_au_registre_m9(base_durable, departements):
    _publier_alerte_perimee("2026-01-11T00:00:00Z")

    resume = evenements.repartir(departements, maintenant="2026-01-11T01:00:00+00:00")
    assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

    alertes = _alertes_m9()
    assert len(alertes) == 1
    alerte = alertes[0]
    assert alerte["metric_id"] == "m4_duree_reelle_minutes"
    assert alerte["type_alerte"] == "REJ-QUALITE-DONNEE-PERIMEE"
    assert alerte["a_qui"] == "m04-field-ops"
    assert alerte["horodatage_reference"] == "2026-01-11T00:00:00Z"
    assert alerte["preuve"]["fraicheur_jours"] == 10.0


def test_relivraison_sous_un_nouvel_evenement_id_est_idempotente(base_durable, departements):
    """Même patron que `test_evenements_travaux_termines.py` : une relivraison du même FAIT
    (même contenu d'alerte), publiée une seconde fois sous un evenement_id DIFFÉRENT (un
    evenement_id identique serait déjà un no-op de l'outbox lui-même), ne crée jamais un second
    maillon côté consommateur."""
    _publier_alerte_perimee("2026-02-11T00:00:00Z")
    evenements.repartir(departements, maintenant="2026-02-11T01:00:00+00:00")
    assert len(_alertes_m9()) == 1

    republiee = dict(_alertes_m9()[0])
    evenements.publier("m8.alerte_proposee", "m08-analytics", republiee, evenement_id="autre-id-relivraison")
    resume2 = evenements.repartir(departements, maintenant="2026-02-11T02:00:00+00:00")
    assert resume2["traites"] == 1

    assert len(_alertes_m9()) == 1  # jamais un second maillon pour la même alerte


def test_repartir_ne_rejoue_jamais_un_evenement_deja_traite(base_durable, departements):
    _publier_alerte_perimee("2026-03-11T00:00:00Z")
    evenements.repartir(departements, maintenant="2026-03-11T01:00:00+00:00")

    resume2 = evenements.repartir(departements, maintenant="2026-03-11T02:00:00+00:00")
    assert resume2 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(_alertes_m9()) == 1


# ---------------------------------------------------------------------------
# Tranche verticale complète (PLAN T3.2) : décision en attente + alerte M8 + fait de la veille,
# tous sourcés, dans un seul m9_produire_briefing_matin
# ---------------------------------------------------------------------------
def test_briefing_matin_de_bout_en_bout_decisions_alertes_et_faits_veille(base_durable, departements):
    maintenant = "2026-09-28T07:00:00-04:00"  # jour = 2026-09-28, veille = 2026-09-27

    # 1) Une décision en attente, réelle, dans la file du propriétaire du socle.
    with stockage.transaction() as cnx:
        demande_id = approbations.creer_demande(
            cnx, "m06-material-control", "m6_creer_bon_commande",
            {"fournisseur": "fictif"}, niveau=Niveau.N4, motif="reappro fictif",
        )

    # 2) Une alerte M8 pour LE JOUR du briefing, livrée par le bus (jamais lue directement).
    _publier_alerte_perimee("2026-09-28T10:00:00Z")
    resume = evenements.repartir(departements, maintenant="2026-09-28T10:05:00+00:00")
    assert resume["traites"] == 1

    # 3) Un fait consolidé par M9 pour LA VEILLE du briefing, ingéré via son propre outil T1.
    par_nom_m9 = {o.nom: o for o in m9_outils()}
    executer_atomique(
        par_nom_m9["m9_etat_consolide"],
        {"snapshot": {
            "module_source": "m04-field-ops", "horodatage": "2026-09-27T15:00:00Z",
            "valeurs": {"m4_wct_id": "wct-veille"},
        }},
    )

    # 4) Le briefing assemble les trois, chacun sourcé — rien d'inventé, rien omis.
    reponse = executer_atomique(par_nom_m9["m9_produire_briefing_matin"], {"maintenant": maintenant})
    assert reponse["ok"] is True
    briefing = reponse["resultat"]

    assert briefing["jour"] == "2026-09-28"
    assert briefing["veille"] == "2026-09-27"

    decisions = briefing["sections"]["decisions_en_attente"]
    assert decisions["vide"] is False
    assert decisions["items"][0]["id"] == demande_id
    assert decisions["items"][0]["departement"] == "m06-material-control"

    alertes = briefing["sections"]["alertes_m8"]
    assert alertes["vide"] is False
    assert alertes["items"][0]["metric_id"] == "m4_duree_reelle_minutes"
    assert alertes["items"][0]["horodatage_reference"] == "2026-09-28T10:00:00Z"

    faits = briefing["sections"]["faits_veille"]
    assert faits["vide"] is False
    assert faits["items"][0]["module_source"] == "m04-field-ops"
    assert faits["items"][0]["valeurs"] == {"m4_wct_id": "wct-veille"}

    assert briefing["sections"]["manques_pour_conclure"] == {"items": [], "vide": True}


def test_briefing_matin_sans_aucune_donnee_declare_les_trois_sections_vides(base_durable, departements):
    """Aucune décision, aucune alerte, aucun fait : le briefing reste honnête — sections vides,
    manques nommés — jamais une section remplie par défaut."""
    par_nom_m9 = {o.nom: o for o in m9_outils()}

    reponse = executer_atomique(
        par_nom_m9["m9_produire_briefing_matin"], {"maintenant": "2026-09-28T07:00:00-04:00"},
    )

    assert reponse["ok"] is True
    briefing = reponse["resultat"]
    for cle in ("decisions_en_attente", "alertes_m8", "faits_veille"):
        assert briefing["sections"][cle] == {"items": [], "vide": True}
    manques = briefing["sections"]["manques_pour_conclure"]
    assert manques["vide"] is False
    assert {m["section"] for m in manques["items"]} == {"decisions_en_attente", "alertes_m8", "faits_veille"}
