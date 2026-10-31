"""Contrat consommateur successeur M8 → M9 (M9.3) : preuve de définition PROPRE à chaque observation.

Module pur. Il remplace la projection de liaisons globales (empreinte → révision), qui pouvait rendre ``COMPATIBLE``
une ancienne observation sans preuve propre dès qu'une liaison était publiée. Trois principes :

1. **Preuve propre.** Une observation n'est comparée que si ELLE porte ``preuve_definition`` : registre, clé, révision
   et empreinte sous lesquelles son producteur l'a calculée. Une empreinte égale à une publication ne prouve pas la
   provenance d'une observation : sans preuve propre, elle reste ``VERSION_NON_COMPARABLE`` (``PREUVE_PROPRE_ABSENTE``).
2. **Identité du contenu ≠ révision de publication.** L'historique publié peut contenir A(v1) → B(v2) → A(v3) : une même
   empreinte à plusieurs révisions est légitime. Seule est une corruption une même (clé, révision) portant deux
   empreintes. Aucune révision n'est choisie à la place de la preuve ; aucun historique n'est écrasé.
3. **Registres non transposés.** Le dictionnaire (clé ``famille/module/id``) et le registre de surveillance (clé
   ``metric_id``) ont des numérotations distinctes : une preuve n'est vérifiée que dans l'historique de SON registre.
   Deux familles ou modules portant le même ``id`` sont deux clés distinctes.

L'historique arrive par pages (``assembler_historique``) : même ``vue`` et même total sur toutes les pages, départs
contigus sans recouvrement, dernière page close, révisions 1..N sans trou par clé, ``vue`` = SHA-256 du JSON canonique
de la liste complète (une altération est détectée). Toute incohérence REFUSE l'historique entier, sans réparation.

Une preuve de définition ne prouve que la définition : jamais la vérité d'un montant ni d'une inférence
(``valeur_verifiee`` reste faux).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

VERSION = "2026-10-30.1"
REGISTRES = frozenset({"dictionnaire", "surveillance"})
RAISONS = frozenset(
    {
        "HISTORIQUE_ABSENT",
        "PREUVE_PROPRE_ABSENTE",
        "PREUVE_MAL_FORMEE",
        "PREUVE_INCOHERENTE",
        "REGISTRE_DIFFERENT",
        "CLE_INCONNUE",
        "REVISION_INCONNUE",
        "EMPREINTE_DIFFERENTE_A_CETTE_REVISION",
    }
)
_EMPREINTE = re.compile(r"[0-9a-f]{64}")
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_CHAMPS_CLE = {"dictionnaire": ("famille", "module", "id"), "surveillance": ("metric_id",)}
LIMITES = (
    "Une preuve de définition prouve sous quelle définition une valeur a été calculée, jamais que la valeur est vraie.",
    "Les numéros de révision du dictionnaire et du registre de surveillance ne sont jamais transposés entre eux.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _canonique(valeur: object) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def vue_de(registre: str, publications: Sequence[Mapping]) -> str:
    """Empreinte d'un historique complet : SHA-256 du JSON canonique ``{registre, publications}`` (ordre publié)."""
    return hashlib.sha256(_canonique({"registre": registre, "publications": list(publications)}).encode()).hexdigest()


def cle_texte(registre: object, cle: object) -> str | None:
    """Clé canonique ``registre:segment/…`` ; ``None`` si la clé n'a pas EXACTEMENT les champs de son registre."""
    if registre not in REGISTRES or not isinstance(cle, Mapping):
        return None
    champs = _CHAMPS_CLE[registre]
    if set(cle) != set(champs):
        return None
    segments = [cle[c] for c in champs]
    if not all(type(s) is str and _SEGMENT.fullmatch(s) for s in segments):
        return None
    return f"{registre}:" + "/".join(segments)


def _publication(ligne: object, registre: str, index: int) -> tuple[str, int, str]:
    if not isinstance(ligne, Mapping) or set(ligne) != {"cle", "revision", "empreinte"}:
        raise _refus("REJ-HISTORIQUE-FORME", f"publication {index} : exactement cle, revision et empreinte")
    cle = cle_texte(registre, ligne["cle"])
    revision, empreinte = ligne["revision"], ligne["empreinte"]
    if cle is None:
        raise _refus("REJ-HISTORIQUE-FORME", f"publication {index} : clé invalide pour le registre {registre}")
    if type(revision) is not int or revision < 1:
        raise _refus("REJ-HISTORIQUE-FORME", f"publication {index} : révision entière >= 1 requise")
    if type(empreinte) is not str or not _EMPREINTE.fullmatch(empreinte):
        raise _refus("REJ-HISTORIQUE-FORME", f"publication {index} : empreinte de 64 hexadécimaux requise")
    return cle, revision, empreinte


def assembler_historique(pages: object) -> dict:
    """Assemble et vérifie les pages d'un historique publié. Refus nommé à la moindre incohérence."""
    if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)) or not pages:
        raise _refus("REJ-HISTORIQUE-PAGES", "liste non vide de pages requise")
    entetes = set()
    attendu = 0
    publications: list[Mapping] = []
    for numero, page in enumerate(pages):
        if not isinstance(page, Mapping) or set(page) != {
            "registre", "vue", "total", "depart", "prochain_depart", "publications",
        }:  # fmt: skip
            raise _refus("REJ-HISTORIQUE-PAGES", f"page {numero} : champs exacts requis")
        registre, vue, total = page["registre"], page["vue"], page["total"]
        if registre not in REGISTRES or type(vue) is not str or not _EMPREINTE.fullmatch(vue):
            raise _refus("REJ-HISTORIQUE-PAGES", f"page {numero} : registre ou vue invalide")
        if type(total) is not int or total < 0 or type(page["depart"]) is not int:
            raise _refus("REJ-HISTORIQUE-PAGES", f"page {numero} : total et départ entiers requis")
        entetes.add((registre, vue, total))
        if len(entetes) != 1:
            raise _refus("REJ-HISTORIQUE-PAGINATION", "pages d'historiques différents (registre, vue ou total)")
        if page["depart"] != attendu:
            raise _refus("REJ-HISTORIQUE-PAGINATION", f"page {numero} : départ {page['depart']} au lieu de {attendu}")
        lignes = page["publications"]
        if not isinstance(lignes, list):
            raise _refus("REJ-HISTORIQUE-PAGES", f"page {numero} : liste de publications requise")
        publications.extend(lignes)
        attendu += len(lignes)
        suivant = page["prochain_depart"]
        derniere = numero == len(pages) - 1
        if derniere and suivant is not None:
            raise _refus("REJ-HISTORIQUE-PAGINATION", "dernière page non close (prochain_depart non nul)")
        if not derniere and suivant != attendu:
            raise _refus("REJ-HISTORIQUE-PAGINATION", f"page {numero} : prochain_depart incohérent")
    registre, vue, total = next(iter(entetes))
    if attendu != total:
        raise _refus("REJ-HISTORIQUE-PAGINATION", f"{attendu} publications reçues pour un total de {total}")
    lues = [_publication(ligne, registre, index) for index, ligne in enumerate(publications)]
    if vue_de(registre, publications) != vue:
        raise _refus("REJ-HISTORIQUE-CORROMPU", "la vue ne correspond pas au contenu reçu")
    par_cle: dict[str, dict[int, str]] = {}
    for cle, revision, empreinte in lues:
        revisions = par_cle.setdefault(cle, {})
        if revision in revisions:
            raise _refus("REJ-HISTORIQUE-CORROMPU", f"{cle} : révision {revision} publiée deux fois")
        revisions[revision] = empreinte
    for cle, revisions in par_cle.items():
        if sorted(revisions) != list(range(1, len(revisions) + 1)):
            raise _refus("REJ-HISTORIQUE-TROU", f"{cle} : révisions non contiguës depuis 1")
    return {"registre": registre, "vue": vue, "total": total, "cles": par_cle}


def verifier_preuve(observation: Mapping, historique: Mapping | None) -> dict:
    """Statut de comparabilité d'UNE observation ``{metric_id, version_definition, preuve_definition?}``.

    ``COMPATIBLE`` : preuve propre vérifiée à la révision courante de sa clé. ``VERSION_PERIMEE`` : preuve vérifiée à
    une révision antérieure (``meme_contenu_que_la_courante`` le dit pour A/B/A, sans changer le statut). Sinon
    ``VERSION_NON_COMPARABLE`` avec une raison de ``RAISONS``."""

    def non_comparable(raison: str, **details) -> dict:
        return {"statut": "VERSION_NON_COMPARABLE", "raison": raison, "valeur_verifiee": False, **details}

    if historique is None:
        return non_comparable("HISTORIQUE_ABSENT")
    preuve = observation.get("preuve_definition")
    if preuve is None:
        return non_comparable("PREUVE_PROPRE_ABSENTE")
    if not isinstance(preuve, Mapping) or set(preuve) != {"registre", "cle", "revision", "empreinte"}:
        return non_comparable("PREUVE_MAL_FORMEE")
    registre, revision, empreinte = preuve["registre"], preuve["revision"], preuve["empreinte"]
    cle = cle_texte(registre, preuve["cle"])
    if (
        cle is None
        or type(revision) is not int
        or revision < 1
        or type(empreinte) is not str
        or not _EMPREINTE.fullmatch(empreinte)
    ):
        return non_comparable("PREUVE_MAL_FORMEE")
    identifiant = preuve["cle"]["id"] if registre == "dictionnaire" else preuve["cle"]["metric_id"]
    if empreinte != observation.get("version_definition") or identifiant != observation.get("metric_id"):
        return non_comparable("PREUVE_INCOHERENTE")
    if registre != historique["registre"]:
        return non_comparable("REGISTRE_DIFFERENT")
    revisions = historique["cles"].get(cle)
    if revisions is None:
        return non_comparable("CLE_INCONNUE", cle=cle)
    if revision not in revisions:
        return non_comparable("REVISION_INCONNUE", cle=cle, revision=revision)
    if revisions[revision] != empreinte:
        return non_comparable("EMPREINTE_DIFFERENTE_A_CETTE_REVISION", cle=cle, revision=revision)
    courante = max(revisions)
    commun = {"cle": cle, "revision": revision, "revision_courante": courante, "valeur_verifiee": False}
    if revision == courante:
        return {"statut": "COMPATIBLE", **commun}
    return {"statut": "VERSION_PERIMEE", "meme_contenu_que_la_courante": revisions[courante] == empreinte, **commun}
