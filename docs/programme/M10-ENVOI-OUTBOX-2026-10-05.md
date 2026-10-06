# Livraison de l’outbox M10 — design et plan d’implémentation

> Exécution ROOT par lots vérifiables ; audit Luna en lecture seule. Choix courants déjà autorisés par Nathan. Ce plan ne déclare pas la livraison complète.

**But :** retirer un lot durable seulement après un dépôt M10 confirmé et exactement lié au profil, à sa révision, au département, à l’affaire et aux mêmes clés de faits. Aucun effet métier original rejoué.

**Architecture :** conserver le collecteur, le worker SQLite, les délais de reprise et les clés tc40/tc64. Ajouter une opération privée au serveur runtime lié au profil, utilisant le dépôt canonique M10 sous la transaction durable existante. Puis livrer au plus quatre lots dus dans une passe sans timer interne, via cette opération ; après timeout ou ACK perdu, les mêmes faits peuvent être déposés à nouveau, jamais reconstruits. Le moteur historique reste distinct jusqu’à une migration explicitement testée.

**Choix :** le serveur M10 historique n’apporte pas de liaison au profil. Lui ajouter des arguments issus du modèle serait insuffisant. L’opération runtime privée apporte l’origine fixe et réutilise les contrôles vivants existants, sans deuxième registre de faits ou bibliothèque de transport.

## Contrats et contraintes

- `opsys_runtime_deposer_faits`, uniquement sur `/mcp/runtime/<profil>` et avec le jeton runtime existant ; absente des catalogues métier et bloquée par la politique des agents.
- Arguments fermés : `affaire_id`, `faits`, `horodatage`, `revision_profil`. Profil et département sont dérivés de la base ; le modèle ne les nomme pas. Un à vingt faits fermés `{cle, outil, resultat, code}`, validés par le contrat canonique M10.
- Profil actif, non supprimé et révision exacte ; chaque outil source doit être encore autorisé dans ce département. Verrou et revalidation avant dépôt et avant commit. Base durable canonique identique avant et après effet.
- Dépôt M10 canonique dans la même transaction. Refus, exception, compteur incohérent, changement de base ou révocation annulent toute écriture. ACK accepté après commit seulement, source dérivée et clés identiques au lot.
- Cette attestation dépend de l’hôte et du jeton runtime : elle ne prouve pas cryptographiquement que le résultat distant s’est produit. La cible vient du ticket dans le collecteur ; l’opération privée ne réémet pas ce ticket historique.
- Aucun envoi client, paiement, publication, provider réel ou dépendance ajoutée. Aucun cron ou reprise permanente annoncé avant raccord réel au cycle de vie.

## Lot A — opération privée et preuve M10 réelle

Fichiers : `src/opsys/postflight_runtime.py`, raccord dans `src/opsys/serveur_mcp.py`, `tests/test_runtime_depot_postflight.py`, catalogue attendu de `tests/test_serveur_mcp_http.py`.

- [x] Écrire et exécuter les tests rouges : dépôt réel MCP/SQLite, rejeu après fermeture/réouverture, conflit divergent, profil périmé/inactif/supprimé/sans outil, outil d’un autre département, arguments supplémentaires, lot invalide, mauvais jeton, catalogue métier absent.
- [x] Implémenter le propriétaire `deposer(departements, cnx_factory, profil_id, arguments)` avec validation canonique, contrôle vivant et transaction existante.
- [x] Simuler panne au second maillon, faux compteur, révocation durant dépôt et changement de base : aucune mutation persistée ni faux ACK.
- [x] Exécuter les fichiers complets concernés, Ruff, manifestes ; conserver chaque reçu, source et limite.

## Lot B — envoi Core et ACK exact

Partir de `opsys-postflight-outbox.ts` et du transport `callOpsysMcpTool`. Définir les fichiers exacts après l’audit de raccord ; aucun second propriétaire SQL.

- [x] Passe bornée, horloge injectée, réservation d’une tentative atomique existante ; pas d’envoi concurrent d’un même lot dans cette passe.
- [x] Revalidation d’autorité avant appel ; transport runtime profilé ; ACK source, affaire et clés exacts, compteurs couvrant tous les faits. ACK absent/incohérent conserve le lot.
- [x] ACK perdu puis même dépôt après redémarrage : un seul fait candidat, aucune répétition de l’outil source.
- [x] Refus de profil/révision/affaire/clé divergents, timeout et échec de suppression locale. Sélection et calendrier de revue restent ceux du worker canonique déjà qualifié.
- [x] Raccord explicite avant cleanup, une passe par tentative retournée ; transport Python/Core réel avec reçu canonique du collecteur.
- [ ] E2E unique du runner avec provider/outil métier réel, compilation globale Core et CI applicable avant promotion production.

## Revue prioritaire

L’atomicité inclut tous les maillons ; une validation de forme ne suffit pas. L’ACK ne supprime pas un autre lot ou une autre tentative. Le retrait de droits n’autorise pas une livraison depuis un ancien profil. Les refus ne divulguent ni token ni résultat métier. Les traces candidates restent hors de la vérité métier consolidée. Une passe manuelle vérifiée ne prouve pas un service autonome permanent.

Lot A qualifié en R334 : 147/147, Ruff et manifestes. [Rapport et limites](../grs/memory/M10-DEPOT-RUNTIME-RAPPORT-2026-10-05.md). Lot B implémenté et qualifié localement en r347 : **167/167 dans huit fichiers complets**, Oxlint/Oxfmt/Ruff. [Raccord, preuves et limites](../grs/memory/M10-LIVRAISON-CORE-RAPPORT-2026-10-05.md). Trois parcours TCP réels ; effet source/admission runtime du parcours collecteur synthétiques. Ancien dépôt partitionné par les seules clés possédées. La passe nécessite une tentative réussie vivante ; aucun service autonome permanent ni production complète annoncé.

## Intention durable — raccord qualifié localement

La réservation SQLite précède désormais le RPC source, dans le même propriétaire de stockage que l’outbox. Les intentions et lots partagent 256 slots / 1 Mio ; résultat inconnu, refus d’admission et crash ne produisent aucun faux fait. La tentative bloque après exception réseau ; une conversion connue est atomique. **Qualification combinée r356/r357 : 210 cas / onze fichiers complets**, avec r356 conservé rouge au lint puis un seul fichier de test corrigé et revérifié intégralement en r357 (10/10, lint/format/types générés verts). [Rapport et limites](../grs/memory/M10-INTENTIONS-DURABLES-RAPPORT-2026-10-05.md).

Aucun rapprochement admin ou tombstone après ACK, aucune garantie exactement une fois métier inter-redémarrages, aucun daemon permanent ni production globale. L’étape suivante est un raccord unique MCP/collecteur/SQLite/M10 HTTP, avec effet source synthétique annoncé. La préparation Git reste locale faute d’identité GitHub disponible.

## Raccord intégré supplémentaire — r363

**Cinq parcours dans le fichier complet, Oxlint/Oxfmt/Ruff verts.** Les deux nouveaux cas traversent le runtime MCP et l’observer réels, la SQLite du transcript et M10 Python HTTP. Le processus source constate lui-même l’intention persistée et zéro lot avant réponse ou perte de transport. Une reconnexion réelle précède les refus de nouveaux effets ; l’incertitude survit à la réouverture de la base. [Preuve et limites](../grs/memory/M10-MCP-COLLECTEUR-E2E-RAPPORT-2026-10-05.md).

Les trois cas antérieurs sont inclus dans ces cinq, pas ajoutés une deuxième fois. Ticket, admission provider et résultat source restent synthétiques ; le parcours modèle/runner/outil métier réel demeure ouvert. Aucune modification de code de production dans cette tranche de qualification. Le diagnostic opérateur est qualifié dans la tranche suivante; le rapprochement humain demeure ouvert.

## Diagnostic opérateur M10 — lecture seule qualifiée

Commande Core `opsys database postflight --agent-id <id> [--json]` : sélection explicite, ouverture canonique read-only et instantané borné. Intentions incertaines séparées des lots de remise; base/schema/table absents ne deviennent pas une file vide. Aucun rejeu, purge, migration, envoi ou nouveau tool modèle. **r37321/21 + r37428/28 sur mêmes sources**, cinq fichiers complets, contrôle SQL global et lint/format verts. [Rapport, mode opératoire et limites](../grs/memory/M10-DIAGNOSTIC-POSTFLIGHT-RAPPORT-2026-10-05.md).

Revue Luna appliquée aux bornes SQL et à l’ID invalide; échéance ne vaut pas admission. Compilation globale r375 non qualifiée : marge mémoire sous prérequis, aucun compilateur lancé. Le diagnostic est local à l’opérateur du Core, pas encore un pont dashboard ni une réconciliation humaine. La file de travail continue; aucune promotion globale, daemon24h ou publication distante annoncée.
