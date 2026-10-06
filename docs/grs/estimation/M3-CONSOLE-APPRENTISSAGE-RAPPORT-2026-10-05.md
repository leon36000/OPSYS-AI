# M3 — Diagnostic de réception des chantiers dans la console

État au 5 octobre 2026 : page et API natives qualifiées sur ASGI/TestClient et SQLite réel avec données fictives. **225 tests passent dans sept fichiers complets en r392**, Ruff réussi; 24 cas portent sur le nouveau raccord. Cette tranche rend visible la réception M4→M3; elle ne mesure pas un gain d’apprentissage et ne termine pas M3.

## Problème et comportement livré

Le [diagnostic M3 existant](M3-COUVERTURE-APPRENTISSAGE-RAPPORT-2026-10-05.md) pouvait révéler une publication de fin de chantier sans reçu M3, mais aucun écran ne permettait à l’administrateur de le consulter. La page Connecteurs propose maintenant « Consulter les écarts de réception M4 → M3 ». Elle mène à une page indiquant les publications M4, reçus M3, identités recoupées, publications sans reçu et reçus hors de l’univers publié. Dix identités maximum par différence, le nombre omis et les deux empreintes sont affichés.

- Page : `GET /opsys/estimation/apprentissage/couverture` avec le préfixe console par défaut.
- API : `GET /opsys/api/estimation/apprentissage/couverture`, même résultat métier `couverture-apprentissage-identites/1`.
- Liens vers le diagnostic JSON et l’aperçu des faits candidats M10. Aucun bouton de relivraison, réparation, ingestion ou activation.

Un univers vide ne devient pas une calibration réussie. Les compteurs comparent des identités de publication/réception de cette instance; le contenu WCT, la provenance, la qualité terrain et la complétude historique ne sont pas attestés. Un reçu hors univers peut être historique; aucune cause n’est déduite. Le texte conserve explicitement « Aucun barème activé » et « aucun gain de précision mesuré ».

## Réutilisation et frontières

Le [routeur console](../../../src/opsys/console/estimation_apprentissage_ui.py) compose directement le service `couverture_apprentissage.auditer` et le lecteur de préfixe `_prefixe_recu_wct` existants. Aucune nouvelle dépendance, copie d’algorithme, table, migration ou modification du contrat métier. Le catalogue serveur doit être celui de `m3_estimation.outils` et contenir le diagnostic attendu. Un catalogue absent ou malformé refuse la lecture.

La session humaine signée est revalidée contre `identite.personne_active`. Administrateur ou propriétaire actif seulement. L’identité et les sources sont lues dans **la même connexion transactionnelle canonique**; une factory qui ne porte pas cette connexion est refusée. Les droits sont vérifiés avant/après le service et à nouveau après le rendu HTML ou la sérialisation JSON, avant restitution. Aucun contexte d’appareil n’est fabriqué. L’outil T0 appareil reste réservé à l’admin appareil et continue de refuser sans cette identité. Le propriétaire est admis par l’autorisation native de la console, sans extension des portées appareil.

## Refus et bornes

Sans session : redirection vers connexion sur la page, 401 sur l’API. Employé, vendeur ou rôle admin retiré : 403. Catalogue/source/backend indisponible ou connexion non canonique : 503. Source invalide, incohérente ou dépassant sa borne : 409, sans compteurs ni réflexion des valeurs invalides. Paramètres de filtrage : 400; POST : 405. Une réponse dépassant 64 Kio est refusée par 413, sans troncature.

Les bornes existantes restent appliquées avant décodage : publications M4 limitées à 2 000, identités ASCII de 1–128 caractères, reçus M3 limités à 20 000 maillons/65 536 octets chacun/4 000 000 octets cumulés puis 2 000 identités uniques. Seules les identités et le contrôle du producteur sortent du bus; les charges WCT ne sont pas sélectionnées. Les maillons de réception sont lus par le codec canonique pour vérifier leur forme. Les exemples d’identités restent internes à la console admin; leur syntaxe ne constitue pas une anonymisation.

SQLite uniquement : PostgreSQL reste non qualifié. Aucune création ou migration ne compense une source manquante. Les réponses sont `no-store`, `no-cache`, sous les en-têtes de sécurité/CSP existants, sans script externe. La lecture est un instantané comparable par empreintes, pas une surveillance live ni une preuve de toutes les publications historiques.

## Qualification et défauts corrigés

Les sept fichiers complets sont `test_console_estimation_apprentissage.py`, `test_console_connecteurs.py`, `test_console_memoire_apprentissage.py`, `test_couverture_apprentissage.py`, `test_portees_appareil.py`, `test_console.py` et `test_console_metier.py` : **225 réussites, zéro échec/erreur/ignoré**, puis Ruff des sources modifiées et de ces fichiers. Les 24 cas du raccord exercent HTML/JSON, admin/owner, refus d’accès avant lecture, cookie ancien, révocation après lecture/rendu/sérialisation, catalogue absent/malformé, connexion non canonique, source invalide, schéma absent, backend refusé, limite de réponse, exemples bornés et absence d’activation/mutation métier. Les parcours positifs interdisent explicitement l’appel au constructeur de contexte d’appareil.

Le scénario joint deux publications fictives et deux reçus fictifs canoniques : une identité recoupée, une publication sans reçu et une réception hors univers. Les tables bus/registres sont identiques avant/après les consultations; les charges privées et références lead ne sortent pas. La connexion par personne et les contrôles SQL sont réels, les fixtures métier sont fictives. La page existante Connecteurs mène bien au nouvel écran.

Historique conservé : r386 échoue sur une erreur de noms de rôle dans la fixture; r387 corrige cette erreur et les 18 tests échouent sur les routes absentes (404). r388 passe les 165 cas de la première sélection. r389 révèle le défaut de catalogue malformé (23 passent, un échoue) : le `TypeError` est maintenant traduit en refus 503 avant les sources. r390 passe les 225 cas mais échoue sur un import Ruff; r391 corrige le lint. r392 requalifie les sept fichiers après renforcement de l’interdiction d’identité d’appareil fabriquée. Ces essais ne sont pas additionnés pour gonfler le résultat.

La révocation est injectée dans les parcours contrôlés; SQLite `BEGIN IMMEDIATE` sérialise les écritures. Les tests ne prétendent pas démontrer l’interruption concurrente d’une transaction déjà engagée. Pas de navigateur rendu, TLS réseau, serveur externe, déploiement VPS, build Core, mobile, suite globale ou CI distante qualifiés par cette tranche. Aucun benchmark SQL, LLM, tokens ou précision sur corpus client.

Les preuves ROOT (sources exactes, préimages, variantes, plans, logs/JUnit et garde r386–r393) sont dans la [capsule](../../research/REPRISE-2026-10-05/preuves/M3-CONSOLE-APPRENTISSAGE-r1.tar.xz) et son [manifeste](../../research/REPRISE-2026-10-05/preuves/M3-CONSOLE-APPRENTISSAGE-r1.json). La revue Luna n’a pas eu lieu : modèle à capacité; ROOT a réalisé la revue et la qualification sans attente extérieure. Le scan de secrets r393 utilise la configuration par défaut sur les fichiers de cette tranche et ses références; il ne qualifie pas tout le dépôt ou les archives historiques.

## Suite orientée entreprise

Comprendre les écarts par les outils de livraison existants avant toute admission ou promotion. Qualifier PostgreSQL sur un environnement disposant des ressources nécessaires. Constituer un corpus client consenti et un jeu de validation distinct pour mesurer l’amélioration de l’estimation des durées/coûts; un compteur de réception ne remplace pas cette évaluation. L’app mobile et la vision géométrique gardent leurs propres critères de sortie.

Préparation locale pour la PR privée #623; aucun commit, push, fusion ou déploiement dans cette tranche. Les autorisations GitHub de l’environnement ne sont pas disponibles.
