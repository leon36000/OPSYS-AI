---
name: rapports-et-preaudit
description: Procédure pour produire les états financiers en brouillon (résultats, bilan, budget contre réel, rentabilité par service et par ville, rapport mensuel) et lire le pré-audit sans jamais prendre une donnée non déclarée pour un zéro, et sans rien exécuter, clore, corriger ni envoyer.
---

# Rapports financiers et pré-audit

Tout vient du grand livre en partie double (écritures DÉFINITIVES). Tu ne calcules rien : tu appelles l'outil, tu lis son
reçu, tu relaies. Chaque rapport est un BROUILLON PRÉPARATOIRE à valider auprès d'un comptable (CPA) ; dis-le.

1. `m5_etat_des_resultats` (debut, fin) et `m5_bilan_brouillon` (au). Lis `completude` : des brouillons
   (`brouillons_non_comptabilises`) ne sont PAS additionnés, l'état est incomplet tant qu'une personne ne les a pas validés
   (N4). Le résultat est AVANT impôts ; le bilan montre un « résultat cumulé non clos » (aucune clôture d'exercice). Si
   `equilibre` est faux, dis l'écart, ne l'explique pas. `marge_brute` « NON_CALCULABLE » : dis qu'il faut déclarer les comptes
   de coûts directs (`configuration.rapports`), n'en suppose aucun.
2. `m5_budget_contre_reel` : le budget est celui que la direction a DÉCLARÉ (`m5_etablir_budget`, N3, une personne
   l'approuve ; un agent seul est refusé). `REJ-BUDGET-A-DECLARER` : relaie ce qu'il faut déclarer, n'invente aucun budget. Un
   mois sans budget est nommé, jamais comparé à zéro ; un compte avec du réel sans ligne de budget est « non budgété ».
3. `m5_rentabilite_par_axe` (service ou ville) : seulement les chantiers à coût complet et à prix définitif. « Non calculable,
   manque X » veut dire que la dimension (publiée par M4 à la fin des travaux) ou le coût complet manque : ne devine jamais
   une ville.
4. `m5_rapport_mensuel_direction` : six sections ; garde la séparation FAITS / HYPOTHÈSES / DONNÉES MANQUANTES. Lis page par
   page (`prochain_depart`).
5. `m5_controler_preaudit` : des constats (règle, gravité, raison, sources, action proposée). Lis `regles_non_evaluees` et
   `regles_partielles` AVANT les constats : une règle non évaluée n'a pas « zéro constat », elle attend une décision de la
   direction (réglages de direction : seuil de transaction hors norme, fenêtre de doublon, historique de changement de compte).
   Une action proposée n'est JAMAIS exécutée par le contrôle ; si tu veux la faire, passe par l'outil suggéré et son niveau
   d'approbation. Un constat est une question posée à une personne, pas un verdict de fraude.
6. `m5_rejouer_rapport_financier` pour prouver qu'un chiffre vient bien de ses entrées. `m5_constater_preaudit` appartient au
   planificateur (publie les seuls comptes pour M8) : ne l'appelle pas toi-même.
