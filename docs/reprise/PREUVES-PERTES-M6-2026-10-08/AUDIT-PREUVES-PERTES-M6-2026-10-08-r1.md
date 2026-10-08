# M6.13 — preuves PERTE/BRIS et aperçu protégé

Le lot relie les pièces de fichiers, la déclaration de matériaux, les preuves append-only et leur consultation admin au même WCT. Il prolonge le contexte M3/M4/M6 du parent `28c467c8f88ed48fb089367d1e06f5a67ff896d2`. OPSYS-AI demeure **PARTIEL** : ce lot ne ferme pas toutes les familles profondes d’alertes M6.13 ni les dix départements.

## Comportement livré par le candidat

L’ACK fichier est validé contre la mutation persistée et les indices réellement reçus. Un ACK incomplet, incohérent ou inconnu conserve l’intention et son UUID. Les anciens reçus envoyés sans preuve de confirmation restent bloquants. Avant une déclaration, chaque fichier local est relu, haché et rapproché de son état serveur sous une autorité vivante. La sérialisation couvre les deux types de déclaration M6 ; une intention antérieure inconnue bloque les nouveaux effets pour le même objet.

Le formulaire employé conserve notes et captures dans le brouillon de son propriétaire, lie les preuves aux positions finales des lignes PERTE/BRIS et utilise la capture autorisée avant les opérations asynchrones de caméra et de stockage. Le coût sensible reste absent. La note seule est un état visible ; l’achat terrain conserve sa voie historique.

`m6_declarer_materiaux_avec_preuves_appareil` réutilise le writer M6, ses cascades et les gardes DEVICE/N3. Identité, cible, quota, relations des preuves et CAS sont vérifiés avant les effets. Stock, preuves et idempotence sont annulés ensemble sur panne ou postcondition refusée. Les preuves se lient aux véritables indices et hashes du registre principal. La confirmation locale conserve les métadonnées réelles du registre qui permettent de vérifier ces relations au redémarrage.

`m6_lire_preuves_pertes_wct_appareil` retourne des pages explicitement courantes à l’admin actif : quantités décimales textuelles, références, notes, dates enregistrées et manques distincts. Une lecture avec métadonnées de mutation est refusée avant réclamation. L’écran admin expose la différence entre preuve absente, note seule et photos déclarées, et ne conserve pas de cache d’autorité.

L’aperçu emprunte une route binaire Gateway DEVICE et un bridge ASGI privé à credential séparé. Le sélecteur est fermé : WCT, référence de preuve index/hash, position de photo. Il ne permet pas un hash CAS libre. Le bridge vérifie les octets, décode réellement PNG/JPEG avec Pillow existant et borne taille, dimensions et pixels avant les headers. Le Core vérifie taille/SHA/ETag/MIME, revalide l’autorité avant chaque émission et ne mélange pas une erreur JSON aux pixels après les headers.

Le client natif existant assemble le flux dans un fichier temporaire privé, vérifie taille et SHA avant rendu, puis purge sur changement de cible, réseau, session ou autorité. Un lecteur dont l’annulation ne termine pas ne retarde plus le nettoyage ; un callback d’erreur d’une ancienne image ne supprime plus le nouvel aperçu.

## Preuves et régressions

Le registre final fournit les empreintes, préimages, reçus, commandes, résultats, ressources et limites exactes. La chaîne de preuves distingue tests purs, tests de collaboration, captures SQL, HTTP réel, rejeu client et export Metro.

La campagne locale Native comporte **45 captures réelles** du Gateway opaque DEVICE vers MCP/ASGI et SQLite/CAS, sur des données explicitement fictives. Le coordinateur a vérifié les 93 fichiers du manifeste, chaque réponse UTF-8 et son hash, les 49 tables intégrales par paire, les 39 lectures/rejeux sans mutation et les six phases dont les effets sont explicitement attendus. La révocation SQL contrôlée modifie seulement la table `roles`. La photo nominale comporte 307 899 octets et une lecture CAS ; les revalidations privées ne relisent pas le CAS. Après un préfixe de 65 536 octets, la révocation coupe le flux sans JSON ajouté. Les redémarrages conservent corps et UUID ; les groupes de processus sont arrêtés et les credentials/base privés supprimés.

Ces 45 captures comprennent un premier segment de 32 appels et une continuation de 13 appels sur le même monde/source, dans de nouveaux processus. Les préparations et oracles rouges restent conservés. Ce total ne représente pas une nouvelle exécution uniforme de 45 appels verts. Les effets des dépôts, déclarations et refus journalisés sont décrits séparément ; « sans mutation » ne s’applique pas à ces écritures.

Le build Core complet frais a réussi en 230,409 secondes, sous la borne de 16 Gio : pic mesuré de 11 259 064 320 octets. Le sous-arbre Core de travail est `4cf65c1d2e8f2c9129d75336fa3f5bf975a5cb21`. Les 11 287 fichiers du dist sont hachés ; ses deux algorithmes de sérialisation de manifeste sont explicitement distingués. Ce build qualifie ce sous-arbre ; le HEAD Git parent et sa CI ne sont pas rebaptisés comme preuves du nouveau commit.

La revue indépendante a reproduit puis fermé les défauts de délai des threads privés, du callback de caméra ancien et des références ACK contradictoires. Les probes originaux restent inchangés. Les deux P2 admin, annulation/nettoyage et erreur d’image périmée, ont également leurs rouges et clôtures conservés. La qualification jointe fraîche et les dispositions des deux anciennes suites de fixtures sont ajoutées au registre final avant publication.

## Limites et suite

La preuve des octets et de leur association déclarée n’établit pas la scène, la cause, la date du dommage, le lieu ni l’auteur réel de la photo. Les dates serveur et déclarées restent distinctes. Aucun employé n’est accusé automatiquement.

Les tests mobiles utilisent des frontières natives simulées. L’export Android construit le JavaScript ; il ne prouve pas un téléphone, Hermes, la caméra réelle ou ExpoSQLite natif. Le Native qualifie SQLite local, pas la concurrence PostgreSQL. Le bridge limite deux opérations coûteuses actives ; l’annulation ASGI n’interrompt pas un appel SQL ou un décodage Python déjà exécuté. La fermeture du client intervient après le buffering initial Core dans cette campagne.

Les bornes extrêmes, corruptions et rollback disposent de tests SQL/ASGI distincts. La campagne Native emploie les quotas ordinaires DIRECT 5 400 et Cap 800 avec deux pertes ; elle ne prétend pas exercer tous les maximums de 24 lignes, 10 000 entrées et 10 Mio. Les pages restent courantes sans snapshot multipage figé.

Le parent 28c dispose de six workflows CI réussis. La nouvelle CI applicable doit viser le commit exact de ce lot. Docker est inaccessible localement ; les résultats runners sont identifiés séparément. Aucune fusion, production, donnée client, commande fournisseur, paiement ou publication publique n’est réalisée.

Les 302 fichiers sources et 124 supports du transfert sont rapprochés à nouveau ; les 104 références de preuves exclues restent explicitement indisponibles/non réexécutées. Supplément généré et conversations absentes restent inconnus. Toutes les préimages, rouges, verts et dispositions de ce lot sont conservés dans la capsule par liste explicite.

La suite conserve les familles d’alertes de pertes, bris, usage inexpliqué, seuils et récurrence, classification humaine des causes, coûts, rétention et exploitation. Chaque capacité restante garde dépendances et critères. La verticale M7→M1→M2→M3→M4/M6→M5→M8/M9/M10 reste le fil du programme et les identifiants communs restent canoniques.


Date Toronto : 2026-10-08T17:20:36.525283-04:00. Qualification finale jointe : 4925 tests mobiles/211 suites, TypeScript global sans erreur, 1921 cas backend (1 ignorés explicitement), Ruff et verifier227/135 verts. Les huit anciennes fixtures ont été corrigées sans relâchement de production ; rouge initial conservé. La campagne backend large conserve 4 628 réussites, 35 erreurs de préparation et deux échecs dans le seul module météo M4, ainsi que 20 tests PyVRP non exécutés et un Docker/PostgreSQL inaccessible. La comparaison au parent exact et la disposition du moteur météo local sont dans le reçu distinct, sans présenter cette campagne comme verte.

Export Android réel : 1 595 modules, SHA bundle `d46de650b6d47fae6bd03fc231f87eea4f284dff00c377acdb727443d6d54486`. Aucun téléphone déduit. Les 75 sources comprennent deux tests existants dont les fixtures de reçus sont remises au contrat fermé. La CI du nouveau commit exact reste à obtenir après publication privée normale.
