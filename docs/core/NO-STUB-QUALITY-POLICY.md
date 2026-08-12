# Politique NO-STUB et qualité diff-aware

## Objet

Le gate `scripts/quality/no_stub_gate.py` refuse les implémentations incomplètes,
les tests sans oracle vérifiable, les suppressions de contrôle non justifiées et
les neutralisations de jobs CI requis.

Le gate est intentionnellement fail-closed pour les motifs qu'il sait prouver
syntaxiquement. Les exceptions aux règles de stub doivent être explicitement
liées aux abstractions standards importées.

## Codes de violation

| Code | Règle |
|---|---|
| `DOCSTRING_ONLY_BODY` | Une fonction ne contient qu'une docstring. |
| `EXECUTABLE_PASS` | Une fonction ne contient que `pass`, `return`, `return None`, ou une combinaison de ces instructions triviales. |
| `EXECUTABLE_ELLIPSIS` | Une fonction ordinaire ou un lambda est réduit à `...` ou à une valeur de stub. |
| `NOT_IMPLEMENTED_STUB` | Une fonction lève `NotImplementedError`. |
| `EMPTY_PRODUCTION_FILE` | Un module de production est vide hors exceptions explicites. |
| `TRIVIAL_ASSERTION` | Une assertion ajoutée porte sur une constante vraie. |
| `TEST_WITHOUT_ORACLE` | Un test ajouté ou modifié ne contient aucun oracle reconnu. |
| `NEW_SKIP_OR_XFAIL` | Un skip ou xfail est ajouté dans le diff. |
| `FORBIDDEN_MARKER` | Un commentaire ajouté contient un marqueur de dette interdit. |
| `UNJUSTIFIED_SUPPRESSION` | Une suppression `type: ignore`, `noqa` ou `nosec` ne porte pas de justification structurée. |
| `SCOPE_ROOT_OMITTED` | Un lanceur de scan omet une ou plusieurs racines Python contractuelles. |
| `REQUIRED_JOB_SOFT_FAILURE` | Un job CI requis utilise `continue-on-error: true`. |
| `REQUIRED_JOB_FORCED_SUCCESS` | Un job CI requis force un succès shell avec `|| true`, `|| :` ou `|| exit 0`. |

## Abstractions légitimes

Une ellipse est acceptée uniquement dans les cas suivants :

- une méthode d'une classe dérivant d'un `typing.Protocol` réellement importé ;
- une méthode portant un décorateur `abc.abstractmethod` réellement importé.

Les imports directs et les alias sont reconnus :

```python
from typing import Protocol
from typing import Protocol as P
import typing as t

from abc import abstractmethod
import abc as a
```

Une classe locale nommée `Protocol` ou une fonction locale nommée
`abstractmethod` ne crée aucune exemption.

## Suppressions de contrôles

Toute suppression doit avoir une justification non vide après `—`, `-` ou `:`.

Les identifiants de règle sont admis avant ce séparateur :

```python
valeur = appel()  # nosec B310 — le schéma est validé par liste blanche
valeur = appel()  # type: ignore[arg-type] — contrat externe documenté
valeur = appel()  # noqa E501 - exception de format justifiée
```

Les formes suivantes restent interdites :

```python
valeur = appel()  # nosec
valeur = appel()  # nosec B310
valeur = appel()  # type: ignore[arg-type]
```

## Workflows CI

Les jobs requis sont définis par `target_required_job_ids` dans
`core/quality-scopes.toml`.

Le gate inspecte les commandes `run:` inline ainsi que les scalaires YAML de
bloc `|`, `|-`, `|+`, `>`, `>-` et `>+`. Une neutralisation shell dans une ligne
d'un bloc appartenant à un job requis produit
`REQUIRED_JOB_FORCED_SUCCESS`.

Les mêmes constructions dans un job non requis ne relèvent pas de cette règle.

## Limites nommées de l'analyse statique

### Périmètre dynamique des scanners

La règle `SCOPE_ROOT_OMITTED` prouve les omissions dans :

- les listes, tuples et sets littéraux ;
- les concaténations directes de collections littérales ;
- les compréhensions qui filtrent explicitement la variable `racines`.

Elle ne résout pas les appels de fonctions, les valeurs construites par import,
les mutations, la réflexion, les évaluations conditionnelles ou toute autre
construction nécessitant l'exécution du programme. Cette limite est nommée
**périmètre dynamique non résolu**.

Le contrat de racines reste la source d'autorité. Les lanceurs opérationnels
doivent préférer une énumération littérale exhaustive ou transmettre directement
les racines contractuelles afin de conserver une preuve statique.

### Sémantique Python non exécutée

Le gate inspecte l'AST sans exécuter le code. Il ne déduit pas les effets de bord
d'appels, de décorateurs arbitraires ni de métaprogrammation. Cette limite est
nommée **sémantique dynamique non exécutée**.

### YAML opérationnel ciblé

Le contrôle CI couvre les formes `run:` inline et les scalaires de bloc usuels
des jobs requis. Il ne prétend pas interpréter les expressions GitHub, les
ancres YAML complexes ou les commandes fabriquées à l'exécution. Cette limite
est nommée **commande CI indirecte**.
