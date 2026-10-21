"""Validation du profil de marque OPSYS-AI — pilotée par le contrat gelé v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Chargement unique du contrat (source de vérité UNIQUE)
# ---------------------------------------------------------------------------
_CONTRACT: dict[str, Any] | None = None


def _load_contract() -> dict[str, Any]:
    """Charge brand-contract.v1.yaml depuis le dossier contracts/ (relatif à ce fichier).

    Lève OSError si le fichier est introuvable. Le résultat est mis en cache au niveau module.
    """
    global _CONTRACT
    if _CONTRACT is not None:
        return _CONTRACT

    contract_path = (
        Path(__file__).resolve().parents[3] / "contracts" / "brand-contract.v1.yaml"
    )
    try:
        with open(contract_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except FileNotFoundError:
        raise OSError(
            f"Contrat introuvable à l'emplacement attendu : {contract_path}"
        ) from None

    if not isinstance(raw, dict):
        raise OSError("Le contrat doit être un mapping YAML")
    _CONTRACT = raw
    return _CONTRACT


# ---------------------------------------------------------------------------
# Constantes dérivées EXCLUSIVEMENT du contrat
# ---------------------------------------------------------------------------
def _contract_profile_schema() -> dict[str, Any]:
    return _load_contract()["profile_schema"]


def contract_version() -> str:
    """Version du contrat gelé en cours (champ `schema_version`)."""
    return str(_load_contract()["schema_version"])


REQUIRED_FIELDS: tuple = tuple(
    field["name"] for field in _contract_profile_schema()["required_fields"]
)

# Messages d'erreur préservés (compatibilité exacte avec les tests existants)
_FIELD_MESSAGES: dict[str, str] = {
    "name": "name doit être une chaîne non vide",
    "tagline": "tagline doit être une chaîne",
    "tone": "tone doit être une chaîne",
    "colors": "colors doit être une liste non vide de chaînes",
    "langue": "langue doit être une chaîne",
}


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------
class ProfileError(Exception):
    """Erreur de validation d'un profil de marque."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_profile(obj: Any) -> dict:
    """Valide et normalise un profil de marque.

    Le dictionnaire retourné est une copie JSON-sérialisable par construction :
    les champs requis sont des chaînes (ou liste de chaînes pour colors), et
    tout champ supplémentaire doit également être JSON-sérialisable.
    """
    if not isinstance(obj, dict):
        raise ProfileError("racine", "l'objet racine doit être un mapping")

    schema = _contract_profile_schema()
    required_fields_defs = schema["required_fields"]

    # Vérification de la présence des champs requis
    for field_def in required_fields_defs:
        field_name = field_def["name"]
        if field_name not in obj:
            raise ProfileError(field_name, f"champ requis manquant : {field_name}")

    # Dictionnaire des définitions pour un accès rapide
    field_defs = {fd["name"]: fd for fd in required_fields_defs}

    # Validation de chaque champ requis selon le contrat
    for field_def in required_fields_defs:
        field_name = field_def["name"]
        value = obj[field_name]

        # Détermination du message d'erreur selon le champ (exactement comme avant)
        msg = _FIELD_MESSAGES[field_name]

        # Validation type + contraintes
        ftype = field_def.get("type")
        if ftype == "string":
            non_empty = field_def.get("non_empty", False)
            if not isinstance(value, str) or (non_empty and not value):
                raise ProfileError(field_name, msg)
        elif ftype == "array":
            min_items = field_def.get("min_items", 0)
            if (
                not isinstance(value, list)
                or len(value) < min_items
                or not all(isinstance(i, str) for i in value)
            ):
                raise ProfileError(field_name, msg)
        else:
            # Par prudence, on conserve le comportement historique
            if not isinstance(value, str):
                raise ProfileError(field_name, msg)

    # Copie et normalisation (forçage en str pour garantir JSON sérialisable)
    result = dict(obj)
    for field_def in required_fields_defs:
        field_name = field_def["name"]
        if field_def["type"] == "array":
            result[field_name] = [str(color) for color in obj[field_name]]
        else:
            result[field_name] = str(obj[field_name])

    # Vérification JSON pour les champs supplémentaires (post-condition inchangée)
    try:
        json.dumps(result)
    except TypeError:
        for key in result:
            if key in field_defs:
                continue
            value = result[key]
            try:
                json.dumps(value)
            except TypeError:
                raise ProfileError(
                    key,
                    f"valeur non JSON-sérialisable (type {type(value).__name__})",
                ) from None
        raise ProfileError(
            "inconnu",
            "valeur non JSON-sérialisable dans le profil",
        ) from None

    return result
