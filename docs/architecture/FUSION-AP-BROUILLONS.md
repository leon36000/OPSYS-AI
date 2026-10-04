# Brouillon de facture fournisseur après PDF natif

Cette tranche ajoute un brouillon AP privé, révisable par un administrateur actif,
à un lot `EXTRAIT_PREPARATOIRE` du pilote PDF. Elle ne crée pas de facture M5,
de dette, d'écriture de registre, d'échéance ou de paiement. Le brouillon reste
`A_REVOIR`; aucune transition de confirmation n'est fournie.

## Parcours et frontières

1. Le pilote PDF existant reçoit et chiffre le PDF, puis son worker Linux isolé
   produit le texte natif borné par page. Les états de refus et d'erreur restent
   ceux de PDF; aucune image/OCR n'est ajoutée.
2. Un opérateur saisit ou corrige un ensemble fixe de champs fournisseur dans
   `opsys.fusion_ap.enregistrer`. Il transmet la révision PDF et la révision
   AP attendues. Un seul brouillon chiffré courant est conservé par lot.
3. `lire` rend uniquement les métadonnées privées; `lire_champs` constitue la
   lecture explicite séparée du contenu déchiffré. Les deux exigent les mêmes
   administrateurs actifs que le pilote PDF et SQLite.

La proposition accepte exactement les champs texte `fournisseur`, `numero`,
`date`, `po`, `sous_total_imprime`, `taxe_imprimee`, `total_imprime` et `devise`.
Chaque valeur est limitée à 128 octets UTF-8; le JSON canonique complet reste
sous 8 Kio. Aucun champ n'est interprété comme date, montant, taxe, fournisseur
catalogué ou commande reçue. Les champs non vides doivent porter de une à trois
références de page.

Une référence contient le numéro de page, l'identifiant du fragment natif et
son SHA-256. Le service compare ces trois éléments au résultat PDF déchiffré et
validé avant d'enregistrer ou de rendre le brouillon. La citation établit
l'origine dans la page citée; elle ne prouve ni que la valeur saisie apparaît
exactement dans un segment, ni son exactitude comptable. L'administrateur
demeure responsable de la lecture et de la correction.

Le compartiment M10 des procédures M03 reste distinct. Une facture ne peut pas
être routée vers la recherche de procédures. Cette version n'envoie aucun texte
financier à la mémoire générale, à un embedding, à un LLM ou à un service réseau.

## Reprise, droits et stockage

Les mutations exigent une clé opaque par acteur et lot. Le même identifiant et
le même contenu rejouent sans nouvelle révision; un contenu différent sous la
même clé est refusé. Les commandes sont plafonnées à 128 par lot. Chaque
modification incrémente la révision AP par CAS; un conflit ne remplace rien.
Une réponse de reprise distingue la révision de cette mutation de la version
courante du brouillon.

Le chiffrement AES-GCM réutilise la référence externe de clé du lot PDF et une
AAD AP dédiée qui lie version de format, lot, SHA-256 source, configuration,
révision PDF et révision AP. Le nom de référence est conservé; aucune clé brute
n'entre en base. La réservation de quota, la commande, le brouillon et l'audit
metadata sont dans la transaction SQLite courante. Le plafond de 16 Mio du
compartiment PDF n'augmente pas : il compte ensemble sources, extraits et
ciphertext du brouillon, avec le tag AES inclus. Un dépassement annule toute la
transaction.

Le journal ne contient pas les valeurs ou les citations : seulement la source,
les révisions, l'état et les compteurs de champs/références. La base refuse les
autres moteurs pour cette tranche. Le remplacement de l'ancien ciphertext
courant ne garantit pas l'effacement de pages SQLite/WAL, de sauvegardes ou de
copies déjà exportées. Aucun effacement automatique ni politique de rétention
n'est ajouté.

## Revue privée dans la console

Le détail d'un PDF extrait offre un lien vers la revue AP réservée au même
administrateur actif que l'admission PDF. La page GET ne rend que l'état et les
révisions; l'affichage des champs passe par une action POST explicite avec CSRF.
Cette lecture renvoie ensemble les champs déchiffrés et leur révision AP dans
une transaction, afin que le formulaire ne mélange pas deux versions
concurrentes. Les formulaires acceptent seulement les champs connus, refusent
les doublons et sont limités à 16 Kio. Les réponses contenant les champs sont
privées et `no-store`; le HTML échappe les valeurs et les références de pages
sont reconstruites à partir des fragments PDF courants, jamais d'un SHA reçu
du navigateur. La sauvegarde conserve la révision PDF/AP attendue, le CAS et
la clé de mutation idempotente du service.

## Limites métier

L'enregistrement du brouillon ne le valide pas contre le registre des fournisseurs,
les PO reçus, les doublons M5, les taxes ou un instantané du registre. Les champs imprimés
peuvent être inexacts, contradictoires ou mal saisis; ils restent à revoir. Les
fonctions M5 `saisir_facture_fournisseur` et `saisir_facture_sans_po` sont des
écritures métier et ne sont jamais appelées par cette tranche. L'écran privé
permet seulement la saisie et la revue; il n'ajoute aucune confirmation AP. Les
administrateurs possédant aussi le rôle `finance` ou `nathan_owner` disposent
depuis le 4 octobre d'une [vérification M5 explicite en lecture seule](../grs/compta/M5-AP-VERIFICATION-REPRISE-2026-10-04.md).
Elle ne confirme pas le brouillon : elle relit PDF/citations, révisions, chaîne AP
et taux; l'humain fournit les identifiants PO/fournisseur et atteste leur
correspondance. Le total imprimé et l'agrégat des taxes sont comparés aux calculs
M5. Les champs monétaires doivent être corrigés en décimaux positionnels au cent,
la date en ISO, la devise en `CAD`; aucun libellé ambigu n'est normalisé.
Une confirmation humaine et la provenance restent à construire séparément avant
toute saisie comptable; aucune facture, dette ni paiement n'est ajouté ici.

Les PDF de qualification doivent être générés localement avec des identités et
valeurs fictives. Le succès du worker natif et ses codes de readiness ne
constituent pas une mesure de précision sur des factures fournisseurs réelles.
