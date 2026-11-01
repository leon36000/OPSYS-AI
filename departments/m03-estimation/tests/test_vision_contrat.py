"""Contrat du pipeline de vision (M3.3, M3.5) : photo avec provenance, sorties = candidats, rejet des sorties illégales.

AUCUN modèle réel : tout passe par des doubles déterministes (``vision_doubles``). Données fictives.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import _commun_vision as cv  # noqa: E402
from m3_estimation import verdicts, vision_contrat, vision_doubles  # noqa: E402
from m3_estimation.vision_contrat import Detection, MasqueRLE, ModeleVision  # noqa: E402

FICTIF = True
AUCUN = frozenset()


def _executer(photo=None, detecteur=None, objets=("objet_test",), politique_validee=False, qualifies=AUCUN):
    detecteur = detecteur or vision_doubles.DetecteurScripte({"synth-1": [cv.detection()]})
    return vision_contrat.executer(
        photo or cv.photo(), detecteur, list(objets), politique_validee=politique_validee, modeles_qualifies=qualifies
    )


def test_un_candidat_a_sa_mesure_calculee_par_le_code_depuis_la_geometrie_et_l_echelle():
    sortie, verdict = _executer()
    assert verdict is None and sortie["aucune_mesure_retenue"] is True
    [c] = sortie["candidats"]
    # 20 x 10 pixels à 0,05 m/px : 200 px x 0,0025 m2 = 0,5 m2 ; quantification (20+10) x 0,0025 = 0,075 m2
    assert (c["grandeur"], c["unite"], c["valeur"], c["pixels"]) == ("surface", "m2", "0.5000", 200)
    assert c["incertitude"]["absolue"] == "0.0750" and c["incertitude"]["calibree"] is False
    assert c["incertitude"]["complete"] is False  # incertitude d'échelle non déclarée : dit, pas devinée
    assert c["statut"] == "candidate_non_validee" and c["sans_echelle"] is False
    assert c["modele"]["identifiant"] == "vision.double-deterministe"
    assert sortie["recu"]["moteur"] == "m3.vision.pipeline"
    assert c["candidat_id"].startswith("cand-") and vision_contrat.empreinte_candidat(c) == c["empreinte"]


def test_l_incertitude_d_echelle_declaree_s_ajoute_a_celle_de_quantification():
    sortie, _ = _executer(photo=cv.photo(rel="0.02"))
    [c] = sortie["candidats"]
    # surface : 0,5 x 0,02 x 2 = 0,02 ; total 0,075 + 0,02
    assert c["incertitude"]["absolue"] == "0.0950" and c["incertitude"]["complete"] is True


def test_sans_masque_le_candidat_est_une_longueur_du_grand_cote_de_la_boite():
    d = vision_doubles.DetecteurScripte({"synth-1": [cv.detection(avec_masque=False, w=40, h=6)]})
    sortie, _ = _executer(detecteur=d)
    [c] = sortie["candidats"]
    assert (c["grandeur"], c["unite"], c["valeur"], c["masque"]) == ("longueur", "m", "2.0000", None)
    assert c["incertitude"]["absolue"] == "0.1000"  # +-1 pixel de chaque côté : 2 x 0,05


def test_une_photo_sans_echelle_n_a_aucune_dimension_seulement_des_pixels():
    sortie, _ = _executer(photo=cv.photo(sans_echelle=True))
    [c] = sortie["candidats"]
    assert c["sans_echelle"] is True and c["valeur"] is None and c["unite"] == "px2"
    assert c["valeur_pixels"] == "200.0000" and c["incertitude"]["absolue"] is None
    assert any("sans échelle" in h or "photo sans échelle" in h for h in c["hypotheses"])


def test_le_pipeline_est_deterministe_meme_entree_meme_sortie():
    a, _ = _executer()
    b, _ = _executer()
    assert a == b


def test_une_photo_reelle_est_refusee_tant_que_la_politique_photos_n_est_pas_validee():
    p = cv.photo(origine="client", fictif=False, consentement="cons-1")
    sortie, verdict = _executer(photo=p, politique_validee=False)
    assert sortie is None and verdict["code"] == "REJ-VISION-PROVENANCE-REFUSEE" and "politique" in verdict["detail"]


def test_une_photo_reelle_exige_un_consentement_meme_si_la_politique_est_validee():
    p = cv.photo(origine="client", fictif=False)
    _, verdict = _executer(photo=p, politique_validee=True)
    assert verdict["code"] == "REJ-VISION-PROVENANCE-REFUSEE" and "consentement" in verdict["detail"]


def test_une_photo_reelle_n_est_traitee_que_par_un_modele_qualifie_et_aucun_ne_l_est():
    p = cv.photo(origine="client", fictif=False, consentement="cons-1")
    detecteur = vision_doubles.DetecteurScripte({"synth-1": [cv.detection()]})
    sortie, verdict = _executer(photo=p, detecteur=detecteur, politique_validee=True, qualifies=AUCUN)
    assert sortie is None and verdict["code"] == "REJ-VISION-AUCUN-MODELE-QUALIFIE"
    assert detecteur.appels == [], "le détecteur n'a même pas été appelé"
    sortie, verdict = _executer(
        photo=p, detecteur=detecteur, politique_validee=True, qualifies=frozenset({"vision.double-deterministe"})
    )
    assert verdict is None and sortie["photo"]["fictif"] is False  # seul un modèle qualifié passe


def test_la_provenance_doit_etre_coherente_synthetique_fictif_reel_non_fictif():
    for p in (cv.photo(fictif=False), cv.photo(origine="client", fictif=True, consentement="c")):
        _, verdict = _executer(photo=p, politique_validee=True)
        assert verdict["code"] == "REJ-VISION-PROVENANCE-REFUSEE"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.pop("photo_id"),
        lambda p: p.update(photo_id="a b"),
        lambda p: p.update(empreinte_sha256="XYZ"),
        lambda p: p.update(empreinte_sha256="A" * 64),
        lambda p: p.update(largeur=0),
        lambda p: p.update(largeur=True),
        lambda p: p.update(largeur=20001),
        lambda p: p.update(hauteur=-3),
        lambda p: p.update(intrus=1),
        lambda p: p["echelle"].update(metres_par_pixel="0"),
        lambda p: p["echelle"].update(metres_par_pixel=0.05),
        lambda p: p["echelle"].update(source="devinee"),
        lambda p: p["echelle"].update(incertitude_relative="1.5"),
        lambda p: p["echelle"].update(metres_par_pixel="-0.05"),
        lambda p: p["echelle"].update(metres_par_pixel="1e-3"),
    ],
)
def test_photos_malformees_refusees(mutation):
    p = cv.photo()
    mutation(p)
    _, verdict = _executer(photo=p)
    assert verdict["code"] in ("REJ-VISION-PHOTO-INVALIDE", "REJ-VISION-PROVENANCE-REFUSEE")


@pytest.mark.parametrize(
    "provenance",
    [
        {"origine": "inconnue", "saisie_le": "2026-01-01T00:00:00+00:00", "fictif": True},
        {"origine": "jeu_synthetique", "saisie_le": "hier", "fictif": True},
        {"origine": "jeu_synthetique", "saisie_le": "2026-01-01T00:00:00", "fictif": True},
        {"origine": "jeu_synthetique", "saisie_le": "2026-01-01T00:00:00+00:00", "fictif": "oui"},
        {"origine": "jeu_synthetique", "saisie_le": "2026-01-01T00:00:00+00:00"},
        "texte",
    ],
)
def test_provenance_malformee_refusee(provenance):
    p = cv.photo()
    p["provenance"] = provenance
    _, verdict = _executer(photo=p)
    assert verdict["code"] == "REJ-VISION-PROVENANCE-REFUSEE"


@pytest.mark.parametrize(
    "objets", [[], ["Objet Test"], ["objet_test", "objet_test"], [f"o{i}x" for i in range(11)], "objet_test", [3]]
)
def test_objets_demandes_invalides_refuses(objets):
    _, verdict = vision_contrat.executer(
        cv.photo(), vision_doubles.DetecteurScripte({}), objets, politique_validee=False, modeles_qualifies=AUCUN
    )
    assert verdict["code"] == "REJ-VISION-PHOTO-INVALIDE"


@pytest.mark.parametrize(
    ("mode", "motif"),
    [
        ("hors_image", "BOITE-HORS-IMAGE"),
        ("confiance", "CONFIANCE-HORS-BORNES"),
        ("masque_hors_boite", "MASQUE-HORS-BOITE"),
        ("type", "SORTIE-TYPE"),
    ],
)
def test_les_sorties_illegales_d_un_detecteur_hostile_sont_rejetees_jamais_corrigees(mode, motif):
    sortie, verdict = _executer(detecteur=vision_doubles.DetecteurHostile(mode))
    assert verdict is None and sortie["candidats"] == []
    assert {r["motif"] for r in sortie["rejetes"]} == {motif}


def test_un_objet_injecte_ou_non_demande_est_rejete_et_n_est_jamais_une_instruction():
    sortie, _ = _executer(detecteur=vision_doubles.DetecteurHostile("objet_injecte"))
    assert sortie["candidats"] == [] and {r["motif"] for r in sortie["rejetes"]} == {"OBJET-NON-DEMANDE"}
    assert "ignore" not in str(sortie["candidats"])


def test_trop_de_detections_est_une_sortie_invalide_entiere():
    _, verdict = _executer(detecteur=vision_doubles.DetecteurHostile("trop_nombreuses"))
    assert verdict["code"] == "REJ-VISION-SORTIE-INVALIDE"


def test_un_detecteur_en_panne_ne_laisse_aucun_resultat_partiel_ni_le_message_d_erreur():
    sortie, verdict = _executer(detecteur=vision_doubles.DetecteurEnPanne())
    assert sortie is None and verdict["code"] == "REJ-VISION-DETECTEUR-INDISPONIBLE"
    assert "RuntimeError" in verdict["detail"] and "simulée" not in verdict["detail"]


def test_un_detecteur_sans_identite_valide_est_refuse():
    class Anonyme:
        modele = None

        def detecter(self, photo, objets):
            return []

    _, verdict = _executer(detecteur=Anonyme())
    assert verdict["code"] == "REJ-VISION-MODELE-INCONNU"

    class MauvaiseEmpreinte:
        modele = ModeleVision("vision.x", "1", "pas-un-sha")

        def detecter(self, photo, objets):
            return []

    _, verdict = _executer(detecteur=MauvaiseEmpreinte())
    assert verdict["code"] == "REJ-VISION-MODELE-INCONNU"


def test_deux_detections_identiques_ne_font_qu_un_candidat():
    d = vision_doubles.DetecteurScripte({"synth-1": [cv.detection(), cv.detection()]})
    sortie, _ = _executer(detecteur=d)
    assert len(sortie["candidats"]) == 1 and {"indice": None, "motif": "DOUBLON"} in sortie["rejetes"]


@pytest.mark.parametrize(
    "masque",
    [
        MasqueRLE(cv.LARGEUR, cv.HAUTEUR, ()),
        MasqueRLE(cv.LARGEUR, cv.HAUTEUR, ((0, 0),)),
        MasqueRLE(cv.LARGEUR, cv.HAUTEUR, ((10, 5), (12, 5))),  # chevauchement
        MasqueRLE(cv.LARGEUR, cv.HAUTEUR, ((20, 5), (10, 5))),  # non trié
        MasqueRLE(cv.LARGEUR, cv.HAUTEUR, ((cv.LARGEUR * cv.HAUTEUR - 1, 5),)),  # déborde de l'image
        MasqueRLE(cv.LARGEUR, cv.HAUTEUR, ((-1, 5),)),
        MasqueRLE(32, 24, ((0, 5),)),  # dimensions différentes de la photo
    ],
)
def test_masques_illegaux_rejetes(masque):
    d = vision_doubles.DetecteurScripte({"synth-1": [Detection("objet_test", (0, 0, 40, 40), masque, Decimal("0.9"))]})
    sortie, verdict = _executer(detecteur=d)
    assert verdict is None and sortie["candidats"] == [] and len(sortie["rejetes"]) == 1


def test_boite_et_masque_de_plusieurs_lignes_la_boite_englobante_est_exacte():
    m = MasqueRLE(10, 10, ((8, 5), (25, 3)))  # ligne 0 colonnes 8-9 puis ligne 1 ; plage 25-27 = ligne 2
    assert m.boite() == (0, 0, 9, 2) and m.pixels == 8
    assert cv.rectangle(3, 4, 5, 2).boite() == (3, 4, 7, 5)


def test_iou_par_fusion_de_plages_cas_connus():
    a, b = cv.rectangle(0, 0, 10, 10), cv.rectangle(5, 0, 10, 10)
    assert vision_contrat.iou(a, a) == Decimal(1)
    assert vision_contrat.iou(a, b) == Decimal(50) / Decimal(150)
    assert vision_contrat.iou(a, cv.rectangle(30, 30, 5, 5)) == Decimal(0)
    with pytest.raises(ValueError):
        vision_contrat.iou(a, MasqueRLE(8, 8, ((0, 3),)))


def test_les_codes_de_refus_du_pipeline_existent_au_catalogue_de_m3():
    for code in (
        "REJ-VISION-PHOTO-INVALIDE",
        "REJ-VISION-PROVENANCE-REFUSEE",
        "REJ-VISION-MODELE-INCONNU",
        "REJ-VISION-AUCUN-MODELE-QUALIFIE",
        "REJ-VISION-DETECTEUR-INDISPONIBLE",
        "REJ-VISION-SORTIE-INVALIDE",
    ):
        assert verdicts.est_verdict(code)
