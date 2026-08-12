# Politique NO-STUB et qualité

Le gate `scripts/quality/no_stub_gate.py` refuse les absences
d'implémentation, les régressions de qualité ajoutées et les moyens de rendre
les contrôles CI non bloquants.

## Contrat de périmètre

Le fichier `core/quality-scopes.toml` est obligatoire lors de l'exécution en
ligne de commande. Il définit les racines Python contrôlées et les identifiants
des jobs GitHub Actions requis.

Une absence, une lecture impossible ou un TOML invalide produit
`CONTRAT_PERIMETRE_ABSENT` et fait échouer le gate. Le contrat ne peut donc pas
être supprimé ou corrompu pour désactiver silencieusement le contrôle.

L'API `scan_repository` reste utilisable dans des dépôts synthétiques sans
contrat : les règles indépendantes du contrat restent actives, tandis que les
règles de comparaison avec les racines contractuelles ne sont pas applicables.

## Codes de violation

| Code | Signification |
| --- | --- |
| `CONTRAT_PERIMETRE_ABSENT` | Le contrat de périmètre requis par la CLI est absent, illisible ou invalide. |
| `EXECUTABLE_PASS` | Une fonction ne contient que des instructions triviales. |
| `EXECUTABLE_ELLIPSIS` | Une fonction ou lambda est réduit à une ellipse ou à une valeur de stub. |
| `NOT_IMPLEMENTED_STUB` | Une fonction lève explicitement une exception d'absence d'implémentation. |
| `DOCSTRING_ONLY_BODY` | Une fonction ne contient qu'une docstring. |
| `EMPTY_PRODUCTION_FILE` | Un module de production est vide. |
| `FICHIER_NON_ANALYSABLE` | Un fichier Python ou YAML ne peut pas être lu ou analysé. |
| `TRIVIAL_ASSERTION` | Une assertion ajoutée porte sur une constante vraie. |
| `TEST_WITHOUT_ORACLE` | Un test modifié ne contient aucun oracle reconnu. |
| `NEW_SKIP_OR_XFAIL` | Un skip ou xfail a été ajouté. |
| `FORBIDDEN_MARKER` | Un commentaire ajouté contient un marqueur de dette interdit. |
| `UNJUSTIFIED_SUPPRESSION` | Une suppression de contrôle ajoutée n'est pas justifiée. |
| `SCOPE_ROOT_OMITTED` | Un lanceur de scan omet ou exclut littéralement une racine contractuelle. |
| `SCOPE_FILTRE_INDECIDABLE` | Un filtre de racines n'est pas décidable statiquement ; il doit être rendu littéral ou justifié. |
| `REQUIRED_JOB_SOFT_FAILURE` | Un job requis, un de ses steps, ou un step d'action composite locale accepte les erreurs. |
| `REQUIRED_JOB_FORCED_SUCCESS` | Un job requis force un succès shell. |
| `LOCAL_ACTION_CYCLE` | Une cascade d'actions composites locales contient un cycle. |
| `LOCAL_ACTION_DEPTH_EXCEEDED` | Une cascade d'actions composites locales dépasse la profondeur autorisée. |

## Exemptions d'abstraction

Une ellipse est admise uniquement dans une méthode de classe dérivant d'un
`typing.Protocol` dont l'import est prouvé, ou dans une méthode décorée par un
`abc.abstractmethod` dont l'import est prouvé. Un nom local homonyme ne crée
pas d'exemption.

Le parcours AST descend dans tous les blocs Python. Une fonction ou une classe
définie dans un `if`, `try`, `with`, `for` ou `while` reste donc soumise aux
mêmes règles.

## Workflows et actions composites

Les jobs requis ne peuvent pas utiliser `continue-on-error: true`, y compris
au niveau d'un step. Toute valeur dynamique contenant `${{` est refusée par
principe. Cette protection est également appliquée aux steps des actions
composites locales appelées en cascade.

Les succès forcés shell, notamment `|| true`, `|| :`, `|| exit 0` et `exit 0`
non gardé, sont refusés dans les jobs requis et leurs actions composites
locales.

## Contrôle des racines

Les listes littérales de racines sont comparées au contrat. Les exclusions
littérales sont signalées par `SCOPE_ROOT_OMITTED`.

Une compréhension qui filtre les racines au moyen d'une variable, d'un appel
non reconnu ou d'une autre condition impossible à trancher statiquement est
signalée par `SCOPE_FILTRE_INDECIDABLE`. L'incapacité du gate à conclure ne
constitue donc jamais une autorisation silencieuse de retirer une racine.

Le filtre `.exists()` reste admis : il exprime le cas légitime d'une cible
optionnelle présente sur le système de fichiers, sans masquer une exclusion
d'identité de racine.
