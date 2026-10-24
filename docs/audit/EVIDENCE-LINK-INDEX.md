# Index des liaisons preuves/registres -> code (R4-S11)

Généré par `scripts/evidence_index.py` — **ne pas éditer à la main**, relancer le script.
Issue : https://github.com/leon36000/OPSYS-AI/issues/593
Mesuré à commit `8977555977bc9c422d7eb8c87ae4f0657fd3eb2a`.

**reviews/** : exclu de ce lot, cf. #591, en attente de décision Nathan.**

`evidence/tasks/EXT-AUD-001-A1-R12-CANDIDATE/**` : territoire actif de la PR #566, laissé intact et non indexé.

## Statistiques (114 entrées)

| Racine | Entrées | PROUVÉ | NON_PROUVÉ |
|---|---:|---:|---:|
| `evidence/` | 43 | 9 | 34 |
| `registries/` | 69 | 0 | 69 |
| `Registres/` | 2 | 0 | 2 |
| **total** | **114** | **9** | **105** |

Granularité : un fichier versionné (git ls-files) = une entrée.

## Méthode (résumé — détail complet dans l'en-tête de `scripts/evidence_index.py`)

1. **champ-explicite** — vocabulaire : `base`, `reviewed_commit`, `reviewed_tree`, `base_tree`, `branche`, `branch`, `code_diff_sha256`, `preuves_jointes`.
2. **commit-introducteur** — commit qui a ajouté le chemin ; message complet scanné.

Champs de texte libre jamais scannés (risque de faux positif, cf. #591) : payload.evenement (registries/ledger/*.jsonl) et tout autre champ de texte libre.

## Entrées NON_PROUVÉES

| Chemin | Raison |
|---|---|
| `Registres/SCHEMA.md` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `Registres/installations.jsonl` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/AUD-CI-002/full.diff` | aucun champ du vocabulaire connu trouvé ; commit introducteur 737b3d042710 (2026-08-27) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/AUD-CI-002/prompt.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur 737b3d042710 (2026-08-27) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/AUD-CI-002/reviews/DeepSeek-V4-Pro-0813.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 737b3d042710 (2026-08-27) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/AUD-CI-002/reviews/Gemini-3.7-Flash.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 737b3d042710 (2026-08-27) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/AUD-CI-002/reviews/Muse-Spark-1.2-Contributor.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 737b3d042710 (2026-08-27) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/AUD-CI-003-004/full.diff` | aucun champ du vocabulaire connu trouvé ; commit introducteur a526da10cd51 (2026-08-27) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/AUD-CI-003-004/prompt.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur a526da10cd51 (2026-08-27) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/AUD-CI-003-004/reviews-context/README.md` | aucun champ du vocabulaire connu trouvé ; commit introducteur e6319f03ad1b (2026-08-26) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/AUD-CI-003-004/reviews/claude-opus-5-native-architecte.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur e6319f03ad1b (2026-08-26) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/CI-HARDENING-001/reviews-context/GPT-5.6-Terra-Pro.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 701ec236a64c (2026-08-11) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/CI-HARDENING-001/reviews/Claude-Opus-5-native-architecte.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 701ec236a64c (2026-08-11) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/CI-HARDENING-001/reviews/Muse-Spark-1.2.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 701ec236a64c (2026-08-11) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/CI-HARDENING-001/reviews/Qwen3.8-Max.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 701ec236a64c (2026-08-11) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r3-rejected/DeepSeek-V4-Pro-0813.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r3-rejected/Gemini-3.7-Flash.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r3-rejected/Muse-Spark-1.2-Contributor.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r4-cbe5af7-approved/DeepSeek-V4-Pro-0813.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r4-cbe5af7-approved/Gemini-3.7-Flash.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r4-cbe5af7-approved/Muse-Spark-1.2-Contributor.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r5-e9a640b-approved/DeepSeek-V4-Pro-0813.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r5-e9a640b-approved/Gemini-3.7-Flash.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r5-e9a640b-approved/Muse-Spark-1.2-Contributor.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r6-rejected-missing-tally-context/DeepSeek-V4-Pro-0813.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 27c7993bc751 (2026-08-27) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r6-rejected-missing-tally-context/Gemini-3.7-Flash.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews-context/r6-rejected-missing-tally-context/Muse-Spark-1.2-Contributor.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews/DeepSeek-V4-Pro-0813.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews/Gemini-3.7-Flash.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CODEQL-BASELINE-572/reviews/Muse-Spark-1.2-Contributor.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CORE-CAS-CONCURRENCY-584/reviews/DeepSeek-V4-Pro-0813.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CORE-CAS-CONCURRENCY-584/reviews/Gemini-3.7-Flash.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CORE-CAS-CONCURRENCY-584/reviews/Muse-Spark-1.2-Contributor.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CORE-STATUS-EVIDENCE-583/reviews/DeepSeek-V4-Pro-0813.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CORE-STATUS-EVIDENCE-583/reviews/Gemini-3.7-Flash.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `evidence/tasks/CORE-STATUS-EVIDENCE-583/reviews/Muse-Spark-1.2-Contributor.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur 5d5396970361 (2026-08-26) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/frameworks.yaml` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/ledger/.gitkeep` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/ledger/decisions.jsonl` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/ledger/executions.jsonl` | aucun champ du vocabulaire connu trouvé ; commit introducteur b614eb75a93e (2026-07-23) : aucune référence Git résoluble dans son message (hors son propre hash). |
| `registries/ledger/preuves.jsonl` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/modules.yaml` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/.gitkeep` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/Composer-2.5.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/DeepSeek-V4-Pro.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/GLM-5.2.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/Gemini-3.1-Pro.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/Kimi-K3.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/MiMo-Pro-V2.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/MiniMax-M3.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/Qwen3.7-Max.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/TRAITEMENT-TOUR-2.md` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/raw/Composer-2.5.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/raw/DeepSeek-V4-Pro.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/raw/GLM-5.2.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/raw/Gemini-3.1-Pro.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/raw/Kimi-K3.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/raw/MiMo-Pro-V2.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/raw/MiniMax-M3.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage-tour2/raw/Qwen3.7-Max.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/Composer-2.5.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/DeepSeek-V4-Pro.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/GLM-5.2.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/Gemini-3.1-Pro.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/Kimi-K3.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/MiMo-Pro-V2.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/MiniMax-M3.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/Qwen3.7-Max.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/TRAITEMENT-TOUR-1.md` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/Composer-2.5.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/DeepSeek-V4-Pro.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/GLM-5.2.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/Gemini-3.1-Pro.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/Kimi-2.7.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/Kimi-K3.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/MiMo-Pro-V2.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/MiniMax-M3.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/audit-000-cadrage/raw/Qwen3.7-Max.brut.verdict.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur fbe2c813b87f (2026-08-05) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/mock-phaseC/gemini-3.1-pro.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/mock-phaseC/glm-5.2.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/mock-phaseC/longcat-2.0.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d3c76aceab74 (2026-07-23) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/Composer-2.5.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/DeepSeek-V4-Pro.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/GLM-5.2.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/Gemini-3.1-Pro.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/Gemini-3.6-Flash.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/Grok-4.5.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/Kimi-2.7.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/LongCat-2.0.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/MiMo-Pro-V2.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/MiniMax-M3.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/Qwen3.7-Max.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/Composer-2.5.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/DeepSeek-V4-Pro.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/GLM-5.2.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/Gemini-3.1-Pro.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/Gemini-3.6-Flash.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/Grok-4.5.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/Kimi-2.7.round2.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/Kimi-2.7.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/LongCat-2.0.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/MiMo-Pro-V2.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/MiniMax-M3.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/raw/Qwen3.7-Max.txt` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |
| `registries/verdicts/phaseC-live/round-1/Kimi-2.7.json` | aucun champ du vocabulaire connu trouvé ; commit introducteur d5c5322957be (2026-07-24) hors périmètre (touche d'autres bundles du même lot) : citations non retenues. |

## Entrées PROUVÉES

| Chemin | Liaisons vérifiées |
|---|---|
| `evidence/tasks/AUD-CI-002/evidence.json` | commit:22b6beb39e8c…(champ-explicite), ref:claude/aud-c…(champ-explicite), diff:944ea105220f…(champ-explicite:export-recalcule) |
| `evidence/tasks/AUD-CI-003-004/evidence.json` | commit:5a155f98b004…(champ-explicite), ref:claude/aud-c…(champ-explicite), diff:115388ae247e…(champ-explicite:export-recalcule), commit:5a155f98b004…(commit-introducteur) |
| `evidence/tasks/AUD-CI-003-004/reviews-context/Kimi-2.7.ANCIEN-SCEAU.json` | commit:5a155f98b004…(commit-introducteur) |
| `evidence/tasks/AUD-CI-003-004/reviews/Gemini-3.7-Flash.json` | commit:5a155f98b004…(commit-introducteur) |
| `evidence/tasks/AUD-CI-003-004/reviews/Muse-Spark-1.2-Contributor.json` | commit:5a155f98b004…(commit-introducteur) |
| `evidence/tasks/CI-HARDENING-001/evidence.json` | commit:092a1367dddc…(champ-explicite), ref:opsys-core/c…(champ-explicite) |
| `evidence/tasks/CODEQL-BASELINE-572/evidence.json` | commit:b9ced941ea7a…(champ-explicite), commit:80d528d645d1…(champ-explicite), tree:1a527eb8100b…(champ-explicite), ref:codex/issue-…(champ-explicite) |
| `evidence/tasks/CORE-CAS-CONCURRENCY-584/evidence.json` | commit:22b6beb39e8c…(champ-explicite), commit:0a0d8be044b2…(champ-explicite), tree:78f93a05f8f5…(champ-explicite), tree:528acf2dee19…(champ-explicite), ref:codex/issue-…(champ-explicite) |
| `evidence/tasks/CORE-STATUS-EVIDENCE-583/evidence.json` | commit:62b9d49a7ebb…(champ-explicite), commit:eaf313ddaeea…(champ-explicite), tree:86f634bc0ac9…(champ-explicite), tree:12af0f1adfdb…(champ-explicite), ref:codex/issue-…(champ-explicite) |

