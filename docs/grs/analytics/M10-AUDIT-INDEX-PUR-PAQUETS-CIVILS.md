# M10 — audit du prochain coût des paquets civils

## Objectif et état actuel

La capture SQL par préparation est qualifiée localement dans le jalon précédent :200 visites
sur67 pages en31,290 s contre80,492 s avant capture. Les13400 T0 réels restent nécessaires
au parcours actuel. Le prochain problème concret est le coût de construction pure de chaque
paquet, sans alléger les couches, les omissions, les sources ni l'autorité.

Cet audit suit une mesure instrumentée; **aucun index pur nouveau n'est implémenté ici**.
Le code produit reste celui du commit `74a6724c`. La capacité générale M10 reste PARTIAL.

## Mesure et pourquoi

Le premier appel réel à `memoire_plan_calendrier.lire` d'un plan PyVRP de200 visites a été
profilé avec `cProfile`, sous les mêmes limites privées que la qualification précédente.
Une seule préparation est instrumentée; les arguments/faits ne sont pas exportés. Le test
existant vérifie ensuite premières/dernières pages, HTTP, vraie datation et rejeu sans effet.
Ce test passe, comme Ruff et le vérificateur297/173. Les temps incluent le coût du profileur;
**ils ne sont pas une nouvelle mesure de latence non instrumentée**.

Observations du profil :200 vrais appels `_paquet`,601 lectures des lecteurs capturés,
939049 appels récursifs à `deepcopy`,280600 classifications `type_evenement` et400 appels
`evenements_de_laffaire`. Le profil entier compte11116612 appels et1,831 s de temps propre
agrégé. La copie profonde cumule0,783 s; le pur assembleur, appelé200 fois, cumule1,226 s.
Ces temps sont **imbriqués et non additionnables**. Aucune prévision chiffrée de gain ne peut
en être déduite directement. Le registre général est encore copié/classifié à chaque affaire.

## Architecture minimale à examiner avant patch

Réutiliser M10 pur et ses algorithmes actuels : `classification`, `signaux`, `amont`,
`decisions`, `consolidation`, `confidentialite`, `paquets`. Ne pas installer un framework pour
ce coût Python local. Le même propriétaire détient les snapshots bornés déjà validés.

Candidat : préparer une projection pure interne sur ces snapshots une fois par préparation,
puis assembler les mêmes quatre couches pour une affaire. Les champs, règles de tri stable,
heure demandée, budgets, compteurs retenus/omis, jours à consolider et niveaux de confidentialité
doivent rester exactement ceux de l'assembleur ordinaire. L'outil T0 garde à chaque appel son
contrôle SQL admin et les gardes de capture (connexion/transaction/savepoint/acteur/durée de vie).
Aucun cache entre requêtes, aucun paquet prêt fourni par le modèle, aucun lecteur mutable exposé.

Ne pas filtrer naïvement le registre par `lead_id` : les variances/rentabilités se résolvent
via WCT et certaines lignes n'ont aucun lead direct. Les signaux parcourent leurs cycles de
vie et réévaluations; les décisions d'entreprise concernent toutes les affaires. Les règles
globales et positions d'origine doivent rester disponibles. La preuve de source continue à
citer les snapshots complets réellement utilisés, pas la tête d'une sous-liste reconstruite.
Une projection ambiguë ou non admissible refuse explicitement; aucune source partielle ne
doit être maquillée en contexte complet.

## Fichiers, données, routes, intégrations et permissions

Surfaces candidates : M10 `paquets.py` et son adaptateur privé `outils.py`, nouveaux tests purs
et tests de capture. La console reste consommatrice des mêmes T0 et sources. Aucune nouvelle
route, table, donnée de santé, permission, API externe ni modification des départements M3/M4.
L'admin SQL actuel reste obligatoire; les données financières/personnelles restent filtrées.

## Tests et risques avant qualification

Équivalence différentielle exacte avec l'assembleur ordinaire sur affaire inconnue, origine
manquante, lead/opportunité, WCT/variance/rentabilité, WCT orphelin, identifiants répétés et ordre
d'arrivée, réévaluation/clôture humaine, consolidations remplacées, décisions globales et statuts,
décalages horaires, omissions/budgets et chaque profil de confidentialité. Tester les copies
sans alias et refus de capture existants; garder le parcours réel200/67pages et la formule
historique de preuve/date/rejeu. Mesurer ensuite le même scénario sans profileur, sous les
mêmes limites, et reporter séparément le coût mémoire. Ne pas additionner les cohortes.

Preuves : `M10-PURE-PROFILE-QUALIFIED.json` dans le chantier CRM; phase QA distincte
`m10-capture-profile-v1` et plugin QA épinglé. Les anciens rouges restent historiques.
**PARTIAL — profilage local qualifié, index non commencé.** Prochaine action précise : définir
et tester différentiellement la projection pure sur les règles métier ci-dessus avant tout
raccord à la capture. Aucun nouveau gate Nathan pour ce travail privé réversible. Production,
PostgreSQL, navigateur, mobile et déploiement restent hors de cette preuve.

## Décision d'implémentation avant patch

Retenir une préparation pure propriétaire, copiée une fois, qui construit l'index WCT global
puis résout chaque événement avec la même fonction de classification. Préserver l'ordre de
registre dans les groupes. Calculer tous les signaux sur les deux registres complets avant
groupage; conserver déduplication globale, positions et réévaluations. Préparer les candidats
avant confidentialité, jamais des paquets filtrés par profil. Partager seulement le dernier
assemblage de sortie et extraire le calcul de situation après classification; la voie ordinaire
conserve sa propre sélection complète et reste l'oracle différentiel.

Revue indépendante : le calcul des faits consolidés filtre l'affaire avant de choisir la dernière
clé, mais les jours non consolidés choisissent les dernières clés globalement. Garder donc
le registre affaires complet pour `_a_consolider`. Tester explicitement la clé contradictoire,
les WCT réutilisés entre affaires, les signaux dédupliqués globalement et les offsets égaux.
Les copies des entrées et sorties doivent isoler aussi les blocs imbriqués. L'adaptateur de
capture reste inchangé tant que cette préparation pure n'a pas ses preuves différentielles.

## Qualification de la projection pure et du raccord

La préparation pure est maintenant implémentée dans `paquets.py`, avec un petit helper de
situation postclassification dans `amont.py`. Elle copie ses entrées une fois, résout les WCT
et signaux globalement, groupe ensuite sans changer l'ordre et garde les candidats complets
avant tout filtre de confidentialité. Chaque sortie reconstruit ses conteneurs. Le lecteur
ordinaire conserve sa sélection complète et partage seulement l'assemblage final de sortie.
Les tests historiques protègent donc aussi contre une régression commune à ce helper partagé.

Dans `outils.py`, seule la capture privée construit cette projection, après bornes et validation
des deux chaînes. Chaque vrai T0 garde ses contrôles SQL admin, connexion/transaction/savepoint,
identité, durée de vie, quota et têtes effectivement consommées. Aucun cache entre requêtes.
Sur24 affaires, la copie répétée des lecteurs capturés est passée de73 à3 appels `lire`, avec
une construction pure unique. Les quatre lectures SQL complètes et les24 T0 sont conservés.

Les cinq jeux différentiels couvrent5 affaires dont une opportunité et une inconnue,11 profils
et3 couples budget/nombre maximal :825 comparaisons exactes, pas825 tests indépendants.
Ils incluent WCT réutilisé entre affaires, variance orpheline, signaux dédupliqués globalement,
réévaluation et clôture humaine, décisions remplacées, tous niveaux de confidentialité,
consolidation avec source tardive et clé contradictoire, et instants égaux avec offsets distincts.
Copies des entrées/sorties et validation par requête sont contrôlées séparément.

Qualification bornée : cohorte pure440 PASS en4,79 s; cohorte adaptateur/civil124 PASS en45,46 s;
deux cas de performance compatibles PASS en24,86 s. Les cohortes sont recoupées et ne sont
pas additionnées. Ruff ciblé et vérificateur297/173 passent. Les rouges initiaux (helper absent,
73 copies) et les erreurs de fixture (identifiant avec caractère interdit et retour dict traité
comme tuple) sont conservés; ces erreurs de harnais ne sont pas déclarées bugs produit.
Revue indépendante statique sans défaut concret après prise en compte du piège de consolidation.

|Même scénario fictif, mêmes deux tests et limites|Avant capture|Capture SQL seule|Projection pure|
|---|---:|---:|---:|
|Navigation complète200 /67 pages|80,492 s|31,290 s|16,781 s|
|T0 réellement exécutés durant la navigation|13400|13400|13400|
|Maximum JSON|46275 octets|46275 octets|46275 octets|
|Mémoire maximale du groupe QA|160591872|160018432|161300480|
|RSS maximal des enfants QA|174460928|175763456|177131520|

La projection réduit de46,4 % le temps observé après capture seule (1,86 fois plus rapide).
L'ensemble des deux changements mesure4,80 fois le parcours initial, soit79,2 % de réduction
observée. Une seule observation par scénario, **aucun SLA ni gain universel**. Fichiers des
deux tests et matrice inchangés, PyVRP0.14.0, un CPU/1Gio/swap0/96 processus, Source en lecture
seule, réseau interdit, homes/tmp privés. La preuve historique globale, la datation réelle
SQLite et le rejeu sans effet passent toujours. Routage haversine bridé; aucun trafic réel.

Preuve finale : `M10-PURE-PROJECTION-FINAL-QUALIFIED.json` dans le chantier CRM.
**PARTIAL — tranche locale SQLite qualifiée.** Le contexte civil reste recalculé par page et
les13400 autorisations T0 restent actuelles. Prochain travail : choisir une capacité serveur
métier encore ouverte après réconciliation de publication/CI; ne pas modifier le modèle
d'autorité pour chasser un autre gain. M10 complet, navigateur, PostgreSQL, mobile, routage
réel et dispatch global ne sont pas qualifiés par cette tranche.
