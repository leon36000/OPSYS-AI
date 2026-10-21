RAPPEL OPSYS-AI v2 — lire AGENTS.md avant toute modification.
Direction durable : docs/produit/DIRECTIVES-NATHAN.md ; périmètre complet M1–M10, multi-agents configurables, mémoire métier + développement isolés.
Preuve avant livraison : vérifications proportionnées, critères de sortie, limites explicites. Jamais de faux vert ni de simulation présentée comme réelle.
Le code calcule (prix, soldes, scores, cédules), le LLM orchestre et rédige. Aucune donnée inventée.
Frontières humaines (T3) : paiements, secrets de prod, suppression définitive de données, publication/déploiement public, engagements externes.
Interdits : stubs présentés comme livrés, test sans assertion, secret dans git, --no-verify, commit direct ou force-push sur main. Travail incomplet suivi dans le plan.
Pas de consensus de trois modèles, fournisseur extérieur imposé ni attente d'un autre modèle pour intégrer. Tests pertinents et CI applicable ; approbations humaines métier conservées.
Économie de tokens : lire le minimum, déterministe d'abord, sorties courtes, contexte ciblé.
Briques open source : chercher d'abord l'existant, GitHub et GitLab ; code, licence, maintenance et adaptation vérifiés (docs/research/INGREDIENTS.md). Core = fork OpenClaw maintenu par OPSYS ; Hermes = ingrédients à qualifier (ADR-0012).
