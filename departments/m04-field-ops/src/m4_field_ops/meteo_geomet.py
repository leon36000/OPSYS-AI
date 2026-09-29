"""Adaptateur MSC GeoMet du port ``FournisseurMeteo`` (PLAN T4.13, M4.10, R7 §2).

FERMÉ par la configuration : jamais appelé tant que le profil météo de l'entreprise ne déclare pas
``fournisseur: msc_geomet`` (`opsys meteo declarer`). Aucun réseau à l'import, aucune connexion à la création.

Source : MSC GeoMet-OGC-API d'Environnement et Changement climatique Canada (ECCC), collection
``citypageweather-realtime`` (« City Page Weather », marquée EXPÉRIMENTALE par ECCC) : la prévision de la page météo de
la localité la plus proche, en JSON GeoJSON.

    GET
    https://api.weather.gc.ca/collections/citypageweather-realtime/items?f=json&lang=en&limit=20&bbox=lon0,lat0,lon1,lat1

Licence : « Environment and Climate Change Canada Data Services End-use Licence » v2.1.1 (août 2026), lue le 2026-09-29
sur https://eccc-msc.github.io/open-data/licence/readme_en/ : licence mondiale, gratuite, perpétuelle, non exclusive,
USAGE COMMERCIAL PERMIS ; à condition de citer la source (``ATTRIBUTION_ECCC``, rendue à chaque résultat) et de lier la
licence, de ne pas suggérer l'aval d'ECCC, et de ne reproduire un avertissement météo (alerte) qu'en n'en altérant ni le
contenu ni l'intention. Ce module NE REPRODUIT AUCUN avertissement : la liste ``warnings`` de la page n'est pas lue (sa
forme n'a pu être vérifiée : elle était vide au moment de la lecture). L'accès à GeoMet est anonyme et gratuit (page MSC
GeoMet).

Forme lue (réponse réelle du 2026-09-29, valeurs recopiées ici seulement en structure) ::

    features[].properties.lastUpdated                                   "2026-09-29T06:02:44Z"  <- heure citée
    features[].properties.identifier / name.en                          "qc-156" / nom de la localité
    features[].properties.hourlyForecastGroup.hourlyForecasts[]
        .timestamp                                                      "2026-09-29T07:00:00Z"  (UTC)
        .temperature.value.en    .wind.speed.value.en    .lop.value.en     °C, km/h, % (probabilité de précipitations)
        .condition.en                                                   texte de la condition
    features[].geometry.coordinates                                     [lon, lat]

Ce que la source NE DONNE PAS, et que l'adaptateur rend donc ``None`` (les règles qui le demandent restent « inconnu »,
jamais « ok ») : les rafales horaires, la quantité de précipitations, et un champ verglas fiable. Le verglas n'est rendu
``True`` que si le texte de la condition dit « freezing » ou « ice pellets » ; sinon ``None``, jamais ``False``. La
prévision horaire couvre environ un jour : une heure hors de la portée rend ``inconnu`` pour cette heure.

Les heures de la source sont en UTC : elles sont converties à l'heure LOCALE du chantier avec le fuseau du profil
(``zoneinfo``), puis comparées sans conversion au créneau. Sans base des fuseaux, la création échoue (verdict).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import meteo, meteo_http, verdicts

FOURNISSEUR = "msc_geomet"
COLLECTION = "citypageweather-realtime"
URL_ITEMS = f"https://{meteo_http.HOTE_MSC_GEOMET}/collections/{COLLECTION}/items"
ATTRIBUTION_ECCC = (
    "Contains information licenced under the Data Server End-use Licence of Environment and Climate Change Canada."
)
LICENCE_ECCC = "https://eccc-msc.github.io/open-data/licence/readme_en/"
VERSION_LICENCE = "2.1.1"
HEURE_TYPE = "mise_a_jour_du_fournisseur"
MARGE_BBOX_MICRODEG = 200_000  # 0,2 degré autour du lieu généralisé
LIMITE_LOCALITES = 20
_MOTS_VERGLAS = ("freezing", "ice pellets")

__all__ = [
    "FOURNISSEUR",
    "URL_ITEMS",
    "ATTRIBUTION_ECCC",
    "LICENCE_ECCC",
    "VERSION_LICENCE",
    "FournisseurMscGeomet",
    "creer_fournisseur_geomet",
]


def _refus(detail):
    return verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail=detail)


def _reponse_invalide(detail):
    return meteo.verdict_meteo(meteo.CODE_REPONSE_INVALIDE, f"MSC GeoMet : {detail}")


def _valeur(objet, *chemin):
    """La valeur au bout du chemin, ou ``None`` si un maillon manque ou n'est pas un objet."""
    for cle in chemin:
        if not isinstance(objet, dict) or cle not in objet:
            return None
        objet = objet[cle]
    return objet


def _nombre(valeur):
    """Un nombre de la source (entier ou ``Decimal``) ; ``None`` sinon : une mesure illisible reste inconnue."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, int):
        return valeur
    if isinstance(valeur, Decimal) and valeur.is_finite():
        return valeur
    return None


def _microdegres(coordonnee):
    nombre = _nombre(coordonnee)
    return None if nombre is None else int(Decimal(nombre) * 1_000_000)


def _distance_carree(localite, lieu):
    """Écart au carré, en microdegrés, entre une localité et le lieu ; la longitude pèse 0,7 (cos de 46 degrés)."""
    coordonnees = _valeur(localite, "geometry", "coordinates")
    if not isinstance(coordonnees, list) or len(coordonnees) != 2:
        return None
    longitude, latitude = _microdegres(coordonnees[0]), _microdegres(coordonnees[1])
    if longitude is None or latitude is None:
        return None
    d_lat = latitude - lieu["latitude_microdegres"]
    d_lon = (longitude - lieu["longitude_microdegres"]) * 7 // 10
    return d_lat * d_lat + d_lon * d_lon


def _point(prevision, zone):
    """Le point horaire au format du port, ou ``None`` si son horodatage est illisible (le point est ignoré)."""
    horodatage = _valeur(prevision, "timestamp")
    if not isinstance(horodatage, str):
        return None
    try:
        instant = dt.datetime.fromisoformat(horodatage)
    except ValueError:
        return None
    if instant.tzinfo is None:
        return None
    condition = _valeur(prevision, "condition", "en")
    verglas = None
    if isinstance(condition, str) and any(mot in condition.lower() for mot in _MOTS_VERGLAS):
        verglas = True
    return {
        "heure": instant.astimezone(zone).isoformat(timespec="seconds"),
        "temperature_c": _nombre(_valeur(prevision, "temperature", "value", "en")),
        "vent_kmh": _nombre(_valeur(prevision, "wind", "speed", "value", "en")),
        "rafales_kmh": None,
        "precipitation_mm_h": None,
        "probabilite_precipitation_pct": _nombre(_valeur(prevision, "lop", "value", "en")),
        "verglas": verglas,
    }


class FournisseurMscGeomet:
    """Fournisseur de prévisions : la page météo de la localité la plus proche, sur MSC GeoMet-OGC-API.

    À créer par ``creer_fournisseur_geomet`` (qui rend un verdict). Sans état, sans cache : une requête par appel."""

    def __init__(self, fuseau, delai_secondes=meteo_http.DELAI_DEFAUT_S, transport=None):
        if not meteo_http.delai_valide(delai_secondes):
            raise ValueError(f"delai_secondes : entier entre {meteo_http.DELAI_MIN_S} et {meteo_http.DELAI_MAX_S}")
        try:
            self._zone = ZoneInfo(fuseau)
        except (ZoneInfoNotFoundError, ValueError, OSError, TypeError) as exc:
            raise ValueError(f"fuseau {fuseau!r} introuvable dans la base des fuseaux du système") from exc
        self._delai = delai_secondes
        self._transport = meteo_http.transport_http if transport is None else transport

    def descripteur(self):
        """Métadonnées stables : la source, sa licence et l'attribution que celle-ci exige."""
        return {
            "fournisseur": FOURNISSEUR,
            "api": COLLECTION,
            "licence": LICENCE_ECCC,
            "version_licence": VERSION_LICENCE,
            "attribution": ATTRIBUTION_ECCC,
        }

    def _url(self, lieu):
        latitude, longitude = lieu["latitude_microdegres"], lieu["longitude_microdegres"]
        bbox = ",".join(
            meteo_http.degres(valeur)
            for valeur in (
                longitude - MARGE_BBOX_MICRODEG,
                latitude - MARGE_BBOX_MICRODEG,
                longitude + MARGE_BBOX_MICRODEG,
                latitude + MARGE_BBOX_MICRODEG,
            )
        )
        return f"{URL_ITEMS}?f=json&lang=en&limit={LIMITE_LOCALITES}&bbox={bbox}"

    def previsions(self, lieu, date_debut, date_fin):
        """Prévisions horaires de la localité la plus proche du lieu généralisé, ou un verdict. Voir
        ``FournisseurMeteo``.

        Une seule requête GET ; rien n'est écrit, rien n'est gardé. Les dates ne servent pas (la source rend sa fenêtre
        d'environ un jour) : une heure hors de la fenêtre est « sans donnée »."""
        if not meteo.est_lieu_generalise(lieu):
            return None, meteo.verdict_meteo(
                meteo.CODE_LIEU_TROP_PRECIS,
                "le lieu envoyé à un fournisseur météo est arrondi au dixième de degré (meteo.lieu_generalise) : "
                "l'adresse d'un chantier ne quitte jamais le serveur",
            )
        donnees, _, verdict = meteo_http.lire_json(self._transport, self._url(lieu), self._delai, "MSC GeoMet")
        if verdict is not None:
            return None, verdict
        localites = _valeur(donnees, "features")
        if not isinstance(localites, list):
            return None, _reponse_invalide("features : une liste est attendue")
        candidates = []
        for localite in localites:
            distance = _distance_carree(localite, lieu)
            groupe = _valeur(localite, "properties", "hourlyForecastGroup", "hourlyForecasts")
            if distance is not None and isinstance(groupe, list) and groupe:
                candidates.append((distance, str(_valeur(localite, "properties", "identifier")), localite))
        if not candidates:
            return None, _reponse_invalide("aucune page météo avec une prévision horaire près de ce lieu")
        _, identifiant, localite = min(candidates, key=lambda candidate: candidate[:2])
        emise_le = _valeur(localite, "properties", "lastUpdated")
        if not isinstance(emise_le, str) or emise_le.strip() == "":
            return None, _reponse_invalide("lastUpdated : l'heure de mise à jour de la page est introuvable")
        points = []
        vues = set()
        for prevision in _valeur(localite, "properties", "hourlyForecastGroup", "hourlyForecasts"):
            point = _point(prevision, self._zone)
            # Au retour à l'heure normale, une heure locale existe deux fois : la première est gardée (`meteo` ne
            # compare que l'heure locale, et une prévision qui la répète serait refusée en entier).
            if point is not None and point["heure"][:16] not in vues:
                vues.add(point["heure"][:16])
                points.append(point)
        if not points:
            return None, _reponse_invalide("hourlyForecasts : aucun point horaire lisible")
        nom = _valeur(localite, "properties", "name", "en")
        return {
            "citation": {
                "source": FOURNISSEUR,
                "emise_le": emise_le,
                "heure_type": HEURE_TYPE,
                "attribution": ATTRIBUTION_ECCC,
                "licence": LICENCE_ECCC,
                "collection": COLLECTION,
                "page_meteo": identifiant if not isinstance(nom, str) else f"{identifiant} ({nom})",
            },
            "points": points,
        }, None


def creer_fournisseur_geomet(fuseau, delai_secondes=meteo_http.DELAI_DEFAUT_S, transport=None):
    """Crée l'adaptateur après validation. Retourne ``(fournisseur, None)`` ou ``(None, verdict)``.

    ``fuseau`` : nom de la base des fuseaux (le profil météo l'exige avec un fournisseur), ex. ``America/Toronto`` ;
    ``delai_secondes`` : délai de socket, 1 à 30 ; ``transport`` : ``(url, delai) -> (corps, entetes)``, ``None`` pour
    le vrai réseau (les tests en donnent un fictif). Aucune connexion n'est ouverte ici."""
    try:
        return FournisseurMscGeomet(fuseau, delai_secondes, transport), None
    except ValueError as exc:
        return None, _refus(f"MSC GeoMet : {exc}")
