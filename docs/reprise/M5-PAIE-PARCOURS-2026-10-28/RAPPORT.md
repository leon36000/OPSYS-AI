# Rapport de livraison — M5 : parcours de paie préparatoire

- **Mission / responsable** : M5-PAIE-PARCOURS-PREPARATOIRE ; conversation Claude Code de mission (Nathan).
- **Dépôt / branche / base / tête** : `leon36000/OPSYS-AI` ; `mission/codex-finance-paie-preparatoire-20261028` ; base `3ab7692f041892ec2af0cab6f241a715edac2d50` ; tête de code vérifiée `55b57e126eb9cbe10b53515edc05617e12164cbe`.
- **PR draft** : https://github.com/leon36000/OPSYS-AI/pull/854 (base `codex/restructuration-2026-09-30`).
- **Résultat métier observable** : avec un employé et un employeur fictifs, le propriétaire ouvre un dossier depuis les heures M4 validées, voit l'admission et les manques,
  exécute les vrais calculateurs, conserve la version exacte, compare une correction, révise le dossier (version + hash) et exporte JSON/HTML pour son professionnel.
  Aucun versement, aucune remise, aucun document fiscal officiel. `PREPARATOIRE` / `NON_QUALIFIEE_POUR_PAIE` partout.
- **Réutilisation** : brut régulier, port M4, admission serveur, RRQ/QC/RQAP-AE/fédéral, modèle de journal chiffré, stockage et coffre de clés du socle (aucune migration).
- **Fichiers possédés** : `departments/m05-financecore/{src,tests,docs,contracts}` (nouveaux modules, `outils.py`, `analyse.py`), `src/opsys/console/{paie_dossier_ui,paie_ui}.py`, `tests/test_console_paie_dossier.py`, `tests/test_paie_preparatoire_integree.py`, docs de mission.
- **Commit de raccord partagé séparé** : `RACCORD COMMUN console … metier.executer` (`src/opsys/console/metier.py`).

| Critère métier | Code/contrat | Preuve | Verdict réel |
|---|---|---|---|
| Parcours M4 → export | `service_dossier_paie`, `paie_dossier_ui` | test HTTP réel + QA navigateur | démontré (SQLite, données fictives) |
| P1 et périodes suivantes, plafonds, sources, arrondis | `dossier_paie_preparatoire` + moteurs existants | chaîne de 26 périodes, oracles Fraction | démontré dans le domaine |
| Totaux seulement si tous postes couverts | `matrice_et_totaux` | tests de couverture, revue complète exige tous les totaux | démontré |
| Postes employeur (RRQ er., FSS, CNESST, normes, FDRCMO) | `cotisations_employeur_2026` | oracles indépendants | calculé sous déclaration ; sources non qualifiées |
| Versions, CAS, rejeu, rollback, altération | `journal_dossiers_paie` | tests service/HTTP/concurrence | démontré (SQLite) |
| Revue liée version+hash, comparaison, export CPA | `revue`, `comparer`, `export_paie_preparatoire` | tests + navigateur | démontré |
| Accès : owner seul, CSRF, XSS, corps bornés | `paie_dossier_ui` | tests HTTP | démontré |
| Agents : aucun accès | `roles_appareil` vide | dispatcher + MCP HTTP réel | refus démontré ; outils **listés** sur le MCP M5 |

## Limites et critères non vérifiés
- **Non qualifié** : aucune qualification fiscale ou juridique ; sources employeur lues en texte officiel par un service tiers, **octets des PDF non re-hachés** ; empreintes PDF épinglées des moteurs existants non revérifiées (réseau 403). Maximum normes du travail 103 000 $ lu deux fois ; FSS (formule, arrondi) relu à la source ; taux normes 0,06 %, seuil FDRCMO, CNESST et RRQ employeur : une lecture. Classement SCIAN de la rénovation = déclaration humaine. À relire par le CPA.
- **Admission en production** : les quatre PDF épinglés ne sont pas dans le dépôt ; tant qu'ils ne sont pas déposés, l'admission refuse (`ADMISSION_REFUSEE`). Les tests utilisent des PDF fictifs avec la vraie configuration serveur recalculée.
- **Hors domaine (restent inconnus/HORS_COUVERTURE)** : surtemps, vacances/fériés payés à part, primes, avantages imposables, rétroactif, changement d'emploi ou de province, régime CCQ, années à 27 paies, autres années que 2026, base hebdomadaire CNESST, FDRCMO au-delà de 2 M$, bulletin/T4/RL-1/RE. M5.4 et FinanceCore **ne sont pas** terminés.
- **Conventions d'arrondi non prescrites par les sources** : cent demi supérieur pour CNESST et normes par période (documenté dans l'instantané). CNESST et FSS sont des estimations périodiques.
- **Confidentialité** : la clé AES de chaque dossier est dans la même base (protège contre une lecture du registre seul, pas contre le vol de la base entière). Détruire la clé d'un dossier rend le journal illisible (fail-closed) : l'effacement Loi 25 par destruction de clé n'est **pas** offert (décision humaine, hors mission). Les octets d'export ne sont pas stockés : un export audité n'est relisible qu'avec le même gabarit/code (reproductibilité à code constant).
- **Idempotence partagée** : un refus transitoire (`SOURCE-REFUSEE`, stockage) est rejoué sous le même `mutation_id` ; le formulaire génère un nouvel identifiant à chaque affichage. Le plafond `MAX_ENTREES` est global (20 000 événements).
- **Non exercés** : PostgreSQL, VPS, CI GitHub (0 check observé sur la PR au moment du rapport), visites M4 multiples de la mission parallèle, agents autorisés (aucun accès livré).
- Régression ciblée : 46 échecs `test_console_fusion_*` identiques sur la base (prérequis `bwrap` absent), non causés par ce travail.

## Contrats à intégrer et reprise
Voir `RACCORD-COORDINATEUR.md` et `CONTRATS.md`. **Prochaine action** : (1) intégrer le commit de raccord ; (2) déposer les quatre PDF d'admission ; (3) laisser tourner la CI complète sur la PR et rejouer `tests/test_console_paie_dossier.py` sur la tête portant les visites M4 ; (4) faire relire par le CPA les règles employeur et le gabarit d'export ; (5) décider si les outils doivent être masqués aux agents (`port_console_prive_requis`).
Processus QA possédés : serveur console 127.0.0.1:8765 (PID noté dans `recus/recu-fermeture.txt`) fermé ; aucun autre service laissé actif.
