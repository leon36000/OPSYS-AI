# tests/e2e/ — Harnais e2e OPSYS-AI (P0-10a)

Preuve de bout en bout que le système FONCTIONNE (pas seulement que les tests unitaires passent).

## Contenu
- `_harness.py` — import isolé du serveur cible + `running_server` (thread daemon, teardown garanti) + helpers HTTP (timeout 5 s).
- `test_e2e_brand.py` — e2e HTTP réel contre le serveur M7 « brand » (200 /brand, 404/405 RFC 9457, YAML invalide -> 500, répétabilité).
- `test_e2e_selftest.py` — **meta-test (RED automatisé)** : prouve que les assertions MORDENT (échouent contre un stub cassé).
- `k6/brand_smoke.js` — smoke de charge k6 (seuils : `http_req_failed==0`, `p95<500ms`).
- `playwright/` — scaffold ; E2E navigateur ajouté avec l'UI dashboard (P0-5).

## Dépendances et lancement

Le harnais E2E dépend de PyYAML et pytest. Le lock
`tests/e2e/requirements.lock` contient ces paquets et leurs dépendances
transitives avec des hashes obligatoires. Le harnais refuse tout interpréteur
implicite : `PYTHON_BIN` doit pointer vers l'environnement préparé.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r tests/e2e/requirements.lock
PYTHON_BIN=.venv/bin/python bash scripts/run-e2e.sh e2e
PYTHON_BIN=.venv/bin/python bash scripts/run-e2e.sh load
```

## Lancer les tests directement

```
.venv/bin/python -m pytest tests/e2e -q  # e2e Python (dépendances du lock)
PYTHON_BIN=.venv/bin/python bash scripts/run-e2e.sh e2e
PYTHON_BIN=.venv/bin/python bash scripts/run-e2e.sh load
PYTHON_BIN=.venv/bin/python bash scripts/run-e2e.sh                 # les deux
```
Codes de sortie du runner : `0` OK · `10` e2e échec · `20` k6 échec.

## CI (deux jobs distincts, aucun ne touche le contexte protégé « gates »)
- **`e2e`** : Python 3.12 fourni par `setup-python`, lock E2E installé avec
  `--require-hashes`, puis `PYTHON_BIN=python3 run-e2e.sh e2e`.
- **`e2e-load`** : même lock + k6 v0.54.0 épinglé par checksum sha256 +
  `PYTHON_BIN=python3 run-e2e.sh load`.

Les deux sont informatifs au départ (promotion en check requis après stabilité, cf. avis architecte).
