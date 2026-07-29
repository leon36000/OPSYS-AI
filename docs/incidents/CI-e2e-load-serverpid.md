# Incident CI — `e2e-load` rouge en permanence sur `main`

Issue : #110. Correctif : `scripts/run-e2e.sh` + `tests/e2e/test_run_e2e_trap.py`.

## Symptôme

Le job `e2e-load` échouait **systématiquement, y compris sur `main`** — pas déclenché par une PR
en particulier. Le test de charge lui-même **réussissait** :

```
http_reqs......................: 1208    120.283421/s
default ✓ [ 100% ] 5 VUs  10s
scripts/run-e2e.sh: line 35: SERVER_PID: unbound variable
##[error]Process completed with exit code 1
```

Un vert transformé en rouge par un défaut de tuyauterie. C'est le pire des deux mondes : le
signal utile est noyé, et un job rouge permanent devient un job qu'on cesse de lire.

## Cause

`SERVER_PID` était déclaré `local` dans `run_k6`, mais `cleanup` s'exécutait sur `trap EXIT` —
donc quand le **shell** sort, **après** le retour de la fonction, quand les variables `local`
n'existent plus. Sous `set -u`, `${SERVER_PID}` devient « unbound variable » et le trap sort en 1.

Reproduction minimale, vérifiée avant toute modification :

```bash
set -euo pipefail
f() {
  local PID
  sleep 30 & PID=$!
  cleanup() { if kill -0 "${PID}" 2>/dev/null; then kill "${PID}" 2>/dev/null || true; fi; }
  trap cleanup EXIT
  echo "travail utile : OK"
  kill "${PID}" 2>/dev/null || true
}
f
echo "fin de script"
# -> travail utile : OK / fin de script / PID : variable sans liaison / rc=1
```

## Preuve du correctif — même `k6` réel, ancien puis nouveau script, tous deux en place

| | itérations k6 | checks | rc |
|---|---|---|---|
| avant | 1225 | `✓ [100%] 5 VUs 10s` | **1** |
| après | 1225 | `✓ [100%] 5 VUs 10s` | **0** |

Le travail utile était identique dans les deux cas : seule la tuyauterie changeait le verdict.

## Correctif

- `SERVER_PID` et `SERVER_LOG` déclarés au niveau du script (plus `local`), avec le pourquoi en
  commentaire ; `PORT` et `BASE_URL` restent locaux, ils ne sont pas lus par le trap ;
- `cleanup` sortie de `run_k6` et renommée `arreter_serveur`, **idempotente** (remise à vide
  après extinction) et robuste sous `set -u` (`${VAR:-}` partout) ;
- `SERVER_LOG` (le `mktemp`) est désormais supprimé — il fuyait à chaque exécution ;
- `trap` posé au niveau du script, couvrant tous les modes ;
- `arreter_serveur` appelée explicitement sur les trois chemins (serveur non prêt, échec `k6`,
  nominal) : l'arrêt est déterministe, pas seulement un effet du trap ;
- en cas d'échec, le contenu de `SERVER_LOG` est affiché sur `stderr` — sans cela un échec réel
  restait indiagnosticable.

Codes de sortie (10 / 20 / 1), modes (`e2e`, `load`, vide) et chemin SKIP-si-`k6`-absent
inchangés, vérifiés par garde avant écriture.

## Tests

`tests/e2e/test_run_e2e_trap.py` — 6 tests exerçant le **vrai** script en sous-processus avec un
`k6` factice : mode `load` nominal, absence d'« unbound variable », SKIP propre sans `k6`, syntaxe
`bash -n`, **échec de `k6`** (rc=20 + nettoyage), et **trap sur SIGTERM** — le seul chemin où le
trap est réellement indispensable, puisque `arreter_serveur` est appelée explicitement ailleurs.

RED capturé avant correctif : les deux tests exerçant le trap échouaient sur le script de `main`.

## Pièges rencontrés, à ne pas répéter

**`pkill -f <motif>` tue le processus qui l'exécute** — son propre argv contient le motif. Le
nettoyage des orphelins doit se faire en excluant explicitement son PID et son parent.

**`pgrep -f <motif>` produit des faux positifs** : il matche l'argv de `pgrep` lui-même et du
shell appelant (deux faux positifs mesurés). Une assertion « aucun processus X sur la machine »
est en outre polluée par tout orphelin préexistant. Le test compare donc les **ensembles de PID
avant/après** avec filtrage sur `/proc/<pid>/cmdline` exigeant `python` **et** `brand_server.py`.

**Un `PATH` réduit pour masquer un binaire masque aussi `bash`** : le test résolvait `bash` via
`PATH`, d'où un `FileNotFoundError` au lieu du test attendu. `bash` est désormais résolu en
absolu, et `PATH` ne contrôle plus que la découverte de `k6`.

## Redondances défensives déclarées

Non isolables par mutation, et volontaires : `${SERVER_PID:-}` est redondant avec
l'initialisation à vide au niveau du script, et l'appel explicite d'`arreter_serveur` sur le
chemin d'échec est redondant avec le trap. Les deux sont conservés en ceinture-et-bretelles :
il s'agit de nettoyage de processus, où une fuite silencieuse coûte plus qu'une ligne en trop.
