RAPPEL OPSYS-AI v2 — lire AGENTS.md avant toute modification.
Preuve avant DONE : tests verts + démonstration exécutée, sinon BLOCKED avec raison. Jamais de faux vert.
Le code calcule (prix, soldes, scores, cédules), le LLM orchestre et rédige. Aucune donnée inventée.
Frontières humaines (T3) : paiements, secrets de prod, suppression définitive de données, publication/déploiement public, engagements externes.
Interdits : stubs dans src/, TODO/FIXME dans un diff, test sans assertion, secret dans git, --no-verify, commit direct ou force-push sur main.
Économie de tokens : lire le minimum, déterministe d'abord, sorties courtes, contexte ciblé.
Briques open source : licence vérifiée (docs/research/INGREDIENTS.md), core = fork dur d'OpenClaw (core/PROVENANCE.md, ADR-0008) ; AGPL/GPL seulement en service séparé non modifié.
