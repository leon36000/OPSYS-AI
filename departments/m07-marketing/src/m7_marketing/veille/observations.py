"""L'OBSERVATION : un fait daté et sourcé lu sur une page PUBLIQUE d'un concurrent déclaré, et son registre.

Ce que l'observation garde de la page : titre, méta-description, titres h1, nombre de mots visibles, types de données
structurées, adresse canonique, langue, nombre de liens internes, nombre d'URL d'un plan de site, robots d'IA
autorisés par le
`robots.txt` de l'hôte, l'empreinte SHA-256 du contenu. Jamais la page. Jamais une coordonnée de personne.

Tout ce qui vient d'un tiers est une DONNÉE, jamais une consigne :
- tout texte passe par le masqueur d'observabilité (courriels, téléphones, NAS, cartes, adresses, codes postaux…) puis
est coupé
  à 200 caractères ; une dernière passe retire ce qu'un masqueur plus faible aurait laissé (courriel, téléphone) ;
- une consigne glissée dans la page (« ignore les instructions précédentes », « tu es maintenant… », « system prompt
», balises de
  rôle, ordre d'envoyer des données à une URL…) est détectée par motifs : le texte concerné est ÉCARTÉ (jamais rendu,
  jamais
  gardé) et `injection_detectee` vaut vrai ;
- chaque observation porte `fiabilite: "non_fiable"` et `contenu_tiers: true`.

Registre `observations_concurrents` : append-only à chaîne de hachage, idempotent par (url, empreinte du contenu, jour
UTC) ;
une observation de plus de 90 jours est `perimee` à la lecture. Le HTML n'est jamais exécuté : il est analysé par un
analyseur de texte (`html.parser`) borné en taille.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import journal_chaine
from ..competitive.analyzers import SEOParser
from . import registre
from .registre import ErreurVeille

REGISTRE_OBSERVATIONS = (registre.DEPARTEMENT, "observations_concurrents")
M_OBSERVATION = "observation"
PEREMPTION_JOURS = 90
TEXTE_MAX = 200
HTML_MAX_OCTETS = 1024 * 1024
BOTS_IA = ("oai-searchbot", "gptbot", "chatgpt-user", "perplexitybot", "perplexity-user", "claudebot", "claude-user",
           "claude-searchbot", "google-extended", "ccbot", "applebot-extended")
MODES = ("collecte_publique", "saisie_humaine")
VERDICTS_ROBOTS = ("autorise", "saisie_humaine")
ACCES = ("ok", "acces_refuse", "absent")
CHAMPS = (
    "observation_id", "concurrent_id", "url", "collecte_le", "mode", "statut_http", "verdict_robots", "acces",
    "empreinte_contenu", "titre", "description_meta", "h1", "nb_mots", "types_schema", "canonical", "langue",
    "liens_internes_nb", "nb_urls_plan_de_site", "robots_ia", "injection_detectee", "fiabilite", "contenu_tiers",
)

# -- injection --------------------------------------------------------------------------------------------------------
_MOTIFS_INJECTION = tuple(re.compile(m) for m in (
    r"ignore[zr]?\s+(?:all|toutes?|les|tes|vos|previous|prior|above|ci-dessus|precedentes?)\b.{0,40}"
    r"(?:instruction|consigne|regle|rule|prompt|directive)",
    r"(?:oublie|oubliez|forget|disregard)\b.{0,40}(?:instruction|consigne|regle|rule|prompt|directive|above|precedent)",
    r"\btu es (?:maintenant|desormais)\b",
    r"\byou are now\b",
    r"\bsystem prompt\b",
    r"\bprompt systeme\b",
    r"\bnouvelles? (?:instructions?|consignes?)\b",
    r"\bnew instructions?\b",
    r"<\s*/?\s*(?:system|assistant|user|im_start|im_end)\b",
    r"<\|[a-z_]+\|>",
    r"\[/?inst\]",
    r"(?:^|\s)#{1,3}\s*(?:system|instructions?)\s*:",
    r"\brole\s*:\s*(?:system|assistant)",
    r"\bagis comme\b",
    r"\bact as (?:an?|the)\b",
    r"\bpretend (?:to be|you)\b",
    r"\bjailbreak\b",
    r"\bdo anything now\b",
    r"(?:envoie|envoyez|send|post|exfiltr\w*|transmets|transmettez|forward)\b.{0,60}https?://",
    r"\b(?:callback|webhook|rappel)\b.{0,30}https?://",
    r"https?://\S+\?\S*(?:prompt|instruction|exfil|leak)=",
    r"\b(?:note|message|attention)\s+(?:to|pour|a)\s+(?:the\s+|l'|le\s+|la\s+)?(?:ai|ia|llm|assistant|agent|model|modele)\b",
))
_CONTROLES = re.compile(r"[\x00-\x1f\x7f-\x9f  ​-‏‪-‮⁦-⁩]")
_COURRIEL = re.compile(r"[^\s@]{1,64}@[^\s@]{1,255}")
_TELEPHONE = re.compile(r"(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}")
_LANGUE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_TYPE_SCHEMA = re.compile(r"^[A-Za-z]{1,40}$")


def _plier(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte.lower()) if not unicodedata.combining(c))


def contient_injection(texte: str) -> bool:
    plie = _plier(_CONTROLES.sub(" ", texte))[:200_000]
    return any(m.search(plie) for m in _MOTIFS_INJECTION)


def texte_tiers(masqueur: Any, texte: Any, maximum: int = TEXTE_MAX) -> tuple[str | None, bool]:
    """(texte minimisé ou `None`, injection détectée). Un texte injecté n'est jamais rendu."""
    if not isinstance(texte, str):
        return None, False
    propre = _CONTROLES.sub(" ", unicodedata.normalize("NFC", texte))
    propre = re.sub(r"\s+", " ", propre).strip()
    if not propre:
        return None, False
    if contient_injection(propre):
        return None, True
    masque = masqueur.masquer(propre[:2000]).texte
    masque = _COURRIEL.sub("[[COURRIEL]]", masque)
    masque = _TELEPHONE.sub("[[TEL]]", masque)
    if len(masque) > maximum:
        masque = masque[:maximum]
        dernier = masque.rfind("[[")
        if dernier != -1 and "]]" not in masque[dernier:]:
            masque = masque[:dernier]
        masque = masque.rstrip()
    return (masque or None), False


# -- analyse de la page
# -------------------------------------------------------------------------------------------------
class _ParseurPage(SEOParser):
    """L'analyseur de la veille (celui de `competitive`) plus l'adresse canonique, la langue et le texte visible."""

    _IGNORES = frozenset({"script", "style", "noscript", "template", "title"})

    def __init__(self) -> None:
        super().__init__()
        self.canonical: str | None = None
        self.langue: str | None = None
        self._ignore = 0
        self.visible: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = [(k, v if v is not None else "") for k, v in attrs]  # `<meta name>` sans valeur ne doit pas planter
        d = dict(attrs)
        if tag == "html" and self.langue is None:
            self.langue = d.get("lang") or None
        if tag == "link" and "canonical" in d.get("rel", "").lower().split() and self.canonical is None:
            self.canonical = d.get("href") or None
        super().handle_starttag(tag, attrs)
        if tag in self._IGNORES:
            self._ignore += 1

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag in self._IGNORES and self._ignore > 0:
            self._ignore -= 1

    def handle_data(self, data):
        super().handle_data(data)
        if self._ignore == 0:
            self.visible.append(data)


def _types_schema(scripts: Sequence[str]) -> list[str]:
    types: set[str] = set()

    def visiter(noeud: Any, profondeur: int = 0) -> None:
        if profondeur > 8:
            return
        if isinstance(noeud, list):
            for e in noeud[:200]:
                visiter(e, profondeur + 1)
        elif isinstance(noeud, dict):
            t = noeud.get("@type")
            for v in (t if isinstance(t, list) else [t]):
                if isinstance(v, str) and _TYPE_SCHEMA.fullmatch(v):
                    types.add(v)
            for e in list(noeud.values())[:200]:
                if isinstance(e, (list, dict)):
                    visiter(e, profondeur + 1)

    for brut in scripts[:20]:
        if len(brut) > 200_000:
            continue
        try:
            visiter(json.loads(brut))
        except (ValueError, RecursionError):
            continue
    return sorted(types)[:10]


def compter_urls_plan_de_site(xml_texte: str) -> int | None:
    """Nombre d'URL (`<loc>` d'un `<url>` ou d'un `<sitemap>`) ; `None` si le XML est illisible. Une déclaration de
    type de
    document ou d'entité est refusée AVANT l'analyse (aucune expansion d'entités)."""
    if len(xml_texte.encode("utf-8")) > HTML_MAX_OCTETS:
        return None
    bas = xml_texte.lower()
    if "<!doctype" in bas or "<!entity" in bas:
        return None
    try:
        racine = ET.fromstring(xml_texte)
    except ET.ParseError:
        return None
    total = 0
    for element in racine.iter():
        if element.tag.split("}")[-1] in ("url", "sitemap"):
            total += sum(1 for e in element if e.tag.split("}")[-1] == "loc" and (e.text or "").strip())
    return total


def _liens_internes(liens: Iterable[str], url_page: str, hotes: Sequence[str]) -> int:
    chemins = set()
    for lien in liens:
        if not isinstance(lien, str) or lien.lower().startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
            continue
        try:
            absolu = urllib.parse.urlsplit(urllib.parse.urljoin(url_page, lien.strip()))
        except ValueError:
            continue
        if absolu.scheme in ("http", "https") and absolu.hostname and any(
                registre.hote_dans(absolu.hostname.lower(), h) for h in hotes):
            chemins.add((absolu.hostname.lower(), absolu.path or "/"))
        if len(chemins) >= 10_000:
            break
    return len(chemins)


def _identifiant(concurrent_id: str, url: str, empreinte: str | None, statut: str, collecte_le: str) -> str:
    jour = datetime.fromisoformat(collecte_le.replace("Z", "+00:00")).astimezone(UTC).date().isoformat()
    corps = json.dumps([concurrent_id, url, empreinte or statut, jour], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(corps.encode("utf-8")).hexdigest()[:32]


def _instant(valeur: Any, champ: str) -> datetime:
    if not isinstance(valeur, str) or len(valeur) > 40:
        raise ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", f"{champ} attendu en RFC 3339 avec fuseau")
    try:
        instant = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError:
        raise ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", f"{champ} n'est pas un instant RFC 3339") from None
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", f"{champ} sans fuseau : refusé, jamais supposé UTC")
    return instant


instant_rfc3339 = _instant


def _base(concurrent_id: str, url: str, collecte_le: str, mode: str, statut: int | None, verdict: str,
          acces: str, empreinte: str | None) -> dict[str, Any]:
    return {
        "observation_id": _identifiant(concurrent_id, url, empreinte, f"{acces}:{statut}", collecte_le),
        "concurrent_id": concurrent_id, "url": url, "collecte_le": collecte_le, "mode": mode, "statut_http": statut,
        "verdict_robots": verdict, "acces": acces, "empreinte_contenu": empreinte, "titre": None,
        "description_meta": None, "h1": [], "nb_mots": None, "types_schema": [], "canonical": None, "langue": None,
        "liens_internes_nb": None, "nb_urls_plan_de_site": None, "robots_ia": None, "injection_detectee": False,
        "fiabilite": "non_fiable", "contenu_tiers": True,
    }


def observation_sans_contenu(concurrent_id: str, url_declaree: str, collecte_le: str, statut: int, acces: str,
                             robots_ia: Mapping[str, bool] | None) -> dict[str, Any]:
    """Un fait sans contenu : accès refusé (401/403) ou page absente (404/410). Aucun contournement n'est tenté."""
    obs = _base(concurrent_id, registre.url_sans_parametres(url_declaree), collecte_le, "collecte_publique", statut,
                "autorise", acces, None)
    obs["robots_ia"] = dict(robots_ia) if robots_ia is not None else None
    return valider(obs)


def depuis_page(masqueur: Any, concurrent_id: str, url_declaree: str, nature: str, collecte_le: str, statut: int,
                contenu: str, octets: bytes, hotes: Sequence[str],
                robots_ia: Mapping[str, bool] | None) -> dict[str, Any]:
    """L'observation d'une page ou d'un plan de site REÇU (2xx), minimisée."""
    url = registre.url_sans_parametres(url_declaree)
    obs = _base(concurrent_id, url, collecte_le, "collecte_publique", statut, "autorise", "ok",
                hashlib.sha256(octets).hexdigest())
    obs["robots_ia"] = dict(robots_ia) if robots_ia is not None else None
    if nature == "plan_de_site":
        obs["nb_urls_plan_de_site"] = compter_urls_plan_de_site(contenu)
        return valider(obs)
    parseur = _ParseurPage()
    try:
        parseur.feed(contenu[:HTML_MAX_OCTETS])
        parseur.close()
    except Exception:  # noqa: BLE001 — une page illisible donne une observation sans champs, jamais une panne
        parseur = _ParseurPage()
    injection = False
    titre, inj = texte_tiers(masqueur, parseur.title)
    injection |= inj
    description, inj = texte_tiers(masqueur, parseur.meta_description)
    injection |= inj
    h1 = []
    for brut in parseur.h1_list:
        texte, inj = texte_tiers(masqueur, brut)
        injection |= inj
        if texte:
            h1.append(texte)
    visible = " ".join(parseur.visible)
    injection |= contient_injection(visible)  # le corps n'est pas gardé : seul le signalement l'est
    obs.update({
        "titre": titre, "description_meta": description, "h1": h1[:5], "nb_mots": len(re.findall(r"\w+", visible)),
        "types_schema": _types_schema(parseur.scripts_ld), "langue": None,
        "liens_internes_nb": _liens_internes(parseur.links, url_declaree, hotes), "injection_detectee": injection,
    })
    langue = (parseur.langue or "").strip()
    obs["langue"] = langue if _LANGUE.fullmatch(langue) else None
    canon = parseur.canonical
    if isinstance(canon, str):
        analyse = urllib.parse.urlsplit(urllib.parse.urljoin(url_declaree, canon.strip()))
        if analyse.scheme == "https" and analyse.hostname and analyse.username is None and len(analyse.path) < 150:
            obs["canonical"] = f"https://{analyse.hostname.lower()}{analyse.path or '/'}"
    return valider(obs)


def depuis_saisie(masqueur: Any, concurrent_id: str, url_declaree: str, saisie: Mapping[str, Any],
                  observe_le: str) -> dict[str, Any]:
    """L'observation que l'humain a lue sur la page publique (même minimisation que la collecte). L'empreinte est celle
    des champs saisis : la même saisie rejouée est la même observation."""
    permis = {"titre", "description_meta", "h1", "nb_mots", "types_schema", "canonical", "langue", "liens_internes_nb",
              "nb_urls_plan_de_site"}
    if not isinstance(saisie, Mapping) or set(saisie) - permis:
        raise ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", f"champs permis de la saisie : {sorted(permis)}")
    url = registre.url_sans_parametres(url_declaree)
    empreinte = hashlib.sha256(json.dumps(dict(saisie), sort_keys=True, ensure_ascii=False,
                                          default=str).encode("utf-8")).hexdigest()
    obs = _base(concurrent_id, url, observe_le, "saisie_humaine", None, "saisie_humaine", "ok", empreinte)
    injection = False
    for champ in ("titre", "description_meta"):
        texte, inj = texte_tiers(masqueur, saisie.get(champ))
        injection |= inj
        obs[champ] = texte
    h1 = saisie.get("h1", [])
    if not isinstance(h1, list) or len(h1) > 5:
        raise ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", "h1 : liste de 5 titres au plus")
    for brut in h1:
        texte, inj = texte_tiers(masqueur, brut)
        injection |= inj
        if texte:
            obs["h1"].append(texte)
    for champ in ("nb_mots", "liens_internes_nb", "nb_urls_plan_de_site"):
        if saisie.get(champ) is not None:
            obs[champ] = saisie[champ]
    types = saisie.get("types_schema", [])
    if not isinstance(types, list) or not all(isinstance(t, str) and _TYPE_SCHEMA.fullmatch(t) for t in types):
        raise ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", "types_schema : liste de noms de types alphabétiques")
    obs["types_schema"] = sorted(set(types))[:10]
    if saisie.get("langue") is not None:
        obs["langue"] = saisie["langue"]
    if saisie.get("canonical") is not None:
        analyse = urllib.parse.urlsplit(str(saisie["canonical"]))
        if analyse.scheme != "https" or not analyse.hostname or analyse.username is not None:
            raise ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", "canonical : URL https sans identifiant attendue")
        obs["canonical"] = f"https://{analyse.hostname.lower()}{analyse.path or '/'}"
    obs["injection_detectee"] = injection
    return valider(obs)


# -- validation --------------------------------------------------------------------------------------------------------
def _entier_ou_none(valeur: Any, champ: str) -> None:
    if valeur is not None and (type(valeur) is not int or not 0 <= valeur <= 10_000_000):
        raise ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", f"{champ} : entier >= 0 ou null")


def valider(obs: Any) -> dict[str, Any]:
    """Forme canonique d'une observation ou `ErreurVeille(REJ-VEILLE-OBSERVATION-INVALIDE)`. Fermée : aucun champ en
    plus, aucun en moins ; l'identifiant est RECALCULÉ."""
    def refus(detail: str) -> ErreurVeille:
        return ErreurVeille("REJ-VEILLE-OBSERVATION-INVALIDE", detail)

    if not isinstance(obs, Mapping) or set(obs) != set(CHAMPS):
        raise refus(f"champs attendus : {list(CHAMPS)}")
    if not isinstance(obs["concurrent_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,39}", obs["concurrent_id"]):
        raise refus("concurrent_id invalide")
    morceaux, _, _ = registre.analyser_url(obs["url"])
    if morceaux is None or obs["url"] != registre.url_sans_parametres(obs["url"]):
        raise refus("url : https sans paramètres attendue")
    _instant(obs["collecte_le"], "collecte_le")
    if obs["mode"] not in MODES or obs["verdict_robots"] not in VERDICTS_ROBOTS or obs["acces"] not in ACCES:
        raise refus("mode, verdict_robots ou acces hors liste")
    statut = obs["statut_http"]
    if statut is not None and (type(statut) is not int or not 100 <= statut <= 599):
        raise refus("statut_http : entier 100 à 599 ou null")
    empreinte = obs["empreinte_contenu"]
    if empreinte is not None and (not isinstance(empreinte, str) or not re.fullmatch(r"[0-9a-f]{64}", empreinte)):
        raise refus("empreinte_contenu : sha256 hexadécimal ou null")
    for champ in ("titre", "description_meta", "canonical"):
        v = obs[champ]
        if v is not None and (not isinstance(v, str) or not 1 <= len(v) <= TEXTE_MAX or _CONTROLES.search(v)
                              or _COURRIEL.search(v) or _TELEPHONE.search(v)):
            raise refus(f"{champ} : texte minimisé de {TEXTE_MAX} caractères au plus ou null")
    if (not isinstance(obs["h1"], list) or len(obs["h1"]) > 5
            or not all(isinstance(t, str) and 1 <= len(t) <= TEXTE_MAX and not _COURRIEL.search(t)
                       and not _TELEPHONE.search(t) for t in obs["h1"])):
        raise refus("h1 : cinq textes minimisés au plus")
    if (not isinstance(obs["types_schema"], list) or len(obs["types_schema"]) > 10
            or not all(isinstance(t, str) and _TYPE_SCHEMA.fullmatch(t) for t in obs["types_schema"])):
        raise refus("types_schema invalide")
    if obs["langue"] is not None and (not isinstance(obs["langue"], str) or not _LANGUE.fullmatch(obs["langue"])):
        raise refus("langue invalide")
    for champ in ("nb_mots", "liens_internes_nb", "nb_urls_plan_de_site"):
        _entier_ou_none(obs[champ], champ)
    robots = obs["robots_ia"]
    if robots is not None and (not isinstance(robots, Mapping) or set(robots) - set(BOTS_IA)
                               or not all(type(v) is bool for v in robots.values())):
        raise refus("robots_ia : {robot connu: booléen} ou null")
    if (type(obs["injection_detectee"]) is not bool or obs["fiabilite"] != "non_fiable"
            or obs["contenu_tiers"] is not True):
        raise refus("injection_detectee booléen, fiabilite 'non_fiable' et contenu_tiers vrai exigés")
    attendu = _identifiant(obs["concurrent_id"], obs["url"], empreinte, f"{obs['acces']}:{statut}", obs["collecte_le"])
    if obs["observation_id"] != attendu:
        raise refus("observation_id ne correspond pas à l'identité de l'observation (recalculé)")
    return {c: (list(obs[c]) if isinstance(obs[c], list) else dict(obs[c]) if isinstance(obs[c], Mapping)
                else obs[c]) for c in CHAMPS}


# -- registre
# -----------------------------------------------------------------------------------------------------------
def charger(journal: Sequence[Any]) -> list[dict[str, Any]]:
    """Les observations du registre, chaîne vérifiée et chaque observation revalidée (une altération est une erreur)."""
    if journal_chaine.verifier(journal):
        raise ErreurVeille("REJ-VEILLE-JOURNAL-ALTERE", "la chaîne de hachage des observations ne correspond plus")
    resultat = []
    for m in journal:
        if m["type"] != M_OBSERVATION:
            raise ErreurVeille("REJ-VEILLE-JOURNAL-ALTERE", "maillon inattendu dans les observations")
        resultat.append(valider({c: m[c] for c in CHAMPS}))
    return resultat


def enregistrer(journal: Any, obs: Mapping[str, Any], horodatage: str) -> dict[str, Any]:
    """Inscrit l'observation, ou constate qu'elle y est déjà (même url, même empreinte, même jour UTC)."""
    canonique = valider(obs)
    if any(o["observation_id"] == canonique["observation_id"] for o in charger(journal)):
        return {"accepte": True, "observation_id": canonique["observation_id"], "deja_presente": True}
    journal_chaine.ajouter(journal, M_OBSERVATION, canonique, horodatage)
    return {"accepte": True, "observation_id": canonique["observation_id"], "deja_presente": False}


def dernieres_par_url(observations: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """La plus récente observation de chaque (concurrent, url)."""
    dernieres: dict[tuple[str, str], dict[str, Any]] = {}
    for o in observations:
        cle = (o["concurrent_id"], o["url"])
        precedente = dernieres.get(cle)
        if precedente is None or _instant(o["collecte_le"], "collecte_le") >= _instant(precedente["collecte_le"],
                                                                                         "collecte_le"):
            dernieres[cle] = dict(o)
    return dernieres


def est_perimee(obs: Mapping[str, Any], maintenant: datetime) -> bool:
    return maintenant - _instant(obs["collecte_le"], "collecte_le") > timedelta(days=PEREMPTION_JOURS)


__all__ = ["ACCES", "BOTS_IA", "CHAMPS", "PEREMPTION_JOURS", "REGISTRE_OBSERVATIONS", "charger",
    "compter_urls_plan_de_site",
           "contient_injection", "depuis_page", "depuis_saisie", "dernieres_par_url", "enregistrer", "est_perimee",
           "instant_rfc3339", "observation_sans_contenu", "texte_tiers", "valider"]
