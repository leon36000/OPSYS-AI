# tests/e2e/ — Harnais e2e OPSYS-AI (P0-10a)

Preuve de bout en bout que le système FONCTIONNE (pas seulement que les tests unitaires passent).

## Contenu
- `_harness.py` — import isolé du serveur cible + `running_server` (thread daemon, teardown garanti) + helpers HTTP (timeout 5 s).
- `test_e2e_brand.py` — e2e HTTP réel contre le serveur M7 « brand » (200 /brand, 404/405 RFC 9457, YAML invalide -> 500, répétabilité).
- `test_e2e_selftest.py` — **meta-test (RED automatisé)** : prouve que les assertions MORDENT (échouent contre un stub cassé).
- `k6/brand_smoke.js` — smoke de charge k6 (seuils : `http_req_failed==0`, `p95<500ms`).
- `playwright/` — scaffold ; E2E navigateur ajouté avec l'UI dashboard (P0-5).

## Lancer
```
python3 -m pytest tests/e2e -q          # e2e Python (aucune dépendance externe)
bash scripts/run-e2e.sh e2e             # idem, via le runner
bash scripts/run-e2e.sh load            # smoke k6 seul (démarre son serveur)
bash scripts/run-e2e.sh                 # les deux
```
Codes de sortie du runner : `0` OK · `10` e2e échec · `20` k6 échec.

## CI (deux jobs distincts, aucun ne touche le contexte protégé « gates »)
- **`e2e`** : deps épinglées (`pytest==9.1.1 PyYAML==6.0.1`) + `run-e2e.sh e2e`.
- **`e2e-load`** : deps épinglées + k6 v0.54.0 épinglé par checksum sha256 + `run-e2e.sh load`.

Les deux sont informatifs au départ (promotion en check requis après stabilité, cf. avis architecte).
