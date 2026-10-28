# CRM-08 — du devis accepté à l’intervention M4 : audit avant raccord

27 octobre 2026, source `8b1c3c741bf9ad98a2557c516f9661da606af826`.
Revue indépendante de texte puis rapprochement ROOT des fonctions et contrats cités.
Aucun nouveau parcours d’acceptation/planification exécuté ou livré par cet audit.
Statut CRM-08 : **PARTIAL**, chaîne départementale existante, raccord au dossier à construire.

## Besoin du secrétariat

La soumission acceptée doit mener au bon de travail et à la cédule, avec ses matériaux et
sa préparation réels. L’interface sert à consulter et intervenir sous les mêmes gardes que
les agents. Un statut accepté ne prouve ni la réception de son événement par M4, ni le stock,
ni la disponibilité d’une équipe à une date civile.

## Réutilisation et sources

- M3 `outils.marquer_devis_accepte` compose transition et événement déterministe
  `m3.devis_accepte`. C’est un outil T3, avec revue d’acceptation N5 et décision humaine.
  Un bouton admin ne doit pas le contourner par un appel direct de domaine.
- M2 `_recevoir_devis_accepte` convertit le dossier et propose `planifier`, sans date promise.
- M4 `_recevoir_devis_accepte` et `etats.inscrire_depuis_devis` créent `a_planifier`.
  `etats.intervention_du_devis` retrouve l’intervention exacte, sans deuxième bon de travail.
- Service, ville et urgence proviennent du fait M1 exact. Un dossier saisi dans M2 sans cette
  source peut laisser la réception M4 en quarantaine. Ne pas fabriquer un événement M1.
- M6 `_recevoir_devis_accepte` transforme les références de besoin matériau en besoins et
  réservations réels, puis `m6.materiel_pret` si les conditions le permettent. Un livre de
  prix connu ne prouve pas la présence du matériel. Un prévu vide peut rester non vérifiable.
- M4 `preparation.evaluer` porte les volets soumission, adresse confirmée, équipe, matériel
  et règles météo. Non vérifiable n’est pas prêt; les règles météo ne sont pas une prévision.
- `cedule_tournees.proposer/appliquer` distingue proposition et affectation et relit les
  sources lors de l’application. Réutiliser ce chemin pour une intervention `a_planifier`.

Le vieux `m4_planifier_intervention` inscrit directement une intervention `planifiee` et
refuse le doublon du bus. Ce n’est pas le raccourci de ce nouveau parcours CRM-08.

## Interface existante et première tranche

`console/crm_ui.py::{soumission,contenu_soumission}` affiche le devis et ses documents.
Raccorder une lecture admin « Préparer la planification » uniquement après lecture exacte
du devis M3 accepté. La vue résout le lien lead/devis/intervention et expose la préparation
par volet, les matériaux sans coûts et l’état réel de réception du bus. Distinguer attente,
source M1 manquante/quarantaine, intervention absente, lecture indisponible et préparation
bloquée. Un GET ne livre pas le bus et ne répare aucune source.

Le port sera privé à la console admin, rôle SQL réévalué; aucune portée MCP/appareil ajoutée.
Il ne prendra pas un identifiant de devis fourni comme preuve de son acceptation. Les lectures
M3/M4 appartiennent à leurs propriétaires, composées par le socle. Sortie bornée, contacts et
coûts exclus de la projection terrain. Les contrats/API historiques restent compatibles.

Ensuite seulement : proposer sur la liste exacte `[intervention_id]`, présenter équipes,
non-cédulés et explications, puis appliquer par l’admin identifié sous les CAS existants.
Une modification de matériel, adresse, équipe, profil ou source après aperçu doit refuser
la nouvelle action sans écriture. Le reçu historique d’un rejeu n’est pas une nouvelle
affirmation de disponibilité.

`console/cedule_plan_ui.py` porte déjà le détail d’un plan appliqué et les dates civiles.
`calendrier_civil.confirmer` relit état, équipe, ancre/révision et conflits datés, mais ne
réévalue pas préparation/météo. Avant de promettre une confirmation finale CRM-08, qualifier
la politique et la relecture actuelles pour le créneau : une préparation ancienne sur GET
ne suffit pas. Ne pas présenter un calendrier interne comme une notification au client.
L’acceptation commerciale reste un parcours humain séparé, à qualifier si son écran est ajouté.

## Preuves à réutiliser et à compléter

`tests/test_cascade_devis_accepte.py` prouve sur vrai bus la conversion M2, M4 `a_planifier`,
les reprises et la source M1 absente. Les tests M4 `test_consommer_devis_accepte.py`,
`test_cedule_tournees_outils.py` et `test_cedule_tournees_profil.py` couvrent les primitives.
Attention : leur fixture `futurs_ok` remplace deux volets; elle n’est pas une intégration
réelle de stock et de prévision. Les E2E `test_materiel_pret_appareil.py` et
`test_meteo_bloquante_appareil.py` réutilisent HTTP/bus/stock réels avec prévision manuelle,
sans fournisseur météo distant ni Core complet démontré. Les dates civiles ont leur cohorte
HTTP/SQLite dans `tests/test_console_dates_cedule.py`.

Pour la première tranche : vrai devis accepté → vrai bus → intervention existante → vue
HTTP de préparation, GET sans effet sur toute la base. Tester lien étranger, devis non
accepté, source manquante, bus pending/quarantaine, sortie excessive et rôle révoqué; aucun
bouton d’action si l’ancre n’est pas complète. Puis qualifier les POST proposition/application
et confirmation avec matériel retiré entre lectures, conflit daté, CSRF, rejeu, audit rollback
et aucune promesse/envoi. Données fictives, homes/tmp privés, Source en lecture seule pendant QA.

Gates inchangés : argent, acceptation commerciale sensible et actions externes humaines;
pas de permission supplémentaire pour préparer ce raccord. M4 complet, VRP/GPS/mobile,
CRM-08 complet et OPSYS complet ne sont pas déclarés par cet audit.


## Jalon exécuté — lecture privée de préparation (27 octobre 2026)

Le lien « Préparer la planification » apparaît maintenant sur la fiche d’un devis M3 accepté.
`src/opsys/console/preparation_chantier.py` compose la lecture admin privée sur
`GET /crm/lead/{lead_id}/soumissions/{devis_id}/preparation-chantier` (préfixe console éventuel).
`crm_ui.py` raccorde ce lien et le routeur. Aucun POST, nouvel outil, portée appareil ou
raccourci d’acceptation commerciale n’est ajouté.

Le rôle admin SQL et l’expiration sont revérifiés avant les sources. La lecture exige le lien
M2 lead/devis, le devis M3 réellement accepté et la charge canonique publiée par M3; elle réutilise
la composition du propriétaire pour la durée estimée optionnelle, sans qualifier ici une nouvelle
E2E de cette variante. Elle distingue publication absente, réception en attente, échec,
quarantaine et reçu traité. Elle vérifie la chaîne M4, l’inscription unique du devis et le reçu
exact; elle lit l’état courant par les fonctions M4, sans rejouer toutes les interventions une
à une. Pour une inscription née du bus, elle compare l’instant d’acceptation et les champs M1
schema/service/urgence, ainsi que la ville tokenisée avec la clé existante uniquement lue.
Une inscription manuelle ou une source M1 absente ne produit pas une ancre bus complète.
Une contradiction refuse la lecture plutôt que d’afficher un chantier prêt.

La préparation est le verdict courant de `m4_verifier_preparation` : soumission, adresse,
équipe, matériel et règles météo. Le GET ne livre pas le bus, ne répare pas une quarantaine,
ne crée pas de clé et ne confirme aucun créneau. La projection de devis est celle du propriétaire
pour l’employé : quantités, unités, descriptions et références matériaux, sans coûts/marges ni
contacts. Les sources sont bornées avant décodage; sorties JSON/HTML bornées et réponse no-store.

### Qualification et limites

`tests/test_console_preparation_chantier.py` passe sur TestClient et SQLite migrée avec vrais
outils, vrai bus M1→M2→M3→M4 et vraie préparation M4. Une réception réelle M6 rend le volet
matériel disponible; la libération réelle de réservation le retire à la lecture suivante.
Chaque GET testé conserve l’instantané de toute la base. Liens étrangers, brouillon, révocation,
expiration, lecture non admin, corruption publication/reçu/chaîne, intervention absente, sources
trop volumineuses et petit quota de sortie sont refusés. Aucune acceptation via nouvelle UI,
navigation navigateur, PostgreSQL, prévision distante ou installation complète démontrée.

Preuves privées du chantier `crm-prefill-qa-20261027-r1` : baseline `crm08-view-red-v1`
(404 attendu avant code), `crm08-view-v1` (165 tests passent, deux erreurs de style conservées).
La revue indépendante a détecté une provenance M1/M4 insuffisante; `crm08-source-red-v1`
reproduit deux HTTP 200 au lieu du refus attendu (service/urgence). La fixture service utilise
ensuite le code déclaré `revetement`; la régression urgence demeure inchangée. Après correction,
`crm08-view-v2` : **168 PASS, 0 FAIL, 0 SKIP, 28,93 s**, Ruff et vérificateur des 297 outils /
173 portées déclarées passent. Les cohortes se recoupent et ne sont pas additionnées.
Revue complémentaire statique indépendante : aucun constat supplémentaire sur le correctif.
Homes/tmp privés avant imports, Source en lecture seule, réseau bloqué, 1 CPU/1 Gio/96 tâches,
commandes, limites effectives, JUnit, empreintes et reçus distincts conservés.

Statut **PARTIAL** : cette première vue est qualifiée localement. Proposition/application de
cédule depuis cette fiche, confirmation civile avec préparation et prévision du créneau relues,
acceptation commerciale humaine et notifications restent des capacités distinctes à raccorder.
