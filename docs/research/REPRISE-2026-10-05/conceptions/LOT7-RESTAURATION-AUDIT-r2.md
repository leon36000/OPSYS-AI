# Audit lot 7 — sauvegarde / restauration (lecture statique)

**Périmètre.** Lecture seule de `deploy/backup.sh`, `deploy/restore.sh`, Compose et des guides d'installation; aucun script n'a été exécuté, aucun conteneur/service/client consulté, aucune modification du dépôt. Constat au **2026-10-05 07:25 UTC = 2026-10-05 03:25 America/Toronto**. Les mentions de tests ci-dessous sont des mentions documentaires, pas des exécutions faites ici.

## Ce que le chemin déployé sauvegarde

- En mode SQLite natif, `opsys_data:/opt/data` emporte la base métier OPSYS; si `OPSYS_DATABASE_URL` vise PostgreSQL, `pg_dump opsys` est requis et remplace la sauvegarde physique Postgres. En profil LiteLLM, `pg_dump litellm` et `litellm_config` sont aussi requis. Le fichier `.env` n'est jamais archivé.
- `openclaw_config` monte dans `/home/node/.openclaw`, le `OPENCLAW_STATE_DIR` configuré du Core. Le chemin Core courant place les bases agent à `agents/<agentId>/agent/openclaw-agent.sqlite`; l'outbox `opsys_postflight_outbox` est persistée dans cette SQLite. L'archive du volume inclut donc config, états agent et outbox (pending/retry) **si** le processus utilise ce state dir et que les fichiers sont sur ce volume. C'est différent de l'export natif documenté plus bas, qui exclut `~/.opsys/core` et donc le Core/outbox.
- `openclaw_auth_secrets` emporte les fichiers d'auth Core; `caddy_data`/`caddy_config` emportent l'état/config Caddy. `litellm_config` est requis en mode LiteLLM, optionnel s'il existe en natif. Le manifeste v3 inscrit profil/backend, ressources et noms de volumes; permissions annoncées 0700/0600.
- La configuration et les secrets d'environnement ne sont pas sauvegardés : `.env`, mots de passe DB, clés fournisseurs, tokens MCP/Gateway, sessions et valeurs injectées restent à reprovisionner. Les configs Core peuvent conserver des références `${ENV}` qui requièrent les nouvelles valeurs compatibles.

## Cinq constats prioritaires

1. **Le volume Core contient bien l'outbox à restaurer; l'export natif ne la contient pas.** `deploy/backup.sh` archive en bloc `openclaw_config`, monté sur le state dir Core; les DB agent résident sous ce répertoire. À l'inverse, la liste blanche de l'export natif ne sort que `opsys.db`, `paliers.yaml`, `entreprise.yaml`. Symptôme d'une restauration native partielle : activité métier restaurée mais sessions, auth Core et lots postflight absents. **Petit pas :** garder les deux parcours clairement séparés dans runbook; tester une outbox pending et retry à travers l'archive Compose (le parent prépare une qualification SQLite à orchestration factice, qui ne prouvera pas Docker/VPS).
2. **Le préflight Compose vérifie la structure, pas la cohérence cryptographique complète.** Il vérifie correspondance manifeste v3/profil/backend, présence, gzip/tar listables; le manifeste n'embarque pas de hash par archive-volume ni par dump. Une archive tronquée est souvent détectée, mais un contenu altéré/recompressé et tar encore lisible ne l'est pas. **Petit correctif faisable :** émettre SHA-256 de chaque archive et exiger leur comparaison avant l'arrêt des services; garder un manifeste signé/hors archive comme qualification ultérieure.
3. **Restore Compose est destructif et sans rollback après première écriture.** Préflight et confirmation précèdent l'arrêt, puis les dumps/volumes courants sont remplacés; en erreur, le message dit explicitement qu'il n'y a pas de rollback et laisse les services arrêtés. Le mode/backend v3 doivent correspondre exactement, ce qui empêche une restauration directe SQLite↔Postgres ou natif↔LiteLLM. **Procédure courte :** restaurer sur un projet/volumes isolés avec copie de sauvegarde de la cible, puis basculer; qualifier des erreurs après première écriture pour rendre le point de non-retour visible.
4. **Secrets/références de config sont à reconstituer par l'opérateur.** `deploy/restore.sh` exige le `.env` cible et ne le restaure pas; les clés fournisseurs, tokens et mots de passe DB y sont injectés depuis l'environnement. L'archive de `openclaw_config` restaure donc des fichiers de config sans garantir que les références se résolvent ni que credentials/API sont valides. **Petit pas :** checklist de mapping des noms de variables par profil et validation locale de présence/format avant démarrage; jamais déduire leur validité d'un healthcheck.
5. **Preuve de sauvegarde/restauration VPS encore limitée.** Le guide VPS (état au 30 septembre) dit explicitement que v3 a été testée sur volumes Docker QA éphémères, parcours complet non certifié sur VPS production. Les healthchecks/readiness n'établissent ni tour agent/auth ni restauration métier. **Qualification manquante :** exécution isolée des scripts réels avec deux bases SQLite factices (registre M10 durable et Core outbox pending+retry), restauration puis intégrité, clé `tc-40`, provenance et rejeu idempotent vérifiés; ensuite vraie qualification daemon/volumes du VPS, et enfin exercice de restauration avec versions/profils/config/secretsrefs cohérents. La qualification factice prévue par ROOT ne vaut pas preuve container ou VPS.

## Scénario borné sans Docker

Le chemin CLI natif permet une restauration SQLite locale sans démarrer Gateway ni joindre un fournisseur : préparer **deux `OPSYS_HOME` jetables** (données synthétiques uniquement), initialiser la base source par les commandes CLI documentées, lancer `opsys metier instance exporter --sortie <tmp>/source.tar.gz`, puis `OPSYS_HOME=<tmp>/cible opsys metier instance restaurer <tmp>/source.tar.gz` et vérifier hash sidecar, `opsys.db`/migrations et un enregistrement synthétique connu. Garder les répertoires sous un `mktemp` mode 0700 et les supprimer après vérification. La documentation exige l'instance cible préparée via installateur; aucune commande de fixture minimale autonome n'est prescrite ici, donc ne pas improviser sur une instance client. Ce scénario valide uniquement l'export/restauration CLI SQLite, **pas** `deploy/restore.sh`, les volumes Core/outbox ni PostgreSQL. Pour Compose, `tar -tzf`/`gzip -t` et inspection du manifeste sans Docker ne sont qu'un préflight de fichiers, pas une restauration.

## Sources ciblées et SHA-256

SHA calculés le 2026-10-05 UTC sur les fichiers lus :

- `deploy/backup.sh` — `05a3f04a2184c9ec0b4a81fb10297af1aaed84aeb8060e8a03799a923f3b1edc`
- `deploy/restore.sh` — `28e0282b5432897e66e31c69a72ffdd6c4e501eb921b7e93124020e40e87daf9`
- `deploy/docker-compose.yml` — `5d98ebf991717cb27f2e3c42b0ce8fee21e318658005f35f96aaaecc100ac5f4`
- `docs/exploitation/INSTALLATION.md` — `83ac9c2083f757980ac8a1f273476bfbb94ccb837488b54072daa36df9bef6c3`
- `docs/ops/INSTALLATION-VPS.md` — `8916c03fb7d40f5d53eb2ac1d5d39312ee7f1beef8165a760ceff53b8561399f`
- `src/opsys/exportation.py` — `e9c04ba01f3698bf3a7b697855710a7f0e3c7816e6a6b16a52a4b9cce19f8f82`
- `src/opsys/cli.py` — `657adcaad4b144417bc704cfe311953f758e3bc7b714f3329609e924f203f75e`
- `core/src/state/openclaw-agent-db.paths.ts` — `41a6f9c7bafa2718058bceea9fd9ef3096c6b5656b6ec7375006bbb3dafa057f`
- `core/src/agents/harness/opsys-postflight-outbox.worker.ts` — `24ac7540eaefc51b4b4b367d93d9ca8cb4148e36f044baf9d9f65c4f0b848705`


## Qualification ROOT communiquée après cette lecture

ROOT rapporte que la qualification r302 du fichier complet a donné **50 cas réussis**; un test explicitement Docker a été ignoré par l'environnement, et le skip global préexistant est resté conservé. Ruff r302 est vert et les manifestes r303 sont verts. Les nouveaux cas SQLite réels couvrent l'archivage/restauration des fichiers, régénérations et rejeu M10 selon ROOT. Ces résultats sont une qualification distincte de mon audit statique; l'orchestration Docker reste factice. Ils ne démontrent ni accès au daemon Docker, ni restauration sur VPS, ni dispatch effectif par worker. Aucun test n'a été exécuté par l'auteur de ce rapport.
