# Calibration des durées : audit de préparation

## Livraison R22 : conserver les entrées du calcul

La trace versionnée [`trace_calibration_temps.py`](../../departments/m03-estimation/src/m3_estimation/trace_calibration_temps.py) conserve désormais service, quantité Decimal exacte, unité, version déclarée du barème, taux utilisé et empreinte typée du barème. Les attributs absents sont explicitement signalés; une estimation bloquée ou sans durée ne produit pas de trace utilisable. Les chaînes antérieures et le contrat gelé `EstimationV1` ne sont pas réécrits. La provenance reste `bareme_fourni` et la sémantique `non_qualifiee`.

Les sept cas spécifiques et les suites M3 concernées passent dans les 467 cas Python de [R22](../research/R22-2026-10-02/README.md). Ce prérequis de collecte est livré; les étapes de cohorte, partition temporelle, candidat, activation et mesure de gain ci-dessous restent à construire. L’absence de corpus client autorisé empêche de revendiquer un gain empirique, pas de développer ces contrôles.

La demande Nathan prévoit que les temps terrain améliorent les futures estimations.
Ce mécanisme reste à construire. La comparaison descriptive existe dans M3; son existence ne
prouve pas une mise à jour des paramètres ni un gain de précision.

## Sources existantes et frontière sémantique

[`estimation.py`](../../departments/m03-estimation/src/m3_estimation/estimation.py) calcule la durée
comme quantité × `duree_minutes_par_unite` du poste du barème fourni. La charge M3 conserve la
version du barème, la durée, le devis et sa chaîne. Avant R22, elle ne conservait pas tous les
attributs nécessaires à une cohorte : type de travaux, quantité, unité et sémantique de temps
ne doivent pas être reconstruits par un modèle après coup.

[`outbox.py`](../../departments/m04-field-ops/src/m4_field_ops/outbox.py) calcule une durée écoulée
sur site, entre premier début et dernier départ, pauses validées déduites; le déplacement est
séparé. Le contrat WCT porte le technicien du dernier départ, sans effectif complet ni
minutes-personne. M3 dit « minutes de main-d'œuvre par unité », sans choisir entre durée écoulée
et minutes-personne : les deux métriques ne sont pas prouvées identiques. Il ne faut pas affirmer
qu'elles sont nécessairement incompatibles non plus.

[`estime_vs_reel.py`](../../departments/m03-estimation/src/m3_estimation/estime_vs_reel.py) relie
par `devis_id`, puis `wct_id` pour les matériaux, et calcule une variance. M6 donne des quantités
déclarées avec contrôle d'unité; M5 valorise le temps et les matériaux depuis des taux/prix
configurés. Ces montants valorisés ne sont pas des factures terrain indépendantes.

## Séquence de construction — trace R22 livrée, autres étapes ouvertes

1. Qualifier la cible du barème : durée écoulée d'intervention ou minutes-personne, unité de
   quantité et conditions d'équipe. Pour les minutes-personne, faire évoluer explicitement le
   contrat de pointage/effectif M4 et le mobile; aucun facteur d'équipe ne peut être inventé.
2. Conserver dans une trace M3 versionnée les attributs exacts utilisés par l'estimation :
   service/type, quantité, unité, version/source du barème, taux de temps, sémantique et conditions.
   Ne pas modifier en place le contrat `EstimationV1` gelé. Une trace ancienne sans ces faits
   reste insuffisante pour ce calcul.
3. Construire une cohorte depuis les registres canoniques validés, avec jointures exactes,
   exclusions explicites, contrôle des unités/périmètres et snapshot vérifiable. Autoriser une vue
   interne agrégée sans noms de clients, techniciens, prix ou taux financiers.
4. Séparer les périodes `[début, fin[` par date de fin de chantier; même devis/intervention dans
   une seule partition. Les données futures réservées à l'évaluation ne servent jamais à ajuster
   le candidat. Mesurer erreur absolue/biais par service et unité, couverture et refus.
5. Produire une suggestion versionnée sourcée; activation/rollback auditables séparés du calcul.
   Une durée proposée n'est pas une précision démontrée. Sans corpus réel autorisé, les tests
   synthétiques qualifient les contrôles, pas les gains métier.

L'outil T0 de préparation proposé dans l'audit ne doit pas devenir une façade qui retourne
systématiquement « non préparé ». Les traces et contrats nécessaires sont le premier travail
codable, puis la préparation pourra être raccordée au moteur M3 existant.

## Portée de l'audit

Lecture seule ciblée M3/M4/M6/M5; aucun test frais, aucun chiffre appris, aucune mutation de
barème. Aucun jeu client réel n'a été identifié dans le dépôt inspecté; cela n'empêche pas de
construire le mécanisme et n'autorise pas à revendiquer un gain empirique. La présence de la
comparaison estimé/réel reste acquise. Les rapports préparatoires conservent aussi la correction
sur la sémantique ambiguë de M3; leur conclusion initiale plus stricte ne prévaut pas sur ce point.
