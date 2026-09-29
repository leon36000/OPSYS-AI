"""Lecture des schémas de configuration du fork (Zod, en TypeScript) depuis les tests du socle.

Le code de `core/` ne s'exécute pas ici : on ne peut donc pas appeler `openclaw config validate`. Ce module lit
plutôt les sources des schémas (`core/src/config/zod-schema.*.ts`, `core/extensions/*/src/config-schema.ts`) pour
en tirer les clés d'un objet et les valeurs d'une énumération, afin que chaque clé et chaque valeur que
`opsys openclaw configurer` écrit soit confrontée au schéma du fork. Le job `e2e-core` de la CI complète ce
contrôle avec le vrai `openclaw config validate`.

La lecture est volontairement étroite : les clés du premier niveau du premier objet `{...}` qui suit une ancre,
et les textes de la liste `[...]` qui suit une ancre (`z.enum([...])`, `z.union([z.literal("a"), ...])`). Une
ancre absente est une erreur, jamais un ensemble vide : un schéma qui a bougé fait échouer le test.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

RACINE_CORE = Path(__file__).resolve().parents[2] / "core"


def lire(chemin_relatif: str) -> str:
    """Source d'un fichier du fork, telle quelle."""
    return (RACINE_CORE / chemin_relatif).read_text(encoding="utf-8")


def _hors_chaines(source: str, debut: int) -> Iterator[tuple[int, str]]:
    """Les caractères de `source` à partir de `debut`, sans les commentaires ni le contenu des chaînes."""
    position = debut
    while position < len(source):
        car = source[position]
        if source.startswith("//", position):
            fin = source.find("\n", position)
            position = len(source) if fin < 0 else fin
            continue
        if source.startswith("/*", position):
            fin = source.find("*/", position + 2)
            position = len(source) if fin < 0 else fin + 2
            continue
        if car in "\"'`":
            position += 1
            while position < len(source) and source[position] != car:
                position += 2 if source[position] == "\\" else 1
            position += 1
            continue
        yield position, car
        position += 1


def _apres(source: str, ancre: str) -> int:
    debut = source.find(ancre)
    if debut < 0:
        raise AssertionError(f"ancre introuvable dans le schéma du fork : {ancre!r} (le schéma a-t-il bougé ?)")
    return debut + len(ancre)


def cles_de_l_objet(source: str, ancre: str) -> set[str]:
    """Clés du premier niveau du premier objet `{...}` qui suit l'ancre (`nom: ...` et `...propagation`)."""
    debut = source.index("{", _apres(source, ancre))
    profondeur = 0
    entrees: list[str] = []
    courante: list[str] = []
    for _position, car in _hors_chaines(source, debut):
        if car in "{([":
            profondeur += 1
            continue
        if car in "})]":
            profondeur -= 1
            if profondeur == 0:
                entrees.append("".join(courante))
                break
            continue
        if profondeur == 1:
            if car == ",":
                entrees.append("".join(courante))
                courante = []
            else:
                courante.append(car)
    else:
        raise AssertionError(f"objet non fermé après l'ancre {ancre!r}")
    cles: set[str] = set()
    for texte in entrees:
        trouve = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", texte)
        if trouve:
            cles.add(trouve.group(1))
    if not cles:
        raise AssertionError(f"aucune clé lue après l'ancre {ancre!r}")
    return cles


def valeurs_apres(source: str, ancre: str) -> set[str]:
    """Textes entre guillemets de la liste `[...]` qui suit l'ancre."""
    debut = source.index("[", _apres(source, ancre))
    profondeur = 0
    for position in range(debut, len(source)):
        if source[position] == "[":
            profondeur += 1
        elif source[position] == "]":
            profondeur -= 1
            if profondeur == 0:
                valeurs = set(re.findall(r'"([^"]*)"', source[debut:position]))
                if not valeurs:
                    raise AssertionError(f"aucune valeur lue après l'ancre {ancre!r}")
                return valeurs
    raise AssertionError(f"liste non fermée après l'ancre {ancre!r}")
