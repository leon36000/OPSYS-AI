# M10 — raccord du collecteur à la tentative Core

Statut : raccord implémenté et vérifié localement. Ce document ne qualifie ni une livraison externe M10 ni le fonctionnement autonome complet.

## Chaîne réutilisée

Le Core instancie un collecteur appartenant à la tentative seulement pour le moteur de contexte OPSYS activé, un agent muni d’admission runtime, une session, un recorder de tour et des outils configurés admissibles au ticket cible. Aucun collector n’est mémorisé dans le runtime MCP partagé.

Avant dispatch du modèle, il attend la persistance effective du tour utilisateur. Le reçu doit correspondre à l’agent et à la session ; son `storePath` canonique désigne la base SQLite, pas le fichier d’index des sessions. L’admission budget fournit profil, révision, département, run, tentative et cycle. Un reçu incohérent efface l’admission précédente et échoue ; son refus avant appel fournisseur libère la réservation selon le propriétaire existant.

L’observateur est transmis par l’appel d’outil de cette tentative, à travers matérialisation, runtime combiné et session MCP. Le ticket cible effectivement délivré apporte affaire, agent, session, serveur et outil. Son contenu privé et les arguments métier ne sont jamais conservés par le collecteur.

La réservation du slot, au dernier callback avant `client.callTool`, revalide l’autorité. Vingt appels uniques au maximum par tentative ; appels déjà lancés distincts restent capturables lorsqu’un autre résultat est en attente. Les nouveaux effets sont refusés dès qu’un fait connu reste non durable ou qu’une capture est incohérente. Une vidange réussie rouvre cette barrière lorsqu’il ne subsiste aucun incident irréparable.

Dès que l’appel MCP retourne une enveloppe exploitable, le fait est capturé avant la validation de schéma et avant propagation de l’annulation au retour. Un résultat connu après révocation est conservé avec compteur opérationnel ; il n’autorise aucun appel ultérieur. Une exception de transport sans résultat n’est jamais transformée en fait métier. Les résultats illisibles, erreurs MCP et attentes d’approbation ne deviennent pas des succès.

Le parseur réutilise les règles du collecteur historique. Le fait fermé garde exactement `{cle, outil, resultat, code}` ; les clés historiques `tc-40` restent stables. La source de profil et la cible viennent des reçus internes, pas du modèle ni du texte de l’affaire. L’outbox SQLite existante applique propriétaire, collision, capacité et transaction. Deux tentatives locales bornées d’écriture puis une vidange finale ; aucune de ces reprises ne rejoue l’outil distant.

## Contrôles conservés

R321 : **164/164 dans onze fichiers complets**, Oxlint et Oxfmt réussis, 25 744 sources gelées inchangées, aucun OOM cgroup. La durée totale est 77.34 secondes. Oxlint conserve un avertissement `max-lines` sur le fichier de tests du prompt ; aucune erreur ni règle désactivée.

R318 reste conservé rouge : assertion de comptage située avant la vidange, et deux fichiers retirés implicitement par la voie rapide du helper de configuration. R319 confirme les 164 tests mais échoue sur quatre erreurs de lint ; leurs corrections conservent la sérialisation JSON exacte et le snapshot borné des clés à vider. Les nouvelles doublures de collector utilisent de véritables instances, sans cast destiné à faire taire le typage. R320 est une action de formatage réussie ; son reçu de sources immuables reste volontairement non qualifié puisque les sources changent pendant le formatage.

La correction exige onze fichiers complets (`excludeUnitFastTests:false`), trois tentatives avant vidange puis quatre après, avec les deux résultats distincts vérifiés. Le parcours SQLite part du reçu réellement produit par `persistApproved`, enregistre le fait, refuse le rejeu divergent, puis ferme et rouvre la base avec le nettoyage asynchrone canonique.

La frontière de prompt réelle est testée avec un collector doublé ; l’appel MCP réel de session avec un observateur doublé ; la persistance avec le véritable collector/recorder/worker SQLite. Les tests HTTP de l’admission utilisent le serveur Python réel. Ces preuves ne forment pas un scénario unique modèle→outil→M10 externe et ne doivent pas être présentées ainsi.

## Limites et prochain lot

- Aucun envoi de cette outbox vers M10, ACK réel distant, boucle cron ou retry de livraison n’est branché par ce raccord. Le dépôt terminal historique `OpsysContextEngine.afterTurn/depositBatch` reste inchangé : il relit le transcript et résout l’affaire puis logue la réponse, sans consommer ni acquitter les nouveaux lots. Sa présence ne prouve donc pas leur livraison.
- Une panne entre effet distant et écriture locale reste une fenêtre de perte. Après épuisement des reprises locales, le fait restant en RAM est perdu si le processus disparaît ; le log ne remplace pas sa conservation durable.
- La limite de vingt appels est réservée en RAM avant effet. Les quotas globaux de l’outbox SQLite sont contrôlés pendant l’écriture après retour métier ; ce raccord ne réserve pas de place durable avant le premier effet sur une base déjà pleine. La barrière bloque ensuite les nouveaux effets tant que la capture reste en attente.
- Pas d’exactly-once global : la clé d’un résultat protège le dépôt, pas l’effet métier ; une collision entre tentatives garde le premier fait et bloque la suivante.
- L’observation couvre les outils configurés du contrat cible, pas chaque outil tiers ou appel humain authentifié.
- Les compteurs d’incident/révocation sont des logs opérationnels ; aucun registre permanent d’incidents nouveau n’est livré.
- Le build Core et les déclarations TypeScript complets restent non qualifiés ; les tests, lint et format ciblés ne les remplacent pas.

Prochaine qualification : livraison M10 réelle avec la même clé, panne/ACK perdu, redémarrage et révocation, sans répétition de l’effet initial. Le [rapport de stockage](M10-POSTFLIGHT-STOCKAGE-RAPPORT-2026-10-05.md) conserve les quotas, migration, worker compilé et limites d’exploitation préalables.

## Sources et reçus

[Capsule](../../research/REPRISE-2026-10-05/preuves/CORE-COLLECTEUR-RACCORD-r1.tar.xz)
— SHA-256 3300076d567ace716c26981b0143d705faf2ba2be0a6e7a5029cbf07b4c6eb2e.
[Inventaire et limites](../../research/REPRISE-2026-10-05/preuves/CORE-COLLECTEUR-RACCORD-r1.json).
Toutes les entrées ont été relues et vérifiées. La capsule conserve le rapport avant ces liens ; scans de code/docs ciblés, pas un scan intégral de l’archive.

## Suite du 5 octobre — lecture du dépôt historique

La mention « reste inchangé » ci-dessus décrit le raccord qualifié en R321. Le lot suivant corrige uniquement sa lecture des compteurs, qualifiée en R328 : [rapport du dépôt historique](M10-DEPOT-COMPTEURS-RAPPORT-2026-10-05.md). Ce durcissement ne livre toujours pas les nouveaux lots de l’outbox.
