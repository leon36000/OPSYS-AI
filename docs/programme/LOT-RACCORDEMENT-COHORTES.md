# Raccordement des cohortes aux faits terrain — audit avant code

État : design à implémenter; aucun apprentissage actif. Le
[rapport pur R30](LOT-COHORTES-TEMPS.md) ne peut pas authentifier ses entrées.
La [provenance R27](LOT-PROVENANCE-ESTIMATION-TEMPS.md) fournit le lien exact
devis/estimation; il faut maintenant relire et qualifier les faits M4.

## Existant réutilisable et limites constatées

- M4 `outbox.calculer_duree_reelle` calcule du premier pointage d’arrivée au
  dernier départ, avec pauses déduites et déplacement exclu. Une durée en
  minutes n’est pas une durée-personne cumulée d’une équipe.
- Le WCT publié porte completion, intervention, lead, devis, durée et statut;
  il peut être `completed_pending_review`. Une revue ultérieure ne doit pas
  être confondue avec le statut originel figé dans le bus.
- Le WCT ne porte pas le premier horodatage d’arrivée. Déduire le début par
  `completion − durée` serait incorrect à cause des pauses et compromettrait
  la partition temporelle. La projection actuelle `lire_ecarts` ne fournit
  ni ce début, ni toutes les preuves nécessaires.
- `evenements.charge_publiee` relit une charge canonique par type et identité,
  dans la transaction courante. Cette fonction évite d’accepter une charge
  WCT envoyée par l’agent. Son existence ne remplace pas les contrôles M4
  de chaîne et de statut courant.
- M3 conserve ses registres et sait résoudre l’estimation par empreinte exacte.
  Les attestations `liaison_exacte` et `chaine_m3_valide` de R30 devront être
  produites par ce raccord serveur après contrôle, jamais reçues du modèle.

## Contrat minimal retenu

M4 doit exposer une projection publique en lecture seule d’un WCT demandé
par identité. Elle vérifie sa chaîne, la concordance du fait publié,
l’intervention et son statut courant, puis fournit arrivée/départ UTC, pauses,
durée recomputée et références de preuve. Les anciens faits incomplets ou
contradictoires sont refusés explicitement; aucune date n’est fabriquée.
Le consommateur M3 passe par cette projection et le bus, sans lire le registre
privé de M4.

Le raccord M3 résout dans une même lecture cohérente lead, devis et estimation
exacte, qualifie service/quantité/unité/version/taux/sens du temps, puis prépare
les observations de R30. Les WCT en revue, chaînes altérées, temps manquants,
unités non comparables et identités divergentes restent hors du jeu avec motifs.
Le rapport indique combien de faits sont refusés et pourquoi. Aucun ratio
n’est réinjecté dans un prix ou une estimation active.

## Vérification requise avant promotion

D’abord produire le rouge du raccord absent, puis des faits fictifs provenant
des véritables transitions et publications M4/M3. Vérifier liens exacts,
rejeu divergent, revue en attente puis résolue, pauses, chaîne altérée, début
manquant et refus des valeurs déclarées par un agent. Un chantier traversant
la coupure doit être entièrement exclu. Les observations d’un même chantier
ne peuvent apparaître dans train et holdout. Une candidate reste inactive
même quand les minima sont atteints.

La publication d’une projection bornée, son raccord durable et la vérification
indépendante précèdent toute UI d’activation. Des gains sur des chantiers réels,
la stabilité par service, la validation du métier, le versionnage et le rollback
restent nécessaires avant de modifier un barème.
