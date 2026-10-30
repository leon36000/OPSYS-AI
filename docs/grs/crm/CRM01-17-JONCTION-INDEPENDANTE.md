# Jonction indépendante M4 → M5 et navigateur fictif

Composition QA isolée, sans fusion ni modification des branches propriétaires : base `f8301cc0138a8734a5282f57e678b0d989ba05bd`, M4 `24479141f0c4dfbfe194f9e330fb4041d310cc3c`, M5 `7f4e311af16d3702f69cfbe64e51ff8ca4746e3e`. L'arbre Git M4 a été archivé, puis uniquement les 27 fichiers différents entre la base et l'arbre M5 y ont été superposés ; aucune intersection avec les fichiers modifiés par M4. `CRM01-17-PREUVES/jonction-v3-independante/composition.txt` conserve ces références. Il s'agit d'une composition QA, pas d'une branche fusionnée ni d'une garantie sur une tête M5 ultérieure.

## Résultat et limites

`jonction-indep-03.xml` : **3 tests, 0 échec, 0 erreur, 0 skip, exit 0**. Dans le scénario positif, la fixture crée les visites avec interruption, deux équipes explicitement typées, une personne homonyme et leurs pointages M4 V3 ; les anomalies de pointage et la revue de complétion sont arbitrées par primitives fictives. Une photo PNG fictive est déposée par l'outil réel. Le vrai outil `m4_completer_intervention` écrit le WCT et publie `m4.travaux_termines` dans sa transaction : le harnais ne publie pas cet événement. La seconde complétion est refusée. Le vrai répartiteur livre le WCT au consommateur M5 et un rejeu n'écrit aucun second reçu. Les tarifs fictifs sont enregistrés au port M5 sous contexte admin, puis la fonction privée de ventilation console M5 relit réellement le producteur M4 V3 et retourne 390 minutes et **730 CAD fictifs de main-d'œuvre**, soit 150 minutes × 100 CAD/h-équipe et 240 × 120 CAD/h-équipe. Pause : 30 minutes ; déplacements : 60 minutes, exclus par cette politique M5 de calcul pur.

Le test refuse aussi une session expirée, un rôle admin révoqué et une source de composition modifiée entre les lectures. Deux lectures identiques n'ajoutent pas de reçu. La session de test est un objet fictif contrôlé, pas une preuve de connexion HTTP M5 ; la revue de complétion est exécutée par primitive, pas via le flux N4 réel. La ventilation est une lecture préparatoire : ce résultat ne démontre ni une rentabilité complète après matériaux, ni une écriture financière, ni la diffusion fiable d'une trace V3 courante à M8/M10. Le scénario ne justifie aucune présence individuelle. Les preuves héritées et les 3 279 tests M4 ne doivent pas être additionnés à cette population recoupée.

`jonction-indep-01` conserve le premier résultat positif. `jonction-indep-02` est rouge car le test de concurrence écrivait dans le mauvais nom de registre (`composition_journaliere` au lieu de `compositions_journalieres`) ; le code du test correspondant est conservé. `jonction-indep-03` corrige uniquement le harnais et démontre le refus avec le vrai registre. Les scripts et logs antérieurs ne sont pas écrasés. SHA-256 du test final : `6cfae0834605b489c1c72d055a02a13d9356234b34f850d57a7a0279a75439cd` ; XML final : `86581a23189c2e2c589b768d00287f8b52c310a79f533265bea96c851b6d6cf6`.

## Relecture navigateur

La base fictive a été conservée par `jonction-browser-prep-01.xml`, puis réouverte par `serveur-browser-01.py`, sur `127.0.0.1:40183`. Dans le navigateur intégré, la page des visites affichait le chantier « Terminé — vérifié », les deux visites fermées, 150 puis 240 minutes, la pause et les déplacements, le motif météo, les équipes prévues et les compositions inconnues. Depuis la première visite, le lien du journal du 3 juin a affiché les pointages et l'ancienne prévision ; son lien vers les temps individuels pour `eq-a` a renvoyé **REJ-TECHNICIEN-AMBIGU** et aucun total, car une personne fictive porte aussi cet identifiant. La grille de semaine a montré le créneau déplacé du vendredi et les liens journaliers. La déconnexion et la reconnexion du compte fictif ont été exercées. Observation par arbre d'accessibilité et capture visuelle dans le navigateur ; aucune capture n'est archivée ici. Les manipulations de pointage, interruption, reprise, preuve et complétion avaient été réalisées par les ports et primitives du test avant l'ouverture du navigateur : ceci n'est pas un parcours de saisie entièrement navigateur, ni une page de coûts M5.

L'onglet QA a été fermé. Le serveur du PID `2185506` a reçu SIGTERM et son superviseur a rendu 143 ; le PID et l'écoute du port 40183 ont été vérifiés absents. Aucune ressource réelle, aucun envoi ni service de production.

## Commande et isolation

Les archives proviennent de `git archive` sur les deux SHA ci-dessus, avec contrôle explicite d'absence de chevauchement avant superposition. Le test final figure dans les preuves sous `jonction-indep-03-test.py` ; le placer dans `departments/m04-field-ops/tests/test_qa_jonction_v3_indep.py` de la composition QA. Le venv et le filtre réseau sont ceux épinglés dans les preuves M4 précédentes.

```sh
QA="$PWD/../preuves-m4-v2/jonction-v3-independante-01"
VENV="$PWD/../preuves-m4-v2/venv"
RUNNER="$PWD/../preuves-m4-v2/runner-tests.py"
env HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 timeout 120s systemd-run --user --scope --quiet -p MemoryMax=2G -p TasksMax=64 -p CPUQuota=100% taskset -c 0 bwrap --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc --bind "$QA" "$QA" --chdir "$QA/repo" -- python3 "$RUNNER" "$VENV/bin/python" -m pytest -p no:cacheprovider -q -s departments/m04-field-ops/tests/test_qa_jonction_v3_indep.py --junitxml="$QA/jonction-indep-03.xml"
```

Pour la relecture navigateur, l'exécution préparatoire reprend ce test avec `-o tmp_path_retention_policy=all` et `--basetemp` privé. Le serveur utilise la base ainsi obtenue, une source montée en lecture seule, des homes privés, un scope 1 CPU/1 Gio/32 tâches et un timeout de 180 s. Son filtre seccomp interdit les connexions sortantes et limite l'écoute à l'IPv4 locale ; il n'accède qu'à la base et aux identités de test.
