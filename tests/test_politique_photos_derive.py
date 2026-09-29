"""Garde de dérive : M1 et M3 lisent la politique « photos » de la même façon (PLAN T4.4).

Un département ne lit pas le code d'un autre : M1 (`m1_front_office.photos`) et M3 (`m3_estimation.politique_photos`)
portent chacun leur lecture du marqueur `STATUT_VALIDATION` de `POLITIQUE-photos-non-contractuelles.md`. Ce test les
confronte, sur les mêmes textes et sur le document réel, pour qu'elles ne divergent pas : une demande de photos ne doit
jamais s'ouvrir chez M1 quand M3 garde sa collecte fermée, ni l'inverse."""

from __future__ import annotations

import pytest
from m1_front_office import outils as outils_m1
from m1_front_office import photos as photos_m1
from m3_estimation import outils as outils_m3
from m3_estimation import politique_photos as politique_m3

TEXTES = [
    None,
    "",
    "un document sans marqueur",
    "STATUT_VALIDATION: valide",
    "STATUT_VALIDATION:valide",
    "STATUT_VALIDATION: proposition",
    "STATUT_VALIDATION: VALIDE",
    "statut_validation: valide",
    "STATUT_VALIDATION: valide-en-attente",
    "> STATUT_VALIDATION: valide\n\n# Politique\n",
    "> PROPOSITION\n\nSTATUT_VALIDATION: valide\n\n# Politique\n",
    "STATUT_VALIDATION: valide\nSTATUT_VALIDATION: proposition",
    "STATUT_VALIDATION: valide\nSTATUT_VALIDATION: valide",
    42,
]


@pytest.mark.parametrize("texte", TEXTES, ids=lambda t: repr(t)[:40])
def test_m1_et_m3_lisent_le_meme_statut_et_ouvrent_ou_ferment_ensemble(texte):
    assert photos_m1.lire_statut_validation(texte) == politique_m3.lire_statut_validation(texte)
    assert photos_m1.politique_validee(texte) == politique_m3.politique_est_validee(texte)
    verdict_m1 = photos_m1.verifier_demande_autorisee(texte)
    verdict_m3 = politique_m3.verifier_collecte_photo_autorisee(texte)
    assert (verdict_m1 is None) == (verdict_m3 is None)
    if verdict_m1 is not None:
        assert verdict_m1["code"] == verdict_m3["code"] == "REJ-PHOTO-POLITIQUE-NON-VALIDEE"


def test_m1_et_m3_lisent_le_meme_document_et_en_tirent_la_meme_decision():
    assert outils_m1._CHEMIN_POLITIQUE_PHOTOS == outils_m3._CHEMIN_POLITIQUE_PHOTOS
    assert outils_m1._CHEMIN_POLITIQUE_PHOTOS.is_file()
    texte_m1, texte_m3 = outils_m1._politique_photos_texte(), outils_m3._politique_photos_texte()
    assert texte_m1 == texte_m3 != ""
    assert photos_m1.politique_validee(texte_m1) == politique_m3.politique_est_validee(texte_m3)
