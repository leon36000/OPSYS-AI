"""Index lexical des bases de connaissances : un ADAPTATEUR par moteur de base, un seul contrat.

Contrat commun (ce que `index.indexer_lexical` et `recherche.rechercher` supposent, quel que soit le moteur) :

- `indexer(cnx, lignes)` reçoit des `(chunk_id, texte_indexe)` où `texte_indexe` est DÉJÀ normalisé en Python
  (`normalisation.termes` : accents repliés, mots vides retirés, radicaux légers). L'index ne normalise rien de plus, de
  sorte que document et requête passent par le MÊME traitement sur les deux moteurs (c'est ce qui fait la parité).
- `candidats(cnx, termes, version_ids, limite)` rend `[(chunk_id, ordre)]` des fragments qui contiennent AU MOINS UN des
  termes (sémantique « OU »), restreints à `version_ids`, du meilleur au moins bon ; `ordre` est croissant (plus petit
  = meilleur) et sert au tri. Les filtres métier (états, date, seuil de couverture, fraîcheur) sont appliqués par
  l'appelant, identiques sur les deux moteurs : un adaptateur ne décide ni de ce qui est publié ni de ce qui est assez
  couvert.
- `mesure` nomme la grandeur rendue au lecteur (`bm25` pour SQLite, `ts_rank_cd` pour PostgreSQL) : les deux ne sont PAS
  comparables entre elles, seul le rang l'est. `valeur_rendue(ordre)` la remet dans son sens naturel.
- Tout autre moteur est un refus typé `REJ-CONN-BACKEND-NON-PRIS-EN-CHARGE` (jamais un repli silencieux).

SQLite : table virtuelle FTS5 `connaissances_fts` (migration 0041), classement `bm25()` (plus petit = meilleur).
PostgreSQL : table `connaissances_lexique` (migration 0053) avec une colonne `tsv` GÉNÉRÉE
(`to_tsvector('simple', …)`) et un index GIN ; requête `websearch_to_tsquery('simple', …)`, classement `ts_rank_cd`
(densité de couverture, normalisation 1). Configuration `simple` et non `french` : le français (accents, pluriels,
mots vides) est déjà traité par la normalisation Python ; empiler le racinisateur `french` de PostgreSQL sur des
termes déjà réduits les réduirait une seconde fois (deux mots distincts se rejoindraient) et éloignerait le
comportement de celui de SQLite. Mesure comparative : docs/qualification/QUALIFICATION-POSTGRESQL.md, §9.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import Connection, bindparam, text

from . import normalisation
from .codes import BACKEND_NON_PRIS_EN_CHARGE, ErreurConnaissances

LOT_VERSIONS = 400
TABLE_PG = "connaissances_lexique"  # migration 0053 ; dans le schéma courant, comme toutes les tables
CONFIG_PG = "simple"  # littéral aussi inscrit dans la colonne générée de la migration 0053 : les deux doivent concorder
_TERME_SAIN = re.compile(r"[a-z0-9]{1,64}")


class IndexLexical(Protocol):
    nom: str
    mesure: str

    def indexer(self, cnx: Connection, lignes: Sequence[tuple[str, str]]) -> None: ...

    def candidats(self, cnx: Connection, termes: Sequence[str], version_ids: Sequence[str], limite: int
                  ) -> list[tuple[str, float]]: ...

    def valeur_rendue(self, ordre: float) -> float: ...


def _termes_sains(termes: Sequence[str]) -> list[str]:
    """Seuls les termes [a-z0-9] passent : aucune syntaxe de requête (FTS5 ou websearch) ne vient de l'utilisateur."""
    return [t for t in termes if _TERME_SAIN.fullmatch(t)]


class LexicalSqliteFts5:
    nom = "sqlite-fts5"
    mesure = "bm25"

    def indexer(self, cnx: Connection, lignes: Sequence[tuple[str, str]]) -> None:
        for chunk_id, terme in lignes:
            cnx.execute(text("INSERT INTO connaissances_fts(terme, chunk_id) VALUES (:t, :c)"),
                        {"t": terme, "c": chunk_id})

    def candidats(self, cnx: Connection, termes: Sequence[str], version_ids: Sequence[str], limite: int
                  ) -> list[tuple[str, float]]:
        sains = _termes_sains(termes)
        if not sains:
            return []
        expression = normalisation.requete_fts(sains)
        instruction = text(
            "SELECT f.chunk_id AS chunk_id, bm25(connaissances_fts) AS s FROM connaissances_fts "
            "JOIN connaissances_fragments f ON f.chunk_id = connaissances_fts.chunk_id "
            "WHERE connaissances_fts MATCH :q AND f.version_id IN :vids ORDER BY s, f.version_id, f.rang LIMIT :n"
        ).bindparams(bindparam("vids", expanding=True))
        trouves: list[tuple[str, float]] = []
        for i in range(0, len(version_ids), LOT_VERSIONS):
            lot = list(version_ids[i:i + LOT_VERSIONS])
            trouves.extend((r[0], float(r[1])) for r in cnx.execute(instruction, {"q": expression, "vids": lot,
                                                                                  "n": limite}))
        trouves.sort(key=lambda t: t[1])  # tri stable : à égalité, l'ordre déjà départagé par SQL (version, rang)
        return trouves[:limite]

    def valeur_rendue(self, ordre: float) -> float:
        return ordre


class LexicalPostgresTsvector:
    nom = "postgresql-tsvector"
    mesure = "ts_rank_cd"

    def indexer(self, cnx: Connection, lignes: Sequence[tuple[str, str]]) -> None:
        for chunk_id, terme in lignes:
            cnx.execute(text(f"INSERT INTO {TABLE_PG}(chunk_id, terme) VALUES (:c, :t)"),
                        {"c": chunk_id, "t": terme})

    def candidats(self, cnx: Connection, termes: Sequence[str], version_ids: Sequence[str], limite: int
                  ) -> list[tuple[str, float]]:
        sains = _termes_sains(termes)
        if not sains:
            return []
        # Chaque terme est entre guillemets : « or » (l'or, le métal) resterait sinon l'opérateur OU de websearch.
        expression = " or ".join(f'"{t}"' for t in sains)
        instruction = text(
            f"SELECT f.chunk_id AS chunk_id, ts_rank_cd(l.tsv, q.requete, 1) AS s "
            f"FROM {TABLE_PG} l JOIN connaissances_fragments f ON f.chunk_id = l.chunk_id "
            f"CROSS JOIN (SELECT websearch_to_tsquery('{CONFIG_PG}', :q) AS requete) q "
            f"WHERE l.tsv @@ q.requete AND f.version_id IN :vids ORDER BY s DESC, f.version_id, f.rang LIMIT :n"
        ).bindparams(bindparam("vids", expanding=True))
        trouves: list[tuple[str, float]] = []
        for i in range(0, len(version_ids), LOT_VERSIONS):
            lot = list(version_ids[i:i + LOT_VERSIONS])
            # ordre croissant = meilleur d'abord (comme bm25) : on range l'OPPOSÉ du rang de densité de couverture.
            trouves.extend((r[0], -float(r[1])) for r in cnx.execute(instruction, {"q": expression, "vids": lot,
                                                                                   "n": limite}))
        trouves.sort(key=lambda t: t[1])
        return trouves[:limite]

    def valeur_rendue(self, ordre: float) -> float:
        return -ordre + 0.0  # « + 0.0 » : jamais « -0.0 » dans une réponse


_SQLITE = LexicalSqliteFts5()
_POSTGRES = LexicalPostgresTsvector()


def pour(cnx: Connection) -> IndexLexical:
    """L'adaptateur du moteur de `cnx`, ou un refus typé."""
    if cnx.dialect.name == "sqlite":
        return _SQLITE
    if cnx.dialect.name == "postgresql":
        return _POSTGRES
    raise ErreurConnaissances(
        BACKEND_NON_PRIS_EN_CHARGE,
        f"l'index lexical des connaissances est pris en charge sur SQLite (FTS5) et PostgreSQL (tsvector), pas sur "
        f"« {cnx.dialect.name} »")
