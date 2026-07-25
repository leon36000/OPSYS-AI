# tests/e2e/playwright/ — E2E navigateur (différé, honnête)

OPSYS-AI n'a pas encore d'UI web : l'unique app HTTP est l'API M7 « brand » (JSON, pas de DOM).
Les tests E2E NAVIGATEUR (Playwright + binaires de navigateur) seront ajoutés **avec l'UI dashboard**
(story P0-5). Les installer maintenant téléchargerait ~100 Mo de navigateurs sans surface à tester.

En attendant, la couverture e2e réelle est assurée par :
- `tests/e2e/test_e2e_brand.py` — e2e HTTP réel contre le vrai serveur brand (stdlib, CI-exécutable).
- `tests/e2e/test_e2e_selftest.py` — meta-test qui PROUVE que les assertions mordent (RED automatisé).
- `tests/e2e/k6/brand_smoke.js` — smoke de charge k6 (seuils : http_req_failed==0, p95<500ms).

Quand P0-5 livre le dashboard : ajouter `playwright.config`, un test de parcours, et l'installation
de navigateur PINNÉE dans le job CI « e2e » (jamais `latest`).
