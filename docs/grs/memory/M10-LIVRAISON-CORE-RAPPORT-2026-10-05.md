# M10 — Livraison Core, reprise et passage de relais

## Résultat local vérifié

ROOT **r347 : 167/167 dans huit fichiers complets**, aucun échec, erreur ou skip ; Oxlint, Oxfmt et Ruff réussis. Les 25 749 sources gelées sont inchangées pendant la qualification, sans variation des compteurs OOM. Oxlint conserve un avertissement de longueur sur le fichier de tests du moteur de contexte. Pas de compilation globale Core, d’analyse TypeScript globale, de CI distante ou de livraison en production qualifiées.

Le sender `core/src/agents/harness/opsys-postflight-delivery.ts` réutilise le worker SQLite canonique et le transport MCP existant. Il choisit **quatre lots dus maximum**, uniquement pour le profil, la révision, le département et le moteur `opsys` admis. Une tentative atomique précède le réseau. Les clés tc40/tc64 existantes restent identiques ; aucun outil métier source n’est rejoué. Timeout, annulation, droits retirés, réponse imprécise et échec d’ACK local conservent le lot. Les diagnostics utilisent des codes fermés.

L’ACK est accepté seulement avec origine, affaire et clés identiques, compteurs entiers non négatifs couvrant tous les faits et nombre de lignes cohérent. Le serveur privé vérifié en [r334](M10-DEPOT-RUNTIME-RAPPORT-2026-10-05.md) confirme après commit. Une réponse « ok » générique ne suffit pas.

## Raccord au cycle de vie

Le collecteur ouvre la DB du reçu canonique de transcription et garde son admission runtime. Son `deliverPending()` vide d’abord la capture locale, revalide l’autorité et appelle le sender. Le runner appelle cette méthode après une exécution retournée, avant le nettoyage de session. **Une seule passe par tentative** ; aucune émission depuis le `finally` après fermeture d’autorité. Une tentative réussie future peut reprendre les lots dus du même profil/révision. Pas de timer, daemon, cron ni garantie de vidage en l’absence de nouvelles tentatives.

L’ancien POSTFLIGHT pouvait choisir une affaire depuis le texte, différente de celle du ticket. Le reçu hôte `opsysDeferredPostflight` contient uniquement l’identité de session/agent et les clés des appels effectivement réservés avant outil par le collecteur, vingt maximum. Le moteur historique exclut ces seules clés quand l’identité concorde ; les autres appels restent pris en charge. Une configuration de profil seule ne supprime aucun dépôt. Ce reçu décrit une prise en charge, **ne confère aucune autorité** et ne prétend pas que tous ces appels ont réussi.

Les deux chemins de fin de tour transmettent le reçu : contexte direct et candidat du tour accepté. Le payload de l’outbox des tours garde ce champ facultatif lors de la récupération. Les anciens payloads restent lisibles, sans migration de table supplémentaire. Un incident de capture empêche la nouvelle livraison et reste signalé ; il ne justifie pas d’inscrire une affaire devinée par l’ancien moteur.

## Ce que les tests prouvent

- **TCP réel + M10/Python + SQLite Core :** dépôt réellement commité puis perte de l’ACK ; fermeture/réouverture Core et reprise avec les mêmes clés ; un seul fait M10, chaîne valide et lot retiré seulement après confirmation.
- Profil révoqué réellement en Python avant livraison : aucune écriture M10, lot durable conservé.
- Reçu de transcription réellement persisté → vrai collecteur → vraie outbox → `deliverPending()` → serveur privé TCP/M10 : reçu de passage de relais exact et ACK vérifié. Le résultat d’outil source et l’admission runtime de ce test sont synthétiques ; aucun provider ou effet métier réel n’est exécuté.
- Doubles contrôlés : filtrage, plafond quatre, tentative incohérente, ACK local échoué, chaque origine incorrecte, compteurs manquants/non numériques/négatifs/incohérents, annulation et révocation pendant l’attente.
- Contexte construit depuis le vrai collecteur/SQLite ; exclusion de la seule clé possédée ; conservation des autres appels ; identités non concordantes ; propagation par le finaliseur ; conservation du reçu dans la récupération de tour durable.

Les preuves composent des frontières réellement raccordées, mais ne constituent pas encore un E2E unique modèle → outil métier réel → mémoire. Le branchement complet du runner est préparé pour la compilation et la CI applicables, pas marqué production vérifiée.

## Historique et limites

r336 : module absent, zéro test exécuté ; JUnit a produit un marqueur de suite échouée. r337 : 9/10, double de serveur lié à la mauvaise réponse. r338 : 21/22, annulation pendant ACK non contrôlée. ROOT corrige ces deux défauts. r339/r340 : comportement vert, qualification rouge sur lint ; r341 : primitive 22/22 et lint. r342 : 109/114, passage de relais absent ; r343 : 142/142. r344 : 15/16, candidat accepté sans reçu ; correction dans son propriétaire. r345/r346 : 166/166 ; r347 ajoute le parcours collecteur/TCP complet décrit ci-dessus. Chaque rouge, préimage et source est conservé. Le stage Luna a été repris après saturation du modèle ; ROOT assume la promotion et la qualification.

Limites maintenues : crash entre effet distant et capture ; quota global SQLite atteint après effet ; incident de capture sans registre permanent ; effet historique non prouvé cryptographiquement ; affectation actuelle d’affaire non revalidée par le dépôt privé ; profil ancien/modifié laissant son lot en revue ; pas de tombstone d’ACK local. Le reçu privé porte la provenance du profil, mais le maillon M10 conserve actuellement le département sans nouveau champ durable de profil. Aucune promesse générale « exactement une fois » ni M10/OPSYS-AI à 100 %.

Prochain lot : intention durable et réservation de capacité **avant** effet métier, puis preuve de panne/reprise avec le vrai outil source et E2E du runner. Les évaluations de mémoire à l’échelle et inter-clients restent dans le programme. GitHub, CI distante, API de production et daemon de travail de 24 heures ne sont pas exécutés par cette qualification.

## Preuves conservées

[Capsule](../../research/REPRISE-2026-10-05/preuves/M10-LIVRAISON-CORE-r1.tar.xz) — SHA-256 fcd156940750461a239089ad7a32866f6c335d111c948c790ecb1fa4ce4e1dfb.
[Inventaire et références](../../research/REPRISE-2026-10-05/preuves/M10-LIVRAISON-CORE-r1.json). Toutes les entrées et références sont relues et vérifiées. Le rapport avant ces liens est conservé ; r348 scanne vingt sources/docs sans exception ajoutée, pas toute l’archive.
