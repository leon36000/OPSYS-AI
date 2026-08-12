# Politique NO-STUB et qualité

Le gate `scripts/quality/no_stub_gate.py` protège les scopes Python définis par
`core/quality-scopes.toml` ainsi que les jobs GitHub requis.

## Violations

| Code | Règle |
| --- | --- |
| `FICHIER_NON_ANALYSABLE` | Un fichier Python ne peut pas être lu en UTF-8 ou ne peut pas être analysé syntaxiquement. Le détail porte la ligne et le message de l'erreur lorsque ceux-ci sont disponibles. Cette règle est fail-closed : un fichier illisible ou invalide n'est jamais considéré propre. |
| `EMPTY_PRODUCTION_FILE` | Un module de production est vide, hors `__init__.py` et `.gitkeep`. |
| `EXECUTABLE_PASS` | Le corps exécutable d'une fonction ne contient que `pass`, `return` ou `return None`. |
| `EXECUTABLE_ELLIPSIS` | Une ellipse ou un lambda réduit à `None` ou `...` sert de stub hors abstraction reconnue. |
| `DOCSTRING_ONLY_BODY` | Une fonction ne contient qu'une docstring. |
| `NOT_IMPLEMENTED_STUB` | Une fonction lève `NotImplementedError`, sa forme qualifiée, ou `NotImplemented`. |
| `TRIVIAL_ASSERTION` | Une assertion ajoutée porte sur une constante vraie. |
| `TEST_WITHOUT_ORACLE` | Un test modifié ne contient aucun oracle reconnu. |
| `NEW_SKIP_OR_XFAIL` | Un skip ou xfail a été ajouté. |
| `FORBIDDEN_MARKER` | Un commentaire ajouté contient un marqueur de dette interdit. |
| `UNJUSTIFIED_SUPPRESSION` | Une suppression de contrôle ajoutée ne porte pas de justification structurée. |
| `SCOPE_ROOT_OMITTED` | Une collection littérale ou une compréhension retire des racines contractuelles. |
| `REQUIRED_JOB_SOFT_FAILURE` | Un job requis emploie `continue-on-error` avec une valeur vraie YAML, ou une expression dynamique. |
| `REQUIRED_JOB_FORCED_SUCCESS` | Une commande d'un job requis, ou d'une action composite locale appelée par lui, force un succès shell. |

`continue-on-error` refuse les valeurs YAML vraies `true`, `yes`, `on`, `y` et
`1`, sans distinction de casse. Une valeur contenant `${{` est également
refusée : elle est dynamique et ne peut pas être décidée statiquement.

## Actions composites

Lorsqu'un step d'un job requis utilise une action locale, sous la forme
`uses: ./chemin`, le gate inspecte `action.yml` puis `action.yaml` du répertoire
visé avec les mêmes règles de succès shell.

Une action externe, telle que `owner/repo@sha`, ne peut pas être inspectée depuis
le dépôt. Un job requis qui délègue son contrôle à une telle action échappe donc
à cette vérification. Cette limite impose de sélectionner des actions externes
fiables et épinglées.

## Limites explicites de l'analyse statique

Le gate ne prétend pas résoudre les cas nécessitant une exécution ou une analyse
de flot de données.

- Une exclusion indirecte, par exemple `exclus = ["tools/proof"]` puis
  `[r for r in racines if r not in exclus]`, n'est pas détectée : suivre la
  valeur de `exclus` nécessiterait une analyse de flot de données.
- Les alias importés ne sont pas suivis après réaffectation. Ainsi,
  `Protocol = MaClasseLocale` après un import n'est pas résolu par la table
  d'alias statique.
- Un `exit 0` conditionnel dont la condition est toujours vraie n'est pas
  détecté comme succès forcé : l'analyse shell est textuelle et n'exécute pas
  les conditions.

Ces limites sont opérationnelles : les revues de code et les contrôles
d'intégration doivent examiner les indirections, les réaffectations et la
logique shell que le gate ne peut pas prouver honnêtement.
