@AGENTS.md

# CLAUDE.md — OPSYS-AI

- Lire `AGENTS.md`, puis `docs/produit/DEFINITION-PRODUIT.md` (§1, §5, §6, et §7 du département
  concerné) avant toute livraison, et `docs/architecture/ARCHITECTURE.md` avant toute modification
  structurelle.
- Direction durable : `docs/produit/DIRECTIVES-NATHAN.md` et ADR-0012.
- Travail en cours : `docs/programme/RESTRUCTURATION-2026-09-30.md` ; `PLAN.md` conserve l'historique.
- Nouveau département ou nouvel outil : suivre `docs/architecture/DEPARTEMENTS.md`. La référence
  vivante est `departments/m03-estimation/`.
- Vérifier les comportements touchés avant livraison ; suites/lint/manifestes selon le périmètre
  défini dans `AGENTS.md`. Documents seuls : liens, cohérence et diff. CI applicable avant intégration.
- Aucun consensus de modèles ni revue d'un autre fournisseur obligatoire. Les comptes rendus
  indiquent les preuves, limites et blocages utiles sans format administratif imposé.
- `core/` est un fork dur d'OpenClaw (ADR-0008) : on le modifie librement, mais le bac à sable
  n'exécute pas son code ; il se construit et se teste en CI.
