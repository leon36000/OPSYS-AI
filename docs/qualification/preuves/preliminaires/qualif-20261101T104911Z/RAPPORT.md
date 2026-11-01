# Rapport du banc qualif-20261101T104911Z

Fin : 2026-11-01T10:51:46.605+00:00  ·  étapes PASSE : 13  ·  ÉCHEC : 4

| Étape | Verdict | Durée (s) | Constats en échec |
|---|---|---|---|
| E00-prevol | PASSE | 0.21 |  |
| E01-installation-depuis-le-depot-local | PASSE | 14.84 |  |
| E02-installateur-public | ECHEC | 0.35 | l'installateur public termine avec succès (code 0) |
| c4g-init | PASSE | 24.85 |  |
| c4g-verifier | PASSE | 3.18 |  |
| c4g-sondes | PASSE | 1.76 |  |
| c4g-parcours | PASSE | 10.15 |  |
| c4g-empreinte-avant | PASSE | 1.52 |  |
| c4g-sauvegarde | PASSE | 2.35 |  |
| c4g-durcissement | ECHEC | 5.56 | système de fichiers de l'image (code, config, hors tests/docs/bibliothèques) : aucun secret ni clé privée; variables d'environnement de l'image : aucune ne ressemble à un secret |
| c4g-destruction | PASSE | 1.85 |  |
| c4g-restauration | PASSE | 10.16 |  |
| c4g-comparaison | PASSE | 4.52 |  |
| c4g-arret-propre | PASSE | 1.6 |  |
| c4g-mise-a-jour | ECHEC | 19.22 | le logiciel PRÉCÉDENT relit la base rétrogradée (base etat, révision 0038) |
| c4g-injections | ECHEC | 48.45 | F2b restauration d'une archive authentique contenant une base corrompue : refusé avec REJ-SAUVEGARDE-BASE-CORROMPUE (code de sortie 26); F4 disque plein (destination de 96 Ko) : refusé avec REJ-SAUVEGARDE-DISQUE-PLEIN (code de sortie 19) |
| E90-etat-final | PASSE | 1.14 |  |

Ce rapport ne qualifie PAS un VPS : voir docs/qualification/QUALIFICATION-CONTENEUR.md, rubrique « NON PROUVÉ ».
