"""Point d'évaluation « local » : le BM25 du dépôt (SQLite FTS5, `opsys.connaissances.lexical` + `normalisation`).

On réutilise TELS QUELS l'adaptateur `LexicalSqliteFts5` et la normalisation française du produit (accents repliés, mots
vides, radicaux légers) sur une base SQLite EN MÉMOIRE reconstruite à chaque exécution ; on y reproduit les deux règles
de la recherche du produit (`opsys.connaissances.recherche`) : candidats « OU » filtrés par une couverture minimale des
termes de la question (0,25 par défaut), puis tri par BM25 et, à égalité, par nombre de termes trouvés.

Ce que cela ne reprend pas : la base complète du produit (versions, états, fraîcheur), qui n'a pas d'effet sur un
classement de passages tous publiés. Le tri final à égalité diffère du produit (identifiant de passage au lieu de
l'ordre de lecture) : il est déterministe, c'est tout ce qu'on lui demande.

Aucune bibliothèque d'embeddings locale n'est installée dans le venv du dépôt (vérifié : ni onnxruntime, ni
sentence-transformers, ni fastembed, ni numpy) : le seul point d'évaluation local est donc lexical. Un embeddeur local
(bge-m3 ONNX, Qwen3-Embedding sur GB10) se branche plus tard par une URL compatible OpenAI, voir banc.py `--local-url`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from opsys.connaissances import normalisation
from opsys.connaissances.lexical import LexicalSqliteFts5

VERSION = "v1"
COUVERTURE_PAR_DEFAUT = 0.25  # valeur de `recherche.Reglages.seuil_couverture`


class Lexique:
    def __init__(self, passages: Mapping[str, str]) -> None:
        self._moteur = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self._adaptateur = LexicalSqliteFts5()
        self._termes: dict[str, set[str]] = {}
        with self._moteur.begin() as cnx:
            cnx.execute(text("CREATE TABLE connaissances_fragments(chunk_id TEXT PRIMARY KEY, version_id TEXT NOT NULL,"
                             " rang INTEGER NOT NULL)"))
            cnx.execute(text("CREATE VIRTUAL TABLE connaissances_fts USING fts5(terme, chunk_id UNINDEXED,"
                             " tokenize='unicode61')"))
            lignes = []
            for rang, (identifiant, contenu) in enumerate(sorted(passages.items())):
                termes = normalisation.termes(contenu)
                self._termes[identifiant] = set(termes)
                cnx.execute(text("INSERT INTO connaissances_fragments(chunk_id, version_id, rang) VALUES (:c, :v, :r)"),
                            {"c": identifiant, "v": VERSION, "r": rang})
                lignes.append((identifiant, " ".join(termes)))
            self._adaptateur.indexer(cnx, lignes)

    def classer(self, requete: str, *, limite: int = 50, couverture: float | None = COUVERTURE_PAR_DEFAUT
                ) -> list[tuple[str, float]]:
        """[(identifiant, bm25 rendu)] du meilleur au moins bon ; vide si la requête n'a aucun terme exploitable.
        `couverture=None` désactive le filtre de couverture (OU pur)."""
        termes = normalisation.termes_uniques(requete)
        if not termes:
            return []
        with self._moteur.connect() as cnx:
            brut = self._adaptateur.candidats(cnx, termes, [VERSION], limite * 4)
        retenus: list[tuple[str, float, int]] = []
        for identifiant, ordre in brut:
            trouves = sum(1 for t in termes if t in self._termes[identifiant])
            if couverture is None or trouves / len(termes) >= couverture:
                retenus.append((identifiant, ordre, trouves))
        retenus.sort(key=lambda t: (round(t[1], 6), -t[2], t[0]))
        return [(i, self._adaptateur.valeur_rendue(o)) for i, o, _ in retenus[:limite]]

    def fermer(self) -> None:
        self._moteur.dispose()


def identifiants(resultats: Sequence[tuple[str, float]]) -> list[str]:
    return [i for i, _ in resultats]
