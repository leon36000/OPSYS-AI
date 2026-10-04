# RPC HTTP privé de remise cron

Ce canal expose huit RPC HTTP pour joindre les propriétaires Python qualifiés. Le
[raccordement Core](CRON-RACCORDEMENT-HOTE-2026-10-03.md) est maintenant intégré partiellement.
Sa qualification reste distincte de celle de ce canal et d’une exécution autonome complète.

Le serveur monte les routes seulement si `OPSYS_CRON_OPERATEUR_JETON` est présent au démarrage.
Le jeton doit contenir au moins 24 caractères et être distinct des valeurs effectivement utilisées
par les audiences MCP publique et contexte. Sa valeur est capturée à la construction de l’application;
un redémarrage du serveur est requis pour la changer. Le middleware choisit l’audience par chemin :

| Route | Méthode | Audience |
|---|---|---|
| `/cron-operateur/v1/{profil_id}/preparer` | POST | `OPSYS_CRON_OPERATEUR_JETON` |
| `/cron-operateur/v1/{profil_id}/lire` | POST | `OPSYS_CRON_OPERATEUR_JETON` |
| `/cron-operateur/v1/{profil_id}/projeter` | POST | `OPSYS_CRON_OPERATEUR_JETON` |
| `/cron-operateur/v1/{profil_id}/accuser` | POST | `OPSYS_CRON_OPERATEUR_JETON` |
| `/cron-operateur/v1/{profil_id}/valider` | POST | `OPSYS_CRON_OPERATEUR_JETON` |
| `/cron-operateur/v1/{profil_id}/renouveler` | POST | `OPSYS_CRON_OPERATEUR_JETON` |
| `/cron-operateur/v1/{profil_id}/preparer-retrait` | POST | `OPSYS_CRON_OPERATEUR_JETON` |
| `/cron-operateur/v1/{profil_id}/accuser-retrait` | POST | `OPSYS_CRON_OPERATEUR_JETON` |
| `/mcp/runtime/{profil_id}` et `/mcp/contexte/{id}` | MCP existant | jeton contexte |
| `/mcp` | MCP existant | jeton public |

Le canal opérateur est HTTP JSON, pas MCP : aucun outil n’est ajouté aux catalogues MCP ou aux
configurations agent. Un jeton d’une autre audience reçoit 401. Les réponses portent
`Cache-Control: no-store`. L’authentification du bearer intervient dans le middleware avant la
lecture du corps ou l’appel d’une route; le credential serveur n’est pas une authentification
personnelle OPSYS et doit rester réservé au processus opérateur de confiance.

Au montage, le serveur ouvre la factory fournie sans migration ni écriture, vérifie que sa connexion
active est celle du stockage canonique OPSYS et que les deux URL désignent le même SQLite fichier.
Les bases mémoire, URI et alias non démontrables sont refusés. Chaque appel réutilise la connexion
de cette factory comme transaction extérieure; le propriétaire ouvre alors son point de sauvegarde
sur cette même connexion. Avant de lire le corps, le handler compare encore l’URL canonique à celle
capturée. Si `OPSYS_BASE_URL` change après montage, l’opération refuse; redémarrer le serveur après
tout changement de configuration. Ce garde exige la factory transactionnelle OPSYS qui fixe
`stockage.connexion_courante()`; il ne qualifie pas un stockage SaaS ou une factory arbitraire.

Le segment `{profil_id}` fixe le profil transmis à `ProprietaireCron`; le corps ne peut pas choisir
un autre profil. Les corps sont des objets JSON UTF-8 `application/json`, sans transfert encodé,
compression, doublons de clés, champs inconnus ni dépassement de 20 KiB. `par` et `role` sont
refusés. Les erreurs de contrôle ne révèlent ni capacité, ni empreinte, chemin de base, ni exception
interne. L’authentification HTTP reçue précède toute lecture du corps et toute ouverture DB par
requête; la validation de configuration au montage est un contrôle distinct de l’hôte.
Le cadrage HTTP exige un seul en-tête `Authorization`, aucun doublon de `Content-Type` ou
`Content-Length`, aucun encodage de contenu/transfert, une longueur décimale d'au plus cinq chiffres
et l'égalité entre longueur déclarée et corps reçu.

`preparer` exige exactement ces clés :

```json
{
  "intention_id": "<id>",
  "empreinte_capacite": "<sha256 hex>",
  "declaration": {},
  "epoch_attendue": 0,
  "revision_native_attendue": null,
  "lease_secondes": 30
}
```

`revision_native_attendue` est toujours présente dans le transport, mais peut valoir `null` parce
que le propriétaire Python autorise explicitement l’absence de révision native initiale. La réponse
est le plan privé du propriétaire, sans capacité secrète ni empreinte. L’intention, l’instance, le
demandeur actif et la déclaration canonique sont revalidés par le propriétaire durable.

`accuser` exige exactement `intention_id`, `capabilite`, `epoch`, `lease_epoch`, `job_id`,
`config_revision` et `declaration`; les arguments sont transmis au propriétaire sans attribution
de rôle ou d’identité humaine par le transport. La capacité apparaît uniquement dans le corps de
requête protégé et n’est ni renvoyée, journalisée ni incluse dans un diagnostic.
La `config_revision` Core est une empreinte `sha256:` suivie de 43 caractères Base64URL sans
padding, produite par `hashCronJobDefinition`. Les anciennes révisions entières restent stockées
dans leurs colonnes historiques et ne sont jamais converties ni comparées numériquement aux
empreintes. `revision_native_attendue` désigne la préimage attendue du CAS que Core doit effectuer;
`config_revision` de l'ACK désigne la cible et peut être différente. Python compare exactement
ces chaînes au rejeu/à la validation, sans prétendre exécuter le CAS natif. Une rotation explicite
peut fournir une nouvelle préimage d'un autre format; un changement de type sans rotation refuse.
Le propriétaire valide le format complet à chaque lecture; les CHECK SQL portables ne contrôlent que
longueur, préfixe et symbole final. Le DDL est compilé hors ligne pour PostgreSQL, sans qualifier
une migration PostgreSQL réelle.

`valider` exige exactement `intention_id`, `capabilite`, `epoch`, `job_id`,
`config_revision` et `declaration`. Le propriétaire relit le demandeur actif, le mandat,
la révision du profil et l’ACK durable. Une réussite retourne seulement
`{"ok":true,"resultat":{"valide":true}}`, sans mutation du journal ou de l’autorité.
Les tests HTTP vérifient ce caractère sans écriture, puis le refus après retrait du rôle
ou du mandat. La vérification est appelée par le consommateur Core intégré; son parcours complet reste à qualifier.

`renouveler` exige exactement `intention_id`, `capabilite`, `epoch`, `lease_epoch`,
`declaration` et `lease_secondes`. Il renouvelle une préparation expirée selon les bornes
et compteurs du propriétaire, avec au plus trois prises par époque, préparation initiale comprise. Le rejeu exact d’un
renouvellement encore actuel ne produit pas un second audit. Il ne réinitialise pas une
autorité perdue et ne réarme pas un job natif.

Qualification du 3 octobre : 21 tests HTTP, 57 tests du propriétaire cron et 24 tests
M03 passent dans une campagne de 102 cas. Ruff passe sur les quatre fichiers concernés
après correction de forme; le résultat initial Ruff reste conservé avec le résultat final.
[Preuve ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CRON-OWNER-RPC-M03-P80-QA-ROOT-r1/execution-r1/VERIFICATION-ROOT.json).

Ce canal ne prouve pas à lui seul qu’un job natif est encore actuel et ne bloque pas un stream.
L’intégration Core contient maintenant capture privée, CAS natif et vérification avant provider.
Son état de qualification est détaillé séparément; les tests HTTP ne prouvent pas cette chaîne complète.

## Retrait durable : propriétaire Python qualifié

`preparer-retrait` exige exactement `intention_id`, `capabilite`, `epoch`, `declaration`,
`job_id` et `native_revision`. `accuser-retrait` ajoute `source_hash` et `receipt_id`.
Les paramètres de requête, champs inconnus et audiences incorrectes sont refusés.
Ces deux opérations vérifient aussi que le credential opérateur dans l'environnement
est toujours celui capturé au montage; une rotation exige un redémarrage.

Le propriétaire lie le retrait à une commande humaine durable exacte de retrait ou
de remplacement. La possession d'un ancien identifiant d'intention ne suffit pas.
L'ancien auteur peut avoir perdu ses droits; l'opérateur de confiance courant reste
nécessaire. La préparation révoque l'autorité d'exécution et laisse l'intention
`a_retirer`. Seul un ACK exact produit le reçu terminal `retiree`. Un ACK répété
conserve son résultat et n'ajoute pas de seconde trace.

La migration additive `0023` conserve ces reçus sans effacer intentions, grants ni
journal. Sa rétrogradation refuse de supprimer des reçus existants. Le SHA natif de
retrait désigne le job désactivé; il peut différer du SHA de l'ACK d'activation. Le
contrôleur natif doit démontrer ce CAS et la suppression dans son propre stockage.
Python ne constate pas lui-même cette suppression : ce protocole est réservé à
l'hôte opérateur de confiance, avec capacité, époque et déclaration liées.

Une nouvelle commande humaine après préparation change l'ancrage et fait refuser
l'ancien ACK. Aucun rapprochement silencieux de ces deux commandes n'est ajouté.
La reprise après DELETE natif exige un reçu chiffré durable côté Core; ce raccord
est encore en préparation et n'est pas qualifié par les tests Python.

La campagne complète passe **185 cas** dans sept fichiers, dont 17 cas du nouveau
propriétaire et cinq de révisions natives. SQLite, migration et HTTP sont réels;
la preuve de suppression native est **simulée explicitement**. Ruff passe sur six
fichiers, les 587 sources restent identiques et aucun nouvel OOM ni processus du
run ne subsiste. Voir [preuve ROOT](../research/REPRISE-2026-10-03/preuves/cron-retrait-python/VERIFICATION-ROOT.json)
et [JUnit complet](../research/REPRISE-2026-10-03/preuves/cron-retrait-python/pytest.xml.gz).

## Sauvegarde Git des autorisations privées cron

Pour une sauvegarde **globale** avec `--exclude-secrets`, le codec conserve la
structure du sidecar `cron_job_runtime_authorities`, vide son autorisation et son
empreinte, puis inscrit `recovery_required=1`. Il désactive seulement les tâches
qui possèdent ce sidecar, dans leurs colonnes SQL et leur JSON. Les tâches
historiques sans sidecar conservent leur statut. Les événements de diagnostic
dont le scope commence par `cron.quarantine:` sont omis, car ils peuvent contenir
l'ancien JSON privé; les autres diagnostics restent présents. Le manifeste
énumère les tables projetées dans `redactedTables`, tout en acceptant les anciens
manifestes qui n'ont pas ce champ.

Un JSON de tâche mal formé, une ancienne autorité privée encore embarquée dans
ce JSON ou un scope de diagnostic non textuel fait refuser l'export expurgé.
Aucun manifeste valide n'est produit. Le codec lit la base sans modifier les
autorisations ni les statuts d'origine. Il ne nettoie pas les sauvegardes anciennes.

La campagne native r14 vérifie huit cas, dont la restauration réelle dans SQLite
et le refus d'admission après réactivation forcée d'une tâche privée sans son
autorisation. La campagne r16 vérifie séparément cinq cas du vrai garde dans son
groupe natif cron, avec plugins désactivés pour cette qualification du helper. Ces preuves
ne constituent pas un parcours complet du scheduler
jusqu'au provider. Les refus mémoire intermédiaires sont également conservés.
[Sauvegarde/restauration r14](/workspace/poursuite-opsys-2026-10-02-r1/CRON-SNAPSHOT-REDACTION-ROOT-r1/green-r14/execution/VERIFICATION-ROOT.json),
[admission r16](/workspace/poursuite-opsys-2026-10-02-r1/CRON-SNAPSHOT-REDACTION-ROOT-r1/helper-r16/execution/VERIFICATION-ROOT.json).

Sans `--exclude-secrets`, le codec conserve les autorités et diagnostics en
JSONL, sans chiffrement ajouté par l'exporteur. Le sidecar OPSYS utilise maintenant
une enveloppe AES-256-GCM liée au stockage, au job et au namespace, avec clé locale privée
extérieure aux racines protégées. Six cas natifs SQLite passent avec les plugins du groupe
cron actifs : contrôle de clé, altération et liaison, conservation du ciphertext en
récupération, révocation explicite.
[Preuve native ROOT](/workspace/poursuite-opsys-2026-10-02-r1/NATIVE-WORKER-AVATAR-ROOT-r21/execution-archive-r28/VERIFICATION-ROOT-r29.json).
Cette protection ne chiffre pas rétroactivement les valeurs historiques en clair, ne qualifie
pas un stockage VPS installé et ne fournit pas le consommateur final Core.
Traiter les sauvegardes complètes actuelles et anciennes
comme des données privées. Cette qualification ne couvre pas les exports par agent.

## Demandes humaines dans le tableau de bord

La fiche `/agents/{profil}` contient une action pour préparer une demande cron avec
un fuseau IANA explicite, et une action pour demander le retrait des intentions.
Les POST sont `/agents/{profil}/declencheurs/cron/demander` et `/retirer`.
Ils appellent `agents_declencheurs.demander/retirer`; ils ne sont pas des RPC du canal
opérateur et utilisent la session personnelle et le CSRF de la console.

Le formulaire ne peut fournir ni acteur ni rôle; les champs inconnus, doublons et UTF-8
invalides sont refusés. La révision attendue est obligatoire. Le propriétaire relit
l’identité active et le profil dans sa transaction; une demande rejouée utilise son
idempotence existante. Le retrait reste possible après désactivation du profil avec
sa nouvelle révision. La garde SQLite partagée exige que la base de la console soit
exactement la base canonique utilisée par le propriétaire : deux bases divergentes
sont refusées sans écrire d’intention, de commande ou d’audit dans l’une ou l’autre.

Le message de réussite indique « demande préparée » ou « retrait demandé ».
Aucune tâche Core n’est créée, activée ou exécutée. Les deux actions demandent une
confirmation explicite. Le [raccordement hôte](CRON-RACCORDEMENT-HOTE-2026-10-03.md) est écrit;
son parcours natif complet reste à qualifier.

Les trois parcours console, 46 cas du propriétaire des intentions, 21 HTTP privés et
20 de la console CFO passent : **90 cas uniques**, zéro échec/erreur/skip. Ruff passe
sur les cinq fichiers modifiés après correction de l’ordre des imports. La première
fixture de connexion et la première sortie Ruff sont conservées pour audit.
[Preuve ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CONSOLE-CRON-INTENTIONS-ROOT-r1/execution-r2/VERIFICATION-ROOT.json).
Cette qualification utilise TestClient et de vrais SQLite temporaires; elle ne prouve
pas le rendu dans un navigateur déployé ni une exécution provider.

## Lecture et projection privées — 3 octobre

`lire` accepte exactement `{}` et retourne dix intentions au plus du profil et de
l’instance actuels, hors intentions retirées. `total`, `retournes` et `omis` rendent
la troncature visible. Les seules métadonnées individuelles sont l’ID d’intention,
l’état, la révision du profil et le fuseau. La lecture reste possible pour réconcilier
un retrait après désactivation; elle ne vaut pas autorisation d’exécution.

`projeter` accepte exactement `{"intention_id": "…"}`. Le propriétaire relit l’acteur
stocké, le profil, la révision, les outils et le mandat. Il rend la déclaration native
actuelle, avec `execute:false`, sans capacité ni commande CLI. Un retrait donne
`native:null` et une instruction de réconciliation. Les deux routes refusent les
paramètres de query, champs supplémentaires, doublons et autres audiences; elles
n’écrivent ni remise ni audit d’action.

**158 cas uniques passent**, sans échec, erreur ou saut, avec Ruff sur les trois
fichiers touchés et 573 sources stables. Ils comprennent les propriétaires de
mandats et de remises, le transport HTTP et les consoles humaines/CFO. Les campagnes
90 et 102 restent historiques et ne s’additionnent pas à cette sélection.
[Qualification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CRON-LECTURE-PROJECTION-ROOT-r1/execution-r1/VERIFICATION-ROOT.json).
Le producteur Core et la validation avant chaque dispatch provider restent ouverts.
