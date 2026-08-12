# Politique qualité NO-STUB

Le gate `scripts/quality/no_stub_gate.py` protège le dépôt contre les
implémentations incomplètes et les protections qualité artificiellement
affaiblies.

## Codes refusés

| Code | Refus |
| --- | --- |
| `EXECUTABLE_PASS` | Fonction dont le corps utile est seulement `pass`. |
| `EXECUTABLE_ELLIPSIS` | Fonction dont le corps utile est seulement `...`. |
| `NOT_IMPLEMENTED_STUB` | Fonction qui lève `NotImplementedError`. |
| `DOCSTRING_ONLY_BODY` | Fonction dont le corps ne contient qu'une docstring. |
| `EMPTY_PRODUCTION_FILE` | Module Python de production vide ou blanc. |
| `TRIVIAL_ASSERTION` | Assertion ajoutée sur une constante vraie. |
| `TEST_WITHOUT_ORACLE` | Test ajouté ou modifié sans assertion, attente ou autre oracle reconnu. |
| `NEW_SKIP_OR_XFAIL` | Appel de skip ou décorateur skip/xfail ajouté. |
| `FORBIDDEN_MARKER` | Marqueur de dette dans un commentaire ajouté. |
| `UNJUSTIFIED_SUPPRESSION` | `type: ignore`, `noqa` ou `nosec` ajouté sans justification structurée. |
| `SCOPE_ROOT_OMITTED` | Un lanceur de scan énumère une partie, mais pas toutes, des racines Python contractuelles. |
| `REQUIRED_JOB_SOFT_FAILURE` | `continue-on-error: true` dans un job CI requis ou une de ses étapes. |
| `REQUIRED_JOB_FORCED_SUCCESS` | Commande d'un job CI requis qui neutralise un échec shell. |

## Deux niveaux de contrôle

Les règles anti-stub sont appliquées à tous les fichiers Python du périmètre,
sans dépendre du diff. Un stub déjà présent reste donc interdit.

Les règles diff-aware sont limitées aux lignes, appels, décorateurs et fonctions
ajoutés ou modifiés depuis `base_ref`. Le gate récupère ces lignes avec Git. Si
la référence ou le dépôt Git ne peut pas être lu, il traite tout le fichier
comme ajouté : une erreur d'infrastructure ne doit pas masquer une violation.

Il est interdit de baseliner un stub existant. Déplacer une violation hors du
diff, l'ajouter à une liste d'exceptions ou modifier la référence ne rend jamais
acceptable un corps vide, une ellipse exécutable ou un
`NotImplementedError`.

## Contrat de périmètre des scans

Le gate vérifie les listes littérales de chaînes présentes dans les lanceurs
nommés `run_*` et dans `core/scripts/`. Lorsqu'une telle liste contient au moins
une racine de `python_roots` mais n'en contient pas toutes, il émet
`SCOPE_ROOT_OMITTED` et nomme les racines manquantes.

Cette restriction de portée est intentionnelle : les listes de racines dans les
tests et fixtures décrivent fréquemment des scénarios partiels légitimes. Dans
un lanceur de scan, une énumération partielle est plus dangereuse qu'une absence
totale de liste, car elle donne une apparence de couverture exhaustive tout en
laissant silencieusement une partie du périmètre hors du contrôle.

Cette règle lit exclusivement
`<repo>/core/quality-scopes.toml`, où `<repo>` est le dépôt analysé. Si ce
contrat est absent ou invalide, le périmètre est inconnu et la règle ne produit
aucune violation.

## Exemptions d'interface

Une méthode dont le corps est `...` est admise uniquement dans deux cas prouvés
par l'AST :

1. la méthode porte `@abstractmethod` ou `@abc.abstractmethod` ;
2. la méthode appartient à une classe héritant de `Protocol` ou
   `typing.Protocol`.

Ces exemptions représentent des contrats de type explicitement déclarés, non
une absence d'implémentation dissimulée. Elles ne s'appliquent pas à
`NotImplementedError`, qui demeure interdit même dans une interface.

## Périmètre

`core/quality-scopes.toml` est la source unique de vérité des racines Python et
des identifiants de jobs CI requis. Les consommateurs chargent ce contrat avec
`tomllib`; ils ne doivent pas recopier les racines dans leur code.

## Exécution locale

Depuis la racine du dépôt :

```bash
python scripts/quality/no_stub_gate.py --repo . --base-ref HEAD
```

Pour vérifier un périmètre ponctuel :

```bash
python scripts/quality/no_stub_gate.py --repo . --base-ref HEAD --scope scripts
```

`--scope` peut être répété. Sans `--scope`, le gate utilise les racines définies
dans `core/quality-scopes.toml`.
