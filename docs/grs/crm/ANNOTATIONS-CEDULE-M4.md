# CRM-02 — Notes rapides des créneaux M4

## Objectif et choix

La secrétaire ouvre la pastille d’une carte hebdomadaire, saisit une note interne ou une correction et retrouve son auteur, son heure serveur et son historique. Un compteur textuel accompagne le point : l’information ne dépend pas d’une couleur. Cette interprétation de la « petite note » provient du message fourni ; aucune validation visuelle réelle n’est revendiquée.

L’audit a exclu deux réemplois trompeurs : les interactions M2 sont des notes de lead ; les notes de preuves M4 concernent la complétion terrain. Le stockage utilise **la classe Registre existante**, dans la collection privée M4 `annotations_calendrier`. Aucune table, dépendance ni framework ajouté.

## Contrat et architecture

L’ancre est le quadruplet exact `intervention_id`, `plan_id`, `source_application_id`, `source_ligne_id` de la confirmation civile. La proposition et l’application doivent réellement contenir une visite unique. Équipe, horaires et révision civile sont dérivés des maillons, jamais des champs du navigateur.

Chaque saisie ajoute une révision pour l’intervention. Une correction conserve les anciennes versions. Le verrou de révision empêche deux éditeurs de remplacer silencieusement leur travail. Une intention réémise à l’identique retrouve son reçu minimal dans la chaîne privée, même après redatation ; des arguments ou un acteur différents sont refusés. Aucun texte n’est copié dans le cache générique d’idempotence.

Après redatation ou nouveau plan, les anciennes notes restent attachées à leur source et deviennent historiques ; le nouveau créneau ne reprend pas leur texte. Une note peut documenter un créneau courant marqué à reconfirmer, sans le reconfirmer. Les dates remplacées sont consultables sans formulaire d’écriture.

## Fichiers et routes

- `departments/m04-field-ops/src/m4_field_ops/annotations_calendrier.py` : logique pure, sources et historique.
- `registre.py` : type d’entrée ; `outils.py` : trois outils déterministes, stockage et identité SQL.
- `src/opsys/console/annotations_cedule_ui.py` : formulaires, détail, pagination, compteurs.
- `cedule_ui.py`, `crm_ui.py`, `metier.py` : intégration des cartes et port administratif.
- `src/opsys/capacites.py` : refus du port générique avant toute copie en approbation ou artefact.
- `GET /crm/cedule/annotations` : paramètres d’ancre explicites, historique borné.
- `POST /crm/cedule/annotations` : CSRF, texte ≤2 000 caractères, révision et intention.

Les pages d’historique contiennent 10 versions, avec plafond de révision stable. Les compteurs de la semaine sont chargés en un appel, sans les textes. Les sources ont une borne explicite de 10 000 maillons ; le dépassement ferme la lecture, sans silence ni perte de notes.

## Permissions, données et effets

Admin SQL actif et session console non expirée requis, y compris avant rejeu. Auteur et horodatage viennent du serveur. Texte échappé dans le HTML, pages privées sans cache, formulaires uniques et bornés. Journal d’audit limité aux références et révision. Ne pas y saisir de données médicales. Les appels MCP/agent sont fermés, sans nouveau droit de rôle, tant que la portée M10 et la protection du transport ne sont pas qualifiées.

Les notes ne changent ni assignation, dates, statut chantier, pointages, paie, facture, matériel, ni notification. Aucune publication M10 automatique. SQLite est le seul chemin d’écriture actuellement qualifiable : la sérialisation `BEGIN IMMEDIATE` englobe le contrôle de version et l’append, avec annulation commune de l’audit. PostgreSQL reste fermé en écriture.

## Tests et statut

Tests dédiés : `departments/m04-field-ops/tests/test_annotations_calendrier.py` et `tests/test_console_annotations_cedule.py`. Couverture attendue : sources exactes et falsifiées, redatation, report, versions, rejeu, autorité révoquée, CSRF, quotas avant append, échappement, concurrence et annulation après échec d’audit. Les résultats d’exécution sont consignés dans le checkpoint et son reçu QA, pas présumés par la présence des tests.

Qualification locale Linux : **106 cas PASS** pour primitive, console, calendrier et registre ; lot distinct de **59 cas PASS** pour contrats d’outils, horloge serveur et politiques. Ces lots ne sont pas additionnés aux populations des jalons précédents. Ruff et `python -B -m opsys.cli verifier` passent (269 outils, 173 portées d’appareil inchangées). Les premiers rouges restent conservés : garde du port direct corrigé, erreur de préfixe du harnais HTTP corrigée, lint corrigé.

Statut : **PARTIAL**, parcours HTTP/SQLite local vérifié. Restent navigateur réel, parcours PostgreSQL, portée agent/M10, personnalisation des couleurs, visites successives et mobile. Le préflight navigateur local précédemment refusé ne doit pas être rejoué avec désactivation du sandbox. Aucun gate Nathan supplémentaire pour la saisie privée réversible ; notifications et actions opérationnelles gardent leurs gates existants.


Évolution CRM-01 : les [repères couleur](COULEURS-CEDULE-M4.md) utilisent une collection séparée, sans détourner le texte des notes. Les formulaires de notes sont maintenant masqués sur les backends dont l’écriture n’est pas qualifiée ; la fermeture existante du writer PostgreSQL reste en place.
