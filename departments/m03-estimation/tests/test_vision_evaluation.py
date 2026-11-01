"""Harnais d'évaluation (M3.3, M3.5) : IoU et erreur de surface sur un jeu synthétique FICTIF. Ne qualifie jamais un
modèle."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import _commun_vision  # noqa: E402,F401
from m3_estimation import vision_contrat, vision_doubles, vision_evaluation  # noqa: E402
from m3_estimation.vision_contrat import Detection  # noqa: E402

FICTIF = True


class DetecteurParfait:
    """Rend, pour chaque photo, exactement le masque de la vérité terrain (double d'évaluation)."""

    def __init__(self, jeu):
        self.modele = vision_contrat.ModeleVision("vision.double-parfait", "1", None)
        self._verites = {e["photo"]["photo_id"]: e for e in jeu}

    def detecter(self, photo, objets):
        e = self._verites[photo.photo_id]
        return [Detection(e["objet"], e["boite_verite"], e["masque_verite"], Decimal("0.95"))]


def test_le_jeu_synthetique_est_deterministe_fictif_et_borne():
    a = vision_evaluation.jeu_synthetique_fictif(7, 12)
    b = vision_evaluation.jeu_synthetique_fictif(7, 12)
    assert a == b and len(a) == 12
    assert vision_evaluation.jeu_synthetique_fictif(8, 12) != a
    for e in a:
        assert e["photo"]["provenance"]["fictif"] is True and e["photo"]["provenance"]["origine"] == "jeu_synthetique"
    for mauvais in ((True, 5), (1, 0), (1, 1001), (1, "5")):
        with pytest.raises(ValueError):
            vision_evaluation.jeu_synthetique_fictif(*mauvais)
    with pytest.raises(ValueError):
        vision_evaluation.jeu_synthetique_fictif(1, 5, largeur=8)


def test_un_detecteur_parfait_a_un_iou_de_un_et_une_erreur_de_surface_nulle():
    jeu = vision_evaluation.jeu_synthetique_fictif(3, 20)
    rapport = vision_evaluation.evaluer(DetecteurParfait(jeu), jeu)
    m = rapport["metriques"]
    assert m["iou_moyen"] == "1.0000" and m["iou_minimum"] == "1.0000" and m["taux_detection"] == "1.0000"
    assert m["erreur_surface_relative_max"] == "0.0000" and m["detections_rejetees_par_le_pipeline"] == 0


def test_un_detecteur_decale_est_mesure_moins_bon_que_le_parfait():
    jeu = vision_evaluation.jeu_synthetique_fictif(3, 20)
    parfait = DetecteurParfait(jeu)
    base = vision_doubles.DetecteurScripte(
        {
            e["photo"]["photo_id"]: [Detection(e["objet"], e["boite_verite"], e["masque_verite"], Decimal("0.9"))]
            for e in jeu
        }
    )
    decale = vision_doubles.DetecteurPerturbe(base, decalage_px=3)
    r_parfait = vision_evaluation.evaluer(parfait, jeu)["metriques"]
    r_decale = vision_evaluation.evaluer(decale, jeu)["metriques"]
    assert Decimal(r_decale["iou_moyen"]) < Decimal(r_parfait["iou_moyen"]) and Decimal(r_decale["iou_moyen"]) > 0
    assert Decimal(r_decale["iou_minimum"]) < Decimal("1")


def test_un_detecteur_qui_ne_trouve_rien_a_un_iou_nul_et_un_taux_de_detection_nul():
    jeu = vision_evaluation.jeu_synthetique_fictif(3, 10)
    rapport = vision_evaluation.evaluer(vision_doubles.DetecteurScripte({}), jeu)
    m = rapport["metriques"]
    assert (m["iou_moyen"], m["taux_detection"], m["erreur_surface_relative_moyenne"]) == ("0.0000", "0.0000", None)


def test_un_detecteur_en_panne_compte_zero_sans_planter_le_harnais():
    jeu = vision_evaluation.jeu_synthetique_fictif(3, 5)
    rapport = vision_evaluation.evaluer(vision_doubles.DetecteurEnPanne(), jeu)
    assert (
        rapport["metriques"]["iou_moyen"] == "0.0000"
        and rapport["metriques"]["detections_rejetees_par_le_pipeline"] == 5
    )


def test_les_seuils_declares_donnent_atteints_ou_non_et_sans_seuil_le_rapport_ne_juge_pas():
    jeu = vision_evaluation.jeu_synthetique_fictif(3, 10)
    parfait = DetecteurParfait(jeu)
    assert vision_evaluation.evaluer(parfait, jeu)["seuils"] is None
    atteints = vision_evaluation.evaluer(parfait, jeu, {"iou_moyen_min": "0.9", "erreur_surface_relative_max": "0.01"})
    assert atteints["seuils"] == "atteints"
    vide = vision_evaluation.evaluer(vision_doubles.DetecteurScripte({}), jeu, {"iou_moyen_min": "0.5"})
    assert vide["seuils"] == "non_atteints"
    # sans détection, l'erreur de surface est inconnue : un seuil sur elle n'est jamais « atteint »
    assert (
        vision_evaluation.evaluer(vision_doubles.DetecteurScripte({}), jeu, {"erreur_surface_relative_max": "0.5"})[
            "seuils"
        ]
        == "non_atteints"
    )
    with pytest.raises(ValueError):
        vision_evaluation.evaluer(parfait, jeu, {"seuil_invente": "1"})
    with pytest.raises(ValueError):
        vision_evaluation.evaluer(parfait, [])


def test_le_rapport_est_toujours_fictif_non_qualifie_et_dit_ce_qu_il_ne_prouve_pas():
    jeu = vision_evaluation.jeu_synthetique_fictif(3, 6)
    rapport = vision_evaluation.evaluer(DetecteurParfait(jeu), jeu, {"iou_moyen_min": "0.5"})
    assert rapport["fictif"] is True and rapport["qualification"] == "non_qualifie"
    assert "jamais un modèle réel" in rapport["portee"] and len(rapport["empreinte"]) == 64
    # un rapport parfait n'ouvre aucune porte : la qualification est une décision du registre, pas du harnais
    assert rapport["seuils"] == "atteints" and rapport["qualification"] == "non_qualifie"


def test_le_rapport_est_deterministe():
    jeu = vision_evaluation.jeu_synthetique_fictif(11, 8)
    assert vision_evaluation.evaluer(DetecteurParfait(jeu), jeu) == vision_evaluation.evaluer(
        DetecteurParfait(jeu), jeu
    )
