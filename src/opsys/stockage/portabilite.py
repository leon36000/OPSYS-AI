"""Expressions SQL portables SQLite / PostgreSQL (un seul appel, deux rendus selon le dialecte de la connexion).

Chaque fonction ici remplace un idiome qui n'existait que sur SQLite et qui, sur PostgreSQL, était une ERREUR SQL
(`CAST(texte AS BLOB)`, `typeof()`, conversion d'un booléen en octets) : défauts latents L2 à L5 du rapport de
qualification PostgreSQL. Le rendu SQLite est EXACTEMENT celui d'avant (même SQL, mêmes valeurs) ; seul le rendu
PostgreSQL est nouveau. Aucune de ces fonctions n'exécute quoi que ce soit : ce sont des éléments d'expression
SQLAlchemy, compilés au moment de l'exécution par le dialecte de la connexion.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, LargeBinary, String, Text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement
from sqlalchemy.sql.sqltypes import Enum, Numeric

SQLITE = "sqlite"
POSTGRESQL = "postgresql"
DIALECTES_QUALIFIES = (SQLITE, POSTGRESQL)


def dialecte(cnx: Any) -> str:
    """Nom du dialecte d'une connexion (ou d'un moteur)."""
    moteur = getattr(cnx, "engine", cnx)
    return moteur.dialect.name


def moteur_qualifie(cnx: Any) -> bool:
    """`True` pour SQLite et PostgreSQL, les deux moteurs éprouvés ; tout autre dialecte reste refusé."""
    return dialecte(cnx) in DIALECTES_QUALIFIES


class nb_octets(FunctionElement):  # noqa: N801 — se lit comme une fonction SQL
    """Nombre d'OCTETS (UTF-8) d'une colonne ou d'une expression texte, entière ou booléenne.

    SQLite : `length(CAST(x AS BLOB))`. PostgreSQL : `octet_length(x)` pour un texte ou un binaire,
    `octet_length(CAST(x AS TEXT))` pour un entier, et 1 pour un booléen (SQLite le stocke en `0`/`1` : un octet,
    jamais `true`/`false`). `NULL` reste `NULL` sur les deux moteurs.
    """

    inherit_cache = True
    type = Integer()
    name = "nb_octets"

    def __init__(self, expression: Any) -> None:
        super().__init__(expression)


@compiles(nb_octets)
def _octets_defaut(element: nb_octets, compilateur, **kw) -> str:  # noqa: ARG001
    return f"length(CAST({compilateur.process(element.clauses.clauses[0], **kw)} AS BLOB))"


@compiles(nb_octets, SQLITE)
def _octets_sqlite(element: nb_octets, compilateur, **kw) -> str:
    return f"length(CAST({compilateur.process(element.clauses.clauses[0], **kw)} AS BLOB))"


@compiles(nb_octets, POSTGRESQL)
def _octets_postgresql(element: nb_octets, compilateur, **kw) -> str:
    interne = element.clauses.clauses[0]
    type_ = getattr(interne, "type", None)
    texte = compilateur.process(interne, **kw)
    if isinstance(type_, Boolean):
        return f"(CASE WHEN {texte} IS NULL THEN NULL ELSE 1 END)"
    if isinstance(type_, LargeBinary):
        return f"octet_length({texte})"
    if isinstance(type_, (String, Text, Enum)):
        return f"octet_length({texte})"
    if isinstance(type_, (Integer, Numeric)):
        return f"octet_length(CAST({texte} AS TEXT))"
    # Type inconnu (littéral, sous-requête, fonction) : on passe par le texte, le seul rendu qui existe pour tout type.
    return f"octet_length(CAST({texte} AS TEXT))"


class _EstDeType(FunctionElement):
    """Base commune de `est_texte` / `est_entier` : une condition booléenne sur le TYPE de stockage d'une valeur."""

    inherit_cache = True
    type = Boolean()

    def __init__(self, expression: Any) -> None:
        super().__init__(expression)


class est_texte(_EstDeType):  # noqa: N801 — se lit comme une fonction SQL
    """Condition « la valeur est stockée comme du texte ».

    SQLite : `typeof(x) = 'text'` (l'affinité souple de SQLite laisse passer un BLOB, un REAL ou un entier dans une
    colonne TEXT : ce contrôle les refuse). PostgreSQL : les colonnes sont typées, mais le contrôle n'est pas supposé
    vrai : `pg_typeof(x)` rend le vrai type (`text`, `character varying`, `character`).
    """

    name = "est_texte"
    inherit_cache = True


class est_entier(_EstDeType):  # noqa: N801 — se lit comme une fonction SQL
    """Condition « la valeur est stockée comme un entier » (`typeof(x) = 'integer'` / `pg_typeof` entier)."""

    name = "est_entier"
    inherit_cache = True


def _type_sqlite(genre: str):
    def rendu(element, compilateur, **kw) -> str:
        return f"(typeof({compilateur.process(element.clauses.clauses[0], **kw)}) = '{genre}')"

    return rendu


def _type_postgresql(noms: tuple[str, ...]):
    def rendu(element, compilateur, **kw) -> str:
        x = compilateur.process(element.clauses.clauses[0], **kw)
        liste = ", ".join(f"'{n}'" for n in noms)
        # SQLite : `typeof(NULL)` vaut 'null', donc ni texte ni entier ; `pg_typeof` d'une colonne NULL rend son type.
        return f"({x} IS NOT NULL AND pg_typeof({x})::text IN ({liste}))"

    return rendu


compiles(est_texte)(_type_sqlite("text"))
compiles(est_texte, SQLITE)(_type_sqlite("text"))
compiles(est_texte, POSTGRESQL)(_type_postgresql(("text", "character varying", "character")))
compiles(est_entier)(_type_sqlite("integer"))
compiles(est_entier, SQLITE)(_type_sqlite("integer"))
compiles(est_entier, POSTGRESQL)(_type_postgresql(("smallint", "integer", "bigint")))


class type_stockage(FunctionElement):  # noqa: N801 — se lit comme une fonction SQL
    """Nom du type de stockage d'une valeur, normalisé : `'text'`, `'integer'`, ou le nom natif du moteur.

    SQLite : `typeof(x)`. PostgreSQL : `pg_typeof(x)` ramené aux deux noms que le code compare (`character varying` et
    `character` valent `text` ; `smallint`, `integer` et `bigint` valent `integer`).
    """

    inherit_cache = True
    type = String()
    name = "type_stockage"

    def __init__(self, expression: Any) -> None:
        super().__init__(expression)


@compiles(type_stockage)
def _type_stockage_defaut(element, compilateur, **kw) -> str:
    return f"typeof({compilateur.process(element.clauses.clauses[0], **kw)})"


@compiles(type_stockage, SQLITE)
def _type_stockage_sqlite(element, compilateur, **kw) -> str:
    return f"typeof({compilateur.process(element.clauses.clauses[0], **kw)})"


@compiles(type_stockage, POSTGRESQL)
def _type_stockage_postgresql(element, compilateur, **kw) -> str:
    x = compilateur.process(element.clauses.clauses[0], **kw)
    return (f"(CASE WHEN {x} IS NULL THEN 'null' "
            f"WHEN pg_typeof({x})::text IN ('text', 'character varying', 'character') THEN 'text' "
            f"WHEN pg_typeof({x})::text IN ('smallint', 'integer', 'bigint') THEN 'integer' "
            f"ELSE pg_typeof({x})::text END)")
