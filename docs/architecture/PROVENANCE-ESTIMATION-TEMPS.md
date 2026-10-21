# Estimation et durée terrain — origine exacte

R27, 2 octobre 2026 : cette tranche prépare une comparaison fiable des durées.
Elle n'ajuste ni les prix, ni les barèmes, ni une estimation active.

## Origine du devis

`m3_estimer_projet` conserve une trace de temps et l'empreinte de son maillon.
Le brouillon peut recevoir `estimation_source_hash`, facultatif pour les anciens
parcours. Cette référence doit être un SHA-256 hexadécimal minuscule exact.
Avant création, M3 valide la chaîne durable et recherche un seul maillon de cette
empreinte, portant les mêmes `devis_id` et `lead_id`. Une référence fournie mais
invalide bloque la création avant écriture. Aucune estimation récente portant
le même identifiant ne remplace cette référence.

L'empreinte entre dans le contenu immuable et l'idempotence du devis. Rejouer un
ancien brouillon sans référence reste compatible; ajouter ou changer la référence
constitue un conflit. Les maillons historiques ne sont pas réécrits. La projection
employé et les faits M10 n'exposent pas cette empreinte.

## Sens de la mesure

Le barème doit déclarer exactement `duree_ecoulee_intervention` : minutes écoulées
d'intervention par unité, pauses et déplacements exclus. Une déclaration absente
ou différente produit `non_qualifiee`. La trace schéma 2 conserve service,
quantité, unité, version, taux, durée et empreinte du barème. Cette déclaration
ne prouve pas la validité terrain du taux.

À l'acceptation, la référence exacte est relue dans la transaction existante.
La durée est transmise à `m3.devis_accepte` seulement si la trace schéma 2 possède
la sémantique attendue et une durée positive concordant avec la charge d'origine.
Un devis valide peut être accepté sans durée comparable. Aucun zéro, estimation
legacy ou dernier maillon ne sert de remplacement.

La comparaison du WCT applique la même résolution et vérifie aussi son lead
contre celui du devis. Un chantier associé manuellement à un devis d'un autre
lead conserve son temps réel, mais n'obtient ni durée estimée ni écart calculé.
L'absence de données comparables produit un motif explicite.

## Portée de la preuve

Le producteur normal calcule la durée et sa trace ensemble. Le lecteur vérifie
la référence, la chaîne, la sémantique et la concordance; il ne refait pas le
calcul quantité × taux. Une réécriture complète de chaîne par un acteur privilégié
n'est pas une authentification de l'origine. Aucun corpus client, taux recalibré,
gain de précision, promotion automatique ou benchmark terrain n'est qualifié.

Sources : `trace_calibration_temps.py`, `outils.py`, `devis_durable.py`,
`estime_vs_reel.py` du département M03 et le catalogue `m3.devis_accepte.json`.
La future calibration doit ajouter unités confirmées, cohortes par chantier,
séparation temporelle et évaluation indépendante. [Résultats R27](../programme/LOT-PROVENANCE-ESTIMATION-TEMPS.md).
