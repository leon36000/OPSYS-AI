"""Matrice de distances et de durées entre chantiers (PLAN T4.1-b, R15 §2 et §4).

Module pur (stdlib, aucune horloge, aucun aléa, aucun accès réseau, aucun import ``opsys``). Il
produit la matrice FIGÉE que le solveur de tournées reçoit en entrée (T4.1-c) : carrée, triée par
identifiant, entière (mètres et secondes), hachée avec ses paramètres. Le solveur ne recalcule
jamais une distance : la matrice fait foi, donc le plan ne dépend pas de la plateforme flottante.

Deux paliers (R15 §2) :

    * Palier 0 (défaut, tout poste) : haversine ENTIÈRE × facteur de détour, vitesse moyenne et
      marge fixe par trajet. Marqué ``mode_distance = "haversine_detour"`` et ``mode_bride = True`` :
      l'écran de dispatch affiche « mode bridé ».
    * Palier 1 (option serveur) : un fournisseur qui respecte le port ``FournisseurMatrice``. Le seul
      adaptateur livré (OSRM, sidecar local) vit dans ``distances_osrm.py``, séparé pour que CE
      module reste sans entrée-sortie (un test le prouve par analyse du code).

Reproductibilité au bit près
    Aucun flottant nulle part : ni dans les entrées (microdegrés entiers), ni dans le calcul, ni dans
    la sortie. La trigonométrie est faite en virgule fixe sur des entiers Python (échelle 10**40) :
    ``sin`` et ``cos`` par série de Taylor, ``atan`` par réduction de l'argument puis série, racine
    carrée par ``math.isqrt`` (exacte). Les entiers de Python sont exacts et leur division entière est
    définie par le langage : le résultat est le même sur toute plateforme et toute version de
    l'interpréteur, sans dépendre de la bibliothèque mathématique du système (``libm``, dont le
    dernier bit des fonctions ``sin``/``atan2`` n'est pas garanti identique d'une plateforme à l'autre).
    L'erreur de calcul est mesurée par les tests contre une référence indépendante en ``Decimal`` à 90
    chiffres (calcul par le vecteur-corde 3D) : moins de 10**-20 m, très en dessous du mètre. L'arrondi final au mètre
    ne diffère donc de celui de la valeur exacte que si celle-ci tombe à moins de 10**-20 m d'un
    demi-mètre ; les tests comparent l'entier obtenu à celui de la référence.

Règles d'arrondi (figées par ``ALGORITHME_PALIER0``, épinglées par des tests)
    1. ``ligne_droite_m`` = distance orthodromique arrondie au mètre le plus proche (demi vers le haut).
    2. ``route_m`` = ``(ligne_droite_m × détour_millièmes + 500) // 1000``.
    3. ``secondes`` = ``ceil(route_m × 3,6 / vitesse_kmh) + marge`` (plafond en entiers : on ne sous-estime
       jamais un trajet), pour deux points distincts ; ``0`` sur la diagonale.

Fail-closed : le détour, la vitesse et la marge sont FOURNIS par l'entreprise. Absents ou hors des
bornes de plausibilité (``BORNES_PARAMETRES``), le verdict dit quoi fournir ; jamais de valeur cachée.
Les bornes sont des limites d'acceptation, PAS des valeurs de départ. Les coordonnées ne sont jamais
recopiées dans un verdict (Loi 25) ; seuls les identifiants opaques y figurent.
"""

from __future__ import annotations

from math import isqrt
from typing import Protocol, runtime_checkable

from . import encodage, verdicts

# ---------------------------------------------------------------------------
# Constantes publiques
# ---------------------------------------------------------------------------
VERSION_MATRICE = "matrice-distances-v1"
ALGORITHME_PALIER0 = "haversine-entier-v1"
MODE_HAVERSINE_DETOUR = "haversine_detour"

# Sphère de rayon 6 371 000 m, comme ``pointage.distance_km`` (6371,0 km) : les deux modules
# s'accordent au mètre près (test de recoupement).
RAYON_TERRESTRE_M = 6_371_000

# Limite par défaut de ``osrm-routed --max-table-size`` (100 emplacements par requête `table`).
# https://project-osrm.org/docs/v26.4.0/tools
MAX_POINTS = 100

CLES_POINT = ("id", "latitude_microdeg", "longitude_microdeg")
LATITUDE_MAX_MICRODEG = 90_000_000
LONGITUDE_MAX_MICRODEG = 180_000_000

# Bornes de PLAUSIBILITÉ (acceptation), jamais des valeurs par défaut.
#   détour : une route ne peut pas être plus courte que l'orthodromie (>= 1,000) ; au-delà de 3,000
#            la ligne droite n'informe plus, l'entreprise doit passer au palier 1 (routage réel).
#   vitesse : 10 km/h (centre dense, hiver) à 110 km/h (autoroute) ; hors de cette plage, une faute
#             de frappe ou une unité erronée (m/s, mph) est bien plus probable qu'une vraie vitesse.
#   marge : de 0 à 1 h par trajet (stationnement, accès au chantier, imprévus).
BORNES_PARAMETRES = {
    "facteur_detour_milliemes": (1000, 3000),
    "vitesse_moyenne_kmh": (10, 110),
    "marge_par_trajet_secondes": (0, 3600),
}

_AIDE_PARAMETRES = {
    "facteur_detour_milliemes": "rapport route sur ligne droite, en millièmes entiers (1300 pour 1,3)",
    "vitesse_moyenne_kmh": "vitesse moyenne de déplacement, en km/h entiers",
    "marge_par_trajet_secondes": "marge fixe ajoutée à chaque trajet (stationnement, accès), en secondes entières",
}

# Verdicts propres à la matrice hors du catalogue gelé de ``verdicts.py`` (T4.1-d les y inscrira
# quand un outil les exposera). Même forme que ``verdicts.construire_verdict``.
CODE_FOURNISSEUR_INDISPONIBLE = "REJ-MATRICE-FOURNISSEUR-INDISPONIBLE"
CODE_REPONSE_INVALIDE = "REJ-MATRICE-REPONSE-INVALIDE"
CODE_TRAJET_INTROUVABLE = "REJ-MATRICE-TRAJET-INTROUVABLE"
CODES_MATRICE = (CODE_FOURNISSEUR_INDISPONIBLE, CODE_REPONSE_INVALIDE, CODE_TRAJET_INTROUVABLE)

__all__ = [
    "VERSION_MATRICE",
    "ALGORITHME_PALIER0",
    "MODE_HAVERSINE_DETOUR",
    "RAYON_TERRESTRE_M",
    "MAX_POINTS",
    "CLES_POINT",
    "BORNES_PARAMETRES",
    "CODE_FOURNISSEUR_INDISPONIBLE",
    "CODE_REPONSE_INVALIDE",
    "CODE_TRAJET_INTROUVABLE",
    "CODES_MATRICE",
    "FournisseurMatrice",
    "verdict_matrice",
    "valider_parametres",
    "valider_points",
    "distance_droite_m",
    "matrice_palier0",
    "obtenir_matrice",
    "verifier_matrice",
    "ecart_etalonnage",
]

# ---------------------------------------------------------------------------
# Trigonométrie en virgule fixe (entiers Python, échelle 10**40)
# ---------------------------------------------------------------------------
_ECHELLE = 10**40
# π × 10**40, arrondi au plus proche (un test le recalcule par la formule de Machin).
_PI = 31415926535897932384626433832795028841972
_MICRODEG_PAR_DEGRE = 1_000_000


def _mul(a, b):
    """Produit en virgule fixe (opérandes >= 0 : la division entière tronque vers zéro)."""
    return a * b // _ECHELLE


def _sin(x):
    """sin(x) pour 0 <= x <= π/2 (x en virgule fixe), série de Taylor."""
    x2 = _mul(x, x)
    terme = somme = x
    k = 1
    while True:
        terme = terme * x2 // (_ECHELLE * (2 * k) * (2 * k + 1))
        if terme == 0:
            return somme
        somme += -terme if k % 2 else terme
        k += 1


def _cos(x):
    """cos(x) pour 0 <= x <= π/2 (x en virgule fixe), série de Taylor ; jamais négatif."""
    x2 = _mul(x, x)
    terme = somme = _ECHELLE
    k = 1
    while True:
        terme = terme * x2 // (_ECHELLE * (2 * k - 1) * (2 * k))
        if terme == 0:
            return max(somme, 0)
        somme += -terme if k % 2 else terme
        k += 1


def _atan(x):
    """atan(x) pour x >= 0 (virgule fixe) : inversion au-delà de 1, trois demi-angles, série."""
    if x > _ECHELLE:
        return _PI // 2 - _atan(_ECHELLE * _ECHELLE // x)
    for _ in range(3):
        x = x * _ECHELLE // (_ECHELLE + isqrt(_ECHELLE * _ECHELLE + x * x))
    x2 = _mul(x, x)
    terme = somme = x
    k = 1
    while True:
        terme = terme * x2 // _ECHELLE
        if terme == 0:
            return somme * 8
        contribution = terme // (2 * k + 1)
        somme += -contribution if k % 2 else contribution
        k += 1


def _cosinus_latitude(latitude_microdeg):
    """cos(latitude) en virgule fixe (le cosinus est pair : la valeur absolue suffit)."""
    return _cos(abs(latitude_microdeg) * _PI // (180 * _MICRODEG_PAR_DEGRE))


def _orthodromie_fp(lat1, lon1, lat2, lon2, cos_lat1, cos_lat2):
    """Distance orthodromique en mètres, en virgule fixe (échelle ``_ECHELLE``), non arrondie.

    Haversine sur la sphère de ``RAYON_TERRESTRE_M``. Symétrique par construction : seules des
    différences en valeur absolue et le produit commutatif des cosinus interviennent.
    """
    d_lat = abs(lat2 - lat1)
    d_lon = abs(lon2 - lon1)
    if d_lon > LONGITUDE_MAX_MICRODEG:
        d_lon = 2 * LONGITUDE_MAX_MICRODEG - d_lon  # le plus court chemin autour du globe
    demi_lat = _sin(d_lat * _PI // (360 * _MICRODEG_PAR_DEGRE))
    demi_lon = _sin(d_lon * _PI // (360 * _MICRODEG_PAR_DEGRE))
    a = _mul(demi_lat, demi_lat) + _mul(_mul(cos_lat1, cos_lat2), _mul(demi_lon, demi_lon))
    a = min(max(a, 0), _ECHELLE)
    racine_a = isqrt(a * _ECHELLE)
    racine_reste = isqrt((_ECHELLE - a) * _ECHELLE)
    # racine_reste == 0 : points antipodaux, angle central de π.
    angle_central = _PI if racine_reste == 0 else 2 * _atan(racine_a * _ECHELLE // racine_reste)
    return RAYON_TERRESTRE_M * angle_central


def _orthodromie_m(lat1, lon1, lat2, lon2, cos_lat1, cos_lat2):
    """Distance orthodromique en mètres ENTIERS : arrondi au plus proche, demi vers le haut."""
    return (_orthodromie_fp(lat1, lon1, lat2, lon2, cos_lat1, cos_lat2) + _ECHELLE // 2) // _ECHELLE


def _est_entier(valeur):
    """Entier Python strict : ni booléen, ni flottant."""
    return type(valeur) is int


def _exiger_coordonnees(latitude_microdeg, longitude_microdeg):
    if not _est_entier(latitude_microdeg) or not _est_entier(longitude_microdeg):
        raise ValueError("les coordonnées sont des microdegrés ENTIERS")
    if abs(latitude_microdeg) > LATITUDE_MAX_MICRODEG or abs(longitude_microdeg) > LONGITUDE_MAX_MICRODEG:
        raise ValueError("coordonnées hors de [-90, 90] degrés de latitude ou [-180, 180] de longitude")


def distance_droite_m(latitude1_microdeg, longitude1_microdeg, latitude2_microdeg, longitude2_microdeg):
    """Distance orthodromique entre deux points, en mètres ENTIERS (règle d'arrondi n° 1).

    Entrées : microdegrés entiers (45,742000° = 45742000). Lève ``ValueError`` si une coordonnée
    n'est pas un entier ou sort de la plage terrestre (erreur de programmation : la validation des
    entrées d'un appelant passe par ``valider_points``, qui rend un verdict).
    """
    _exiger_coordonnees(latitude1_microdeg, longitude1_microdeg)
    _exiger_coordonnees(latitude2_microdeg, longitude2_microdeg)
    return _orthodromie_m(
        latitude1_microdeg, longitude1_microdeg, latitude2_microdeg, longitude2_microdeg,
        _cosinus_latitude(latitude1_microdeg), _cosinus_latitude(latitude2_microdeg),
    )


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------
def verdict_matrice(code, detail=""):
    """Verdict propre à la matrice (code de ``CODES_MATRICE``), même forme que les verdicts M4."""
    if code not in CODES_MATRICE:
        raise verdicts.CodeVerdictInconnu(f"Code verdict de matrice invalide : {code!r}")
    return {"code": code, "statut": "", "detail": detail}


def _rejet(code, detail):
    return verdicts.construire_verdict(code, detail=detail)


# ---------------------------------------------------------------------------
# Validation des entrées
# ---------------------------------------------------------------------------
def valider_parametres(parametres):
    """Valide les trois paramètres d'entreprise du palier 0. Retourne (paramètres, None) ou (None, verdict).

    Chaque paramètre est un entier obligatoire, dans ``BORNES_PARAMETRES``. Un paramètre absent (ou
    ``None``) donne ``REJ-CHAMP-MANQUANT`` ; un type ou une valeur hors bornes, une clé inconnue
    (faute de frappe), ``REJ-CONTRAT-INVALIDE``. Le détail liste TOUT ce qu'il faut fournir, en une fois.
    """
    if not isinstance(parametres, dict):
        return None, _rejet(
            "REJ-CONTRAT-INVALIDE",
            "parametres de distance : un objet est attendu avec " + ", ".join(BORNES_PARAMETRES)
            + " (à fournir par l'entreprise, aucune valeur par défaut)",
        )
    absents = []
    invalides = []
    valeurs = {}
    for cle, (minimum, maximum) in BORNES_PARAMETRES.items():
        valeur = parametres.get(cle)
        aide = _AIDE_PARAMETRES[cle]
        if valeur is None:
            absents.append(f"{cle} manquant : {aide}, entre {minimum} et {maximum}")
        elif not _est_entier(valeur):
            invalides.append(f"{cle} : entier requis ({aide}), type reçu {type(valeur).__name__}")
        elif not minimum <= valeur <= maximum:
            invalides.append(f"{cle} : {valeur} hors bornes, attendu entre {minimum} et {maximum} ({aide})")
        else:
            valeurs[cle] = valeur
    inconnus = sorted(str(cle) for cle in parametres if cle not in BORNES_PARAMETRES)
    if inconnus:
        invalides.append("clés inconnues : " + ", ".join(inconnus))
    if absents:
        return None, _rejet("REJ-CHAMP-MANQUANT", " ; ".join(absents + invalides))
    if invalides:
        return None, _rejet("REJ-CONTRAT-INVALIDE", " ; ".join(invalides))
    return valeurs, None


def _nom_point(indice, point):
    identifiant = point.get("id") if isinstance(point, dict) else None
    if isinstance(identifiant, str) and identifiant:
        return f"point {identifiant!r}"
    return f"point n° {indice}"


def valider_points(points):
    """Valide les points et les rend triés par identifiant. Retourne (liste, None) ou (None, verdict).

    Un point est ``{"id": str, "latitude_microdeg": int, "longitude_microdeg": int}``, ni plus ni
    moins (aucune adresse ni autre donnée personnelle ne passe ici). Refusés : liste vide ou de plus
    de ``MAX_POINTS`` points, identifiant vide ou en double, coordonnée non entière ou hors plage,
    et (0, 0), valeur d'absence classique qui enverrait une équipe dans le golfe de Guinée.
    La liste rendue est une copie, triée par identifiant (ordre des points de code Unicode).
    """
    if not isinstance(points, (list, tuple)):
        return None, _rejet("REJ-CONTRAT-INVALIDE", "points : une liste est attendue")
    if not points:
        return None, _rejet(
            "REJ-CHAMP-VIDE",
            "points : fournir au moins un point avec id, latitude_microdeg et longitude_microdeg",
        )
    if len(points) > MAX_POINTS:
        return None, _rejet(
            "REJ-CONTRAT-INVALIDE",
            f"points : {len(points)} points, maximum {MAX_POINTS} par matrice (scinder la journée)",
        )
    normalises = []
    vus = set()
    for indice, point in enumerate(points):
        nom = _nom_point(indice, point)
        if not isinstance(point, dict):
            return None, _rejet("REJ-CONTRAT-INVALIDE", f"{nom} : un objet est attendu")
        manquantes = [cle for cle in CLES_POINT if point.get(cle) is None]
        if manquantes:
            return None, _rejet("REJ-CHAMP-MANQUANT", f"{nom} : à fournir : {', '.join(manquantes)}")
        en_trop = sorted(str(cle) for cle in point if cle not in CLES_POINT)
        if en_trop:
            return None, _rejet("REJ-CONTRAT-INVALIDE", f"{nom} : clés inconnues : {', '.join(en_trop)}")
        identifiant = point["id"]
        if not isinstance(identifiant, str) or not identifiant:
            return None, _rejet("REJ-CONTRAT-INVALIDE", f"{nom} : id doit être une chaîne non vide")
        if identifiant in vus:
            return None, _rejet("REJ-CONTRAT-INVALIDE", f"{nom} : identifiant en double")
        vus.add(identifiant)
        latitude = point["latitude_microdeg"]
        longitude = point["longitude_microdeg"]
        if not _est_entier(latitude) or not _est_entier(longitude):
            return None, _rejet(
                "REJ-CONTRAT-INVALIDE",
                f"{nom} : latitude_microdeg et longitude_microdeg sont des entiers (45,742° = 45742000)",
            )
        if abs(latitude) > LATITUDE_MAX_MICRODEG or abs(longitude) > LONGITUDE_MAX_MICRODEG:
            return None, _rejet(
                "REJ-CONTRAT-INVALIDE",
                f"{nom} : coordonnées hors de la plage terrestre (latitude ±90°, longitude ±180°)",
            )
        if latitude == 0 and longitude == 0:
            return None, _rejet(
                "REJ-CHAMP-MANQUANT",
                f"{nom} : coordonnées (0, 0) refusées, valeur d'absence probable : fournir la position confirmée",
            )
        normalises.append({"id": identifiant, "latitude_microdeg": latitude, "longitude_microdeg": longitude})
    normalises.sort(key=lambda p: p["id"])
    return normalises, None


# ---------------------------------------------------------------------------
# Palier 0 : haversine entière × détour
# ---------------------------------------------------------------------------
def _metres_route(ligne_droite_m, facteur_detour_milliemes):
    """Règle d'arrondi n° 2."""
    return (ligne_droite_m * facteur_detour_milliemes + 500) // 1000


def _secondes_trajet(route_m, vitesse_kmh, marge_secondes):
    """Règle d'arrondi n° 3 (plafond en entiers) : 3,6 = 18/5, donc route_m × 18 / (5 × vitesse)."""
    return -(-(route_m * 18) // (5 * vitesse_kmh)) + marge_secondes


def _assembler(ids, metres, secondes, mode_distance, mode_bride, parametres, repli):
    corps = {
        "version": VERSION_MATRICE,
        "mode_distance": mode_distance,
        "mode_bride": mode_bride,
        "repli": repli,
        "ids": list(ids),
        "metres": metres,
        "secondes": secondes,
        "parametres": parametres,
    }
    matrice = dict(corps)
    matrice["empreinte"] = encodage.empreinte(corps)
    return matrice


def _matrice_palier0(points_tries, parametres, repli):
    n = len(points_tries)
    cosinus = [_cosinus_latitude(p["latitude_microdeg"]) for p in points_tries]
    metres = [[0] * n for _ in range(n)]
    secondes = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            a = points_tries[i]
            b = points_tries[j]
            droite = _orthodromie_m(
                a["latitude_microdeg"], a["longitude_microdeg"],
                b["latitude_microdeg"], b["longitude_microdeg"],
                cosinus[i], cosinus[j],
            )
            route = _metres_route(droite, parametres["facteur_detour_milliemes"])
            duree = _secondes_trajet(route, parametres["vitesse_moyenne_kmh"], parametres["marge_par_trajet_secondes"])
            metres[i][j] = metres[j][i] = route
            secondes[i][j] = secondes[j][i] = duree
    parametres_matrice = {
        "algorithme": ALGORITHME_PALIER0,
        "rayon_terrestre_m": RAYON_TERRESTRE_M,
        "facteur_detour_milliemes": parametres["facteur_detour_milliemes"],
        "vitesse_moyenne_kmh": parametres["vitesse_moyenne_kmh"],
        "marge_par_trajet_secondes": parametres["marge_par_trajet_secondes"],
    }
    return _assembler(
        [p["id"] for p in points_tries], metres, secondes,
        MODE_HAVERSINE_DETOUR, True, parametres_matrice, repli,
    )


def matrice_palier0(points, parametres):
    """Matrice du palier 0 (haversine entière × détour). Retourne (matrice, None) ou (None, verdict).

    ``points`` : liste de ``{"id", "latitude_microdeg", "longitude_microdeg"}`` (voir ``valider_points``).
    ``parametres`` : ``facteur_detour_milliemes``, ``vitesse_moyenne_kmh``, ``marge_par_trajet_secondes``,
    fournis par l'entreprise (voir ``valider_parametres``).

    La matrice est un dict JSON-compatible, sans flottant :
        ``version``, ``mode_distance`` (``"haversine_detour"``), ``mode_bride`` (``True``), ``repli``
        (``None``), ``ids`` (triés), ``metres`` et ``secondes`` (carrés, ``[i][j]`` = trajet de
        ``ids[i]`` vers ``ids[j]``, diagonale nulle, symétriques au palier 0), ``parametres`` et
        ``empreinte`` (SHA-256 canonique de tout le reste, via ``encodage.empreinte``).
    """
    valeurs, verdict = valider_parametres(parametres)
    if verdict is not None:
        return None, verdict
    tries, verdict = valider_points(points)
    if verdict is not None:
        return None, verdict
    return _matrice_palier0(tries, valeurs, None), None


# ---------------------------------------------------------------------------
# Palier 1 : port et repli explicite
# ---------------------------------------------------------------------------
@runtime_checkable
class FournisseurMatrice(Protocol):
    """Port d'un fournisseur de trajets routiers (palier 1).

    Un fournisseur ne fait QUE fournir des trajets bruts ; l'ajout de la marge, le tri, le hachage
    et le repli sont faits ici, une seule fois, pour tous les fournisseurs.

    ``descripteur()`` : dict de chaînes non vides, stable d'un appel à l'autre, qui entre dans
    l'empreinte de la matrice. Il porte au moins ``mode_distance`` (autre que ``haversine_detour``,
    réservé au palier 0) et tout ce qui change le contenu de la matrice (version des données routières).

    ``trajets(points)`` : reçoit les points VALIDÉS et triés par identifiant. Retourne
    ``({"metres": [[int]], "secondes": [[int]]}, None)`` (matrices carrées dans l'ordre des points,
    entiers >= 0, diagonale nulle, sans marge) ou ``(None, verdict)``. Ne lève rien ; n'écrit rien ;
    n'est appelé que si l'appelant en fournit un.
    """

    def descripteur(self):
        """Métadonnées stables du fournisseur, entrant dans l'empreinte (voir la classe)."""

    def trajets(self, points):
        """Trajets bruts entre les points triés, ou un verdict (voir la classe)."""


def _valider_descripteur(descripteur):
    if not isinstance(descripteur, dict) or not descripteur:
        return "le descripteur du fournisseur doit être un objet non vide"
    for cle, valeur in descripteur.items():
        if not isinstance(cle, str) or not isinstance(valeur, str) or not cle or not valeur:
            return "le descripteur du fournisseur ne contient que des chaînes non vides"
    mode = descripteur.get("mode_distance")
    if mode is None:
        return "le descripteur du fournisseur doit porter mode_distance"
    if mode == MODE_HAVERSINE_DETOUR:
        return f"mode_distance {MODE_HAVERSINE_DETOUR!r} est réservé au palier 0"
    return None


def _matrice_carree_entiere(table, n):
    """Vrai si ``table`` est une matrice n×n d'entiers >= 0 à diagonale nulle."""
    if not isinstance(table, list) or len(table) != n:
        return False
    for i, ligne in enumerate(table):
        if not isinstance(ligne, list) or len(ligne) != n:
            return False
        for j, valeur in enumerate(ligne):
            if not _est_entier(valeur) or valeur < 0 or (i == j and valeur != 0):
                return False
    return True


def _repli_depuis(descripteur, verdict):
    return {"depuis": descripteur["mode_distance"], "code": verdict["code"], "detail": verdict["detail"]}


def obtenir_matrice(points, parametres, fournisseur=None):
    """Matrice de trajets, avec repli EXPLICITE sur le palier 0. Retourne (matrice, None) ou (None, verdict).

    ``parametres`` (détour, vitesse, marge) est TOUJOURS validé d'abord, même avec un fournisseur :
    on n'apprend pas au moment d'une panne que le repli est impossible. La marge s'ajoute à chaque
    trajet entre deux points distincts, quel que soit le fournisseur.

    * ``fournisseur=None`` : palier 0 direct, aucune entrée-sortie.
    * fournisseur qui répond bien : matrice du fournisseur, ``mode_bride`` ``False``.
    * fournisseur indisponible, réponse invalide, ou qui lève une exception : repli sur le palier 0,
      JAMAIS silencieux. La matrice porte ``mode_bride`` ``True`` et ``repli`` =
      ``{"depuis", "code", "detail"}`` (dans l'empreinte : une matrice de repli n'a jamais la même
      empreinte qu'une matrice routière).
    * ``REJ-MATRICE-TRAJET-INTROUVABLE`` (le fournisseur affirme qu'il n'existe pas de route entre deux
      points, ou qu'un point n'est pas rattachable au réseau) n'est PAS une panne : c'est une donnée
      à corriger. Le verdict est rendu tel quel, sans repli, car le palier 0 inventerait un trajet.
    """
    valeurs, verdict = valider_parametres(parametres)
    if verdict is not None:
        return None, verdict
    tries, verdict = valider_points(points)
    if verdict is not None:
        return None, verdict
    if fournisseur is None:
        return _matrice_palier0(tries, valeurs, None), None

    try:
        descripteur = fournisseur.descripteur()
    except Exception as exc:  # un port défaillant est un cas de repli marqué, jamais un plantage
        return None, _rejet(
            "REJ-CONTRAT-INVALIDE", f"fournisseur de matrice : descripteur() a échoué ({type(exc).__name__})",
        )
    probleme = _valider_descripteur(descripteur)
    if probleme is not None:
        return None, _rejet("REJ-CONTRAT-INVALIDE", f"fournisseur de matrice : {probleme}")

    try:
        trajets, verdict_fournisseur = fournisseur.trajets([dict(p) for p in tries])
    except Exception as exc:
        trajets = None
        verdict_fournisseur = verdict_matrice(
            CODE_FOURNISSEUR_INDISPONIBLE, f"le fournisseur a levé {type(exc).__name__}",
        )
    if verdict_fournisseur is None:
        n = len(tries)
        if (
            isinstance(trajets, dict)
            and _matrice_carree_entiere(trajets.get("metres"), n)
            and _matrice_carree_entiere(trajets.get("secondes"), n)
        ):
            return _matrice_fournisseur(tries, trajets, descripteur, valeurs), None
        verdict_fournisseur = verdict_matrice(
            CODE_REPONSE_INVALIDE,
            "trajets du fournisseur : matrices carrées d'entiers >= 0 à diagonale nulle attendues",
        )
    if not isinstance(verdict_fournisseur, dict) or not isinstance(verdict_fournisseur.get("code"), str):
        verdict_fournisseur = verdict_matrice(CODE_REPONSE_INVALIDE, "verdict du fournisseur mal formé")
    if verdict_fournisseur["code"] == CODE_TRAJET_INTROUVABLE:
        return None, verdict_fournisseur
    repli = _repli_depuis(descripteur, {
        "code": verdict_fournisseur["code"], "detail": str(verdict_fournisseur.get("detail", "")),
    })
    return _matrice_palier0(tries, valeurs, repli), None


def _matrice_fournisseur(points_tries, trajets, descripteur, valeurs):
    n = len(points_tries)
    marge = valeurs["marge_par_trajet_secondes"]
    secondes = [
        [0 if i == j else trajets["secondes"][i][j] + marge for j in range(n)]
        for i in range(n)
    ]
    metres = [list(ligne) for ligne in trajets["metres"]]
    details = {cle: valeur for cle, valeur in descripteur.items() if cle != "mode_distance"}
    parametres_matrice = {"marge_par_trajet_secondes": marge, "fournisseur": details}
    return _assembler(
        [p["id"] for p in points_tries], metres, secondes,
        descripteur["mode_distance"], False, parametres_matrice, None,
    )


# ---------------------------------------------------------------------------
# Vérification d'une matrice reçue (le solveur ne fait jamais confiance à une matrice non vérifiée)
# ---------------------------------------------------------------------------
_CLES_MATRICE = (
    "version", "mode_distance", "mode_bride", "repli", "ids", "metres", "secondes", "parametres", "empreinte",
)


def _valeurs_sans_flottant(valeur):
    """Vrai si ``valeur`` ne contient que dict/list de str, int (pas bool sauf drapeaux), None."""
    if isinstance(valeur, dict):
        return all(isinstance(cle, str) and _valeurs_sans_flottant(v) for cle, v in valeur.items())
    if isinstance(valeur, list):
        return all(_valeurs_sans_flottant(v) for v in valeur)
    return valeur is None or isinstance(valeur, (str, bool)) or _est_entier(valeur)


def verifier_matrice(matrice):
    """Vérifie une matrice par recalcul. Retourne (True, "") ou (False, message) ; ne lève jamais.

    Contrôle : clés exactes, version, identifiants triés et uniques, matrices carrées d'entiers >= 0 à
    diagonale nulle, cohérence de ``mode_bride`` et de ``repli`` avec ``mode_distance``, absence de
    flottant, et empreinte recalculée (elle couvre les paramètres : en changer un change l'empreinte).
    """
    if not isinstance(matrice, dict):
        return False, "matrice : un objet est attendu"
    if set(matrice) != set(_CLES_MATRICE):
        return False, "matrice : clés incorrectes"
    if matrice["version"] != VERSION_MATRICE:
        return False, f"matrice : version inconnue {matrice['version']!r}"
    ids = matrice["ids"]
    if (
        not isinstance(ids, list) or not ids or len(ids) > MAX_POINTS
        or not all(isinstance(i, str) and i for i in ids)
        or any(a >= b for a, b in zip(ids, ids[1:], strict=False))
    ):
        return False, "matrice : ids non vides, uniques et triés attendus"
    n = len(ids)
    if not _matrice_carree_entiere(matrice["metres"], n) or not _matrice_carree_entiere(matrice["secondes"], n):
        return False, "matrice : metres et secondes doivent être carrées, entières, >= 0, à diagonale nulle"
    mode = matrice["mode_distance"]
    if not isinstance(mode, str) or not mode:
        return False, "matrice : mode_distance manquant"
    if not isinstance(matrice["mode_bride"], bool) or matrice["mode_bride"] != (mode == MODE_HAVERSINE_DETOUR):
        return False, "matrice : mode_bride incohérent avec mode_distance"
    repli = matrice["repli"]
    if repli is not None:
        if mode != MODE_HAVERSINE_DETOUR:
            return False, "matrice : un repli ne peut que produire le palier 0"
        if (
            not isinstance(repli, dict) or set(repli) != {"depuis", "code", "detail"}
            or not all(isinstance(v, str) for v in repli.values())
        ):
            return False, "matrice : repli mal formé"
    if not isinstance(matrice["parametres"], dict) or not _valeurs_sans_flottant(matrice["parametres"]):
        return False, "matrice : parametres sans flottant attendus"
    corps = {cle: matrice[cle] for cle in _CLES_MATRICE if cle != "empreinte"}
    if matrice["empreinte"] != encodage.empreinte(corps):
        return False, "matrice : empreinte invalide"
    return True, ""


# ---------------------------------------------------------------------------
# Étalonnage (R15 §2 : calibrer le détour sur au moins 30 paires réelles mesurées avec OSRM)
# ---------------------------------------------------------------------------
def ecart_etalonnage(ligne_droite_m, route_reference_m, facteur_detour_milliemes):
    """Écart du modèle « ligne droite × détour » à une distance routière de référence, en entiers.

    Retourne un dict :
        ``route_estimee_m`` (règle d'arrondi n° 2), ``ecart_m`` (estimée − référence : négatif si le
        modèle SOUS-estime), ``ecart_pour_mille`` (écart sur la référence, en ‰, arrondi à l'entier le
        plus proche, demi vers le haut sur la valeur absolue), ``rapport_reel_milliemes`` (route de
        référence sur ligne droite, en millièmes : le détour réellement observé sur cette paire).

    Les deux distances sont des entiers > 0 (mètres) ; sinon ``ValueError`` (une paire sans distance
    ne s'étalonne pas). Fonction de mesure : elle ne fixe aucun paramètre de l'entreprise.
    """
    for nom, valeur in (("ligne_droite_m", ligne_droite_m), ("route_reference_m", route_reference_m)):
        if not _est_entier(valeur) or valeur <= 0:
            raise ValueError(f"{nom} doit être un entier > 0 (mètres)")
    if not _est_entier(facteur_detour_milliemes) or facteur_detour_milliemes <= 0:
        raise ValueError("facteur_detour_milliemes doit être un entier > 0")
    estimee = _metres_route(ligne_droite_m, facteur_detour_milliemes)
    ecart = estimee - route_reference_m
    pour_mille = (abs(ecart) * 1000 + route_reference_m // 2) // route_reference_m
    return {
        "route_estimee_m": estimee,
        "ecart_m": ecart,
        "ecart_pour_mille": -pour_mille if ecart < 0 else pour_mille,
        "rapport_reel_milliemes": (route_reference_m * 1000 + ligne_droite_m // 2) // ligne_droite_m,
    }
