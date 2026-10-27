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
