# R30 — cohortes de temps sur observations préparées

La couche pure est **vérifiée localement le 2 octobre 2026** dans le périmètre
du [contrat des cohortes](../architecture/CALIBRATION-COHORTES-TEMPS.md).
Deux fichiers Python sont livrés : le module `calibration_cohortes.py` et ses
tests, tous fondés sur des observations fictives préparées. Il n'existe dans
ce lot ni raccord durable/API, ni admission authentifiée des données terrain,
ni barème actif, entraînement, gain mesuré ou appel LLM.

## Qualification ROOT et correctif numérique

La campagne `cohortes-pures-root-r2-2026-10-02`, du **09:15:49 au 09:15:49 UTC**,
passe **14 identités de test uniques**, zéro échec, erreur ou skip.
Le JUnit `cohortes-root-r2.xml` contient ces 14 cas; les deux campagnes auteur
r2 portent les mêmes scénarios et ne sont pas additionnées à ce compte ROOT.
Les 1 107 empreintes sélectionnées restent identiques avant/après la campagne;
cela n'étend pas sa qualification métier aux autres sources.

La campagne de qualité `pdf-natif-qualite-root-r1-2026-10-02`, du **09:17:03 au
09:17:05 UTC**, inclut ces deux fichiers dans ses contrôles AST/Ruff et sort 0.
Ses 1 107 empreintes sont également stables. Son périmètre plus large comprend
d'autres lots; R30 n'en revendique pas la qualification. Les docs présentes
ont seulement reçu une vérification de cohérence et de liens, sans nouvelle QA.

Le reçu historique `DECIMAL-CONTEXTE-ROOT-r1.json` conserve le défaut ROOT :
sur le même cas fictif, la précision ambiante 28 donnait une médiane train
de 105, contre 100 avec la précision 2, avec deux hashes de rapport différents.
La première campagne ROOT r1 passait ses 13 cas sans couvrir cette invariance.
Le correctif r2 fixe un contexte local Decimal 64, `ROUND_HALF_EVEN`, préserve
le contexte appelant et signale les divisions de taux non exactes. Le 14e cas
vérifie l'indépendance à des contextes appelants de précisions 2 et 3, arrondis
différents et piège `Inexact` actif. Il n'atteste aucune précision terrain.
Le diagnostic Ruff r2-01 (`I001`) et sa reprise r2-02 vide sont conservés,
ainsi que les préimages numériques initiales et tous les reçus r1.

## Portée livrée et suite

La fonction contrôle formes, attestations, sémantiques et unités déclarées,
identité `estimée = quantité × taux`, rejeux et conflits. Elle sépare par
chantier toutes les fins avant/à la coupure de tous les débuts après celle-ci;
elle exclut tout chantier traversant. Segmentation exacte et minima fixes
précèdent les statistiques robustes et une proposition toujours inactive.
Le rapport est déterministe à entrées égales sous son contexte numérique fixé.

La prochaine tranche doit raccorder une API publique de provenance au
[lecteur R27](../architecture/PROVENANCE-ESTIMATION-TEMPS.md), confirmer le sens
et la stabilité des mesures M4, établir les jointures réelles et les doublons
métier, puis évaluer un corpus réel autorisé avec protocole fixé avant holdout.
Une décision humaine distincte resterait nécessaire pour toute activation.
M3 global, apprentissage géospatial et calibration automatique ne sont pas
déclarés terminés. Les bibliothèques standard sont réutilisées pour cette
première couche; aucune dépendance ML n'est ajoutée.

## Garde des preuves

Les plans, recherches OSS, préimages, reçus auteur, diagnostic numérique et
JUnit ROOT sont dans
`/workspace/poursuite-opsys-2026-10-02-r1/calibration-suite`.
Les reçus/logs/snapshots ROOT sont dans
`/workspace/restructuration-opsys-2026-09-30/preuves`, préfixes
`cohortes-pures-root-r1-2026-10-02`, `cohortes-pures-root-r2-2026-10-02`
et `pdf-natif-qualite-root-r1-2026-10-02`.
La proposition d'archive R30 reste distincte de son exécution par ROOT;
elle doit conserver les reprises et les refus sans remplacer R19–R27.

Empreintes Python qualifiées r2 :

- Module : `76c07eb743e3a7468328bd15513966814626f133bb65bd90d548355c0dc63571`.
- Tests : `124008e136db9e271f01c6251d47e4e794f41491d7bf474d1c9e210afc6dfce4`.
- JUnit ROOT : `f08f6680787611edfbe4e55dc11cc39a0d29392b1011419a775f4573efe9499d`.
