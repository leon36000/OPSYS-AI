"""Profils fictifs de marque v2 (M7-MARQUE). Aucune donnée réelle : une entreprise, des mots et des garanties
inventés."""

from __future__ import annotations

import copy

import pytest
from m7_marketing.brand import profil_v2

FICTIF = True
VALIDE = {"statut": "valide", "par": "nathan", "le": "2026-11-02"}

PROFIL_V1 = {
    "name": "Toitures Boréales Fictive Inc.",
    "tagline": "Rénovation extérieure au Québec, sans surprise",
    "tone": "professionnel, factuel",
    "colors": ["#1a1a1a", "#ffffff"],
    "langue": "fr",
    "site_url": "https://exemple-fictif.ca/",
}

PROFIL_V2 = {
    **PROFIL_V1,
    "promesse": "Un chantier propre et bien expliqué du début à la fin",
    "avantages": ["Une équipe locale qui connaît la région"],
    "zones_desservies": ["Repentigny", "Terrebonne"],
    "valeurs": ["Honnêteté", "Propreté du chantier"],
    "objections_frequentes": [
        {"objection": "Les travaux seront trop longs", "reponse": "Nous expliquons chaque étape avant de commencer."}
    ],
    "preuve_sociale": ["Nos clients nous recommandent à leurs voisins"],
    "garanties_validees": ["Garantie légale de qualité des travaux"],
    "garanties_a_valider": ["Garantie de dix ans sur tout le revêtement"],
    "mots_interdits": ["pas cher", "bas de gamme"],
    "messages_interdits": ["vous ne trouverez pas mieux ailleurs"],
    "voix": {"adresse": "vous", "exclamations_max": 1, "majuscules_max_pct": 30, "emojis_max": 1},
    "style_plateforme": {"facebook": {"longueur_min": 60, "hashtags_max": 3, "emojis_max": 1}},
    "validation_champs": {
        "promesse": VALIDE,
        "valeurs": VALIDE,
        "zones_desservies": VALIDE,
    },
}


@pytest.fixture
def v1():
    return copy.deepcopy(PROFIL_V1)


@pytest.fixture
def v2():
    return profil_v2.normaliser(copy.deepcopy(PROFIL_V2))


# -- base durable et outils réels (comme en production : une transaction par appel)
# -------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    from opsys import stockage

    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def proprietaire(base_durable):
    from opsys import identite, stockage

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-de-test-1234", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "etienne", "Étienne fictif", "mot-de-passe-de-test-1234", ["employee"])


@pytest.fixture
def appeler(base_durable):
    from m7_marketing import outils

    from opsys import contexte
    from opsys.outils import executer_atomique

    catalogue = {o.nom: o for o in outils.outils()}

    def _appeler(nom, *, appareil=None, **arguments):
        if appareil is None:
            return executer_atomique(catalogue[nom], arguments)
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(*appareil)):
            return executer_atomique(catalogue[nom], arguments)

    return _appeler


@pytest.fixture
def enregistrer_marque(base_durable):
    """Enregistre un profil dans le registre durable de marque (signé par `nathan`), comme le ferait le propriétaire."""
    from m7_marketing.brand import registre

    from opsys import stockage

    def _enregistrer(profil, signataire="nathan"):
        with stockage.transaction():
            return registre.enregistrer(profil, signataire, "2026-11-02T09:00:00-05:00")

    return _enregistrer


@pytest.fixture
def charge():
    """Un WCT `m4.travaux_termines` complet, avec le consentement marketing et sa preuve."""
    return {
        "wct_id": "wct-marque-1",
        "intervention_id": "int-marque-1",
        "lead_id": "lead-marque-1",
        "technicien_id": "etienne",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 245,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "ab" * 32,
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
        "devis_id": "devis-marque-1",
        "statut": "completed_verified",
        "ville": "Repentigny",
        "type_travaux": "gouttières",
        "photos": ["photo-apres-1", "photo-apres-2"],
        "description_factuelle": "Installation terminée, sans imprévu.",
        "consentement_marketing": True,
        "client_satisfait": True,
        "consentement_recueilli_par": "etienne",
        "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
        "consentement_version_texte": "consentement-client-fr-CA-v1",
    }


@pytest.fixture
def semer_wct(base_durable):
    from opsys import stockage

    def _semer(charge):
        with stockage.transaction():
            stockage.maillons("m07-marketing", "wct_recus").append(dict(charge))
        return charge["wct_id"]

    return _semer
