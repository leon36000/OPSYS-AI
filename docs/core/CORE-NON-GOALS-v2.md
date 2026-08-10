# CORE-NON-GOALS-v2 — Ce que ce programme Core NE construit PAS (C00-005)

`OPSYS_TASK_ID:C00-005`. Ce document documente EXPLICITEMENT ce qui n'est
pas construit par le programme Core (`C00`→`C24`), conformément à
l'instruction « documenter explicitement ce qui n'est pas construit dans
ce programme » (Implémentation strictement bornée, Task Spec C00-005).
Un non-objectif n'est pas un renoncement : c'est une frontière de
périmètre, sourcée, qui protège contre la dérive et le faux `DONE`.

## 1. Aucun travail métier M1–M10 pendant le Core (CORE-003)

> Aucun travail métier M1–M10 ni interface finale n’est autorisé pendant l’exécution du Core.

Source : `sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md:25`.

Conséquence directe et vérifiée mécaniquement par chaque tâche C00-* de ce
programme (interdiction listée dans chaque Task Spec) : aucune tâche
C00-001 à C00-024 ne modifie `Modules M/*`. C00-005 elle-même ne fait pas
exception — elle documente uniquement, sans toucher à `Modules M/*` ni à
`core/src/`.

## 2. Ce qui reste hors du programme Core, nommément

D'après `sources/continuity/key/69-CORE-ARCHITECTURE-DESIGN-v1.0.0.md:107` :

> Core contracts for `ADMIN`, `VENDEUR`, `EMPLOYÉ`, `CLIENT`, offline sync, GPS windows, payments, notifications and avatar routing are frozen and tested early. The complete mobile application, 3D avatar and visual polish remain outside this Core implementation program.

Concrètement, restent HORS de ce programme Core (repris de
`sources/continuity/key/19-MOBILE-APP-OPERATIONS-BRIDGE-CANON.md`, §11
« Stratégie de livraison » — « Fin du programme ») :

- l'application mobile complète et son design final ;
- la navigation et l'expérience utilisateur cohérentes de bout en bout ;
- l'avatar et la voix dans leur version finale (`avatar/voix final`) ;
- l'optimisation mobile, l'accessibilité complète et le polish ;
- la publication sur les stores et le lifecycle mobile ;
- la qualification E2E réelle des quatre profils en conditions réelles.

Ce qui EST dû tôt, à l'inverse (même source, « Tôt dans le programme »),
reste dans le périmètre canonique mais n'est PAS construit par C00-005
elle-même (cette tâche documente le canon, elle n'implémente aucun de ces
contrats) : contrats mobile/API, modèle d'identité et permissions,
simulateur des quatre profils, verticales E2E minimales, preuve
offline/sync, provider ports pour paiement, notification, carte,
profondeur et avatar.

## 3. Aucune activation réelle des mécanismes cités au canon

`CORE-CANON-v2.md` cite des mécanismes canoniques (Legal & Compliance
Service, gates de paiement M5, workflow de recouvrement intermodule,
routage avatar). **Aucun de ces mécanismes n'est implémenté, activé ni
exécuté par C00-005** — cette tâche ne produit que 3 documents Markdown et
un fichier de test qui en vérifie la couverture textuelle. Toute
implémentation réelle (code, gates exécutables, intégrations) reste une
tâche future, hors périmètre strictement borné de C00-005.

## 4. Rappel des interdits absolus du Task Spec C00-005

- Aucun travail dans un dépôt différent de `leon36000/OPSYS-AI`.
- Aucun push direct sur la branche par défaut.
- Aucune modification de la logique métier M1–M10 hors périmètre.
- Aucun secret, tag flottant, dépendance non verrouillée ou adaptation
  silencieuse.
- Aucun rapport narratif, label GitHub ou consensus de modèles ne peut
  créer un faux `PASS`/`VERIFIED` — seule la couverture mécanique de
  `test_core_canon_coverage.py` fait foi.
