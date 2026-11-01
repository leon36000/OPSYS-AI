"""Données FICTIVES communes aux tests de vision (M3.3, M3.5) : photo, masque rectangulaire, détection scriptée."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation.vision_contrat import Detection, MasqueRLE  # noqa: E402

FICTIF = True
SHA = "a" * 64
LARGEUR, HAUTEUR = 64, 48


def photo(
    photo_id="synth-1",
    echelle="0.0500",
    rel=None,
    origine="jeu_synthetique",
    fictif=True,
    sha=SHA,
    consentement=None,
    sans_echelle=False,
):
    p = {
        "photo_id": photo_id,
        "empreinte_sha256": sha,
        "largeur": LARGEUR,
        "hauteur": HAUTEUR,
        "provenance": {"origine": origine, "saisie_le": "2026-01-01T00:00:00+00:00", "fictif": fictif},
    }
    if consentement is not None:
        p["provenance"]["consentement_ref"] = consentement
    if not sans_echelle:
        p["echelle"] = {"metres_par_pixel": echelle, "source": "declaree"}
        if rel is not None:
            p["echelle"]["incertitude_relative"] = rel
    return p


def rectangle(x0, y0, w, h, largeur=LARGEUR, hauteur=HAUTEUR):
    """Masque RLE d'un rectangle plein, bornes ``[x0, x0+w[`` et ``[y0, y0+h[``."""
    return MasqueRLE(largeur, hauteur, tuple((y * largeur + x0, w) for y in range(y0, y0 + h)))


def detection(objet="objet_test", x0=10, y0=8, w=20, h=10, confiance="0.90", avec_masque=True):
    masque = rectangle(x0, y0, w, h) if avec_masque else None
    return Detection(objet, (x0, y0, x0 + w - 1, y0 + h - 1), masque, Decimal(confiance))
