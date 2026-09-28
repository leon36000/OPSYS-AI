---
name: localiser-un-chantier
description: Procédure pour obtenir les coordonnées confirmées d'un chantier à partir de son adresse, par l'index local du Référentiel québécois des adresses, sans jamais deviner une position ni en confirmer une à la place d'un humain.
---

# Localiser un chantier

Sans coordonnées CONFIRMÉES, un chantier n'entre pas dans une tournée : il reste « coordonnées
manquantes : à confirmer ». Tu proposes, un humain confirme.

1. Rassemble l'adresse du chantier. Champs séparés de préférence : `numero_municipal`, `suffixe` et
   `unite` s'ils existent, `odonyme` (« boulevard Iberville »), `municipalite`, et le `code_postal` si
   le client le donne. Une ligne « 2-56 A boulevard X, Ville J3B 5J6 » est acceptée (« 2-56 » se lit
   unité 2 de l'immeuble 56 ; une plage « 56-58 » n'existe pas dans le référentiel : demande UN numéro).
   Si un élément manque, demande-le au client : n'invente ni numéro, ni municipalité.
2. Appelle `m4_proposer_localisation` avec l'adresse (et le `chantier_id`, qui est le `lead_id` en v1).
   Elle ne lit que l'index local du RQA, sans réseau, et n'écrit rien.
   - `accepte: true` → c'est une PROPOSITION : `coordonnees` en microdegrés, `precision`,
     `rqa_identifiant`, `rqa_version`. Montre-la à l'humain avec l'`adresse_formatee` et l'`attribution`
     (CC-BY 4.0, à afficher telle quelle). `confirmation_actuelle` dit si une confirmation existe déjà.
   - `REJ-COORDONNEES-A-CONFIRMER` → aucune position n'est proposée. Lis `raison` :
     `aucune_correspondance` (redemande le numéro, le suffixe ou l'unité ; `candidats` liste les unités
     ou suffixes du même immeuble), `plusieurs_correspondances` (redemande le code postal ou la
     municipalité exacte), `qualite_insuffisante` ou `adresse_non_certifiee` (position à vérifier sur
     place). Ne choisis JAMAIS un candidat, ne propose jamais le centre de la ville ou d'un code postal.
   - `REJ-INDEX-RQA-ABSENT` → l'index n'est pas importé : demande à l'administrateur d'importer le CSV du
     RQA. Ce n'est pas « adresse introuvable ».
3. L'humain confirme (ou corrige) : appelle `m4_confirmer_localisation`, avec son nom dans `confirme_par`.
   - Proposition acceptée : `source: rqa`, `rqa_identifiant` de la proposition, et la MÊME `adresse`.
     Les coordonnées viennent de l'index, jamais de tes arguments.
   - L'humain a choisi parmi des doublons : même appel, avec l'`rqa_identifiant` qu'il a choisi.
   - Coordonnées données par l'humain : `source: manuel`, `latitude_microdegres` et
     `longitude_microdegres` (degrés × 1 000 000, entiers). Jamais des coordonnées lues ailleurs et
     recopiées à sa place.
   - `motif` obligatoire pour remplacer une confirmation, la retirer (`action: retiree`), ou confirmer
     une position de qualité faible : dis ce qui a été vérifié et comment.
4. Un refus nomme la faute : corrige la saisie ou demande à l'humain, ne réessaie pas en changeant une
   valeur au hasard. En mode ombre, ta confirmation attend la validation d'une personne : n'insiste pas.
5. La confirmation est versionnée : la dernière gagne et l'historique reste. Elle ne porte ni l'adresse
   ni les coordonnées en clair (chiffrées, effaçables). Ne recopie pas une coordonnée dans un message.
