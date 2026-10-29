# M9.5 — salle de guerre quotidienne et briefing du matin

Statut : **GATED_NATHAN** (planification : hôte opérateur ; la matrice d'exigences le classe `PARTIEL`).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md) ·
[autorité cron](../../architecture/AGENTS-CRON-AUTORITE.md).

## Objectif

Donner chaque matin à Nathan, pour un instant qu'il fournit, l'état utile : couverture des sources et manques, risques
actifs et changements depuis la veille, décisions en attente, alertes M8, conseils en cours et recommandations à valider
par un humain — en lecture seule, sans planifier, exécuter ni décider.

## Pourquoi

Le briefing doit être exploitable sans être rédigé par un modèle : chaque élément vient d'une source nommée, une section
vide reste vide, et une page lue après un changement d'état ne doit jamais être recollée à l'ancienne.

## État actuel

Deux vues coexistent :

- **Briefing du matin** (historique, T3.2) : `briefing_matin.assembler_briefing_matin`, quatre sections ordonnées —
  `decisions_en_attente` (file du propriétaire, lue en entier), `alertes_m8` (reçues du bus, fenêtre de
  `fenetre_alertes_jours` = 3 jours dans `department.yaml`), `faits_veille` (snapshots consolidés de la veille),
  `manques_pour_conclure`. Borné sous `BUDGET_SORTIE` ; le reste se lit par `m9_lire_suite_briefing`.
- **Salle de guerre** (`m9_salle_de_guerre`, M9.5 du cahier) : vue calculée à la demande sur les 19 lectures du
  catalogue et les registres de M9.
- Planification : `department.yaml` déclare `briefing-du-matin` (`0 7 * * 1-5`), dont la consigne appelle
  `m9_produire_briefing_matin`. `opsys.openclaw` n'en tire qu'une ligne `openclaw automations add` dans la configuration
  générée ; aucun ordonnanceur n'est installé ni qualifié par M9, et aucun cron global n'existe.

## Architecture

Contenu de la salle de guerre (`outils_direction.salle_de_guerre`) :

- `couverture` : complète ou non, lectures non présentes, dénombrement par statut ; `manques` nommés ; nombre de
  contradictions ;
- `risques` : actifs, à reconfirmer, levés, règles non évaluées (risque inconnu, pas nul), cinq premiers, statut de la
  grille (`risques.evaluer`) ;
- `changements_depuis_la_veille` : risques apparus, levés, gravité changée entre `reference − 1 jour` et `reference`
  (`risques.delta`, chaque radar calculé sur ce que M9 connaissait à l'instant), captures reçues dans les 24 h ;
- `decisions_en_attente` (file du propriétaire), `alertes_m8` dans la fenêtre, conseils en cours (tours en attente ou en
  échec), recommandations closes dont une action exige une validation humaine ;
- `responsabilites` : « M9 propose ; toute décision sensible reste au propriétaire ; aucun effet ici ».

Listes bornées à `MAX_ITEMS_SALLE` = 5 avec totaux. **Vue périmée** : `vue` = empreinte du contenu et des têtes des
registres de captures et de sessions ; une relecture avec `vue_attendue` différente est refusée (`REJ-VUE-PERIMEE`,
« relire sans vue »).

## Fichiers

[briefing_matin.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/briefing_matin.py),
[outils_direction.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_direction.py),
[risques.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/risques.py),
`lecture_alertes.py`, `outils.py` (briefing, alertes M8), `department.yaml` (planification et fenêtre).

## Outils et pages de console

| Outil | Accès |
|---|---|
| `m9_salle_de_guerre` (`reference`, `vue_attendue`) | admin strict, agent refusé |
| `m9_produire_briefing_matin` (`maintenant`), `m9_lire_suite_briefing` | `_exiger_admin_pour_appareil` : admin d'appareil ou voie agent |
| `m9_lire_alertes_m8`, `m9_radar_risques` | lecture bornée et paginée |

Page `/direction` : formulaire sans date préremplie (connaissance + jour civil), puis panneaux indépendants « Briefing —
salle de guerre », risques, indicateurs, prévisions, plans, actions, veille ; un panneau refusé affiche son code sans
masquer les autres. `/direction/risques` détaille le radar (péremption `perime_apres_jours` facultative).

## Données et registres

Lecture de `captures_strategiques`, `sessions_conseil`, `snapshots`, `alertes_m8` et de la file `approbations` du
socle. Rien n'est écrit par ces outils.

## Workflows

1. L'admin saisit l'instant de connaissance et le jour civil (M9 n'a pas d'horloge).
2. La salle de guerre et les panneaux se calculent ; les manques sont nommés.
3. Pour paginer ou rafraîchir sans changer de monde, repasser la `vue` ; si l'état a changé, relire depuis le début.

## Intégrations

Bus M8 (`m8.alerte_proposee`, `m8.snapshot_chantier`), file d'approbation native (`approbations.file_proprietaire`),
registres de conseil. Planification prévue par les grants/remises cron natifs (`opsys.agents_cron_autorite`), appelés
par l'hôte opérateur authentifié.

## Risques

- La consigne planifiée appelle le briefing, pas la salle de guerre : un agent planifié ne verrait pas la salle de
  guerre (admin strict), seulement le briefing historique.
- La fenêtre des alertes et la grille de gravité sont des réglages proposés, non des seuils d'affaires validés.
- Une salle de guerre sans captures récentes reste correcte mais pauvre : la valeur dépend des captures faites.

## Gates Nathan

Qualification de la planification : grants cron réels créés par l'hôte opérateur (installation, exécution matinale
observée). Décider si la salle de guerre doit être produite par l'agent planifié (et sous quelle identité).

## Tests

`departments/m09-strategic-intelligence/tests/test_briefing_matin.py`, `test_briefing_borne.py`,
`test_briefing_capacites.py`, `test_configuration_briefing.py` (fenêtre de trois jours), `test_risques.py` (delta apparu,
levé, gravité) ; `tests/test_m9_direction_integre.py` (couverture, manques, vue périmée refusée, rôles retirés) ;
`tests/test_console_direction_m9.py` (tableau de bord : risques actifs, changements depuis la veille, aucune date
fabriquée).

## Statut

GATED_NATHAN : vues livrées et vérifiées en processus et en navigateur ; planification non qualifiée.

## Prochaines étapes

1. Hôte opérateur : créer le grant cron du profil M9 et observer une exécution réelle.
2. Aligner la consigne planifiée sur la salle de guerre ou documenter pourquoi le briefing suffit.
3. Écran mobile admin (phase mobile, contrat `CONTRAT-MOBILE-ADMIN-M9.md`).
