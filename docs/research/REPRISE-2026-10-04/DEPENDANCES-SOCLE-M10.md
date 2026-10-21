# Dépendances de test du socle et contrat privé M10 — 4 octobre 2026

La CI sur `669f32165e30aaf8e172a919fe9265a01e6b9939` révèle cinq erreurs de collecte
au socle (job 111336064318), ainsi qu’une erreur M10 (job 111336064411).
Le socle importe ReportLab sans installer l’extra `soumission`. M10 et deux tests
HTTP du socle importent `httpx`, alors que le SDK MCP n’installe transitivement
que `httpx2`, qui fournit un autre module Python.

Le correctif ajoute `httpx==0.28.1` à l’extra de développement, et `soumission`
aux deux étapes d’installation du socle. ReportLab reste optionnel pour le produit.
`uv.lock` est régénéré avec uv 0.12.19 : deux lignes ajoutées, aucune version ni
source changée parmi les 83 paquets. L’export runtime demeure identique à
`requirements-runtime.lock.txt` après les deux lignes d’en-tête générées.
L’export de test contient httpx 0.28.1 et ReportLab 4.5.1.

Après réparation de l’import HTTPX, le test M10 révèle un second défaut : son
ensemble attendu oublie l’outil privé existant `opsys_contexte_creer_ticket_memoire`.
Le test exige maintenant les trois outils privés réels, et vérifie explicitement
que les deux émetteurs privés sont absents du catalogue public. Les contrôles
HTTP 401, de bearer privé et de falsification d’agent restent actifs.
Aucun outil public nouveau et aucune modification du propriétaire M10.

## Qualification ROOT

- `qa-r39` : collecte des cinq fichiers affectés réussie (109 cas collectés),
  Ruff et actionlint réussis ; 71 tests réussis et un échec du contrat privé obsolète.
- `qa-r40` : source finale figée, trois fichiers entiers : **72 réussis, aucun ignoré**.
  Cela inclut le transport HTTP M10 réel. Ruff et actionlint réussissent.
  Les 109 cas des cinq autres fichiers ont seulement été collectés ; ils ne sont
  pas déclarés exécutés par cette campagne.
- `qa-r41` : scan Gitleaks des quatre fichiers modifiés, aucune alerte brute.
- L’essai de verrouillage hors ligne échoue sur un cache vide ; son résumé est conservé.
  Le verrouillage suivant réussit sans isolation de build. Aucun environnement neuf
  de dépendances n’a été installé localement ; cette qualification relève de GitHub.

La PR #623 reste en brouillon. La CI globale n’est pas encore verte : les preuves M3
ont notamment atteint le délai de 90 minutes, et le gate mobile demeure rouge.
Aucun gate n’est affaibli par ce correctif. Les nouvelles validations distantes
sont requises avant de qualifier l’environnement verrouillé complet.

[Archive](preuves/DEPENDANCES-SOCLE-M10-r1.tar.xz) et
[inventaire SHA256](preuves/DEPENDANCES-SOCLE-M10-r1.json) conservent diagnostics,
exports, verrou antérieur, reçu final, échec intermédiaire et résultats ROOT.
