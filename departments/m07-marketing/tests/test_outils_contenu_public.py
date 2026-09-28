"""Tests — outil d'agent `m7_preparer_contenu_public` (adaptateur, PLAN T4.3).

Base durable temporaire isolée (même patron que `tests/test_evenements_travaux_termines.py`) :
le registre `contenu_public` est persisté via `opsys.stockage.maillons`, jamais un dict en
mémoire de processus.
"""

from __future__ import annotations

import pytest
from m7_marketing import outils
from m7_marketing.moderation.detection import Detection
from m7_marketing.moderation.image import Boite

from opsys import stockage
from opsys.outils import Autonomie, executer

BRAND_VALIDE = {
    "name": "Entreprise Test Fictive",
    "tagline": "Tagline de test",
    "tone": "professionnel",
    "colors": ["#111111"],
    "langue": "fr",
}

_CHARGE = {
    "wct_id": "wct-outil-1",
    "intervention_id": "int-1",
    "lead_id": "lead-1",
    "ville": "Repentigny",
    "type_travaux": "gouttières",
    "consentement_marketing": True,
}

_PHOTO = {
    "reference": "chantier-apres.jpg",
    "image": {"largeur": 2, "hauteur": 2, "pixels": [[255, 0, 0]] * 4},
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


class _DetecteurFixe:
    def __init__(self, detections=()):
        self._detections = detections

    def detecter(self, image):
        return list(self._detections)


# ---------------------------------------------------------------------------
# Comportement RÉEL de ce bac à sable : cv2 absent -> refus nommé, jamais un faux vert
# ---------------------------------------------------------------------------
def test_detecteur_reel_indisponible_dans_ce_bac_a_sable(base_durable):
    resultat = outils.preparer_contenu_public(
        dict(_CHARGE), [_PHOTO], BRAND_VALIDE, seuil_confiance=0.8
    )
    assert resultat["brouillon"] is None
    assert resultat["statut"] == "detecteur_indisponible"
    assert "cv2" in resultat["motif"]


# ---------------------------------------------------------------------------
# Détecteur injecté (monkeypatch de l'usine par défaut) : chemin complet de l'adaptateur
# ---------------------------------------------------------------------------
def test_succes_avec_detecteur_injecte_depose_dans_le_registre(base_durable, monkeypatch):
    monkeypatch.setattr(
        outils.moderation_detection,
        "detecteur_opencv_par_defaut",
        lambda: _DetecteurFixe([Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=0.95)]),
    )
    resultat = outils.preparer_contenu_public(
        dict(_CHARGE), [_PHOTO], BRAND_VALIDE, seuil_confiance=0.8
    )
    assert resultat["statut"] == "propose"
    assert resultat["brouillon"]["approval_status"] == "PROPOSE"
    assert resultat["brouillon"]["wct_id"] == "wct-outil-1"

    registre = list(stockage.maillons("m07-marketing", "contenu_public"))
    assert len(registre) == 1
    assert registre[0]["id"] == resultat["brouillon"]["id"]


def test_idempotent_par_wct_id(base_durable, monkeypatch):
    monkeypatch.setattr(
        outils.moderation_detection, "detecteur_opencv_par_defaut", lambda: _DetecteurFixe([])
    )
    premier = outils.preparer_contenu_public(dict(_CHARGE), [_PHOTO], BRAND_VALIDE, seuil_confiance=0.8)
    assert premier["statut"] == "propose"

    second = outils.preparer_contenu_public(dict(_CHARGE), [_PHOTO], BRAND_VALIDE, seuil_confiance=0.8)
    assert second["statut"] == "deja_prepare"
    assert second["brouillon"]["id"] == premier["brouillon"]["id"]

    registre = list(stockage.maillons("m07-marketing", "contenu_public"))
    assert len(registre) == 1  # jamais un second brouillon pour le même chantier


def test_refus_consentement_absent_ne_persiste_rien(base_durable, monkeypatch):
    monkeypatch.setattr(
        outils.moderation_detection, "detecteur_opencv_par_defaut", lambda: _DetecteurFixe([])
    )
    charge_sans_consentement = {k: v for k, v in _CHARGE.items() if k != "consentement_marketing"}
    resultat = outils.preparer_contenu_public(
        charge_sans_consentement, [_PHOTO], BRAND_VALIDE, seuil_confiance=0.8
    )
    assert resultat["brouillon"] is None
    assert resultat["statut"] == "refuse"
    assert "consentement_marketing" in resultat["motif"]
    assert list(stockage.maillons("m07-marketing", "contenu_public")) == []


# ---------------------------------------------------------------------------
# Contrat de l'outil (manifeste, autonomie, exécution via le contrat générique)
# ---------------------------------------------------------------------------
def test_outil_declare_en_t1_jamais_publication_automatique():
    outil = next(o for o in outils.outils() if o.nom == "m7_preparer_contenu_public")
    assert outil.autonomie == Autonomie.T1


def test_outil_executable_via_le_contrat_generique(base_durable):
    outil = next(o for o in outils.outils() if o.nom == "m7_preparer_contenu_public")
    reponse = executer(
        outil,
        {
            "charge": dict(_CHARGE, wct_id="wct-outil-executer"),
            "photos": [_PHOTO],
            "brand": BRAND_VALIDE,
            "seuil_confiance": 0.8,
        },
    )
    assert reponse["ok"] is True
    assert reponse["resultat"]["statut"] == "detecteur_indisponible"  # comportement réel, jamais un faux vert
