"""Suggestion déterministe de prochaine meilleure action (PLAN T2.2, M2.6) : `suggestions.py`.

Module testé PUR : ces tests n'importent que des modules purs du paquet (jamais
`outils.py`/`opsys`), même patron que `test_doublons.py`/`test_readiness.py`.
"""

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m2_revenue_crm import doublons, ingestion, interactions, registre, statuts, suggestions  # noqa: E402


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


def _amener_a(reg, lead_id, statut_cible, **surcharges_contrat):
    """Fait avancer un lead fictif jusqu'à `statut_cible`, par les fonctions métier pures
    (jamais outils.py) — même patron que test_evenements.py::_amener_a, en pur."""
    ingestion.ingerer(_contrat(lead_id, **surcharges_contrat), reg, "2026-06-01T09:00:00+00:00")
    if statut_cible == "nouveau":
        return
    statuts.transitionner(
        lead_id, "qualifie", reg, "2026-06-01T09:05:00+00:00",
        owner="Alice", prochaine_action={"description": "Appeler", "echeance": "2026-06-05T09:00:00+00:00"},
    )
    if statut_cible == "qualifie":
        return
    if statut_cible == "perdu":
        statuts.transitionner(lead_id, "perdu", reg, "2026-06-01T09:10:00+00:00", motif="Ne répond plus")
        return
    statuts.transitionner(lead_id, "converti", reg, "2026-06-01T09:10:00+00:00", reference_devis_m3="DEVIS-1")
    if statut_cible == "converti":
        return
    statuts.transitionner(lead_id, "cedule", reg, "2026-06-01T09:15:00+00:00")
    if statut_cible == "cedule":
        return
    statuts.transitionner(lead_id, "chantier", reg, "2026-06-01T09:20:00+00:00")
    if statut_cible == "chantier":
        return
    statuts.transitionner(
        lead_id, "facture", reg, "2026-06-01T09:25:00+00:00",
        prochaine_action={"description": "Facturer", "echeance": "2026-06-10T09:00:00+00:00"},
    )
    if statut_cible == "facture":
        return
    statuts.transitionner(lead_id, "paiement", reg, "2026-06-01T09:30:00+00:00")
    if statut_cible == "paiement":
        return
    statuts.transitionner(lead_id, "avis", reg, "2026-06-01T09:35:00+00:00")


class TestCasDeBase:
    def test_lead_introuvable(self):
        reg = registre.Registre()
        resultat, verdict = suggestions.suggerer(reg, "INEXISTANT", "2026-06-15T10:00:00+00:00")
        assert resultat is None
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"

    def test_horodatage_invalide(self):
        reg = registre.Registre()
        _amener_a(reg, "H1", "nouveau")
        resultat, verdict = suggestions.suggerer(reg, "H1", "pas-une-date")
        assert resultat is None
        assert verdict["code"] == "REJ-HORODATAGE-INVALIDE"

    def test_lead_perdu_dossier_clos(self):
        reg = registre.Registre()
        _amener_a(reg, "P1", "perdu")
        resultat, verdict = suggestions.suggerer(reg, "P1", "2026-06-15T10:00:00+00:00")
        assert resultat is None
        assert verdict["code"] == "REJ-CONVERSATION-CLOSE"

    def test_fonction_pure_registre_inchange(self):
        reg = registre.Registre()
        _amener_a(reg, "PUR1", "qualifie")
        taille_avant = reg.taille()
        suggestions.suggerer(reg, "PUR1", "2026-06-15T10:00:00+00:00")
        assert reg.taille() == taille_avant, "suggerer ne doit jamais écrire au registre"


class TestDoublonEnAttentePrioritaire:
    def test_doublon_en_attente_prime_sur_le_reste_de_la_table(self):
        contact = {"nom": "Marie Roy", "telephone": "581-555-1111"}
        reg = registre.Registre()
        _amener_a(reg, "DB1", "nouveau", contact=dict(contact))
        ingestion.ingerer(_contrat("DB2", contact=dict(contact)), reg, "2026-06-02T09:00:00+00:00")
        signalement, verdict = doublons.signaler(reg, "DB1", "DB2", "2026-06-02T09:05:00+00:00")
        assert verdict is None

        resultat, v = suggestions.suggerer(reg, "DB1", "2026-06-15T10:00:00+00:00")
        assert v is None
        assert resultat["regle"] == "doublon_en_attente"
        assert signalement["signalement_id"] in resultat["suggestion"]

    def test_doublon_arbitre_ne_bloque_plus_la_suggestion(self):
        contact = {"nom": "Marie Roy", "telephone": "581-555-1111"}
        reg = registre.Registre()
        _amener_a(reg, "DB3", "nouveau", contact=dict(contact))
        ingestion.ingerer(_contrat("DB4", contact=dict(contact)), reg, "2026-06-02T09:00:00+00:00")
        signalement, _ = doublons.signaler(reg, "DB3", "DB4", "2026-06-02T09:05:00+00:00")
        doublons.arbitrer(reg, signalement["signalement_id"], "distincts_confirmes", "2026-06-02T09:10:00+00:00")

        resultat, v = suggestions.suggerer(reg, "DB3", "2026-06-15T10:00:00+00:00")
        assert v is None
        assert resultat["regle"] == "assigner_owner", "statut nouveau, plus de doublon en attente"


class TestParStatut:
    def test_nouveau_suggere_assigner_owner(self):
        reg = registre.Registre()
        _amener_a(reg, "N1", "nouveau")
        resultat, v = suggestions.suggerer(reg, "N1", "2026-06-15T10:00:00+00:00")
        assert v is None
        assert resultat["regle"] == "assigner_owner"
        assert resultat["statut"] == "nouveau"

    def test_qualifie_sans_interaction_suggere_completer_readiness(self):
        reg = registre.Registre()
        _amener_a(reg, "Q1", "qualifie")
        resultat, v = suggestions.suggerer(reg, "Q1", "2026-06-15T10:00:00+00:00")
        assert v is None
        assert resultat["regle"] == "completer_readiness"
        assert "interaction" in resultat["suggestion"]

    def test_qualifie_pret_suggere_transmettre_m3(self):
        reg = registre.Registre()
        _amener_a(reg, "Q2", "qualifie")
        interactions.enregistrer("Q2", "Alice", "Appel de suivi", reg, "2026-06-01T10:00:00+00:00")
        resultat, v = suggestions.suggerer(reg, "Q2", "2026-06-15T10:00:00+00:00")
        assert v is None
        assert resultat["regle"] == "transmettre_m3"

    @pytest.mark.parametrize("statut_cible", ["converti", "cedule", "chantier"])
    def test_chantier_en_cours_suggere_suivre_chantier(self, statut_cible):
        reg = registre.Registre()
        _amener_a(reg, f"C-{statut_cible}", statut_cible)
        resultat, v = suggestions.suggerer(reg, f"C-{statut_cible}", "2026-06-15T10:00:00+00:00")
        assert v is None
        assert resultat["regle"] == "suivre_chantier"
        assert resultat["statut"] == statut_cible

    @pytest.mark.parametrize("statut_cible", ["facture", "paiement"])
    def test_post_chantier_suggere_suivre_paiement(self, statut_cible):
        reg = registre.Registre()
        _amener_a(reg, f"F-{statut_cible}", statut_cible)
        resultat, v = suggestions.suggerer(reg, f"F-{statut_cible}", "2026-06-15T10:00:00+00:00")
        assert v is None
        assert resultat["regle"] == "suivre_paiement"

    def test_avis_suggere_relance_avis_reference(self):
        reg = registre.Registre()
        _amener_a(reg, "AV1", "avis")
        resultat, v = suggestions.suggerer(reg, "AV1", "2026-06-15T10:00:00+00:00")
        assert v is None
        assert resultat["regle"] == "relance_avis_reference"
