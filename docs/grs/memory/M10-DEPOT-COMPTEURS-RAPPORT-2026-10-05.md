# M10 — validation des compteurs du dépôt historique

Statut : correction locale vérifiée du dépôt terminal historique, distincte du collecteur et de son outbox.

## Défaut reproduit et comportement corrigé

`OpsysContextEngine.afterTurn` collecte les résultats du transcript puis appelle le dépôt M10 par lots. Sa lecture de réponse remplaçait les compteurs absents par zéro et pouvait journaliser un succès sans vérifier combien de faits étaient confirmés.

La réponse doit maintenant conserver l’enveloppe de succès et l’acceptation M10, puis fournir `ecrits` et `deja_deposes` : nombres entiers sûrs, non négatifs, dont la somme égale exactement le nombre de faits envoyés. Compteurs absents, chaîne, booléen, fraction, valeur négative, entier non sûr, total incomplet ou excessif produisent un avertissement de refus, sans journal de succès. Un dépôt entièrement déjà connu et un lot mêlant faits nouveaux et déjà déposés restent acceptés.

Deux fichiers changent : le moteur `core/src/context-engine/opsys-contexte-engine.ts` et son fichier de tests complet. La doublure M10 par défaut rapporte désormais la taille réelle du lot de la fixture ; elle ne peut pas annoncer arbitrairement un fait écrit pour un lot de vingt. Trois exécuteurs de Promise des tests de timeout ont une fonction bloc vide, conservant leur attente sans résolution et corrigeant le lint existant.

## Preuves et limites

- R325 : reproduction rouge, 95 cas dont 11 échecs attendus sur les compteurs invalides.
- R326 : formatage réussi ; reçu de qualification immuable volontairement rouge, car seuls les deux fichiers détenus sont formatés.
- R327 : 96/96 dans deux fichiers complets, mais trois erreurs de lint ; reçu conservé rouge.
- R328 : **96/96 dans les deux fichiers complets**, Oxlint et Oxfmt réussis, 25 744 sources inchangées, aucun OOM. Un avertissement `max-lines` sur le fichier de tests reste visible ; aucune règle désactivée.

Les tests exécutent le véritable moteur avec un service M10 doublé et le transport MCP stdio avec une fixture echo. Ils ne prouvent pas un dépôt vers le serveur Python M10 réel. Cette correction ne consomme pas l’outbox du [collecteur](M10-COLLECTEUR-RACCORD-RAPPORT-2026-10-05.md), ne crée pas de nouvel ACK durable et ne rejoue aucun outil métier. Une réponse refusée est signalée ; ce chemin historique ne fournit pas de reprise durable à lui seul.

Les preuves de sources réutilisent par empreinte la capsule Core existante pour éviter de recopier tous les fichiers inchangés. Les variantes modifiées, reçus rouges et verts, drivers et configurations sont conservés dans une nouvelle capsule incrémentale. Le build Core complet, la CI et la livraison externe restent non qualifiés.

## Capsule incrémentale

[Preuves](../../research/REPRISE-2026-10-05/preuves/M10-DEPOT-COMPTEURS-r1.tar.xz) — SHA-256 a1e188443f941952ac438c80f54a1a263f3cabbc8a06cd29785fbfc0c5c788f6.
[Inventaire](../../research/REPRISE-2026-10-05/preuves/M10-DEPOT-COMPTEURS-r1.json).
La capsule dépend de la capsule Core existante nommée dans l’inventaire ; toutes les références et entrées ont été relues et vérifiées. Le rapport avant ces liens est archivé ; le scan cible le code et les documents, pas toute l’archive.
