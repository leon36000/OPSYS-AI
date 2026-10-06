# M5 — finalité du prix dans l'événement de rentabilité

Rapport technique UTC du 5 octobre 2026; soirée du 4 octobre America/Toronto.
Correctif local de la première tranche du [programme 24 h](../../programme/PROGRAMME-24H-2026-10-04.md).
Statut global M5 et OPSYS : **PARTIEL**. Ni push, CI distante ni déploiement qualifiés ici.

## Problème et comportement livré localement

M5 connaît le statut de sa facture, mais perdait `prix_definitif` en publiant sa rentabilité.
Une facture BROUILLON avec coût complet pouvait donc produire une charge `CALCULEE` sans
indiquer le caractère provisoire du prix. Cette charge est lue par M8 et mémorisée par M10.

Le producteur ajoute désormais le booléen déjà calculé : `false` pour BROUILLON ou facture
absente, `true` pour ENVOYEE/PAYEE. Le catalogue fermé accepte ce champ facultatif et refuse
chaîne, entier ou null. Les champs historiques restent requis. M8 conserve l'indication
lorsqu'elle est présente; M10 conserve déjà la charge complète sous confidentialité FINANCIAL.
Une ancienne charge sans indication demeure acceptée et **inconnue**, jamais déduite vraie
depuis `CALCULEE` ou un montant. Aucune réécriture des anciennes traces ni publication forcée.

`true` signifie finalité du prix selon le statut M5; ENVOYEE ne signifie pas paiement encaissé.
Le correctif ne modifie ni coût, revenu, marge, numérotation, `version_entrees`, séquence,
grand livre, permissions ou autonomie. Il n'active aucun apprentissage du prix. Les vues/mesures
historiques M8 gardent leurs calculs; l'exploitation explicite de cette finalité dans un rapport
de calibration et dans les interfaces reste la tranche suivante. Le statut interne CALCULEE
reste distinct de la finalité du prix et de la complétude de toutes les données d'entreprise.

## Fichiers

- `departments/m05-financecore/src/m5_financecore/cout_reel.py` : charge du producteur.
- `src/opsys/evenements/catalogue/m5.rentabilite_chantier.json` : champ optionnel strict.
- `departments/m08-analytics/src/m8_analytics/mesures_chantier.py` : conservation sans défaut inventé.
- Tests complets M5 événement, M8 événement et M10 mémorisation : cas nouveaux et historique.

La compatibilité concerne le **nouveau lecteur lisant l'historique**. Un ancien serveur portant
encore le catalogue fermé antérieur peut refuser une nouvelle charge. Un déploiement doit donc
mettre à jour les lecteurs/catalogues avant d'activer le producteur; aucune compatibilité de
déploiement progressif mixant les deux versions n'est revendiquée. Le déploiement n'a pas été fait.

Conception : [design](M5-FINALITE-EVENEMENT-DESIGN-2026-10-05.md).

## Vérification ROOT

| Campagne | Résultat et portée |
|---|---|
| r223 avant code | Deux cas de régression sélectionnés échouent sur `prix_definitif` absent, M5 et M8. Le reçu signale aussi une erreur du vérificateur JUnit prévu pour fichiers complets : cette exécution n'est pas une qualification. Log/JUnit conservés. |
| r224 après code | Ruff et manifests verts; 328 cas réussis, un cas PostgreSQL en échec `initdb: No space left on device`. Pas un vert global. |
| r225 reprise | **329/329**, neuf fichiers complets, aucun échec/erreur/saut, Ruff et manifests verts. Sources inchangées avant/après, OOM inchangé. |

La reprise emploie le vrai PostgreSQL éphémère du harnais existant, données dans tmpfs borné
256 MiB, conteneur plafonné 512 MiB. Le plugin QA externe ne modifie aucune assertion ni fichier
de test; il sélectionne explicitement `stockage_en_memoire=True` pour surmonter le disque plein.
Cela vérifie le bus PostgreSQL, pas la durabilité de ses données sur disque ou une restauration VPS.
Les autres cas du correctif financier utilisent SQLite ou les modules purs sur données fictives.

Les suites couvrent statuts BROUILLON/ENVOYEE/PAYEE, facture absente, changements de version,
rejeu, coût partiel, historique, booléen mal formé et conservation M8/M10. Le même lot rejoue
le trajet HTTP M7→M1→M2→M8; le Core/navigateur/téléphone physiques restent hors preuve.

La revue ROOT a corrigé avant promotion les tests du staging qui supposaient tous les champs
requis et un `pop` d'un champ absent. Les préimages et erreurs ont été conservées; le rapport
de l'ouvrier seul n'a pas été traité comme validation. La capsule de reprise comprend les
reçus, sorties, sources et rapports bruts; le plan local de publication porte les SHA définitifs.

## Suite

Relier cette indication à la lecture bornée M3/M4/M6/M5 du résultat chantier; exclure facture
brouillon, coût partiel et source incompatible des statistiques de marge finale. Mesurer
ensuite sur un corpus autorisé avant toute activation d'une politique de calibration.
