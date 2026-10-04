# ADR-0012 — Réutilisation prioritaire, profondeur des départements et contrôles proportionnés

- Date : 2026-09-30.
- Statut : **Accepté sur directive explicite du propriétaire** ; transcription de son mandat,
  pas promotion de fonctionnalités au statut vérifié.
- Source : [Directives Nathan](../produit/DIRECTIVES-NATHAN.md), prompts M1/M5/M7/M10 retransmis
  et audit de la branche `claude/opsys-ai-analysis-x4jt87` au commit `2e56c0d`.
- Remplace : les obligations de consensus/revue par modèles de la méthode antérieure ;
  l'exclusion de la mémoire du développement du périmètre M10 (ADR-0008, réponse au point 5).
- Complète : ADR-0008 (fork), ADR-0009 (vérité métier), ADR-0010 (mémoire), sans les réécrire.

## Décisions

1. **Réutiliser avant d'écrire.** Inventorier l'existant puis rechercher GitHub/GitLab pour toute
   capacité coûteuse. Vérifier code, commit, licence, maintenance et coût d'adaptation. Une preuve
   d'intégration sur un parcours métier précède l'adoption ; un catalogue n'est pas une installation.
2. **Conserver le fork disponible.** Le code OpenClaw déjà greffé reste OPSYS-CORE. Examiner Hermes
   et d'autres projets comme ingrédients, sans importer un deuxième cœur par simple comparaison
   de README. Le verdict d'ADR-0008 sur Hermes n'interdit pas la récupération de ses composants.
   Maintenir nous-mêmes le fork et reporter les correctifs pertinents après veille de sécurité.
3. **Conserver l'ambition métier.** Les périmètres complets M1, M5/CFO, M7/CMO et M10 sont des
   cibles de livraison. Adapter les anciens chemins et frameworks ; garder les capacités requises,
   les scénarios, permissions et preuves. Préserver aussi la profondeur des six autres départements.
4. **Deux domaines M10.** Affaires et développement partagent les principes de traçabilité, avec
   stores/logiques d'accès distincts selon les données. Prompts, plans, code et tests peuvent se
   relier aux décisions et modules sans exposer secrets ni données client aux agents développeurs.
   Cette capacité ne rend pas Forge, Cursor, Qdrant, Cognee ou Temporal nécessaires à l'installation.
5. **Plusieurs agents configurables.** Le dashboard cible gère rôles, capacités, modèles, mémoire,
   budgets et déclencheurs. Un responsable de flux et des contrats événementiels coordonnent les
   spécialistes. Les données et l'autorité sont vérifiées côté serveur, jamais déduites d'un nom
   d'agent fourni dans la requête.
6. **Économie mesurable.** Déterminisme avant LLM, contexte sous budget, résultats réutilisés,
   caches isolés et invalidables, modèles adaptés, limites de tours/retries et de concurrence.
   Les budgets doivent couvrir les appels réels au fournisseur, pas uniquement les outils MCP.
7. **Fin des validations externes obligatoires de développement.** Aucun vote de trois modèles,
   autre fournisseur imposé ou attente d'un modèle extérieur pour intégrer un changement. L'auteur
   vérifie les invariants et les régressions ; revue humaine ou indépendante facultative et ciblée.
   Les tests pertinents et la CI applicable restent des preuves techniques. Une CI en échec est
   diagnostiquée ; un test vert n'efface pas un défaut reproduit.
8. **Validation proportionnée.** Documents : liens, cohérence et diff. Métier : régressions et
   parcours concernés. Sécurité/argent : tests négatifs, rejeu, isolation, droits et audit. Migration :
   intégrité, restauration et rollback. Core : CI prévue par `core/AGENTS.md`. Ne pas relancer toutes
   les suites avant chaque petit changement de texte. Un TODO lié à une tâche n'est pas une preuve
   de livraison ; le suivi explicite du travail incomplet est permis.
9. **Frontières humaines conservées.** Les actions officielles, financières, légales, fiscales,
   sensibles ou irréversibles gardent les approbations humaines des prompts et N0–N5. L'autorisation
   de développer ne vaut pas autorisation de déployer, publier, payer, merger ou pousser sur GitHub.

## Conséquences et vérification

Les ADR antérieurs et recherches datées restent disponibles pour expliquer l'historique. Les
documents d'entrée décrivent l'état actuel et renvoient vers la matrice ; ils n'annoncent pas
« 100 % ». Les défauts de l'audit, notamment autorité, confidentialité M10, idempotence M5/M6,
restauration et mobile, restent à corriger avant qualification de production.

Premier lot : règles, documents d'entrée, périmètre, recherche qualifiée et plan de consolidation.
Les dépendances nouvelles sont candidates tant qu'un patch d'intégration n'est pas testé.
