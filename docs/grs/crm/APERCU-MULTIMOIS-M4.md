# CRM-01 — Aperçu de trois mois depuis M4

## Objectif, audit et état

La secrétaire peut consulter trois mois côte à côte et ouvrir la semaine d’un jour choisi. Les comptes distinguent les dates internes confirmées et les dates anciennes à reconfirmer. Un jour vide ne prouve aucune disponibilité et une date interne ne confirme aucun rendez-vous client.

L’audit initial a identifié une projection hebdomadaire plafonnée à 200 créneaux et un carnet global sans dates plafonné à 50. Additionner ces réponses aurait répété les semaines chevauchant deux mois et les interventions non datées. Le patch réemploie les projections civiles M4 et leurs validations de source, depuis un seul instantané du registre principal. Aucune nouvelle dépendance, table ou application BI.

## Architecture, fichiers et données

- `departments/m04-field-ops/src/m4_field_ops/apercu_mois.py` : agrégation pure, calendrier civil et contrôle des ancres.
- `outils.py` : lecture SQL par le port privé administratif et quota de sortie.
- `src/opsys/console/mois_cedule_ui.py` : validation des compteurs et rendu HTML local ; raccords dans `crm_ui.py`, `cedule_ui.py`, `metier.py`, `ressources.py`.
- `src/opsys/capacites.py` : fermeture du nouvel outil aux appels génériques et profilés.

La source porte sa tête et son nombre de maillons. Les trois mois contiennent tous leurs jours, y compris les jours sans créneau. Chaque intervention courante compte une seule fois, à sa date de début dans le fuseau `America/Montreal`. La vue ne représente pas la durée d’occupation des chantiers sur plusieurs jours. Le nombre sans date concerne tout le carnet et apparaît une seule fois, séparément des totaux mensuels. Une redatation remplace la date courante ; un report conserve un avertissement à reconfirmer.

La limite de source est de 10 000 maillons, vérifiée dans la logique et après lecture SQL dans l’adaptateur. Ce dernier charge encore les maillons avant ce contrôle : la limite ne garantit donc pas une lecture SQL paginée ni une mémoire constante. Un registre trop volumineux ou incohérent est refusé. La sortie respecte aussi le quota du contexte. Aucun nom, adresse, téléphone, coût, GPS ou identifiant client ne figure dans l’aperçu.

## Routes, workflow et intégrations

`GET /crm/cedule/mois?premier_mois=AAAA-MM` appelle `m4_lire_apercu_mois`. Le premier mois doit être compris entre `1900-01` et `2199-10`, afin de rendre trois mois complets. La navigation avance ou recule d’un mois et la grille semaine propose un lien vers cet aperçu.

Session admin → instantané M4 → vérification de chaîne et projection → contrôles des sources exactes → agrégation → validation des jours et des sommes par le rendu → affichage et liens vers la semaine existante. Aucun append, audit de mutation, notification ou événement M10 n’est créé par cette lecture.

Un clic ouvre `/crm/cedule?debut_semaine=AAAA-MM-JJ`. Les liens dont la fin de semaine exclusive sortirait des bornes civiles sont désactivés. La grille hebdomadaire garde sa limite de 200 créneaux et son avertissement de troncature : son détail peut donc être partiel même quand le compteur mensuel inclut toute la population admissible. Une évolution de pagination reste nécessaire.

## Permissions, risques et gates

Admin actif et session valide requis ; aucun nouveau droit d’appareil. L’outil reste privé à la console. Les appels génériques/profilés sont refusés avant leur dispatch. Les pages ne sont pas mises en cache, les textes sont échappés et les arguments inattendus ou répétés sont refusés. Une réponse malformée produit une indisponibilité explicite, jamais un faux calendrier vide.

Les couleurs manuelles des cartes n’influencent pas les comptes. Orange et le texte « à reconfirmer » indiquent une date à revoir. Aucun score de performance ni disponibilité n’est inféré. Aucun nouveau gate Nathan pour la lecture ; les validations opérationnelles et financières restent inchangées. Pas de synchronisation Google, de nouvelle portée agent, de donnée réelle ou de notification implicite.

## Tests, statut et prochaines étapes

Tests dédiés : `departments/m04-field-ops/tests/test_apercu_mois.py` et `tests/test_console_mois_cedule.py`. Vraie chaîne SQLite et requêtes HTTP locales : chevauchements semaine/mois, changement d’année, années bissextiles, source corrompue, report, redatation, carnet sans date, absence de mutation, révocation admin, préfixe de console, limites civiles et refus du port générique. Les cas de réponse malformée injectée qualifient seulement le garde du rendu.

Lot intégré Linux : **261 PASS, zéro SKIP**, incluant les 213 cas antérieurs de calendrier/annotations/couleurs ; ces populations ne s’additionnent pas. Ruff et vérificateur des manifestes passent : 273 outils, 173 déclarés par rôle d’appareil. Revue indépendante statique des raccords : aucun défaut concret relevé ; elle ne remplace pas les tests.

Statut **PARTIAL** : aperçu trois mois HTTP/SQLite qualifié localement. Restent pagination du grand carnet, visites successives, validation visuelle dans un navigateur réel, parcours PostgreSQL et mobile. L’échec historique du sandbox navigateur reste conservé ; aucun contournement des protections n’est autorisé par ce document. La CI distante et la publication sont suivies dans le checkpoint du chantier, sans déduire une qualification globale de ces tests locaux.
