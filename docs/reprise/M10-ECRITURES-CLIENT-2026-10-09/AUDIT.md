# Continuation M10 : écritures documentaires et intentions mobile

État : **PARTIEL**. Base GitHub `ceca7308392f6948f069f18fc070bd596405fb63`, PR privée #623 en brouillon. Audit Toronto : 2026-10-09T22:54:27.338229-04:00.

Le backend SQLite ajoute dépôt, activation et retrait avec un accusé complet lié à la personne, à l’appareil et à la même intention. Une réponse inconnue conserve l’UUID ; les opérations suivantes de la même affaire restent bloquées. Un propre rejeu de v1 reste confirmable après v2 ou retrait. Les gardes admin, révocation, quotas et rollback précèdent les effets. Les déclarations sont dérivées du schéma canonique.

Le client mobile ajoute les trois intentions durables au SDK/outbox existant, avec contrôle de destination et validation de l’accusé transport puis du reçu persisté. Aucun nouvel écran n’est livré dans cet incrément. La correction HTTP locale émet le 503 puis ferme après un drain borné à 100 ms et 139 264 octets : elle corrige le BrokenPipe reproduit entre en-têtes et corps sans deuxième inférence. Le délai dépend aussi de l’ordonnancement, et aucun 503 universel pour un client hostile n’est promis.

La qualification fraîche sur le checkout principal obtient 478 tests Python sans saut et 553 tests mobile dans 27 suites. Ruff, types mobile et vérificateur métier passent : dix départements, 240 outils, 148 déclarations appareil. Les 44 tests embeddings sont inclus dans les 478, les 59 tests mobile ciblés dans les 553. Ces compteurs ne s’additionnent pas une seconde fois.

Une campagne distincte utilise des tokens DEVICE opaques du Core compilé, le Gateway officiel minimal, HTTP MCP public et SQLite : 56 fenêtres Gateway, 52 outils/call, 2 744 paires sur 49 tables recensées, sept écritures N3 et 49 fenêtres sans mutation. Ces dernières ne sont pas 49 lectures T0. L’accusé complet retrouve les mêmes octets après redémarrage des processus. Clôture extérieure PASS, PIDFD/EOF, état privé supprimé, scanners propres. La reprise mobile entre deux processus Node utilise un shim node:sqlite et un ACK RAM lié ; elle ne qualifie pas Expo sur téléphone ni une capture backend.

La CI du HEAD de base reste rouge sur la saturation HTTP et le gate qui en dépend. Le nouveau commit doit recevoir sa propre CI ; aucune réussite parent n’est transférée. Les types Core et son build complet sont actuellement bloqués localement par la mémoire disponible sous les seuils préparés, et Docker par les permissions du socket. Les runners sont une qualification distincte.

Les modèles fournissent des avis statiques. Les constats matériels sont confrontés aux sources puis aux tests avant adoption. Les niveaux HIGH/MAX configurés ne prouvent pas un effort interne non émis. Ni quota illimité ni taux d’usage d’abonnement n’est attesté. Les essais rouges, absences et limites restent conservés dans la capsule et le registre.

Les 104 preuves exclues du pack léger, le supplément complet et les conversations absentes restent indisponibles. La modification du BRIEF M10 dans F15, sans propriétaire établi, est préservée et exclue de cette publication. Les preuves Q présentes sont locales et identifiées par leurs empreintes ; elles ne sont pas déclarées téléchargées ou présentes dans les artifacts GitHub.

La suite conserve dix départements profonds, Core OpenClaw, permissions, dashboard, quatre profils mobile/hors ligne, avatars et mémoires métier/développement séparées. Prochain incrément : rendre les documents/provenances exploitables dans la verticale commune M7→M1→M2→M3→M4/M6→M5→M8/M9/M10, avec lecture pure, écran admin et intentions déjà durables ; critères et dépendances doivent être vérifiés avant livraison. Aucune fusion, force-push ou production.
