# Lot proposé — mesure plane synthétique M3

**But du lot.** Conserver un noyau géométrique déterministe, borné et vérifiable sur données synthétiques, comme préparation à une éventuelle mesure plane. Ce lot n’active aucune prise de mesure réelle ni aucun effet financier.

## État de référence

La fonction existe dans `departments/m03-estimation/src/m3_estimation/mesure_plan.py`; les cas sont dans `departments/m03-estimation/tests/test_mesure_plan.py`. Elle reçoit une image synthétique en mémoire, un profil caméra empreinté à résolution donnée, des points d’ajustement et points de contrôle séparés en pixels et en mètres, les deux extrémités du segment choisies explicitement, et une attestation de coplanarité. L’algorithme enlève la distorsion déclarée, ajuste l’homographie sur le jeu d’ajustement, vérifie le jeu tenu à l’écart contre un seuil borné, puis calcule la distance dans le plan. Les cas couvrent la perspective synthétique et plusieurs refus de calibration, géométrie, résidu, résolution, types et bornes.

Le profil est contrôlé selon sa structure et son empreinte; l’empreinte ne transforme pas une calibration fournie en calibration physiquement qualifiée. La coplanarité est une entrée déclarée, pas une détection. L’algorithme ne trouve pas la gouttière, ne segmente pas l’image, ne choisit pas ses extrémités et ne reconstruit pas de scène 3D. Le résultat indique `PROPOSITION_PREPARATOIRE_NON_QUALIFIEE` et `NON_QUALIFIEE` pour l’incertitude terrain.

## Parcours autorisé dans ce lot

Le seul chemin positif est la fixture synthétique créée en mémoire par le test, avec dimensions métriques connues de la scène artificielle. Le type `PHOTO_REELLE` est refusé. Pas d’image fournie par un utilisateur ou client, pas de stockage, caméra, endpoint ni appel externe. La politique photo M3 demeure à l’état `proposition`; sa validation humaine et un futur adaptateur sécurisé sont des préalables séparés, hors de ce lot.

Le résultat ne devient ni quantité de devis, ni prix, ni promesse au client. Même après une éventuelle autorisation distincte de mesure réelle, les points de calibration, la coplanarité, le choix des extrémités et la vérification contre des mesures terrain indépendantes resteront nécessaires. Un résidu numérique petit sur des données synthétiques ne fournit pas une précision terrain.

## Dépendance, version et licence

Qualification R1 ROOT : neuf cas sur neuf avec vraie roue OpenCV en RAM, aucun skip (preuve `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/mesure-plan-root-r1.xml`). ROOT r2 a maintenant qualifié les neuf cas avec wheel (9 pass, 0 skip, exit 0; 1112 sources stables, delta vide). Reçu : `/workspace/restructuration-opsys-2026-09-30/preuves/mesure-plan-synthetique-root-r2-2026-10-02-resultat.json`; JUnit : `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/mesure-plan-root-r2.xml`. Le parcours sans extra garde 8 skips explicites et ne constitue pas une qualification du calcul.

La version observée est `opencv-python-headless==4.13.0.92`, wheel ABI3 manylinux2014 x86_64 SHA-256 `0525a3d2c0b46c611e2130b5fdebc94cf404845d8fa64d2f3a3b679572a5bd22`, NumPy runtime 2.5.3. Le wheel pèse 56 016 764 octets et son contenu installé temporairement 155 757 527 octets. Les licences vérifiées sont Apache-2.0 pour le code OpenCV, MIT pour le wrapper et les notices tierces du wheel, incluant les composants binaires concernés; les fichiers d’avis doivent rester avec toute redistribution. La distribution comporte des XML de cascades Haar qui ne sont pas chargés par le noyau. Il n’y a pas de modèle neuronal ni de poids chargés. Voir le reçu de wheel et la `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/EXTRA-VISION-PROPOSITION-r1.md`.

L’extra reste proposé, non livré. Ne pas attribuer à ce lot la modification éventuelle du `pyproject.toml` ou du lock; ROOT la sérialisera après les changements de dépendances PDF.

## Critères vérifiables et limites de preuve

- Avec la wheel exacte disponible: les cas géométriques synthétiques s’exécutent réellement; sans extra, le test reste collectable et les seuls cas dépendant d’OpenCV/NumPy sont explicitement marqués skip. La branche refusant une photo réelle demeure exécutable sans extra.
- Une perspective synthétique issue d’une pose et d’une longueur artificielle connue vérifie que l’homographie projette les extrémités choisies dans le plan; les refus vérifient que les entrées incomplètes ou inadmissibles n’aboutissent pas à une longueur.
- Toute sortie positive reste étiquetée préparation non qualifiée; les tests ne démontrent ni précision terrain, ni capture sûre, ni intégration M3 complète.
- Pour toute phase future réelle, exiger données autorisées, évaluations contre mesures indépendantes, erreurs par cas et critère de refus défini avant revue. Ne pas publier de marge ou score de précision sans calibration terrain représentative.

Commande locale de reproduction avec l’extra déjà installé: `pytest departments/m03-estimation/tests/test_mesure_plan.py`. L’absence de dépendance doit produire les skips explicites ci-dessus, pas un faux passage des assertions géométriques.
