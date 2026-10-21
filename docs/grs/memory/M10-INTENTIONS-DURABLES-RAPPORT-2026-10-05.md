# M10 — intention durable avant effet source

État : implémenté et qualifié localement, sans promotion globale de M10 ni d’OPSYS-AI. La fenêtre de crash entre effet métier et capture est désormais précédée d’une réservation SQLite durable : un résultat inconnu reste visible et empêche une répétition automatique de la même clé. Ce registre conserve l’incertitude ; il ne prouve pas que l’action distante a réussi.

## Contrat et code

Le worker canonique `core/src/agents/harness/opsys-postflight-outbox.worker.ts` garde le même propriétaire SQL et les mêmes transactions/admissions. La table STRICT additive `opsys_postflight_intents` contient une clé tc40, une enveloppe fermée, l’état `uncertain` et l’horodatage. Le schéma canonique et les types Kysely générés sont mis à jour sans nouvelle bibliothèque ni second stockage. `opsys-postflight-outbox.ts` expose réservation, lecture et conversion.

Chaque intention réserve un slot et 4 096 octets dans le quota commun de 256 slots / 1 Mio. Les métadonnées et le pire futur singleton sont validés avant réservation. Un lot ordinaire ne peut utiliser une clé réservée. Un doublon d’intention est refusé, même si l’enveloppe est identique. La conversion d’un résultat connu supprime l’intention et écrit le lot dans une transaction : toute erreur, saturation ou admission retirée annule les deux mutations. Un ACK local perdu peut être confirmé uniquement par un lot existant strictement identique ; cela n’autorise jamais un nouvel appel métier.

Le collecteur `opsys-postflight-collector.ts` attend la réservation avant dispatch et conserve les clés ouvertes. L’identité de lignée est hachée avec SHA-256 pour corrélation ; elle ne constitue ni chiffrement ni anonymisation forte. Ni arguments métier, ni jeton, ni ticket privé, ni transcription brute ne sont stockés dans l’intention. La cible doit correspondre au reçu privé issu de l’hôte.

`agent-bundle-mcp-runtime.ts` revalide l’autorité et l’annulation après cette attente, avant `client.callTool`. Le catch entoure seulement le RPC source. Si celui-ci lève une exception, le collecteur signale le résultat inconnu une seule fois, conserve l’intention et bloque les nouveaux effets dans cette tentative, même avec une autre clé d’appel. L’exception originale remonte. Aucun fait ok/refus n’est inventé. Une réponse inexploitable, un refus de capture ou une révocation conservent également l’incertitude et les diagnostics. Le finally existant n’annonce pas une capture réussie lorsqu’une intention reste ouverte.

## Vérification et preuves

Qualification combinée : **210 cas comportementaux dans onze fichiers complets**. r356 exécute quatre groupes séquentiels, tous verts (21 stockage, 38 frontière MCP, 25 cycle de vie, 126 livraison), mais son verdict global reste rouge pour une variable masquée dans un test. Seul ce fichier de test change ensuite : r357 le revérifie intégralement, **10/10**, avec Oxlint, Oxfmt et vérification des types générés verts. Les 200 autres cas sont reportés uniquement parce que leurs sources et toutes les sources de production sont identiques entre ces reçus. Le reçu combiné conserve cette distinction ; r357 ne prétend pas avoir exécuté 210 tests.

Les gardes restent 2 Gio RSS, 180 secondes par exécution et heap Node 1 024 Mio. r353 n’a produit aucun JUnit exploitable ; aucune réussite n’en est déduite. r354 a confirmé un dépassement RSS à 2 169 548 800 octets, puis le groupe a été découpé en fichiers complets sans augmenter les limites. Aucun OOM, aucune mutation de sources pendant les exécutions. L’avertissement de longueur du worker (839 lignes, seuil 700) demeure une dette de maintenance. Les premiers tests rouges, incidents du pilote, variantes de sources et reçus sont conservés.

Les tests couvrent réservation préalable, refus de doublon, quotas communs et borne future, rollback d’admission, conversion atomique, capture après ACK perdu, réouverture SQLite, résultat réseau inconnu, annulation pendant l’attente, et livraison M10 existante. Les trois parcours TCP réels vers Python/M10 utilisent SQLite Core ; le résultat source et une partie de l’admission de leur parcours collecteur sont synthétiques. Aucun parcours unique du modèle/runner vers un véritable outil métier puis M10 n’est revendiqué.

## Limites et suite

- Une intention incertaine n’expire pas et n’est ni purgée ni rejouée automatiquement. Aucun écran ou protocole de rapprochement humain n’est encore livré. Jusqu’à 256 cas ambigus peuvent bloquer les nouvelles actions : ce blocage conservateur est visible dans les erreurs, mais nécessite un outil de diagnostic/rapprochement à construire.
- La suppression du lot après ACK M10 ne conserve pas de tombstone. Une action métier exactement une fois après livraison/redémarrage n’est pas garantie. L’idempotence du fait M10 ne garantit pas celle de l’effet source.
- La façade stockage et l’ACK runtime reposent sur l’hôte autorisé ; ils ne prouvent pas cryptographiquement un ancien résultat distant. La révision de profil et les droits sont contrôlés actuellement, pas reconstruits comme preuve historique.
- Une révocation ou expiration pendant l’attente peut laisser une intention conservatrice sans dispatch. Le serveur source revalide son ticket ; le cas exact d’expiration durant l’attente reste à qualifier.
- La lecture des intentions existe dans la façade privée, sans route publique ni interface admin. Pas de timer, cron, daemon permanent ou nouvelle dépendance.
- Compilation globale Core, types globaux et CI distante restent non qualifiés. Aucun push GitHub, merge main, déploiement ou accès fournisseur réel dans ce lot.

Prochaine priorité : un test de raccord unique avec runtime MCP réel, collecteur, SQLite et M10 HTTP, avec la part synthétique explicitement identifiée ; ensuite diagnostic humain des intentions et protocole de rapprochement sourcé sans autoriser un replay aveugle.

## Revue et méthode

ROOT a écrit le contrat puis les tests négatifs avant implémentation. Cinq revues Luna en lecture seule ont examiné l’audit, le design, les quotas, la frontière asynchrone et le résultat inconnu. Les briefs donnaient objectif, fichiers, invariants et livrable borné ; ROOT a contrôlé les assertions et intégré les corrections. Aucune approbation de trois modèles ni attente d’un arbitre externe. Aucun benchmark LLM ou gain de tokens mesuré n’est annoncé.

## Dossier durable

[Capsule de preuves](../../research/REPRISE-2026-10-05/preuves/M10-INTENTIONS-DURABLES-r1.tar.xz) ; [inventaire SHA-256 et qualification combinée](../../research/REPRISE-2026-10-05/preuves/M10-INTENTIONS-DURABLES-r1.json). Les variantes initiales manquantes ont été reconstruites depuis les scripts et préimages conservés, puis comparées aux SHA immuables des exécutions ; les reçus de reconstruction sont inclus. Toutes les entrées et références d’archives doivent être relues avant finalisation. Le contrôle de secrets r358 utilise la configuration par défaut sur 21 sources, documents et rapports de revue ; r359 revérifie les trois documents finaux. Ces contrôles ne prétendent pas scanner toute l’archive.

## Raccord intégré supplémentaire — r363

**Cinq parcours dans le fichier complet, Oxlint/Oxfmt/Ruff verts.** Les deux nouveaux cas traversent le runtime MCP et l’observer réels, la SQLite du transcript et M10 Python HTTP. Le processus source constate lui-même l’intention persistée et zéro lot avant réponse ou perte de transport. Une reconnexion réelle précède les refus de nouveaux effets ; l’incertitude survit à la réouverture de la base. [Preuve et limites](M10-MCP-COLLECTEUR-E2E-RAPPORT-2026-10-05.md).

Les trois cas antérieurs sont inclus dans ces cinq, pas ajoutés une deuxième fois. Ticket, admission provider et résultat source restent synthétiques ; le parcours modèle/runner/outil métier réel demeure ouvert. Aucune modification de code de production dans cette tranche de qualification. Le diagnostic et rapprochement humain des intentions reste à construire.
