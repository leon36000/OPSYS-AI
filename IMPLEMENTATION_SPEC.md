# ForgeAI PROOF IDE System — IMPLEMENTATION SPEC

**Version :** v0.2-draft  
**Statut :** plan d'implémentation proposé — à valider avant code  
**Date :** 23 juillet 2026

## 0. Instruction d'exécution

Ne pas commencer par écrire un gros framework complet.

Commencer par :

1. vérifier les capacités réelles des IDE ciblés;
2. consolider les schémas et invariants;
3. construire une tranche verticale complète sur Claude Code;
4. prouver le comportement automatique et les gates;
5. extraire le noyau commun;
6. ajouter les autres adaptateurs sans dupliquer la méthode.

Chaque module ci-dessous devient une ou plusieurs stories PROOF atomiques.

## 1. Objectif du produit

Construire un système installable dans Claude Code, Codex, Cursor et VS Code/Copilot qui :

- applique automatiquement `FORGE_METHOD.md`;
- charge les règles et l'état à l'ouverture ou au premier usage d'un projet;
- déclenche automatiquement les mini-agents requis;
- utilise réellement Superpowers via un fork ou une couche de patchs ForgeAI;
- utilise Forge Design pour les plans, sans installer le framework BMAD;
- gère le contexte avec Headroom, LLMLingua-2 et des budgets explicites;
- utilise DSPy et GEPA dans un laboratoire d'optimisation contrôlé;
- fonctionne sans infrastructure ForgeAI;
- peut utiliser l'équipe multi-modèle ForgeAI avec une clé virtuelle LiteLLM;
- bloque les faux `DONE`, les stubs, les dérives et les actions non prouvées;
- reste modulaire, réparable, désinstallable et portable.

## 2. Comportement attendu côté utilisateur

### 2.1 Installation globale

L'utilisateur installe le paquet une fois par poste :

```text
forge install --ide claude-code
forge install --ide codex
forge install --ide cursor
forge install --ide vscode-copilot
```

L'installateur :

- détecte les IDE présents;
- installe seulement les adaptateurs demandés;
- sauvegarde tout fichier existant avant modification;
- n'écrase rien silencieusement;
- enregistre un manifeste d'installation;
- peut être relancé sans duplication;
- fournit `doctor`, `repair` et `uninstall`.

### 2.2 Initialisation d'un projet

```text
forge init /chemin/projet
```

Cette commande :

- détecte le dépôt Git;
- propose le profil PROOF;
- crée le noyau `.forge/`;
- génère les fichiers adaptateurs natifs;
- crée ou référence `AGENTS.md`;
- valide `config.ini`;
- configure les hooks locaux;
- prépare les dossiers de stories, état et preuves;
- ne modifie pas le code du projet.

### 2.3 Ouverture du projet

À l'ouverture ou au premier prompt :

- l'adaptateur charge `AGENTS.md`;
- exécute `forge session start` ou son équivalent;
- vérifie le projet avec un doctor léger;
- recharge la story active et le contexte critique;
- active les déclencheurs de mini-agents;
- refuse les écritures si la story ou le préflight est absent.

### 2.4 Mode connecté simplifié

Pour l'édition interne ForgeAI :

1. l'URL LiteLLM est préconfigurée;
2. l'utilisateur exécute `forge secrets set litellm`;
3. il colle sa clé virtuelle dans une invite masquée;
4. la clé est stockée dans le coffre du système;
5. les alias `forge-*` deviennent disponibles dans tous les IDE pris en charge.

Aucune clé réelle ne doit être écrite dans `config.ini`.

## 3. Architecture cible

```text
┌──────────────────────────────────────────────────────────┐
│ Claude Code │ Codex │ Cursor │ VS Code/Copilot          │
└───────┬──────────┬──────────┬──────────────┬─────────────┘
        │          │          │              │
        └──────────┴──── Forge IDE Adapters ─┘
                           │
                    Forge Session Bootstrap
                           │
        ┌──────────────────┼───────────────────┐
        │                  │                   │
   PROOF Policy       Mini-Agent Router   Context Plane
        │                  │                   │
        │          Forge Superpowers      Headroom
        │                  │              LLMLingua-2
        │                  │                   │
        └──────────────────┼───────────────────┘
                           │
                    Forge Model Gateway
               Native │ Direct │ LiteLLM connecté
                           │
              State / Claims / Proof Ledger
                           │
                  Git / Worktrees / CI
```

## 4. Choix techniques de référence

Ces choix sont proposés pour la première implémentation et doivent être validés avant code.

### 4.1 Langage principal

**Python 3.12+** pour :

- CLI cross-platform;
- DSPy et GEPA;
- LLMLingua-2;
- orchestration des outils;
- validation de configuration;
- intégrations LiteLLM;
- génération de fichiers adaptateurs.

Utiliser de petits wrappers shell, PowerShell ou Node uniquement lorsque l'IDE l'exige.

### 4.2 Stockage autonome

- SQLite pour l'état local transactionnel;
- JSONL append-only hash-chaîné pour les preuves et décisions;
- fichiers YAML ou JSON validés par schéma pour les stories;
- Git pour le code, les décisions approuvées et l'historique;
- coffre OS pour les secrets.

### 4.3 Stockage connecté optionnel

- API ForgeAI ou service de claims optionnel;
- PostgreSQL pour claims atomiques, sessions et métriques partagées;
- stockage d'artefacts configurable;
- aucune dépendance à ce service pour le mode autonome.

### 4.4 Configuration

- `config.ini` comme interface humaine principale;
- schéma interne strict et validation au démarrage;
- variables d'environnement et coffre OS pour secrets;
- surcharge par projet sans modifier la configuration globale;
- profils `native`, `standalone` et `connected`.

## 5. Structure de dépôt proposée

```text
/
├── AGENTS.md
├── VISION.md
├── FORGE_METHOD.md
├── IMPLEMENTATION_SPEC.md
├── config.ini.example
├── pyproject.toml
├── src/forgeai_proof/
│   ├── cli/
│   ├── core/
│   │   ├── policy/
│   │   ├── state/
│   │   ├── stories/
│   │   ├── claims/
│   │   ├── evidence/
│   │   └── schemas/
│   ├── adapters/
│   │   ├── claude_code/
│   │   ├── codex/
│   │   ├── cursor/
│   │   └── vscode_copilot/
│   ├── superpowers/
│   ├── agents/
│   ├── context/
│   │   ├── headroom/
│   │   ├── llmlingua/
│   │   └── packs/
│   ├── models/
│   │   ├── native/
│   │   ├── direct/
│   │   └── litellm/
│   ├── optimization/
│   │   ├── dspy/
│   │   └── gepa/
│   ├── canon/
│   ├── hooks/
│   ├── doctor/
│   └── security/
├── templates/
│   ├── common/
│   ├── claude-code/
│   ├── codex/
│   ├── cursor/
│   └── vscode-copilot/
├── policies/
├── prompts/
├── schemas/
├── benchmarks/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   ├── adapters/
│   ├── failure_injection/
│   └── fixtures/
└── vendor/
    └── superpowers-patches/
```

## 6. Module A — PROOF Core

### 6.1 Responsabilités

- machine d'état des stories;
- transitions autorisées;
- profils PROOF-Solo et PROOF-Team;
- tiers T0-T3;
- règles de préflight;
- définition de `DONE`, `BLOCKED`, `REOPENED`;
- politiques de reviewer/vendor;
- autorisations de fichiers et actions;
- validation des preuves.

### 6.2 Exigences

- aucune décision critique ne repose uniquement sur du texte libre d'un LLM;
- transitions validées par fonctions déterministes;
- politiques testables indépendamment des IDE;
- mode fail-closed configurable, activé par défaut;
- messages de blocage précis et remédiables.

### 6.3 Critères d'acceptation

- saut de `READY` à `DONE` refusé;
- story sans critères refusée;
- T3 sans approbation humaine refusé;
- auteur utilisé comme reviewer indépendant refusé;
- `DONE` sans manifeste de preuves refusé;
- une story peut être rouverte par un gate ou la Sentinelle.

## 7. Module B — État, claims et ledger

### 7.1 État local

Créer dans chaque projet :

```text
.forge/
├── config.ini
├── state/forge.db
├── stories/
├── claims/
├── decisions/
├── evidence/
├── sessions/
├── context/
├── reviews/
├── generated/
└── backups/
```

### 7.2 Claims

Un claim associe :

- story;
- utilisateur ou agent;
- machine;
- IDE;
- branche;
- worktree;
- chemins réservés;
- expiration;
- timestamp et hash.

### 7.3 Anti-duplication

Avant claim :

- rechercher les stories similaires;
- rechercher les symboles et fonctions existants;
- vérifier les claims chevauchants;
- vérifier les branches actives;
- afficher les tentatives échouées pertinentes.

### 7.4 Ledger

Fichiers append-only :

- `decisions.jsonl`;
- `executions.jsonl`;
- `evidence.jsonl`;
- `reviews.jsonl`;
- `installations.jsonl`;
- `routing.jsonl`.

Chaque ligne contient un hash du contenu précédent.

### 7.5 Critères d'acceptation

- deux claims incompatibles sont bloqués;
- une reprise retrouve la story, la branche et le dernier état;
- une altération du ledger est détectée;
- une preuve peut être reliée au commit et à la story;
- l'état peut être exporté sans secret.

## 8. Module C — Forge IDE Adapters

Créer une interface commune :

```text
install()
uninstall()
doctor()
render_project_files()
register_hooks()
start_session()
stop_session()
capability_probe()
```

Chaque adaptateur doit déclarer ce qu'il peut réellement imposer.

### 8.1 Claude Code

Générer ou installer :

- `CLAUDE.md` court qui référence le noyau;
- agents spécialisés;
- skills/commandes nécessaires;
- hooks de démarrage, outil, compactage, arrêt et subagent;
- configuration MCP si requise;
- règles de permission compatibles.

Objectif : première tranche verticale complète.

### 8.2 Codex

Générer ou installer :

- `AGENTS.md` à la racine et instructions ciblées si supportées;
- configuration du fournisseur ou des outils Forge;
- skills/outils compatibles;
- MCP ForgeAI lorsque nécessaire;
- bootstrap de session et gates externes.

Ne pas supposer que toutes les primitives Claude existent. Les manques doivent être compensés par le CLI, Git et CI.

### 8.3 Cursor

Générer ou installer :

- règles de projet Cursor;
- référence au canon commun;
- MCP ou commandes Forge;
- déclencheurs compatibles avec le mode Agent;
- fallback externe lorsque la délégation native n'est pas disponible.

### 8.4 GitHub Copilot natif (github.com) — remplace VS Code/Copilot local

Décision Nathan (23 juillet 2026) : le quatrième adaptateur cible GitHub Copilot NATIF sur
github.com plutôt qu'une installation VS Code locale. Deux capacités distinctes du même produit,
toutes deux lisent `.github/copilot-instructions.md` :

- **Gouvernance (rôle cockpit)** : Copilot Chat sur github.com, revue de code automatique sur PR,
  suivi des checks requis et du merge queue — zéro installation locale.
- **Coding agent / cloud agent (rôle construction, optionnel)** : assignation d'une issue à
  `@copilot` déclenche un agent asynchrone (sandbox GitHub Actions) qui produit une PR. Ce N'EST
  PAS un cockpit passif — c'est un cinquième front de construction soumis aux MÊMES règles PROOF
  que les autres (story claim avant assignation, zones bornées, pipeline complet, jamais de merge
  sans le tally). L'issue assignée DOIT porter le contexte PROOF requis (story_id, tier, chemins
  autorisés) dans son corps ou via `custom_instructions`.

Générer ou installer :

- `.github/copilot-instructions.md` (repository custom instructions, lu par les deux capacités);
- gabarit d'issue pour l'assignation au coding agent (story claim + tier + chemins autorisés);
- checks requis / règles de protection de branche référençant les gates PROOF;
- pas de `.vscode/` : aucune dépendance à une installation locale pour ce front.

### 8.5 Critères d'acceptation communs

- même story et mêmes invariants dans les quatre IDE;
- adaptateurs minces, sans copie divergente de la méthode;
- installation idempotente;
- sauvegarde et restauration des fichiers existants;
- `doctor` distingue limitation IDE et erreur Forge;
- tests e2e par IDE.

## 9. Module D — Forge Superpowers

### 9.1 Stratégie

Utiliser le framework Superpowers réel.

Choisir après étude de code entre :

- fork maintenu;
- sous-module + patchs;
- package vendored + overlays;
- plugin d'extension si l'API amont est suffisante.

La décision doit privilégier :

- mise à jour amont facile;
- patchs ForgeAI isolés;
- tests de compatibilité;
- absence de divergence cachée.

### 9.2 Modifications obligatoires

- routage par rôles Forge;
- remplacement de l'auto-review par PROOF review;
- propagation des règles aux sous-agents;
- intégration au système de claims;
- context packs fournis par Context Plane;
- gates no-stub, secrets, tests, symbol sweep et preuve;
- journalisation du modèle/vendor;
- blocage si le passthrough modèle ne fonctionne pas.

### 9.3 Firing tests

Créer des tests prouvant :

- alias d'implémentation servi par le modèle attendu;
- reviewer servi par un vendor distinct;
- sous-agent connaissant les invariants applicables;
- review inline désactivée ou non reconnue comme indépendante;
- fallback journalisé;
- reprise après timeout.

## 10. Module E — Mini-Agent Router

### 10.1 Moteur de déclencheurs

Les déclencheurs sont définis dans des politiques versionnées, pas uniquement dans des descriptions en langage naturel.

Exemples de signaux :

- taille et type de changement;
- nombre de fichiers et modules;
- présence de schéma, auth, réseau ou migration;
- tier de risque;
- story marquée architecture;
- pression de contexte;
- compactage ou reprise;
- modification de documentation/canon;
- préparation de review ou `DONE`.

### 10.2 Contrats d'agents

Chaque rôle possède :

- description;
- permissions;
- entrées obligatoires;
- classes de contexte autorisées;
- outils permis;
- format de sortie;
- budget;
- timeout;
- politique de fallback;
- capacité ou non de modifier des fichiers.

### 10.3 Déclencheurs initiaux

- `context-scout` au début d'une zone inconnue;
- `architect` pour changements structurels ou T2;
- `hard-coder` pour tâche difficile ou multi-fichiers;
- `test-runner` après implémentation et avant revue;
- `drift-checker` après compactage et avant merge;
- `docs-canon` après changement fonctionnel;
- `security-reviewer` pour auth, secrets, dépendances, réseau, T2/T3;
- `evidence-synthesizer` avant `DONE`.

### 10.4 Critères d'acceptation

- un trigger obligatoire ne peut pas être ignoré silencieusement;
- l'agent reçoit seulement son context pack;
- profondeur de délégation limitée;
- budget et timeout appliqués;
- sortie invalide rejetée;
- agent non disponible produit un fallback conforme ou `BLOCKED`.

## 11. Module F — Forge Model Gateway

### 11.1 Trois backends

1. **Native** — modèle de l'IDE.
2. **Direct** — API compatible configurée par l'utilisateur.
3. **LiteLLM** — passerelle externe ou ForgeAI.

### 11.2 Rôles

Le noyau appelle seulement des alias logiques. La configuration mappe :

- provider;
- modèle;
- vendor;
- capacités;
- contexte;
- coût;
- timeout;
- fallbacks;
- statut du firing test.

### 11.3 Profil ForgeAI connecté

Alias minimum :

- `forge-architect`;
- `forge-hard-coder` → Kimi K3 dans le profil interne actuel (code compliqué);
- `forge-bulk-coder` → Kimi Code 2.7 dans le profil interne actuel (code facile/standard);
- `forge-canon-keeper` → Gemini Flash 3.6 dans le profil interne actuel (proposal_only, ne pas sous-estimer);
- `forge-sentinelle` → tandem DeepSeek V4 Pro + GLM-5.2 (contrôle continu, ne valide jamais);
- `forge-parallel` → Grok 4.5 (worktrees ; double rôle possible avec Cursor natif, voir note CIV §8.3);
- `forge-reviewer-1`;
- `forge-reviewer-2`;
- `forge-reviewer-3`;
- `forge-security`;
- `forge-evidence`.

### 11.4 Sécurité LiteLLM

- URL HTTPS vérifiée;
- clé virtuelle par poste ou IDE;
- stockage keyring/DPAPI/Keychain/Secret Service;
- jamais de clé dans Git;
- timeout et retries bornés;
- redaction des logs;
- rotation et révocation;
- modèle et vendor servis enregistrés.

### 11.5 Critères d'acceptation

- l'utilisateur interne peut se connecter en fournissant uniquement sa clé si l'URL est préconfigurée;
- l'édition autonome accepte une URL et une clé externes;
- OpenRouter et DeepInfra peuvent être décrits sans changement de code;
- l'indépendance vendor est vérifiée;
- une passerelle non compatible échoue avant toute story réelle;
- aucun secret ne figure dans une archive de diagnostic.

## 12. Module G — Forge Context Plane

### 12.1 Context classifier

Classifier chaque élément C0, C1, C2 ou C3.

La classification peut être suggérée par un modèle, mais les règles C0/C1 sont déterministes et prioritaires.

### 12.2 Context pack builder

Entrées :

- story;
- canon applicable;
- symboles et fichiers;
- décisions;
- état;
- tests;
- budget du modèle.

Sorties :

- pack versionné;
- manifeste;
- sources;
- hashes;
- exclusions;
- rapport de compression.

### 12.3 Headroom

Phase 1 : audit seulement.  
Phase 2 : filtrage C3.  
Phase 3 : préparation C2 après benchmarks.  
Phase 4 : cache et optimisations validées.

Désactiver toute mutation automatique du canon ou des fichiers d'instructions.

### 12.4 LLMLingua-2

Appliquer uniquement à C2 après classification et tests de fidélité.

Le pipeline doit refuser explicitement C0/C1.

### 12.5 Pas de double compression aveugle

Une unité de contenu porte :

- original hash;
- transformateur;
- version;
- paramètres;
- résultat hash;
- score de fidélité;
- possibilité de retrouver l'original.

### 12.6 Critères d'acceptation

- code, diff, tests et verdicts restent byte-identiques;
- un document C2 peut être compressé avec provenance;
- un log C3 répétitif est réduit;
- absence de GPU ou composant optionnel ne casse pas la session;
- compactage suivi d'une reprise conserve toutes les contraintes C0;
- le budget et la réserve sont respectés.

## 13. Module H — Documentation et canon

### 13.1 Canon keeper

Le rôle produit seulement :

- rapport de cohérence;
- diff proposé;
- références à la story et aux preuves;
- liste des contradictions.

Il ne peut pas :

- fusionner;
- modifier une règle T3;
- réécrire les invariants;
- supprimer l'historique;
- auto-approuver sa proposition.

### 13.2 Sync des adaptateurs

Les fichiers IDE sont générés depuis le canon commun. Un test détecte toute divergence manuelle.

### 13.3 Critères d'acceptation

- changement fonctionnel sans documentation requise bloque `DONE`;
- changement de canon produit une PR distincte ou clairement identifiée;
- hash de la version de méthode présent dans chaque session;
- Gemini Flash 3.6 est un mapping configurable, pas une dépendance hardcodée.

## 14. Module I — Gates, revues et preuves

### 14.1 Gates locaux

- lint/format;
- secrets;
- no-stub;
- tests ciblés;
- symbol sweep;
- scope check;
- state check;
- evidence check.

### 14.2 Review pipeline

- template neutre;
- pack identique;
- envoi parallèle;
- dépôts scellés;
- validation de schéma;
- tally par script;
- vérification des vendors;
- Delphi anonymisé si nécessaire.

### 14.3 Evidence pack

Format minimum :

```text
story.yaml
context-manifest.json
gates.json
tests.json
routing.json
reviews/*.json
diff.patch
artifacts/
proof-summary.md
manifest.sha256
```

### 14.4 Critères d'acceptation

- un `DONE` sans pack échoue;
- un verdict modifié après scellement est détecté;
- deux reviewers du même vendor échouent en PROOF-Team;
- un test déclaré mais non exécuté échoue;
- un artifact manquant invalide le manifeste.

## 15. Module J — DSPy et GEPA

### 15.1 Séparation stricte

Le laboratoire ne tourne pas automatiquement sur chaque prompt utilisateur.

Il consomme des traces expurgées et des jeux de tâches autorisés.

### 15.2 Registry des programmes

Pour chaque programme :

- nom et version;
- rôle;
- prompt ou module DSPy;
- métriques;
- données d'entraînement;
- holdout;
- coût;
- résultats;
- décision de promotion;
- version de rollback.

### 15.3 Métriques

- réussite des critères;
- faux `DONE`;
- omissions de contraintes;
- dérive de périmètre;
- exactitude des citations et preuves;
- coût et latence;
- stabilité entre modèles;
- taille de contexte;
- taux de réouverture.

### 15.4 Critères d'acceptation

- aucune promotion sans holdout;
- aucune modification automatique des invariants;
- rollback en une commande;
- benchmark reproductible;
- données sensibles exclues ou anonymisées;
- une optimisation plus économique mais moins fiable est rejetée.

## 16. Module K — CLI, installateur et maintenance

### 16.1 Commandes minimales

```text
forge install
forge init
forge session start
forge status
forge claim
forge release
forge context build
forge gate run
forge review
forge prove
forge doctor
forge repair
forge secrets set
forge config validate
forge uninstall
```

### 16.2 Installateur

- dry-run par défaut pour opérations destructives;
- manifeste de fichiers;
- sauvegardes;
- checksums;
- détection des conflits;
- rollback;
- aucune dépendance réseau non déclarée;
- support Windows, macOS et Linux.

### 16.3 Doctor

Vérifie :

- versions;
- chemins;
- hooks;
- configuration;
- keyring;
- connectivité;
- alias modèles;
- passthrough LiteLLM;
- Superpowers;
- Headroom;
- LLMLingua-2;
- état et ledger;
- adaptateurs IDE.

### 16.4 Critères d'acceptation

- installation répétée sans doublon;
- réparation sans perte de fichiers utilisateur;
- désinstallation restaure les sauvegardes applicables;
- diagnostic ne révèle aucun secret;
- erreur précise pour chaque dépendance manquante.

## 17. Phases de construction

### Phase 0 — Consolidation et recherche vérifiée

Livrables :

- validation de `VISION.md` et `FORGE_METHOD.md`;
- threat model;
- matrice de capacités réelle des quatre IDE;
- étude du code Superpowers et choix fork/overlay;
- étude d'intégration Headroom, LLMLingua-2, DSPy, GEPA et LiteLLM;
- ADR pour chaque choix majeur;
- benchmark de référence sans Forge.

Gate de sortie : aucune architecture basée sur une capacité IDE non vérifiée.

### Phase 1 — Noyau PROOF autonome

Livrables :

- schémas;
- machine d'état;
- SQLite;
- ledger;
- claims locaux;
- CLI minimal;
- config validator;
- gates déterministes;
- tests unitaires.

Gate de sortie : `DONE` impossible sans preuve dans un projet fixture.

### Phase 2 — Tranche verticale Claude Code

Livrables :

- adaptateur Claude Code;
- chargement automatique;
- mini-agents de base;
- hooks;
- préflight;
- context pack simple sans compression;
- TDD et preuve;
- e2e sur projet fixture.

Gate de sortie : fonctionnalité complète exécutée de DESIGN à DONE avec reprise de session.

### Phase 3 — LiteLLM et équipe multi-modèle

Livrables :

- stockage sécurisé de clé;
- alias de rôles;
- passthrough test;
- logs de modèle/vendor;
- Kimi K3 hard-coder (compliqué) et Kimi Code 2.7 bulk-coder (facile) sont des mappings configurables;
- Gemini Flash 3.6 canon keeper est un mapping configurable dans le profil interne;
- reviewers indépendants;
- tally script renforcé.

Gate de sortie : trois implémentations/revues de test prouvent le routage attendu et l'absence d'auto-review.

### Phase 4 — Forge Superpowers

Livrables :

- intégration du framework réel;
- patch de routage;
- propagation de règles;
- remplacement de review;
- update strategy;
- suite de compatibilité.

Gate de sortie : workflow Superpowers réel applique PROOF sans doublon de pipeline.

### Phase 5 — Context Plane

Livrables :

- classification C0-C3;
- budgets;
- Headroom audit puis filtrage C3;
- LLMLingua-2 C2;
- manifestes et hashes;
- tests de compactage/reprise.

Gate de sortie : réduction mesurée du contexte sans perte sur le jeu de fidélité.

### Phase 6 — Codex, Cursor et VS Code/Copilot

Livrables :

- trois adaptateurs;
- templates natifs;
- MCP/outils communs;
- tests e2e;
- documentation de limites.

Gate de sortie : même scénario de conformité dans les quatre IDE.

### Phase 7 — DSPy/GEPA Optimization Lab

Livrables :

- registry;
- datasets;
- métriques;
- pipeline candidate/holdout/canary;
- rollback;
- premier prompt optimisé et prouvé.

Gate de sortie : une amélioration promue sans changer les invariants ni augmenter les faux `DONE`.

### Phase 8 — Mode connecté avancé

Livrables optionnels :

- claims atomiques multi-PC;
- Postgres;
- dashboards;
- budgets centralisés;
- politiques organisationnelles;
- intégration ForgeAI Toolkit.

Cette phase ne bloque pas la version autonome.

## 18. Matrice de tests obligatoire

### 18.1 Systèmes

- Windows;
- macOS;
- Linux.

### 18.2 IDE

- Claude Code;
- Codex;
- Cursor;
- GitHub Copilot natif (github.com — cockpit + coding agent optionnel).

### 18.3 Modes

- native;
- autonome direct;
- LiteLLM externe;
- LiteLLM ForgeAI.

### 18.4 Scénarios de panne

- compactage en milieu de story;
- redémarrage IDE;
- panne réseau;
- timeout modèle;
- modèle incorrect derrière un alias;
- reviewer même vendor;
- claim concurrent;
- branche incorrecte;
- fichier hors périmètre;
- TODO/stub;
- test sans assertion;
- fuite de secret;
- ledger altéré;
- canon divergent;
- Headroom indisponible;
- LLMLingua sans GPU;
- Superpowers upstream incompatible;
- clé révoquée;
- budget dépassé.

### 18.5 Tests anti-dérive longue durée

Créer des scénarios multi-session où :

- la conversation est compactée plusieurs fois;
- les IDE sont alternés;
- des tentatives échouent;
- une décision change;
- plusieurs agents cherchent à toucher le même module;
- la documentation doit suivre le code.

Mesurer : oublis, duplications, rework, faux `DONE`, coût et contexte utilisé.

## 19. Threat model minimal

Menaces :

- prompt injection dans documentation ou sortie d'outil;
- exfiltration de clés;
- contournement de hooks;
- alias LiteLLM mal routé;
- falsification de preuve;
- reviewer collusif ou même vendor;
- fichier d'instruction IDE modifié;
- dépendance amont compromise;
- compression supprimant une contrainte;
- données sensibles envoyées à un fournisseur non autorisé;
- update automatique non audité.

Contrôles :

- classification des sources;
- allowlists d'outils et de destinations;
- secret scanning;
- signatures/checksums;
- pinning;
- sandbox;
- logs de routage;
- comparaison de vendor;
- packs non compressés pour review;
- mises à jour par PR;
- fail-closed.

## 20. Observabilité et vie privée

- logs structurés locaux par défaut;
- télémétrie distante désactivée par défaut dans l'édition autonome;
- aucune collecte de code sans consentement explicite;
- redaction des secrets;
- identifiants de trace corrélables sans exposer le contenu;
- export de diagnostic contrôlé;
- politique de rétention configurable.

## 21. Compatibilité ECC

ECC peut servir de source de composants ou de référence pour :

- packaging multi-IDE;
- doctor/repair/uninstall;
- hooks et sécurité;
- ergonomie d'installation.

Il ne devient pas :

- le canon;
- l'orchestrateur;
- la mémoire officielle;
- un second pipeline TDD;
- une dépendance obligatoire.

Tout code repris est isolé, audité, versionné et conforme à sa licence.

## 22. Décisions humaines à prendre avant la Phase 1

1. nom final du produit;
2. licence de l'édition autonome;
3. fork ou overlay Superpowers;
4. langage principal proposé Python 3.12+;
5. télémétrie par défaut;
6. URL LiteLLM intégrée à l'édition interne;
7. liste initiale des modèles et vendors;
8. politique de mise à jour automatique ou manuelle;
9. niveau de compatibilité Windows requis dès v1;
10. service de claims connecté inclus ou reporté.

## 23. Définition de la v1

La v1 est terminée uniquement lorsque :

- les quatre adaptateurs sont installables;
- la méthode se charge automatiquement;
- une story complète peut être conçue, réclamée, exécutée, testée, revue et prouvée;
- le contexte critique survit à une reprise;
- le mode autonome fonctionne sans ForgeAI;
- le mode connecté fonctionne avec une clé virtuelle LiteLLM;
- Kimi K3, Kimi Code 2.7 et Gemini Flash 3.6 sont des mappings configurables dans le profil interne;
- Superpowers réel est intégré et testé;
- Headroom et LLMLingua-2 respectent les classes de contexte;
- DSPy/GEPA disposent d'un pipeline de promotion sécurisé;
- les pannes principales produisent `BLOCKED`, jamais un faux succès;
- l'installateur, doctor, repair et uninstall passent les tests cross-platform définis.

---

**Règle d'implémentation :** construire d'abord la plus petite tranche verticale qui prouve l'ensemble de la méthode. Ne pas paralléliser les adaptateurs avant que le noyau et Claude Code soient réellement démontrés de bout en bout.
