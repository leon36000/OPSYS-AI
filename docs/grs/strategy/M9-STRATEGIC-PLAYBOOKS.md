# M9.15 — playbooks stratégiques

Statut : **DONE_VERIFIED** (gabarits gouvernés ; aucune étape exécutée par M9).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [radar de risques](M9-RISK-RADAR.md) ·
[exécution et actions](M9-EXECUTION-OKR.md) · [gouvernance](M9-GOVERNANCE-HUMAN-VALIDATION.md) ·
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Proposer, pour une situation connue de l'entreprise (trésorerie tendue, rupture de matériaux, surcharge, météo, saison,
expansion…), une marche à suivre écrite à l'avance : déclencheur, étapes ordonnées, qui décide, critères de succès et
d'arrêt lisibles sur les données des propriétaires, risques et plan de retour.

## Pourquoi

Un plan d'action improvisé par un modèle n'est ni rejouable ni gouverné. Un gabarit versionné, validé au chargement,
garantit que chaque étape sensible reste une validation humaine et que le succès se mesure chez le propriétaire, pas
dans la parole du modèle.

## État actuel

`playbooks.py` (version `2026-10-28.1`) contient **17 gabarits** (`CATALOGUE`) : `cash`, `baisse_leads`, `surcharge`,
`meteo`, `rupture`, `hausse_prix`, `trop_de_leads`, `risque_plaintes`, `conversion_devis_faible`,
`roi_marketing_faible`, `debut_de_saison`, `reserve_fin_de_saison`, `embauche`, `achat_equipement`, `expansion_ville`,
`nouveau_service`, `relance_avis_clients`.

- **Champs obligatoires** (`CHAMPS`) : `nom`, `declenche_par`, `etapes`, `succes`, `arret`, `limites`,
  `donnees_requises`, `departements`, `risques`, `plan_retour` ; `approbation_requise` est **dérivé** (vrai dès qu'une
  étape est sensible) et un gabarit qui le contredit est refusé.
- **Déclencheurs** : quatre gabarits sont déclenchés par des règles du radar (`cash`, `surcharge`, `meteo`, `rupture`) ;
  les treize autres n'ont aucune mesure automatique et sont `A_DECLARER` par la personne (nommé comme tel).
- **Étapes** : type `information`, `suivi_interne` ou `action_sensible` ; une étape sensible porte un genre de
  `conseil.ACTIONS_SENSIBLES` (dépense réelle, budget marketing, embauche, achat majeur, dette, prix global, décision
  fiscale ou légale, contrat). Seize gabarits ont au moins une étape sensible ; `relance_avis_clients` n'en a aucune.
- **Critères** : 34 critères de succès ou d'arrêt, opérateurs `==`, `!=`, `>=`, `<=`, `aucun`, `manuel` ; six portent
  une cible à lier par la personne (`cible_a_lier`).

## Architecture

- `verifier_catalogue` (exécuté au chargement) refuse avec `REJ-PLAYBOOK-GABARIT` : champ manquant, plan de retour ou
  risques vides, règle de déclenchement inconnue du radar, donnée requise hors `catalogue_producteurs`, départements non
  triés ou non déclarés (y compris ceux touchés par une étape ou un port), critère lisant une lecture non requise.
- `declenchement(gabarit, radar)` : `DECLENCHE` (risque `ACTIF`), `NON_DECLENCHE`, `INCONNU` (règle non évaluée, ou
  signal `A_RECONFIRMER`), `A_DECLARER`.
- `instancier(...)` : étapes sensibles `VALIDATION_HUMAINE_REQUISE` avec `proprietaire_decision`, autres `PROPOSABLE` ;
  `effet_autorise: false` partout ; `liaisons` = cibles décimales textuelles de la personne (`REJ-PLAYBOOK-LIAISON`
  sinon) ; identifiant d'instance = empreinte du contenu. Playbook inconnu : `REJ-PLAYBOOK-INCONNU`.
- `evaluer_criteres` (via `criteres.evaluer`) lit la dernière capture complète et non contradictoire : `SATISFAIT`,
  `NON_SATISFAIT`, `INCONNU` (lecture absente, refusée, partielle, contradictoire, cible absente, valeur non numérique) ou
  `A_JUGER_PAR_LA_PERSONNE` (`manuel`). Verdict : `ARRET` si un critère d'arrêt est satisfait, `SUCCES` si tous les
  critères de succès le sont, sinon `INCONNU` ou `EN_COURS`. Un critère manuel n'est jamais satisfait par le code.

## Fichiers

[playbooks.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/playbooks.py),
[criteres.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/criteres.py),
[outils_playbooks.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_playbooks.py),
`risques.py`, `catalogue_producteurs.py`, `conseil.py`.

## Outils et pages de console

| Outil | Accès |
|---|---|
| `m9_lister_playbooks` (`depart`) | admin strict, T0/N0, fiches paginées (`REJ-PLAYBOOK-DEPART`) |
| `m9_evaluer_playbook` (`playbook_id`, `connaissance`, `perime_apres_jours`, `declare_par_la_personne`, `liaisons`) | admin strict, T0/N0 |

Aucune page de console dédiée n'est livrée. Le contrat mobile (`CONTRAT-MOBILE-ADMIN-M9.md`) décrit encore
`m9_lister_playbooks` comme listant « six gabarits » : libellé périmé, le code en compte 17.

## Données et registres

Aucun registre propre : les gabarits sont du code versionné ; l'instance et l'évaluation sont calculées à la demande sur
`captures_strategiques` (table `strategic_playbook_run` du cahier remplacée par ce calcul).

## Workflows

1. Lire le radar ; choisir un gabarit (ou le déclarer si aucun producteur ne mesure le signal).
2. Évaluer : étapes, cibles liées, critères mesurés.
3. Une étape sensible devient, si Nathan le veut, une action proposée par l'orchestrateur (M9.17) et décidée dans la
   file native ; un suivi devient un plan (M9.16).

## Intégrations

Lectures citées (via le catalogue) chez M2, M3, M4, M5, M6, M7, M8 ; ports nommés dans les étapes (par exemple
`m5_prevoir_tresorerie`), vérifiés comme outils réels par `tests/test_m9_playbooks_integre.py`. Le cadrage de décision
(M9.10) rend `playbooks_a_examiner` pour chaque type de décision.

## Risques

- Treize gabarits dépendent d'une déclaration humaine faute de signal mesuré.
- Les cibles par défaut d'un gabarit sont des conventions écrites ; les cibles chiffrées viennent de la personne.
- Un gabarit ne connaît pas la capacité réelle d'équipe (non exposée par M4).

## Gates Nathan

Toute étape `action_sensible` ; le choix des cibles liées ; l'ajout d'un gabarit (revue humaine du catalogue).

## Tests

`departments/m09-strategic-intelligence/tests/test_playbooks.py` (dix-sept gabarits et genres connus du conseil,
champs, approbation dérivée, gabarit incohérent refusé, aucun effet autorisé, cible liée, rupture déclenchée, sans
signal / lecture absente, déclaration, critères, météo, refus nommés, identifiant d'instance) ;
`tests/test_m9_playbooks_integre.py` (ports réels, outils réels sans donnée → `INCONNU` ou `A_DECLARER`, refus
d'identité) ; `tests/test_m9_gouvernance.py` (genres des étapes sensibles ⊂ familles du conseil).

## Statut

DONE_VERIFIED en processus ; pas de page de console.

## Prochaines étapes

1. Brancher un déclencheur mesuré dès qu'un producteur publie le signal (leads, conversion, avis).
2. Corriger la description « six gabarits » dans le contrat mobile lors de sa prochaine génération.
