# Profil serveur rootless — candidat de configuration

Ce profil réutilise Docker Engine rootless et le Core natif. Il est distinct de
[`deploy/install.sh`](../../deploy/install.sh), qui installe un daemon rootful et
des services système : **ne pas lancer cet installateur pour ce profil**. Aucun
provisionnement de l'hôte, daemon, image, compte, clé ou ancien volume n'est effectué
par [`rootless.py`](../../deploy/rootless.py).

La tranche livrée est génération + préflight en lecture seule. Les tests utilisent
des observations rootless fictives, les helpers Node/Python réels sous UID1000 sur
fichiers temporaires privés et le vrai parseur Compose, sans contacter un daemon. **Image serveur, Gateway/MCP/10 modules en runtime, sandbox dans cette pile,
edge TLS et VPS restent non qualifiés.** Les preuves C01 locales antérieures ne sont
pas une preuve du profil rootless : voir la qualification R20 dans le dépôt principal.

## Frontière et prérequis

Un compte Linux dédié non-root héberge **le même daemon rootless** pour toute la
pile et les sandboxes. UID/GID1000 dans les images Python et Core doivent correspondre
aux mêmes UID/GID subordonnés sur l'hôte. Les répertoires de state/config/auth/données
sont des **binds privés**, pas des volumes nommés : le Core natif peut ainsi traduire
les seuls sous-répertoires workspace/skills qu'il projette dans chaque sandbox.

Le Gateway, contrôleur de confiance, reçoit Docker CLI via
`OPENCLAW_INSTALL_DOCKER_CLI=1` (déjà supporté par le
[`Dockerfile Core`](../../core/Dockerfile)). Il joint son daemon par SSH avec une clé
dédiée et une clé hôte ed25519 vérifiée hors bande. Le répertoire `.ssh` est séparé
de tous les workspaces/state et monté RO **uniquement dans le Gateway**. Aucun
socket, ssh-agent, forwarding, clé ou state global n'est ajouté aux sandboxes. Les
fragments OPSYS et la garde Core `sandbox-required` restent inchangés.

Le contrôleur possède le pouvoir de son daemon. Rootless réduit ce pouvoir à celui
du compte dédié et de ses mappings ; il ne rend pas une compromission du Gateway
inoffensive pour la pile. Les fournisseurs/MCP/outils réseau natifs restent dans
le contrôleur ; `network=none` concerne les sandboxes. Ce profil n'est pas une
isolation SaaS multitenant. Un socket rootful, même bindé RO, n'est jamais une
alternative acceptée par le préflight.

Prérequis à préparer explicitement par l'opérateur, selon les documents Docker :

- Docker Engine rootless opérationnel, `newuidmap/newgidmap`, plages subuid/subgid
  suffisantes et service utilisateur persisté ; aucun de ces éléments n'est installé ici.
- cgroup v2 + driver systemd, délégation mémoire/CPU/PID. Le préflight refuse
  les flags non supportés et vérifie les limites **appliquées** aux deux conteneurs.
- Compose **>=2.24.4**, qui supporte `!override`. Sans ce remplacement, les anciens
  ports80/443 ou volumes nommés pourraient subsister.
- Images Core/Python construites avec le fork et l'image sandbox standard déjà
  disponibles sur ce même daemon. Aucun build/pull n'est fait par cet outil.
- SSH joignable du Gateway, serveur à clé connue et autorisation dédiée. Pour la
  clé du contrôleur, limiter `authorized_keys` à `restrict` et une commande forcée
  adaptée au socket rootless, par exemple `env -u DOCKER_CONTEXT
  DOCKER_HOST=unix:///run/user/1000/docker.sock /usr/bin/docker system dial-stdio`.
  Remplacer UID1000 par l'UID réel du **compte hôte**, pas celui de l'image. Ne pas
  transmettre de mot de passe, ni clé privée dans une commande ou un fichier `.env`.
  Le GET `/info` prouve l'identité atteinte ; il ne prouve pas à lui seul que toutes
  les restrictions du serveur SSH/`authorized_keys` sont appliquées.

Sources primaires : [Docker rootless](https://docs.docker.com/engine/security/rootless/),
[conseils rootless](https://docs.docker.com/engine/security/rootless/tips/),
[accès au daemon par SSH](https://docs.docker.com/engine/security/protect-access/).
Le fork réutilise son client/daemon Docker et OpenSSH ; aucun broker/framework ajouté.

## Génération explicite sans secret

Obtenir l'Engine ID par le socket rootless connu avec `docker --host
unix:///run/user/UID/docker.sock info --format '{{.ID}}'`. Cet ID n'est pas une clé.
Épingler également l'empreinte **publique** OpenSSH `SHA256:...` de la clé hôte ed25519
du contrôleur, obtenue/vérifiée hors bande. Le profil est version2 ; un ancien profil
sans cette empreinte est refusé et doit être régénéré explicitement, jamais converti.
La génération accepte uniquement un hôte DNS/IPv4, un compte SSH simple, des chemins
absolus simples et des ports hauts distincts ; elle refuse les URL et commandes.

```bash
python3 deploy/rootless.py generer \
  --racine /home/opsys-rootless/opsys-state \
  --ssh-dir /home/opsys-rootless/opsys-controller \
  --daemon-id ID_OBSERVE \
  --controleur controller.example.test --utilisateur opsys-rootless \
  --host-key-sha256 SHA256:EMPREINTE_PUBLIQUE_VERIFIEE \
  --uid 1000 --gid 1000 --sortie /chemin/nouveau-profil
```

La sortie neuve contient `profil.json`, `rootless.env` et `ssh-config`, modes privés.
Elle ne contient aucun secret et ne crée **ni bind ni credential**. La génération
annonce `runtime_verifie=false`. Aucun fichier existant n'est remplacé.

Préparer séparément une clé privée dédiée `id_ed25519`, le seul hôte contrôleur dans
`known_hosts` et le contenu exact de `ssh-config` sous le nom `config`. Ne pas faire
de `ssh-keyscan` une décision de confiance : vérifier la clé hôte hors bande.
Le préflight accepte uniquement des fichiers réguliers, sans symlink/hardlink,
propriétaire UID/GID1000 **dans le Gateway**, mode600, bornés16KiB et un répertoire
mode700. Le helper Node vérifie leur accès dans son namespace, sans ingérer la clé
privée ; seul le client OpenSSH la lit pour son authentification depuis Gateway.
La clé hôte publique/configuration sont lues et contrôlées depuis ce namespace.
Aucune clé copiée vers le compte hôte et aucun élargissement de ses permissions.

## Binds frais et reprise

Quatre répertoires frais sous la racine choisie : `core-state`, `core-auth`,
`opsys-data`, `litellm-config`. Le répertoire SSH est ailleurs. Tous sont privés700
et appartiennent à UID/GID1000 **du namespace rootless**, pas au nombre1000 hôte
par supposition. Le profil interdit la création implicite des chemins manquants.

Pour une **racine neuve vide** détenue par le compte rootless, l'opérateur peut
utiliser son Docker natif et une image locale déjà approuvée pour créer les seuls
répertoires frais. Exemple à adapter, exécuté manuellement après vérification du
daemon rootless ; il n'est jamais appelé par `rootless.py` :

```bash
docker --host unix:///run/user/UID/docker.sock run --rm --network none \
  --user 0:0 --mount type=bind,src=/RACINE_NEUVE,dst=/state \
  --entrypoint /bin/sh opsys:local -ec '
    for n in core-state core-auth opsys-data litellm-config; do
      test ! -e "/state/$n" && test ! -L "/state/$n"
    done
    for n in core-state core-auth opsys-data litellm-config; do
      mkdir -m 700 "/state/$n"
      chown 1000:1000 "/state/$n"
    done'
```

Le changement de propriétaire ci-dessus concerne **uniquement des dossiers que la
commande vient de créer**. L'opérateur doit préparer le répertoire SSH neuf et
ses trois fichiers, puis leurs propriétaires mappés/modes avec la même prudence.
Aucune conversion d'un ancien named volume, chown récursif, chmod global ni réparation
silencieuse. Pour un ancien UID/root/config sans mode local, arrêter la reprise,
prendre un snapshot et organiser une restauration assistée ; conserver les octets
et la provenance. Les préflights de l'entrypoint Python restent actifs.

## Compose et préflight

Parser uniquement, avec l'environnement de secrets géré par l'opérateur :

```bash
docker --host unix:///run/user/UID/docker.sock compose \
  --env-file deploy/.env --env-file /chemin/nouveau-profil/rootless.env \
  -f deploy/docker-compose.yml -f deploy/docker-compose.rootless.yml config --quiet
```

Cette commande ne démarre rien. Utiliser **ce même socket rootless et couple de fichiers**
pour toute opération ultérieure ; les helpers backup/restore actuels et `deploy/install.sh`
emploient seulement la base et ne sont pas raccordés au nouveau profil. La base
conserve readiness, bootstrap local/auth, dépendances, modèles natifs et UID1000
Compose. L'overlay impose `user: 1000:1000` aux deux services et remplace leurs binds,
active le Docker CLI, impose256PID/2CPU et remplace journald par `local` pour Python.
Les limites mémoire512MiB/2GiB existantes sont conservées ; no-new-privileges est
explicite aussi pour Python. Les images indépendantes/dev/installateur natif ne
changent pas d'utilisateur.
La jail fail2ban existante fondée sur `journalmatch=SYSLOG_IDENTIFIER=opsys` ne peut
pas être considérée active avec ce pilote `local` ; son raccord reste distinct.

Après un démarrage **distinct et explicitement autorisé**, obtenir les deux IDs
complets64hex avec Compose et lancer le préflight sur l'hôte :

```bash
python3 deploy/rootless.py verifier --profil /chemin/nouveau-profil/profil.json \
  --gateway-id ID_COMPLET_GATEWAY --python-id ID_COMPLET_OPSYS
```

L'opérateur doit être le compte rootless UID/GID du profil. L'hôte utilise son
socket privé pour `docker info/inspect`, puis deux **exec transitoires** sous
`1000:1000`, sans shell : Node dans Gateway, Python dans `opsys`. Les scripts et
commandes sont constants. Le helper Node reçoit un JSON de comparaison borné8KiB,
construit après validation du profil complet : config attendue, hôte et empreinte
publique. Ce sont des données contrôlées, pas des chemins/commandes libres ni clé
privée. Ils ne font que des
lectures ; aucune écriture durable, migration, réparation, create/up/build/pull/prune.
L'API exec crée deux processus : cette tranche n'est donc plus « zéro exec Docker ».

Chaque helper lit ses maps et son cgroup via `/proc/self/cgroup` puis
`/sys/fs/cgroup` **dans son propre namespace**, vérifie les limites noyau
`memory.max/pids.max/cpu.max`, les métadonnées/inodes des binds et l'accès réel du
UID1000. Le profil impose Config.User1000:1000 ; chaque helper lit `/proc/1/status`
et exige les quatre UID/GID réels/effectifs/sauvegardés/fs de PID1/init égaux1000.
Un init root est refusé même si le helper est lancé UID1000. Cela ne recense ni ne
qualifie chaque futur processus enfant/applicatif.

Le helper Gateway lit uniquement config/known_hosts publics et vérifie les
credentials privés dans son namespace. Il utilise le Docker CLI natif
`/usr/bin/docker --host ssh://opsys-rootless-control info --format '{{json .}}'`
avec HOME=/home/node, passwd home=/home/node, PATH fixe, variables Docker/TLS/context
et ssh-agent contrôlées et sans clés fournisseur héritées. Le client SSH utilise
le seul config privé exact. **Avant tout spawn Docker/SSH**, le helper compare la
configuration octet pour octet, le seul hôte de known_hosts et l'empreinte publique
épinglée. Config divergente/ProxyCommand, hôte ou clé divergents sont refusés sans
appeler le runner Docker. Une comparaison hôte après l'authentification serait trop
tardive et n'est plus le mécanisme principal. Le daemon atteint **depuis le Gateway** doit avoir le
même Engine ID rootless que celui observé par l'hôte. Les appels API du client natif
(info/version/ping) sont en lecture seule ; aucun shell SSH libre n'est demandé.

L'hôte fait seulement lstat des **racines** des binds et de leurs parents, jamais
une traversée de `.ssh`700 ni une ouverture de ses fichiers600 mappés. Les inodes
observés à l'intérieur doivent correspondre à ces racines ; les mappings1000 de
Python et Core doivent être identiques. Le préflight recontrôle les deux IDs,
PID et StartedAt après les probes ; remplacement/redémarrage donne un refus.

La capture hôte est bornée1MiB/15s, ou20s pour un exec dont le client Docker/SSH
interne est borné15s. Les sorties brutes/erreurs et secrets ne sont pas imprimés.
Un refus laisse `preflight_verifie` absent : jamais de succès partiel présenté vrai.
Cette observation n'est pas un verrou transactionnel ni une preuve de révocation ;
le Core natif revalide bootID/namespace et traduction avant création d'un sandbox.

Sans conteneurs vivants vérifiables, le préflight refuse ; génération seule ne vaut
pas validation. L'outil ne vérifie pas l'image sandbox, readiness HTTP, les dix
modules, un tour modèle ou l'application des options `authorized_keys`. Ces parcours
restent des critères runtime séparés, même si le préflight est vert. Les tests
locaux exécutent uniquement les helpers en processus Node/Python sur fixtures, et
un Docker CLI factice ; aucun Docker exec/daemon/SSH réel n'a été exécuté ici.

Les seuls ports publiés sont127.0.0.1:8080/8443 par défaut. Un edge ultérieur devra
gérer les ports publics/TLS et les origines attendues. Le Caddy existant peut tenter
ACME selon le domaine ; le profil ne prétend pas le rendre joignable ni émettre un
certificat sur ces ports. Il ne change pas CORS/auth pour permettre un navigateur
sur8443. Aucun accès public/VPS n'est validé par `preflight_verifie=true` ; la sortie
garde `runtime_sandbox_verifie=false` et `vps_qualifie=false`.
