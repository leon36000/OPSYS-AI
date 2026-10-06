---
name: faire-progresser-vers-m3
description: Procédure pour qualifier un lead, enregistrer ses interactions commerciales et vérifier qu'il est prêt à être transmis à M3, sans jamais halluciner une décision humaine.
---

# Faire progresser un lead vers M3

1. La transition de `nouveau` vers `qualifie` exige un owner humain non vide ET une
   prochaine action complète (description non vide, échéance ISO-8601 avec fuseau) : ces deux
   éléments viennent toujours d'un humain, jamais de toi. Appelle `m2_transitionner_statut`
   avec exactement ce qu'on t'a fourni. L'owner est l'identifiant OPSYS de la personne (par
   exemple `vendeur.un`), jamais son nom : c'est cet identifiant qui rend le lead visible à son
   vendeur sur l'app. Si on ne te donne qu'un nom, demande l'identifiant.
2. Une fois qualifié, chaque interaction commerciale réelle (appel, courriel, rencontre) doit
   être enregistrée avec `m2_enregistrer_interaction` (auteur, résumé, horodatage). Une
   interaction inventée pour satisfaire la gate est un aveu de responsabilité que tu ne dois
   jamais faire. Depuis l'app, l'auteur est la personne connectée : il n'est pas à fournir.
3. Appelle `m2_evaluer_readiness` avant d'annoncer que le lead peut passer à M3. Si le
   marqueur n'est pas émis, la réponse contient un `verdict` qui liste précisément ce qui
   manque (statut, owner, service/type de travaux, ville, ou interaction à la qualification ou après) : relaie cette
   liste, n'improvise pas une explication.
   Cette gate est commerciale : les photos et la précision de mesure restent à M3. Elle ne
   déclenche ni estimation, ni conversion, ni envoi. Après une modification du dossier et avant
   de transmettre à M3, refais cette lecture; ne réutilise pas un marqueur gardé hors ligne.
   Transmets le contrat et le marqueur reçus pour le même `lead_id`, jamais une forme reconstruite.
4. Le passage à `converti` exige une décision humaine explicite ET une référence de devis M3
   déjà acceptée ; le passage à `perdu` exige une décision humaine explicite ET un motif. Un
   dossier perdu est définitivement clos : n'essaie plus d'y écrire. Un dossier converti, lui,
   continue son cycle de vie (cédule, chantier, facture, paiement, avis) — seul un retour vers
   `nouveau` ou `qualifie` reste refusé (protection commerciale). Quand M4 termine le chantier,
   c'est `m2_marquer_chantier_termine` (pas `m2_transitionner_statut`) qui avance le dossier
   vers `facture` et écrit l'activité système ; il exige une prochaine action fournie par
   l'appelant, jamais inventée par toi.

Pour rendre compte : faits/source → verdict exact → prochaine action proposée → limite.
Si une donnée manque, nomme-la sans lui donner une valeur. Un refus d'accès ne justifie ni une
autre identité, ni une nouvelle tentative identique. Après une panne, annonce « non vérifié »;
ne transforme pas le cache, la suggestion ou un message client en autorisation.
