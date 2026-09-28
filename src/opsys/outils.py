"""Contrat d'un outil de département : ce que l'agent voit et ce qui s'exécute.

Un outil enveloppe une fonction métier déterministe (le code calcule, le LLM orchestre).
Le schéma JSON des paramètres est la seule chose que le modèle voit : il doit rester court
et précis, car il est envoyé à chaque tour.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import decimal
import enum
import re
from collections.abc import Callable, Mapping
from typing import Any

_NOM_OUTIL = re.compile(r"^(m(?:10|[1-9])|opsys)_[a-z][a-z0-9_]{1,60}$")
_TYPES_JSON: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float, decimal.Decimal),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


class Autonomie(enum.StrEnum):
    """Niveau de risque d'un outil, qui décide du besoin d'approbation humaine."""

    T0 = "T0"  # lecture ou calcul pur, sans effet de bord
    T1 = "T1"  # écriture interne (registre, journal, brouillon)
    T2 = "T2"  # action externe réversible (message à un client, publication de brouillon)
    T3 = "T3"  # frontière humaine : paiement, écriture financière, publication, engagement, suppression


@dataclasses.dataclass(frozen=True)
class Outil:
    nom: str
    description: str
    parametres: Mapping[str, Any]
    fonction: Callable[..., Any]
    autonomie: Autonomie = Autonomie.T0

    def __post_init__(self) -> None:
        if not _NOM_OUTIL.match(self.nom):
            raise ValueError(
                f"nom d'outil invalide {self.nom!r} : attendu mN_nom_en_snake_case ou opsys_nom"
            )
        if not self.description.strip() or len(self.description) > 1024:
            raise ValueError(f"{self.nom} : description vide ou trop longue (max 1024)")
        if self.parametres.get("type") != "object":
            raise ValueError(f"{self.nom} : le schéma des paramètres doit être de type object")
        proprietes = self.parametres.get("properties", {})
        if not isinstance(proprietes, Mapping):
            raise ValueError(f"{self.nom} : 'properties' doit être un objet")
        manquants = set(self.parametres.get("required", ())) - set(proprietes)
        if manquants:
            raise ValueError(f"{self.nom} : paramètres requis non décrits : {sorted(manquants)}")
        if not isinstance(self.autonomie, Autonomie):
            raise ValueError(f"{self.nom} : autonomie invalide {self.autonomie!r}")

    @property
    def departement_code(self) -> str:
        """Préfixe du nom : 'm3' pour m3_qualifier_photos, 'opsys' pour un outil commun."""
        return self.nom.split("_", 1)[0]


def _type_accepte(valeur: Any, type_json: str) -> bool:
    if type_json == "null":
        return valeur is None
    attendus = _TYPES_JSON.get(type_json)
    if attendus is None:
        return True
    if isinstance(valeur, bool) and type_json in ("integer", "number"):
        return False
    return isinstance(valeur, attendus)


def valider_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> list[str]:
    """Validation JSON Schema minimale (types, requis, enum, propriétés inconnues).

    Volontairement réduite au sous-ensemble utilisé par les outils OPSYS : la validation
    métier fine reste dans le code du département, qui refuse par ValueError.
    """
    erreurs: list[str] = []
    if not isinstance(arguments, Mapping):
        return ["les arguments doivent être un objet JSON"]
    proprietes: Mapping[str, Any] = schema.get("properties", {})
    for requis in schema.get("required", ()):
        if requis not in arguments:
            erreurs.append(f"paramètre requis manquant : {requis}")
    if schema.get("additionalProperties") is False:
        for nom in arguments:
            if nom not in proprietes:
                erreurs.append(f"paramètre inconnu : {nom}")
    for nom, valeur in arguments.items():
        definition = proprietes.get(nom)
        if not isinstance(definition, Mapping):
            continue
        types = definition.get("type")
        if types is not None:
            liste = [types] if isinstance(types, str) else list(types)
            if not any(_type_accepte(valeur, t) for t in liste):
                erreurs.append(f"{nom} : type attendu {'|'.join(liste)}")
                continue
        if "enum" in definition and valeur not in definition["enum"]:
            erreurs.append(f"{nom} : valeur hors liste {list(definition['enum'])}")
    return erreurs


def vers_json(valeur: Any) -> Any:
    """Convertit un résultat métier en données sérialisables JSON sans perte de sens.

    Decimal devient une chaîne (jamais un float : un montant ne perd pas de précision).
    """
    if isinstance(valeur, decimal.Decimal):
        return str(valeur)
    if isinstance(valeur, (dt.datetime, dt.date, dt.time)):
        return valeur.isoformat()
    if isinstance(valeur, enum.Enum):
        return vers_json(valeur.value)
    if dataclasses.is_dataclass(valeur) and not isinstance(valeur, type):
        return {c.name: vers_json(getattr(valeur, c.name)) for c in dataclasses.fields(valeur)}
    if isinstance(valeur, Mapping):
        return {str(k): vers_json(v) for k, v in valeur.items()}
    if isinstance(valeur, (list, tuple, set, frozenset)):
        return [vers_json(v) for v in valeur]
    return valeur


def depuis_couple(couple: tuple[Any, Any]) -> dict[str, Any]:
    """Traduit le patron métier fail-closed ``(resultat, verdict)`` en réponse explicite.

    Un verdict de rejet est une information utile pour l'agent (quoi corriger, quoi demander),
    pas une erreur technique : il est renvoyé tel quel, jamais masqué.
    """
    resultat, verdict = couple
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": resultat}


def executer(outil: Outil, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Exécute un outil et renvoie toujours une enveloppe {ok, resultat | erreur, details}.

    Un refus métier (ValueError, TypeError, KeyError levé par le département) est une
    réponse normale pour l'agent, pas une panne : il doit pouvoir corriger ou escalader.
    """
    erreurs = valider_arguments(outil.parametres, arguments)
    if erreurs:
        return {"ok": False, "erreur": "arguments_invalides", "details": erreurs}
    try:
        resultat = outil.fonction(**dict(arguments))
    except (ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "erreur": "refus_metier", "details": str(exc)}
    return {"ok": True, "resultat": vers_json(resultat)}
