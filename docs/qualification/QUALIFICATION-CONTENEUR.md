# Qualification d'installation Linux reproductible en conteneur

> **Ceci ne qualifie PAS un VPS.** La cible de production n'est pas fournie ; aucun VPS réel n'a reçu OPSYS-AI. Ce document
> consigne ce qu'un banc scripté, rejouable, a **réellement** prouvé dans des conteneurs Linux fictifs, sans réseau, sans
> root, puis, sans euphémisme, ce qui échoue et ce qui reste **NON PROUVÉ** (§9). Formule exacte autorisée :
> **« moteur Python d'OPSYS-AI installé, démarré, sauvegardé, détruit, restauré et mis à jour dans des conteneurs fictifs ;
> VPS non qualifié »**.

Date : 1er novembre 2026 · Base de code : ligne architecte `0773dea68` + branche `claude/qualification-docker`.
Banc : [`install/qualification/`](../../install/qualification/) · Preuves brutes (JSON + Markdown, horodatées, codes de
sortie réels) : [`preuves/`](preuves/) · Plan hors site (non exécuté) : [PLAN-COPIE-HORS-SITE.md](PLAN-COPIE-HORS-SITE.md).

## 1. Ce que le banc fait

`python3 install/qualification/banc.py tout` (ou `gabarit --memoire 2g`, `balayage --gabarits 448m 416m`) :

1. **Pré-vol** (E00) : daemon, image de base en cache, disque, état des conteneurs étrangers (comparé à la fin : intacts).
2. **Installation depuis le dépôt local** (E01) : `install/qualification/Dockerfile` — mêmes utilisateur, variables, droits,
   `EXPOSE` et **le vrai `deploy/entrypoint.sh`** que `deploy/Dockerfile` ; le paquet `opsys-ai` est installé depuis le dépôt
   (`pip install --no-deps --no-build-isolation -e`), les dépendances viennent d'un environnement déjà installé
   (`preparer_contexte.py`, §9 pour l'écart).
3. **Installateur public** (E02) : `install/install.sh` dans un conteneur propre non root sans réseau — échec consigné.
4. Par gabarit mémoire, dans des conteneurs `--network none --user 1000 --read-only --cap-drop ALL --security-opt
   no-new-privileges --pids-limit 256`, avec `--init` comme Compose : **init** (démarrage à vide, personnes via la VRAIE
   CLI sous pseudo-terminal, paliers, entreprise fictive, profils de base, redémarrage) → **`opsys-metier verifier`** →
   **sondes** (MCP, console, authentification, en-têtes, connexion) → **parcours métier** → **empreintes avant** →
   **sauvegarde chiffrée** → **durcissement** → **destruction** → **restauration sur conteneur neuf** → **comparaison** →
   **arrêt propre** → **mise à jour 0038→0040 et retour arrière** → **injections de défauts**.

Chaque étape écrit `NN-<étape>.json` et `.md` : verdict, constats (nom, résultat, détail), mesures, commandes avec **code de
sortie réel** et durée. Le banc refuse d'écrire une preuve qui contiendrait une valeur de secret (masque, test unitaire).
Un échec est consigné comme échec ; aucun constat n'est simulé.

### Exécutions conservées (aucune n'est écrasée, rouges comprises)

| Exécution | Contenu | Résultat |
|---|---|---|
| `preuves/qualif-20261101T110043Z` (**A**) | Pré-vol, installation, installateur public ; parcours complet à **4 Go** ; parcours à **2 Go** ; balayage 1 g, 768 m, 512 m, 384 m | 4 Go : tout PASSE. 2 Go : tout PASSE **sauf `mise-a-jour` : défaut du banc** (`FileExistsError`, répertoire de l'ancienne version réutilisé), corrigé puis rejoué en **B**. 384 m : OOM (voir §4) |
| `preuves/qualif-20261101T111039Z` (**B**) | Parcours complet à **2 Go** après correction du banc | Tout PASSE (hors E02, échec documenté) |
| `preuves/qualif-20261101T111355Z` (**C**) | Balayage fin 448 m, 416 m | 448 m viable ; 416 m OOM |
| `preuves/preliminaires/` | Deux exécutions de mise au point, **rouges conservées** : balayage de motifs de secrets trop large, argv erroné vers l'ancien logiciel, refus d'export/restauration non typés (F2b, F4) | Échecs réels, à l'origine des correctifs de §7 |

Le commit de code des exécutions A est `a41d6e7aa` (arbre propre, voir `01-e00-prevol.json`) ; B et C tournent sur le commit
suivant (banc seulement). L'hôte est **aarch64** (Docker 29.6.2, cgroup v2, 20 cœurs, 121 Go) — pas la VM ARM64 de test, qui
manquait de mémoire.

## 2. Résultats par étape (exécution A, 4 Go ; B, 2 Go, identique)

| Étape | Verdict | Durée (s) | Ce qui est prouvé |
|---|---|---|---|
| E00 pré-vol | PASSE | 0,2 | Daemon joignable ; `python:3.12-slim` (3.12.15, arm64) déjà en cache ; 39 Go libres |
| E01 installation depuis le dépôt | PASSE | 29,4 (build 24,3) | Image construite sans réseau ; `pip` a installé `opsys-ai` ; `opsys-metier --version` ; `pip check` propre ; uid 1000 |
| **E02 installateur public** | **ÉCHEC (documenté)** | 0,4 | `install.sh` sort en erreur : « Node.js est introuvable » (Node 24.16+/26.1+, uv, pnpm, Docker et réseau requis). **Jamais terminé avec succès ici.** |
| init | PASSE | 24,9 | 1er démarrage : readiness 3 (en attente de configuration), puis après initialisation (2 personnes par la CLI humaine, paliers, entreprise, profils de base) et redémarrage : readiness 0 |
| verifier | PASSE | 3,4 | `opsys-metier verifier` code 0 : 10 départements, 415 outils |
| sondes | PASSE (16) | 1,9 | MCP `/sante` 200, POST 405, sans jeton 401, mauvais jeton 401, bon jeton 200 ; console `/connexion` 200, en-têtes, 404 sans trace, redirection sans session ; connexion (mauvais refusée, bonne → cookie HttpOnly/Secure/SameSite) |
| parcours | PASSE (14) | 10,0 | Lead par la route MCP HTTP → M2 qualifie → M3 crée la soumission (625,00 $ calculé par l'outil) → N3 refusée → accordée (§6) → M4 « à planifier » |
| empreinte avant | PASSE | 1,6 | 86 tables, 109 lignes, `integrity_check` ok, deux lectures identiques |
| sauvegarde | PASSE | 2,3 | Archive chiffrée 46 408 octets, 0600, aucune donnée lisible, clé hors du dossier, `verifier` indépendant |
| durcissement | PASSE (20) | 4,7 | §5 |
| destruction | PASSE | 1,3 | Arrêt code 0 en 0,73 s, volumes data/cfg supprimés, sauvegarde et clé survivent |
| restauration | PASSE | 10,1 | Conteneur et volumes neufs : restauration 0,84 s ; prêt (readiness 0) 7,0 s après démarrage ; connexion avec le mot de passe d'origine |
| comparaison | PASSE | 4,6 | **86 tables, 109 lignes : toutes identiques** (SHA-256 de contenu par table, journal d'audit hors lignes `instance.*`), empreinte globale identique, approbation N3 présente |
| arrêt propre | PASSE | 1,5 | Code 0, « arrêt demandé », pas de faux « processus mort », pas d'OOM |
| mise à jour | PASSE (15) | 22,1 | §3 |
| injections | PASSE (28) | 58,4 | §7 |

## 3. Mise à jour 0038 → 0040 et retour arrière (état réel)

La version précédente est un **arbre `git archive 2ffa4f606^`** (dernier état avant la migration 0039), monté en lecture seule
sur `PYTHONPATH` : c'est CE logiciel (`/ancien/src/opsys`, vérifié dans la sortie) qui écrit la base à la révision **0038**
(76 tables, 31 lignes : une personne, un lead, une soumission). Puis :

- le logiciel courant migre : code 0, **0,96 s, 67,5 Mo de RSS**, révision 0040 (+10 tables) ; **les 76 tables d'origine sont
  identiques** (SHA-256 par table) ; `integrity_check` ok ; les services démarrent sur cette base et s'arrêtent proprement ;
- **retour arrière alembic** 0040 → 0038 sur une copie : code 0, données identiques à l'état d'avant, et **le logiciel
  précédent relit la base** (`base etat` → 0038) ; nouvelle montée à la tête : mêmes données ;
- **le logiciel précédent sur une base à 0040** : refus (code ≠ 0), base inchangée (empreinte identique) ;
- migration interrompue : voir F3 (§7).

Limite : la rétrogradation 0040 est refusée par la migration dès qu'une table du chantier courriel contient une ligne (voir son
docstring) ; ici ces tables sont vides. Le retour arrière d'une instance avec courriels réels n'est pas éprouvé.

## 4. Mesures : mémoire, temps, tailles

### Mémoire par gabarit (parcours jusqu'à la sauvegarde chiffrée, même charge à chaque gabarit)

`memory.peak` du cgroup du conteneur (inclut le cache de pages, réclamable) et RSS maximal par processus (`VmHWM`) :

| Limite du conteneur | Viable ? | Pic cgroup | RSS max par processus | Arrêt |
|---|---|---|---|---|
| **4 Go** (parcours complet) | oui | 433,7 Mo | console 142,2 Mo ; MCP 134,2–135,4 Mo ; CLI/outil de passage ~32 Mo ; sauvegarde 69,7 Mo ; migration 67,5 Mo | code 0 |
| **2 Go** (parcours complet) | oui | 431,9–433,4 Mo | idem | code 0 |
| 1 Go, 768 Mo, 512 Mo, 448 Mo | oui | 432,9–433,9 Mo | idem | code 0, pas d'OOM |
| **416 Mo** | **non : OOM-killed** pendant le parcours | — | — | `OOMKilled=true` |
| 384 Mo | non : OOM-killed | — | — | `OOMKilled=true` |

**Plus petit gabarit viable établi par mesure, pour cette charge fictive : entre 416 Mo (échec) et 448 Mo (succès).**
Le plafond `mem_limit: 512m` de `deploy/docker-compose.yml` pour le service `opsys` est donc **à ~14 % au-dessus du plancher
d'une charge triviale** (une personne, un lead, une soumission, sans modèle ni embeddings ni charge). Recommandation (non
appliquée, décision d'allocation de l'architecte) : **≥ 1 Go** pour `opsys` en production ; 2 Go laisse de la marge sur un VPS
de 8 Go. Les deux processus longue durée (console + MCP) tiennent ~280 Mo de RSS à eux seuls ; chaque appel CLI ajoute 30–70 Mo
(scrypt des mots de passe, migrations, export).

**Le problème de mémoire de la VM ARM64 n'est PAS reproduit** : il survenait pendant l'installateur public (construction du
Core TypeScript, `pnpm`), que ce banc ne peut pas exécuter (E02, réseau et Node absents). Ces gabarits mesurent le moteur Python
seul. Le besoin mémoire de la construction du Core reste à mesurer, sur la cible ou avec réseau.

### Temps (exécution A, secondes)

Build image 24,3 ; démarrage à vide → readiness 3 : 6,8 ; initialisation complète : 24,9 (dont redémarrage → prêt 6,8) ;
`verifier` 3,4 ; sondes 1,9 ; parcours 10,0 ; sauvegarde (processus) 0,81 ; restauration (processus) 0,84 ; démarrage →
prêt après restauration 7,0 ; migration 0038→0040 0,96 ; arrêt propre 0,6–1,2. Les durées détaillées de chaque commande sont
dans les JSON.

### Tailles

Image : **638 Mo sur disque** (`docker image ls`, exécution C) dont 205 Mo d'image de base ; couches ajoutées : venv 113 Mo, `docs/` 48 Mo,
bibliothèque Python 31 Mo, `departments/` 23 Mo, **`mobile/` 18 Mo**, **`tests/` 9 Mo**, `src/` 5 Mo. Données de l'instance
fictive : `/opt/data` 1,6 Mo (86 tables), configuration 0,75 Mo, sauvegarde chiffrée 46 Ko. L'image de production embarque le
dépôt entier hors `.dockerignore` (mobile, tests, docs) : ~75 Mo inutiles au runtime (recommandation, non appliquée : voir §8).

## 5. Durcissement vérifié (étape `durcissement`, service en marche)

| Contrôle | Résultat |
|---|---|
| Processus non root | uid/gid 1000 ; aucun processus du conteneur en root |
| Racine en lecture seule | Écriture refusée dans `/opt/opsys`, `/usr/local`, `/etc`, le venv ; seuls `/tmp` (tmpfs), `/opt/data`, `/openclaw-config` inscriptibles |
| Capacités / élévation | `CapEff = 0`, `NoNewPrivs = 1` ; `docker inspect` : `CapDrop=[ALL]`, `no-new-privileges`, limite mémoire et PID posées |
| Permissions des secrets | Dossier des clés 0700 ; clé de sauvegarde et mots de passe de test 0600 ; **base `opsys.db`, `-wal`, `-shm` en 0600** (défaut corrigé, §7) |
| Secrets dans l'image | Balayage du système de fichiers (code, config ; hors tests/docs/mobile/bibliothèques) : aucune clé privée ni motif de clé API ; historique et variables de l'image sans valeur de secret (`GPG_KEY` = empreinte publique de l'image de base Python) |
| Secrets dans les journaux et volumes | Journaux du service (5 174 octets) et volumes `data`/`cfg`/`sauvegardes` : aucune valeur de jeton, secret de console, clé fournisseur, mot de passe ni clé de sauvegarde |
| Journalisation sans PII | Ni téléphone du client, ni identifiant tapé lors d'un échec de connexion (défaut corrigé, §7) |
| Ports | Écoute exactement `8765` (MCP) et `8700` (console) ; l'image n'expose que ces deux ; **aucun port publié** (réseau `none`) |
| En-têtes de la console | `Content-Security-Policy` (`default-src 'none'`…, `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` ; cookie de session HttpOnly + Secure + SameSite |

Non couvert : `Strict-Transport-Security` et TLS (portés par Caddy, non testé) ; limitation de débit (fail2ban, hôte) ;
sandbox des agents (Docker du Core). `deploy/docker-compose.yml` porte désormais ces réglages pour `opsys` (lecture seule,
`/tmp` en tmpfs, `cap_drop: [ALL]`, `no-new-privileges`, `pids_limit`) — jamais rejoué avec le vrai Compose complet ni avec le
profil optionnel `ingestion-pdf` (bubblewrap), **non requalifié sous ces réglages**.

## 6. Parcours métier minimal : approbation N3

`m3_marquer_devis_accepte` est une action N3 (engagement externe : l'acceptation du client). Constats réels :

1. Un **agent** (route MCP du département) qui l'appelle est **refusé** (`ticket_cible_requis`), rien n'est exécuté.
2. Une demande d'approbation est créée (**par l'API du socle** `approbations.creer_demande` : le chemin agent avec ticket de
   session M10 n'est pas rejoué) ; décider avec une identité vide, inconnue ou celle d'un `system_agent` est refusé, la demande
   reste `en_attente` ; la CLI sans terminal et avec un mauvais mot de passe : code 1, `en_attente`.
3. `opsys-metier approbations approuver` par `nathan_owner` avec son vrai mot de passe tapé sous pseudo-terminal : code 0, statut
   `executee`, décision signée (personne + rôle) ; une seconde décision est refusée. Le devis passe à `accepte`, M4 reçoit
   « à planifier ». Après destruction et restauration, cette approbation est présente.

## 7. Sauvegarde et restauration ; injections de défauts

### Politique (module `src/opsys/sauvegarde_chiffree.py`)

- **Chiffrement** : AES-256-GCM par blocs de 1 Mio, clé de bloc dérivée (HKDF-SHA256) de la clé et d'un sel aléatoire ;
  chaque bloc est authentifié avec l'en-tête et un drapeau « dernier bloc » ; le rang du bloc est dans le nonce.
- **Clé hors de la sauvegarde** : fichier 0600 (propriétaire courant, dossier privé), jamais dans le dossier des sauvegardes
  ni dans l'instance (refus `REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE`, code 13), distincte de la clé maîtresse du coffre. Sa
  garde hors serveur est humaine ([plan](PLAN-COPIE-HORS-SITE.md)).
- **Intégrité** : vérification par déchiffrement en flux après écriture (la sauvegarde est retirée si elle diverge) ;
  à la restauration, **toute l'archive est authentifiée avant** qu'`exportation.restaurer` (empreintes, membres, `integrity_check`,
  révision) ne touche à l'instance ; rien n'est écrasé sans `--remplacer`, et le fichier final n'existe qu'après succès.
- **Rétention** : `retention --garder N --jours J` garde les N plus récentes ET tout ce qui a moins de J jours ; le reste est
  **mis de côté** (`a-detruire/`), jamais supprimé (destruction définitive = décision humaine). Éprouvé par tests unitaires.
- Codes de sortie : 10 clé absente · 11 clé invalide · 12 permissions · 13 clé dans la sauvegarde · 14 mauvaise clé · 15 altérée ·
  16 tronquée · 17 format · 18 version de format · 19 disque plein · 20 dépendance · 21 rétention · 22 E/S · 23 export ·
  24 restauration · 25 version du logiciel · 26 base corrompue.

### Injections de défauts (étape `injections`, 4 Go et 2 Go — toutes PASSENT)

Pour chaque défaut : refus, code attendu, et **instance existante intacte** (empreinte SHA-256 identique avant/après).

| # | Défaut injecté | Résultat observé |
|---|---|---|
| F1 | Restauration avec une **mauvaise clé** sur une instance non vide (`--remplacer`) | `REJ-SAUVEGARDE-MAUVAISE-CLE`, code 14, rien déchiffré, instance intacte |
| F2a | **Base vivante corrompue** (pages écrasées) → export | `REJ-SAUVEGARDE-BASE-CORROMPUE`, code 26, aucune sauvegarde laissée |
| F2b | Archive **authentique** (manifeste cohérent) contenant une base corrompue → restauration | code 26, cible restée vide |
| F3 | **Migration interrompue** : `SIGKILL` à 5 %, 25 %, 50 %, 75 %, 95 %, 99,9 % des 36 instructions SQL | Après les 4 premiers kills : base saine, **révision 0038** (retour en arrière atomique) ; après les 2 derniers (post-validation) : 0040 ; `integrity_check` ok, données d'origine identiques ; reprise `base migrer` → 0040 sans perte |
| F4 | **Disque plein** (destination limitée à 96 Ko) | `REJ-SAUVEGARDE-DISQUE-PLEIN`, code 19, instance intacte |
| F5a | **Secret manquant** : clé de sauvegarde absente | `REJ-SAUVEGARDE-CLE-ABSENTE`, code 10 |
| F5b | `OPSYS_CONSOLE_SECRET` / `OPSYS_MCP_JETON` manquants au démarrage | Le service s'arrête (code 1) en disant pourquoi ; données intactes |
| F5c | Clé de fournisseur de modèle absente | Le service **reste en marche** et dit « en attente de configuration » (readiness 3, `ANTHROPIC_API_KEY`) |
| F6a | Archive d'une **version plus récente** (révision 9999) | `REJ-SAUVEGARDE-VERSION-LOGICIEL`, code 25, cible vide |
| F6b | Format de sauvegarde chiffrée **v99** | `REJ-SAUVEGARDE-VERSION-FORMAT`, code 18 |
| F7a/b | **Restauration partielle corrompue** : archive tronquée à 50 % ; un seul bit modifié | `REJ-SAUVEGARDE-TRONQUEE` (16) / `REJ-SAUVEGARDE-ALTEREE` (15), sur cible vierge ET sur instance non vide ; rien écrit, pas de `.partiel` |
| F8 | Clé rangée **dans** le dossier des sauvegardes | `REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE`, code 13 |
| — | Logiciel précédent sur base à 0040 (§3) | Refus, base inchangée |

F4 : l'absence de fichier `.partiel` résiduel est prouvée par test unitaire (le tmpfs du conteneur est éphémère).

## 8. Défauts révélés par le banc

### Corrigés dans le dépôt (changements minimaux, chacun avec un test qui échoue sans le correctif)

1. **`deploy/entrypoint.sh` : `docker stop` sortait en code 1** avec le faux message « un processus longue durée s'est
   arrêté ». Un arrêt demandé sort maintenant en 0 (et dit « arrêt demandé ») ; un processus qui meurt sort toujours en 1.
   Test : `tests/test_entrypoint_arret.py` (échoue avec l'ancien script, vérifié).
2. **Base SQLite (`opsys.db`, `-wal`, `-shm`) créée en 0644** : renseignements personnels, empreintes de mots de passe et clés
   de chiffrement destructibles lisibles par tout compte de l'hôte/du volume. Resserrée en 0600 à la connexion
   (`stockage.moteur.restreindre_base`, jamais élargie). Test : `tests/test_sauvegarde_chiffree.py::test_la_base_de_l_instance…`.
3. **Journal d'un échec de connexion** : l'identifiant tapé (parfois un courriel) était écrit tel quel. Remplacé par une
   empreinte courte (le filtre fail2ban lit la ligne d'accès, pas celle-ci). Test : `tests/test_console.py::test_le_journal_d_un_echec…`.
4. **Refus d'export/restauration non typés** : `ErreurExportation` porte maintenant un `code` facultatif (`REJ-EXPORT-…` :
   base corrompue, version incompatible, empreinte, disque plein) et la CLI `instance` l'affiche sur une ligne `CODE :`.
5. **Pas de chiffrement des sauvegardes** (la doc renvoyait à `age`/`gpg`, absents de l'image) : module
   `opsys.sauvegarde_chiffree` (§7), 18 tests.
6. **Service `opsys` du Compose sans durcissement** alors que le banc prouve qu'il tourne ainsi : lecture seule, `/tmp`
   tmpfs, `cap_drop: ALL`, `no-new-privileges`, `pids_limit: 256` (`docker-compose.rootless.yml` : doublon `security_opt`
   retiré, que `docker compose config` refusait). Test : `tests/test_deploy_durcissement_opsys.py` et `test_deploy_rootless.py`.

### Constatés, NON corrigés (décisions pour l'architecte)

- `deploy/Dockerfile` : la directive `# syntax=docker/dockerfile:1.7` oblige BuildKit à joindre le registre : **la construction
  échoue hors réseau** ; sa base est épinglée par un digest (`3.12.14-slim-trixie`) absent du cache local, et `pip install
  --require-hashes` exige le réseau. Rien de tout cela n'a été exécuté ici.
- `mem_limit: 512m` pour `opsys` : marge ~14 % au-dessus du plancher mesuré (§4).
- L'image embarque `mobile/`, `tests/`, `docs/` (~75 Mo) ; une entrée dans `Dockerfile.dockerignore` les retirerait (non fait :
  `test_deploy_python_context` épingle ce fichier).
- `opsys-metier instance exporter` brut (hors module) : d'après la lecture du code (non rejoué), une erreur d'écriture hors SQLite (disque plein pendant la fabrication de l'archive) sort en exception non rattrapée par `cmd_instance` ; le module `sauvegarde_chiffree` la type.
- `opsys-metier base migrer` affiche l'URL complète de la base (chemin) — sans secret, mais à connaître.

## 9. NON PROUVÉ (dit sans euphémisme)

- **Un VPS réel** : aucun. Réseau public, **TLS/Caddy réels**, **DNS**, certificats ACME, `fail2ban`/`ufw`, journald : non testés.
- **Le Core OPSYS (TypeScript)** : non construit, non démarré ; le Gateway, les tours d'agent, la sandbox Docker des agents,
  l'appairage mobile ne sont pas exercés. `opsys-metier openclaw configurer` génère ses fragments, rien ne les lit.
- **L'installateur public** `install/install.sh` : n'a jamais terminé avec succès ici (E02) ; `uv`, `pnpm`, `systemd --user`
  non éprouvés. **Le manque de mémoire de la VM ARM64 n'est pas reproduit** (construction du Core non exécutée).
- **`pip install --require-hashes -r requirements-runtime.lock.txt`** : non exécuté (réseau). Les dépendances sont copiées
  d'un environnement local aux mêmes versions que le verrou ; **les empreintes du verrou ne sont pas vérifiées** ; l'extra
  « tournées » (PyVRP, NumPy et dépendances numériques : 12 distributions) est **absent** de l'image du banc.
- **`deploy/backup.sh` / `restore.sh`**, Docker Compose complet, volumes nommés Compose, journald, PostgreSQL, Valkey, LiteLLM :
  non rejoués (tests existants avec Docker factice seulement).
- **Matériel ARM64 réel** (VM de test ou VPS) : l'hôte du banc est un aarch64 puissant, pas la cible ; **charge**,
  concurrence, longue durée, redémarrage de la machine : non mesurés. Le plancher mémoire (§4) vaut pour la charge fictive.
- **Fournisseur d'hébergement**, **copie hors site** ([plan](PLAN-COPIE-HORS-SITE.md), non exécuté), garde de la clé hors
  serveur, rotation des clés.
- **Approbation N3 par un agent avec ticket de session M10** (chemin complet) ; modèles de langage réels ; embeddings (valeurs
  fictives, rien n'est appelé) ; canaux SMS/courriel.
- **Pas d'acceptation des conditions, pas de paiement, pas de déploiement** : rien d'irréversible n'a été exécuté.

*Note de transparence.* Le banc n'utilise aucun réseau (`--network none`). Au tout début, une requête `HEAD` vers `pypi.org`
(sonde de joignabilité, rien n'a été téléchargé ni installé) a reçu une réponse : la machine a donc un accès réseau partiel ; la
construction d'image, elle, n'a pas pu joindre le registre de `docker/dockerfile` (DNS).

## 10. Rejouer

```bash
python3 install/qualification/banc.py tout --venv <venv déjà installé>     # ~12 min : 4 g, 2 g, balayage 1 g … 96 m
python3 install/qualification/banc.py gabarit --memoire 2g --venv <venv>
python3 install/qualification/banc.py balayage --gabarits 448m 416m --venv <venv>
```

Prérequis : Docker, `python:3.12-slim` en cache, un venv aux versions du verrou. Les ressources sont étiquetées
`opsys.banc=<run>` et retirées à la fin ; aucun conteneur étranger n'est touché (vérifié en E90). Plafond disque du banc : image
~0,6 Go + volumes de quelques Mo.

Tests : `tests/test_sauvegarde_chiffree.py` (18), `tests/test_banc_qualification.py` (8), `tests/test_entrypoint_arret.py` (2),
`tests/test_deploy_durcissement_opsys.py` (3), `tests/test_console.py` (+1). Mutations : 14 mutations manuelles tuées, dont une
survivante initiale fermée (type d'erreur SQLite accepté trop largement) ; liste dans le rapport de la tâche.
