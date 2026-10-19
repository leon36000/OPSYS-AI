# M9-strategic-intelligence

Strategic Intelligence OS — direction IA, harnais déterministe pur (aucun Council en v1).

Statut : **PARTIEL**. Département OPSYS structuré (manifeste, SOUL, skill, outils d'agent) sur le modèle de
M3-estimation, mode `ombre`. Les cinq stories de domaine S001-S005 du PRD sont livrées et
vertes : contrats gelés (`SnapshotModule` réutilisé de M8, `CHAMPS_RAPPORT_STRATEGIQUE` 15
clés), validation structurelle d'entrée, registre append-only hash-chaîné, Business State
Graph et détection de contradiction interne, validation structurelle du rapport stratégique,
conformité statique.

- `department.yaml` — manifeste (`m9_strategic_intelligence.outils`, dépend de
  `m08-analytics` et `m10-memoire`).
- `SOUL.md` — identité de l'agent.
- `skills/etat-consolide-et-contradictions/` — procédure d'ingestion → état consolidé.
- `src/m9_strategic_intelligence/outils.py` — outil composé `m9_etat_consolide` (validation →
  registre → état consolidé, contradictions comprises) + 3 outils unitaires.
- Correctif de fiabilité (TDD, test dans `tests/test_etat_consolide.py`) : le dernier fait
  connu par module était choisi par comparaison ALPHABÉTIQUE des horodatages bruts ; comparé
  désormais en `datetime` ISO-8601 parsé, fuseaux compris (patron `m8_analytics/semantique.py`).
- Cohérence inter-départements (`tests/test_contrat_snapshot_m8_m9.py`) : le contrat
  `SnapshotModule` est validé identiquement par M8 et M9 — une valeur numérique est rejetée
  par les deux, jamais acceptée par l'un et refusée par l'autre.

- PLAN T1.5-d : le briefing du matin est borné par le code sous la limite de sortie du socle (« N autres
  éléments non affichés », lus par `m9_lire_suite_briefing`) ; `m9_produire_lecture_strategique` lit les
  alertes de mesure de chantier de M8 et cite leurs preuves, sans décider (la décision revient au
  propriétaire). `department.yaml` : `configuration.fenetre_alertes_jours`.
- PLAN T1.5-d (dernier reste) : `m9_lire_alertes_m8` (`admin`) est borné comme le briefing. Avant, il rendait TOUTES
  les alertes de M8 reçues, sans limite : au-delà d'une dizaine, la réponse dépassait les 6 000 caractères de
  `Capacites` et l'app recevait un aperçu coupé. Maintenant il accepte `depart` (entier ≥ 0, 0 par défaut) et
  rend autant d'alertes que `BUDGET_SORTIE` en laisse tenir (le budget de `m9_lire_suite_briefing`, mesuré par le
  code sur la taille sérialisée). Ordre stable : le plus récent d'abord (`horodatage_reference` comparé en
  instant, fuseaux compris), puis `evenement_id` croissant. Pas de filtre de date. La réponse est un objet
  `ALERTES_M8` : `alertes`, `total`, `depart`, `affichees`, `reste`, `prochain_depart` (nul à la fin), `message`,
  `ordre`, `source`. Un `depart` égal au total rend une page vide ; au-delà, ou négatif, un refus métier qui dit
  de reprendre à 0 ; une alerte incomplète, à l'horodatage illisible ou plus grosse que la borne est un refus qui
  la nomme (jamais ignorée). Code : `lecture_alertes.py` (module pur). **Changement de forme :** la réponse était
  la liste nue ; une liste ne peut porter ni total ni `prochain_depart`, et cette forme n'était pas un contrat
  gelé (aucun schéma, aucune entrée sous `contracts/`, aucun consommateur dans `src/`, `mobile/` ou les E2E ;
  seuls deux tests la figeaient, mis à jour). Les alertes sont maintenant sous la clé `alertes`. L'app mobile
  n'appelle pas cet outil : aucun écran ne change.

Council d'agents, Strategic Supervisor, scénarios narratifs et Decision Intelligence Engine
restent GATED (hors périmètre v1, cf. `docs/bmad/02-PRD-PM.md` §3.2).

## Dossier préparatoire de direction sourcé (CF-034, tranche M9.10)

`m9_preparer_dossier_direction(question, modules_attendus)` prépare une lecture de la chaîne
de snapshots déjà reçus pour une question de chantiers, équipes, matériaux ou autres faits
déclarés par les modules. La question reste inchangée ; les 1 à 16 identifiants attendus sont
explicites, distincts et conservés tels quels, sans catalogue ni correspondance inventée.
L'outil capture et valide la source une seule fois, puis réutilise cette copie pour l'état
consolidé et ses citations. Il ne modifie aucun registre métier, suivi, approbation ou événement ;
le journal normal d'invocation du socle demeure actif. Sur appareil, l'admin et son rôle SQL
courant sont requis, comme pour la lecture de l'état consolidé.

Le résultat `DOSSIER_PREPARATOIRE_DIRECTION` conserve l'`etat_id`, les faits sélectionnés et
les métadonnées de contradictions du consolidateur. `preuves` contient les maillons complets,
triés par index, y compris chaque variante contradictoire non sélectionnée. Une référence
absente ou ambiguë provoque un refus explicite, même si les hashes de la chaîne sont valides.
Une source dont les clés ou valeurs changeraient à la sérialisation JSON est aussi refusée,
sans réécrire la preuve ; l'ingestion durable ordinaire exige déjà des clés et valeurs textuelles.
`modules_manquants` nomme les identifiants demandés absents ; une liste vide ne démontre pas
une couverture complète. L'empreinte `dossier_id` lie question, périmètre déclaré et contenu.

La sortie reste `NON_VALIDE`, avec actualité `NON_EVALUEE`. Elle n'arbitre aucune contradiction
et ne recommande ni n'exécute d'action. Si dossier et citations dépassent le budget de sortie
du socle, l'outil refuse sans tronquer ni supprimer de preuve. Il n'offre pas encore de pagination
pour les grands registres ; une revue séparée reste nécessaire dans ce cas. Ce format distinct
ne remplace pas le rapport stratégique complet à 21 sections ni son validateur structurel
historique à 15 clés. M9 et OPSYS-AI restent **PARTIELS**.

`tests/test_dossier_direction.py` exerce la consommation par `Capacites` en SQLite temporaire,
les citations contradictoires, la capture unique, les refus et les accès. Toutes les données
sont fictives ; ces essais ne prouvent ni une décision terrain ni un parcours Core/mobile réel.

`m9_diagnostiquer_dossier_direction(question, modules_attendus, horodatage_reference)`
réutilise ce producteur serveur autorisé, avec une seule capture validée, puis rend le
`dossier` et son `diagnostic` temporel liés par leurs identifiants. Aucun dossier n'est accepté
en argument. La référence doit porter un fuseau explicite ; aucune horloge interne ni
conversion implicite d'une observation sans fuseau n'est ajoutée. L'écart signé en secondes
vaut référence moins observation : `OBSERVATION_FUTURE`, `A_REFERENCE` ou
`ANTERIEURE_REFERENCE`. Les faits sélectionnés et toutes leurs preuves historiques demeurent
inchangés, y compris les contradictions. Cet âge ne démontre ni fraîcheur métier ni SLA :
`actualite_metier` reste `NON_EVALUEE`. Sur appareil, l'admin SQL courant est revérifié avant
la capture. Dossier, preuves et diagnostic doivent tenir ensemble ; une borne de transport
plus basse produit aussi un refus explicite, sans troncature ni artefact.

`tests/test_diagnostic_direction.py` vérifie ce consommateur en SQLite temporaire, les
frontières de rôle, la capture unique et les deux bornes. Ce parcours reste distinct d'une
qualification Core/mobile, PostgreSQL ou métier complète ; M9 et OPSYS-AI restent **PARTIELS**.

## Suivi interne d’une décision sur preuve M8 (CF-034, première tranche)

Le département reste **PARTIEL**. Trois outils ajoutent un parcours déterministe :

- `m9_preparer_suivi_decision(evenement_id)` relit une alerte de mesure M8 déjà reçue par le bus et calcule son empreinte canonique. La preuve rendue est `historique_recue`, sa couverture `non_evaluee` ; aucune actualité métier n’est déduite.
- L’agent propose `m9_ouvrir_suivi_decision(evenement_id, empreinte_source, action, responsable_id, echeance)`. Le suivi est écrit seulement pendant l’exécution de **sa propre demande N3**, approuvée par un `nathan_owner` encore actif en SQL. Une ancienne ingestion approuvée et un appel direct ne donnent pas ce mandat. Le code relit la preuve exacte et le responsable interne actif au point d’effet ; l’échéance ISO doit porter un fuseau explicite.
- `m9_lire_suivi_decision(suivi_id)` relit le suivi sans mutation. Son identifiant est celui de la demande dédiée. Les deux lectures sont réservées à l’admin sur appareil, avec rôle SQL courant revérifié.

Le registre durable séparé `suivi_decisions` conserve la preuve reçue entière, son empreinte, les arguments approuvés et le signataire/date SQL. La taille est refusée avant append si le résultat ne tient pas dans le budget ; jamais de succès tronqué. Le statut `planifiee` signifie uniquement que le suivi interne est enregistré. Aucun achat, envoi, dispatch, écriture financière, achèvement d’action ou alimentation automatique M10 n’en résulte. Une échéance passée explicite n’est ni déplacée ni présentée comme respectée.

`tests/test_suivi_decisions.py` exerce le producteur M8, le bus, les approbations natives, les refus et le rejeu après réouverture du pool SQL. Les événements de devis et chantier en entrée sont des fixtures fictives ; ce test ne prouve pas le parcours terrain M3/M4, le Gateway, un téléphone, PostgreSQL ou un redémarrage de processus.

Les appels MCP à l’ouverture exigent un ticket de cible privé, y compris par `/mcp` sans département ou avec un profil runtime valide. L’origine MCP est fixée par le wrapper, jamais par les arguments ou `_meta`. L’appel programmatique natif garde sa proposition sans ticket puis son approbation dédiée ; un ticket ne remplace jamais cette approbation.

Le résolveur SQLite confronte l’alerte M8 reçue à sa publication et à son reçu, puis au WCT publié par M4 et mémorisé sans ambiguïté dans la chaîne M10 `evenements`. Son affaire canonique doit correspondre à la liaison de session courante dans la chaîne M10 `affaires`. Ces contrôles sont rejoués à l’effet de l’approbation scellée : passer de la session liée à A vers B refuse l’ancien ticket, même si le propriétaire reste valide. Aucun identifiant d’affaire n’est fabriqué depuis le WCT, aucune alerte historique n’est réécrite.

`tests/test_suivi_m9_cible_core.py` couvre les vraies routes MCP HTTP, le profil runtime, les deux chaînes M10, la provenance et le changement de liaison. La configuration destinée au Core déclare une cible `ticket` ; ces essais Python/MCP ne certifient pas à eux seuls un parcours Gateway/TypeScript complet. La liaison de cible reste fermée hors SQLite selon le contrat du socle existant ; aucun oracle PostgreSQL M9 n’est revendiqué.

Restent ouverts : rapport de décision complet, couverture/fraîcheur stratégique, tableau de bord stratégique complet, révision des suivis et clôture des actions terrain sur preuve, orchestration des actions dans les départements et qualification complète des parcours Core/mobile correspondants. L’ambition M9.10/M9.16/M9.17 est conservée, sans assimiler cette ouverture à leur livraison complète.


### Clôturer la revue humaine d’un suivi interne

`m9_preparer_cloture_suivi_decision(suivi_id, evenement_id)` relit le plan original et une
preuve M8 reçue. Elle rend l’empreinte du plan et la preuve exacte. Métrique, chantier
(`wct_id`) et version de définition doivent correspondre à la preuve initiale ; l’alerte
initiale elle-même est admise. Cette lecture reste réservée à l’admin SQL courant.

`m9_clore_suivi_decision(suivi_id, empreinte_suivi, evenement_id, empreinte_preuve, bilan)`
propose une **nouvelle demande N3 dédiée**. Après approbation par le propriétaire SQL encore
actif, le code relit les deux empreintes et enregistre une clôture unique dans
`clotures_suivi_decisions`. Le bilan humain doit être explicite et borné. Le plan initial et
sa source demeurent inchangés ; `m9_lire_suivi_decision` ajoute la clôture et
`etat_suivi: cloturee_par_revue_humaine`. La sortie complète est bornée avant l’écriture.
Un appel direct, l’approbation d’ouverture, une preuve étrangère ou modifiée et une seconde
clôture ne donnent aucun droit d’écriture. Le rejeu conserve le même résultat.

Il s’agit de la **validation humaine d’une revue interne**, sans exécution d’action,
attestation terrain, fraîcheur métier ni preuve d’amélioration causale. Le parcours SQLite
est distinct du Gateway et du téléphone. La mutation demeure fermée au MCP générique sans
cible et aucun émetteur de ticket privé Core de clôture n’est livré par cette tranche.
Les tests fictifs de `test_cloture_suivi_decisions.py` conservent cette séparation.


### Retrouver les actions assignées encore ouvertes

`m9_lister_suivis_decision(horodatage_reference, depart=0, vue_attendue=None)` lit les
suivis internes approuvés qui ne sont pas clôturés par revue humaine. Chaque ligne conserve
le plan original, son responsable, son échéance, sa preuve M8 historique et son empreinte.
Le code trie par instant d’échéance croissant puis identifiant, et calcule `EN_RETARD`,
`A_ECHEANCE` ou `A_VENIR` face à la référence explicitement zonée de l’appelant. Il ne lit
aucune horloge et ne déduit ni actualité métier, ni action terrain exécutée.

La lecture T0 reste réservée à l’admin SQL courant sur le chemin appareil ; le chemin
agent natif existant reste disponible. Plans et clôtures sont lus dans la même transaction.
Une date invalide, un doublon, une clôture orpheline ou incohérente sont refusés.

La page rend `total`, `affichees`, `reste`, `prochain_depart` et une empreinte de `vue`
liée aux plans, aux clôtures et à la référence. Pour reprendre après le premier rang,
passer `depart=prochain_depart` et `vue_attendue=vue`. Toute modification de cette vue,
y compris une clôture intervenue entre deux lectures, exige une reprise depuis zéro.
Une ligne trop volumineuse est refusée entière ; aucune action n’est masquée silencieusement.
Ce lecteur ne crée aucune tâche dans un département et ne qualifie pas une interface
Core/mobile. Le département et le produit restent **PARTIELS**.


### Consulter les suivis internes dans la console

L’onglet **Suivis stratégiques** ouvre `/opsys/strategie`. La personne saisit une référence
ISO 8601 avec fuseau explicite ; aucune date courante n’est inventée. La page reprend
`m9_lister_suivis_decision` : actions encore ouvertes, responsables, échéances originales,
états face à la référence, total et reste. Les liens conservent référence et identité de vue.
Une clôture ou une modification entre deux pages refuse la reprise et propose de recommencer.

Le détail `/opsys/strategie/suivi?suivi_id=…` reprend `m9_lire_suivi_decision` et présente
le plan initial, sa preuve historique M8 et la clôture humaine éventuelle. Les textes sont
échappés. La session signée et le rôle SQL `admin` courant sont nécessaires pour lire ces données,
y compris pour une personne portant aussi `nathan_owner` ; un cookie ancien ne maintient pas
un rôle retiré. Aucun bouton d’exécution ou de clôture n’est ajouté.

`tests/test_console_suivis_m9.py` parcourt les vraies routes HTTP, la session, les approbations
et les preuves fictives SQLite/M8 : lecture et détail, pagination exhaustive sur plusieurs pages,
reprise périmée, retrait du rôle, paramètres refusés, échappement et absence de mutation métier.
Cette consultation constitue une tranche du tableau de bord M9 ; elle ne qualifie pas tout le
tableau de bord exécutif, un téléphone physique, PostgreSQL, une action terrain ou la fraîcheur
métier des preuves historiques.
