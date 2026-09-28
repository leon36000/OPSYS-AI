# M8-analytics

Analytics — vérité chiffrée, XmR, le LLM ne calcule jamais.

Statut : département OPSYS complet (manifeste, SOUL, skill, outils d'agent) sur le modèle de
M3-estimation, mode `ombre`. Les six stories de domaine S001-S006 du PRD sont livrées et
vertes : contrats gelés, validation d'entrée, dictionnaire de métriques (avec garde de
devise CAD), registre append-only hash-chaîné, couche sémantique, détection XmR, rapports
filtrés par rôle, conformité statique et digest quotidien.

- `department.yaml` — manifeste (`m8_analytics.outils`, dépend de `m07-marketing`).
- `SOUL.md` — identité de l'agent.
- `skills/rapport-analytique-quotidien/` — procédure d'ingestion → rapport.
- `src/m8_analytics/outils.py` — outil composé `m8_rapport_metriques` (validation → registre →
  sémantique → XmR → rapport) + 5 outils unitaires.
- Correctifs de fiabilité (TDD, tests dans `tests/`) : `ZeroDivisionError` sur un historique
  vide dans `xmr.py` ; `rapports.py` fail-closed pour un rôle sans liste d'autorisations ;
  `validation.py` refuse désormais les valeurs de snapshot non textuelles (PRD §5.2) ;
  `dictionnaire.py` refuse une devise monétaire non CAD (garde qui rejette nommément la
  métrique M7 historiquement en EUR — docs/research/R9-m7-m8.md §1.3).

DuckDB/Parquet, MMM (PyMC-Marketing) et l'orchestrateur horaire réel restent GATED (hors
périmètre v1, cf. `docs/bmad/02-PRD-PM.md` §3.2).
