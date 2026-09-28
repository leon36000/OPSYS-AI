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
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS


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


def _amener_a(lead_id: str, statut_cible: str, **surcharges_contrat) -> None:
    """Amène un lead fictif jusqu'à `statut_cible`, par les outils composés de M2 (pas d'accès
    direct au registre) — mêmes étapes que test_outils_agent.py::TestMarquerChantierTermine.

    PLAN T2.2 : étendu au-delà de `chantier` (facture, paiement, avis) pour les scénarios de
    réouverture d'opportunité, toujours via les outils composés (`marquer_chantier_termine` puis
    `transitionner_statut`), jamais un accès direct au registre. `surcharges_contrat` permet de
    fixer un CONTACT précis (même client, plusieurs opportunités)."""
    outils.ingerer_lead(_contrat(lead_id, **surcharges_contrat), "2026-09-01T09:00:00-04:00")
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
    outils.marquer_chantier_termine(
        lead_id, "2026-09-01T09:25:00-04:00",
        prochaine_action={"description": "Facturer", "echeance": "2026-09-05T09:00:00-04:00"},
    )
    if statut_cible == "facture":
        return
    outils.transitionner_statut(lead_id, "paiement", "2026-09-01T09:30:00-04:00")
    if statut_cible == "paiement":
        return
    outils.transitionner_statut(lead_id, "avis", "2026-09-01T09:35:00-04:00")
    if statut_cible == "avis":
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


def _deps_bus():
    """Seuls M2 et M10 reçoivent les événements de ces tests : les comptes de `repartir()` sont
    globaux, et chaque nouveau consommateur de `m4.travaux_termines` (M6, M7, M8…) ou de ce qu'il
    publie en retour (`m6.variance_chantier` vers M4) les changerait. M10 reste inclus parce que
    la relivraison vérifie aussi qu'aucun maillon M10 ne s'ajoute."""
    tous = charger_departements()
    return {nom: tous[nom] for nom in ("m02-revenue-crm", "m10-memoire")}


class TestManifeste:
    def test_m2_declare_consommer_travaux_termines(self):
        dep = charger_departements()["m02-revenue-crm"]
        assert dep.evenements_consomme == ("m4.travaux_termines",)
        assert "m4.travaux_termines" in dep.charger_consommateurs()

    def test_m2_declare_publier_client_associe(self):
        """PLAN T2.2 (Client 360)."""
        dep = charger_departements()["m02-revenue-crm"]
        assert dep.evenements_publie == ("m2.client_associe",)


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

        resume = evenements.repartir(_deps_bus(), maintenant="2026-09-15T14:05:00-04:00")
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
        deps = _deps_bus()
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

        deps = _deps_bus()
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
    def test_meme_wct_sous_un_nouvel_evenement_id_est_un_no_op(self, base_durable):
        """Un même fait republié sous un autre evenement_id (rejeu du producteur) ne met jamais
        M2 en quarantaine : la complétion est déjà appliquée, rien ne s'écrit une seconde fois."""
        lead_id = "WCT-REDELIVRE-2"
        _amener_a(lead_id, "converti")
        charge = _wct(lead_id, "2026-09-15T14:00:00-04:00", client_satisfait=True)
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-rejeu-1")
        deps = _deps_bus()
        evenements.repartir(deps, maintenant="2026-09-15T14:05:00-04:00")
        assert statuts.statut_courant(_registre(), lead_id) == "facture"
        taille_apres_1 = _registre().taille()

        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-rejeu-2")
        resume = evenements.repartir(deps, maintenant="2026-09-15T14:10:00-04:00")
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        with stockage.transaction() as cnx:
            statut_recu = cnx.execute(select(EVENEMENTS_RECUS.c.statut).where(
                EVENEMENTS_RECUS.c.evenement_id == "evt-rejeu-2",
                EVENEMENTS_RECUS.c.consommateur == "m02-revenue-crm",
            )).scalar_one()
        assert statut_recu == "traite"
        assert _registre().taille() == taille_apres_1, "aucun maillon M2 de plus"
        assert statuts.statut_courant(_registre(), lead_id) == "facture"

    def test_relivraison_naffecte_rien(self, base_durable):
        lead_id = "WCT-REDELIVRE-1"
        _amener_a(lead_id, "converti")
        charge = _wct(lead_id, "2026-09-15T14:00:00-04:00", client_satisfait=True)
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-redelivre-1")

        deps = _deps_bus()
        resume1 = evenements.repartir(deps, maintenant="2026-09-15T14:05:00-04:00")
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


class TestEvenementClientAssocie:
    """PLAN T2.2 (Client 360) : m2_ingerer_lead publie `m2.client_associe` dans la même
    transaction que l'ingestion, en mode durable seulement (voir outils._publier_si_durable)."""

    def test_ingerer_lead_publie_client_associe(self, base_durable):
        reponse = outils.ingerer_lead(_contrat("EVT1"), "2026-09-01T09:00:00-04:00")
        assert reponse["accepte"] is True
        assert evenements.deja_publie("m2-client-associe-EVT1")

    def test_charge_publiee_porte_lead_id_client_id_horodatage(self, base_durable):
        reponse = outils.ingerer_lead(_contrat("EVT2"), "2026-09-01T09:00:00-04:00")
        with stockage.transaction() as cnx:
            ligne = cnx.execute(
                select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == "m2-client-associe-EVT2")
            ).mappings().one()
        charge = codec.decoder(ligne["charge"])
        assert charge == {
            "lead_id": "EVT2",
            "client_id": reponse["client_id"],
            "horodatage_association": "2026-09-01T09:00:00-04:00",
        }
        assert ligne["type_evenement"] == "m2.client_associe"
        assert ligne["producteur"] == "m02-revenue-crm"

    def test_redelivrance_du_meme_lead_est_un_no_op(self, base_durable):
        """evenement_id déterministe (f"m2-client-associe-{lead_id}") : REJ-LEAD-DEJA-INGERE
        empêche de toute façon un second appel pour le même lead_id, mais l'idempotence de
        l'événement lui-même reste prouvée en appelant `evenements.publier` une seconde fois
        avec le même evenement_id et la même charge."""
        reponse = outils.ingerer_lead(_contrat("EVT3"), "2026-09-01T09:00:00-04:00")
        with stockage.transaction() as cnx:
            avant = cnx.execute(
                select(EVENEMENTS_SORTANTS.c.evenement_id)
            ).scalars().all()
        charge = {
            "lead_id": "EVT3",
            "client_id": reponse["client_id"],
            "horodatage_association": "2026-09-01T09:00:00-04:00",
        }
        evenements.publier("m2.client_associe", "m02-revenue-crm", charge, evenement_id="m2-client-associe-EVT3")
        with stockage.transaction() as cnx:
            apres = cnx.execute(
                select(EVENEMENTS_SORTANTS.c.evenement_id)
            ).scalars().all()
        assert sorted(apres) == sorted(avant), "aucun second événement créé"


class TestReattachementOpportunite:
    """PLAN T2.2 (relevé T1.2-e) : un WCT pour un lead déjà à facture/paiement/avis, dont le
    CLIENT (même contact — clients.py) porte une AUTRE opportunité actuellement en cours, se
    rattache à CELLE-CI plutôt que d'échouer."""

    def test_rattache_a_l_unique_opportunite_en_cours_du_meme_client(self, base_durable):
        contact = {"nom": "Client Répété", "telephone": "418-555-9999", "courriel": "repete@example.test"}
        lead_termine = "REP-A"
        lead_en_cours = "REP-B"
        _amener_a(lead_termine, "facture", contact=dict(contact))
        _amener_a(lead_en_cours, "chantier", contact=dict(contact))
        # REP-A porte déjà UNE interaction système, écrite par SA PROPRE complétion (_amener_a
        # l'a amené à facture via marquer_chantier_termine) — avant même que ce WCT n'existe.
        interactions_origine_avant = [
            m for m in _registre().lire()
            if m["type_entree"] == "interaction" and m["lead_id"] == lead_termine
        ]
        assert len(interactions_origine_avant) == 1

        charge = _wct(lead_termine, "2026-09-20T14:00:00-04:00", client_satisfait=True)
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
        resume = evenements.repartir(_deps_bus(), maintenant="2026-09-20T14:05:00-04:00")
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

        # Le lead D'ORIGINE du WCT (déjà à facture) reste INCHANGÉ.
        assert statuts.statut_courant(_registre(), lead_termine) == "facture"
        # L'AUTRE opportunité du même client a reçu la transition.
        assert statuts.statut_courant(_registre(), lead_en_cours) == "facture"

        interactions_cible = [
            m for m in _registre().lire()
            if m["type_entree"] == "interaction" and m["lead_id"] == lead_en_cours
        ]
        assert len(interactions_cible) == 1
        assert interactions_cible[0]["auteur"] == "system:m4"

        interactions_origine_apres = [
            m for m in _registre().lire()
            if m["type_entree"] == "interaction" and m["lead_id"] == lead_termine
        ]
        assert interactions_origine_apres == interactions_origine_avant, (
            "aucune NOUVELLE écriture sur le lead d'origine : ce WCT ne lui appartient plus"
        )


class TestNouvelleOpportuniteAuLieuDeQuarantaine:
    """PLAN T2.2 (relevé T1.2-e) : « un second chantier pour un lead déjà à facture part en
    quarantaine chez M2 (le cycle de vie est par lead, pas par chantier) ». Un WCT pour un lead
    déjà à facture/paiement/avis, dont le client N'A AUCUNE autre opportunité en cours, ouvre une
    NOUVELLE opportunité pour ce même client au lieu de partir en quarantaine."""

    @pytest.mark.parametrize("statut_depart", ["facture", "paiement", "avis"])
    def test_ouvre_une_nouvelle_opportunite_sans_quarantaine(self, base_durable, statut_depart):
        contact = {"nom": "Client Seul", "telephone": "418-555-1234", "courriel": "seul@example.test"}
        lead_id = f"SOLO-{statut_depart}"
        _amener_a(lead_id, statut_depart, contact=dict(contact))
        client_id = outils.trouver_client_de_lead(lead_id)["resultat"]["client_id"]

        wct_id = f"wct-second-{lead_id}"
        charge = _wct(lead_id, "2026-09-20T14:00:00-04:00", wct_id=wct_id)
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
        resume = evenements.repartir(_deps_bus(), maintenant="2026-09-20T14:05:00-04:00")
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

        # Le lead d'origine reste inchangé : ce n'est PAS lui qui reçoit la transition.
        assert statuts.statut_courant(_registre(), lead_id) == statut_depart

        nouvelle_opportunite = f"{lead_id}~opp~{wct_id}"
        assert statuts.statut_courant(_registre(), nouvelle_opportunite) == "nouveau"
        assert outils.trouver_client_de_lead(nouvelle_opportunite)["resultat"]["client_id"] == client_id

        interactions_nouvelle = [
            m for m in _registre().lire()
            if m["type_entree"] == "interaction" and m["lead_id"] == nouvelle_opportunite
        ]
        assert len(interactions_nouvelle) == 1
        assert interactions_nouvelle[0]["auteur"] == "system:m4"
        assert wct_id in interactions_nouvelle[0]["resume"]

        # Aucun signalement de doublon n'a été créé contre le lead d'origine (M2.14, pas un
        # doublon accidentel).
        signalements = [m for m in _registre().lire() if m["type_entree"] == "doublon_signale"]
        assert signalements == []

        lignes_quarantaine = [
            ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == "m02-revenue-crm"
        ]
        assert lignes_quarantaine == [], "au lieu d'une quarantaine (relevé T1.2-e)"

    def test_redelivrance_du_meme_wct_apres_ouverture_est_un_no_op(self, base_durable):
        """Un même WCT republié sous un autre evenement_id (rejeu du producteur) ne rouvre pas
        une SECONDE opportunité : reconnu par son wct_id (même patron que le chemin nominal)."""
        contact = {"nom": "Client Seul Bis", "telephone": "418-555-4321"}
        lead_id = "SOLO-REJEU"
        _amener_a(lead_id, "facture", contact=dict(contact))
        wct_id = "wct-solo-rejeu"
        charge = _wct(lead_id, "2026-09-20T14:00:00-04:00", wct_id=wct_id)
        deps = _deps_bus()

        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-solo-1")
        evenements.repartir(deps, maintenant="2026-09-20T14:05:00-04:00")
        taille_apres_1 = _registre().taille()

        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-solo-2")
        resume = evenements.repartir(deps, maintenant="2026-09-20T14:10:00-04:00")
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        assert _registre().taille() == taille_apres_1, "aucun maillon de plus, aucune seconde opportunité"


class TestOpportuniteAmbigue:
    """PLAN T2.2 : le client porte PLUSIEURS opportunités en cours — impossible de déterminer
    laquelle rattacher sans décision humaine (jamais un choix arbitraire)."""

    def test_plusieurs_opportunites_en_cours_va_en_quarantaine_avec_verdict_nomme(self, base_durable):
        contact = {"nom": "Client Multiple", "telephone": "418-555-5678", "courriel": "multiple@example.test"}
        lead_termine = "AMB-A"
        lead_b = "AMB-B"
        lead_c = "AMB-C"
        _amener_a(lead_termine, "facture", contact=dict(contact))
        _amener_a(lead_b, "converti", contact=dict(contact))
        _amener_a(lead_c, "chantier", contact=dict(contact))
        taille_avant = _registre().taille()

        charge = _wct(lead_termine, "2026-09-20T14:00:00-04:00")
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

        deps = _deps_bus()
        t = dt.datetime(2026, 9, 20, 14, 5, tzinfo=dt.UTC)
        resume = None
        for _ in range(5):
            resume = evenements.repartir(deps, maintenant=t.isoformat())
            t += dt.timedelta(seconds=100)

        assert resume["quarantaines"] == 1, resume
        assert _registre().taille() == taille_avant, "aucune écriture, y compris partielle"
        # Aucun des trois leads n'a bougé.
        assert statuts.statut_courant(_registre(), lead_termine) == "facture"
        assert statuts.statut_courant(_registre(), lead_b) == "converti"
        assert statuts.statut_courant(_registre(), lead_c) == "chantier"

        lignes = [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == "m02-revenue-crm"]
        assert len(lignes) == 1
        assert "OpportuniteAmbigue" in lignes[0]["derniere_erreur"]
