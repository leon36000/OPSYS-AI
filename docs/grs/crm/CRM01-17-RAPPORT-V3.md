# M4 → M5 : provenance d'équipe V3

**Jalon historique :** les constats ci-dessous sur le refus M5 `cc2cd7e29`, l'absence de jonction positive et les prochaines étapes ont été dépassés par les compositions vérifiées et les relectures navigateur documentées dans [CRM01-17-JONCTION-INDEPENDANTE.md](CRM01-17-JONCTION-INDEPENDANTE.md). Le verdict courant et les limites de diffusion aval figurent dans [CRM01-17-RAPPORT.md](CRM01-17-RAPPORT.md).

**Producteur M4 vérifié ; jonction M5 partielle.** Branche `mission/m4-visites-integration-20261028`, PR draft #855, base du jalon `356791f223e0e4e68ffb1d190a01eb391bbf7f97`. Contrat et fixture au commit `8f6d9a572` ; propriétaire M4, fait typé, producteur et tests au commit `d83a19d4e242297400bdb65c62c331781bd5f2cd`. Aucun fichier M5 n'a été modifié ; aucune fusion, écriture comptable, paie ni production.

Le contrat [CRM01-17-CONTRAT-TEMPS-V3.md](CRM01-17-CONTRAT-TEMPS-V3.md) décrit l'API privée, l'objet V3 et les limites de confiance. Le nouveau port M4 écrit le pointage et son attestation d'équipe dans le même savepoint, avec contrôle admin, horloge serveur, CAS, audit et rejeu. La V3 revalide les pointages, la visite, la route, les audits et les préfixes de source SQL ; un ancien fait sans provenance complète reste inconnu. Il s'agit d'une déclaration d'équipe authentifiée, pas d'une preuve de présence de chaque personne ni d'une signature cryptographique. Le profil complet historique n'est pas archivé ; seule son empreinte est disponible.

| Risque ou scénario | Preuve | Résultat |
|---|---|---|
| Absence initiale du producteur | `v3/v3-red-02.xml` | Rouge réel avant le port ; `v3-red-01` conserve une erreur de collecte corrigée. |
| Pointages typés, interruption et reprise | `v3/v3-preuve-reelle-01.xml`, `v3/projection-v3-reelle-fictive.json` | Deux équipes fictives, 150 + 240 = 390 minutes, pause 30, déplacement 60 ; aucune présence individuelle inférée. GPS manuels arbitrés par primitives, revue de complétion simulée par primitive M4. Projection issue de SQLite et du vrai producteur, fichier SHA-256 `874a116ff4d4a71234d749d8eea6400483e587b1394aeb752956577c6769093b`. |
| Compatibilité V2, homonyme, sources et sécurité | `v3/v3-regression-01.xml` | 67 tests, aucun échec ni skip ; comprend V2, V3, reprises et registre. Homonyme personne/équipe, source périmée, changement tardif, audit falsifié, rôle révoqué, rollback tardif, rejeu et relecture après fermeture sont exercés. |
| Nouveau type de registre | `v3/v3-m4-complet-01.xml` | Premier lot : échec du test de catalogue gelé lors d'un état de travail mutable ; le nouveau type a ensuite été explicitement ajouté à la liste ratifiée et au contrat. Ce lot n'est pas une preuve sur la tête finale. |
| Format M5 | `v3/m5-v3-compat-01.log` | Archive M5 `cc2cd7e29b82a0607768b5c22732d11f6e89dd10` : le vrai validateur refuse la projection réelle V3 avec `version non prise en charge`. Aucun adaptateur de confiance M4 → M5, ni coût complet, n'est démontré. |
| Suite M4 intégrale | `v3/v3-m4-complet-02.xml` | 3 279 tests, 0 échec, 0 erreur, 0 skip ; exit 0, durée 258,125 s, sur le code `d83a19d4e` figé. Ruff `v3-lint-final-01.log` : exit 0. |

La fixture contractuelle synthétique `CRM01-17-FIXTURE-TEMPS-V3.json` n'est pas une sortie réelle ; sa source et son empreinte sont épinglées dans le contrat. Le calcul pur M5 `chiffrer_visites`, appelé séparément avec la projection M4 réelle fictive et les deux taux fictifs du scénario, donne 250 + 480 = 730 CAD (`v3/m5-v3-calcul-pur-01.log`, exit 0). Ce calcul contourne le validateur M5 qui refuse V3 ; il ne prouve pas l’adaptateur de confiance et ne constitue pas un coût certifié ou réel.

QA : Python 3.12 et dépendances du venv privé, homes/TMP/OPSYS/XDG privés, sources montées en lecture seule, réseau/PID isolés, seccomp ; boucle locale uniquement pour les tests OSRM. Lots bornés à 2 CPU, 2 Gio, 64 tâches, 600 secondes au maximum et deux processus QA simultanés. Les scripts et sorties sont dans `CRM01-17-PREUVES/v3/`. `v3-preuve-reelle-01` conserve des données fictives seulement. Voir aussi le checkpoint antérieur pour les quatre échecs V1 et la suite M4 précédente. Le profil et l'audit proviennent de la fixture locale, pas de données réelles.

Prochaine étape : communiquer le contrat et le commit M4 au propriétaire M5 dans le cadre de coordination autorisé, puis composer les SHA explicites dans un dossier QA séparé lorsque le consommateur acceptera la V3. Tester la provenance de confiance, les refus et l'oracle économique avec de vraies fonctions M4 et M5 ; distinguer cette jonction d'une fixture et des tests purement locaux. La qualification navigateur et PostgreSQL reste distincte.

Commande de la suite intégrale, depuis le clone isolé ; la sortie et le code de retour ont été capturés dans les preuves :

```sh
QA="$PWD/../preuves-m4-v2"
env HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 timeout 600s systemd-run --user --scope --quiet -p MemoryMax=2G -p TasksMax=64 -p CPUQuota=200% taskset -c 0,1 bwrap --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc --bind "$QA" "$QA" --chdir "$PWD" -- python3 "$QA/runner-loopback.py" "$QA/venv/bin/python" -m pytest -p no:cacheprovider -q departments/m04-field-ops/tests --junitxml="$QA/v3-m4-complet-02.xml"
```

GitGuardian était le seul contrôle distant visible et réussi sur `42da7f6924b7d75cdea916fa623fd0c9fa2dd278` avant ce reçu documentaire. `git diff --check` sur les seuls fichiers de code entre la base V3 et `d83a19d4e` est vert ; les logs de preuves reproduisent à l'identique les espaces de sortie pytest, et un contrôle global les signale. Le dernier état CI de la PR doit être consulté pour sa tête exacte.
