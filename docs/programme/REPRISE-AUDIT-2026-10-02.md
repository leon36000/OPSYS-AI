# Reprise : audit et décisions du chef de projet

Jalon : 2 octobre 2026 UTC, 1er octobre au Québec. Référence Git `2e56c0d5605dfe575bde9244f38924d5390f2674`,
branche `codex/restructuration-2026-09-30`. Le travail local n'est pas publié. L'inventaire initial
conserve 2 465 entrées `git status --porcelain -uall`, dont des artefacts; ce nombre n'est pas un
nombre de fichiers métier ni de lignes de code. Les autres checkouts n'ont pas été modifiés.

## Verdict

Conserver la base d'Opus et poursuivre son durcissement. Les contrats, sources métier,
approbations, core, mémoire et tests constituent un travail conséquent. Les commits attribués
à Claude n'authentifient pas le modèle utilisé. Le produit reste partiel : ni autonomie universelle,
ni ingestion massive, ni avatar audiovisuel, ni mesure photographique de précision ne sont prouvés.

L'audit précédent a recensé 47 constats (14 P1, 30 P2, 3 P3); le registre actuel décrit 42
corrections locales et cinq constats partiels. Ce ne sont pas 47 nouveaux défauts réouverts.
Les suites historiques sont distinctes et se recoupent; leurs comptes ne s'additionnent pas.
Voir le [bilan antérieur](BILAN-RESTRUCTURATION-2026-09-30.md) et le
[registre](REGISTRE-AUDIT-2026-09-30.md). Le présent audit cible aussi les nouvelles exigences
de Nathan; il ne prétend pas relire exhaustivement chaque ligne du fork.

## Ce qui existe, ce qui reste

| Périmètre | Base à conserver | Limite qui conditionne la complétion |
|---|---|---|
| Core, droits, spécialistes | Fork dur, profils configurables, budgets/réservations, sandbox et garde d'admission | Couverture universelle des cibles, qualification image/Core/VPS et parcours réellement autonomes |
| M1 réception | Conversations, qualification, SMS déclaré, suivi, voix par phases et import STT | Fournisseurs réels, temps réel, français québécois, transferts/notifications et autonomie mesurés |
| M2 CRM | Pipeline et sources commerciales, outils transactionnels et cascade | Parcours opérationnels complets avec connecteurs, quotas, reprise et identité |
| M3 estimation | Prix/marge déterministes, qualité photo déclarée, incertitude et estimé/réel | Vision à l'échelle, données géospatiales de mesure et calibration des futurs paramètres |
| M4 terrain | Cédule, temps, clôture, événements, solveur/routage optionnels | Sidecars réels, dispatch produit, temps/quantités suffisamment qualifiés pour apprendre |
| M5 finance | Facturation/ledger, réserves, cashflow, CFO préparatoire, CSV AR et paie par tranches | Paie/fiscalité officielle qualifiées, connecteurs comptables réels et CFO complet |
| M6 matériaux | Réservations, sorties, réel/variance et événements | Fournisseurs réels, mobile, contrôles de stock et performance à l'échelle de production |
| M7 croissance | Marque, calendrier/export, performance, médias privés et lecture Growth | Publication/connecteurs, attribution exhaustive, saisie/provenance et apprentissage marketing |
| M8 analytique | Métriques/événements gouvernés et sources financières M5 | Couverture et fraîcheur de toutes les sources, dashboard et alertes opérationnels |
| M9 direction | Sources et rapports préparatoires | Décisions fondées sur couverture réelle, orchestration durable et retour d'expérience mesuré |
| M10 mémoire | Provenance/révisions, affaires/développement, contexte, PG/vectoriel et consolidation | Ingestion fichiers, classification, reprise/versionnage, évaluation longitudinale et qualité par domaine |
| Interface/mobile | Console, profils, plusieurs routes métier et parcours appareil | Avatar, espace connecteurs complet, ingestion, surfaces départementales et essais appareils réels |

Inspection directe : `src/opsys/console/application.py`, `src/opsys/console/pages.py`,
`src/opsys/memoire/store.py`, `departments/m03-estimation/src/m3_estimation/estime_vs_reel.py`,
`departments/m03-estimation/src/m3_estimation/qualite_photos.py`,
`departments/m04-field-ops/src/m4_field_ops/distances_osrm.py`.
Les jugements des lignes non revisitées ici reprennent le bilan daté, pas une nouvelle exécution globale.

## Clarifications retrouvées

Les [directives durables](../produit/DIRECTIVES-NATHAN.md),
[périmètres](../produit/PERIMETRE-MODULES.md) et ADR-0012 conservent réutilisation prioritaire,
profondeur, autonomie sous permissions, agents configurables, mémoire du développement et suppression
du consensus obligatoire de trois modèles. Le fichier du prompt signalé comme perdu a ensuite
été reçu et conservé sans modification dans
[PROMPT-NATHAN-RECUPERE-2026-10-01.txt](../produit/PROMPT-NATHAN-RECUPERE-2026-10-01.txt)
(16 341 octets; SHA-256 `e16d45ce779bf1af2030b886daf653400089cbe0527a2220410c0da349fb0419`).
Il contient la directive de réutilisation et le prompt M7 jusqu'à M7.8; les périmètres M1/M5/M10
déjà reçus restent dans les directives et la définition produit. Ce reçu ne prétend pas restaurer
une conversation absente ni compléter les parties absentes de ce fichier.
La [nouvelle instruction reçue](../produit/INSTRUCTION-NATHAN-2026-10-02.md) est conservée textuellement;
ses précisions sont appliquées dans la [vision](../produit/VISION-ENTREPRISE-APPRENANTE.md).

## Vérification fraîche avant développement

`opsys-metier verifier` via le module source passe : dix départements, 207 outils, 116 outils
déclarés aux appareils; SMS inactif sans ses variables requises. Capture de 1 070 sources
sélectionnées identiques avant/après, exit 0. Une première invocation hors `PYTHONPATH` pointait
sur la roue installée et échouait à localiser `departments`; c'est une erreur de chemin du harnais,
pas une panne démontrée du source courant. Elle n'est pas convertie en réussite produit.

## Recherche et priorité

Qualifier Docling pour extraction; Rasterio/py3dtiles pour données et visualisation géospatiales;
ODM uniquement en service AGPL non modifié séparé; Pipecat/LiveKit et rendu navigateur pour
audio/3D; NVIDIA ACE/Audio2Face en option GPU avec licences de code/poids/services séparées.
MemoryBench et les évaluations de mémoire longitudinale inspirent les tests; aucun résultat
publié ne prouve OPSYS. Aucune de ces nouvelles briques n'est intégrée par cette recherche.

Premier lot : rendre visibles les prérequis déjà pris en charge dans un espace Connecteurs privé,
sans nouvelle sortie réseau ni affichage de secrets. Ensuite : ingestion métier reprenable,
assimilation mesurée, calibration, précision visuelle/géospatiale, audio/avatar et qualification VPS.
Voir le [plan de reprise](REPRISE-PLAN-2026-10-02.md).

## Livraison locale de cette reprise

Le premier lot est codé : `src/opsys/console/connecteurs_ui.py`, montage dans `application.py`,
navigation dans `pages.py` et `tests/test_console_connecteurs.py`. GET `/connecteurs` et
`/api/connecteurs` sont privés admin/owner, avec droits relus avant lecture et avant réponse.
Les prérequis existants sont réutilisés; aucune valeur de secret, écriture ou requête fournisseur.
Le catalogue affiche aussi les capacités à construire sans les annoncer comme actives.

La campagne intégrée fraîche passe **312 cas**, zéro échec/erreur/skip : **296 console dont
17 Connecteurs**, et **16 E2E clôture de chantier**. Cinq cas PostgreSQL sont désélectionnés;
PostgreSQL n'est pas qualifié. Les E2E exécutent HTTP MCP, SQLite et bus métier avec données fictives,
pas le Core TypeScript ou les fournisseurs réels. Les 1 072 chemins sources sélectionnés restent
identiques pendant chaque campagne. Le rouge initial des deux routes et le premier échec Ruff
sont conservés; Ruff corrigé et catalogue passent. La revue Luna ciblée ne trouve aucun défaut
bloquant concret. Les instantanés SQL du test concernent quatre tables, pas tout le système.

Correction documentaire M3 : `estime_vs_reel.py` affirmait à tort que la durée estimée n'était
jamais produite. `estimation.py` la calcule et la persiste lorsque les données le permettent;
`outils.py` la reprend dans `m3.devis_accepte`. La docstring est corrigée, avec AST identique
hors commentaire et **149 tests M3 ciblés réussis** après correction. L'écart reste informatif :
aucune calibration/version de barème n'a été ajoutée. La suite 312 précède cette correction
documentaire; la preuve M3 la date séparément. Aucun total cumulatif de tests n'est revendiqué.

| Capacité | État de ce jalon | Preuve ou travail restant |
|---|---|---|
| Catalogue Connecteurs privé, présence seulement | VÉRIFIÉ LOCALEMENT | Routes et cas positifs/négatifs intégrés |
| Configuration API interactive et probes | NON LIVRÉ | Références de secrets, scope, quotas et adaptateurs réels |
| Ingestion massive / Fusion opérationnelle | CIBLE DOCUMENTÉE, NON LIVRÉE | Lots fichiers persistants, classification, reprise et évaluation |
| Apprentissage M3 | COMPARAISON EXISTANTE; CALIBRATION NON LIVRÉE | Paramètres versionnés, unités et jeu de contrôle indépendant |
| Mesure photo/géospatial | NON QUALIFIÉE | Pipeline de mesure et erreur contre mesures terrain |
| Audio/avatars par département | CIBLE DOCUMENTÉE, NON LIVRÉE | Pipeline vocal, rendu, actifs/licences, latence et coût |

La [recherche R21](../research/R21-2026-10-02/README.md) conserve candidats, notices, sources,
preuves et limites. Aucun candidat nouvellement étudié n'a été adopté. Les anciennes archives
restent inchangées. Le registre des 47 constats antérieurs reste distinct de cette sous-matrice.
