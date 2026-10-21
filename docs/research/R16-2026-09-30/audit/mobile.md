# Audit mobile OPSYS-AI — 30 septembre 2026

**Cible :** `/workspace/OPSYS-AI-recent`, HEAD `2e56c0d5605dfe575bde9244f38924d5390f2674`. Audit en lecture seule ; aucune correction, aucun fichier du dépôt modifié. Le mobile contient **296 fichiers**, dont 287 sous `src/` et `app/`, 117 fichiers de tests et 27 fichiers de routes. Inventaire lexical, imports, fonctions et noms de tests : [mobile-inventory.json](mobile-inventory.json). Empreintes des 296 fichiers : [mobile-source-hashes.json](mobile-source-hashes.json).

**Verdict : FAIL pour la robustesse de la synchronisation et l'isolation des personnes ; PARTIAL pour la couverture du produit et des plateformes natives.** TypeScript et les tests existants passent. Ils ne prouvent pas les cas de reprise, de changement de personne et de concurrence décrits ci-dessous. Onze probes exécutés contre les fonctions réelles reproduisent ces comportements, sans exécuter le core.

## Constats, par risque

### MOB-01 — Captures d'une ancienne personne visibles et réémises sous la nouvelle personne

**Gravité : élevée. Confiance : élevée pour les fonctions exécutées ; intégration native non exécutée.**

`mobile/src/photos/mutation.ts:10`, `mobile/src/fichiers/candidats.ts:82` et `:94` filtrent seulement le chantier, le type et le statut, sans `proprietaire`. `mobile/src/fichiers/service.ts:74` lit toute la file et prépare ces captures. L'orchestrateur ne transporte pas le propriétaire de la capture dans les nouvelles mutations `fichier_bloc` ; `mobile/src/outbox/proprietaire.ts:39` leur pose donc la personne courante.

**Reproduction :** A laisse une photo après et une signature en brouillon pour I1. Sous B, `listerPhotosDuChantier` montre la photo de A et `candidatSignature` choisit sa signature. `preparerEnvoiFichier` produit deux blocs appartenant à B ; le vrai vidangeur les envoie avec la session de B. Le probe `cross_owner_capture_reissued` observe `draftOwner: A`, `newBlockOwners: [B,B]`, deux envois sous B.

Conséquence : divulgation locale, réattribution de preuve et transport possible de fichiers d'une autre personne. La quarantaine du vidangeur protège les lignes existantes, mais pas leur transformation en nouvelles lignes. `docs/architecture/MOBILE.md:613` documente la visibilité des brouillons et affirme qu'ils « ne partent jamais » ; cette dernière affirmation n'est pas vraie pour la préparation de nouveaux blocs. Un chantier partagé, une navigation directe vers son identifiant ou la réutilisation du téléphone suffisent côté mobile ; les permissions serveur restent une défense distincte.

Direction minimale : filtrer les lectures et candidats par propriétaire confirmé, préserver ce propriétaire lors de la transformation capture → blocs, puis vérifier la session avant et après les étapes asynchrones. Ne pas effacer les brouillons pour résoudre ce problème.

### MOB-02 — Complétion reçue hors de l'écran : `wct_id` perdu, matériaux bloqués

**Gravité : élevée. Confiance : élevée.**

`mobile/src/outbox/vidangeur.ts:270` persiste seulement le statut `envoyee`. Le résumé métier n'existe que dans `RapportVidange.resultatsAcceptes` (`:313`). Le schéma SQLite et `MutationOutbox` n'ont pas de champ d'accusé. Seul `mobile/app/(employee)/job/[id]/complete.tsx:196` lit ce résumé et écrit `wct_id` (`:202`). Les déclencheurs de `mobile/app/_layout.tsx:49` ignorent le rapport. `materials.tsx:63` exige le `wct_id` local ; `complete.tsx:227` désactive une complétion déjà envoyée.

**Reproduction :** le vrai vidangeur reçoit un accusé valide de huit clés pour une vraie mutation construite par `construireArgumentsCompleterIntervention`. La ligne persistée devient `envoyee`, sans WCT ; `lireWctIdCompletion` rend `null`. Le rapport transitoire contient bien `fictif-WCT1`. Probe `background_completion_ack_not_persisted`.

Conséquence : une soumission hors ligne, envoyée après reconnexion pendant que l'écran est fermé, peut clôturer le chantier sans permettre la déclaration des matériaux. Une panne entre la persistance du statut et l'écriture du WCT a le même résultat. Limite déjà reconnue dans `docs/architecture/MOBILE.md:1236`, mais incompatible avec la cascade de §6 et le hors ligne de §9.2 de la définition produit.

Direction minimale : enregistrer durablement l'accusé utile avec la transition `envoyee`, puis reconstituer le lien matériaux depuis cette donnée ; fournir une récupération sûre pour les lignes existantes.

### MOB-03 — Reprise serveur : fichier complet distant, fichier local éternellement incomplet

**Gravité : moyenne. Confiance : élevée.**

`mobile/src/fichiers/envoiOrchestrateur.ts:110` lit les blocs reçus ; `:118` ne les enfile pas. `mobile/src/fichiers/etatEnvoi.ts:52` compte uniquement les lignes locales `envoyee` et `:63` exige le nombre total déclaré. Les blocs évités ne sont pas représentés dans cet état ; l'accusé `complet` du dépôt n'est pas conservé.

**Reproduction :** fichier de deux blocs, bloc 0 connu du serveur, aucune ligne locale. Seul le bloc 1 est créé et accepté avec `complet: true`, `blocs_recus: [0,1]`. L'état local vaut `en_cours`, `blocsEnvoyes: 1`, `nombreBlocs: 2` ; `evaluerPreparationCompletion` rend `fichiers_en_cours`. Si tous les blocs sont déjà reçus, zéro ligne est créée et l'état reste `non_demarre`. Probes `server_resume_never_completes` et `server_already_complete_invisible`.

Conséquence : la reprise annoncée ne permet pas de terminer le chantier pour cette capture ; répéter la préparation coupe court sur l'état local `en_cours`. Le test actuel de reprise s'arrête après avoir vérifié qu'un bloc est enfilé (`envoiOrchestrateur.test.ts:123`), sans vérifier la complétion finale.

Direction minimale : réconcilier durablement les indices reçus et la référence serveur avec l'état local, puis tester reprise → réception → préparation de complétion.

### MOB-04 — Écriture partielle de la file : les blocs manquants ne sont jamais recréés

**Gravité : moyenne. Confiance : élevée.**

La boucle de `mobile/src/fichiers/envoiOrchestrateur.ts:116` persiste chaque bloc séparément, sans transaction globale. Après un arrêt ou une erreur de stockage au second bloc, `calculerEtatEnvoiFichier` déclare `en_cours` dès qu'un premier bloc existe. Le court-circuit `envoiOrchestrateur.ts:91` rend alors immédiatement `{ok:true, blocsEnfiles:0}`.

**Reproduction :** injection d'une panne au deuxième `depot.inserer`, dépôt réel mémoire conservant le premier bloc. Au redémarrage, la fonction réelle ne crée aucun bloc supplémentaire ; seul l'indice 0 d'un fichier de deux blocs subsiste. Probe `partial_enqueue_unrecoverable`.

Conséquence : attendre le réseau ne peut pas réparer les blocs qui n'ont jamais été écrits ; la photo et la complétion restent bloquées. Une capture identique garde la même empreinte et retrouve ce blocage.

Direction minimale : déterminer les indices locaux présents et en créer uniquement les absents, avec une insertion atomique ou une reprise documentée après panne.

### MOB-05 — Préparations concurrentes : doublons d'indices et faux état complet

**Gravité : moyenne. Confiance : élevée pour la concurrence logique, moyenne pour son calendrier exact en UI.**

Le montage de `complete.tsx:123` démarre la préparation sans attendre et sans poser `enTraitement` ; l'appui sur Terminer relance la même opération (`:146`). La préparation n'a pas de verrou par fichier. Le vidangeur a un verrou, mais il intervient après la préparation. `etatEnvoi.ts:52` compte les lignes au lieu des indices distincts.

**Reproduction :** deux appels concurrents réels avec le même état initial produisent `[0,0,1,1]`. Deux lignes d'indice 0 confirmées donnent `complet`, `blocsEnvoyes:2`, `nombreBlocs:2`, alors qu'aucun indice 1 n'est confirmé. `evaluerPreparationCompletion` rend `pret:true`. Probe `concurrent_enqueue_duplicate_indices`.

Conséquence : doublons, trafic inutile et annonce prématurée que les preuves sont prêtes. Le serveur vérifie séparément les indices et la référence complète, ce qui limite le risque de clôture incorrecte mais laisse des rejets définitifs et un état incohérent dans l'app.

Direction minimale : sérialiser la préparation pour l'ensemble personne/chantier/empreinte, imposer l'unicité des indices et calculer la complétude à partir de l'ensemble d'indices attendu.

### MOB-06 — Délai HTTP retiré avant la lecture du corps

**Gravité : moyenne. Confiance : élevée ; réseau HTTP local réel.**

`mobile/src/protocole/client.ts:63` efface le minuteur quand `fetch` livre les en-têtes ; `response.json()` est attendu ensuite (`:69`) sans limite. Ce client est utilisé par les lectures et le vidangeur. `identite/client.ts` conserve correctement son minuteur pendant la lecture du corps.

**Reproduction :** serveur HTTP local Node, en-têtes immédiats puis corps différé de 230 ms, `delaiMs:60`. À 120 ms, l'appel est toujours en attente, le signal n'est pas annulé ; il finit vers 250 ms en succès. Probe `transport_slow_body`.

Conséquence : une connexion terrain bloquée après les en-têtes immobilise la passe et son verrou, ainsi que les actions qui l'attendent. Un corps qui n'arrive jamais peut bloquer indéfiniment.

Direction minimale : couvrir la totalité du transport et du décodage par le même délai ; préserver la distinction délai/réseau/rejet.

### MOB-07 — Rupture pendant le corps HTTP 200 : événement classé en échec permanent

**Gravité : moyenne. Confiance : élevée ; réseau HTTP local réel et vrai vidangeur.**

Le `catch` de `client.ts:70` ignore l'erreur de lecture du corps puis classe le résultat sur HTTP 200 (`:85`). `estStatutReessayable(200)` vaut faux. Le vidangeur marque donc la mutation `echec_permanent` (`vidangeur.ts:266`) et ne la retente plus, même avec sa clé d'idempotence intacte.

**Reproduction :** serveur local qui livre HTTP 200 puis détruit la connexion avant le JSON. Résultat `{origine:http,status:200,reessayable:false}` ; une mutation passée par le vrai vidangeur devient `echec_permanent`. Probes `transport_disconnected_body` et `transport_body_error_permanent_mutation`.

Conséquence : un aléa réseau transforme un pointage, fichier ou autre écriture en refus définitif ; le serveur pourrait déjà avoir appliqué l'effet. Le contrat de reprise par la même clé existe précisément pour cette issue incertaine.

Direction minimale : traiter une lecture de corps interrompue comme un échec de transport réessayable, avec la même clé d'idempotence ; ne pas inventer un rejet métier.

### MOB-08 — Changement de session pendant la purge : état d'identité périmé appliqué

**Gravité : moyenne. Confiance : élevée pour la fonction ; durée et rendu natifs non mesurés.**

`mobile/src/identite/appliquerLecture.ts:26` compare la configuration avant `await synchroniserCaches(etat)` ; `:37` applique l'état sans nouvelle comparaison. Le hook réel appelle cette fonction (`hooks.ts:75`) et le nouvel appairage change l'état pendant que l'ancienne lecture peut être en cours (`:105`).

**Reproduction :** purge mise en attente, configuration remplacée par un nouveau jeton, puis purge libérée. La fonction rend `true` et applique l'ancien état admin/personne A avec l'ancien jeton, malgré la nouvelle session. Probe `identity_switch_during_purge`.

Conséquence : l'ancienne identité peut rouvrir provisoirement un profil et altérer le marqueur de caches pendant le réappairage. Le lien jeton/personne d'`obtenirSessionEnvoi` reste une défense qui empêche de confondre automatiquement les sessions d'envoi ; le finding ne prétend pas un contournement du contrôle serveur.

Direction minimale : revalider la session après les opérations asynchrones et rendre la synchronisation des caches consciente de la génération de session. Le test existant vérifie seulement un changement déjà réalisé avant l'entrée.

### MOB-09 — Réponse métier inconnue interprétée comme un accusé positif

**Gravité : élevée. Confiance : élevée pour l'état mobile ; effet final serveur dépend de ses contrôles.**

`mobile/src/fichiers/protocole.ts:162`, `m4/pointage.ts:230`, `m4/interventions.ts:235`, `m4/completion.ts:135`, `m4/consentementGps.ts:176` et `m6/materiaux.ts:128` rendent `accepte:true` sur une forme non reconnue. Le vidangeur convertit cet accord inventé en `envoyee` (`:271`). Cela contredit `mobile/README.md` : « une réponse illisible n'est jamais un succès », et l'invariant fail-closed d'AGENTS.

**Reproduction :** retour de transport réussi, mais payload métier `{}`. Le vrai interprète de dépôt accepte les deux blocs, le vrai vidangeur les marque `envoyee`, l'état fichier devient `complet` et la préparation rend `pret:true`, sans aucune confirmation serveur des indices. Probe `unknown_ack_is_success`. Il ne s'agit pas d'affirmer que le serveur courant émet `{}` : la preuve porte sur une frontière qui se comporte mal en cas de dérive, proxy, tronquage ou réponse incompatible.

Conséquence : événement considéré livré sans preuve, arrêt des réessais et références fabriquées comme si les fichiers existaient. Les approbations et les notes vendeur ont, au contraire, des lecteurs qui refusent l'accusé illisible. Le test `fichiers/protocole.test.ts:68` **exige ce succès inconnu**, donc protège actuellement le comportement défectueux.

Direction minimale : exiger l'enveloppe et les champs minimaux d'un accusé valide ; traiter les réponses incompatibles comme une issue incertaine récupérable, avec une erreur visible.

## Vérification exécutée et provenance

L'installation et les sorties ont été limitées à `proof/recent/mobile-copy`. Node **24.19.0**, npm **11.9.0** ; la CI prévoit Node 22.x. Le core n'a été ni installé, ni construit, ni exécuté. L'audit applique le skill `code-verification` et AGENTS : preuve avant verdict, source inchangée, distinction contrats/preuves/limites.

| Commande | Résultat | Preuve |
|---|---|---|
| `npm ci --ignore-scripts --no-audit --no-fund` | Code 0 ; 810 paquets, copie externe | [mobile-npm-ci.log](mobile-npm-ci.log) |
| `npm run typecheck` | Code 0, TypeScript strict | [mobile-typecheck.log](mobile-typecheck.log) |
| `npm test -- --ci --runInBand --coverage …` | Code 0 ; **117 suites, 2578 tests**, aucun snapshot | [mobile-jest.log](mobile-jest.log) |
| `node mobile-repro.cjs` | Code 0 ; **11 probes** avec assertions du comportement observé | script (archive : `/workspace/audit-opsys-2026-09-30/proof/recent/mobile-repro.cjs`), [résultats JSON](mobile-repro-results.json), [journal](mobile-repro.log) |
| `git status --porcelain` | Vide avant et après | [mobile-checks.json](mobile-checks.json) |

Les probes transpileront les fichiers TypeScript **réels** du dépôt en mémoire avec TypeScript ; ils ne copient pas leur logique. Le SHA-256 des octets est calculé par Node crypto. Le test HTTP utilise un vrai serveur local et le vrai `fetch` Node. Les probes d'orchestration utilisent les dépôts et le vidangeur réels avec des dépendances injectées : octets fictifs, panne de dépôt, état/accusé serveur contrôlés. Ils prouvent les transitions au niveau de cette frontière, pas un parcours Android/iOS ni une acceptation par le serveur de production. Toutes les données de probe sont fictives.

**CI :** le run mobile [36642024371](https://github.com/leon36000/OPSYS-AI/actions/runs/36642024371) est `success` au commit `1b1c70cb3549202a5301ba88452586cc462cdc4b`, terminé le 29 septembre à 22:53:09 UTC. Les métadonnées indiquent installation, contrôle de types et Jest réussis : [run](mobile-ci-run.json), [jobs](mobile-ci-jobs.json). L'arbre Git `mobile` est **identique** entre ce commit et HEAD : `2d1f8d0f8aaffb51a882af69679257d86197a08d` ; le workflow n'a pas changé. Ce résultat est donc pertinent pour ces mêmes fichiers, sans appeler cela une exécution CI à HEAD. `gh run view --log` n'a livré aucun contenu ; le téléchargement direct des logs du job a échoué avec Forbidden sur l'hôte de stockage des actions. Aucun nombre de tests CI n'a été inventé ; le nombre 2578 vient de l'exécution locale fraîche.

## Couverture et qualité des tests

La CI n'impose ni collecte de couverture ni seuil. L'audit a collecté explicitement **tous** `src/**/*.{ts,tsx}` et `app/**/*.{ts,tsx}`. Totaux : **65,75 % statements, 66,56 % branches, 64,61 % fonctions, 65,66 % lignes**. Il s'agit de la couverture d'exécution, pas d'une mesure de complétude fonctionnelle. Données brutes : coverage-final.json (archive : `/workspace/audit-opsys-2026-09-30/proof/recent/mobile-coverage/coverage-final.json`) ; regroupement : [mobile-coverage-summary.json](mobile-coverage-summary.json).

| Surface | Lignes | Interprétation |
|---|---:|---|
| Routes `app/` | **0 %** | Aucun rendu/exécution des 27 routes |
| `src/ecrans` | 98,93 % | Modèles purs bien exercés, câblage React absent |
| `src/protocole` | 100 % | Branches couvertes par réponses immédiates ; durée et corps interrompu manquants |
| `src/outbox` | 85,85 % | Logique solide, hooks/service natifs non exécutés |
| `src/fichiers` | 82,63 % | Pas d'enchaînement complet de reprise ni de concurrence |
| `src/identite` | 78,80 % | Fonction de purge testée, hook/cycle réel non rendu |
| `src/photos` | 47,50 % | Service natif de copie/capture non exercé |
| `src/signature` | 34,37 % | Service de persistance et WebView non exercés |
| `src/vendeur` | 94,01 % | Lecteurs et chargeurs, service natif absent |
| `src/admin` | 68,29 % | Composants de rendu à 0 % |

**Points forts des tests existants :** oracle indépendant Node crypto pour Ed25519 et SHA-256 ; vecteurs protocolaires figés et comparés dynamiquement ; vrai moteur `node:sqlite` pour DDL/migration/SQL ; table de transitions fermée ; absence de personne, autre personne, changement de jeton en cours de passe, 401/403 et quarantaine testés ; fixtures prises du vrai moteur pour les trois profils ; refus distinct des pannes et des listes tronquées ; cache par personne et tests écrivains/purge ; cohérence d'empreinte pour les pages de prévision ; textes fr-CA/en-CA contrôlés. Les tests ne sont donc pas globalement de simples miroirs de l'implémentation.

**Angles morts observables :** `protocole/client.test.ts` simule un AbortError immédiat au lieu de faire expirer une réponse ; ses faux `json()` répondent immédiatement. Le test de reprise fichier vérifie l'enfilage, pas le fichier prêt après accusé. Aucun test ne coupe l'écriture entre deux blocs, ne prépare deux fois simultanément, ni ne compte des indices dupliqués. La quarantaine est testée au transport, sans le trajet capture ancienne → nouvelles mutations. Le test d'identité périmée change la session avant l'appel, pas pendant la purge. L'accusé de complétion n'est pas testé à travers une fermeture/redémarrage. Enfin, certains tests imposent expressément que l'accusé inconnu soit accepté : cette attente doit venir d'un invariant de livraison, pas du code existant.

**Dessins de tests recommandés, sans ajout au dépôt :**

1. Transport réel ou stream contrôlé : headers reçus, corps retenu au-delà du délai ; même cas avec corps interrompu après effet serveur et rejeu sous la même clé.
2. Reprise complète : serveur a zéro/un/tous les blocs ; déposer le reste ; redémarrer ; la préparation doit être prête uniquement quand tous les indices sont confirmés.
3. Panne après chaque insertion de bloc, base SQLite réelle puis réouverture ; tous les indices nécessaires doivent finir présents une seule fois.
4. Deux préparations concurrentes via une barrière contrôlée ; unicité des indices et interdiction de complétude à partir de doublons.
5. A capture puis B reprend le même appareil et chantier ; aucune image/signature de A visible ni transformée/enfilée pour B ; retour de A conserve ses brouillons.
6. Réappairage au milieu de la purge ; l'ancien résultat ne modifie ni le profil ni le marqueur courant.
7. Soumission de complétion hors ligne ; écran fermé ; reconnexion ; processus arrêté après accusé ; matériaux restent accessibles au redémarrage grâce au WCT durable.
8. Réponses métier absentes, tronquées ou incompatibles pour chaque descripteur ; aucun `envoyee` sans accusé reconnu.
9. Rendu des routes critiques et test Android/iOS : capture/permission, disque plein, SecureStore inaccessible, WebView, SQLite natif, navigation et déclencheurs. Les fonctions pures ne prouvent pas ces chemins.

## Contrats et limites du périmètre

| Exigence / risque | Preuve la plus forte | Résultat |
|---|---|---|
| Appairage signé, clé privée/jeton dans SecureStore, rôle nommé | Tests crypto/protocole/contrat exécutés ; code natif inspecté | PASS logique, PARTIAL natif |
| Cache personne, refus distinct des pannes, liste coupée visible | Suites exécutées, fixtures moteur et lecteurs | PASS sur comportements couverts |
| Aucune mutation existante d'A envoyée avec B | Suites `proprietaire` / `suiviDuJeton` / `vidangeur` | PASS pour lignes existantes ; FAIL pour dérivation de captures MOB-01 |
| Reprise de synchronisation fiable | Probes de panne, reprise et concurrence | FAIL MOB-03/04/05/06/07 |
| Fichier réellement reçu avant complétion | Probes indices et accusé inconnu | FAIL état mobile MOB-05/09 ; contrôles serveur conservés |
| Cascade fin de chantier → matériaux | Vidangeur/accusé durable inspectés et exécutés | FAIL MOB-02 |
| Résultat d'identité lié à la session courante | Probe avec purge suspendue | FAIL MOB-08 |
| Quatre profils métier complets | Source routes + définition produit §9 | PARTIAL, périmètre client encore minimal |
| Parcours mobile réel appareil → core → moteur | Aucune exécution native ; CI mobile typecheck/Jest | INCONCLUSIF pour le déploiement mobile réel |

Les limites documentées ne sont pas toutes des régressions : `app/(client)/client.tsx` est un accueil minimal, `RoleNomme` n'accepte pas `client` car ce profil doit utiliser un lien signé ; pas de parcours client signé dans la tranche inspectée. GPS et pointages portent encore des preuves `fictif:true` du mode ombre, pas une collecte réelle complète ; notifications push et tâche système de synchronisation en arrière-plan absentes. Les déclencheurs AppState/NetInfo opèrent dans le processus vivant ; ils ne prouvent pas l'envoi après suspension/arrêt de l'app. Le formulaire matériaux en saisie et les notes/choix de complétion vivent dans le state React avant soumission ; l'audit n'en conclut pas une persistance de brouillon. Pas de purge post-confirmation des fichiers locaux, limite déclarée dans MOBILE.md:1827. Ces écarts au produit sont à traiter dans le plan de livraison ; les neuf findings ci-dessus sont des erreurs concrètes du comportement déjà câblé.

**Actions volontairement exclues :** aucune correction source/test/configuration ; aucun commit ou PR ; aucune publication, aucun déploiement, aucun appel à un appareil/compte réel ; aucune installation/exécution du core. Le présent rapport prouve l'audit et ses observations, sans annoncer une app prête en production.

PREUVE
