# R23 — Préparation CSV bornée

Clôture du pilote privé CSV M5/M10. Le [bilan ROOT R23](docs-cloture/docs--programme--REPRISE-PREPARATEUR-BILAN-R23.md--14fe960f39e4.gz) décrit le parcours et ses limites. Le lot ajoute 29 cas ciblés inclus dans la campagne ROOT. ROOT confirme 496 tests dans le JUnit d’intégration r2, zéro failure, erreur ou skip. Reçu: [preparateur-integre-root-r2-2026-10-02-resultat.json](preuves-root/preparateur-integre-root-r2-2026-10-02-resultat.json--272eb10d4603.gz). Qualité: [preparateur-qualite-root-r2-2026-10-02-resultat.json](preuves-root/preparateur-qualite-root-r2-2026-10-02-resultat.json--c9ed5e493e31.gz).

Le même lot durable reprend au plus 20 tranches transactionnelles de 100 lignes. Les seuils coopératifs de 2 s par tranche et 8 s totales sont observés aux frontières; ce ne sont pas des deadlines. Le parcours de 2 000 lignes injecte une horloge pour vérifier la borne, sans mesurer les performances. Les tests de déconnexion injectent l’indicateur HTTP et vérifient le drainage du worker; ils ne simulent pas une panne socket.

Les réponses exposent des métadonnées autorisées. Le préparateur ne fait aucune mutation comptable finale, création de facture ou paiement. Il ne lance aucun appel LLM ou externe. Les tests utilisent des données fictives. PostgreSQL demeure non qualifié et n’a pas été exécuté.

## Sources et conservation

Le delta Python R22 vers R23 est exactement : `src/opsys/console/fusion_ui.py, src/opsys/fusion_csv.py, tests/test_fusion_preparateur.py`. La sélection Python R23 contient 1093 fichiers. Le snapshot Core r3 (35209 fichiers) est encore identique; **Core n’a pas été rerun pour R23**. [SOURCES-FINALES.json](SOURCES-FINALES.json) contient les empreintes, sans recopier les sources générales.

[MANIFEST.json](MANIFEST.json) décrit 101 archives gzip déterministes, leurs tailles et SHA-256. `QUALIFICATION.json` est créée après le README et certifie les liens, archives, snapshots, HEAD et `git diff --check`. Les reçus et rouges ROOT r1/r2 sont conservés sans réécriture.
