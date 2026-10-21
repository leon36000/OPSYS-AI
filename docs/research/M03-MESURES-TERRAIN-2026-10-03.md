# M03 terrain / M04→coûts — scan décisionnel
Constat au 2026-10-03; lecture locale + notices GitHub/arXiv; pas de clone, install, photo ou benchmark OPSYS.

## État produit observé (pas l'ancien audit R7)
- M03 a déjà `mesure_plan.py`: homographie OpenCV sur correspondances manuelles, profil caméra signé, 4 points d'ajustement + 2 contrôles indépendants; seuil de résidu explicite ≤5 cm. La fonction n'accepte que `SYNTHESE_FICTIVE`; résultat `PROPOSITION_PREPARATOIRE_NON_QUALIFIEE`, résidu ≠ incertitude terrain. Source: `departments/m03-estimation/src/m3_estimation/mesure_plan.py:301-476`.
- Photo réelle non activable: politique photos encore `STATUT_VALIDATION: proposition`, collecte consentie/stockage/rétention à concevoir; la garde fail-closed existe. `docs/compliance/politiques/POLITIQUE-photos-non-contractuelles.md:1-70`, `politique_photos.py`.
- `qualite_photos.py`/`hierarchie_echelle.py` restent métadonnées déclarées; pas de segmentation pixel/poids/sidecar. Le vieux `docs/departements/M3-audit.md` est pré-implémentation de l'orchestrateur/calibration; l'utiliser seulement pour ce constat visuel confirmé par code présent.
- M04 a déjà matrice haversine entière bridée et adaptateur OSRM sidecar privé facultatif, route solver PyVRP 0.14; réel OSRM non qualifié et distance/région M3 non intégrées. `departments/m04-field-ops/README.md:70-125`, `src/m4_field_ops/distances_osrm.py`.
- Boucle temps existe: M03 trace estimée + cohortes train/holdout M4/WCT, candidates exact-scope et approbation N4; politique empirique explicitement `non_qualifiee_empiriquement`, sémantique min/unité ambiguë, cohorte M4 incomplète. `departments/m03-estimation/docs/calibration-temps.md`.
- Aval déjà branché: M4 produit durée WCT; M5 coût réel main-d'œuvre = minutes WCT × taux équipe fourni et attend variance M6; M6 compare besoin estimé M3 aux déclarations WCT. Aucun résultat de précision réelle M03↔M4→M5/M6 n'est documenté dans les sources lues. `m05_financecore/cout_reel.py:27-38,296-366`; `m06-material-control/README.md`.

## Candidats OSS primaires (commit de branche observé par GitHub API, 2026-10-03)
| Brique / source primaire | Code vs poids/données; usage/cout; limites décisionnelles |
|---|---|
| [OpenCV](https://github.com/opencv/opencv/tree/20e367198c7adde8f1efc0f525256b1e15798024), `5.x` commit `20e3671`; Apache-2.0. | Pas de poids ni dataset. CPU/local, aucun coût API. Correspond directement au `cv2` lazy de M03: QA flou/exposition et géométrie; aucune mesure n'est vraie sans calibration/correspondances et photos légitimes. R29 a vérifié une roue 4.13.0.92 en RAM, non adoptée ni terrain qualifiée. |
| [SAM 2](https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4), Apache-2.0; commit `2b90b9f` (2024-12-16). | Checkpoints `.pt` séparés du code; téléchargement externe, tailles exactes non mesurées ici; repo demande PyTorch ≥2.5.1/torchvision ≥0.20.1 et exemple CUDA. Self-host, coût GPU/opérations non chiffré; masque interactif, pas d'échelle physique. Données d'entraînement SA-V distinctes; pas requises pour inférence. |
| [Depth Pro](https://github.com/apple-aiml-research/ml-depth-pro/tree/9e65e4dbe9568d23c546fcec53302b10445e109e), commit `9e65e4d`; code ET poids sous Apple Sample Code License (non-OSI, conditions Apple), checkpoints téléchargés séparément. | Papier annonce 2.25 MP en 0.3 s sur « standard GPU »; aucun coût API, GPU local/coût infra non mesuré; CPU OPSYS non qualifié. Métrique absolue prometteuse mais pas preuve toiture/façade QC. Pas de dataset client permis/nécessaire à la recherche. |
| [COLMAP](https://github.com/colmap/colmap/tree/def61ed02c94e22756b379d2ec312bd836432563), commit `def61ed`; BSD-3-Clause; dépendances tierces à licencier séparément; pas de poids. | SfM/MVS multi-images local; CPU sparse possible, dense MVS GPU/temps/espace plus lourds; zéro coût API. Échelle absolue exige contrôle/GCP/GPS connu; surdimensionné pour mesure ponctuelle. |
| [OpenDroneMap](https://github.com/OpenDroneMap/ODM/tree/77439b1f45ceb4775b826f900916c64f03736331), commit `77439b1`; AGPL-3.0; pas de poids ML, données photos/GCP utilisateur séparées. | Ortho/nuage de points/modèle depuis images drone, sidecar local; SIFT GPU annoncé ~2× CPU sur portable type, non mesuré ici; coûts données/stockage/calcul élevés et à chiffrer. Copyleft serveur réseau et acquisition drone/GCP à arbitrer juridiquement. |

## Publications et métriques, sans transfert de précision
- Ravi et al., [SAM 2 (arXiv:2408.00714)](https://arxiv.org/abs/2408.00714), CVPR 2025: 58.9 mIoU 1-click vs 58.1 SAM sur 23 jeux d'images, mesure de segmentation; A100 FPS. Ce n'est pas une erreur en cm/m ni une garantie d'objets résidentiels. AlphaXiv à tester n'a pas été nécessaire pour consulter arXiv HTML.
- Bochkovskii et al., [Depth Pro (arXiv:2410.02073)](https://arxiv.org/abs/2410.02073); alphaXiv consultable [2410.02073](https://alphaxiv.org/abs/2410.02073). Résultats zéro-shot sur Booster, ETH3D, Middlebury, NuScenes, Sintel, SUN-RGBD; δ1 = proportion de pixels à moins de 25% de profondeur vraie. Domaine/distance pixels ≠ surfaces de rénovation; preuve locale d'étalonnage indispensable.

## Décision / première tranche recommandée
- Ne brancher aucun modèle photo maintenant: consentement/politique/rétention et collecte manquent; aucune métrique terrain réelle n'existe. Pas d'appel vision cloud ni d'entraînement client.
- Tranche la plus utile et la moins spéculative: parcours pilote local guidé, après validation écrite de politique, qui sauvegarde uniquement une photo consentie bornée + 4 points d'échelle/plan ajustement + ≥2 contrôles tenus à part + annotations manuelles; OpenCV contrôle qualité, M03 retourne mesure « à confirmer » ou refus, journalise provenance, sans devis automatique. D'abord jeu de vérité terrain indépendant multi-matériaux/angles et erreur absolue/p90 avant seuil produit; seuil 5 cm actuel n'est qu'un garde géométrique.
- En parallèle conserver la boucle temps existante, enrichir seulement la complétude contrôlée des WCT/M03 acceptés et rapporter n, couverture, MAE/p80 holdout par service/quantité; activation N4 seulement si politique d'échantillonnage et sémantique minutes clarifiée. Aucun modèle externe ne fournit le barème de coûts.

## Revue détaillée de la boucle de calibration

# Revue RO M03/M04 calibration temps — 2026-10-03

- Périmètre: lecture seule dépôt; aucune QA/test lancé, aucun patch déposé dans le repo, aucune activation N4.
- Durée estimée: `estimation.py` reçoit quantité × minutes/unité. `trace_calibration_temps.py` garde service, quantité/unité, taux/version/hash, résultat et sémantique; ambiguïté personne-minutes vs temps écoulé reste `non_qualifiee` tant que le barème ne déclare pas explicitement la valeur qualifiée.
- Durée réelle WCT: `outbox.py::calculer_duree_reelle` = première arrivée → dernier départ, moins pauses; trajet séparé. Projection M4 recalcule depuis pointages, contrôle chaîne M4, WCT/bus et statut `completed_verified`.
- L’invariant qualifié est donc temps sur site net des pauses, sans trajet ni heures-personnes; sémantique déclaré `duree_ecoulee_intervention`, minute. Pas un coût ni une durée personne.
- Admission M3 refuse lignes aux identifiants, durées, dates, quantités/taux, trace, hashes, chaîne/jointure/sémantique/unités incomplets ou invalides. M4 corpus reste explicitement `non_prouvee`.
- Regroupement strict par service, unité, version/hash barème, quantité exacte, taux et calibration version; cela prévient interpolation entre quantités, au prix de petits groupes/refus.
- Comptages/complétude et seuils existent déjà: 20 chantiers train + 10 holdout, séparation par chantier; promoteur journalisé qualifie numérateur/dénominateur couverture, MAE, p80 absolu et bootstrap; candidat reste inactif.
- Point améliorable confirmé: `_stats` expose `erreur_minutes_p80` signée, alors le lecteur peut prendre ce champ pour l’amplitude d’erreur. L’évaluateur de promotion calcule séparément le P80 absolu. Patch scratch additif: `erreur_absolue_minutes_p80`, préserver le champ signé existant.
- Fixture de test discriminante ajoutée en scratch: erreurs `[-100,1,2,3,4]`, p80 signé `3`, p80 absolu `4`; test n’a pas été exécuté.
- Risque données: WCT accepte service/type facultatif, projection M4 réduit l’objet sans l’exposer, donc pas de contrôle explicite WCT-service contre trace M3 dans raccord. M3 estimation dérive toutefois son `type_service` du service/type de son lead accepté, M4 tire également son champ de ce lead; risque résiduel à couvrir par test de raccord (mismatch si champ WCT connu, absence legacy explicite), pas preuve d’un mismatch actuel.
- Multiples pointages: durée span première arrivée/dernier départ moins pauses; interruptions non déclarées peuvent gonfler la durée. Le protocole conserve le fait vérifié, n’invente pas une correction; future admission pourrait refuser les séquences incohérentes seulement si règle métier établit les transitions attendues.
- Recommandation minimale: conserver la sélection stricte et l’inactivité. Ajouter test raccord WCT service connu/divergent vs trace, et absence WCT legacy; garder les inconnus exclus/compte couverture. Ne pas modifier sémantique, taux, photo, prix, coût ni seuils sans observations propriétaires.
- Sources: `departments/m03-estimation/docs/calibration-temps.md`; `src/m3_estimation/{estimation.py,trace_calibration_temps.py,calibration_cohortes.py,calibration_raccord.py,calibration_versions.py}`; `departments/m04-field-ops/src/m4_field_ops/{outbox.py,calibration_projection.py,etats.py}`; `departments/m04-field-ops/docs/heures-regulieres-validees.md`.
- Préimage exactes scratch: `calibration_cohortes.py` SHA256 `086825bccb93a7e9b82e8c290b3445de5f17a167bb0dcf53370c6867cb090412`; test SHA256 `fa7290b283d6602eb7b49c6f1dba776f6293fbaa25c0a91ed98affd3cc73adc1`.
- Candidat scratch seulement: source SHA256 `d7d4dfaf52089e8305e30f43517f340b8d3d056829089217e9205e7b9642a138`; test SHA256 `229ce5b743c2b2224a6d45d33953d9d66f3f333f57eabd24fd25c36498653713`.

## Qualification ROOT postérieure à la revue scratch

Le champ additif `erreur_absolue_minutes_p80` est maintenant appliqué dans le dépôt.
Le test utilise des durées réelles positives et distingue les erreurs `[-100,1,2,3,4]` :
P80 signé `3`, P80 absolu `4`. Les 16 cas des cohortes et les 8 cas de promotion passent
dans la campagne de 102 cas; Ruff passe après correction de forme.
[Preuve ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CRON-OWNER-RPC-M03-P80-QA-ROOT-r1/execution-r1/VERIFICATION-ROOT.json).
Les rapports historiques hashés ne sont pas réécrits. Aucun taux, seuil, prix, coût ou
statut d’activation n’est modifié; aucune précision empirique terrain n’est déduite de ces tests.

## Recherche complémentaire GitLab

# Recherche GitLab OSS M03/M04/M10 — 2026-10-03

- Consultations publiques GitLab API v4 sans authentification ni clé; toutes réponses GET utiles HTTP 200, aucun 403. Aucune clone, install, modèle/dataset téléchargé, aucun dépôt modifié.
- Seam observé: M03 `qualite_photos.py` qualifie champs déclaratifs (dimensions, éclairage, angle, référence échelle), sans vision; M04 a `localisation.py`, `distances.py`, `distances_osrm.py` et solveur tournées déjà séparé; M10 dispose de sa conception RAG/ingestion dans `docs/memory/RAG-PREMIUM.md` et composants natifs. Pas de gap justifiant d'importer un framework complet.
- Candidat SAM GitLab `WangJewell/segment-anything` [repo](https://gitlab.com/WangJewell/segment-anything), API [projet](https://gitlab.com/api/v4/projects/47548934), [tags](https://gitlab.com/api/v4/projects/47548934/repository/tags?per_page=3), licence raw [LICENSE](https://gitlab.com/api/v4/projects/47548934/repository/files/LICENSE/raw?ref=main). API: 1 étoile, 0 forks, dernière activité 2023-07-10, aucun tag; LICENSE Apache-2.0. Copie inférence seulement; poids de modèle non inclus, provenance/licence modèle à vérifier séparément chez l’éditeur; aucune métrique de précision adaptée à photos toiture/gouttière. Pas retenir ce fork obsolète.
- Candidat documentaire `mayan-edms/mayan-edms` [repo](https://gitlab.com/mayan-edms/mayan-edms), API [projet](https://gitlab.com/api/v4/projects/396557), [tags](https://gitlab.com/api/v4/projects/396557/repository/tags?per_page=3), [LICENSE](https://gitlab.com/api/v4/projects/396557/repository/files/LICENSE/raw?ref=master). Activité 2026-09-21, 682 étoiles, 346 forks; licence GPL-2.0. DMS complet Django; pourrait stocker documents, mais ne complète pas le seam d’ingestion/connaissance M10 et introduirait service, DB, tâches et régime copyleft sans besoin validé. Aucun poids ML; coût d’hébergement/maintenance non mesuré. Pas retenir.
- Candidat géospatial `mitanshu.sukhwani/osmnx` [repo](https://gitlab.com/mitanshu.sukhwani/osmnx), API [projet](https://gitlab.com/api/v4/projects/69244479), tags [endpoint](https://gitlab.com/api/v4/projects/69244479/repository/tags?per_page=3), licence [LICENSE.txt](https://gitlab.com/mitanshu.sukhwani/osmnx/-/blob/main/LICENSE.txt). Description = téléchargement/analyse réseau OSM; copie inactive depuis 2025-04-24, 0 étoile/fork/tag; licence URL répond 404 pour le nom standard. OSMnx ajouterait graphe/réseau, alors M4 délègue déjà au sidecar OSRM local; aucun gain évident. Sources OSM/extrais restent une licence/dépendance de données distincte du code.
- Recherche GitLab `segment-anything`, `photogrammetry`, `opencv`, `label studio`, `mapillary`, `geospatial python`, `document ai` a surtout retourné miroirs ou projets peu actifs; aucun moteur calibré terrain / évalué toiture. Pas de candidat GitLab crédible à intégrer.
- Les pages publiques/API ne donnent aucun benchmark applicable, CPU/GPU ou coût API pertinent. Aucun chiffre de précision, de gain, de poids ou de coût revendiqué.
- Décision: ne pas ajouter de brique GitLab maintenant. Garder composants actuels; prochain progrès mesurable vient d’un jeu terrain consenti/étiqueté et protocole holdout (photos par type/dommage ou adresses/temps réels), avant tout modèle. Le dataset et droits photos/coordonnées sont indépendants de la licence du code.
- État code examiné: `departments/m03-estimation/src/m3_estimation/qualite_photos.py`; `departments/m04-field-ops/src/m4_field_ops/{distances.py,distances_osrm.py,localisation.py,cedule_tournees.py}`; `docs/memory/RAG-PREMIUM.md`; `pyproject.toml`.
