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

Les deux derniers contrôles portent les codes `REQUIRED_JOB_STRUCTURE_INVALIDE`
et `REQUIRED_JOB_ABSENT`. Ils ne s'appliquent qu'aux ids listés dans
`target_required_job_ids` : un job facultatif de forme inattendue reste ignoré,
pour qu'un durcissement ne se paie pas en faux positifs sur le reste du dépôt.

## Conditionnelles shell et `exit 0`

Un `exit 0` situé dans une branche conditionnelle est légitime : il exprime une
sortie choisie, pas un contournement. Le gate distingue les deux en lisant les
ouvertures (`if`, `case`), les fermetures (`fi`, `esac`) et les `exit 0` **dans
leur ordre d'apparition**, y compris plusieurs fois sur une même ligne.

```sh
if true; then exit 0; fi        # accepté — la sortie est conditionnelle
if false; then :; fi; exit 0    # refusé  — la sortie est après le `fi`
```

Raisonner ligne par ligne ne suffit pas : sur la seconde forme, la présence d'un
`if` quelque part sur la ligne couvrirait à tort tout ce qui suit.

Les mots-clés ne comptent qu'en **position de commande** (début de ligne, ou
après `;`, `|`, `&`, `(`, `then`, `do`, `else`). Sans cette borne, une option
longue ouvrirait une garde imaginaire et masquerait un contournement réel :

```sh
grep --ignore-case motif fichier; exit 0    # refusé — `case` n'ouvre rien ici
```

## Absence d'implémentation

La sentinelle `NotImplemented` et l'exception `NotImplementedError` sont
refusées à égalité, sous leurs formes nue, appelée, importée sous alias et
qualifiée par attribut. Un attribut du même nom qui n'est pas levé n'est pas
concerné.
