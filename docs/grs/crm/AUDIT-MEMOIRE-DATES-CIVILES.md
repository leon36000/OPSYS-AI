# CRM-08 — contexte et intégrité avant datation civile : audit

27 octobre 2026, parent 8e6eb56f0c8fad1e786b3af68cec0b3a0ade8923. PARTIAL.
Lecture indépendante ciblée des propriétaires, rapprochée par ROOT; aucune intégration civile
M10 n’est qualifiée par ce document.

## Ancres réelles et absence de devis

`calendrier_civil.lire_plan` expose intervention/équipe/jour/minutes et sources proposition,
application et date, sans lead_id ni devis_id. Résoudre chaque intervention dans un snapshot
M4 borné et validé; inscription unique requise, recoupée à la proposition. Le propriétaire
`etats.inscrire_depuis_devis` porte source=m3.devis_accepte, lead/devis et heure d’acceptation.
L’inscription manuelle `inscrire_intervention` porte un lead, un devis optionnel et aucune
source M3. Un devis renseigné manuellement n’est pas une preuve d’acceptation.

Pour le bus M3, réutiliser le lecteur exact `memoire_chantier.lire` et vérifier l’intervention.
Pour un manuel, lire le contexte restrictif du lead M4 exact sans appeler le lecteur mono-devis,
et annoncer l’absence d’un lien accepté vérifié. Aucun identifiant de substitution, notamment
intervention_id. Deux devis d’une affaire partagent le paquet, pas leur preuve d’acceptation.
Préserver affaire inconnue, origine absente, identifiant non représentable, omissions et signaux.

## Intégrité avant la première date

`annotations_calendrier._creneau` vérifie déjà les empreintes métier proposition/application,
mais exige une vraie ligne de date. Il ne peut pas servir à la révision civile 0 sans inventer
une date, ce qui est interdit. Le lecteur et le writer civils actuels vérifient la chaîne et
les états/équipes, mais n’appellent pas ce contrôle d’empreintes métier. Hypothèse précise à
reproduire avant correction : visite horaire altérée et chaîne reconstituée, sans corriger
les empreintes métier, acceptée avant toute date. La lecture météo ne ferme pas ce cas à
révision 0, puisqu’elle ne propose alors aucun contrôle de prévision datée.

Priorité minimale : test rouge du vrai plan appliqué sans date, en lecture HTTP et en
confirmation propriétaire; extraire le contrôle d’ancres déjà existant dans une primitive
pure partagée M4 utilisable sans calendrier. La réutiliser dans les lecteurs/writers civils
et dans les annotations historiques, sans reconstruire le solveur ni inventer une date.
Conserver états courants, conflits datés et filtres de visite inchangés. Rejouer les cohortes
civiles/annotations/couleurs et les cas CRM touchés; pas de promesse de dispatch ou météo fraîche.

## Raccord M10 suivant, après cette intégrité

Adaptateur privé `memoire_plan_calendrier` : séparer empreinte du plan (tête M4, sources,
révision) et empreinte mémoire (têtes réellement consommées, liaisons, paquets sans heure
volatile). Après une confirmation, comparer seulement la mémoire : M4 a légitimement changé.
Réutiliser le port restrictif M10 et charger chaque affaire une seule fois. Les bornes de
sources doivent précéder décodage; éviter une lecture/validation complète des registres M10
par visite. Prévoir une projection globale bornée avec omissions explicites et détail par
affaire, plutôt que couper les contextes pour montrer le bouton.

Le contrat civil reste 31 jours et 200 visites; aucun bouton si détail tronqué. Un champ
supplémentaire d’empreinte porte le maximum de 34 à 35 champs : adapter explicitement le parser
et le validateur. `metier.executer(preuve_commande=...)` incorpore la preuve dans l’intention,
sans la transmettre à M4. Employer la preuve soumise après vérification. Les anciens reçus
avaient les arguments seuls : détecter la clé enregistrée, borner et vérifier son intention
exacte sous admin courant; ne jamais convertir un conflit en fallback legacy. Une nouvelle
commande sans preuve doit être refusée. Rejeu historique sans nouvelle date ni contexte
historique M10 prétendu. Savepoint et autorité après effet restent obligatoires.

## Tests et limites

Plan mixte réel : M3 accepté, manuel sans devis, deux visites d’une affaire; liaisons exactes
et paquet non dupliqué. Contexte modifié depuis revue ou pendant confirmation : refus et
rollback complet, reçu ancien exact sans nouvel effet. 31 jours/200 visites, champ 35,
projection tronquée, source absente/contradictoire, quota et révocation. Le volume maximal de
contextes doit être qualifié; le budget individuel M10 ne borne pas un assemblage multiplié
par 200. Aucune solution partielle ne doit être appelée capacité globale.

Gates Nathan : aucun nouveau fournisseur, engagement, rôle, paiement ou déploiement pour ces
préparations réversibles. M10 avant datation n’est pas encore livré; politique de fraîcheur,
trajets/capacité globale et dispatch restent ouverts. Prochaine action : reproduire puis
fermer l’intégrité des ancres avant première date, avant le raccord mémoire multi-affaire.

## Jalon exécuté — intégrité métier avant toute date

`civil-integrity-red-v1` reproduit deux refus manquants : un vrai plan appliqué sans date,
aux heures altérées puis rechaîné, restait consultable HTTP 200 et pouvait recevoir sa première
date par le propriétaire. La correction extrait la formule déjà utilisée par les annotations
dans `cedule_tournees.verifier_empreintes_plan_applique` et la réutilise à l’index civil dès
l’application. L’index refuse aussi propositions/applications dupliquées et applications sans
proposition antérieure. Aucun solveur, date ou politique de capacité supplémentaire n’est créé.
Les annotations historiques réutilisent la même preuve au lieu d’en maintenir une copie.

Une `PreuvePlanInvalide` distingue cette corruption des arguments de saisie; les trois outils
calendrier la rendent sous le code existant REJ-REGISTRE-INVALIDE. La console présente une
indisponibilité 503, sans afficher de faux formulaire. Les autres validations calendaires,
les états, les conflits datés et les rôles restent chez leurs propriétaires.

`civil-integrity-v1` : 165 PASS, 5 rouges conservés. Deux concernaient la classification HTTP
400 au lieu de 503 après le premier correctif. Trois fixtures de volume remplaçaient le plan
par « plan-volume-fictif » et modifiaient les visites sans reconstruire leurs empreintes. Ces
fixtures ont été corrigées pour sceller leur import synthétique; aucun contrôle produit n’a
été affaibli pour elles. Elles qualifient les bornes 200/201 visites et 31/32 jours et la
troncature, pas une optimisation réelle de 200 chantiers ni leur faisabilité.

`civil-integrity-v2` **170 PASS, 0 FAIL/SKIP, 25,09 s** : premières dates, dates existantes,
annotations, couleurs, détail, outils SQL et météo datée réels. `civil-integrity-v3` ajoute
**3 PASS, 1,10 s** pour les duplications et l’ordre avant toute date; sources produit inchangées,
anciens tests préservés comme préfixe exact. Cohortes non additionnées. Ruff et vérificateur
297/173 passent; revue statique indépendante du contrôle partagé sans constat concret restant.
Source lecture seule pendant QA, données/homes/tmp privés, réseau interdit, 1 CPU/1 Gio/96 tâches;
chaque commande, pin, log, JUnit et reçu reste distinct, y compris les rouges historiques.

**PARTIAL** : intégrité métier préalable aux dates qualifiée et fail-closed. Le contexte M10
multi-affaire avant datation n’est toujours pas raccordé. La prochaine tranche doit résoudre
les inscriptions M4 sans inventer un devis sur un manuel et qualifier le budget/chargement
unique des paquets avant de modifier le formulaire civil et ses reçus. Fraîcheur météo,
capacité globale/trajets, dispatch, navigateur, PostgreSQL et mobile restent ouverts.

## Contrat du premier adaptateur privé, sans formulaire ni writer

API de lecture seule `memoire_plan_calendrier.lire(cnx, deps, session, plan_id)` : admin SQL
courant; sources M4 et M10 bornées avant décodage. Comparer le détail T0 au snapshot civil
validé, résoudre une inscription unique par visite, recouper l’état du plan et ses ancres.
Les visites tronquées refusent une consultation complète; un plan complet mais bloqué peut
rester consultable avec permis=false, sans nouvelle permission de mutation.

Renvoyer les liaisons séparément des contextes d’affaire. Origine M3 : couple lead/devis
accepté réel et intervention identique, référence canonique M10. Origine manuelle : devis
vérifié absent même si un devis est déclaré, contexte du lead seulement, aucune requête M3
inventée. Charger une seule fois le vrai paquet restrictif de chaque affaire distincte,
conserver ses omissions/signaux et vérifier ses têtes réellement consommées. Deux empreintes
stables : plan M4 et mémoire/liaisons sans l’heure volatile. Relire identité et têtes avant
retour. Quota global JSON 64 Kio : refus explicite, aucun sous-ensemble silencieux. La future
UI devra qualifier détail/pagination pour les plans qui excèdent cette borne; le présent
adaptateur n’est pas branché à la datation et ne bloque donc aucun parcours legacy existant.

Mesurer appels et durée dans les preuves QA pour un vrai plan mixte et la déduplication;
ne factoriser le propriétaire M10 que si un coût répété est effectivement démontré. Ce
premier raccord ne change ni politiques de signaux, ni dates, ni reçu d’idempotence.


## Jalon exécuté — contexte civil privé en lecture seule

`memoire_plan_calendrier` résout maintenant les inscriptions M4 et relit les vrais ports T0,
sans appeler M3 pour un manuel. Un vrai plan mixte de trois visites partage deux affaires :
un devis M3 accepté est lié canoniquement; un manuel de la même affaire garde son devis
simplement déclaré, sans le convertir en devis vérifié. Deux paquets M10 sont réellement
appelés pour ces trois visites, une fois par affaire; les temps sont enregistrés dans le JUnit.
Cette mesure ne démontre aucun gain de débit sans comparaison A/B.

La revue indépendante a révélé une projection M10 inadmissible pour un vrai lead M3 contenant
un caractère Unicode. Le rouge `memory-calendar-nonrepr-red-v1` a reproduit ce défaut : M3/M4
acceptaient le lead, M10 le mettait légitimement en quarantaine selon son contrat restrictif,
mais l'adaptateur tentait encore sa projection canonique. Il conserve désormais le vrai lien
M3/M4 et annonce NON_REPRESENTABLE sans référence/paquet substitué. Aucun élargissement M10.

Deux autres refus ont été prouvés par `memory-calendar-identity-red-v3` : une inscription
rechaînée dont le type de travaux ou l'urgence contredit l'état scellé du plan. Le lecteur
compare maintenant ces champs immuables via la taxonomie M4. Les statuts/affectations courants,
qui peuvent légitimement évoluer, restent évalués par le propriétaire civil. Le rouge v2 du
type était un mauvais oracle (ravalement réécrit à l'identique), corrigé en v3 avec assertion
sur la valeur initiale et remplacement réel; il ne constitue pas une preuve produit.

`memory-calendar-v8` : **48 PASS, 0 FAIL/SKIP, 19,51 s**, dont 12 nouveaux cas de l'adaptateur,
les ports M10 antérieurs, N3 et les dates existantes. Ruff ciblé et vérificateur 297/173 passent.
Sources en lecture seule pendant QA; limites et artefacts durables décrits ci-dessus. Les
v3/v4 ont refusé au lint, v5/v6 ont révélé des prérequis de fixture (payload legacy plat et
fenêtres client explicites), corrigés sans modifier les politiques produit. Tous les rouges,
les reçus et les populations recoupées sont conservés, jamais additionnés.

**PARTIAL** : ce port privé est qualifié sur SQLite avec refus de détail tronqué, quota global,
révocation et changement de source pendant lecture. Il n'est pas encore affiché avant la
confirmation civile. Le formulaire, sa preuve d'intention, son rollback après effet et ses
reçus legacy restent à raccorder; le volume réel maximal et sa pagination restent à qualifier.
Ni dispatch, ni capacité globale/trajets, ni fraîcheur météo, ni navigateur/PG/mobile ne sont
qualifiés par ce jalon. Prochaine action : UI mémoire par affaire avant datation, preuve CAS
liée au reçu et relecture mémoire après effet sous savepoint, sans nouvelle politique de signaux.
