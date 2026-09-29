# M9-strategic-intelligence

Strategic Intelligence OS — direction IA, harnais déterministe pur (aucun Council en v1).

Statut : département OPSYS complet (manifeste, SOUL, skill, outils d'agent) sur le modèle de
M3-estimation, mode `ombre`. Les cinq stories de domaine S001-S005 du PRD sont livrées et
vertes : contrats gelés (`SnapshotModule` réutilisé de M8, `CHAMPS_RAPPORT_STRATEGIQUE` 15
clés), validation structurelle d'entrée, registre append-only hash-chaîné, Business State
Graph et détection de contradiction interne, validation structurelle du rapport stratégique,
conformité statique.

- `department.yaml` — manifeste (`m9_strategic_intelligence.outils`, dépend de
  `m08-analytics` et `m10-memoire`).
- `SOUL.md` — identité de l'agent.
- `skills/etat-consolide-et-contradictions/` — procédure d'ingestion → état consolidé.
- `src/m9_strategic_intelligence/outils.py` — outil composé `m9_etat_consolide` (validation →
  registre → état consolidé, contradictions comprises) + 3 outils unitaires.
- Correctif de fiabilité (TDD, test dans `tests/test_etat_consolide.py`) : le dernier fait
  connu par module était choisi par comparaison ALPHABÉTIQUE des horodatages bruts ; comparé
  désormais en `datetime` ISO-8601 parsé, fuseaux compris (patron `m8_analytics/semantique.py`).
- Cohérence inter-départements (`tests/test_contrat_snapshot_m8_m9.py`) : le contrat
  `SnapshotModule` est validé identiquement par M8 et M9 — une valeur numérique est rejetée
  par les deux, jamais acceptée par l'un et refusée par l'autre.

- PLAN T1.5-d : le briefing du matin est borné par le code sous la limite de sortie du socle (« N autres
  éléments non affichés », lus par `m9_lire_suite_briefing`) ; `m9_produire_lecture_strategique` lit les
  alertes de mesure de chantier de M8 et cite leurs preuves, sans décider (la décision revient au
  propriétaire). `department.yaml` : `configuration.fenetre_alertes_jours`.

Council d'agents, Strategic Supervisor, scénarios narratifs et Decision Intelligence Engine
restent GATED (hors périmètre v1, cf. `docs/bmad/02-PRD-PM.md` §3.2).
