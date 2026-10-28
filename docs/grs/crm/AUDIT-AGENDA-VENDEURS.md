# CRM03 — audit initial agenda vendeurs

27 octobre 2026. Source avant modification : eb5d2af90a210ba38b7875ca026806fe325d946f.

## Constat
Aucun rendez-vous vendeur ou agenda commercial dans M2. Les rappels de relance ne représentent pas une réservation horaire. M4 possède une cédule d'équipes; celle-ci reste distincte. La console CRM exige admin/owner, les lecteurs CRM exigent admin confirmé SQL. Les vendeurs ont déjà une identité seller et la propriété des leads dans M2, mais aucune session console vendeur n'est ouverte. Le module acces.py lit la dernière assignation réelle; outils.py vérifie les personnes actives. Le registre M2 chaîné et le stockage SQL par collection fournissent append-only et transaction; aucun besoin de nouvelles tables pour cette tranche.

## Réutilisation examinée
- Registre M2, assignation/proprietaires, identité SQL, transaction SQLite, console CSRF/no-store, port privé et intentions de mutations (patron annotations M4). Réutiliser ces composants.
- https://github.com/fullcalendar/fullcalendar : calendrier JS avec vues et interaction; utile pour une future interface graphique avancée, ne fournit pas identité métier ni propriété des leads. Pas adopté, aucune qualification de dépendances/licence effectuée.
- https://gitlab.com/davical-project/davical : serveur CalDAV/iCalendar; synchronisation distincte du besoin de registre interne. Pas adopté, aucune qualification d'intégration ou licence effectuée.
Aucun nouveau framework ou téléchargement pour la tranche interne.

## Patch minimal et contrat
M2 est propriétaire des rendez-vous commerciaux. Collection privée agenda_vendeurs, type rendez_vous, registre existant. Une personne admin authentifiée peut créer, déplacer ou annuler un rendez-vous d'un vendeur actif, lié à un lead actuellement attribué à ce vendeur. Auteur et horodatage viennent du serveur. Aucun message, confirmation client, dispatch M4 ou Google sync.
Identité métier du rendez-vous (rendez_vous_id, lead_id, vendeur_id) immuable. Révision attendue obligatoire, intentions durables idempotentes, refus de conflit horaire entre rendez-vous actifs d'un même vendeur. Intervalles semi-ouverts comparés UTC. Dates ISO avec offset réel America/Montreal; heure inexistante ou mauvais offset refusés, heures répétées explicitées par offset. Durée >0 <=12h. Une réassignation du lead rend le rendez-vous à revoir, jamais transféré; annulation permise, modification active bloquée tant que propriétaire incohérent. Ancien rendez-vous actif continue de réserver son créneau jusqu'à annulation explicite.
Lectures jour/semaine/mois (période exacte de 1 à31 jours), filtrées par vendeur; historique par rendez-vous; plafond strict au lieu de troncature silencieuse. Console admin uniquement pour cette étape; aucun nouveau droit vendeur, agent, appareil, finance ou global-client. API outils privée refusée hors console.

## Risques et preuves requises
Tests domaine : recouvrement/adjacence/autre vendeur, annulation, modification CAS/rejeu contradictoire, DST/fuseau, source corrompue ou réassignée, bornes.
Tests HTTP SQLite : session/CSRF/rôle révocable, chemin réel M2→agenda→historique, confidentialité HTML, persistance, audit+rollback, aucune mutation M4/M5/client. Tests entrée générique/profil privé refusés avant effet.
Source test fictive, homes privés et QA bornée hors réseau avant imports. PostgreSQL writer, compte vendeur console, Google, notifications, récurrences, disponibilités externes et interface glisser-déposer restent non qualifiés. CRM03 reste PARTIAL tant que ces exigences ne sont pas démontrées.
