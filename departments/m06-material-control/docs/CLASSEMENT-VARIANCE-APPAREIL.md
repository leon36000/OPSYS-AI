# Classement humain de la variance — T4.27-b

Trois outils DEVICE admin : `m6_lister_variances_classables_wct_appareil` et
`m6_lire_historique_classement_variance_appareil` sont T0/N0 ;
`m6_classer_cause_variance_appareil` est T1/N3. Le classement est une annotation
interne révisable : aucun stock, coût, statut M4, levée d'alerte ou publication M10
n'est changé. Le code ne déduit ni cause ni faute d'une personne.

La personne et le rôle admin sont confirmés en SQL à chaque admission ; agent et
console sont refusés. Les arguments ne fournissent aucun auteur/rôle faisant
foi. La portée contexte de la mutation est `affaire`, cible
`("selection", "wct_id")`, identité `wct` ; elle ne publie pas une mémoire.

## Source et sélection

La liste reçoit `{wct_id,decalage,limite}`. Source terminale obligatoire : vraie
publication `m6.variance_chantier` produite par M6, ID
`m6-variance-<wct_id>-evaluee`, catalogue et liens M4/WCT/chantier revérifiés.
Les lignes classables sont critiques dans la publication OU réellement liées à
un PERTE/BRIS du même WCT, matériau et chantier. La couverture annonce les autres
écarts hors périmètre, sans recalcul du seuil ou de l'écart.

`selection` contient `{wct_id,reference_variance,position_ligne,materiau_id}`.
`reference_variance` contient `{type,evenement_id,empreinte_charge}` ; son
empreinte est `encodage.empreinte(charge validée entière)`, pas un hash natif du
bus. La position est celle du tableau publié, jamais l'offset de page ni la
position du formulaire ou de la photo.

La liste rend le couple `{accepte:true,resultat:{wct,source_variance,lignes,
pagination,couverture}}`. Chaque ligne contient `selection`, les six champs
natifs `source_ligne`, `pieces_disponibles_a_selectionner`, et
`classement_courant` nullable. Les pièces sont des références déclarées ; la
liste ne promet pas la disponibilité actuelle des pixels ni l'authenticité de
la scène. Les anciennes preuves absentes restent nulles et sans photo.

## Écriture et replay

La mutation reçoit exactement `{selection,cause,motif,classement_attendu,
references_pieces}`. Les six causes sont celles de `contrats.CAUSES_VARIANCE_CHANTIER`.
Motif humain non blanc ≤500 points de code ; 0..8 pièces uniques, références
réelles de `principal` et éventuellement `preuves_pertes_bris`, positions photo
0..2 effectivement déclarées. Aucun hash CAS ou URL libre.

`classement_attendu` est null au premier ajout, puis la référence de la dernière
révision de CET objet. Cette précondition ne vaut que pour une écriture fraîche.
Le rang global protège séparément l'append de la chaîne `classements_variance`.
Les anciennes révisions restent intactes. Une autre ligne ajoutée n'invalide pas
la précondition métier.

L'ACK métier est `{accepte:true,resultat:<classement>,registre:{taille,hash_tete}}`.
Le classement contient `reference`, `selection`, `cause`, `motif`,
`reference_precedente`, `auteur:{personne,role,source}`, `appareil_id`, `classe_le`,
`horodatage_appareil_declare`, `references_pieces`. Auteur et réception viennent
du serveur ; l'heure appareil est déclarative, jamais la date du dommage.
Cap ajoute l'enveloppe `ok/resultat` et `rejoue`.

La seam `autoriser_classement_variance_appareil(arguments,nom=...)` vérifie
l'autorité/source avant claim ou restitution. La seam
`verifier_rejeu_classement_variance_appareil(arguments,reponse)` vérifie le propre
maillon de l'ACK persisté, même après une correction suivante ; aucun dernier
rang historique, nouvelle écriture ou lecture CAS n'est exigé. Le replay
s'applique à la même clé/appareil/outil/payload ; les conflits restent nommés.
Un refus courant de rôle/source/quota peut masquer un succès ancien : il ne
prouve pas l'absence d'effet, et l'intention conserve son UUID/payload.

## Bornes et historique

L'historique reçoit `{selection,decalage,limite}` et rend le couple de
`{selection,source_variance,historique,pagination,couverture}`. Ordre des
révisions par index croissant. Pages courantes, pas de snapshot figé.
`decalage` est un entier strict 0..10000, `limite` 1..8 ; aucune valeur booléenne.
Pagination : `decalage,limite,total,affichees,reste,decalage_suivant,borne_atteinte`.
La borne caractères peut réduire le nombre rendu ; rien n'est coupé dans une
ligne. Une première ligne ou un noyau trop grand donne un refus fermé.

Quota source agrégé 10000 après copies (inclut lignes publiées, mouvements,
preuves, classements et admission) ; aucune garantie avant allocation.
Enveloppe JSON entière ≤min(5400,quota Cap), mesure Python en points de code
`ensure_ascii=False`, distincte des octets UTF-8. Préflight avant append et
postflight du vrai ACK dans le savepoint ; refus contrôlé traduit après rollback
local, panne technique/concurrence remontée pour rollback extérieur du claim.
N3 trace seulement un succès accepté ; aucune sortie ARTEFACT ou ACK partiel.

Les tests du département et captures SQL fictives qualifient le producteur et
ses invariants. La qualification Cap/idempotence et la Gateway DEVICE sont
séparées, de même que téléphone/ExpoSQLite/Hermes. Les pièces actuelles ne
certifient pas leur présence au moment du calcul terminal ; ni M4 N4 ni M10 ne
sont automatiquement raccordés.
