# Rappels importés : file admin et prise interne DEVICE

Les deux outils sont ajoutés à la fin de la factory historique M1. La console conserve
`m1_consigner_suivi_rappel` T1/N2, sa restriction console et son retour natif.
Les appels, messages, contacts obtenus et rendez-vous ne sont pas produits par cette tranche.

- `m1_lister_rappels_appareil` : T0/N0, admin actif DEVICE. Arguments fermés
  `apres_transfert_id` (null ou tr-hex20 exclusif, défaut null), `taille_page` (1..8, défaut 8).
  La file contient les transferts ventes ouverts liés à de vrais `appel_importe` acceptés
  `manque`/`voicemail`, avec correspondance tâche/transfert/conversation/source/signal vérifiée.
  Une source revendiquée incohérente refuse la lecture entière ; ventes ordinaire est exclu.
  La liste ne projette aucun téléphone, contact, message, texte source libre ou appel_id.
  Le curseur ordonne les IDs, pas les dates. Chaque page est courante ; une nouvelle clé plus
  petite exige un rafraîchissement. Aucun snapshot immuable n'est promis.
- `m1_prendre_en_charge_rappel_appareil` : T1/N2, admin actif DEVICE. Corps fermé
  `{transfert_id,snapshot_attendu}` uniquement. `idempotence.Meta` est posé dans
  `rappels_appareil.contexte_mutation`, jamais dans le corps. La réception serveur est obligatoire.
  La prise est attribuée à la personne confirmée ; le transfert reste ouvert.

La file renvoie le couple `accepte/resultat`, avec `rappels` et `page` :
`apres_transfert_id`, `taille_page`, `total`, `retournes`, `reste`, `apres_suivant`.
Chaque rappel porte `transfert_id`, `conversation_id`, `lead_id` nullable, `canal`,
`ouvert_le`, `nombre_sources`, `derniere_source` (ligne_id/statut/recu_le) et les sept
champs natifs de `suivi_rappel`. Le détail reste `m1_lire_transfert` côté serveur.

L'ACK fermé v1 porte le propre maillon, son précédent/index zéro, le snapshot original,
l'acteur admin/source appareil, l'appareil/UUID original, les deux horloges et la projection
au préfixe immédiatement après cet effet. L'heure appareil est normalisée par ISO-8601 ;
l'heure serveur initiale reste dans le maillon. Aucun horaire n'est accepté comme argument.

Les seams publiques sont `outils.autoriser_prise_rappel_appareil(arguments, *, nom)` et
`outils.verifier_rejeu_prise_rappel_appareil(arguments,reponse)` ; `Refus.suffixe` est fermé.
La Cap doit appeler ces seams sous `contexte_mutation(meta)` avant claim/rejeu et borner
l'enveloppe complète. L'autorité actuelle est indépendante des préconditions fraîches.
Le replay confirme son propre maillon/préfixe, même après une tentative ou une clôture ;
il ne compare ni la tête globale ni le snapshot courant. Un refus préalable ou un ACK
incohérent ne prouve jamais l'absence d'un ancien effet : même UUID/payload à conserver.

L'identité courante est validée avant lecture métier. SQLite/DBAPI doit être réellement
sous transaction et lié à l'instance courante. Les bornes SQL M1 sont contrôlées avant
le décodage : 10000 lignes, 65536 octets par maillon, 8388608 octets au total.
La chaîne entière doit être valide. La sortie complète est limitée à min(5400, quota Cap)
caractères Unicode, pas seulement aux faits. Débordement liste : refus nommé sans détail
partiel. Préflight writer : refus certain avant append. Panne après append/projection/ACK :
RuntimeError, pour rollback de la transaction incluant la réclamation. Le budget interne
préflight utilise un hash de même longueur, jamais transmis comme un reçu.

Les tests département utilisent vrais imports M1, identités SQL, SQLite fichier et
concurrence ; les contextes DEVICE sont injectés. Les preuves Cap/HTTP/Gateway, CI et
mobile doivent être qualifiées séparément. Aucun fournisseur, téléphone réel, Postgres,
appel sortant, envoi SMS ou complétion omnicanal n'est qualifié ici. M1 profond reste PARTIEL.

Un refus frais certain enregistré se rejoue également à l'identique : TRANSFERT-CLOS,
SNAPSHOT-PERIME, DEJA-ATTRIBUE ou SORTIE-TROP-VOLUMINEUSE du préflight avant append.
Le verdict fermé doit être exactement celui du writer, sans champ ajouté ni détail remplacé.
Autorité, source, Meta et quota complet rejoue=true restent vérifiés avant restitution.
Le refus sans append n'a pas de maillon à exiger ; la Cap lie sa clé et son corps persistés.
Identité/source/horodatage inconnus ne sont jamais convertis en négation certaine.
Un dépassement après append est RuntimeError : aucune négation certaine n'est enregistrée.

Une réponse négative canonique ne remplace jamais la preuve d'un effet DEVICE : la seam
refuse REJEU-INCOHERENT si un maillon prise_en_charge/source appareil porte déjà la même
paire (appareil,intention_uuid). La paire est composée : un UUID identique sur un autre
appareil n'est pas cet effet. Les anciens maillons console sans paire DEVICE gardent leur
forme et ne constituent pas une preuve d'effet de cette intention d'appareil.
