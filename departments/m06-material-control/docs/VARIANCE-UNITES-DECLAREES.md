# Variance : conserver l’unité réellement déclarée

Statut : correction locale vérifiée, qualification native complète encore ouverte.

## Défaut et comportement corrigé

Quand une consommation de 5 pi précédait l’arrivée du besoin canonique de 5 boîtes,
le registre perdait l’unité réelle. La comparaison pouvait annoncer AUCUN_ECART et
publier une variance évaluée. Le garde de déclaration protégeait seulement les
besoins déjà connus.

Les nouveaux mouvements CONSOMMATION, RETOUR, PERTE et BRIS gardent maintenant
l’unité déclarée dans leur empreinte. Aucun ancien maillon n’est réécrit. Une unité
absente, mixte ou incompatible rend la comparaison INDETERMINE. Le producteur émet
alors `unites_indeterminees`, avec `signal_critique=null` et `lignes=null` : ce résultat
ne peut déclencher une vérification automatique M4 ni alimenter un ratio M3/M8.
Les lecteurs stricts des pertes, preuves et réapprovisionnement acceptent le champ
additif ; les lectures de pertes exposent l’unité connue sans la deviner.

## Contrats et limites

Le catalogue canonique `m6.variance_chantier` décrit le nouveau statut. Il est ajouté
après les quatre slots historiques des lectures appareil, sans prétendre que leur
ordre est chronologique. Les consommateurs M3/M4/M5/M8/M10 conservent leur traitement
des résultats non évalués. Aucun coût, conversion d’unité, droit appareil ou paiement
n’est ajouté par ce patch.

Les événements historiques déjà évalués ne sont pas réécrits ni rejoués. Leur revue
et une éventuelle correction versionnée restent à concevoir. Le stock historique
sans unité ne devient pas une quantité dimensionnellement validée grâce à ce patch.
Un agrégat brut INDETERMINE ne doit pas être réutilisé comme mesure physique.

## Vérifications

Les tests permanents couvrent l’arrivée tardive du besoin (unités compatibles et
incompatibles), les unités historiques absentes ou mixtes, l’intégrité des empreintes,
le rejet atomique d’une unité invalide et l’idempotence du WCT. Les tests des
consommateurs vérifient l’absence de finalisation ou d’apprentissage sur ce statut.

Preuves du chantier : `work/chantier-opsys-20261010/m6-late-unit-20261027-r1` dans
l’espace de qualification externe à Source. Le rouge de composition v5 est conservé.
La composition verte v6 passe ; la suite M6 v8 passe (1491 cas) ; les vérifications
ciblées aval et projections v10 passent (271 cas, population recoupée, non additive).
Le lint v12 et le vérificateur des manifestes/événements passent. Ces preuves utilisent
SQLite durable et des données fictives sous limites systemd/Landlock, réseau Internet
interdit, Source en lecture seule et homes temporaires privés avant imports.

Cela ne constitue pas une preuve E2E native authentifiée Gateway/appareil, ni une
qualification complète de M6. Prochaine étape : revue du diff puis intégration normale
sur la branche autorisée ; conserver les gates des essais natifs et des données réelles.
