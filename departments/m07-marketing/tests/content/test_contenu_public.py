"""Tests — brouillon de contenu public (photo de chantier), consentement + floutage (PLAN T4.3).

Module pur testé isolément (comme `reputation/demande_avis.py` / `test_demande_avis.py`) :
aucune donnée réelle, images synthétiques uniquement (AGENTS.md « données inventées »).
"""

from __future__ import annotations

import inspect

from m7_marketing.brand.profil_client import PLACEHOLDER_NOM
from m7_marketing.content import contenu_public
from m7_marketing.moderation.detection import Detection
from m7_marketing.moderation.image import Boite, ImageSynthetique

BRAND_VALIDE = {
    "name": "Entreprise Test Fictive",
    "tagline": "Tagline de test",
    "tone": "professionnel",
    "colors": ["#111111"],
    "langue": "fr",
}

_WCT_BASE = {
    "wct_id": "wct-demo-1",
    "intervention_id": "int-1",
    "lead_id": "lead-1",
    "ville": "Repentigny",
    "type_travaux": "gouttières",
    "consentement_marketing": True,
}


def _wct(**overrides):
    charge = dict(_WCT_BASE)
    charge.update(overrides)
    return charge


def _image_unie(largeur=2, hauteur=2, couleur=(255, 0, 0)) -> ImageSynthetique:
    return ImageSynthetique(largeur=largeur, hauteur=hauteur, pixels=(couleur,) * (largeur * hauteur))


class _DetecteurFixe:
    def __init__(self, detections=()):
        self._detections = detections

    def detecter(self, image):
        return list(self._detections)


_PHOTOS_UNE_PHOTO = [("chantier-apres.jpg", _image_unie())]


# ---------------------------------------------------------------------------
# Consentement : absent ou faux -> refus nommé, fail-closed. Pas de notion de « retrait » ici :
# aucune source de vérité n'existe pour ça aujourd'hui (voir docstring du module,
# README.md/SOUL.md) — seul l'état tel que reçu du WCT fait foi.
# ---------------------------------------------------------------------------
def test_consentement_absent_refuse():
    charge = {k: v for k, v in _WCT_BASE.items() if k != "consentement_marketing"}
    assert "consentement_marketing" not in charge
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        charge, _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon is None
    assert motif == contenu_public.REFUS_CONSENTEMENT_ABSENT


def test_consentement_faux_refuse():
    charge = _wct(consentement_marketing=False)
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        charge, _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon is None
    assert motif == contenu_public.REFUS_CONSENTEMENT_FAUX


# ---------------------------------------------------------------------------
# Profil de marque : absent (invalide) ou non configuré (placeholder) -> refus
# ---------------------------------------------------------------------------
def test_brand_invalide_refuse():
    brand_incomplet = {k: v for k, v in BRAND_VALIDE.items() if k != "colors"}
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        _wct(), _PHOTOS_UNE_PHOTO, brand_incomplet, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon is None
    assert "colors" in motif


def test_brand_encore_placeholder_refuse():
    brand_non_configure = dict(BRAND_VALIDE, name=PLACEHOLDER_NOM)
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        _wct(), _PHOTOS_UNE_PHOTO, brand_non_configure, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon is None
    assert "GATE" in motif or "configuré" in motif


# ---------------------------------------------------------------------------
# Autres refus fail-closed
# ---------------------------------------------------------------------------
def test_aucune_photo_refuse():
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        _wct(), [], BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon is None
    assert motif == contenu_public.REFUS_AUCUNE_PHOTO


def test_wct_id_absent_refuse():
    charge = {k: v for k, v in _WCT_BASE.items() if k != "wct_id"}
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        charge, _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon is None
    assert motif == contenu_public.REFUS_WCT_ID_ABSENT


# ---------------------------------------------------------------------------
# Succès : consentement accordé, marque configurée, floutage réussi
# ---------------------------------------------------------------------------
def test_succes_detections_confiantes_pas_de_revue_requise():
    detecteur = _DetecteurFixe([Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=0.95)])
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        _wct(), _PHOTOS_UNE_PHOTO, BRAND_VALIDE, detecteur, seuil_confiance=0.8
    )
    assert motif is None
    assert brouillon["approval_status"] == "PROPOSE"  # jamais un envoi/publication
    assert brouillon["wct_id"] == "wct-demo-1"
    assert brouillon["ville"] == "Repentigny"
    assert brouillon["brand_name"] == "Entreprise Test Fictive"
    assert brouillon["revue_humaine_requise"] is False
    assert brouillon["motifs_revue_humaine"] == []
    assert len(brouillon["photos"]) == 1
    assert brouillon["photos"][0]["reference"] == "chantier-apres.jpg"
    assert brouillon["photos"][0]["detections"][0]["floutee"] is True
    assert brouillon["preuve_consentement"]["consentement_marketing"] is True
    assert brouillon["preuve_consentement"]["wct_id"] == "wct-demo-1"


def test_succes_doute_de_detection_force_revue_humaine_mais_produit_quand_meme_le_brouillon():
    """Un doute de détection force la revue humaine — il ne bloque pas la préparation du
    brouillon lui-même, puisque M7 ne publie jamais automatiquement de toute façon (N5, hors
    périmètre) : le brouillon DOIT porter le signal, pas disparaître silencieusement."""
    detecteur = _DetecteurFixe([Detection(type="plaque", boite=Boite(0, 0, 1, 1), confiance=0.3)])
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        _wct(), _PHOTOS_UNE_PHOTO, BRAND_VALIDE, detecteur, seuil_confiance=0.8
    )
    assert motif is None
    assert brouillon is not None
    assert brouillon["revue_humaine_requise"] is True
    assert len(brouillon["motifs_revue_humaine"]) == 1
    assert "plaque" in brouillon["motifs_revue_humaine"][0]


def test_id_deterministe_pour_le_meme_wct_id():
    brouillon1, _ = contenu_public.preparer_brouillon_contenu_public(
        _wct(), _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    brouillon2, _ = contenu_public.preparer_brouillon_contenu_public(
        _wct(), _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon1["id"] == brouillon2["id"]


def test_id_differe_pour_un_wct_id_different():
    brouillon_a, _ = contenu_public.preparer_brouillon_contenu_public(
        _wct(wct_id="wct-a"), _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    brouillon_b, _ = contenu_public.preparer_brouillon_contenu_public(
        _wct(wct_id="wct-b"), _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon_a["id"] != brouillon_b["id"]


def test_plusieurs_photos_toutes_traitees():
    photos = [
        ("avant.jpg", _image_unie()),
        ("apres.jpg", _image_unie(couleur=(0, 255, 0))),
    ]
    detecteur = _DetecteurFixe([Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=0.9)])
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        _wct(), photos, BRAND_VALIDE, detecteur, seuil_confiance=0.8
    )
    assert motif is None
    assert [p["reference"] for p in brouillon["photos"]] == ["avant.jpg", "apres.jpg"]


def test_module_pur_contenu_public_naimporte_jamais_opsys():
    source = inspect.getsource(contenu_public)
    assert "import opsys" not in source
    assert "from opsys" not in source
