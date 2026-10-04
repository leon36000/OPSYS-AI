# Préparation CSV en une action — lot R23

Contrat arrêté par ROOT le 2 octobre 2026 UTC, après la clôture [R22](../research/R22-2026-10-02/README.md). Implémentation qualifiée localement dans [R23](../research/R23-2026-10-02/README.md); voir le [bilan et les limites](REPRISE-PREPARATEUR-BILAN-R23.md).

## Résultat attendu

Un administrateur peut préparer le même lot CSV durable en un clic. Le serveur réutilise fusion_csv.traiter, au plus vingt fois, avec cent lignes et une transaction indépendante par appel. Chaque appel revalide identité, révision, snapshot M5 et quota. Aucune nouvelle base, file, table, bibliothèque, tâche LLM ou écriture comptable finale.

Routes privées : POST /api/fusion-operationnelle/lots/{lot_id}/preparer et formulaire POST /fusion-operationnelle/lots/{lot_id}/preparer. Le lot vient du chemin validé; les paramètres de requête sont refusés. L’API exige JSON UTF-8 borné à 16 KiB, sans doublon, et exactement revision_attendue (entier strict positif). Le formulaire exige exactement csrf et revision_attendue, urlencoded borné. Authentification admin/owner vivante et CSRF précèdent toute préparation. Aucun plafond, budget, rôle ou source n’est fourni par le navigateur.

## Transactions et arrêts

Le plafond serveur est vingt tranches, cohérent avec les 2 000 lignes M5. Budget total indicatif de huit secondes et seuil par tranche de deux secondes, mesurés par horloge monotone uniquement aux frontières. Ces seuils sont **coopératifs**, sans borne garantie de durée HTTP : le parseur, le snapshot ou l’attente de verrou SQLite peuvent dépasser un seuil dans la tranche courante. Aucune transaction n’est interrompue au milieu. Le plafond de travail demeure réel même si une opération dépasse le budget.

Le service s’exécute dans le threadpool Starlette pour garder la boucle HTTP disponible. La route surveille la déconnexion et transmet un événement d’arrêt coopératif; le service le consulte avant et après chaque tranche. Une annulation demande aussi l’arrêt. L’opération en cours peut néanmoins finir ou échouer; aucun job n’est détaché, planifié ou relancé. Aucun travail supplémentaire ne commence après observation de l’arrêt.

Arrêt immédiat au terminal, sans progression, au plafond, au budget, à la déconnexion observée ou à la première erreur. Pas de retry automatique et pas de rattrapage de révision après conflit. La révision suivante est uniquement celle du commit précédent. Les commits antérieurs restent durables; pour reprendre, recharger le même lot puis soumettre sa révision courante. Une répétition avec l’ancienne révision est un conflit, pas une préparation dupliquée.

Les erreurs de métier gardent leur statut/code stable, sans résumé de données. Une révocation produit 403 sans nouvelle progression ni détail du lot; les commits antérieurs restent durables. Un verrou SQLite occupé reconnu produit 503 STOCKAGE_OCCUPE, sans SQL, paramètres ou exception brute; les autres erreurs inattendues gardent 500. Une panne après plusieurs commits ne les annule pas : le GET privé permet de connaître la progression.

## Résumé autorisé

Une lecture de métadonnées dédiées revalide identité et snapshot dans la transaction, sans déchiffrer les lignes et sans appeler lire ou retourner _vue_lot intégralement. La réponse et le HTML ne rendent que lot ID, statut, révision, curseur, total de lignes, nombre de propositions, tranches exécutées, plafond serveur, durée et code d’arrêt stable. Aucun compte, hash, montant, cellule, nom de fichier, clé, nonce ou ciphertext.

L’état terminal présent à l’entrée est un no-op vérifié, avec zéro tranche; un snapshot devenu obsolète masque toujours les propositions. Un snapshot qui change avant le résumé final doit être détecté. Une erreur de droit pendant cette relecture refuse toute réponse métier.

## Preuves requises

- Préimages datées avant la première modification, sans écraser les preuves R22.
- Parcours API et HTML jusqu’au terminal sur plusieurs tranches; un cas de 2 000 lignes démontre le plafond réel.
- Corps/media/champs/CSRF refusés avant travail; pas de plafond contrôlé client.
- Budget et arrêt coopératif contrôlés aux frontières avec horloge/événement injectés dans les tests; pas de promesse de timeout dur.
- Concurrence même révision, reprise après commits partiels, verrou reconnu, révocation, quota/clé, snapshot modifié entre tranches et avant réponse.
- Parser appelé une fois, pas de doublon de ligne/provenance, audit de l’acteur effectif, réponse sans données comptables.
- Campagne ROOT fraîche, sources stables et contrôles de qualité ciblés après revue.

PostgreSQL demeure refusé par le pilote. Un daemon autonome, l’ingestion multi-format et la classification massive restent des lots distincts.

## Résultat local

ROOT : 496 tests intégrés, zéro échec/erreur/skip, durée JUnit 93,064 s; 1 093 empreintes
sélectionnées identiques avant/après. Les 29 nouveaux cas protègent ce contrat, notamment
reprise après commit, concurrence et relecture finale de droits/snapshot. Le cas de 2 000 lignes
neutralise l'horloge du service pour isoler le plafond; il ne mesure pas une latence de production.
Les essais d'arrêt injectent la déconnexion ou l'annulation; ils ne prouvent pas une panne réelle de socket.
Ruff sur les trois surfaces et le contrôle du diff passent. Les premières erreurs de collecte
ROOT et d'ordre des imports restent archivées; le test corrigé utilise le mode d'import natif.
