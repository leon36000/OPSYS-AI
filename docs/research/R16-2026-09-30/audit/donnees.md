# Audit données, restauration, confidentialité et identité du socle

**Cible :** `/workspace/OPSYS-AI-recent`, commit `2e56c0d5605dfe575bde9244f38924d5390f2674`, le 30 septembre 2026. Dépôt et tests existants laissés inchangés ; `git status --short` vide avant et après les sondes. Les scripts et preuves sont externes au dépôt, sous ce dossier d’audit. Données exclusivement fictives, bases temporaires, conteneur PostgreSQL éphémère arrêté en fin de sonde.

**Verdict : FAIL pour la reprise et le cloisonnement examinés.** L’atomicité SQLite métier/outbox/audit/idempotence, la sauvegarde WAL et plusieurs barrières d’entrée passent. La restauration n’assure pas un retour cohérent après échec ; le contrôle de révision ne lit pas la révision réelle ; une interruption d’import historique empêche la reprise automatique. La console manque de contrôles de rôle et de révocation ; les artefacts et l’upsert RAG ont des limites de gouvernance reproduites. Ce verdict ne constitue pas une certification générale de tous les départements ni du Gateway.

Les invariants de référence sont la reprise annoncée fail-closed dans `src/opsys/exportation.py:25`, la transaction commune ADR-0009, et le contrôle d’accès, la rétention et l’export contrôlé de `docs/produit/DEFINITION-PRODUIT.md:179`. Les constats suivants séparent le comportement observé de ses conséquences possibles.

## Constats prouvés

### DON-01 — P1 / élevé, confiance haute : un compte employee modifie les modes et les paliers, même après désactivation

**Emplacement :** `src/opsys/console/application.py:163` (session lue uniquement du cookie), `:172` et `:178` (session + CSRF), `:210` et `:220` (actions), `:400` et `:449` (routes). `src/opsys/tableau_de_bord.py:87` et `:205`, puis `src/opsys/approbations.py:392`, n’exigent pas un rôle d’administration ou une personne encore active pour ces écritures. La session est signée avec les rôles pris à la connexion (`src/opsys/console/securite.py:70`) et dure huit heures par défaut (`:28`).

**Preuve réutilisée, non réexécutée ici :** `../execution/repro_console_autorisations.py:35` et `../execution/repro-console.json`. Une connexion réelle avec une personne ne portant que `employee` obtient 200 sur les cinq lectures administratives, POSTe le mode `autonome` avec 200, puis PUTe un palier `custom` vers `https://collecteur.invalid/v1` avec 200. Après `identite.activer(..., False)`, le même cookie et le même CSRF modifient encore le mode avec 200 ; la valeur est confirmée en base.

**Préconditions :** disposer d’une session console obtenue avec des identifiants employee valides ; le CSRF est celui fourni à cette session. La désactivation survient après la connexion. **Impact observé :** écriture effective de réglages globaux hors du rôle et révocation inefficace sur ces routes. Les lectures ont bien renvoyé 200 ; leur contenu dépend des données présentes. L’envoi effectif de données à l’URL modifiée n’a pas été testé. **Direction minimale :** autoriser chaque action et projection selon la personne et les rôles actuels en base, puis tester désactivation et retrait de rôle sur une session déjà ouverte.

### DON-02 — P1 / élevé, confiance haute : la restauration échouée laisse la nouvelle base en place ou un mélange base/réglage

**Emplacement :** `src/opsys/exportation.py:369` met les anciens fichiers de côté, `:376` pose les nouveaux ; le rattrapage `:379` ne remet l’ancien fichier que si la cible est absente (`:380`). La migration `:383` et le journal d’audit `:384` se trouvent après ce rattrapage.

**Preuves :** `probes.py:81` / `resultats-probes.json.rollback_apres_premiere_pose` : une panne `OSError` injectée au remplacement du deuxième fichier, `paliers.yaml`, laisse le marqueur de la base **archive-fictif**, mais le réglage **avant-fictif**. Une ancienne copie reste disponible. `probes.py:104` / `rollback_apres_migration_echec` : une migration refusée après pose laisse les nouveaux fichiers malgré l’exception de restauration.

**Préconditions :** restauration avec `remplacer=True` d’une instance existante et échec pendant une pose ou pendant la migration suivante ; injection locale déterministe, sans panne matérielle réelle. **Impact :** opération signalée comme échouée après modification effective de la vérité partagée ; réglages et registres de chantiers, factures ou approbations peuvent correspondre à des générations différentes. Les anciennes données sont conservées en copies ; aucune destruction physique irréversible n’est démontrée. **Direction minimale :** préparer et migrer la base candidate avant bascule, puis gérer explicitement une bascule/reprise de l’ensemble cohérent, y compris ses effets d’audit. Le défaut est indépendant du constat de révision DON-03.

### DON-03 — P1 / élevé, confiance haute : le précontrôle accepte une révision de manifeste différente de la révision SQLite

**Emplacement :** `src/opsys/exportation.py:318` vérifie l’intégrité SQLite puis ne prend la révision que du manifeste (`:329` à `:336`). La table `alembic_version` du fichier n’est pas comparée à ce manifeste.

**Preuve :** `probes.py:119`, `resultats-probes.json.revision_manifeste_vs_base`. Une archive synthétique dont tous les SHA-256 sont exacts contient une base en révision **9999** et annonce **0008**. `_verifier_base` accepte 0008 ; `restaurer(..., remplacer=True)` pose ensuite la base 9999, puis lève `CommandError: Can't locate revision identified by '9999'`. La révision 9999 et les données de l’archive restent dans l’instance cible après le refus.

**Préconditions :** archive incohérente mais dont les empreintes sont acceptées, plus `--remplacer`. Ce scénario ne démontre pas le contournement d’un SHA-256 conservé séparément par une personne ; il démontre que l’empreinte et `integrity_check` ne garantissent pas la cohérence sémantique de la révision. **Impact :** le refus annoncé avant modification survient après remplacement, rendant l’instance inutilisable avec ce logiciel ; récupération manuelle depuis les copies nécessaire. **Direction minimale :** lire et valider la révision effective du fichier extrait, sa concordance avec le manifeste et sa migrabilité avant toute pose.

### DON-04 — P2 / modéré, confiance haute : l’import historique interrompu ne reprend pas les données de etat.db

**Emplacement :** `src/opsys/etat.py:73` importe les lignes puis renomme la source dès `:84`. Le commit de l’import survient seulement à la sortie de `src/opsys/stockage/__init__.py:39` à `:43`. Au redémarrage, l’absence du nom original déclenche le retour `src/opsys/etat.py:62`.

**Preuve :** `probes.py:188`, `resultats-probes.json.reprise_import_etat_interrompu`. Un sous-processus est arrêté par `os._exit(73)` immédiatement après le renommage et avant commit. À la reprise, `migrer()` rend **0008**, le journal cible contient **0** ligne, `etat.db` est absent ; `etat.db.migre-*` contient encore la ligne fictive d’origine.

**Préconditions :** première migration d’une installation pré-ADR-0009 avec `etat.db` et interruption dans cette fenêtre. **Impact :** migration apparemment réussie avec disparition logique de l’historique d’audit/contrôle de l’instance active ; la source renommée permet une récupération manuelle. **Direction minimale :** conserver une source automatiquement reprenable jusqu’au commit confirmé, et enregistrer un état de reprise durable. Un simple renommage post-commit doit aussi traiter le risque de réimport après interruption et les cibles partiellement peuplées.

### DON-05 — P2 / modéré, confiance haute : un artefact connu se relit depuis un autre département

**Emplacement :** `src/opsys/jetons.py:124` construit l’identifiant depuis le hash du contenu ; `:125` stocke source/contenu sans portée ni identité, comme `src/opsys/stockage/schema.py:129`. `jetons.lire_artefact` ne filtre que sur l’identifiant (`:139` à `:149`). `src/opsys/capacites.py:98` expose cet outil commun et `:132` le lit sans filtre de département.

**Preuve :** `complements.py:78`, `resultats-complements.json.artefact_interdepartement`. Le département A produit une sortie confidentielle fictive tronquée. Une instance `Capacites` filtrée sur B, où l’outil source A est absent, récupère néanmoins le contenu A via `opsys_lire_artefact` en connaissant l’identifiant.

**Préconditions :** accès MCP interne du département B et identifiant d’artefact A déjà connu. Aucune recherche exhaustive ni acquisition distante de cet identifiant n’a été démontrée. **Impact :** le cloisonnement de l’outil source ne se propage pas à sa sortie conservée. **Limite importante :** ce n’est pas une fuite directement démontrée depuis le mobile : `src/opsys/openclaw.py:345` à `:350` ferme les outils communs `opsys_*` aux appareils. **Direction minimale :** conserver avec l’artefact le département et les règles de projection/identité nécessaires, et appliquer ces règles à chaque reprise ; le caractère difficile à deviner de l’ID ne remplace pas cette autorisation.

### DON-06 — P2 / modéré, confiance haute : l’ajout RAG dans une nouvelle portée reclasse un fragment existant et retire sa rétention

**Emplacement :** unicité globale `(document_id, empreinte)` dans `src/opsys/memoire/schema.sql:50`, document unique par source `:28`. `src/opsys/memoire/store.py:285` à `:297` remplace département, portée, sensibilité, sujets et échéance en cas de conflit. Le contrôle de l’outil `src/opsys/memoire/outils.py:143` à `:146` vérifie la **nouvelle** portée d’écriture du département, sans comparer la gouvernance du fragment existant.

**Preuve réelle PostgreSQL 17 + pgvector :** `memoire_probe.py:34`, `resultat-memoire.json`. Un fragment M5 `mouvements`, classé `personnelle` avec sujet `client:C-fictif` et échéance à 30 jours, est ajouté une deuxième fois avec source et texte identiques via `opsys_memoire_ajouter` au nom de M1 dans sa portée permise `signaux`. La sonde suit la file T1 en mode ombre, puis une approbation effective du propriétaire. Le **même fragment** devient M1 / signaux / interne / sujets `[]` / échéance `NULL`. La recherche `signaux` passe de zéro à un résultat.

**Préconditions :** mémoire PostgreSQL configurée, source et texte exacts connus, autorisation d’écrire la nouvelle portée. En mode ombre, l’approbation humaine du T1 est nécessaire et a été exercée dans la preuve ; aucune escalade sans approbation n’est démontrée. **Impact observé :** l’ajout approuvé pour M1 modifie la gouvernance d’un fragment financier existant, élargit sa récupération et enlève les sélecteurs/échéance de rétention. Aucun transfert externe n’a été exécuté. **Direction minimale :** inclure le domaine de gouvernance dans la déduplication ou refuser les métadonnées incompatibles ; réserver la reclassification explicite à une opération contrôlée sur l’ancienne et la nouvelle portée.

## Contrats positifs et frontières vérifiées

| Contrat | Résultat et preuve | Limite de la preuve |
|---|---|---|
| Transaction métier + outbox + audit + idempotence | **PASS**, `probes.py:140` et `resultats-probes.json.transaction_metier_outbox_audit_idempotence` : après refus/panne, trois comptes à zéro ; succès avec un seul commit ; renvoi avec exactement une ligne dans chaque registre, outbox, audit et mutation | Outil synthétique exécuté par Capacites ; ne couvre pas les effets hors base ou la base RAG distincte |
| Sauvegarde SQLite WAL | **PASS**, `probes.py:65` : WAL non vide avant export, donnée présente dans la copie, `integrity_check=ok`, journal_mode DELETE | Instantané de la base ; cohérence inter-fichiers DB/YAML sous modification concurrente non démontrée |
| Fichiers inclus dans l’export | **PASS**, `complements.py:132` : dépôt accepté d’un fichier fictif, contenu extrait de `fichiers_blocs.contenu_base64` identique dans opsys.db archivé | Dépôt et base sauvegardés, pas de test de rendu/image mobile |
| Revalidation au départ N3 | **PASS**, `complements.py:64` : une exécution avec personne active ; après retrait de rôle et après désactivation, nouvelles clés idempotentes renvoyées en attente d’approbation, aucune nouvelle exécution | Ce raccourci N3 relit personne et rôle ; ne certifie ni toutes les lectures T0 ni les modes qui n’exigent pas d’approbation |
| Migrations idempotentes et écrivains SQLite concurrents | **PASS**, `complements.py:146` : deux processus, chacun deux appels migrer puis vingt écritures ; retours 0/0 et quarante lignes conservées | Base déjà initialisée ; pas de panne disque, de démarrage simultané d’une base vierge ni de stress prolongé |
| Barrières JSON de la console | **PASS**, `complements.py:113` : sans session 401, sans CSRF 403, JSON illisible 400, tableau au lieu d’objet 400, corps > 65 536 octets 413 ; 1 200 niveaux d’imbrication refusés 400 | Preuve TestClient locale sur route de mode ; limite d’octets aussi vérifiée pendant le flux dans application.py:105 ; pas de mesure sous charge |

La **revalidation N3 est bien effective** : `capacites.py:283` à `:300` appelle `approbations.signataire_valide`, qui relit `identite.personne_active` et l’appartenance au rôle (`approbations.py:275` à `:279`). Aucun défaut d’exécution N3 fondé uniquement sur une ancienne attribution core de personne/rôle n’est retenu. Le renvoi idempotent d’une réponse déjà enregistrée ne correspond pas à une nouvelle exécution.

Le **RBAC des décisions d’approbation** est distinct de celui de la console : `approbations.decider:200` à `:215` exige une personne active et un rôle permis pour le niveau et le département ; la réservation conditionnelle `:232` à `:239` protège l’exécution unique. N5 reste fixé au propriétaire dans `departements.py:36` et exige l’attestation dans `approbations.py:217`. Cette lecture est corroborée par les mécanismes exercés dans la sonde RAG, sans prétendre couvrir ici chaque combinaison de rôle/niveau.

La **CLI est une frontière de confiance locale**, pas une authentification humaine. `cli.py:196` transmet `--par` à `decider`; `complements.py:99` reproduit un refus sous le nom d’un propriétaire existant, sans son mot de passe. La vérification du rôle en base passe, mais ne prouve pas qui a tapé la commande. `cli.py:208` permet aussi l’amorçage et la gestion locale des personnes/rôles ; `:279` attribue les exports au compte du poste par défaut. Un opérateur disposant déjà de la CLI et de la base est donc privilégié. Aucune exploitation distante de cette frontière n’est démontrée, et elle n’est pas comptée comme une seconde vulnérabilité console. SHA-256 d’archive signifie intégrité par rapport à une empreinte attendue, pas signature de l’auteur.

L’**authentification MCP HTTP** exige le bearer partagé avec comparaison constante (`serveur_mcp.py:153` à `:164`), sauf la santé sans donnée métier ; le secret court est refusé (`:198`). `_meta` véhicule personne/rôle (`:80`) sans signature individuelle vérifiée par Python. Le détenteur du bearer interne peut donc fabriquer ce contexte ; cette limite est déjà documentée dans `docs/architecture/IDEMPOTENCE.md:411`. La table des appareils n’est pas relue dans `signataire_valide`. La chaîne d’authentification native core et la révocation d’un appareil complet ne sont pas reproduites ici : **BLOCKED pour un verdict bout en bout sur cette seule base de preuves**, sans assimiler ce manque à un défaut démontré.

Les **archives restent aussi sensibles que la base** : elles contiennent les clés destructibles et les fichiers métier en base, malgré les exclusions du `.env` et de l’état core. `exportation.py:21` et `:77` l’annoncent ; `:79` précise qu’un effacement ultérieur ne détruit pas les archives existantes. Cette limite documentée n’est pas comptée comme un défaut nouveau. Chiffrement des transferts, conservation géographique et destruction des copies ne sont pas exécutés dans cet audit.

Pour les **verrous et la réentrance**, `stockage/moteur.py:65` applique WAL, clés étrangères, attente de cinq secondes et synchronous NORMAL ; `:70` démarre par BEGIN IMMEDIATE. `transaction:80` réutilise une connexion de contexte avec savepoint : cette transaction est celle d’une instance, même si un appel imbriqué fournit une autre URL. `stockage.migrer` ouvre sa propre connexion et sert au démarrage ; sa réentrance dans une transaction active ou des migrations sur plusieurs bases en threads n’a pas été certifiée. `liberer()` ferme le pool du processus courant ; il ne prouve pas l’arrêt d’un service externe pendant la restauration. Le rollback et le précontrôle défectueux ont été reproduits indépendamment de cette limite d’exploitation.

## Reproduction et portée du verdict

Depuis le dépôt, les trois commandes finales suivantes ont toutes terminé avec **code 0**, assertions de sondes incluses. Aucun test du dépôt n’a été ajouté, modifié ni exécuté en concurrence avec les suites coordonnées ailleurs.

```bash
/workspace/audit-opsys-2026-09-30/venv/bin/python /workspace/audit-opsys-2026-09-30/donnees/probes.py
/workspace/audit-opsys-2026-09-30/venv/bin/python /workspace/audit-opsys-2026-09-30/donnees/complements.py
/workspace/audit-opsys-2026-09-30/venv/bin/python /workspace/audit-opsys-2026-09-30/donnees/memoire_probe.py
```

Environnement observé : Python 3.12.14, SQLAlchemy 2.1.1, Alembic 1.20.0, psycopg 3.2.3 ; image locale `pgvector/pgvector:pg17`, Docker 28.4.0. Sorties brutes et erreurs : `probes.stdout` / `probes.stderr`, `complements.stdout` / `complements.stderr`, `memoire.stdout` / `memoire.stderr`. Les JSON sont les résultats des exécutions finales ; les stderr finaux sont vides. La console DON-01 s’appuie sur la reproduction déjà exécutée et fournie par le coordinateur, pas sur une duplication.

**À vérifier séparément avant un verdict de mise en service :** contrôles sur le chemin complet Gateway → MCP → outils réels, restaurations avec services réellement arrêtés/reprises, reprise après panne physique, charge et concurrence PostgreSQL, cohérence des opérations couvrant à la fois la base d’instance et le RAG PostgreSQL. Ces points sont non certifiés ici ; aucun PASS global n’en est déduit.
