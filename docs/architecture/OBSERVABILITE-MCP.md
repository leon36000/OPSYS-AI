# Observabilité, masquage des renseignements personnels et registre MCP en liste blanche

Statut : tranche 1 (2026-11-01). Code : `src/opsys/observabilite/`, `src/opsys/registre_mcp/`, `src/opsys/console/observabilite_ui.py`,
`src/opsys/evaluation/securite_mcp.py`. Tests : `tests/test_pii_masquage.py`, `test_traces_journal.py`,
`test_registre_mcp.py`, `test_rule_of_two.py`, `test_evaluation_securite_mcp.py`, `test_console_observabilite.py`.
Décisions d'origine : feuille de route technologique A (lignes Observabilité/éval, MCP, Agents) et recherche R6.

## Ce qui est livré, et ce qui ne l'est pas

| Brique | Livré et prouvé par exécution (hors ligne, doubles de test) | Pas prouvé / pas fait |
|---|---|---|
| Masquage PII par motifs | NAS (Luhn), cartes (Luhn + émetteur), téléphones NANP, courriels, codes postaux, adresses civiques, RAMQ, NEQ et numéros d'entreprise, secrets (préfixes, clé=valeur, entropie), civilité + nom ; jetons HMAC stables ; modes irréversible / réversible dans le coffre ; mesure sur un corpus fictif ; temps borné sur entrées hostiles | **Presidio non installé, non branché** (le port `MasqueurPII` l'attend). Aucune mesure sur des données réelles. Le corpus de mesure est écrit par le même auteur que les motifs : 100 % sur lui ne dit rien du réel |
| Traces | Modèle de span, journal local append-only à chaîne HMAC, masquage avant écriture, rétention bornée, tableaux coût/latence en CLI et en console, double de destination | **Aucun tour d'agent n'est encore émis par le runtime** : seuls les appels d'outils du serveur MCP le sont (si `OPSYS_TRACES=1`). Le coût d'un tour vient d'un tarif configuré, jamais d'une facture |
| Export | Port `DestinationTraces`, double mémoire, adaptateur Langfuse qui construit le lot d'ingestion | **Jamais exécuté contre un Langfuse réel** ; aucun transport HTTP livré ; format du lot non vérifié contre un serveur |
| Registre MCP | 433 outils exposés à la livraison de cette tranche (421 de départements + 3 de contexte + 9 d'hôte ; **683 à la révision 23 de la ligne actuelle**) scellés avec leur empreinte ; vérification au démarrage et à chaque appel ; dérive de description, de schéma ou de niveau, et outil inconnu, refusés et tracés ; CLI de scellement et de vérification ; garde de CI | La protection tient autant que le dépôt et la revue : voir « Limites du registre ». Snyk Agent Scan non exécuté (hors ligne) |
| Rule of Two | Table par surface, règle des trois propriétés, tests avec les outils réels (courriel → envoi, ingestion → paiement, web → publication) | C'est l'**hôte** qui déclare l'exposition. Le Core ne le fait pas encore. Le planificateur isolé (CaMeL) n'est pas implémenté |
| Évaluation | 37 cas déterministes sur les outils réels, 100 % ; une garde complaisante échoue sur chaque refus bloquant | Aucun modèle réel mesuré |
| Migration SDK v2 | Audit, écarts, plan, checklist, estimation (§ 7) | **Pas migré** (hors périmètre, pas de réseau) |

La migration alembic **0043 n'a pas été créée** : le journal de traces est un fichier local (voir § 2), ce qui n'ajoute aucune table, aucune
tête de migration et aucun conflit avec 0041 / 0042. Le numéro 0043 reste libre pour un stockage en base si on le veut un jour (voir « Pourquoi un
fichier »).

## 1. Activation

Rien ne change sans configuration. Les deux variables se lisent à la création de chaque serveur MCP (`creer_serveur`).

| Variable | Effet |
|---|---|
| `OPSYS_MCP_REGISTRE=defaut` (ou un chemin) | active la garde : registre scellé + Rule of Two ; une configuration cassée **refuse de démarrer** (jamais une garde désactivée en silence) |
| `OPSYS_MCP_REGISTRE_STRICT=1` | un outil dérivé ou inconnu au démarrage fait échouer la création du serveur (sinon : quarantaine) |
| `OPSYS_MCP_REGISTRE_HMAC=1` | exige un sceau HMAC (clé locale, usage `mcp/registre/v1`) |
| `OPSYS_TRACES=1` | active le journal de traces `<OPSYS_HOME>/traces/` |
| `OPSYS_OBS_CLE_FICHIER` | chemin de la clé locale (défaut `<OPSYS_HOME>/observabilite/cle-locale`, 0600) |

À faire par l'installateur et le déploiement (non fait ici) : poser `OPSYS_MCP_REGISTRE=defaut` et `OPSYS_TRACES=1` dans l'environnement du serveur
`opsys-mcp`, et envisager `OPSYS_MCP_REGISTRE_STRICT=1` en production.

Commandes (depuis le core : `opsys metier …`) :

```bash
opsys-metier traces tableau [--jours 7] [--json]      # coût et latence par département (lecture seule)
opsys-metier traces verifier                          # chaîne d'intégrité du journal
opsys-metier traces exporter --destination langfuse --a-blanc   # compte ce qui partirait et ce que la garde de sortie retient
opsys-metier traces purger [--confirmer]              # rétention (à blanc sans --confirmer)
opsys-metier traces masquer --texte "…" | --mesurer   # masque un texte / mesure sur le corpus fictif
opsys-metier registre-mcp lister | verifier [--json] | sceller --par PERSONNE [--retirer] [--hmac] [--a-blanc]
opsys-metier registre-mcp rule-of-two [--surface courriel_entrant|document_ingere|web] [--json]
opsys-metier evaluer securite-mcp [--sortie dossier]  # corpus transverse (§ 6)
```

La commande du moteur s'appelle `registre-mcp` et non `mcp` : `mcp` est déjà une commande du core (`tests/test_commande_metier.py` l'impose).
Les deux nouveaux noms (`traces`, `registre-mcp`) sont dans `OPSYS_METIER_MOVED_COMMANDS` (core) et `COMMANDES_DEPLACEES` (faux core).

## 2. Traces d'exécution

### Schéma d'un span (`opsys.observabilite.traces.Span`)

| Champ | Contenu |
|---|---|
| `trace_id`, `span_id`, `parent_id` | identifiants hexadécimaux (32, 16, 16) ; un champ de forme inattendue est écarté, jamais écrit tel quel |
| `type` | `appel_outil`, `tour_agent` ou `refus_mcp` |
| `debut`, `duree_ms` | ISO 8601 UTC à la milliseconde ; durée mesurée par horloge monotone |
| `departement`, `agent` | `mNN-nom` ou `opsys` ; identifiant d'agent (`opsys/runtimeProfileId` quand l'hôte le donne, sinon `non_identifie`) |
| `outil`, `niveau` | nom de l'outil et niveau d'approbation N0–N5 effectif |
| `issue` | `ok`, `refus`, `attente_approbation`, `erreur` |
| `code_refus` | `REJ-…` du refus (ou code de l'enveloppe) ; une exception n'écrit que `exception_<classe>`, jamais son message |
| `approbation_id` | `demande_id` de la file d'approbation quand l'appel a été mis en attente (lien vers la demande) |
| `jetons_entree`, `jetons_sortie`, `modele`, `cout_estime_usd` | pour un `tour_agent` ; coût en `Decimal` (chaîne), `null` si le tarif est inconnu (jamais zéro inventé) |
| `attributs` | au plus 20 clés `a-z0-9_.`, valeurs ≤ 200 caractères, masquées **puis** coupées ; une clé qui nomme un contenu (`corps`, `contenu`, `prompt`, `sortie`, `message`, `arguments`…) ou un secret (`password`, `token`…) est refusée |

Il n'y a **aucun champ de contenu** : ni corps de courriel, ni prompt, ni sortie d'outil, ni arguments. Le masquage est une seconde barrière, pas la première.

### Journal local

- Un fichier par jour UTC, `<OPSYS_HOME>/traces/traces-AAAAMMJJ.jsonl` (0600, dossier 0700), écrit en `O_APPEND` sous verrou
  (`flock` entre processus sous POSIX ; verrou de processus seulement ailleurs — non exercé sous Windows ici).
- Chaque ligne : `{"v":1,"seq":n,"prev":"<h précédent>","span":{…},"h":"<HMAC-SHA256>"}`. `h` = HMAC (clé locale, usage `traces/chaine/v1`) de
  `prev|seq|span`. `traces verifier` détecte une ligne modifiée, supprimée, insérée, dupliquée, réordonnée, tronquée (ligne coupée) ou un segment du milieu
  disparu, et ne plante pas sur une ligne hostile (NaN, imbrication démesurée : elle est signalée comme illisible). Le premier segment
  restant peut commencer après un segment purgé. **Limite, sans ancre externe** : retirer les DERNIÈRES lignes du dernier segment (ou
  ce segment entier) n'est pas détectable, la chaîne restante étant valide ; de même une réécriture complète par quelqu'un qui lit la clé
  locale. Seule une ancre conservée hors du dossier (tête de chaîne publiée ailleurs) fermerait cette limite.
- **Rétention bornée** : `retention_jours` (30 par défaut, 1–3650) et `taille_max_octets` (256 Mio) ; le dépassement supprime des **segments entiers**,
  le plus ancien d'abord, jamais le segment du jour ; chaque purge est consignée dans `purges.jsonl` (segments, raisons, dernier maillon). La
  purge s'exécute à la création d'un segment ; `traces purger --confirmer` la déclenche à la main (à blanc par défaut) ; l'exécuteur `retention.traces` du planificateur ([PLANIFICATION.md](PLANIFICATION.md) §5) l'applique périodiquement après validation humaine sur aperçu. La rétention vient de `OPSYS_TRACES_RETENTION_JOURS` (30 par défaut, valeur invalide refusée) pour le serveur, la CLI et l'exécuteur. Ce sont de la télémétrie,
  pas des données d'affaires : la suppression de ces segments est la rétention voulue, pas une suppression définitive de données d'affaires.
- **La télémétrie ne casse jamais l'appel** : une panne d'écriture est journalisée (nom de la classe d'exception seulement, pas son message) et
  l'outil continue.

### Pourquoi un fichier et pas une table

Une migration 0043 aurait cassé la tête alembic sur cette branche (le numéro 0042 n'y existe pas), fait échouer les tests qui épinglent la tête
(`test_courriel_registre_console`, `test_coffre_secrets`) et ajouté un conflit certain avec les branches 0041 / 0042. Un journal à segments
convient à de la télémétrie (rétention par segment, aucune mise à jour). Prix à payer, dit sans euphémisme : **le journal n'est pas dans
l'export d'instance** (`exportation.py` : liste blanche fermée sur `opsys.db`), donc ni sauvegardé ni restauré avec la base. Si l'on veut des traces
sauvegardées ou interrogeables en SQL, le chemin est une table `traces_spans` (index département, début) avec déclencheurs d'immuabilité comme
`courriel_journal` (migration 0040), et `JournalTraces` devient une implémentation parmi d'autres derrière le même contrat.

### Tableaux et console

`opsys.observabilite.tableaux.agreger` : par département, appels d'outils, tours, refus (et taux), attentes d'approbation, erreurs, latence p50 / p95 /
max (rang le plus proche), jetons, coût estimé, et le nombre de tours **sans coût** (compté à part). `/observabilite` et `/api/observabilite`
(console) : mêmes gardes que la Plateforme — session, rôle `nathan_owner`/`admin` relu en base avant et après la lecture, `Cache-Control: no-store`,
aucun formulaire, page contrôlée contre les secrets actifs, journal ouvert **en lecture seule** (sans clé, il ne peut ni écrire ni purger).

### Export

`DestinationTraces.envoyer(spans)` ; `DestinationMemoire` (double) ; `DestinationLangfuse(url, cles, transport)` construit un lot `POST
/api/public/ingestion` (`trace-create`, `span-create`, `generation-create`, identifiants d'événements déterministes pour rejouer sans doublon) ;
sans `transport`, il refuse (`REJ-OBS-DESTINATION-NON-CONFIGUREE`). `exporter()` : curseur par destination, avancé **après** succès seulement ;
**garde de sortie** : chaque span est revérifié par le masqueur avant envoi ; un span qui contiendrait encore un renseignement est retenu
(`refuses_pii`). Les clés Langfuse se lisent dans le coffre (`langfuse.cle-publique`, `langfuse.cle-secrete`) au moment de l'envoi, jamais dans
l'environnement ni dans le journal.

### Plan Langfuse (E0, à faire)

1. Service Langfuse auto-hébergé **séparé** (cœur MIT ; ne jamais activer `ee/`), qualifié en QA : PostgreSQL, ClickHouse, Redis, S3 — poids sur un
   VPS de PME à mesurer.
2. Un `TransportHTTP` réel (httpx) vers l'URL interne, avec délais et reprise ; qualification de l'API d'ingestion réelle (le format ci-dessus
   vient de la documentation publique, pas d'un essai).
3. Choisir **un** schéma canonique : OTLP par `diagnostics-otel` du Core (conventions `gen_ai.*` + `opsys.*`) ou l'API d'ingestion ci-dessus. Les
   deux portent les mêmes dimensions (département, outil, niveau N, refus, lien d'approbation) ; ne pas mélanger.
4. Émettre les **tours d'agent** : aujourd'hui seule `opsys_runtime_concilier` connaît les jetons réels d'un cycle, et elle ne trace rien. Le
   critère E0 (« 100 % des tours de 10/10 départements produisent une trace ; coût ±2 % du coût réconcilié ») n'est donc **pas atteint**.
5. Rapprocher le coût estimé de la facture du fournisseur (écart connu).

## 3. Masquage des renseignements personnels

### Ce que fait `MasqueurMotifs` (hors ligne, déterministe)

| Catégorie | Règle | Jeton |
|---|---|---|
| NAS | 9 chiffres en groupes 3-3-3 (espace, espace insécable, point, tiret) **et** somme de Luhn ; collé : exige « NAS / assurance sociale » devant ; jamais devant `$`/`€`/décimale ; pas précédé d'un autre groupe de chiffres | `[[NAS:…]]` |
| Carte | 13–19 chiffres, Luhn, préfixe d'émetteur reconnu (Visa, Mastercard, Amex, Discover, JCB, Diners, UnionPay) | `[[CARTE:…]]` |
| Téléphone | plan nord-américain (indicatif et central 2–9, pas N11), parenthèses, séparateurs, `+1`, poste ; 10 chiffres collés seulement avec indicatif ou mot de contexte (« tél », « texto »…) | `[[TEL:…]]` |
| Courriel | forme usuelle, normalisé en minuscules | `[[COURRIEL:…]]` |
| Code postal | A1A 1A1 avec les lettres permises ; collé : majuscules obligatoires | `[[CP:…]]` |
| Adresse civique | numéro + type de voie (rue, avenue, boul., chemin, rang, route, côte… ; Street/Avenue/Road… en anglais) + nom, appartement facultatif | `[[ADRESSE:…]]` |
| RAMQ | 4 lettres majuscules + AAMMJJNN, mois 01–12 ou 51–62, jour 01–31 | `[[RAMQ:…]]` |
| NEQ / numéro d'entreprise | NEQ (10 chiffres 11/22/33/88) avec mot de contexte ; `123456789 RT0001`, TVQ `… TQ 0001` ; 9 chiffres avec contexte (« numéro d'entreprise », TPS) | `[[NEQ:…]]`, `[[NE:…]]` |
| Secret | PEM, préfixes connus (`sk-`, `ghp_`, `AKIA`, `AIza`, JWT, `opsys-jeton:v1:`…), `Bearer`, `clé=valeur` (api_key, password, token…), `https://u:mot@hôte`, longue chaîne à forte entropie (≥ 4 bits/car., lettres et chiffres) ; les chaînes hexadécimales (empreintes, identifiants) ne sont **pas** des secrets | `[[SECRET:…]]` |
| Civilité + nom | M., Mme, Dre, Me… + nom capitalisé ; ou nom d'un **lexique** fourni (clients du CRM) | `[[NOM:…]]` |

Les valeurs vivantes du coffre (`secrets_coffre.masquage`) sont remplacées **avant** tout (`•••`). Un masquage est idempotent, et un jeton `[[…]]`
n'est pas du PII.

### Jetons stables et modes

`[[ÉTIQUETTE:hmac12]]`, où `hmac12` = 12 premiers hex de HMAC-SHA256(clé `pii/v1`, catégorie ‖ valeur normalisée). Même valeur, même jeton
(un NAS écrit avec des espaces, des tirets ou des espaces insécables donne le même), clé différente, jeton différent ; 48 bits suffisent pour
corréler sans collision pratique sur quelques millions de valeurs.

- **Irréversible** (défaut, seul mode des traces) : la valeur n'est gardée nulle part.
- **Réversible dans le coffre** (`ModeMasquage.REVERSIBLE_COFFRE`) : la valeur est déposée sous le jeton dans un `CoffrePII`. Adaptateur
  `CoffrePIIDuCoffre` : secret `pii.<étiquette>.<hmac12>` du coffre chiffré (AES-256-GCM) ; `reveler` exige un administrateur actif relu en base et
  laisse une ligne dans `coffre_acces`. **Un secret n'est jamais déposé**, même dans ce mode. Aucun export en clair n'existe.

### Mesure (corpus fictif `corpus_pii.py`, `traces masquer --mesurer`)

51 détections attendues, 26 textes d'affaires sans renseignement : précision 1,00, rappel 1,00, 0 faux positif sur les négatifs. **Lire avec
méfiance** : motifs et corpus sont du même auteur. Le corpus nomme en plus :

- **4 faux positifs connus** (assumés) : identifiant de commande à Luhn valide masqué comme carte, référence `H2X1Y4` masquée comme code postal,
  « 12 rue principale » masqué comme adresse, chaîne alphabétique longue masquée comme secret ;
- **8 limites** (ce que des motifs ne voient pas) : nom propre sans civilité, prénom seul, nom d'entreprise individuelle, adresse décrite en mots,
  numéro écrit en lettres, courriel obscurci (« jean arobase… »), valeur coupée sur deux lignes, secret hexadécimal. Le test exige qu'on les
  voie **toujours rater** : une amélioration doit être déclarée, pas supposée.

### Ce que Presidio devra apporter (plan)

Les noms propres et les adresses libres : seul un NER les voit. Brancher `MasqueurPresidio` (MIT, `presidio-analyzer` + modèle spaCy français) derrière
`MasqueurPII`, en **chaîne après** `MasqueurMotifs` (`MasqueurEnChaine`) — les motifs gardent la main sur les formats québécois (NAS, RAMQ, NEQ,
codes postaux), que les reconnaisseurs par défaut de Presidio ne couvrent pas. Avant d'adopter : inscrire la brique dans `docs/research/INGREDIENTS.md`
(déjà listée), fixer les versions, **mesurer sur un corpus de 200 cas synthétiques** (critère E0 : 0 fuite) et reprendre `traces masquer --mesurer`
pour comparer. Le coût (modèle spaCy, mémoire) est à mesurer sur le VPS cible.

## 4. Registre MCP en liste blanche

### Entrée du registre

Pour chaque outil exposé : `nom`, `departement`, `niveau` (N0–N5), `surface` (`departement`, `contexte`, `runtime`), `description`,
`schema_entree`, `empreinte`, `parties` (empreinte du nom, de la description, du schéma, pour dire *ce qui* a changé) et `version` (1 à l'ajout,
+1 à chaque révision qui change cet outil).

**Empreinte** = `sha256` du JSON canonique (clés triées, sans espace, UTF-8, **sans normalisation**) du triplet `{nom, description, schéma d'entrée}`.
Un homoglyphe, un espace ou un caractère de largeur nulle change l'empreinte. Le **niveau** est comparé à part (abaisser un niveau retire une
approbation).

Les 433 outils scellés à la livraison de cette tranche (683 à la révision 23 de la ligne actuelle) : 421 de départements et communs (`Capacites.lister()`), 3 outils privés de contexte (tickets de cible et de mémoire,
succès M9) et 9 outils d'hôte du serveur d'admission (`/mcp/runtime/<profil>`, lus par un vrai `tools/list`). Un outil `runtime` nouveau et non classé
dans `NIVEAUX_RUNTIME` fait **échouer l'inventaire** (fermé par défaut).

### Vérification

| Moment | Ce qui se passe |
|---|---|
| Démarrage de chaque serveur (`creer_serveur`, serveur d'admission) | comparaison du catalogue au registre ; un outil dérivé / inconnu / de niveau changé est mis en quarantaine, rapporté (journal + span `refus_mcp`) ; en mode strict, le serveur ne démarre pas |
| `tools/list` | un outil non conforme n'est **pas annoncé** |
| **Chaque** `tools/call` | l'empreinte est **recalculée sur l'outil tel qu'il est exposé maintenant** (aucun cache) et comparée ; une dérive survenue après le démarrage est refusée avant toute exécution |

Codes : `REJ-MCP-EMPREINTE-DERIVE` (description, schéma ou nom modifié, avec la partie nommée), `REJ-MCP-NIVEAU-DERIVE`, `REJ-MCP-OUTIL-INCONNU`
(absent du registre ou d'une autre surface : un outil `runtime` appelé sur l'endpoint d'un département est inconnu), `REJ-MCP-REGISTRE-ALTERE`,
`REJ-MCP-REGISTRE-SCEAU`, `REJ-MCP-REGISTRE-ABSENT`, `REJ-MCP-REGISTRE-RETRAIT`, `REJ-MCP-DESCRIPTION-SUSPECTE`. Un outil scellé mais non exposé
ici (mémoire sans `psycopg`, par exemple) est une information (`absents`), jamais un refus. La réponse au Core garde la forme
`{"ok": false, "erreur": "REJ-MCP-…", "details": …}` (un bloc texte JSON, `isError` vrai).

### Révision approuvée

`opsys-metier registre-mcp sceller --par PERSONNE` relit les outils réellement exposés, **montre** ce qui change (ajoutés, modifiés, niveaux,
retirés) et écrit une nouvelle révision : numéro, approbateur, date, historique chaîné (empreinte de chaque révision et de la précédente), sceau.
Sans changement, rien n'est écrit. Un **retrait** exige `--retirer`. Une description qui porte des caractères invisibles ou de contrôle, une
consigne adressée au modèle (« ignore les instructions précédentes », « ne le dis pas à l'utilisateur », `<IMPORTANT>`…) ou une longue suite opaque
**bloque** le scellement (`inspecter_description`). Le registre s'écrit un outil par ligne : une modification d'outil est une ligne de diff.

**Garde de CI** : `tests/test_registre_mcp.py::test_le_registre_livre_correspond_exactement_au_catalogue_reel` échoue dès qu'une description, un
schéma ou un niveau d'outil change sans nouvelle révision. C'est la « révision approuvée » : le diff du registre est relu dans la revue de code.
**À l'intégration des branches parallèles (m10-connaissances, m7-studio-creatif, cablage-connecteurs…), les outils ajoutés ou modifiés feront échouer
cette garde : l'architecte reconstruit alors le registre une fois (`registre-mcp sceller --par …`) et relit le diff.** Le registre livré a été
scellé par `architecte` pour revue ; il n'a pas été approuvé par un humain.

### Limites du registre

- Sans clé HMAC, quiconque écrit le fichier **et** modifie l'outil peut resceller : la revue du diff est alors la seule barrière. Avec `--hmac`, il
  faut aussi la clé locale ; or un processus du même compte la lit. Pour une vraie séparation des privilèges, mettre le sceau sous une clé que l'agent
  et le serveur ne lisent pas (non fait).
- **Historique et sceau.** Depuis la revue adverse (reg), un sceau neuf couvre aussi l'empreinte de TOUTES les fiches d'historique (champ
  `sceau.historique`, dans la charge sha256 / HMAC) : réécrire « qui a scellé quoi, quand » sans la clé casse le HMAC. La dernière fiche est de
  plus recoupée avec la révision courante (`par`, `le`, nombre d'outils). Un registre scellé AVANT ce changement (sans `sceau.historique`, dont
  le registre livré) reste lisible, mais l'historique de ses anciennes fiches n'y est pas authentifié : il le devient à la prochaine révision
  scellée. Les fiches d'une révision ne sont pas recalculables seules (les outils d'alors ne sont pas conservés) : seule la marque les protège.
- Le registre protège la **définition annoncée**, pas le comportement du code derrière : un outil dont la fonction change sans changer sa
  description passe. Les tests et la revue de code restent la barrière.
- `inspecter_description` cherche des motifs ; il ne prouve pas qu'une description est sûre.
- Les serveurs MCP **tiers** que l'on configurerait côté Core ne passent pas par ce registre (il couvre `opsys.serveur_mcp`). Le plan A3 prévoit
  Snyk Agent Scan (Apache-2.0) en CI pour eux : non fait ici.
- Si `OPSYS_MCP_REGISTRE` n'est pas posé, **rien n'est vérifié**.

## 5. Rule of Two

Une session d'agent ne cumule pas plus de deux de ces propriétés sans approbation humaine : **[A]** contenu non fiable (courriel entrant, document
ingéré, page web) ; **[B]** accès à des données sensibles (tout outil de département, par défaut — fermé par défaut, sauf trois outils déclarés sans
donnée) ; **[C]** effet : niveau N3 ou plus (action externe ou modification interne non finale, ADR-0009 §4).

Pour un appel fait par une session exposée à au moins une surface non fiable :

1. B ∧ C → `REJ-MCP-RULE-OF-TWO`, **même si l'outil figurait par erreur dans la table**, sauf `ApprobationPreuve` (humaine, niveau N3 ou plus,
   approbateur et demande renseignés) ;
2. sinon l'outil doit figurer dans la table de **chaque** surface exposée (lectures N0 seulement, vérifiées contre le registre réel par
   `valider_table`) ; sinon `REJ-MCP-SURFACE-NON-FIABLE`, sauf la même approbation.

Table (8 à 10 lectures par surface ; `opsys-metier registre-mcp rule-of-two`) : sur 433 outils (chiffres de la livraison de cette tranche), 9 sont permis sans approbation sur `courriel_entrant`,
8 sur `document_ingere`, 10 sur `web` ; 134 outils sont refusés par la règle des trois propriétés sur chaque surface ; environ 290 exigent une approbation
parce qu'ils sortent de la table. C'est strict **par choix** (« lecture seule uniquement ») : un brouillon (N1) ou une tâche interne (N2) exige une
approbation sous exposition, ce qui bridera M1 si ses agents doivent, par exemple, escalader une plainte lue dans un courriel (`m1_escalader_plainte`,
N2). Si ce coût est trop élevé, la décision à prendre est un second palier « écriture interne sans effet externe » dans la table, pas un
assouplissement de la règle.

**D'où vient l'exposition.** De l'hôte, jamais du modèle : `_meta["opsys/surfacesNonFiables"]` (liste, que le Core devra renseigner quand un tour a
lu un courriel, un document ou une page) ou le paramètre `expositions` de `creer_serveur` (profil d'agent déclaré). Un agent ne peut que **l'ajouter**
(une liste vide ne retire rien). Une valeur mal formée est refusée (`REJ-MCP-EXPOSITION-INVALIDE`). **Le Core ne renseigne pas encore ce champ** :
tant qu'il ne le fait pas, seul un profil déclaré côté serveur est protégé. Le serveur ne passe aucune approbation dans la bande : un appel B ∧ C
est refusé net (aucune demande n'est créée) ; l'exécution après approbation humaine passe par `approbations.decider`, qui n'emprunte pas le serveur MCP.

**Planificateur isolé (CaMeL), non implémenté.** Patron cible pour M1, l'ingestion et le web : un planificateur privilégié qui ne lit jamais le contenu
non fiable choisit les outils et leurs arguments à partir de la demande de l'humain ; un traitement en quarantaine lit le contenu non fiable et ne
rend que des valeurs typées (jamais du texte libre réinjecté dans le planificateur). La Rule of Two est le garde-fou minimal en attendant.

**Observation hors périmètre** : `m9_decider_demande_approbation` est déclaré N2 (rôle `admin`) alors qu'il approuve ou refuse des demandes N3/N4. Sous la
règle, le niveau N2 le range hors de l'effet [C] ; à réexaminer par l'architecte (niveau ou rôle).

## 6. Intégration au gabarit d'évaluation

`opsys-metier evaluer securite-mcp` exécute `corpus_transverse/securite-mcp.v1.yaml` (format fermé `opsys.evaluation.securite-mcp/v1`) : 37 cas écrits
à la main sur les outils **réels** (témoins intacts ; dérive de description, d'homoglyphe, de caractère invisible, de schéma, de niveau ; outils
inconnus ; Rule of Two avec courriel → envoi, ingestion → paiement, web → publication, clôture comptable, approbations suffisantes et
insuffisantes, table altérée ; exposition mal formée). Les corpus des dix départements et leur empreinte ne sont pas touchés (fichier à part).
Résultat : 37/37, garde qualifiée. **Preuve que le corpus mord** : avec un registre scellé sur l'outil déjà altéré et la Rule of Two coupée
(`garde_complaisante`), chaque refus bloquant est manqué ; sans la Rule of Two seule, les cas Rule of Two échouent et la dérive reste attrapée.

## 7. Migration vers le SDK MCP v2 / spécification 2026-07-28

**Échéance** : la branche 1.x du SDK TypeScript reçoit des correctifs « au moins six mois » après la sortie de la v2 (2026-07-27) : fin estimée
**fin janvier 2027** (hypothèse H de R6, à confirmer auprès du dépôt). **À planifier maintenant.**

### État mesuré dans le dépôt

| Côté | Constat |
|---|---|
| Moteur Python | `pyproject.toml` : `mcp>=2.0.0,<3` ; **2.2.0 installé** (R6 cite 2.3.0 du 2026-10-02 : mise à jour à qualifier). `mcp_types.version.KNOWN_PROTOCOL_VERSIONS` = 2024-11-05 … **2026-07-28** ; un client en mémoire négocie **2026-07-28** avec `creer_serveur`. Le serveur OPSYS est donc **déjà sur le SDK v2 et la spec 2026-07-28** ; il n'y a rien à migrer côté Python. Le serveur de réception SMS tolère déjà les clés `_meta` réservées de la spec (`PROTOCOL_VERSION_META_KEY`, `CLIENT_INFO_META_KEY`, `CLIENT_CAPABILITIES_META_KEY`) |
| Core TypeScript | `@modelcontextprotocol/sdk` **1.31.0** dans `core/package.json`, mais **1.32.0** dans le catalogue pnpm et le verrou : incohérence à résoudre en premier. **99 fichiers** TS référencent le SDK (dont les tests), 43 hors tests et fixtures |
| Client (agents) | ≈ 25 fichiers `core/src/agents/mcp-*.ts` et `agent-bundle-mcp-*` : transports HTTP, stdio, SSE, OAuth (fournisseur, magasin, rafraîchissement), cycle de vie, métadonnées d'outils, validation JSON Schema, contenu, erreurs, ressources UI ; `context-engine/opsys-contexte-mcp.ts`, `agents/harness/opsys-postflight-collector.ts` |
| Serveurs internes du Core | `core/src/mcp/` (channel-server, plugin-tools-serve, openclaw-tools-serve, tools-stdio-server, codex-supervision-tools-serve), `gateway/mcp-http.handlers.ts`, `node-host/mcp.ts` |
| Extension | `core/extensions/browser` : 5 fichiers `chrome-mcp-*` |
| Surface publique | `core/src/plugin-sdk/agent-harness-runtime.ts` ré-exporte des types du SDK : le gate de surface du plugin (`check-plugin-sdk-exports`, `plugin-sdk-api-diff`) verra le changement |
| Comptes d'imports (tests compris) | `sdk/types.js` 39, `shared/transport.js` 17, `client/index.js` 15, `client/auth.js` 8, `server/mcp.js` 6, `inMemory.js` 6, `server/index.js` 5, `client/streamableHttp.js` 5, `server/streamableHttp.js` 4, `shared/stdio.js` 4, `shared/auth.js` 4, `client/sse.js` 2, `server/stdio.js` 2 |

### Écarts connus (R6, niveau V, à relire dans le changelog avant de coder)

Packages scindés (`@modelcontextprotocol/server`, `/client`, 2.4.0) ; plus de sessions ni d'en-tête `Mcp-Session-Id` ; plus de `initialize` (version
et capacités dans `_meta` à chaque requête) ; `server/discover` obligatoire ; `subscriptions/listen` ; tâches déplacées dans l'extension
`io.modelcontextprotocol/tasks` (le Core exclut déjà les outils `taskSupport: "required"` dans `mcp-tool-metadata.ts`) ; **MRTR**
(`InputRequiredResult`) à la place des requêtes serveur → client ; `resultType` obligatoire ; propagation `traceparent` dans `_meta` ; `ttlMs` /
`cacheScope` ; **Sampling, Roots et Logging dépréciés** ; DCR déprécié au profit des Client ID Metadata Documents ; `iss` (RFC 9207) validé par le
client. Rupture avec les serveurs 2025-xx : prévoir un **mode double** (le client Python 2.2 en offre un, `mode='legacy'` ; vérifier celui du client
TypeScript).

Points propres à OPSYS :

1. **`_meta` des appels.** Le Core transporte `opsys/idempotencyKey`, `opsys/appareil`, `opsys/personne`, `opsys/role`, `opsys/runtimeProfile*`,
   `opsys/cfoGrantTicket`… dans le `_meta` de `tools/call`. En 2026-07-28 le client y met aussi version et capacités : la composition doit **fusionner**,
   pas écraser (tests `mcp-call-meta*.test.ts`).
2. **Registre et empreintes.** Le triplet nom + description + schéma ne dépend pas du transport ; l'ordre déterministe des outils de la spec simplifie
   la comparaison. Rescellé après la migration (une ligne de diff par outil dont l'annonce change, ex. champs d'annotations ou `outputSchema`).
3. **Intégration Python-HTTP.** Neuf tests `*.python-http.integration.test.ts` exercent le client TS contre le serveur Python : ils mesurent l'écart
   réel (non lancés ici, le bac à sable n'exécute pas le Core).
4. **OAuth.** Fournisseur, magasin et rafraîchissement (`mcp-oauth*.ts`, `state-migrations.mcp-oauth-format.ts`) touchent DCR → CIMD et `iss`.

### Plan

| Phase | Contenu | Estimation (jours-personne, H) |
|---|---|---|
| P0 | Résoudre 1.31 / 1.32 ; geler l'inventaire ci-dessus ; lire le changelog v2 ; confirmer la date de fin de support v1 | 0,5–1 |
| P1 | Spike en branche : `mcp-client-lifecycle` + transport HTTP sur v2 ; rejouer les 9 tests Python-HTTP ; décider du mode double | 2–3 |
| P2 | Client : transports (HTTP, stdio, SSE), OAuth, cycle de vie, métadonnées / validateurs, contenu, erreurs, ressources UI | 5–8 |
| P3 | Serveurs internes du Core (`core/src/mcp/*`, gateway, node-host) | 3–5 |
| P4 | Extension navigateur (`chrome-mcp-*`) | 2–3 |
| P5 | Gate de surface du plugin-sdk, `dependency-ownership.json`, verrou, documentation | 2 |
| P6 | Mode double 2025-xx ; tests de contrat contre l'Inspector ; qualification Docker du chemin Core ↔ moteur | 2–3 |
| P7 | Resceller le registre ; relancer `evaluer securite-mcp` et les corpus ; Snyk Agent Scan en CI | 1–2 |
| **Total** | | **≈ 18–27 jours-personne, soit 4 à 6 semaines calendaires avec CI et revues** |

Calendrier proposé : P0–P1 en novembre 2026 (décision de mode double), P2–P3 en décembre, P4–P7 début janvier, fusion avant la mi-janvier pour garder
deux semaines de marge sur la fin estimée du support v1. Estimation **non mesurée** (hypothèse) : elle se resserre à la fin de P1.

### Liste de contrôle

- [ ] Version unique du SDK dans `package.json`, catalogue pnpm et verrou
- [ ] Tous les imports `@modelcontextprotocol/sdk/*` remplacés (99 fichiers, tests compris) ; aucun import résiduel (garde de CI)
- [ ] Client : `server/discover`, `_meta` de version et de capacités, `resultType`, MRTR, sans `initialize` ni `Mcp-Session-Id`
- [ ] Mode double validé contre un serveur 2025-11-25 et contre le serveur OPSYS
- [ ] `_meta` `opsys/*` intact bout en bout (idempotence, identité d'appareil, profil runtime, ticket CFO)
- [ ] OAuth : CIMD, `iss`, migration de format du magasin
- [ ] Serveurs internes du Core migrés, gate de surface du plugin-sdk vert ou dérogation datée
- [ ] Registre MCP rescellé, `registre-mcp verifier` et `evaluer securite-mcp` verts
- [ ] Neuf tests Python-HTTP verts en CI ; Inspector ; Docker
- [ ] Snyk Agent Scan en CI (serveurs tiers)

## 8. Ce qui n'est pas prouvé

- Aucun test contre un vrai Langfuse, un vrai Presidio, un vrai Core : tout passe par des doubles ou par le client MCP en mémoire du SDK.
- Les motifs PII ne sont mesurés que sur un corpus fictif de même auteur ; aucune donnée réelle.
- Le verrou inter-processus du journal (`flock`) n'est exercé que par des fils d'un même processus ici ; aucun essai sous Windows.
- L'efficacité de la Rule of Two dépend d'un hôte qui déclare l'exposition ; le Core ne le fait pas encore.
- Aucune charge : le recalcul d'empreinte à chaque appel coûte un JSON canonique et un SHA-256 par appel (négligeable devant l'appel d'outil, mais non
  mesuré sous charge) ; `tools/list` recalcule une empreinte par outil exposé (421 à la livraison de cette tranche).
- La migration SDK v2 n'est pas faite ; l'estimation est une hypothèse.
