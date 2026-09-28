"""Mémoire d'entreprise OPSYS : couche B du RAG premium (docs/memory/RAG-PREMIUM.md).

- `store.MemoireEntreprise` : PostgreSQL + pgvector + plein texte français, fusion RRF, portées,
  effacement Loi 25, rétention.
- `embeddings.ClientEmbeddings` : client `/v1/embeddings` OpenAI-compatible (stdlib).
- `outils.outils()` : capacités MCP `opsys_memoire_*` (T0 / T1 / T3).

psycopg n'est importé qu'à la connexion : le paquet se charge sans l'extra `postgres`, et les outils
refusent alors explicitement.
"""

from .embeddings import ClientEmbeddings, ErreurEmbeddings
from .store import MemoireEntreprise, MemoireIndisponible, Recherche, Resultat

__all__ = [
    "ClientEmbeddings",
    "ErreurEmbeddings",
    "MemoireEntreprise",
    "MemoireIndisponible",
    "Recherche",
    "Resultat",
]
