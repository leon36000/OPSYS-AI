# OCR financier — contrat de candidat et plan de raccord

4 octobre 2026 UTC. Statut : **PARTIEL — contrat qualifié localement**, aucun trajet OCR
produit activé. Le client doit pouvoir lire une pièce scannée avant sa saisie
fournisseur, sans transformer une erreur de reconnaissance en vérité comptable.
Le [rapport de qualification](M5-OCR-CONTRAT-RAPPORT-2026-10-04.md) précise les
82 cas du contrat et les suites PDF adjacentes; il ne qualifie pas un worker OCR.

## Décision et réutilisation

Le [pilote CPU](../../research/REPRISE-2026-10-04/M5-OCR-PILOTE-CPU-2026-10-04.md)
a réutilisé PDFium et Tesseract sur deux scans fictifs. La reconnaissance du
numéro de facture change sur l'image inclinée : conserver le texte et les scores
bruts, puis demander une revue humaine. Le pilote a acquis le modèle français
épinglé; les audits en lecture seule antérieurs à cette acquisition ne constituent
pas un nouvel inventaire d'installation.

La [recherche GitHub/GitLab](../../research/REPRISE-2026-10-04/M5-OCR-GITHUB-GITLAB.md)
reste applicable. L'interface TSV de Tesseract fournit déjà mots, boîtes et score;
réutiliser ce protocole au lieu d'ajouter un extracteur de factures ou un LLM.
La licence du moteur, du wrapper, du binaire PDFium/tiers et des poids reste
séparée. Ce contrat standard Python ne redistribue aucun de ces composants.

Le premier incrément est une frontière pure dans `src/opsys/ocr_candidat.py` :
conversion TSV et validation stricte du JSON candidat. Il ne lance pas de worker,
ne lit pas de fichier, ne chiffre ni n'écrit une donnée, ne crée pas de facture,
ne change pas le lecteur PDF natif et ne fournit pas d'endpoint. Le stockage,
l'isolation et la console sont des incréments suivants, avec leurs propres preuves.

## Contrat fermé v1

Les seuls champs racine sont `schema_version` (1), `genre`
(`m5.ocr_scan_candidat`), `statut` (`CANDIDAT_A_REVOIR`), `lot_id`,
`source_sha256`, `revision_source`, `configuration_sha256`, `profil`, `page`.
Le lot est un UUID minuscule canonique; les empreintes sont 64 hex minuscules;
la révision source est un entier de 1 à 2 147 483 647, jamais un booléen.

`ContexteOCR`, immuable, est fourni par l'orchestrateur autorisé à partir du lot
et de son profil installé, pas par le document ou un formulaire. Il contient
lot/hash/révision/configuration et les identités `rasteriseur` (`pypdfium2-X.Y.Z`),
`moteur` (`tesseract-X.Y.Z`), `leptonica` (`leptonica-X.Y.Z`),
`pdfium_sha256`, `modele_sha256`. Le `profil` JSON contient exactement ces cinq
identités et `langue` (`fra`). Elles doivent égaler le contexte attendu.
Les trois noms versionnés font chacun au plus 64 caractères et conservent leur
famille exacte : un nom de moteur ne peut pas se substituer au rasteriseur.
La concordance de métadonnées ne prouve pas à elle seule les binaires exécutés :
le futur prévol doit mesurer et contrôler ces identités avant le lancement.

`page` contient exactement `numero` (1), `largeur_px`, `hauteur_px`, `tokens`.
Dimensions entières positives ≤ 4 096 chacune; produit ≤ 4 000 000 pixels.
De 1 à 2 048 tokens; chaque token porte exactement `texte`, `x0`, `y0`, `x1`,
`y1`, `confiance_brute`. Boîte entière de surface positive dans la page; score
numérique fini entre 0 et 100, non calibré et sans valeur de validation.
Texte non vide/non blanc, UTF-8 strict, ≤ 512 octets/token et ≤ 65 536 octets au
total; caractères de contrôle C0/C1, substituts Unicode et U+FFFD refusés.
Le HTML reste du texte non fiable : son échappement relève de la future console.

JSON UTF-8 ≤ 262 144 octets avant décodage; clés inconnues ou doublonnées,
NaN/Inf, mauvais types, autre source/profil/révision ou page hors bornes refusés
avec une erreur générique sans texte OCR. Un score élevé n'approuve aucun montant.

Le TSV est borné à 524 288 octets avant décodage et 4 096 lignes de données.
En-tête Tesseract exact à douze colonnes; lignes à douze cellules, champs
entiers décimaux bornés. Hiérarchie page/bloc/paragraphe/ligne/mot valide,
parents antérieurs et identifiants uniques, aucun niveau externe à 1–5.
Une unique page 1 à l'origine doit égaler les dimensions attendues. Les niveaux
1–4 ont score -1 et texte vide; les mots ont score 0–100 et boîte positive.
Un TSV sans mot exploitable est refusé. Le parseur conserve l'ordre machine et
les boîtes : aucune correction, réorganisation, taxe ou montant interprété.

## Plan d'implémentation et vérification

Exécution décidée par Nathan : autonome avec délégation utile GPT-6 Luna;
ROOT garde le contrôle qualité. Aucun nouvel accord de conception routinier.

1. Écrire `tests/test_ocr_candidat.py` avant le module : candidat français valide,
   liaison source/profil/révision, JSON doublonné/non fini, bornes exactes et types,
   TSV Tesseract valide et parents/boîtes/scores/colonnes invalides. Conserver le rouge.
2. Implémenter `ContexteOCR`, `decoder_candidat(sortie: bytes, *, contexte)` et
   `candidat_depuis_tsv(tsv: bytes, *, contexte, largeur_px, hauteur_px)` dans le
   module unique. Aucun accès OS, dépendance lourde, parser PDF ou side effect.
3. Exécuter les fichiers de tests complets du contrat et des PDF natifs/console;
   lint des deux nouveaux fichiers. Épingler les sources, conserver reçus/JUnit et
   refus; contrôler secrets et liens. Vérifier des TSV historiques du pilote s'ils
   sont disponibles, en distinguant cette relecture d'un nouveau run OCR.
4. Publication sur la branche/PR existante seulement après qualification;
   documentation du périmètre et des limites, jamais « OCR opérationnel ».

Les bornes, booléens numériques, scores -1 de mots, lignes hiérarchiques absentes
et mismatch de version sont des classes adverses prévues par les tests.

## Incréments suivants

Worker séparé Linux/bubblewrap, diagnostic conservateur image seule/une page,
source ≤ 1 Mio, rendu DPI fixe et budget OCR propre mesuré. Aucun repli hors
isolation; conserver `PDF_IMAGE_OU_MIXTE` dans le chemin natif. Profil d'artefacts
verrouillé et notices complètes; prévol réel dans l'image opérateur obligatoire.
Le namespace Docker du profil PDF actuel n'est pas qualifié pour cet usage.

Candidat chiffré séparé, AAD lié à source/configuration/révision, revalidation
autorité après worker et avant lecture; quotas, reprise et audit sans corps.
POST humain privé explicite avec session/CSRF et écran échappé `no-store`.
La saisie AP demeure une action humaine distincte; aucun texte financier dans
l'ingestion de procédures M10. Précision sur corpus métier représentatif, revue
des identifiants/montants, mobile, photos, redressement et multipage restent à
qualifier. Le contrat seul ne prouve aucun de ces parcours.
