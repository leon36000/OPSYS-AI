# Réapprovisionnement courant — lecture appareil M6

`m6_lire_reapprovisionnement_appareil(decalage, limite)` est T0/N0, exclusivement
pour une identité DEVICE active et admin courante, revérifiée avant la configuration,
les registres et le bus. Entrées fermées, requises : entier strict `decalage` de 0 à
10000 et `limite` de 1 à 8. Aucun seuil, auteur, rôle ou historique n'est un argument.

Le corpus est limité aux articles déjà constatés dans `besoins_commande`. Dernier
constat par rang durable, puis ordre strict des derniers rangs décroissants ; aucune
chronologie n'est inférée de la date. La déclaration peut précéder la livraison du
WCT à M6 : absence de reçu M6 légitime ; un reçu existant lié doit être intégralement
vérifiable. Les vieux reçus étrangers ne bloquent pas le corpus. Leur copie intégrale
reste comptée et empreintée ; aucun reçu lié invalide n'est omis.

Chaque dernier constat est rapproché de la publication M4 par identifiant réel,
type, producteur, catalogue et date, et d'un mouvement de déclaration du même
WCT/article/chantier. `constat_id` est vérifié par recomposition interne sans être
projeté. Le registre des constats n'est pas hash-chaîné : `reference.rang` est natif,
`reference.empreinte_snapshot` est calculée sur la copie courante, jamais présentée
comme une empreinte historique conservée.

La façade réutilise les règles existantes `stock.deriver_disponibilite`,
`reservations.reserve_par_article`, `emplacements.hors_main_par_article`,
`reapprovisionnement.lire_parametres` et `evaluer`. Les cinq chiffres sont le stock
théorique tous lieux, hors main, en main, réservé et disponible. Le stock physique
et l'homogénéité d'unité ne sont pas connus : `unite` reste null, l'unité du dernier
constat est distincte. La date du dernier constat n'est pas la date du calcul courant.
Aucun coût, responsable, emplacement individuel, photo ou payload brut n'est projeté.

Les quatre états existants sont exposés : `stock_bas`, `stock_suffisant`,
`seuil_absent`, `configuration_invalide`. `stock_negatif` est exactement `en_main < 0`,
même sans configuration. Les seuil/cible configurés restent visibles pour un stock
suffisant. La proposition de quantité ne vient que du moteur pour le stock bas et
reste null si l'en main est négatif. Le disponible négatif est conservé ; rien n'est
ramené à zéro. Les nombres sont des textes décimaux canoniques exacts. Un contexte
Decimal dimensionné aux sources piège arrondi, inexactitude et overflow ; les moteurs
et writers sont inchangés. Un grand entier n'est pas refusé du seul fait de dépasser
MAX_SAFE_INTEGER lorsque sa projection est un texte.

Le fichier du manifeste est copié une fois et empreinté ; la configuration lisible
mais malformée donne `configuration_invalide` et un code canonique sans texte brut.
Un fichier non copiable refuse nominalement. Un bloc absent donne `seuil_absent`.
La source publique nomme le chemin logique fixe du manifeste, le bloc et ce SHA ;
les fixtures utilisent un remplacement privé explicitement fictif.

La sortie DIRECTE entière est bornée à 5400 points de code JSON Unicode conservés,
avec `taille_caracteres` mesuré au point fixe. La page peut se réduire ; son `suivant`
permet de lire les articles restants. Si un seul article ou le noyau fixe ne tient
pas, refus nommé sans détail partiel. Les six copies combinées sont bornées à 10000
lignes après copie : quatre registres, reçus M6 et publications ciblées. Cette borne
n'est pas une limite initiale d'allocation. Sources de snapshot explicitement distinctes
des têtes de chaînes ; les chaînes natives du principal et des transferts sont validées.

Aucune commande, réception, modification de seuil, réconciliation, publication,
constat, mouvement, stock, cache ou artefact n'est écrit par cette lecture. Les
guards du socle refusent aussi le dépassement de sa limite effective avant repli.
