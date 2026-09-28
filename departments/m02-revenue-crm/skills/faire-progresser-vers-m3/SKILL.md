---
name: faire-progresser-vers-m3
description: Procédure pour qualifier un lead, enregistrer ses interactions commerciales et vérifier qu'il est prêt à être transmis à M3, sans jamais halluciner une décision humaine.
---

# Faire progresser un lead vers M3

1. La transition de `nouveau` vers `qualifie` exige un owner humain non vide ET une
   prochaine action complète (description non vide, échéance ISO-8601 avec fuseau) : ces deux
   éléments viennent toujours d'un humain, jamais de toi. Appelle `m2_transitionner_statut`
   avec exactement ce qu'on t'a fourni.
2. Une fois qualifié, chaque interaction commerciale réelle (appel, courriel, rencontre) doit
   être enregistrée avec `m2_enregistrer_interaction` (auteur, résumé, horodatage). Une
   interaction inventée pour satisfaire la gate est un aveu de responsabilité que tu ne dois
   jamais faire.
3. Appelle `m2_evaluer_readiness` avant d'annoncer que le lead peut passer à M3. Si le
   marqueur n'est pas émis, la réponse contient un `verdict` qui liste précisément ce qui
   manque (owner, type de travaux, ville, ou interaction post-qualification) : relaie cette
   liste, n'improvise pas une explication.
4. Le passage à `converti` exige une décision humaine explicite ET une référence de devis M3
   déjà acceptée ; le passage à `perdu` exige une décision humaine explicite ET un motif. Un
   dossier converti ou perdu est définitivement clos : n'essaie plus d'y écrire.
