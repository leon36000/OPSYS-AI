# M4 visites certifiées — checkpoint initial

Base : `f8301cc0138a8734a5282f57e678b0d989ba05bd` (PR #853 draft), descendante de `3ab7692f041892ec2af0cab6f241a715edac2d50`. Branche : `mission/m4-visites-integration-20261028`. Clone distinct du coordinateur et de la mission précédente. Le bundle a été vérifié après acquisition de la base publiée. CRC et 23 empreintes du pack conformes.

Les quatre échecs signalés dans `VERIFICATION-PR853.md` sont reproduits sur la base exacte : `baseline-01.xml`, 4 tests, 4 échecs, aucune erreur ni omission. Le schéma public V1 de report a été élargi et deux déclarations de rôle admin ont désynchronisé les tables, le fragment et les compteurs ; les droits réels doivent être vérifiés avant toute correction.

Preuves : `CRM01-17-PREUVES/baseline-01.xml` SHA-256 `360279a6566d7f8400e968ae1af80000b16fa10fa2b34898188d33c71a1b4`, `baseline-01.log` SHA-256 `a25ebd8f500f7b40337881b8dcb8f846956f7d76158d68663e2b65efa2325862`, `pins-01.txt` SHA-256 `395f78384d5a8adeb3a12833a69b087102692a8a26c5bb186e5ecba5b424865b`. Python 3.12.3, environnement virtuel privé ; HOME, OPSYS_HOME, XDG et TMP en 0700. Source montée en lecture seule, namespace réseau/PID isolée et filtre socket ; scope systemd MemoryMax=2G, TasksMax=64, CPUQuota=200 %, affinité CPU 0-1, timeout 90 s. PostgreSQL privé non détecté à ce stade ; aucune ressource provisionnée.

Prochaines actions : figer et publier le contrat factuel V2 et sa fixture ; séparer le report V1 gelé du port privé versionné ; qualifier les rôles sans élargir les droits ; implémenter le producteur réel et ses preuves. M5 n'est pas encore intégré.

## Jalon report V1 et rôles

Le report V1 retrouve ses trois paramètres gelés et son horloge serveur ; le nouveau port `m4_interrompre_visite_console_v2` est privé, sans rôle appareil. Les gardes du port de replanification sont renforcées. Commits `ed3e360b8` (M4 et console spécifique), `21d38abd4` (raccord `metier.py` isolé), `09cf44a97` (table des rôles et documentation communes). Le catalogue contient 179 outils déclarés sur 311 ; le rôle admin en reçoit 178. Aucun droit appareil n'est ajouté pour le nouveau port.

`CRM01-17-PREUVES/ci-agent/contrat-roles-01.xml` : 158 tests verts, aucun saut ; `lint-01.log` : exit 0. `rouge-contrat-01.xml` conserve les échecs préalables, `ports-auth-01.xml` une erreur de fixture corrigée, et `ports-auth-02.xml` les onze cas verts de frontières. Harnais de l'agent : venv et homes privés distincts, source RO, réseau isolé, scope systemd borné (2 CPU, 2 Gio, 64 tâches), une session QA à la fois. Les limites et l'absence d'intégration M5 subsistent.

## Jalon producteur V2 initial

Contrat et fixture : `07cacb3ab` ; producteur et tests : `30b6cab3e`. L'export privé `m4_field_ops.temps_certifies_v2.projeter` lit les trois snapshots SQLite sous la transaction canonique et l'autorité admin console existante ; il relie les faits certifiés à l'unique WCT, garde compositions et présence inconnue séparées, vérifie les sources en sortie et produit l'empreinte contractuelle. WCT V1 et bus inchangés. La signature de travail est `projeter(cnx, intervention_id, wct_id, *, source_attendue=None)` ; retour `{source, projection}`.

`v2-test-05.xml` : 10 tests verts, aucun saut ; `v2-lint-03.log` : exit 0. Le scénario SQLite avec deux équipes fournit 150+240=390 minutes, pause 30 et déplacement 60 ; rôles, reprise, refus de source périmée, empreinte, WCT falsifié, quota et revue sont exercés. `v2-red-01` garde une erreur de fixture, `v2-red-02` l'import absent avant implémentation, `v2-test-02` les deux refus d'identité mal enveloppés corrigés ensuite. `compat-01.xml` : 15 tests verts incluant les quatre échecs initiaux. Les commandes et logs sont dans `CRM01-17-PREUVES/`. La branche M5 existe au SHA `67767d93587e0d02a67b9897adee93b533366216` mais à ce point ne fournit qu'un calcul pur, sans consommation vérifiée du producteur ; jonction réelle encore PARTIAL.

## Revue de provenance et harnais complet

La relecture du report a démontré deux écarts supplémentaires : verdict V1 incorrect après commencement et acceptation d'une réception serveur absente ou liée au mauvais appareil. `ci-agent/rouge-revue-02.xml` conserve ces rouges ; le correctif `658e43736` préserve le verdict historique et exige l'horodatage serveur lié à l'admin pour les mutations privées. `ci-agent/contrat-roles-02.xml` : 160 tests verts ; `lint-02.log` : exit 0.

La relecture du producteur a établi que l'égalité entre identifiant pointé et équipe prévue ne prouve pas son type : une personne peut être homonyme de son équipe. Les trois rouges dans `v2-provenance-red-01.xml` incluent ce cas, un état WCT précédent falsifié et une revue sans justification ; `v2-test-06.xml` est vert (13 tests). Les commits `9ad107f9f` et `1d2669988` corrigent respectivement le contrat/fixture et le producteur : l'équipe pointée est inconnue en l'absence de provenance historique typée. Fixture corrigée SHA-256 `0b8dcf208c24654f4949051acb757527465e8716e2dd0d2a27b52e5fc7fb0f66`, empreinte V2 `ecff1a74611af8051673d3134fa83ed00eca4a116d14c9885d9786c97474df2e`. La première fixture est conservée dans le commit `07cacb3ab` et ne doit pas être utilisée comme preuve de type. Le total économique de 730 CAD reste un oracle hypothétique, pas un coût certifié.

`m4-complet-01.xml` : 3 273 cas, 6 échecs et 58 erreurs tous dans `test_distances_osrm.py` car le harnais interdisait les sockets nécessaires au serveur local fictif ; 20 SKIP PyVRP absent. Aucun échec produit n'est déduit de ces traces. Le namespace réseau séparé ne contient que loopback (`namespace-reseau-01.log`) ; `osrm-loopback-02.xml` : 106 tests verts avec ce seul accès local. `osrm-loopback-01.log` conserve une erreur de configuration seccomp corrigée. PyVRP 0.14.0, extra M4 déjà prévu, est désormais installé dans le seul venv QA ; la suite complète doit être rejouée sur la tête intégrée avec ce harnais et ses SKIP restants rapportés.

## Jalon de jonction M4 → M5

Le code M4 `d3426c71d6b9201382a531bb84441af6759579ea` a été archivé dans un dossier QA isolé, puis seul le département M5 de `a5b977af29c9b62f2e406c0e2369ebb27242f365` y a été superposé. `CRM01-17-PREUVES/jonction/RAPPORT-JONCTION.md` contient la commande, les empreintes et les limites ; il ne s'agit ni d'une fusion ni de la branche de livraison.

`jonction-03.xml` : 2 cas, 1 vert et 1 rouge attendu, exit 1. Le cas vert traverse les registres SQLite fictifs, le vrai producteur M4, le validateur et la ventilation M5 ; 390 travail, 30 pause, 60 déplacement, aucun total de coût faute d'équipe prouvée, source périmée refusée. Le rouge modifie et ré-empreinte en mémoire une projection pour présenter comme identifiée une équipe à partir de l'égalité route/prévision ; le validateur M5 l'accepte encore comme structure valide. Ce rouge n'établit pas une attaque via le port M4. L'adaptateur d'autorité et le calcul de 730 CAD avec des équipes effectivement prouvées ne sont pas exercés. Une synchronisation du contrat M5 et une provenance typée sont nécessaires avant certification d'un total. Aucune modification M5 n'est proposée ici.

## Jalon console HTTP

`http/http-02.xml` : 23 tests verts, aucun skip. `http/http-01` conserve le premier échec du harnais interdisant un socket local. Le serveur fictif en boucle locale a permis la connexion, une consultation, le refus CSRF 403, la prévision et l'ouverture (réponses 303), puis a été fermé. `http/RAPPORT-QA.txt` précise les commandes et `http/live-http-03.log` les observations. Les pointages, l'interruption, la reprise et la complétion ne sont pas couverts par cette session ; le navigateur IAB n'est pas disponible. Les preuves navigateur de #853 sont historiques et ne qualifient pas cette nouvelle tête.

## Régression intégrale M4 rejouée

`m4-complet-02.xml` : **3 276 tests, 0 échec, 0 erreur, 0 skip**, exit 0, durée pytest 261,848 s. L'exécution est sur le code de `d3426c71d6b9201382a531bb84441af6759579ea` avec `departments/m04-field-ops/tests`, dépendances privées épinglées dans `pins-02.txt` et PyVRP 0.14.0 (`install-pyvrp-01.log`). Source montée RO, HOME/OPSYS_HOME/XDG/TMP privés, namespace réseau/PID, boucle locale uniquement, scope 2 CPU/2 Gio/64 tâches, timeout 600 s ; commande reproductible en fin de cette section. La première exécution et ses erreurs de harnais sont conservées, sans additionner les populations.

```sh
QA="$PWD/../preuves-m4-v2"
env HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 timeout 600s systemd-run --user --scope --quiet -p MemoryMax=2G -p TasksMax=64 -p CPUQuota=200% taskset -c 0,1 bwrap --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc --bind "$QA" "$QA" --chdir "$PWD" -- python3 "$QA/runner-loopback.py" "$QA/venv/bin/python" -m pytest -p no:cacheprovider -q departments/m04-field-ops/tests --junitxml="$QA/m4-complet-02.xml"
```

## Reprise historique corrigée et relue sur HTTP

Le parcours réseau a révélé un 409 réel pour les anciens leads `type_travaux` : les tables de durée et de compétences requises n'étaient pas transmises. `http-extension/RAPPORT-DIAGNOSTIC.txt` conserve le diagnostic ; `ci-agent/legacy-reprise-red-02.xml` reproduit le défaut. Le correctif `055f9d133` relit les données du plan source lié à la visite interrompue, garde ses références dans l'audit et indique que sa durée initiale n'est pas la durée restante. `ci-agent/legacy-reprise-suite-02.xml` : 10 verts ; les traces Ruff initiales et corrigées sont conservées. La matrice initiale omise du plan normalisé empêche de recalculer séparément l'empreinte d'entrée de ce seul plan ; cette limite subsiste, sans prétendre une attestation supplémentaire.

`http-extension/RAPPORT-CORRECTIF.txt` : sur `055f9d133`, le parcours HTTP fictif atteint la proposition équipe différente, approbation N3, date civile, prévision, ouverture et fermeture de la seconde visite. Transitions en route et pointages injectés par primitives, horloge contrôlée. La complétion et photo sont aussi par primitives : un seul WCT de 120 minutes, double refusé, relecture HTTP après redémarrage affichant les deux visites et le statut terminé en attente de revue. Aucun navigateur disponible. Tous serveurs QA de cette tranche sont fermés.

Après formatage `fc044e412`, `ci-agent/legacy-regression-01.xml` : 139 tests, 0 échec, 0 erreur, 0 skip, exit 0 sur les fichiers `tests/test_console_reprise_visite.py`, `tests/test_console_visites_chantier.py`, `tests/test_console_report_visite_v2.py`, `tests/test_portees_appareil.py`. Même harnais privé à boucle locale et limites que la régression M4, timeout 180 s. `ci-agent/legacy-lint-01.log` conserve deux défauts de formatage ; `legacy-lint-02.log` : Ruff exit 0. La suite M4 complète de 3 276 tests a été exécutée avant ce correctif limité aux fichiers console et tests console ; la régression ciblée précédente porte sur le code final.

## Jalon provenance d'équipe V3 — 30 octobre

Contrat/fixture `8f6d9a572`, producteur et port privé `d83a19d4e242297400bdb65c62c331781bd5f2cd`. Rapport de détail : `CRM01-17-RAPPORT-V3.md`. La V3 est additive ; la V2 et le WCT V1 restent inchangés. Les pointages déjà ambigus restent inconnus. Les nouveaux pointages ont une preuve typée déclarée par un admin actif, enregistrée dans le même savepoint, avec CAS, audit et vérification des préfixes historiques des registres. Ce n'est ni une preuve de présence individuelle ni une signature cryptographique.

`v3-regression-01.xml` : 67 tests verts ; `v3-preuve-reelle-01.xml` : 3 tests verts incluant un vrai parcours SQLite fictif à 150 + 240 minutes et deux équipes. Audit altéré, source modifiée, rôle révoqué, rollback tardif, rejeu et homonymie sont couverts ; les traces rouges et les erreurs de harnais sont conservées. Le premier lot complet `v3-m4-complet-01.xml` a été lancé sur des fichiers en cours d'édition et échoué sur le garde du catalogue de types ; ce n'est pas une preuve de la tête finale. Le type V3 a été explicitement ratifié dans le test M4. `v3-m4-complet-02.xml` a ensuite passé 3 279 tests sans échec, erreur ni skip, exit 0, en 258,125 s sur `d83a19d4e` figé ; Ruff final exit 0.

La branche M5 lue à `cc2cd7e29b82a0607768b5c22732d11f6e89dd10` refuse encore `opsys.m4.temps_certifies.v3` (preuve `v3/m5-v3-compat-01.log`). Aucun changement M5 ni adaptation de transport n'a été effectué. La jonction et un coût complet restent non démontrés.

Le calcul pur M5 sur la projection M4 fictive et des taux fictifs donne 250 + 480 = 730 CAD (`v3/m5-v3-calcul-pur-01.log`, exit 0). Le validateur M5 refuse simultanément V3 : ce test d'arithmétique contourne la validation et ne démontre ni une jonction de confiance ni un coût certifié.

## Jonction indépendante et navigateur — reprise du 30 octobre

La composition isolée M4 `24479141f0c4dfbfe194f9e330fb4041d310cc3c` + M5 `7f4e311af16d3702f69cfbe64e51ff8ca4746e3e`, sans fichier commun divergent, a été vérifiée par `jonction-v3-independante/jonction-indep-03.xml` : 3 tests verts, aucun skip. Cette preuve actualise les constats antérieurs fondés sur l'ancien M5 : le vrai outil M4 publie son WCT, le vrai répartiteur et consommateur M5 le reçoivent, le port V3 est relu et la ventilation fictive fournit 150 + 240 minutes et 730 CAD de main-d'œuvre, avec taux sourcés fictifs. Rejeu, rôle révoqué et source changée pendant lecture sont refusés. La revue de complétion est effectuée par primitive et la session console simulée ; ni la cascade financière durable ni la fraîcheur M8/M10 ne sont démontrées.

Le navigateur intégré devenu disponible a permis une relecture après redémarrage : deux visites distinctes, motif météo, 150/240 minutes, journal, grille et refus du temps individuel ambigu observés. Il ne s'agit pas d'une saisie complète au navigateur ni d'un écran M5. L'onglet et le serveur QA ont été fermés. Les commandes, périmètres et échecs intermédiaires sont dans `CRM01-17-JONCTION-INDEPENDANTE.md`.

Le contrôle de concurrence SQLite `jonction-v3-independante/concurrence-v3-02.xml` passe 2 tests sans échec ni skip : deux transactions concurrentes sur la même source produisent une seule écriture, avec rejet de source périmée ou rejeu identique selon la clé de mutation. Cette preuve locale ne couvre pas PostgreSQL ni une charge distribuée.

Après publication M5 `65ee79c91d472d1a5d3dd4e51514f437538d3069`, nouvelle composition sans chevauchement : cinq tests indépendants et trois scénarios M5 passent, sans échec ni skip. Les routes M5 sont exercées par client HTTP de test ; l'analyse locale historique complète fictive atteint 1 050 CAD et −450 CAD, et une modification de tarif marque la trace antérieure comme périmée. La trace complète n'est pas publiée sur le bus et la fraîcheur aval M8/M10 reste non démontrée. Détail et commandes dans `CRM01-17-JONCTION-INDEPENDANTE.md`.

La base fictive de ce scénario a été rouverte dans un serveur QA privé : le navigateur M5 montre l'ancienne analyse comme périmée, puis enregistre une nouvelle analyse locale à jour en conservant l'historique et en indiquant l'absence de publication. Préparation, capture et limites dans `CRM01-17-PREUVES/jonction-m5-65ee/` et le rapport de jonction. Onglet et serveur fermés.
