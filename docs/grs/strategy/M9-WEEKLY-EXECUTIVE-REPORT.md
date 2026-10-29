# M9.6–7 — revues hebdomadaire, mensuelle et trimestrielle

Statut : **DONE_VERIFIED** (M9.6 et M9.7). [Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) ·
[salle de guerre](M9-DAILY-WAR-ROOM.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Publier, pour une période civile, la revue de direction telle que M9 la connaissait à la fin de la période : vingt
sections de direction, couverture des sources, contradictions, décisions du conseil, arrivées tardives — en versions
immuables, reproductibles et datées par des bases temporelles explicites.

## Pourquoi

Une revue réécrite après coup ne prouve plus rien. Le cahier demande un rapport hebdomadaire et des revues mensuelle et
trimestrielle reliés à leurs versions de sources, sans reconstruction historique non observée et sans chiffre produit
par M9.

## État actuel

- Granularités `hebdomadaire` (semaine ISO, lundi), `mensuelle`, `trimestrielle` ; fuseau IANA demandé (ex.
  `America/Toronto`), heure d'été comprise (`REJ-REVUE-FUSEAU`, `REJ-REVUE-GRANULARITE`, `REJ-REVUE-ANCRE`).
- 20 sections (`rapport_direction.SECTIONS`, version `2026-10-29.1`) : résumé ; revenus, cash et marge ; pipeline et
  ventes ; estimations et soumissions ; production et cédule ; inventaire et fournisseurs ; marketing et visibilité ;
  clients et satisfaction ; risques ; opportunités ; ce qui a fonctionné (mesuré) ; ce qui a échoué (mesuré) ; leçons
  apprises (déclarées) ; décisions à prendre ; plan de la période suivante ; objectifs mesurables ; actions par
  département ; prévisions des propriétaires à 4 et à 13 semaines ; recommandations stratégiques.
- Chaque section : `RENSEIGNEE`, `PARTIELLE` ou `NON_DISPONIBLE` (ce qui manque, qui le possède) ; jamais un zéro.
- Pas d'envoi externe : la publication reste dans le registre de M9.

## Architecture

- `revue_periodique.composer(...)` : refuse une connaissance antérieure à la fin de période (`REJ-REVUE-PRECOCE`) et un
  instant sans fuseau (`REJ-REVUE-TEMPS`). Tout est calculé à la **fin** de la période sur `connues_a(captures, fin)` ;
  bornes de période `MAX_CAPTURES_PERIODE` = 2 000 (`REJ-REVUE-BORNE`).
- **Bases temporelles** (écrites dans la revue) : période `[début, fin)` en heure locale ; captures rattachées par leur
  réception (`recu_a`) ; sessions par leur réception ; étendue métier déclarée citée seulement pour son chevauchement ;
  arrivées tardives = reçues après la fin et chevauchant la période.
- `tendances_de_la_connaissance` : écart avec la période précédente (captures reçues, refusées, sessions ouvertes et
  closes, contradictions, lectures non présentes) — tendances de ce que M9 sait, pas de l'entreprise.
- `rapport_direction.sections(...)` : faits cités (adresse + texte exact d'une capture complète), dénombrements, état des
  registres de M9 (plans, actions, expériences, conseils), radars, indicateurs et prévisions des propriétaires. « Ce
  qui a fonctionné/échoué » ne reprend que des résultats mesurés ; « leçons » seulement des déclarations.
- `revue_id` = empreinte du contenu sans l'instant de connaissance : republier sans rien de nouveau est un rejeu.
- **Versions immuables** (`publier`, schéma `opsys.m9.publication_revue/v1`) : une nouvelle publication de la même période
  ajoute la version `n + 1`, cite `remplace_version` et compte `arrivees_tardives_ajoutees` ; l'ancienne reste intacte.
  Publication datée avant la connaissance : refusée.

## Fichiers

[revue_periodique.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/revue_periodique.py),
[rapport_direction.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/rapport_direction.py),
[outils_direction.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_direction.py).
Historiques réutilisés : `rapport_periode.py` (`m9_rapport_periode`), `rapport_activite.py`
(`m9_rapport_activite_periode`), `bilan_suivis.py`.

## Outils et pages de console

| Outil | Rôle | Autonomie |
|---|---|---|
| `m9_apercu_revue` | compose sans publier, par tranches | T0 |
| `m9_publier_revue` | ajoute une publication (ou rejeu) | T1 / N2 |
| `m9_lister_revues` | pages bornées, plus récente d'abord, `vue` | T0 |
| `m9_lire_revue` | une publication par tranches | T0 |

Admin strict. Pages `/direction/revues` (liste filtrable par granularité, page suivante avec `vue`) et
`/direction/revue?index=…` (lecture par tranches). La publication n'a pas de formulaire de console (non livré) : elle passe
par l'outil ; `direction_ui.py` ne porte que deux commandes internes, toutes deux sur les plans.

## Données et registres

Registre `publications_revue` ; lit `captures_strategiques`, `sessions_conseil`, `plans`, `actions`, `experiences`
(chacun validé avant usage : `REJ-REVUE-CHAINE-INVALIDE`, `REJ-PLAN-CHAINE-INVALIDE`, `REJ-ACTION-CHAINE-INVALIDE`,
`REJ-EXPERIENCE-CHAINE-INVALIDE`).

## Workflows

1. Après la fin de la période, aperçu (`granularite`, `ancre`, `fuseau`, `connaissance`).
2. Publication datée ; un registre modifié entre deux pages donne `REJ-VUE-PERIMEE` à la liste.
3. Une capture tardive concernant la période entre dans une version suivante, jamais dans l'ancienne.

## Intégrations

Captures M1–M8 et M10 (tissu de données), conseil (décisions closes), plans, actions et expériences (M9.16–18), radars
(M9.12–13), indicateurs (M9.3), prévisions des propriétaires (M9.9).

## Risques

- La richesse d'une revue dépend des captures faites pendant la période ; une période sans capture produit surtout des
  sections `NON_DISPONIBLE`.
- Les tendances ne mesurent que la connaissance de M9 ; les lire comme des tendances d'affaires serait une erreur.

## Gates Nathan

Aucun pour la publication. Toute diffusion hors du registre (courriel, mobile) est une décision séparée.

## Tests

`departments/m09-strategic-intelligence/tests/test_revue_periodique.py` (périodes locales, heure d'été, connaissance
précoce, rattachement par réception, arrivée tardive en nouvelle version, chaîne altérée) ;
`tests/test_m9_direction_integre.py` (publication, rejeu, mensuelle et trimestrielle sur deux fuseaux) ;
`tests/test_m9_rapport_direction_integre.py` (vingt sections, revue figée à la fin, refus non admin) ;
`tests/test_console_direction_m9.py`.

## Statut

DONE_VERIFIED : publication versionnée, pagination et reproductibilité prouvées en processus et en console.

## Prochaines étapes

1. Planifier l'aperçu hebdomadaire avec la même autorité que le briefing (gate M9.5).
2. Contrat mobile : lecture des revues publiées (phase mobile).
