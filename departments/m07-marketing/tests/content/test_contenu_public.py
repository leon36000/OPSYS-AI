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

# La preuve d'un consentement, posée par M4 (qui, quand, quel texte) : sans elle, le consentement n'est pas documenté.
PREUVE = {
    "consentement_recueilli_par": "etienne",
    "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
    "consentement_version_texte": "consentement-client-fr-CA-v1",
}

_WCT_BASE = {
    "wct_id": "wct-demo-1",
    "intervention_id": "int-1",
    "lead_id": "lead-1",
    "ville": "Repentigny",
    "type_travaux": "gouttières",
    "consentement_marketing": True,
    **PREUVE,
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
# Consentement : absent, faux ou sans sa preuve -> refus nommé, fail-closed. Le retrait est un registre à part
# (`usine.retrait`), consulté par l'adaptateur avant ce module : voir `tests/usine/test_service_usine.py`.
# ---------------------------------------------------------------------------
def test_consentement_absent_refuse():
    charge = {k: v for k, v in _WCT_BASE.items() if k != "consentement_marketing"}
    assert "consentement_marketing" not in charge
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        charge, _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert brouillon is None
    assert motif == contenu_public.REFUS_CONSENTEMENT_ABSENT


def test_le_consentement_est_strictement_vrai_jamais_une_valeur_qui_y_ressemble():
    """Un fait de consentement n'est ni « oui », ni « true », ni 1 : seul le booléen vrai du WCT consent."""
    for pas_un_consentement in ("oui", "true", "True", 1, ["x"], {"a": 1}):
        charge = _wct(consentement_marketing=pas_un_consentement)
        assert contenu_public.verifier_consentement(charge) == contenu_public.REFUS_CONSENTEMENT_FAUX, (
            pas_un_consentement)
    assert contenu_public.verifier_consentement(_wct(consentement_marketing=True)) is None


def test_consentement_sans_preuve_refuse():
    """Un consentement que personne ne peut relire (qui, quand, quel texte) n'est pas documenté : fail-closed,
    même si `consentement_marketing` est vrai."""
    for cle in PREUVE:
        charge = {k: v for k, v in _WCT_BASE.items() if k != cle}
        brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
            charge, _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
        )
        assert brouillon is None, cle
        assert motif == contenu_public.REFUS_PREUVE_ABSENTE, cle
    vide = _wct(consentement_recueilli_par="  ")
    assert contenu_public.verifier_consentement(vide) == contenu_public.REFUS_PREUVE_ABSENTE


def test_le_brouillon_porte_la_preuve_du_consentement():
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        _wct(), _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), seuil_confiance=0.8
    )
    assert motif is None
    assert brouillon["preuve_consentement"] == {
        "consentement_marketing": True, "recueilli_par": "etienne",
        "recueilli_le": "2026-09-28T18:05:00+00:00", "version_texte": "consentement-client-fr-CA-v1",
        "source": "wct_m4_travaux_termines", "wct_id": "wct-demo-1",
    }


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


def test_lead_v2_le_brouillon_garde_le_service_et_jamais_un_type_travaux_deduit():
    """PLAN T0.13-b : un WCT de lead v2 porte `service` à la place de `type_travaux`, aucun n'est déduit de l'autre."""
    charge = {k: v for k, v in _wct().items() if k != "type_travaux"} | {"service": "gouttieres"}
    brouillon, motif = contenu_public.preparer_brouillon_contenu_public(
        charge, _PHOTOS_UNE_PHOTO, BRAND_VALIDE, _DetecteurFixe(), 0.5)
    assert motif is None
    assert (brouillon["service"], brouillon["type_travaux"]) == ("gouttieres", None)


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
