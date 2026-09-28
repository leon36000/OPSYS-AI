---
name: receptionner-une-commande
description: Procédure pour enregistrer la réception physique d'un bon de commande — résolution du prix, écriture du stock, signal à M5 si un montant est dû, suggestion de réapprovisionnement.
---

# Réceptionner une commande

1. Rassemble le `bon_demande` (po_id, chantier_id, lignes demandées, horodatage)
   et la `reception_po` déclarée (mêmes po_id/chantier_id, lignes reçues,
   horodatage). Le catalogue fourni (facultatif) donne les coûts unitaires
   connus ; sans lui, le prix vient de l'historique du registre, sinon il reste
   indéterminé — jamais un prix inventé.
2. Appelle `m6_receptionner_commande` avec `registre_historique` (l'historique
   renvoyé par le dernier appel connu pour ce même registre, `[]` sinon) et,
   si tu en as, des `seuils_reorder`.
3. Lis `accuse_reception.verdict_reception` : `CONFORME`, `RECEPTION_INFERIEURE`,
   `RECEPTION_SUPERIEURE` ou `RECEPTION_MIXTE` — présente-le tel quel, sans
   l'arrondir à un seul mot.
4. Si `signal_po_a_payer` n'est pas nul, transmets-le à M5 tel quel : c'est M5 qui
   décide et exécute le règlement, jamais toi.
5. Si `signaux_reorder` contient des entrées, présente-les comme des suggestions —
   jamais comme une commande déjà passée.
6. Conserve `registre_historique` renvoyé pour le prochain appel sur ce même
   registre.
