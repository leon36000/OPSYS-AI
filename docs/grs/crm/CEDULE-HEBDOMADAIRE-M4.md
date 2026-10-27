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
M4 reste propriétaire : plans, équipes, interventions, statuts. Aucun nom, téléphone, adresse, prix ou GPS dans la projection. M2 garde les fiches clients. Pas d'écriture M10 ou notification inventée. UI web, couleurs, notes, visites réelles multiples et mobile : étapes ultérieures, non livrées par cette tranche.

## Tests et statut
Qualifié localement sur données fictives : parcours vrai solveur DP → application → datation → semaine; absence/proposition seule; révisions périmées; dates invalides/DST; conflit équipe; report/annulation/réassignation; identité active/admin/agent; relecture durable SQLite. Données fictives, source en lecture seule, réseau entièrement fermé dans le harnais privé. Statut PARTIAL : source serveur réelle, interface hebdomadaire non livrée. 31 tests ciblés passent, dont le vrai parcours durable de six chantiers, une course entre deux confirmations (une seule révision écrite), le rejeu d’idempotence après révocation admin et les refus sans écriture. PostgreSQL, navigateur et MCP transport non qualifiés.

## Prochaine étape
Implémenter et qualifier la source civile, puis brancher une grille équipes×jours dans la console sur cette lecture, sans reconstruire M4.

## Fichiers et preuve
- `departments/m04-field-ops/src/m4_field_ops/calendrier_civil.py` : dates, DST, révisions, conflits et projection.
- `outils.py` / `registre.py` dans le même module : contrat, identité active, transaction durable, nouveau fait `cedule_datee`.
- `src/opsys/capacites.py` : revalidation admin avant retour d'un reçu en cache.
- `test_calendrier_civil.py`, `test_calendrier_civil_outils.py`, catalogue fermé de `test_registre.py` : tests reproductibles.
- Preuves locales hors dépôt : `work/chantier-opsys-20261010/crm-root-qa-20261027-r1/calendar-sql-final-v1-*`, JUnit et qualification dans `crm-calendar-20261027-r1`. Les échecs précédents restent conservés : import de fixture incompatible avec pytest importlib, commande de vérification erronée (`opsys` au lieu de `opsys.cli`), fixture de conflit incomplète et catalogue attendu à étendre explicitement. Aucun de ces échecs n'est masqué.

## Limites et prochaines évolutions
Bornes : dates 1900–2199, 200 créneaux et 50 interventions sans date par réponse, troncature et totaux visibles. Ajouter pagination avant d'afficher un gros carnet comme complet. Le contrôle de conflit couvre les chevauchements de visites confirmées connues d'une équipe ; il ne qualifie ni les trajets entre plans, ni congés, ni horaires externes. Les jours non datés empêchent toute affirmation de disponibilité globale. Un plan dont certaines interventions sont commencées ou annulées ne peut être redaté en bloc : proposer un nouveau plan pour les interventions restantes. Pas de notification ni confirmation client implicite.
