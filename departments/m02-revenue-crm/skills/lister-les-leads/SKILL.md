---
name: lister-les-leads
description: Procédure pour lister les leads d'un vendeur ou du pipeline entier, par statut et par segment, page par page, sans confondre un segment non calculable avec une liste vide.
---

# Lister les leads

1. Appelle `m2_lister_leads` avec l'instant courant (`horodatage`, ISO-8601 avec fuseau). Depuis l'app, la
   liste est celle de la personne connectée : un vendeur ne reçoit que SES leads (ceux dont il est
   propriétaire), l'admin reçoit tout. N'essaie jamais de désigner un autre vendeur : aucun paramètre ne le
   permet, et un lead d'un autre n'est ni listé ni compté.
2. Filtre au besoin par `statut` (nouveau, qualifie, converti, perdu, cedule, chantier, facture, paiement,
   avis) et par `segment` (les 14 de M2.11). Chaque lead porte les segments qui s'appliquent, avec la règle
   citée (`regle`, énoncé dans `regles`) et la donnée qui l'a déclenchée (`donnee`). Cite-les tels quels :
   n'ajoute jamais un segment de ton cru.
3. Un segment « non calculable, manque X » n'est PAS un segment vide : la donnée n'existe pas (photos, valeur du
   client, satisfaction, plaintes, saisons, devis envoyé) ou le seuil n'est pas configuré. Relaie ce que
   `segments_non_calculables` dit manquer. Un filtre sur un tel segment est refusé
   (`REJ-SEGMENT-NON-CALCULABLE`) : dis ce qui manque, ne réponds jamais « aucun lead ». Les seuils de
   `dormant_lead` et de `quote_stale` sont à configurer par l'administrateur dans `department.yaml`
   (`configuration.segments`) : n'en propose pas de valeur comme si elle était décidée.
4. Lis la liste page par page : tant que `suivant` n'est pas nul, rappelle l'outil avec `decalage = suivant`.
   L'ordre est stable (le plus ancien lead d'abord). `total` compte tous les leads du filtre, `reste` ce qui
   suit la page. Si `total` change entre deux pages, relis depuis `decalage = 0`. Une page vide au-delà de la
   fin n'est pas une erreur.
5. La liste ne porte ni montant, ni contact : pour le détail d'un lead, `m2_obtenir_client_360`.
