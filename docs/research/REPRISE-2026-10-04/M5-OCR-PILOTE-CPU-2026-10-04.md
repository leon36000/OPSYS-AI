# Factures scannées — pilote CPU isolé sur deux fixtures

4 octobre 2026 UTC. **Prototype de recherche, aucun OCR intégré au produit.**
Suite à la [comparaison GitHub/GitLab](M5-OCR-GITHUB-GITLAB.md), un premier essai
réutilise les moteurs présents dans l’environnement. Aucun changement de `src/`,
endpoint, facture M5, fournisseur IA, budget ou installation système.

## Résultat observé

| Source entièrement fictive | Lignes identiques aux 10 libellés attendus | PDFium | Tesseract | Lecteur PDF natif existant |
|---|---:|---:|---:|---|
| Image nette, droite | 10/10 | 0,212 s | 0,349 s |`PDF_IMAGE_OU_MIXTE`, refus conservé|
| Même image tournée de 8°, contraste réduit | 4/10 | 0,264 s | 0,331 s |Même refus|

Ces décomptes comparent des lignes textuelles exactes sur deux fixtures; **ils
ne sont pas un taux de précision OCR, un score fr-CA ni une mesure VPS**. Les
montants fictifs sont reconnus dans cet essai, mais le numéro de la facture
inclinée change de `FACT-FICTIVE-001` à `FACT-FICTIVE-007`. Le fournisseur et
plusieurs libellés sont aussi altérés. Une confiance OCR brute, même élevée,
ne valide donc pas les identifiants métier. Texte et boîtes sont conservés,
sans nettoyage qui cacherait ces erreurs et sans correspondance AP automatique.

ROOT r133 clôt le parcours isolé des deux fixtures en 1,931 s au mur. Pic RSS
**observé par échantillonnage** du groupe : 48 242 688 octets, pas une garantie
maximale pour des fichiers inconnus. Les 1 248 sources/artefacts suivis restent
identiques; aucun OOM. Ce pilote n’est pas une suite pytest/JUnit et ses deux
observations ne s’ajoutent pas aux 668 tests de la consultation AP.

ROOT r132 rouge est conservé: le répertoire privé ne contenait pas le fichier
de configuration TSV; Tesseract produisait du texte simple, que le parseur du
pilote a refusé. r133 active explicitement `tessedit_create_tsv=1`, contrôle
l’en-tête et borne TSV/diagnostics. Aucun texte simple n’est déclaré TSV valide.
Le générateur a aussi été revu avant exécution pour élargir sa colonne monétaire
et éviter de créer une fixture tronquée; la préimage est conservée.

## Profil effectivement exercé

- PDF image seul, une page lettre, 69 672 ou 289 910 octets; création déterministe
  Pillow 12.3.0/ReportLab 4.5.1, identités et taxes fictives.
- Rendu PDFium à 150 dpi ; ≤ 4 millions de pixels, source ≤ 1 Mio, PNG/JSON/TSV ≤ 512 Kio.
- Deux workers isolés par la géométrie bubblewrap du lecteur natif: `unshare-all`,
  environnement effacé, bibliothèques et modèle en lecture seule, aucun réseau,
  aucune donnée client/secrets montés. `RLIMIT_AS` à 512 Mio, CPU 10 s,
  `RLIMIT_FSIZE=0`, délai 15 s par worker. PNG sur stdin → TSV sur stdout, un thread OCR.
- Tesseract 5.5.0 Debian `5.5.0-1+b1`, Leptonica 1.84.1. pypdfium2 **5.3.0 installé**,
  distinct du candidat stable 5.13.0 de la recherche; le profil n’a pas été mis à jour.
- ROOT a téléchargé seulement le modèle public `fra.traineddata` fast au commit
  `87416418657359cb625c412a48b6e1d6d41c29bd` : 1 130 365 octets,
  SHA-256 `ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca`,
  blob Git `d9e2b2160be0d1ca3b8f1bf2730fae476ef3b4a6` revérifié.
  Montage privé; aucune modification du tessdata système. L’audit RO de l’agent
  précède ce téléchargement et cette exécution ROOT, ce qui explique ses mentions
  « pas de poids téléchargé » dans les annexes originales.

## Licences, provenance et décision

Les notices installées et textes amont sont conservés: Apache-2.0 pour le moteur
et les données françaises séparément, BSD Leptonica, Apache/BSD pour le wrapper,
notices propres au bundle PDFium et à ses dépendances. Les polices synthétiques
DejaVu et leurs notices sont référencées séparément; aucune police DarkGarden
de ReportLab n’est utilisée. Les licences wrapper ne couvrent pas à elles seules
les binaires ou modèles. Le commit source du PDFium natif installé 145/build 7616
reste **non identifié** par ses métadonnées. Son `.so` est épinglé par SHA-256
`504df0960b4fab9e7c3bce8e4cf944d072a5aba76a5a199609d7addc49656568`;
les notices du bundle diffèrent de celles du tag wrapper. Aucun binaire ni poids
n’est redistribué dans la capsule de preuve.

Décision: poursuivre la qualification d’un OCR CPU dédié avec boîtes citables;
ce premier parcours direct PDFium→Tesseract évite d’installer OCRmyPDF pour une
simple exploration de fragments. OCRmyPDF reste un candidat de redressement et
Docling un candidat de layout/table, sans adoption. Avant intégration produit:
identifier et verrouiller l’artefact rasterizer déployable et ses notices,
conserver les coordonnées de la source après redressement, borner chaque page/
processus et tester les refus/quotas/reprises. Constituer un corpus représentatif
annoté, mesurer erreurs d’identifiants/montants et calibrer la revue humaine.
Ne pas activer un modèle seulement parce que cette facture nette réussit.

La sélection du profil sera explicite, isolée du lecteur natif et reliée aux
hashes source/config/moteur/modèle. Les propositions resteront à revoir;
le validateur pur M5 existant conserve fournisseur/PO/date/CAD/taux/arithmétique,
puis une confirmation séparée crée éventuellement la dette. Ce pilote ne
qualifie ni ces intégrations, 20 pages, mobile, image réelle client, concurrence,
PostgreSQL, production CFO ou assimilation massive.

[Capsule des fixtures/scripts/lectures](preuves/M5-OCR-PILOTE-CPU-r1.tar.xz),
[manifeste SHA-256](preuves/M5-OCR-PILOTE-CPU-r1.json). r132/r133, quotas, sorties,
préimages, notices et captures primaires sont conservés. Les moteurs et poids ne
sont pas copiés; la capsule donne leurs empreintes et sources de reproduction.
