# Actifs avatar et audio : licences et choix pratique

Recherche initiale du 2026-10-02, actualisée le 2026-10-03 UTC. Le candidat MPFB a ensuite été téléchargé intégralement et transformé localement; cette qualification structurelle est détaillée ci-dessous. Aucun poids Audio2Face ou service NVIDIA n’a été installé. Pour consulter le catalogue NVIDIA, ROOT a exécuté temporairement la CLI via `npx` avec cache sous `/dev/shm`; la CLI a cloné le dépôt du catalogue dans cet espace temporaire. Aucun skill NVIDIA n’a été installé durablement dans le projet ni adopté. La consultation du catalogue NVIDIA n’a exécuté aucun test ni modifié le code produit. Les constats initiaux ci-dessous proviennent des métadonnées et README publics; la qualification ultérieure distingue inspection structurelle et rendu.

## Résultat

Le modèle actuel `core/assets/avatar-models/robotexpressive-quaternius-cc0-v1.glb` est CC0, mais son inspection précédente trouve seulement trois morphs d’émotion (`Angry`, `Surprised`, `Sad`), sans morphs de visèmes ni mâchoire explicite. Il ne peut pas faire de lip-sync directement avec les visèmes Oculus de TalkingHead. Une animation idle ou pilotée par l’amplitude ne constitue pas une synchronisation labiale.

Le dépôt **TalkingHead** est MIT (code), mais les licences de ses exemples diffèrent : `mpfb.glb` est annoncé CC0; `brunette.glb` est CC BY-NC 4.0 (non commercial). L’arbre GitHub donne 36 815 920 octets pour MPFB (blob `cd2ebbe1fe8bcbf3d5b2dfbf1262a7f76814e68f`). Lecture Range bornée : header GLB et chunk JSON seulement, 132 596 octets; aucun chunk BIN. Le JSON annonce GLB v2, buffer embarqué, 76 nœuds, 8 maillages, 1 skin/67 joints, zéro animation, 7 images et 7 textures embarquées. Le mesh `base` comporte 66 morph targets, dont 14 nommés `viseme_*`; un nœud `Jaw` apparaît. Ces éléments sont des déclarations JSON; géométrie, texture rendue et correspondance visuelle non inspectées. Ils suggèrent une piste, sans qualifier l’avatar ou son intégration.

Le validateur courant exige un modèle épinglé par taille/SHA, plafonne GLB à 10 MiB et JSON à 2 MiB, refuse images/textures et plus de 512 bufferViews (`core/src/agents/assistant-avatar-model-file.ts:7-83`). MPFB n’est pas au catalogue (`core/src/shared/assistant-avatar-model-catalog.ts:3-12`); son JSON annonce 653 bufferViews, 7 images et 7 textures. Le fichier amont dépasse le plafond et le profil structurel. Un export transformé distinct peut réduire son contenu; la qualification ci-dessous ne relève aucun plafond. Ne pas augmenter le plafond seul ni ajouter cet actif directement. Le code TalkingHead MIT n’étend pas la licence de ses avatars.

| Option | Signal établi | Licence et limite pratique |
|---|---|---|
| **TalkingHead** (`met4citizen/TalkingHead`) | API documentée pour jouer `AudioBuffer`/PCM avec mots, horodatages, visèmes ou animation; mode streaming disponible. Le JSON de `mpfb.glb` annonce 14 cibles `viseme_*` et un nœud `Jaw`, sans preuve de compatibilité au rendu. | Code MIT. Attend un avatar muni de canaux de bouche adaptés; ne résout pas l’absence de visèmes du GLB actuel. Son exemple `brunette.glb` est CC BY-NC 4.0 et exclu d’un usage commercial. `mpfb.glb` est annoncé CC0, mais 36,8 MB et 7 textures ne cadrent pas avec le validateur courant de 10 MiB, qui refuse aussi textures et profils à plus de 512 bufferViews. |
| **Rhubarb Lip Sync** (`DanielSWolf/rhubarb-lip-sync`) | Outil local hors ligne pour produire des cues bouche A–H/X horodatés à partir d’un clip finalisé; pas un flux temps réel ni une animation GLB. | Projet MIT; GitHub classe le fichier de licence `NOASSERTION`, et les dépendances ont leurs propres avis. Le français canadien n’est pas qualifié; une adaptation des cues vers un rig avec canaux de bouche reste nécessaire. Candidat à une preuve offline seulement. |
| **NVIDIA Audio2Face-3D SDK / ACE** | SDK annoncé pour générer de l’animation faciale depuis l’audio; aucune correspondance de son output au GLB local ni intégration streaming OPSYS n’est établie. | Le code SDK est MIT; cela ne couvre pas automatiquement les poids. CUDA/TensorRT et une empreinte de plusieurs Go sont annoncés; modèles et services NVIDIA ont des conditions distinctes. Option premium, non provisionnée ni qualifiée. |

Les actifs alternatifs doivent être évalués sur leur propre licence, séparément du moteur qui les charge. Les captures du README TalkingHead documentent aussi les étapes MPFB pour créer un avatar avec visèmes Meta/Oculus et ARKit, mais elles ne prouvent ni la licence de chaque ressource MPFB, ni la taille finale, ni la compatibilité de `mpfb.glb` préconstruit. Rocketbox annonce une bibliothèque d’avatars MIT et des blendshapes, mais la capture du chemin `LICENSE` à la racine retourne 404; vérifier le paquet et l’avis attaché à chaque actif avant adoption.

Les recherches GitHub/GitLab n’ont pas fait ressortir d’autre candidat CC0 prêt à l’emploi : la recherche GitHub `avatar viseme CC0` ne retourne aucun dépôt (capture 55 octets); la recherche GitLab `avatar viseme` retourne `[]` (2 octets). Ce sont des recherches lexicales bornées, pas une preuve d’absence d’autres projets. Les recherches antérieures ont trouvé des miroirs/forks GitLab pour NVIDIA, sans upstream NVIDIA confirmé. Le catalogue NVIDIA interrogé par `npx skills add nvidia/skills --list` annonce 398 skills; son journal ne contient aucune entrée correspondant à `Audio2Face`, `avatar` ou `viseme`. Aucun skill ni dépôt n’a été installé par cette vérification du catalogue.

## Qualification structurelle du candidat MPFB — 3 octobre UTC

Le fichier complet de 36 815 920 octets est désormais conservé dans la capsule
`/workspace/poursuite-opsys-2026-10-02-r1/AVATAR-MPFB-CC0-STRUCTURE-ROOT-r1/source-candidat-scripts-avant.tar.gz`.
La source est épinglée au commit TalkingHead `b3e277b3b46f88e557bf28a2c5612a5b04e075c3`,
SHA-256 `63c645a2a863b9972e9a9c2ed576a1de4c390b8475508e1473e69c87a3ee299c`,
avec vérification du blob Git `cd2ebbe1fe8bcbf3d5b2dfbf1262a7f76814e68f`.
Le README de ce même commit attribue explicitement CC0 à cet actif, distinctement du code MIT.

Un export déterministe supprime images, textures, samplers et cibles d’expression non retenues,
puis remappe les accès aux octets sans simplifier la géométrie. Il garde les quatorze visèmes,
`jawOpen`, clignements et sourires, le squelette et les skin weights. Le résultat r2 fait
**6 582 764 octets**, SHA-256 `61467281010defa1ee1af4d905bf06cfa783b183556fa61edabc434d967c97a5` :
76 nœuds, 8 maillages, 67 joints, 53 116 sommets POSITION, 141 accessors, 217 bufferViews et
76 accessors sparse. Des couleurs de matériau remplacent les textures; cette perte d’apparence
reste à évaluer visuellement. Les seuils du validateur produit restent inchangés.

ROOT a vérifié les empreintes et le contenu de la capsule, les remappages et octets de chaque
bufferView, les accessors sparse, les attributs/indices de géométrie, les skins et le squelette.
La vérification structurelle indépendante passe; preuves dans `VERIFICATION-ROOT.json`,
`structure-resultat-root.json` et `VERIFICATION-STRUCTURE-ROOT.json` du répertoire ci-dessus.
Cela ne qualifie ni le rendu, ni le chargement par le validateur produit, ni l’apparence commerciale,
ni la synchronisation audio. L’actif n’est pas ajouté au catalogue produit à ce stade.

## Tranche suivante

Charger cet export dans le vrai GLTFLoader/Three.js sous Chromium, vérifier les visèmes et leurs
déformations, puis inspecter les captures du visage et du corps. La revue du lanceur a trouvé un
import `three.core.js` absent de sa liste blanche; la correction précède toute exécution.
Après qualification visuelle seulement, adapter le catalogue et qualifier le parcours produit.
Relier ensuite un clip TTS local à des cues temporels et mesurer la synchronisation sur fr-CA.
Audio2Face/ACE reste une option premium dont GPU, licences des poids et coût doivent être établis.

## Sources et empreintes conservées

- Captures primaires GitHub/GitLab et métadonnées HTTP : `/workspace/poursuite-opsys-2026-10-02-r1/avatar-actifs-licences-r1/CAPTURES.json`, SHA-256 `6b3e26099e44992fb5268491b65eaee0aa6ded027867499e1da0c3a494dde849`. Les README et résultats individuels sont dans le sous-dossier `captures/`; notamment TalkingHead README (70 296 octets, SHA-256 `1415c35c3c328f000fc9408456861f2d74bd0fb7bd365cfe1d14e510fa9a2fa4`), arbre avatar (1 567 octets, SHA-256 `04dbbdb6ecc9391523c38e7592a64b80ef9a24acdd7c5b57f728a268d6cc573d`), GitHub search CC0-viseme (`4af480b8ee5b87b369a76c49bd22c9a783908272ebffbe97898f8ab0f0772a5f`) et GitLab avatar-viseme (`4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`).
- TalkingHead [README](https://github.com/met4citizen/TalkingHead/blob/b3e277b3b46f88e557bf28a2c5612a5b04e075c3/README.md), [licence MIT](https://github.com/met4citizen/TalkingHead/blob/b3e277b3b46f88e557bf28a2c5612a5b04e075c3/LICENSE), [mpfb.glb](https://github.com/met4citizen/TalkingHead/blob/6de99a0d7f94e6b0d04b3517b35eaa9a633ce7ae/avatars/mpfb.glb). README: 70 296 octets, SHA-256 ci-dessus; licence: 1 075 octets, SHA-256 `a168d1f90b70b313fb594ddb07e03c9dea08fe2a43df2b4f607db6920ce69cfa`.
- Lecture partielle autorisée du candidat : `/workspace/poursuite-opsys-2026-10-02-r1/avatar-mpfb-range-r1/capture-manifest.json` et `mpfb-json-summary.json`; chunk JSON brut zippé (`mpfb-json-chunk.gz`). Trois plages HTTP `206`, total 132 596 octets, source épinglée à l’URL raw ci-dessus; Content-Range final `bytes 20-132595/36815920`; SHA-256 de ces octets de chunk JSON `facbf07f0b42be3de57d43e517692458a24574c73fe9027e7399a427887aa13c`. Ce hash ne couvre pas le fichier GLB complet.
- [Rhubarb README](https://github.com/DanielSWolf/rhubarb-lip-sync), HEAD `9b9573cd21b253c9ba58739bbd1aa0b50b991bff`, version 1.14.0; capture détaillée et empreinte de licence dans [la comparaison audio existante](/workspace/poursuite-opsys-2026-10-02-r1/voix-avatar-audio-comparison-r1.md), SHA-256 `309e5b69a7c4b4988bc6d74ca890bac802548b507f31baa183d5d2a361841344`.
- [NVIDIA Audio2Face-3D SDK](https://github.com/NVIDIA/Audio2Face-3D-SDK), HEAD `1ca0f02535ed774f5dbcd724a31cd486368dc783`; [NIM/ACE](https://docs.nvidia.com/ace/audio2face-3d-microservice/latest/text/getting-started/getting-started.html). Licence SDK, contraintes et incertitudes poids/modèles consignées dans la comparaison ci-dessus.
- Catalogue NVIDIA : `/dev/shm/nvidia-skills-catalogue-root-r1/catalogue.log`, 179 715 octets, SHA-256 `69b7fc90705dc2efb021c819c14e9b3fef172006e6164244f1b39d550721b11e`; source annoncée `https://github.com/nvidia/skills.git`, « Found 398 skills ».

**Portée :** cette note conserve la recherche initiale et la qualification structurelle ultérieure du candidat MPFB. Elle distingue déclarations publiques, octets vérifiés et parcours restant à qualifier. La consultation du catalogue est temporaire et n’installe ni poids/service NVIDIA ni skill dans le projet; aucune option n’est adoptée ou déclarée compatible. La note ne remplace pas la vérification des avis de licence inclus avec chaque actif distribué ni une inspection de son contenu avant intégration.

## Rendu effectif et refus visuel — 3 octobre 2026

Le viewer r7 a chargé l'export r2 avec Three.js 0.186.1 et son GLTFLoader sous
Chromium/WebGL2. ROOT a vérifié les captures du corps et du visage, ainsi que les
changements de pixels des visèmes et de la mâchoire. Les empreintes restent
identiques avant/après; aucun nouvel OOM ni processus du banc restant.
La [décision ROOT](/workspace/poursuite-opsys-2026-10-02-r1/AVATAR-MPFB-CC0-VIEWER-ROOT-r7/execution/VERIFICATION-ROOT.json)
sépare le chargement technique réussi de l'apparence refusée : yeux uniformes,
sans iris ni pupilles après retrait des textures. L'export r2 n'est pas adopté.
Les essais rouges précédents du lanceur demeurent conservés.

Un export r3 de **6 600 124 octets**, SHA-256
`47d377b91d9872e439cbcc363b20630bcf68cda057218683aa0565372509b4df`,
projette les couleurs de la texture originale `brown_eye` par ses UV dans un
attribut `COLOR_0` des yeux. La texture source est épinglée
`4659691c7295ad6206c78b003e5fd0e5f91dcd53032fa914a229bb48cabe424b`.
Le RGB est converti en lumière linéaire; l'alpha et le mode MASK d'origine sont
conservés. Les données de géométrie, de squelette et de morphs restent celles
de l'export structurel précédent. Le candidat reste sous le profil existant,
sans image ni texture embarquée. Son rendu doit encore être vérifié sous le
viewer r8; aucune intégration produit ni synchronisation labiale audio n'est
déclarée par cette transformation.

## Inspection r8 et intégration facultative dans les sources

Le viewer r8 a effectivement rendu l'export r3 sous Chromium/WebGL2 avec le même
profil de ressources. ROOT a inspecté les captures neutre et `aa`; les yeux
corrigés sont acceptés pour une option humaine stylisée. L'actif de 6 600 124 octets
conserve son SHA-256 ci-dessus, quatorze visèmes et la mâchoire, sans clip
d'animation. Le [reçu indépendant ROOT](/workspace/poursuite-opsys-2026-10-02-r1/AVATAR-MPFB-CC0-VIEWER-ROOT-r8/execution/VERIFICATION-ROOT.json)
consigne les captures, déformations, ressources et limites du banc.

Les sources produit proposent désormais `mpfb-human-cc0-v1` facultativement; le
robot reste disponible. Le GLB et le README amont contenant la déclaration CC0
de cet actif sont conservés dans `core/assets/avatar-models/`; la transformation
est documentée dans `core/PROVENANCE.md`. Le code MIT de TalkingHead n'est pas
importé par cette adoption de l'actif. La sélection UI n'est pas encore qualifiée
dans un build déployé; le validateur natif doit encore passer ses tests sur ces
octets. Les visèmes sont des données disponibles, pas une synchronisation audio
livrée. Le raccord vocal et l'évaluation ACE restent des étapes distinctes.
