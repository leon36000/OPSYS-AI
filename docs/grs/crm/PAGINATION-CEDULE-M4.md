# CRM-01 — Parcourir tout le carnet de la cédule

## Objectif et audit

La grille hebdomadaire doit permettre de retrouver les chantiers au-delà des 200 créneaux et 50 interventions sans date du contrat historique. Cette troncature était affichée, mais aucun lien ne donnait accès au reste. La nouvelle lecture administrative propose deux listes paginées indépendamment, sans transformer la navigation en nouvelle planification.

Réutilisation : instantané et contrôles de source de `apercu_mois.py`, projection civile M4, liens HTML et ports privés existants. Aucune nouvelle bibliothèque, table, portée d’appareil ni donnée externe.

## Architecture et données

`pages_semaine.py` est un module pur. `outils.py` adapte sa lecture au stockage existant. `cedule_ui.py` valide les pages et rend leurs liens ; `crm_ui.py` reçoit les paramètres et conserve le rattachement des cartes aux dossiers M2 réellement reconnus. Les badges de notes et de couleurs restent présents sur les cartes affichées.

Une page contient au plus 25 créneaux datés et 25 interventions sans date. Les deux offsets sont indépendants, multiples de 25 et bornés. Les totaux se rapportent respectivement à la semaine et à tout le carnet non daté : ils ne doivent pas être additionnés entre pages. Les dates sont triées par début, équipe et intervention ; les interventions sans date par identifiant.

La tête du registre principal accompagne les liens. Dès qu’une continuation est demandée, cette référence est obligatoire et comparée à l’instantané courant. Un changement de la source produit HTTP 409 avec un lien « Recommencer la lecture ». Aucune page n’est recalée silencieusement. La tête n’est pas un jeton d’accès : les permissions sont toujours vérifiées. Les notes et couleurs restent des lectures de présentation courantes dans leurs collections séparées.

## Routes et workflow

La route existante `GET /crm/cedule` accepte `debut_semaine`, `offset_interventions`, `offset_sans_date`, `source_attendue`. La semaine doit rester explicite avec une référence de source. Les paramètres répétés, inconnus, malformés ou hors borne sont refusés.

Elle appelle le nouvel outil privé `m4_lire_page_cedule_semaine`. L’ancien outil `m4_lire_cedule_semaine` conserve son contrat plafonné pour ses consommateurs existants. Les navigations entre semaines ou vers l’aperçu trois mois démarrent une nouvelle lecture ; les liens de page conservent la semaine, l’autre offset et la source.

Session admin active → instantané unique → validation de chaîne, projection et source → contrôle des offsets → page bornée → validation des totaux et de la longueur → résolution de 25 liens M2 maximum → badges → HTML privé. Aucun changement au calendrier, temps, facture, inventaire, notification ou mémoire M10.

## Permissions, limites et risques

L’outil n’accorde aucun nouveau droit d’appareil. Les appels génériques et profilés sont fermés ; le port console exige un admin actif. L’absence ou la corruption d’une source ne devient jamais une semaine vide. Les paramètres et contenus sont échappés. Une cellule vide signifie seulement qu’aucun créneau de cette page n’y figure.

Le registre est plafonné à 10 000 maillons. Un comptage SQL vérifie la limite avant la matérialisation de la liste ; la logique pure revérifie ensuite cet instantané. Ce patch ne qualifie ni une pagination SQL des maillons ni un coût constant. La résolution M2 reste une lecture par lead affiché. Les totaux de la vue multi-mois conservent leur propre sémantique par date de début. Les visites successives sur plusieurs jours et les disponibilités des équipes restent des travaux distincts.

Aucun nouveau gate Nathan pour cette lecture réversible. Les actions client, financières, RH et opérationnelles sensibles gardent leurs contrôles. Pas de synchronisation Google implicite.

## Tests et statut

Les preuves visent un carnet fictif supérieur à 200 créneaux datés et 50 non datés, entièrement parcouru sans doublon via HTTP et SQLite ; deux navigations indépendantes ; modification entre pages ; rejet d’une source périmée ; limites d’arguments ; rôles et ports privés ; absence d’écriture. Les tests du contrat historique sont conservés.

Qualification Linux locale : **307 PASS, zéro SKIP** dans le lot intégré ; **175 PASS, zéro SKIP** dans le lot de contrats outils/horloge/permissions. Les 306 cas de la version précédente et les anciennes tranches sont inclus ou recoupés : aucun cumul. Ruff et vérification des manifestes passent : 274 outils, 173 déclarés par rôle. Statut produit **PARTIAL** ; navigateur réel, parcours PostgreSQL, visites successives et mobile restent ouverts.


## Coût de lecture mesuré et correction

Un test HTTP SQLite a établi 27 lectures SQL complètes du principal pour seulement trois créneaux et une intervention sans date. Les badges notes/couleurs relisaient la source par intervention. Le principal est désormais matérialisé une fois pour ces lectures ; les collections de repères restent durables, avec leurs append, contrôle de révision et rollback inchangés. Le test exige au maximum six lectures et passe.

Le calcul d’index civil copiait aussi huit fois le registre pour trois interventions. Il réutilise maintenant le lecteur d’instantané existant de `cedule_tournees`, après validation de chaîne, sans changer les règles d’état ou d’assignation. Le test de régression exige une seule copie et compare les résultats à la projection métier existante.

Sous la même limite d’un cœur CPU, le parcours QA complet de 206 créneaux et 61 interventions sans date est passé de **108,43 s à 7,71 s** après cette seconde correction ; il comprend génération des données et navigation HTTP, ce n’est pas une mesure de latence de production. Le lot intégré est passé de 198,47 s à 43,78 s, avec un test de non-régression ajouté.

Les traces historiques restent conservées : premier budget QA de 180 s expiré sans JUnit final ; exécution suivante interrompue par signal 11 pendant une trace faulthandler, cause non établie ; lint initial corrigé ; deux régressions de coût d’abord rouges puis vertes. Ces incidents de qualification ne sont pas maquillés en succès produit. Le dernier lot s’exécute sans faulthandler, avec réseau fermé, HOME/TMP privés, source en lecture seule et ressources bornées. Revue indépendante statique des raccords : aucun défaut concret relevé.
