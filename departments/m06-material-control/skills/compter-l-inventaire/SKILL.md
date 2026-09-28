---
name: compter-l-inventaire
description: Procédure pour soumettre un comptage physique et obtenir la variance contre le stock théorique — un constat neutre, jamais une accusation.
---

# Compter l'inventaire

1. Rassemble le comptage (chantier_id, materiau_id, quantité comptée,
   horodatage).
2. Appelle `m6_soumettre_comptage` avec `registre_historique` (l'historique du
   registre de ce chantier).
3. Lis `verdict_variance` : `AUCUN_ECART`, `STOCK_INFERIEUR_AU_THEORIQUE`,
   `STOCK_SUPERIEUR_AU_THEORIQUE`, ou `INDETERMINE` (aucun mouvement théorique
   préalable pour ce couple — rien à comparer, ne fabrique jamais un écart
   contre zéro).
4. `note_investigation` reste toujours nulle à cet appel : ne remplis jamais de
   cause ni de responsable toi-même — l'investigation est une décision humaine
   distincte.
5. Présente l'écart comme un CONSTAT chiffré et daté, jamais comme une
   accusation envers une personne.
