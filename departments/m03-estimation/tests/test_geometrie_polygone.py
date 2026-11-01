"""Aire et périmètre d'un polygone (M3.7) par le moteur déterministe : lacet, projection locale, reçu, refus. Données
fictives.

Contrôle INDÉPENDANT : l'aire d'une cellule de graticule sur l'ellipsoïde GRS 80 a une forme fermée (latitude
authalique) ; le test la calcule en flottants (mathématique de la bibliothèque standard) et la compare au moteur en
Decimal.
"""

from __future__ import annotations

import copy
import math
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import geometrie_polygone as g  # noqa: E402
from m3_estimation import verdicts  # noqa: E402

FICTIF = True
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = 2 * _F - _F * _F
_E = math.sqrt(_E2)


def _q(phi):
    s = math.sin(phi)
    return (1 - _E2) * (s / (1 - _E2 * s * s) + (1 / (2 * _E)) * math.log((1 + _E * s) / (1 - _E * s)))


def _aire_cellule(lat1, lat2, lon1, lon2):
    """Aire exacte d'une cellule lat/lon sur GRS80 : (a²/2) Δλ (q(φ2) - q(φ1))."""
    return _A * _A / 2 * math.radians(lon2 - lon1) * (_q(math.radians(lat2)) - _q(math.radians(lat1)))


def _cellule(lat, lon, dlat, dlon):
    return [
        [f"{lat:.7f}", f"{lon:.7f}"],
        [f"{lat:.7f}", f"{lon + dlon:.7f}"],
        [f"{lat + dlat:.7f}", f"{lon + dlon:.7f}"],
        [f"{lat + dlat:.7f}", f"{lon:.7f}"],
    ]


def _geo(sommets, **plus):
    return g.calculer({"systeme": "geographique", "sommets": sommets, **plus})


def _plan(sommets, **plus):
    return g.calculer({"systeme": "plan_metrique", "sommets": sommets, **plus})


# ------------------------------------------------------------------------------------------ lacet en plan métrique
def test_rectangle_et_triangle_connus_en_plan_metrique():
    recu, verdict = _plan([["0", "0"], ["10", "0"], ["10", "5"], ["0", "5"]])
    assert verdict is None and recu["resultat"]["aire_m2"] == "50.00" and recu["resultat"]["perimetre_m"] == "30.00"
    recu, _ = _plan([["0", "0"], ["4", "0"], ["0", "3"]])
    assert recu["resultat"]["aire_m2"] == "6.00" and recu["resultat"]["perimetre_m"] == "12.00"  # 3-4-5


def test_l_orientation_et_le_sommet_de_depart_ne_changent_pas_le_resultat():
    base = [["0", "0"], ["10", "0"], ["10", "5"], ["4", "8"], ["0", "5"]]
    a, _ = _plan(base)
    b, _ = _plan(list(reversed(base)))
    c, _ = _plan(base[2:] + base[:2])
    assert a["resultat"] == b["resultat"] == c["resultat"]
    assert a["resultat"]["aire_m2"] == "65.00"  # 10 x 5 + triangle 10 x 3 / 2


def test_un_polygone_concave_en_L_est_exact():
    recu, verdict = _plan([["0", "0"], ["6", "0"], ["6", "2"], ["2", "2"], ["2", "6"], ["0", "6"]])
    assert verdict is None and recu["resultat"]["aire_m2"] == "20.00"


def test_l_anneau_ferme_explicitement_donne_le_meme_resultat():
    ouvert = [["0", "0"], ["10", "0"], ["10", "5"], ["0", "5"]]
    ferme = ouvert + [["0", "0"]]
    assert _plan(ouvert)[0]["resultat"] == _plan(ferme)[0]["resultat"]


def test_le_facteur_d_echelle_de_grille_n_est_jamais_suppose_egal_a_un():
    sans, _ = _plan([["0", "0"], ["10", "0"], ["10", "10"], ["0", "10"]])
    assert sans["resultat"]["facteur_echelle_grille_applique"] is None
    assert any("aucun facteur d'échelle de grille déclaré" in a for a in sans["avertissements"])
    avec, _ = _plan([["0", "0"], ["10", "0"], ["10", "10"], ["0", "10"]], facteur_echelle_grille="0.9999")
    assert avec["resultat"]["aire_m2"] == "100.02" and avec["resultat"]["perimetre_m"] == "40.00"  # 100 / 0,9999²
    assert avec["resultat"]["facteur_echelle_grille_applique"] == "1.00"  # arrondi d'affichage à 0,01
    # en coordonnées géographiques le facteur n'a pas de sens
    _, verdict = _geo(_cellule(45.5, -73.6, 0.001, 0.001), facteur_echelle_grille="0.9999")
    assert verdict["code"] == "REJ-GEO-ENTREE-INVALIDE"


# ------------------------------------------------------------------------------------------ projection géographique
@pytest.mark.parametrize(("lat", "dlat", "dlon"), [(45.5, 0.0018, 0.002), (46.8, 0.0045, 0.005), (55.0, 0.009, 0.02)])
def test_l_aire_geographique_concorde_avec_la_forme_fermee_de_l_ellipsoide(lat, dlat, dlon):
    recu, verdict = _geo(_cellule(lat, -73.6, dlat, dlon))
    assert verdict is None
    exact = _aire_cellule(lat, lat + dlat, -73.6, -73.6 + dlon)
    mesure = float(recu["resultat"]["aire_m2"])
    assert abs(mesure - exact) / exact < 1e-6, (mesure, exact)  # mesuré : de l'ordre de 1e-7 et moins


def test_une_projection_spherique_naive_serait_mesurablement_pire_que_l_ellipsoide():
    """Garde contre un retour au rayon unique : à 45,5 ° la sphère de 6 371 km s'écarte de plus de 0,2 % en aire."""
    exact = _aire_cellule(45.5, 45.5018, -73.6, -73.598)
    spherique = 6371008.8**2 * math.radians(0.002) * (math.sin(math.radians(45.5018)) - math.sin(math.radians(45.5)))
    recu, _ = _geo(_cellule(45.5, -73.6, 0.0018, 0.002))
    assert abs(spherique - exact) / exact > 2e-3
    assert abs(float(recu["resultat"]["aire_m2"]) - exact) / exact < 1e-6


def test_le_perimetre_geographique_est_la_somme_des_distances_planes():
    recu, _ = _geo(_cellule(45.5, -73.6, 0.0018, 0.002))
    assert 700 < float(recu["resultat"]["perimetre_m"]) < 725  # ~156 m x 2 + 200 m x 2 à 45,5 degrés


def test_le_meme_polygone_translate_en_longitude_garde_son_aire():
    a, _ = _geo(_cellule(46.0, -73.6, 0.001, 0.001))
    b, _ = _geo(_cellule(46.0, -71.2, 0.001, 0.001))
    assert abs(float(a["resultat"]["aire_m2"]) - float(b["resultat"]["aire_m2"])) < 0.01


# ------------------------------------------------------------------------------------------ incertitude et reçu
def test_incertitude_d_aire_d_ordre_un_seulement_si_la_source_en_declare_une():
    sans, _ = _plan([["0", "0"], ["10", "0"], ["10", "5"], ["0", "5"]])
    assert sans["resultat"]["incertitude_aire_m2"] is None  # jamais zéro
    assert any("incertitude de position non déclarée" in a for a in sans["avertissements"])
    avec, _ = _plan([["0", "0"], ["10", "0"], ["10", "5"], ["0", "5"]], incertitude_position_m="0.1")
    assert avec["resultat"]["incertitude_aire_m2"] == "3.00"  # périmètre 30 m x 0,1 m


def test_le_recu_se_verifie_se_rejoue_et_detecte_toute_retouche():
    recu, _ = _geo(_cellule(45.5, -73.6, 0.0018, 0.002), incertitude_position_m="0.5")
    assert g.verifier_recu(recu) == (True, "") and g.rejouer(recu) == (True, "")
    assert recu["moteur"] == g.MOTEUR and recu["mention"].endswith("pas un arpentage ni un avis professionnel.")
    for chemin in (("resultat", "aire_m2"), ("parametres", "etendue_max_m"), ("methode",)):
        retouche = copy.deepcopy(recu)
        cible = retouche
        for cle in chemin[:-1]:
            cible = cible[cle]
        cible[chemin[-1]] = "autre" if chemin[-1] != "etendue_max_m" else 9999
        assert g.verifier_recu(retouche)[0] is False, chemin
    retouche = copy.deepcopy(recu)
    retouche["entrees"]["sommets"][0][0] = "46.0000000"
    assert g.verifier_recu(retouche)[0] is False
    # un reçu dont le résultat a été retouché ET dont l'empreinte a été recalculée est attrapé par le rejeu
    habile = copy.deepcopy(recu)
    habile["resultat"]["aire_m2"] = "99999.00"
    corps = {k: v for k, v in habile.items() if k not in ("entrees", "empreinte")}
    habile["empreinte"] = g.journal_site.empreinte_canonique(corps)
    assert g.verifier_recu(habile) == (True, "") and g.rejouer(habile) == (False, "résultat différent")


def test_le_recu_est_deterministe_et_ne_contient_aucun_flottant():
    a, _ = _geo(_cellule(45.5, -73.6, 0.0018, 0.002))
    b, _ = _geo(_cellule(45.5, -73.6, 0.0018, 0.002))
    assert a == b

    def sans_flottant(x):
        if isinstance(x, dict):
            return all(sans_flottant(v) for v in x.values())
        if isinstance(x, list):
            return all(sans_flottant(v) for v in x)
        return not isinstance(x, float)

    assert sans_flottant(a)


def test_rejouer_refuse_un_recu_compact_ou_mal_forme():
    recu, _ = _plan([["0", "0"], ["10", "0"], ["10", "5"], ["0", "5"]])
    compact = {k: v for k, v in recu.items() if k != "entrees"}
    assert g.rejouer(compact) == (False, "reçu compact : entrées absentes")
    assert g.verifier_recu("texte")[0] is False and g.verifier_recu({"format": "autre"})[0] is False


# ------------------------------------------------------------------------------------------ refus
@pytest.mark.parametrize(
    ("sommets", "code"),
    [
        ([["0", "0"], ["10", "0"], ["0", "10"], ["10", "10"]], "REJ-GEO-AUTO-INTERSECTION"),  # nœud papillon
        (
            [["0", "0"], ["10", "0"], ["10", "10"], ["5", "-5"]],
            "REJ-GEO-AUTO-INTERSECTION",
        ),  # arête qui en coupe une autre
        (
            [["0", "0"], ["10", "0"], ["20", "0"], ["10", "0"], ["10", "10"]],
            "REJ-GEO-AUTO-INTERSECTION",
        ),  # sommet répété
        # pointe : le contour revient sur lui-même
        ([["0", "0"], ["10", "0"], ["10", "10"], ["10", "5"]], "REJ-GEO-AUTO-INTERSECTION"),
        ([["0", "0"], ["10", "0"], ["5", "0"]], "REJ-GEO-AUTO-INTERSECTION"),  # alignés : contour aller-retour
        (
            [["0", "0"], ["5", "0"], ["10", "0"]],
            "REJ-GEO-AUTO-INTERSECTION",
        ),  # alignés : aucune aire, contour aller-retour
        ([["0", "0"], ["1", "1"]], "REJ-GEO-POLYGONE-INVALIDE"),
        (
            [["0", "0"], ["0", "0"], ["1", "1"], ["2", "0"]],
            "REJ-GEO-POLYGONE-INVALIDE",
        ),  # sommets consécutifs identiques
        ([["0", "0"], ["1"]], "REJ-GEO-POLYGONE-INVALIDE"),
        ([["0", "0"], [1, 0], ["0", "1"]], "REJ-GEO-ENTREE-INVALIDE"),  # entier, pas un texte
        ([["0", "0"], [1.5, 0], ["0", "1"]], "REJ-GEO-ENTREE-INVALIDE"),  # flottant
        ([["0", "0"], ["1e3", "0"], ["0", "1"]], "REJ-GEO-ENTREE-INVALIDE"),
        ([["0", "0"], ["NaN", "0"], ["0", "1"]], "REJ-GEO-ENTREE-INVALIDE"),
        ("0,0 1,0 0,1", "REJ-GEO-POLYGONE-INVALIDE"),
    ],
)
def test_polygones_invalides_refuses_avec_un_code_du_catalogue(sommets, code):
    recu, verdict = _plan(sommets)
    assert recu is None and verdict["code"] == code and verdicts.est_verdict(code)


def test_deux_aretes_colineaires_qui_se_chevauchent_sont_une_auto_intersection():
    en_u = [["0", "0"], ["10", "0"], ["10", "5"], ["6", "5"], ["6", "0"], ["4", "0"], ["4", "5"], ["0", "5"]]
    recu, verdict = _plan(en_u)
    assert recu is None and verdict["code"] == "REJ-GEO-AUTO-INTERSECTION"


def test_trop_de_sommets_et_etendue_excessive_sont_refuses():
    # 501 sommets sur un cercle approximatif (carré à pas fin) : refusé avant tout calcul
    pts = [[str(i), str((i * i) % 97)] for i in range(501)]
    recu, verdict = _plan(pts)
    assert recu is None and verdict["code"] in ("REJ-GEO-POLYGONE-INVALIDE", "REJ-GEO-AUTO-INTERSECTION")
    recu, verdict = _plan([["0", "0"], ["2001", "0"], ["2001", "5"], ["0", "5"]])
    assert recu is None and verdict["code"] == "REJ-GEO-ETENDUE-EXCESSIVE"
    recu, verdict = _plan([["0", "0"], ["2000", "0"], ["2000", "5"], ["0", "5"]])
    assert verdict is None  # la borne est incluse


def test_hors_quebec_et_latitude_longitude_inversees_sont_refuses():
    recu, verdict = _geo([["-73.6", "45.5"], ["-73.598", "45.5"], ["-73.598", "45.5018"], ["-73.6", "45.5018"]])
    assert recu is None and verdict["code"] == "REJ-GEO-HORS-QUEBEC"
    recu, verdict = _geo(_cellule(48.8566, 2.3522, 0.001, 0.001))  # Paris
    assert recu is None and verdict["code"] == "REJ-GEO-HORS-QUEBEC"
    recu, verdict = _geo(_cellule(44.0, -73.6, 0.001, 0.001))  # au sud du rectangle de vraisemblance
    assert recu is None and verdict["code"] == "REJ-GEO-HORS-QUEBEC"


@pytest.mark.parametrize(
    "entrees",
    [
        None,
        [],
        {"systeme": "geographique"},
        {"sommets": []},
        {"systeme": "mercator", "sommets": []},
        {"systeme": "plan_metrique", "sommets": [["0", "0"], ["1", "0"], ["0", "1"]], "intrus": 1},
        {"systeme": "plan_metrique", "sommets": [["0", "0"], ["1", "0"], ["0", "1"]], "incertitude_position_m": "0"},
        {"systeme": "plan_metrique", "sommets": [["0", "0"], ["1", "0"], ["0", "1"]], "incertitude_position_m": 0.1},
        {"systeme": "plan_metrique", "sommets": [["0", "0"], ["1", "0"], ["0", "1"]], "facteur_echelle_grille": "-1"},
    ],
)
def test_entrees_mal_formees_refusees_sans_exception(entrees):
    recu, verdict = g.calculer(entrees)
    assert recu is None and verdict["code"] == "REJ-GEO-ENTREE-INVALIDE"


def test_aucun_import_reseau_horloge_ou_alea_dans_le_moteur():
    import ast

    arbre = ast.parse((_SRC / "m3_estimation" / "geometrie_polygone.py").read_text(encoding="utf-8"))
    importes = {n.names[0].name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import)}
    importes |= {
        n.module.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module and n.level == 0
    }
    assert not importes & {
        "socket",
        "urllib",
        "http",
        "requests",
        "random",
        "time",
        "datetime",
        "opsys",
        "math",
        "numpy",
    }
