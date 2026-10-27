# CRM-08 — application humaine du plan : audit avant raccord

27 octobre 2026, parent `c9e9c7dec5c796536449854fb979abc5b436ece6`.
Statut **PARTIAL**. Revue indépendante statique puis rapprochement ROOT des propriétaires.
Le formulaire de proposition et sa revue sont qualifiés; aucun nouveau parcours d’application
n’est exécuté ni livré par cet audit.

## Propriétaires et décision N3

Le vrai outil `m4_appliquer_cedule` est T1/N3, admin appareil. Le manifeste M4 autorise admin
à décider N3. Réutiliser l’approbation persistée du socle : `approbations.creer_demande` puis
`approbations.decider(..., role="admin")`, dans le même savepoint que l’action et son reçu.
Le patron `console/fusion_ap_m5_saisie.py` montre le couplage demande/décision/réponse vérifiée.
Pour M4, conserver l’identité console admin vivante et l’heure de réception serveur pendant
la décision : `_acteur_appareil` et `acces.controler_confirmant` doivent aussi relire la personne.
Ne pas recopier mécaniquement le contexte sans acteur du cas M5, ni appeler le domaine seul.
Exiger décision `executee`, transport réussi et verdict métier accepté avant finalisation.
Aucune permission ni rôle ne doit être ajouté pour ce raccord privé admin.

## Patch minimal prévu

1. Préparer la revue exacte par `proposition_chantier.lire` : ancre lead/devis/intervention,
   vrai plan, sortie/état/plan_id cohérents. L’empreinte de décision inclut la revue, la tête M4,
   les profils équipes/météo et la préparation courante; ce n’est pas une nouvelle vérité métier.
2. Formulaire distinct à trois champs CSRF/intention/empreinte, cible dans la route exacte
   `/propositions-chantier/{plan_id}/appliquer`. Auteur, heure et arguments de l’outil sont
   exclusivement construits par le serveur : `{plan_id, horodatage, confirme_par}`.
3. Relire sous transaction, refuser une source changée, une préparation non prête, un plan
   sans visite, une intervention hors `a_planifier` ou une preuve périmée. Le propriétaire
   `cedule_tournees.appliquer` recalcule préparation, état/assignation, localisation, profil,
   entrée/matrice et `tournees.verifier_plan`, puis l’admissibilité des équipes avant mutation.
4. Vérifier le marqueur réel `cedule_appliquee`, ses transitions et son affectation exactes,
   relire les profils fichiers avant finalisation, puis clôturer approbation, audit et reçu
   dans le même savepoint. Toute incohérence/panne/quota annule cette tentative complète.
5. Après application, rediriger vers l’éditeur existant `/crm/cedule/plan/{plan_id}`; ses dates
   explicites, révisions et conflits doivent rester l’autorité du calendrier civil.

`cedule_tournees.appliquer` rend `deja_appliquee` avant ses vérifications actuelles. Un rejeu
est donc une lecture historique, jamais une nouvelle preuve de disponibilité. Revalider
l’admin avant reçu, comparer l’intention et reconstruire depuis le marqueur M4 et l’approbation
réelle; aucune seconde décision lors du même rejeu. Après report/remplacement, montrer l’état
courant et empêcher toute présentation du reçu comme une confirmation actuelle.

## Limite de capacité à préserver et à qualifier

L’application compare les interventions de son plan; le code ne compare pas les plages des
autres plans mono-intervention. Les jours numériques de deux plans n’ont pas une date commune
implicite. Une affectation interne ne doit donc pas être présentée comme une réservation de
date ou une disponibilité globale validée. Le scénario à deux plans sera reproduit avec de
vrais propriétaires pour qualifier cette limite, sans simuler de refus inexistant.

`calendrier_civil.confirmer` refuse ensuite les chevauchements avec les créneaux datés et
actuellement confirmés. Il ne vérifie ni trajet entre plans, ni disponibilité externe, ni
prévision du créneau. L’éditeur l’annonce comme dates internes. La capacité finale de dispatch
avec capacité globale et météo datée reste exigée pour M4 complet; cet audit ne l’abaisse pas
à l’affectation interne. Aucune notification ou promesse client ne découle de cette tranche.

## Qualification ciblée prévue

- Vrai devis/bus/préparation/proposition : application → une décision N3 sous admin SQL,
  une transition et une affectation, aucune date ni envoi; reçu lié à ses preuves réelles.
- Révocation, CSRF, plan étranger, intention différente, matériel retiré, position déplacée,
  profil changé après aperçu ou pendant exécution : refus sans écriture de la tentative.
- Rejeu après report ou remplacement : historique clairement identifié, sans nouvelle
  approbation ni effet; cache altéré ou preuve manquante refusés.
- Erreur audit/approbation/finalisation ou sortie excessive : rollback complet, y compris si
  l’exception est capturée dans la transaction extérieure.
- Deux plans d’une équipe : distinguer application interne des dates; datation chevauchante
  refusée par le propriétaire civil. Le résultat ne prouve pas les trajets ou la météo réelle.

Données fictives, homes/tmp privés avant imports, Source en lecture seule pendant QA,
ressources et réseau bornés, commandes/empreintes/JUnit/reçus distincts. Navigateur, PostgreSQL,
mobile, dispatch global et produit complet restent ouverts. Prochaine étape : tests-first
puis port privé d’application, avant de raccorder sa décision explicite dans la revue HTTP.
