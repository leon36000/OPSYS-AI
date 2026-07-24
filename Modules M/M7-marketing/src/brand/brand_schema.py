"""Validation du profil de marque OPSYS-AI."""

from __future__ import annotations

import json
from typing import Any


REQUIRED_FIELDS = ("name", "tagline", "tone", "colors", "langue")


class ProfileError(Exception):
    """Erreur de validation d'un profil de marque."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


def validate_profile(obj: Any) -> dict:
    """Valide et normalise un profil de marque.

    Le dictionnaire retourné est une copie JSON-sérialisable par construction :
    les champs requis sont des chaînes (ou liste de chaînes pour colors), et
    tout champ supplémentaire doit également être JSON-sérialisable.
    """
    if not isinstance(obj, dict):
        raise ProfileError("racine", "l'objet racine doit être un mapping")

    for field in REQUIRED_FIELDS:
        if field not in obj:
            raise ProfileError(field, f"champ requis manquant : {field}")

    name = obj["name"]
    if not isinstance(name, str) or not name:
        raise ProfileError("name", "name doit être une chaîne non vide")

    tagline = obj["tagline"]
    if not isinstance(tagline, str):
        raise ProfileError("tagline", "tagline doit être une chaîne")

    tone = obj["tone"]
    if not isinstance(tone, str):
        raise ProfileError("tone", "tone doit être une chaîne")

    langue = obj["langue"]
    if not isinstance(langue, str):
        raise ProfileError("langue", "langue doit être une chaîne")

    colors = obj["colors"]
    if not isinstance(colors, list) or len(colors) == 0:
        raise ProfileError("colors", "colors doit être une liste non vide de chaînes")
    for color in colors:
        if not isinstance(color, str):
            raise ProfileError("colors", "colors doit être une liste non vide de chaînes")

    result = dict(obj)
    result["name"] = str(name)
    result["tagline"] = str(tagline)
    result["tone"] = str(tone)
    result["langue"] = str(langue)
    result["colors"] = [str(color) for color in colors]

    try:
        json.dumps(result)
    except TypeError:
        for key in result:
            if key in REQUIRED_FIELDS:
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

