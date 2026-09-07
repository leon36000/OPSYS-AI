# Diagnostic Sonar — issue #182

Statut : candidat de diagnostic, non qualifié sur le compte Sonar privé. Ce script ne corrige pas à lui seul les anomalies du produit et ne constitue pas un gate de fusion.

## Utilisation

Depuis une copie isolée du candidat, fournir `SONAR_TOKEN` via le gestionnaire de secrets autorisé, sans l'afficher. Ne pas réutiliser un credential GitHub, créer un jeton automatiquement ou transmettre un credential dans une conversation.

Préparer un vrai répertoire `.opsys/diagnostics` à la racine de cette copie, avec des permissions privées. Ni `.opsys` ni `diagnostics` ne doivent être des liens symboliques. Le script ne crée pas ces répertoires et refuse un environnement ne permettant pas les opérations sécurisées par descripteur.

```sh
python3 scripts/sonar_diagnostics.py \
  --revision fcb65bcf20980a0b36847dbd41808527ba616d52 \
  --output sonar-main-diagnostic.json
```

La révision ci-dessus était celle de main à la préparation : revalider le SHA actuel avant exécution. L'output est un nom de fichier JSON ASCII, sans sous-répertoire, ancré à `.opsys/diagnostics` du dépôt contenant le script, indépendamment du répertoire courant. Un chemin absolu est accepté seulement s'il désigne directement ce même répertoire. Les traversées, préfixes voisins et autres destinations sont refusés avant toute requête réseau. Le fichier ne doit pas exister ; aucun écrasement, même d'un lien symbolique.

L'ancien mode autorisant une destination arbitraire a été supprimé pour traiter l'annotation sécurité Sonar. Ne pas versionner les exports ; les examiner avant tout partage. L'outil ne modifie pas `.gitignore` et ne prétend pas que les fichiers produits sont automatiquement ignorés.

Python 3.12+ et bibliothèque standard ; publication sécurisée sur les plateformes POSIX offrant `O_NOFOLLOW`, `O_DIRECTORY` et `dir_fd`, sinon refus explicite. Tests :

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider scripts/tests/test_sonar_diagnostics.py
```

## Contrat de collecte

GET HTTPS uniquement vers `sonarcloud.io`, projet `leon36000_OPSYS-AI`, branche `main`. Vérifier session connectée ET accès au projet : `authentication/validate` seul peut accepter l'anonyme.

Le rapport rassemble identité d'analyse, conditions du Quality Gate, douze métriques globales/nouveau code et leurs absences, issues non résolues, hotspots et blocs dupliqués. Pagination complète avec refus des doublons et des changements de compte ; identité d'analyse relue en fin de collecte. Les compteurs de duplication n'acceptent que les chiffres ASCII, y compris après simplification de l'expression régulière.

Messages libres, auteurs, identités de compte et extraits source ne sont pas sélectionnés. Vérifier les métadonnées avant partage : ce n'est pas un scanner universel de secrets. Le SHA-256 accompagne l'export sans prétendre à une signature Sonar.

| Code | Signification |
|---|---|
| 0 | Collecte achevée, gate reçu OK, conditions présentes et métriques demandées mesurées. Pas une qualification globale. |
| 1 | Rapport exporté, gate ou condition rouge. |
| 2 | Collecte/publication refusée : chemin, plateforme, authentification, accès, révision, pagination, schéma, réseau ou fichier. |
| 3 | Rapport exporté, mais mesure/condition absente, ignorée ou non évaluée. |

`quality_verified` reste toujours false. `collection_status=COMPLETE` décrit les collections demandées, pas la santé du dépôt. Aucun seuil, exclusion ou résultat Sonar n'est modifié.

## Protection et limites

Redirections refusées, proxies d'environnement désactivés, TLS standard, timeout socket de 15 secondes, 8 Mio maximum par réponse et 10 000 éléments maximum par collection. Ce timeout ne borne pas la durée totale. Pas de retry caché.

Le chemin CLI est validé lexicalement ; chaque composant du répertoire fixe est ouvert sans suivre de symlink. Création du temporaire, publication par lien dur et nettoyage utilisent le même descripteur de répertoire. Un remplacement du chemin par un symlink pendant l'écriture ne redirige pas ces opérations vers sa cible. Fichier créé en mode 0600, sans écrasement. La durabilité du répertoire après crash et la protection contre un acteur ayant déjà le contrôle complet du dépôt ou du processus ne sont pas garanties.

Les statuts des issues peuvent changer sans nouvelle analyse : la double lecture n'est pas une transaction serveur. La collecte authentifiée privée reste non exécutée. Les réponses publiques et les fixtures ne sont jamais présentées comme données OPSYS-AI.

## Preuves et diagnostic des annotations

Les cinq annotations du check 101584689339 sur `ccf530b` ont été lues via un job temporaire GitHub Actions, run 34070652062, job 101587244353 : permissions Checks/Metadata en lecture, aucun checkout, aucun credential Sonar. Le workflow temporaire est retiré de ce candidat ; aucun workflow existant n'est modifié.

Correction du confinement : RED 11 échecs/99 réussites avant modification ; GREEN 110 réussites. Huit mutants détectés : garde chemin retirée 7 échecs, symlinks suivis 2, chiffres Unicode admis 3, authentification retirée 4, révision retirée 3, première page seule 4, rouge transformé en succès 4, protection du jeton retirée 1. Les tests historiques restent présents ; ceux de publication sont adaptés à la racine désormais imposée. Patch appliqué/annulé/réappliqué byte-exact dans une copie partielle, pas un clone complet.

Autres corrections ciblées : extraction de la projection des périodes pour réduire la complexité ; suppression des exceptions redondantes déjà couvertes par OSError ; expression de chiffres avec re.ASCII pour ne pas élargir le contrat. Recontrôler Sonar et la CI sur le nouveau SHA, sans anticiper leur résultat. La couverture de 99,02 % de l'ancien exporteur est historique et n'est pas revendiquée pour cette version.

Aucune nouvelle dépendance ni modification métier. Ne pas fermer #182 avec cet outillage. Aucun verdict scellé inventé ; l'absence de revue reste explicite dans le manifeste.

## Sources primaires

- https://docs.sonarsource.com/sonarqube-cloud/appendices/web-api
- https://docs.github.com/en/rest/checks/runs#list-check-run-annotations
- https://docs.python.org/3/library/os.html
- https://docs.python.org/3/library/re.html
