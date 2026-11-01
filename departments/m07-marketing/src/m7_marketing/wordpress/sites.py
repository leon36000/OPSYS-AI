"""Registre des sites WordPress du client : un site, une clé de coffre, un identifiant que le plugin connaît.

Registre append-only à chaîne de hachage (`journal_chaine`) : `site_enregistre`, `site_desactive`. Le registre ne
contient
JAMAIS le secret partagé : seulement `secret_ref` (le NOM du secret dans le coffre et l'identifiant de clé annoncé au
plugin). Un site enregistré ne se modifie pas : pour changer d'adresse ou de coffre, on désactive et on enregistre
un autre
`site_id` (le jeton d'approbation est lié au `site_id`, donc à un seul site à la fois).

Un site fictif (`fictif: true`) a obligatoirement un domaine réservé (`.example`, `.test`, `.invalid`, `.localhost`)
; un site
réel n'en a jamais un : une fixture ne peut pas pointer sur un vrai domaine, ni l'inverse.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from .. import journal_chaine
from . import jeton, signature

TYPES_CONTENU = ("post", "page")
RESERVES = (".example", ".test", ".invalid", ".localhost")
MAILLON_ENREGISTRE = "site_enregistre"
MAILLON_DESACTIVE = "site_desactive"

REJ_SITE = "REJ-WP-SITE-INVALIDE"
REJ_URL = "REJ-WP-URL-INVALIDE"
REJ_SECRET_REF = "REJ-WP-SECRET-REF-INVALIDE"
REJ_TYPES = "REJ-WP-TYPES-INVALIDES"
REJ_FICTIF = "REJ-WP-FICTIF-DOMAINE"
REJ_EXISTANT = "REJ-WP-SITE-EXISTANT"
REJ_DESACTIVE = "REJ-WP-SITE-DESACTIVE"
REJ_INCONNU = "REJ-WP-SITE-INCONNU"
REJ_JOURNAL = "REJ-WP-JOURNAL-ALTERE"

_NOM_COFFRE = re.compile(r"[a-z0-9][a-z0-9._-]{2,79}")
_ETIQUETTE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_CHEMIN = re.compile(r"(?:/[A-Za-z0-9._~-]{1,60}){0,4}/?")


@dataclasses.dataclass(frozen=True)
class SiteWordPress:
    site_id: str
    base_url: str
    secret_nom: str
    cle_id: str
    types_autorises: tuple[str, ...]
    fictif: bool


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def hote_reserve(hote: str) -> bool:
    return hote.endswith(RESERVES)


def valider_url(base_url: Any, fictif: bool) -> tuple[str | None, str | None]:
    """(url normalisée, détail du refus). HTTPS seulement, nom DNS (aucune adresse IP, aucun identifiant dans l'URL),
    port 443 par défaut, aucun paramètre ni fragment, chemin court (installation dans un sous-dossier permise)."""
    if not isinstance(base_url, str) or len(base_url) > 200 or base_url != base_url.strip():
        return None, "URL de 200 caractères au plus, sans espace autour"
    try:
        parties = urlsplit(base_url)
        port = parties.port
    except ValueError:
        return None, "URL illisible"
    hote = parties.hostname or ""
    if parties.scheme != "https":
        return None, "https obligatoire"
    if parties.username or parties.password or parties.query or parties.fragment or port not in (None, 443):
        return None, "ni identifiant, ni paramètre, ni fragment, ni autre port que 443"
    etiquettes = hote.split(".")
    if (
        len(etiquettes) < 2
        or parties.netloc != parties.netloc.lower()
        or not all(_ETIQUETTE.fullmatch(e) for e in etiquettes)
        or etiquettes[-1].isdigit()
    ):
        return None, "nom d'hôte DNS en minuscules attendu (aucune adresse IP)"
    if not _CHEMIN.fullmatch(parties.path) or any(segment in (".", "..") for segment in parties.path.split("/")):
        return None, "chemin d'installation invalide"
    if fictif != hote_reserve(hote):
        return None, (
            "un site fictif a un domaine réservé (.example, .test, .invalid, .localhost)"
            if fictif
            else "un site réel n'a pas de domaine réservé"
        )
    return f"https://{hote}{parties.path.rstrip('/')}", None


def plier(journal: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """`site_id -> {site, actif}` du journal."""
    sites: dict[str, dict[str, Any]] = {}
    for maillon in journal:
        if maillon["type"] == MAILLON_ENREGISTRE:
            donnees = maillon["site"]
            sites[donnees["site_id"]] = {
                "site": SiteWordPress(
                    site_id=donnees["site_id"],
                    base_url=donnees["base_url"],
                    secret_nom=donnees["secret_ref"]["nom"],
                    cle_id=donnees["secret_ref"]["cle_id"],
                    types_autorises=tuple(donnees["types_autorises"]),
                    fictif=donnees["fictif"],
                ),
                "actif": True,
            }
        elif maillon["type"] == MAILLON_DESACTIVE:
            sites[maillon["site_id"]]["actif"] = False
    return sites


def actifs(journal: Iterable[Any]) -> dict[str, SiteWordPress]:
    return {i: e["site"] for i, e in plier(journal).items() if e["actif"]}


def _lire(journal: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return {}, _refus(REJ_JOURNAL, "$", "; ".join(problemes[:3]))
    return plier(journal), None


def enregistrer(
    journal: Any,
    site_id: Any,
    base_url: Any,
    secret_ref: Any,
    types_autorises: Any,
    fictif: Any,
    par: str,
    horodatage: str,
) -> dict[str, Any]:
    """Enregistre un site. Idempotent pour le même enregistrement ; un autre contenu sous le même `site_id` est refusé.
    """
    if not isinstance(site_id, str) or not jeton.MOTIF_SITE.fullmatch(site_id):
        return _refus(REJ_SITE, "$.site_id", "minuscules, chiffres, point, tiret ; 3 à 64 caractères")
    if type(fictif) is not bool:
        return _refus(REJ_SITE, "$.fictif", "booléen attendu")
    url, detail = valider_url(base_url, fictif)
    if url is None:
        code = REJ_FICTIF if "réservé" in (detail or "") else REJ_URL
        return _refus(code, "$.base_url", detail or "invalide")
    if (
        not isinstance(secret_ref, Mapping)
        or set(secret_ref) != {"nom", "cle_id"}
        or not isinstance(secret_ref["nom"], str)
        or not _NOM_COFFRE.fullmatch(secret_ref["nom"])
        or not isinstance(secret_ref["cle_id"], str)
        or not signature.MOTIF_CLE.fullmatch(secret_ref["cle_id"])
    ):
        return _refus(
            REJ_SECRET_REF, "$.secret_ref", "{nom (nom du secret dans le coffre), cle_id} attendus : jamais la valeur"
        )
    if (
        not isinstance(types_autorises, (list, tuple))
        or not types_autorises
        or len(set(types_autorises)) != len(types_autorises)
        or not set(types_autorises) <= set(TYPES_CONTENU)
    ):
        return _refus(REJ_TYPES, "$.types_autorises", f"sous-ensemble non vide, sans doublon, de {list(TYPES_CONTENU)}")
    existants, refus = _lire(journal)
    if refus is not None:
        return refus
    site = {
        "site_id": site_id,
        "base_url": url,
        "secret_ref": {"nom": secret_ref["nom"], "cle_id": secret_ref["cle_id"]},
        "types_autorises": sorted(types_autorises),
        "fictif": fictif,
    }
    courant = existants.get(site_id)
    if courant is not None:
        if not courant["actif"]:
            return _refus(REJ_DESACTIVE, "$.site_id", "site désactivé : un autre site_id pour un nouvel enregistrement")
        if dataclasses.asdict(courant["site"]) == {
            "site_id": site_id,
            "base_url": url,
            "secret_nom": secret_ref["nom"],
            "cle_id": secret_ref["cle_id"],
            "types_autorises": tuple(site["types_autorises"]),
            "fictif": fictif,
        }:
            return {"accepte": True, "site_id": site_id, "deja_enregistre": True}
        return _refus(
            REJ_EXISTANT, "$.site_id", "ce site_id existe avec un autre enregistrement : un site ne se modifie pas"
        )
    journal_chaine.ajouter(journal, MAILLON_ENREGISTRE, {"site": site, "par": par}, horodatage)
    return {"accepte": True, "site_id": site_id, "deja_enregistre": False}


def desactiver(journal: Any, site_id: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    existants, refus = _lire(journal)
    if refus is not None:
        return refus
    courant = existants.get(site_id)
    if courant is None:
        return _refus(REJ_INCONNU, "$.site_id", f"site inconnu : {site_id!r}")
    if not courant["actif"]:
        return {"accepte": True, "site_id": site_id, "deja_desactive": True}
    journal_chaine.ajouter(
        journal, MAILLON_DESACTIVE, {"site_id": site_id, "par": par, "motif": motif[:300]}, horodatage
    )
    return {"accepte": True, "site_id": site_id, "deja_desactive": False}
