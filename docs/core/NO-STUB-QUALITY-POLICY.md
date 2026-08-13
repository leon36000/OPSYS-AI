# Politique de qualité NO-STUB

Le gate `scripts/quality/no_stub_gate.py` protège les modules Python, le
périmètre contractuel et les jobs GitHub Actions obligatoires. Il échoue fermé :
une absence de preuve de couverture ou d'exécution d'un contrôle requis est une
violation.

## Contrat de périmètre

`core/quality-scopes.toml` est une frontière de confiance.

- `python_roots` doit être une liste non vide de chaînes ;
- `target_required_job_ids` doit être une liste non vide de chaînes ;
- sans option `--scope`, le CLI analyse exactement toutes les racines de
  `python_roots` ;
- avec une ou plusieurs options `--scope`, toutes les racines contractuelles
  doivent encore être présentes. Les scopes supplémentaires restent possibles,
  mais un sous-ensemble silencieux est refusé.

Les violations correspondantes sont :

- `CONTRAT_PERIMETRE_ABSENT` : le contrat est absent, illisible, invalide ou
  contient une liste contractuelle vide ;
- `SCOPE_ROOT_OMITTED` : une liste, une compréhension ou les options `--scope`
  omettent une racine contractuelle ;
- `SCOPE_FILTRE_INDECIDABLE` : une compréhension qui itère sur des racines
  applique un filtre dont l'effet ne peut pas être prouvé statiquement.

La reconnaissance des compréhensions est volontairement limitée aux itérables
dont le nom prouve qu'ils représentent les racines contractuelles. Un filtrage
littéral d'une collection sans rapport avec les racines ne constitue pas une
violation.

## Jobs GitHub Actions requis

Les jobs indiqués par `target_required_job_ids` ne peuvent ni accepter une
erreur, ni forcer un succès shell, ni dépendre d'une condition d'exécution
arbitraire.

- `REQUIRED_JOB_SOFT_FAILURE` refuse `continue-on-error: true`, y compris les
  scalaires YAML quotés équivalents à vrai : `true`, `yes`, `on`, `y` et `1`,
  sans distinction de casse. Une valeur dynamique `${{ ... }}` est également
  refusée. Les valeurs fausses, notamment `"false"`, restent acceptées.
- `REQUIRED_JOB_FORCED_SUCCESS` refuse les formes shell qui neutralisent une
  erreur, telles que `|| true`, `|| :`, `|| exit 0`, `; true` et `exit 0`.
  Les contenus entre quotes simples ou doubles sont neutralisés avant cette
  analyse : un exemple affiché par `echo "|| true"` n'est pas du code shell.
  Le code entourant une chaîne reste analysé.
- `REQUIRED_JOB_CONDITIONNEL` refuse une clé `if:` sur un job requis ou une de
  ses étapes sauf `always()` et `success()`, avec ou sans enveloppe
  `${{ ... }}`. Ces deux formes sont explicitement tolérées car elles ne
  conditionnent pas le contrôle requis à une donnée métier ou à une expression
  arbitraire. Toute autre valeur, y compris `false` ou une expression dynamique,
  ne prouve plus l'exécution du contrôle.
- `LOCAL_ACTION_CYCLE` et `LOCAL_ACTION_DEPTH_EXCEEDED` refusent les graphes
  d'actions composites locales impossibles à analyser de façon bornée.

Les mêmes règles de condition et de succès souple s'appliquent aux étapes des
actions composites locales atteintes depuis un job requis.

## Stubs et alias importés

Le gate refuse les corps exécutables réduits à `pass`, `...`, `return` ou
`return None`, les fonctions à docstring seule et les levées de
`NotImplementedError` ou `NotImplemented`.

Les imports aliasés depuis `builtins`, par exemple
`from builtins import NotImplementedError as E`, sont résolus pour détecter
`raise E` et `raise E()`.

L'exemption des méthodes de `typing.Protocol` et des méthodes
`abc.abstractmethod` ne s'applique que si l'origine importée est encore prouvée.
Une réaffectation directe au niveau module d'un alias importé retire cet alias de
la table de preuve. Le gate ne tente pas de résoudre les réaffectations
conditionnelles, locales ou indirectes (`globals()`), qui nécessiteraient une
analyse de flot de données complète.

## Liaisons de noms : ce qui fait tomber une exemption

Une exemption `Protocol` / `@abstractmethod` repose sur la table des alias
d'import. Cette table n'est fiable que si elle suit les REDÉFINITIONS.

Toute liaison de niveau module qui écrase un nom importé le retire de la table —
`Assign`, `AnnAssign`, `ClassDef`, `FunctionDef`, `AsyncFunctionDef`, et les
cibles de `for` / `with`. Fail-closed : au moindre doute, l'exemption tombe.

```python
from typing import Protocol

class Protocol:            # écrase l'import -> l'exemption ne s'applique plus
    ...

class X(Protocol):
    def f(self): ...       # correctement signalé
```

Les imports LOCAUX à une fonction n'alimentent pas la table utilisée pour juger
les classes de niveau module : ils ne lient pas le nom global. Un
`from typing import Protocol` sous `if TYPE_CHECKING:` continue en revanche de
l'alimenter — c'est un bloc, pas une fonction, et c'est l'idiome standard.

**Limite nommée** : une réaffectation hors niveau module (conditionnelle, dans
une fonction, via `globals()`) n'est pas suivie. La fermer exigerait une analyse
de flot de données.

## Succès forcé : ce qui compte comme repli

Après un `||`, toute commande qui réussit inconditionnellement neutralise
l'échec du job requis. `true`, `:`, `echo …`, `printf …`, `exit 0` sont donc
traités comme des replis interdits — le détail de la violation NOMME la commande
détectée.

Ce n'est pas cosmétique : `gate.py || echo "en échec"` fait passer le step au
vert avec le code de retour du `echo`, alors que le gate a échoué.

`|| exit 1` et `|| false` restent tolérés : ils propagent l'échec.

## Neutralisation shell : l'ordre compte

Avant toute recherche de motif, les chaînes littérales PUIS les commentaires
sont neutralisés, en préservant longueurs et positions (les numéros de ligne
restent justes).

L'ordre est ce qui rend la règle correcte dans les deux sens :

| Commande | Verdict | Pourquoi |
|---|---|---|
| `# ne pas utiliser \|\| true` | aucune violation | le motif est dans un commentaire, jamais exécuté |
| `echo "couleur #ff0000" && verif \|\| true` | violation | le `#` est DANS une chaîne : il n'ouvre pas de commentaire, et le `\|\| true` qui suit est bien du code |
| `verif \|\| true  # justification` | violation | le motif précède le commentaire |

## Workflows : fail-closed sur structure inattendue

Un fichier de `.github/workflows/` dont la racine n'est pas un mapping, ou dont
`jobs` est présent mais d'un type inattendu, est une violation : le gate ne peut
pas analyser les jobs requis et ne doit pas réussir en silence.

Distinction préservée : un fichier SANS clé `jobs` du tout (configuration
d'action, par exemple) n'est pas signalé.

## Piège de fixture rencontré, documenté pour les suivants

Deux fixtures de test écrites en YAML brut se sont révélées fausses, pas le gate :

- `run: verif || :` rend le YAML **invalide** (`ScannerError`). Le gate rendait
  correctement `FICHIER_NON_ANALYSABLE` — son fail-closed fonctionnait.
- `run: echo "couleur #ff0000" && …` : un ` #` non quoté ouvre un **commentaire
  YAML** qui avale la fin de la ligne. PyYAML rend `echo "couleur`.

Toute fixture de workflow contenant `:`, `#` ou `|` dans une commande doit être
QUOTÉE. Diagnostiquer avant de conclure qu'un test rouge accuse le code.

