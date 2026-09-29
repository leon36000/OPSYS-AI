"""Transport HTTP des adaptateurs météo (PLAN T4.13, M4.10).

Avec ``distances_osrm.py``, le seul module de M4 qui ouvre une connexion réseau, et seulement quand un fournisseur météo
a été OUVERT par la configuration de l'entreprise (`opsys meteo declarer`, clé ``fournisseur``). Il est séparé de
``meteo.py`` pour que celui-ci reste sans entrée-sortie (un test le prouve par analyse du code) et pour que les tests
n'ouvrent jamais un socket : chaque adaptateur reçoit un ``transport`` (une fonction ``(url, delai) -> (corps,
entetes)``), et les tests lui en donnent un qui rend des réponses FICTIVES.

Garde-fous
    * HTTPS et un hôte de la liste fermée ``HOTES_PERMIS`` seulement : l'adresse d'un fournisseur ne vient jamais d'un
      appelant ni d'un agent, et aucune coordonnée ne peut partir ailleurs (un lieu de chantier est un renseignement
      personnel, Loi 25 ; l'adaptateur n'envoie de toute façon qu'un lieu GÉNÉRALISÉ au dixième de degré) ;
    * aucune redirection suivie : une redirection enverrait le lieu (et la clé d'API) ailleurs ;
    * délai borné (``DELAI_MIN_S`` à ``DELAI_MAX_S``) appliqué à chaque opération de socket. Le module ne lit aucune
      horloge (règle de M4) : il ne peut pas plafonner la durée TOTALE d'un serveur qui répond goutte à goutte ; la
      taille lue est, elle, plafonnée à ``TAILLE_MAX_REPONSE`` octets ;
    * toute erreur devient un verdict (réseau, délai, statut HTTP, JSON, forme). Les détails ne contiennent que des
    éléments
      stables (statut, nom de classe d'erreur) : jamais l'URL (elle porte le lieu et la clé), jamais un message
      d'exception.

Une panne n'est JAMAIS « ok » : le verdict rendu (``REJ-METEO-FOURNISSEUR-INDISPONIBLE`` ou
``REJ-METEO-REPONSE-INVALIDE``)
donne un créneau « inconnu » à l'appelant.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from . import meteo

DELAI_MIN_S = 1
DELAI_MAX_S = 30
DELAI_DEFAUT_S = 5
TAILLE_MAX_REPONSE = 4 * 1024 * 1024

HOTE_MSC_GEOMET = "api.weather.gc.ca"
HOTE_OPEN_METEO_COMMERCIAL = "customer-api.open-meteo.com"
# Liste FERMÉE. L'API gratuite d'Open-Meteo (`api.open-meteo.com`) n'y est PAS : elle est réservée à un usage non
# commercial.
HOTES_PERMIS = frozenset({HOTE_MSC_GEOMET, HOTE_OPEN_METEO_COMMERCIAL})

__all__ = [
    "DELAI_MIN_S",
    "DELAI_MAX_S",
    "DELAI_DEFAUT_S",
    "TAILLE_MAX_REPONSE",
    "HOTE_MSC_GEOMET",
    "HOTE_OPEN_METEO_COMMERCIAL",
    "HOTES_PERMIS",
    "delai_valide",
    "degres",
    "transport_http",
    "lire_json",
]


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    """Refuse de suivre une redirection : l'appelant reçoit l'erreur HTTP 3xx (donc un verdict)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Les mandataires de l'environnement (HTTPS_PROXY) restent permis : un fournisseur public n'est pas un sidecar local.
_OUVREUR = urllib.request.build_opener(_SansRedirection)


def delai_valide(delai_secondes):
    """Vrai si le délai est un entier de ``DELAI_MIN_S`` à ``DELAI_MAX_S`` secondes."""
    return type(delai_secondes) is int and DELAI_MIN_S <= delai_secondes <= DELAI_MAX_S


def degres(microdegres):
    """Microdegrés entiers -> texte décimal exact à 6 décimales (sans flottant)."""
    signe = "-" if microdegres < 0 else ""
    valeur = abs(microdegres)
    return f"{signe}{valeur // 1_000_000}.{valeur % 1_000_000:06d}"


def transport_http(url, delai_secondes):
    """Un GET HTTPS ; rend ``(corps, entetes)`` (noms d'en-tête en minuscules). Le transport par défaut des adaptateurs.

    Lève ``ValueError`` pour un schéma ou un hôte hors de ``HOTES_PERMIS`` (rien n'est envoyé), et les erreurs
    d'entrée-sortie de ``urllib`` sinon ; ``lire_json`` les convertit toutes en verdict."""
    morceaux = urllib.parse.urlsplit(url)
    if morceaux.scheme != "https" or morceaux.hostname not in HOTES_PERMIS:
        raise ValueError("hôte hors de la liste fermée des fournisseurs météo")
    requete = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "opsys-m4-meteo"},
    )
    with _OUVREUR.open(requete, timeout=delai_secondes) as reponse:
        corps = reponse.read(TAILLE_MAX_REPONSE + 1)
        entetes = {nom.lower(): valeur for nom, valeur in reponse.headers.items()}
    return corps, entetes


def _indisponible(detail):
    return meteo.verdict_meteo(meteo.CODE_FOURNISSEUR_INDISPONIBLE, detail)


def _reponse_invalide(detail):
    return meteo.verdict_meteo(meteo.CODE_REPONSE_INVALIDE, detail)


def _refuser_constante(nom):
    raise ValueError(f"constante JSON refusée : {nom}")


def lire_json(transport, url, delai_secondes, fournisseur):
    """``(objet JSON, entetes, None)`` ou ``(None, None, verdict)``. Ne lève rien.

    Les décimaux JSON sont lus en ``Decimal`` exact (aucun flottant). ``fournisseur`` (nom) sert aux messages."""
    try:
        reponse = transport(url, delai_secondes)
    except urllib.error.HTTPError as exc:
        return None, None, _indisponible(f"{fournisseur} a répondu HTTP {exc.code}")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return None, None, _indisponible(f"{fournisseur} sans réponse en {delai_secondes} s (délai dépassé)")
        return None, None, _indisponible(f"{fournisseur} injoignable ({type(exc.reason).__name__})")
    except TimeoutError:
        return None, None, _indisponible(f"{fournisseur} sans réponse en {delai_secondes} s (délai dépassé)")
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return None, None, _indisponible(f"échec de la requête à {fournisseur} ({type(exc).__name__})")
    if not isinstance(reponse, tuple) or len(reponse) != 2:
        return None, None, _reponse_invalide(f"{fournisseur} : le transport doit rendre (octets, en-têtes)")
    corps, entetes = reponse
    if not isinstance(corps, (bytes, bytearray)) or not isinstance(entetes, dict):
        return None, None, _reponse_invalide(f"{fournisseur} : le transport doit rendre (octets, en-têtes)")
    if len(corps) > TAILLE_MAX_REPONSE:
        return None, None, _reponse_invalide(f"réponse de {fournisseur} de plus de {TAILLE_MAX_REPONSE} octets")
    try:
        donnees = json.loads(bytes(corps).decode("utf-8"), parse_float=Decimal, parse_constant=_refuser_constante)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, None, _reponse_invalide(f"réponse de {fournisseur} : JSON invalide")
    return donnees, {str(nom).lower(): valeur for nom, valeur in entetes.items()}, None
