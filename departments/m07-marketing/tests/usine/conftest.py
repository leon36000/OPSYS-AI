"""Données fictives communes aux tests de l'usine à contenu (PLAN T4.17) : WCT reçu, profil de marque, nature."""

from __future__ import annotations

import pytest
from m7_marketing.usine.chantier import Nature

FICTIF = True

PREUVE_CONSENTEMENT = {
    "consentement_recueilli_par": "etienne",
    "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
    "consentement_version_texte": "consentement-client-fr-CA-v1",
}

PROFIL = {
    "name": "Toitures Boréales Fictive Inc.",
    "tagline": "Rénovation extérieure au Québec, sans surprise",
    "tone": "professionnel, factuel",
    "colors": ["#1a1a1a", "#ffffff"],
    "langue": "fr",
    "site_url": "https://exemple-fictif.ca/",
    "heures_publication": {"facebook": "18:30", "instagram": "19:15"},
}


def _fabriquer_charge(**surcharges):
    """Un WCT `m4.travaux_termines` complet, avec le consentement marketing et sa preuve (M4 les pose ensemble)."""
    charge = {
        "wct_id": "wct-usine-1", "intervention_id": "int-usine-1", "lead_id": "lead-usine-1",
        "technicien_id": "etienne", "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5}, "duree_reelle_minutes": 245,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "ab" * 32,
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"], "devis_id": "devis-usine-1",
        "statut": "completed_verified", "ville": "Repentigny", "type_travaux": "gouttières",
        "photos": ["photo-apres-1", "photo-apres-2"], "description_factuelle": "Installation terminée, sans imprévu.",
        "consentement_marketing": True, "client_satisfait": True, **PREUVE_CONSENTEMENT,
    }
    charge.update(surcharges)
    return charge


@pytest.fixture
def fabriquer_charge():
    """La fabrique de WCT : `fabriquer_charge(client_satisfait=False)` surcharge des clés, jamais autre chose."""
    return _fabriquer_charge


@pytest.fixture
def cles_de_preuve():
    return tuple(PREUVE_CONSENTEMENT)


@pytest.fixture
def charge():
    return _fabriquer_charge()


@pytest.fixture
def profil():
    return dict(PROFIL)


@pytest.fixture
def nature():
    return Nature("Gouttières et descentes", ("gouttière", "descente pluviale", "descente de gouttière"))
