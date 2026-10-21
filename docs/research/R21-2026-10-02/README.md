# R21 — Reprise, recherche et Connecteurs

2 octobre 2026 UTC, 1er octobre au Québec. Base Git `2e56c0d5605dfe575bde9244f38924d5390f2674`;
branche locale `codex/restructuration-2026-09-30`. Aucun changement publié.
Voir l'[audit de reprise](../../programme/REPRISE-AUDIT-2026-10-02.md), la
[vision produit](../../produit/VISION-ENTREPRISE-APPRENANTE.md) et le
[plan](../../programme/REPRISE-PLAN-2026-10-02.md).

## Preuves du changement

L'espace privé Connecteurs expose les prérequis SMS/STT M1 et mémoire/embeddings M10.
Il vérifie l'identité active admin/owner avant lecture et avant réponse, masque les valeurs
et distingue présence déclarée de connexion prouvée. Les formulaires de configuration,
références de secrets et tests fournisseurs sont les lots suivants.

| Campagne | Résultat | Limite |
|---|---|---|
| Routes avant code | 2 échecs 404 contre 200 attendus | Rouge intentionnel, conservé |
| Connecteurs ciblés | 17 réussites | Données fictives, HTTP local |
| Console et clôture de chantier intégrées | 312 réussites, 0 échec/erreur/skip; 5 PostgreSQL désélectionnés | 296 console dont 17 Connecteurs, et 16 E2E MCP/SQLite/bus; Core TypeScript et fournisseurs réels non exécutés |
| M3 après correction du commentaire | 149 réussites, 0 échec/erreur/skip | Logique AST identique hors docstring; durée/comparaison déjà implémentées, calibration non livrée |
| Ruff, quatre fichiers console/Connecteurs | Réussite après correction d'import | Le premier échec I001 est conservé |
| Catalogue après code | 10 départements, 207 outils, 116 déclarés aux appareils | Une déclaration ne prouve pas une exécution fournisseur |

La suite intégrée s'est déroulée de 00:47:56 à 00:49:51 UTC sur 1 072 sources sélectionnées
identiques avant/après. Elle précède la correction du commentaire M3; l'identité de logique
et les 149 cas M3 datent cette correction séparément. Ces comptes ne s'additionnent pas
aux campagnes historiques et ne constituent pas une qualification globale du dépôt.

Preuves : [résultat intégré](preuves/reprise-console-e2e-root-r1-2026-10-02-resultat.json--bf3dbef7a06c.gz),
[JUnit](reprise/connecteurs-console-e2e-r1.xml--1da451223444.gz),
[journal](preuves/reprise-console-e2e-root-r1-2026-10-02.log--928bec070a9e.gz),
[rouge](preuves/reprise-connecteurs-rouge-root-r1-2026-10-02-resultat.json--26c929f47596.gz),
[M3](preuves/reprise-m3-commentaire-root-r2-2026-10-02-resultat.json--10fbc61a7814.gz),
[AST](reprise/m3-docstring-verification.json--c650257e6281.gz),
[Ruff](preuves/reprise-connecteurs-ruff-root-r2-2026-10-02-resultat.json--a032497b2e5d.gz),
[catalogue](preuves/reprise-connecteurs-verifier-root-r2-2026-10-02-resultat.json--d6cb5350ea9b.gz).

La [revue indépendante Luna](reprise/connecteurs-revue.md--a7e389cc2461.gz) est statique et ciblée;
elle ne trouve aucun défaut bloquant dans cette tranche. Le test d'absence de mutation couvre
quatre tables et le réseau; il ne suffit pas seul à prouver toute absence future d'écriture SQL/fichier.
Les callbacks et le lecteur observés n'effectuent aucune écriture métier.
L'[audit des commits Claude](reprise/opus-audit.md--d640bc57226f.gz) distingue provenance Git
et modèle non authentifié. Son commentaire sur la docstring M3 décrit l'état avant correction.

## Recherche, sans adoption

Les [résultats Luna](reprise/recherche-briques.md--e6ee848d7385.gz) et leurs
[sources datées](reprise/recherche-briques-sources.json--ca71bb566ca4.gz) complètent les
[captures des outils ROOT](sources/sources-root-recherche-outils.json--0b74958fdc76.gz).
Les notices primaires retenues sont conservées dans le manifeste avec URL, date et empreinte.

| Candidat | Utilité à évaluer | Conditions avant intégration |
|---|---|---|
| Docling | Extraction structurée PDF/documents/tableaux/OCR | Code MIT; poids et moteurs séparés, lots bornés, contrôle des montants, coût/reprise |
| Rasterio, py3dtiles | Raster géoréférencé et affichage de nuages de points | BSD-3/Apache-2; CRS, échelle, date, données et actifs sous licences adaptées |
| OpenDroneMap | Photogrammétrie expérimentale | AGPL, service séparé non modifié selon politique du dépôt; mesures terrain et ressources à qualifier |
| Pipecat ou LiveKit Agents | Sessions vocales et transports temps réel | BSD-2/Apache-2; choisir après mesure fr-CA, interruptions, latence, coût et droits |
| TalkingHead | Rendu navigateur et visèmes | Code MIT; actifs d'exemple non commerciaux à remplacer, voix et avatars à qualifier |
| NVIDIA Audio2Face-3D SDK / NIM / ACE | Animation faciale GPU optionnelle | SDK MIT confirmé; poids/services/licences distincts, GPU/CUDA et profil à qualifier; SDK seul sans rendu avatar |
| MemoryBench, LongMemEval-V2, AgentCL | Évaluation de rappel et apprentissage longitudinal | Méthodes pour essais OPSYS, aucun résultat tiers transféré au produit |

ROOT a relu directement les notices Docling, Audio2Face SDK et py3dtiles et les pages arXiv
MemoryBench, LongMemEval-V2 et AgentCL. La requête directe alphaXiv a retourné 403;
les extraits indexés via Exa et les sources primaires arXiv restent distingués.
L'URL initiale `LICENSE` du SDK retournait 404; la notice valide est `LICENSE.txt`.
Les [tentatives initiales](sources/sources-root-sources.json--03c843605481.gz),
[reprise NVIDIA/arXiv](sources/sources-root-sources-r2.json--4d0d1c6d156f.gz) et
[GitLab/arXiv](sources/sources-root-sources-r3.json--ca054be23b33.gz) sont préservées.

Aucune installation, adoption, licence de poids, benchmark de précision ou économie mesurée
n'est obtenue par cette recherche. L'ingestion de fichiers et la calibration restent à construire.
Le [premier échec de préparation du harnais M3](reprise/m3-harnais-echec-r1.json--3abfd750faf2.gz)
n'avait pas lancé pytest; la campagne r2 est la preuve exécutée.

## Conservation

[MANIFEST.json](MANIFEST.json) décrit 73 archives gzip déterministes : origine, taille et SHA-256
du contenu original et compressé. Les rapports, notices, captures, préimages, sources de la tranche,
rouges et résultats sont conservés. Les bases fictives temporaires des tests sont exclues.
R19 et R20 ne sont pas réécrits par ce paquet.
