"""M2 consomme `m4.travaux_termines` (ADR-0009 §3, PLAN T1.2-c partie 1) : le lead avance de
façon déterministe jusqu'à `chantier` puis `marquer_chantier_termine` l'amène à `facture`, la
prochaine action suit une table de règles documentée, une incohérence de données (lead introuvable
ou statut incompatible) est mise en quarantaine sans écriture, une relivraison n'a aucun effet.

Utilise le VRAI bus (`evenements.repartir` + `opsys.departements.charger_departements()`, sur les
manifestes réels de `departments/` — pas une racine de démonstration : c'est le seul moyen de
prouver que `department.yaml` de M2 déclare bien `evenements.consomme` et que `consommateurs()`
s'y raccorde), sur une base SQLite temporaire migrée (patron de
`test_registre_durable.py::base_durable`). Les WCT publiés sont des événements de test fictifs
(clients, techniciens et identifiants de test — DEFINITION-PRODUIT §1, jamais des données réelles).
"""

from __future__ import annotations

import datetime as dt

import pytest
from m2_revenue_crm import outils, statuts
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_RECUS


def _contrat(lead_id: str, **surcharges) -> dict:
    base = {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    base.update(surcharges)
    return base


def _wct(lead_id: str, horodatage_completion: str, **overrides) -> dict:
    base = {
        "wct_id": f"wct-{lead_id}",
        "intervention_id": f"int-{lead_id}",
        "lead_id": lead_id,
        "technicien_id": "tech-fictif-1",
        "horodatage_completion": horodatage_completion,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": f"hash-{lead_id}",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
        "devis_id": f"devis-{lead_id}",
        "statut": "completed_verified",
    }
    base.update(overrides)
    return base


def _amener_a(lead_id: str, statut_cible: str) -> None:
    """Amène un lead fictif jusqu'à `statut_cible`, par les outils composés de M2 (pas d'accès
    direct au registre) — mêmes étapes que test_outils_agent.py::TestMarquerChantierTermine."""
    outils.ingerer_lead(_contrat(lead_id), "2026-09-01T09:00:00-04:00")
    if statut_cible == "nouveau":
        return
    outils.transitionner_statut(
        lead_id, "qualifie", "2026-09-01T09:05:00-04:00",
        owner="Alice", prochaine_action={"description": "Appeler", "echeance": "2026-09-05T09:00:00-04:00"},
    )
    if statut_cible == "qualifie":
        return
    outils.transitionner_statut(
        lead_id, "converti", "2026-09-01T09:10:00-04:00", reference_devis_m3="DEVIS-FICTIF-1"
    )
    if statut_cible == "converti":
        return
    outils.transitionner_statut(lead_id, "cedule", "2026-09-01T09:15:00-04:00")
    if statut_cible == "cedule":
        return
    outils.transitionner_statut(lead_id, "chantier", "2026-09-01T09:20:00-04:00")
    if statut_cible == "chantier":
        return
    raise ValueError(f"statut_cible {statut_cible!r} non géré par ce helper de test")


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée (patron de test_registre_durable.py::base_durable), avec le
    registre de M2 branché sur le stockage DURABLE (jamais la mémoire des autres suites)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()


def _registre():
    return outils._obtenir_registre()


class TestManifeste:
    def test_m2_declare_consommer_travaux_termines(self):
        dep = charger_departements()["m02-revenue-crm"]
        assert dep.evenements_consomme == ("m4.travaux_termines",)
        assert "m4.travaux_termines" in dep.charger_consommateurs()


class TestNominal:
    """DEFINITION-PRODUIT §6, cascade « travaux terminés », ligne M2. La table de règles pour la
    prochaine action (_regle_prochaine_action, outils.py) est exercée sur ses trois branches :
    client insatisfait (M2.11 complaint_risk), client satisfait (M2.7 + M2.11 referral_candidate),
    signal non recueilli (M2.11 invoice_pending, repli par défaut)."""

    @pytest.mark.parametrize(
        ("statut_depart", "client_satisfait", "mot_attendu"),
        [
            ("converti", True, "avis et référence"),
            ("cedule", False, "risque de plainte"),
            ("chantier", None, "suivi de la facture"),
        ],
        ids=["converti-satisfait", "cedule-insatisfait", "chantier-signal-absent"],
    )
    def test_lead_avance_jusqua_facture_et_prochaine_action_suit_la_regle(
        self, base_durable, statut_depart, client_satisfait, mot_attendu
    ):
        lead_id = f"WCT-NOM-{statut_depart}"
        _amener_a(lead_id, statut_depart)
        assert statuts.statut_courant(_registre(), lead_id) == statut_depart

        horodatage_completion = "2026-09-15T14:00:00-04:00"
        charge = _wct(lead_id, horodatage_completion)
        if client_satisfait is not None:
            charge["client_satisfait"] = client_satisfait
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

        resume = evenements.repartir(charger_departements(), maintenant="2026-09-15T14:05:00-04:00")
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

        assert statuts.statut_courant(_registre(), lead_id) == "facture"

        interactions = [
            m for m in _registre().lire() if m["type_entree"] == "interaction" and m["lead_id"] == lead_id
        ]
        assert len(interactions) == 1, "l'interaction système (DEFINITION-PRODUIT §6 ligne M2) est écrite"
        assert interactions[0]["auteur"] == "system:m4"
        assert mot_attendu in interactions[0]["resume"]

        transitions_facture = [
            m for m in _registre().lire()
            if m["type_entree"] == "transition_statut" and m["lead_id"] == lead_id and m["statut"] == "facture"
        ]
        assert len(transitions_facture) == 1
        prochaine_action = transitions_facture[0]["prochaine_action"]
        assert prochaine_action["echeance"] == horodatage_completion, (
            "l'échéance est l'horodatage RÉEL du WCT, jamais une date inventée"
        )
        assert mot_attendu in prochaine_action["description"]


class TestLeadIntrouvable:
    def test_lead_inconnu_va_en_quarantaine_apres_reessais_sans_ecriture(self, base_durable):
        lead_id = "LEAD-INCONNU-FICTIF"
        charge = _wct(lead_id, "2026-09-15T14:00:00-04:00")
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

        taille_avant = _registre().taille()
        deps = charger_departements()
        t = dt.datetime(2026, 9, 15, 14, 5, tzinfo=dt.UTC)
        resume = None
        for _ in range(5):
            resume = evenements.repartir(deps, maintenant=t.isoformat())
            t += dt.timedelta(seconds=100)

        assert resume["quarantaines"] == 1, resume
        assert _registre().taille() == taille_avant, "un lead introuvable n'écrit rien"
        assert statuts.statut_courant(_registre(), lead_id) is None

        lignes = [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == "m02-revenue-crm"]
        assert len(lignes) == 1
        assert lignes[0]["tentatives"] == 5
        assert "LeadIntrouvable" in lignes[0]["derniere_erreur"]


class TestStatutIncompatible:
    """Un statut commercial antérieur à la conversion (nouveau, qualifie) est, comme un lead
    introuvable, une incohérence de données (PLAN T1.2-c) : même traitement (quarantaine, aucune
    écriture), erreur nommée distincte (StatutIncompatibleAvecCompletion)."""

    @pytest.mark.parametrize("statut_depart", ["nouveau", "qualifie"])
    def test_statut_anterieur_a_la_conversion_va_en_quarantaine_sans_ecriture(self, base_durable, statut_depart):
        lead_id = f"LEAD-AVANT-CONVERSION-{statut_depart}"
        _amener_a(lead_id, statut_depart)
        taille_avant = _registre().taille()

        charge = _wct(lead_id, "2026-09-15T14:00:00-04:00")
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

        deps = charger_departements()
        t = dt.datetime(2026, 9, 15, 14, 5, tzinfo=dt.UTC)
        resume = None
        for _ in range(5):
            resume = evenements.repartir(deps, maintenant=t.isoformat())
            t += dt.timedelta(seconds=100)

        assert resume["quarantaines"] == 1, resume
        assert _registre().taille() == taille_avant, "un statut incompatible n'écrit rien"
        assert statuts.statut_courant(_registre(), lead_id) == statut_depart, "le lead n'a pas bougé"

        lignes = [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == "m02-revenue-crm"]
        assert len(lignes) == 1
        assert "StatutIncompatibleAvecCompletion" in lignes[0]["derniere_erreur"]


class TestRedelivraison:
    def test_relivraison_naffecte_rien(self, base_durable):
        lead_id = "WCT-REDELIVRE-1"
        _amener_a(lead_id, "converti")
        charge = _wct(lead_id, "2026-09-15T14:00:00-04:00", client_satisfait=True)
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-redelivre-1")

        deps = charger_departements()
        resume1 = evenements.repartir(deps, maintenant="2026-09-15T14:05:00-04:00")
        # Le nombre total de consommateurs dépend des autres départements : on vérifie seulement
        # qu'aucun n'a échoué et que le reçu de M2 est traité.
        assert resume1["echecs"] == 0 and resume1["quarantaines"] == 0, resume1
        with stockage.transaction() as cnx:
            statut_recu = cnx.execute(select(EVENEMENTS_RECUS.c.statut).where(
                EVENEMENTS_RECUS.c.evenement_id == "evt-redelivre-1",
                EVENEMENTS_RECUS.c.consommateur == "m02-revenue-crm",
            )).scalar_one()
        assert statut_recu == "traite"

        statut_apres_1 = statuts.statut_courant(_registre(), lead_id)
        assert statut_apres_1 == "facture"
        taille_m2_apres_1 = _registre().taille()
        taille_m10_apres_1 = len(stockage.maillons("m10-memoire", "evenements"))

        resume2 = evenements.repartir(deps, maintenant="2026-09-15T15:00:00-04:00")
        assert resume2 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}

        assert statuts.statut_courant(_registre(), lead_id) == statut_apres_1
        assert _registre().taille() == taille_m2_apres_1, "aucun maillon M2 supplémentaire"
        assert len(stockage.maillons("m10-memoire", "evenements")) == taille_m10_apres_1, (
            "aucun maillon M10 supplémentaire"
        )
