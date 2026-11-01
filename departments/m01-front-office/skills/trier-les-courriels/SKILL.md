---
name: trier-les-courriels
description: "Lire le tri automatique des courriels reçus (classe, confiance, raisons, aiguillage), traiter la relecture humaine et alimenter la boucle d'apprentissage sans jamais activer une règle."
---

# Trier les courriels reçus

Le tri est fait par du code (`m1_trier_courriel`, aussi déclenché à la réception) : une classe parmi demande de soumission,
plainte, facture de fournisseur, confirmation de fournisseur, commande de matériaux, réponse de client, interne,
pourriel/hameçonnage ou autre, une confiance, les règles déclenchées et le département aiguillé. Tu ne reclasses pas à ta tête.

1. `m1_lire_tri_courriel` (filtre `revue_seulement`) : ce qu'une personne doit relire. Un texte neutralisé, des classes proches
   ou une confiance basse imposent la relecture ; un courriel qui porte le domaine de l'entreprise sans authentification de
   confiance est une usurpation possible, jamais un courriel interne.
2. Le tri n'agit pas : une plainte ouvre un transfert interne, une facture devient une attente chez M5, une commande ou la
   confirmation d'un fournisseur un brouillon chez M6. Dis « classé et aiguillé », jamais « traité ».
3. Une erreur de classe se corrige par une PERSONNE (`m1_consigner_correction_tri`). `m1_proposer_amelioration` en tire des
   propositions mesurées sur le corpus fictif ; `m1_decider_proposition` (canari, promotion, retour arrière) est une décision
   humaine. Tu ne promeus rien toi-même.
4. `m1_evaluer_tri_courriel` mesure les règles actives sur un corpus FICTIF : c'est un contrôle de cohérence, pas une promesse
   de performance sur du courrier réel.
