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
from typing import Any, Literal

_NOM_OUTIL = re.compile(r"^(m(?:10|[1-9])|opsys)_[a-z][a-z0-9_]{1,60}$")
PorteeContexte = Literal["affaire", "globale"]
IdentiteContexte = Literal["affaire", "lead", "wct"]
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


class Niveau(enum.StrEnum):
    """Échelle unique d'approbation humaine (ADR-0009 §4, DEFINITION-PRODUIT §5) : N0 lecture,
    N1 brouillon, N2 tâche interne — automatique ; N3 action externe à faible risque ou modification
    interne non finale — validation humaine au départ ; N4 engagement (dépense, prix, envoi sensible,
    écriture finale) — le propriétaire ; N5 argent réel, fiscal, légal, paie, RH, achat majeur — le
    propriétaire ET l'attestation du professionnel concerné, jamais automatique."""

    N0 = "N0"
    N1 = "N1"
    N2 = "N2"
    N3 = "N3"
    N4 = "N4"
    N5 = "N5"


_RANG_NIVEAU: dict[Niveau, int] = {niveau: rang for rang, niveau in enumerate(Niveau)}

# Correspondance par défaut T -> N (ADR-0009 §4). T0 recouvre N0 à N2 (lecture, brouillon, tâche
# interne) : les trois sont "automatique" dans l'ADR, aucun n'exige jamais d'approbation, donc le
# choix exact parmi les trois ne change aucun comportement d'approbation ; on retient N0 (lecture),
# le sens premier de T0 ("calcul pur, sans effet de bord"). T1, T2 et T3 ont chacun une
# correspondance ponctuelle documentée dans l'ADR : T1 -> N3, T2 -> N4, T3 -> N5.
_NIVEAU_PAR_DEFAUT: dict[Autonomie, Niveau] = {
    Autonomie.T0: Niveau.N0,
    Autonomie.T1: Niveau.N3,
    Autonomie.T2: Niveau.N4,
    Autonomie.T3: Niveau.N5,
}


def niveau_par_defaut(autonomie: Autonomie) -> Niveau:
    """Niveau N par défaut d'un outil qui ne fixe pas `Outil.niveau` explicitement (ADR-0009 §4)."""
    return _NIVEAU_PAR_DEFAUT[autonomie]


@dataclasses.dataclass(frozen=True)
class Outil:
    nom: str
    description: str
    parametres: Mapping[str, Any]
    fonction: Callable[..., Any]
    autonomie: Autonomie = Autonomie.T0
    # N explicite (ADR-0009 §4) : optionnel, sinon `niveau_effectif` retombe sur la correspondance
    # par défaut depuis `autonomie` (`niveau_par_defaut`). Aucune régression des paliers T existants :
    # tant qu'aucun outil ne fixe `niveau`, tout se comporte exactement comme avant.
    niveau: Niveau | None = None
    # Rôles d'appareil (`opsys.appareils.ROLES_APPAREIL` : `employee`, `seller`, `admin`) qui peuvent
    # appeler cet outil depuis un téléphone appairé (T1.4-j, `docs/architecture/ROLES.md`). VIDE par
    # défaut : un outil sans déclaration n'est appelable par AUCUN appareil (fermé, jamais un accès
    # implicite). La déclaration vit ici, à côté de l'autonomie et des paramètres, pour que la
    # relecture d'un outil montre qui peut l'appeler, et qu'un renommage n'orpheline aucune entrée.
    # `opsys.openclaw.roles_outils` est la seule projection vers le core ; un outil T3/N5 n'est
    # jamais projeté, quoi que déclare cet attribut (`opsys-metier verifier` le refuse aussi).
    roles_appareil: frozenset[str] = frozenset()
    # Scope consumed by the core's M10 before-tool guard. An absent declaration is projected as
    # unresolved for N3+ calls; it never silently means global. `cible_contexte` is a JSON path in
    # the validated tool arguments, and `identite_contexte` says how it names M10's canonical case.
    portee_contexte: PorteeContexte | None = None
    cible_contexte: tuple[str, ...] | None = None
    identite_contexte: IdentiteContexte | None = None

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
        if self.portee_contexte not in (None, "affaire", "globale"):
            raise ValueError(f"{self.nom} : portee_contexte doit être 'affaire' ou 'globale'")
        if self.portee_contexte == "affaire":
            if (
                not self.cible_contexte
                or not all(isinstance(segment, str) and segment for segment in self.cible_contexte)
                or self.identite_contexte not in ("affaire", "lead", "wct")
            ):
                raise ValueError(f"{self.nom} : une portée affaire exige un chemin et une identité explicites")
            current: Any = self.parametres
            for segment in self.cible_contexte:
                properties = current.get("properties") if isinstance(current, Mapping) else None
                if not isinstance(properties, Mapping) or segment not in properties:
                    raise ValueError(f"{self.nom} : cible contexte absente du schéma: {self.cible_contexte!r}")
                current = properties[segment]
        elif self.cible_contexte is not None or self.identite_contexte is not None:
            raise ValueError(f"{self.nom} : une cible ou identité contexte exige une portée affaire")
        if self.niveau is not None and not isinstance(self.niveau, Niveau):
            raise ValueError(f"{self.nom} : niveau invalide {self.niveau!r}")
        # Forme seulement : le contenu (rôle connu, outil non T3) est contrôlé par `opsys-metier verifier`
        # (`departements.verifier_portees`) et rejoué par `roles_outils`. Une chaîne nue serait
        # itérée caractère par caractère : refusée d'office.
        if not isinstance(self.roles_appareil, frozenset) or not all(
            isinstance(role, str) and role for role in self.roles_appareil
        ):
            raise ValueError(
                f"{self.nom} : roles_appareil doit être un frozenset de noms de rôle non vides, "
                f"reçu {self.roles_appareil!r}"
            )

    @property
    def niveau_effectif(self) -> Niveau:
        """N explicite si fixé (`niveau`), sinon la correspondance par défaut depuis `autonomie`."""
        return self.niveau if self.niveau is not None else niveau_par_defaut(self.autonomie)

    @property
    def frontiere_humaine(self) -> bool:
        """Vrai pour un outil T3 ou de niveau N5 (argent réel, fiscal, légal, paie, RH, achat majeur,
        suppression, publication) : `nathan_owner` et l'attestation du professionnel seulement
        (ADR-0009 §5). Aucun rôle d'appareil ne peut l'appeler, quelle que soit sa déclaration."""
        return self.autonomie is Autonomie.T3 or self.niveau_effectif is Niveau.N5

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


class _Annulation(Exception):
    """Transporte une réponse en échec hors de la transaction, qui est alors annulée."""

    def __init__(self, reponse: dict[str, Any]) -> None:
        super().__init__(reponse.get("erreur"))
        self.reponse = reponse


def executer_atomique(outil: Outil, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """`executer` dans une transaction de la base de l'instance (ADR-0009).

    Toutes les écritures d'un appel (registres, événements, audit) sont validées ensemble si la
    réponse est un succès, annulées ensemble si elle est un échec ou si une exception survient.
    """
    from .stockage import transaction

    try:
        with transaction():
            reponse = executer(outil, arguments)
            if not reponse.get("ok"):
                raise _Annulation(reponse)
            return reponse
    except _Annulation as annulation:
        return annulation.reponse
