---
name: consommer-du-materiel-terrain
description: Procédure pour confirmer une consommation de matériaux sur une intervention terrain (WCT) — le technicien ne voit jamais un coût.
---

# Consommer du matériel terrain

1. Vérifie que tu disposes du WCT complet émis par M4 (12 clés exactes, `"M6"`
   présent dans `consommateurs_cibles`) — ne le reconstruis jamais toi-même.
2. Rassemble le formulaire de consommation (wct_id, intervention_id, chantier_id,
   lignes consommées avec quantités positives).
3. Appelle `m6_consommer_materiaux` avec `registre_historique` (l'historique du
   registre de ce chantier, `[]` si aucun encore).
4. Une consommation qui dépasserait le stock disponible est refusée
   (`REJ-STOCK-INSUFFISANT`) : le stock n'est jamais négatif silencieusement — si
   ce refus survient, vérifie qu'une réception a bien été enregistrée avant.
5. La confirmation renvoyée (`ConfirmationConsommationTerrain`) ne porte jamais de
   coût : présente-la au technicien telle quelle, sans y ajouter de prix.
