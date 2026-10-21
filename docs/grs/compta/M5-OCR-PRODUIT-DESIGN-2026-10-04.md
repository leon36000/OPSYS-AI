# M5 — première frontière produit pour les scans OCR

**EN COURS**, 4 octobre 2026. Décision ROOT après audit des vrais raccords PDF,
AP, stockage et console. Le [pilote qualifié](../../research/REPRISE-2026-10-04/M5-OCR-RUNTIME-PDFIUM-2026-10-04.md)
prouve raster et TSV sous confinement sur deux scans fictifs. Il ne prouve pas
qu'un PDF arbitraire est une image seule. La mauvaise reconnaissance du numéro
de facture interdit de confondre ce résultat avec une vérité comptable.

## Réutiliser avant d'ajouter

`fusion_pdf.py` et son worker préservent le lot source chiffré et rejettent
`PDF_IMAGE_OU_MIXTE`. Le contrat pur `ocr_candidat.py` vérifie le résultat OCR,
la source, la révision et les empreintes. Le flux AP possède déjà sa revue et
ses attestations humaines. Aucun de ces états ni de ces contrats n'est détourné.
Le profil qualifié est pypdfium2 5.13.0 / PDFium 153.0-7999, Tesseract 5.5.0 /
Leptonica 1.84.1 ; les ressources exactes restent celles de la preuve r171.

## Composant immédiat autorisé

Ajouter `src/opsys/ocr_pdf_structure.py` et ses tests : une classification
structurelle prudente, préalable à toute rasterisation. Son entrée est un
lecteur pypdf déjà construit **dans le worker confiné**. Ce composant n'est pas
une entrée HTTP ni un parseur à exécuter sur l'hôte avec une pièce client.
Les appels de tests portent uniquement sur des fixtures explicitement fictives.

Sortie fermée : verdict candidat ou refus et géométrie déclarée utile. Aucun
texte, montant, nom client, contenu image, OCR, confiance commerciale ou saisie
comptable. Une candidature structurelle ne valide ni la facture ni son contenu.
Les valeurs proviennent du code ; aucune décision LLM.

Profil volontairement étroit : une page, une image unique effectivement dessinée
sur toute la page, sans texte natif superposé. Source ≤1 Mio dans le lanceur,
page sans rotation ni recadrage et matrice compatible avec la page complète.
Images déclarées ≤4 096 pixels par dimension / ≤16 millions de pixels ; cette
borne déclarative ne remplace pas les limites du worker ou du raster final
≤4 millions de pixels. Encodages/couleurs/opérateurs autorisés doivent être une
liste explicite. Une structure inconnue produit un refus, jamais une supposition.

Refuser notamment PDF actif/chiffré/multi-page, annotations, formulaire, actions,
texte visible ou invisible, formes imbriquées, masques/transparence, image non
utilisée, plusieurs dessins/images, clipping, crop/rotation ambiguë, opération
inconnue, nombres non finis ou booléens et géométrie/dimensions excessives.
La grammaire exacte retenue et ses limites doivent être expliquées par les tests.
Ne pas annoncer une détection universelle de tous les PDF mixtes.

Le futur worker active les plafonds pypdf, RLIMIT et temps mural **avant** lecture
et classification, puis refuse si le profil/runtime réel est absent ou différent.
Le helper ne permet aucun repli hors confinement. Cette tranche ne crée pas
encore le lanceur, l'extra OCR, le téléchargement de poids, le stockage ou l'UI.

## Vérification et partage du travail

Luna possède le module et le fichier de tests ; ROOT possède ce design, la revue
et la qualification finale. Tests comportement d'abord, logs distincts même
rouges. Couvrir une candidature réelle simple puis les refus et mutations de
structure. Les deux scans fictifs historiques peuvent servir à inspecter la
grammaire ; ils restent immuables et un refus conservateur est acceptable.
La qualification ROOT doit inclure une exécution dans la sandbox existante.
Un test en mémoire avec un faux lecteur ne suffit pas à cette preuve.

## Verticale produit suivante

Après classification qualifiée : worker OCR dédié sous bubblewrap avec artefacts
et profil épinglés, validation du candidat, nouveau compartiment OCR chiffré
avec AAD/quota/CAS lié au lot et à sa révision, puis revue privée `no-store`.
Revalider l'identité et la source après le calcul. Prévol dans l'image/VPS cible,
aucun téléchargement au démarrage. Conserver le refus natif et les corps OCR
hors de la provenance M10. Aucun champ AP prérempli automatiquement ni paiement.

Les suites natives PDF/AP/M10 restent les protections de non-régression. M5,
la fonction OCR complète et OPSYS-AI restent **PARTIEL**. Le raccord productif
final sera l'accès à un candidat revu humainement, pas le seul classificateur.
