# Audit des départements M1–M10 — état récent du 30 septembre 2026

**Cible :** `/workspace/OPSYS-AI-recent`, commit `2e56c0d5605dfe575bde9244f38924d5390f2674`. **Verdict produit : FAIL sur l’intégrité métier et la confidentialité ; les tests verts ne suffisent pas à déclarer les départements prêts.** Trois constats élevés sont confirmés : une collision d’identifiant de facture efface la créance de la vue courante, l’argument `agent` de M10 ouvre une vue privée, et l’ancien outil de consommation M6 permet une double sortie de stock liée à une autre intervention.

**État du livrable : PREUVE.** Les défauts décrits ci-dessous ont une reproduction exécutée et une localisation source. Ce statut signifie que cet audit borné est étayé ; il ne signifie pas que le produit satisfait ses critères de complétion.

## Cadre, preuve et limites

Lecture seule des sources, conformément à [AGENTS.md](../../../../AGENTS.md). Référentiel : [définition produit, §1, §5, §6 et §7](../../../produit/DEFINITION-PRODUIT.md). Les invariants examinés sont la vérité financière M5, le temps réel M4, la provenance et l’idempotence M6/M10, les retraits de consentement M7, la qualité M8, les contradictions M9 et la confidentialité M10. Aucun paiement, envoi, publication ou système extérieur n’a été actionné. Les scripts externes utilisent des fixtures fictives et une base SQLite jetable.

Les inventaires couvrent **903 fichiers, 241 272 lignes** : 470 fichiers M1–M5 et 433 M6–M10. Les SHA-256 des 903 fichiers ont été comparés aux fichiers actuels : **aucune différence**. Ils sont dans M1–M5/inventory.json (`archive:m1-m5/recent/inventory.json`) et M6–M10/inventory.json (`archive:m6-m10/recent/inventory.json`). L’inventaire et l’index AST ne sont pas une lecture humaine intégrale de chaque fichier. Cette passe confirme les reproductions déjà établies, examine les sources impliquées et suit leurs adaptateurs publics ; elle n’est pas une preuve d’absence de défaut sur tout le département.

Trois ensembles de preuves sont disponibles :

- reproductions M1–M5 (`archive:m1-m5/recent/reproductions.py`), résultat original (`archive:m1-m5/recent/reproductions.jsonl`), confirmation fraîche (`archive:m1-m5/recent/confirmation.jsonl`) ;
- reproductions M6–M10 (`archive:m6-m10/recent/reproductions.py`), résultat original (`archive:m6-m10/recent/reproductions.json`), confirmation fraîche (`archive:m6-m10/recent/confirmation.json`) ;
- confirmation des frontières (`archive:confirmation-frontieres.py`), [résultats](confirmation-frontieres.json) : **vrai `Capacites.appeler`, adaptateurs de production et stockage SQLite jetable**, sans simulation du répartiteur. Cette preuve remplace les limites d’extraction AST des anciens scripts pour le retrait M7 et la vue privée M10. La préparation d’états initiaux fictifs est indiquée dans le script.

Les dix manifestes démarrent en **mode `ombre`**. [Capacites._distribuer](../../../../src/opsys/capacites.py#L190) met les écritures T1/N3 en approbation dans ce mode ; un appel M1 forgé l’a effectivement vérifié. Les reproductions d’écritures au répartiteur utilisent ensuite le mode **`supervise`**, mode supporté où T1/N3 s’exécute, sur les seuls objets de configuration fictifs. Elles établissent ce qui se passe lorsque l’action s’exécute, pas un contournement de l’approbation du mode ombre. Le filtre privé M10 est une lecture T0, donc cette protection du mode ombre ne s’y applique pas. [executer](../../../../src/opsys/outils.py#L216) et [valider_arguments](../../../../src/opsys/outils.py#L152) valident une forme minimale ; la vérité métier reste à la charge des départements.

Confiance **élevée** pour le comportement reproduit de chaque constat. La gravité tient compte de son accès réel ; les primitives internes et les hypothèses de transport sont signalées. Aucun constat ne prétend démontrer une attaque distante anonyme, un accès entre locataires ou une action financière réelle.

## Constats élevés

### DEP-001 — M5 : un nouvel identifiant de devis peut remplacer une facture existante

**Gravité élevée.** Sources : [facturation.py:192](../../../../departments/m05-financecore/src/m5_financecore/facturation.py#L192), [garde de création:316](../../../../departments/m05-financecore/src/m5_financecore/facturation.py#L316), [adaptateur:569](../../../../departments/m05-financecore/src/m5_financecore/outils.py#L569), [outil exposé:2029](../../../../departments/m05-financecore/src/m5_financecore/outils.py#L2029).

La création vérifie l’unicité d’un devis actif, sans interdire un `facture_id` déjà employé pour un autre devis. La projection des états, indexée par `facture_id`, remplace alors l’état précédent avec le nouvel événement `facture_creee`.

**Preuve :** `M5_COLLISION_FACTURE_ID` puis `M5_CAPACITES_COLLISION`. Une facture de 100 $ avant taxes est en état ENVOYEE et les comptes à recevoir valent **114,98 $**. Une seconde création avec le même `facture_id` et un autre `devis_id` est acceptée. La vue courante devient BROUILLON pour le nouveau devis ; les comptes à recevoir passent à **0**. Les trois événements restent présents et la chaîne hashée reste valide. Au répartiteur, le passage initial à ENVOYEE est préparé par la primitive dans la base fictive, sans aucun envoi extérieur ; la seconde création est un appel réel de `m5_creer_facture_brouillon`.

**Conséquence :** créance masquée, facture active précédente perdue dans les projections et corruption du rapprochement devis/facture. Le contrôle d’approbation d’envoi ne protège pas contre une création interne ultérieure. **Direction corrective :** unicité immuable de `facture_id`, rejeu identique explicitement idempotent et conflit de contenu explicitement refusé ; verrouiller aussi l’unicité au stockage.

### DEP-002 — M10 : l’appelant choisit l’identité qui ouvre CLIENT_PRIVATE

**Gravité élevée.** Sources : [outils.py:397](../../../../departments/m10-memoire/src/m10_memoire/outils.py#L397), [schéma public:691](../../../../departments/m10-memoire/src/m10_memoire/outils.py#L691), [allow-list de confidentialité:63](../../../../departments/m10-memoire/src/m10_memoire/confidentialite.py#L63).

`m10_paquet_contexte_affaire` expose `agent` comme argument libre et le transmet au filtre de confidentialité. Le commentaire dit qu’il est posé par le moteur de contexte ; le code ne le compare pas au département authentifié par le répartiteur.

**Preuve :** `R8-M10-agent-usurpe` puis `M10_CAPACITES_AGENT`. Un fait marqué CLIENT_PRIVATE, avec le texte fictif `DONNEE_CLIENT_FICTIVE`, est retenu pour `agent='m10-memoire'`. Le même appel à l’outil M10 avec `agent='m01-front-office'` le rend en clair dans `faits_affaire`, via `Capacites`. Le répartiteur entre pourtant dans le contexte du département M10 pour cet outil. Lecture T0 : aucune approbation d’écriture n’intervient.

**Conséquence :** un appelant ayant l’outil peut choisir un département autorisé à lire des faits privés de client, sans posséder cette identité. **Direction corrective :** dériver le destinataire du contexte d’appel fiable ; le paramètre éventuel ne doit pouvoir que restreindre la vue. Couvrir l’usurpation par un test au répartiteur, pas seulement par des tests du filtre pur.

### DEP-003 — M6 : l’ancien outil de consommation reste exposé et accepte le rejeu et une autre intervention

**Gravité élevée.** Sources : [materiel.py:35](../../../../departments/m06-material-control/src/m6_material_control/materiel.py#L35), [adaptateur:1026](../../../../departments/m06-material-control/src/m6_material_control/outils.py#L1026), [outil public:1567](../../../../departments/m06-material-control/src/m6_material_control/outils.py#L1567).

`m6_consommer_materiaux` prend toujours le WCT fourni par l’appelant. Ce chemin ne vérifie pas sa présence sur le bus, ne lie pas l’intervention du formulaire à celle du WCT et n’enregistre pas une clé WCT pour empêcher un second débit. La vérification de disponibilité, elle, fonctionne.

**Preuve :** `R1-M6-consommation-rejouee` puis `M6_CAPACITES_LEGACY`. Une réception fictive de 10 unités est préparée. Deux appels identiques avec un WCT inconnu du bus et une intervention de formulaire différente sont acceptés. Le stock passe **10 → 7 → 4** et la confirmation nomme l’autre intervention. Le rejeu présenté ici est sans `_meta` d’idempotence d’appareil ; une déduplication par clé de transport ne remplace pas une unicité du fait WCT, notamment pour un agent ou une autre clé.

**Conséquence :** double consommation, rattachement erroné et clôture possible d’une réservation depuis un WCT simplement affirmé. **Direction corrective :** fermer ce chemin exposé ou lui appliquer les mêmes contrôles de source, de concordance et d’unicité métier que la déclaration enrichie.

**Limite positive confirmée :** [m6_declarer_materiaux_utilises:1090](../../../../departments/m06-material-control/src/m6_material_control/outils.py#L1090) lit le WCT publié par M4, contrôle intervention/chantier et déclarant, et [soumettre_materiaux_utilises:162](../../../../departments/m06-material-control/src/m6_material_control/materiel.py#L162) refuse une deuxième déclaration. `M6_CAPACITES_NEW_UNKNOWN` rend effectivement `REJ-WCT-INCONNU`. Le constat porte sur l’ancien outil toujours présent, pas sur ces contrôles nouveaux.

## Constats moyens

### DEP-004 — M4 : les pauses après départ produisent un temps réel négatif

Sources : [pointage.py:185](../../../../departments/m04-field-ops/src/m4_field_ops/pointage.py#L185), [calcul des pauses:176](../../../../departments/m04-field-ops/src/m4_field_ops/outbox.py#L176), [soustraction:293](../../../../departments/m04-field-ops/src/m4_field_ops/outbox.py#L293), [adaptateur de complétion:791](../../../../departments/m04-field-ops/src/m4_field_ops/outils.py#L791).

**Preuve :** `M4_NEGATIVE_DURATION` et `M4_CAPACITES_NEGATIVE`. Arrivée 09:00, départ 10:00, pause début 10:10, pause fin 12:10 : tous les pointages sont acceptés. Le départ laisse l’intervention `sur_site`, ce qui autorise encore les pauses. Le calcul soustrait 120 minutes d’une présence de 60 minutes et retourne **−60** sans verdict. Dans la confirmation publique, le consentement GPS est enregistré, le GPS est chiffré et un vrai fichier JPEG fictif est déposé par l’outil. `m4_completer_intervention` accepte le dossier et émet un WCT à **−60 minutes, `completed_pending_review`**. Le catalogue d’événement n’impose pas de minimum à cette durée.

La première reproduction primitive rend `completed_verified` en choisissant `ecart_detecte=False`. **Le chemin public actuel impose `verification_en_attente=True` : il ne déclare pas directement le chantier vérifié.** Il laisse néanmoins sortir une durée impossible vers les consommateurs. Aucun paiement de paie négative n’a été démontré. **Direction corrective :** vérifier les sessions arrivée/départ et l’inclusion des pauses, refuser un résultat négatif avant toute écriture/publication, conserver la revue humaine pour les corrections.

### DEP-005 — M7 : un retrait reçu avant le WCT ne s’étend pas ensuite au lead

Sources : [service.py:462](../../../../departments/m07-marketing/src/m7_marketing/usine/service.py#L462), [retrait.py:117](../../../../departments/m07-marketing/src/m7_marketing/usine/retrait.py#L117), [outil public:941](../../../../departments/m07-marketing/src/m7_marketing/outils.py#L941).

**Preuve :** `R5-M7-retrait-anterieur-WCT` et `M7_CAPACITES_RETRAIT`. Le retrait d’un WCT encore inconnu est accepté avec `lead_id=null`. Après réception du WCT, un nouvel appel indique `wct_connu=true`, mais conserve l’ancien maillon idempotent avec `lead_id=null`. Le contrôle d’applicabilité pour un second WCT du même lead rend **aucun retrait applicable**. Le premier WCT reste bloqué ; aucune publication réelle n’a été lancée.

**Conséquence :** la promesse « ce chantier et les chantiers du même lead » n’est pas conservée pour cette arrivée dans le désordre. Le STOP transmis directement par M1 avec les lead_ids est une autre voie et n’est pas mis en défaut par cette preuve. **Direction corrective :** ajouter un lien de retrait vers le lead lorsque le WCT devient connu, par un nouveau maillon, puis appliquer ce lien à tous les contrôles de contenus/export.

### DEP-006 — M10 : la consolidation ignore définitivement les événements tardifs

Sources : [consolidation.py:42](../../../../departments/m10-memoire/src/m10_memoire/consolidation.py#L42), [court-circuit:118](../../../../departments/m10-memoire/src/m10_memoire/consolidation.py#L118), [outil:411](../../../../departments/m10-memoire/src/m10_memoire/outils.py#L411).

**Preuve :** `R9-M10-consolidation-retard` et `M10_CAPACITES_LATE`. Un WCT du 29 septembre est consolidé. Un second WCT du même jour arrive ensuite. Une nouvelle consolidation garde le premier fait : **2 événements, 1 source**, `deja_consolide=true`. La liste des jours non consolidés est vide dans la preuve pure.

**Conséquence :** le résumé durable est incomplet et le moteur n’a plus de raison de consolider ce jour. Les événements bruts ne sont pas supprimés ; le risque porte sur la mémoire condensée et sur les anciens événements omis du paquet par le budget. **Direction corrective :** versionner la consolidation par ensemble/empreinte des sources ou par position d’eau, ajouter une consolidation complémentaire quand des sources nouvelles apparaissent et vérifier la couverture des sources avant de considérer un jour traité.

### DEP-007 — M8 : le texte « nan » devient une métrique présente sans alerte de qualité

Sources : [semantique.py:32](../../../../departments/m08-analytics/src/m8_analytics/semantique.py#L32), [qualite.py:38](../../../../departments/m08-analytics/src/m8_analytics/qualite.py#L38), [plage:70](../../../../departments/m08-analytics/src/m8_analytics/qualite.py#L70), [composition publique:777](../../../../departments/m08-analytics/src/m8_analytics/outils.py#L777).

**Preuve :** `R6-M8-NaN-non-signale` et `M8_CAPACITES_NAN`. Un snapshot contient la chaîne JSON valide **`"nan"`** pour `cpl`. `m8_rapport_metriques` l’accepte, produit `valeur=NaN` et `n=1`. Avec une définition enregistrée, fraîcheur 2 jours et plage 0–100, `m8_evaluer_qualite_metrique` renvoie **`verdict=null`, `alertes_proposees=[]`**. Le rapport XmR signale séparément un échantillon insuffisant ; il ne signale pas une valeur non numérique.

**Conséquence :** une donnée impossible compte comme une observation et traverse les comparaisons de qualité. Le chemin jusqu’à `Capacites` est exécuté ; la sérialisation MCP/HTTP ou le rendu navigateur d’un NaN n’a pas été exercé. **Direction corrective :** exiger une valeur finie après la conversion, traiter sa qualité explicitement et ne pas incrémenter l’échantillon valide pour cette valeur.

### DEP-008 — M9 : les représentations équivalentes d’un instant masquent une contradiction

Sources : [etat_consolide.py:37](../../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/etat_consolide.py#L37), [clé de groupe:41](../../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/etat_consolide.py#L41), [adaptateur:164](../../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils.py#L164).

**Preuve :** `R7-M9-contradiction-fuseaux` puis `M9_CAPACITES_TIMEZONES`. Deux snapshots M5 portent le même instant, `2026-09-30T08:00:00-04:00` et `2026-09-30T12:00:00Z`, avec cash **1** puis **100**. Tous deux sont acceptés, la seconde valeur est retenue et `contradictions=[]`. Le choix du dernier fait compare bien des dates parsées, mais la détection groupe par chaîne de caractères brute.

**Conséquence :** la direction reçoit une source ambiguë avec une liste de contradictions vide. **Direction corrective :** utiliser une clé d’instant canonique UTC pour la détection, tout en gardant les horodatages source dans la trace.

### DEP-009 — M10 : un WCT modifié est dédupliqué comme s’il était identique

Sources : [wct.py:45](../../../../departments/m10-memoire/src/m10_memoire/wct.py#L45), [adaptateur public:198](../../../../departments/m10-memoire/src/m10_memoire/outils.py#L198), [outil:590](../../../../departments/m10-memoire/src/m10_memoire/outils.py#L590).

**Preuve :** `R10-M10-WCT-conflit-masque` et `M10_CAPACITES_WCT`. Le même `wct_id` est mémorisé une première fois avec durée **1**, puis présenté avec durée **90**. Le second appel est accepté et retourne la durée **1**, sans verdict de conflit ; un seul maillon demeure. L’outil direct prend le WCT complet fourni par l’appelant, sans le relire au bus.

**Conséquence :** une correction ou une première version erronée demeure invisible ; l’outil public peut aussi préempter le fait authentique si une écriture arbitraire précède sa livraison. Cela exige l’accès à cet outil et l’exécution d’une écriture ; ce n’est pas une preuve d’attaque sans autorisation. Le bus empêche la redélivrance du même `(evenement_id, consommateur)`, mais la fonction se présente précisément comme défense supplémentaire contre un autre identifiant d’événement. **Direction corrective :** comparer une empreinte du contenu canonique avant de dédupliquer ; tout écart doit produire un conflit à revoir. Lire le fait à la source pour le chemin exposé.

### DEP-010 — M1 : un objet conversation forgé suffit à valider la dernière phase

Sources : [phases_voix.py:62](../../../../departments/m01-front-office/src/m1_front_office/phases_voix.py#L62), [adaptateur:367](../../../../departments/m01-front-office/src/m1_front_office/outils.py#L367), [outil public:1494](../../../../departments/m01-front-office/src/m1_front_office/outils.py#L1494).

**Preuve :** `M1_PHASE_FORGED_PUBLIC_TOOL` et `M1_CAPACITES_FORGED`. Un registre vierge et un objet déclarant `phase_courante=4`, cinq phases construites par l’appelant et `dernier_ligne_id=null` suffisent pour accepter la transition **4 → 5**, fermer normalement la conversation et écrire un maillon valide. Le registre ne contient aucune ouverture ni les transitions 0 → 4. Au répartiteur en mode ombre, le même appel reste en attente d’approbation ; en mode supervisé il s’exécute.

**Conséquence :** la progression et l’historique vocal peuvent être affirmés plutôt que prouvés. Aucun prix, qualification de lead ou engagement client induit n’a été démontré. **Direction corrective :** recevoir un identifiant et relire l’état du registre, ou valider le dernier maillon et le contenu complet contre l’état canonique ; la consigne « reporter tel quel » dans la description ne constitue pas un contrôle.

### DEP-011 — M7 : la primitive d’approbation compare l’auteur à un champ mutable

Sources : [content/approval.py:35](../../../../departments/m07-marketing/src/m7_marketing/content/approval.py#L35), [approve:47](../../../../departments/m07-marketing/src/m7_marketing/content/approval.py#L47).

**Preuve :** `R4-M7-autoapproval`. Après une proposition par `alice`, un objet de même identifiant change `proposer` en `bob` et remplace le corps. `approve(..., actor='alice')` accepte et conserve **un corps jamais proposé**. `_exiger_item_propose` ne compare que la présence de l’identifiant et son statut en file ; `approve` relit l’auteur et le contenu de l’objet de l’appelant.

**Portée : primitive Python interne, pas contournement démontré de `m7_decider_contenu`.** Les outils actuels de l’usine utilisent le service durable et le socle d’approbation ; le workflow historique [chantier_social.py:174](../../../../departments/m07-marketing/src/m7_marketing/workflows/chantier_social.py#L174) utilise cette primitive, mais son chemin normal ne forge pas l’objet. **Direction corrective :** approuver la version relue en file, rendre cette version immuable et vérifier l’auteur stocké. Éviter les références mutables rendues par `list_items`.

### DEP-012 — M7 : les couleurs CSS peuvent injecter un script accepté par le garde-fou

Sources : [generator.py:46](../../../../departments/m07-marketing/src/m7_marketing/site/generator.py#L46), [garde G-14:422](../../../../departments/m07-marketing/src/m7_marketing/site/guardrail.py#L422).

**Preuve :** `R3-M7-script-dans-couleur`. Une couleur YAML `bg` termine `</style>`, ajoute `<script>globalThis.audit_m7 = 1</script>` puis rouvre le style. `render_html` produit le script et `guardrail.validate` rend **`[]`**. G-14 examine les attributs d’événement et les protocoles `javascript:`, sans refuser une balise script ordinaire.

**Portée : génération locale à partir d’un contenu/configuration modifié ; aucune voie client anonyme et aucune exécution navigateur ni publication n’est prouvée.** Le site livré pourrait contenir du code actif si ce contenu lui est fourni. **Direction corrective :** allow-list des formats de couleur, refus explicite des scripts hors JSON-LD attendu et échappement contextuel des champs insérés.

### DEP-013 — M3 : un seuil d’éclairage NaN supprime le blocage des photos

Sources : [qualite_photos.py:33](../../../../departments/m03-estimation/src/m3_estimation/qualite_photos.py#L33), [comparaison:154](../../../../departments/m03-estimation/src/m3_estimation/qualite_photos.py#L154), [outil:1010](../../../../departments/m03-estimation/src/m3_estimation/outils.py#L1010).

**Preuve :** `M3_NAN_THRESHOLD` et `M3_CAPACITES_NAN`. Une photo d’éclairage **0** avec `eclairage_minimal=float('nan')` rend `photos_acceptables=true`, `prix_bloque=false`, `AUCUN_BLOCAGE`. Le validateur ne vérifie que le type numérique du seuil, et toute comparaison `< NaN` vaut faux.

**Limite :** le NaN est ici un objet Python fourni au répartiteur, pas un nombre JSON standard ; son passage par le transport MCP n’a pas été testé. Les seuils constituent une entrée de politique, pas un pixel non fiable qui serait traité par erreur. **Direction corrective :** valider finitude et domaine de tous les seuils avant comparaison, avec un verdict nommé ; ajouter une vérification de la politique à son chargement.

### DEP-014 — M5 : le solde dépend du contexte Decimal ambiant

Source : [soldes.py:9](../../../../departments/m05-financecore/src/m5_financecore/soldes.py#L9). **Preuve :** `M5_PRECISION_CONTEXT`. Le même registre contient les mouvements fictifs **100 000 000**, **0,01** et **−100 000 000**. `calculer_solde` rend **0,01** avec précision 28 et **0** avec précision 8. Les entrées du registre ne changent pas ; seule la précision d’un `decimal.localcontext` entourant l’appel change.

**Conséquence :** perte d’exactitude si une autre bibliothèque ou l’appelant modifie le contexte de calcul. Ce n’est pas une primitive offerte au modèle pour changer la précision ; aucune modification ambiante par le runtime normal n’a été identifiée. **Direction corrective :** fixer et dimensionner le contexte des sommes monétaires, ou calculer sur des entiers de cents ; tester l’indépendance du contexte ambiant et les bornes de montants supportées.

## Constats faibles de robustesse

### DEP-015 — M3 : des paramètres finis débordent vers Infinity puis font échouer l’outil

Sources : [monte_carlo.py:100](../../../../departments/m03-estimation/src/m3_estimation/monte_carlo.py#L100), [arrondi d’adaptateur:368](../../../../departments/m03-estimation/src/m3_estimation/outils.py#L368). `M3_FINITE_INPUT_OVERFLOW` emploie un coût unitaire fini **1e308** et une quantité **10** ; la primitive retourne les deux bornes `Infinity` avec verdict nul. `M3_CAPACITES_OVERFLOW` confirme que le chemin public lève ensuite **`decimal.InvalidOperation`** lors de l’arrondi. **L’outil public n’a pas été observé retournant un intervalle Infinity accepté.** Entrée extrême, sans vraisemblance métier normale ; erreur non nommée, sans écriture chiffrée prouvée. Direction : borner les domaines métier et vérifier la finitude après opérations, avant arrondi.

### DEP-016 — M5 : un montant fini extrême produit une exception non traduite en verdict

Sources : [facturation.py:152](../../../../departments/m05-financecore/src/m5_financecore/facturation.py#L152), [taxes.py:60](../../../../departments/m05-financecore/src/m5_financecore/taxes.py#L60). `M5_FINITE_AMOUNT_EXCEPTION` appelle les taxes avec `Decimal('1e100')` et lève `InvalidOperation`. `M5_CAPACITES_FINITE_EXCEPTION` confirme qu’une ligne de facture de prix texte **`"1e100"`**, pourtant fini, lève la même exception au répartiteur avant écriture de cette facture. `executer` ne capture que ValueError, TypeError et KeyError. Pas de perte financière prouvée ; panne d’appel au lieu d’un refus métier. Direction : plage monétaire explicite, calcul contrôlé et verdict nommé pour les erreurs Decimal prévues.

### DEP-017 — M1 : la chaîne vide ignore une ancre externe non vide

Source : [registre.py:112](../../../../departments/m01-front-office/src/m1_front_office/registre.py#L112). `M1_EMPTY_CHAIN_ANCHOR` enregistre un maillon, garde sa tête, vide **directement la liste privée en mémoire**, puis appelle `valider_chaine(ancre_attendue=ancre)`. Résultat : **`(True, None)`** malgré une tête désormais vide. Le retour anticipé précède la comparaison d’ancre.

Violation confirmée du contrat de cette classe, sans voie publique démontrée pour effacer ce stockage. Ce constat ne prouve pas un effacement de la base durable par un agent. Direction : vérifier l’ancre aussi sur une chaîne vide et couvrir la troncature totale dans le test de chaîne.

## Observation dont la qualification doit rester bornée

**OBS-DEP-001 — M6, déclaration enrichie et stock négatif.** `R2-M6-stock-negatif` confirme que [soumettre_materiaux_utilises:126](../../../../departments/m06-material-control/src/m6_material_control/materiel.py#L126) permet une consommation de **20** après une réception de **10**, donc un stock théorique **−10**, sans appeler la garde de disponibilité de l’ancien chemin. Le [PRD CA-M6-13](../../../../departments/m06-material-control/docs/bmad/02-PRD-PM.md#L414) parle de rejet d’une consommation au-delà du disponible.

La conclusion « stock négatif silencieux en production » serait excessive : l’adaptateur actuel appelle [_constater_stock_des_articles](../../../../departments/m06-material-control/src/m6_material_control/outils.py#L1147) après déclaration et les tests `test_stock_bas_cascade.py::test_stock_theorique_negatif_est_signale_sans_quantite_a_commander` couvrent précisément ce signal. La déclaration réelle de matériaux peut refléter un inventaire initial incomplet plutôt qu’un débit autorisé. Il faut reconciler le contrat documentaire de rejet, la fonction primitive et cette politique de constat/revue, puis vérifier le trajet public pour déterminer le verdict correct. Cette observation n’est pas comptée parmi les trois défauts élevés ni présentée comme un défaut d’idempotence du nouveau chemin.

## Suites exécutées et ce que le vert couvre

Les suites locales ont été exécutées par la coordination dans le venv externe. Commande de référence : `venv/bin/python -m pytest /workspace/OPSYS-AI-recent/departments/<département>/tests -ra --junitxml=<artefact externe>`. Les commandes exactes et codes de sortie sont dans les `.result.json` et `.xml` sous execution (`archive:execution`). Je n’ai pas relancé ces suites ; seules les démonstrations externes ont été réexécutées.

| Département | Fichiers inventoriés | Tests locaux | Résultat et limite |
|---|---:|---:|---|
| M1 | 80 | 1 550 | 0 échec, code 0 ; DEP-010/017 restent reproductibles |
| M2 | 77 | 1 794 | 0 échec, code 0 ; aucun nouveau défaut confirmé dans cette sélection, absence de défaut non prouvée |
| M3 | 108 | 2 124 passés, 1 ignoré | Code 0 pour la base locale ; deux fichiers de gardes/preuve exclus, voir ci-dessous |
| M4 | 123 | 2 827 | 0 échec, code 0 ; DEP-004 confirmé au répartiteur |
| M5 | 82 | 1 987 | 0 échec, code 0 ; DEP-001/014/016 reproductibles |
| M6 | 87 | 1 108 | 0 échec, code 0 ; ancien outil et nouveau chemin ont des garanties différentes |
| M7 | 158 | 992 | 0 échec, code 0 ; primitive historique distincte du service public actuel |
| M8 | 70 | 722 | 0 échec, code 0 ; NaN non détecté par la qualité |
| M9 | 48 | 259 | 0 échec, code 0 ; ordre chronologique correct, contradiction d’instant équivalent manquée |
| M10 | 70 | 854 | 0 échec, code 0 ; confidentialité, consolidation et conflit WCT restent reproductibles |

**Total local : 14 217 tests passés, 1 ignoré**, dont **12 093** passés dans les neuf suites complètes hors M3. M3 : m03-base.result.json (`archive:execution/m03-base.result.json`), m03-base.xml (`archive:execution/m03-base.xml`). Les exclusions sont `test_gardes_des_outils.py` et `test_outils_de_preuve.py` ; le test ignoré est une garde destinée à la CI dans `test_soumission_pdf.py:588`. Un premier essai M3 avec désélection incorrecte a été arrêté par SIGTERM ; il n’est pas compté comme une suite verte. Les états CI du commit sont consignés séparément dans checks-head.json (`archive:historique/checks-head.json`) ; ils ne remplacent pas les démonstrations de ces cas manquants.

Les exemples suivants expliquent précisément pourquoi les tests existants peuvent rester verts :

- M5 protège le second brouillon du **même devis**, mais DEP-001 réemploie la **même facture avec un autre devis**. Le hash-chaînage valide la conservation des écritures, pas l’unicité métier de leur identité.
- M1 teste les sauts de phase à partir d’un objet ouvert normalement ; DEP-010 affirme directement une phase 4. Les tests d’ancre détectent une réécriture non vide ; DEP-017 vide tout le registre.
- M4 contrôle l’ordre des heures et les pauses mal formées, mais l’ordre `départ puis pause complète` respecte les heures tout en sortant la pause de la session travaillée.
- M6 durcit la nouvelle déclaration et le stock insuffisant de l’ancien chemin, mais ces deux chemins exposés ne partagent pas les garanties de provenance et d’unicité.
- M7 `test_approve_refuse_un_item_jamais_propose` refuse un identifiant absent ; DEP-011 reprend un identifiant existant et change son auteur et son contenu. `test_auto_approbation_interdite` conserve le bon auteur dans l’objet transmis.
- M8 distingue texte non convertible et absence de valeur ; `float('nan')` est convertible, donc DEP-007 reçoit `n=1` et échappe aux comparaisons de plage.
- M9 couvre le choix chronologique entre fuseaux et les conflits d’horodatages textuellement identiques ; DEP-008 croise ces deux dimensions.
- M10 teste des vues de confidentialité et le rejeu d’un jour déjà consolidé séparément ; DEP-002 forge le destinataire au point d’entrée public, DEP-006 ajoute une nouvelle source après consolidation et DEP-009 change le contenu sous la même identité.

Les démonstrations ont été exécutées avec les trois commandes suivantes, **toutes code 0** :

```text
/workspace/audit-opsys-2026-09-30/venv/bin/python /workspace/audit-opsys-2026-09-30/m1-m5/recent/reproductions.py
/workspace/audit-opsys-2026-09-30/venv/bin/python /workspace/audit-opsys-2026-09-30/m6-m10/recent/reproductions.py
/workspace/audit-opsys-2026-09-30/venv/bin/python /workspace/audit-opsys-2026-09-30/confirmation-frontieres.py
```

Le code 0 confirme le fonctionnement des scripts de preuve ; leurs sorties démontrent les violations. Il ne signifie pas que les cas adversariaux ont été correctement refusés.

## Progrès confirmés et séparation avec l’ancien arbre

Les contrôles d’approbation et les transactions de `Capacites` fonctionnent dans les cas observés. Les chemins nouveaux M4 exigent des fichiers effectivement déposés, gardent le GPS sous consentement et chiffrement et imposent la revue initiale ; la preuve publique DEP-004 respecte ces contrôles. Le nouveau chemin M6 relit le WCT de M4 et refuse un identifiant inconnu. M8 conserve les définitions versionnées et la provenance des mesures. M10 ferme les niveaux sensibles/financiers/secrets/légaux dans les paquets ; DEP-002 vise le choix du destinataire de CLIENT_PRIVATE, pas l’ouverture générale de tous les niveaux.

Le dossier `recent` est l’autorité de ce rapport. Les notes et reproductions de `/workspace/OPSYS-AI` portent l’ancien arbre et ne prouvent pas automatiquement un défaut actuel. Quelques comparatifs bornés sont établis par les preuves séparées de la coordination :

- La dépendance au contexte Decimal M5, la mutabilité de la primitive d’approbation M7 et le retour vert de l’ancre vide M1 sont hérités ; ils ont été rejoués sur les sources récentes.
- Le rejeu/mauvais rattachement M6 subsiste dans le contrat historique, alors que la déclaration enrichie nouvelle ajoute des garanties effectives. Dire « tout M6 est inchangé » serait inexact.
- Le défaut ancien M9 de **tri lexical des horodatages** est corrigé dans l’état récent par la comparaison de dates parsées. DEP-008 est une autre omission : le groupement des contradictions n’emploie pas la même normalisation.
- Les autres pistes de l’ancien arbre, notamment références/révisions M10, contrats M1, ROI M7 ou valeurs M6 non finies, restent dans les rapports comparatifs de la coordination. Elles ne sont pas ajoutées comme constats récents sans reproduction récente.

## Matrice de verdict

| Exigence/risque | Observation indépendante | Preuve dominante | Verdict |
|---|---|---|---|
| Identité immuable des factures et créance exacte | Une création remplace la facture envoyée dans la projection | `M5_CAPACITES_COLLISION` | FAIL |
| Données privées livrées au seul département autorisé | Paramètre libre ouvre CLIENT_PRIVATE à la vue M1 | `M10_CAPACITES_AGENT` | FAIL |
| Consommation prouvée et une seule fois par fait | Ancien outil débite deux fois sur WCT affirmé | `M6_CAPACITES_LEGACY` | FAIL |
| Temps réel valide avant WCT | −60 minutes publiées sous revue | `M4_CAPACITES_NEGATIVE` | FAIL |
| Retrait appliqué au lead malgré arrivée dans le désordre | Ancien retrait ne se lie pas au lead découvert | `M7_CAPACITES_RETRAIT` | FAIL |
| Mémoire condensée couvrant les sources tardives | Jour déclaré consolidé avec une source omise | `M10_CAPACITES_LATE` | FAIL |
| Qualité explicite pour tout chiffre | Texte « nan » présent sans alerte de qualité | `M8_CAPACITES_NAN` | FAIL |
| Contradictions détectées pour le même instant | Valeurs différentes, même instant, liste vide | `M9_CAPACITES_TIMEZONES` | FAIL |
| Rejeu identique distingué d’un conflit | WCT changé accepté avec l’ancien contenu | `M10_CAPACITES_WCT` | FAIL |
| Approbation des écritures en mode ombre | Appel M1 mis en attente avant mutation | `M1_DEFAULT_MODE` | PASS borné à ce cas |
| WCT lu à la source par la nouvelle déclaration M6 | Identifiant inconnu explicitement refusé | `M6_CAPACITES_NEW_UNKNOWN` | PASS borné à ce cas |
| Complétion produit globale : E2E, mobile, connecteurs, traces, documentation | Suites unitaires/integration locales et lectures ciblées seulement | Artefacts ci-dessus | PARTIAL ; pas de verdict de complétion globale |

**Priorité corrective :** traiter DEP-001/002/003 avant exposition élargie, puis durcir les entrées et invariants de DEP-004 à DEP-010 aux points d’entrée réels. Les comparaisons d’empreinte, tests de séquences croisées et tests de destinataire au répartiteur apportent davantage de preuve que l’ajout de nouvelles assertions de forme sur les primitives.

**PREUVE — audit borné terminé, sources inchangées ; le verdict d’intégrité/confidentialité reste FAIL.**
