---
name: gerer-une-intervention
description: Procédure pour planifier une intervention terrain depuis un lead M2 qualifié, suivre son avancement par les pointages du technicien jusqu'à sa complétion, sans jamais imposer de date ferme ni calculer un prix.
---

# Gérer une intervention

0. Un devis accepté (M3) fait déjà naître une intervention `a_planifier` : `m4_lister_interventions` avec
   `statut: a_planifier` la montre, avec son service lu à la source (M1), jamais deviné. Appelle
   `m4_verifier_preparation` : le verdict nomme ce qui manque, volet par volet (soumission, adresse confirmée,
   équipe, matériel, météo). Un volet `non_verifiable` n'est pas prêt ; ne dis jamais qu'une intervention est
   prête tant que le verdict n'est pas `pret`, et ne promets ni date ni créneau au client (c'est M4 qui confirme).
   Un lead saisi directement dans M2, sans passer par M1, n'a pas d'intervention née du devis : passe par l'étape 1.
1. Vérifie que le lead vient de M2 avec un marqueur de readiness et le contrat gelé (sept clés).
   Sinon : demande-le, stop. N'invente jamais un champ manquant.
2. Rassemble les techniciens et fenêtres horaires disponibles ce jour-là, puis appelle
   `m4_planifier_intervention` une seule fois : elle inscrit l'intervention ET calcule sa cédule.
   Un technicien EST une personne OPSYS : donne son identifiant de personne, jamais un code libre.
   L'intervention est alors assignée (consignée au registre) au technicien que la cédule retient ;
   c'est lui seul, parmi les employés, qui la voit et peut partir, pointer et terminer.
   - `accepte: false` → corrige l'entrée indiquée par le `verdict` ou escalade.
   - `non_cedulee: true` → aucun technicien disponible : signale-le, ne force rien (personne n'est
     assigné, donc aucun employé ne la voit).
3. Le jour venu, appelle `m4_demarrer_route` avec le technicien réellement assigné (celui rendu
   à l'étape 2). Un autre technicien ne peut pas partir à sa place.
4. À chaque pointage terrain (arrivée, départ), appelle `m4_pointer` avec l'horodatage, le fix
   GPS et la fenêtre de travail fournis par l'appelant — jamais une valeur devinée.
   - `statut: sur_site` → le travail peut commencer.
   - `statut: en_revue` → une anomalie GPS a été détectée ; ne la résous pas toi-même, escalade.
5. Après le pointage de départ final sans anomalie, appelle `m4_completer_intervention` : elle
   calcule la durée réelle et émet le Work Completion Trigger en une seule écriture.
6. Pour confirmer la fin des travaux au client, appelle `m4_notifier_client_completion` : c'est
   une action externe, elle reste en attente d'approbation humaine en mode ombre.
7. Toute réponse `accepte: false` contient un `verdict` nommant la faute : corrige ou escalade,
   ne réessaie jamais en devinant une autre valeur.
