# R17 — corrections et vérification locale

Cette passe porte sur les corrections de fiabilité et les premiers raccords agents/M1/M5/M7/M10
du 30 septembre 2026, sur la branche locale `codex/restructuration-2026-09-30`, base
`2e56c0d5605dfe575bde9244f38924d5390f2674`. Les modifications ne sont pas commitées.
Les lots d'approfondissement suivants restent distincts de cette preuve datée.

Le [bilan](../../programme/BILAN-EXECUTION-2026-09-30.md) explique les comportements et limites.
Le [plan à douze chantiers](../../programme/RESTRUCTURATION-2026-09-30.md) conserve l'ambition
des dix départements. Cette preuve ne les déclare pas complets.

## Résultats mesurés

Les JUnit Python ont été relus et leurs identifiants `(classe, nom)` comparés : **16 611 cas
distincts, 16 506 réussis, 105 sautés, aucun échec ni erreur**. Les tests ciblés supplémentaires
déjà inclus dans ces suites ne sont pas additionnés une deuxième fois.

| Périmètre | Réussis | Sautés | Preuve compressée exacte |
|---|---:|---:|---|
| Socle hors installation/E2E | 1 926 | 78 | [JUnit](preuves/integration-socle-hors-install-final.xml.gz) |
| Trois suites installation séparées | 63 | 0 | [JUnit](preuves/installer-extra-final.xml.gz) |
| Parcours E2E HTTP et appareil | 145 | 26 | [JUnit](preuves/integration-parcours-appareil-final.xml.gz) |
| M1 | 1 575 | 0 | [JUnit](preuves/integration-m1-final.xml.gz) |
| M2/M4/M6/M8/M9 | 6 731 | 0 | [JUnit](preuves/integration-m2-m4-m6-m8-m9-final.xml.gz) |
| M3, suite ordinaire | 2 133 | 1 | [JUnit](preuves/integration-m3-ordinaire-final.xml.gz) |
| M5 après correction de couverture fiscale | 2 014 | 0 | [JUnit](preuves/m5-taxes-pieces-final.xml.gz) |
| M7 | 1 011 | 0 | [JUnit](preuves/integration-m7-final.xml.gz) |
| M10 | 908 | 0 | [JUnit](preuves/integration-m10-final.xml.gz) |

Les 78 sauts du socle sont 76 cas Windows/PowerShell, un test Docker volontairement activable
et un contrôle `actionlint` absent. Les 26 sauts E2E exigent PostgreSQL/Docker non disponible
dans le PATH de cette exécution. M10 a, séparément, exercé PostgreSQL 17 en conteneur éphémère
dans le test API indiqué dans [M10-PREUVES](M10-PREUVES.md). Cela ne valide pas tous les E2E
PostgreSQL. Le saut M3 est déclaré dans son JUnit. Deux scripts M3 de mutation/instrumentation
sont exclus de la suite ordinaire; leurs preuves spécialisées restent séparées.

Le mobile passe **2 607 tests dans 118 suites**, avec `npm run typecheck` réussi après le raccord
de couverture fiscale et l'actualisation de cinq champs de la fixture moteur. Le
[rapport Jest](preuves/mobile-jest-final.json.gz) contient les cas et résultats.

Pour le Core :

- **244 tests de frontières** sont verts dans le [rapport Vitest](preuves/core-frontieres.json.gz).
- Le rapport auteur consigne **44 tests d'admission et 72 tests voisins** verts. Le
  [JUnit MCP réel](preuves/core-admission-runtime-mcp-http.xml.gz) couvre un cas de ce lot :
  vrai service Python HTTP, transport MCP et SQLite, fournisseur `StreamFn` simulé. Succès,
  mauvais bearer, budget insuffisant et rejeu vérifient le nombre d'appels fournisseur.
- Le [lanceur du fork compilé](preuves/core-cli-reel-final.json.gz) appelle réellement
  `opsys metier verifier` : dix départements, 193 outils et 109 outils déclarés pour appareil
  à la date de cette preuve. Aucun Gateway ni fournisseur n'est lancé dans ce contrôle.
- Les [25 shards de typage test](preuves/core-tsgo-core-test-final-status.json.gz) passent sur
  plusieurs invocations, après adaptation de trois fichiers de tests au helper deferred
  existant. Les premières commandes intégrales échouées restent consignées; aucun parcours
  navigateur/Playwright ou live n’a été lancé.
- La [vérification CI statique](preuves/ci-admission-cibles-final.json.gz) trouve 153 cibles
  existantes et uniques, dont les cinq fichiers admission, et vérifie Python/uv verrouillés
  ainsi que l'absence de scripts tiers implicites dans les installations pnpm.

Les nombres Core restent séparés : leurs suites peuvent se chevaucher. La compilation locale,
le packaging et le typage ne remplacent pas la CI distante ni une image Docker officielle Core.

## Traçabilité et reproduction

Le [manifeste](VERIFICATION-EXECUTION.json) conserve comptes, SHA-256 des originaux et des
archives, chemins des journaux locaux et périmètres. Les `.gz` sont des copies exactes,
reproductibles (`mtime=0`), de preuves de tests; leur décompression a été comparée aux originaux.
Leurs empreintes permettent de contrôler une copie sans enregistrer de données d'instance.
Le [manifeste du socle](preuves/integration-socle-hors-install-final.json.gz) conserve les
commandes et exclusions exactes. Les autres commandes pertinentes sont :

```sh
PYTHONPATH=src python -m pytest departments/m01-front-office/tests
PYTHONPATH=src python -m pytest departments/m05-financecore/tests
PYTHONPATH=src python -m pytest departments/m07-marketing/tests
PYTHONPATH=src python -m pytest departments/m10-memoire/tests
ruff check src tests departments core/test/opsys-runtime-admission-fixture.py
cd mobile
npm test -- --runInBand --json
npm run typecheck
```

Utiliser les versions Python/pnpm et environnements du manifeste. Pytest charge les chemins des
dix départements déclarés dans `pyproject.toml`. L'exécution MCP Core exige explicitement
`OPSYS_TEST_PYTHON`; son absence fait échouer le test. Aucune clé de fournisseur n'est nécessaire.
Les rapports rouges initiaux et les journaux interrompus sont conservés dans le workspace,
sans être présentés comme résultats verts.

## État du registre et limites

Le [registre JSON](ETAT-CONSTATS.json) conserve les 47 IDs : **42 corrigés localement, 5 partiels**.
La [réconciliation documentaire](COHERENCE-DOCUMENTAIRE.md) ferme le défaut précis C05 des
références de catalogue/architecture/garde; elle ne certifie pas toutes les pages historiques.
Les écarts découverts pendant l'implémentation sont suivis séparément, sans gonfler ce dénominateur.

Restent notamment la frontière OS opérateur/agent, la liaison universelle des cibles métier,
l'image officielle Core Docker et le VPS neuf, les avis npm modérés du mobile et la CI distante.
Les E2E Python `e2e_core` emploient une passerelle factice. La voix réelle, les connecteurs
marketing/finance, le CFO complet et l'évaluation globale de la mémoire ne sont pas prouvés.
Les réservations agents portent sur des tokens estimés; les appels incertains restent réservés.
M10 reconstruit le journal entier avant ses plafonds d'analyse. Aucun paiement, publication,
fusion, déploiement public ou appel à un fournisseur LLM réel n'a été effectué.
