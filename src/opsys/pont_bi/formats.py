"""Formats d'export : CSV, JSON Lines et OData v4 minimal, en stdlib, avec minimisation des renseignements personnels.

Principes (tous testés) :

* LECTURE SEULE, SANS SURPRISE. Aucun format n'exécute ni n'interprète de donnée. Une cellule CSV qui pourrait être lue
  comme une formule par un tableur (début par ``=``, ``+``, ``-``, ``@``, tabulation ou retour chariot) est précédée
  d'une
  apostrophe, sauf si c'est un nombre décimal exact (une marge de ``-1500.00`` reste un nombre).
* MINIMISATION PII. Une colonne dont la FORME est déclarée (identifiant, instant, décimal, code) n'est jamais masquée
mais
  est VÉRIFIÉE : une valeur qui ne respecte pas sa forme (un courriel dans un identifiant) est masquée par le masqueur
  de
  `opsys.observabilite`. Une colonne de texte libre est toujours masquée. Un masqueur absent ou en panne est un refus
  (fail-closed), jamais un export sans masquage.
* OData v4 MINIMAL, dit honnêtement : document de service, `$metadata` (EDMX), collection avec `$top`, `$skip`,
`$select`,
  `$count`. Toute autre option (`$filter`, `$orderby`, `$expand`, `$search`, `$apply`…) est refusée 501 dans le format
  d'erreur OData, jamais ignorée en silence (un `$filter` ignoré ferait croire à un filtre qui n'a pas eu lieu).
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from ..observabilite.pii import MasqueurPII
from .jeux import EDM_ENTIER_LONG, Colonne, Jeu

_FORMULE = re.compile(r"^[=+\-@\t\r]")
_NOMBRE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
TOP_MAX = 5000
OPTIONS_ODATA = frozenset({"$top", "$skip", "$select", "$count"})
NS = "OPSYS.M8"


class ErreurFormat(ValueError):
    """Un refus de format avec son statut HTTP et son code OData."""

    def __init__(self, statut: int, code: str, message: str) -> None:
        super().__init__(f"{code} : {message}")
        self.statut = statut
        self.code = code
        self.message = message


def neutraliser_cellule(valeur: str) -> str:
    """Précède d'une apostrophe une cellule de texte qu'un tableur lirait comme une formule (sauf un nombre exact)."""
    if _FORMULE.match(valeur) and not _NOMBRE.match(valeur):
        return "'" + valeur
    return valeur


def minimiser(
    jeu: Jeu,
    colonnes: Sequence[Colonne],
    lignes: Iterable[Mapping[str, Any]],
    masqueur: MasqueurPII | None,
) -> tuple[list[dict[str, Any]], int]:
    """Les lignes avec leurs cellules de texte vérifiées ou masquées ; le nombre de cellules masquées. Un texte libre,
    ou une valeur qui n'a pas la forme de sa colonne, passe par le masqueur ; sans masqueur, refus."""
    sortie: list[dict[str, Any]] = []
    masquees = 0
    for ligne in lignes:
        propre: dict[str, Any] = {}
        for colonne in colonnes:
            valeur = ligne.get(colonne.nom)
            if isinstance(valeur, str):
                conforme = colonne.forme is not None and colonne.forme.match(valeur) is not None
                if not conforme:
                    if masqueur is None:
                        raise ErreurFormat(
                            500, "masqueur_indisponible", "le masquage des renseignements personnels est indisponible"
                        )
                    masque = masqueur.masquer(valeur).texte
                    masquees += masque != valeur
                    valeur = masque
            propre[colonne.nom] = valeur
        sortie.append(propre)
    return sortie, masquees


def _cellule_csv(valeur: Any) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    return neutraliser_cellule(str(valeur))


def vers_csv(colonnes: Sequence[Colonne], lignes: Iterable[Mapping[str, Any]]) -> str:
    """CSV RFC 4180 (UTF-8, fins de ligne CRLF), en-tête comprise ; une cellule vide est une donnée absente."""
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    ecrivain.writerow([c.nom for c in colonnes])
    for ligne in lignes:
        ecrivain.writerow([_cellule_csv(ligne.get(c.nom)) for c in colonnes])
    return tampon.getvalue()


def vers_jsonl(colonnes: Sequence[Colonne], lignes: Iterable[Mapping[str, Any]]) -> str:
    """Une ligne JSON par enregistrement (JSON Lines), les colonnes dans l'ordre déclaré, ``null`` pour l'absent."""
    return "".join(
        json.dumps({c.nom: ligne.get(c.nom) for c in colonnes}, ensure_ascii=False, separators=(",", ":")) + "\n"
        for ligne in lignes
    )


# ---------------------------------------------------------------------------
# OData v4 minimal
# ---------------------------------------------------------------------------
def _erreur_odata(statut: int, code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def corps_erreur(erreur: ErreurFormat) -> dict[str, Any]:
    return _erreur_odata(erreur.statut, erreur.code, erreur.message)


def lire_options(params: Sequence[tuple[str, str]], colonnes_permises: Sequence[str]) -> dict[str, Any]:
    """Les options OData d'une requête. ``$top`` (1 à 5000, défaut 1000), ``$skip`` (≥ 0), ``$select`` (colonnes
    permises seulement), ``$count`` (``true`` ou ``false``). Une option répétée, inconnue ou non prise en charge est un
    refus : 501 pour une option OData qu'on ne fait pas, 400 pour une valeur illisible."""
    vues: dict[str, str] = {}
    for cle, valeur in params:
        if cle in vues:
            raise ErreurFormat(400, "option_repetee", f"option répétée : {cle}")
        vues[cle] = valeur
    for cle in vues:
        if cle.startswith("$") and cle not in OPTIONS_ODATA:
            raise ErreurFormat(
                501,
                "option_non_prise_en_charge",
                f"{cle} n'est pas pris en charge (seulement {', '.join(sorted(OPTIONS_ODATA))}) ; "
                "l'option n'est pas ignorée en silence",
            )
        if not cle.startswith("$"):
            raise ErreurFormat(400, "parametre_inconnu", f"paramètre inconnu : {cle}")

    def entier(nom: str, defaut: int, minimum: int, maximum: int) -> int:
        brut = vues.get(nom)
        if brut is None:
            return defaut
        if not re.fullmatch(r"[0-9]{1,9}", brut) or not minimum <= int(brut) <= maximum:
            raise ErreurFormat(400, "valeur_invalide", f"{nom} : entier de {minimum} à {maximum}")
        return int(brut)

    selection = None
    if "$select" in vues:
        noms = [n.strip() for n in vues["$select"].split(",")]
        if not noms or any(n not in colonnes_permises for n in noms) or len(set(noms)) != len(noms):
            raise ErreurFormat(400, "select_invalide", "$select ne nomme que des colonnes du jeu, une fois chacune")
        selection = noms
    compte = vues.get("$count", "false")
    if compte not in ("true", "false"):
        raise ErreurFormat(400, "valeur_invalide", "$count : true ou false")
    return {
        "top": entier("$top", 1000, 1, TOP_MAX),
        "skip": entier("$skip", 0, 0, 10**9),
        "select": selection,
        "count": compte == "true",
    }


def document_de_service(base: str, jeux: Iterable[Jeu]) -> dict[str, Any]:
    return {
        "@odata.context": f"{base}/$metadata",
        "value": [{"name": j.entite, "kind": "EntitySet", "url": j.entite} for j in jeux],
    }


def _type_edm(colonne: Colonne) -> str:
    return EDM_ENTIER_LONG if colonne.edm == EDM_ENTIER_LONG else colonne.edm


def metadata_edmx(jeux: Iterable[Jeu], financier: bool) -> str:
    """Le document ``$metadata`` (EDMX 4.0) des jeux visibles, colonnes visibles seulement."""
    morceaux = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">',
        f'<edmx:DataServices><Schema Namespace="{NS}" xmlns="http://docs.oasis-open.org/odata/ns/edm">',
    ]
    jeux = list(jeux)
    for jeu in jeux:
        visibles = jeu.colonnes_visibles(financier)
        cles = "".join(f"<PropertyRef Name={quoteattr(k)}/>" for k in jeu.cles)
        proprietes = "".join(
            f'<Property Name={quoteattr(c.nom)} Type={quoteattr(_type_edm(c))} Nullable="true"/>' for c in visibles
        )
        morceaux.append(f"<EntityType Name={quoteattr(jeu.entite)}><Key>{cles}</Key>{proprietes}</EntityType>")
    ensemble = "".join(
        f"<EntitySet Name={quoteattr(j.entite)} EntityType={quoteattr(NS + '.' + j.entite)}/>" for j in jeux
    )
    morceaux.append(f'<EntityContainer Name="M8">{ensemble}</EntityContainer>')
    morceaux.append("</Schema></edmx:DataServices></edmx:Edmx>")
    return "".join(morceaux)


def collection_odata(
    base: str,
    jeu: Jeu,
    colonnes: Sequence[Colonne],
    lignes: Sequence[Mapping[str, Any]],
    *,
    total: int,
    options: Mapping[str, Any],
    url_suite: Callable[[int], str],
) -> dict[str, Any]:
    reponse: dict[str, Any] = {"@odata.context": f"{base}/$metadata#{jeu.entite}"}
    if options["count"]:
        reponse["@odata.count"] = total
    reponse["value"] = [{c.nom: ligne.get(c.nom) for c in colonnes} for ligne in lignes]
    suivant = options["skip"] + len(lignes)
    if suivant < total:
        reponse["@odata.nextLink"] = url_suite(suivant)
    return reponse


def echapper_xml(texte: str) -> str:
    return escape(texte)
