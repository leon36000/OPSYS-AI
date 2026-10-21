# M5 — classification structurelle des scans PDF

**QUALIFIÉ LOCAL — composant seul**, 4 octobre 2026. M5, l’OCR produit et
OPSYS-AI restent **PARTIEL**. Aucune publication GitHub dans cette tranche.

## Résultat et périmètre

Le module `src/opsys/ocr_pdf_structure.py` fournit un verdict fermé et la
seule géométrie de page. Son entrée est un lecteur pypdf déjà créé après les
limites du worker isolé. Il ne constitue pas une entrée HTTP, ne décode pas
l’image, ne reconnaît aucun texte et n’alimente aucune écriture comptable.
Une image structurellement candidate peut encore être malformée ou illisible.

La grammaire accepte une page, un XObject image unique, une matrice directe
positive couvrant exactement MediaBox et un seul dessin, avec q/Q équilibrés.
Catalogue et page ont des clés autorisées explicites ; ressources inconnues,
texte natif même invisible, dessin vectoriel, clipping, formulaire, action,
annotation, masque, transparence, filtre composé et JPX sont refusés.
Couleurs admises : DeviceGray/RGB/CMYK à 8 bits ; encodage brut, Flate ou DCT.
Cette inspection conservatrice ne garantit pas la prise en charge de tous les
PDF scanners. Une clé inoffensive non qualifiée peut provoquer un refus.

La source ≤1 Mio est une responsabilité du worker. Image déclarée : ≤4 096
pixels par axe et ≤16 millions au total. Raster attendu à 150 DPI : ≤4 096
par axe et ≤4 millions au total. Le calcul utilise `ceil(points * (150/72))`,
comme le pilote PDFium : une page 612 × 792 donne 1 275 × 1 651. Les pixels
originaux du bitmap ne sont pas confondus avec ceux du raster.

## Vérification ROOT

QA r182 : **179/179 tests**, zéro échec/erreur/skip, trois fichiers complets :
34 structure, 82 contrat OCR, 63 préparation PDF native. Ruff et vérificateur
métier passent. 1 259 entrées source/qualification inchangées avant/après,
16,029 s de campagne, compteurs OOM inchangés et aucun processus survivant
signalé par les gardes. La capsule conserve les reçus et les sources exactes.

L’appel réel à bubblewrap réutilise le lanceur et l’exécuteur borné PDF natif :
espaces séparés, réseau isolé, environnement effacé, montages lecture seule,
/tmp éphémère, RLIMIT avant pypdf. Aucun repli de parsing sur l’hôte. Quatre
PDF fictifs vérifient le candidat simple et les refus texte/dessin/multipage.
Le payload bitmap minimal de cette fixture ne prouve pas une rasterisation.
Les deux vrais scans fictifs du pilote r171 sont lus aussi sous confinement :
**tous deux refusés** par cette grammaire. Ils restent immuables. Leur ancien
succès raster/OCR ne prouve pas leur admissibilité structurelle au produit.

## Historique préservé

- r178 : collecte en échec car module absent ; preuve négative de collecte,
  pas preuve que 34 assertions échouaient.
- r179 : pilote de qualification ROOT mal raccordé ; ancien orchestrateur
  appelé sur un répertoire d’extraction déjà rempli. Aucun verdict produit.
- r180 : mauvais chemin ROOT des fixtures (`inputs` au lieu de `inputs/pdf`).
  Aucun verdict produit ; correction du harness, pas du module.
- r181 : six appels confinés conformes, puis deux erreurs de lint des tests
  (ordre des imports et longueur de ligne). Aucun succès global annoncé.
- r182 : mêmes comportements après correction du seul format des tests,
  campagne entièrement verte.

Le log agent initial `pytest-red-r1.log` indique un environnement sans pytest ;
il ne remplace pas un test fonctionnel négatif. Les logs disponibles sont
conservés tels quels avec leurs noms distincts, y compris les échecs ROOT.

## Livraison suivante

Voir le [design produit](M5-OCR-PRODUIT-DESIGN-2026-10-04.md) et
[l’audit des raccords](M5-OCR-PRODUIT-AUDIT-2026-10-04.md). Restent à construire :
worker OCR produit avec artefacts installés et épinglés, compartiment chiffré
lié à la révision source, revue privée humaine, installation et prévol de
l’image/VPS. Le refus PDF natif reste intact. Aucun corps OCR dans M10,
aucun préremplissage AP ni paiement automatique dans cette tranche.

Preuves : [capsule](../../research/REPRISE-2026-10-04/preuves/M5-OCR-STRUCTURE-r1.tar.xz)
et [inventaire](../../research/REPRISE-2026-10-04/preuves/M5-OCR-STRUCTURE-r1.json).
