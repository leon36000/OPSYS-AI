# CRM07 — une version de modèle conservée dans chaque nouveau devis

## Objectif, raison et état
Le secrétariat choisit un texte de travaux et ses clauses pour préparer une nouvelle soumission,
sans réécrire les documents déjà acceptés lorsque le catalogue évolue. Cette tranche reprend le catalogue
M3 versionné et le calcul déterministe des lignes. Audit : [rattachement](AUDIT-RATTACHEMENT-MODELE-DEVIS.md).
CRM07 reste PARTIAL : le modèle est textuel; les lignes/quantités/coûts préremplis, mobile et M10 restent ouverts.
Aucun modèle juridique n'est généré. Aucun courriel ou engagement n'est envoyé.

## Architecture et fichiers
- `modeles_soumission.valider_modele_fige` valide la forme fermée du snapshot à six champs.
- `devis_durable.creer_devis` conserve cette copie dans la création, compare son contenu au rejeu et la garde aux transitions.
- `outils.creer_devis_depuis_modele` assure la provenance : version exacte lue dans le registre M3 vérifié,
  empreinte exacte attendue, lead existant dans M2, admin SQL actif, horodatage serveur.
- `soumission.contenu_client` est la liste blanche commune HTML/PDF. Seuls titre, description et clauses
  sont ajoutés au document, sans référence interne du modèle, auteur, coût ou taux de majoration.
- `devis_modele_ui.py` présente le choix paginé et le formulaire; `crm_ui.py` relie le projet et ses documents.
- `metier.py` ouvre le port humain privé; `capacites.py` le refuse aux voies génériques, agents et profils runtime.

## Données, routes et parcours
Le snapshot contient modele_id, revision positive, source_id, titre, description et clauses.
Il n'est jamais recalculé à la lecture du devis ni remplacé par la dernière version du catalogue.
1. Depuis les soumissions du projet : « Créer un brouillon depuis un modèle ».
2. Choisir un modèle parmi les pages de 25. La sélection transmet sa version et sa source exactes.
3. Lire les textes figés, saisir les lignes connues, quantité, unité, coût unitaire et majoration.
4. Créer le brouillon M3. M3 calcule les montants; la console ne les invente pas.
5. Consulter le détail ou télécharger le brouillon HTML/PDF. Ces fichiers conservent la mention non contractuelle.

Routes : GET/POST `/crm/lead/{lead_id}/nouvelle-soumission`,
GET `/crm/lead/{lead_id}/soumissions/{devis_id}/document/{format}` (html/pdf).
Ports privés : `m3_creer_devis_depuis_modele` et `m3_document_devis_console`.
Aucune nouvelle permission appareil. Les anciens appels `m3_creer_devis` restent inchangés.

## Atomicité, permissions et bornes
La réclamation idempotente, la création et l'audit sont dans la transaction SQLite existante.
Le reçu central contient une empreinte et des références, sans texte du modèle ni coûts.
L'autorité SQL est vérifiée avant chaque accès, y compris le rejeu. Réutiliser une intention pour une autre
charge est refusé. Une panne de l'audit ou un dépassement de quota annule la création et la réclamation.
Les deux voies génériques sont fermées avant tout effet. Le writer PostgreSQL demeure fermé.

Formulaire : vingt lignes maximum, corps 131072 octets, champs fermés et CSRF. Description de ligne500,
unité40, référence100 caractères. Nombres non négatifs en notation décimale ordinaire : neuf chiffres entiers,
six décimales au plus; majoration strictement inférieure à10000. Ce sont des bornes de saisie de cette tranche,
pas une politique de prix ou une recommandation de marge. Les refus métier M3 restent applicables.
Le validateur léger du socle ne contrôlant pas toutes les contraintes imbriquées, l'adaptateur vérifie
explicitement les types, champs, longueurs, motifs et tailles avant toute réclamation.
Lecture M2 principal et journal devis :10000 maillons maximum, sinon refus explicite; catalogue1000versions.
Sortie console65536octets : aucun PDF tronqué. Le défaut historique des autres outils PDF est conservé.
Les documents sont privés, no-store, téléchargés sans publication; le texte HTML et ReportLab est échappé.
La police PDF reste limitée aux caractères pris en charge; un caractère non représentable provoque un refus explicite.

## Tests, risques et prochaines étapes
Tests domaine : format fermé, versions, copies, idempotence, devis acceptés, ancien rendu sans modèle inchangé.
Tests document : prix affichés sans coûts, texte multilignes échappé, PDF réellement généré puis relu par pypdf,
ancienne version stable après modification du catalogue, clauses longues et quota adapté.
Tests HTTP/SQLite : vrais formulaires, création, source modifiée, rejeu, conflit, révocation, audit rollback,
limites numériques et textuelles, mauvais projet, concurrence et fermeture des ports agents.
Preuves d’exécution : reçus privés `crm-modele-devis-qa-20261027-r1`, qualification ci-dessous.

La liaison aux estimations mesurées et aux lignes préremplies demeure à approfondir. Ce formulaire ne remplace
pas l'estimation technique M3, le travail terrain M4, la facturation M5 ou les achats M6. M10, mobile,
qualification navigateur natif et writer PostgreSQL restent distincts. Les règles Nathan d'envoi et d'approbation
s'appliquent toujours; aucun gate externe n'est ouvert ici.

## Qualification locale — 27 octobre 2026

Le parcours HTTP/SQLite réel crée un devis depuis une version choisie, produit un PDF relu par pypdf,
puis conserve exactement HTML/PDF après acceptation et nouvelles révisions du catalogue.
La sélection finale `contracts-v1` : **745 réussites, 1 saut CI-only, 0 échec**, 36,22 s; Ruff et
`opsys-metier verifier` passent (283 outils, 173 déclarés aux appareils). Ces populations recoupent les
preuves précédentes et ne s’additionnent pas. Le saut vérifie uniquement un prérequis GitHub Actions;
les tests de génération et de lecture PDF ont réellement été exécutés localement.

La revue a conduit à renforcer les bornes imbriquées des arguments, le reçu idempotent de succès et
le quota PDF privé. La régression du quota par défaut détectée au troisième passage est corrigée;
les quatre passages antérieurs, y compris rouges de harnais et rouge produit, restent conservés.

La CI du précédent commit `2267acb7` est rouge : catalogue de verdicts agenda M2 incomplet et garde
d’inventaire d’outils M3 non actualisée. Les quinze refus agenda sont maintenant explicites, reconnus
par le catalogue fermé; un suffixe inconnu est rejeté. La garde M3 reste exacte et vérifie aussi
l’absence de portées appareil des ports CRM07. Ces régressions passent dans la sélection finale.
Une garde de mutation observée échouait sur cette même référence M3 rouge; sa campagne complète
reste à revérifier en CI. Aucun ancien run n’est annulé ni présenté comme réussi.

Reçu privé : `crm-modele-devis-20261027-r1/QUALIFIED-LOCAL.json`. Source en lecture seule pendant QA,
HOME/tmp privés avant imports, réseau interdit, limites effectives 1 GiB / un CPU / 96 tâches.
La qualification porte sur cette tranche locale; CRM07, M2, M3 et OPSYS-AI restent partiels.

Prochain raccord audité : [lignes réutilisables et coûts M6](AUDIT-LIGNES-PREFILL-M3-M6.md).
Ce document prépare le contrat; il ne prétend pas que les lignes préremplies sont déjà disponibles.
