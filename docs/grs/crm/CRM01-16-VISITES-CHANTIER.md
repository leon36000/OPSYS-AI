# CRM-01/16 — tranche de protection, mission inachevée

Base publiée : `3ab7692f041892ec2af0cab6f241a715edac2d50`. Branche : `mission/claude-crm-visites-20261028`. Cette tranche ne fournit ni identité de visite, ni interruption/reprise, ni raccord console. Ne pas ouvrir la transition sur_site → reportee sur cette base.

## Audit et contrat à poursuivre

Le journal quotidien laisse `ancre_visite=None` ; le calcul WCT prenait la première arrivée et le dernier départ. Le brouillon `temps.py` appelle les calculs de déplacement et pause, `calibration_projection.py` et la complétion appellent la durée réelle ; `heures_regulieres.py` refuse les points multiples et multi-techniciens. Les notes et couleurs gardent leurs ancres existantes. Les références anciennes ambiguës ne doivent pas être attribuées par proximité ; la composition déclarée n'est pas une présence observée. Aucun calcul de paie ici.

Une future fondation doit créer une identité explicite et durable par visite et relier les faits nouveaux à leurs références, distinguer prévision, équipe déclarée, pointages et inconnu, valider chronologie et pauses par session, conserver l'unique WCT final et traiter les anciennes données sans backfill. Avant d'ouvrir la FSM, adapter tous les lecteurs ou les faire refuser, définir transaction SQLite/CAS, idempotence, autorité, pagination, relecture et raccord console. Les contrats M5 et schémas communs restent inchangés. Aucun nouveau fichier réservé de mission n'existait à la base pour le test créé.

## Preuve et limites

Scénario fictif lundi 09–12 avec pause 30 min, vendredi 09–13 (heure Montréal, pointages vendredi en UTC) : 150 + 240 = 390 minutes. Le test rouge `rouge-03.log` a montré 5970 minutes (exit 1), par injection directe de faits dans le registre, pas par le parcours d'écriture métier. Désormais les calculs durée et déplacement refusent plusieurs arrivées faute d'identité fiable. Un seul départ supplémentaire reste accepté pour préserver la revue GPS ; ce n'est pas une preuve de la procédure d'arbitrage entière.

Les premiers essais `rouge-01` et `rouge-02` ont échoué à l'import faute de dépendances, et `vert-03` faute de fixtures désactivées : erreurs de harnais, pas produit. `vert-01` a révélé un test qui dupliquait la même intervention ; `base-01` montre qu'il passait sur la base, puis sa fixture a été corrigée pour créer deux interventions distinctes. `vert-02` et `vert-04` sont verts ; populations recoupées, ne pas additionner.

Commande depuis la racine du clone, avec `QA` pointant vers les répertoires privés :

```sh
env HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 timeout 90s python3 ../preuves-qa/runner.py ../preuves-qa/venv/bin/python -m pytest -p no:cacheprovider -q departments/m04-field-ops/tests/test_visites_temps.py departments/m04-field-ops/tests/test_outbox.py departments/m04-field-ops/tests/test_pointage.py departments/m04-field-ops/tests/test_etats.py
```

Exit 0 (`vert-04`). Python 3.12, dépendances dans `pins-01.txt`. Le runner charge seccomp (socket/socketpair refusés), limite mémoire virtuelle 1536 Mio, CPU 60 s et processus 96 ; timeout 90 s. `unshare -n` refusé par l'hôte. Source non montée en lecture seule : limite du harnais, bytecode et cache pytest désactivés. Aucun service QA lancé. Aucun SQL, HTTP, navigateur, révocation, rollback tardif, pagination visites, XSS ou CSRF démontré pour cette mission. La liste complète des régressions du manifeste reste à exécuter avec les dépendances nécessaires.

## Reprise

Installer/reconstituer le harnais isolé et ses dépendances à partir des pins, confirmer les preuves, puis développer le modèle de visite et son registre durable, les calculs par session et les transitions gardées ; seulement ensuite raccorder et exercer SQL/HTTP/console. Le correctif de garde ne satisfait pas l'objectif métier. Pas de raccord commun préparé, aucune migration, aucun M5, aucune mise en production.

## Tranche suivante : calcul pur non raccordé

`visites_chantier.calculer_sessions` calcule des intervalles explicitement fournis en UTC, contrôle l'unicité des identités, l'ordre, les chevauchements, la précision à la minute et les pauses dans leur visite ; les déplacements restent distincts. L'oracle 390 minutes, le changement d'heure, les refus et l'absence de mutation sont exercés par `test_visites_chantier.py` (`vert-06.log`, exit 0 avec le même harnais et les deux fichiers `test_visites_chantier.py` et `test_visites_temps.py`). `rouge-04.log` est un import absent, non une démonstration métier ; la preuve métier rouge reste `rouge-03.log`. Ce calcul ne vérifie pas encore les sources, ne crée aucun fait, n'est raccordé à aucun writer ni WCT et ne prouve pas une reprise réelle. Les tests sont des entrées fictives, pas des données terrain.
