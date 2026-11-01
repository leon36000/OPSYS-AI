"""Catalogue FERMÉ des mesures d'entreprise de M8 (M8.2, M8.8, M8.11, M8.12, M8.14).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. Le catalogue (``definitions/m8-catalogue.v1.yaml``)
est la
seule liste de mesures que les couches de lecture (entrepôt, wallboards, score de santé, copilote, pont BI)
connaissent :
elles ne choisissent jamais une mesure, une colonne ou une requête par leur propre moyen. Chaque entrée RÉFÉRENCE une
métrique gouvernée d'un registre existant (``m8-entonnoir``, ``m8-contenus``, ``m8-synthese``,
``m8-interdepartements``) : définition, unité, propriétaire et version de définition viennent d'elle, une seule fois.

Fail-closed : un catalogue mal formé (clé inconnue, énuméré hors liste, doublon, métrique non définie, fenêtre invalide,
synonyme vide ou partagé entre deux mesures) est un refus ``REJ-CATALOGUE-…``, jamais un catalogue partiel.

La version du catalogue (``version_catalogue``) est l'empreinte de sa forme canonique : elle change si et seulement si
une
entrée change, et sert de ``version`` à l'entrepôt, aux reçus du copilote et aux wallboards.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

import yaml

from . import contenus, encodage, entonnoir, fraicheur_lectures, mesures_interdepartements, synthese

_CHEMIN_CATALOGUE = Path(__file__).resolve().parents[2] / "definitions" / "m8-catalogue.v1.yaml"
SCHEMA = "opsys.m8.catalogue_mesures/v1"

_DOMAINES = frozenset({"ventes", "marketing", "operations", "qualite", "finance", "clientele"})
_SENS = frozenset({"plus_est_mieux", "moins_est_mieux", "neutre"})
_SENSIBILITES = frozenset({"agregat", "financier"})
_CLES_ENTREE = frozenset({"metric_id", "domaine", "sens", "sensibilite", "fraicheur", "synonymes"})
_CLES_FRAICHEUR = frozenset({"fenetre_s", "terminale"})
_SYNONYMES_MAX = 12
_LONGUEUR_SYNONYME_MAX = 80

REJ_CATALOGUE_ILLISIBLE = "REJ-CATALOGUE-ILLISIBLE"
REJ_CATALOGUE_INVALIDE = "REJ-CATALOGUE-INVALIDE"
REJ_CATALOGUE_METRIQUE_INCONNUE = "REJ-CATALOGUE-METRIQUE-INCONNUE"


class CatalogueRefuse(ValueError):
    """Le catalogue est refusé : ``code`` est le verdict, le détail dit l'entrée fautive."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail


def normaliser(texte: str) -> str:
    """Forme comparable d'un texte du français : minuscules, accents et apostrophes typographiques repliés, ponctuation
    ramenée à des espaces, espaces simples. Une seule règle, partagée par le catalogue et le copilote."""
    decompose = unicodedata.normalize("NFKD", texte.casefold())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    brut = "".join(c if c.isalnum() else " " for c in sans_accents.replace("’", "'"))
    return " ".join(brut.split())


def definitions_gouvernees() -> dict[str, dict[str, str]]:
    """Toutes les définitions gouvernées que le catalogue peut référencer, ``{metric_id: définition}`` (chaque
    définition porte son ``proprietaire``). Un ``metric_id`` défini deux fois dans deux registres est une erreur."""
    reunies: dict[str, dict[str, str]] = {}
    for charger in (
        entonnoir.charger_definitions,
        contenus.charger_definitions,
        synthese.charger_definitions,
        mesures_interdepartements.charger_definitions,
    ):
        for metric_id, definition in charger().items():
            if metric_id in reunies:
                raise CatalogueRefuse(REJ_CATALOGUE_INVALIDE, f"métrique définie dans deux registres : {metric_id}")
            reunies[metric_id] = definition
    return reunies


def _refus(detail: str) -> CatalogueRefuse:
    return CatalogueRefuse(REJ_CATALOGUE_INVALIDE, detail)


def _valider_fraicheur(metric_id: str, brut: Any) -> dict[str, Any]:
    if not isinstance(brut, dict) or not brut or set(brut) - _CLES_FRAICHEUR:
        raise _refus(f"{metric_id} : fraicheur doit être {{fenetre_s}} ou {{terminale: true}}")
    if "fenetre_s" in brut and "terminale" in brut:
        raise _refus(f"{metric_id} : fraicheur : fenetre_s et terminale s'excluent")
    if "terminale" in brut:
        if brut["terminale"] is not True:
            raise _refus(f"{metric_id} : fraicheur.terminale ne vaut que true")
        return {"terminale": True}
    raison = fraicheur_lectures.raison_invalide(brut["fenetre_s"])
    if raison is not None:
        raise _refus(f"{metric_id} : fraicheur.fenetre_s : {raison}")
    return {"fenetre_s": brut["fenetre_s"]}


def _valider_entree(brut: Any, definitions: dict[str, dict[str, str]], vus: dict[str, str]) -> dict[str, Any]:
    if not isinstance(brut, dict):
        raise _refus("chaque entrée du catalogue est un objet")
    metric_id = brut.get("metric_id")
    if not isinstance(metric_id, str) or not metric_id:
        raise _refus("une entrée sans metric_id")
    inconnues = set(brut) - _CLES_ENTREE
    manquantes = _CLES_ENTREE - set(brut)
    if inconnues or manquantes:
        raise _refus(f"{metric_id} : clés inconnues {sorted(inconnues)} ou manquantes {sorted(manquantes)}")
    if metric_id not in definitions:
        raise CatalogueRefuse(REJ_CATALOGUE_METRIQUE_INCONNUE, f"{metric_id} n'a aucune définition gouvernée")
    for cle, permis in (("domaine", _DOMAINES), ("sens", _SENS), ("sensibilite", _SENSIBILITES)):
        if brut[cle] not in permis:
            raise _refus(f"{metric_id} : {cle} {brut[cle]!r} hors liste {sorted(permis)}")
    synonymes = brut["synonymes"]
    if not isinstance(synonymes, list) or not 1 <= len(synonymes) <= _SYNONYMES_MAX:
        raise _refus(f"{metric_id} : 1 à {_SYNONYMES_MAX} synonymes attendus")
    normalises: list[str] = []
    for synonyme in synonymes:
        if not isinstance(synonyme, str) or not 2 <= len(synonyme) <= _LONGUEUR_SYNONYME_MAX:
            raise _refus(f"{metric_id} : synonyme illisible")
        forme = normaliser(synonyme)
        if not forme:
            raise _refus(f"{metric_id} : synonyme vide après normalisation")
        autre = vus.get(forme)
        if autre is not None and autre != metric_id:
            raise _refus(f"synonyme « {synonyme} » partagé par {autre} et {metric_id}")
        vus[forme] = metric_id
        normalises.append(forme)
    definition = definitions[metric_id]
    return {
        "metric_id": metric_id,
        "nom": definition["nom"],
        "unite": definition["unite"],
        "proprietaire": definition["proprietaire"],
        "domaine": brut["domaine"],
        "sens": brut["sens"],
        "sensibilite": brut["sensibilite"],
        "fraicheur": _valider_fraicheur(metric_id, brut["fraicheur"]),
        "synonymes": list(synonymes),
        "synonymes_normalises": normalises,
        "version_definition": encodage.empreinte(definition),
    }


def charger(chemin: str | Path | None = None) -> dict[str, Any]:
    """Le catalogue validé : ``{schema, version, version_catalogue, mesures: [entrée, …]}`` dans l'ordre du fichier.
    Chaque entrée porte nom, unité, propriétaire et ``version_definition`` de sa définition gouvernée."""
    fichier = Path(chemin) if chemin is not None else _CHEMIN_CATALOGUE
    try:
        contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as erreur:
        raise CatalogueRefuse(REJ_CATALOGUE_ILLISIBLE, f"{fichier} ({erreur})") from erreur
    if not isinstance(contenu, dict) or contenu.get("schema") != SCHEMA:
        raise _refus(f"schema attendu : {SCHEMA}")
    if set(contenu) - {"schema", "version", "mesures"}:
        raise _refus(f"clés inconnues à la racine : {sorted(set(contenu) - {'schema', 'version', 'mesures'})}")
    version = contenu.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _refus("version : entier positif attendu")
    brutes = contenu.get("mesures")
    if not isinstance(brutes, list) or not brutes:
        raise _refus("mesures : liste non vide attendue")
    definitions = definitions_gouvernees()
    vus: dict[str, str] = {}
    mesures: list[dict[str, Any]] = []
    identifiants: set[str] = set()
    for brute in brutes:
        entree = _valider_entree(brute, definitions, vus)
        if entree["metric_id"] in identifiants:
            raise _refus(f"{entree['metric_id']} figure deux fois au catalogue")
        identifiants.add(entree["metric_id"])
        mesures.append(entree)
    return {
        "schema": SCHEMA,
        "version": version,
        "version_catalogue": encodage.empreinte(brutes),
        "mesures": mesures,
    }


def par_identifiant(catalogue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entree["metric_id"]: entree for entree in catalogue["mesures"]}


__all__ = [
    "CatalogueRefuse",
    "REJ_CATALOGUE_ILLISIBLE",
    "REJ_CATALOGUE_INVALIDE",
    "REJ_CATALOGUE_METRIQUE_INCONNUE",
    "SCHEMA",
    "charger",
    "definitions_gouvernees",
    "normaliser",
    "par_identifiant",
]
