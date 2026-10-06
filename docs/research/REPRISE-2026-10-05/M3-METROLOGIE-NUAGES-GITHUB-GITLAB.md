# M3 — métrologie des nuages et incertitude

Recherche du 5 octobre 2026 UTC ; **candidates non adoptées**. Elle complète la [comparaison photogrammétrique](../REPRISE-2026-10-04/M3-PHOTOGRAMMETRIE-GITHUB-GITLAB.md), sans refaire COLMAP/OpenSfM/GigaMesh. Objectif : transformer une reconstruction en mesures de façade, longueurs de gouttière et surfaces de revêtement vérifiables avant chiffrage.

## Décision

Premier banc à préparer : **COLMAP pour reconstruire, Open3D comme worker géométrique séparé** pour filtrer, sélectionner un plan et mesurer avec une échelle contrôlée. Aucun paquet installé, poids téléchargé ou connecteur livré par cette recherche. PDAL reste une alternative lorsque les données LAS/LiDAR, reprojections et CRS deviennent nécessaires. Eigen est une dépendance numérique à qualifier dans le composant retenu, pas un second moteur à empiler. Metric3Dv2 reste une piste de recherche, sans adoption commerciale de poids dont les droits ne sont pas vérifiés.

## État OPSYS réellement lu

`hierarchie_echelle.py` déclare et applique une classification **des métadonnées**, sans ouverture de pixels. `m3_classifier_confiance` rend niveau/motifs ; la présence d’une référence déclarée qualifiante ne constitue pas une mesure photogrammétrique effectuée. `estimation.py` distingue le niveau statistique Monte Carlo de coût (`niveau_confiance`) de la hiérarchie photo (`niveau_confiance_hierarchie`). Ni l’un ni l’autre ne devient une erreur géométrique empirique ou une précision en millimètres. Les sources et leurs SHA sont conservés dans la capture ; aucun comportement runtime modifié.

## Comparaison de code et licences

Les pins GitHub ci-dessous désignent les **HEAD observés**, pas des releases stables adoptées. L’API publique de release a refusé trois demandes par limite de débit. L’annonce Git publique obtenue par HTTP fournit les SHA ; la capture Open3D est bornée à 250 001 octets et tronquée après l’annonce initiale de HEAD. Git direct, lancé sans configuration/identité héritée, échoue à se connecter ; ce diagnostic ne démontre pas une panne du dépôt. La consultation HTTP réussit sans credentials. Les demandes 404 restent conservées et ne servent pas de preuve d’interface ou de tests.

| Candidate | Pin et licence relue | Apport concret / limite | Choix |
|---|---|---|---|
| [Open3D](https://github.com/isl-org/Open3D/tree/b6c5e196384ad71e75b6e6f9c5da22d046221f1d) | `b6c5e196384ad71e75b6e6f9c5da22d046221f1d`, `LICENSE` MIT | `PointCloud.h` expose `Scale`, `RemoveStatisticalOutliers`, covariances et `SegmentPlane`. Le fichier `cpp/tests/geometry/PointCloud.cpp` contient des cas de Scale et covariance ; ils ont été lus, pas exécutés. CMake active Python et GUI par défaut, CUDA désactivé par défaut. Les dépendances transitives et la distribution CPU minimale restent à qualifier. | Premier candidat de traitement géométrique après reconstruction ; service borné, sans GUI. |
| [PDAL](https://github.com/PDAL/PDAL/tree/0fffb222dc9f60543a99ed93931a63d9cfe24456) | `0fffb222dc9f60543a99ed93931a63d9cfe24456`, `LICENSE.txt` BSD trois clauses | `filters/OutlierFilter.cpp` distingue inliers/outliers et marque Classification ; `NormalFilter.cpp` calcule normales avec Eigen. Le seuil statistique d’outlier n’est pas une précision de mesure. CMake exige GDAL ≥3.8 et PROJ ≥9.0 ; plugins/transitives non audités. Deux chemins de tests essayés donnent 404 : aucune couverture de filtre n’est qualifiée par ces captures. | Reporter jusqu’à un cas GIS/LiDAR réel ; ne pas ajouter cette pile au même premier banc. |
| [Eigen GitLab](https://gitlab.com/libeigen/eigen/-/tree/2774a036e1c3a891acacd4dce74983ab11882143) | `2774a036e1c3a891acacd4dce74983ab11882143`, master observé ; `COPYING.README` et `COPYING.MPL2` : MPL-2.0 principale | Algèbre linéaire utilisée notamment par PDAL. Le README de licence cite des composants compatibles et des dépendances facultatives sous d’autres licences, dont GPL. Les obligations MPL concernent les fichiers concernés ; ne pas extrapoler une licence unique à toutes les options. | Examiner comme transitive de la brique retenue ; aucun fork ou runtime supplémentaire proposé. |
| [Metric3D](https://github.com/YvanYin/Metric3D/tree/eb5b6fac0dc155e4e52f576e304fbf11655ff339) | `eb5b6fac0dc155e4e52f576e304fbf11655ff339`, code `LICENSE` BSD deux clauses | README : sans intrinsèques, neuf réglages de focale par défaut ; une focale inadéquate déforme le nuage ; vues aériennes et objets peu représentés restent difficiles. Le code permissif ne prouve pas les droits de chaque checkpoint, dataset ou backbone. Aucun poids téléchargé/évalué. | Recherche seulement ; une prédiction monoculaire ne remplace pas un contrôle terrain. |

**Poids de distribution, pas benchmark :** la réponse PyPI annonce Open3D `0.20.0`. La roue `cp311-manylinux_2_35_x86_64` fait **400 803 434 octets** ; l’arm64 correspondante **48 461 815 octets**, Python ≥3.10. Ce sont les tailles compressées de ces artefacts et architectures, pas RAM/CPU/poids installés mesurés. Ce pin PyPI n’est pas déclaré identique aux sources HEAD inspectées. Ne pas installer la roue x86 dans un environnement qui n’a pas l’espace ni la compatibilité glibc nécessaires.

## Lecture scientifique

[Metric3Dv2, arXiv 2404.15506](https://arxiv.org/abs/2404.15506), [version HTML v3](https://arxiv.org/html/2404.15506v3), Yin et al., traite explicitement l’ambiguïté métrique des caméras et propose une transformation en caméra canonique. La section III-A montre qu’un objet peut conserver la même taille projetée avec focale et distance changées ; III-B introduit la transformation canonique. La capture HTML est tronquée à 250 001 octets : les sections présentes ont été lues, aucune lecture intégrale revendiquée. L’article HTML indique CC-BY-4.0 ; cette licence documentaire ne s’étend pas aux modèles/poids.

Les résultats zero-shot de l’article soutiennent un **candidat expérimental**, pas un seuil d’erreur validé sur façades québécoises ou téléphone client. Une covariance locale de nuage, la confiance produite par un réseau et l’intervalle de coût Monte Carlo sont trois objets distincts ; aucun ne certifie seul la couverture d’une erreur de dimension.

## Premier banc et critères avant adaptation

1. Entrées contrôlées : images autorisées et SHA, vues, caméra/intrinsèques/distorsion, système de coordonnées, unité, référence physique mesurée et contrôle indépendant. Paramètres et modèle/version fixés ; absence d’échelle : résultat non métrique, aucune quantité chiffrable automatique.
2. Worker isolé : fichiers bornés, plafond de points et taille, CPU/RAM/durée, annulation et absence de réseau non requis. Mesurer avant de choisir roue complète ou build CPU minimal ; conserver notices et licences effectivement distribuées.
3. Géométrie : reconstruction existante → sélection/filtrage → plan/polyligne → échelle → longueur/surface et provenance. Le filtre conserve les indices/rejets ; ne pas enlever silencieusement une rive utile ni prendre une bounding box pour une surface vendable.
4. Golden set : contrôles terrain laissés hors de l’ajustement, façades réfléchissantes, occultation, végétation, erreur de focale, vues répétées, référence douteuse et projection/coordonnées incompatibles. Mesurer erreur absolue/relative, biais, couverture et taux de refus ; valeurs d’acceptation métier à fixer, aucune précision inventée.
5. Raccord M3 : un artefact de mesure candidat source les quantités et unités du calcul existant. Validation humaine avant remplacement d’une quantité approuvée ou prix client ; API/dashboard déclarent mesures disponibles, manquants et limites. M10 garde source, version, décision et résultat ; aucun apprentissage automatique à partir d’une mesure non qualifiée.

Cette proposition maintient l’ambition d’une précision exceptionnelle tout en exigeant des preuves de mesures, pas seulement une image ou une démonstration. L’installation, le banc réel, les licences transitives/poids, les photos terrain et l’adaptateur métier restent à faire.

## Captures conservées

[Capsule](preuves/M3-METROLOGIE-RECHERCHE-r1.tar.xz), SHA-256 38a8629423ed08fc83f43bdeadfb860b3eab00c8699b87555158184e99d46742.
[Inventaire](preuves/M3-METROLOGIE-RECHERCHE-r1.json) : captures réussies, refus, troncatures, pins, licences et sources OPSYS. Toutes les entrées relues par SHA. R324 vérifie 38 fichiers code/docs/captures et ne trouve aucun secret ; aucun test de brique n’a été exécuté. Rapport conservé avant ces liens.
