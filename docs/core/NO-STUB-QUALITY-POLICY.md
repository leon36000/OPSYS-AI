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
