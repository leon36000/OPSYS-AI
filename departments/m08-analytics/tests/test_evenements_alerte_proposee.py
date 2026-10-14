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

import pytest
from m8_analytics import outils as m8_outils
from m8_analytics.outils import outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.outils import Outil, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

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


def test_alerte_donnee_non_finie_est_distincte_et_publiee(base_durable):
    par_nom = {o.nom: o for o in outils()}
    executer_atomique(par_nom["m8_enregistrer_definition_metrique"], {"definition": _DEFINITION_M4})
    rapport = executer_atomique(
        par_nom["m8_rapport_metriques"],
        {
            "dictionnaire": {"m04-field-ops": {"m4_duree_reelle_minutes": {}}},
            "snapshot": {
                "module_source": "m04-field-ops", "horodatage": "2026-01-04T00:00:00Z",
                "valeurs": {"m4_duree_reelle_minutes": "nan"},
            },
            "metric_ids": ["m4_duree_reelle_minutes"],
            "horodatage_reference": "2026-01-04T00:00:00Z", "n_minimal": 1,
        },
    )
    assert rapport["resultat"]["accepte"] is False
    assert "rapport" not in rapport["resultat"]
    resultat = executer_atomique(
        par_nom["m8_evaluer_qualite_metrique"],
        {"metric_id": "m4_duree_reelle_minutes", "horodatage_reference": "2026-01-04T00:00:00Z"},
    )
    alerte = resultat["resultat"]["alertes_proposees"][0]
    assert resultat["resultat"]["n"] == 0 and resultat["resultat"]["valeur"] is None
    assert alerte["type_alerte"] == "REJ-QUALITE-DONNEE-INVALIDE"
    assert alerte["preuve"] == {"metric_id": "m4_duree_reelle_minutes", "n": 0, "valeurs_invalides": 1}
    publies = _evenements_publies("m8.alerte_proposee")
    assert len(publies) == 1
    assert publies[0]["charge"]["type_alerte"] == "REJ-QUALITE-DONNEE-INVALIDE"
    assert publies[0]["charge"]["preuve"] == alerte["preuve"]


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


def _alerte_fictive():
    return {
        "type_alerte": "REJ-QUALITE-DONNEE-ABSENTE", "quoi": "Observation fictive",
        "a_qui": "m04-field-ops", "pourquoi": "Aucune mesure", "source": "fixture",
        "preuve": {"metric_id": "fictif", "n": 0},
    }


@pytest.mark.parametrize("site", ["mesure", "qualite"])
@pytest.mark.parametrize("collision", ["type", "producteur"])
def test_rejeu_m8_refuse_autre_enveloppe_et_annule_metier(base_durable, site, collision):
    alerte = _alerte_fictive()
    reference = "2026-01-04T00:00:00Z"
    ident = f"m8-alerte-fictif-{alerte['type_alerte']}-{reference}"
    charge = dict(alerte, evenement_id=ident, metric_id="fictif", horodatage_reference=reference)
    if collision == "type":
        evenements.publier("opsys.demo_complete", "m08-analytics", {"message": "fictif"}, evenement_id=ident)
    else:
        evenements.publier("m8.alerte_proposee", "autre-producteur-fictif", charge, evenement_id=ident)
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS)).one()

    def publier():
        stockage.maillons("m08-analytics", "fictif-collision").append({"test": True})
        if site == "mesure":
            return m8_outils._publier_charges_mesure([charge])
        m8_outils._publier_alerte_proposee("fictif", alerte, reference)
        return {}

    outil = Outil("m8_test_collision", "Publication fictive", {"type": "object"}, publier)
    reponse = executer_atomique(outil, {})
    stockage.liberer()
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert len(stockage.maillons("m08-analytics", "fictif-collision")) == 0
    with stockage.transaction() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS)).one() == avant


def test_rejeu_qualite_conserve_premiere_preuve_meme_si_evaluation_change(base_durable):
    alerte = _alerte_fictive()
    reference = "2026-01-04T00:00:00Z"
    with stockage.transaction():
        m8_outils._publier_alerte_proposee("fictif", alerte, reference)
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS)).one()
    alerte["preuve"] = {"metric_id": "fictif", "n": 1}
    alerte["pourquoi"] = "Nouvelle évaluation fictive"
    with stockage.transaction():
        m8_outils._publier_alerte_proposee("fictif", alerte, reference)
    stockage.liberer()
    with stockage.transaction() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS)).one() == avant


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


def test_alerte_doublon_nest_jamais_publiee_sur_le_bus_catalogue_non_etendu(base_durable):
    """T3.1-suite : REJ-QUALITE-DOUBLON et REJ-QUALITE-INCOHERENCE ne figurent pas dans l'énuméré
    `type_alerte` du catalogue (src/opsys/evenements/catalogue/m8.alerte_proposee.json),
    volontairement non étendu par ce lot (catalogue d'événements touché seulement si nécessaire —
    ce ne l'était pas ici). Publier l'une de ces deux alertes ferait échouer la validation JSON
    Schema du bus ; `outils.py::_publier_alerte_proposee` filtre donc explicitement par
    `_TYPES_ALERTE_SUR_BUS`. L'alerte reste néanmoins dans la réponse de l'outil (et peut nourrir
    le digest quotidien), jamais perdue — seule sa publication sur le bus est omise."""
    par_nom = {o.nom: o for o in outils()}
    executer_atomique(par_nom["m8_enregistrer_definition_metrique"], {"definition": _DEFINITION_M4})
    for valeur in ("42", "43"):  # même horodatage : doublon d'observation
        executer_atomique(
            par_nom["m8_rapport_metriques"],
            {
                "dictionnaire": {"m04-field-ops": {"m4_duree_reelle_minutes": {}}},
                "snapshot": {
                    "module_source": "m04-field-ops",
                    "horodatage": "2026-01-01T00:00:00Z",
                    "valeurs": {"m4_duree_reelle_minutes": valeur},
                },
                "metric_ids": ["m4_duree_reelle_minutes"],
                "horodatage_reference": "2026-01-01T00:00:00Z",
                "n_minimal": 1,
            },
        )

    reponse = executer_atomique(
        par_nom["m8_evaluer_qualite_metrique"],
        # +12h < fraicheur_attendue_jours=2 : fraîche, donc seul le doublon est en jeu ici.
        {"metric_id": "m4_duree_reelle_minutes", "horodatage_reference": "2026-01-01T12:00:00Z"},
    )

    assert reponse["ok"] is True
    alertes = reponse["resultat"]["alertes_proposees"]
    assert len(alertes) == 1 and alertes[0]["type_alerte"] == "REJ-QUALITE-DOUBLON"

    assert _evenements_publies("m8.alerte_proposee") == []
