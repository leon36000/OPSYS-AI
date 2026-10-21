# Tableau de bord — jobs de consolidation M10

Date : 2026-09-30. Statut : raccord local implémenté et vérifié dans l’arbre partagé; aucun job n’est
déclenché par les routes HTTP et aucune installation de cron/scheduler n’est revendiquée.
Référence de conception : [consolidation planifiée](M10-CONSOLIDATION-PLANIFIEE-DESIGN.md).

## Plan concret

1. Ajouter une page `/memoire/consolidation` et un module de rendu isolé qui affiche les métadonnées
   stables des jobs, le fuseau/créneau, le backlog, le dernier statut et son rapport expurgé. Tous les
   textes issus du registre sont échappés; secret, capability, hash et chemin de credential restent
   absents du HTML.
2. Ajouter les routes sous `/api/memoire-developpement/jobs` : liste, détail, dernier rapport ou rapport
   sélectionné, création de grant, révocation. Les fonctions worker (`lister_jobs`, `lire_statut`,
   `lire_rapport`, `autoriser`, `revoquer`) restent propriétaires de leur validation durable et de
   l’acteur courant. Aucun endpoint ne lance `executer`.
3. Toute action humaine passe par le cookie live et une relecture du compte actif et du rôle
   `admin`/`nathan_owner` en DB; toute mutation exige CSRF. Les corps sont strictement bornés et
   n’acceptent ni identité/rôle, ni dépôt, capability/credential, commande ou option worker libre.
4. Le dépôt vient exclusivement de `_repository()` côté serveur. Le chemin de credential est dérivé de
   `OPSYS_HOME` et du `job_id` validé. Après authentification seulement, vérifier composants sans
   symlink, propriétaire et permissions avant toute création; ne jamais renvoyer chemin ni secret.
5. Écrire d’abord les tests de contrat/sécurité : refus avant raccord, parcours session → grant → liste,
   détail/rapport → révocation avec stockage SQLite isolé, CSRF/arguments inattendus, compte désactivé,
   rôle retiré, symlink, rapport XSS. Le worker peut être appelé directement dans le test pour produire
   un rapport; aucune route console ne l’exécute.
6. Raccorder la page à la navigation mémoire, monter le routeur dans `application.py`, puis consigner les
   résultats ciblés, liens et limites. Ne pas revendiquer l’installation d’un cron ni d’un scheduler.

Un grant actif n’est pas la preuve d’un ordonnanceur installé ni d’une planification Core vérifiée.
Après chaque nouveau grant ou renouvellement, l’opérateur doit préparer explicitement la déclaration par
le CLI humain authentifié :

```text
opsys-metier memoire-developpement configurer-cron --job-id <job_id>
```

Cette commande prépare une déclaration de cron native; elle ne prouve pas une installation ou une
exécution nocturne. Après révocation, un renouvellement utilise un credential dérivé de la version
suivante (`<job_id>-v2.json`, puis versions suivantes), garde l’ancien fichier intact et indique que la
déclaration Core doit être régénérée. Une autorisation active répétée est refusée en 409 sans écrire.

## Preuves et statut

- `PYTHONPATH=src /workspace/audit-opsys-2026-09-30/venv/bin/python -m pytest -p no:cacheprovider tests/test_console_memoire_jobs.py -q` : **11 passés**; couvre session/CSRF, grant réel, liste/statut,
  rapport durable, révocation, renouvellement avec secrets distincts, compte désactivé, rôle retiré,
  parcours admin, JSON/champs/query invalides, backend PostgreSQL refusé sans credential, symlink du parent,
  absence d’effet fichier sans session et échappement XSS.
- `PYTHONPATH=src /workspace/audit-opsys-2026-09-30/venv/bin/python -m pytest -p no:cacheprovider tests/test_console.py tests/test_console_memoire_jobs.py --junitxml=/tmp/opsys-console-jobs-final.xml -q` : **57 passés**, exit 0.
  Log et JUnit sont conservés hors dépôt sous `/tmp/opsys-console-jobs-final.log` et
  `/tmp/opsys-console-jobs-final.xml`.
- Le parcours de rapport appelle le worker directement dans le test, avec la base SQLite temporaire
  de `OPSYS_HOME`; aucune route API ou HTML n’appelle `executer`.
- Ruff sur le module UI, le raccord,
  l’application et les tests : réussi. `git diff --check` : réussi.
- Création de credential : chemin fixé côté serveur sous `OPSYS_HOME/secrets/memoire-jobs/<job_id>.json`,
  répertoires privés créés après authentification seulement, vérification sans suivi de symlinks et
  propriété/mode; le worker écrit le fichier en `0600`. Le renouvellement ajoute le suffixe de version
  et ne remplace pas l’ancien credential. Chemins/credentials/capabilities ne sont pas renvoyés dans HTML
  ou JSON. Les caps des entrées humaines sont lues depuis les plafonds publics du worker.
- Les requêtes GET de liste et statut refusent les query params; les rapports n’acceptent qu’un
  `report_id` unique et renvoient 404 lorsqu’un identifiant explicite est inconnu. Le HTML du rapport
  réutilise le rendu d’audit sourcé et échappé, et expose les références/empreintes, caps, omissions,
  ainsi que les états déclarés/observés/inconnus du modèle de soi sans rendre de charge brute.
- Le backend autre que SQLite fichier est explicitement refusé avec 409 avant l’écriture d’un credential.

La page consulte les métadonnées et rapports persistés; elle ne déclenche pas les créneaux, ne montre
pas le secret, et ne modifie pas le journal métier des affaires. Ces tests locaux ne prouvent ni le
déploiement d’un ordonnanceur ni une isolation OS contre un processus ayant accès aux mêmes fichiers.
