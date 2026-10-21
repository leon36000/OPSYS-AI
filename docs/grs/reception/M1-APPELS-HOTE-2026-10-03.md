# M1 — port privé d’import des appels manqués

État au 3 octobre 2026 : **port Python intégré et qualifié dans la portée ci-dessous;
raccord Core intégré, tests natifs et transport Core→Python HTTP qualifiés; build et
parcours téléphonique bout en bout encore non qualifiés**. M1 reste partiel. Cette tranche réutilise
l’import, le registre et le transfert humain existants; elle ne crée aucune inbox parallèle.

## Parcours intégré

Le serveur MCP expose `opsys_runtime_importer_appel_manque` uniquement sur
`/mcp/runtime/<profil>`, avec le jeton interne de contexte. L’identité du profil vient
de la route; aucun argument ne permet de choisir un autre agent. La capacité est absente
du catalogue public des départements. Le Core conserve son refus des namespaces privés
dans les outils visibles du modèle.

Les six arguments sont fermés : `provider`, `event_id`, `call_id`, `occurred_at`,
`telephone`, `revision_profil`. Les fournisseurs autorisés sont `mock`, `twilio`,
`telnyx`, `plivo`; `mock` sert aux essais. L’identifiant ne peut contenir de caractère
de contrôle et est borné à 200 caractères. L’heure doit être un RFC3339 valide avec
fuseau; elle est normalisée en UTC. Le téléphone doit respecter le contrat E.164 du
propriétaire M1, avec des chiffres ASCII. Le propriétaire de l’hôte refuse le mode
registre en mémoire, même si la route possède une connexion DB valide.
Aucun média, texte de transcription, statut libre ou source libre
n’est accepté.

Avant l’import, le serveur vérifie dans la base canonique : profil actif, département M1,
révision actuelle et droit `m1_importer_appel_manuellement`. Ce droit autorise le
propriétaire commun de l’import; le port privé n’est pas un nouvel outil du modèle.
L’import impose `voice-call:<provider>`, `manque`, `appel_operateur` et une provenance
de contact propre à l’hôte. Il réutilise la conversation et le rappel M1 existants,
sans appeler de LLM ni émettre de communication externe.

L’ACK fermé contient seulement `ok`, `source`, `call_id`, `status`. Il ne sort qu’après
commit. Profil et base canonique sont revérifiés après les effets M1, dans la même
transaction. Un retrait de droit, une rotation de base ou un résultat M1 non conforme
annule l’unité entière. Les refus retournent `import_appel_refuse`, sans exception
brute ni coordonnées.

## Provenance et rejeu

L’import manuel refuse désormais le namespace réservé `voice-call:`. L’empreinte
métier de l’hôte inclut le domaine `hote_voix_v1`; l’empreinte historique des imports
manuels ordinaires reste inchangée. Un ancien import manuel revendiquant la même
source ne devient donc pas un fait de l’hôte : il provoque un conflit, conservé pour
examen humain, plutôt qu’une reclassification silencieuse.

Le rejeu porte sur source/appel/statut et contenu métier. Un nouvel `event_id` de
transport et un fuseau équivalent ne créent pas de rappel supplémentaire. Un téléphone
ou une heure différente est contradictoire. Les enregistrements historiques restent
conservés. Cette preuve SQLite séquentielle ne démontre pas une livraison exactement
une fois entre plusieurs processus PostgreSQL.

## Qualification ROOT

[Reçu et capsules conservées](../../research/REPRISE-2026-10-03/preuves/m1-appels-hote-durable-r2/VERIFICATION-ROOT.json) :
**205 cas passés, zéro échec, erreur ou skip**, neuf fichiers complets; Ruff sur les
cinq chemins modifiés et `opsys-metier verifier` réussis. Sources gelées : 677 chemins,
9 488 034 octets, inchangés pendant la campagne finale. Le reçu porte les mesures exactes;
aucun compteur OOM n’a augmenté et aucun processus du groupe n’a survécu.

Le client MCP SDK exerce la route via HTTP ASGI; le fichier de régression MCP existant
exerce aussi ses serveurs HTTP natifs. Les appels, téléphones et profils sont fictifs.
Les assertions de rollback comparent toutes les chaînes de registre, outbox, reçus,
clés, mutations et profils. Des compteurs prouvent que le propriétaire a effectivement
écrit avant le retrait simulé ou le faux ACK. Le rejeu compare aussi cet état complet.

La campagne RED conservée `r5` avait 116 succès et trois échecs : deux défauts de
provenance démontrés, plus un harnais tentant de redémarrer un gestionnaire MCP à usage
unique. Les erreurs de style et de Host des campagnes précédentes sont conservées.
La correction du harnais respecte la protection DNS native; elle ne l’assouplit pas.
Les nombres des campagnes qui se recouvrent ne s’additionnent pas.

Une seconde campagne RED `r8`, conservée dans les nouvelles capsules, démontre deux
autres défauts : chiffres non ASCII acceptés dans E.164 et ACK produit par un
propriétaire M1 en mémoire. La campagne finale `r9` corrige ces cas et passe 205 tests.
La qualification antérieure de [203 cas](../../research/REPRISE-2026-10-03/preuves/m1-appels-hote/VERIFICATION-ROOT.json)
reste historique; elle précède ces corrections.

Fichiers :

- [Route privée](../../../src/opsys/serveur_mcp.py).
- [Propriétaire d’import](../../../departments/m01-front-office/src/m1_front_office/outils.py).
- [Provenance du transfert](../../../departments/m01-front-office/src/m1_front_office/transferts.py).
- [Tests du port privé](../../../tests/test_runtime_import_appel_manque.py).
- [Régression MCP HTTP](../../../tests/test_serveur_mcp_http.py).

## Raccord Core intégré et qualification native

La [recherche GitHub/GitLab](../../research/REPRISE-2026-10-03/M1-BRIQUES-GITHUB-GITLAB-2026-10-03.md)
a conduit à réutiliser `voice-call` du fork possédé. Le candidat `r6` est intégré
localement, puis corrigé et qualifié par ROOT. Les anciens candidats `r2`/`r3`
restent historiques : tests inactifs, révocation tardive et rechargements successifs
insuffisamment fermés avaient été relevés. Leurs
[48 capsules et préimages](/workspace/poursuite-opsys-2026-10-02-r1/M1-TRANSPORT-DECISION-ROOT-r1/core-candidats-r2-r3/REVUE-ROOT.json)
sont conservées. Les corrections récentes ne reconstruisent ni la téléphonie ni M1.

`missedCallIngress` est désactivé par défaut. Le service déclare un contrat V1 et
l’hôte fournit une opération fermée seulement au service `voicecall` du plugin
`voice-call` bundled. Copier le descripteur dans un plugin workspace ne donne aucun
accès. La cible est le profil admis de l’agent; serveur et outil MCP sont imposés.
Les [types et leur contrat](../../../core/extensions/voice-call/README.md)
sont exposés par les sous-chemins SDK existants, sans nouveau barrel de compatibilité.

La signature est vérifiée dans le transport. Le raccord exige un appel entrant connu,
jamais répondu, terminé par `no-answer` ou `busy`, la clé de rejeu vérifiée et l’heure
de début conservée. Cette heure est observée par l’hôte, pas attestée par l’horloge du
fournisseur. `mock`, `skipSignatureVerification` et un fournisseur construit différent
de celui configuré sont refusés pour ce parcours public. Le fournisseur mock du port
privé Python reste réservé aux données fictives.

L’ACK M1 exact précède le traitement du manager et l’accusé HTTP du webhook. Un refus
libère la réservation de rejeu existante pour permettre une nouvelle livraison.
Avant et après chaque attente, le Core vérifie lease, arrêt, périmètre de configuration,
profil et révision. Stop/reload annule immédiatement les imports, avant même la fin
d’un nettoyage de service bloqué. Aucun nouveau cache de rejeu, inbox, appel LLM ou
envoi externe n’est ajouté pour ce raccord.

[Qualification native ROOT](../../research/REPRISE-2026-10-03/preuves/m1-core-appels-hote/VERIFICATION-ROOT.json) :
**164 cas passés, zéro échec, erreur ou skip**, sept fichiers complets et propriétaires
Vitest natifs, exécutés séquentiellement par fichier sans changer leur pool. Répartition :
10 cas du port hôte, 27 cas de services, 127 cas du plugin. Sources gelées : 5 715 chemins,
61 470 637 octets, inchangés; durée 57,118 s; pointe RSS de groupe 809 775 104 octets.
Les gardes de mémoire sont conservées, sans nouvel OOM ni processus survivant.

Le format passe sur 18 chemins. Le lint syntaxique passe sur 16 fichiers avec deux
avertissements de longueur de fichiers; les quatre règles natives de frontière passent.
Ce résultat ne constitue pas un lint typé ni une compilation complète.
Deux tests HTTP utilisent le vrai validateur Twilio et une clé fictive : HMAC correct
accepté, HMAC calculé avec un mauvais secret refusé avant parsing/lookup/import;
ACK avant commit vérifié. Le manager et le port M1 y sont doublés. Les autres tests
couvrent le rejeu, les appels inconnus/sortants/répondus et la révocation des capacités.

La campagne RED `r11` conserve cinq vrais `ReferenceError` dus à l’import manquant du
résolveur d’agent; ils sont corrigés. `r14` conserve dix défauts de lint corrigés.
`r16` conserve un défaut de harnais : historique d’un mock LLM hérité d’un test antérieur,
réinitialisé avant la requête concernée. Les arrêts mémoire, fichiers exclus par un
mauvais propriétaire Vitest et incident de parseur JUnit des campagnes précédentes
restent aussi archivés; aucun cas absent ou interrompu ne compte comme succès.

## Transport réel Core→Python entre processus

Le [compagnon HTTP natif](../../research/REPRISE-2026-10-03/preuves/m1-core-python-http/VERIFICATION-ROOT.json)
passe **deux scénarios complets**, sans échec, erreur ou skip : le constructeur de
production utilise le vrai client MCP du Core, la vraie CLI Python lancée dans un
nouveau processus et une base SQLite isolée. Aucun override de `callTool` n’est utilisé.
Un import fictif produit exactement un rappel et un transfert humain durables;
un rejeu avec un autre identifiant d’événement préserve les six tables observées.
Le jeton public et le retrait du profil actif refusent l’import, y compris le rejeu
d’un ancien reçu, sans mutation de ces tables. Aucun appel de modèle n’est nécessaire.

La campagne ROOT gèle 6 394 chemins, 70 984 208 octets, inchangés avant/après;
format, lint syntaxique, règles de frontière TS et Ruff du fixture Python passent.
L’environnement des processus est fermé, sans secret hérité; les enfants sont arrêtés
et récoltés, sans survivant ni changement des compteurs OOM. Le parcours utilise un
fournisseur privé `mock`, des coordonnées fictives et une portée de service synthétique;
il ne prouve pas le démarrage intégral du Gateway ni sa récupération après reload.

Le fichier compagnon M9 existant a été tenté séparément après l’ajout des modes au
fixture partagé. Son exécution s’est arrêtée au plancher mémoire brut de 256 MiB,
sans JUnit : **zéro cas M9 qualifié**. Le reçu rouge est conservé dans la même capsule.
Les quatre fonctions M9 préexistantes du fixture sont restées identiques; cela ne
remplace pas leur régression native.

Les huit fichiers natifs de cette tranche sont ensuite ajoutés à la liste
`core/test/opsys-tests-cibles.txt`. Le job existant `tests-opsys` fournit déjà
`OPSYS_TEST_PYTHON`; cette inscription est une configuration CI, pas un résultat
de CI distante ni une nouvelle campagne locale de 164 cas.

## Limites et prochaine qualification

Un rechargement de configuration du plugin recrée son descripteur. Un rechargement
service-only changeant l’agent effectif peut garder le précédent descripteur : le
plugin refuse le démarrage si la capacité cible encore l’ancien agent. Un test natif
exerce ce refus local. La lecture des propriétaires Gateway montre un redémarrage de
récupération qui réenregistre le plugin; ce chemin de récupération n’est pas encore
qualifié de bout en bout.

Le backend Python ne vérifie **ni signature fournisseur, ni direction de l’appel, ni
absence de réponse** : ces faits relèvent de l’hôte de confiance. Les 205 cas Python et
les 164 cas Core sont deux campagnes distinctes; leurs nombres ne prouvent pas un
parcours Core→MCP HTTP Python réel entre processus. La nouvelle campagne de deux
scénarios fournit cette preuve dans sa portée distincte, sans addition des comptes.
La cryptographie locale Twilio ne qualifie pas Telnyx/Plivo, un compte opérateur réel,
un appel téléphonique, l’audio, la latence québécoise, le consentement réel, la mémoire
M10 de cet événement ou un VPS.

Le [préflight ROOT du build](../../research/REPRISE-2026-10-03/preuves/m1-core-appels-hote/reviews/opsys-m1-core-build-root-preflight-r1--PREFLIGHT-ROOT.json.gz)
constate 26 718 208 octets de disque libres et environ 2,38 Go de mémoire disponible
effective. Le build natif exige une heap mesurée de 4 352 MiB, avec allocations natives
supplémentaires. Il n’a pas été lancé; les 333 MiB de `dist` existants sont préservés.
Le build complet, ses exports SDK générés et le profilage du plugin fraîchement compilé
restent **NON QUALIFIÉS**. Aucun ancien bundle ni heap réduite ne les remplace.

La prochaine tranche doit qualifier le build/profilage sur une
ressource suffisante et un bac à sable téléphonique. M1 et le Front Office autonome
complet restent **PARTIELS**; aucune activation de trunk, dépense ou publication n’a
été effectuée.
