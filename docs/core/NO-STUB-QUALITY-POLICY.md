# Politique qualité NO-STUB

Le gate `scripts/quality/no_stub_gate.py` protège les racines Python déclarées
dans `core/quality-scopes.toml`.

## Exécution CI

Le gate est exécuté par le job requis `types` de
`.github/workflows/core-ci.yml` :

```sh
python3 scripts/quality/no_stub_gate.py --repo . --base-ref origin/main
```

Le checkout de ce job récupère l'historique complet puis exécute :

```sh
git fetch origin main --quiet
```

La référence `origin/main` est donc disponible pour les contrôles diff-aware.
Le gate ne doit jamais être exécuté avec `continue-on-error`, `|| true` ou une
neutralisation équivalente de son code de retour.

## Contrôles refusés

Le gate refuse notamment :

- les corps exécutables réduits à `pass`, `...`, `return` ou `return None` ;
- les levées de `NotImplementedError` ou `NotImplemented`, directes, importées
  ou qualifiées ;
- les tests modifiés sans oracle et les assertions trivialement vraies ;
- les marqueurs de dette ajoutés et les suppressions de contrôles non justifiées ;
- les jobs CI requis qui absorbent un échec shell ;
- les jobs CI requis conditionnels ou avec `continue-on-error` ;
- les jobs requis de forme invalide, notamment une définition non mapping ou un
  champ `steps` qui n'est pas une liste ;
- l'absence globale d'un id déclaré dans `target_required_job_ids`.

Un id requis peut être déclaré dans un workflow différent des autres ids :
la couverture est vérifiée sur l'ensemble de `.github/workflows/`, ce qui
permet notamment la répartition actuelle entre `ci.yml` et `core-ci.yml`.
