# PDF natif facultatif dans l'image Python

L'overlay `deploy/docker-compose.ingestion-pdf.yml` prépare le même service `opsys`
avec bubblewrap et le verrou complet `requirements-ingestion-pdf.lock.txt`. Il ajoute
seulement pypdf 6.19.0 aux dépendances runtime existantes, sans changer leurs versions
ou hashes. L'image standard garde le verrou runtime et n'installe pas bubblewrap.
Cette option ne fournit ni OCR, ni interprétation comptable, ni écriture financière.
Le [contrat PDF](../architecture/FUSION-PDF-NATIF.md) conserve ses limites.

**État R48 après diagnostic R3 : contrats locaux et doubles ; création de namespace
refusée sur le profil Docker testé.** Aucun build ou conteneur de l'image produit
`opsys:ingestion-pdf-local` n'a été exécuté. Le 2026-10-02, ROOT a testé une QA
hybride sur la base officielle Python 3.12.14, avec 54 distributions projetées et
bubblewrap 0.12.0 fourni explicitement hors image. Le diagnostic R3 a repris une
seule extraction du document public fixe de 233 octets, sous UID1000, seccomp
Docker builtin et sans capacité ajoutée. Les gardes de chemins ont accepté la
commande ; le processus a démarré puis quitté avec le code 1. Bubblewrap signale
« No permissions to create a new namespace » ; l'exécuteur existant remonte le refus
`PDF_ISOLATION_INDISPONIBLE`. Les 210 octets de stderr ont été recueillis sans
troncature ; aucun errno ou syscall précis n'a été identifié.

Le nettoyage QA a réussi ; la baseline et les compteurs OOM étaient inchangés. Les 32 sources
du périmètre courant étaient stables, dont 30 effectivement chargées ; ce résultat
n'affirme pas une stabilité des 139 sources courantes. Le gate PDF et la comparaison
des namespaces n'ont pas été atteints. L'ingestion PDF est **indisponible sur ce
profil Docker** ; l'overlay reste une préparation opt-in, sans compatibilité
qualifiée. Les preuves PDF/SQLite R28 sur l'hôte restent distinctes. Installation
VPS, pile complète et image produit restent à vérifier réellement.

Le build de l'image Python utilise `deploy/Dockerfile.dockerignore`, qui a priorité
sur le fichier global. Il reprend **toutes** les règles globales de secrets/caches
dans le même ordre, puis exclut `core/`, `docs/research/` et les dossiers `.artifacts`.
Le Core garde son build séparé et ses exclusions propres. `src/`, `departments/`,
les manifestes, SOUL/skills, les contrats et ressources M7, `docs/compliance/` et
les scripts/configurations de déploiement restent disponibles à l'image Python.
Les politiques « photos » de M1/M3 sont lues depuis `docs/compliance/` au runtime ;
exclure toutes les docs ferait donc perdre une ressource métier.

Cette réduction de contexte ne mesure pas la taille de l'image ni le pic disque
du build. Avant de construire, réserver aussi la base Python, les paquets système,
les dépendances décompressées et les couches/cache du builder. Avec un stockage
`vfs`, les copies de couches peuvent dépasser largement le contexte retenu.
Un contrôle des règles et une projection Python sur l'hôte ne qualifient pas le
transport Docker, le build ou l'isolation bubblewrap dans l'image.

## Préconditions et secrets

Ce pilote exige Linux et la base entreprise SQLite. Le préflight vérifie la
configuration du stockage réel (`OPSYS_BASE_URL`, SQLite par défaut) ; un backend
PostgreSQL pour cette base est refusé. `OPSYS_DATABASE_URL` désigne la mémoire
d'entreprise séparée : sélectionner son profil ne prouve pas le dialecte entreprise.

L'opérateur fournit une **clé externe existante AES-256 de 32 octets en base64**
via son dispositif de secrets. Ni cet overlay ni l'installateur ne créent ou
remplacent une clé d'ingestion. Ne pas utiliser un jeton de console ou de fournisseur.

Préparer un fichier privé **extérieur au dépôt et au contexte de build**, détenu
par le compte opérateur, mode600 avec un parent privé. Le fichier et son parent
doivent aussi être extérieurs aux racines canoniques de lecture du worker : `/usr`,
les préfixes Python, leurs bibliothèques et le fichier worker. Le chargeur refuse
une référence située dans ces montages avant d'ouvrir la clé, même avec les bons
droits Unix. Le client Compose doit pouvoir lire le fichier ; le montage des clés
reste distinct du worker. Son contenu suit ce format, où la valeur
est fournie par le dispositif de secrets, jamais par cet exemple :

```dotenv
OPSYS_INGESTION_CLE_REFERENCE=OPSYS_CLE_INGESTION_V1
OPSYS_CLE_INGESTION_V1=<CLE_BASE64_EXTERNE_DE_32_OCTETS>
```

La référence par défaut `OPSYS_INGESTION_CLE` reste prise en charge. Ce fichier est
réservé aux références/clés d'ingestion ; ne pas y placer des variables fournisseur,
de stockage ou d'authentification. Il est passé à `opsys` seul, jamais au Gateway,
au serveur d'embeddings ou à un modèle. Ne pas publier la sortie complète de
`docker compose config`, qui résout les secrets ; utiliser `config --quiet`.

Chaque lot retient sa référence d'origine. Une rotation est une opération distincte
et explicite : conserver les anciennes variables/clés pour relire et reprendre les
anciens lots. Sauvegarder la base et les clés **séparément**, et conserver leurs
références. Les archives de volumes ne sauvegardent pas ce fichier externe ; une
restauration sans les clés ne peut pas déchiffrer les lots. Le préflight ne prouve
pas la présence de toutes les anciennes clés ni une restauration complète.

## Activation explicite à qualifier

Déclarer uniquement le chemin du fichier privé dans l'environnement de Compose
(par exemple dans le fichier opérateur `deploy/.env`, sans valeur de clé) :

```dotenv
OPSYS_INGESTION_ENV_FILE=/etc/opsys/private/ingestion.env
```

Depuis la racine du dépôt, les commandes de préparation suivantes sont proposées
pour une fenêtre de qualification autorisée ; elles n'ont pas été exécutées ici :

```bash
docker compose --env-file deploy/.env \
  -f deploy/docker-compose.yml -f deploy/docker-compose.ingestion-pdf.yml config --quiet
docker compose --env-file deploy/.env \
  -f deploy/docker-compose.yml -f deploy/docker-compose.ingestion-pdf.yml build opsys
docker compose --env-file deploy/.env \
  -f deploy/docker-compose.yml -f deploy/docker-compose.ingestion-pdf.yml up -d opsys
```

Le tag distinct `opsys:ingestion-pdf-local` conserve l'image standard. Garder le
même ensemble d'overlays/env-files pour les opérations suivantes. Avec le
[profil rootless candidat](SERVEUR-ROOTLESS.md), ajouter son fichier/env-file et
garder le daemon rootless prévu ; ce guide ne provisionne pas le daemon ou SSH.
L'installateur `deploy/install.sh` et ses helpers emploient la base seule : ils
n'activent pas cette option, et une relance peut recréer le service sans celle-ci.

La sonde opt-in réutilise readiness R45 puis le worker existant sur un document
fixe de zéro page. Le refus exact `PDF_PAGES_BORNEES` confirme l'import du parseur,
ses limites et l'exécution isolée. Aucun document métier n'est admis en base ou
parsé hors du worker, et aucun appel modèle n'est effectué. Le worker conserve
son délai mural de 15 s ; le healthcheck opt-in est borné à 30 s.

Un chemin de secrets absent/inaccessible fait échouer Compose. Une clé absente
avec les contrôles runtime réussis donne 3, en attente de configuration ; une clé
invalide, un backend non qualifié, une dépendance absente ou une isolation refusée
donnent 1. Toute erreur runtime prime sur une attente opérateur. `healthy` atteste
ces contrôles, sans certifier chaque futur document, les anciennes clés ou un VPS.

**Installer bubblewrap ne suffit pas** : Docker/seccomp, le noyau et les namespaces
utilisateur peuvent interdire `--unshare-all`. Le préflight doit alors refuser
explicitement. Ne pas ajouter `privileged`, `SYS_ADMIN`, un seccomp désactivé ou
un parseur hors isolation pour obtenir un état vert. Cette compatibilité doit
être observée sur l'image réelle non-root et le daemon retenu avant publication
d'une revendication d'usage. La mémoire 512 MiB de la base Compose reste conservée ;
la consommation cumulée MCP/console/worker dans cette image reste à mesurer.

Le profil standard Moby 28.4 conditionne les créations de namespaces par `clone`
et `unshare` à `CAP_SYS_ADMIN`. R3 observe CapBnd sans cette capacité, CapEff nul
et Seccomp=2 ; son diagnostic situe le refus dans la création de namespace
bubblewrap, après les gardes de chemins et le spawn. Cela étaye l'incompatibilité
avec le profil testé, sans isoler le syscall, son errno ou la responsabilité exacte
du filtre plutôt que d'une restriction du noyau. Le profil rootless ne garantit
pas qu'un namespace imbriqué soit autorisé.

Le **même moteur Python natif sur Linux** dispose maintenant d'un raccord opt-in
dans `install/install.sh` : `--avec-ingestion-pdf` ajoute l'extra verrouillé,
`--sans-ingestion-pdf` le désactive. Le choix est conservé entre les installations
et reste désactivé par défaut. Bubblewrap système doit déjà être disponible ;
l'installateur ne provisionne ni paquets privilégiés ni nouveau daemon. Désactiver
le raccord ne supprime pas les données ou les clés.

Définir `OPSYS_INGESTION_ENV_FILE` avec le **chemin absolu seul** du fichier privé
existant. Python lit les clés ; le shell ne charge pas leur contenu et le Core,
`metier.json` et le Gateway ne reçoivent pas leurs valeurs. Aucune création ou
rotation implicite de clé n'est prévue. Les anciennes références restent requises
pour les anciens lots. `deploy/readiness_pdf.py --pdf-only` réutilise `verifier_pdf()`
sans imposer le gate Compose. L'initialisation, les migrations et les services
utilisateur existants restent le parcours natif. `/sante` mesure la vivacité du
moteur, pas la disponibilité PDF.

La [qualification ROOT du 2 octobre](../research/PDF-NATIF-GEOMETRIE-2026-10-02/README.md)
conserve **56 tests ciblés sans échec ni skip**, dont les contrats d'installateur
avec doubles, et une sonde native réelle sous UID1000 dans l'environnement cloud.
Cette sonde observe les codes **0 / 3 / 1** : clé fictive valide et worker isolé,
clé absente après réussite du worker, fichier de clé aux droits invalides refusé
avant le worker. Le contrôle utilise le document public de zéro page ; aucun
document client ni base métier n'est créé. Les clés de fixture sont retirées.

Ce résultat qualifie le gate natif sur cet hôte, **pas une installation complète**
de l'installateur, les services d'un VPS neuf, TLS ou l'image produit Docker.
Le refus Docker R3 ci-dessus reste valable ; aucun profil de sécurité n'a été
assoupli pour le contourner.

Le Docker sandbox des agents Core est un mécanisme distinct. Cette option PDF
ne fournit ni son Docker CLI, ni son daemon, ni son image sandbox, ni TLS. Les
`/healthz` statiques de Caddy attestent seulement la vie de l'edge ; le parcours
authentifié, les dix départements et un tour agent sandboxé restent séparés.
