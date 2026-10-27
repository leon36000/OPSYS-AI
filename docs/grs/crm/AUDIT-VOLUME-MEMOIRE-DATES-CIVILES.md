# Audit — volume réel des contextes civils M10

## Objectif, état et réutilisation

Après le raccord HTTP/CAS qualifié localement en f820f1f1, le lecteur civil assemble tous les
paquets restrictifs dans une réponse limitée à 64 Kio. Il refuse au lieu de confirmer sur un
sous-ensemble. Cela protège la décision mais ne qualifie pas les 200 visites du contrat M4.
La précédente fixture synthétique de volume scellait un import; elle ne prouvait pas un plan
réel de cette taille. Mesurer d'abord la frontière et le coût, avant d'en changer l'architecture.

Réutiliser les vrais outils inscription/localisation/proposition/application M4, le solveur
PyVRP 0.14.0 déjà épinglé, le propriétaire M10 amont et son port restrictif, TestClient/SQLite
et les preuves privées existantes. Aucun nouveau framework, stockage ou endpoint externe.
L'extra solveur de QA est installé hors ligne dans un répertoire privé distinct : 14 roues
du cache existant, SHA256 comparés au lock; l'environnement précédent n'est pas modifié.

## Mesure et données

Trois populations indépendantes de 6, 24 et 64 affaires fictives : inscriptions manuelles M4
et positions réellement confirmées; durées/fenêtres/quarts explicites fournis pour le scénario;
vrai plan PyVRP, toutes les visites effectivement appliquées. L'absence de durée réelle ou de
trafic reste une limite : ce scénario qualifie la projection mémoire, pas des promesses client.
M10 reçoit un fait amont fictif validé par son propriétaire par affaire, sans simuler un canal
M1 réel ni déduire un service d'un type legacy. Les deux taxonomies restent déclarées.

Mesurer séparément préparation/solveur et lecture du contexte : temps, nombre d'appels réels
M10, SELECT SQL, taille de réponse UTF-8, retour complet ou refus explicite du quota. Aucune
somme des populations et aucune extrapolation de gain sans comparaison. Le GET du même plan
doit conserver la base et afficher le contexte complet ou une indisponibilité sans bouton.
Les tests reconnaissent un refus de quota comme une limite, jamais comme capacité complète.

## Architecture, fichiers, routes et permissions

Fichiers : `memoire_plan_calendrier.py`, `memoire_chantier.py`, `confirmation_dates_chantier.py`,
`crm_ui.py`; propriétaire `m4_field_ops.cedule_tournees/tournees` et M10 `paquets/amont`.
Routes existantes GET/POST `/crm/cedule/plan/{plan_id}`; aucune route ou permission supplémentaire.
Admin SQL actif/session courante; schémas/données/profils gardés par leurs propriétaires.
Source en lecture seule pendant les QA; homes/tmp/caches privés avant imports; un CPU, 1 Gio,
swap nul, 96 tâches, dix minutes maximum, sockets réseau interdits. Seulement données fictives.

## Statut, risques, gates et prochaine action

**PARTIAL — mesure à acquérir.** Si le quota bloque un plan réel, comparer pagination bornée
et résumé déterministe signé avec détail par affaire, en réutilisant les pages déjà présentes.
Une décision doit toujours être liée aux sources complètes, aux omissions et aux signaux,
sans élargir le budget d'un outil d'agent ni substituer un simple résumé à une preuve complète.
Conserver les refus de sources/quotas et l'ancien format des reçus; aucun replay interdit.
Pas de nouveau gate Nathan pour ce travail privé réversible; aucun client, achat, donnée réelle,
paiement, droit, fusion ou déploiement. Volume maximal, PostgreSQL, navigateur et mobile ouverts.


## Mesure acquise et décision ciblée

`civil-volume-v1` a refusé trois mauvais oracles de QA : mode_bride désigne le routage haversine,
pas l'absence de PyVRP. Sans modifier le produit, `v2` vérifie le vrai solveur/version et garde
ce mode de distance explicite. Les trois vrais plans sont appliqués sans visite non cédulée.
6 affaires : 13 203 octets, 6 appels M10, 80 SELECT, 0,041 s de lecture; 24 : 49 042 octets,
24 appels, 188 SELECT, 0,086 s. Pour 64 visites réellement appliquées : refus explicite de
quota après 30 paquets, HTTP 503 et aucune confirmation partielle (0,144 s, 210 SELECT).
Trois tests passent en 3,53 s, ce qui mesure cette frontière et ne qualifie pas 64 contextes.
Le compteur ciblé maillons utilisait le mauvais nom SQL : son zéro n'est pas une absence de
lecture; le compteur SELECT global reste valable. Les propriétés JUnit conservent ces faits.

Réemployer le contrat de `pages_semaine` (ordre stable, continuation liée à la source,
reprise explicite si source changée), sans appeler le lecteur hebdomadaire ni emprunter ses
25 éléments. Le port civil doit valider et lire **tous** les paquets des affaires distinctes,
hasher les liaisons/paquets complets réellement consommés, puis exposer une synthèse globale
et au plus trois visites détaillées par page. Si nécessaire, réduire la page jusqu'à une
visite pour rester sous 64 Kio; si même une ne tient pas, refus explicite conservé. L'offset
est un curseur de visite, pas d'affaire : une affaire avec 200 visites ne gonfle pas une page.

La synthèse globale compte affaires/visites, non-représentabilité, inconnues/origines absentes,
liens de devis non mémorisés, signaux et omissions **par couche**, jours-affaire à consolider.
Pas de total naïf de faits recoupés entre couches. Les détails hors page restent annoncés.
L'empreinte de confirmation reste identique quelle que soit la page et conserve la formule
historique complète; aucune migration des reçus, aucun offset dans l'intention. La continuation
est liée au plan et à M10. GET accepte seulement offset/source valides; POST reste sans query.
Le bouton utilise la preuve globale après lecture de tous les paquets; aucune nouvelle
obligation de visiter chaque page ni nouvelle politique de signaux n'est inventée.

La pagination traite la réponse et la disponibilité. Elle ne promet pas de réduire les
lectures M10 : mesurer encore les appels/SQL et le POST avant d'optimiser les snapshots.
Préserver savepoint/rejeu legacy/contrôles après effet. Tests : vrai plan 64 parcouru sans
perte ni doublon de visite, source changée entre pages, contexte dangereux/défectueux hors
page, formulaire/preuve globale identique entre pages, confirmation réelle depuis une page
ultérieure, quotas, rôles et refus des paramètres. 200 visites restent à mesurer séparément.


## Qualification exécutée — pagination et preuve globale

Le port charge et valide tous les paquets distincts, produit la même empreinte complète que
le format historique, puis projette au plus trois visites (et leurs affaires) par page. Une
synthèse globale précède les détails et le bouton; elle inclut signaux hors page, inconnues,
origines, non-représentabilité, omissions par couche et jours-affaire à consolider. Chaque
réponse garde sa borne de 64 Kio; elle réduit le détail à une visite si nécessaire, sinon
refuse explicitement. Ni budget d'outil, ni faits protégés, ni permission ne sont élargis.

Le GET accepte uniquement une continuation offset/source stricte. Une modification M4 ou
M10 rend la continuation obsolète : HTTP 409 avec reprise au début. Le POST reste sans query;
l'offset n'entre pas dans l'intention et le reçu exact reste historique. Un test reconstruit
indépendamment l'ancienne formule avec les vrais paquets complets et prouve son identité.
Le parcours des 64 visites ne perd ni ne duplique une visite, puis confirme réellement les
dates depuis la dernière page et rejoue son reçu sans nouvel effet. Un signal ou un paquet
défectueux hors page reste contrôlé : six signaux réels sont visibles dans la synthèse et
une mauvaise réponse hors page empêche toute confirmation.

La revue indépendante a trouvé un retour arrière calculé naïvement à offset-3 malgré des
pages réduites à une ou deux visites. `civil-volume-pagination-back-red-v1` reproduit 3→4,
puis retour incorrect à1 au lieu de3. Les bornes précédentes sont maintenant recalculées à
partir des pages réellement acceptées au même budget et aux mêmes sources, sans nouvel
appel M10 ni SQL. L'aller-retour sous quota réducteur passe. Le quota irréductible reste
refusé; l'ancien test artificiel de4500 octets utilise désormais2500 pour tester le cas où
même une visite détaillée ne tient pas, après l'ajout volontaire de la pagination explicite.

`civil-volume-pagination-v2` conserve 78 PASS et un rouge de prérequis de volume : les200
interventions inscrites sont refusées avant proposition par le contrat de matrice100 points
(200 chantiers +2 dépôts =202). Aucun plan de200 n'a été créé ni prétendu qualifié. Le test
réel de frontière est désormais98 visites +2 dépôts;200 vérifie séparément le refus sans
nouvelle proposition/application. La limite100 demeure une capacité produit ouverte, pas
un bug de solveur déduit d'une erreur de harnais. Elle exige un prochain chantier explicite.

`civil-volume-pagination-v3` : **81 PASS, 0 FAIL/SKIP, 45,92 s** (10 cas de volume/pagination
et les71 cas précédents inclus, aucun cumul). Ruff ciblé et vérificateur297/173 passent.
Source lecture seule pendant QA; mêmes limites et dépendances privées décrites plus haut.
Le rouge initial64→503, le mauvais oracle de mode bridé, les refus au lint, le rouge200 et
celui du retour arrière restent distincts dans les commandes/logs/JUnit/reçus conservés.

Mesures sous un CPU, sans allégation de gain de débit :

| Affaires/visites réellement appliquées | Réponse JSON | Appels M10 distincts | SELECT | Lecture | HTTP |
|---|---:|---:|---:|---:|---:|
|6|8421 octets|6|80|0,041 s|200|
|24|11936 octets|24|188|0,064 s|200|
|64|19739 octets|64|428|0,185 s|200|

Le cas64 traite maintenant tous les paquets; l'ancienne lecture refusée s'arrêtait après30
(0,144 s), donc ce n'est pas un gain de vitesse. Les réponses HTML mesurent7897/10513/16427
octets. Les lectures restent répétées par affaire; la pagination ne les cache pas. Le vrai
plan98 est appliqué en1,303 s de préparation; premières/dernières pages :26375/22785 octets,
deux lectures en0,710 s. Toute la navigation98 n'est pas qualifiée. Les200 inscriptions
conduisent au refus explicite de matrice en4,112 s, sans plan. Durées fictives5 minutes,
quatre jours numériques, distances haversine_detour en mode bridé : aucune promesse terrain,
optimisation routière de production ou trafic réel n'est déduite de ces scénarios.

**PARTIAL.** Les cas64 et frontière98 sont qualifiés dans ces périmètres;200 demeure ouvert.
Prochaine action : auditer le contrat100 points et le réemploi d'un calcul/matrice par blocs,
sans relever une limite à l'aveugle ni inventer une disponibilité globale. Mesurer ensuite
le coût des snapshots M10 répétés avant toute mutualisation. Navigateur, PostgreSQL, mobilité,
trajets réels, capacité opérationnelle complète et fraîcheur météo restent ouverts. Aucun
client, fournisseur, paiement, droit, fusion ou déploiement réel n'a été engagé.


Jalon suivant : [séparation matrice globale/transport](../field/M4-AUDIT-MATRICE-GRANDE-CAPACITE.md).
La borne globale est désormais256, OSRM transport reste100 sans nouvelle requête. Un vrai
plan200 PyVRP/haversine a été appliqué, parcouru sur67 pages, confirmé et rejoué sans effet.
Les353 cas puis les deux contrôles complémentaires compatibles passent, sans cumul. Le refus
historique202>100 n'est pas effacé. Le batch routier et les autres limites restent PARTIAL.
La mesure13400 appels M10/80,492 s pour la navigation200 rend la mutualisation des snapshots
par préparation pertinente; aucun gain ni coût constant n'est encore revendiqué.

Jalon suivant : [snapshots M10 par préparation](../analytics/M10-AUDIT-SNAPSHOTS-PAQUETS-CIVILS.md).
Sur le même scénario et sous les mêmes limites, les 200 visites / 67 pages passent de80,492 s
à31,290 s, avec13400 vrais T0 conservés et la même preuve globale/date/rejeu. Sur24 affaires,
les lectures SQL M10 complètes passent de53 à4. Capture privée par requête, autorité SQL
courante à chaque T0, aucune cache interrequêtes. Ce gain local observé ne constitue ni un
SLA, ni une qualification terrain/dispatch. **PARTIAL**; profiler ensuite le pur assembleur.
