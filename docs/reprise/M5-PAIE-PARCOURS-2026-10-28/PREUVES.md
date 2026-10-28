# Preuves (commandes exactes, environnement, résultats)

Base `3ab7692f041892ec2af0cab6f241a715edac2d50` ; tête vérifiée `55b57e126eb9cbe10b53515edc05617e12164cbe` (les commits suivants ne touchent
que ces documents). Aucun résultat n'est additionné entre populations recoupées. Les reçus conservés sont dans `recus/` ; les rouges intermédiaires
(avant correction de produit) sont listés plus bas et n'ont pas été écrasés (journaux `log-*` et `junit-*` d'origine dans le scratchpad de la session).

## Environnement
Python 3.13, venv dédié (`pip install -e ".[dev]"` + `reportlab==4.5.1`, `cryptography==50.0.2`, `pypdf==6.19.0`), HOME/OPSYS_HOME/XDG/TMP privés par exécution
(`run.sh`, mode 0700, `OPSYS_BASE_URL` retiré), `ulimit -v 8000000 -u 512`, `timeout` 1500 s (3300 s pour la régression ciblée). Sources lues depuis le dépôt
(pas de montage en lecture seule : le harnais ne l'offrait pas). Réseau : proxy de session ; `revenuquebec.ca`, `canada.ca`, `cnesst.gouv.qc.ca` → 403 au tunnel.
SQLite uniquement. Aucun GPU. Aucun NAS, compte réel ni donnée réelle : fixtures `fictif: true`, PDF d'admission fictifs.

## Résultats par critère

| Critère | Commande | Résultat |
|---|---|---|
| Tête : département M5 entier + parcours HTTP + MCP + paie console existante | `pytest departments/m05-financecore/tests tests/test_console_paie_dossier.py tests/test_paie_preparatoire_integree.py tests/test_console_paie.py tests/test_console_admission_paie.py tests/test_console_paie_obligations.py tests/test_pont_heures_paie.py -q` | **2844 tests, 0 échec, 0 erreur, 0 skip** (`recus/junit-final-tete-*.xml`) |
| Lint socle + département | `ruff check src tests departments/m05-financecore` | All checks passed |
| Cohérence départements | `opsys-metier verifier` | OK : 10 départements, 314 outils, noms uniques, portées d'appareil valides |
| Aucun diff d'espaces | `git diff --check 3ab7692f HEAD` | exit 0 |
| Fichiers épinglés par l'admission | `git diff --name-only 3ab7692f HEAD` | aucun des huit fichiers Source modifié |
| Régression ciblée (console, metier, capacites, departements, outils, idempotence, identite, cles, serveur MCP, approbations — 136 fichiers) | `pytest <136 fichiers> -q --continue-on-collection-errors` (exécutée sur la tête précédant les corrections de revue) | 2718 tests : **46 échecs, 43 skip** ; les 46 échecs sont tous dans `tests/test_console_fusion_*.py` et sont **identiques sur la base** `3ab7692f` (worktree séparé, `recus/log-base-fusion-3ab7692f.txt`) : prérequis absent du harnais (`bwrap` non installé → `ERREUR_REPRENABLE` au lieu de `EXTRAIT_PREPARATOIRE`), pas un défaut du produit ni de ce travail |
| Baseline paie existante avant modification | `pytest` brut, RRQ, QC, RQAP/AE, fédéral, admission, console paie, pont M4 | 165 tests verts (sur la base) |
| QA navigateur privé (Chromium/Playwright) | `qa_serveur.py` (SQLite jetable, 127.0.0.1:8765) + `navigateur.js` | 18 étapes OK : connexion, formulaire de 80 champs rempli par le navigateur, aperçu, conservation, revue avec charge XSS (non exécutée, affichée en texte), exports JSON et HTML lisible, réouverture, correction, comparaison, vérification, 0 erreur console (`recus/navigateur-resultats-*.json`) |
| CI GitHub complète sur la tête `e9f148c7` (run `ci` n°2296) | workflow `ci.yml` sur la PR #854 | 38 jobs : 35 success, 3 skipped (`installateur`, `dependency_audit`, `mobile`), `gates` success. Runs antérieurs rouges : voir `RAPPORT.md` |
| Services QA possédés fermés | `kill` du PID du serveur QA, port 8765 refermé | `recus/recu-fermeture.txt` ; aucun autre processus lancé ; worktree de base supprimé |

## Où chaque critère de la mission est démontré

- Heures M4 lues en lecture seule → dossier → admission → composition → version → revue → export, état SQL avant/après et redémarrage :
  `tests/test_console_paie_dossier.py::test_parcours_complet_…` (aucune table autre que `registres_maillons`, `cles_chiffrement`, `mutations_appliquees`, `journal`
  ne change ; seul le registre `dossiers_paie_preparatoires` croît ; M4/M5 principal, factures, contrats inchangés) et `::test_redemarrage_…`.
- P1 et périodes suivantes, plafonds, janvier/juillet, contexte Decimal hostile, refus des composants : `test_dossier_paie_preparatoire.py` (chaîne de 26 périodes, plafonds RRQ/RQAP/AE
  exacts, édition fédérale 122e → 123e au 1er juillet, oracles indépendants en `Fraction`).
- Postes employeur : `test_cotisations_employeur_2026.py` (FSS secteurs et bornes, CNESST/normes plafond 103 000 $, FDRCMO seuil, aucune reconduction hors 2026, aucun taux par défaut).
- Rejeu exact / autre charge / CAS périmé / concurrence / panne tardive / altération SQL / clé détruite / rejeu après changement de source : `test_service_dossier_paie.py` et tests HTTP.
- Revue de la mauvaise version, autre salarié, export non revu, source modifiée, doublon : service + HTTP.
- Rôle insuffisant, owner révoqué, session expirée, CSRF, corps bornés, JSON malformé, XSS : `test_console_paie_dossier.py`.
- Agents : `test_paie_preparatoire_integree.py` (dispatcher `Capacites` et serveur MCP HTTP réel : refus, aucun montant, aucune écriture).

## Rouges intermédiaires conservés (produit, tous corrigés puis re-prouvés)
- `junit-employeur-…094927Z` : formatage Decimal sous contexte appelant (`InvalidOperation`), date hors 2026 non refusée sur RQAP/AE employeur.
- `junit-composition-…095056Z` : addition DAS hors contexte isolé (270,34 $ au lieu de 270,30 $) ; oracles de test erronés (306,52 $ est correct).
- `junit-m5-garde-…095155Z`/`095215Z` : gardes de conformité M5 (clé `cause`, aléa système, énumérations sans échappatoire) ; `junit-m5-complet-…095812Z` : classement analyse/hors analyse des nouveaux outils.
- `junit-http-dossier-…101330Z`…`101518Z` : schéma d'outil sans `horodatage`, champ de formulaire non autorisé, affichage des entrées figées.
- `junit-http-dossier-…101732Z`/`101839Z` : refus d'export sans verdict JSON ; écritures d'audit d'un refus.
- `junit-p5-coherence-…102825Z` : cohérence origine/période des cumuls (cas mal construits dans mes tests).
- `junit-socle-complet-…102421Z` : erreur de collecte `reportlab` absent du venv (prérequis du harnais, installé ensuite).
Revue de code indépendante (sous-agent, lecture seule) : 3 défauts importants, 5 mineurs ; corrigés ou documentés comme limites (voir `RAPPORT.md`).
