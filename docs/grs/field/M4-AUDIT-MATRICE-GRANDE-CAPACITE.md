# M4 — audit de la capacité globale des matrices

## Objectif et constat prouvé

Le vrai scénario de200 inscriptions a été refusé avant toute proposition :202 points avec
les deux dépôts, limite globale100. Cette limite est copiée du transport OSRM alors que le
palier haversine est un calcul local sans HTTP. Les98 visites à deux dépôts et la pagination
civile sont qualifiées; ni plan200 ni routage de production200 ne l'étaient.

Réutilisation : `distances.py` (calcul entier, tri, empreinte, validation, repli global),
`distances_osrm.py` (sidecar local optionnel, sans redirection/proxy), PyVRP0.14.0 déjà épinglé,
`cedule_tournees` et les fixtures/outils réels. Ne pas reconstruire le solveur ni l'inventaire.
Aucune nouvelle bibliothèque ni dépendance de produit.

## Recherche et frontière du fournisseur

Le code primaire OSRMv26.4.0 contrôle sources×destinations <= max_table_size², pas simplement
le nombre de positions : [table.cpp](https://raw.githubusercontent.com/Project-OSRM/osrm-backend/v26.4.0/src/engine/plugins/table.cpp).
Le [contrat Table](https://project-osrm.org/docs/v5.24.0/api/#table-service) autorise des indices
sources/destinations locaux et des cellules null pour absence de route. Profil réel lié au
prétraitement Lua; data_version optionnel est un horodatage OSM, pas une preuve d'immutabilité
des poids routiers entre appels. Ne jamais activer fallback_speed ni remplir une cellule null.

Recherche GitHub/GitLab déléguée, sans adoption de code : OSRM officiel suffit pour le contrat;
[pattern de blocs GitHub](https://raw.githubusercontent.com/geospatialrouting/batch-route-optimizer/main/src/batch_route_optimizer/matrix.py)
repéré, mais son commentaire de limite et sa provenance/cache ne sont pas notre contrat;
[OS-Walk-EU GitLab](https://gitlab.com/ils-research/os-walk-eu) repéré sans implémentation accessible
suffisamment vérifiée. Aucune licence ni disponibilité non vérifiée n'est présentée comme acquise.

Le découpage conservateur50×50 avec au plus100 positions par requête demanderait25 requêtes
pour202 points et36 pour256, et non quatre. Le délai actuel est par opération socket, pas une
échéance globale; la version/répétition des points entre blocs ne suffit pas à garantir un
graphe immuable. Ce nouveau transport doit donc être qualifié séparément avec borne cumulée,
échéance, asymétrie, diagonales globales, null, réponse tardive et cohérence des snapshots.

## Patch minimal décidé avant implémentation

Séparer explicitement capacité **globale256 points** et capacité **transport OSRM100 positions**.
256 borne deux tables carrées à131072 cellules entières (65536 chacune), compatible avec200
chantiers plus dépôts sans toucher au contrat civil200 visites. Mesurer temps/RSS sous QA
bornée, tester la frontière256/257 et les vrais202 points. Pas de relèvement illimité.

Conserver exactement algorithme, arrondis, schéma/version et empreintes pour les entrées
historiques; le validateur de matrice finale doit accepter la même nouvelle borne globale.
OSRM garde son chemin actuel <=100. Au-delà, refuser **avant HTTP** avec un verdict fournisseur
explicite; `obtenir_matrice` produit alors un repli global haversine marqué, jamais une route
réelle prétendue ni une matrice mêlant fournisseurs/approximations. Aucun nouveau réseau,
aucun sidecar démarré, aucune requête externe. Le batch routier reste **PARTIAL**.

## Données, APIs, workflows et permissions

Outils existants `m4_proposer_cedule`/`m4_appliquer_cedule`, puis GET/POST civil privé. Même
admin actif, approbation et journal des propriétaires; ni permission ni route supplémentaire.
Coordonnées confirmées et durées/quarts/fenêtres explicites du scénario fictif uniquement.
Le champ mode_bride reste affiché; les dates internes ne valent ni disponibilité globale,
ni confirmation client, ni envoi d'équipe. M10/CAS/reçus et quotas restent inchangés.

## Tests, risques et statut

Avant patch : test rouge202 points globaux et garde transport100 distincte. Ensuite :
matrice256 complète/empreinte validée,257 refusé avant fournisseur, transport202 sans requête,
repli global marqué, petit transport inchangé via seam de réponse (pas sidecar réel), bases
distances/tournées et vrai200→application→contexte/cas→dates avec PyVRP sous1CPU/1Gio/96tâches,
réseau interdit, homes/tmp privés et Source readonly pendant QA. Les erreurs de prérequis
ne deviennent pas des bugs produit; toutes les preuves rouges/SKIP sont conservées.

**PARTIAL — candidat à qualifier.** Aucun gate Nathan nouveau pour cette préparation privée;
ni production, donnée réelle, fournisseur/paiement, droits, achat, fusion ou déploiement.
Après preuve de capacité locale200, prochaine tranche : transport routier par blocs et son
contrat d'immuabilité/budgets. Pas de revendication OR-Tools production, trafic, mobile,
PostgreSQL ou navigateur sur une preuve PyVRP/haversine locale.


## Jalon exécuté — capacité locale200 et transport conservé

`matrix-capacity-red-v2` reproduit deux exigences absentes :202 points refusés globalement,
et aucune séparation avec la capacité du transport. Le premier rougev1 s'était arrêté au
lint (import inutilisé), sans exécuter le produit. Le patch porte `distances.MAX_POINTS` à256
pour calcul/validation finale, garde `MAX_POINTS_REQUETE=100` dans OSRM et refuse au-delà
avant URL/HTTP. `obtenir_matrice` conserve son repli global marqué. Aucun batch, délai,
rattachement, proxy, redirection, cache ou appel réseau supplémentaire n'a été ajouté.

`matrix-capacity-v1` : **353 PASS, 0 FAIL/SKIP, 69,49 s**, avec bases distances/tournées,
frontière256/257,100 positions via seam de réponse (sans sidecar réel),202 sans HTTP et repli
sans mélange, contexte/pagination/reçus/cas précédents et vrai200. Ruff et vérificateur297/173
passent. La matrice256 produit131072 cellules entières en0,253 s; sa preuve est validée.

Le scénario200 produit et applique réellement le plan PyVRP0.14.0 de202 points avec toutes
les visites retenues. Préparation5,369 s; premières/dernières pages et HTTP3,720 s; réponses
JSON46272/42684 octets, HTML34631 octets. Il confirme ensuite une vraie première date puis
rejoue son reçu sans effet. Ce n'est plus un import synthétique de plan ni un refus crédité
comme capacité. Le refus historique de200 sous l'ancienne borne reste dans ses preuves.

Qualification complémentaire `matrix-capacity-nav200-v2` : **2 PASS, 0 FAIL/SKIP, 91,27 s**,
dont frontière256 recoupée et extension de la navigation réelle200. Le produit est inchangé
par rapport aux353 cas; la variante64 du test est conservée par comparaison AST après retrait
des seuls paramètres/mesures. Aucun cumul. Les67 pages parcourent200 visites sans perte ni
doublon, preuve globale identique à la formule historique, confirmation depuis dernière page
et rejeu sans effet. Le plus grand JSON vaut46275 octets. L'essai navv1 avait seulement refusé
une signature de test trop longue au lint. Le premier normaliseur AST oubliait le tuple des
mesures ajouté : préparation corrigée sans import ni réémission produit, incident conservé.

La navigation complète prend80,492 s et13400 vrais appels M10, soit200 par page : c'est une
preuve de disponibilité sous quota, **pas** un gain de débit. Cette mesure justifie un prochain
travail ciblé sur snapshots/lectures groupées M10. Le groupe QA atteint160591872 octets de
mémoire comptabilisée; le RSS maximal des enfants est174460928 octets (mesures distinctes).
Limites effectives1CPU/1Gio/swap0/96tâches; homes/tmp/caches privés avant imports, Source readonly,
sockets interdits; roues privées existantes épinglées hors ligne. Aucun processus externe ni
fournisseur réel n'a été lancé. Toutes commandes, sources, JUnit, logs et reçus sont distincts.

**PARTIAL — capacité locale200 qualifiée, transport routier large non qualifié.** Données et
services fictifs de5minutes, quatre jours explicites, haversine_detour en mode bridé. Les routes
réelles, la fraîcheur météo, OR-Tools production, dispatch global, navigateur, PostgreSQL et
mobile restent ouverts. Les matrices OSRM>100 sont refusées avant réseau avec repli annoncé.
Prochaines capacités : mutualisation mesurée des snapshots M10 par préparation, puis batch
OSRM avec budget cumulatif/échéance et preuve d'immuabilité du graphe. Pas de fusion/déploiement.
