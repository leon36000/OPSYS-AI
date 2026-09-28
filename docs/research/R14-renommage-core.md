# R14 — Renommage OpenClaw → OPSYS dans le core (mesure et découpage)

- Date : 2026-09-28.
- Mesure faite en lecture seule sur `core/`, sans exécuter de code, par un agent de recherche.
- Les décisions ci-dessous sont de l'ingénieur en chef. Elles servent de base à la tâche T0.7 du
  plan.

## Mesures

| Surface | Constat | Où |
|---|---|---|
| Marque dans l'interface | Titre, manifeste PWA, écran de secours, environ 90 chaînes dans la locale anglaise | `ui/index.html`, `ui/public/manifest.webmanifest`, `ui/src/i18n/locales/en*.ts` |
| Locales | 21 locales. **`fr` traduite à 100 %** (9 840 clés sur 9 840) ; aucune `fr-CA` | `ui/src/i18n/.i18n/fr.meta.json` |
| Glossaires de traduction | Épinglent `OpenClaw → OpenClaw` dans chaque langue ; sans correction, le pipeline réinjecte la marque | `ui/src/i18n/.i18n/glossary.*.json` |
| Invites système | Une dizaine d'invites commencent par « You are OpenClaw… » ou « running inside OpenClaw » | `src/system-agent/assistant-prompts.ts`, `src/agents/system-prompt.ts`, `src/gateway/talk/session-config.ts`… |
| CLI | `CLI_NAME = "openclaw"` en un seul endroit ; bannière `--version`, slogans ; 4 `process.title` en dur | `src/cli/cli-name.ts:2`, `openclaw.mjs:452`, `src/cli/tagline.ts` |
| Dossier d'état | `.openclaw`, surchargé par `OPENCLAW_STATE_DIR` et `OPENCLAW_HOME` ; fichier `openclaw.json` en une seule constante | `src/config/state-dir.ts`, `src/config/paths.ts:32` |
| Migration Doctor | **Existe déjà** : `.clawdbot → .openclaw` (déplacement, lien de compatibilité, retour arrière) | `src/infra/state-migrations.state-dir.ts` |
| Services | Noms centralisés (`openclaw-gateway`, `ai.openclaw.gateway`…), avec une liste d'anciens noms déjà en place | `src/daemon/constants.ts` |
| Identifiants internes | Environ 3 452 fichiers importent `openclaw/plugin-sdk/*` ; 59 paquets `@openclaw/*` ; 491 variables `OPENCLAW_*` ; 44 manifestes `openclaw.plugin.json`, dont le nom est dupliqué une quinzaine de fois | `package.json`, `tsconfig.json`, `config/env-var-count-budget.txt` |
| Tests qui figent la marque | 539 assertions dans 282 fichiers | `rg "OpenClaw"` sur les assertions |

## Décisions

1. **Aucun renommage dans les fichiers de licence et de provenance.**
   - Fichiers concernés : `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` et `PROVENANCE.md`.
   - Raison : obligation MIT et avis de marque.
2. **On renomme ce que voit l'utilisateur, jamais l'API interne du fork.**
   - Restent tels quels : les imports `openclaw/plugin-sdk/*`, les paquets `@openclaw/*`, les
     variables `OPENCLAW_*` et le nom de fichier `openclaw.plugin.json`.
   - Raisons :
     - aucun utilisateur ne les voit ;
     - les renommer touche plus de 3 400 fichiers pour aucun bénéfice produit ;
     - chaque correctif de sécurité porté depuis l'amont deviendrait plus difficile à appliquer.
   - L'installateur et le superviseur d'OPSYS règlent les variables `OPENCLAW_*` eux-mêmes.
3. **Une seule commande `opsys`, qui est celle du core.**
   - Le core porte le produit : Gateway, canaux, agents, accueil, mises à jour.
   - Le CLI Python actuel (`opsys verifier`, `opsys base…`) devient `opsys metier <commande>`. La
     commande `metier` est ajoutée au core et lance le moteur métier par `uv` (T0.10).
   - Le point d'entrée Python est renommé `opsys-metier`.
   - Pendant la transition, `openclaw` reste un alias du binaire.
4. **Un seul dossier d'instance, `OPSYS_HOME` (`~/.opsys`).**
   - Le core y garde son état dans `core/`, placé par `OPENCLAW_STATE_DIR`.
   - La base métier reste `opsys.db` à la racine de ce dossier.
   - Le fichier de configuration devient `opsys.json`. `openclaw.json` passe dans la liste des
     anciens noms, que le mécanisme existant sait déjà relire.
   - Une migration Doctor de `~/.openclaw` n'est utile que pour un poste qui faisait déjà tourner
     OpenClaw. On réutilise pour cela `autoMigrateLegacyStateDir`.
5. **Langue par défaut : fr-CA.**
   - La locale `fr-CA` est dérivée de `fr` : on n'ajuste que les écarts propres au Québec.
   - Les glossaires épinglent `OPSYS`.

## Découpage de T0.7, du plus sûr au plus risqué

Chaque lot se livre avec la CI du core au vert, et les assertions de marque mises à jour dans le
même commit.

| Lot | Contenu | Migration | Risque |
|---|---|---|---|
| 1 | Marque visible : interface, locales et glossaires, `fr-CA`, bannière et slogans, invites système, nom de découverte, titre des notifications, `og:site_name` | aucune | 539 assertions à mettre à jour ; aucun risque d'installation |
| 2 | Commande `opsys` (et alias `openclaw`), `process.title`, commande `metier` | aucune | scripts qui appellent `openclaw` : l'alias les couvre |
| 3 | Dossier d'instance et `opsys.json`, anciens noms relus | Doctor (mécanisme existant) | installations existantes : le lien de compatibilité et le retour arrière existent déjà |
| 4 | Services système (`opsys-gateway`, `ai.opsys.gateway`), anciens noms nettoyés par la liste existante | Doctor | identifiants dispersés hors de `src/daemon/constants.ts` : à traiter à la main |

Les scripts d'applications natives (iOS, Android, macOS) restés dans `scripts/` sont orphelins
depuis le retrait de `apps/`. On les supprime avec T0.6 au lieu de les renommer.
