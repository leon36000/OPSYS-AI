"""Fabriques de données fictives du sas de publication sociale (module à nom unique : `conftest` est ambigu)."""

from __future__ import annotations

from datetime import UTC, datetime

FICTIF = True
MAINTENANT = datetime(2026, 1, 5, 15, 0, 0, tzinfo=UTC)  # lundi 10 h à Toronto
HORODATAGE = "2026-01-05T15:00:00Z"
DEMAIN_10H = "2026-01-06T15:00:00Z"  # mardi 10 h à Toronto (UTC-5 en janvier)
TEXTE = "Une toiture bien entretenue protège la maison pendant de longues années."
CLE = "cle-publication-0123456789"
JETON = "jeton-fictif-pour-le-double-0123456789abcdef"
COMPTE = "page-horizon-fictive"


def media_photo(reference="photo-chantier-001", format_="jpeg", **plus):
    media = {
        "reference": reference,
        "type_media": "image",
        "format": format_,
        "sha256": "a" * 64,
        "octets": 500_000,
        "largeur": 1600,
        "hauteur": 1200,
        "duree_s": None,
        "alt": "Toiture neuve en bardeaux gris, vue de la rue",
        "origine": "photo_chantier",
        "ia_generee": False,
        "realiste": False,
        "moderation": "verifiee",
        "controle_ocr": "non_requis",
    }
    media.update(plus)
    return media


def media_video(reference="video-chantier-001", format_="mp4", **plus):
    media = {
        "reference": reference,
        "type_media": "video",
        "format": format_,
        "sha256": "b" * 64,
        "octets": 20_000_000,
        "largeur": 1080,
        "hauteur": 1920,
        "duree_s": 30,
        "alt": "",
        "origine": "photo_chantier",
        "ia_generee": False,
        "realiste": False,
        "moderation": "verifiee",
        "controle_ocr": "non_requis",
    }
    media.update(plus)
    return media


OPTIONS_TIKTOK = {"confidentialite": "SELF_ONLY", "commentaires": False, "duo": False, "stitch": False}


def publication(reseau="facebook", compte=COMPTE, **plus):
    """Une publication VALIDE pour `reseau` (chaque réseau a ses exigences de médias et d'options)."""
    base = {
        "reseau": reseau,
        "compte": compte,
        "texte": TEXTE,
        "titre": None,
        "medias": [media_photo()],
        "planifie_le": DEMAIN_10H,
        "divulgation": {"texte_ia": True, "media_synthetique_realiste": False, "contenu_commercial": False},
        "type_publication": "organique",
        "budget": None,
        "options": {},
    }
    if reseau == "gbp" or reseau == "instagram":
        base["medias"] = [media_photo()]
    elif reseau == "youtube":
        base["titre"] = "Pose d'une toiture neuve"
        base["medias"] = [media_video()]
    elif reseau == "tiktok":
        base["medias"] = [media_video()]
        base["options"] = dict(OPTIONS_TIKTOK)
    base.update(plus)
    return base


def annonce(reseau="facebook", **plus):
    return publication(
        reseau,
        type_publication="annonce_payante",
        budget={"montant_cents": 3000, "plafond_quotidien_cents": 1000, "duree_jours": 3},
        **plus,
    )
