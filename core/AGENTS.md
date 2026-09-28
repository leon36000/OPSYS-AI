# AGENTS.md — OPSYS-CORE (`core/`)

Ce dossier contient OPSYS-CORE, un fork dur d'OpenClaw v2026.9.6 (ADR-0008). Pour sa provenance et
son contrat de configuration, voir `PROVENANCE.md`. Ces règles s'ajoutent à celles du dépôt.

## Ordre d'autorité

1. **Le `AGENTS.md` de la racine du dépôt.**
   - Il fixe le produit, la preuve avant DONE et les frontières humaines T3.
   - Il interdit les stubs, les TODO et les secrets.
   - Il fixe les commits en français.
2. **La définition du produit** (`docs/produit/DEFINITION-PRODUIT.md`). Elle remplace `VISION.md`,
   qui ne décrit que la vision historique d'OpenClaw.
3. **Ce fichier.**
4. **Les `AGENTS.md` des sous-dossiers.** Ce sont des guides techniques hérités de l'amont, en
   anglais. Ils valent pour les conventions de leur zone, sauf s'ils contredisent ce qui précède.
   - Leurs renvois vers `docs/`, `apps/`, `.agents/` ou les workflows de mainteneurs d'OpenClaw
     sont caducs, car ces chemins sont élagués. Le code source et ses tests font foi.
   - Les processus propres à l'amont ne s'appliquent pas : Night Watch, Testbox, Convex, Daybreak,
     releases npm d'OpenClaw, règle « pas de trailer d'attribution ».

## Exécution

- **Le bac à sable de développement n'exécute pas le code du core** : ni `pnpm install`, ni
  construction, ni tests. La raison : `pnpm install` lance des scripts de paquets tiers.
  - La preuve vient de la CI `.github/workflows/core.yml` (Node 24, pnpm de `packageManager`).
  - Lire le code, `rg` et les outils Python sans exécution restent permis.
- **Lockfile** : on le régénère sans script de paquet, avec
  `pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile`.
- **Dépendances** : un ajout ou une mise à jour passe les contrôles de chaîne d'approvisionnement
  de `pnpm-workspace.yaml` et s'inscrit dans `docs/research/INGREDIENTS.md`.

## Langue et marque

- **Code** : les identifiants et les commentaires restent en anglais, pour garder la base homogène.
- **Textes vus par l'utilisateur** : ils passent par l'i18n, avec fr-CA comme langue par défaut
  d'OPSYS.
- **Marque visible** : OPSYS.
- **Identifiants internes** : paquet `openclaw`, imports `openclaw/plugin-sdk/*`, variables
  `OPENCLAW_*`, dossier `~/.openclaw`, clés de config.
  - Ils changent seulement par le renommage planifié (PLAN T0.7), avec migration Doctor et CI
    verte.
  - Jamais par renommage partiel à la main.

## Règles d'ingénierie conservées de l'amont

- **Un propriétaire par responsabilité.** Les appelants consomment ses opérations. Une migration
  bascule tous les appelants ensemble et retire l'ancien chemin.
- **Choisir la surface de capacité dans l'ordre suivant :**
  1. étendre un propriétaire existant ;
  2. utiliser un contrat de plugin existant, idéalement une extension dans `extensions/` ;
  3. créer une capacité générique étroite dans le core ou le SDK ;
  4. en dernier recours, ajouter une surface universelle au core.

  Les greffes OPSYS (moteur de contexte, mémoire d'entreprise, connecteur du moteur métier) sont
  d'abord des extensions.
- **Plugins** : ils passent par les contrats `openclaw/plugin-sdk/*` et leur manifeste, jamais par
  les internes du core ni par les fichiers privés d'un autre plugin.
- **État et caches** :
  - ils vivent dans SQLite (Kysely ; SQL brut seulement pour les schémas, migrations et primitives
    justifiées), jamais dans de nouveaux fichiers JSON/JSONL ;
  - les transactions d'écriture sont synchrones, sans `await` dans le rappel ;
  - l'accès à la base se fait dans des workers, jamais sur le fil principal de la Gateway.
- **Config** : un changement qui invalide une config existante vient avec sa migration Doctor.
- **Actions privilégiées** : on revalide l'autorité juste avant l'effet de bord. Un jeton ou un
  identifiant seul ne prouve pas une autorité vivante.
- **TypeScript** : ESM strict, pas de `@ts-nocheck`, pas de cast pour faire taire l'analyse
  statique. On ne modifie pas `node_modules` ni les artefacts générés à la main.
- **Tests** : ils protègent un comportement observable. Pas de minuterie réelle, de `sleep` ni
  d'attente active. Un échec est un défaut à comprendre, jamais une relance « pour voir vert ».
- **Mises à jour** : elles doivent toujours réussir. Toute modification de la mise à jour, de
  Doctor, du cycle de vie du service ou des migrations dit comment elle se comporte sur une
  installation existante.
