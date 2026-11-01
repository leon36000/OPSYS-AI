"""Bases de connaissances par département : sources versionnées et SOURCÉES, recherche hybride
(docs/architecture/CONNAISSANCES.md).

Chaque département a sa mémoire propre (Couche A, `opsys.memoire`) ET une base de connaissances métier : des documents
de
référence (normes, barèmes, textes officiels) avec leur provenance complète, leur licence, leurs empreintes, leur
version, leur état (`brouillon` → `revu` → `publie` → `retire`) et leur échéance de révision. Phase 1 : SQLite FTS5
(BM25) + similarité exacte des vecteurs en Python, derrière des ports (embeddings, reranker) que le registre de
fournisseurs configure. Cible de production : PostgreSQL + pgvector + BM25 (plan documenté, non exécuté).

Modules : `modele` (vocabulaire), `normalisation`, `extraction`, `decoupage`, `isolation` (contenu non fiable),
`ports` / `doubles` (embeddings et reranker), `vecteurs`, `index`, `etats`, `ingestion`, `cycle`, `recherche`,
`lecture`, `mesure` (harnais recall@k, MRR), `outils` (outils communs de lecture), `cli`.

Ce paquet ne fait aucun appel réseau. Il ne contient aucun contenu fiscal, comptable ou juridique réel.
"""
