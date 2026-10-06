# M5 — worker OCR opt-in, design d’implémentation

**EN COURS**, décision ROOT du 4 octobre 2026. La classification structurelle
est qualifiée localement, mais le pilote r6 n’est pas un worker produit.
Cette étape prépare un candidat brut ; ni stockage, ni HTTP, ni AP, ni M10.

## Contrat et réutilisation

Réutiliser bubblewrap et le pump borné de `fusion_pdf`, les limites du worker
natif, le classificateur `ocr_pdf_structure` et le contrat `ocr_candidat`.
Le lanceur reçoit les octets source et un contexte métier explicite (lot UUID,
révision) ; le PDF ne fournit jamais le profil attendu. Sa sortie est validée
avec l’empreinte source calculée avant l’appel. Aucun parseur PDF sur l’hôte.
Absence de Linux, confinement, dépendance ou artefact conforme : refus fermé.

Profil installé volontairement étroit Linux x86_64 : pypdf 6.19.0, Pillow
12.3.0, wheel pypdfium2 5.13.0 déjà qualifié, PDFium 153.0-7999, Tesseract
5.5.0, Leptonica 1.84.1, modèle français tessdata_fast déjà qualifié. Les
empreintes wheel/PDFium/modèle sont ancrées dans le code. L’exécutable système
Tesseract du profil local est également épinglé ; les dépendances système
transitives restent à qualifier dans l’image. Le prévol VPS reste non acquis.

Un bundle fourni par l’administration contient `wheel.whl`, `rasterizer/`
avec les trois packages complets et `tessdata/fra.traineddata`. Il est déjà
installé, sans symlink ni objet spécial, non modifiable par groupe/autres et
appartenant à root ou à l’utilisateur du service. Vérifier le wheel et RECORD,
les fichiers extraits et le modèle avant import. Monter seulement les fichiers
vérifiés en lecture seule, puis revérifier dans le worker. Le bundle n’est pas
une archive cliente et ne provient pas du PDF. Aucun download, installation,
extraction, cache ou réparation au démarrage de ce lanceur.

Le worker active les limites avant dépendances/parser, vérifie le runtime,
classe le PDF, puis seulement rend une page à 150 DPI. Comparer géométrie
pypdf/PDFium/bitmap avant OCR. PNG ≤512 Kio, raster ≤4 Mpx/4 096 par axe,
TSV ≤256 Kio, stdout global ≤512 Kio, stderr ≤8 Kio, AS512 Mio, CPU10 s et
mur15 s. Tesseract reçoit le PNG en pipe avec stdin/stdout/stderr multiplexés,
≤8 s internes, environnement explicite, un seul thread. Le descendant est
attendu/tué au besoin ; le groupe externe fournit la dernière limite murale.

La seule sortie de succès est le candidat validé par `ocr_candidat` (source,
lot, révision, configuration et profil). Refus fermés et messages génériques ;
aucun traceback, texte, PNG ou TSV dans journaux/erreurs. Le texte reconnu
reste non fiable et non corrigé. Une bonne structure ne garantit pas un
résultat OCR ni une facture correcte.

## Preuves attendues

Tests bundle : identité, RECORD, fichiers manquants/additionnels/altérés,
symlinks, permissions, bornes, ZIP invalide et modèle incorrect. Tests lanceur :
source/contexte/profil incorrects refusés avant exécution, commande confinée,
enveloppe et contenu refusés, timeout/échec sans repli. Tests worker : refus
structure avant renderer/Tesseract, versions/hash/chemins incohérents, limites
d’entrées/sorties et cleanup. Parcours ROOT réel séparé sur fixture fictive
avec bitmap valide, en conservant les deux scans historiques inchangés.
Les mocks de moteurs ne remplacent pas cette exécution réelle.

Le contrat ne promet pas l’absence de modification par un administrateur
hostile de l’hôte pendant l’exécution. Python et bibliothèques système sont
la base de confiance du déploiement ; vérifier leurs versions ne qualifie pas
leur provenance complète. Reproduction image/VPS et corpus métier restent
nécessaires avant une offre commerciale. M5/OCR/OPSYS-AI : **PARTIEL**.
