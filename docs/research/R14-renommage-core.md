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

## Addendum du lot 3 : le dossier d'instance (décisions de l'agent du lot)

Écrit avec le lot 3 (T0.7). Ces décisions précisent la décision 4 ; celles qui s'en écartent sont dites telles. Preuve et
détail : `core/PROVENANCE.md` (« Renommage, lot 3 »), `docs/exploitation/INSTALLATION.md`.

| # | Décision | Pourquoi |
|---|---|---|
| 3.1 | L'état du core du profil `opsys` est `~/.opsys/core` (le dossier personnel du **compte**, pas `OPSYS_HOME`). | Le core ne lit pas `OPSYS_HOME`, et la définition du service, qui ne la porte pas, doit désigner le même dossier que la CLI. Avec l'`OPSYS_HOME` par défaut, c'est bien « un seul dossier d'instance » ; avec un `OPSYS_HOME` personnalisé, les données métier sont ailleurs et le moteur Python l'avertit. **Nuance à R14** : `OPSYS_HOME` n'est PAS déplacé (les données restent où elles sont), et le core n'y est pas placé par `OPENCLAW_STATE_DIR` mais par le profil (`isDefaultInstallIdentity` refuse tout service pour un état posé à la main). |
| 3.2 | `opsys.json` est le nom canonique de la configuration **du profil `opsys`** ; `openclaw.json` reste lu et n'est jamais renommé par Doctor. | Le service installé nomme son fichier de configuration : le renommer avant la réinstallation du service le ferait démarrer sans configuration. Le renommage est laissé au lot 4, qui réécrit les services. **Écart à R14** : R14 disait « le fichier devient `opsys.json` » pour tout le core. Le nom `openclaw.json` est resté celui du profil par défaut, des autres profils et de Docker : 752 fichiers de tests (1 960 occurrences) l'écrivent ou le lisent, que le bac à sable ne peut pas rejouer ; un renommage global se fait avec la CI sous les yeux, en son propre lot. |
| 3.3 | Tant que seul l'ancien dossier (`~/.openclaw-opsys`) porte un état, le core l'utilise en place ; Doctor le déplace ensuite. | Même repli que `.clawdbot` vers `.openclaw`. Sans lui, une commande lancée avant la migration créerait un second état, et le service encore lancé sur l'ancien chemin ne parlerait plus du même état que la CLI. |
| 3.4 | La migration DÉPLACE (un `rename`), laisse un lien à l'ancien chemin, vérifie, s'arrête sur un conflit (ancien ET nouveau non vides), et ne supprime jamais. | Copier créerait deux états ; supprimer l'ancien est une décision humaine (frontière T3). Le lien fait marcher un service installé avant le lot jusqu'à sa réinstallation. |
| 3.5 | Le moteur Python REFUSE d'écrire tant que l'ancien état existe, avec la marche à suivre (`opsys doctor --non-interactive`, puis relancer l'installateur). Il ne migre pas lui-même. | Le mécanisme de migration est celui de Doctor, dans le core ; une seconde implémentation, en Python, serait un second mécanisme à tenir d'accord. |
| 3.6 | Le nom du service ne change pas (lot 4). | Découpage de R14. |

**Laissé au propriétaire.** (a) Le renommage global du fichier de configuration (`openclaw.json` -> `opsys.json` pour tout le core) :
il demande un lot avec la CI sous les yeux. (b) Faut-il faire suivre `OPSYS_HOME` au dossier d'état du core ? Cela exigerait que le
core lise `OPSYS_HOME` ET que le service la porte ; le lot ne le fait pas. (c) L'ordre des lots 3 et 4 pour les postes qui portent
déjà un service : le lien de compatibilité les couvre jusqu'à la réinstallation.
