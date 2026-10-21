# Mesure géométrique plane M3 — état et limites

**État :** noyau calculatoire local à l’état préparatoire, limité aux images synthétiques en mémoire. Il ne constitue pas une fonction utilisable sur les photos d’un client.

## Ce que calcule le noyau

`departments/m03-estimation/src/m3_estimation/mesure_plan.py` expose `mesurer_segment_plan(...)` et des contrats typés (`ProfilCalibrationCamera`, `CorrespondancesPlan`, `ResultatMesure`, `RefusMesure`). L’appelant fournit l’image BGR en mémoire, un profil caméra versionné (identifiant, résolution, intrinsèques, cinq coefficients de distorsion et empreinte SHA-256), les correspondances pixels↔mètres, les extrémités pixel du segment et une déclaration de coplanarité. Le profil est vérifié structurellement et par empreinte; cette vérification ne prouve pas la qualité physique de la calibration.

Le calcul corrige les points de distorsion, ajuste une homographie sur les seuls points d’ajustement, puis contrôle la reprojection sur un jeu séparé. Si le résidu fourni est dépassé, si la géométrie est dégénérée, si des bornes échouent ou si la coplanarité n’est pas attestée, l’appel retourne un `RefusMesure` avec code fermé. Sinon il projette les deux extrémités explicitement fournies et calcule leur distance dans le plan métrique. Il ne détecte ni ne segmente l’objet et ne choisit aucun point à la place de l’opérateur.

Le seul mode accepté est `SYNTHESE_FICTIVE`. `PHOTO_REELLE` est refusé avant import/décodage d’image. La sortie positive porte le statut `PROPOSITION_PREPARATOIRE_NON_QUALIFIEE`, la valeur `incertitude_terrain="NON_QUALIFIEE"`, des hypothèses explicites et une provenance comprenant les empreintes/version, résolution, correspondances, résidus et version d’OpenCV. Le résidu de reprojection décrit les points de contrôle du calcul; ce n’est ni une incertitude de mesure sur le terrain, ni une preuve que les dimensions des repères fournis sont exactes.

## Frontière produit et données

M3 a vocation à produire une estimation honnête de travaux de rénovation extérieure pour Synergy. Le noyau présent est uniquement un calcul préparatoire qui pourrait un jour soutenir une longueur sur un plan coplanaire, par exemple un segment droit de gouttière. Le choix métier de l’objet et de ses extrémités appartient encore à un opérateur. Aucune quantité issue de ce code ne peut alimenter un devis, prix ou engagement client.

La politique [Photos non contractuelles](../compliance/politiques/POLITIQUE-photos-non-contractuelles.md) porte encore le marqueur `STATUT_VALIDATION: proposition`. Aucun adaptateur d’upload, collecte client, API, caméra, stockage photo ou voie d’autorisation réelle n’est livré. Les exigences de cette politique restent préalables à tout accès à des pixels réels. Le noyau ne fait ni segmentation, ni reconstruction 3D/multi-vues, ni géocodage, ni estimation de dimension depuis une adresse ou une résolution seule. Il ne mesure pas un objet hors du plan de calibration.

## Dépendance et distribution

Les neuf cas synthétiques ont été exécutés par ROOT avec le wheel temporaire `opencv-python-headless==4.13.0.92`, ABI3 manylinux2014 x86_64, NumPy 2.5.3 observé, sans skip; preuve R1 : `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/mesure-plan-root-r1.xml`, reçu détaillé `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/evidence-r1/WHEEL-LICENSE-RECEIPT.json`. ROOT a confirmé R2 le 2026-10-02 : 9 tests, 0 échec/erreur/skip, exit 0 et 1112 sources stables (delta vide). Reçu ROOT : `/workspace/restructuration-opsys-2026-09-30/preuves/mesure-plan-synthetique-root-r2-2026-10-02-resultat.json`; JUnit : `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/mesure-plan-root-r2.xml`. Hors extra, 1 test passe et 8 cas géométriques sont explicitement sautés; ce parcours ne qualifie pas la géométrie. Voir aussi `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/FREEZE-r2.json` et `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/REPORT-R2.md`.

Le wheel étudié inclut les licences OpenCV Apache-2.0 et wrapper MIT ainsi qu’un fichier de licences tierces, notamment des avis pour des bibliothèques embarquées; toute distribution doit conserver ces notices et être revue selon ses composants. Il contient aussi des fichiers XML de cascades Haar, non chargés par ce calcul. L’extra optionnel proposé est décrit dans `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/EXTRA-VISION-PROPOSITION-r1.md`; il n’est pas déclaré livré et l’intégration au lock reste réservée à ROOT après sérialisation. Aucun modèle neuronal ou poids n’est utilisé.

## Références

- Implémentation: `departments/m03-estimation/src/m3_estimation/mesure_plan.py`.
- Tests: `departments/m03-estimation/tests/test_mesure_plan.py` (fixture signalée fictive).
- Décision/périmètre initial: `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/DECISION-PILOTE-r1.md` et `/workspace/poursuite-opsys-2026-10-02-r1/geospatial/PLAN-MESURE-r1.md`.
- Le statut préparatoire n’est pas une qualification terrain ni une autorisation de collecte réelle.
