# Boucle d'exécution OPSYS-AI

## Une itération utile

1. Lire la tâche du plan courant et le contexte du département, puis vérifier l'état Git. Les
   [directives Nathan](../produit/DIRECTIVES-NATHAN.md) et ADR-0012 priment sur les méthodes anciennes.
2. Choisir un livrable dans le périmètre autorisé, avec entrées, sortie et preuve explicites.
   Découper les grands départements en parcours utilisables sans perdre leur périmètre cible.
3. Inspecter l'existant ; rechercher GitHub/GitLab si une brique peut éviter une réécriture.
   Qualifier licence, code, maintenance et coût d'adaptation. Déléguer les morceaux indépendants
   quand cela économise du travail, avec responsabilités et fichiers distincts.
4. Implémenter le changement et sa régression pertinente. Le code calcule, les modèles orchestrent.
   Aucun vote de modèles, fournisseur extérieur obligatoire ni revue imposée entre chaque étape.
5. Vérifier proportionnellement : documents → liens/cohérence/diff ; code → tests du parcours,
   lint ; contrats/manifestes → `opsys-metier verifier` ; argent/accès/rejeu → tests négatifs ;
   migration/backup → intégrité et restauration. Core → CI prévue par `core/AGENTS.md`.
   Une même preuve n'est répétée que si un nouveau changement ou échec le justifie.
6. Mettre à jour le plan et la mémoire de projet : résultat, fichiers, décision, commandes,
   limites, statut et prochaine action. Une panne OAuth laisse un repli explicite ; elle ne
   bloque pas les capacités internes indépendantes et ne devient pas une fausse preuve en réel.
7. Continuer jusqu'au livrable autorisé complet. Préparer un diff révisable. Commit, push, merge
   et déploiement suivent l'autorisation de la session ; ils ne sont pas déclenchés par la boucle.

## Garde-fous

- Conserver les validations humaines N0–N5 pour les effets financiers, fiscaux, légaux et sensibles.
- Revalider droits, objet et arguments au moment de l'action, avec audit et protection du rejeu.
- Les tests ciblés et la construction du Core sont permis localement, avec les dépendances verrouillées
  et les contrôles décrits dans `core/AGENTS.md`; cette qualification ne vaut pas déploiement.
- Décrire ce qui est prouvé et ce qui manque ; aucune promesse de « 100 % » sans critères couverts.
- Économiser tokens et contexte ; ne pas déclencher plusieurs agents pour un calcul déterministe.
