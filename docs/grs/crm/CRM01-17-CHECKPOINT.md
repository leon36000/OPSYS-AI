# M4 visites certifiées — checkpoint initial

Base : `f8301cc0138a8734a5282f57e678b0d989ba05bd` (PR #853 draft), descendante de `3ab7692f041892ec2af0cab6f241a715edac2d50`. Branche : `mission/m4-visites-integration-20261028`. Clone distinct du coordinateur et de la mission précédente. Le bundle a été vérifié après acquisition de la base publiée. CRC et 23 empreintes du pack conformes.

Les quatre échecs signalés dans `VERIFICATION-PR853.md` sont reproduits sur la base exacte : `baseline-01.xml`, 4 tests, 4 échecs, aucune erreur ni omission. Le schéma public V1 de report a été élargi et deux déclarations de rôle admin ont désynchronisé les tables, le fragment et les compteurs ; les droits réels doivent être vérifiés avant toute correction.

Preuves : `CRM01-17-PREUVES/baseline-01.xml` SHA-256 `360279a6566d7f8400e968ae1af80000b16fa10fa2b34898188d33c71a1b4`, `baseline-01.log` SHA-256 `a25ebd8f500f7b40337881b8dcb8f846956f7d76158d68663e2b65efa2325862`, `pins-01.txt` SHA-256 `395f78384d5a8adeb3a12833a69b087102692a8a26c5bb186e5ecba5b424865b`. Python 3.12.3, environnement virtuel privé ; HOME, OPSYS_HOME, XDG et TMP en 0700. Source montée en lecture seule, namespace réseau/PID isolée et filtre socket ; scope systemd MemoryMax=2G, TasksMax=64, CPUQuota=200 %, affinité CPU 0-1, timeout 90 s. PostgreSQL privé non détecté à ce stade ; aucune ressource provisionnée.

Prochaines actions : figer et publier le contrat factuel V2 et sa fixture ; séparer le report V1 gelé du port privé versionné ; qualifier les rôles sans élargir les droits ; implémenter le producteur réel et ses preuves. M5 n'est pas encore intégré.

## Jalon report V1 et rôles

Le report V1 retrouve ses trois paramètres gelés et son horloge serveur ; le nouveau port `m4_interrompre_visite_console_v2` est privé, sans rôle appareil. Les gardes du port de replanification sont renforcées. Commits `ed3e360b8` (M4 et console spécifique), `21d38abd4` (raccord `metier.py` isolé), `09cf44a97` (table des rôles et documentation communes). Le catalogue contient 179 outils déclarés sur 311 ; le rôle admin en reçoit 178. Aucun droit appareil n'est ajouté pour le nouveau port.

`CRM01-17-PREUVES/ci-agent/contrat-roles-01.xml` : 158 tests verts, aucun saut ; `lint-01.log` : exit 0. `rouge-contrat-01.xml` conserve les échecs préalables, `ports-auth-01.xml` une erreur de fixture corrigée, et `ports-auth-02.xml` les onze cas verts de frontières. Harnais de l'agent : venv et homes privés distincts, source RO, réseau isolé, scope systemd borné (2 CPU, 2 Gio, 64 tâches), une session QA à la fois. Les limites et l'absence d'intégration M5 subsistent.
