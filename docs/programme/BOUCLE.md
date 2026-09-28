# Boucle d'exécution OPSYS-AI (« Ralph »)

Consigne relue au début de **chaque** itération. Elle ne change pas d'une itération à l'autre ;
c'est `PLAN.md` qui avance.

## Une itération

1. **Relire l'état** : `docs/programme/PLAN.md` (tâche courante, tâches bloquées) et `git log -5`.
   Ne relire la définition produit que pour le département ou le flux touché.
2. **Choisir** la première tâche non cochée de la tranche en cours dont les dépendances sont
   faites. Une tâche trop grosse pour une itération est d'abord découpée dans le plan.
3. **Exécuter jusqu'au bout**, avec des sous-agents en parallèle quand les morceaux sont
   indépendants (fichiers distincts). TDD : le test d'abord, puis le code. Le code calcule, le LLM
   orchestre. Les briques sont des ingrédients : licence vérifiée et inscrite dans
   `docs/research/INGREDIENTS.md`.
4. **Prouver** : exécuter les gates du dépôt (`pytest`, `ruff check src tests`, `opsys verifier`,
   plus les tests du département touché, et la CI du core si `core/` change). Aucun faux vert : une
   porte fermée devient « PARTIEL — GATE NATHAN » avec son repli implémenté.
5. **Mettre à jour `PLAN.md`** : cocher la tâche avec une ligne de preuve (commande et résultat),
   ou la marquer `BLOQUÉ :` avec la raison. Ajouter les tâches découvertes.
6. **Commit et push** sur la branche de travail, message en français qui dit pourquoi.
7. **Relancer** l'itération suivante. Ne s'arrêter que si le plan est entièrement coché, ou si toutes
   les tâches restantes attendent une décision de Nathan (les lister, une seule fois).

## Garde-fous permanents

- Frontières humaines T3 : paiement, secrets de production, suppression définitive, publication
  ou déploiement public, engagement externe. Jamais sans Nathan.
- Ne jamais exécuter le code amont dans le bac à sable : le core se construit et se teste en CI.
- Test de dérive (définition, §0.5) à chaque livrable.
- Économie de tokens : lectures ciblées, sorties courtes, sous-agents pour les recherches larges.
