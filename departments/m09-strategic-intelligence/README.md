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
- PLAN T1.5-d (dernier reste) : `m9_lire_alertes_m8` (`admin`) est borné comme le briefing. Avant, il rendait TOUTES
  les alertes de M8 reçues, sans limite : au-delà d'une dizaine, la réponse dépassait les 6 000 caractères de
  `Capacites` et l'app recevait un aperçu coupé. Maintenant il accepte `depart` (entier ≥ 0, 0 par défaut) et
  rend autant d'alertes que `BUDGET_SORTIE` en laisse tenir (le budget de `m9_lire_suite_briefing`, mesuré par le
  code sur la taille sérialisée). Ordre stable : le plus récent d'abord (`horodatage_reference` comparé en
  instant, fuseaux compris), puis `evenement_id` croissant. Pas de filtre de date. La réponse est un objet
  `ALERTES_M8` : `alertes`, `total`, `depart`, `affichees`, `reste`, `prochain_depart` (nul à la fin), `message`,
  `ordre`, `source`. Un `depart` égal au total rend une page vide ; au-delà, ou négatif, un refus métier qui dit
  de reprendre à 0 ; une alerte incomplète, à l'horodatage illisible ou plus grosse que la borne est un refus qui
  la nomme (jamais ignorée). Code : `lecture_alertes.py` (module pur). **Changement de forme :** la réponse était
  la liste nue ; une liste ne peut porter ni total ni `prochain_depart`, et cette forme n'était pas un contrat
  gelé (aucun schéma, aucune entrée sous `contracts/`, aucun consommateur dans `src/`, `mobile/` ou les E2E ;
  seuls deux tests la figeaient, mis à jour). Les alertes sont maintenant sous la clé `alertes`. L'app mobile
  n'appelle pas cet outil : aucun écran ne change.

Council d'agents, Strategic Supervisor, scénarios narratifs et Decision Intelligence Engine
restent GATED (hors périmètre v1, cf. `docs/bmad/02-PRD-PM.md` §3.2).
