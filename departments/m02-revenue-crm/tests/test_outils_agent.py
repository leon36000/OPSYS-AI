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
    marquer_chantier_termine,
    obtenir_client_360,
    outils,
    produire_digest,
    reinitialiser_registre,
    signaler_doublon,
    suggerer_prochaine_action,
    transitionner_statut,
    trouver_client_de_lead,
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
    assert "m2_marquer_chantier_termine" in noms
    assert all(nom.startswith("m2_") for nom in noms)
    assert len(noms) == len(set(noms)), "noms d'outils en double"
    # PLAN T1.1-a : m04-field-ops ajouté — M2 consomme le signal de fin de chantier de M4
    # (DEFINITION-PRODUIT §6, cascade « travaux terminés », ligne M2) via
    # m2_marquer_chantier_termine. M2.7 : m03-estimation ajouté — M2 consomme le signal de devis
    # sans réponse de M3 (voir test_evenements.py::TestManifeste).
    assert dep.dependances == ("m01-front-office", "m03-estimation", "m04-field-ops")
    assert dep.mode == "ombre"
    # PLAN T2.2 : Client 360 + suggestion de prochaine action, trois nouveaux outils T0 (lecture).
    for nom_attendu in ("m2_trouver_client_de_lead", "m2_obtenir_client_360", "m2_suggerer_prochaine_action"):
        assert nom_attendu in noms
        outil = next(o for o in dep.charger_outils() if o.nom == nom_attendu)
        assert outil.autonomie.value == "T0", f"{nom_attendu} doit être une lecture pure (T0)"


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
        # PLAN T2.2 (Client 360) : chaque lead ingéré est rattaché à un client.
        assert reponse["client_id"], "client_id doit être présent et non vide"
        assert reponse["client_id"] == reponse["accuse_ingestion"]["client_id"]

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

        # PLAN T1.1-a : converti n'est plus un statut terminal (la suite du cycle de vie —
        # cédule, chantier, facture, paiement, avis — lui succède, DEFINITION-PRODUIT §7 M2).
        # Le retour vers qualifie reste refusé (protection commerciale), mais via
        # REJ-TRANSITION-ILLEGALE (couple hors table) et non plus REJ-CONVERSATION-CLOSE.
        reouverture = transitionner_statut("C1", "qualifie", "2026-06-17T09:00:00+00:00", owner="Bob")
        assert reouverture["accepte"] is False
        assert reouverture["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"

    def test_transition_vers_perdu_exige_un_motif(self):
        ingerer_lead(_contrat("P1"), "2026-06-15T09:00:00+00:00")
        refus = transitionner_statut("P1", "perdu", "2026-06-15T09:30:00+00:00")
        assert refus["accepte"] is False
        assert refus["verdict"]["code"] == "REJ-MOTIF-ABSENT"

        perte = transitionner_statut("P1", "perdu", "2026-06-15T09:30:00+00:00", motif="Ne répond plus")
        assert perte["accepte"] is True
        assert perte["resultat"]["statut"] == "perdu"


# ---------------------------------------------------------------------------
# m2_marquer_chantier_termine (PLAN T1.1-a) : chorégraphie « travaux terminés » côté M2
# (DEFINITION-PRODUIT §6, cascade, ligne M2 ; §9.7).
# ---------------------------------------------------------------------------
class TestMarquerChantierTermine:
    def _lead_au_chantier(self, lead_id):
        """Amène un lead jusqu'au statut 'chantier', par les outils composés (pas d'accès
        direct au registre)."""
        ingerer_lead(_contrat(lead_id), "2026-06-15T09:00:00+00:00")
        transitionner_statut(
            lead_id, "qualifie", "2026-06-15T09:05:00+00:00",
            owner="Alice",
            prochaine_action={"description": "Appeler", "echeance": "2026-06-20T09:00:00+00:00"},
        )
        transitionner_statut(lead_id, "converti", "2026-06-15T09:10:00+00:00", reference_devis_m3="DEVIS-1")
        transitionner_statut(lead_id, "cedule", "2026-06-15T09:15:00+00:00")
        transitionner_statut(lead_id, "chantier", "2026-06-15T09:20:00+00:00")

    def test_nominal_ecrit_deux_maillons_et_avance_a_facture(self):
        self._lead_au_chantier("WCT1")
        taille_avant = _obtenir_registre().taille()

        reponse = marquer_chantier_termine(
            "WCT1", "2026-06-20T16:00:00+00:00",
            prochaine_action={
                "description": "M5 : émettre la facture",
                "echeance": "2026-06-25T09:00:00+00:00",
            },
        )

        assert reponse["accepte"] is True
        assert reponse["resultat"]["transition"]["statut"] == "facture"
        assert reponse["resultat"]["transition"]["statut_precedent"] == "chantier"
        assert _obtenir_registre().taille() == taille_avant + 2, "exactement deux maillons"

        maillons_interaction = [
            m for m in _obtenir_registre().lire() if m["type_entree"] == "interaction" and m["lead_id"] == "WCT1"
        ]
        assert len(maillons_interaction) == 1
        interaction = maillons_interaction[0]
        assert interaction["auteur"] == "system:m4", "jamais un humain pour cette interaction système"
        assert "WCT1" in interaction["resume"]
        assert "M5 : émettre la facture" in interaction["resume"], "résumé construit depuis les champs reçus"
        assert reponse["resultat"]["interaction"]["ligne_id"] == interaction["ligne_id"]

    def test_sans_prochaine_action_rejete_fail_closed_sans_ecriture(self):
        self._lead_au_chantier("WCT2")
        taille_avant = _obtenir_registre().taille()

        reponse = marquer_chantier_termine("WCT2", "2026-06-20T16:00:00+00:00")

        assert reponse["accepte"] is False
        assert reponse["verdict"]["code"] == "REJ-ACTION-ABSENTE"
        assert _obtenir_registre().taille() == taille_avant, "rejet fail-closed : aucun maillon écrit"

        # Preuve positive que le lead est resté exactement à 'chantier' (pas de maillon
        # orphelin, pas d'état intermédiaire) : le même appel réussit une fois la prochaine
        # action fournie.
        reponse_ok = marquer_chantier_termine(
            "WCT2", "2026-06-20T16:01:00+00:00",
            prochaine_action={"description": "Facturer", "echeance": "2026-06-25T09:00:00+00:00"},
        )
        assert reponse_ok["accepte"] is True
        assert reponse_ok["resultat"]["transition"]["statut_precedent"] == "chantier"

    def test_hors_statut_chantier_rejete_sans_ecriture(self):
        """Un lead qui n'est pas encore au chantier (encore 'nouveau') ne peut pas être marqué
        terminé : REJ-TRANSITION-ILLEGALE, et aucun des deux maillons n'est écrit."""
        ingerer_lead(_contrat("WCT3"), "2026-06-15T09:00:00+00:00")
        taille_avant = _obtenir_registre().taille()

        reponse = marquer_chantier_termine(
            "WCT3", "2026-06-20T16:00:00+00:00",
            prochaine_action={"description": "Appeler", "echeance": "2026-06-25T09:00:00+00:00"},
        )

        assert reponse["accepte"] is False
        assert reponse["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"
        assert _obtenir_registre().taille() == taille_avant

    def test_outil_expose_en_t1_avec_prochaine_action_obligatoire(self):
        outil = next(o for o in outils() if o.nom == "m2_marquer_chantier_termine")
        assert outil.autonomie.value == "T1", "écriture interne au registre, comme les autres outils d'écriture de M2"
        assert set(outil.parametres["required"]) == {"lead_id", "horodatage", "prochaine_action"}

    def test_prochaine_action_absente_refusee_par_le_schema(self):
        """Double filet : la couche schéma (arguments_invalides) rejette déjà l'absence de
        prochaine_action avant même d'exécuter la fonction métier — qui la rejette aussi
        (test_sans_prochaine_action_rejete_fail_closed_sans_ecriture)."""
        outil = next(o for o in outils() if o.nom == "m2_marquer_chantier_termine")
        reponse = executer(outil, {"lead_id": "WCT4", "horodatage": "2026-06-20T16:00:00+00:00"})
        assert reponse["erreur"] == "arguments_invalides"


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


# ---------------------------------------------------------------------------
# Client 360 (PLAN T2.2)
# ---------------------------------------------------------------------------
class TestClient360:
    def test_trouver_client_de_lead_et_obtenir_client_360(self):
        reponse = ingerer_lead(_contrat("CL1"), "2026-06-15T09:00:00+00:00")
        client_id = reponse["client_id"]

        trouve = trouver_client_de_lead("CL1")
        assert trouve["accepte"] is True
        assert trouve["resultat"] == {"lead_id": "CL1", "client_id": client_id}

        vue = obtenir_client_360(client_id)
        assert vue["accepte"] is True
        assert vue["resultat"]["client_id"] == client_id
        assert len(vue["resultat"]["opportunites"]) == 1
        assert vue["resultat"]["opportunites"][0]["lead_id"] == "CL1"

    def test_deux_leads_du_meme_contact_partagent_le_meme_client_et_la_meme_vue(self):
        contact = {"nom": "Client Répété", "telephone": "418-555-7777", "courriel": "repete@example.test"}
        r1 = ingerer_lead(_contrat("CL2", contact=contact), "2026-01-10T09:00:00+00:00")
        r2 = ingerer_lead(_contrat("CL3", contact=contact), "2026-08-15T09:00:00+00:00")
        assert r1["client_id"] == r2["client_id"]

        vue = obtenir_client_360(r1["client_id"])
        assert vue["accepte"] is True
        leads_vus = sorted(o["lead_id"] for o in vue["resultat"]["opportunites"])
        assert leads_vus == ["CL2", "CL3"]

    def test_client_id_introuvable_rend_un_verdict_nomme(self):
        reponse = obtenir_client_360("client-jamais-vu")
        assert reponse["accepte"] is False
        assert reponse["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"

    def test_lead_introuvable_pour_trouver_client_rend_un_verdict_nomme(self):
        reponse = trouver_client_de_lead("lead-jamais-vu")
        assert reponse["accepte"] is False
        assert reponse["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"

    def test_outils_client_360_exposes_en_t0_lecture_pure(self):
        for nom in ("m2_trouver_client_de_lead", "m2_obtenir_client_360"):
            outil = next(o for o in outils() if o.nom == nom)
            arguments = {"lead_id": "peu-importe"} if "lead" in nom else {"client_id": "peu-importe"}
            reponse = executer(outil, arguments)
            # Lecture pure : même un identifiant inconnu rend une réponse normale (verdict), pas
            # une exception ; l'outil n'écrit jamais (T0 déjà vérifié par le manifeste ci-dessus).
            assert reponse["ok"] is True


# ---------------------------------------------------------------------------
# Suggestion de prochaine action (PLAN T2.2, M2.6)
# ---------------------------------------------------------------------------
class TestSuggererProchaineAction:
    def test_lead_nouveau_suggere_assigner_owner(self):
        ingerer_lead(_contrat("SG1"), "2026-06-15T09:00:00+00:00")
        reponse = suggerer_prochaine_action("SG1", "2026-06-15T10:00:00+00:00")
        assert reponse["accepte"] is True
        assert reponse["resultat"]["regle"] == "assigner_owner"

    def test_jamais_applique_automatiquement_au_registre(self):
        """La suggestion ne modifie JAMAIS statut/prochaine_action réels du lead : seul un humain
        les fixe via m2_transitionner_statut."""
        ingerer_lead(_contrat("SG2"), "2026-06-15T09:00:00+00:00")
        taille_avant = _obtenir_registre().taille()
        suggerer_prochaine_action("SG2", "2026-06-15T10:00:00+00:00")
        assert _obtenir_registre().taille() == taille_avant

    def test_lead_introuvable_rend_un_verdict_nomme(self):
        reponse = suggerer_prochaine_action("jamais-ingere", "2026-06-15T10:00:00+00:00")
        assert reponse["accepte"] is False
        assert reponse["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"
