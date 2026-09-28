"""Tests — brouillon de demande d'avis à partir d'un WCT `m4.travaux_termines` (PLAN T1.2-c).

`construire_brouillon` est une fonction pure (aucun import `opsys`, testée ici sans base de
données ni bus d'événements) ; l'intégration bout en bout (bus réel, registre durable,
idempotence de l'adaptateur) est couverte par `tests/test_evenements_travaux_termines.py`.
"""

from __future__ import annotations

from m7_marketing.reputation import demande_avis

# ---------------------------------------------------------------------------
# Données de test (forme d'un WCT m4.travaux_termines, champs requis minimaux + optionnels M7)
# ---------------------------------------------------------------------------
_WCT_BASE = {
    "wct_id": "wct-demo-1",
    "intervention_id": "int-1",
    "lead_id": "lead-1",
    "technicien_id": "tech-1",
    "horodatage_completion": "2026-09-28T14:00:00-04:00",
    "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
    "duree_reelle_minutes": 180,
    "ecart_signale": False,
    "revue_id": None,
    "hash_maillon": "deadbeef",
    "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
    "devis_id": "devis-1",
    "statut": "completed_verified",
}


def _wct(**overrides):
    charge = dict(_WCT_BASE)
    charge.update(overrides)
    return charge


# ---------------------------------------------------------------------------
# Autorisation : consentement vrai ET client_satisfait pas faux
# ---------------------------------------------------------------------------
def test_consentement_vrai_et_client_satisfait_produit_un_brouillon_propose():
    charge = _wct(ville="Repentigny", type_travaux="gouttières", consentement_marketing=True, client_satisfait=True)
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert motif is None
    assert brouillon["approval_status"] == "PROPOSE"
    assert brouillon["wct_id"] == "wct-demo-1"
    assert brouillon["intervention_id"] == "int-1"
    assert brouillon["lead_id"] == "lead-1"
    assert brouillon["ville"] == "Repentigny"
    assert brouillon["type_travaux"] == "gouttières"
    assert "gouttières à Repentigny" in brouillon["texte"]


def test_client_satisfait_null_non_recueilli_produit_quand_meme_un_brouillon():
    """`client_satisfait: null` (« non recueilli, jamais inventé », catalogue m4.travaux_termines)
    n'est pas `false` : la règle est « n'est pas faux », donc ceci reste autorisé."""
    charge = _wct(consentement_marketing=True, client_satisfait=None)
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert motif is None
    assert brouillon is not None


# ---------------------------------------------------------------------------
# Fail-closed : tout champ absent ou défavorable vaut refus, jamais un brouillon
# ---------------------------------------------------------------------------
def test_consentement_absent_refuse_fail_closed():
    charge = _wct(client_satisfait=True)  # consentement_marketing absent du tout
    assert "consentement_marketing" not in charge
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_CONSENTEMENT_ABSENT


def test_consentement_faux_refuse():
    charge = _wct(consentement_marketing=False, client_satisfait=True)
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_CONSENTEMENT_FAUX


def test_client_satisfait_absent_refuse_fail_closed():
    charge = _wct(consentement_marketing=True)  # client_satisfait absent du tout
    assert "client_satisfait" not in charge
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_CLIENT_SATISFAIT_ABSENT


def test_client_insatisfait_refuse():
    charge = _wct(consentement_marketing=True, client_satisfait=False)
    brouillon, motif = demande_avis.construire_brouillon(charge)
    assert brouillon is None
    assert motif == demande_avis.REFUS_CLIENT_INSATISFAIT


# ---------------------------------------------------------------------------
# Gabarit fixe : jamais un fait inventé quand ville / type_travaux manquent
# ---------------------------------------------------------------------------
def test_gabarit_sans_ville_ni_type_travaux_reste_generique():
    charge = _wct(consentement_marketing=True, client_satisfait=True)
    brouillon, _ = demande_avis.construire_brouillon(charge)
    assert brouillon["ville"] is None
    assert brouillon["type_travaux"] is None
    assert "pour vos travaux. " in brouillon["texte"]
    assert "None" not in brouillon["texte"]


def test_gabarit_avec_ville_seule():
    charge = _wct(ville="Lévis", consentement_marketing=True, client_satisfait=True)
    brouillon, _ = demande_avis.construire_brouillon(charge)
    assert "à Lévis" in brouillon["texte"]


# ---------------------------------------------------------------------------
# Identifiant déterministe (condition nécessaire à l'idempotence côté adaptateur)
# ---------------------------------------------------------------------------
def test_id_deterministe_pour_le_meme_wct_id():
    charge = _wct(wct_id="wct-fixe", consentement_marketing=True, client_satisfait=True)
    brouillon1, _ = demande_avis.construire_brouillon(charge)
    brouillon2, _ = demande_avis.construire_brouillon(charge)
    assert brouillon1["id"] == brouillon2["id"]


def test_id_differe_pour_un_wct_id_different():
    charge_a = _wct(wct_id="wct-a", consentement_marketing=True, client_satisfait=True)
    charge_b = _wct(wct_id="wct-b", consentement_marketing=True, client_satisfait=True)
    brouillon_a, _ = demande_avis.construire_brouillon(charge_a)
    brouillon_b, _ = demande_avis.construire_brouillon(charge_b)
    assert brouillon_a["id"] != brouillon_b["id"]


# ---------------------------------------------------------------------------
# Jamais d'exception : un refus métier n'est pas une panne
# ---------------------------------------------------------------------------
def test_charge_minimale_sans_champs_optionnels_ne_leve_jamais():
    brouillon, motif = demande_avis.construire_brouillon(_wct())
    assert brouillon is None
    assert isinstance(motif, str) and motif
