# CRM05 — audit du raccord des rencontres au dossier

Source avant code : 570a7954b6716e9689cdc0d38ee0649bb029b3c8, 27 octobre 2026.

## Existant
M2 possède maintenant agenda_vendeurs (révisions, leads, vendeurs, instants Montréal, auteur, source).
Le dossier CRM lit le client 360 puis présente les projets du client; sa section Rencontres reste non branchée.
Le lecteur agenda actuel filtre par vendeur et période. Il ne convient pas pour retrouver toutes les rencontres
liées à un projet après réassignation : l'ancien vendeur garde son rendez-vous, sans transfert automatique.
Le lecteur historique actuel connaît un rendez-vous précis, pas tous ceux d'un lead.

## Réutilisation et patch minimal
Réutiliser _charger/_public du domaine agenda, les sources validées M2, le port console privé admin, l'échappement
HTML, les transactions et les tests HTTP existants. Aucune brique ou dépendance externe nouvelle.
Ajouter m2_lire_rencontres_lead, lecture uniquement : exact lead_id, toutes périodes et tous vendeurs d'origine,
état courant de chaque rendez-vous (actifs ET annulés), accès à son historique. Aucun cumul client implicite.
Pagination25, décalage multiple25, curseur empreinte liée au lead et aux deux têtes (principal+agenda).
Toute modification source invalide la continuation avec409 et lien pour recommencer; aucun doublon/saut silencieux.
Afficher premièrepage dans le dossier et une page dédiée /crm/lead/{lead_id}/rencontres pour la suite.
Une source défaillante affiche une indisponibilité explicite dans le dossier; la page dédiée refuse503.
Un lead inconnu n'est jamais présenté comme un agenda vide. Autorité SQLadmin revérifiée à chaque lecture.
Aucun nouveau droit seller/appareil/agent; aucun effet métier, aucune notification ou mémoire implicite.

## Critères de vérification
Vraies ingestion/qualification/réassignation et révisions agenda; deux projets du même client restent isolés.
Avant/après base inchangée pour toutes les lectures; ancienvendeur+nouveauvendeur, annulations, liens historique,
HTMLéchappé, absence de source≠zéro; anonymes/nonadmins/révocation refusés.
Parcours26+ rencontres sur2pages avec source figée puis ajout agenda ou réassignation M2→409.
Paramètres inconnus/dupliqués/maltypés et tampering refusés; quota/bornes conservés.

## Statut et limites
Audit terminé avant code; raccord en préparation. SQLSQLite/HTTP à démontrer avec fixturesfictives et QAprivée.
Le calendrier interactif Google, les droits vendeur, l'écriture PostgreSQL, la mémoire M10, le mobile et les courriels
restent des exigences distinctes ouvertes. Ce raccord n'est ni une confirmation client ni une réunion réalisée.

Jalon suivant : raccord implémenté et qualifié localement (315 tests dans la population recoupée, Ruff et verifier valides).
Voir [contrat, preuves et limites](RENCONTRES-DOSSIER-M2.md). L’audit initial ci-dessus est conservé.
