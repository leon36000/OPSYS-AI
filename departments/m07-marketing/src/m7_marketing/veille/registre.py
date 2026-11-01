"""Registre des concurrents DÉCLARÉS par le client, et le catalogue FERMÉ des refus de la veille (`REJ-VEILLE-*`).

La veille concurrentielle est gouvernée : OPSYS ne regarde que ce que le client a déclaré, et seulement des SOURCES
PUBLIQUES
qu'il a nommées une à une (site officiel, plan de site, communiqué, registre public). Ce registre est la liste blanche :

- un concurrent = un identifiant, un nom d'affichage (une ENTREPRISE, jamais une personne), un domaine public, au plus
cinq
  sources (URL HTTPS) et, au besoin, des hôtes additionnels déclarés (un site de communiqués distinct) ;
- une source est refusée si elle est hors du domaine déclaré (sauf hôte additionnel explicite), si elle porte un
identifiant
  ou un paramètre d'authentification, si son hôte est une adresse IP, un nom interne ou local, ou si c'est une
  PLATEFORME
  (réseaux sociaux, moteurs de recherche, places de marché, interfaces d'IA : liste fermée ci-dessous) — la collecte
  n'est
  JAMAIS un scraping de plateformes ni un accès authentifié ;
- le registre est append-only à chaîne de hachage (`journal_chaine`) : `concurrent_declare`, `concurrent_retire`. Un
concurrent
  ne se modifie pas : on le retire et on en déclare un autre sous un autre identifiant. Au plus dix concurrents actifs.

Aucune donnée personnelle de tiers n'entre ici : un nom d'affichage qui porte un courriel, un téléphone, un NAS ou une
civilité est refusé.

Module pur : aucune entrée-sortie, aucune horloge (l'horodatage vient de l'appelant).
"""

from __future__ import annotations

import dataclasses
import re
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import Any

from opsys.secrets_coffre import masquage

from .. import journal_chaine

DEPARTEMENT = "m07-marketing"
REGISTRE = (DEPARTEMENT, "concurrents_declares")
M_DECLARE = "concurrent_declare"
M_RETIRE = "concurrent_retire"

CODES_VEILLE: tuple[str, ...] = (
    "REJ-VEILLE-ARGUMENT-INVALIDE",
    "REJ-VEILLE-CONCURRENT-INVALIDE",
    "REJ-VEILLE-DOMAINE-INVALIDE",
    "REJ-VEILLE-URL-INVALIDE",
    "REJ-VEILLE-PLATEFORME-INTERDITE",
    "REJ-VEILLE-AUTHENTIFICATION-INTERDITE",
    "REJ-VEILLE-HOTE-NON-DECLARE",
    "REJ-VEILLE-LIMITE-CONCURRENTS",
    "REJ-VEILLE-CONCURRENT-EXISTANT",
    "REJ-VEILLE-CONCURRENT-INCONNU",
    "REJ-VEILLE-CONCURRENT-RETIRE",
    "REJ-VEILLE-DONNEE-PERSONNELLE",
    "REJ-VEILLE-JOURNAL-ALTERE",
    "REJ-VEILLE-SOURCE-NON-DECLAREE",
    "REJ-VEILLE-TRANSPORT-NON-BRANCHE",
    "REJ-VEILLE-ROBOTS-INTERDIT",
    "REJ-VEILLE-DELAI-NON-ECOULE",
    "REJ-VEILLE-REDIRECTION-HORS-DOMAINE",
    "REJ-VEILLE-REDIRECTION-TROP-LONGUE",
    "REJ-VEILLE-REPONSE-TROP-GROSSE",
    "REJ-VEILLE-REPONSE-INVALIDE",
    "REJ-VEILLE-TYPE-CONTENU",
    "REJ-VEILLE-FOURNISSEUR-INDISPONIBLE",
    "REJ-VEILLE-RESEAU",
    "REJ-VEILLE-LIMITE-PAGES",
    "REJ-VEILLE-OBSERVATION-INVALIDE",
    "REJ-VEILLE-MARQUE-CONCURRENT",
    "REJ-VEILLE-COPIE",
)
_CODES = frozenset(CODES_VEILLE)
_DETAIL_MAX = 300


class ErreurVeille(Exception):
    """Refus typé de la veille : un code du catalogue, un détail masqué (jamais un morceau de page de tiers)."""

    def __init__(self, code: str, detail: str = "", *, reprenable: bool = False,
                 reessayer_apres_s: int | None = None) -> None:
        if code not in _CODES:
            raise ValueError(f"code de veille hors catalogue : {code!r}")
        detail = masquage.masquer_texte(detail)[:_DETAIL_MAX]
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail
        self.reprenable, self.reessayer_apres_s = reprenable, reessayer_apres_s

    def publique(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "reprenable": self.reprenable,
                "reessayer_apres_s": self.reessayer_apres_s}


# -- plateformes interdites
# ---------------------------------------------------------------------------------------------
PLATEFORMES_INTERDITES: tuple[str, ...] = (
    "facebook.com", "instagram.com", "linkedin.com", "tiktok.com", "x.com", "twitter.com", "youtube.com",
    "google.com", "bing.com", "duckduckgo.com", "yelp.ca", "yelp.com", "amazon.ca", "amazon.com", "kijiji.ca",
    "pagesjaunes.ca", "glassdoor.com", "indeed.com", "reddit.com", "pinterest.com", "snapchat.com", "threads.net",
    "whatsapp.com", "t.me", "x.ai", "chatgpt.com", "perplexity.ai",
    # raccourcis qui mènent aux mêmes plateformes
    "fb.com", "youtu.be", "t.co", "wa.me", "instagr.am",
)
NATURES_SOURCE = ("site_officiel", "plan_de_site", "communique", "registre_public")
MAX_CONCURRENTS_ACTIFS = 10
MAX_SOURCES = 5
MAX_HOTES_ADDITIONNELS = 3
_NOMS_PARAMETRES_AUTH = re.compile(
    r"(?:^|[_.-])(?:token|key|apikey|api[_-]?key|session|sessionid|sid|auth|authorization|password|passwd|pwd|secret|"
    r"sig|signature|access[_-]?token|jwt|bearer|cookie|credential|login)(?:$|[_.-])", re.IGNORECASE)
_SUFFIXES_NON_PUBLICS = (".onion", ".local", ".internal", ".localhost", ".lan", ".home", ".corp", ".intranet",
                         ".private", ".arpa")
_ETIQUETTE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
_COURRIEL = re.compile(r"[^\s@]{1,64}@[^\s@]{1,255}")
_TELEPHONE = re.compile(r"(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}")
_NAS = re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b")
_CIVILITE = re.compile(r"^(?:m\.|mr\.?|mme\.?|mlle\.?|dr\.?|me\.?|monsieur|madame|mademoiselle|docteur|maitre|maître)"
                       r"\s",
                       re.IGNORECASE)
_CONTROLES = re.compile(r"[\x00-\x1f\x7f-\x9f  ​-‏‪-‮⁦-⁩]")


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def domaine_valide(valeur: Any) -> str | None:
    """Le nom d'hôte PUBLIC, en minuscules, ou `None` : au moins deux étiquettes ASCII (punycode pour l'international),
    un dernier mot alphabétique (donc ni adresse IP ni nombre décimal ou hexadécimal), aucun suffixe interne ou local,
    ni port, ni identifiant, ni chemin."""
    if not isinstance(valeur, str) or not valeur or len(valeur) > 253 or _CONTROLES.search(valeur):
        return None
    nom = valeur.strip().lower().rstrip(".")
    if not nom or any(c in nom for c in " /\\:@?#[]%"):
        return None
    if nom == "localhost" or nom.endswith(_SUFFIXES_NON_PUBLICS):
        return None
    etiquettes = nom.split(".")
    if (len(etiquettes) < 2 or not all(_ETIQUETTE.fullmatch(e) for e in etiquettes)
            or not _TLD.fullmatch(etiquettes[-1])):
        return None
    return nom


def plateforme_interdite(hote: str) -> str | None:
    """La plateforme interdite dont `hote` est le domaine ou un sous-domaine, sinon `None`."""
    for domaine in PLATEFORMES_INTERDITES:
        if hote == domaine or hote.endswith("." + domaine):
            return domaine
    return None


def hote_dans(hote: str, domaine: str) -> bool:
    return hote == domaine or hote.endswith("." + domaine)


def analyser_url(url: Any) -> tuple[urllib.parse.SplitResult | None, str | None, str]:
    """(url analysée, code de refus, détail). Contrôles COMMUNS aux sources et aux redirections : https seulement, aucun
    identifiant, port 443 seulement, hôte public, aucune plateforme, aucun paramètre d'authentification."""
    if not isinstance(url, str) or not url or len(url) > 300 or _CONTROLES.search(url) or any(c in url for c in " \\"):
        return None, "REJ-VEILLE-URL-INVALIDE", "URL de 300 caractères au plus, sans espace ni caractère de contrôle"
    try:
        morceaux = urllib.parse.urlsplit(url)
        port = morceaux.port
    except ValueError:
        return None, "REJ-VEILLE-URL-INVALIDE", "URL illisible"
    if morceaux.scheme != "https":
        return None, "REJ-VEILLE-URL-INVALIDE", "https exigé"
    if morceaux.username is not None or morceaux.password is not None or "@" in morceaux.netloc:
        return (None, "REJ-VEILLE-AUTHENTIFICATION-INTERDITE",
                "aucun identifiant dans l'URL : jamais d'accès authentifié")
    if port not in (None, 443):
        return None, "REJ-VEILLE-URL-INVALIDE", "seul le port 443 est permis"
    hote = domaine_valide(morceaux.hostname or "")
    if hote is None:
        return None, "REJ-VEILLE-URL-INVALIDE", "hôte public exigé (ni IP, ni nom local ou interne)"
    if morceaux.fragment:
        return None, "REJ-VEILLE-URL-INVALIDE", "aucun fragment"
    interdite = plateforme_interdite(hote)
    if interdite is not None:
        return None, "REJ-VEILLE-PLATEFORME-INTERDITE", f"plateforme interdite ({interdite}) : aucune collecte"
    for nom, _ in urllib.parse.parse_qsl(morceaux.query, keep_blank_values=True):
        if _NOMS_PARAMETRES_AUTH.search(nom):
            return None, "REJ-VEILLE-AUTHENTIFICATION-INTERDITE", "paramètre d'authentification dans l'URL : refusé"
    if re.search(r"/(?:login|signin|sign-in|auth|account|admin|wp-admin|connexion)(?:/|$)", morceaux.path,
                 re.IGNORECASE):
        return None, "REJ-VEILLE-AUTHENTIFICATION-INTERDITE", "chemin d'authentification : refusé"
    return morceaux, None, ""


def url_sans_parametres(url: str) -> str:
    m = urllib.parse.urlsplit(url)
    return f"https://{m.hostname}{m.path or '/'}"


@dataclasses.dataclass(frozen=True)
class Source:
    url: str
    nature: str


@dataclasses.dataclass(frozen=True)
class Concurrent:
    concurrent_id: str
    nom_affiche: str
    domaine: str
    sources: tuple[Source, ...]
    hotes_additionnels: tuple[str, ...]
    actif: bool = True

    def hotes(self) -> tuple[str, ...]:
        return (self.domaine, *self.hotes_additionnels)

    def possede_hote(self, hote: str) -> bool:
        return any(hote_dans(hote, d) for d in self.hotes())


def nom_valide(valeur: Any) -> tuple[str | None, str]:
    if not isinstance(valeur, str):
        return None, "nom d'entreprise en texte attendu"
    nom = valeur.strip()
    if not 2 <= len(nom) <= 80 or _CONTROLES.search(nom):
        return None, "2 à 80 caractères, sans caractère de contrôle"
    if _COURRIEL.search(nom) or _TELEPHONE.search(nom) or _NAS.search(nom) or _CIVILITE.match(nom):
        return None, "le nom d'une ENTREPRISE est attendu : ni courriel, ni téléphone, ni civilité de personne physique"
    return nom, ""


def plier(journal: Iterable[Any]) -> dict[str, Concurrent]:
    resultat: dict[str, Concurrent] = {}
    for m in journal:
        if m["type"] == M_DECLARE:
            resultat[m["concurrent_id"]] = Concurrent(
                concurrent_id=m["concurrent_id"], nom_affiche=m["nom_affiche"], domaine=m["domaine"],
                sources=tuple(Source(s["url"], s["nature"]) for s in m["sources"]),
                hotes_additionnels=tuple(m["hotes_additionnels"]), actif=True)
        elif m["type"] == M_RETIRE:
            resultat[m["concurrent_id"]] = dataclasses.replace(resultat[m["concurrent_id"]], actif=False)
    return resultat


def actifs(journal: Iterable[Any]) -> dict[str, Concurrent]:
    return {cle: c for cle, c in plier(journal).items() if c.actif}


def sources_actives(concurrents: Mapping[str, Concurrent]) -> dict[str, tuple[Concurrent, Source]]:
    """url déclarée -> (concurrent, source), pour les concurrents ACTIFS seulement."""
    return {s.url: (c, s) for c in concurrents.values() if c.actif for s in c.sources}


def declarer(journal: Any, concurrent_id: Any, nom_affiche: Any, domaine: Any, sources: Any,
             hotes_additionnels: Any, par: str, horodatage: str) -> dict[str, Any]:
    if not isinstance(concurrent_id, str) or not _ID.fullmatch(concurrent_id):
        return _refus("REJ-VEILLE-CONCURRENT-INVALIDE", "$.concurrent_id", "minuscules, chiffres et tirets ; 2 à 40")
    nom, detail = nom_valide(nom_affiche)
    if nom is None:
        code = "REJ-VEILLE-DONNEE-PERSONNELLE" if isinstance(nom_affiche, str) and (
            _COURRIEL.search(nom_affiche) or _TELEPHONE.search(nom_affiche) or _NAS.search(nom_affiche)
            or _CIVILITE.match(nom_affiche.strip())) else "REJ-VEILLE-ARGUMENT-INVALIDE"
        return _refus(code, "$.nom_affiche", detail)
    domaine_norm = domaine_valide(domaine)
    if domaine_norm is None:
        return _refus("REJ-VEILLE-DOMAINE-INVALIDE", "$.domaine",
                      "nom d'hôte public attendu (ni IP, ni localhost, ni port, ni suffixe interne ou .onion)")
    interdite = plateforme_interdite(domaine_norm)
    if interdite is not None:
        return _refus("REJ-VEILLE-PLATEFORME-INTERDITE", "$.domaine", f"plateforme interdite ({interdite})")
    additionnels = hotes_additionnels if hotes_additionnels is not None else []
    if not isinstance(additionnels, list) or len(additionnels) > MAX_HOTES_ADDITIONNELS:
        return _refus("REJ-VEILLE-ARGUMENT-INVALIDE", "$.hotes_additionnels",
                      f"liste d'au plus {MAX_HOTES_ADDITIONNELS} noms d'hôte")
    hotes_norm = []
    for i, h in enumerate(additionnels):
        norme = domaine_valide(h)
        if norme is None:
            return _refus("REJ-VEILLE-DOMAINE-INVALIDE", f"$.hotes_additionnels[{i}]", "nom d'hôte public attendu")
        if plateforme_interdite(norme) is not None:
            return _refus("REJ-VEILLE-PLATEFORME-INTERDITE", f"$.hotes_additionnels[{i}]", "plateforme interdite")
        if norme not in hotes_norm and norme != domaine_norm:
            hotes_norm.append(norme)
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
        return _refus("REJ-VEILLE-ARGUMENT-INVALIDE", "$.sources", f"1 à {MAX_SOURCES} sources attendues")
    permis = (domaine_norm, *hotes_norm)
    normalisees, vues = [], set()
    for i, brute in enumerate(sources):
        chemin = f"$.sources[{i}]"
        if not isinstance(brute, Mapping) or set(brute) != {"url", "nature"} or brute["nature"] not in NATURES_SOURCE:
            return _refus("REJ-VEILLE-ARGUMENT-INVALIDE", chemin,
                f"{{url, nature parmi {list(NATURES_SOURCE)}}} attendu")
        morceaux, code, detail = analyser_url(brute["url"])
        if morceaux is None:
            return _refus(code, f"{chemin}.url", detail)
        if not any(hote_dans(morceaux.hostname, d) for d in permis):
            return _refus("REJ-VEILLE-HOTE-NON-DECLARE", f"{chemin}.url",
                          "l'hôte n'est pas le domaine du concurrent : le déclarer comme hôte additionnel")
        if brute["url"] in vues:
            return _refus("REJ-VEILLE-ARGUMENT-INVALIDE", chemin, "source en double")
        vues.add(brute["url"])
        normalisees.append({"url": brute["url"], "nature": brute["nature"]})
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return _refus("REJ-VEILLE-JOURNAL-ALTERE", "$", "; ".join(problemes[:3]))
    courants = plier(journal)
    nouveau = {"concurrent_id": concurrent_id, "nom_affiche": nom, "domaine": domaine_norm, "sources": normalisees,
               "hotes_additionnels": hotes_norm}
    existant = courants.get(concurrent_id)
    if existant is not None:
        if not existant.actif:
            return _refus("REJ-VEILLE-CONCURRENT-RETIRE", "$.concurrent_id",
                          "concurrent retiré : déclarer un autre identifiant pour un nouvel enregistrement")
        identique = (existant.nom_affiche, existant.domaine, existant.hotes_additionnels,
                     tuple((s.url, s.nature) for s in existant.sources)) == (
            nom, domaine_norm, tuple(hotes_norm), tuple((s["url"], s["nature"]) for s in normalisees))
        if identique:
            return {"accepte": True, "concurrent_id": concurrent_id, "deja_declare": True}
        return _refus("REJ-VEILLE-CONCURRENT-EXISTANT", "$.concurrent_id",
                      "ce concurrent existe avec une autre déclaration : un concurrent ne se modifie pas")
    if sum(1 for c in courants.values() if c.actif) >= MAX_CONCURRENTS_ACTIFS:
        return _refus("REJ-VEILLE-LIMITE-CONCURRENTS", "$", f"{MAX_CONCURRENTS_ACTIFS} concurrents actifs au plus")
    journal_chaine.ajouter(journal, M_DECLARE, {**nouveau, "par": par}, horodatage)
    return {"accepte": True, "concurrent_id": concurrent_id, "deja_declare": False}


def retirer(journal: Any, concurrent_id: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return _refus("REJ-VEILLE-JOURNAL-ALTERE", "$", "; ".join(problemes[:3]))
    courant = plier(journal).get(concurrent_id)
    if courant is None:
        return _refus("REJ-VEILLE-CONCURRENT-INCONNU", "$.concurrent_id", f"concurrent inconnu : {concurrent_id!r}")
    if not courant.actif:
        return {"accepte": True, "concurrent_id": concurrent_id, "deja_retire": True}
    journal_chaine.ajouter(journal, M_RETIRE, {"concurrent_id": concurrent_id, "par": par, "motif": motif[:300]},
                           horodatage)
    return {"accepte": True, "concurrent_id": concurrent_id, "deja_retire": False}


__all__ = ["CODES_VEILLE", "Concurrent", "DEPARTEMENT", "ErreurVeille", "MAX_CONCURRENTS_ACTIFS", "NATURES_SOURCE",
           "PLATEFORMES_INTERDITES", "REGISTRE", "Source", "actifs", "analyser_url", "declarer", "domaine_valide",
           "hote_dans", "plateforme_interdite", "plier", "retirer", "sources_actives", "url_sans_parametres"]
