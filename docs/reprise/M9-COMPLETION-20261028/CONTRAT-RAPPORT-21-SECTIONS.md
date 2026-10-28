# M9.10 — rapport de décision : 21 sections, proposition à arbitrer

**Statut : `PROPOSITION_NON_RATIFIEE`.** Aucune énumération canonique des 21 sections n'existe dans le dépôt.

## Recherche de la source maîtresse (Lot 0)
- `docs/produit/DEFINITION-PRODUIT.md` §M9.10 : « rapport en 21 sections » ; douze notions citées seulement (question,
  décision recommandée, options, données utilisées et manquantes, hypothèses, scénarios, impacts, dépendances,
  conditions, validation, plan d'action, mesure du succès).
- Annexe A de la définition : « Prompt maître M9 (courriel « Intelligence Stratégique », 9 juin 2026) — M9 complet ; la 2e
  copie ajoute le critère 27 ». **Ce prompt n'est pas versionné** (`git grep` sur la base `3ab7692f` : aucune occurrence
  hors l'Annexe et `docs/departements/M9-audit.md` §2.6, qui constate le même manque).
- Pack de mission, `README`/`department.yaml` M9, `docs/produit/*`, `docs/research/R10-m9-capabilities.md` : aucune liste.

## Proposition (code : `rapport_decision_v2.py`, tests : `test_rapport_decision_v2.py`)
15 sections correspondent une à une aux 15 clés du contrat historique, qui reste inchangé ; 6 sont des extensions
justifiées par la définition ou le cahier. Chaque section porte son origine dans `SECTIONS`.

| # | Section v2 | Origine | Clé historique |
|---|---|---|---|
| 1 | `question` | définition | — (extension) |
| 2 | `etat` | historique | `etat` |
| 3 | `donnees_utilisees` | définition | `preuves` |
| 4 | `donnees_manquantes` | définition | — (extension) |
| 5 | `contradictions` | cahier | — (extension) |
| 6 | `hypotheses` | définition | `hypotheses` |
| 7 | `incertitudes` | historique | `incertitudes` |
| 8 | `diagnostic` | historique | `diagnostic` |
| 9 | `options_alternatives` | définition | — (extension) |
| 10 | `scenarios` | définition | `scenarios` |
| 11 | `impacts` | définition | `impacts` |
| 12 | `dependances` | définition | — (extension) |
| 13 | `risques` | historique | `risques` |
| 14 | `priorites` | historique | `priorites` |
| 15 | `decision_recommandee` | définition | `recommandations` |
| 16 | `conditions` | définition | — (extension) |
| 17 | `validation` | définition | `validation` |
| 18 | `plan_action` | définition | `actions` |
| 19 | `taches_par_departement` | historique | `taches_par_departement` |
| 20 | `mesure_succes_suivi` | définition | `suivi` |
| 21 | `memoire_m10` | historique | `memoire_m10` |

## Règles du schéma (vérifiées par tests)
- Enveloppe exacte, `statut_contrat = PROPOSITION_NON_RATIFIEE` (un schéma « ratifié » est refusé), empreinte `rapport_id`.
- Une section non renseignée dit `NON_DISPONIBLE`/`NON_APPLICABLE` + raison et ne porte **aucun contenu inventé** ;
  une abstention complète (pas de décision recommandée) est un rapport valide.
- **Règle dure M9 :** aucune option, scénario, impact, dépendance, risque, priorité, recommandation, condition, action,
  tâche ni mesure sans référence à une source (`donnees_utilisees`) ou hypothèse déclarée, vérifiée de proche en proche ;
  une référence inconnue, ultérieure ou circulaire est refusée.
- Un chiffre n'existe qu'en texte avec unité et propriétaire du calcul (`source_calcul`) ; jamais produit par le schéma.
- `vers_contrat_historique` projette exactement vers les 15 clés et passe le validateur historique inchangé.

## Décision requise de Nathan (gate `GATED_HUMAN`)
Ratifier, amender ou remplacer cette énumération, ou verser le prompt maître M9 (courriel du 9 juin 2026). Tant que ce
n'est pas fait, la ligne M9.10 reste ouverte : le code produit et valide la proposition, et ne l'affirme jamais ratifiée.
Les autres capacités (conseil, scénarios, priorités, suivi) n'attendent pas cet arbitrage.
