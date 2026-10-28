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


## Jalon exécuté — port privé N3 (sans nouveau bouton HTTP)

`src/opsys/console/application_chantier.py::{preparer,appliquer}` relit la revue exacte et
prépare son empreinte avec les profils, la préparation et la tête M4. Il refuse une preuve
changée ou un plan non applicable avant décision. L’action construit les seuls arguments
M4 permis à partir de l’admin et de l’heure serveur. Elle crée et décide une vraie demande
N3 sous `role=admin` en gardant l’identité console; le propriétaire refait ses contrôles.

Avant finalisation, la preuve relie le marqueur `cedule_appliquee` au plan exact et à son
intervention, à une transition unique `a_planifier → planifiee` avec la même heure et la même
empreinte de préparation, puis à l’assignation attendue après cette transition. Le préfixe
historique avant marqueur confirme état/équipe; les modifications ultérieures n’effacent pas
cette preuve. La demande SQL est bornée avant décodage et doit être N3 exécutée, signée admin
par la même personne, avec arguments et résultat métier exacts. Le reçu est fermé et réussi
`ok`; rôle/expiration sont relus avant les sources et après l’action, et la configuration est
relue avant audit/finalisation. Toute erreur annule aussi la décision et les mutations.

Un rejeu relit l’autorité et reconstruit depuis le marqueur, la transition, l’assignation et
l’approbation réelle. Il porte `historique=true`, y compris après report, sans nouvelle décision
ni affectation. Cache libre/altéré, preuve manquante, signataire ou résultat incohérent et
approbation trop volumineuse sont refusés. Un nouvel identifiant ne réapplique pas un ancien plan.

`tests/test_console_application_chantier.py` utilise les vrais M1/M2/M3/M4/M6, profils et
décision N3. L’application produit une approbation admin, une transition et une assignation,
aucune date. Retrait matériel, localisation retirée et profil modifié après aperçu refusent;
profil changé après décision, panne d’audit/finalisation/décision et quota final annulent la
tentative SQL, même si l’exception est attrapée à l’intérieur de la transaction extérieure.
La configuration fichier indépendante modifiée par le scénario reste distincte du rollback SQL.

La revue indépendante a détecté une preuve de transition insuffisante :
`crm08-apply-transition-red-v1` reproduit un rejeu accepté après altération de l’empreinte de
préparation et rechaînage valide de M4. La liaison exacte transition/assignation décrite ci-dessus
ferme ce cas; revue statique complémentaire sans autre constat.

Le scénario à deux affaires est exécuté : deux propositions réelles et deux applications
N3 peuvent attribuer la même équipe, jour numérique 0, même heure de début, sans date civile.
La première datation explicite réussit; la deuxième sur la même date est refusée pour conflit
sans changement de base. Cette preuve confirme la limite d’affectation interne et le garde
civil; elle ne qualifie ni capacité globale ni trajet entre plans ni prévision météo.

Preuves privées `crm-prefill-qa-20261027-r1` : baseline `crm08-apply-red-v1` module absent;
`v1` 35 PASS avec style; rouge de transition conservé; `v2` 51 PASS, Ruff/vérificateur passent;
`v3` **52 PASS, 0 FAIL/SKIP, 24,25 s** avec une ligne de test à 121 caractères. Le seul changement
final coupe cette ligne, AST identique documenté; `v4` reprend le cas à deux plans inclus :
**1 PASS, 2,04 s**, Ruff ciblé et vérificateur 297/173 passent. Les cohortes se recoupent et
ne sont pas additionnées. Le harnais fait désormais le contrôle statique avant les tests et
épingle ses scripts, pour éviter de répéter une cohorte métier à cause d’une erreur de style.
Commandes, limites, sources, JUnit et reçus restent distincts; Source en lecture seule,
homes/tmp privés, réseau interdit, 1 CPU/1 Gio/96 tâches.

**PARTIAL** : port privé qualifié sur SQLite. Prochaine étape : formulaire de décision N3
distinct dans la revue HTTP et retour vers l’éditeur civil existant; les avertissements sur
l’absence de disponibilité globale/date/prévision doivent rester visibles. Navigateur,
PostgreSQL, mobile, dispatch complet et CRM-08 complet ne sont pas qualifiés par ce jalon.


## Jalon exécuté — décision N3 dans la revue HTTP

`proposition_chantier_ui.py` raccorde maintenant le port privé, sans nouvelle portée d’outil.
La revue GET prépare les preuves courantes sans écrire; si `peut_appliquer` est vrai, elle
présente un formulaire distinct « Confirmer l’affectation interne » avec CSRF, intention et
empreinte. Le texte annonce explicitement l’affectation sans réservation de date et les
limites sur les autres plans, les trajets et la météo du créneau.

`POST /crm/lead/{lead_id}/soumissions/{devis_id}/propositions-chantier/{plan_id}/appliquer`
ferme ces trois champs, vérifie le CSRF et appelle le port N3 sous la session SQL actuelle.
Un premier succès redirige 303 vers `/crm/cedule/plan/{plan_id}` : l’éditeur existant montre
révision 0 et dates vides, sans les remplir ni confirmer un client. Un rejeu rend une page
HTTP 200 « Reçu historique », relit l’état courant et n’affiche pas de formulaire d’application.
Après report, le reçu montre `reportee`, aucune nouvelle affectation ni disponibilité; un
nouvel identifiant sur la vieille empreinte refuse. Le rendu reste échappé, borné et no-store.

`tests/test_console_application_chantier_http.py` exécute le vrai parcours proposé → décision
N3 signée → marqueur/affectation → éditeur civil distinct → rejeu sans seconde approbation.
Chaque GET et chaque refus conserve l’instantané complet de la base. Sont vérifiés : CSRF,
champs d’identité/heure/plan injectés, doublons, taille/type de formulaire, rôle retiré,
non-admin, plan inconnu, matériel retiré après affichage et rejeu HTTP après report.

Preuves privées bornées : `crm08-apply-http-red-v1` formulaire absent avant code;
`v1` arrêt au contrôle statique avant tout test (ligne d’import), sans verdict métier.
`v2` **41 PASS, 0 FAIL/SKIP, 20,54 s**, Ruff/vérificateur 297/173 passent.
`v3` ajoute les deux cas HTTP report et non-admin/plan inconnu : **2 PASS, 2,39 s**, contrôle
statique et vérificateur passent. Les sources produit restent identiques à v2 et les octets
des tests précédents sont conservés comme préfixe; la preuve de compatibilité évite un rejeu
inutile de toute la cohorte. Les populations ne sont pas additionnées. Revue indépendante
statique du contrôleur : aucun nouveau constat. Commandes et scripts du harnais sont épinglés.

**PARTIAL** : parcours d’affectation interne qualifié sur HTTP/SQLite, avec décision N3 et
rejeu historique. Les dates internes restent une action séparée. Avant dispatch réel et
promesse client, restent à qualifier ensemble capacité globale, trajets entre plans, readiness
actuelle et prévision du créneau, ainsi que les sources/mémoires requises par M4. Navigateur,
PostgreSQL, mobile, M4 complet et OPSYS complet ne sont pas déclarés par ces jalons.
