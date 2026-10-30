# Contrats attendus des propriétaires (consommateur M9)

Les données manquantes ne sont ni fabriquées ni extrapolées en prévision de propriétaire. M9 fixe la FORME attendue
(`contrats_attendus.py`) ; les modifications côté producteur sont à coordonner avec chaque propriétaire, en commits
séparés. Tests : `departments/m09-strategic-intelligence/tests/test_contrats_attendus.py`,
`tests/test_m9_contrats_attendus_integre.py`, `test_preuves_definition.py`, `tests/test_m9_semantique_integre.py`.

| Domaine | Propriétaire | Contrat attendu | État constaté |
|---|---|---|---|
| Historique des définitions (M9.3) | M8 | contrat successeur : historique paginé vérifié et preuve propre par observation — `CONTRAT-HISTORIQUE-DEFINITIONS-M8-M9.md` | non publié par M8 ; candidat MR !1 non intégré, non lu ici ; `historique_definitions = NON_CONSOMME` |
| Prévision de trésorerie | M5 | `m5.prevision_tresorerie` (déjà lue) | publiée ; seule prévision de propriétaire |
| Capacité d'équipe (M9.11) | M4 | `m4.capacite_equipe` : semaine, équipes, heures disponibles/planifiées en texte décimal, `calculable`, `manque` | absente du catalogue et du port privé |
| Dépenses marketing (M9.18) | M7 | `m7.depenses_marketing` : période, couverture, lignes {canal, montant_cad en texte, date, source} | absente ; `m7.performance_campagnes` dit `DEPENSES_NON_BRANCHEES` |
| Plaintes structurées | M1 | `m1.plaintes_structurees` : comptes par catégorie fermée de `taxonomie.CATEGORIES_SIGNAL_PLAINTE`, jamais de texte ni d'identité | absente ; le digest ne compte les plaintes qu'en texte |

## M9.3
Le premier contrat (liaisons globales `liaisons_versions`) est retiré : voir `CONTRAT-HISTORIQUE-DEFINITIONS-M8-M9.md`.

## Extrapolation
Une tendance calculée par M9 porte `origine = tendance_extrapolee` ; `refuser_extrapolation` la refuse si elle est
présentée comme prévision de propriétaire (`REJ-CONTRAT-EXTRAPOLATION`).
