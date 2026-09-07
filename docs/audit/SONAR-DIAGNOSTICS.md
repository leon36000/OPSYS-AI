# Diagnostic Sonar — issue #182

Statut : candidat de diagnostic, non qualifié sur le compte Sonar privé.
Ce script ne corrige pas les anomalies du produit et ne constitue pas un gate de fusion.

## Utilisation

Depuis une copie isolée du candidat, fournir `SONAR_TOKEN` via le gestionnaire de secrets autorisé, sans l'afficher. Le jeton est un PAT Sonar doté de l'accès au projet ; ne pas réutiliser un credential GitHub, créer de jeton automatiquement, ou le transmettre dans une conversation.

```sh
python3 scripts/sonar_diagnostics.py \
  --revision fcb65bcf20980a0b36847dbd41808527ba616d52 \
  --output /chemin/prive/existant/sonar-main-diagnostic.json
```

La révision ci-dessus était celle de main à la préparation. Revalider le SHA actuel avant exécution. Le parent du fichier doit exister et la destination ne doit pas exister. Un retard de l'analyse Sonar sur Git produit un refus explicite, jamais la sélection silencieuse d'une ancienne analyse.

Python 3.12+ et bibliothèque standard seulement. Tests :

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q -p no:cacheprovider scripts/tests/test_sonar_diagnostics.py
```

## Contrat

GET HTTPS uniquement vers `sonarcloud.io`, projet `leon36000_OPSYS-AI`, branche `main`. La session connectée ET l'accès au projet sont vérifiés. `authentication/validate` seul n'est pas un oracle d'authentification : le service peut accepter l'anonyme.

Le rapport rassemble l'identité de l'analyse, les conditions du Quality Gate, douze métriques globales/nouveau code et leurs absences, les issues non résolues, les hotspots et les blocs dupliqués. Pagination complète avec refus des doublons ou changements de compte. L'identité d'analyse est relue en fin de collecte.

Les messages libres, auteurs, identités de compte et extraits source ne sont pas sélectionnés. Vérifier les métadonnées avant partage : ce n'est pas un scanner universel de secrets. L'export est accompagné de son SHA-256, sans prétendre à une signature Sonar.

| Code | Signification |
|---|---|
| 0 | Collecte achevée, gate reçu OK, conditions présentes et métriques demandées mesurées. Pas une qualification globale. |
| 1 | Rapport exporté, gate ou condition rouge. |
| 2 | Collecte/publication refusée : authentification, accès, révision, pagination, schéma, réseau ou fichier. |
| 3 | Rapport exporté, mais mesure/condition absente, ignorée ou non évaluée. |

`quality_verified` reste toujours false. `collection_status=COMPLETE` décrit les collections demandées, pas la santé du dépôt. Aucun seuil/exclusion/résultat Sonar n'est modifié.

## Protection et limites

Redirections refusées, proxies d'environnement désactivés, TLS standard, timeout réseau configuré à 15 secondes, 8 Mio maximum par réponse et 10 000 éléments maximum par collection. Ce timeout socket n'est pas une garantie de durée totale pour toute la collecte. Pas de retry caché.

Publication atomique par lien dur d'un temporaire du même système de fichiers, permissions restrictives et aucun écrasement, même d'un symlink. Un système de fichiers incompatible échoue explicitement ; la durabilité du répertoire après crash n'est pas garantie.

Les statuts des issues peuvent changer indépendamment d'une nouvelle analyse : la double lecture d'analyse n'est pas une transaction serveur. Compatibilité complète et collecte authentifiée privée restent non exécutées. Des réponses publiques Sonar ont été inspectées pour les formats de mesures/pagination/hotspots, sans les présenter comme données OPSYS-AI ni tester l'authentification privée.

## Preuves et portée

Le paquet local du 6 septembre 2026 contient la phase RED et les tests de mutations. Nouveau rejeu avant publication : 91 tests réussis, aucun ignoré ; cinq mutants détectés (4, 3, 4, 1 et 4 échecs). Empreintes source et tests identiques au paquet. La couverture antérieure de 99,02 % concerne uniquement l'exporteur ; elle n'est ni la couverture OPSYS-AI ni une note Sonar.

Aucune nouvelle dépendance, aucun workflow ni produit métier modifié. Ne pas fermer #182 avec ce seul outillage. Le manifeste conserve explicitement l'absence de collecte privée, de revue et de qualification complète.

## Sources primaires

- https://docs.sonarsource.com/sonarqube-cloud/appendices/web-api
- https://sonarcloud.io/api/webservices/list
- https://sonarcloud.io/api/metrics/search?ps=500

Les exemples publics et les réponses de tests ne remplacent jamais le résultat réel du compte autorisé.
