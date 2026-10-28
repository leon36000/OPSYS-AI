# CRM03 — agenda commercial interne M2

## Objectif et état

Permettre au secrétariat de planifier une visite commerciale associée à un lead M2 et à son vendeur.
Le registre des rendez-vous est distinct de la cédule des équipes M4. CRM03 reste **PARTIAL** :
le compte vendeur console, Google, notifications, récurrences et glisser-déposer ne sont pas livrés par cette tranche.
Audit préalable : [AUDIT-AGENDA-VENDEURS.md](AUDIT-AGENDA-VENDEURS.md).

## Architecture, fichiers et données

- `departments/m02-revenue-crm/src/m2_revenue_crm/agenda_vendeurs.py` : domaine déterministe, registre append-only.
- `outils.py` : identité SQL, collection `agenda_vendeurs`, horodatage serveur, intention et audit atomiques.
- `src/opsys/console/agenda_ui.py` : formulaires et vues jour/semaine/mois en français.
- `src/opsys/console/metier.py` : port privé authentifié, sans reçu générique contenant le titre.
- `src/opsys/capacites.py` : refus des voies générique et profil avant toute approbation ou copie de charge.

La source d'attribution reste `m02-revenue-crm/principal`; les rendez-vous ne modifient pas les leads.
Identités rendez-vous/lead/vendeur immuables; titre et horaires versionnés; annulation terminale conservée.
Chaque révision cite sa source, son auteur admin et l'heure serveur. Les dates contiennent un offset explicite
correspondant réellement à `America/Montreal`; l'heure répétée à l'automne peut être désambiguïsée par cet offset.
Une heure inexistante, une fin avant le début ou une durée dépassant douze heures est refusée.

## Routes et outils

- `GET /crm/agenda?vendeur_id=...&jour=AAAA-MM-JJ&vue=jour|semaine|mois`
- `GET /crm/agenda/rendez-vous/{id}` : historique et édition.
- `POST /crm/agenda/enregistrer` : CSRF, intention et révision attendue obligatoires.
- Outils privés : `m2_enregistrer_rendez_vous`, `m2_lire_agenda_vendeur`, `m2_historique_rendez_vous`.

Aucun nouveau grant appareil, profil agent ou seller. La console revalide le rôle admin en base,
y compris avant un rejeu. Un propriétaire sans rôle admin ne peut pas accéder au registre.
Un vendeur actif et propriétaire courant du lead est requis pour un rendez-vous actif. Le retrait de rôle
ou la réassignation du lead n'efface pas l'historique; l'admin peut annuler une ancienne réservation.
Les lectures historiques restent accessibles à l'admin même pour un vendeur devenu inactif.

## Workflows et règles

1. Ouvrir l'agenda du vendeur et choisir une période.
2. Entrer le lead, l'objet, le début et la fin avec offset de Montréal.
3. Vérifier propriétaire réel et absence de chevauchement, puis écrire dans la même transaction que l'audit.
4. Déplacer avec la révision affichée; un éditeur périmé reçoit un conflit.
5. Annuler explicitement pour libérer le créneau; aucune suppression d'historique.

Les intervalles sont semi-ouverts et comparés en UTC : deux visites adjacentes sont possibles.
Un rendez-vous actif d'un lead réassigné reste réservé et signalé à revoir jusqu'à intervention admin.
La même intention et la même charge renvoient la révision initiale sans nouvel effet;
une charge différente sous la même intention est refusée. La lecture suivante montre l'état courant.

## Permissions, intégrations et gates

SQLite : transaction existante `BEGIN IMMEDIATE`, relecture/CAS et audit sous sauvegarde transactionnelle.
PostgreSQL : écriture fermée tant que qualification spécifique absente; formulaire masqué.
Aucun effet M4, M5, message client, Google ou M10 implicite. Le journal technique exclut le titre du rendez-vous.
L'agenda ne prouve pas les disponibilités externes, les temps de déplacement ni une confirmation du client.
Activer un connecteur ou des notifications exigera ses permissions, ses contrats et ses propres preuves.

## Bornes et risques

Au plus 10 000 maillons par source, contrôle avant chargement. Période de 1 à 31 jours,
100 rendez-vous ou révisions au plus et sortie bornée; refus explicite, aucune liste faussement complète.
Les grands historiques nécessiteront une pagination source-figée avant généralisation.
Les champs texte ne doivent contenir que le contexte commercial utile, jamais des données RH.
La parité visuelle Google Agenda avancée et le parcours navigateur restent à qualifier séparément.

## Tests et prochaines étapes

`departments/m02-revenue-crm/tests/test_agenda_vendeurs.py` : domaine, horaires, conflits, historique, sources.
`tests/test_console_agenda.py` : parcours HTTP avec registre M2 et SQLite réels, droits/CSRF/rejeux,
réouverture, concurrence, audit/rollback et absence d'effet M4. Fixtures fictives exclusivement.
Les résultats d'exécution sont conservés dans les reçus de qualification du chantier CRM03.
Validation locale intégrée : **287 tests PASS, zéro SKIP**, Ruff et vérification des manifestes réussis
(277 outils dont 173 déclarés aux appareils, aucun nouveau grant). Cette population inclut les tests CRM
et les contrats existants; elle ne s’ajoute pas aux décomptes des autres tranches. Le parcours HTTP démontre
création, déplacement, annulation, réassignation et formulaire réellement rendu; aucun parcours navigateur
ni serveur PostgreSQL n’est déduit de ce résultat. Les premiers échecs restent conservés : signature CSRF
incorrecte corrigée, puis sélecteur QA incluant le formulaire de déconnexion et assertion de statut devenue
obsolète corrigés. La CI du précédent commit demeure distincte de cette preuve locale.

Prochaines étapes : rencontres dans le dossier client, accès vendeur limité, pagination des grands historiques,
interface interactive et connecteurs autorisés, sans présenter cette tranche comme la totalité de CRM03.
