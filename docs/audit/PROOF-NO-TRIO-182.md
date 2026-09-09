# Preuve sans trio — adaptation bornée à #182 / PR #622

## Décision et portée

Nathan demande de retirer le trio tout en imposant des contrôles techniques réellement verts. Ce candidat ajoute le profil explicite `EXECUTION_RECEIPTS_V1` pour la seule tâche `SONAR-DIAGNOSTICS-182`. Aucun vote n'est fabriqué ; `reviews` doit être vide, et un dossier de revues existant ne peut pas être ignoré. Le mode historique `SEALED_REVIEWS` reste inchangé pour les autres tâches. Cela ne réalise pas la refonte CLR-003 ni une qualification globale du Core.

Le nom du job `proof-sealed` est conservé pour ne pas modifier les workflows possédés par d'autres missions. Son rapport distingue les politiques : le nouveau profil affiche `review=NOT_PERFORMED` et `reexecution=SEPARATE_CI_JOBS`, jamais un trio fictif. Aucun seuil Sonar, scanner, test ou protection GitHub n'est supprimé.

## Contrat du nouveau profil

Le vérificateur existant recalcule toujours le diff et contrôle le manifeste des revues. Pour ce profil, il mesure aussi les chemins modifiés par Git : ils doivent rester dans les six fichiers explicitement autorisés. Un autre chemin de code bloque. Les six fichiers source/tests, y compris le vérificateur lui-même et les anciens tests de scellement, sont relus et comparés à leurs SHA-256.

Trois suites sont exigées : exporteur (au moins 112 cas), nouveau profil (58 cas), ancien vérificateur (28 cas). Chaque reçu contient les versions Python/pytest, les arguments exacts, le code retour réel, les compteurs de collecte/désélection et les événements pytest setup/call/teardown. Échec, absence, test ignoré, xfail/xpass, événement incomplet, doublon, mauvais fichier de test, compteur booléen ou code retour non nul bloquent.

Neuf artefacts sont obligatoires et inventoriés exactement : pour chaque suite, un reçu JSON compressé zlib, stdout et stderr. Le hash de chaque artefact est vérifié ; toute modification, omission ou addition bloque. JSON ambigu, compression tronquée, suffixe ajouté, taille supérieure à 2 Mio compressée ou décompressée et liens symboliques sont refusés. Les arguments contenus dans un reçu ne sont jamais exécutés par le vérificateur.

## Nature de la preuve

Les reçus sont des traces d'exécution dont l'intégrité et la cohérence sont contrôlées, pas des attestations signées par un tiers. Un acteur contrôlant simultanément le code, le vérificateur et les reçus pourrait les falsifier : ce modèle de menace n'est pas fermé ici. Les jobs CI existants continuent de réexécuter les tests et scans indépendamment du contenu des reçus.

Les reçus locaux ont été produits par le harnais `capture_receipts.py` fourni dans le paquet de travail : trois invocations réelles de pytest, hashes d'entrée avant/après, événements pytest bruts et sorties conservées. Un job temporaire de capture sur cette branche reprend ces suites dans le dépôt complet et ne publie que le manifeste et les neuf traces. Le workflow de capture n'est pas destiné à main. Tout échec de capture conserve la PR en rouge/brouillon.

## Vérifications et résultats négatifs

Avant implémentation : 50 tests du profil échouaient ; l'intégration échouait ensuite sur l'absence de verdicts. Après correction et durcissement : 198 tests locaux passent (112 + 58 + 28), aucun ignoré. Sept mutations finales sont détectées : hash d'entrée, hash d'artefact, test non passé, plancher de tests, périmètre, reçu périmé et exécution partielle. La première mutation de hash d'entrée survivait parce qu'une autre garde rejetait les mêmes fixtures : ajout d'un cas altérant uniquement le manifeste supérieur, résultat négatif conservé.

Le snapshot local provient d'une archive Git des chemins concernés au SHA `6f6aaa69a936eb32d5469e75562f575d89b8dfb1`. Il ne s'agit pas d'un clone complet. Ses hashes source sont vérifiés ; les contrôles CI du nouveau candidat doivent encore être lus avant toute promotion.

## Retrait et suite

Rollback : retirer le profil, son branchement et ses artefacts sur la branche candidate, sans réécrire main. Les anciennes revues et les données produit restent intactes. Aucune fusion n'est autorisée par cette documentation. La couverture Sonar non importée, la collecte privée Sonar et les défauts de main/#612 restent distincts.
