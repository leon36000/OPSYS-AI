# R28 — pilote PDF financier natif

**Backend et interface privée vérifiés localement dans cette portée.** Contrat et limites :
[Fusion PDF natif](../architecture/FUSION-PDF-NATIF.md). Cette tranche prolonge
le lot ingestion multi-format du [plan de reprise](REPRISE-PLAN-2026-10-02.md).

## Surface qualifiée

Neuf chemins : `fusion_pdf.py`, `fusion_pdf_worker.py`, schéma stockage,
migration `0018`, `pyproject.toml`, `uv.lock`, profil verrouillé
`requirements-ingestion-pdf.lock.txt`, tests PDF et les trois attentes de tête
dans `test_stockage.py`. Les fichiers nouveaux et les préimages sont inventoriés
dans `ingestion-pdf/backend-r1/GEL-SOURCES-r1.json` sous le répertoire de travail
`/workspace/poursuite-opsys-2026-10-02-r1`.

ROOT passe **122 tests** en une sélection PDF, SQLite, préparation CSV et
console CSV, le 2 octobre 2026 de **05:15:49 à 05:16:16 heure de Toronto**.
Zéro échec/erreur/skip; un PostgreSQL désélectionné. JUnit
`ingestion-pdf/backend-root-r1.xml`, SHA-256
`785f169fb09a631f7901d5bd83bfeae67d70e7c131e93c33b5e189403b8976c0`.
Le reçu `pdf-natif-backend-integre-root-r1-2026-10-02` conserve la sélection,
les sorties et les 1 107 empreintes stables. Les 65 cas auteur r5 se recouvrent
avec cette sélection et ne sont pas additionnés.

Le contrôle ROOT `pdf-natif-qualite-root-r1-2026-10-02` vérifie les neuf
empreintes finales, les 64 dépendances hors OPSYS inchangées, Ruff/AST,
catalogue dix départements/207 outils et diff. L'export frozen/offline garde
les versions runtime existantes et ajoute seulement pypdf 6.19.0.
Cette préparation de métadonnées ne constitue pas une installation VPS.

## Refus, panne et rouges conservés

Le corpus couvre extraction réelle sous bwrap, source/résultat chiffrés,
rejeu, CAS concurrent, clé/AAD/source corrompues, configuration inconnue,
quotas et rollback des écritures en échec. Les PDF actifs, chiffrés même à
mot de passe vide, images/texte invisible détectés, pages/texte/décompression
excessifs et réparations sont refusés. Les limites kernel réelles sont
observées avant l'envoi de la source.

Les rouges auteur restent conservés : import initial absent, fixture malformed
différente du refus attendu et découverte des descendants PID via une entrée
procfs absente. Le correctif kernel utilise PPid pour retrouver le même worker,
sans réduire ses limites. Le mode strict uv no-build refusait les métadonnées
du projet editable; la reprise autorisée ne construit que les métadonnées
locales OPSYS, offline et sans construction des 64 autres paquets.

## Suite et limites

L’interface ajoute trois chemins : routeur privé PDF, montage/hub minimal
dans l’application et tests HTTP. La sélection ROOT intégrée passe **145 cas**
le 2 octobre 2026 de **05:44:57 à 05:45:30 heure de Toronto**, zéro échec,
erreur ou skip, avec **1 112 sources surveillées stables**. Un PostgreSQL est
désélectionné. JUnit `ingestion-pdf/pdf-ui-integre-root-r1.xml`, SHA-256
`9c8bc5cc26a837f1aefff8a0b9c5586289cb6aac1b7ceb4b10a07a7bd54209ef`.
Reçu : `pdf-ui-integre-root-r1-2026-10-02`. Ces 145 cas incluent les 122
précédents; aucun cumul. Ruff sur les trois chemins UI passe aussi dans
`pdf-ui-geometrie-memoire-qualite-root-r1-2026-10-02`.

CSRF, autorité vivante, upload borné/fermé, rejeu, texte explicite paginé/échappé
et erreurs privées sont couverts. ROOT a identifié deux 500 : lot inconnu et
extraits d’un lot RECU. Les rouges HTTP ont été conservés puis corrigés en
404 et 409. Les clés absentes, résultats corrompus, PermissionError et retrait
d’identité pendant une erreur sont également testés. Le hash UI erroné du
rapport auteur r1 est corrigé par une note distincte, sans écraser l’original.
Pas de qualification navigateur, OCR, ingestion massive ou installation VPS.

Le pilote garde sources et résultat dans SQLite entreprise avec clés externes.
Aucune source financière n'est envoyée à un modèle et aucune écriture finale
n'est produite. OCR, documents mixtes génériques, ingestion massive, recherche
documentaire financière, purge et restauration VPS restent ouverts. M5, M10
et l'autonomie globale conservent leur statut partiel.
