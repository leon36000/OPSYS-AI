"""Normalisation DÉTERMINISTE des paramètres UTM entrants, sur la convention gelée `contracts/utm-convention.v1.yaml`.

La convention (énumérés de `utm_source` et `utm_medium`, format de `utm_campaign`, alphabet de `utm_content`) reste
celle du moteur `utm/utm_engine.py`, qui la lit dans le contrat gelé : ce module ne la recopie pas. Il ajoute ce qui
manque pour MESURER : ramener ce qu'un visiteur ou un import a réellement écrit (`Facebook`, `fb`, `facebook.com`,
`Paid Search`) à une valeur de la convention, ou dire pourquoi c'est impossible.

Règles :
- une valeur déjà dans la convention est `conforme` ; une valeur qu'une TABLE D'ALIAS DÉCLARÉE ICI (et seulement
elle) ramène
  à la convention est `normalisable` ; tout le reste est `non_normalisable` AVEC sa raison. Jamais une valeur
  devinée, jamais « autre » ;
- une valeur AMBIGUË (`meta` : Facebook ou Instagram ?) est non normalisable : on ne tranche pas à la place du client ;
- la campagne passe par `normaliser_slug` du moteur et doit tomber sur le format du contrat
(`fenetre|workflow|contenu-…-AAAA`) ; - les identifiants publicitaires de clic (gclid, fbclid, msclkid…) sont
SIGNALÉS par leur nom et ÉCARTÉS : leur valeur n'est
  jamais conservée ni renvoyée (Loi 25, minimisation) ;
- les URL fournies sont des textes : elles ne sont jamais ouvertes, et la sortie ne les recopie pas (on rend leur rang).

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..utm import utm_engine

URL_MAX = 2048
URLS_MAX = 500
VALEUR_MAX = 100
CHAMPS_MAX = 50

CONFORME = "conforme"
NORMALISABLE = "normalisable"
NON_NORMALISABLE = "non_normalisable"
ABSENT = "absent"

# Identifiants de clic publicitaire : jamais conservés (leur NOM est signalé, jamais leur valeur).
IDENTIFIANTS_CLIC = frozenset(
    {
        "gclid",
        "gbraid",
        "wbraid",
        "dclid",
        "gclsrc",
        "fbclid",
        "msclkid",
        "ttclid",
        "twclid",
        "li_fat_id",
        "yclid",
        "igshid",
        "epik",
        "ScCid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
    }
)
_CLICS_MINUSCULES = frozenset(n.lower() for n in IDENTIFIANTS_CLIC)

# La table d'alias est la SEULE source de normalisation hors énuméré. Clés sous forme pliée (voir `plier`).
ALIAS_SOURCE: Mapping[str, str] = {
    "fb": "facebook",
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
    "m.facebook.com": "facebook",
    "l.facebook.com": "facebook",
    "lm.facebook.com": "facebook",
    "ig": "instagram",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "l.instagram.com": "instagram",
    "google.com": "google",
    "www.google.com": "google",
    "google.ca": "google",
    "www.google.ca": "google",
    "google-ads": "google",
    "googleads": "google",
    "adwords": "google",
    "gmb": "gbp",
    "google-business-profile": "gbp",
    "googlebusinessprofile": "gbp",
    "google-my-business": "gbp",
    "linkedin.com": "linkedin",
    "www.linkedin.com": "linkedin",
    "lnkd.in": "linkedin",
    "tiktok.com": "tiktok",
    "www.tiktok.com": "tiktok",
    "tik-tok": "tiktok",
    "perplexity.ai": "perplexity",
    "www.perplexity.ai": "perplexity",
    "newsletter": "infolettre",
}
ALIAS_MEDIUM: Mapping[str, str] = {
    "ppc": "cpc",
    "paid": "cpc",
    "paid-search": "cpc",
    "paidsearch": "cpc",
    "sea": "cpc",
    "payant": "cpc",
    "paid-social": "cpc",
    "organic": "organique",
    "seo": "organique",
    "gratuit": "organique",
    "social-media": "social",
    "reseaux-sociaux": "social",
    "rs": "social",
    "email": "courriel",
    "e-mail": "courriel",
    "mail": "courriel",
    "reference": "referral",
    "banner": "display",
    "banniere": "display",
}
# Valeurs qu'on refuse de trancher : la raison dit ce que le client doit préciser.
AMBIGUES: Mapping[str, str] = {
    "meta": "Facebook ou Instagram : préciser la plateforme",
    "social": "plateforme sociale non précisée (c'est un medium, pas une source)",
    "ads": "régie non précisée",
    "paid": "plateforme payante non précisée (c'est un medium, pas une source)",
    "direct": "visite directe : aucune source à attribuer",
    "(direct)": "visite directe : aucune source à attribuer",
    "none": "aucune source",
    "(none)": "aucune source",
    "(not-set)": "aucune source",
    "not-set": "aucune source",
}
_CONTROLES = re.compile(r"[\x00-\x1f\x7f-\x9f  ​-‏‪-‮⁦-⁩]")


def plier(valeur: str) -> str:
    """Forme pliée d'une valeur : sans accents, minuscules, espaces et soulignés en tirets, tirets fusionnés."""
    ascii_ = unicodedata.normalize("NFD", valeur).encode("ascii", "ignore").decode("ascii").lower().strip()
    return re.sub(r"-+", "-", re.sub(r"[\s_]+", "-", ascii_)).strip("-")


def _enums() -> tuple[tuple[str, ...], tuple[str, ...]]:
    contrat = utm_engine._charger_contrat()
    return tuple(contrat["enums"]["utm_source"]), tuple(contrat["enums"]["utm_medium"])


def _resultat(brut: Any, normalise: str | None, verdict: str, raison: str | None) -> dict[str, Any]:
    return {"brut_present": brut is not None, "normalise": normalise, "verdict": verdict, "raison": raison}


def _valeur_propre(brut: Any) -> tuple[str | None, str | None]:
    """(valeur, raison) : la valeur utilisable ou la raison de son refus."""
    if not isinstance(brut, str):
        return None, "texte attendu"
    if len(brut) > VALEUR_MAX:
        return None, f"valeur de plus de {VALEUR_MAX} caractères"
    if _CONTROLES.search(brut):
        return None, "caractère de contrôle refusé"
    return brut, None


def _normaliser_enum(
    brut: Any, enum: Sequence[str], alias: Mapping[str, str], nom: str, ambigus: Mapping[str, str] | None = None
) -> dict[str, Any]:
    if brut is None:
        return _resultat(None, None, ABSENT, f"{nom} absent")
    valeur, raison = _valeur_propre(brut)
    if valeur is None:
        return _resultat(brut, None, NON_NORMALISABLE, raison)
    pliee = plier(valeur)
    if not pliee:
        return _resultat(brut, None, NON_NORMALISABLE, f"{nom} vide")
    if ambigus and pliee in ambigus and pliee not in enum:
        return _resultat(brut, None, NON_NORMALISABLE, f"valeur ambiguë : {ambigus[pliee]}")
    if valeur == pliee and valeur in enum:
        return _resultat(brut, valeur, CONFORME, None)
    if pliee in enum:
        return _resultat(brut, pliee, NORMALISABLE, None)
    if pliee in alias:
        return _resultat(brut, alias[pliee], NORMALISABLE, None)
    return _resultat(brut, None, NON_NORMALISABLE, f"{nom} hors de la convention et de la table d'alias")


def normaliser_source(brut: Any) -> dict[str, Any]:
    sources, _ = _enums()
    return _normaliser_enum(brut, sources, ALIAS_SOURCE, "utm_source", AMBIGUES)


def normaliser_medium(brut: Any) -> dict[str, Any]:
    _, mediums = _enums()
    return _normaliser_enum(brut, mediums, ALIAS_MEDIUM, "utm_medium")


def normaliser_campagne(brut: Any) -> dict[str, Any]:
    if brut is None:
        return _resultat(None, None, ABSENT, "utm_campaign absent")
    valeur, raison = _valeur_propre(brut)
    if valeur is None:
        return _resultat(brut, None, NON_NORMALISABLE, raison)
    contrat = utm_engine._charger_contrat()
    slug = utm_engine.normaliser_slug(valeur)
    gabarit = re.compile(contrat["format"]["campaign"]["regex"])
    if not slug:
        return _resultat(brut, None, NON_NORMALISABLE, "utm_campaign vide après normalisation")
    if len(slug) > contrat["format"]["campaign"]["max_length"] or not gabarit.fullmatch(slug):
        return _resultat(
            brut,
            None,
            NON_NORMALISABLE,
            "utm_campaign hors du format de la convention (fenetre|workflow|contenu-<nom>-<année>)",
        )
    return _resultat(brut, slug, CONFORME if slug == valeur else NORMALISABLE, None)


def normaliser_contenu(brut: Any) -> dict[str, Any]:
    if brut is None:
        return _resultat(None, None, ABSENT, "utm_content absent")
    valeur, raison = _valeur_propre(brut)
    if valeur is None:
        return _resultat(brut, None, NON_NORMALISABLE, raison)
    contrat = utm_engine._charger_contrat()
    slug = utm_engine.normaliser_slug(valeur)
    if not slug or len(slug) > contrat["format"]["content"]["max_length"]:
        return _resultat(brut, None, NON_NORMALISABLE, "utm_content vide ou trop long après normalisation")
    return _resultat(brut, slug, CONFORME if slug == valeur else NORMALISABLE, None)


def normaliser_parametres(
    source: Any = None, medium: Any = None, campagne: Any = None, contenu: Any = None
) -> dict[str, Any]:
    """Les quatre paramètres normalisés un à un, et le verdict d'ensemble (le plus faible des paramètres REQUIS ; le
    contenu est facultatif et ne dégrade jamais le verdict d'un lien sans contenu)."""
    parties = {
        "utm_source": normaliser_source(source),
        "utm_medium": normaliser_medium(medium),
        "utm_campaign": normaliser_campagne(campagne),
        "utm_content": normaliser_contenu(contenu),
    }
    requis = [parties[n]["verdict"] for n in ("utm_source", "utm_medium", "utm_campaign")]
    if contenu is not None:
        requis.append(parties["utm_content"]["verdict"])
    if NON_NORMALISABLE in requis or ABSENT in requis:
        global_ = NON_NORMALISABLE
    elif NORMALISABLE in requis:
        global_ = NORMALISABLE
    else:
        global_ = CONFORME
    return {"parametres": parties, "verdict": global_}


def analyser_url(url: Any) -> dict[str, Any]:
    """Verdict d'UNE URL fournie en texte (jamais ouverte). La sortie ne contient ni l'URL ni aucune valeur brute."""
    if not isinstance(url, str) or not url.strip():
        return {
            "verdict": NON_NORMALISABLE,
            "raison": "URL absente ou vide",
            "parametres": {},
            "identifiants_ecartes": [],
        }
    if len(url) > URL_MAX:
        return {
            "verdict": NON_NORMALISABLE,
            "raison": f"URL de plus de {URL_MAX} caractères",
            "parametres": {},
            "identifiants_ecartes": [],
        }
    if _CONTROLES.search(url):
        return {
            "verdict": NON_NORMALISABLE,
            "raison": "caractère de contrôle refusé",
            "parametres": {},
            "identifiants_ecartes": [],
        }
    try:
        morceaux = urllib.parse.urlsplit(url.strip())
        paires = urllib.parse.parse_qsl(morceaux.query, keep_blank_values=True, max_num_fields=CHAMPS_MAX)
    except ValueError:
        return {
            "verdict": NON_NORMALISABLE,
            "raison": "URL illisible ou avec trop de paramètres",
            "parametres": {},
            "identifiants_ecartes": [],
        }
    if morceaux.scheme not in ("http", "https"):
        return {
            "verdict": NON_NORMALISABLE,
            "raison": "schéma refusé : http ou https seulement",
            "parametres": {},
            "identifiants_ecartes": [],
        }
    ecartes = sorted({cle for cle, _ in paires if cle.lower() in _CLICS_MINUSCULES})
    utm = [(cle.lower(), val) for cle, val in paires if cle.lower().startswith("utm_")]
    doubles = sorted({cle for cle, _ in utm if sum(1 for c, _v in utm if c == cle) > 1})
    if doubles:
        return {
            "verdict": NON_NORMALISABLE,
            "raison": f"paramètre répété : {', '.join(doubles)}",
            "parametres": {},
            "identifiants_ecartes": ecartes,
        }
    valeurs = dict(utm)
    resultat = normaliser_parametres(
        valeurs.get("utm_source"), valeurs.get("utm_medium"), valeurs.get("utm_campaign"), valeurs.get("utm_content")
    )
    inconnus = sorted(c for c in valeurs if c not in resultat["parametres"])
    return {
        "verdict": resultat["verdict"],
        "raison": None,
        "parametres": resultat["parametres"],
        "utm_inconnus": inconnus,
        "identifiants_ecartes": ecartes,
    }


def analyser_urls(urls: Sequence[Any]) -> dict[str, Any]:
    """Un verdict par URL (par rang) et la couverture exacte. Au plus `URLS_MAX` URL (sinon `ValueError` typée par "
    "l'appelant)."""
    if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes)):
        raise ValueError("REJ-MESURE-UTM-ENTREE-INVALIDE : liste d'URL attendue")
    if len(urls) > URLS_MAX:
        raise ValueError(f"REJ-MESURE-UTM-ENTREE-INVALIDE : au plus {URLS_MAX} URL par appel")
    lignes = []
    for rang, url in enumerate(urls):
        lignes.append({"rang": rang, **analyser_url(url)})
    total = len(lignes)
    compte = {
        v: sum(1 for ligne in lignes if ligne["verdict"] == v) for v in (CONFORME, NORMALISABLE, NON_NORMALISABLE)
    }

    def part(n: int) -> str | None:
        return (
            None
            if total == 0
            else format((Decimal(n) / Decimal(total)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")
        )

    return {
        "urls": lignes,
        "couverture": {
            "total": total,
            "conformes": compte[CONFORME],
            "normalisables": compte[NORMALISABLE],
            "non_normalisables": compte[NON_NORMALISABLE],
            "part_conforme": part(compte[CONFORME]),
            "part_exploitable": part(compte[CONFORME] + compte[NORMALISABLE]),
        },
    }


__all__ = [
    "ABSENT",
    "ALIAS_MEDIUM",
    "ALIAS_SOURCE",
    "AMBIGUES",
    "CONFORME",
    "IDENTIFIANTS_CLIC",
    "NON_NORMALISABLE",
    "NORMALISABLE",
    "URLS_MAX",
    "URL_MAX",
    "analyser_url",
    "analyser_urls",
    "normaliser_campagne",
    "normaliser_contenu",
    "normaliser_medium",
    "normaliser_parametres",
    "normaliser_source",
    "plier",
]
