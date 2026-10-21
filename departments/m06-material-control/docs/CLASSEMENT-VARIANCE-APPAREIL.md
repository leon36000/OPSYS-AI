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

L'ACK métier historique v1 est
`{accepte:true,resultat:<classement>,registre:{taille,hash_tete}}`.
Le classement contient `reference`, `selection`, `cause`, `motif`,
`reference_precedente`, `auteur:{personne,role,source}`, `appareil_id`, `classe_le`,
`horodatage_appareil_declare`, `references_pieces`. Auteur et réception viennent
du serveur ; l'heure appareil est déclarative, jamais la date du dommage.
Cap ajoute l'enveloppe `ok/resultat` et `rejoue`. Les nouvelles mutations DEVICE
rendent les formes v2 fermées de la section « Association d'intention v2 et preuve
de refus » ci-dessous ; la forme v1 reste celle des succès historiques.

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
preuves de pertes/bris, classements, preuves de refus et admission) ; aucune
garantie avant allocation.
Enveloppe JSON entière ≤min(5400,quota Cap), mesure Python en points de code
`ensure_ascii=False`, distincte des octets UTF-8. Préflight avant append et
postflight du vrai ACK dans le savepoint. Un refus métier admissible avant append
du classement reçoit une preuve négative durable. Toute panne après append,
y compris un Refus contrôlé à ce stade, devient RuntimeError et remonte pour
rollback extérieur du writer et du claim, puis reprise du même UUID.
N3 trace seulement un succès accepté ; aucune sortie ARTEFACT ou ACK partiel.

Les tests du département et captures SQL fictives qualifient le producteur et
ses invariants. La qualification Cap/idempotence et la Gateway DEVICE sont
séparées, de même que téléphone/ExpoSQLite/Hermes. Les pièces actuelles ne
certifient pas leur présence au moment du calcul terminal ; ni M4 N4 ni M10 ne
sont automatiquement raccordés.

## Association d'intention v2 et preuve de refus

Une nouvelle mutation DEVICE exige la Meta canonique dans le contexte spécifique
`classement_variance_contexte.contexte_mutation(meta)`. Ce contexte est remis à
zéro à sa sortie. Le body conserve ses cinq arguments et ne fournit aucune
identité : `intention(arguments)` lie l'appareil, la clé exacte et l'empreinte
canonique des arguments. Pour cette mutation M6, `Meta.cle` est admise comme
texte non vide d'au plus 256 points de code, sans nouvelle regex UUID ni
normalisation ; cette borne n'est pas une règle générale de toutes les Meta. Une heure Meta sans fuseau ou invalide
est refusée avant les sources métier.

Les nouveaux maillons `classements_variance` portent `version_schema: 2` et
`intention: {appareil_id, intention_uuid, empreinte_arguments}` dans leur hash.
Les maillons et ACK v1 restent inchangés : aucune association rétroactive.
Le rejeu positif confirme sa propre référence, même après une correction suivante.
L'ACK de succès v2 est
`{accepte:true,version_schema:2,resultat:<classement_v2>,registre:{taille,hash_tete}}`.
La projection du classement reprend les champs v1 et ajoute exactement
`version_schema` et `intention`.

Un vrai refus frais admissible écrit une preuve append-only distincte dans
`refus_classement_variance`, pas un classement. Ses colonnes métier sont version,
intention, sélection, verdict canonique, auteur SQL confirmé, réception serveur et
heure appareil déclarée ; index et hashes protègent sa chaîne. Son ACK v2 fermé
porte `accepte`, `version_schema`, `verdict`, `intention`, `preuve_refus`, `auteur`
et `horodatage_appareil_declare`. Le client lie la preuve à sa personne, son
appareil, sa clé, son heure d'origine et l'empreinte de ses cinq arguments.

Les six suffixes métier atteignables après admission sont `ARGUMENTS-INVALIDES`,
`LIGNE-HORS-PERIMETRE`, `PIECES-INVALIDES`, `LIAISON-INCOHERENTE`,
`REVISION-PERIMEE`, `SORTIE-TROP-VOLUMINEUSE`. Un rejet du schéma ou de l'admission
n'est pas transformé en preuve fraîche ; identité/source/contexte/chaîne inconnus
et pannes techniques n'en sont jamais des causes.

La paire appareil/clé doit être unique entre nouveaux classements et preuves de
refus. Une vraie preuve étrangère, une négation v1 sans preuve ou un faux ACK v2
ne certifie pas l'absence d'effet : issue inconnue, même clé/corps conservés. Ni
heure, ni personne, ni égalité du corps ne remplacent la paire. Le registre de
preuves est lu et compté avec toutes les autres sources avant claim/restitution ;
le plafond local 10000 est vérifié après copies, pas une borne globale d'allocation.

Les deux enveloppes complètes `rejoue:false/true` doivent tenir sous
`min(5400, quota Cap)` avant append et après relecture. Si la preuve du refus
ne tient pas, aucune certitude partielle n'est livrée. Toute panne après append
(classement ou preuve), y compris un Refus contrôlé à ce stade, remonte comme
RuntimeError : rollback du writer et de sa réclamation, puis reprise du même UUID.
Le frais certain modifie seulement preuve et idempotence ; le succès garde sa trace
N3 existante. Aucun stock/coût/M4/M10, effet physique ou causalité n'est déduit.
