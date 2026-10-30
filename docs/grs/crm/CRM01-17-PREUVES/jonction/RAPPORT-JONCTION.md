# Preuve de jonction M4/M5 — portée et limites

- Base M4 archivée : `d3426c71d6b9201382a531bb84441af6759579ea`.
- Seul le répertoire `departments/m05-financecore` a été superposé à partir de l'arbre Git `a5b977af29c9b62f2e406c0e2369ebb27242f365` ; les modifications M5 hors de ce répertoire ne sont pas superposées. Il ne s'agit pas d'un merge ni d'une branche à livrer.
- Test synthétique de jonction : `repo/departments/m04-field-ops/tests/test_jonction_m4_m5_temp.py`, SHA-256 `c3200771176c407b58c77bce04210e189906d891c04df1eea226fba3380a1939`.
- Copie obtenue dans un dossier privé par `git archive d3426c71d | tar -x -C ../preuves-jonction-m4-m5/repo`, suivi de `git archive a5b977af29c9b62f2e406c0e2369ebb27242f365 departments/m05-financecore | tar -x -C ../preuves-jonction-m4-m5/repo`. Aucun checkout opérationnel, aucune branche modifiée.

Exécution depuis `preuves-jonction-m4-m5`, venv initialement mis en place pour M4 :

```sh
QA="$PWD"
REPO="$QA/repo"
BASE="$(dirname "$QA")"
env HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" PYTHONPATH="$REPO/departments/m04-field-ops/tests:$REPO/tests/fixtures" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 timeout 90s systemd-run --user --scope --quiet -p MemoryMax=2G -p TasksMax=64 -p CPUQuota=100% taskset -c 0 bwrap --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc --bind "$QA" "$QA" --chdir "$REPO" -- python3 "$BASE/preuves-m4-v2/runner-tests.py" "$BASE/preuves-m4-v2/venv/bin/python" -m pytest -p no:cacheprovider -q departments/m04-field-ops/tests/test_jonction_m4_m5_temp.py --junitxml="$QA/jonction-03.xml" > "$QA/jonction-03.log" 2>&1
```

Sortie pytest : `.F [100%]`, 2 cas, 1 échec, 0 erreur, 0 omission, exit pytest 1. Le premier test vert construit réellement le chantier fictif SQLite par la fixture M4 : export `projeter`, WCT dans le registre, validation et chiffrage M5, puis fonction M5 `_main_d_oeuvre_ventilee`. Les minutes sont 390 travaillées, 30 de pause et 60 de déplacement. Le validateur accepte la structure, refuse l'exploitation en présence d'équipes non établies, et rejette un CAS périmé ; la ventilation refuse un total. Aucun coût financier n'est certifié.

Le second test est volontairement rouge : il altère une projection en mémoire, remplace les équipes inconnues par des équipes « identifiee » avec la justification `egalite_route_et_prevision`, retire les inconnus et recalcule son empreinte. Le validateur M5 renvoie exactement `{'valide': True, 'exploitable': False, 'raisons': ['revue du chantier en attente']}` alors que le test exige le refus. L'égalité des identifiants n'est pas une preuve du type équipe et ne correspond plus au contrat M4. La projection altérée ne provient pas du port M4 ; ce test ne démontre ni contournement réel du port M4 ni attaque de production. Le validateur M5 documente explicitement que l'empreinte n'authentifie pas et exige un adaptateur propriétaire de confiance ; ce chemin d'autorité, l'accès à des tarifs et une imputation certifiée n'ont pas été exercés. Il faut synchroniser le contrat M5 et vérifier séparément sa provenance avant une jonction positive.

Traces conservées sans écrasement : `jonction-01.log` (exit 2, chemin du harnais erroné), `jonction-02.log/xml` (exit 1, erreur de signature de ce test, corrigée avant 03), `jonction-03.log/xml` (1 vert, 1 rouge). SHA-256 respectifs : `e37dd6c9a81d18f8769c4a37ac137a60e2a065c5972e80a6b5399bb03fc194f3`, `1c217e5862f8cfff618559c0a06b6e988eb22df7edeaca3b7b7da58eb2fdd74b`, `8acb9e5240bf967e6c5e18df0c29e772bf49b4d5ff45af512f6c8c0444de16b9`, `aab277f6aa9c68f75f65027670721c56998fd68c4af40cb5aefd048f79d74442`, `6a0afdcadfb67bbbc3f3a5cd8f101cfe4e0676783221396511cf3c520009a7c2`.

Le processus systemd, pytest et le namespace sont terminés ; aucun service ou serveur n'a été lancé. Données, home et SQLite fictifs dans le dossier privé.
