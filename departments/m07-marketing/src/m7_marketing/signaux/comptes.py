"""Registre des sources de données propres que le client a déclarées (une propriété Search Console, un site Umami, un
compte publicitaire, une fiche d'établissement…).

Registre append-only à chaîne de hachage (`journal_chaine`) : `source_enregistree`, `source_desactivee`. Il ne contient
JAMAIS un jeton : seulement le NOM du secret dans le coffre (`secret_ref.nom`, et au plus les noms de secrets annexes
que
la source exige, p. ex. le jeton de développeur Google Ads). Le connecteur résout la valeur au moment de lire. Une
source
inconnue ou désactivée n'est jamais lue.

Déclarer une source est une connexion permanente à un système externe : c'est une décision de la direction (N3, voir
`signaux_outils.py`). Le registre ne prouve pas que le compte est accessible ni autorisé chez le fournisseur, seulement
que l'entreprise l'a déclaré.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
import re
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import Any

from .. import journal_chaine
from . import modele

M_ENREGISTRE = "source_enregistree"
M_DESACTIVE = "source_desactivee"

REJ_SOURCE = "REJ-SIGNAUX-SOURCE-INCONNUE"
REJ_ARGUMENT = "REJ-SIGNAUX-ARGUMENT-INVALIDE"
REJ_SECRET_REF = "REJ-SIGNAUX-SECRET-REF"
REJ_EXISTANT = "REJ-SIGNAUX-COMPTE-EXISTANT"
REJ_DESACTIVE = "REJ-SIGNAUX-COMPTE-DESACTIVE"
REJ_INCONNU = "REJ-SIGNAUX-COMPTE-INCONNU"
REJ_JOURNAL = "REJ-SIGNAUX-JOURNAL-ALTERE"

_NOM_COFFRE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_HOTE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_CHEMIN_BASE = re.compile(r"^(?:/[a-z0-9._~-]{1,40}){0,3}/?$")
# Forme de l'identifiant externe, par source. Fermé : une forme inconnue est refusée, jamais devinée.
_RESSOURCES: Mapping[str, re.Pattern[str]] = {
    modele.SEARCH_CONSOLE: re.compile(
        r"^(?:https://[a-z0-9.-]{3,253}(?:/[A-Za-z0-9._~/-]{0,100})?|sc-domain:[a-z0-9.-]{3,253})$"
    ),
    modele.BING_WEBMASTER: re.compile(r"^https://[a-z0-9.-]{3,253}(?:/[A-Za-z0-9._~/-]{0,100})?$"),
    modele.PAGESPEED: re.compile(r"^https://[a-z0-9.-]{3,253}(?:/[A-Za-z0-9._~/-]{0,100})?$"),
    modele.CRUX: re.compile(r"^https://[a-z0-9.-]{3,253}$"),
    modele.UMAMI: re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    modele.MATOMO: re.compile(r"^[1-9][0-9]{0,8}$"),
    modele.GBP_AVIS: re.compile(r"^accounts/[0-9]{1,24}/locations/[0-9]{1,24}$"),
    modele.GBP_INSIGHTS: re.compile(r"^locations/[0-9]{1,24}$"),
    modele.GOOGLE_ADS: re.compile(r"^[0-9]{10}$"),
    modele.META_ADS: re.compile(r"^act_[0-9]{5,20}$"),
}
OPTIONS_PAR_SOURCE: Mapping[str, tuple[str, ...]] = {modele.GBP_AVIS: ("extraits_avis",)}


@dataclasses.dataclass(frozen=True)
class CompteSource:
    source: str
    compte_ref: str
    ressource: str
    secret_nom: str
    secrets_annexes: tuple[tuple[str, str], ...]
    base_url: str | None
    options: tuple[tuple[str, bool], ...]
    fictif: bool
    actif: bool = True

    def option(self, nom: str) -> bool:
        return dict(self.options).get(nom, False)


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def url_base_valide(valeur: Any) -> str | None:
    """L'adresse HTTPS d'un service auto-hébergé : un nom d'hôte public (pas d'adresse IP, pas `localhost`), sans
    identifiant
    ni port ni paramètres. Rend l'adresse canonique sans barre finale, ou `None`."""
    if not isinstance(valeur, str) or len(valeur) > 200:
        return None
    morceaux = urllib.parse.urlsplit(valeur)
    try:
        port = morceaux.port
    except ValueError:
        return None
    if (
        morceaux.scheme != "https"
        or morceaux.username is not None
        or morceaux.password is not None
        or port not in (None, 443)
        or morceaux.query
        or morceaux.fragment
        or not morceaux.hostname
        or not _HOTE.fullmatch(morceaux.hostname)
        or not _CHEMIN_BASE.fullmatch(morceaux.path or "")
    ):
        return None
    # Une adresse IP (décimale, hexadécimale, v4 ou v6) n'a pas d'étiquette finale alphabétique : `_HOTE` l'a déjà
    # refusée.
    if morceaux.hostname.endswith((".local", ".internal", ".localhost")):
        return None
    return f"https://{morceaux.hostname}{(morceaux.path or '').rstrip('/')}"


def plier(journal: Iterable[Any]) -> dict[tuple[str, str], CompteSource]:
    comptes: dict[tuple[str, str], CompteSource] = {}
    for m in journal:
        if m["type"] == M_ENREGISTRE:
            comptes[(m["source"], m["compte_ref"])] = CompteSource(
                source=m["source"],
                compte_ref=m["compte_ref"],
                ressource=m["ressource"],
                secret_nom=m["secret_ref"]["nom"],
                secrets_annexes=tuple(sorted((k, v["nom"]) for k, v in m["secrets_annexes"].items())),
                base_url=m["base_url"],
                options=tuple(sorted(m["options"].items())),
                fictif=m["fictif"],
                actif=True,
            )
        elif m["type"] == M_DESACTIVE:
            comptes[(m["source"], m["compte_ref"])] = dataclasses.replace(
                comptes[(m["source"], m["compte_ref"])], actif=False
            )
    return comptes


def actifs(journal: Iterable[Any]) -> dict[tuple[str, str], CompteSource]:
    return {cle: c for cle, c in plier(journal).items() if c.actif}


def enregistrer(
    journal: Any,
    source: Any,
    compte_ref: Any,
    ressource: Any,
    secret_ref: Any,
    secrets_annexes: Any,
    base_url: Any,
    options: Any,
    fictif: Any,
    par: str,
    horodatage: str,
) -> dict[str, Any]:
    if source not in modele.SOURCES_LECTURE:
        return _refus(
            REJ_SOURCE,
            "$.source",
            f"une de {list(modele.SOURCES_LECTURE)} attendue (une source d'import seulement n'a pas de compte)",
        )
    decl = modele.SOURCES[source]
    if not modele.compte_valide(compte_ref):
        return _refus(REJ_ARGUMENT, "$.compte_ref", "minuscules, chiffres, point, tiret, souligné ; 2 à 64 caractères")
    if type(fictif) is not bool:
        return _refus(REJ_ARGUMENT, "$.fictif", "booléen attendu")
    if not isinstance(ressource, str) or not _RESSOURCES[source].fullmatch(ressource):
        return _refus(REJ_ARGUMENT, "$.ressource", f"identifiant de ressource invalide pour {source}")
    if (
        not isinstance(secret_ref, Mapping)
        or set(secret_ref) != {"nom"}
        or not isinstance(secret_ref["nom"], str)
        or not _NOM_COFFRE.fullmatch(secret_ref["nom"])
    ):
        return _refus(
            REJ_SECRET_REF, "$.secret_ref", "{nom} attendu : le NOM du secret dans le coffre, jamais le jeton"
        )
    annexes = secrets_annexes if secrets_annexes is not None else {}
    if (
        not isinstance(annexes, Mapping)
        or set(annexes) != set(decl.secrets_annexes)
        or any(
            not isinstance(v, Mapping)
            or set(v) != {"nom"}
            or not isinstance(v["nom"], str)
            or not _NOM_COFFRE.fullmatch(v["nom"])
            for v in annexes.values()
        )
    ):
        return _refus(
            REJ_SECRET_REF,
            "$.secrets_annexes",
            f"secrets annexes exigés par {source} : {list(decl.secrets_annexes)}, chacun {{nom}}",
        )
    if decl.auto_heberge:
        canonique = url_base_valide(base_url)
        if canonique is None:
            return _refus(
                REJ_ARGUMENT,
                "$.base_url",
                "adresse HTTPS d'un nom d'hôte public (ni IP, ni port, ni "
                "identifiant, ni paramètres) exigée pour un service auto-hébergé",
            )
    else:
        canonique = None
        if base_url is not None:
            return _refus(REJ_ARGUMENT, "$.base_url", f"{source} n'a pas d'adresse de base déclarable")
    permises = OPTIONS_PAR_SOURCE.get(source, ())
    opts = options if options is not None else {}
    if not isinstance(opts, Mapping) or set(opts) - set(permises) or any(type(v) is not bool for v in opts.values()):
        return _refus(REJ_ARGUMENT, "$.options", f"options permises pour {source} : {list(permises)} (booléens)")
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return _refus(REJ_JOURNAL, "$", "; ".join(problemes[:3]))
    nouveau = {
        "source": source,
        "compte_ref": compte_ref,
        "ressource": ressource,
        "secret_ref": {"nom": secret_ref["nom"]},
        "secrets_annexes": {k: {"nom": annexes[k]["nom"]} for k in sorted(annexes)},
        "base_url": canonique,
        "options": {k: opts[k] for k in sorted(opts)},
        "fictif": fictif,
    }
    existant = plier(journal).get((source, compte_ref))
    if existant is not None:
        if not existant.actif:
            return _refus(
                REJ_DESACTIVE, "$.compte_ref", "compte désactivé : un autre identifiant pour un nouvel enregistrement"
            )
        identique = (
            existant.ressource,
            existant.secret_nom,
            existant.secrets_annexes,
            existant.base_url,
            existant.options,
            existant.fictif,
        ) == (
            ressource,
            secret_ref["nom"],
            tuple(sorted((k, v["nom"]) for k, v in nouveau["secrets_annexes"].items())),
            canonique,
            tuple(sorted(nouveau["options"].items())),
            fictif,
        )
        if identique:
            return {"accepte": True, "source": source, "compte_ref": compte_ref, "deja_enregistre": True}
        return _refus(
            REJ_EXISTANT, "$.compte_ref", "ce compte existe avec un autre enregistrement : un compte ne se modifie pas"
        )
    journal_chaine.ajouter(journal, M_ENREGISTRE, {**nouveau, "par": par}, horodatage)
    return {"accepte": True, "source": source, "compte_ref": compte_ref, "deja_enregistre": False}


def desactiver(journal: Any, source: str, compte_ref: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return _refus(REJ_JOURNAL, "$", "; ".join(problemes[:3]))
    courant = plier(journal).get((source, compte_ref))
    if courant is None:
        return _refus(REJ_INCONNU, "$.compte_ref", f"compte inconnu : {source}/{compte_ref}")
    if not courant.actif:
        return {"accepte": True, "source": source, "compte_ref": compte_ref, "deja_desactive": True}
    journal_chaine.ajouter(
        journal, M_DESACTIVE, {"source": source, "compte_ref": compte_ref, "par": par, "motif": motif[:300]}, horodatage
    )
    return {"accepte": True, "source": source, "compte_ref": compte_ref, "deja_desactive": False}


__all__ = ["CompteSource", "OPTIONS_PAR_SOURCE", "actifs", "desactiver", "enregistrer", "plier", "url_base_valide"]
