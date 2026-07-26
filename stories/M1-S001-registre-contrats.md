# M1-S001 — Registre anti-perte chaîné + contrats gelés (socle M1)

T2 · allowed: M1 `src/`, `tests/`, `contracts/`, `fixtures/` · deps : aucune · zéro réseau/horloge.
Cadrage BMAD : `Modules M/M1-front-office/docs/bmad/` (brief analyste, PRD PM, architecture — PR #77).

## Livré
- **Registre APPEND-ONLY chaîné** : `ligne_id` = sha256 canonique déterministe, `precedent_ligne_id`,
  `valider_chaine()` détecte toute altération, **aucune API de suppression/modification exposée**
  (asserté par test), enum fermé des types d'entrée, fixture signaux `fictif: true` fail-closed,
  **zéro perte prouvée** (1 signal de la fixture = 1 ligne de registre).
- **Contrats GELÉS sha256** (D-015, tests consommateurs) : M1↔M2 `m1-lead-qualifie.v1.yaml`
  (`40433e0d…`) et M1↔M3 `m1-demande-chiffrage.v1.yaml` (`a5f42648…`) — enums fermés, contact avec
  au moins un champ non vide, `description_factuelle` 50-500 caractères **sans prix ni date**
  (frontières de vérité : prix = M3, dates = M4).
- **verdicts.py** : identifiants stables `REJ-`/`EVT-` catalogués ; **horodatage.py** exige un
  ISO-8601 **avec fuseau, fourni par l'appelant** (aucune horloge interne).

## Preuve
RED capturé (`ModuleNotFoundError: registre`) → **23 tests verts** ; régression globale 455 + 97
verts ; structure_lint VERT ; no-stub propre. Isolation par fixture autouse (fuite d'état inter-tests
détectée et corrigée).

## Note CI (dette explicite, invariant PROOF n°1)
Le job `gates` ne découvre pas encore `Modules M/M1-front-office/tests` et le manifeste interdit
`.github/` à la story → **chore T1 de branchement CI immédiatement après ce merge**, sinon la story
n'est pas prouvée en intégration continue.
