# M10 — Mémoire long terme, intelligence et conscience opérationnelle (condensé fonctionnel du prompt de Nathan, juin 2026)

But : le **cerveau permanent** de Forge/GRS. Rien d'important n'est oublié ; les agents ne travaillent jamais « dans le vide ». Pas un
simple RAG : mémoire gouvernée, versionnée, vérifiable, interrogeable, auditable. Deux mondes reliés mais séparés par permissions :
**mémoire de l'usine** (développement : prompts, plans, décisions, code, tests, erreurs, conventions, infra) et **mémoire d'affaires**
(clients, procédures, services, prix, marketing, compta, équipes, inventaire, factures, chantiers, apprentissages). (Le dépôt actuel
sépare déjà le domaine développement des données d'affaires, ADR-0012.)

## Politiques (règles de non-oubli)
1. Tout travail produit une trace (événement, résumé, fichiers, raison, preuve, tests, statut, auteur, horodatage, dépendances, impact,
   prochaine action). 2. **Aucun agent ne code sans contexte** : avant de modifier, récupérer constitution, matrice de complétion,
   module concerné, décisions, prompts/plans liés, fichiers clés, erreurs historiques, conventions, tests, dépendances, risques, gates,
   dernière modification liée ; sinon arrêt + alerte (« preflight »). 3. Rien n'est écrasé sans mémoire (historique, dépendances, routes,
   tests, docs, instantané, retour arrière, décision, validation si risque). 4. Toute décision a une raison (contexte, options, avantages,
   risques, conséquences, date, responsable, statut proposée/validée/remplacée/annulée). 5. La mémoire est révisable : fusion de doublons,
   remplacement d'une vérité obsolète, marquage « dépassé », historique conservé, jamais de perte de la trace d'origine (supersede /
   archive / redact / tombstone, pas de suppression dure). 6. Toute information importante est **sourcée**. 7. Le système se connaît :
   identité, mission, limites, architecture, modules, état, valeurs, règles, modes, critères de qualité, interdits. 8. Mémoire avant
   génération (injecter le contexte pertinent). 9. Mémoire après action (« postflight » : ce qui a été fait, pourquoi, résultat). 10. Pas
   de mémoire magique : stockée, indexée, récupérable, vérifiable.

## Questions auxquelles il doit répondre à tout moment (avec sources)
Qui sommes-nous, qu'est-ce que Forge/GRS, ce que chaque module doit faire, ce qui est fait/incomplet, pourquoi telle décision, quels
prompts/plans ont orienté le travail, quels fichiers modifiés, dépendances entre composants, quels tests prouvent quoi, quelles erreurs
ne jamais répéter, quelles décisions de Nathan sont des règles permanentes, quels modules ne pas reconstruire, quels gates exigent un
humain, quel contexte injecter avant de coder, quelle est la vérité actuelle.

## Couches
Journal d'événements immuable (append-only) ; mémoire structurée canonique (événements, entités, relations, décisions, prompts, plans,
instantanés de fichiers, changements de code, résultats de tests, paquets de contexte, pièges connus « gotchas », modèle de soi) ;
mémoire vectorielle filtrée (collections par type : événements, code, prompts, plans, décisions, docs, erreurs, tests, affaires, clients,
marketing, compta, CRM, opérations, modèle de soi — chaque point renvoie à une entité canonique, jamais orphelin) ; **graphe de
connaissances** (DEPENDS_ON, IMPLEMENTS, MODIFIES, BREAKS, FIXES, TESTS, DOCUMENTS, SUPERSEDES, CONTRADICTS, SUPPORTS, REQUIRES_GATE,
GENERATED_FROM, CAUSED_BY, OWNED_BY…, avec validité temporelle) ; points de reprise de workflows ; registre de prompts et de plans ;
registre de décisions (ADR) ; mémoire de code (fichiers, symboles, routes, imports, dépendances, résumé de diff, analyse d'impact) ;
mémoire d'erreurs (symptôme, cause racine, correctif, test de non-régression, prévention) ; mémoire de validation (tests, commandes,
résultats, preuves) ; mémoire d'agents (rôle, outils, permissions, historique, forces/faiblesses, critères d'escalade) ; mémoire
temporelle (ce qui était vrai, ce qui l'est maintenant, ce qui a changé, quand, pourquoi, par qui) ; routeur de récupération ; injecteur
de contexte ; auditeur de mémoire ; gouvernance (permissions, confidentialité, rétention, oubli contrôlé) ; banc d'évaluation.

## Fonctions attendues
- **Journal d'événements** typé (prompt créé, plan créé, tâche démarrée/terminée, fichier modifié, décision, test, bug trouvé/corrigé,
  statut de module, route ajoutée, doc, config, gate bloqué, instruction de l'utilisateur, observation système, échec runtime,
  validation réussie/échouée).
- **Paquets de contexte automatiques** (identité Forge, identité GRS, mémoire M10, préparation au codage, contexte par module, historique
  prompts/plans, bugs et pièges, mémoire d'affaires) en **couches** : indispensable (court, toujours injecté) / important (décisions,
  fichiers, risques) / preuves / approfondissement ; chaque paquet : résumé, puces critiques, sources, fichiers, risques, tests, TODO.
- **Récupération intelligente** combinant sémantique, mots-clés, module, domaine, fraîcheur, importance, statut, autorité de la source,
  voisinage dans le graphe, décisions, erreurs, tests, permissions, contexte de tâche ; pondérations différentes pour le code (plus de
  code/décisions/pièges/tests) et pour les affaires (procédures, CRM, compta, clients, décisions de Nathan).
- **Résolveur de vérité canonique**, ordre : constitution > décisions explicites de Nathan > matrice vivante > rapports récents validés >
  tests et sondes runtime > code actuel > documentation > journaux > mémoires anciennes > hypothèses. Contradiction = on ne tranche pas
  au hasard : créer une contradiction, marquer, proposer une résolution, valider si critique.
- **Préparation / clôture de tâche (preflight/postflight)** pour les agents de développement : feu vert/rouge avec risque, paquet de
  contexte, « ne pas casser », fichiers à lire, décisions/prompts/plans liés, pièges, tests requis, approbation requise ; en clôture :
  événement, résumé de diff, mise à jour des instantanés, statut du module, relations prompt→plan→changements→fichiers→tests, index
  vectoriel, graphe, TODO, tests/docs manquants, mise à jour de matrice nécessaire.
- **Consolidation nocturne** : scanner dépôt, historique Git, prompts, plans, rapports, journaux, tests, traces LLM, santé runtime,
  matrice ; détecter nouveautés, doublons, contradictions, mémoires obsolètes, composants orphelins, modules sans tests, routes sans doc,
  prompts sans résultat, décisions non documentées, fichiers modifiés non mémorisés ; mettre à jour les index et le graphe ; rapport +
  actions ; alerte si risque.
- **Audit hebdomadaire / « pas d'oubli »** avec questions-tests (état réel, modules en stub, derniers changements, erreurs corrigées, gates
  ouverts…), réponses sourcées, scores (rappel, précision, fraîcheur, contradictions, couverture des sources, qualité des paquets, non-oubli).
- **Modèles de soi** générés et tenus à jour (usine ; entreprise-OS) : identité, rôle, règles, modules, états, limites, prochaine priorité.
- **Gouvernance et confidentialité** : jamais de secret en clair (références au gestionnaire de secrets), masquage des données
  personnelles dans l'index vectoriel si inutile, permissions par domaine, audit des accès, export contrôlé, droit à l'oubli pour données
  client, rétention configurable ; niveaux (interne, sensible, financier, privé client, référence de secret, verrouillé légal).
- **Observabilité** : trace de chaque agent (quel contexte, quelle mémoire utilisée, quel prompt, quel modèle, coût, latence), métriques
  (événements/jour, latence de récupération, taille des paquets, taux de succès, contradictions, périmées, orphelines, violations de
  « pas de préparation », score de non-oubli, relations du graphe).
- **Interface en ligne de commande** (statut, ingestion dépôt/Git/prompts/plans, préparation, clôture, question, contexte de module,
  audit, contradictions, orphelins, nuit, export de paquet) et **tableau de bord admin** (recherche, modèle de soi, mémoire de module,
  registres prompts/plans/décisions, mémoire de code, d'erreurs, visionneuse de paquets, rapports d'audit, revue des contradictions,
  revue de la mémoire sensible, santé des magasins) ; **app mobile** : admin (recherche, derniers changements, décisions à valider,
  contradictions, rapport) ; employé (note de chantier, « chose à ne pas oublier », erreur terrain ; ne voit pas la mémoire interne) ;
  vendeur (mémoire client/lead autorisée, apprentissage de vente, objection client).
- **Tests** : création d'événement/entité/relation, registres, paquets de contexte, résolveur de vérité, classificateur de sensibilité,
  révision, détection de contradiction ; intégration (prompt→plan→fichiers→tests→mémoire ; préparation d'un module récupère décisions,
  fichiers, pièges ; décision obsolète remplacée ; contradiction rapport ancien vs matrice récente ; secret non stocké en clair ; impact
  d'une modification CRM sur la compta ; test échoué → mémoire d'erreur ; question → réponse sourcée) ; E2E « ne jamais oublier un prompt »,
  « avant de coder M7 », « erreur historique », « contradiction », « travail minuscule » (petit fichier de config modifié puis retrouvé).
- **Critère** : pas d'état « vérifié » sans E2E verts de non-oubli, docs, matrice à jour.
