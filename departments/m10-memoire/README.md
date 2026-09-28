# M10-memoire

Mémoire Long Terme — non-oubli, PREFLIGHT tracé (POSTFLIGHT applicatif hors périmètre v1).

Statut : département OPSYS complet (manifeste, SOUL, 2 skills, outils d'agent) sur le modèle
de M3-estimation, mode `ombre`. Les six stories de domaine S001-S006 du PRD sont livrées et
vertes : contrats gelés, deux registres append-only hash-chaînés distincts (Événements/Affaires,
anciennement Forge/Business — ADR-0010 décision 2), câblés sur le stockage durable de l'instance
(ADR-0009), consommation du Work Completion Trigger de M4 sans recalcul de hash, décisions à
raison obligatoire (statut par relecture), révision sans fusion, prédicat de contexte suffisant
avec trace du refus, référence `memoire_m10` vérifiable, conformité statique (dont la garde
anti-mutation).

- `department.yaml` — manifeste (`m10_memoire.outils`, aucune dépendance — M10 est la fondation
  mémoire que M9 consomme).
- `SOUL.md` — identité de l'agent.
- `skills/journaliser-une-decision/` et `skills/preflight-contexte-suffisant/` — procédures.
- `src/m10_memoire/outils.py` — deux outils composés, `m10_journaliser_decision` (validation →
  écriture Affaires → référence) et `m10_contexte_preflight` (PREFLIGHT, trace le refus sans
  jamais interrompre l'appelant), + 6 outils unitaires (WCT, révision, statuts, vérification de
  référence).
- Correctifs de fiabilité (TDD, tests dans `tests/`) :
  - `revision.py` — l'arbitrage d'une révision qui n'a jamais été signalée était accepté ;
    refusé nommément désormais (`REJ-REVISION-SIGNALEMENT-INTROUVABLE`).
  - `contexte.py` — `verifier_reference` acceptait un champ `registre` incohérent (None, vide,
    mauvais type) et un `hash_tete` positionné AVANT la ligne référencée (impossible
    causalement) dès lors qu'il existait ailleurs dans la chaîne ; les deux sont désormais des
    refus nommés.
  - `validation.py` — `valider_evenement` et `construire_verdict` étaient du code mort, jamais
    appelés par un chemin d'écriture réel ; `contexte.py` délègue désormais réellement sa
    validation du sous-dossier `EvenementMemoire` à `valider_evenement`, et
    `tracer_refus_contexte` trace un `verdict` construit par `construire_verdict`.

Vector memory, graphe de connaissances inféré, context injector et l'application effective du
PREFLIGHT/POSTFLIGHT (D-014, hook applicatif) restent GATED (hors périmètre v1, cf.
`docs/bmad/02-PRD-PM.md` §3.2 et `docs/research/R4-memory-rag.md`).
