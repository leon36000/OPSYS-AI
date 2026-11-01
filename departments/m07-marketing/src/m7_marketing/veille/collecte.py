"""La COLLECTE de sources publiques autorisées : un port de transport SANS implémentation réelle, et le collecteur
qui l'encadre.

AUCUN transport réel n'est branché dans ce dépôt : `TransportPublicNonBranche` est le seul transport par défaut et il
refuse
(`REJ-VEILLE-TRANSPORT-NON-BRANCHE`). Le port ne connaît que l'URL et l'agent déclaré : ni en-tête, ni cookie, ni
authentification, et il ne suit AUCUNE redirection (le collecteur les suit à la main, une à une, en les revalidant).

Le collecteur ne demande qu'une source DÉCLARÉE d'un concurrent ACTIF (`registre.sources_actives`), et pour chaque
hôte :
1. il lit d'abord `https://<hôte>/robots.txt` par le même port (une seule fois par tour) et applique la RFC 9309
(`robots.py`) avec
   l'agent `OpsysVeille/1.0` : un chemin interdit n'est JAMAIS demandé (`REJ-VEILLE-ROBOTS-INTERDIT`) ; un `robots.txt`
   inaccessible (5xx, délai, 401 ou 403 — plus strict que la RFC, car on ne contourne aucune authentification)
   interdit tout ;
2. il respecte `Crawl-delay` et un délai minimal par hôte (10 s) en REFUSANT (`REJ-VEILLE-DELAI-NON-ECOULE`,
reprenable, avec les
   secondes à attendre) plutôt qu'en dormant : l'horloge est injectée. Le délai se compte entre deux PAGES du même
   hôte ;
3. il suit au plus 3 redirections, chacune revalidée (https, hôte déclaré, aucune plateforme, aucun identifiant,
robots) : un saut
   hors des hôtes déclarés est refusé (`REJ-VEILLE-REDIRECTION-HORS-DOMAINE`) ;
4. 401 et 403 deviennent un fait « accès refusé » : jamais de contournement ni de second essai d'une autre façon ; 404
et 410, un
   fait « absente » ; 429 et 5xx, un échec reprenable ;
5. types de contenu permis : texte, HTML, XML ; au plus 1 Mio ; décodé en UTF-8 avec remplacement, jamais exécuté.

Ce qui n'est PAS prouvé : rien n'a été collecté chez un vrai site (aucun réseau). Le délai par hôte est tenu en
mémoire d'un
collecteur, pas d'un tour à l'autre. Les conditions d'utilisation d'un site peuvent interdire ce que son `robots.txt`
permet : le
client reste responsable du choix de ses sources.

Module sans entrée-sortie : aucun module réseau n'est importé (un test le vérifie sur la source).
"""

from __future__ import annotations

import dataclasses
import math
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from . import observations, registre, robots
from .registre import Concurrent, ErreurVeille, Source

AGENT_UTILISATEUR = "OpsysVeille/1.0 (veille déclarée par le client)"
AGENT_ROBOTS = "OpsysVeille/1.0"
TYPES_PERMIS = frozenset({"text/html", "application/xhtml+xml", "application/xml", "text/xml", "text/plain"})
OCTETS_MAX = 1024 * 1024
DELAI_MIN_DEFAUT_S = 10
SAUTS_MAX = 3
PAGES_MAX_DEFAUT = 20
DELAI_HTTP_S = 20.0
ERREURS_QUI_ARRETENT_LE_TOUR = frozenset({"REJ-VEILLE-TRANSPORT-NON-BRANCHE", "REJ-VEILLE-LIMITE-PAGES"})


@dataclasses.dataclass(frozen=True)
class ReponsePublique:
    """Ce que le transport rend : statut, en-têtes (clés en minuscules), corps en octets, URL finale éventuelle."""

    statut: int
    en_tetes: Mapping[str, str] = dataclasses.field(default_factory=dict)
    corps: bytes = b""
    url_finale: str | None = None


class ErreurTransportPublic(Exception):
    """Panne sous le HTTP (délai, connexion, TLS) : le collecteur la traduit en échec reprenable, sans son texte."""


class TransportPublic(Protocol):
    def obtenir(self, url: str, agent_utilisateur: str, delai_s: float) -> ReponsePublique:
        """Demande UNE URL (GET) et rend la réponse telle quelle. Ne suit pas les redirections. Aucun en-tête, cookie ni
        identifiant ne peut être ajouté par l'appelant."""


class TransportPublicNonBranche:
    """Le transport par défaut : il n'y en a pas. Rien ne part, rien n'est lu."""

    def obtenir(self, url: str, agent_utilisateur: str, delai_s: float) -> ReponsePublique:
        raise ErreurVeille("REJ-VEILLE-TRANSPORT-NON-BRANCHE",
                           "aucun transport réel n'est branché : la collecte chez un site public n'a jamais été "
                           "exercée")


def _attente(en_tetes: Mapping[str, str], defaut: int) -> int:
    for nom, valeur in (en_tetes or {}).items():
        if isinstance(nom, str) and nom.lower() == "retry-after":
            try:
                return min(max(int(str(valeur).strip()), 1), 86400)
            except ValueError:
                return defaut
    return defaut


def _entete(en_tetes: Mapping[str, str], nom: str) -> str | None:
    for cle, valeur in (en_tetes or {}).items():
        if isinstance(cle, str) and cle.lower() == nom and isinstance(valeur, str):
            return valeur
    return None


class Collecteur:
    def __init__(self, transport: TransportPublic | None = None, *, concurrents: Mapping[str, Concurrent],
                 maintenant: Callable[[], datetime], masqueur: Any, delai_min_s: int = DELAI_MIN_DEFAUT_S,
                 pages_max: int = PAGES_MAX_DEFAUT, delai_http_s: float = DELAI_HTTP_S) -> None:
        if masqueur is None:
            raise ErreurVeille("REJ-VEILLE-ARGUMENT-INVALIDE", "masqueur de renseignements personnels obligatoire")
        self._transport = transport if transport is not None else TransportPublicNonBranche()
        self._sources = registre.sources_actives(concurrents)
        self._maintenant, self._masqueur = maintenant, masqueur
        self._delai_min_s, self._pages_max, self._delai_http_s = delai_min_s, pages_max, delai_http_s
        self._cache_robots: dict[str, robots.RegleRobots] = {}
        self._dernier: dict[str, datetime] = {}
        self._pages = 0

    @property
    def pages_demandees(self) -> int:
        return self._pages

    # -- transport -----------------------------------------------------------------------------------------------------
    def _obtenir(self, url: str) -> ReponsePublique:
        try:
            reponse = self._transport.obtenir(url, AGENT_UTILISATEUR, self._delai_http_s)
        except ErreurVeille:
            raise
        except ErreurTransportPublic:
            raise ErreurVeille("REJ-VEILLE-RESEAU", "panne de transport (délai, connexion ou TLS)",
                               reprenable=True) from None
        except Exception:  # noqa: BLE001 — le texte d'une exception de transport n'est jamais recopié
            raise ErreurVeille("REJ-VEILLE-RESEAU", "panne de transport inattendue", reprenable=True) from None
        if (not isinstance(reponse, ReponsePublique) or type(reponse.statut) is not int
                or not isinstance(reponse.corps, (bytes, bytearray))):
            raise ErreurVeille("REJ-VEILLE-REPONSE-INVALIDE", "réponse de transport illisible")
        return reponse

    # -- robots.txt ----------------------------------------------------------------------------------------------------
    def _regle_robots(self, hote: str) -> robots.RegleRobots:
        if hote in self._cache_robots:
            return self._cache_robots[hote]
        url = f"https://{hote}/robots.txt"
        regle = robots.RegleRobots("inaccessible")
        for _ in range(SAUTS_MAX + 1):
            try:
                reponse = self._obtenir(url)
            except ErreurVeille as erreur:
                if erreur.code == "REJ-VEILLE-TRANSPORT-NON-BRANCHE":
                    raise
                break
            if 300 <= reponse.statut < 400:
                suivant = _entete(reponse.en_tetes, "location")
                morceaux = None
                if suivant:
                    morceaux, _, _ = registre.analyser_url(urllib.parse.urljoin(url, suivant))
                if morceaux is None or morceaux.hostname != hote:
                    break  # une redirection du robots.txt hors de l'hôte : inaccessible, donc tout interdit
                url = f"https://{hote}{morceaux.path}"
                continue
            statut = 503 if reponse.statut in (401, 403) else reponse.statut
            texte = bytes(reponse.corps[:OCTETS_MAX]).decode("utf-8", errors="replace")
            regle = robots.analyser(texte, statut)
            break
        self._cache_robots[hote] = regle
        return regle

    def _delai(self, hote: str, regle: robots.RegleRobots) -> None:
        exige = robots.delai_exige_s(regle, AGENT_ROBOTS) or 0
        attente = max(exige, self._delai_min_s)
        dernier = self._dernier.get(hote)
        if dernier is None:
            return
        ecoule = (self._maintenant() - dernier).total_seconds()
        if ecoule < attente:
            raise ErreurVeille("REJ-VEILLE-DELAI-NON-ECOULE",
                               f"délai de {attente} s entre deux pages du même hôte non écoulé", reprenable=True,
                               reessayer_apres_s=max(1, math.ceil(attente - ecoule)))

    # -- une source ----------------------------------------------------------------------------------------------------
    def collecter_url(self, url: str) -> dict[str, Any]:
        """L'observation de UNE source déclarée, ou `ErreurVeille`. Voir le module pour l'ordre des contrôles."""
        trouve = self._sources.get(url)
        if trouve is None:
            raise ErreurVeille("REJ-VEILLE-SOURCE-NON-DECLAREE",
                               "cette URL n'est pas une source d'un concurrent actif : rien n'est demandé")
        concurrent, source = trouve
        if self._pages >= self._pages_max:
            raise ErreurVeille("REJ-VEILLE-LIMITE-PAGES", f"{self._pages_max} pages par tour au plus", reprenable=True)
        courant, sauts = url, 0
        while True:
            morceaux, code, detail = registre.analyser_url(courant)
            if morceaux is None or not concurrent.possede_hote(morceaux.hostname):
                if sauts == 0:
                    raise ErreurVeille(code or "REJ-VEILLE-SOURCE-NON-DECLAREE", detail or "hôte non déclaré")
                raise ErreurVeille("REJ-VEILLE-REDIRECTION-HORS-DOMAINE",
                                   "la redirection mène hors des hôtes déclarés (ou vers une URL interdite)")
            hote = morceaux.hostname
            regle = self._regle_robots(hote)
            chemin = (morceaux.path or "/") + (f"?{morceaux.query}" if morceaux.query else "")
            if not robots.autorise(regle, AGENT_ROBOTS, chemin):
                raise ErreurVeille("REJ-VEILLE-ROBOTS-INTERDIT",
                                   f"le robots.txt de {hote} interdit ce chemin à {AGENT_ROBOTS} : jamais demandé")
            self._delai(hote, regle)
            self._dernier[hote] = self._maintenant()
            reponse = self._obtenir(courant)
            self._pages += 1
            if 300 <= reponse.statut < 400:
                sauts += 1
                if sauts > SAUTS_MAX:
                    raise ErreurVeille("REJ-VEILLE-REDIRECTION-TROP-LONGUE", f"plus de {SAUTS_MAX} redirections")
                suivant = _entete(reponse.en_tetes, "location")
                if not suivant:
                    raise ErreurVeille("REJ-VEILLE-REPONSE-INVALIDE", "redirection sans destination")
                courant = urllib.parse.urljoin(courant, suivant.strip())
                continue
            break
        return self._observation(concurrent, source, url, reponse, regle)

    def _observation(self, concurrent: Concurrent, source: Source, url: str, reponse: ReponsePublique,
                     regle: robots.RegleRobots) -> dict[str, Any]:
        maintenant = self._maintenant()
        collecte_le = maintenant.isoformat().replace("+00:00", "Z")
        robots_ia = {bot: robots.autorise(regle, bot, "/") for bot in observations.BOTS_IA}
        statut = reponse.statut
        if statut in (401, 403):
            return observations.observation_sans_contenu(concurrent.concurrent_id, url, collecte_le, statut,
                                                         "acces_refuse", robots_ia)
        if statut in (404, 410):
            return observations.observation_sans_contenu(concurrent.concurrent_id, url, collecte_le, statut, "absent",
                                                         robots_ia)
        if statut == 429 or 500 <= statut < 600:
            raise ErreurVeille("REJ-VEILLE-FOURNISSEUR-INDISPONIBLE", f"le site répond HTTP {statut}", reprenable=True,
                               reessayer_apres_s=_attente(reponse.en_tetes, 300 if statut == 429 else 600))
        if not 200 <= statut < 300:
            raise ErreurVeille("REJ-VEILLE-REPONSE-INVALIDE", f"statut HTTP inattendu {statut}")
        declare = _entete(reponse.en_tetes, "content-length")
        if len(reponse.corps) > OCTETS_MAX or (declare is not None and declare.isdigit() and int(declare) > OCTETS_MAX):
            raise ErreurVeille("REJ-VEILLE-REPONSE-TROP-GROSSE", f"réponse de plus de {OCTETS_MAX} octets")
        type_contenu = (_entete(reponse.en_tetes, "content-type") or "").split(";")[0].strip().lower()
        if type_contenu not in TYPES_PERMIS:
            raise ErreurVeille("REJ-VEILLE-TYPE-CONTENU", "type de contenu non permis (texte, HTML ou XML seulement)")
        contenu = bytes(reponse.corps).decode("utf-8", errors="replace")
        return observations.depuis_page(self._masqueur, concurrent.concurrent_id, url, source.nature, collecte_le,
                                        statut, contenu, bytes(reponse.corps), concurrent.hotes(), robots_ia)


def tour_veille(collecteur: Collecteur, journal: Any, *, concurrents: Mapping[str, Concurrent],
                maintenant: Callable[[], datetime], attendre: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Un tour : chaque source déclarée d'un concurrent actif, une observation inscrite au registre (idempotente).
    Un échec
    typé d'une source n'arrête pas les autres, SAUF l'absence de transport et la limite de pages. `attendre`
    (facultatif,
    injecté) est appelé avec les secondes d'un délai court non écoulé (60 s au plus), puis la source est retentée une
    fois ;
    sans lui, le délai est simplement rendu dans l'échec reprenable. Exécuteur hors outil : aucun planificateur ne
    l'appelle
    dans cette version."""
    bilan: dict[str, Any] = {"nouvelles": 0, "deja_presentes": 0, "acces_refuse": 0, "echecs": []}
    for url in sorted(registre.sources_actives(concurrents)):
        for essai in range(2):
            try:
                obs = collecteur.collecter_url(url)
                horodatage = maintenant().isoformat().replace("+00:00", "Z")
                ack = observations.enregistrer(journal, obs, horodatage)
                bilan["deja_presentes" if ack["deja_presente"] else "nouvelles"] += 1
                if obs["acces"] == "acces_refuse":
                    bilan["acces_refuse"] += 1
                break
            except ErreurVeille as erreur:
                if (erreur.code == "REJ-VEILLE-DELAI-NON-ECOULE" and attendre is not None and essai == 0
                        and (erreur.reessayer_apres_s or 0) <= 60):
                    attendre(float(erreur.reessayer_apres_s or 1))
                    continue
                bilan["echecs"].append({"url": url, **erreur.publique()})
                if erreur.code in ERREURS_QUI_ARRETENT_LE_TOUR:
                    return bilan
                break
    return bilan


__all__ = ["AGENT_ROBOTS", "AGENT_UTILISATEUR", "Collecteur", "ErreurTransportPublic", "OCTETS_MAX", "ReponsePublique",
           "SAUTS_MAX", "TransportPublic", "TransportPublicNonBranche", "tour_veille"]
