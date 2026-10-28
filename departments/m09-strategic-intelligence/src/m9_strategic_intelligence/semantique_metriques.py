"""Couche sémantique exécutive M9.3 : rapprocher des valeurs de métriques sans jamais les recalculer ni les fusionner.

Module pur. M8 possède les définitions des métriques (identifiant, propriétaire, unité, fraîcheur attendue, version) ;
M9
LIT ces définitions (captures du registre M8) et les valeurs mesurées par leurs propriétaires. Ce module ne calcule
aucune
valeur : il classe chaque observation face à la définition courante et refuse de réunir ce qui n'est pas comparable.

Classement d'une observation ``{metric_id, valeur, unite?, version_definition?}`` :

* ``SANS_DEFINITION`` — la métrique n'existe pas dans le registre connu : aucune valeur n'est rapprochée ni citée comme
mesure ;
* ``UNITE_DIVERGENTE`` — l'unité de l'observation n'est pas celle de la définition ;
* ``VERSION_PERIMEE`` / ``VERSION_NON_DECLAREE`` — la version de définition ayant produit la valeur n'est pas la
courante, ou
  n'est pas déclarée (la comparabilité ne peut pas être affirmée) ;
* ``VERSION_NON_COMPARABLE`` — l'observation porte une EMPREINTE de définition (64 hexadécimaux) alors que le registre
  numérote ses versions en entiers : les deux schémas de version ne sont pas reliés, M9 n'affirme ni la péremption ni la
  compatibilité ;
* ``COMPATIBLE`` — même métrique, même unité, même version que la définition courante.

Les groupes de sortie sont clés par ``(metric_id, unité, version)`` : deux groupes ne sont jamais additionnés, moyennés
ni
comparés par ce module (``agregable`` reste faux : M9 ne refait pas le calcul du propriétaire). Une valeur est conservée
en
TEXTE exact ; aucun nombre n'est produit ici.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

STATUTS = frozenset(
    {
        "COMPATIBLE",
        "SANS_DEFINITION",
        "UNITE_DIVERGENTE",
        "VERSION_PERIMEE",
        "VERSION_NON_DECLAREE",
        "VERSION_NON_COMPARABLE",
    }
)
_EMPREINTE = re.compile(r"[0-9a-f]{64}")
_LIMITES = (
    "M9 ne calcule ni n'agrège aucune métrique : les groupes sont des juxtapositions de valeurs de leurs "
    "propriétaires.",
    "Compatible = même identifiant, même unité, même version de définition que la définition courante du registre M8.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def cataloguer(definitions: Sequence[Mapping]) -> dict[str, dict]:
    """Registre ``metric_id → définition courante``. Deux définitions du même identifiant à la même version mais d'unité
    ou de propriétaire différents sont une contradiction du registre : refus, jamais un choix silencieux."""
    courant: dict[str, dict] = {}
    for definition in definitions:
        if not isinstance(definition, Mapping):
            raise _refus("REJ-SEMANTIQUE-DEFINITION", "définition objet requise")
        metric_id = definition.get("metric_id")
        unite = definition.get("unite")
        version = definition.get("version")
        if type(metric_id) is not str or not metric_id or type(unite) is not str or not unite or version in (None, ""):
            raise _refus("REJ-SEMANTIQUE-DEFINITION", "metric_id, unité et version requis")
        precedente = courant.get(metric_id)
        if precedente is not None:
            if precedente["version"] == version:
                if precedente["unite"] != unite or precedente.get("departement_proprietaire") != definition.get(
                    "departement_proprietaire"
                ):
                    raise _refus(
                        "REJ-SEMANTIQUE-CONTRADICTION", f"{metric_id} : deux définitions pour la version {version}"
                    )
                continue
            if _rang(version) < _rang(precedente["version"]):
                continue
        courant[metric_id] = dict(definition)
    return courant


def _rang(version: object) -> tuple[int, str]:
    """Ordre des versions : entiers d'abord (comparés comme nombres), sinon texte. Une version non ordonnable reste
    départagée par son texte ; le registre M8 numérote en entiers croissants."""
    if type(version) is int:
        return (1, f"{version:020d}")
    return (0, str(version))


def classer(observation: Mapping, catalogue: Mapping[str, Mapping]) -> dict:
    metric_id = observation.get("metric_id")
    valeur = observation.get("valeur")
    if type(metric_id) is not str or not metric_id or type(valeur) is not str:
        raise _refus(
            "REJ-SEMANTIQUE-OBSERVATION", "metric_id et valeur textuelle requis (une valeur n'est jamais recalculée)"
        )
    definition = catalogue.get(metric_id)
    resultat = {
        "metric_id": metric_id,
        "valeur": valeur,
        "unite": observation.get("unite"),
        "version_definition": observation.get("version_definition"),
        "source": observation.get("source"),
    }
    if definition is None:
        return resultat | {"statut": "SANS_DEFINITION", "proprietaire": None}
    resultat["proprietaire"] = definition.get("departement_proprietaire")
    resultat["unite_definition"] = definition["unite"]
    unite_observee = observation.get("unite")
    if unite_observee is not None and unite_observee != definition["unite"]:
        return resultat | {"statut": "UNITE_DIVERGENTE"}
    declaree = observation.get("version_definition")
    if declaree in (None, ""):
        return resultat | {"statut": "VERSION_NON_DECLAREE"}
    courante = definition.get("version_definition", definition["version"])
    if type(declaree) is str and _EMPREINTE.fullmatch(declaree) and type(courante) is int:
        return resultat | {"statut": "VERSION_NON_COMPARABLE", "version_courante": courante}
    if declaree != courante:
        return resultat | {
            "statut": "VERSION_PERIMEE",
            "version_courante": definition.get("version_definition", definition["version"]),
        }
    return resultat | {"statut": "COMPATIBLE", "unite": definition["unite"]}


def rapprocher(observations: Sequence[Mapping], catalogue: Mapping[str, Mapping]) -> dict:
    """Classe chaque observation et les range en groupes ``(metric_id, unité, version)`` jamais fusionnés."""
    classees = [classer(observation, catalogue) for observation in observations]
    groupes: dict[tuple, dict] = {}
    for element in classees:
        cle = (element["metric_id"], element.get("unite"), element.get("version_definition"), element["statut"])
        groupe = groupes.setdefault(
            cle,
            {
                "metric_id": element["metric_id"],
                "unite": element.get("unite"),
                "version_definition": element.get("version_definition"),
                "statut": element["statut"],
                "proprietaire": element.get("proprietaire"),
                "valeurs": [],
                "agregable": False,
            },
        )
        groupe["valeurs"].append({"valeur": element["valeur"], "source": element.get("source")})
    ordre = sorted(
        groupes.values(), key=lambda g: (g["metric_id"], str(g["unite"]), str(g["version_definition"]), g["statut"])
    )
    incompatibles = [element for element in classees if element["statut"] != "COMPATIBLE"]
    return {
        "type": "RAPPROCHEMENT_METRIQUES",
        "observations": classees,
        "groupes": ordre,
        "comparables_ensemble": [g for g in ordre if g["statut"] == "COMPATIBLE"],
        "non_comparables": incompatibles,
        "limites": list(_LIMITES),
    }
