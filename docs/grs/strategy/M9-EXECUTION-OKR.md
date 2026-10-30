# M9.16–17 — plans d'exécution (OKR) et orchestrateur d'actions

Statut : **DONE_VERIFIED** (M9.16 et M9.17).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [playbooks](M9-STRATEGIC-PLAYBOOKS.md) ·
[gouvernance](M9-GOVERNANCE-HUMAN-VALIDATION.md) · [mémoire M10](M9-M10-MEMORY-INTEGRATION.md) ·
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Suivre ce qui a été décidé — objectif, porteur, échéance, résultats clés mesurés chez leurs propriétaires — et proposer
les actions qui en découlent à un humain, sans que M9 exécute ni rejoue quoi que ce soit.

## Pourquoi

Un plan noté « fait » parce que quelqu'un l'a écrit n'a rien prouvé. Le suivi est une déclaration ; seul un critère
mesuré chez le propriétaire rend un résultat clé atteint. De même, M9 n'a aucun moyen d'agir : il dépose une demande
exacte dans la file d'approbation native, et constate ensuite ce qui s'est réellement passé.

## État actuel

**Plans (M9.16, `plans.py`, schéma `m9.plans.v1`, événements `PLAN`, `ANNULATION`, `SUIVI`)** :

- Plan = `plan_id`, `objectif`, `porteur`, `echeance` (jour), 1 à 12 `resultats_cles`, au plus 12 `sources` (adresses de
  faits citables, valeur figée au dépôt), `decision_ref` facultatif. Une révision ajoute une version (motif obligatoire,
  `REJ-PLAN-REVISION` si identique) ; un plan annulé ne se rouvre pas (`REJ-PLAN-ANNULE`).
- Résultat clé : mesurable (`lecture`, `chemin`, opérateur, cible) ou `manuel` (`A_JUGER_PAR_LA_PERSONNE`).
- Vue à un instant et un jour civil fournis : `ATTEINT_MESURE` seulement si tous les résultats clés sont `SATISFAIT`
  mesurés, sinon `EN_RETARD` (échéance passée), `EN_COURS` ou `ANNULE`. Chaque résultat rend `suivis_declares` à part.
- **Suivi ≠ effet** : `m9_noter_suivi_plan` répond `effet_realise: false` ; un suivi ne change aucun statut.
- **Source changée** (`sources_changees`) : la valeur citée au dépôt est relue au même chemin dans la dernière capture
  complète ; l'écart est signalé, le plan n'est pas modifié.

**Orchestrateur (M9.17, `orchestrateur.py` + port `opsys.actions_m9`)** :

- **Liste blanche** `ACTIONS_AUTORISEES` (identique à `orchestrateur.ACTIONS`, égalité imposée par test) :
  `m02-revenue-crm` → `m2_preparer_relance`, `m2_reassigner_lead` ; `m04-field-ops` → `m4_planifier_intervention`,
  `m4_creer_demande_ecart` ; `m10-memoire` → `m10_journaliser_decision`. Hors liste : `REJ-ACTION-NON-AUTORISEE`.
- Le port n'accepte qu'un outil T1 de niveau N3 à N5, valide les arguments contre le schéma de l'outil cible, puis crée
  une demande `en_attente` (`approbations.creer_demande`). Il refuse tout appelant qui n'est pas l'admin authentifié
  agissant via M9, rôle relu en base.
- Le registre `actions` garde le département, l'outil, l'**empreinte** des arguments (jamais leur contenu), 1 à 12
  sources (adresse de fait ou `playbook:`, `priorisation:`, `radar:`, `conseil:`, `veille:` + empreinte), le motif et
  l'identifiant de demande native.
- Constats tirés de l'état natif : `EN_ATTENTE_APPROBATION`, `REFUSEE`, `ECHEC`, `EXECUTEE_CONFIRMEE` (succès déclaré
  par le producteur), sinon `INCONNU` (introuvable, `en_cours`, arguments divergents, exécutée sans succès déclaré).
- **Pas de rejeu** (`REJ-ACTION-REJEU`) tant que l'action est en attente, exécutée ou inconnue ; seuls `REFUSEE` et
  `ECHEC` ouvrent une tentative numérotée. Un effet inconnu ne se rejoue jamais.

## Architecture

`m9_proposer_action` contrôle liste blanche, sources, motif et rejeu **avant** toute écriture native, appelle le port,
vérifie que l'empreinte rendue égale celle de M9 (`REJ-ACTION-ARGUMENTS` sinon), puis ajoute la proposition au registre
dans la même transaction : si l'un échoue, l'autre aussi. `m9_reconcilier_action` relit la demande native et n'ajoute un
constat que s'il change. Port non installé : `REJ-ACTION-PORT-ABSENT` ; refus du port : `REJ-ACTION-REFUSEE`.

## Fichiers

[plans.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/plans.py),
[outils_plans.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_plans.py),
[orchestrateur.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/orchestrateur.py),
[outils_actions.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_actions.py),
[actions_m9.py](../../../src/opsys/actions_m9.py), `criteres.py`, `chainage.py`.

## Outils et pages de console

| Outil | Accès |
|---|---|
| `m9_enregistrer_plan`, `m9_annuler_plan`, `m9_noter_suivi_plan` | admin strict, T1/N2 |
| `m9_lire_plans` (`connaissance`, `jour`, `plan_id`) | admin strict, T0/N0 |
| `m9_proposer_action`, `m9_reconcilier_action` | admin strict, T1/N2 (la demande native créée est N3) |
| `m9_lire_actions` (`action_id`) | admin strict, T0/N0, sans arguments en clair |

Pages : `/direction/plans` (lecture ; formulaires POST `/direction/plans/suivi` et `/direction/plans/annuler`, jeton
CSRF, `mutation_id` idempotent, annulation avec case de confirmation ; l'horodatage est posé par le serveur) ;
`/direction/actions` (lecture, renvoi vers la file native `/approbations`). Le dépôt d'un plan et la proposition d'une
action ne sont pas exposés en console : ils passent par les outils.

## Données et registres

Registres chaînés `plans` et `actions` (`REJ-PLAN-CHAINE-INVALIDE`, `REJ-ACTION-CHAINE-INVALIDE`), lecture de
`captures_strategiques`, file native `approbations` du socle.

## Workflows

1. Déposer un plan qui cite ses sources ; le lire chaque jour avec le jour civil.
2. Noter des suivis ; constater mesure, retard ou source changée ; réviser ou annuler (décision humaine).
3. Proposer une action de la liste blanche ; un humain approuve ou refuse dans la file ; réconcilier.

## Intégrations

M2 et M4 (actions proposables), M10 (`m10_journaliser_decision`, voir M9.20), producteurs des lectures citées par les
résultats clés, file d'approbation et rôles de la politique du département cible.

## Risques

- Ajouter un outil à la liste blanche élargit ce que M9 peut proposer : revue humaine requise, des deux côtés.
- Un résultat clé `manuel` empêche `ATTEINT_MESURE` par construction.
- Un effet `INCONNU` exige une réconciliation ou un arbitrage humain ; rien n'est automatique.

## Gates Nathan

Approbation de chaque action dans la file native (rôles du département cible) ; décision de réviser ou d'annuler un plan.

## Tests

Département : `test_plans.py` (historique, refus, révision, suivi ≠ effet, atteinte mesurée, source changée, chaîne
falsifiée), `test_orchestrateur.py` (cycle, constats natifs, inconnu bloquant, refus, sources admises).
Intégration : `tests/test_m9_plans_integre.py`, `tests/test_m9_actions_integre.py` (proposition non exécutée puis
approbation humaine, refus puis tentative numérotée, effet inconnu jamais rejoué, arguments modifiés → `INCONNU`, échec
d'écriture qui annule la demande native, listes blanches identiques) ; `tests/test_console_direction_m9.py` (CSRF,
idempotence, confirmation, reprise).

## Statut

DONE_VERIFIED en processus et en navigateur (plans) ; aucune action réelle exécutée hors fixtures fictives.

## Prochaines étapes

1. Ajouter un outil proposable seulement sur demande, avec test d'égalité des listes et revue humaine.
2. Mesurer automatiquement des résultats clés aujourd'hui `manuel` quand un producteur publiera la mesure.
