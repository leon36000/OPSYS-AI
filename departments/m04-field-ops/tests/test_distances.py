"""Matrice de distances et de durées, palier 0 et port (PLAN T4.1-b, R15 §2 et §4).

Tout est fictif : coordonnées de test proches de Repentigny et de Joliette (fictif: true), paramètres
d'entreprise de test (les valeurs de départ de R15 §2, non sourcées).
"""

from __future__ import annotations

import ast
import json
import math
import os
import random
import socket
import subprocess
import sys
from decimal import ROUND_FLOOR, Decimal, localcontext
from pathlib import Path

import pytest
from m4_field_ops import digest, distances, encodage, pointage, verdicts

_SRC = Path(distances.__file__).resolve().parent
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "etalonnage_lanaudiere.json"

# Paramètres d'entreprise de TEST (R15 §2 : 1,3 ; 50 km/h ; 10 min).
PARAMS = {"facteur_detour_milliemes": 1300, "vitesse_moyenne_kmh": 50, "marge_par_trajet_secondes": 600}


def _point(identifiant, latitude, longitude):
    return {"id": identifiant, "latitude_microdeg": latitude, "longitude_microdeg": longitude}


# fictif: true
POINTS = [
    _point("b-repentigny", 45742000, -73450000),
    _point("a-joliette", 46020000, -73440000),
    _point("c-terrebonne", 45700000, -73640000),
]

# Valeurs épinglées de la matrice ci-dessus avec PARAMS (recoupées à la main et par pointage.distance_km).
METRES_ATTENDUS = [[0, 40199, 50449], [40199, 0, 20114], [50449, 20114, 0]]
SECONDES_ATTENDUES = [[0, 3495, 4233], [3495, 0, 2049], [4233, 2049, 0]]
EMPREINTE_ATTENDUE = "a182c47192f18d737a074af2ec06d9dfd29e999d962745e5960e4de1532823a2"


def _matrice(points=None, params=None):
    matrice, verdict = distances.matrice_palier0(POINTS if points is None else points, params or PARAMS)
    assert verdict is None
    return matrice


# ---------------------------------------------------------------------------
# Référence indépendante : Decimal à 90 chiffres, vecteur-corde 3D (autre formule, autre arithmétique)
# ---------------------------------------------------------------------------
_PI_DEC = Decimal(
    "3.14159265358979323846264338327950288419716939937510582097494459230781640628620899"
)


def _sin_dec(x):
    terme = somme = x
    k = 1
    while abs(terme) > Decimal(10) ** -85:
        terme = -terme * x * x / ((2 * k) * (2 * k + 1))
        somme += terme
        k += 1
    return somme


def _cos_dec(x):
    terme = somme = Decimal(1)
    k = 1
    while abs(terme) > Decimal(10) ** -85:
        terme = -terme * x * x / ((2 * k - 1) * (2 * k))
        somme += terme
        k += 1
    return somme


def _asin_dec(y):
    theta = Decimal(math.asin(float(y)))
    for _ in range(6):
        theta -= (_sin_dec(theta) - y) / _cos_dec(theta)
    return theta


def _radians_dec(microdegres):
    with localcontext() as contexte:
        contexte.prec = 90
        return Decimal(microdegres) * _PI_DEC / Decimal(180_000_000)


def _distance_reference(lat1, lon1, lat2, lon2):
    """Distance orthodromique exacte (mètres, Decimal) : 2·R·asin(corde / 2) entre vecteurs unitaires."""
    with localcontext() as contexte:
        contexte.prec = 90
        p1, l1, p2, l2 = (_radians_dec(v) for v in (lat1, lon1, lat2, lon2))
        v1 = (_cos_dec(p1) * _cos_dec(l1), _cos_dec(p1) * _sin_dec(l1), _sin_dec(p1))
        v2 = (_cos_dec(p2) * _cos_dec(l2), _cos_dec(p2) * _sin_dec(l2), _sin_dec(p2))
        corde = sum((a - b) ** 2 for a, b in zip(v1, v2, strict=True)).sqrt()
        return 2 * _asin_dec(corde / 2) * distances.RAYON_TERRESTRE_M


def _arrondi_demi_haut(valeur):
    with localcontext() as contexte:
        contexte.prec = 90
        return int((valeur + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# 1. Haversine entière
# ---------------------------------------------------------------------------
def test_valeurs_de_forme_fermee_a_l_equateur_et_au_meridien():
    """R × π/180 par degré, quart de méridien R × π/2, antipodes R × π : valeurs analytiques."""
    assert distances.distance_droite_m(0, 0, 1_000_000, 0) == 111195  # 111194,93
    assert distances.distance_droite_m(0, 0, 0, 1_000_000) == 111195
    assert distances.distance_droite_m(0, 0, 90_000_000, 0) == 10007543  # 10 007 543,40
    assert distances.distance_droite_m(0, 0, 0, 180_000_000) == 20015087  # 20 015 086,80
    assert distances.distance_droite_m(-90_000_000, 5, 90_000_000, 5) == 20015087


def test_le_resultat_est_un_entier_python_strict():
    valeur = distances.distance_droite_m(45742000, -73450000, 46020000, -73440000)
    assert type(valeur) is int
    assert valeur == 30922


def test_zero_pour_le_meme_point_et_symetrie_exacte():
    assert distances.distance_droite_m(45742000, -73450000, 45742000, -73450000) == 0
    generateur = random.Random(20260928)
    for _ in range(200):
        a = (generateur.randint(-90_000_000, 90_000_000), generateur.randint(-180_000_000, 180_000_000))
        b = (generateur.randint(-90_000_000, 90_000_000), generateur.randint(-180_000_000, 180_000_000))
        assert distances.distance_droite_m(*a, *b) == distances.distance_droite_m(*b, *a)


def test_egal_a_la_reference_decimal_independante_sur_des_paires_aleatoires():
    """L'entier obtenu est exactement l'arrondi de la valeur exacte (Decimal à 90 chiffres)."""
    generateur = random.Random(1)
    verifiees = 0
    for indice in range(120):
        if indice % 2:  # trajets régionaux, de quelques mètres à ~30 km
            lat1 = generateur.randint(45_000_000, 47_000_000)
            lon1 = generateur.randint(-75_000_000, -72_000_000)
            lat2 = lat1 + generateur.randint(-300_000, 300_000)
            lon2 = lon1 + generateur.randint(-300_000, 300_000)
        else:  # tout le globe, hors voisinage des antipodes (la référence Newton y est singulière)
            lat1 = generateur.randint(-89_000_000, 89_000_000)
            lon1 = generateur.randint(-180_000_000, 180_000_000)
            lat2 = generateur.randint(-89_000_000, 89_000_000)
            lon2 = generateur.randint(-180_000_000, 180_000_000)
        exact = _distance_reference(lat1, lon1, lat2, lon2)
        if exact > 19_000_000:
            continue
        assert distances.distance_droite_m(lat1, lon1, lat2, lon2) == _arrondi_demi_haut(exact)
        verifiees += 1
    assert verifiees >= 100


def test_erreur_de_calcul_sous_1e_20_metre_contre_les_formes_fermees():
    """Sur l'équateur et un méridien, la distance vaut R × angle ; l'erreur de la virgule fixe est infime,
    y compris à 1 µdeg des antipodes où l'arctangente reçoit un argument énorme."""
    borne = Decimal(10) ** -20
    cas = [(0, 0, 0, longitude) for longitude in (1, 1000, 45_000_000, 90_000_000, 179_999_000, 179_999_999)]
    cas += [(0, 5, latitude, 5) for latitude in (1, 777_777, 45_742_000, 89_999_999)]
    for lat1, lon1, lat2, lon2 in cas:
        with localcontext() as contexte:
            contexte.prec = 90
            exact = _radians_dec(max(abs(lon2 - lon1), abs(lat2 - lat1))) * distances.RAYON_TERRESTRE_M
            obtenu = Decimal(distances._orthodromie_fp(
                lat1, lon1, lat2, lon2,
                distances._cosinus_latitude(lat1), distances._cosinus_latitude(lat2),
            )) / Decimal(distances._ECHELLE)
            assert abs(obtenu - exact) < borne, (lat1, lon1, lat2, lon2)


def test_le_plus_court_chemin_autour_du_globe():
    """De −179,9° à +179,9° : 0,2° d'écart (≈ 22 km à l'équateur), pas 359,8°."""
    assert distances.distance_droite_m(0, -179_900_000, 0, 179_900_000) == distances.distance_droite_m(
        0, 179_900_000, 0, 179_700_000,
    )
    assert distances.distance_droite_m(0, -179_900_000, 0, 179_900_000) == 22239  # 0,2° × 111 194,93


def test_recoupement_avec_le_haversine_flottant_de_pointage():
    """Les deux modules s'accordent au mètre près (même sphère de 6371 km)."""
    generateur = random.Random(7)
    for _ in range(100):
        lat1 = generateur.randint(45_000_000, 47_000_000)
        lon1 = generateur.randint(-75_000_000, -72_000_000)
        lat2 = generateur.randint(45_000_000, 47_000_000)
        lon2 = generateur.randint(-75_000_000, -72_000_000)
        flottant_m = pointage.distance_km(lat1 / 1e6, lon1 / 1e6, lat2 / 1e6, lon2 / 1e6) * 1000
        assert abs(distances.distance_droite_m(lat1, lon1, lat2, lon2) - flottant_m) <= 1.0


def test_pi_de_la_constante_est_celui_de_la_formule_de_machin():
    echelle = 10**60

    def arctan_inverse(n):
        terme = somme = echelle // n
        k = 1
        while terme:
            terme //= n * n
            somme += (-1) ** k * (terme // (2 * k + 1))
            k += 1
        return somme

    pi_60 = 16 * arctan_inverse(5) - 4 * arctan_inverse(239)
    assert (pi_60 + 5 * 10**19) // 10**20 == distances._PI


def test_sin_cos_atan_en_virgule_fixe_contre_math():
    echelle = distances._ECHELLE
    for k in range(0, 32):
        x = k * echelle // 20
        reel = k / 20
        assert abs(distances._sin(x) / echelle - math.sin(reel)) < 1e-15
        assert abs(distances._cos(x) / echelle - math.cos(reel)) < 1e-15
        assert abs(distances._atan(x) / echelle - math.atan(reel)) < 1e-15
    for reel in (1.5, 3.0, 40.0, 1e6):
        x = int(Decimal(reel) * echelle)
        assert abs(distances._atan(x) / echelle - math.atan(reel)) < 1e-15
    assert 0 <= distances._cos(distances._PI // 2) < 10**3  # jamais négatif, ~ 0 à 10**-37 près


@pytest.mark.parametrize("coordonnees", [
    (45.7, 0, 0, 0),
    (True, 0, 0, 0),
    (0, 0, "45", 0),
    (90_000_001, 0, 0, 0),
    (0, -180_000_001, 0, 0),
])
def test_distance_droite_refuse_les_coordonnees_non_entieres_ou_hors_plage(coordonnees):
    with pytest.raises(ValueError):
        distances.distance_droite_m(*coordonnees)


# ---------------------------------------------------------------------------
# 2. Paramètres d'entreprise : obligatoires, bornés, jamais de valeur par défaut
# ---------------------------------------------------------------------------
def test_parametres_valides_sont_rendus_tels_quels():
    valeurs, verdict = distances.valider_parametres(dict(PARAMS))
    assert verdict is None
    assert valeurs == PARAMS


def test_parametres_absents_disent_quoi_fournir_avec_les_bornes():
    matrice, verdict = distances.matrice_palier0(POINTS, {})
    assert matrice is None
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    assert verdicts.est_verdict(verdict["code"])
    for cle, (minimum, maximum) in distances.BORNES_PARAMETRES.items():
        assert f"{cle} manquant" in verdict["detail"]
        assert f"entre {minimum} et {maximum}" in verdict["detail"]


@pytest.mark.parametrize("cle", sorted(PARAMS))
def test_un_seul_parametre_absent_ou_nul_nomme_seulement_celui_la(cle):
    for retire in ({k: v for k, v in PARAMS.items() if k != cle}, {**PARAMS, cle: None}):
        matrice, verdict = distances.matrice_palier0(POINTS, retire)
        assert matrice is None
        assert verdict["code"] == "REJ-CHAMP-MANQUANT"
        assert f"{cle} manquant" in verdict["detail"]
        assert sum("manquant" in morceau for morceau in verdict["detail"].split(" ; ")) == 1


@pytest.mark.parametrize(("cle", "valeur"), [
    ("facteur_detour_milliemes", 999),
    ("facteur_detour_milliemes", 3001),
    ("facteur_detour_milliemes", 0),
    ("facteur_detour_milliemes", -1300),
    ("vitesse_moyenne_kmh", 9),
    ("vitesse_moyenne_kmh", 111),
    ("vitesse_moyenne_kmh", 0),
    ("marge_par_trajet_secondes", -1),
    ("marge_par_trajet_secondes", 3601),
])
def test_parametres_hors_bornes_sont_refuses_avec_les_bornes(cle, valeur):
    matrice, verdict = distances.matrice_palier0(POINTS, {**PARAMS, cle: valeur})
    assert matrice is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    minimum, maximum = distances.BORNES_PARAMETRES[cle]
    assert cle in verdict["detail"]
    assert f"entre {minimum} et {maximum}" in verdict["detail"]


@pytest.mark.parametrize(("cle", "valeur"), [
    ("facteur_detour_milliemes", 1.3),
    ("facteur_detour_milliemes", "1300"),
    ("vitesse_moyenne_kmh", 50.0),
    ("vitesse_moyenne_kmh", True),
    ("marge_par_trajet_secondes", 600.5),
    ("marge_par_trajet_secondes", [600]),
])
def test_parametres_non_entiers_sont_refuses(cle, valeur):
    matrice, verdict = distances.matrice_palier0(POINTS, {**PARAMS, cle: valeur})
    assert matrice is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "entier requis" in verdict["detail"]


def test_bornes_incluses_sont_acceptees():
    for cle, (minimum, maximum) in distances.BORNES_PARAMETRES.items():
        for valeur in (minimum, maximum):
            matrice, verdict = distances.matrice_palier0(POINTS, {**PARAMS, cle: valeur})
            assert verdict is None
            assert matrice["parametres"][cle] == valeur


def test_cle_inconnue_ou_parametres_non_objet_sont_refuses():
    matrice, verdict = distances.matrice_palier0(POINTS, {**PARAMS, "vitesse": 50})
    assert matrice is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "vitesse" in verdict["detail"]
    for invalide in (None, [], "1300;50;600", 1300):
        matrice, verdict = distances.matrice_palier0(POINTS, invalide)
        assert matrice is None
        assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


# ---------------------------------------------------------------------------
# 3. Points
# ---------------------------------------------------------------------------
def test_points_sont_rendus_tries_par_identifiant_sans_toucher_l_entree():
    entree = [dict(p) for p in POINTS]
    tries, verdict = distances.valider_points(entree)
    assert verdict is None
    assert [p["id"] for p in tries] == ["a-joliette", "b-repentigny", "c-terrebonne"]
    assert entree == POINTS
    assert tries[0] is not entree[1]


@pytest.mark.parametrize(("points", "code"), [
    ([], "REJ-CHAMP-VIDE"),
    (None, "REJ-CONTRAT-INVALIDE"),
    ({"id": "x"}, "REJ-CONTRAT-INVALIDE"),
    (["a-joliette"], "REJ-CONTRAT-INVALIDE"),
    ([_point("x", 45742000, -73450000), _point("x", 45700000, -73640000)], "REJ-CONTRAT-INVALIDE"),
    ([_point("", 45742000, -73450000)], "REJ-CONTRAT-INVALIDE"),
    ([_point(7, 45742000, -73450000)], "REJ-CONTRAT-INVALIDE"),
    ([_point("x", 45.742, -73.45)], "REJ-CONTRAT-INVALIDE"),
    ([_point("x", True, -73450000)], "REJ-CONTRAT-INVALIDE"),
    ([_point("x", 90_000_001, 0)], "REJ-CONTRAT-INVALIDE"),
    ([_point("x", 0, 180_000_001)], "REJ-CONTRAT-INVALIDE"),
    ([_point("x", 0, 0)], "REJ-CHAMP-MANQUANT"),
    ([{"id": "x", "latitude_microdeg": 45742000}], "REJ-CHAMP-MANQUANT"),
    ([{"id": "x", "latitude_microdeg": 45742000, "longitude_microdeg": None}], "REJ-CHAMP-MANQUANT"),
    ([{"id": "x", "latitude_microdeg": 45742000, "longitude_microdeg": -73450000, "adresse": "1 rue X"}],
     "REJ-CONTRAT-INVALIDE"),
])
def test_points_invalides_sont_refuses_par_un_verdict_du_catalogue(points, code):
    tries, verdict = distances.valider_points(points)
    assert tries is None
    assert verdict["code"] == code
    assert verdicts.est_verdict(code)
    assert verdict["detail"] != ""


def test_trop_de_points_est_refuse_et_la_limite_est_acceptee():
    limite = [_point(f"p{i:03d}", 45_000_000 + i, -73_000_000) for i in range(distances.MAX_POINTS)]
    tries, verdict = distances.valider_points(limite)
    assert verdict is None
    assert len(tries) == distances.MAX_POINTS
    tries, verdict = distances.valider_points([*limite, _point("zzz", 45_100_000, -73_000_000)])
    assert tries is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert str(distances.MAX_POINTS) in verdict["detail"]


def test_les_verdicts_ne_recopient_jamais_une_coordonnee():
    """Loi 25 : un verdict nomme le point par son identifiant opaque, jamais par sa position."""
    secret_lat, secret_lon = 45123457, -73987651
    cas = [
        [_point("chantier-9", secret_lat, secret_lon), _point("chantier-9", secret_lat, secret_lon)],
        [{"id": "chantier-9", "latitude_microdeg": secret_lat, "longitude_microdeg": secret_lon, "adresse": "x"}],
        [_point("chantier-9", secret_lat, 999_999_999)],
        [_point("chantier-9", secret_lat + 0.5, secret_lon)],
    ]
    for points in cas:
        _, verdict = distances.valider_points(points)
        assert verdict is not None
        assert "chantier-9" in verdict["detail"]
        assert str(secret_lat) not in verdict["detail"]
        assert str(secret_lon) not in verdict["detail"]


# ---------------------------------------------------------------------------
# 4. Matrice du palier 0
# ---------------------------------------------------------------------------
def test_matrice_epinglee_recoupee_a_la_main():
    """Repentigny–Joliette : 30 922 m en ligne droite ; × 1,3 = 40 198,6 -> 40 199 m ;
    40 199 m × 3,6 / 50 km/h = 2 894,3 s -> 2 895 s ; + 600 s de marge = 3 495 s."""
    matrice = _matrice()
    assert matrice["ids"] == ["a-joliette", "b-repentigny", "c-terrebonne"]
    assert matrice["metres"] == METRES_ATTENDUS
    assert matrice["secondes"] == SECONDES_ATTENDUES
    assert matrice["metres"][0][1] == (distances.distance_droite_m(46020000, -73440000, 45742000, -73450000)
                                       * 1300 + 500) // 1000
    assert matrice["secondes"][0][1] == math.ceil(40199 * 3.6 / 50) + 600
    assert matrice["empreinte"] == EMPREINTE_ATTENDUE


def test_mode_distance_et_mode_bride_sont_exposes():
    matrice = _matrice()
    assert matrice["mode_distance"] == "haversine_detour" == distances.MODE_HAVERSINE_DETOUR
    assert matrice["mode_bride"] is True
    assert matrice["repli"] is None
    assert matrice["version"] == distances.VERSION_MATRICE == "matrice-distances-v1"
    assert matrice["parametres"] == {
        "algorithme": "haversine-entier-v1",
        "rayon_terrestre_m": 6_371_000,
        **PARAMS,
    }


def test_proprietes_diagonale_nulle_symetrie_entiers_positifs():
    generateur = random.Random(42)
    points = [
        _point(f"p{i:02d}", generateur.randint(45_000_000, 47_000_000), generateur.randint(-75_000_000, -72_000_000))
        for i in range(25)
    ]
    matrice = _matrice(points)
    n = len(points)
    assert len(matrice["metres"]) == len(matrice["secondes"]) == n
    for i in range(n):
        assert len(matrice["metres"][i]) == len(matrice["secondes"][i]) == n
        assert matrice["metres"][i][i] == 0
        assert matrice["secondes"][i][i] == 0
        for j in range(n):
            assert matrice["metres"][i][j] == matrice["metres"][j][i]
            assert matrice["secondes"][i][j] == matrice["secondes"][j][i]
            for table in (matrice["metres"], matrice["secondes"]):
                assert type(table[i][j]) is int
                assert table[i][j] >= 0
            if i != j:
                assert matrice["secondes"][i][j] >= PARAMS["marge_par_trajet_secondes"]


def test_inegalite_triangulaire_en_ligne_droite_avant_marge():
    """La ligne droite est une vraie distance : d(a,c) <= d(a,b) + d(b,c), à 1 m d'arrondi par arête près."""
    generateur = random.Random(5)
    for _ in range(100):
        a, b, c = ((generateur.randint(45_000_000, 47_000_000), generateur.randint(-75_000_000, -72_000_000))
                   for _ in range(3))
        assert distances.distance_droite_m(*a, *c) <= (
            distances.distance_droite_m(*a, *b) + distances.distance_droite_m(*b, *c) + 1
        )


def test_deux_chantiers_au_meme_endroit_coutent_la_marge_sans_distance():
    points = [_point("a", 45742000, -73450000), _point("b", 45742000, -73450000)]
    matrice = _matrice(points)
    assert matrice["metres"] == [[0, 0], [0, 0]]
    assert matrice["secondes"] == [[0, 600], [600, 0]]


def test_un_seul_point_donne_une_matrice_nulle():
    matrice = _matrice([_point("depot", 45742000, -73450000)])
    assert matrice["ids"] == ["depot"]
    assert matrice["metres"] == [[0]]
    assert matrice["secondes"] == [[0]]
    assert distances.verifier_matrice(matrice) == (True, "")


def test_la_duree_est_arrondie_au_plafond_jamais_sous_estimee():
    """route 1 m à 50 km/h = 0,072 s -> 1 s ; la marge s'y ajoute."""
    points = [_point("a", 45742000, -73450000), _point("b", 45742009, -73450000)]  # 9 µdeg ≈ 1,0 m
    matrice = _matrice(points, {**PARAMS, "facteur_detour_milliemes": 1000, "marge_par_trajet_secondes": 0})
    assert matrice["metres"][0][1] == 1
    assert matrice["secondes"][0][1] == 1


def test_le_facteur_de_detour_et_la_vitesse_agissent_comme_documente():
    base = _matrice()
    double_detour = _matrice(params={**PARAMS, "facteur_detour_milliemes": 2000})
    assert double_detour["metres"][0][1] == (30922 * 2000 + 500) // 1000 == 61844
    assert double_detour["metres"][0][1] > base["metres"][0][1]
    vitesse_double = _matrice(params={**PARAMS, "vitesse_moyenne_kmh": 100})
    assert vitesse_double["metres"] == base["metres"]
    assert vitesse_double["secondes"][0][1] == math.ceil(40199 * 3.6 / 100) + 600


def test_l_ordre_des_points_en_entree_ne_change_rien():
    reference = _matrice()
    generateur = random.Random(3)
    for _ in range(10):
        melange = [dict(p) for p in POINTS]
        generateur.shuffle(melange)
        assert _matrice(melange) == reference


def test_meme_entree_meme_empreinte_et_empreinte_hexadecimale_sha256():
    premiere = _matrice()
    seconde = _matrice([dict(p) for p in reversed(POINTS)], dict(PARAMS))
    assert premiere["empreinte"] == seconde["empreinte"] == EMPREINTE_ATTENDUE
    assert len(premiere["empreinte"]) == 64
    assert set(premiere["empreinte"]) <= set("0123456789abcdef")


@pytest.mark.parametrize("cle", sorted(PARAMS))
def test_l_empreinte_change_si_un_parametre_change(cle):
    base = _matrice()["empreinte"]
    for delta in (-1, 1):
        modifie = _matrice(params={**PARAMS, cle: PARAMS[cle] + delta})
        assert modifie["empreinte"] != base


def test_l_empreinte_change_si_un_point_ou_un_identifiant_change():
    base = _matrice()["empreinte"]
    deplace = [dict(p) for p in POINTS]
    deplace[0]["latitude_microdeg"] += 1000
    assert _matrice(deplace)["empreinte"] != base
    renomme = [dict(p) for p in POINTS]
    renomme[0]["id"] = "b-repentigny-2"
    assert _matrice(renomme)["empreinte"] != base


def test_aucun_flottant_nulle_part_dans_la_matrice_et_elle_survit_au_json():
    matrice = _matrice()

    def parcourir(valeur):
        if isinstance(valeur, dict):
            for cle, contenu in valeur.items():
                assert isinstance(cle, str)
                parcourir(contenu)
        elif isinstance(valeur, list):
            for contenu in valeur:
                parcourir(contenu)
        else:
            assert not isinstance(valeur, float)
            assert valeur is None or isinstance(valeur, (str, bool, int))

    parcourir(matrice)
    revenu = json.loads(json.dumps(matrice, sort_keys=True))
    assert revenu == matrice
    assert distances.verifier_matrice(revenu) == (True, "")


def test_meme_empreinte_dans_des_interpreteurs_aux_graines_de_hachage_differentes():
    """Reproductible d'un processus à l'autre (PYTHONHASHSEED 1, 2, 3 : R15 §1) : même octets, même empreinte."""
    programme = (
        "import json;"
        "from m4_field_ops import distances as d;"
        "pts=[{'id':'b-repentigny','latitude_microdeg':45742000,'longitude_microdeg':-73450000},"
        "{'id':'a-joliette','latitude_microdeg':46020000,'longitude_microdeg':-73440000},"
        "{'id':'c-terrebonne','latitude_microdeg':45700000,'longitude_microdeg':-73640000}];"
        "m,v=d.matrice_palier0(pts,{'facteur_detour_milliemes':1300,'vitesse_moyenne_kmh':50,"
        "'marge_par_trajet_secondes':600});"
        "print(json.dumps(m,sort_keys=True))"
    )
    sorties = set()
    for graine in ("1", "2", "3"):
        environnement = {**os.environ, "PYTHONHASHSEED": graine, "PYTHONPATH": os.pathsep.join(sys.path)}
        resultat = subprocess.run(
            [sys.executable, "-c", programme], capture_output=True, text=True, env=environnement, check=True,
        )
        sorties.add(resultat.stdout)
    assert len(sorties) == 1
    assert json.loads(sorties.pop()) == _matrice()


# ---------------------------------------------------------------------------
# 5. Vérification d'une matrice reçue
# ---------------------------------------------------------------------------
def test_verifier_matrice_accepte_une_matrice_intacte():
    assert distances.verifier_matrice(_matrice()) == (True, "")


def test_verifier_matrice_refuse_toute_falsification():
    def alterations():
        yield "metres", lambda m: m["metres"][0].__setitem__(1, m["metres"][0][1] + 1)
        yield "secondes", lambda m: m["secondes"][1].__setitem__(2, 0)
        yield "parametres", lambda m: m["parametres"].__setitem__("vitesse_moyenne_kmh", 60)
        yield "ids", lambda m: m.__setitem__("ids", ["a-joliette", "b-repentigny", "d-x"])
        yield "empreinte", lambda m: m.__setitem__("empreinte", "0" * 64)
        yield "mode", lambda m: m.__setitem__("mode_distance", "osrm_table")
        yield "bride", lambda m: m.__setitem__("mode_bride", False)
        yield "repli", lambda m: m.__setitem__("repli", {"depuis": "x", "code": "y", "detail": "z"})

    for nom, alterer in alterations():
        matrice = json.loads(json.dumps(_matrice()))
        alterer(matrice)
        ok, message = distances.verifier_matrice(matrice)
        assert ok is False, nom
        assert message.startswith("matrice"), nom


def _forger(matrice, **changements):
    """Recalcule l'empreinte après un changement : on teste alors la structure, pas seulement le hachage."""
    forge = {**matrice, **changements}
    forge["empreinte"] = encodage.empreinte({k: v for k, v in forge.items() if k != "empreinte"})
    return forge


@pytest.mark.parametrize("changement", [
    {"version": "matrice-distances-v0"},
    {"ids": ["b", "a", "c"]},
    {"ids": ["a", "a", "b"]},
    {"ids": []},
    {"metres": [[0, 1, 2], [1, 0, 3]]},
    {"metres": [[0, 1.5, 2], [1, 0, 3], [2, 3, 0]]},
    {"metres": [[0, 1, 2], [1, 5, 3], [2, 3, 0]]},
    {"secondes": [[0, -1, 2], [-1, 0, 3], [2, 3, 0]]},
    {"secondes": [[0, True, 2], [1, 0, 3], [2, 3, 0]]},
    {"mode_bride": "oui"},
    {"parametres": {"vitesse_moyenne_kmh": 50.0}},
    {"parametres": []},
    {"repli": {"depuis": "x"}},
])
def test_verifier_matrice_refuse_une_structure_invalide_meme_avec_une_empreinte_recalculee(changement):
    base = _matrice()
    trois = {**base, "ids": ["a", "b", "c"]}
    ok, _ = distances.verifier_matrice(_forger(trois, **changement))
    assert ok is False


def test_verifier_matrice_ne_leve_jamais():
    for objet in (None, [], "matrice", 3, {}, {"version": distances.VERSION_MATRICE}):
        ok, message = distances.verifier_matrice(objet)
        assert ok is False
        assert message != ""


# ---------------------------------------------------------------------------
# 6. Port FournisseurMatrice et repli explicite
# ---------------------------------------------------------------------------
class _Fournisseur:
    """Fournisseur factice : matrices asymétriques déterministes, ou un verdict, ou une exception."""

    def __init__(self, verdict=None, exception=None, trajets=None, descripteur=None):
        self.verdict = verdict
        self.exception = exception
        self.trajets_forces = trajets
        self.descripteur_force = descripteur
        self.appels = []

    def descripteur(self):
        if self.descripteur_force is not None:
            return self.descripteur_force
        return {"mode_distance": "fictif_table", "fournisseur": "fictif", "version_donnees": "jeu-1"}

    def trajets(self, points):
        self.appels.append([p["id"] for p in points])
        if self.exception is not None:
            raise self.exception
        if self.verdict is not None:
            return None, self.verdict
        if self.trajets_forces is not None:
            return self.trajets_forces, None
        n = len(points)
        metres = [[0 if i == j else 1000 * (i + 1) + 10 * j for j in range(n)] for i in range(n)]
        secondes = [[0 if i == j else 60 * (i + 2) + j for j in range(n)] for i in range(n)]
        return {"metres": metres, "secondes": secondes}, None


def test_le_port_est_reconnu_par_isinstance():
    assert isinstance(_Fournisseur(), distances.FournisseurMatrice)
    assert not isinstance(object(), distances.FournisseurMatrice)


def test_sans_fournisseur_aucune_entree_sortie_reseau(monkeypatch):
    """Le palier 0 et le palier 1 « absent » ne touchent jamais au réseau."""
    def interdit(*args, **kwargs):
        raise AssertionError("accès réseau interdit")

    monkeypatch.setattr(socket.socket, "connect", interdit)
    monkeypatch.setattr(socket, "create_connection", interdit)
    monkeypatch.setattr(socket, "getaddrinfo", interdit)
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS)
    assert verdict is None
    assert matrice == _matrice()


def test_fournisseur_qui_repond_donne_une_matrice_routiere_non_bridee():
    fournisseur = _Fournisseur()
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, fournisseur)
    assert verdict is None
    assert fournisseur.appels == [["a-joliette", "b-repentigny", "c-terrebonne"]]
    assert matrice["mode_distance"] == "fictif_table"
    assert matrice["mode_bride"] is False
    assert matrice["repli"] is None
    assert matrice["metres"][0] == [0, 1010, 1020]
    assert matrice["metres"][1] == [2000, 0, 2020]  # asymétrique : gardée telle quelle
    # marge de 600 s sur chaque trajet entre points distincts, diagonale nulle
    assert matrice["secondes"][0] == [0, 120 + 1 + 600, 120 + 2 + 600]
    assert matrice["secondes"][1] == [180 + 0 + 600, 0, 180 + 2 + 600]
    assert matrice["parametres"] == {
        "marge_par_trajet_secondes": 600,
        "fournisseur": {"fournisseur": "fictif", "version_donnees": "jeu-1"},
    }
    assert distances.verifier_matrice(matrice) == (True, "")


def test_l_empreinte_d_une_matrice_routiere_couvre_les_donnees_et_la_marge():
    base, _ = distances.obtenir_matrice(POINTS, PARAMS, _Fournisseur())
    autre_donnees, _ = distances.obtenir_matrice(
        POINTS, PARAMS,
        _Fournisseur(descripteur={
            "mode_distance": "fictif_table", "fournisseur": "fictif", "version_donnees": "jeu-2",
        }),
    )
    autre_marge, _ = distances.obtenir_matrice(POINTS, {**PARAMS, "marge_par_trajet_secondes": 601}, _Fournisseur())
    palier0 = _matrice()
    assert len({base["empreinte"], autre_donnees["empreinte"], autre_marge["empreinte"], palier0["empreinte"]}) == 4


def test_parametres_valides_meme_avec_un_fournisseur_avant_tout_appel():
    fournisseur = _Fournisseur()
    matrice, verdict = distances.obtenir_matrice(POINTS, {}, fournisseur)
    assert matrice is None
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    matrice, verdict = distances.obtenir_matrice([], PARAMS, fournisseur)
    assert matrice is None
    assert verdict["code"] == "REJ-CHAMP-VIDE"
    assert fournisseur.appels == []


@pytest.mark.parametrize("code", [distances.CODE_FOURNISSEUR_INDISPONIBLE, distances.CODE_REPONSE_INVALIDE])
def test_panne_du_fournisseur_replie_sur_le_palier_0_avec_une_marque_explicite(code):
    verdict_panne = distances.verdict_matrice(code, "sidecar hors service (test)")
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, _Fournisseur(verdict=verdict_panne))
    assert verdict is None
    assert matrice["mode_distance"] == "haversine_detour"
    assert matrice["mode_bride"] is True
    assert matrice["repli"] == {"depuis": "fictif_table", "code": code, "detail": "sidecar hors service (test)"}
    assert matrice["metres"] == METRES_ATTENDUS  # les trajets sont ceux du palier 0
    assert matrice["secondes"] == SECONDES_ATTENDUES
    assert matrice["empreinte"] != EMPREINTE_ATTENDUE  # jamais confondu avec un palier 0 voulu
    assert distances.verifier_matrice(matrice) == (True, "")


def test_exception_du_fournisseur_replie_aussi_avec_le_nom_de_l_erreur():
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, _Fournisseur(exception=RuntimeError("boum secret")))
    assert verdict is None
    assert matrice["mode_bride"] is True
    assert matrice["repli"]["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert "RuntimeError" in matrice["repli"]["detail"]
    assert "boum secret" not in matrice["repli"]["detail"]


@pytest.mark.parametrize("trajets", [
    {"metres": [[0, 1, 2], [1, 0, 3], [2, 3, 0]]},
    {"metres": [[0, 1], [1, 0]], "secondes": [[0, 1], [1, 0]]},
    {"metres": [[0, 1.5, 2], [1, 0, 3], [2, 3, 0]], "secondes": [[0, 1, 2], [1, 0, 3], [2, 3, 0]]},
    {"metres": [[0, -1, 2], [1, 0, 3], [2, 3, 0]], "secondes": [[0, 1, 2], [1, 0, 3], [2, 3, 0]]},
    {"metres": [[1, 1, 2], [1, 0, 3], [2, 3, 0]], "secondes": [[0, 1, 2], [1, 0, 3], [2, 3, 0]]},
    {"metres": [[0, 1, 2], [1, 0, 3], [2, 3, 0]], "secondes": [[0, True, 2], [1, 0, 3], [2, 3, 0]]},
    "n'importe quoi",
])
def test_un_fournisseur_qui_ment_sur_la_forme_replie_avec_reponse_invalide(trajets):
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, _Fournisseur(trajets=trajets))
    assert verdict is None
    assert matrice["mode_bride"] is True
    assert matrice["repli"]["code"] == distances.CODE_REPONSE_INVALIDE


def test_trajet_introuvable_est_un_verdict_sans_repli():
    """Le palier 0 inventerait une route que le fournisseur dit inexistante : on rend le verdict."""
    verdict_donnee = distances.verdict_matrice(distances.CODE_TRAJET_INTROUVABLE, "aucune route pour a->b")
    fournisseur = _Fournisseur(verdict=verdict_donnee)
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, fournisseur)
    assert matrice is None
    assert verdict == verdict_donnee
    assert len(fournisseur.appels) == 1


@pytest.mark.parametrize("descripteur", [
    {},
    None,
    {"fournisseur": "x"},
    {"mode_distance": "haversine_detour"},
    {"mode_distance": "ok", "profil": 3},
    {"mode_distance": "ok", "profil": ""},
])
def test_descripteur_invalide_est_refuse_sans_repli_ni_appel(descripteur):
    fournisseur = _Fournisseur(descripteur=descripteur)
    if descripteur is None:  # None = « pas de forçage » dans la fabrique de test : on force un objet invalide
        fournisseur.descripteur = lambda: None
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, fournisseur)
    assert matrice is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert fournisseur.appels == []


def test_descripteur_qui_leve_est_refuse():
    fournisseur = _Fournisseur()

    def casse():
        raise OSError("disque")

    fournisseur.descripteur = casse
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, fournisseur)
    assert matrice is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "OSError" in verdict["detail"]


def test_verdict_matrice_refuse_un_code_hors_liste():
    assert distances.verdict_matrice(distances.CODE_REPONSE_INVALIDE, "x") == {
        "code": distances.CODE_REPONSE_INVALIDE, "statut": "", "detail": "x",
    }
    with pytest.raises(verdicts.CodeVerdictInconnu):
        distances.verdict_matrice("REJ-INVENTE")
    for code in distances.CODES_MATRICE:
        assert verdicts.est_verdict(code)  # inscrits au catalogue par T4.1-d


# ---------------------------------------------------------------------------
# 7. Gardes de code : module pur, sans flottant
# ---------------------------------------------------------------------------
def _arbre(nom):
    return ast.parse((_SRC / nom).read_text(encoding="utf-8"))


def _imports(arbre):
    modules = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0:
            modules.add((noeud.module or "").split(".")[0])
    return modules


def test_distances_est_pur_aucun_import_reseau_horloge_ou_alea():
    modules = _imports(_arbre("distances.py"))
    assert modules == {"__future__", "math", "typing"}


@pytest.mark.parametrize("nom", ["distances.py", "distances_osrm.py"])
def test_aucun_flottant_ni_division_vraie_dans_le_code(nom):
    """Pas de littéral flottant, pas de ``/`` (division vraie), pas de ``float()`` ni de ``math.*`` trig."""
    arbre = _arbre(nom)
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Constant):
            assert not isinstance(noeud.value, float), (nom, noeud.lineno)
        if isinstance(noeud, (ast.BinOp, ast.AugAssign)):
            assert not isinstance(noeud.op, ast.Div), (nom, noeud.lineno)
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"float", "round"}, (nom, noeud.lineno)
        if isinstance(noeud, ast.Attribute) and isinstance(noeud.value, ast.Name) and noeud.value.id == "math":
            assert noeud.attr == "isqrt", (nom, noeud.lineno)


def test_les_gardes_du_paquet_passent_avec_les_nouveaux_modules():
    assert digest.garde_absence_horloge() == (True, "")
    assert digest.garde_conformite_r020() == (True, "")


# ---------------------------------------------------------------------------
# 8. Étalonnage (fixture fictive)
# ---------------------------------------------------------------------------
def test_ecart_etalonnage_valeurs_calculees_a_la_main():
    # ligne droite 10 000 m × 1,3 = 13 000 m estimés ; référence 12 000 m : +1 000 m, +83 ‰ (83,33), détour réel 1,2.
    assert distances.ecart_etalonnage(10_000, 12_000, 1300) == {
        "route_estimee_m": 13_000, "ecart_m": 1000, "ecart_pour_mille": 83, "rapport_reel_milliemes": 1200,
    }
    # sous-estimation : référence 16 000 m -> −3 000 m, −187,5 ‰ arrondi à −188 (demi vers le haut,
    # sur la valeur absolue).
    assert distances.ecart_etalonnage(10_000, 16_000, 1300) == {
        "route_estimee_m": 13_000, "ecart_m": -3000, "ecart_pour_mille": -188, "rapport_reel_milliemes": 1600,
    }
    assert distances.ecart_etalonnage(10_000, 13_000, 1300)["ecart_m"] == 0


@pytest.mark.parametrize("arguments", [
    (0, 12_000, 1300), (10_000, 0, 1300), (-1, 12_000, 1300), (10_000.0, 12_000, 1300),
    (10_000, 12_000, 0), (10_000, 12_000, 1.3), (True, 12_000, 1300),
])
def test_ecart_etalonnage_refuse_les_entrees_invalides(arguments):
    with pytest.raises(ValueError):
        distances.ecart_etalonnage(*arguments)


def test_fixture_d_etalonnage_lanaudiere_documente_l_ecart_du_modele():
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["fictif"] is True
    assert "TOUT est fictif" in fixture["avertissement"]
    assert all(paire["source_reference"].startswith("fictif") for paire in fixture["paires"])
    assert len(fixture["paires"]) == len(fixture["attendu"]) >= 8
    valeurs, verdict = distances.valider_parametres({k: v for k, v in fixture["parametres"].items() if k != "note"})
    assert verdict is None
    points, verdict = distances.valider_points(fixture["points"])
    assert verdict is None
    par_id = {p["id"]: p for p in points}
    for paire, attendu in zip(fixture["paires"], fixture["attendu"], strict=True):
        a, b = par_id[paire["a"]], par_id[paire["b"]]
        droite = distances.distance_droite_m(
            a["latitude_microdeg"], a["longitude_microdeg"], b["latitude_microdeg"], b["longitude_microdeg"],
        )
        ecart = distances.ecart_etalonnage(droite, paire["route_reference_m"], valeurs["facteur_detour_milliemes"])
        assert {"a": paire["a"], "b": paire["b"], "ligne_droite_m": droite, **ecart} == attendu
        # recoupement flottant indépendant de la ligne droite
        flottant_m = pointage.distance_km(
            a["latitude_microdeg"] / 1e6, a["longitude_microdeg"] / 1e6,
            b["latitude_microdeg"] / 1e6, b["longitude_microdeg"] / 1e6,
        ) * 1000
        assert abs(droite - flottant_m) <= 1.0


def test_fixture_documente_que_le_modele_sous_estime_la_paire_a_cours_d_eau():
    """Les paires sans obstacle restent à moins de 10 % du modèle ; la paire au franchissement d'un cours
    d'eau s'en écarte de plus de 20 % : la limite que R15 §2 annonce, à mesurer sur des paires réelles."""
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    ecarts = {(x["a"], x["b"]): x["ecart_pour_mille"] for x in fixture["attendu"]}
    franchissement = ecarts.pop(("repentigny", "laval-des-rapides"))
    assert franchissement < -200
    assert max(abs(v) for v in ecarts.values()) <= 100
    medianes = sorted(x["rapport_reel_milliemes"] for x in fixture["attendu"])
    milieu = (medianes[len(medianes) // 2 - 1] + medianes[len(medianes) // 2]) // 2
    assert 1250 <= milieu <= 1350  # le détour de départ de 1,3 colle à la médiane de la fixture (inventée)


def test_le_calcul_de_matrice_sur_la_fixture_recoupe_les_ecarts():
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    matrice, verdict = distances.matrice_palier0(
        fixture["points"], {k: v for k, v in fixture["parametres"].items() if k != "note"},
    )
    assert verdict is None
    indice = {identifiant: i for i, identifiant in enumerate(matrice["ids"])}
    for attendu in fixture["attendu"]:
        assert matrice["metres"][indice[attendu["a"]]][indice[attendu["b"]]] == attendu["route_estimee_m"]
