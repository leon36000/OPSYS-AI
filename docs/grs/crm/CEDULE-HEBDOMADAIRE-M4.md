# CRM-01 — Dates civiles de la cédule M4

## Audit initial ciblé
Source auditée : cfbed5e3, 2026-10-27. Complète les audits M4 existants et EXIGENCES-SECRETARIAT-3EN1, section 3.1.
`cedule_tournees.proposer/appliquer` conserve routes, jour numérique, minutes, assignations et empreintes dans le registre M4. `etats.lister_interventions` rend encore `fenetre_planifiee: None`. Le calendrier de `meteo_creneaux` est un argument de lecture non persisté. Aucun jour civil ne peut être déduit de ces faits. Le tableau semaine demandé par le secrétariat nécessite cette source avant sa présentation graphique.

## Objectif et patch minimal
Réutiliser le registre chaîné M4, les tournées existantes, les identités SQL et datetime/zoneinfo. Aucun nouveau solveur, calendrier externe ou framework. Ajouter une confirmation administrative explicite des dates d'un plan déjà appliqué et une lecture de semaine. Les jobs sans date restent explicitement non datés. Aucune migration des anciennes tournées par supposition.

## Contrat et gouvernance
Deux outils M4 : `m4_confirmer_dates_cedule` (plan_id, calendrier jour→date ISO, revision_attendue), `m4_lire_cedule_semaine` (debut_semaine ISO lundi). Fuseau America/Montreal. Identité admin active relue en base; aucun auteur libre, aucun agent anonyme pour confirmer. Première écriture revision 1, révisions suivantes append-only avec contrôle de concurrence. SQLite durable uniquement pour l'écriture tant que PostgreSQL n'est pas qualifié. Horodatage serveur.
Toutes les journées comportant des visites doivent être datées exactement une fois, en ordre strict. Créneaux inexistants/ambigus au changement d'heure ou durée UTC différente refusés. Plan proposé seul, plan remplacé, intervention non planifiée ou réassignée : refus. Chevauchement connu de la même équipe : refus avant écriture.
La lecture expose le dernier plan appliqué, les dates avec références de registre et statuts actuels. Report, annulation ou réassignation après datation invalident le créneau; le retour à planifiée ne ressuscite pas une ancienne date. La dernière date périmée reste lisible comme historique, sans promesse ; les anciennes révisions demeurent au registre, sans écran historique livré dans cette tranche. Une nouvelle confirmation est nécessaire. Les révisions demeurent au registre.
Cette confirmation date une planification interne; elle n'atteste ni l'accord client, ni la météo, ni le matériel. Aucun envoi client, paie, facture, dispatch réel. Disponibilités externes et temps de trajet entre deux plans distincts non prouvés : avertissement explicite, jamais affirmation de faisabilité globale.

## Données, intégrations, permissions
M4 reste propriétaire : plans, équipes, interventions, statuts. Aucun nom, téléphone, adresse, prix ou GPS dans la projection. M2 garde les fiches clients. Pas d'écriture M10 ou notification inventée. La tranche serveur ne livre pas d’UI. La tranche interface décrite ci-dessous ajoute ensuite la grille web ; couleurs personnalisées, notes ancrées aux cartes, visites réelles multiples et mobile restent ouverts.

## Tests et statut
Qualifié localement sur données fictives : parcours vrai solveur DP → application → datation → semaine; absence/proposition seule; révisions périmées; dates invalides/DST; conflit équipe; report/annulation/réassignation; identité active/admin/agent; relecture durable SQLite. Données fictives, source en lecture seule, réseau entièrement fermé dans le harnais privé. Statut de la fondation serveur : PARTIAL ; interface traitée séparément ci-dessous. 31 tests ciblés passent, dont le vrai parcours durable de six chantiers, une course entre deux confirmations (une seule révision écrite), le rejeu d’idempotence après révocation admin et les refus sans écriture. PostgreSQL, navigateur et MCP transport non qualifiés.

## Prochaine étape
Fondation réalisée, puis grille en lecture seule réalisée ci-dessous. Prochaine étape : une surface administrative de confirmation des dates, après lecture des jours et révisions du plan appliqué, sans reconstruire M4.

## Fichiers et preuve
- `departments/m04-field-ops/src/m4_field_ops/calendrier_civil.py` : dates, DST, révisions, conflits et projection.
- `outils.py` / `registre.py` dans le même module : contrat, identité active, transaction durable, nouveau fait `cedule_datee`.
- `src/opsys/capacites.py` : revalidation admin avant retour d'un reçu en cache.
- `test_calendrier_civil.py`, `test_calendrier_civil_outils.py`, catalogue fermé de `test_registre.py` : tests reproductibles.
- Preuves locales hors dépôt : `work/chantier-opsys-20261010/crm-root-qa-20261027-r1/calendar-sql-final-v1-*`, JUnit et qualification dans `crm-calendar-20261027-r1`. Les échecs précédents restent conservés : import de fixture incompatible avec pytest importlib, commande de vérification erronée (`opsys` au lieu de `opsys.cli`), fixture de conflit incomplète et catalogue attendu à étendre explicitement. Aucun de ces échecs n'est masqué.

## Limites et prochaines évolutions
Bornes : dates 1900–2199, 200 créneaux et 50 interventions sans date par réponse, troncature et totaux visibles. Ajouter pagination avant d'afficher un gros carnet comme complet. Le contrôle de conflit couvre les chevauchements de visites confirmées connues d'une équipe ; il ne qualifie ni les trajets entre plans, ni congés, ni horaires externes. Les jours non datés empêchent toute affirmation de disponibilité globale. Un plan dont certaines interventions sont commencées ou annulées ne peut être redaté en bloc : proposer un nouveau plan pour les interventions restantes. Pas de notification ni confirmation client implicite.

## Tranche interface — audit avant modification
Le serveur qualifié r2912 expose les dates, mais `console/metier.py` ne les autorise pas encore et `crm_ui.py` ne contient aucune grille. Réutiliser ces surfaces avec un rendu HTML local sans JavaScript : `/crm/cedule`, semaine lundi→dimanche et fuseau Montréal. La semaine courante par défaut sélectionne une vue, sans dater aucun chantier. Un dossier n’est lié que si M2 le reconnaît. Les cellules vides ne représentent jamais de la disponibilité ; les créneaux à reconfirmer, le carnet sans dates et toute troncature restent visibles. Les couleurs représentent des statuts avec texte, pas encore des préférences personnalisées. Qualification prévue : vraie chaîne SQLite M4/M2→console TestClient, rôles révoqués, XSS, navigation et aucune écriture au registre. Le navigateur réel reste hors preuve de cette tranche.

## Tranche interface — résultat vérifié localement
`GET /crm/cedule?debut_semaine=2030-06-03` (exemple fictif) rend une grille équipes × sept jours, navigation semaine précédente/suivante/courante et sélection d’un lundi. L’heure affichée est celle de Montréal. Le lien est accessible depuis le répertoire CRM. Bleu = date interne confirmée ; orange = ancien créneau à reconfirmer, toujours accompagné du libellé. L’équipe actuelle reste consultable dans les références si l’affectation a changé. Une cellule vide ne signifie jamais « libre » et seules les équipes portant un créneau sont affichées.

Les cartes présentent les heures prévues, le statut courant, la révision et les références M4. Un lien vers le dossier n’est créé qu’après résolution par M2 ; un chantier orphelin affiche « Dossier M2 non relié ». Le carnet sans dates est distinct de la semaine, avec compteurs et avertissement si la lecture est tronquée. Aucun contact, prix ou GPS n’est copié dans la projection.

Fichiers : `src/opsys/console/cedule_ui.py` (rendu pur), `crm_ui.py` (route et liens M2), `metier.py` (lecture fermée au rôle admin actif), `ressources.py` (CSS local). Aucun CDN, JavaScript ou style en ligne ajouté. La page ne propose aucune écriture, notification ou dispatch.

Preuve : 12 tests ciblés `tests/test_console_cedule.py`, inclus dans une population de 113 tests console/CRM tous verts (ne pas additionner ces populations). Vrai registre SQLite, inscription/localisation/proposition/application/datation M4, lecture console et résolution M2. Comparaison de toute la base avant/après GET ; révocation admin et owner sans admin refusés ; rôle owner+admin conservé correctement ; navigation, validation de date, report puis retour à planifiée, échappement HTML et troncature. Une source sans fuseau provoque 503, jamais une fausse semaine vide. Ruff et vérificateur de manifestes passent. Le test d’erreur de source et celui d’injection HTML sont explicitement des tests de frontière, pas une preuve de panne réelle.

Preuves locales : `work/chantier-opsys-20261010/crm-weekgrid-20261027-r1/`, harnais `crm-root-qa-20261027-r1/weekgrid-*`. Rouge initial : route absente ; premier vert fonctionnel suivi de corrections de lint ; historique conservé. Aucun navigateur réel, mobile ni PostgreSQL qualifié. Aucune publication tant que la CI du lot précédent reste pending.

### Reste à faire pour CRM-01
Formulaire de confirmation/redatation des plans avec lecture des jours source, CSRF et révision attendue ; couleurs personnalisées indépendantes des statuts ; vue multi-mois ; visites multiples et historique de déplacement ; pagination au-delà de 200 créneaux/50 non datés ; revue visuelle et E2E navigateur. La résolution des dossiers est bornée à 200 leads distincts mais reste une lecture par lead : mesurer et grouper avant de qualifier un grand carnet. Cette livraison ne certifie pas la disponibilité globale des équipes.
