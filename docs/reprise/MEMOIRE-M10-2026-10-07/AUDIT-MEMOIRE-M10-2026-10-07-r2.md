# M10 intégré et qualification du socle — Toronto, 7 octobre 2026

OPSYS-AI reste **PARTIEL**. Cette continuation privée part du commit `21ab50cd259bf46bdeca5039f9a98e74cee74c0c`. Le registre exhaustif associé rapproche les 302 sources et les 124 supports du pack léger, avec leurs empreintes de transport, préimages Git et contenus intégrés. Les 104 preuves exclues, le supplément généré et les conversations absentes restent absents ou inconnus ; aucune exécution n’est déduite d’une référence.

## Tranche M10

L’écran admin sépare les signaux, décisions et révisions. Deux lecteurs canoniques ajoutent un catalogue de références et le dossier des deux faits. Le catalogue affiche des pages courantes de huit éléments au plus ; les signaux restent bornés à 50 et au budget de 5 400 caractères. Les omissions et les références retenues par confidentialité sont comptées. Les pages et les lectures indépendantes ne constituent pas un snapshot atomique.

La garde confirme l’admin actif avant le registre. La confidentialité porte sur le signalement, les deux faits et le dernier arbitrage. Le lecteur refuse entièrement un dossier privé, invalide ou trop grand, sans exposer une tête privée globale dans le catalogue. Le domaine développement reste distinct du registre affaires. Les appels internes sans identité conservent leur contrat.

Le contrôleur exige une session actuelle, le réseau, deux faits contenant des champs, un statut cohérent et une file locale lisible. L’outbox existante persiste l’UUID, la personne et les arguments avant le réseau. Le reçu natif de onze champs doit correspondre à la cible, au choix, à la personne et au hash canonique. Un reçu ancien ou invalide reste conservé ; un résultat inconnu garde son intention et bloque un nouvel effet sur la même révision. Ni motif, fusion ni suppression de fait n’est inventé.

Le cache est informatif et personnel : signaux et pages de références seulement. Les dossiers et statuts restent au serveur. Une perte de réseau masque la comparaison ; un changement d’identité ou de rôle masque les réponses tardives. Un refus d’outil ne sert jamais de cache pour cette lecture. Le contrat existant conserve toutefois le cache daté après un refus d’outil ; la purge est portée par le cycle d’identité confirmé. La capture de révocation backend prouve le refus des données fraîches, sans promettre une purge automatique déclenchée par chaque réponse d’outil.

## Corrections reproduites du socle

- Les nouveaux `OPSYS_HOME` sont créés en mode `0700`, même sous umask `0002`. Les droits d’un répertoire existant ne sont pas modifiés ; les gardes continuent de refuser un home non privé.
- L’écriture et la lecture des quotas utilisent le jour UTC déjà canonique de l’admission. Les jours explicites et les lignes historiques sont préservés. Les tests couvrent minuit UTC et 23 h Toronto, les refus de dépassement, l’upsert et la conciliation. Les calculs financiers sont inchangés.
- Le SDK d’embeddings local reprend une seule fois un refus explicite `503` par lot, après une seconde. Les autres erreurs et résultats réseau inconnus ne sont pas rejoués. Le serveur et sa limite de concurrence restent inchangés.
- Le harnais de diagnostic installateur isole les journaux fictifs HOME et Core. Son chemin historique par défaut est conservé ; les assertions de secrets et leur masquage restent actifs. Aucun fichier de production `install/` n’est modifié.
- Le harnais CI attend la fin effective des descendants dont il a établi l’identité avant d’effacer les manifestes. Les délais sont bornés et les pidfd sont fermés. Une racine morte avant ou pendant la découverte conserve les manifestes avec une erreur explicite ; des descendants devenus inconnus ne sont pas tués par un PID de manifeste. Les états Linux morts Z/X/x sont distingués des états vivants ([documentation Linux](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html)). Les rouges et la revue qui a trouvé cette seconde course sont conservés.

## Preuves et limites

Le mobile intégré passe **3 140 tests, 154 suites**, ainsi que TypeScript. Les contrôles Python affectés passent **1 291 tests**, avec un skip PostgreSQL explicite. Ruff et le vérificateur métier passent : **10 départements, 219 outils, 127 déclarations d’appareil**, dérivés du schéma canonique. Les bornes numériques du lecteur catalogue sont vérifiées localement ; leur application générale par le validateur de schéma reste une limite distincte.

La Gateway Node réelle a exécuté **13 phases** sous appairage DEVICE opaque, avec HTTP MCP et SQLite réels : cinq lecteurs, refus de profils, usurpation, arbitrage, rejeu, redémarrage backend, conflit UUID et rôle retiré. Les tables métier restent inchangées pendant les lectures. Deux tentatives de catalogue distant au démarrage sont bloquées par la garde réseau du test ; aucune garantie sur tout le réseau de la machine n’est annoncée. La capsule utilise exclusivement l’allowlist publique ; tokens, configurations privées, bases et états Core en sont exclus.

Le build Core complet local passe en **89,925 secondes**, avec un pic de **10 777 313 280 octets**. Le JavaScript de démarrage mesure **371 238 octets gzip**, sous le plafond inchangé de 371 332. L’export Android JavaScript passe ; la compilation Hermes locale a échoué sur le binaire x86-64 fourni, incompatible avec la machine ARM64. Téléphone, Expo SQLite et Hermes natifs restent non qualifiés.

Le socle local complet r3 est conservé : **4 367 réussites, 224 skips, 3 échecs**, sur 4 594 cas, sans variation des sources pendant l’exécution. Deux oracles rootless exigent `cpu.max`, absent du cgroup de ce poste ; ils échouent avant de tester les helpers. Le troisième échec est une assertion de test Hermes au jour local : les hooks comptaient et alertaient correctement au jour UTC. Ce test est corrigé sous horloge UTC figée, puis **95 tests voisins passent, 5 skips PostgreSQL**. La nouvelle CI exacte devra requalifier le socle complet ; aucun succès global local n’est annoncé par addition de reçus ciblés.

La CI de `21ab50cd` reste rouge et scellée : **4 547 réussites, 1 échec, 17 skips, 1 warning** du socle ; gate dérivé. Les 77 échecs marketing du parent sont fermés. Cinq autres workflows passent, soit 35 jobs verts, deux rouges et deux Docker Desktop opt-in ignorés. Le seul échec de nettoyage est traité dans cette continuation ; seule sa nouvelle CI exacte pourra fermer cette preuve. Les historiques rouges et verts restent disponibles séparément.

## Continuité

M1/T4.26 possède un candidat isolé : digest daté, transfert serveur sans cache de contacts/messages, liens depuis les attentes existantes, Gateway réelle et tests mobiles distincts. Il n’est pas livré par ce commit M10 et doit être rapproché du futur parent exact avant intégration.

La verticale M7→M1→M2→M3→M4/M6→M5→M8/M9/M10, les dix départements profonds, le Core fork, les outils déterministes, permissions, dashboard, quatre profils hors ligne, avatars et mémoires métier/développement séparées restent requis. Cette tranche n’active aucun prestataire, paiement, envoi public, fusion ou déploiement de production.
