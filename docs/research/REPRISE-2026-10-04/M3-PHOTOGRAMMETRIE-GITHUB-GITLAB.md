# M3 — briques métriques multi-vues, recherche du 4 octobre

Décision : conserver le parcours M3 actuel et préparer un banc multi-vues séparé
avec **COLMAP comme premier candidat**; OpenSfM est une seconde piste pour des
relevés géoréférencés. Aucun paquet, modèle, poids, dépendance ou service n'est
adopté par cette recherche. Aucune précision terrain OPSYS n'est démontrée.

Cette recherche prolonge [R7](../R7-m3-m4.md), [R21](../R21-2026-10-02/README.md)
et la [recherche M3 du 3 octobre](../REPRISE-2026-10-03/M3-BRIQUES-GITHUB-GITLAB-2026-10-03.md).
Elle vérifie les sources primaires, licences réelles, commits, contraintes de mesure
et coût d'adaptation. La littérature est examinée au niveau métadonnées/résumé;
aucune expérience publiée n'a été reproduite.

## État du propriétaire métier

`departments/m03-estimation/src/m3_estimation/mesure_plan.py` garde le calcul de
segment sur un plan, profil de caméra versionné, correspondances métriques fournies,
points de contrôle séparés et provenance. `PHOTO_REELLE` est explicitement refusée.
Le seuil interne de résidu de 0,05 m est un critère de refus, pas une preuve de
précision sur chantier. Les données admises et le calcul déterministe du prix
restent sous leurs propriétaires; un LLM ne produit pas les dimensions.

Une reconstruction multi-vues demande des photos recouvrantes et un référentiel
métrique. Une scène reconstruite en coordonnées arbitraires ne fournit pas une
longueur en mètres. Géocodage, segmentation et qualité visuelle ne suffisent pas
à établir l'échelle ou une erreur de mesure.

## Candidats comparés

| Brique/source | Version et licence vérifiées | Utilité et contraintes | Décision |
|---|---|---|---|
| [COLMAP](https://github.com/colmap/colmap) | Release **4.2.1**, tag → `bd1fcf654d2dd8fefa1466999c190a246f83f4b9`, publiée le 29 septembre 2026. `COPYING.txt` exact : BSD à trois clauses pour COLMAP; dépendances séparément licenciées. | SfM multi-vues, intrinsèques partagés/calibrés, alignement métrique par références. La géoregistration des centres d'images exige au moins trois correspondances. Convention centre de pixel : +0,5 sur cx/cy venant d'OpenCV. Sparse CPU possible; performance/RAM non mesurées ici. Dense CUDA/GPU. | Premier candidat de banc séparé pour éviter de recréer SfM. Construire l'inventaire des licences de dépendances et mesurer CPU/RAM avant tout paquet VPS ou intégration. |
| [OpenSfM actuel](https://github.com/OpenSfM/OpenSfM) | **v1.1** → `8b6b77efddebf4429044d3206c7dc21c4e767e08`, release du 16 août 2026, dernier push observé 8 septembre. `LICENSE` exact : BSD à deux clauses. | Intrinsèques, GCP et checkpoints exclus de l'optimisation, CRS projeté et incertitudes. GCP observé dans au moins deux images reconstruites. Rapports avec erreurs 3D/CE90/LE90; dense OpenCL/GPU. Lock Linux : 256 URL de paquets, poids installé non mesuré. | Seconde piste si le besoin devient aérien/GIS; ne pas empiler ses dépendances avec COLMAP dès maintenant. Le dépôt historique Mapillary n'est pas le pin évalué. |
| [GigaMesh, GitLab](https://gitlab.com/tacume/GigaMesh) | `23d8cf49bf8a04517b27df08484e6e6fccadaeb4`, commit du 21 février 2024. `LICENSE.txt` et `COPYING` : GPL-3.0 ou ultérieure, avis tiers distincts. | C++17/Qt5/CMake, inspection et profils de maillages déjà métriques; pas une reconstruction de photos. L'activité de projet de 2026 n'est pas une preuve de maintenance du code. | Non retenu pour ce parcours. Sa licence limiterait ici un usage éventuel au service séparé non modifié; son périmètre et sa maintenance n'en justifient pas l'adoption. |

Les données, poids et licences d'autres dépendances ne sont pas couverts par la
licence du dépôt principal. Aucun chiffre de taille finale, de latence, de débit
ou d'économie n'est annoncé sans installation et mesure. Le candidat GitLab
`educelab/pgs-recon` était déjà recensé dans R21; il n'est pas présenté comme une
nouvelle découverte. GigaMesh est un projet GitLab distinct, pas un miroir compté
comme une seconde brique de reconstruction.

## Contrôle ROOT et correction de pin

La première collecte associait à tort la release COLMAP 4.2.1 au commit de
développement `def61ed02c94e22756b379d2ec312bd836432563` du 2 octobre. ROOT a
interrogé `git/ref/tags/4.2.1` et détecté l'écart. Les fichiers release ont été
recapturés au vrai SHA `bd1fcf…`; sa racine utilise `COPYING.txt`, pas `LICENSE`.
Les captures initiales restent historiques, explicitement développement; elles
ne qualifient pas la release. ROOT vérifie aussi le tag OpenSfM, les textes de
licence et les tailles/SHA-256 des **39 entrées de manifestes** (26 initiales,
13 de reprise, avec recaptures). Ce ne sont pas 39 briques ni expériences.

Le résumé [arXiv 2607.24409v1](https://arxiv.org/abs/2607.24409v1), repéré via
alphaXiv/recherche, décrit la précision de **localisation visuelle** dans un
environnement de rue pré-cartographié et fortement contrôlé. Ses résultats
centimétriques ne valident pas des longueurs de gouttières/revêtement ni les photos
de nos clients. L'API Atom et son résumé sont capturés; le papier complet n'est
pas traité comme une expérience reproduite ou un benchmark OPSYS.

## Prochaine qualification métier

Choisir un service et une méthode de collecte avant le banc : caméra/résolution/
recadrage, vues recouvrantes, référence métrique connue sur le plan ou GCP levés en
3D, CRS/unité et droits des sources. Séparer références d'ajustement et contrôles
indépendants. Comparer des sites tenus hors ajustement à des mesures terrain
vérifiées; publier biais, MAE/p95, couverture des intervalles, taux de refus et
coûts CPU/RAM. Fixer le seuil d'acceptation par usage avant cette mesure.

Un adaptateur ultérieur restituerait longueur/unité, référentiel, sources/calibration,
résidus/contrôles et refus explicites vers M3. Échantillons insuffisants, échelle
absente ou caméra inconnue doivent demander des mesures supplémentaires. Les
images/fichiers entrants sont non fiables : quotas, traitement isolé, sorties
bornées et aucune instruction documentaire exécutée. Aucun poids ou API externe
ne remplace ce contrôle. Le dashboard devra distinguer configuré, testé et qualifié.

## Sources et limites de ce livrable

[Captures immuables, briefs et correction r2](preuves/M3-PHOTOGRAMMETRIE-r1.tar.xz),
[inventaire/SHA-256](preuves/M3-PHOTOGRAMMETRIE-r1.json). Les sources primaires sont
épinglées dans les manifestes de la capsule : API releases/tags/commits, fichiers
de licence, FAQ, CMake, documents GCP/dense/qualité et lock. Pas de clone massif,
build, installation, test de précision, donnée client ou changement de code M3.
Cette recherche facilite la décision suivante; elle ne livre pas la photogrammétrie.
