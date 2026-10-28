# M4 visites fiables — rapport au coordinateur

**Statut : PARTIAL, jonction financière et parcours complet non prouvés.** PR draft [#855](https://github.com/leon36000/OPSYS-AI/pull/855), branche `mission/m4-visites-integration-20261028`, empilée sur #853. Base exacte `f8301cc0138a8734a5282f57e678b0d989ba05bd`, parent publié `3ab7692f041892ec2af0cab6f241a715edac2d50`. Clone isolé du coordinateur et de la précédente mission. Voir le checkpoint pour l'historique non écrasé.

| Exigence | Preuve | Résultat / limite |
|---|---|---|
| Quatre échecs PR853 | `baseline-01.xml`, `compat-01.xml` | 4 rouges reproduits ; 15 verts après correction. Report V1 conserve ses paramètres, son verdict historique et son horloge serveur. |
| Interruption privée, rôles et autorité | `ci-agent/rouge-revue-02.xml`, `ci-agent/contrat-roles-02.xml`, `ci-agent/lint-02.log` | Rouge conservé ; 160 tests verts, lint exit 0. Nouvelle interruption versionnée privée, sans droit appareil ajouté. |
| Projection V2, ancrage et rejeu | `v2-provenance-red-01.xml`, `v2-test-06.xml` | 3 rouges de provenance, 13 verts après correction ; snapshots, WCT, CAS, autorité et composition séparée. Équipe pointée et présence individuelle inconnues sans preuve typée. |
| M4 → M5 | `jonction/RAPPORT-JONCTION.md`, `jonction-03.xml` | Producteur et consommateur réels : 390/30/60 minutes, coût incomplet refusé et CAS périmé refusé. Rouge sur ancienne justification d'équipe côté M5 ; autorité de bout en bout et coût positif non prouvés. |
| Régression M4 complète | `m4-complet-01.xml`, `osrm-loopback-02.xml` | Premier lot : 6 échecs et 58 erreurs de harnais réseau, 20 skips PyVRP. 106 cas OSRM verts en boucle locale isolée. Deuxième lot `m4-complet-02.xml` : 3 276 tests verts, aucun skip, exit 0 ; PyVRP 0.14.0 privé et boucle locale isolée. |
| Console HTTP et navigateur | `http/RAPPORT-QA.txt`, `http-extension/RAPPORT-CORRECTIF.txt` | 23 tests verts. HTTP fictif : prévision, ouverture, fermeture, interruption, replanification, proposition, approbation, date civile et reprise. Pointages et complétion par primitives ; après redémarrage 2 visites et un WCT de 120 minutes. Navigateur indisponible. |

L'oracle fictif utilise deux visites : 150 minutes lundi après pause de 30 minutes et 240 minutes vendredi, total 390 ; déplacements 60 minutes. Aucune minute entre visites. Les montants 250 + 480 = 730 CAD du pack supposent respectivement des taux fictifs de 100 et 120 CAD/heure-équipe et une imputation indépendante prouvée ; ils ne sont pas certifiés par la projection actuelle.

Contrat initial `07cacb3ab`, rectification de provenance `9ad107f9f`, producteur `30b6cab3e` et correctif `1d2669988`. Raccords communs séparés `21d38abd4` (routeur) et `09cf44a97` (rôles/test) ; ne pas appliquer sans revue. Aucun changement M5, migration, paie ou contrat bus WCT V1.

Environnement : données et homes fictifs privés avant imports, venv privé ; source montée en lecture seule, namespace PID/réseau, 2 CPU, 2 Gio, 64 tâches, timeout 10 minutes par lot. Le réseau local du harnais OSRM est isolé ; aucun service distant n'est utilisé par les tests. PostgreSQL privé absent à la qualification initiale : ce chemin reste UNKNOWN. Logs, échecs et pins sont dans `CRM01-17-PREUVES/`.

Le parcours historique V1 refusait la reprise faute de durées et compétences : rouge `ci-agent/legacy-reprise-red-02.xml`, correctif `055f9d133`, suite ciblée `ci-agent/legacy-reprise-suite-02.xml` (10 verts). Ces paramètres sont relus depuis la proposition liée à la visite, non inventés ; la durée est explicitement une prévision initiale, pas le reste à faire. La matrice initiale ne figure pas dans le plan normalisé : son empreinte d’entrée ne peut être recalculée de façon indépendante à partir de cette seule archive, limite à conserver lors de la revue du coordinateur. Le reformatage ultérieur ne change pas le comportement.
