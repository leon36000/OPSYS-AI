"""Capacités d'agent de M2 : contrat des outils et pipeline d'ingestion composé.

Couvre aussi les trois défauts d'audit corrigés dans ce département :
- interactions.py utilisait la taille du registre comme ligne_id au lieu de
  l'identifiant réel retourné par registre.ajouter ;
- digest.py acceptait date_jour sans jamais filtrer les entrées ;
- ingestion.py n'appelait jamais la détection de doublons (PRD §2b).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m2_revenue_crm.outils import (
    _obtenir_registre,
    arbitrer_doublon,
    detecter_doublons,
    enregistrer_interaction,
    evaluer_readiness,
    ingerer_lead,
    outils,
    produire_digest,
    reinitialiser_registre,
    signaler_doublon,
    transitionner_statut,
)

from opsys.departements import lire_manifeste
from opsys.outils import executer


def _contrat(lead_id: str, **surcharges) -> dict:
    base = {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Test", "telephone": "418-555-0000", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    base.update(surcharges)
    return base


@pytest.fixture(autouse=True)
def _registre_propre():
    """Chaque test démarre avec le registre départemental (état partagé) vide."""
    reinitialiser_registre()
    yield
    reinitialiser_registre()


# ---------------------------------------------------------------------------
# Manifeste
# ---------------------------------------------------------------------------
def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m2_ingerer_lead"
    assert all(nom.startswith("m2_") for nom in noms)
    assert len(noms) == len(set(noms)), "noms d'outils en double"
    assert dep.dependances == ("m01-front-office",)
    assert dep.mode == "ombre"


# ---------------------------------------------------------------------------
# m2_ingerer_lead — cas nominal
# ---------------------------------------------------------------------------
class TestIngererLeadNominal:
    def test_lead_neuf_sans_doublon(self):
        reponse = ingerer_lead(_contrat("L1"), "2026-06-15T10:00:00+00:00")
        assert reponse["accepte"] is True
        assert reponse["statut"] == "nouveau"
        assert reponse["pret_pour_m3"] is False, "aucun owner ni interaction encore : pas prêt"
        assert reponse["doublons_signales"] == []
        assert reponse["accuse_ingestion"]["doublons_detectes"] == []

    def test_doublon_probable_detecte_et_signale(self):
        """Correctif d'audit PRD §2b : un doublon probable est signalé à l'ingestion."""
        contact = {"nom": "Marie Roy", "telephone": "581-555-1111", "courriel": "marie@example.test"}
        ingerer_lead(_contrat("D1", contact=contact), "2026-06-15T08:00:00+00:00")
        reponse = ingerer_lead(_contrat("D2", contact=contact), "2026-06-17T08:00:00+00:00")
        assert reponse["accepte"] is True
        assert reponse["accuse_ingestion"]["doublons_detectes"] == ["D1"]
        assert len(reponse["doublons_signales"]) == 1
        signalement = reponse["doublons_signales"][0]
        assert signalement["critere"] == "contact_identique"
        assert sorted([signalement["lead_id_a"], signalement["lead_id_b"]]) == ["D1", "D2"]

        # Le signalement est bien inscrit au registre, visible par detecter_doublons/digest.
        d = produire_digest("2026-06-17", "2026-06-17T12:00:00+00:00")
        assert signalement["signalement_id"] in d


# ---------------------------------------------------------------------------
# m2_ingerer_lead — refus
# ---------------------------------------------------------------------------
class TestIngererLeadRefus:
    def test_frontiere_violee_refusee(self):
        reponse = ingerer_lead(_contrat("F1", ville="Québec, devis 4500 $"), "2026-06-15T10:00:00+00:00")
        assert reponse["accepte"] is False
        assert reponse["etape"] == "ingestion"
        assert reponse["verdict"]["code"] == "REJ-FRONTIERE-VIOLEE"

    def test_lead_deja_ingere_refuse(self):
        ingerer_lead(_contrat("U1"), "2026-06-15T10:00:00+00:00")
        reponse = ingerer_lead(_contrat("U1"), "2026-06-15T11:00:00+00:00")
        assert reponse["accepte"] is False
        assert reponse["verdict"]["code"] == "REJ-LEAD-DEJA-INGERE"

    def test_horodatage_manquant_est_un_argument_invalide(self):
        outil = next(o for o in outils() if o.nom == "m2_ingerer_lead")
        reponse = executer(outil, {"contrat": _contrat("H1")})
        assert reponse["erreur"] == "arguments_invalides"

    def test_champ_hors_contrat_refuse_par_la_liste_blanche(self):
        """Le schéma JSON de l'outil ne valide pas récursivement l'intérieur de
        'contrat' (c'est le rôle de contrats.valider_structure, appelé par
        ingestion.ingerer) : un champ en trop y est rejeté par la liste blanche
        stricte du métier, pas par la couche schéma."""
        outil = next(o for o in outils() if o.nom == "m2_ingerer_lead")
        contrat = _contrat("S1")
        contrat["prix_estime"] = 1000
        reponse = executer(outil, {"contrat": contrat, "horodatage": "2026-06-15T10:00:00+00:00"})
        assert reponse["ok"] is True
        assert reponse["resultat"]["accepte"] is False
        assert reponse["resultat"]["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"

    def test_statut_cible_hors_enum_refuse_par_le_schema(self):
        """Preuve symétrique du cas ci-dessus : statut_cible EST un paramètre de
        premier niveau (pas niché dans un sous-objet), donc son enum est bien
        appliqué par la couche schéma (arguments_invalides), sans même exécuter
        la fonction métier."""
        outil = next(o for o in outils() if o.nom == "m2_transitionner_statut")
        reponse = executer(outil, {
            "lead_id": "TE1", "statut_cible": "archive", "horodatage": "2026-06-15T10:00:00+00:00",
        })
        assert reponse["erreur"] == "arguments_invalides"


# ---------------------------------------------------------------------------
# Cycle de vie complet : nouveau → qualifie → interaction → readiness → converti
# ---------------------------------------------------------------------------
class TestCycleDeVieComplet:
    def test_progression_jusqu_a_pret_pour_m3_puis_converti(self):
        ingerer_lead(_contrat("C1"), "2026-06-15T09:00:00+00:00")

        refus_sans_owner = transitionner_statut("C1", "qualifie", "2026-06-15T09:30:00+00:00")
        assert refus_sans_owner["accepte"] is False
        assert refus_sans_owner["verdict"]["code"] == "REJ-OWNER-ABSENT"

        qualif = transitionner_statut(
            "C1", "qualifie", "2026-06-15T09:30:00+00:00",
            owner="Alice",
            prochaine_action={"description": "Appeler le client", "echeance": "2026-06-20T09:00:00+00:00"},
        )
        assert qualif["accepte"] is True

        pas_encore_pret = evaluer_readiness("C1", "2026-06-15T09:31:00+00:00")
        assert pas_encore_pret["accepte"] is False
        assert pas_encore_pret["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"
        assert "interaction" in pas_encore_pret["verdict"]["detail"]

        interaction = enregistrer_interaction("C1", "Alice", "Appel de suivi effectué", "2026-06-15T10:00:00+00:00")
        assert interaction["accepte"] is True

        pret = evaluer_readiness("C1", "2026-06-15T10:05:00+00:00")
        assert pret["accepte"] is True
        assert pret["resultat"]["readiness_ok"] is True
        assert pret["resultat"]["lead_id"] == "C1"

        conversion = transitionner_statut(
            "C1", "converti", "2026-06-16T09:00:00+00:00", reference_devis_m3="DEVIS-M3-001"
        )
        assert conversion["accepte"] is True
        assert conversion["resultat"]["statut"] == "converti"

        # Statut terminal : toute écriture ultérieure est refusée.
        reouverture = transitionner_statut("C1", "qualifie", "2026-06-17T09:00:00+00:00", owner="Bob")
        assert reouverture["accepte"] is False
        assert reouverture["verdict"]["code"] == "REJ-CONVERSATION-CLOSE"

    def test_transition_vers_perdu_exige_un_motif(self):
        ingerer_lead(_contrat("P1"), "2026-06-15T09:00:00+00:00")
        refus = transitionner_statut("P1", "perdu", "2026-06-15T09:30:00+00:00")
        assert refus["accepte"] is False
        assert refus["verdict"]["code"] == "REJ-MOTIF-ABSENT"

        perte = transitionner_statut("P1", "perdu", "2026-06-15T09:30:00+00:00", motif="Ne répond plus")
        assert perte["accepte"] is True
        assert perte["resultat"]["statut"] == "perdu"


# ---------------------------------------------------------------------------
# Doublons : détection unitaire, signalement, arbitrage
# ---------------------------------------------------------------------------
class TestDoublonsUnitaires:
    def test_detecter_signaler_arbitrer(self):
        contact = {"nom": "Zoé Leblanc", "telephone": "450-555-2222", "courriel": "zoe@example.test"}
        ingerer_lead(_contrat("Z1", contact=contact), "2026-06-01T08:00:00+00:00")
        # Isole detecter_doublons de l'auto-signalement de m2_ingerer_lead : on ingère Z2
        # directement via ingestion pure (sans passer par le composite) pour tester le
        # chemin manuel m2_detecter_doublons / m2_signaler_doublon indépendamment.
        from m2_revenue_crm import ingestion
        ingestion.ingerer(_contrat("Z2", contact=contact), _obtenir_registre(), "2026-06-02T08:00:00+00:00")

        trouves = detecter_doublons("Z2")
        assert trouves == ["Z1"]

        signalement = signaler_doublon("Z1", "Z2", "2026-06-02T09:00:00+00:00")
        assert signalement["accepte"] is True
        sig_id = signalement["resultat"]["signalement_id"]

        arbitrage = arbitrer_doublon(sig_id, "distincts_confirmes", "2026-06-02T10:00:00+00:00")
        assert arbitrage["accepte"] is True
        assert arbitrage["resultat"]["arbitrage"] == "distincts_confirmes"

        # Toujours deux dossiers distincts : aucune fusion n'existe.
        assert _obtenir_registre().taille() >= 3  # 2 ingestions + 1 signalement (+ arbitrage)

    def test_decision_arbitrage_hors_enum_refusee_par_le_schema(self):
        outil = next(o for o in outils() if o.nom == "m2_arbitrer_doublon")
        reponse = executer(outil, {
            "signalement_id": "peu-importe",
            "decision": "fusionne",
            "horodatage": "2026-06-02T10:00:00+00:00",
        })
        assert reponse["erreur"] == "arguments_invalides"


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------
class TestDigest:
    def test_lead_en_attente_apparait_au_digest(self):
        ingerer_lead(_contrat("DG1"), "2026-06-15T08:00:00+00:00")
        texte = produire_digest("2026-06-15", "2026-06-15T12:00:00+00:00")
        assert "DG1" in texte


# ---------------------------------------------------------------------------
# Correctifs d'audit
# ---------------------------------------------------------------------------
class TestCorrectifsAudit:
    def test_interaction_ligne_id_est_une_empreinte_pas_un_compteur(self):
        """interactions.py utilisait registre.taille() comme ligne_id au lieu de
        l'identifiant réel retourné par .ajouter()."""
        ingerer_lead(_contrat("LI1"), "2026-06-15T08:00:00+00:00")
        transitionner_statut(
            "LI1", "qualifie", "2026-06-15T08:30:00+00:00", owner="Alice",
            prochaine_action={"description": "Suivi", "echeance": "2026-06-20T09:00:00+00:00"},
        )
        reg = _obtenir_registre()
        taille_avant = reg.taille()
        reponse = enregistrer_interaction("LI1", "Alice", "Appel", "2026-06-15T09:00:00+00:00")
        assert reponse["accepte"] is True
        ligne_id = reponse["resultat"]["ligne_id"]
        assert ligne_id != taille_avant + 1, "ligne_id ne doit pas être un compteur d'entrées (bug audit)"
        assert isinstance(ligne_id, str) and len(ligne_id) >= 32
        assert ligne_id == reg.lire()[-1]["ligne_id"], "ligne_id doit être l'identifiant réel du maillon écrit"

    def test_digest_date_jour_filtre_les_leads_futurs(self):
        """digest.py acceptait date_jour sans jamais filtrer : un lead ingéré
        après date_jour ne doit pas apparaître dans le digest de cette date."""
        ingerer_lead(_contrat("DJ1"), "2026-06-20T08:00:00+00:00")
        texte_avant = produire_digest("2026-06-10", "2026-06-10T12:00:00+00:00")
        assert "DJ1" not in texte_avant, "un lead ingéré après date_jour ne doit pas y apparaître"
        texte_apres = produire_digest("2026-06-20", "2026-06-20T12:00:00+00:00")
        assert "DJ1" in texte_apres

    def test_doublons_signales_a_l_ingestion_visibles_par_arbitrage(self):
        """Correctif d'audit PRD §2b, de bout en bout : le doublon signalé à
        l'ingestion via m2_ingerer_lead est le même objet qu'un arbitrage humain
        peut ensuite trancher avec m2_arbitrer_doublon."""
        contact = {"nom": "Yan Côté", "telephone": "819-555-3333", "courriel": "yan@example.test"}
        ingerer_lead(_contrat("A1", contact=contact), "2026-06-15T08:00:00+00:00")
        reponse = ingerer_lead(_contrat("A2", contact=contact), "2026-06-16T08:00:00+00:00")
        assert len(reponse["doublons_signales"]) == 1
        sig_id = reponse["doublons_signales"][0]["signalement_id"]

        arbitrage = arbitrer_doublon(sig_id, "distincts_confirmes", "2026-06-16T09:00:00+00:00")
        assert arbitrage["accepte"] is True

        texte = produire_digest("2026-06-16", "2026-06-16T12:00:00+00:00")
        assert sig_id not in texte, "un signalement arbitré ne doit plus figurer en attente"
