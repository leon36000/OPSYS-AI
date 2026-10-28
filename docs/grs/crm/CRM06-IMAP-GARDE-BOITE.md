# CRM06 / M1 — empêcher une reprise du curseur dans la mauvaise boîte IMAP

## Objectif, pourquoi et état

Un changement de boîte sous un même compte ne doit pas réutiliser une progression UID étrangère
et ignorer des courriels clients. Défaut reproduit, correction qualifiée localement. **M1, CRM06
et OPSYS-AI restent PARTIAL; le journal des courriels et le raccord au CRM restent manquants.**
[Audit/design avant code](CRM06-AUDIT-SUIVI-COURRIELS.md).

## Architecture, fichiers et données

`core/extensions/imap/src/state.ts` ajoute `mailbox` aux nouveaux curseurs. La première inscription
est atomique via `registerIfAbsent`; deux initialisations ne peuvent pas lier un compte à deux
boîtes. `initializeImapCursor(..., mailbox)` reprend seulement la même boîte. Dans cette boîte,
le reset d’UIDValidity natif reste inchangé. Les identités sont comparées exactement; aucun alias,
changement de casse ou normalisation Unicode présumé. Chaîne non vide, max 1024 caractères,
NUL/CR/LF refusés avant écriture.

`watcher.ts` retient pour chaque connexion la boîte et l’UIDValidity réellement ouvertes, dans un
WeakMap privé. `assertImapCursorSource` compare le curseur courant à cette identité avant FETCH,
puis de nouveau avant chaque traitement après l’attente FETCH. L’avance reçoit cette identité
capturée, et relit aussi boîte/UIDValidity courantes avant d’écrire. Un remplacement tardif ne
peut plus servir de preuve de sa propre autorité.

Aucune route/API, migration de base, bibliothèque, permission modèle/SMS ou activation ajoutée.
Les claims et le ring Message-ID gardent leurs limites natives; ce garde ne les transforme pas
en preuve documentaire ni en archive. Changement de serveur sous le même compte, multi-boîtes
et preuve de provenance complète demandent leurs propres contrats.

## Workflow, intégrations et activation

Nouveau compte sans curseur : baseline native, boîte inscrite. Compte déjà lié à cette boîte :
reprise. Autre boîte, ancien curseur sans boîte ou identité incohérente : refus explicite et
conservation intégrale. Aucun effacement, reprise devinée, reset ou rattrapage automatique.

**Gate avant activation d’un ancien état :** qualifier une procédure de reprise qui prouve sa
boîte et sa progression, avec sauvegarde et décision opérateur. Ce lot ne fournit pas encore cette
procédure et n’est pas déployé. Ne pas supprimer l’ancien état ni changer l’identifiant de compte
pour contourner le refus : une nouvelle baseline pourrait ignorer des messages en attente.

M1 reste propriétaire de l’accueil; M2 du futur lien au projet. Le prompt normalisé/tronqué n’est
pas le courriel original; un ACK de tour modèle ne prouve pas une réception métier durable. Les
droits actuels, le contrôle d’expéditeur et `deliver` sont inchangés, sans envoi réel autorisé.

## Tests et preuve

`state.test.ts` : reprise/reset, autre boîte, legacy, limites, concurrence de première liaison et
avance d’UIDValidity périmée. `watcher-mailbox.test.ts` : client mocké, ouverture RO puis refus
avant FETCH/dispatch, y compris remplacement après connexion. Le transport est nommé comme mocké.
`core/test/scripts/imap-state-persistence.test.ts` : **store natif SQLite du SDK**, entête binaire vérifiée dans le home
fictif, fermeture/réouverture et conservation des lignes lié/legacy après refus. Le coordinateur
natif utilise un répertoire privé de cette fixture. `imap-test-support.ts` notifie aussi la première
liaison atomique; la fixture de packaging `.mjs` porte explicitement INBOX.

Suite finale **47 PASS**, format oxfmt et lint oxlint natifs OK, huit fichiers de code. Les lots
39/41/45 sont inclus et ne sont pas additionnés. Trois rouges initiaux puis quatre rouges de revue
restent conservés. Revue P2 : le garde de sweep initial s’appuyait sur le curseur modifié lui-même;
régression RED→GREEN et suite entière après correction, sans nouvelle boucle d’opinions.

Linux privé : Source RO, home/tmp/caches avant imports, Node 24.22.0 et modules existants identifiés,
CPU 1, mémoire 1 Gio, swap 0, PID 96, TTL 210 s, sockets UNIX/IPv4/IPv6 refusés avant imports.
Toutes unités arrêtées/reçus rc=0 pour la suite finale. Le probe loopback-only n’a pas prouvé son
filtre noyau : **aucun test TCP réel admis**, aucune prétention de qualification d’authentification
IMAP, serveur réel, packaging reconstruit, flux email→M1→M2 ou provenance métier complète.

## Risques et prochaines étapes

Réconcilier la CI publiée avant publication corrective de ce lot. Exécuter le protocole et le
packaging dans une enveloppe compatible. Concevoir la reprise des curseurs anciens avant toute
activation. Puis réception exacte durable avec ACK avant curseur, rattachement admin au projet M2
et consultation du suivi; enfin fils/réponses, envois et statuts de livraison sourcés.
Préflight M10 privé frais, sans prétendre consulter la mémoire réelle du projet. Aucune donnée
réelle, connexion fournisseur, dépense, droit élargi, purge, fusion ou déploiement.

Le test de persistance natif réside côté hôte (`core/test/scripts/imap-state-persistence.test.ts`) et consomme `core/extensions/imap/api.ts`. Le plugin ne dépend pas des internes du Core; cette façade expose ses propres opérations existantes sans nouveau sous-chemin SDK.
