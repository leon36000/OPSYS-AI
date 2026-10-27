"""Adaptateur OSRM du port ``FournisseurMatrice`` (PLAN T4.1-b, R15 §2 palier 1).

OPTIONNEL et jamais appelé par défaut : ``distances.obtenir_matrice`` ne le touche que si l'appelant
lui en passe un. C'est le SEUL module de M4 qui ouvre une connexion réseau ; il est séparé de
``distances.py`` pour que celui-ci reste sans entrée-sortie (test d'analyse du code).

Ce que l'adaptateur appelle : le service `table` d'un sidecar OSRM LOCAL (R15 : « jamais de serveur
de démonstration tiers » : les coordonnées d'un chantier sont un renseignement personnel, Loi 25).

    GET {url_base}/table/v1/{profil}/{lon},{lat};{lon},{lat};...?annotations=duration,distance

Forme de réponse attendue, d'après la documentation d'OSRM :
    https://project-osrm.org/docs/v5.24.0/api/#table-service
    https://project-osrm.org/docs/v26.4.0/http#table-service
    * HTTP 200 et ``{"code": "Ok", "durations": [[...]], "distances": [[...]], ...}`` ;
    * ``durations[i][j]`` : secondes de la source i vers la destination j ; ``distances[i][j]`` :
      mètres du trajet LE PLUS RAPIDE (pas le plus court) ; matrices en ordre de lignes, ``null`` si
      aucune route n'existe entre i et j ; nombres JSON pouvant être décimaux (192.6) ;
    * en cas d'erreur : HTTP 400 et ``{"code": "<InvalidQuery|NoSegment|TooBig|NoTable|...>",
      "message": "..."}`` ;
    * ``sources`` et ``destinations`` (waypoints avec noms de rue et « hint ») sont ignorés : on ne
      lit, ne garde et ne recopie que les deux matrices.
    Une requête sans ``sources`` ni ``destinations`` demande la matrice n×n de tous les points ; le
    nombre de points est limité par ``osrm-routed --max-table-size`` (100 par défaut :
    https://project-osrm.org/docs/v26.4.0/tools).
    Non vérifié contre un vrai sidecar : la documentation illustre ``annotations=distance`` par
    « for CH » ; à confirmer sur l'installation réelle. Une réponse sans matrice ``distances`` valide
    est un verdict (``REJ-MATRICE-REPONSE-INVALIDE``) puis un repli marqué, jamais des mètres inventés.
    L'option ``fallback_speed`` d'OSRM n'est JAMAIS demandée : elle remplacerait en silence un trajet
    introuvable par une ligne droite. Une cellule ``null`` devient ``REJ-MATRICE-TRAJET-INTROUVABLE``.

Aucun flottant : le JSON est lu avec ``Decimal`` ; les secondes sont arrondies au plafond (on ne
sous-estime jamais un trajet), les mètres au plus proche (demi vers le haut).

Garde-fous
    * l'URL doit désigner un sidecar LOCAL : ``localhost``, adresse de boucle locale ou privée (hors
      liaison locale), ou nom de service sans point (réseau de conteneurs). Toute autre adresse est
      refusée à la configuration : aucune coordonnée ne sort. Limite connue : on ne résout pas le
      DNS ; un nom sans point est réputé interne au réseau de conteneurs ;
    * aucune redirection suivie (un sidecar ne devrait pas rediriger, et une redirection enverrait les
      coordonnées ailleurs) ; aucun mandataire (variables ``HTTP_PROXY``) : le trafic reste local ;
    * délai borné (``DELAI_MIN_S`` à ``DELAI_MAX_S``) appliqué à chaque opération de socket. Le module
      ne lit aucune horloge (règle de M4) : il ne peut donc pas plafonner la durée TOTALE d'un serveur
      qui répond goutte à goutte ; la taille lue est, elle, plafonnée à ``TAILLE_MAX_REPONSE`` octets ;
    * toute erreur devient un verdict (réseau, délai, statut HTTP, JSON, forme, valeurs). Les détails
      ne contiennent que des éléments stables (code OSRM, statut, nom de classe d'erreur) : jamais de
      message d'exception ni de coordonnée, pour que la marque de repli d'une matrice se reproduise.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from . import distances, verdicts

DELAI_MIN_S = 1
DELAI_MAX_S = 30
DELAI_DEFAUT_S = 5
TAILLE_MAX_REPONSE = 8 * 1024 * 1024
MODE_OSRM = "osrm_table"
PROFIL_DEFAUT = "driving"
# Politique conservatrice du transport actuel, distincte de la capacité de calcul globale.
MAX_POINTS_REQUETE = 100

# Plafond de plausibilité d'une cellule (1 000 000 km ou ≈ 11,5 jours) : au-delà, la réponse est
# rejetée comme invalide plutôt que transmise au solveur.
_CELLULE_MAX = 10**9

_MOTIF_PROFIL = re.compile(r"[a-z][a-z0-9_]{0,31}")
_MOTIF_VERSION_DONNEES = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_MOTIF_CODE_OSRM = re.compile(r"[A-Za-z]{1,32}")

__all__ = [
    "DELAI_MIN_S",
    "DELAI_MAX_S",
    "DELAI_DEFAUT_S",
    "TAILLE_MAX_REPONSE",
    "MODE_OSRM",
    "MAX_POINTS_REQUETE",
    "PROFIL_DEFAUT",
    "FournisseurOsrm",
    "creer_fournisseur_osrm",
]


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    """Refuse de suivre une redirection : l'appelant reçoit l'erreur HTTP 3xx (donc un verdict)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OUVREUR = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SansRedirection)


def _hote_local(hote):
    nom = hote.lower()
    if nom == "localhost" or nom.endswith(".localhost"):
        return True
    try:
        adresse = ipaddress.ip_address(nom)
    except ValueError:
        return "." not in nom  # nom de service d'un réseau de conteneurs
    if adresse.version == 6 and adresse.ipv4_mapped is not None:
        adresse = adresse.ipv4_mapped  # ::ffff:8.8.8.8 est l'adresse publique 8.8.8.8, pas une adresse privée
    if adresse.is_unspecified or adresse.is_link_local or adresse.is_multicast:
        return False
    return adresse.is_loopback or adresse.is_private


def _valider_configuration(url_base, version_donnees, profil, delai_secondes):
    """Retourne (configuration normalisée, None) ou (None, message de refus)."""
    if not isinstance(url_base, str) or not url_base:
        return None, "url_base : l'URL du sidecar OSRM local est à fournir (ex. http://127.0.0.1:5000)"
    try:
        morceaux = urllib.parse.urlsplit(url_base)
        hote = morceaux.hostname
        morceaux.port  # noqa: B018 : lève ValueError si le port est invalide
    except ValueError:
        return None, "url_base : URL invalide"
    if morceaux.scheme not in ("http", "https") or not hote:
        return None, "url_base : schéma http ou https et un hôte sont requis"
    if morceaux.username is not None or morceaux.password is not None:
        return None, "url_base : aucun identifiant dans l'URL"
    if morceaux.path not in ("", "/") or morceaux.query or morceaux.fragment:
        return None, "url_base : ni chemin, ni requête, ni fragment (seulement schéma, hôte et port)"
    if not _hote_local(hote):
        return None, (
            "url_base : l'hôte doit être un sidecar LOCAL (localhost, boucle locale, réseau privé ou nom de "
            "service sans point) : les coordonnées d'un chantier ne sortent pas du serveur (Loi 25)"
        )
    if not isinstance(version_donnees, str) or not _MOTIF_VERSION_DONNEES.fullmatch(version_donnees):
        return None, (
            "version_donnees : l'instantané de l'extrait routier épinglé est à fournir "
            "(ex. quebec-260927 ; lettres, chiffres, point, tiret, 64 caractères au plus)"
        )
    if not isinstance(profil, str) or not _MOTIF_PROFIL.fullmatch(profil):
        return None, "profil : nom de profil OSRM en minuscules (ex. driving)"
    if type(delai_secondes) is not int or not DELAI_MIN_S <= delai_secondes <= DELAI_MAX_S:
        return None, f"delai_secondes : entier entre {DELAI_MIN_S} et {DELAI_MAX_S}"
    base = f"{morceaux.scheme}://{morceaux.netloc}"
    return {
        "url_base": base, "version_donnees": version_donnees, "profil": profil, "delai_secondes": delai_secondes,
    }, None


def creer_fournisseur_osrm(url_base, version_donnees, profil=PROFIL_DEFAUT, delai_secondes=DELAI_DEFAUT_S):
    """Crée l'adaptateur après validation. Retourne (fournisseur, None) ou (None, verdict).

    ``url_base`` : sidecar LOCAL, ex. ``http://127.0.0.1:5000`` (voir les garde-fous du module).
    ``version_donnees`` : nom de l'instantané de l'extrait routier (ex. ``quebec-260927``) ; il entre
    dans l'empreinte de la matrice, pour qu'un changement de données routières change l'empreinte.
    ``profil`` : segment de profil de l'URL OSRM. ``delai_secondes`` : délai de socket, 1 à 30.
    Aucune connexion n'est ouverte ici.
    """
    configuration, refus = _valider_configuration(url_base, version_donnees, profil, delai_secondes)
    if refus is not None:
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail=refus)
    return FournisseurOsrm(**configuration), None


def _degres(microdegres):
    """Microdegrés entiers -> texte décimal exact à 6 décimales (sans flottant)."""
    signe = "-" if microdegres < 0 else ""
    valeur = abs(microdegres)
    return f"{signe}{valeur // 1_000_000}.{valeur % 1_000_000:06d}"


def _refuser_constante(nom):
    raise ValueError(f"constante JSON refusée : {nom}")


def _reponse_invalide(detail):
    return distances.verdict_matrice(distances.CODE_REPONSE_INVALIDE, detail)


def _indisponible(detail):
    return distances.verdict_matrice(distances.CODE_FOURNISSEUR_INDISPONIBLE, detail)


def _code_osrm(corps):
    """Code d'erreur OSRM lisible dans un corps de réponse, ou ``inconnu`` (jamais le message libre)."""
    try:
        donnees = json.loads(corps.decode("utf-8"), parse_float=Decimal, parse_constant=_refuser_constante)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return "inconnu"
    code = donnees.get("code") if isinstance(donnees, dict) else None
    return code if isinstance(code, str) and _MOTIF_CODE_OSRM.fullmatch(code) else "inconnu"


def _cellule(valeur, arrondi):
    """Cellule JSON -> entier, ou None si invalide (booléen, texte, négatif, hors plage)."""
    if type(valeur) is int:
        nombre = Decimal(valeur)
    elif isinstance(valeur, Decimal) and valeur.is_finite():
        nombre = valeur
    else:
        return None
    if nombre < 0 or nombre > _CELLULE_MAX:
        return None
    return int(nombre.to_integral_value(rounding=arrondi))


def _lire_table(donnees, cle, n, arrondi, ids):
    """Retourne (table d'entiers, None) ou (None, verdict)."""
    table = donnees.get(cle)
    if not isinstance(table, list) or len(table) != n:
        return None, _reponse_invalide(f"{cle} : matrice de {n} lignes attendue")
    resultat = []
    introuvables = []
    for i, ligne in enumerate(table):
        if not isinstance(ligne, list) or len(ligne) != n:
            return None, _reponse_invalide(f"{cle} : ligne {i} de {n} colonnes attendue")
        entiers = []
        for j, valeur in enumerate(ligne):
            if valeur is None:
                introuvables.append(f"{ids[i]}->{ids[j]}")
                entiers.append(0)
                continue
            entier = _cellule(valeur, arrondi)
            if entier is None:
                return None, _reponse_invalide(f"{cle} : valeur invalide ligne {i}, colonne {j}")
            if i == j and entier != 0:
                return None, _reponse_invalide(f"{cle} : diagonale non nulle ligne {i}")
            entiers.append(entier)
        resultat.append(entiers)
    if introuvables:
        montrees = ", ".join(introuvables[:5]) + (", ..." if len(introuvables) > 5 else "")
        return None, distances.verdict_matrice(
            distances.CODE_TRAJET_INTROUVABLE,
            f"OSRM ne trouve aucune route pour {len(introuvables)} trajet(s) ({montrees}) : vérifier les coordonnées",
        )
    return resultat, None


class FournisseurOsrm:
    """Fournisseur de trajets routiers : service `table` d'un sidecar OSRM local.

    À créer par ``creer_fournisseur_osrm`` (qui rend un verdict) ; le constructeur valide aussi et lève
    ``ValueError`` si la configuration est refusée. Sans état, sans cache : une requête par matrice.
    """

    def __init__(self, url_base, version_donnees, profil=PROFIL_DEFAUT, delai_secondes=DELAI_DEFAUT_S):
        configuration, refus = _valider_configuration(url_base, version_donnees, profil, delai_secondes)
        if refus is not None:
            raise ValueError(refus)
        self._url_base = configuration["url_base"]
        self._version_donnees = configuration["version_donnees"]
        self._profil = configuration["profil"]
        self._delai_secondes = configuration["delai_secondes"]

    def descripteur(self):
        """Métadonnées stables, dans l'empreinte de la matrice. L'URL n'y figure pas (configuration locale)."""
        return {
            "mode_distance": MODE_OSRM,
            "fournisseur": "osrm",
            "api": "table/v1",
            "profil": self._profil,
            "version_donnees": self._version_donnees,
        }

    def _url(self, points):
        coordonnees = ";".join(
            f"{_degres(p['longitude_microdeg'])},{_degres(p['latitude_microdeg'])}" for p in points
        )
        return f"{self._url_base}/table/v1/{self._profil}/{coordonnees}?annotations=duration,distance"

    def _delai_depasse(self):
        return _indisponible(f"sidecar OSRM sans réponse en {self._delai_secondes} s (délai dépassé)")

    def _requete(self, url):
        """Retourne (octets, None) ou (None, verdict). Toute exception d'E/S devient un verdict."""
        requete = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with _OUVREUR.open(requete, timeout=self._delai_secondes) as reponse:
                corps = reponse.read(TAILLE_MAX_REPONSE + 1)
        except urllib.error.HTTPError as exc:
            try:
                partiel = exc.read(TAILLE_MAX_REPONSE + 1)
            except (OSError, http.client.HTTPException):
                partiel = b""
            code = _code_osrm(partiel) if len(partiel) <= TAILLE_MAX_REPONSE else "inconnu"
            if code == "NoSegment":
                return None, distances.verdict_matrice(
                    distances.CODE_TRAJET_INTROUVABLE,
                    "OSRM ne peut rattacher un point au réseau routier (NoSegment) : vérifier les coordonnées",
                )
            return None, _indisponible(f"OSRM a répondu HTTP {exc.code} (code {code})")
        except urllib.error.URLError as exc:
            # urllib enveloppe l'échec de connexion, y compris un délai dépassé, dans une URLError.
            if isinstance(exc.reason, TimeoutError):
                return None, self._delai_depasse()
            return None, _indisponible(f"sidecar OSRM injoignable ({type(exc.reason).__name__})")
        except TimeoutError:
            return None, self._delai_depasse()
        except (OSError, http.client.HTTPException, ValueError) as exc:
            return None, _indisponible(f"échec de la requête OSRM ({type(exc).__name__})")
        if len(corps) > TAILLE_MAX_REPONSE:
            return None, _reponse_invalide(f"réponse OSRM de plus de {TAILLE_MAX_REPONSE} octets")
        return corps, None

    def trajets(self, points):
        """Trajets bruts (sans marge) entre ``points``, en ordre d'identifiant. Voir ``FournisseurMatrice``.

        Retourne ``({"metres": [[int]], "secondes": [[int]]}, None)`` ou ``(None, verdict)``. Une seule
        requête GET vers le sidecar ; rien n'est écrit, rien n'est gardé.
        """
        tries, verdict = distances.valider_points(points)
        if verdict is not None:
            return None, verdict
        if len(tries) > MAX_POINTS_REQUETE:
            return None, _indisponible(
                f"transport OSRM limité à {MAX_POINTS_REQUETE} positions par requête ; "
                "matrice par blocs non qualifiée : repli global explicite requis",
            )
        corps, verdict = self._requete(self._url(tries))
        if verdict is not None:
            return None, verdict
        try:
            donnees = json.loads(corps.decode("utf-8"), parse_float=Decimal, parse_constant=_refuser_constante)
        except (UnicodeDecodeError, ValueError, RecursionError):
            return None, _reponse_invalide("réponse OSRM : JSON invalide")
        if not isinstance(donnees, dict):
            return None, _reponse_invalide("réponse OSRM : un objet JSON est attendu")
        code = donnees.get("code")
        if code != "Ok":
            code_lisible = code if isinstance(code, str) and _MOTIF_CODE_OSRM.fullmatch(code) else "inconnu"
            if code_lisible == "NoSegment":
                return None, distances.verdict_matrice(
                    distances.CODE_TRAJET_INTROUVABLE,
                    "OSRM ne peut rattacher un point au réseau routier (NoSegment) : vérifier les coordonnées",
                )
            return None, _indisponible(f"OSRM a refusé la requête (code {code_lisible})")
        ids = [p["id"] for p in tries]
        n = len(tries)
        secondes, verdict = _lire_table(donnees, "durations", n, ROUND_CEILING, ids)
        if verdict is not None:
            return None, verdict
        metres, verdict = _lire_table(donnees, "distances", n, ROUND_HALF_UP, ids)
        if verdict is not None:
            return None, verdict
        return {"metres": metres, "secondes": secondes}, None
