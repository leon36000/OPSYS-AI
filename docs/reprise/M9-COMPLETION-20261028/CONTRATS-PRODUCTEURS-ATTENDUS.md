# Contrats attendus des propriétaires (consommateur M9)

Les données manquantes ne sont ni fabriquées ni extrapolées en prévision de propriétaire. M9 fixe la FORME attendue
(`contrats_attendus.py`) ; les modifications côté producteur sont à coordonner avec chaque propriétaire, en commits
séparés. Tests : `departments/m09-strategic-intelligence/tests/test_contrats_attendus.py`,
`tests/test_m9_contrats_attendus_integre.py`, `test_semantique_metriques.py`, `tests/test_m9_semantique_integre.py`.

| Domaine | Propriétaire | Contrat attendu | État constaté |
|---|---|---|---|
| Liaison de versions de métriques (M9.3) | M8 | champ `resultat.liaisons_versions[*] = {metric_id, revision (entier ≥ 1), empreinte (sha256 hex)}` dans `m8.definitions_metriques` | absent chez M8 : `liaisons_versions = 0`, mesures à empreinte `VERSION_NON_COMPARABLE` (`AUCUNE_LIAISON`) |
| Prévision de trésorerie | M5 | `m5.prevision_tresorerie` (déjà lue) | publiée ; seule prévision de propriétaire |
| Capacité d'équipe (M9.11) | M4 | `m4.capacite_equipe` : semaine, équipes, heures disponibles/planifiées en texte décimal, `calculable`, `manque` | absente du catalogue et du port privé |
| Dépenses marketing (M9.18) | M7 | `m7.depenses_marketing` : période, couverture, lignes {canal, montant_cad en texte, date, source} | absente ; `m7.performance_campagnes` dit `DEPENSES_NON_BRANCHEES` |
| Plaintes structurées | M1 | `m1.plaintes_structurees` : comptes par catégorie fermée de `taxonomie.CATEGORIES_SIGNAL_PLAINTE`, jamais de texte ni d'identité | absente ; le digest ne compte les plaintes qu'en texte |

## Règle de liaison M8 ↔ M9 (M9.3)
La révision entière du registre et l'empreinte de la définition restent deux informations distinctes. Une mesure portant
une empreinte est : `COMPATIBLE` si une liaison la relie à la révision courante ; `VERSION_PERIMEE` si à une révision
plus ancienne ; `VERSION_NON_COMPARABLE` si la liaison manque, ou pointe une révision absente du registre. Deux liaisons
contradictoires (même empreinte pour deux révisions, ou deux empreintes pour une révision) sont REFUSÉES, jamais
arbitrées. Les mesures historiques sans liaison fiable restent non comparables. M9 ne modifie pas M8.

## Extrapolation
Une tendance calculée par M9 porte `origine = tendance_extrapolee` ; `refuser_extrapolation` la refuse si elle est
présentée comme prévision de propriétaire (`REJ-CONTRAT-EXTRAPOLATION`).
