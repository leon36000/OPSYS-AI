# Briques transversales — M2, M3, M4, M6, M8 et M9

Recherche documentaire du 30 septembre 2026 ; aucune dépendance ajoutée ni code candidat exécuté.
Les six départements restent au périmètre de la [définition](../../produit/DEFINITION-PRODUIT.md).
Les ingrédients ci-dessous apportent des capacités à qualifier, pas un remplacement de leur cœur.

| Source fixée | Licence primaire lue | Utilité OPSYS | Adaptation / preuve d'adoption |
|---|---|---|---|
| [InvenTree](https://github.com/inventree/InvenTree/blob/9478c25a70696feddafbff139e6f41d3b0abe78d/LICENSE), commit du 29 septembre | MIT | M6 : stock, emplacements, achats/réception, allocation et history | Reprendre un patron ou service API si utile ; Django ajoute coût et seconde DB. Préserver stock OPSYS canon. Prouver réservation→réception→consommation→retour/rejeu avant choix |
| [OR-Tools](https://github.com/google/or-tools/blob/100f66e6242ab8bf8d32feb8f3bf086db66ae2b5/LICENSE), 17 septembre | Apache-2 | M4 : contraintes cédule/capacité/routage ; M3/M5 scénarios | Bibliothèque, pas API propriétaire de planning. Fournir disponibilité/compétences/durée/trajets ; cas impossible et changements météo rendent conflit motivé, pas date inventée |
| [NetworkX](https://github.com/networkx/networkx/blob/92f497e2eb8192d1ce9205595f512294e4a9b696/LICENSE.txt), 29 septembre | BSD-3 (API GitHub NOASSERTION) | M10/M9 : relations, dépendances et analyse d'impact | Calcul en mémoire à partir de relations autorisées ; pas nouveau graph store. Prouver parcours module→fichiers→tests et isolement de domaines |
| [DuckDB](https://github.com/duckdb/duckdb/blob/028c980193d8115cff19d86e2e73e716376bf03f/LICENSE), 30 septembre | MIT | M8 : agrégations/analyse exports ; M5/M9 scénarios | Analyse locale, données sourcées et snapshot ; ne jamais devenir vérité facture/stock. Benchmark de volume + déterminisme montants et filtre autorisé |
| [SimPy, GitLab](https://gitlab.com/team-simpy/simpy/-/blob/f43816490c6f76f336ad6e457d3cab9f386894af/LICENSE.rst), 23 mai | MIT | M4/M6/M9 : simulation discrète équipes, matériel et scénarios ; M5 capacité/revenus | Bibliothèque sans service. Scénarios distinguent hypothèses/distributions des faits ; graine et paramètres versionnés, calibration et incertitude documentées |
| [Graphviz, GitLab](https://gitlab.com/graphviz/graphviz/-/blob/73780af60a7d334f3d67b92afa8b7ab5980696fe/LICENSE), 29 septembre | EPL-2 | M10 : vues graphe dépendances et lineage exportables | Option de rendu, pas graphe mémoire canon. Licence hors liste permissive standard : qualifier obligations du paquet, pas fusionner sa source dans core. Pas nécessaire à l'installation |

Métadonnées : [index](preuves-transversales/index.json). Les APIs GitLab consultées n'exposent pas
le champ `archived` pour ces projets publics ; sa valeur reste inconnue, pas convertie en faux.
Les licences ont été lues dans les fichiers au commit et ne couvrent pas automatiquement toutes
les dépendances, plugins ou modèles. Les releases stables retenues pour un essai devront être
compatibles avec Python/OS/CPU du produit ; un HEAD récent n'est pas nécessairement un tag stable.

Pour M2, garder le pipeline et les dossiers actuels. Une suite ERP/CRM ajouterait migrations et
deuxième source d'autorité ; examiner ses composants seulement après cartographie d'un manque précis.
Pour M3, les mesures/incertitudes et tarifs validés restent déterministes ; ces briques ne remplacent
ni les photos autorisées ni les données terrain fiables. M8 lit M5 pour les métriques financières.
M9 peut exploiter des simulations sans présenter leur distribution comme une prédiction certaine.

Prochaine preuve utile : parcours M3→M4→M6→coûts réels M5, puis comparaison d'un planning contraint
et d'un scénario saisonnier, avec l'existant comme référence. Aucun gain en heures ou dollars n'est
annoncé avant l'essai ; aucune stack supplémentaire installée sur la seule lecture de ces dépôts.
