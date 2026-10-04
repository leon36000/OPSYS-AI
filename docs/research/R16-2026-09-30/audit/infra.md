# Audit infrastructure — HEAD récent — 2026-09-30

Cible : `/workspace/OPSYS-AI-recent`, commit **`2e56c0d5605dfe575bde9244f38924d5390f2674`**, branche `claude/opsys-ai-analysis-x4jt87`. Dépôt propre au début et à la fin des lectures. Aucun fichier du dépôt modifié, aucune installation réelle, aucun déploiement, aucune suppression réelle de données. Les reproductions emploient des fixtures externes fictives et une fausse commande Docker ; la désinstallation est exécutée exclusivement avec `--simuler`.

**Verdict : échec des garanties de reprise et de conservation des données.** La restauration annoncée comme réussie ignore les cinq volumes sauvegardés ; la garde de désinstallation accepte deux chemins qui désignent les données protégées ; le contexte Docker peut embarquer des sauvegardes et des secrets locaux. Le HEAD n'a pas de CI globale verte : `socle` a dépassé son délai de 20 minutes et `gates` a échoué. Les points ci-dessous distinguent comportements reproduits, constats de source et conditions d'exposition.

Autorité lue : [AGENTS.md](../../../../AGENTS.md), [core/AGENTS.md](../../../../core/AGENTS.md). L'interdiction d'exécuter le core est respectée : aucune installation pnpm, construction, suite core ou bibliothèque applicative du core exécutée. Le lock a seulement été lu par Python. Méthode : skill `code-verification`.

## Constats classés

### INFRA-R01 — P1 — La restauration ne lit aucune des cinq archives de volumes produites par la sauvegarde

**Confiance élevée ; reproduit.** [backup.sh:59](../../../../deploy/backup.sh#L59) fabrique `volume-${1}.tar.gz` avec un argument déjà préfixé, par exemple `deploy_opsys_data` ([l.74](../../../../deploy/backup.sh#L74)). [restore.sh:78](../../../../deploy/restore.sh#L78) cherche `volume-opsys_data.tar.gz`, sans ce préfixe. Les cinq noms ne correspondent pas.

**Précondition :** utiliser les deux scripts tels quels, avec leur nom de projet par défaut et une sauvegarde complète produite par `backup.sh`. La reproduction sauvegarde cinq volumes fictifs puis appelle la copie exacte de `restore.sh`, avec Docker remplacé par une commande factice. La sauvegarde produit les cinq archives préfixées ; la restauration émet cinq avertissements, n'exécute aucune extraction, retourne **0**, et affiche « PREUVE : restauration … terminée ».

**Conséquence :** les bases sont remplacées mais l'état des volumes, les configurations, les secrets d'authentification et les certificats ne sont pas restaurés. Sur une machine neuve ils manquent ; sur une machine existante ils restent anciens. Le succès annoncé masque une reprise partielle. **Direction minimale :** définir un format commun d'archive et vérifier tous les éléments requis avant d'arrêter ou d'écraser quoi que ce soit.

Preuves : deploy_results.json (`archive:infra/recent/deploy_results.json`), clés `backup_present` et `restore_after_backup`, repro_deploy.py (`archive:infra/recent/repro_deploy.py`). Les empreintes des deux copies de scripts ont été comparées aux sources du HEAD dans restore-empty-results.json (`archive:infra/recent/restore-empty-results.json`). **Limite :** aucune restauration PostgreSQL/Docker réelle ; la preuve porte sur les noms, les branches exécutées et le code de retour.

### INFRA-R02 — P1 — La garde de désinstallation compare les chemins textuels, sans résoudre `..` ni les liens intermédiaires

**Confiance élevée ; décision de suppression reproduite en simulation.** [uninstall.sh:123](../../../../install/uninstall.sh#L123) compare les chaînes de chemins. La suppression réelle serait un `rm -rf -- "$dossier"` ([l.149](../../../../install/uninstall.sh#L149)).

**Préconditions :** chemins personnalisés incohérents ou passant par un alias/lien ; droits de suppression de l'utilisateur. Cas 1 : `OPSYS_LOGICIEL=/fixture/alias/../software`, `OPSYS_HOME=/fixture/software/venv`. Cas 2 : `OPSYS_LOGICIEL=/fixture/linked-software`, lien intermédiaire vers `/fixture/software`, même `OPSYS_HOME`. Dans les deux cas, le script autorise « suppression de …/venv », rc **0**, tandis que `Path(...).resolve()` établit que cette cible est exactement le dossier de données protégé. L'annonce finale affirme que les données sont conservées.

**Conséquence :** un usage sans `--simuler` peut supprimer la base de l'instance et ses fichiers au lieu de seulement retirer le logiciel. **Direction minimale :** résoudre les chemins des deux côtés avant les tests de contenance, contrôler les composants symboliques et conserver la vérification juste avant l'effet de bord.

Preuves : guard_results.json (`archive:infra/recent/guard_results.json`), repro_guard.py (`archive:infra/recent/repro_guard.py`). **Limites :** aucune donnée réellement supprimée, uniquement fixtures fictives et `--simuler`. Ce constat est confirmé pour Bash/Linux ; les effets des jonctions et reparse points Windows n'ont pas été exécutés. La version PowerShell normalise lexicalement avec `GetFullPath` ([uninstall.ps1:112](../../../../install/uninstall.ps1#L112)), ce qui traite `..`, mais ne constitue pas une preuve de résolution physique des liens Windows.

### INFRA-R03 — P1 — Le contexte Docker peut embarquer sauvegardes et secrets locaux dans l'image

**Confiance élevée sur la règle de copie ; exposition conditionnelle, aucun secret réel observé.** [Dockerfile:37](../../../../deploy/Dockerfile#L37) fait `COPY . /opt/opsys`. [.dockerignore:10](../../../../.dockerignore#L10) exclut uniquement `deploy/.env` et `deploy/**/*.env` pour les secrets. Il n'exclut ni `.env` à la racine, ni `core/.env`, ni `.forge/secrets/`, ni `deploy/backups/`. Les exclusions de `.gitignore` ne s'appliquent pas au contexte Docker.

**Précondition concrète :** construire depuis un checkout contenant ces fichiers locaux. En particulier, `backup.sh` écrit **par défaut dans `deploy/backups/`** ([l.15](../../../../deploy/backup.sh#L15)) ; reconstruire ensuite l'image depuis ce même checkout inclut les dumps SQL et l'archive `openclaw_auth_secrets`. Le contexte est la racine du dépôt ([docker-compose.yml:102](../../../../deploy/docker-compose.yml#L102)).

**Conséquence :** renseignements d'entreprise et secrets conservés dans les couches d'image et potentiellement transmis au builder ou au registre utilisés par l'opérateur. **Direction minimale :** exclure les données/sauvegardes et les formes de secrets dans `.dockerignore`, puis limiter les sources copiées. **Limite :** constat de source, sans build Docker ni publication d'image, et aucune fuite de clé de production démontrée.

Preuve regroupée : supply-results.json (`archive:infra/recent/supply-results.json`), copie et empreinte de `.dockerignore`, instruction COPY et exemples de chemins non exclus.

### INFRA-R04 — P2 — Sauvegarde et restauration tolèrent l'absence de données requises et annoncent encore un succès complet

**Confiance élevée ; reproduit.** [backup.sh:61](../../../../deploy/backup.sh#L61) avertit puis `return` si un volume manque, sans positionner `FAIL=1`. Le manifeste continue à annoncer les cinq volumes et la branche finale affiche « complète et sans erreur ». Une reproduction avec les **cinq volumes absents** produit seulement les deux dumps et le manifeste, rc **0**.

[restore.sh:59](../../../../deploy/restore.sh#L59) et [l.79](../../../../deploy/restore.sh#L79) ignorent pareillement les bases/volumes absents. Une nouvelle reproduction avec un dossier contenant **uniquement un manifeste fictif** ignore les deux bases et les cinq volumes, puis affiche une restauration terminée, rc **0**. Le contenu du manifeste n'est pas validé. Ce défaut est distinct du mauvais nom d'archive de R01.

**Préconditions :** volume non trouvé/non lisible depuis l'hôte, nom de projet Compose différent, ou jeu de sauvegarde incomplet. Les scripts calculent le préfixe depuis le nom du dossier plutôt que depuis le projet Compose effectif ; un `COMPOSE_PROJECT_NAME` personnalisé augmente notamment le risque de volumes non trouvés. **Conséquence :** suivi automatisé et opérateur peuvent accepter une sauvegarde/reprise sans données attendues ; la purge locale reste exécutée. **Direction minimale :** inventaire vérifié, erreur non nulle pour tout élément requis manquant, contrôle préalable complet à la restauration.

Preuves : `backup_missing` dans deploy_results.json (`archive:infra/recent/deploy_results.json`), restore-empty-results.json (`archive:infra/recent/restore-empty-results.json`). **Observation de source supplémentaire :** `RESTIC_REPOSITORY` défini avec `restic` absent produit aussi seulement un avertissement, sans `FAIL=1` ([backup.sh:111](../../../../deploy/backup.sh#L111)). Cette branche distante n'a pas été reproduite ; aucun dépôt restic réel contacté.

### INFRA-R05 — P2 — L'installation VPS neuve exige un `.env.example` absent du dépôt

**Confiance élevée ; absence vérifiée, ordre d'échec établi par source.** `deploy/.env.example` n'existe pas au HEAD et `git ls-files deploy/.env.example` est vide. [install.sh:109](../../../../deploy/install.sh#L109) tente de le copier en l'absence de `.env`. Les étapes Docker et création de l'utilisateur sont appelées **avant** cette copie ([l.262](../../../../deploy/install.sh#L262)). La procédure publiée exige également `cp .env.example .env` ([INSTALLATION-VPS.md:45](../../../ops/INSTALLATION-VPS.md#L45)). `.gitignore` ignore `.env*` sans exception pour le modèle deploy ; le modèle core est suivi séparément.

**Précondition :** checkout neuf, sans `.env` déjà préparé. **Conséquence :** procédure documentée impossible telle quelle ; un lancement direct du script peut échouer après installation de paquets/activation Docker et création d'un compte. **Direction minimale :** livrer un modèle exploitable et vérifier sa présence avant toute mutation système. **Limite :** aucun installateur root réellement exécuté ; les mutations précédentes sont établies par l'ordre des appels, pas par une installation destructive.

Preuves : clé `missing_template` dans deploy_results.json (`archive:infra/recent/deploy_results.json`), [.gitignore:18](../../../../.gitignore#L18).

### INFRA-R06 — P2 — Les sauvegardes locales héritent de permissions potentiellement publiques aux utilisateurs de l'hôte

**Confiance élevée ; modes reproduits.** [backup.sh:38](../../../../deploy/backup.sh#L38) crée le dossier sans permissions privées et le script ne fixe pas d'umask/chmod pour les dumps et archives. Avec l'umask courant **022**, les fichiers sont **0644**, et le dossier daté **0755**, y compris l'archive d'authentification. Cela concerne aussi les dumps contenant des renseignements personnels.

**Précondition d'exposition :** les répertoires parents du chemin de sortie sont traversables par les autres utilisateurs ; droits ordinaires de lecture sur l'hôte. **Conséquence :** lecture locale non autorisée des sauvegardes. **Direction minimale :** umask privé avant création, dossier privé et contrôle des permissions des fichiers existants.

Preuves : `backup_present.modes` dans deploy_results.json (`archive:infra/recent/deploy_results.json`) et `directory_modes` dans restore-empty-results.json (`archive:infra/recent/restore-empty-results.json`). **Limite importante :** le répertoire parent de la fixture d'audit est lui-même privé (0700) ; la reproduction prouve les modes créés par le script, pas une lecture de données par un autre compte.

### INFRA-R07 — P2 — Le gate principal couvre seulement la CI Python ; le HEAD échoue par dépassement du délai du socle

**Confiance élevée sur les workflows et l'état exact du HEAD ; protection effective de branche non vérifiable.** [ci.yml:172](../../../../.github/workflows/ci.yml#L172) dépend de `socle`, `departement` et `m03-preuves`. Il ne dépend pas de `core`, `mobile`, `installateur` ou `e2e-core`, qui sont des workflows séparés, filtrés par chemins. Un succès de ce gate ne suffit donc pas à établir la réussite de ces autres surfaces. Le workflow mobile possède également un job nommé `gates` ([mobile.yml:24](../../../../.github/workflows/mobile.yml#L24)) : la configuration de la protection doit être inspectée pour savoir précisément quels contrôles elle exige, sans déduire un contournement effectif du seul nom partagé.

**Preuve exacte du HEAD :** 22 jobs observés : dix départements et dix jobs de preuve M3 réussis, `socle` annulé, `gates` en échec. Les annotations GitHub disent explicitement **« The job has exceeded the maximum execution time of 20m0s »**. `socle` dure 20 min 15 s ; l'installation, le lint et `opsys-metier verifier` réussissent ; `pytest` est interrompu. Le délai configuré est 20 minutes ([ci.yml:22](../../../../.github/workflows/ci.yml#L22)). Il s'agit d'un timeout confirmé, pas d'une annulation utilisateur supposée. Le gate refuse correctement le résultat incomplet.

**Conséquence :** absence de preuve CI verte sur le HEAD et couverture de release incomplète si seul le gate Python est requis. **Direction minimale :** rendre explicites les checks requis de toutes les surfaces applicables, avec noms non ambigus, et dimensionner/découper la suite socle pour qu'elle termine. **Limites :** API de protection `main` : **403, Resource not accessible by integration** ; on ne peut pas attester les exigences effectives ni conclure qu'elles sont désactivées. Le téléchargement du journal détaillé socle est refusé par le stockage Azure ; les étapes et annotations API sont accessibles.

Preuves : checks-head.json (`archive:historique/checks-head.json`), socle-job.txt (`archive:infra/recent/socle-job.txt`), socle-annotations.json (`archive:infra/recent/socle-annotations.json`), protection-main.json (`archive:historique/protection-main.json`).

### INFRA-R08 — P2 — Les locks contiennent des versions visées par des avis de sécurité actuels ; les workflows ne lancent pas d'audit de dépendances

**Confiance élevée sur les versions et les avis du registre ; exploitabilité OPSYS non démontrée.** Une requête de métadonnées npm a été exécutée le 2026-09-30, sans installation ni code du core : lecture Python des **deux documents** de `core/pnpm-lock.yaml`, 1 413 noms / 1 542 versions, puis POST vers l'API publique d'avis npm, HTTP **200**. Dix avis visent quatre paquets verrouillés :

| Paquet core | Version | Avis du registre | Chemin établi dans le lock |
|---|---:|---|---|
| `brace-expansion` | 5.0.9 | 2 high : [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7), [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p) ; 1 moderate : [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) | dépendance production racine `minimatch` → `brace-expansion` |
| `fast-uri` | 4.1.4 | 2 moderate : [GHSA-hrr3-gc8f-f4qj](https://github.com/advisories/GHSA-hrr3-gc8f-f4qj), [GHSA-jvvf-x445-j334](https://github.com/advisories/GHSA-jvvf-x445-j334) | SDK MCP → `ajv` → `fast-uri` |
| `ip-address` | 10.7.0 | 2 moderate : [GHSA-j6r3-76f7-8jcv](https://github.com/advisories/GHSA-j6r3-76f7-8jcv), [GHSA-h3mg-xc3c-68pw](https://github.com/advisories/GHSA-h3mg-xc3c-68pw) | SDK MCP → `express-rate-limit` → `ip-address` |
| `joi` | 18.2.3 | 1 high : [GHSA-6h2x-m376-mqjq](https://github.com/advisories/GHSA-6h2x-m376-mqjq) ; 2 low : [GHSA-6w3j-5fw6-r9vr](https://github.com/advisories/GHSA-6w3j-5fw6-r9vr), [GHSA-gg4h-3hg2-grpc](https://github.com/advisories/GHSA-gg4h-3hg2-grpc) | extension IMAP → `mailauth` → `joi` |

Les trois premiers ont des overrides explicites dans [pnpm-lock.yaml:179](../../../../core/pnpm-lock.yaml#L179) et [pnpm-workspace.yaml:67](../../../../core/pnpm-workspace.yaml#L67). Les versions appartiennent aux plages vulnérables renvoyées. La présence en production dans le graphe n'établit pas que les API vulnérables reçoivent un input attaquant : les avis décrivent surtout des dénis de service, ainsi que normalisation d'hôte, injection mailto, contenance IP et pollution de prototype, avec leurs préconditions propres.

Une copie externe du lock mobile, contrôlée par `npm audit --package-lock-only --ignore-scripts --json`, retourne **1**, avec **13 paquets signalés moderate, 0 high, 0 critical**. Cela représente **deux avis racines**, propagés au graphe Expo : `decode-uri-component@0.2.2` ([GHSA-vcc3-ghjq-m6fr](https://github.com/advisories/GHSA-vcc3-ghjq-m6fr), via `expo-router` → `query-string`) et `uuid@7.0.3` ([GHSA-w5hq-g745-h8pq](https://github.com/advisories/GHSA-w5hq-g745-h8pq), notamment via `xcode`/outillage Expo). Les suggestions automatiques de rétrogradation majeure d'Expo ne sont pas validées comme remédiation.

**Préconditions d'impact :** emploi d'une fonction concernée avec une entrée déclenchant l'avis ; pour IMAP, extension utilisée ; pour l'outillage Expo, contexte de développement/construction concerné. **Direction minimale :** triage de chaque chemin/API, mises à jour contrôlées et scan régulier en CI. Le hook manuel `pnpm-audit-prod` existe sous `core/.pre-commit-config.yaml`, mais les cinq workflows de la racine ne l'exécutent pas. Aucune configuration Dependabot/Renovate suivie n'a été trouvée ; cela ne prouve pas l'absence d'un service externe de veille.

Preuves : core-npm-bulk.json (`archive:infra/recent/core-npm-bulk.json`), audit_core_metadata.py (`archive:infra/recent/audit_core_metadata.py`), core-audit-paths.json (`archive:infra/recent/core-audit-paths.json`), mobile-npm-audit.json (`archive:infra/recent/mobile-npm-audit.json`). **Limites :** métadonnées du registre au moment de la requête, pas un test d'exploitation, pas un audit exhaustif Python ou images conteneurs ; aucun paquet téléchargé/exécuté pour le core, aucune dépendance installée pour le mobile.

### INFRA-R09 — P2 — Le moteur Python et les outils de construction ne sont pas verrouillés de façon reproductible

**Confiance élevée ; constat de source.** Le dépôt suit uniquement `core/pnpm-lock.yaml` et `mobile/package-lock.json` parmi les formats de lock/requirements recherchés. [pyproject.toml:11](../../../../pyproject.toml#L11) conserve des plages pour PyYAML, MCP, SQLAlchemy, Alembic et jsonschema, `setuptools>=69`, `uvicorn` et `ruff`, sans verrou transitif ni empreintes. Les installateurs utilisent `uv pip install --editable` ([install.sh:411](../../../../install/install.sh#L411), [install.ps1:420](../../../../install/install.ps1#L420)), et l'image utilise `pip install --upgrade pip`, puis une installation éditable non verrouillée ([Dockerfile:48](../../../../deploy/Dockerfile#L48)). La CI installe aussi `uv` sans version ([installateur.yml:148](../../../../.github/workflows/installateur.yml#L148)).

**Précondition :** installation/reconstruction à deux dates ou avec deux états différents du registre/résolveur. **Conséquence :** le même commit ne décrit pas un environnement moteur identique à celui testé ; une réinstallation peut sélectionner de nouvelles versions compatibles avec les plages. **Direction minimale :** lock d'exécution/CI avec versions et empreintes, consommé par les chemins d'installation et de construction ; politique explicite de mise à jour. **Limite :** aucune divergence de comportement entre deux installations réelles n'a été provoquée. Il s'agit d'une lacune démontrée de reproductibilité, pas de la preuve qu'une plage donnée casse aujourd'hui.

## État CI : séparer le HEAD des résultats historiques

Les 300 runs disponibles dans actions-branche.json (`archive:historique/actions-branche.json`) montrent les dernières exécutions suivantes. Les réussites sont des preuves de leurs commits respectifs, pas une réussite globale du HEAD audité.

| Workflow | Dernier commit exécuté | Résultat | Run |
|---|---|---|---|
| `ci` | **2e56c0d5605dfe575bde9244f38924d5390f2674** | cancelled ; socle timeout ; gates failure | [36653609207](https://github.com/leon36000/OPSYS-AI/actions/runs/36653609207) |
| dernier `ci` entièrement vert | eaf7e6587d58fb11a236fefecf046976b6440db7 | success | [36631126286](https://github.com/leon36000/OPSYS-AI/actions/runs/36631126286) |
| `core` | 7189c9197e301391769f737b4dfbcb0f1f95698e | success | [36628215473](https://github.com/leon36000/OPSYS-AI/actions/runs/36628215473) |
| `installateur` | f62104f7067c57adc3fabc93914e9554bcfa1af6 | success | [36643413089](https://github.com/leon36000/OPSYS-AI/actions/runs/36643413089) |
| `mobile` | 1b1c70cb3549202a5301ba88452586cc462cdc4b | success | [36642024371](https://github.com/leon36000/OPSYS-AI/actions/runs/36642024371) |
| `e2e-core` | cc34ac4ee6691d99d664d62ed038ed3ab6a46592 | success | [36653429845](https://github.com/leon36000/OPSYS-AI/actions/runs/36653429845) |

Les filtres par chemins expliquent qu'un workflow puisse ne pas avoir de run au HEAD. Une ancienne réussite peut rester pertinente à des fichiers inchangés, mais il faut comparer les sources et les dépendances concernées pour l'étendre ; ce rapport ne lui attribue pas automatiquement le statut du HEAD.

**Complément local de l'audit global :** socle-rerun.log (`archive:execution/socle-rerun.log`) se termine par **2 020 passed, 77 skipped in 1113.32s (18 min 33 s)** ; socle-rerun.result.json (`archive:execution/socle-rerun.result.json`) enregistre le code **0**. La suite socle peut donc terminer dans cet environnement local. Cela ne remplace pas la CI du HEAD interrompue, ni les couches sautées (notamment PowerShell/actionlint absents ici), et ne permet pas d'identifier un test fonctionnel en échec dans la CI annulée.

## Points positifs et limites opérationnelles

- Les **27 références d'actions** des workflows racine sont épinglées à un SHA de 40 caractères ; permissions `contents: read`, pas de secret de production référencé dans ces workflows. Le binaire `actionlint` téléchargé est vérifié par SHA-256 avant extraction/exécution ([installateur.yml:89](../../../../.github/workflows/installateur.yml#L89)).
- Les six images Compose et la base Python du Dockerfile sont référencées par digest SHA-256. Le core et le mobile possèdent des locks, consommés par `pnpm install --frozen-lockfile` et `npm ci`. `packageManager` fixe pnpm avec empreinte ; le workspace impose un délai de publication et une liste explicite d'autorisations de builds. Les 1 542 entrées versions de paquets lues dans le lock core possèdent une intégrité. Ces contrôles ne remplacent pas le triage des avis R08, et le fallback npm des installateurs vérifie la version du gestionnaire, pas explicitement son hash `packageManager`.
- L'image métier exécute l'application sous l'utilisateur `opsys`, pas sous root. Seul Caddy publie 80/443 ; Postgres, Valkey, LiteLLM et MCP ne publient pas de port. Le socket Docker n'est pas monté par défaut. Le Gateway retire NET_RAW/NET_ADMIN et fixe `no-new-privileges`. Caddy désactive son API d'administration ; la console a une origine distincte, cookie sécurisé et source proxy autorisée explicite.
- Le jail fail2ban prévoit la chaîne `DOCKER-USER`, adaptée aux ports publiés Docker, et le conteneur métier journalise via journald. Leur efficacité réelle sur un VPS n'a pas été vérifiée ; aucun firewall, DNS, ACME ou règle iptables modifié.
- L'installateur hôte conserve un commit source identifié, refuse la mise à jour d'un clone géré avec changements locaux, utilise le profil core dédié, confronte le chemin de configuration prévu et celui du core, et exige la santé du Gateway et du moteur. Les journaux Bash sont privés et les sorties masquées ; la lecture `.env` du wrapper métier Bash n'évalue pas son contenu. Le modèle de permissions Windows n'a pas été validé sur ce système Linux.
- Le scan de motifs de secrets effectué sur **25 fichiers du périmètre infrastructure** n'a trouvé aucun candidat de clé privée, token GitHub, clé AWS ou clé fournisseur. Résultat borné, enregistré dans supply-results.json (`archive:infra/recent/supply-results.json`) ; ce n'est pas un scan exhaustif du dépôt/historique et aucune clé de production n'a été recherchée dans les données d'un opérateur.
- La restauration exige une confirmation explicite, sauf `--yes`. La désinstallation exige que l'export demandé réussisse avant tout retrait et vérifie les marques des commandes à supprimer. Ces contrôles utiles sont présents mais ne compensent pas R01/R02/R04.
- Les appels extérieurs de l'installation Docker concernent les dépôts HTTPS officiels et les paquets apt signés via keyring ; les scripts de synchronisation contactent le LiteLLM configuré et les sondes locales ont des délais. Les sauvegardes restic distantes restent optionnelles et administrées par l'opérateur. Aucun fournisseur LLM, Twilio ou stockage restic de production n'a été contacté pendant cet audit ; les appels d'audit externes se limitent aux API GitHub en lecture et aux métadonnées de vulnérabilités npm.

**Limite d'architecture documentée :** Compose exécute toujours l'image officielle OpenClaw 2026.9.6, pas le fork `core/` du commit audité ([docker-compose.yml:221](../../../../deploy/docker-compose.yml#L221), [INSTALLATION-VPS.md:7](../../../ops/INSTALLATION-VPS.md#L7)). Le Dockerfile exclut explicitement la construction du core. Les greffes OPSYS de celui-ci ne sont donc pas livrées par cette image. La doc maintient cette option historique et prévoit une décision séparée pour le superviseur ([INSTALLATION.md:16](../../../exploitation/INSTALLATION.md#L16)). Une CI verte du fork construit par les installateurs hôtes ne valide pas cette pile Docker, ni les parcours mobiles propres au fork sur cette pile. Ce rapport établit la divergence de livraison ; il ne prétend pas avoir exécuté et observé tous ses effets produit.

**Limite de livraison de la branche :** la recette « dépôt cloné » ([INSTALLATION.md:34](../../../exploitation/INSTALLATION.md#L34), Windows l.38) fait `git clone` sans branche puis lance un script qui n'existe pas sur `origin/main` observé, **`fcb65bcf20980a0b36847dbd41808527ba616d52`**. Celui-ci ne contient ni les deux installateurs, ni `pyproject.toml`, ni `core/openclaw.mjs`. Le script de la branche récente fonctionne depuis son checkout grâce à la détection du dépôt voisin ; téléchargé/lancé hors dépôt, il choisit **`main` par défaut**, sans repli vers la branche récente ([install.sh:658](../../../../install/install.sh#L658), [install.ps1:683](../../../../install/install.ps1#L683)). Cette voie sélectionnerait donc la mauvaise génération du dépôt dans l'état observé. La doc signale expressément que l'installation distante n'est **pas publiée** (l.41) : c'est une limite de disponibilité actuelle et de la recette de clone, pas la preuve d'un service publié défectueux. Avant intégration/publication, utiliser une référence explicite de la branche/du commit audité ou `OPSYS_SOURCE` approprié. Preuve de présence/absence Git, sans clone réseau ni installation : install-main-ref.json (`archive:infra/recent/install-main-ref.json`).

## Matrice de preuve et exécutions

| Garantie examinée | Meilleure preuve | Résultat |
|---|---|---|
| sauvegarde → restauration des cinq volumes | scripts exacts, fausse commande Docker, archives fictives | **Fail**, R01 |
| refus d'effacer les données à la désinstallation | chemins alias/`..`, résolution physique, `--simuler` | **Fail** sur la décision de suppression, R02 |
| secrets/données exclus du contexte image | contexte Compose, COPY, `.dockerignore`, emplacement backup par défaut | **Fail conditionnel**, R03 |
| absence de données requises → code non nul | cinq volumes absents ; restauration manifeste seul | **Fail**, R04 |
| VPS neuf installable selon procédure | template manquant et appels dans le script | **Fail statique**, R05 ; installation réelle non exécutée |
| confidentialité des fichiers de backup | umask 022, modes des fichiers et dossier daté | **Fail conditionnel**, R06 |
| CI du HEAD complète | jobs, étapes, annotations exact HEAD | **Fail**, timeout confirmé |
| suite socle locale de l'audit global | log et résultat de la relance locale | **Pass** pour 2 020 cas ; **Partial** avec 77 cas sautés |
| protection de `main` effective | API protection | **Inconclusive**, 403 |
| triage vulnérabilités dependencies core/mobile | locks + avis npm actuels + chemins du graphe | **Partial**, alertes confirmées, exploitabilité non testée |
| reproductibilité moteur Python | manifestes et commandes install/build | **Fail statique**, R09 |
| syntaxe Bash | `bash -n` des huit scripts concernés | **Pass** limité à la syntaxe |
| pile Docker, Linux/macOS/Windows complets au HEAD | pas de plateforme réelle exécutée ici ; CI ancienne identifiée | **Partial / non certifié** |

Résultats enregistrés : static_results.json (`archive:infra/recent/static_results.json`) (`bash -n`, huit retours 0 ; chemins `.env` ignorés), deploy_results.json (`archive:infra/recent/deploy_results.json`), guard_results.json (`archive:infra/recent/guard_results.json`), restore-empty-results.json (`archive:infra/recent/restore-empty-results.json`), socle-gh-results.json (`archive:infra/recent/socle-gh-results.json`), supply-results.json (`archive:infra/recent/supply-results.json`), audits npm ci-dessus. Les wrappers Docker existants et les copies des scripts sont consultables sous `deploy-repro/` ; les fixtures de garde sous `guard-repro/`. Les écritures restent exclusivement dans le dossier d'audit externe.

**PREUVE — audit en lecture seule terminé avec sources et artefacts traçables ; certification du déploiement/reprise au HEAD bloquée par les défauts confirmés et les vérifications réelles manquantes.**
