# Design — Finalité de la marge M5

## Constat
M5 calcule `prix_definitif` dans sa lecture interne à partir du statut de facture:
`ENVOYEE` et `PAYEE` donnent vrai; `BROUILLON`, facture absente ou autre statut donnent faux.
La charge publiée `m5.rentabilite_chantier` oublie cette distinction, alors que M8 transforme la charge en fait analytique et M10 la mémorise.

## Changement proposé
Ajouter `prix_definitif`, booléen facultatif, à la charge et au schéma fermé du catalogue. M5 l'émet à chaque nouvelle trace depuis le booléen déjà calculé. Le champ reste facultatif dans le schéma: une charge historique sans ce champ est acceptée et signifie « finalité inconnue ». Aucun lecteur ne déduit `true` de l'absence, du verdict `CALCULEE`, d'un montant ou d'une marge.

M8 conserve la valeur lorsqu'elle est présente et omet le champ lorsque la charge historique ne le porte pas. M10 stocke la charge complète telle quelle; son comportement actuel préserve déjà le nouveau champ sans changement de code. Les consommateurs peuvent alors distinguer un prix provisoire explicitement faux d'une finalité inconnue.

## Invariants et limites
Aucun calcul de coût, de revenu, de marge, de version ou de séquence ne change. `CALCULEE` continue de signifier coût complet et facture connue selon le contrat historique; le nouveau champ précise séparément si le prix est définitif. Aucun statut n'est inféré à partir de montants. Le rejeu reste idempotent et chaque version d'entrée conserve sa publication. Aucun changement au grand livre, à l'autonomie ou à la politique d'apprentissage; pas de migration et aucune réécriture de l'historique.

## Vérifications ciblées
Couvrir les trois statuts `BROUILLON`, `ENVOYEE`, `PAYEE`, l'absence de facture, un booléen mal formé, l'acceptation d'une charge historique sans champ, la préservation par M8/M10 et la valeur transportée lors du rejeu et des versions d'entrée distinctes. Les tests d'intégration du dépôt restent à lancer par ROOT.
