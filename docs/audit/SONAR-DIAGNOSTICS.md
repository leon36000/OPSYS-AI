# Diagnostic Sonar — issue #182

Statut : candidat de diagnostic, non qualifié sur le compte Sonar privé. Ne ferme pas #182 et ne constitue pas une qualification globale d'OPSYS-AI.

## Utilisation

Dans une copie isolée du candidat, préparer le vrai répertoire `.opsys/diagnostics` à la racine du dépôt, avec permissions privées. Aucun composant ne doit être un lien symbolique. Fournir `SONAR_TOKEN` depuis l'environnement autorisé, sans l'afficher ni le transmettre dans une conversation. Ne pas créer de credential automatiquement et ne pas réutiliser un jeton GitHub.

```sh
python3 scripts/sonar_diagnostics.py --revision fcb65bcf20980a0b36847dbd41808527ba616d52
```

Revalider la révision courante avant exécution. **L'option `--output` a été supprimée** : l'outil génère `sonar-main-<aléatoire>.json` dans le répertoire fixe `.opsys/diagnostics` du dépôt contenant le script, indépendamment du répertoire courant. Le nom créé est affiché après export. Un ancien argument de destination est refusé avant tout accès réseau ; aucune valeur CLI ne sélectionne un chemin de publication.

Publication sans écrasement, fichier mode 0600, opérations ancrées au même descripteur de répertoire et refus des symlinks. Le répertoire doit déjà exister. POSIX avec O_NOFOLLOW/O_DIRECTORY/dir_fd requis, sinon refus explicite. L'API interne de publication conserve en plus une validation stricte des noms/chemins.

Ne pas versionner les exports ; vérifier leurs métadonnées avant partage. L'outil ne modifie pas `.gitignore` et ne prétend pas que les fichiers sont automatiquement ignorés.

## Collecte

Python 3.12+ et bibliothèque standard. GET HTTPS seulement vers sonarcloud.io ; projet `leon36000_OPSYS-AI`, branche `main` fixes. Session authentifiée et accès au projet obligatoires ; révision exacte et identité d'analyse contrôlées avant/après. Pagination complète et bornée, redirections refusées, pas de retry caché. Douze métriques, conditions du gate, anomalies, hotspots et blocs dupliqués. Messages libres, auteurs, identités de compte et extraits de code non sélectionnés. Le SHA-256 de l'export n'est pas une signature Sonar.

Codes : 0 collecte achevée avec gate/conditions OK et métriques mesurées ; 1 rapport exporté mais gate rouge ; 2 collecte/publication refusée ; 3 rapport avec état incomplet/non évalué. **`quality_verified` reste false dans tous les cas.** Une collecte n'est pas un audit de tout le dépôt.

Timeout socket 15 secondes, 8 Mio maximum par réponse, 10 000 éléments par collection. La durée totale n'est pas bornée par ce timeout. Les changements de statuts d'issues sans nouvelle analyse ne sont pas transactionnels. Durabilité du répertoire après crash et protection contre un acteur contrôlant déjà le processus/dépôt non garanties. Aucun seuil ni exclusion Sonar changé.

## Vérification

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider scripts/tests/test_sonar_diagnostics.py
```

Les tests utilisent un service réseau fictif et le vrai système de fichiers temporaire. 112 tests passent localement ; retrait de huit gardes détecté par 6/2/3/4/3/4/5/1 échecs. Les deux nouveaux contrats CLI échouaient avant suppression de l'option de destination. Les contrats de confinement précédents avaient 11 échecs/99 réussites avant correction. Patch appliqué, annulé et réappliqué avec contenu exact sur snapshot partiel, pas sur clone complet. Aucune couverture globale du produit ni exécution Sonar privée alléguée.

Les cinq annotations initiales ont été récupérées via le job temporaire 101587244353 (run34070652062, check101584689339). La correction précédente a supprimé quatre annotations ; le check101588758936 restait rouge C avec une annotation sur la publication. Celle-ci a été relue par le job101588975482/run34071280202 avant suppression de la destination CLI. Les deux lectures avaient uniquement Checks/Metadata read, aucun checkout et aucun credential Sonar. Le workflow temporaire est retiré du candidat et aucun workflow existant n'est modifié.

Autres correctifs : extraction de la projection des périodes, simplification des exceptions couvertes par OSError et expression de chiffres avec re.ASCII pour conserver le contrat. Les résultats Sonar/CI sur chaque nouveau SHA restent à vérifier, jamais anticipés. Aucun verdict de revue fabriqué ; aucun trio lancé.

## Sources

https://docs.github.com/en/rest/checks/runs#list-check-run-annotations
https://docs.sonarsource.com/sonarqube-cloud/appendices/web-api
https://docs.python.org/3/library/os.html
