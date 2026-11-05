---
name: consommer-du-materiel-terrain
description: Procédure pour confirmer une consommation de matériaux sur une intervention terrain (WCT) — le technicien ne voit jamais un coût.
---

# Consommer du matériel terrain

1. Vérifie que tu disposes du WCT complet émis par M4 (12 clés exactes, `"M6"`
   présent dans `consommateurs_cibles`) — ne le reconstruis jamais toi-même.
2. Rassemble le formulaire de consommation (wct_id, intervention_id, chantier_id,
   lignes consommées avec quantités positives).
3. Appelle `m6_consommer_materiaux` dans sa transaction durable avec le `wct` et le
   formulaire; l'outil relit le WCT canonique publié par M4 et le registre durable.
4. Une consommation qui dépasserait le stock théorique du chantier ou, si les chaînes
   durables sont valides, l'en-main global est refusée (`REJ-STOCK-INSUFFISANT`). Si ce
   refus survient, vérifie la réception et le détail des emplacements.
5. La confirmation renvoyée (`ConfirmationConsommationTerrain`) ne porte jamais de
   coût : présente-la au technicien telle quelle, sans y ajouter de prix.

Limite du contrat historique : un succès ne suffit pas, à lui seul, à prouver que les unités
sont physiquement localisées dans ce chantier ni qu'elles restent disponibles après les
réservations. Si l'emplacement ou les réservations changent la décision, consulte d'abord les
détails du stock et les réservations; ne présente pas la confirmation comme une preuve de
stock local.
