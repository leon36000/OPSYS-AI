# FORGE METHOD — Méthode unifiée PROOF pour IDE agentiques

**Version :** v2.0-draft  
**Statut :** consolidation proposée — non canonique avant approbation humaine  
**Date :** 23 juillet 2026

## 0. Autorité et vocabulaire

Ce document définit la méthode de travail que ForgeAI PROOF IDE System doit faire appliquer automatiquement.

Ordre d'autorité :

1. décisions humaines T3 et amendements approuvés;
2. présent document une fois approuvé;
3. spécification d'implémentation approuvée;
4. décisions d'architecture enregistrées;
5. story active et critères d'acceptation;
6. tests, code, preuves et registres;
7. conversation courante.

La conversation n'est jamais la source de vérité.

### 0.1 Les couches ne se concurrencent pas

- **PROOF Core** gouverne les états, les gates, les preuves et les revues.
- **Forge Design Pipeline** conçoit et décompose. Il reprend les idées utiles de BMAD, mais n'utilise pas le framework BMAD officiel.
- **Forge Superpowers** utilise réellement le framework Superpowers, sous forme de fork ou de couche de patchs maintenable.
- **Forge Context Plane** gère le contexte avec Headroom, LLMLingua-2 et des politiques de prompt managing.
- **Forge Mini-Agents** exécutent les rôles spécialisés.
- **Forge Model Gateway** choisit les modèles selon les rôles et les contraintes de vendor.
- **Forge Optimization Lab** utilise DSPy et GEPA hors du chemin critique de production.
- **Forge IDE Adapters** traduisent la même méthode dans les primitives de chaque IDE.

Règle : **un seul control plane par fonction**. Aucun composant ne doit créer un second pipeline de validation ou une seconde source d'état.

## 1. Résultat autorisé

Toute unité de travail se termine dans un seul des états suivants :

- `DONE` — tous les critères sont satisfaits et les preuves sont présentes;
- `BLOCKED` — une cause précise, vérifiable et exploitable empêche la suite;
- `CANCELLED` — annulation humaine enregistrée;
- `REOPENED` — une preuve, un test ou une revue invalide un ancien `DONE`.

Les états vagues comme « presque terminé », « devrait fonctionner », « probablement correct » ou « fait sauf… » sont interdits.

## 2. Calibration obligatoire

Chaque projet et chaque nouvelle phase commencent par une calibration enregistrée.

### 2.1 Profil de rigueur

- **PROOF-Solo** : projet personnel, petit ou exploratoire. Gates déterministes, no-stub, preuve avant `DONE`, revue indépendante lorsque disponible, T3 humain.
- **PROOF-Team** : produit public, critique, financier, juridique, de sécurité ou de données sensibles. Pipeline complet, reviewers indépendants, dépouillement scripté, Sentinelle et gouvernance renforcée.

Un seul profil actif par projet. Tout changement de profil est une décision enregistrée.

### 2.2 Mode d'exécution

- **Native** : l'IDE utilise principalement son propre modèle; les mini-agents sont natifs lorsque l'IDE le permet.
- **Autonome externe** : les rôles sont reliés à des modèles configurés localement dans `config.ini`.
- **Connecté ForgeAI** : les rôles passent par la passerelle LiteLLM ForgeAI avec une clé virtuelle.

La méthode ne change pas entre les modes. Seules les capacités disponibles et la composition de l'équipe changent.

### 2.3 Niveau de risque

- **T0 — mécanique** : formatage, renommage sûr, documentation non canonique, génération déterministe.
- **T1 — standard** : fonctionnalité normale, bug non critique, refactor limité.
- **T2 — critique** : sécurité, authentification, données sensibles, architecture, dépendances majeures, migration, argent, légal.
- **T3 — irréversible ou externe** : secrets de production, paiement réel, suppression définitive, publication, déploiement public, engagement externe.

T3 exige toujours l'approbation humaine explicite.

### 2.4 Probe de capacités

Avant la première exécution, le système vérifie réellement :

- IDE et version;
- hooks et primitives disponibles;
- capacité de lancer des sous-agents;
- capacité d'utiliser des outils et des sorties structurées;
- accès au dépôt, aux tests et à Git;
- accès au fournisseur ou à LiteLLM;
- identité du vendor pour chaque modèle;
- disponibilité des modèles configurés;
- limites de contexte et de coût;
- stockage sécurisé des secrets;
- compatibilité des composants de contexte.

Une capacité supposée mais non prouvée ne peut pas servir de gate.

## 3. Invariants non négociables

1. **Conception avant code non trivial.**
2. **Story atomique avec critères testables.**
3. **Une story active, réclamée et tracée avant modification.**
4. **TDD; TDAD renforcé pour T2/T3.**
5. **No-stub et no-fake-done.**
6. **Auteur et reviewer indépendants.**
7. **Reviewers multi-vendor lorsque le profil l'exige.**
8. **Verdicts scellés et dépouillement déterministe.**
9. **Aucun LLM n'écrit seul un score de qualité final.**
10. **Preuve réelle avant `DONE`.**
11. **PR uniquement pour les changements destinés à la branche principale.**
12. **Canon proposé par l'IA, jamais modifié silencieusement.**
13. **Le contexte critique n'est jamais compressé avec perte.**
14. **Les secrets ne sont jamais placés dans Git, les prompts ou les registres.**
15. **Tout contournement, fallback ou changement de modèle est journalisé.**
16. **Toute amélioration de la méthode passe par la méthode elle-même.**
17. **Un blocage honnête est acceptable; une exception silencieuse ne l'est jamais.**

## 4. Forge Design Pipeline

Forge Design Pipeline est une méthode interne inspirée de la séparation des rôles utilisée par BMAD. Le produit n'installe pas le framework BMAD et ne dépend pas de son runtime.

### 4.1 Déclenchement

Forge Design est obligatoire pour :

- tout nouveau projet;
- toute fonctionnalité non triviale;
- toute modification d'architecture;
- toute demande dont le périmètre, les utilisateurs ou les contraintes sont ambigus;
- toute story T2 ou T3.

Une correction T0/T1 clairement bornée peut utiliser une spécification légère.

### 4.2 Artefacts

1. **Brief** — problème, utilisateurs, contexte, objectifs, contraintes, hors périmètre.
2. **PRD ou spécification fonctionnelle** — parcours, comportements, critères de succès, v1 et suite.
3. **Architecture** — modules, interfaces, flux, données, dépendances, décisions et risques.
4. **Plan d'exécution** — ordre, dépendances, migrations, stratégies de rollback.
5. **Stories** — unités assez petites pour tenir dans un contexte propre, avec critères d'acceptation et preuves attendues.

Chaque artefact relit le brief approuvé. Toute extension du périmètre est explicitement étiquetée comme proposition.

### 4.3 Anti-dérive de conception

Avant de produire ou modifier un artefact, l'agent doit comparer :

- objectif initial;
- décisions approuvées;
- contraintes non fonctionnelles;
- éléments hors périmètre;
- version courante du canon.

Une contradiction bloque la génération finale et produit une demande de décision.

## 5. Cycle de vie d'une story

Chemin normal :

```text
DRAFT
→ READY
→ CLAIMED
→ CONTEXT_READY
→ RED
→ IMPLEMENTING
→ VERIFYING
→ REVIEWING
→ APPROVED
→ MERGED
→ DONE
```

États latéraux : `BLOCKED`, `REOPENED`, `CANCELLED`.

Aucun saut n'est autorisé. Chaque transition exige les artefacts attendus.

### 5.1 Manifeste minimal

```yaml
story_id: FORGE-0001
title: ""
status: READY
risk_tier: T1
profile: PROOF-Team
owner: ""
branch: ""
worktree: ""
allowed_paths: []
forbidden_paths: []
dependencies: []
acceptance_criteria: []
required_tests: []
required_reviews: []
context_manifest: ""
evidence_manifest: ""
```

Le manifeste est l'autorité de périmètre de la story.

## 6. Préflight obligatoire

Avant tout code, l'agent doit prouver :

- story active identifiée;
- claim ou réservation obtenue;
- branche ou worktree correct;
- dépendances terminées;
- travail similaire recherché;
- code existant inspecté;
- règles applicables chargées;
- périmètre autorisé compris;
- tests et preuves attendus identifiés;
- risques T2/T3 reconnus;
- contexte critique présent et vérifié.

Si un élément manque, l'action d'écriture est bloquée.

## 7. Mini-agents automatiques

Les mini-agents sont des rôles, pas des modèles fixes. Le moteur de politiques décide de leur invocation selon des déclencheurs vérifiables. Un modèle peut suggérer une délégation, mais ne peut pas supprimer une délégation obligatoire.

### 7.1 Rôles essentiels

| Rôle logique | Déclencheur principal | Sortie attendue |
|---|---|---|
| `forge-context-scout` | nouvelle story, zone inconnue, reprise après compactage | cartographie sourcée, fichiers pertinents, risques et contexte minimal |
| `forge-design-analyst` | besoin ambigu ou fonctionnalité non triviale | brief et questions bloquantes |
| `forge-architect` | structure, interface, schéma, dépendance ou T2 | avis d'architecture avant code |
| `forge-hard-coder` | tâche difficile, longue, multi-fichiers ou algorithmiquement complexe | implémentation bornée à la story |
| `forge-test-runner` | changement de code, gate ou reprise | commandes exécutées, résultats, hashes et échecs |
| `forge-drift-checker` | avant plan, après compactage, avant review et avant merge | divergences, doublons, omissions et périmètre |
| `forge-docs-canon` | changement fonctionnel, documentation ou canon touché | proposition de diff documentation/canon |
| `forge-security-reviewer` | T2/T3, secrets, auth, réseau, dépendances | objections sourcées et tests de sécurité |
| `forge-reviewer-*` | story prête pour revue | verdict scellé au format standard |
| `forge-evidence-synthesizer` | avant `DONE` ou fin de phase | manifeste de preuves sans inventer de résultat |

### 7.2 Règles d'invocation

- invocation automatique lorsqu'un déclencheur obligatoire est satisfait;
- profondeur de sous-agent limitée par défaut à un niveau;
- nombre d'appels et budget configurables;
- pas de sous-agent imbriqué sans autorisation explicite;
- chaque agent reçoit un context pack minimal et un contrat de sortie;
- chaque agent reste dans les chemins autorisés;
- chaque changement de modèle ou fallback est enregistré;
- un agent qui ne peut pas produire la sortie contractuelle retourne `BLOCKED`.

### 7.3 Autorité

- Les agents de recherche, drift, sécurité et canon peuvent signaler ou proposer.
- La Sentinelle peut rouvrir une story, mais ne peut pas l'approuver.
- Le test runner rapporte l'exécution; il ne transforme pas un échec en succès.
- Le docs/canon keeper ne fusionne jamais seul un changement canonique.
- Les reviewers ne voient pas les autres verdicts avant scellement.

## 8. Équipe multi-modèle

### 8.1 Rôles stables, modèles remplaçables

Le code et les prompts utilisent des alias comme :

```text
forge-orchestrator
forge-architect
forge-hard-coder
forge-canon-keeper
forge-reviewer-1
forge-reviewer-2
forge-reviewer-3
forge-security
forge-test-runner
forge-evidence
```

Les identifiants de modèles sont définis dans la configuration ou dans LiteLLM.

### 8.2 Profil interne ForgeAI déclaré

Ce profil est un défaut opérationnel, pas une dépendance du noyau :

| Rôle | Modèle déclaré | Vendor |
|---|---|---|
| Orchestrateur de session | modèle principal de l'IDE (natif) | selon IDE |
| Architecte | GLM-5.2 | Zhipu AI |
| Code compliqué / long / multi-fichiers / 1M ctx | Kimi K3 | Moonshot AI |
| Code facile / standard | Kimi Code 2.7 | Moonshot AI |
| Documentation et canon (proposal_only) | Gemini Flash 3.6 | Google |
| Reviewer indépendant 1 | DeepSeek V4 Pro | DeepSeek |
| Reviewer indépendant 2 multimodal | Gemini 3.1 Pro | Google |
| Reviewer indépendant 3 / sécurité | LongCat 2.0 | Meituan |
| Sentinelle (tandem, contrôle continu, ne valide jamais) | DeepSeek V4 Pro + GLM-5.2 | DeepSeek + Zhipu |
| Parallélisme / worktrees | Grok 4.5 | xAI |
| Synthèse de preuves | MiMo 2.5 Pro | Xiaomi |
| Pool de rotation | Kimi, Qwen 3.7 Max, MiMo 2.5 Pro, MiniMax M3 | Moonshot/Alibaba/Xiaomi/MiniMax |

Chaque modèle doit réussir un firing test avant autonomie (seuil 0.90, voir config.ini). Le nom public
ou commercial d'un modèle ne constitue pas une preuve de capacité — la preuve de routage (§20.4) fait foi.

**Résolution de conception (23 juillet 2026) :** un seul Canon Keeper (Gemini Flash 3.6, proposal_only)
gouverne la cohérence documentaire quotidienne. La fonction d'arbitrage de cohérence CROSS-STORY
(détecter les divergences entre stories, avant merge) n'est PAS un second rôle canon — elle est déjà
couverte par le mini-agent `forge-drift-checker` (§7.1, déclenché après compactage et avant merge).
L'Orchestrateur (natif, Claude Code) joue ce rôle nativement dans sa session — aucun alias séparé requis.
Ceci retire toute notion antérieure de « tandem Canon Keeper » à deux modèles distincts : une seule
autorité par fonction (§0.1).

### 8.3 Indépendance critique

- un reviewer ne partage pas le vendor du codeur de la story;
- les reviewers d'une même story sont issus de vendors différents lorsque PROOF-Team l'exige;
- les verdicts sont produits en parallèle et scellés;
- l'identité réelle du vendor est vérifiée par la passerelle et enregistrée;
- un alias mal routé ou impossible à prouver bloque la revue indépendante;
- aucun fallback silencieux vers le modèle auteur.

### 8.4 Équipe optionnelle

Le système n'appelle pas tous les modèles à chaque tâche.

- T0 : gates déterministes; mini-agent seulement si nécessaire.
- T1 : auteur + un reviewer indépendant lorsque disponible.
- T2 : architecte selon impact + auteur + trois reviewers vendors distincts + Sentinelle.
- T3 : même chaîne + approbation humaine.

Si le mode autonome ne dispose pas de vendors indépendants, le système l'indique clairement. Il ne prétend pas avoir réalisé une revue indépendante fictive.

## 9. Forge Superpowers

ForgeAI utilise réellement le framework Superpowers pour l'exécution. Il est adapté plutôt que réécrit sans nécessité.

### 9.1 Éléments conservés

- workflows de planification et d'exécution utiles;
- pratiques TDD;
- debugging systématique;
- utilisation de branches ou worktrees;
- commandes et ergonomie compatibles lorsque possible.

### 9.2 Éléments remplacés ou renforcés

- routage des implémenteurs vers les alias ForgeAI;
- revue inline ou auto-review remplacée par la revue PROOF indépendante;
- propagation obligatoire du contexte de discipline aux sous-agents;
- hooks PROOF de début, fin, pré-commit, review et merge;
- gates no-stub, secrets, symbol sweep et no-fake-done;
- contexte fourni par Forge Context Plane;
- logs et preuves vers Forge State & Evidence.

### 9.3 Maintenance du fork

- version amont épinglée;
- patchs ForgeAI isolés et documentés;
- tests de compatibilité automatisés;
- mise à jour amont uniquement sur branche dédiée;
- audit des changements de prompts, hooks et agents;
- promotion après suite de conformité PROOF;
- rollback vers la version précédente disponible.

## 10. TDD et TDAD

### 10.1 Cycle normal

```text
Plan
→ Spec
→ Test RED réel
→ Implémentation GREEN réelle
→ Refactor
→ Vérification d'exécution
```

Les tests doivent échouer pour la bonne raison avant l'implémentation, puis passer réellement.

### 10.2 TDAD renforcé

Pour T2/T3 :

- tests et comportements attendus revus avant le code;
- tests négatifs et scénarios d'abus;
- sélection des tests impactés;
- rollback ou migration testée;
- preuves d'exécution conservées;
- validation humaine lorsque T3.

### 10.3 Interdits

- `pass`, `NotImplementedError`, `...`, corps vides;
- TODO/FIXME/HACK/PLACEHOLDER dans un diff destiné au merge;
- `assert True` ou tests sans assertion utile;
- skip/xfail sans justification enregistrée;
- données inventées présentées comme réelles;
- mocks hors tests ou simulant le cœur du comportement à prouver;
- test annoncé sans sortie d'exécution;
- couverture gonflée par des tests sans valeur.

## 11. Le contexte comme ressource rare

### 11.1 Classes de contexte

**C0 — constitutionnel, jamais compressé**

- invariants applicables;
- story active;
- critères d'acceptation;
- contraintes T2/T3;
- décisions d'architecture applicables;
- chemins autorisés et interdits.

**C1 — preuve et exécution, fidélité intégrale**

- code pertinent;
- interfaces;
- diffs;
- tests;
- erreurs exactes;
- packs de revue;
- verdicts;
- preuves et hashes.

**C2 — connaissance de travail, compressible avec provenance**

- documentation longue;
- résultats RAG;
- décisions anciennes non directement applicables;
- recherche technique;
- historique de tentatives.

**C3 — éphémère, filtrable agressivement**

- logs répétitifs;
- sorties d'outils volumineuses;
- JSON redondant;
- traces temporaires;
- conversations anciennes non canoniques.

### 11.2 Budget

Chaque appel possède :

- budget total estimé;
- réserve minimale pour la réponse, les outils et la récupération;
- quotas par classe;
- seuils de compactage;
- stratégie de fallback.

Le budget est configuré selon le modèle, pas supposé identique pour tous.

### 11.3 Context pack

Chaque context pack contient :

- identifiant et version;
- story et objectif;
- tranche de canon applicable;
- fichiers et symboles pertinents;
- interfaces touchées;
- décisions applicables;
- échecs précédents utiles;
- preuves attendues;
- sources et hashes;
- éléments exclus volontairement;
- budget et niveau de compression.

Le pack doit être reproductible. Un résumé libre sans provenance ne peut pas remplacer un pack.

### 11.4 Headroom

Headroom est le candidat principal pour :

- filtrer les sorties d'outils;
- réduire les répétitions;
- gérer le cache et les préfixes stables;
- préparer les éléments C2/C3;
- observer la pression de contexte.

Il commence en mode audit. Toute écriture automatique dans `AGENTS.md`, `CLAUDE.md` ou le canon est désactivée. Une transformation doit être mesurable et réversible.

### 11.5 LLMLingua-2

LLMLingua-2 ou un équivalent peut compresser les documents C2 volumineux.

Il ne s'applique jamais à :

- C0;
- code;
- diff;
- tests;
- erreurs exactes;
- pack de revue;
- verdicts;
- preuves.

Headroom et LLMLingua-2 ne doivent pas compresser successivement le même contenu sans benchmark démontrant l'absence de perte utile.

### 11.6 Compactage et reprise

Avant compactage :

1. écrire l'état structuré;
2. finaliser le journal de session;
3. enregistrer les décisions et tentatives;
4. produire le manifeste du prochain contexte;
5. vérifier les hashes.

Après compactage ou redémarrage :

1. recharger C0;
2. recharger le manifeste de story;
3. recharger l'état et les décisions applicables;
4. exécuter le drift checker;
5. reprendre uniquement après validation du contexte.

## 12. Prompt managing

Les prompts sont des artefacts versionnés.

### 12.1 Structure

- préfixe stable : identité du rôle, invariants, contrat de sortie;
- bloc projet : canon applicable et politiques;
- bloc story : objectif, périmètre, critères, tests;
- bloc contexte : fichiers et preuves pertinents;
- bloc dynamique : demande courante.

### 12.2 Règles

- aucun méga-prompt contenant tout le projet;
- aucun prompt de revue écrit librement pour influencer le verdict;
- templates neutres générés de manière déterministe;
- versions et hashes enregistrés;
- changement de prompt traité comme changement de code;
- tests de régression avant promotion;
- rollback immédiat possible.

## 13. DSPy et GEPA

DSPy et GEPA appartiennent au **Forge Optimization Lab**.

### 13.1 Usages autorisés

- optimisation des prompts de rôles;
- sélection du contexte C2/C3;
- choix d'un mini-agent;
- routage vers un rôle ou un modèle;
- stratégies de récupération après échec;
- décomposition de tâches;
- génération de variantes de prompt à tester.

### 13.2 Interdictions

Ils ne peuvent pas modifier automatiquement :

- le canon;
- les invariants;
- les gates;
- les critères `DONE`;
- les frontières T3;
- les règles d'indépendance;
- le format des preuves;
- les données de holdout.

### 13.3 Promotion

```text
trace réelle
→ proposition candidate
→ tests unitaires du prompt
→ benchmark contrôlé
→ holdout non vu
→ revue indépendante
→ canary
→ approbation
→ version promue
→ surveillance
```

Une optimisation qui réduit le coût mais augmente la dérive, la variance ou les faux `DONE` est rejetée.

## 14. Canon et documentation

### 14.1 Source unique

Le canon vit dans des fichiers versionnés. Les copies IDE sont générées ou référencent la source; elles ne divergent pas silencieusement.

### 14.2 Gardien du canon

Le rôle interne par défaut est confié à **Gemini Flash 3.6** (modèle puissant, à ne pas sous-estimer).
Dans les éditions autonomes, il est configurable.

Le gardien :

- détecte contradictions et documentation obsolète;
- propose des diffs;
- relie chaque modification à une story ou une décision;
- vérifie la cohérence entre code, tests et docs;
- ne fusionne jamais seul;
- ne réécrit pas les invariants sans amendement.

### 14.3 Mise à jour post-merge

Un changement fonctionnel ne peut être déclaré `DONE` si la documentation ou le canon applicable doit être mis à jour et ne l'est pas. L'absence de mise à jour doit être prouvée comme intentionnelle.

## 15. État, claims et anti-duplication

### 15.1 État durable

L'état officiel est stocké hors conversation :

- stories et statuts;
- claims;
- dépendances;
- branches et worktrees;
- décisions;
- tentatives échouées;
- modèles et vendors utilisés;
- context manifests;
- preuves et verdicts.

### 15.2 Claim obligatoire

Avant modification :

- rechercher une story identique ou chevauchante;
- vérifier les claims actifs;
- réserver la story et les chemins;
- créer ou vérifier la branche/worktree;
- publier le claim lorsque plusieurs machines collaborent.

Un conflit de claim bloque l'écriture jusqu'à résolution.

### 15.3 Mode sans service central

Le mode autonome utilise l'état local, Git et des claims versionnés. Si plusieurs postes travaillent sur le même dépôt, les claims doivent être poussés avant le code. Les limites de concurrence sont explicitement signalées.

### 15.4 Mode connecté

Le mode connecté peut utiliser une autorité de claims distante afin d'obtenir des réservations atomiques. Cette autorité reste optionnelle pour l'édition autonome.

## 16. Gates déterministes

### 16.1 Gates locaux

- format et lint;
- détection de secrets;
- no-stub;
- tests ciblés;
- symbol sweep et usages des symboles touchés;
- vérification du périmètre;
- vérification du manifeste de contexte;
- preuve enregistrée.

### 16.2 Gates CI

- tests unitaires, intégration et e2e pertinents;
- couverture avec détection de baisse significative;
- sécurité et dépendances;
- vérification des hashes;
- vérification des verdicts et vendors;
- no-fake-done;
- documentation/canon;
- conformité du ledger;
- interdiction de commit direct sur la branche protégée.

Un gate rouge ne peut pas être remplacé par l'avis d'un modèle.

## 17. Revue indépendante

### 17.1 Pack identique

Tous les reviewers reçoivent le même pack non compressé comprenant :

- story;
- critères;
- diff;
- fichiers nécessaires;
- tests et sorties;
- risques;
- format de verdict.

### 17.2 Scellement

Les verdicts sont déposés sans accès aux verdicts des autres. Le format est validé par schéma.

### 17.3 Dépouillement

Un script vérifie :

- nombre attendu;
- vendors distincts;
- absence du vendor auteur;
- timestamps;
- hashes des packs;
- format des objections;
- verdicts et objections critiques.

Aucun LLM ne décide seul du résultat du tally.

### 17.4 Désaccord

Round Delphi anonymisé, maximum deux tours. Ensuite, arbitrage humain ou orchestrateur sur pièces selon le niveau de risque, avec justification enregistrée. T3 reste humain.

## 18. Preuves et ledger

Le ledger est append-only et hash-chaîné.

Une preuve minimale contient :

- timestamp;
- acteur et rôle;
- modèle et vendor si applicable;
- story;
- commande exacte;
- code de sortie;
- hash de la sortie complète;
- artefacts;
- commit ou diff;
- hash précédent.

Le synthétiseur peut organiser les preuves, mais ne peut pas inventer un résultat absent.

## 19. Intégration automatique aux IDE

### 19.1 Démarrage

À l'ouverture ou à la première utilisation d'un projet :

1. détecter l'IDE;
2. charger l'adaptateur natif;
3. vérifier la présence du noyau Forge;
4. exécuter un `doctor` léger;
5. charger le canon et l'état actif;
6. enregistrer la session;
7. activer les déclencheurs de mini-agents;
8. refuser les actions d'écriture si le préflight échoue.

### 19.2 Fichiers natifs

Le dépôt contient un noyau commun et des adaptateurs générés :

- `AGENTS.md` comme entrée universelle;
- `CLAUDE.md` et agents/hooks Claude Code;
- règles Cursor;
- instructions et agents VS Code/Copilot;
- configuration et instructions Codex;
- MCP ou outils communs lorsque nécessaires.

Les fichiers adaptateurs ne dupliquent pas toute la méthode. Ils pointent vers la source canonique et contiennent seulement les instructions propres au harness.

## 20. LiteLLM et secrets

### 20.1 Configuration

Les fichiers de configuration contiennent :

- URL de la passerelle;
- noms des variables d'environnement ou références du coffre;
- alias de rôles;
- vendor déclaré;
- budgets, délais et fallbacks autorisés.

Ils ne contiennent jamais une clé réelle.

### 20.2 Clé virtuelle

Chaque poste ou IDE utilise une clé virtuelle distincte, limitée par :

- modèles autorisés;
- budget;
- expiration;
- identité;
- possibilité de révocation.

### 20.3 Mode interne simplifié

L'édition ForgeAI peut embarquer l'URL de la passerelle. L'utilisateur n'a alors qu'à enregistrer sa clé virtuelle avec la commande sécurisée prévue.

### 20.4 Preuve de routage

Chaque appel critique enregistre l'alias demandé, le modèle servi, le vendor et l'identifiant de trace. Une équipe multi-vendor non prouvée est considérée indisponible.

## 21. Méthodologie-as-code

- la méthode possède une version et un changelog;
- les prompts, politiques, schémas et gates ont des tests;
- les performances par rôle et par modèle sont mesurées;
- le firing test contrôle l'autonomie;
- une régression de méthode peut rouvrir les changements associés;
- tout amendement passe par PR, revue PROOF-Team et validation humaine;
- aucune divergence locale permanente n'est autorisée.

## 22. Définition de DONE

Une story est `DONE` uniquement si :

- tous les critères d'acceptation sont prouvés;
- tests et gates sont verts;
- aucun stub interdit n'existe;
- le symbol sweep est traité;
- le périmètre est respecté;
- les reviews attendues sont valides;
- les vendors requis sont prouvés;
- la documentation et le canon sont cohérents;
- le ledger contient les preuves;
- le commit ou merge attendu existe;
- aucune action T3 n'attend une approbation;
- la Sentinelle n'a pas rouvert la story.

Sinon, la story est `BLOCKED` ou `REOPENED`.

## 23. Comportement en cas d'incertitude

L'agent doit :

1. distinguer fait, hypothèse et décision;
2. rechercher les sources disponibles;
3. demander une décision lorsque l'ambiguïté change l'architecture, le risque ou le périmètre;
4. choisir `BLOCKED` plutôt qu'inventer;
5. enregistrer la cause et la prochaine action exacte.

---

**Formule exécutoire :**

> Conçois avant de coder. Réserve avant de modifier. Charge seulement le contexte vérifié nécessaire. Teste réellement. Fais revoir indépendamment. Prouve avant `DONE`. Échoue fermé plutôt que dériver silencieusement.
