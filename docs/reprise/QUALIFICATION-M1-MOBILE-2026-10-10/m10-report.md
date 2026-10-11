# M10 D1 — sélection contradictoire fermée

Le contrôleur efface la sélection quand une réponse serveur contredit les métadonnées immuables de sa ligne d’index. La fermeture RAM est attachée à l’affaire et à la référence du document. Une resélection suspendue, une panne, un rafraîchissement ou un nouveau brouillon ne réhabilitent pas cette cible ; un détail serveur cohérent la réouvre. Le changement de session efface cet état privé.

Cette mémoire RAM évite le contournement d’une simple remise à null : auparavant `selectionner` réinstallait la ligne avant son attente réseau. Aucun stockage durable ni nouvelle permission n’est ajouté. Les différences de statut et d’activation restent admises ; une panne ordinaire, sans contradiction préalable, conserve le geste fondé sur l’index. Un nouveau document indépendant reste possible. Les intentions inconnues/permanentes et leur identité sont inchangées.

## Preuves fraîches

- RED sur production préimage : 8 échecs attendus, 1 succès témoin, 25 tests non sélectionnés ; 1,736 s, RSS 385114112 octets, sortie 1.
- GREEN, fichier complet : 34 succès, aucun échec/ignoré ; 1,889 s, RSS 395120640 octets, sortie 0.
- Chaque wrapper ferme EOF et ses propriétaires avec stratégie PIDFD. Budgets : 120 s, 1,5 GiB RSS, 16 MiB de logs, un worker.
- Les six variantes immuables (titre, empreinte, points, octets, auteur, horaire) refusent activer/déposer/retirer : aucune création UUID, aucun appel au vidangeur, dépôt RAM vide. Leur resélection cohérente permet ensuite une intention réelle dans le dépôt RAM.
- Les nouveaux témoins couvrent resélection suspendue puis panne, création indépendante et panne ordinaire. Les cas existants de statut mutable, révocation, résultat inconnu, permanence et ordre restent dans les 34 succès.

Le contrôleur, les lecteurs stricts et le dépôt mémoire sont réels ; les réponses de transport sont substituées et fictives. Les compteurs réseau observés sont ceux du double de vidangeur. Ces tests ne prouvent ni une contradiction réelle du backend, ni un échange HTTP, ni SQLite/Expo/téléphone. Aucun nouveau test de rendu n’a été exécuté ici.

## Conservation et remise

Deux fichiers seulement sont modifiés, avec préimages, copies finales et diff complet. Sur l’inventaire ciblé de 611 fichiers mobiles, les 609 autres sont identiques ; Core4 et les 623 entrées fixes GREEN sont inchangés. Les deux fichiers Briefing du propriétaire parallèle sont exclus explicitement. Les 15 imports mobiles effectifs sont attendus et n’atteignent pas Briefing.

`OWNED-SOURCE2-FROZEN-r1.json` libère les deux sources. `receipt-final-r1.json` lie leurs empreintes aux deux campagnes. Les JUnit sont dérivés des JSON Jest fermés et identifiés comme tels. `COMMON-FOUR-FILES-QUALIFICATION-INACTIVE-r2.json` prépare pour Root les dix suites affectées, types, lint quatre fichiers et quatre shards globaux. Cette préparation reste inactive jusqu’au gel Briefing et à la capture commune fraîche : aucun succès global, typage, lint ou rendu supplémentaire n’est revendiqué.
