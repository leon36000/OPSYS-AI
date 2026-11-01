# Rapport du banc qualif-20261101T111355Z

Fin : 2026-11-01T11:15:44.270+00:00  ·  étapes PASSE : 13  ·  ÉCHEC : 5

| Étape | Verdict | Durée (s) | Constats en échec |
|---|---|---|---|
| E00-prevol | PASSE | 0.2 |  |
| E01-installation-depuis-le-depot-local | PASSE | 18.59 |  |
| E02-installateur-public | ECHEC | 0.17 | l'installateur public termine avec succès (code 0) |
| g448m-init | PASSE | 24.72 |  |
| g448m-verifier | PASSE | 3.24 |  |
| g448m-sondes | PASSE | 1.81 |  |
| g448m-parcours | PASSE | 9.62 |  |
| g448m-empreinte-avant | PASSE | 1.58 |  |
| g448m-sauvegarde | PASSE | 2.44 |  |
| g448m-arret | PASSE | 1.31 |  |
| g416m-init | PASSE | 24.74 |  |
| g416m-verifier | PASSE | 3.37 |  |
| g416m-sondes | PASSE | 1.82 |  |
| g416m-parcours | ECHEC | 5.97 | sortie JSON illisible |
| g416m-empreinte-avant | ECHEC | 1.03 | deux lectures successives identiques (instance au repos) |
| g416m-sauvegarde | ECHEC | 0.01 | sauvegarde chiffrée réussie (code 0) |
| g416m-arret | ECHEC | 0.04 | arrêt propre : code 0, sans OOM |
| E90-etat-final | PASSE | 1.11 |  |

Ce rapport ne qualifie PAS un VPS : voir docs/qualification/QUALIFICATION-CONTENEUR.md, rubrique « NON PROUVÉ ».
