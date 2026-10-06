# Ingestion OCR — complément de qualification GitHub/GitLab

Recherche du 5 octobre 2026 UTC, en lecture seule via Exa. Elle complète la
[recherche OCR précédente](../REPRISE-2026-10-04/M5-OCR-GITHUB-GITLAB.md), sans remplacer son
pilote Tesseract/PyPDF, télécharger de poids, installer une dépendance ni traiter un document client.
Objectif : améliorer la proposition documentaire à revoir dans M5, jamais créer ou approuver une dette depuis l’OCR.

## Décision

| Brique examinée | Sources et qualification | Décision actuelle |
|---|---|---|
| Docling | `v2.133.0`, commit `b0315ea356298e4659c9727e9f5191dd2001860a`; LICENSE MIT et pyproject du même commit relus | Conserver comme candidat pour structure/tableaux, avec un profil minimal explicite et benchmark séparé |
| Kreuzberg | Dépôt canonique `kreuzberg-dev/kreuzberg`; LICENSE sur `main` extrait sous Elastic 2.0; une autre capture à `c03b0cc` retourne une licence de type MIT et une identité `xberg-io/xberg` | Ne pas adopter : identité/version et licence divergent entre captures; la capture Elastic est exclue par AGENTS.md |
| Reimburse OCR AI Agent, GitLab | Projet `elint-ai-community/reimburse-ocr`; page projet indique Open Software License 3.0; page LICENSE retrouvée, mais texte complet non extrait | Non qualifié : licence littérale et version manquent; aucun emprunt de code |

Le fork `Ac31415/kreuzberg` remonté dans la recherche est écarté comme source canonique. Les exemples
Docling Graph et projets de reçus/factures trouvés ne constituent pas des preuves de rapprochement AP québécois.
Les étoiles, catégories « production », chiffres de formats ou performances déclarées restent des déclarations amont.

## Ce que le code Docling permet de préciser

Le `pyproject.toml` épinglé déclare `docling-slim` 2.133.0 et sépare les extras de formats, OCR,
modèles et CLI. Le groupe de base contient neuf dépendances directes, dont `docling-core`, Pydantic,
requests et langcodes; le commentaire annonce environ 50 MB et « 8 packages ». Ce commentaire
n’est ni un inventaire exact du groupe ni une mesure d’installation OPSYS.

`format-pdf` ajoute pypdfium2 et docling-parse. `feat-ocr-tesserocr` ajoute tesserocr et pandas;
`feat-ocr-rapidocr-onnx` ajoute RapidOCR et ONNX Runtime. `models-local` ajoute notamment
torch, torchvision, docling-ibm-models et accelerate. Le bundle `standard` inclut ce dernier groupe :
installer le bundle complet serait un choix de ressources à qualifier, pas une optimisation démontrée.
Les marqueurs de tests distinguent `ml_ocr`, `ml_pdf_model`, `ml_vlm`, `ml_asr` et services externes.
Ils ne prouvent pas que ces tests passent dans notre environnement.

La licence MIT du code ne qualifie pas les poids et toutes les dépendances. Les réserves déjà documentées
sur les licences de modèles, le cache/préchargement, CPU/RAM et les limites du worker restent ouvertes.
Le chemin utile est un adaptateur isolé produisant texte/pages/zones et hashes, puis une proposition
humaine utilisant les contrôles AP existants. Un document mieux extrait ne devient pas une facture validée.

## Prochaine expérience utile

Comparer le pilote local existant et un seul profil Docling arrêté à l’avance sur un corpus anonymisé
autorisé, séparé du corpus de développement : factures francophones CAD, scans inclinés, tableaux,
taxes absentes et incohérences. Mesurer rappel/exactitude des champs et citations, refus pertinents,
latence, pic RAM, espace temporaire et nombre de corrections humaines. Précharger seulement les poids
dont les licences sont vérifiées; exécution sans réseau et sans écriture AP, sous limites explicites.
Sans avantage mesuré et provenance au moins équivalente, conserver l’adaptateur existant.

## Sources et limites de collecte

- [Docling LICENSE au commit](https://github.com/docling-project/docling/blob/b0315ea356298e4659c9727e9f5191dd2001860a/LICENSE)
  et [pyproject au même commit](https://github.com/docling-project/docling/blob/b0315ea356298e4659c9727e9f5191dd2001860a/pyproject.toml).
- [Kreuzberg LICENSE main](https://github.com/kreuzberg-dev/kreuzberg/blob/main/LICENSE),
  [capture à référence abrégée](https://github.com/kreuzberg-dev/kreuzberg/blob/c03b0cc/LICENSE)
  et [liste de commits](https://github.com/kreuzberg-dev/kreuzberg/commits/main/).
  La liste extraite s’arrête au 4 avril 2026 : elle n’atteste pas le HEAD d’octobre.
- [Projet GitLab](https://gitlab.com/elint-ai-community/reimburse-ocr) et
  [LICENSE retrouvé](https://gitlab.com/elint-ai-community/reimburse-ocr/-/blob/main/LICENSE).

Trois recherches valides ont demandé 21 résultats, avec doublons. Quatre recherches initiales aux
arguments invalides n’ont apporté aucune source. Deux requêtes directes à l’API publique GitHub
ont reçu HTTP 403 : aucun HEAD n’a été qualifié par cette voie. Les captures Exa sont du texte
extrait, dont les SHA identifient nos captures, pas les octets Git bruts. Ne pas présenter cette recherche
comme un benchmark, une revue exhaustive de dépendances ou une qualification de licence complète.

Les captures, préimages des prompts et revue sont conservées dans la
[capsule de cette tranche](preuves/PROMPTS-RECHERCHE-OCR-r1.tar.xz) et son
[inventaire vérifiable](preuves/PROMPTS-RECHERCHE-OCR-r1.json).
Les candidats ne sont pas des ingrédients intégrés au produit.
