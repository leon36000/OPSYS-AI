"""Adaptateur Open-Meteo du port ``FournisseurMeteo`` (PLAN T4.13, M4.10, R7 §2).

FERMÉ par la configuration, et deux fois : le profil météo doit déclarer ``fournisseur: open_meteo`` ET un forfait
COMMERCIAL (`opsys-metier meteo declarer`), et la clé d'API doit être dans la variable d'environnement que le profil
nomme.
Sans forfait commercial, la création est REFUSÉE (``REJ-METEO-FOURNISSEUR-FERME``) : jamais une requête part.

Pourquoi. Conditions d'utilisation lues le 2026-09-29 sur https://open-meteo.com/en/terms : l'API GRATUITE est réservée
à un usage NON COMMERCIAL (moins de 10 000 appels par jour ; « operating websites or apps that have subscriptions or
display advertisements », « integrating our service into commercial products » sont des usages commerciaux) ; l'usage
commercial exige un forfait payant (Standard, Professional ou Enterprise), servi par le préfixe ``customer-`` du serveur
et le paramètre ``apikey`` (https://open-meteo.com/en/docs). OPSYS-AI sert une entreprise : ouvrir Open-Meteo est donc
une DÉCISION DU PROPRIÉTAIRE (GATE NATHAN, PLAN T4.13), avec son forfait. L'adaptateur existe ; il ne s'ouvre pas tout
seul. Le serveur gratuit (``api.open-meteo.com``) ne figure pas dans la liste fermée des hôtes
(``meteo_http.HOTES_PERMIS``).

Données : licence CC BY 4.0 (https://open-meteo.com/en/licence, lue le 2026-09-29) : citer « Weather data by
Open-Meteo.com » avec un lien vers https://open-meteo.com/ (``ATTRIBUTION_OPEN_METEO``, rendue à chaque résultat). Le
code serveur d'Open-Meteo est sous AGPL-3.0 : il n'est pas exécuté ici, seule l'API hébergée est consommée en HTTP.

    GET https://customer-api.open-meteo.com/v1/forecast?latitude=..&longitude=..&hourly=temperature_2m,precipitation,
        precipitation_probability,wind_speed_10m,wind_gusts_10m,weather_code&wind_speed_unit=kmh&temperature_unit=celsius
        &precipitation_unit=mm&timezone=<fuseau>&start_date=..&end_date=..&apikey=<clé>

Forme lue (documentation d'Open-Meteo, https://open-meteo.com/en/docs, lue le 2026-09-29) : ``hourly.time`` en heure
LOCALE (``AAAA-MM-JJTHH:MM``) quand ``timezone`` est fourni, un tableau par variable de même longueur,
``utc_offset_seconds``. Le tableau ``precipitation`` et ``wind_gusts_10m`` résument l'heure PRÉCÉDENTE (le module
``meteo`` inclut donc les deux bouts d'un créneau). ``weather_code`` suit les codes WMO : 56, 57 (bruine verglaçante) et
66, 67 (pluie verglaçante) donnent ``verglas`` vrai, tout autre code faux ; sans code, ``None``.

L'API ne date pas sa prévision : l'heure citée est l'en-tête HTTP ``Date`` de la réponse (``HEURE_TYPE``), celle du
serveur du fournisseur, jamais une horloge de M4 ; sans elle, la réponse est refusée (une prévision sans heure ne se
cite pas).
"""

from __future__ import annotations

import datetime as dt
import email.utils
import urllib.parse
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import meteo, meteo_http, verdicts

FOURNISSEUR = "open_meteo"
URL_PREVISIONS = f"https://{meteo_http.HOTE_OPEN_METEO_COMMERCIAL}/v1/forecast"
FORFAIT_COMMERCIAL = "commercial"
ATTRIBUTION_OPEN_METEO = "Weather data by Open-Meteo.com (https://open-meteo.com/), licence CC BY 4.0"
LICENCE_OPEN_METEO = "https://open-meteo.com/en/licence"
HEURE_TYPE = "reponse_http_du_fournisseur"
VARIABLES = (
    "temperature_2m",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_gusts_10m",
    "weather_code",
)
# variable Open-Meteo -> champ du point du port
_CHAMPS = {
    "temperature_2m": "temperature_c",
    "precipitation": "precipitation_mm_h",
    "precipitation_probability": "probabilite_precipitation_pct",
    "wind_speed_10m": "vent_kmh",
    "wind_gusts_10m": "rafales_kmh",
}
CODES_WMO_VERGLAS = (56, 57, 66, 67)

__all__ = [
    "FOURNISSEUR",
    "URL_PREVISIONS",
    "FORFAIT_COMMERCIAL",
    "ATTRIBUTION_OPEN_METEO",
    "LICENCE_OPEN_METEO",
    "HEURE_TYPE",
    "VARIABLES",
    "CODES_WMO_VERGLAS",
    "FournisseurOpenMeteo",
    "creer_fournisseur_open_meteo",
]


def _ferme(detail):
    return meteo.verdict_meteo(meteo.CODE_FOURNISSEUR_FERME, detail)


def _reponse_invalide(detail):
    return meteo.verdict_meteo(meteo.CODE_REPONSE_INVALIDE, f"Open-Meteo : {detail}")


def _nombre_ou_none(valeur):
    """Un nombre de la source (entier ou ``Decimal``), ``None`` pour null ; ``False`` si la valeur n'est ni l'un ni
    l'autre."""
    if valeur is None:
        return None
    if isinstance(valeur, bool):
        return False
    if isinstance(valeur, int) or (isinstance(valeur, Decimal) and valeur.is_finite()):
        return valeur
    return False


def _decalage(secondes):
    """Décalage UTC ISO (``-04:00``) d'un nombre de secondes entier."""
    signe = "-" if secondes < 0 else "+"
    minutes = abs(secondes) // 60
    return f"{signe}{minutes // 60:02d}:{minutes % 60:02d}"


def _heure_de_reponse(entetes):
    """L'en-tête ``Date`` en ISO 8601 UTC, ou ``None`` s'il manque ou est illisible."""
    brut = entetes.get("date")
    if not isinstance(brut, str):
        return None
    try:
        instant = email.utils.parsedate_to_datetime(brut)
    except (TypeError, ValueError, IndexError):
        return None
    if instant is None or instant.tzinfo is None:
        return None
    return instant.astimezone(dt.UTC).isoformat(timespec="seconds")


class FournisseurOpenMeteo:
    """Fournisseur de prévisions : l'API commerciale d'Open-Meteo, hôte ``customer-api``.

    À créer par ``creer_fournisseur_open_meteo`` (qui rend un verdict) ; le constructeur valide aussi et lève
    ``ValueError`` si la configuration est refusée. Sans état, sans cache : une requête par appel."""

    def __init__(self, forfait, cle_api, fuseau, delai_secondes=meteo_http.DELAI_DEFAUT_S, transport=None):
        if forfait != FORFAIT_COMMERCIAL:
            raise ValueError(
                "l'API gratuite d'Open-Meteo est réservée à un usage NON commercial (conditions lues le 2026-09-29) "
                ": ouvrir ce fournisseur est une décision du propriétaire, avec un forfait commercial (forfait: "
                "commercial)"
            )
        if not isinstance(cle_api, str) or cle_api.strip() == "":
            raise ValueError(
                "la clé d'API du forfait commercial est absente : elle se lit dans la variable d'environnement que le "
                "profil météo nomme (open_meteo.cle_env), jamais dans le profil ni dans le code"
            )
        if not meteo_http.delai_valide(delai_secondes):
            raise ValueError(f"delai_secondes : entier entre {meteo_http.DELAI_MIN_S} et {meteo_http.DELAI_MAX_S}")
        try:
            ZoneInfo(fuseau)
        except (ZoneInfoNotFoundError, ValueError, OSError, TypeError) as exc:
            raise ValueError(f"fuseau {fuseau!r} introuvable dans la base des fuseaux du système") from exc
        self._cle_api = cle_api
        self._fuseau = fuseau
        self._delai = delai_secondes
        self._transport = meteo_http.transport_http if transport is None else transport

    def descripteur(self):
        """Métadonnées stables (la clé d'API n'y figure jamais)."""
        return {
            "fournisseur": FOURNISSEUR,
            "api": "v1/forecast",
            "forfait": FORFAIT_COMMERCIAL,
            "licence": LICENCE_OPEN_METEO,
            "attribution": ATTRIBUTION_OPEN_METEO,
        }

    def _url(self, lieu, date_debut, date_fin):
        requete = urllib.parse.urlencode(
            {
                "latitude": meteo_http.degres(lieu["latitude_microdegres"]),
                "longitude": meteo_http.degres(lieu["longitude_microdegres"]),
                "hourly": ",".join(VARIABLES),
                "wind_speed_unit": "kmh",
                "temperature_unit": "celsius",
                "precipitation_unit": "mm",
                "timezone": self._fuseau,
                "start_date": date_debut,
                "end_date": date_fin,
                "apikey": self._cle_api,
            }
        )
        return f"{URL_PREVISIONS}?{requete}"

    def previsions(self, lieu, date_debut, date_fin):
        """Prévisions horaires du lieu généralisé pour ``[date_debut, date_fin]``, ou un verdict. Voir
        ``FournisseurMeteo``.

        Une seule requête GET ; rien n'est écrit, rien n'est gardé. Le verdict ne cite jamais l'URL (lieu et clé)."""
        if not meteo.est_lieu_generalise(lieu):
            return None, meteo.verdict_meteo(
                meteo.CODE_LIEU_TROP_PRECIS,
                "le lieu envoyé à un fournisseur météo est arrondi au dixième de degré (meteo.lieu_generalise) : "
                "l'adresse d'un chantier ne quitte jamais le serveur",
            )
        if not meteo.est_date(date_debut) or not meteo.est_date(date_fin) or date_debut > date_fin:
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail="dates AAAA-MM-JJ attendues, la première au plus égale à la seconde",
            )
        donnees, entetes, verdict = meteo_http.lire_json(
            self._transport,
            self._url(lieu, date_debut, date_fin),
            self._delai,
            "Open-Meteo",
        )
        if verdict is not None:
            return None, verdict
        if isinstance(donnees, dict) and donnees.get("error") is True:
            return None, meteo.verdict_meteo(
                meteo.CODE_FOURNISSEUR_INDISPONIBLE,
                "Open-Meteo a refusé la requête (error: true)",
            )
        horaire = donnees.get("hourly") if isinstance(donnees, dict) else None
        decalage = donnees.get("utc_offset_seconds") if isinstance(donnees, dict) else None
        temps = horaire.get("time") if isinstance(horaire, dict) else None
        if not isinstance(temps, list) or not temps or isinstance(decalage, bool) or not isinstance(decalage, int):
            return None, _reponse_invalide("hourly.time et utc_offset_seconds : forme inattendue")
        tableaux = {}
        for variable in VARIABLES:
            tableau = horaire.get(variable)
            if not isinstance(tableau, list) or len(tableau) != len(temps):
                return None, _reponse_invalide(f"hourly.{variable} : un tableau de {len(temps)} valeurs est attendu")
            tableaux[variable] = tableau
        emise_le = _heure_de_reponse(entetes)
        if emise_le is None:
            return None, _reponse_invalide("en-tête Date absent ou illisible : une prévision sans heure ne se cite pas")
        suffixe = _decalage(decalage)
        points = []
        for rang, heure in enumerate(temps):
            if not isinstance(heure, str) or len(heure) != 16:
                return None, _reponse_invalide(f"hourly.time[{rang}] : AAAA-MM-JJTHH:MM attendu")
            point = {"heure": f"{heure}:00{suffixe}"}
            for variable, champ in _CHAMPS.items():
                valeur = _nombre_ou_none(tableaux[variable][rang])
                if valeur is False:
                    return None, _reponse_invalide(f"hourly.{variable}[{rang}] : nombre ou null attendu")
                point[champ] = valeur
            code = _nombre_ou_none(tableaux["weather_code"][rang])
            if code is False:
                return None, _reponse_invalide(f"hourly.weather_code[{rang}] : nombre ou null attendu")
            point["verglas"] = None if code is None else int(code) in CODES_WMO_VERGLAS
            points.append(point)
        return {
            "citation": {
                "source": FOURNISSEUR,
                "emise_le": emise_le,
                "heure_type": HEURE_TYPE,
                "attribution": ATTRIBUTION_OPEN_METEO,
                "licence": LICENCE_OPEN_METEO,
                "forfait": FORFAIT_COMMERCIAL,
            },
            "points": points,
        }, None


def creer_fournisseur_open_meteo(forfait, cle_api, fuseau, delai_secondes=meteo_http.DELAI_DEFAUT_S, transport=None):
    """Crée l'adaptateur après validation. Retourne ``(fournisseur, None)`` ou ``(None, verdict)``.

    Refuse, sans rien ouvrir : un forfait qui n'est pas ``commercial`` (l'API gratuite est non commerciale), une clé
    d'API absente, un fuseau inconnu, un délai hors bornes. ``transport`` : ``None`` pour le vrai réseau (les tests en
    donnent un fictif). Aucune connexion n'est ouverte ici."""
    try:
        return FournisseurOpenMeteo(forfait, cle_api, fuseau, delai_secondes, transport), None
    except ValueError as exc:
        return None, _ferme(f"Open-Meteo fermé : {exc}")
