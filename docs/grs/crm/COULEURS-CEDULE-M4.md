# CRM-01 — Couleurs administratives des créneaux

## Objectif, audit et état

La secrétaire choisit un repère de couleur sur une carte de chantier et retrouve ses modifications. La couleur est un repère administratif partagé, sans signification automatique de statut, de service, de performance ou de disponibilité. La règle de classement par équipe/service reste inconnue : cette tranche permet le choix manuel, sans la deviner.

Avant ce patch, la grille utilisait seulement une bordure bleue de date interne confirmée et une bordure orange de créneau à reconfirmer. Aucun réglage de couleur par chantier n’existait sur la surface inspectée. CRM02 fournit déjà la validation du créneau exact, les révisions et le stockage privé. Ces briques sont réutilisées : aucune dépendance externe ni table nouvelle.

## Architecture, fichiers et données

- `departments/m04-field-ops/src/m4_field_ops/couleurs_calendrier.py` : logique pure, palette et historique. Réemploie les validations d’ancre/source de `annotations_calendrier.py`.
- `registre.py` : type explicite `couleur_calendrier` ; `outils.py` : adaptateur SQL, auteur, heure serveur, intention et audit.
- `src/opsys/console/couleurs_cedule_ui.py` : lecture, formulaire, historique et badge ; raccords dans `crm_ui.py`, `cedule_ui.py`, `ressources.py`, `metier.py`.
- `src/opsys/capacites.py` : fermeture des ports génériques et profilés avant approbation ou copie d’arguments.

Les préférences du cockpit vivent dans la collection de présentation `couleurs_calendrier`, distincte des notes et du registre opérationnel M4. Aucun statut, plan, pointage ou coût n’y est réécrit. L’ancre est le quadruplet `intervention_id`, `plan_id`, `source_application_id`, `source_ligne_id` : les dates et l’équipe sont relues depuis la source réelle.

Palette fermée : sans repère, bleu, violet, vert, rose, ambre, gris. Aucune valeur CSS/HTML fournie par le navigateur. Le marqueur et son nom sont visibles ensemble ; la bordure et le texte de validité du créneau restent indépendants. Choisir vert sur un chantier reporté conserve « Reporté » et « À reconfirmer ».

## Routes, outils et workflow

- `GET /crm/cedule/couleurs` : ancre exacte, historique de 10 versions par page, plafond stable de révision.
- `POST /crm/cedule/couleurs` : CSRF, jeton de palette, révision attendue et intention.
- `m4_definir_couleur_calendrier`, `m4_lire_couleurs_calendrier`, `m4_resumer_couleurs_calendrier` : ports privés de la console.

Carte → détail du créneau → choix → contrôle d’identité/source/version → append et audit dans une transaction → reçu minimal → nouvelle lecture. Le choix « sans repère » retire le marquage courant, tout en conservant l’historique. Les compteurs de révision sont propres à chaque intervention. Après redatation, aucun transfert implicite : l’ancienne couleur reste lisible sur son ancien créneau ; le nouveau commence sans repère.

Deux éditeurs partant de la même révision ne s’écrasent pas. La réémission exacte d’une intention retrouve son reçu, même après redatation ; changer ses arguments ou son acteur est refusé. Le contrôle de quota précède l’append. Les historiques et sources sont bornés à 10 000 maillons ; un dépassement est explicite.

## Permissions, intégrations et limites

Admin SQL actif et session console valide requis. Auteur et horodatage sont dérivés du serveur. Pages privées sans cache, chaînes échappées, formulaires stricts. Aucun changement de droits d’appareil : les nouveaux outils restent fermés au MCP/agent jusqu’à qualification de leur portée. Pas de notification ni de mémoire M10 automatique. Les audits contiennent références et révision, sans reproduire les notes privées.

L’écriture SQLite utilise le verrou transactionnel existant et annule le changement si le journal d’audit échoue. PostgreSQL reste fermé en écriture ; la console masque les formulaires non qualifiés de notes et de couleurs. La vérification de cette fermeture d’interface ne constitue pas un E2E PostgreSQL.

Aucun gate Nathan nouveau pour ce repère réversible. Les validations opérationnelles, financières et RH restent celles des départements concernés. Aucune couleur ne vaut approbation humaine d’une action sensible.

## Tests et statut

Tests dédiés : `test_couleurs_calendrier.py` et `tests/test_console_couleurs_cedule.py`. Parcours HTTP avec vraie chaîne SQLite : choix/retrait/historique, source exacte, redatation sans transfert, report préservé, deux éditeurs, rejeu, rôle révoqué, CSRF, palette malformée, source forgée, quota avant écriture et rollback d’audit.

Qualification Linux locale : lot intégré final **213 PASS**, sans SKIP, incluant notes, couleurs, calendrier et contrats M4 touchés ; Ruff et vérification des manifestes passent. Le lot distinct de régression outils/horloge/politiques est **59 PASS**. Les 145 cas de la première exécution fonctionnelle sont inclus dans les 213 : ne pas les additionner. L’échec de préparation du premier harnais n’a importé aucun produit ; le lint initial et les rouges CI antérieurs restent conservés.

La CI du commit précédent a révélé une régression d’ordre du catalogue d’outils et un catalogue de types non actualisé. Le patch restaure les quatre outils historiques de fin de liste et déclare explicitement les deux types privés dans le test d’énumération exacte. Les trois tests CI concernés passent localement dans le lot final ; leur CI distante suivante reste à observer.

Statut **PARTIAL** : couleur par créneau utilisable en HTTP/SQLite local, sans validation visuelle navigateur. Restent vue multi-mois, visites successives, pagination du grand carnet, PostgreSQL, portée agent/M10 et mobile. Le navigateur local dont le sandbox a échoué ne doit pas être relancé avec protection désactivée. Prochaine capacité : vue multi-mois sourcée par le calendrier M4, après audit des bornes de lecture.

Évolution suivante : [aperçu trois mois](APERCU-MULTIMOIS-M4.md) qualifié en HTTP/SQLite. Ses comptes de validité restent indépendants des couleurs manuelles.
