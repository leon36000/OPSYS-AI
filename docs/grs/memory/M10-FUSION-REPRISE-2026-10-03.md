# M10 / Fusion : audit RO et première tranche — 2026-10-03

- **Seams** : console Fusion CSV `src/opsys/console/fusion_ui.py` → service `src/opsys/fusion_csv.py` → parser/comptes M5; console de procédures M10 `src/opsys/console/memoire_ingestion_ui.py` → `MemoireEntreprise.procedures()` (`src/opsys/memoire/ingestion_procedures.py`, persistance dans `store.py`). Ce sont deux parcours distincts.
- **Fusion CSV déjà livré** : identité active admin/owner + CSRF; CSV UTF-8 CAD mappé explicitement, 1 MiB/2 000 lignes; clé d’idempotence de mutation, SHA source/snapshot, déduplication compte+mapping+snapshot; ciphertext AES-GCM; lots `RECU` puis jusqu’à 20×100 lignes/transactions, révision/cursor, reprise après erreur; provenance M10 `FINANCIAL`, pas de cellules/montants; quotas 64 lots/64 MiB. SQLite seulement; aucune écriture comptable finale.
- **M10 procédures déjà livré** : upload individuel TXT/MD UTF-8 attesté humainement « pas de PII/secret » (pas un scan), 1 MiB, 100 chunks max; clé admission idempotente, document/version SHA/auteur; état `RECU` → indexation transactionnelle `INDEXE` → activation humaine par CAS; oubli propagé. Portée fixe `m03-estimation/procedures/interne`; aucun embeddings à l’admission/indexation, recherche citations vérifiées. Quota 64 séries, 8 versions/série, 64 MiB sources.
- **Droits** : UI privée console; contrôle session vivante avant/après opérations et CSRF; sources Finance non exposées à mémoire et pas de LLM/provider dans Fusion CSV. Les deux chemins séparent le montant privé du résumé/provenance.
- **Données manquantes** : aucun intake général multi-format/classification massive/OCR ni corpus entreprise représentatif. M10 R26 qualifie vrai PostgreSQL temporaire avec données et embeddings synthétiques; l’audit dit explicitement PDF/OCR, massive ingestion et assimilation représentative hors preuve. CSV R23 éprouve 2 000 lignes simulées avec horloge injectée pour le plafond, pas débit production; dataset affaires fictif. Pas de métrique terrain de coût/qualité globale.
- **Première tranche métier recommandée** : bouton console « Indexer les prochains reçus » M10, borné à 5 versions `RECU`, appelant le même `procedures.indexer` idempotent une version/transaction, et résumant IDs/états/erreurs stables. Après interruption, rechargement sélectionne seulement les versions encore `RECU`; succès conserve son état et ne duplique pas les fragments. Activation reste humaine/CAS.
- **Pourquoi** : transforme le flux actuel fichier-par-fichier en lot d’assimilation reprenable sans nouvelle file/table/framework ni classification automatique; ne prétend pas supporter PDF ou toute l’entreprise. Scope documenté = procédures internes M03 uniquement.
- **Coût mesurable** : plafond 5 documents × 100 chunks = 500 fragments indexés par action; 0 appel modèle/embedding/API, 0 token LLM; journaliser seulement compteurs docs/chunks/échecs et durée, sans contenu ou titres. Mesurer octets déjà disponibles via version; aucun benchmark débit réel impliqué.
- **Surfaces probables** : `src/opsys/console/memoire_ingestion_ui.py` (action privée/CSRF/résumé), `src/opsys/memoire/ingestion_procedures.py` (liste ordonnée des versions RECU bornée; réutiliser indexer), pas de modification de Fusion Finance ni de store si les métadonnées existantes suffisent.
- **Tests natifs** : `tests/test_console_memoire_ingestion.py` : session révocable/CSRF, 5 max, aucun contenu source rendu, succès partiel + retry sans doublon, état après erreur; `tests/test_memoire_ingestion.py` : un seul index par SHA, hash source/occurrences/citations inchangés après rejeu, droits/quota. Vérifier que seuls statuts `RECU` avancent et qu’aucune version n’est activée automatiquement.
- **Preuves existantes** : `docs/research/R26-2026-10-02/README.md` (console/API/procédures Postgres réel; fixtures synthétiques); `docs/research/R22-2026-10-02/README.md` (CSV pilote/467 intégrés; synthétique); `docs/research/R23-2026-10-02/README.md` (496 intégrés, 2 000 lignes + horloge injectée); limites consolidées dans `docs/grs/memory/M10-AUDIT-INITIAL.md` et vision dans `docs/produit/VISION-ENTREPRISE-APPRENANTE.md`.

## Cadrage retenu pour la tranche suivante

Le parcours est limité aux procédures internes M03 déjà admises; la sélection et
l’indexation réutilisent le propriétaire PostgreSQL et son extraction bornée. Une action
indexe au plus cinq versions RECU, avec autorité personnelle revalidée avant chaque
version et avant la réponse. Chaque version reste une transaction distincte.
Aucun appel LLM, embedding ou activation automatique n’est ajouté.

L’acceptation exige des tests HTTP et PostgreSQL réels : cinq versions maximum, reprise
après succès partiel sans duplications, contenu privé absent des erreurs, refus CSRF
et session révoquée, versions INDEXE non retraitées et activation toujours humaine.
Le corpus de test reste synthétique. Le débit sur corpus client, l’import universel
de données, l’OCR et une note d’assimilation globale ne sont pas qualifiés par ce lot.

## Tranche appliquée et historique de qualification PostgreSQL

Les quatre fichiers proposés ont été adaptés et appliqués dans l’arbre de travail.
Le POST `/memoire/procedures/indexer-recues` sélectionne au plus cinq versions RECU,
relit chaque SHA/état et contrôle le rôle actuel dans le callback avant la transaction.
Il conserve les succès partiels, affiche une alerte pour les refus ou versions déjà
traitées, et ne rend ni contenu source ni détail d’exception. Le libellé « traitées »
ne suppose pas qu’une nouvelle indexation a été créée par cette seule requête.

Ruff passe sur les quatre fichiers avec 573 empreintes stables. Le fichier de test
complet comporte désormais 14 cas prévus, dont un intercalage déterministe de deux
indexations du même SHA; ce cas ne mesure pas une charge parallèle réelle.
La première exécution PostgreSQL a été arrêtée par la garde de réserve mémoire
avant un JUnit complet. Elle ne qualifie donc pas le lot. Les sources, le conteneur
préexistant et les compteurs OOM sont inchangés; le reçu signale aussi deux processus
zombies sans RSS après arrêt, sans les présenter comme une fermeture parfaite.
[Contrôle statique ROOT](/workspace/poursuite-opsys-2026-10-02-r1/M10-INDEXATION-LOT-ROOT-r1/preparation-r3/execution-r1/receipt.json),
[exécution PostgreSQL non qualifiée](/workspace/poursuite-opsys-2026-10-02-r1/M10-INDEXATION-LOT-ROOT-r1/execution-pg-r1/VERIFICATION-ROOT.json).

Deux limites restent explicites. Cinq reçus durablement fautifs peuvent occuper toutes
les places du lot; les actions unitaires et l’oubli contrôlé restent disponibles,
sans quarantaine ou curseur supplémentaire dans cette tranche. Un retrait du rôle
après le dernier contrôle et pendant une transaction PostgreSQL déjà engagée ne
peut l’annuler atomiquement : identité SQLite et indexation PostgreSQL sont séparées.
Les documents suivants sont refusés dès que le retrait est observé. Aucun taux
d’assimilation, benchmark client ou module M10 entièrement achevé n’est annoncé.

### Deuxième essai PostgreSQL : garde toujours bloquante

Après retrait ciblé de paquets dérivés du cache uv, un second essai conserve les mêmes
sources et seuils. Un vrai conteneur PostgreSQL est créé et sa mémoire est mesurée
par ID exact; la réserve cgroup passe néanmoins sous 512 MiB. Le harnais l’arrête
avant un JUnit complet. Il ne reste ni processus du run ni conteneur créé par lui;
le conteneur préexistant, les sources et les compteurs OOM sont inchangés.
Cet essai ne qualifie pas les 14 cas. La prochaine reprise examine une configuration
moins consommatrice de la base éphémère, sans abaisser les gardes du harnais.
[Reçu du second essai](/workspace/poursuite-opsys-2026-10-02-r1/M10-INDEXATION-LOT-ROOT-r1/execution-pg-r2/VERIFICATION-ROOT.json).

### Qualification obtenue sur PostgreSQL réel

Les **14 cas du fichier complet passent**, sans échec, erreur ni saut. Le run utilise
PostgreSQL 17/pgvector réellement lancé, `shared_buffers=16MB` observé par `SHOW`,
et des fixtures synthétiques. Une aide de test en lecture seule conseille au noyau
de libérer les pages des fichiers d’image avant de lancer l’entrée PostgreSQL
d’origine; elle ne lit pas les contenus et ne modifie ni les sources ni la base.
Le diagnostic a isolé la copie du rootfs Docker VFS comme pression principale.

Les plafonds restent inchangés : réserve cgroup 512 MiB, groupe Python + PostgreSQL
768 MiB, budget global 120 s. La réserve minimale observée est 629 055 488 octets;
le pic combiné est 266 482 647 octets. Les 573 sources, le conteneur préexistant
et les compteurs OOM restent inchangés. Aucun conteneur créé ou processus du run
ne subsiste. Les essais rouges antérieurs sont conservés, dont le refus lié à une
trace de démarrage tronquée; ils ne sont pas présentés comme des succès.

[Qualification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/M10-INDEXATION-LOT-ROOT-r1/execution-pg-r6/VERIFICATION-ROOT.json).
Le lot est qualifié dans ce profil de test. L’import multi-format client, le débit
sur corpus représentatif et M10 complet restent ouverts, ainsi que les deux limites
de concurrence et de sélection explicitées plus haut.


## Intake multi-fichier — candidat r4 non appliqué

Le candidat r4 ajoute un dépôt de **un à cinq TXT/MD** aux procédures internes M03, en réutilisant `procedures.admettre`. Il conserve le formulaire individuel et ses reprises. Chaque fichier admis aurait sa transaction et sa clé d’idempotence; les succès partiels resteraient RECU. L’admission ne fait ni indexation, ni activation, ni embedding, ni classification générale.

La revue ROOT a fait corriger trois défauts avant intégration : un contenu multipart sans nom de fichier ne doit pas être ignoré, les NUL doivent être refusés avant toute écriture, et les clés de reprise doivent rester attachées au numéro de leur emplacement original. Une liste compactée les associait mal aux emplacements 2 ou 1/3/5; le candidat r4 utilise un mapping par emplacement. Les tests écrits prévoient aussi le renvoi du seul fichier en échec et le retrait d’autorité après une première admission réussie.

Bornes proposées : 1 MiB par fichier, 5 MiB de sources, UTF-8 TXT/MD et champs fermés; extraction et contrôle de tous les fichiers actifs avant la première admission. Le rôle et la session sont contrôlés avant chaque effet. Une indisponibilité arrête les fichiers suivants; un refus métier isolé conserve les autres succès et indique les fichiers non tentés. L’attestation humaine « pas de PII/secret » ne constitue pas un scan automatique. Aucun contenu ni nom de fichier brut n’est rendu dans les erreurs.

[Revue, empreintes et capsules exactes du candidat r4](/workspace/poursuite-opsys-2026-10-02-r1/M10-INTAKE-CANDIDATS-ROOT-r1/r4/REVUE-ROOT.json). Le patch gelé a pour SHA-256 `0223be95e2aba8bdca98b36c9a14bc3c844eaf15ecf10cf2a6136fd439f0788a`. **Ce candidat n’est pas appliqué; ses tests ne sont pas exécutés.** Les 14 cas PostgreSQL du lot d’indexation qualifié plus haut ne qualifient pas ce nouvel intake.

La qualification PostgreSQL reste empêchée par l’espace disque disponible : Docker `vfs` copie le rootfs de l’image même avec des données en RAM. Aucun conteneur préexistant, image ou donnée n’est supprimé pour forcer ce test; aucun double SQLite ne remplace sa preuve PostgreSQL. Restent aussi hors périmètre : intake universel, OCR, corpus client, cohorte durable et oubli groupé, métrique d’assimilation et exploitation VPS.

## Suite du 4 octobre : manifeste d'import durable

La [nouvelle tranche](M10-IMPORT-LOTS-REPRISE-2026-10-04.md) utilise un manifeste
PostgreSQL intégré au store canonique et une console de reprise. Elle a son design,
ses régressions et sa qualification distincts. Le candidat r4 décrit plus haut reste
historique et non appliqué : son patch et ses tests ne sont pas présentés comme les
sources ou preuves de la nouvelle implémentation.
