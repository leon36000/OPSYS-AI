# ForgeAI PROOF IDE System — VISION

**Statut :** VALIDÉ par Nathan — corrections roster appliquées (voir RECONCILIATION.md)  
**Date :** 23 juillet 2026  
**Nom de travail du produit :** ForgeAI PROOF IDE System

> Ce document devient canonique uniquement après validation humaine explicite. Il consolide la méthode PROOF existante et les décisions ajoutées ensuite; il ne remplace pas silencieusement les documents antérieurs.

## 1. ForgeAI

ForgeAI est une entreprise et une institution qui conçoit des méthodes, des outils et des infrastructures propriétaires ou distribuables afin d'améliorer le développement et le déploiement de systèmes d'intelligence artificielle.

Deux produits doivent rester distincts :

1. **ForgeAI Toolkit** : application modulaire et clé en main de déploiement d'infrastructures IA, avec stacks préconstruites, optimisées et compatibles avec des déploiements multinœuds.
2. **ForgeAI PROOF IDE System** : système intégré aux IDE agentiques pour faire appliquer automatiquement les méthodes de travail ForgeAI pendant la conception, l'exécution, la vérification et la documentation des projets.

Le Toolkit pourra plus tard installer ou déployer le PROOF IDE System, mais le PROOF IDE System ne doit pas dépendre du Toolkit.

## 2. Problème à résoudre

Les agents de développement deviennent peu fiables lorsque les projets et les conversations s'allongent. Les problèmes récurrents sont :

- oubli du canon, des décisions et des contraintes;
- dérive progressive hors du périmètre;
- travail en double entre sessions, agents, branches ou IDE;
- boucles et répétitions sans progrès mesurable;
- perte d'état après compactage, redémarrage ou changement de machine;
- modifications de fichiers hors périmètre;
- auto-évaluation complaisante et faux `DONE`;
- documentation qui ne correspond plus au code;
- surcharge de contexte par des logs, recherches et sorties d'outils;
- comportements différents entre Claude Code, Codex, Cursor et VS Code/Copilot.

Un meilleur prompt ne suffit pas. La solution doit combiner une méthode, des fichiers d'autorité, des hooks, des gates déterministes, une gestion explicite du contexte, des sous-agents spécialisés et des preuves vérifiables.

## 3. Mission

Transformer les agents intégrés aux IDE en exécutants gouvernés, remplaçables et vérifiables qui appliquent automatiquement les méthodes ForgeAI sans exiger que l'utilisateur répète constamment les règles.

Le système doit :

- s'installer dans les IDE ciblés;
- se charger automatiquement à l'ouverture ou à l'utilisation d'un projet;
- détecter le type de travail demandé;
- appliquer la bonne séquence méthodologique;
- invoquer automatiquement les mini-agents requis;
- conserver l'état utile hors de la conversation;
- gérer le contexte comme une ressource rare;
- utiliser les modèles natifs de l'IDE ou une équipe multi-modèle distante;
- bloquer les sorties non conformes plutôt que dériver silencieusement;
- produire des preuves et permettre une reprise exacte après interruption.

## 4. Définition opérationnelle de « fiable au maximum »

Le système ne prétend pas garantir mathématiquement l'absence totale de bugs. Le terme « infaillible » est traduit en objectifs vérifiables :

- aucune dérive silencieuse;
- aucun `DONE` sans preuve;
- aucun contournement silencieux d'un gate;
- aucune modification T3 sans approbation humaine;
- aucune auto-review présentée comme revue indépendante;
- aucun oubli d'état critique après compactage ou reprise;
- aucune duplication de tâche connue sans alerte ou blocage;
- toute panne, incertitude ou incompatibilité devient `BLOCKED` avec une raison exploitable;
- toute action critique est traçable et récupérable.

La philosophie reste : **liberté sur le chemin, rigueur sur les sorties**.

## 5. Deux modes, une seule méthode

### 5.1 Mode autonome

Le système fonctionne sur le poste du développeur sans infrastructure ForgeAI obligatoire.

Il peut utiliser :

- le modèle natif de l'IDE;
- des modèles locaux;
- des fournisseurs externes compatibles configurés dans `config.ini`;
- OpenRouter, DeepInfra ou d'autres passerelles compatibles;
- une passerelle LiteLLM appartenant à l'utilisateur.

Les rôles sont définis logiquement. Aucun modèle commercial précis n'est indispensable au noyau.

### 5.2 Mode connecté ForgeAI

Le système se connecte à la passerelle LiteLLM de ForgeAI et accède à l'équipe multi-modèle interne par des alias de rôles.

Pour l'utilisateur interne, l'installation doit pouvoir préconfigurer l'URL. L'utilisateur fournit seulement une clé virtuelle LiteLLM stockée dans le coffre du système d'exploitation.

Le profil interne actuel prévoit notamment :

- **Gemini Flash 3.6** pour la documentation et la garde du canon, en mode proposition uniquement (modèle puissant, ne pas sous-estimer);
- **Kimi K3** pour les tâches de code difficiles, longues ou multi-fichiers;
- des modèles distincts pour l'architecture, les revues indépendantes, la sécurité, les tests et la synthèse de preuves.

Les identifiants réels restent configurables et ne doivent jamais être codés en dur dans la méthode.

## 6. Les couches du système

Le produit est un ensemble cohérent de couches superposées, avec une seule autorité par fonction :

1. **PROOF Core** — constitution, niveaux de risque, gates, preuves, revues et états autorisés.
2. **Forge Design Pipeline** — méthode de conception inspirée des idées de BMAD, sans dépendre du framework BMAD officiel.
3. **Forge Superpowers** — utilisation réelle du framework Superpowers, maintenu sous forme de fork ou de couche de patchs, avec routage, revues, contexte et hooks adaptés à ForgeAI.
4. **Forge Context Plane** — prompt managing, budgets de contexte, Headroom et LLMLingua-2 selon le type de contenu.
5. **Forge Mini-Agents** — délégation automatique des tâches spécialisées lorsque les déclencheurs sont satisfaits.
6. **Forge Model Gateway** — rôles logiques, LiteLLM, fournisseurs externes et indépendance entre vendors.
7. **Forge Optimization Lab** — DSPy et GEPA pour optimiser les prompts, la sélection de contexte et le routage après évaluation contrôlée.
8. **Forge IDE Adapters** — intégrations natives pour Claude Code, Codex, Cursor et VS Code/Copilot.
9. **Forge State & Evidence** — état durable, réservations, décisions, registres append-only, hashes et artefacts.

Aucune couche ne doit devenir un second orchestrateur concurrent. PROOF gouverne, Forge Design conçoit, Superpowers exécute, Context Plane prépare le contexte et DSPy/GEPA optimisent hors production.

## 7. Le contexte est une ressource rare

Le contexte doit être :

- budgété;
- typé;
- versionné;
- sourcé;
- mesuré;
- compressé uniquement lorsque cela est sûr;
- reconstituable après compactage ou redémarrage.

Le canon, les règles applicables, la story active, les critères d'acceptation, le code, les diffs, les tests, les verdicts et les preuves ne doivent jamais subir une compression avec perte.

Les logs répétitifs, sorties d'outils volumineuses, anciennes conversations et documents de référence peuvent être filtrés ou compressés sous contrôle.

## 8. Publics visés

- ForgeAI pour ses projets internes;
- développeurs individuels utilisant plusieurs IDE;
- équipes qui souhaitent une méthode reproductible;
- organisations qui veulent connecter leurs propres modèles et fournisseurs;
- futurs utilisateurs du ForgeAI Toolkit.

## 9. Périmètre de la première version utilisable

La première version doit fournir :

- un installateur idempotent;
- un noyau de méthode commun dans le dépôt;
- les adaptateurs Claude Code, Codex, Cursor et VS Code/Copilot;
- le chargement automatique des instructions;
- les mini-agents essentiels et leurs déclencheurs;
- un fork ou une couche de patchs Forge Superpowers;
- les gates PROOF locaux et CI;
- un état local durable et un ledger append-only;
- la gestion du contexte avec politiques sans perte;
- un mode autonome;
- un mode LiteLLM connecté;
- un fichier `config.ini` validé par schéma;
- un stockage sécurisé des clés;
- des commandes `install`, `init`, `doctor`, `repair`, `status` et `uninstall`;
- une suite de tests de conformité multi-IDE.

## 10. Hors périmètre initial

- remplacer complètement les IDE;
- appeler dix modèles sur chaque tâche;
- laisser un modèle modifier seul le canon;
- laisser DSPy ou GEPA promouvoir automatiquement une méthode en production;
- compresser le code, les tests, les diffs, les verdicts ou les preuves;
- dépendre obligatoirement d'un serveur ForgeAI;
- fusionner ForgeAI Toolkit et PROOF IDE System en un seul produit;
- promettre l'absence absolue de défauts sans preuve mesurable.

## 11. Principes non négociables

- **Une seule autorité par fonction.**
- **DONE avec preuve ou BLOCKED avec raison.**
- **Le modèle auteur ne valide jamais seul son propre travail.**
- **Les actions T3 restent humaines.**
- **Le canon est proposé par l'IA, approuvé par le processus.**
- **Le contexte critique reste fidèle et non compressé.**
- **Les secrets ne sont jamais stockés dans Git ou dans un prompt.**
- **Les modèles sont remplaçables; les rôles et les contrats restent stables.**
- **Les méthodes sont versionnées, testées et amendées par preuve.**
- **Le système échoue fermé lorsque sa conformité ne peut pas être prouvée.**

## 12. Distribution

Le produit doit pouvoir exister sous plusieurs éditions partageant le même format de méthode et de configuration :

- édition autonome ou communautaire;
- édition ForgeAI connectée;
- modules commerciaux éventuels de gouvernance, d'infrastructure, de conformité et de support.

Le choix juridique final entre open core, double licence ou source-available doit être décidé séparément avant publication. La méthode technique ne doit pas dépendre de ce choix.

## 13. Critères de succès

Le produit est prêt pour une première diffusion lorsque :

1. le même dépôt peut être ouvert dans les quatre IDE ciblés avec les mêmes invariants;
2. l'installation et la désinstallation sont idempotentes et ne détruisent aucun fichier utilisateur;
3. une tâche non triviale déclenche automatiquement la conception et la décomposition adaptées;
4. une story ne peut pas atteindre `DONE` sans artefacts de preuve;
5. une modification hors périmètre, un faux stub ou une fuite de secret est bloqué;
6. une session reprise après compactage recharge l'état critique exact;
7. le contexte compressible est réduit sans altérer les éléments critiques;
8. le mode connecté route les alias vers l'équipe LiteLLM et prouve le vendor utilisé;
9. le mode autonome fonctionne sans infrastructure ForgeAI;
10. chaque optimisation DSPy/GEPA peut être comparée, rejetée et restaurée.

## 14. Vision finale

> **ForgeAI PROOF IDE System transforme chaque IDE agentique en environnement de développement gouverné, contextuellement discipliné, multi-modèle lorsque disponible, et incapable de déclarer silencieusement un travail terminé sans preuve.**
