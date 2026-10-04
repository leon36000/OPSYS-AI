# Raccordement des intentions cron au Core — 3 octobre 2026

Ce document distingue le code intégré localement de sa qualification encore partielle. Le tableau de bord prépare et
retire les intentions humaines; les RPC opérateur préparent, acquittent, vérifient et
renouvellent une autorité privée. Leur qualification ne prouve pas une exécution Core.
Voir [le contrat actuel](AGENTS-CRON-OPERATEUR.md).

## Réutilisation retenue

Le scheduler, les mutations natives, les grants à usage unique et le sidecar SQLite
existent. `cron.add` reçoit déjà une capture privée issue du scope authentifié, puis
la transmet au service dans sa transaction. Le sidecar OPSYS chiffre l’autorité et
la lie au stockage, au job, au runtime, au namespace et à l’empreinte d’entrée.
Les projections publiques excluent cette autorité. Aucun deuxième scheduler n’est
nécessaire.

Le canal privé de lecture/projection des intentions est désormais qualifié sur
SQLite/HTTP. Le client privé Core, le producteur hôte et le reconciler sont désormais écrits.
Le resolver transmet une capture issue du mandat Python; la tâche reste désactivée
jusqu’à ACK puis CAS natif. La vérification est placée avant chaque dispatch provider.
Le stockage natif et le stream SDK restent à qualifier : l’exécution autonome complète
n’est pas prouvée.

## Parcours intégré, qualification partielle

1. Le contrôleur hôte lit des intentions bornées, liées au profil configuré et à
   l’instance. Il re-projette le mandat actuel avant de construire une tâche.
2. L’hôte crée une capacité aléatoire de 32 octets. Python reçoit son SHA, puis la
   capacité n’est transmise que par le canal privé et la capture native chiffrée.
   Ni modèle, prompt, réponse publique ni JSON de configuration ne reçoit le secret.
3. La création native reste explicitement désactivée. Le grant one-shot est capturé
   par le vrai `cron.add`; le secret devient durable dans son sidecar.
4. L’ACK Python vise le SHA de la définition cible activée. L’activation native compare
   séparément la préimage désactivée par CAS. L’ACK ne remplace pas cette comparaison.
5. Avant chaque candidat et chaque fallback provider, le consommateur relit le job,
   recalcule sa révision et appelle `valider` avec son autorité privée. Toute erreur,
   révocation, divergence ou récupération requise empêche le nouveau dispatch.

## Reprises et frontière de révocation

Après capture durable, une perte de réponse ACK se rejoue avec les mêmes capacité,
époque, job et révision. Une perte de réponse CAS se résout en relisant le SHA : cible
activée = succès; préimage exacte = reprise possible; autre définition = blocage.

Une perte du secret après préparation mais avant capture durable n’est pas réparée
par renouvellement. L’intention reste inerte; une nouvelle autorisation humaine ou
un reset propriétaire audité devra être défini, sans réactivation implicite.
La validation distante et le démarrage provider ne sont pas une transaction commune;
elle ne peut pas arrêter rétroactivement un stream déjà autorisé et démarré.

## Preuves requises

La qualification restante doit couvrir la vraie chaîne resolver → Cron tool → Gateway
→ sidecar, l’absence de secrets dans les surfaces publiques, les deux SHA distincts,
l’ACK avant activation, les réponses perdues, les refus après révocation et une nouvelle
validation pour chaque fallback. Les appels provider seront comptés dans le harnais;
aucun provider réel, job de production ou dépense n’est nécessaire pour ces essais.

[Revue RO conservée](/workspace/poursuite-opsys-2026-10-02-r1/M10-CRON-CADRAGE-ROOT-r1/revue-core-host-ro-r1.md).

## Déclenchement de convergence

Le superviseur métier possède déjà une boucle de contrôle de santé. Un callback
sur une sonde saine peut appeler la réconciliation système existante, sérialisée et
liée à l’époque de configuration, avec coalescence des appels. Cette approche
réutilise le scheduler natif; elle ne planifie pas les agents dans une seconde file.
Le callback et le reconciler OPSYS sont intégrés à cette sonde, avec contrôle d’époque
et coalescence. Le client refuse les destinations non loopback et les redirections
avant d’envoyer son credential opérateur. L’arrêt ou le remplacement de l’hôte invalide
son resolver : une ancienne capture ne réarme pas un hôte arrêté.


## Preuves actuelles et limites

La lecture privée est exhaustive jusqu’à 16 intentions. La liste de la console humaine
reste bornée à 10. Un dépassement est refusé sans valider une liste partielle.
Le retrait terminal Python et la migration `0023` passent **185 cas**, avec une preuve
native simulée dans cette campagne. [Preuve Python](../research/REPRISE-2026-10-03/preuves/cron-retrait-python/VERIFICATION-ROOT.json).

Le candidat natif cumulatif r4 est intégré localement. Ses campagnes complètes distinctes
qualifient **30 cas du client privé**, **52 du validateur/reconciler/superviseur**,
et **10 des sauvegardes/secrets**. Les trois contrôles de format passent sur les 44
chemins Core concernés; aucun fichier de test n’a été réduit. Ces nombres ne sont pas
additionnés et ne décrivent pas une chaîne d’exécution de bout en bout.

- [Client privé, huit opérations](../research/REPRISE-2026-10-03/preuves/cron-retrait-core/client-cleanup-r4-root-r2/VERIFICATION-ROOT.json).
- [Convergence hôte](../research/REPRISE-2026-10-03/preuves/cron-retrait-core/gateway-cleanup-r4/VERIFICATION-ROOT.json).
- [Sauvegardes et secrets](../research/REPRISE-2026-10-03/preuves/cron-retrait-core/backup-secret-cleanup-r4/VERIFICATION-ROOT.json).

Les propriétaires natifs sont doublés dans la campagne de convergence. Les onze cas
écrits pour le véritable retrait CronService/SQLite n’ont pas démarré : le plancher de
1 472 MiB n’était pas disponible. [Reçu RED conservé](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/retrait-core-r4/qualification-root-r1/retirement-cleanup-r4/VERIFICATION-ROOT.json).
Une seconde tentative, avec un plafond de groupe plus petit et la même réserve de
512 MiB, a démarré puis été arrêtée par cette garde avant de produire un JUnit.
Elle ne qualifie aucun cas : [reçu de réserve](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/retrait-core-r4/qualification-root-r1/retirement-cleanup-r4-budget-r2/VERIFICATION-ROOT.json).
Le reconciler SQLite natif (six cas), le CAS (17), le cycle de vie hôte (12) et le stream
SDK (deux) restent aussi non qualifiés. Le correctif de libération avant dispatch est
intégré : 18 cas du wrapper Core et 110 cas Python SQLite passent dans leurs campagnes
distinctes. Le compagnon Python HTTP complet reste non qualifié, ainsi que cinq cas
PostgreSQL. Les 11 anciens cas sont historiques. [Contrat et preuves actuelles](AGENTS-BUDGET-AVANT-DISPATCH-2026-10-03.md).

Aucun provider réel, job de production, dépense ou déploiement VPS n’a été déclenché.
Le statut global reste **PARTIEL**.

### Retrait natif durable intégré r4

La revue r2 avait trouvé une écriture SQLite sur le fil principal Gateway. Le code
intégré transmet désormais une capture composée de données au worker de sauvegarde
existant. Ce worker compare la préimage désactivée, écrit le reçu chiffré et supprime
le job dans sa même transaction, sous admission au début et avant commit. L’ACK du
reçu emprunte également un port d’admission worker; le mutateur SQL ne reçoit pas de
callback Gateway. [Revue r2 historique](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/revue-retrait-core-r2/MANIFEST-ROOT.json).

Le reçu indépendant du job survit à son DELETE. La réconciliation draine au plus 16
reçus par profil avant de reprendre les intentions; elle n’acquitte pas Python sans
preuve native exacte. Le chiffrement lie stockage, job, autorité et source. La
sauvegarde Git exclut entièrement cette table de secrets; la sauvegarde opérateur
complète conserve le ciphertext et nécessite sa clé externe.

Le point « réponse worker perdue » a été reclassé après examen des appelants : le
helper existant invalide la révision de partition, puis les lectures et le scheduler
rechargent le magasin. Aucun réarmement n’a été démontré. Les nouveaux tests écrits
incluent ce cas avec les deux états du scheduler, mais leur qualification SQLite
reste à faire. [Addendum de revue conservé](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/revue-retrait-core-r3/ADDENDUM-MANIFEST-ROOT.json).

Un premier contrôle de format a révélé une erreur de syntaxe dans un test candidat.
ROOT l’a corrigée avant les campagnes positives; le reçu RED original, le gel initial
et les sources formatées qualifiées sont conservés séparément dans
[l’archive ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/retrait-core-r4/qualification-root-r1/sources-qualifiees-r8/MANIFEST-ROOT.json).
