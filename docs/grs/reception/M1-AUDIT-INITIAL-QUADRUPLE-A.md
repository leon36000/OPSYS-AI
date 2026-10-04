# Audit initial M1 — réception et voicemail

Date : 2026-09-30. Audit ciblé en lecture seule du dépôt partagé. Le statut de juin dans
`DEFINITION-PRODUIT.md` et l’audit M1 du 28 septembre sont des repères historiques, pas une mesure
de l’état actuel. Cet audit ne valide aucun canal fournisseur, aucun STT de production et aucun appel
réel.

**Actualisation du 3 octobre :** le [port privé d’import d’appel manqué](M1-APPELS-HOTE-2026-10-03.md)
est désormais intégré et qualifié par 205 cas dans une campagne de régression ciblée.
Il réserve la provenance de l’hôte et annule les écritures si le profil ou la base
change avant commit. Le raccord Core est intégré localement et qualifié par 164 tests
natifs, dont HTTP avec vrai validateur Twilio et clé fictive. Deux nouveaux scénarios
qualifient aussi le vrai transport Core→MCP HTTP Python→SQLite entre processus.
Le build/profilage, le recovery Gateway et tout fournisseur réel restent non qualifiés. Les sections datées du 30 septembre ci-dessous restent historiques. Le code
ultérieur possède aussi un marqueur de rejeu STT après import accepté; ses limites de
crash et de concurrence sont précisées dans la [recherche actuelle](../../research/REPRISE-2026-10-03/M1-BRIQUES-GITHUB-GITLAB-2026-10-03.md).

## Contrat produit examiné

La définition produit §7 demande que M1 capte et trace toute demande entrante, qualifie les leads,
organise le suivi et distribue les demandes. M1.5 prévoit transcription, résumé, extraction, lead et
tâche pour les messages vocaux. La progression vocale reste audit → voicemail → bac à sable → hors
heures → supervision → production contrôlée. Le produit interdit d’enregistrer sans politique de
consentement, de laisser une conversation sans prochaine action et d’inventer les champs manquants.
Une transcription incertaine doit mener à une vérification humaine.

Directives appliquées : lire les briques en place avant d’en ajouter; garder les calculs métier dans
les outils déterministes; distinguer le comportement codé, le comportement testé et le canal réellement
opéré; aucune donnée de client ni action externe dans cette tranche.

## État de la tranche upload — 2026-09-30

Le routeur `src/opsys/console/voicemail_ui.py` est monté dans l’application console et relié à la
navigation Réception. Il fournit `GET`/`POST /reception/voicemail`, appelle
`voicemail_stt.transcrire_et_importer`, puis passe l’import final par `console.metier.executer`.
Cette tranche livre l’acquisition **manuelle** d’un WAV déjà obtenu par l’opérateur; la réception
téléphonique ou l’acquisition automatique depuis un fournisseur restent absentes.

Preuve fournie par root : **50 tests passés**, soit 19 tests d’upload monté,
22 tests adaptateur/import durable et 9 tests console métier; 21,50 s, exit 0. JUnit externe
`m1-voicemail-mounted-final.xml` et log externe adjacent. Ruff sur les cinq fichiers du raccord et
`git diff --check` passent. Dans ces tests, le STT est exercé par un serveur fictif sur loopback et un WAV
fictif. Cela prouve l’upload via l’application montée et le parcours M1/M2, pas un fournisseur externe,
la qualité d’une transcription réelle, le téléphone ou une voix de production.

### Complément : STT local CPU réel sur un échantillon public

Une exécution distincte a réutilisé la route admin montée et son import canonique avec
faster-whisper 1.2.1, CTranslate2 4.8.2 et les modèles tiny/base épinglés, dans un environnement
d'essai extérieur au dépôt. Une seule phrase FLEURS `fr_fr/dev`, 14,46 s, a donné WER 30 % pour
tiny et 12,5 % pour base après normalisation identique; ces distances ont été recalculées
indépendamment. Le texte effectivement conservé dans le registre M1 a été comparé à la sortie
STT lors d'un passage supplémentaire du même échantillon : égalité exacte, rappel ouvert sans
envoi, aucun lead qualifié. La métadonnée de consentement était synthétique. Serveur et base
temporaires ont été fermés; aucun audio ni modèle n'a été ajouté au dépôt.

Les [preuves R19](../../research/R19-2026-09-30/README.md) conservent révisions, hashes, mesures et
attribution CC-BY-4.0 de FLEURS. PyAV 19 s'est révélé incompatible avec cette version de
faster-whisper; le pin de l'essai a été corrigé vers 16.1.0. Les notices du bundle FFmpeg/codecs
nécessitent qualification avant redistribution. Ce complément démontre une inférence CPU locale
et le raccord durable; il ne valide ni accent québécois, ni audio téléphonique/bruité, ni
consentement d'un vrai appelant, ni téléphonie, ni modèle par défaut de production.

Le parseur Starlette reçoit un flux borné à 25 MiB plus 64 KiB de champs/enveloppe; il accepte un seul
fichier WAV, des champs fermés et refuse doublons. L’acteur admin est relu avant parsing, après upload
et validation juste avant le transfert audio vers STT, puis de nouveau avant l’import final. Aucun
verrou DB ne reste ouvert pendant l’appel réseau. Le parseur peut déplacer un `SpooledTemporaryFile`
vers le disque temporaire après 1 MiB; Starlette le ferme sur les erreurs de parsing et FormData ferme
le spool après traitement. Aucun audio ne reste conservé par l’application. Le texte reçu va dans le
registre métier M1 selon ses règles actuelles et l’écran le marque « à vérifier par une personne »;
aucun score de confiance n’est calculé. Un rejeu de mutation retransfère néanmoins l’audio au STT avant
que l’import canonique idempotent ne restitue le résultat déjà conservé.

## Raccords présents

| Surface | Raccord réel observé | Limite actuelle |
|---|---|---|
| Import canonique d’appel | `departments/m01-front-office/src/m1_front_office/outils.py::importer_appel_manuellement` valide source, IDs, heure et E.164; importe `manque`/`voicemail` dans le registre durable, passe le texte à la qualification M1 si consentement explicite, publie un lead via le contrat M1→M2 et ouvre un transfert/tâche de rappel si nécessaire. Idempotence métier sur source/appel/statut; rejeu contradictoire refusé. | C’est un import d’événement manuel, pas une acquisition de fichier, de téléphonie ou un webhook fournisseur. Le registre reçoit le texte lorsqu’il est conservé; l’audio n’y est pas écrit. |
| Adaptateur STT | `departments/m01-front-office/src/m1_front_office/voicemail_stt.py::transcrire_et_importer` accepte des octets déjà lus, un suffixe et les métadonnées d’appel, puis utilise `m1_importer_appel_manuellement`. Consentement d’enregistrement obligatoire; consentement distinct requis pour un endpoint distant. Endpoint explicite par configuration; refus des redirections, bornes de taille/durée/réponse/transcription. Une absence ou panne STT importe le voicemail sans texte afin de garder le rappel. `valider_wav` contrôle l’en-tête/durée même sans configuration STT. | Le module ne stocke pas l’audio. Le diagnostic `/models` n’atteste pas le STT. Il n’ajoute pas un score de confiance STT ni une revue humaine structurée des mots extraits. |
| Console de réception | `src/opsys/console/frontoffice_marketing.py::creer_router` fournit `GET /reception`, `POST /reception/appels`, `GET /api/reception/appels`, `POST /api/reception/appels`, lecture/clôture des transferts. `voicemail_ui.py` est aussi monté dans `src/opsys/console/application.py` et lié à la navigation. Il appelle l’import canonique via le métier console avec une clé d’idempotence. | L’acquisition est manuelle d’un WAV; aucun fournisseur, webhook téléphonique ou flux d’appel manqué n’est connecté. |
| Contrôle console | `session_page` relit la personne active et `admin` ou `nathan_owner`; la mutation requiert CSRF. Le parseur multipart local et borné conserve intact le plafond global de 64 KiB. Le handler relit l’acteur après parsing/validation immédiatement avant STT, puis avant l’import métier final; l’import passe par `metier.executer`. | Un rejeu retransfère le média au STT avant l’idempotence de l’import final; l’import métier et le lead ne sont pas dupliqués. |
| Réception métier | `reception.py` valide SMS, courriel et formulaire, origine/contact, taille, horodatage, ID et STOP. `consentement.py` applique le fail-closed; `suivi.py` construit les prochaines actions sans horloge inventée; `plaintes.py`/`transferts.py` priorisent plaintes/urgences et demandent une clôture humaine. | Les fonctions de message ne constituent pas un transport audio. Les transcriptions manuelles ne prouvent pas la qualité d’un STT. |
| Core/canaux | M1 déclare SMS dans son manifeste; M1 et le core ont des raccords de canal documentés. R16 recommande de garder les transports OPSYS-CORE et d’ajouter les ponts métier manquants. | Ni téléphone, ni messagerie vocale fournisseur, ni webhook d’appel manqué n’est démontré par ce parcours console. L’extension `voice-call` ne doit pas être présentée comme un intégrateur M1 déjà branché. |

## Capacités déjà testées et absentes

Les tests existants les plus proches sont `departments/m01-front-office/tests/test_voicemail_stt.py`,
`test_import_appels_durable.py`, `test_reception.py`, `test_recevoir_message_canal.py`,
`test_consentement.py`, `test_suivi_conversation.py`, `test_transferts.py` et
`tests/test_console_metier.py`.

Les tests adaptateur montent un faux endpoint HTTP local et un WAV fictif. Ils vérifient import canonique,
lead M2, rejeu idempotent, redirection refusée, HTTP/JSON invalides, consentements absents, endpoint non
configuré, limites de taille/durée et absence d’audio/transcription au refus. Les 19 tests de
`tests/test_console_voicemail_upload.py` ajoutent le parcours monté, rôle/CSRF, limites multipart,
fermeture spool, refus externe sans consentement, révocation entre parsing/STT et entre STT/import,
rejeu/conflit et absence de fuite XSS/secrets. Les 9 tests `tests/test_console_metier.py` couvrent les
routes métier adjacentes. Le faux endpoint loopback ne prouve ni fournisseur réel, ni exactitude ou
confiance de la transcription.

Absences qui empêchent de revendiquer M1.5 en service : acquisition automatique depuis un fournisseur,
liaison stable avec l’événement/source téléphonique, STT/qualité sur audio québécois autorisé,
validation humaine des faits extraits, politique/rétention des fichiers et intégration téléphone,
retours fournisseur et reprise. Résumé et extraction ne sont pas des sorties structurées séparées dans
l’adaptateur actuel; la transcription alimente le pipeline de qualification existant.

## Tranche réalisée : upload console vers adaptateur

Le routeur est monté dans l’application et accessible depuis la navigation Réception. `GET` et `POST /reception/voicemail` permettent à un administrateur d’importer un WAV déjà obtenu par un moyen
autorisé, en réutilisant l’adaptateur STT et l’import métier canonique. Cette acquisition manuelle ne
branche ni téléphonie, ni webhook fournisseur, ni STT de production.

Le handler accepte un seul WAV et des champs fermés, plafonne le fichier à 25 MiB et conserve la
limite globale multipart de 64 KiB pour l’enveloppe/champs. Il vérifie l’en-tête et la durée même sans
configuration STT. L’identité admin est relue avant parsing, après parsing/validation immédiatement
avant le transfert STT, puis encore après STT et juste avant l’import métier. Aucun verrou DB ne reste
ouvert pendant l’appel réseau. L’identité, le rôle, l’URL STT et le chemin du fichier sont dérivés côté
serveur ou refusés s’ils sont fournis par le client.

Sans configuration/consentement requis, aucun audio ne part au STT et le parcours conserve le rappel
selon le contrat métier. L’interface présente le texte comme à vérifier par une personne; aucun score
de confiance n’est calculé. Le spool temporaire peut utiliser le disque au-delà de 1 MiB et est fermé
par le parseur/handler. L’audio n’est pas conservé par l’application. **État historique avant le
prototype de réutilisation** : le rejeu retransmettait l’audio au STT avant que l’import canonique
idempotent restitue l’événement; l’import n’était pas dupliqué, mais le coût et le transfert STT
pouvaient se répéter.

### Réutilisation d’un STT terminé — intégrée le 1er octobre 2026

Le chemin actif calcule, après validation courante de l’autorisation, des consentements et du WAV,
une empreinte opaque des octets, du format, des métadonnées, des consentements et paramètres STT.
La clé API contribue au digest final pour invalider sa rotation; la clé et son empreinte distincte
ne sont jamais écrites. Après un STT réussi et un import canonique accepté, un maillon privé de
complétion est ajouté au registre append-only M1 et lié à l’empreinte de cet import. Un rejeu ne
retourne que la réponse canonique persistée, et seulement si le marqueur, l’import, le hash WAV,
les métadonnées, les consentements et la configuration correspondent. Aucun audio ni texte n’est
recopié dans le marqueur.

Les imports antérieurs/manuels, résultats STT incertains, absence de
consentement, rôle retiré, empreinte absente ou différence de fichier ou de configuration produisent
une absence de cache et suivent le chemin actuel. Le marqueur est écrit après la transaction
d’import : une panne dans cet intervalle entraîne un nouvel appel STT. Deux uploads concurrents
peuvent tous deux appeler STT; aucun verrou ne couvre le réseau et aucune garantie exactly-once ou
reprise après crash n’est revendiquée. La promotion root porte sur cinq chemins de code et de test. La campagne intégrée du
1er octobre (10:58:48–11:00:03 UTC) passe 1 628 tests, sans échec/erreur/skip, en 74,344 s;
1 115 chemins sélectionnés sont identiques avant/après. Elle couvre tout M1, les uploads console,
les routes métier et la provenance des demandes humaines. Le serveur STT de ces tests est fictif :
aucun fournisseur réel ni coût monétaire n’est qualifié. Les preuves externes portent le nom
`m1-reutilisation-stt-integres-root-r1-2026-10-01` et conservent commande, JUnit et empreintes.

Preuve finale communiquée par root : **50 tests passés**, 21,50 s, exit 0; 19 tests d’upload monté,
22 adaptateur/import durable et 9 routes métier console. Rapport JUnit `m1-voicemail-mounted-final.xml`
et journal associés conservés hors dépôt. Ruff sur les cinq fichiers du raccord est vert; le dernier
changement après la suite était la suppression d’un import inutilisé. Le serveur STT utilisé par les
tests est fictif et local, avec audio fictif. Cela prouve le parcours monté et les refus testés, pas la
qualité d’une transcription réelle ni un canal téléphonique exploitable.

Empreintes SHA-256 des trois fichiers de cette tranche :

| Fichier | SHA-256 |
|---|---|
| `src/opsys/console/voicemail_ui.py` | `651d8dfb8151cb8e908eecff7ccd6376b35486501775f92c0ea419b720208dd6` |
| `departments/m01-front-office/src/m1_front_office/voicemail_stt.py` | `bd1a0114a2a77e44d35ffec6bd946e7e219661a7de3825aca83b35083cd3b895` |
| `tests/test_console_voicemail_upload.py` | `3dce9593a4cb0cdd0fe236bb8387d88aaa2126251cd3097db352819e258bc8b1` |

### Interfaces à réutiliser

- Métier : `m1_front_office.voicemail_stt.transcrire_et_importer` valide le WAV et les consentements;
  l’import console final passe par le callable étroit du routeur vers `console.metier.executer`, avec
  l’acteur vivant relu depuis la session.
- Identité et persistance : aucune identité n’est acceptée du formulaire; l’import canonique M1 et les
  mécanismes existants restent propriétaires du métier et de l’idempotence.
- Console : préserver `session_page`, `ecriture_api`, `securite.csrf_valide`, `_mutation_id` et
  `metier.executer` comme portes; créer un parseur fichier local à la route plutôt que modifier le
  parseur formulaire partagé ou son plafond global.
- Persistance : conserver l’import canonique M1 et les tables/files actuelles; pas de nouvelle table,
  de fichier média durable ou de copie parallèle de l’événement.

### Dépendance et risques

`python-multipart==0.0.32` existe déjà dans `requirements-runtime.lock.txt` et `uv.lock`; éviter une
nouvelle dépendance de parsing. Vérifier sa disponibilité dans l’extra console avant usage de
`Request.form()`. Aucun paquet STT n’est requis pour la tranche d’upload : le STT reste un endpoint
explicitement configuré. R16 qualifie faster-whisper MIT, mais CTranslate2, PyAV/FFmpeg et chaque
modèle ont des dépendances/licences propres; ne pas l’installer dans cette tranche. `ffprobe` est un
binaire externe et doit être qualifié avant tout support audio non-WAV.

Risques principaux : consentement d’enregistrement et consentement de transfert ne sont pas
interchangeables; un admin ne doit pas pouvoir déclencher un upload distant en cochant seulement le
premier. Un fichier multipart peut être temporairement spoulé sur disque par le parseur. Le multipart
et le contenu audio sont non fiables; extension/MIME ne prouvent pas un format WAV, il faut valider
l’en-tête WAV et la durée. L’idempotence actuelle inclut le contenu métier : une seconde transcription
différente d’un même appel sera un conflit; le chemin doit présenter ce conflit à la personne sans
écraser la première. Une transcription conservée entre dans le registre M1; rétention et accès
doivent rester ceux du registre métier, sans copie dans la console.

## Preuves et limites de test

La preuve finale montée couvre le parcours uploadé, les limites de multipart/WAV, CSRF et rôles,
révocation avant STT et avant import, adaptateur/import durable, tâche, rejeu, conflit et XSS. Le faux
endpoint local et le WAV fictif ne valident ni fournisseur, ni exactitude de transcription. Le rejeu
transfère de nouveau l’audio au STT avant le contrôle d’idempotence métier; ce comportement reste une
limite connue.

Absences qui empêchent de revendiquer M1.5 en service : acquisition automatique depuis un fournisseur,
liaison stable avec l’événement/source téléphonique, STT/qualité sur audio québécois autorisé,
validation humaine des faits extraits, politique/rétention des fichiers et intégration téléphone,
retours fournisseur et reprise. Résumé et extraction ne sont pas des sorties structurées séparées dans
l’adaptateur actuel; la transcription alimente le pipeline de qualification existant.

## Références

- [Définition produit §7 — M1](../../produit/DEFINITION-PRODUIT.md#7-les-10-départements)
- [Directives Nathan](../../produit/DIRECTIVES-NATHAN.md)
- [Audit M1 historique du 28 septembre et note du 30 septembre](../../departements/M1-audit.md)
- [Recherche M1 R16](../../research/R16-2026-09-30/recherche-m1.md)
- [Recommandations M1 R16 et limites de preuve](../../research/R16-2026-09-30/preuves/m1/recommendations.json)
- [Réception M1](../../../departments/m01-front-office/src/m1_front_office/reception.py)
- [Import canonique et outils M1](../../../departments/m01-front-office/src/m1_front_office/outils.py)
- [Adaptateur voicemail](../../../departments/m01-front-office/src/m1_front_office/voicemail_stt.py)
- [Route console actuelle](../../../src/opsys/console/frontoffice_marketing.py)
- [Montage et limites de corps console](../../../src/opsys/console/application.py)
- [Tests adaptateur STT](../../../departments/m01-front-office/tests/test_voicemail_stt.py)
- [Tests réception console](../../../tests/test_console_metier.py)
