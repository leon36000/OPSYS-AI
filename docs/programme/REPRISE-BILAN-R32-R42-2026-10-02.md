# Bilan indépendant des tranches R32–R48 — 2 octobre 2026

Ce relevé donne les états observés tranche par tranche. Il ne remplace pas les bilans R22/R23, ne promeut pas un lot au statut global « fait » et n’additionne pas des suites qui se recouvrent. Les qualifications attestent uniquement leurs scénarios, snapshots et limites indiqués. Une préimage antérieure du bilan (SHA `e4910e340a43cff92c96189e0cb63489208e0752083066c0a769f99023a7bebb`) est conservée dans l’[archive R37 scellée](../research/R37-2026-10-02/README.md); la préimage immédiate avant cette révision R43–R45 (SHA `7d726d9b569121c3a021528510234f8dc1fdfb110e60e74af401e0c165678000`) est conservée [ici](/workspace/poursuite-opsys-2026-10-02-r1/bilan-r32-r42-preimages-r4/REPRISE-BILAN-R32-R42-before-R43-R45-r1.md).

| Lot | Capacité examinée ou obtenue | Qualification et limites exactes | Preuve principale |
|---|---|---|---|
| R29 | Mesure de longueur sur plan synthétique avec profil de calibration, points de fit/contrôle et homographie; séparation des unités pixels/mètres. | 9 tests réels OpenCV CPU, zéro skip, deux campagnes. Extra non adopté. Pas de photo client/terrain, segmentation, géocodage, reconstruction 3D ou précision physique qualifiée; photo non préparée refusée. | [Archive R29](../research/R29-2026-10-02/README.md), `QUALIFICATION.json`; wheel temporaire en RAM et reçus de licence dans le scratch géospatial. |
| R30 | Cohortes temporelles M3, split train/holdout par chantier et coupure UTC, statistiques déterministes. | 14 cas ROOT verts. Candidat inactif; aucun gain terrain. Le raccord M4 arrive en R32. | [Archive R30](../research/R30-2026-10-02/README.md), [qualification](../research/R30-2026-10-02/QUALIFICATION.json). |
| R31 | Évaluation retrieval sur corpus synthétique de 12 fragments et 9 questions, comparant lexical et double déterministe. | 18 cas ROOT verts. Le double a un forbidden-hit@10 de 1,0; lexical 0,333. C’est une mesure exploratoire de classement sur le corpus minuscule, pas une métrique d’accès ni une ACL; les contrôles d’autorité M10 sont une preuve distincte R33. La campagne auteur PG et le reçu détaillent séparément ces limites. | [Archive R31](../research/R31-2026-10-02/README.md), [reçu auteur](/workspace/poursuite-opsys-2026-10-02-r1/memoire-evaluation/receipt-r31-pg-final.md). |
| R32 | Raccord d’évaluation M3 aux faits M4, bus et registres réels, avec parcours devis accepté puis intervention et projection. | 80 cas ROOT uniques verts, zéro skip/erreur. Un seul WCT fictif : rapport insuffisant aux minima de cohorte (20 train/10 holdout); candidate et barème restent inactifs, aucun gain démontré. Archive scellée par ROOT : 52 capsules gzip, 477 154 octets. Le fichier `SCELLEMENT-ROOT-r1.json` est distinct du scellement R30 inclus dans l’ancien historique. | [Archive R32](../research/R32-2026-10-02/README.md), [reçu R32-r2](/workspace/poursuite-opsys-2026-10-02-r1/calibration-suite/RECU-R32-R2.md), [scellement ROOT](/workspace/poursuite-opsys-2026-10-02-r1/calibration-suite/SCELLEMENT-R32-ROOT-r1.json), qualification. |
| R33 | Autorité de lecture M10 liée à la session, au client canonique M2, au ticket et au parcours MCP. | ROOT : 192 tests Python préservés et 42 tests Core r4 verts; Oxfmt/Oxlint ciblés sont verts. Typegraph terminé par OOM et non qualifié; l’archive ne prouve pas une isolation SaaS/départementale générale. | [Archive et qualification R33](../research/R33-2026-10-02/README.md), [sceau ROOT](/workspace/restructuration-opsys-2026-10-02/memoire-premium-autorite-r33-archive-r2-preparation/SCELLEMENT-ROOT-r1.json). R26 traite l’ingestion/recherche de procédures, R33 l’autorité client. |
| R35 | Essai local du modèle BGE-M3 ONNX quantifié et mesure exploratoire de retrieval sur le banc R31. | 21 vecteurs 1024D; 9 requêtes/12 fragments. L’exécution d’inférence a réussi, mais la campagne PostgreSQL auteur a exit 1 après écriture sur une erreur de résumé; ROOT a relu les artefacts et recalculé les métriques sans nouvelle inférence. Forbidden-hit@10 est une métrique de pertinence du banc, jamais une ACL. Pas de service HTTP intégré, qualité premium, latence/coût/VPS qualifiés. Archive ROOT : 23 gzip, 263 109 octets. | [Archive R35](../research/R35-2026-10-02/README.md), [sceau du banc](/workspace/poursuite-opsys-2026-10-02-r1/recherche-model-r35/SCELLEMENT-BANC-ROOT-r1.json), [vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/recherche-model-r35/VERIFICATION-ROOT-r1.json). |
| R36 | Durcissement de la restauration du volume PostgreSQL physique : arrêt vérifié avant écriture, refus des mélanges logique/physique; correction des indications sandbox. | 39 cas locaux verts, zéro skip; les rouges sont conservés. Faux Docker stateful, SQLite WAL et Bash, pas de PostgreSQL réel, cluster/WAL récupéré ou VPS. | [Rapport R36](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/R36-postgres-physique/rapport-r1.md), XML vert; [archive historique R34](../research/R34-2026-10-02/README.md). |
| R37 | Synthèse privée de progression Fusion par domaine, sans contenu, montants, hash ou score d’entreprise; scénario M03 PostgreSQL synthétique de 51 séries/52 versions paginées. | 58 cas ROOT verts, zéro échec/erreur/skip, 1 111 sources stables; Ruff cinq fichiers vert. Archive ROOT scellée : 32 gzip, 307 217 octets. Les admissions sont fictives; aucun pilote CSV/PDF qualifié sous PostgreSQL. | [Archive R37](../research/R37-2026-10-02/README.md), [sceau ROOT](/workspace/poursuite-opsys-2026-10-02-r1/fusion-dashboard-r37/SCELLEMENT-ROOT-r1.json), [gel r2](/workspace/poursuite-opsys-2026-10-02-r1/fusion-dashboard-r37/FREEZE-R37-r2.json). |
| R38 | Sauvegarde et restauration physique de PGDATA, puis sauvegarde et restauration SQL sur PostgreSQL 17 isolé; la correction résout les erreurs r1/r2 de volume Compose et `compose start --wait`. | Archive R38 scellée. ROOT rapporte 49 cas du banc source verts et un scénario Docker dédié explicitement sauté. En essai réel r3, les 21 contrôles physiques et SQL passent; cleanup en 78,808 s, aucun conteneur/volume restant, baseline et sources inchangées. Données QA fictives et services applicatifs sleep absents : aucun parcours OPSYS, VPS, gateway/Caddy ou reprise utilisateur n’est qualifié. | [Archive et qualification R38](../research/R38-2026-10-02/README.md), [scellement](../research/R38-2026-10-02/POST-CHECK.json), [rapport source r3](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/R38-postgresql-reel/correction-source-r3/rapport-source-r3.md), [résultat réel r3](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/R38-postgresql-reel/r3/RESULTAT-r3.json). |
| R39 | Tests du chemin de migration des grants de l’agent CFO vers le schéma courant. | Un rouge conservé pour assertion `head0015` obsolète; après correction du test, la sélection de 15 cas passe, zéro échec/erreur/skip, 1 110 sources stables. Cela valide les tests isolés du chemin de migration; ce n’est ni une migration de production réellement appliquée, ni une action CFO externe, ni un cycle complet de restauration. | Reçu vert `/workspace/restructuration-opsys-2026-09-30/preuves/migration-cfo-r39-green-root-r1-2026-10-02-resultat.json`, reçu rouge adjacent. |
| R40 | Audit des sources primaires et de la couverture de paie Québec 2026. | Lecture seule : neuf PDFs re-hachés/identiques, analyse limitée de TP-1015/T4127 et bibliothèques candidates. Aucun parseur de barèmes, calcul, test ou taux de production ajouté; catalogue actuel explicitement non qualifié. | [Audit R40](/workspace/poursuite-opsys-2026-10-02-r1/paie-qc-r40/paie-qc-suite-audit-r40.md) et manifeste des captures. |
| R41 | Service HTTP local BGE-M3 raccordé au client d’embeddings et à PostgreSQL sur un scénario fictif isolé. | ROOT réel : **1 test passé, zéro échec/erreur/skip**, modèle et tokenizer épinglés, vecteur 1024D enregistré puis fragment attendu retrouvé en recherche hybride. Requête de 512 tokens : 888,76 ms observées; RSS provider maximal observé 1 130 848 256 octets; marge cgroup minimale 814 284 800 octets. Sept postconditions passent : sources stables, aucun secret dans les preuves, nettoyage exact et baseline intacte. Les erreurs du banc R3 (interpréteur venv) et R4 (migration avant nettoyage) sont conservées; huit helpers ROOT passent séparément. La campagne initiale 37 passed/1 skip reste historique. Pas d’image provider construite; M03 était lexical dans ce snapshot historique, aucun corpus client représentatif ni qualité premium/ACL/VPS qualifiés par ce scénario. | [Archive scellée R41](../research/R41-2026-10-02/README.md), [sceau ROOT](/workspace/poursuite-opsys-2026-10-02-r1/recherche-model-r35/SCELLEMENT-R41-ROOT-r1.json), [Résultat réel ROOT](/workspace/restructuration-opsys-2026-09-30/preuves/r41-bge-pg-root-r5-20261002T140431Z-final.json), [JUnit réel](/workspace/restructuration-opsys-2026-09-30/preuves/r41-bge-pg-root-r5-20261002T140431Z.xml), [gel final](/workspace/poursuite-opsys-2026-10-02-r1/recherche-model-r35/R41-FREEZE-R6.json), [helpers ROOT8](/workspace/poursuite-opsys-2026-10-02-r1/recherche-model-r35/R41-HELPERS-R4-ROOT-r1.xml). |
| R42 | Fonction pure préparatoire d’impôt QC régulier selon TP-1015.F, limitée au résident QC, salaire fixe bihebdomadaire et 26 périodes. Le correctif relie les coefficients canoniquement sélectionnés et réellement consommés par le calcul. | Archive publiée et scellée par ROOT : 30 gzip, 35 fichiers, 1 185 893 octets; SHA MANIFEST `8b8bf142c7d620744e784db307051aaf3b981d46a6e0ab9282bcd1db809a99c5`, SHA QUALIFICATION `e6f5b8487442481697b71e42c328715387d559d67269dc36c81939091dd68d77`. ROOT : 57 tests verts (0 échec/erreur/skip), 0,721 s, 1 117 sources stables; Ruff, format et diff verts. Les cinq points de contrôle publiés viennent d’un seul scénario, pas de cinq employés indépendants. Le catalogue demeure `NON_QUALIFIEE`, l’applicabilité juridique 2026 n’est pas établie. Pas de runtime/outil, net, RRQ, fédéral, bulletin, remise, dépôt ni paie réelle. | [Archive et qualification R42](../research/R42-2026-10-02/README.md), [manifest scellé](../research/R42-2026-10-02/MANIFEST.json), [scellement ROOT](</workspace/poursuite-opsys-2026-10-02-r1/paie-qc-r42/archive-r42-r1/SCELLEMENT-ROOT-r1.json>), [rapport auteur r2](/workspace/poursuite-opsys-2026-10-02-r1/paie-qc-r42/RAPPORT-r2.md), [résultat ROOT57](/workspace/restructuration-opsys-2026-09-30/preuves/impot-qc-preparatoire-root-r3-2026-10-02-resultat.json), [qualité ROOT](/workspace/restructuration-opsys-2026-09-30/preuves/impot-qc-qualite-root-r3-2026-10-02-resultat.json). |
| R43 | Construction CPU de whisper.cpp v1.8.0 et banc préparatoire fr-CA sur 20 clips Common Voice, avec WAV PCM16 mono 8 kHz. | Build CPU réel, puis HTTP réel sur 20 clips/20 locuteurs distincts, CPU deux threads. ROOT recalcule indépendamment WER 56/193 = 29,02 %, p50 41,55 s et p95 42,16 s ; les 20 requêtes dépassent la limite Core de 4 s. Pic RSS du groupe 938 639 360 octets, aucun nouvel OOM, serveur arrêté. Ce candidat est refusé pour le vocal temps réel sur cet environnement ; ce corpus de parole lue ne qualifie pas les conversations métier. R4/R5 et leurs erreurs sont conservés. | [Protocole R6](/workspace/poursuite-opsys-2026-10-02-r1/R43-whisper-r6/R43-whisper-r6.md), [vérification ROOT des helpers](/workspace/poursuite-opsys-2026-10-02-r1/R43-whisper-r6/VERIFICATION-HELPERS-ROOT-r1.json), [mesures et recalcul ROOT](/workspace/poursuite-opsys-2026-10-02-r1/R43-qualification-root-r1/VERIFICATION-ROOT-r1.json), [capsule R43 scellée](../research/R43-2026-10-02/README.md). Les vingt fichiers audio évalués ne sont plus présents dans les emplacements examinés; cette limite de reproduction est conservée dans la capsule. |
| R44 | Marque canonique → brouillons de chantier ; preuve de marque et contrôle de fraîcheur avant revue/export console. | ROOT combinée : **1 172 tests verts, zéro échec/erreur/skip**, dont 1 136 M7 et 36 installation, 59,687 s ; 1 124 sources sélectionnées stables. Les 39 nouveaux cas M7 sont inclus dans 1 136. R44a archivé : 94 gzip, 99 fichiers, 657 522 octets, roundtrip SHA vérifié indépendamment. La voie MCP générique peut rejouer un reçu historique avant le service ; la fraîcheur universelle reste non prouvée. Édition humaine R44b qualifiée séparément par ROOT : 1 181 tests verts, zéro échec/erreur/skip, 65,538 s et 1 127 chemins stables. Les campagnes se recouvrent et ne s’additionnent pas ; SQLite/fictif, aucune publication ni OAuth. | [Archive R44](../research/R44-2026-10-02/README.md), [résultat ROOT](/workspace/restructuration-opsys-2026-09-30/preuves/marketing-installation-root-r1-2026-10-02-resultat.json), [qualité ROOT](/workspace/restructuration-opsys-2026-09-30/preuves/marketing-installation-qualite-root-r1-2026-10-02-resultat.json), [guide](../grs/marketing/M7-MARQUE-USINE-R44A.md), [qualification ROOT R44b](/workspace/restructuration-opsys-2026-09-30/preuves/marketing-edition-root-r1-20261002-resultat.json), [édition humaine](../grs/marketing/M7-EDITION-TEXTES-R44B.md). |
| R45 | Correction des faux succès de l’installateur et de readiness. | Échecs gateway/edge fatals ; configuration opérateur absente = attente explicite code 3, distincte des erreurs runtime/configuration invalide code 1. Projection du générateur et validation embeddings relues ; console contrôlée même en attente. ROOT vérifie 36 cas R45/bootstrap inclus dans la campagne combinée de 1 172 ; Bash, Ruff et diff verts. Docker/HTTP de ces essais sont simulés ; aucune pile réelle, image, TLS ni VPS n’est qualifié. | [Archive scellée R45](../research/R45-2026-10-02/README.md), [Rapport R45](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/R45-installation-lecture-seule/rapport.md), [gel r3](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/R45-installation-lecture-seule/GEL-r3.json), [résultat ROOT](/workspace/restructuration-opsys-2026-09-30/preuves/marketing-installation-root-r1-2026-10-02-resultat.json). |

| R47 | Navigation explicite vers un département configuré : les listes absentes, invalides et les rafraîchissements échoués ne déclenchent pas de conversation de remplacement. | ROOT indépendant après formatage : **69 tests Node verts, aucun échec/erreur/saut**, six sources stables ; pic RSS du groupe 964 911 104 octets, marge cgroup minimale 3 268 698 112 octets. Aucun navigateur ni graphe TypeScript complet. La route implicite et les routes de sessions historiques conservent leur comportement. Avatar 3D et parole ne sont pas livrés par cette correction. | [Reçu ROOT69](/workspace/poursuite-opsys-2026-10-02-r1/R47-chat/ROOT-r1.json), [JUnit](/workspace/poursuite-opsys-2026-10-02-r1/R47-chat/ROOT-r1.xml), [design 3D](/workspace/poursuite-opsys-2026-10-02-r1/R47-avatar3d-transport-r1.md). |
| R48 | Installation PDF natif facultative : dépendances épinglées, bubblewrap et contrôle du worker isolé, clés hors image. | ROOT : **37 tests verts, zéro échec/erreur/skip**, 0,841 s ; 1 129 sources capturées stables. Tests de contrat sur doubles et probe négative du worker local : aucune image Docker construite, sandbox en conteneur ni VPS qualifiés. Le gel R2 fixe ces cinq sources ; le contexte Python séparé est maintenant couvert par **19 tests auteur verts**, zéro échec/erreur/saut, avec sources stables et Ruff ciblé relu par ROOT. Cette projection des fichiers et imports ne qualifie pas le transport Docker ni une image construite; elle conserve les ressources métier et exclut seulement Core et les archives de recherche. | [Résultat ROOT37](/workspace/restructuration-opsys-2026-09-30/preuves/pdf-install-root-r1-20261002-resultat.json), [JUnit](/workspace/restructuration-opsys-2026-09-30/preuves/pdf-install-root-r1-20261002.xml), [gel R2](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/installation-image-sandbox-pdf-readonly-r1/GEL-r2.json), [guide](../ops/INGESTION-PDF-DOCKER.md), [projection auteur19](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/python-context-r1/RESULTAT-vert-r3.json). |


Compléments vérifiés après les tranches scellées :

- **Essai PDF réel dans une base Python Docker isolée : refus d’isolation confirmé.** La base Python 3.12.14/glibc 2.41, les 54 distributions et les 139 fichiers projetés sont vérifiés; UID 1000, aucune capability effective, seccomp actif, réseau absent et filesystem racine en lecture seule. Le premier worker retourne `PDF_ISOLATION_INDISPONIBLE`; aucune extraction ni contrôle PDF de readiness n’est atteint. La cause syscall exacte reste inconnue à ce stade. Le conteneur QA R2 est retiré et la baseline reste intacte. R1 avait interrompu une création dont le conteneur est apparu tardivement : son nettoyage immédiat annoncé réussi était incomplet; ROOT a identifié puis retiré ce conteneur QA précis. Aucun sandbox en conteneur, image produit, pile complète ou VPS n’est qualifié. [Résultat réel durable R2](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/python-pdf-hybrid-isolation-refus-r1/RESULTAT-r1.json), [nettoyage tardif ROOT R1](/workspace/poursuite-opsys-2026-10-02-r1/PDF-HYBRIDE-CREATE-TARDIF-ROOT-r1/RECU-ROOT-r1.json).
- **Rapport d’acquisition M7 privé : 1 261 tests ROOT verts**, zéro échec/erreur/saut, 1 134 sources stables. Le rapport utilise les SDK M2/M5/M8 sous identité DB réelle et borne ses lectures et sa sortie. Dans ce snapshot, aucune affectation financière aux campagnes n’existait encore. Une tranche ultérieure ci-dessous ajoute les affectations documentées; elle ne transforme pas une facture AP saisie en dépense payée ni en ROI. [Capsule scellée M7](../research/M7-ACQUISITION-2026-10-02/README.md), [reçu ROOT](/workspace/poursuite-opsys-2026-10-02-r1/M7-ACQUISITION-ROOT-r2.json), [contrat et limites](../grs/marketing/M7-RAPPORT-ACQUISITION-SOURCEE.md).
- **Affectation des coûts M5 aux campagnes M7 : 1 522 tests ROOT verts**, aucun échec, erreur ou saut; 1 136 sources observées stables, avec deux chemins RRQ indépendants explicitement exclus. Le service privé relie des pièces AP vérifiées à une campagne, sous approbation N4, journal append-only, CAS, idempotence et contrôle d’autorité DB. Les parts cumulées ne dépassent pas la base HT/TTC déclarée; les pièces modifiées sont signalées périmées. La console permet affectation et retrait, sans paiement, écriture finale ou action externe. Les calculs sont qualifiés sur SQLite et données fictives; cette nouvelle projection refuse PostgreSQL. Paiement, récupération fiscale, coût économique, CPL et ROI demeurent inconnus. [Guide](../grs/marketing/M7-COUTS-AFFECTES.md), [capsule scellée](../research/M5-M7-COUTS-2026-10-02/README.md), [vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/M5-M7-COUTS-ROOT-r1/VERIFICATION-ROOT-r1.json).
- **Pilote vocal léger sur CPU : vingt inférences réelles sur dix extraits DEV.** tiny et base sont exécutés sur les mêmes audios, distincts du corpus TEST R43. p95 bout en bout : 2,133 s et 3,033 s; WER : 47,22 % et 39,81 %. La latence passe sur ce petit corpus de lecture, mais l’exactitude ne qualifie aucun agent de réception client. Aucun modèle adopté; les oracles et audios restent privés. [Mesures et capsule scellée](../research/VOIX-CPU-PILOTE-2026-10-02/README.md).
- **Confidentialité TTS : 30 tests ROOT verts**, aucun échec/erreur/saut. Les deux chemins de synthèse locale journalisent désormais uniquement la longueur du texte. Les nouveaux tests vérifient l’absence du texte et de ses préfixes dans ces deux messages. La campagne précédente interrompue par sa garde mémoire est conservée. Aucun modèle TTS ou autre chemin de journalisation n’est qualifié par ce correctif. [Capsule scellée](../research/TTS-CONFIDENTIALITE-2026-10-02/README.md), [vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/tts-local-privacy-r1/outputs/run-20261002T184923318729Z/VERIFICATION-TTS-ROOT-r1.json).
- **RRQ préparatoire Québec 2026 : 40 tests ROOT verts**, aucun échec/erreur/saut. Fonction pure C, C2 et CSA, limitée à un emploi régulier continu, 26 périodes et PM=12 explicitement attesté. Les plafonds annuels, transitions de tranche et arrondis sont testés; un contexte Decimal propre empêche les réglages externes de produire NaN. Les tableaux et exemples officiels sont sourcés. Aucun net, DAS, coût employeur complet, dépôt, outil ou raccord runtime de paie. [Guide](../../departments/m05-financecore/docs/m54f-cotisations-rrq-regulieres-preparatoire.md), [capsule scellée](../research/M5-RRQ-26P-2026-10-02/README.md), [vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/M5-RRQ-ROOT-r1/VERIFICATION-ROOT-r1.json).
- **Messages de navigation en français québécois : deux traductions locales appliquées par le mécanisme du catalogue.** ROOT vérifie la conservation à l’identique des 8 721 anciennes entrées et les deux nouvelles entrées de provenance `curated-local`. Les 38 tests auteur du mécanisme sont verts ; cette application ne prouve pas un rendu navigateur. [Vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/R47-frCA-application-root-r1/VERIFICATION-ROOT-r1.json), [source et procédure](../../core/ui/src/i18n/curated/README.md).
- **Avatar 3D : ressource serveur qualifiée sur 22 cas ROOT.** L’asset CC0, son catalogue et l’affectation explicite sont présents. Les 22 cas du handler passent; la suite HTTP générale suivante est interrompue par la garde mémoire et reste non qualifiée. Dix tests supplémentaires passent sur HTTP loopback réel, avec authentification bearer et autorité SQLite réelles : GET/HEAD, refus 401/404, retrait d’affectation et changement de droits pendant une lecture. La campagne R1 interrompue par sa garde mémoire reste conservée; R2 passe sans nouvel OOM, avec 39 empreintes stables. Ce serveur local appelle le handler réel et ne constitue pas un bootstrap Gateway complet. [Vérification HTTP ROOT10](/workspace/poursuite-opsys-2026-10-02-r1/R47-avatar-server/http-loopback-r2/VERIFICATION-ROOT-http-loopback-r2.json), [capsule avatar serveur scellée](../research/R47-AVATAR-2026-10-02/README.md). Aucun moteur de rendu 3D, voix ou lipsync n’est attesté. [Vérification ROOT22](/workspace/poursuite-opsys-2026-10-02-r1/R47-avatar-server/qualification-root-r6-owner-split/VERIFICATION-ROOT-r6.json), [reçu complet avec interruption](/workspace/poursuite-opsys-2026-10-02-r1/R47-avatar-server/qualification-root-r6-owner-split/RECU-ROOT-r6-owner-split.json).
- **Promotion et retour arrière de calibration M3 : 2 202 cas ROOT verts et neuf sauts identifiés.** Le parcours SDK fictif relie devis, faits M4, cohorte train/holdout, décision humaine N4, nouveau devis et retour arrière; les anciens devis sont préservés. Trois bancs historiques imbriqués sont exclus de cette sélection et ne sont pas déclarés qualifiés par elle. Les huit sauts OpenCV ont une qualification antérieure distincte R29; le neuvième est un contrôle PDF réservé à la CI. La concurrence est qualifiée sous SQLite seulement. Aucun gain sur chantiers réels ni calibration empirique en production ne découle de ces fixtures. [Capsule M3 scellée](../research/M3-PROMOTION-2026-10-02/README.md), [vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/M3-PROMOTION-ROOT-VERIFICATION-r3.json).

La suite M03 du provider R41 exige maintenant la recette canonique complète, avec empreinte et types stricts, pour éviter de mélanger des espaces vectoriels. ROOT a vérifié indépendamment **50 tests unitaires verts**, aucun échec/erreur/saut, sur douze chemins stables ; pic RSS 62 705 664 octets et Ruff vert sur huit fichiers Python modifiés. [Reçu et périmètre](/workspace/poursuite-opsys-2026-10-02-r1/memoire-m03-hybride/ROOT-unites-r1.json). Cinq tests distincts passent ensuite sur PostgreSQL réel avec embedder simulé, dont activation et oubli pendant la vectorisation. Un scénario réel supplémentaire passe avec le modèle ONNX épinglé, HTTP et PostgreSQL : procédure vectorisée, citation vérifiée en recherche hybride, puis oubli effectif. Son conducteur R1 sort néanmoins avec le code 1 après le reçu réussi, à cause d’une double suppression du dossier temporaire; les postconditions ont été relues indépendamment et ce rouge du conducteur est conservé. Le correctif scratch R2 n’a pas été rejoué. RSS arbre maximal 1 163 079 680 octets, marge cgroup minimale 588 025 856 octets, aucun nouvel OOM, port fermé et conteneur retiré. La recherche de procédures devient hybride uniquement avec le profil compatible explicitement configuré; sans profil elle reste lexicale. Ces scénarios fictifs ne qualifient ni pertinence premium sur corpus client, ni isolation SaaS, ni déploiement VPS. [Vérification ROOT PostgreSQL5](/workspace/poursuite-opsys-2026-10-02-r1/memoire-m03-hybride/pg-cas-r1/VERIFICATION-PG5-ROOT-r1.json), [vérification ROOT réelle1](/workspace/poursuite-opsys-2026-10-02-r1/memoire-m03-hybride/pg-real-r1/VERIFICATION-REAL-M03-ROOT-r1.json). La preuve R41 historique concerne son propre snapshot. [Capsule M03 hybride scellée](../research/M03-HYBRIDE-2026-10-02/README.md).

## Suites produit à approfondir

1. **M1 et mobile.** R43 a mesuré whisper.cpp/turbo q5 réellement sur CPU : 29,02 % de WER et p95 42,16 s sur 20 clips. Ce candidat ne respecte pas le budget temps réel Core de 4 s. Examiner un fournisseur ou un matériel adapté avant intégration ; puis compléter un parcours vocal fr-CA réel sur appareil, avec capture, permission, interruption, reprise et repli texte. La configuration STT et la dictée Core ne qualifient ni transcription, qualité vocale, latence, coûts ou cycle mobile.
2. **M5 finance.** Étendre les pilotes CSV/PDF à des documents autorisés représentatifs avec versions, contrôles d’extraction et rapprochement revu par une personne; qualifier le backend PostgreSQL et la reprise. Pour la paie, transcrire les règles versionnées après revue indépendante et bâtir des vecteurs oracles; aucun total net ou posting ne découle des audits R40/R42.
3. **M4 terrain/mobile, M3 calibration et M7 marketing.** Qualifier le parcours mobile session → intervention → événements terrain (M4), puis accumuler des observations indépendantes suffisantes avant toute calibration M3. R44a raccorde la marque canonique et les contenus de chantier avec preuve de version vérifiée ; R44b qualifie localement l’édition des textes par nouvelles versions non approuvées. Puis compléter calendrier, réputation, ROI, raccords CMO/API, exports et approbations. R32 reste insuffisant et ne calibre aucun barème; la promotion M3 ultérieure est prouvée sur une cohorte fictive indépendante, sans gain terrain revendiqué.
4. **M10 mémoire premium.** R41 a franchi le trajet réel modèle ONNX→HTTP→client→PostgreSQL→recherche hybride sur un fragment fictif. Il reste à qualifier l’image et son déploiement, les limites sous charge et les corpus représentatifs par permissions; une mesure ponctuelle de latence/RSS ne remplace pas une distribution en production. Maintenir provenance/citations, droits et effacement testables; distinguer pertinence du classement et autorisation. Le profil local compatible permet désormais une recherche M03 hybride sur les procédures explicitement vectorisées; le mode sans profil reste lexical. Ne pas convertir ce raccord en score d’assimilation de l’entreprise.
5. **VPS et restauration.** R38 prouve séparément le roundtrip physique et SQL sur PostgreSQL QA fictif isolé, mais aucun service applicatif/VPS. R45 a corrigé et vérifié les faux succès de readiness et des contrôles de santé sur doubles ; R48 a testé le contrat opt-in PDF et le worker local sans construire l’image. La suite doit prouver l’installation réelle OPSYS : volumes/profils, images et extras, sandbox requise, secrets/TLS, charge et surveillance, puis parcours de reprise côté utilisateur. Les preuves R34/R36 restent des contrôles locaux à faux Docker; R38 n’exécute aucun service applicatif ni VPS.

Les nombres de tests ci-dessus appartiennent à des sélections différentes; ils ne s’additionnent pas en total produit. Aucun test sur données d’entreprise réelles, aucun déploiement, publication ou effet financier n’est affirmé par ce bilan.

## Mémoire d’apprentissage et centre de configuration — vérifications suivantes

M10 propose désormais une revue privée d’observations M03 sourcées, sans activer de procédure ni déduire une cause à partir d’une fréquence. La sélection SQL et les deux chaînes de preuves sont bornées avant décodage ; le catalogue M03 est réellement injecté, les sorties sont limitées, et les droits sont relus après le rendu. **68 tests ROOT passent**, dont 22 de cette tranche et 46 voisins console, avec 17 empreintes stables. La preuve est limitée à SQLite fictive ; aucune qualité premium, économie de tokens ou amélioration terrain n’est déduite de ces observations. [Guide](../memory/PROPOSITIONS-APPRENTISSAGE-M10.md), [capsule scellée](../research/M10-APPRENTISSAGE-2026-10-02/README.md), [vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/M10-APPRENTISSAGE-ROOT-r1/VERIFICATION-ROOT-r1.json).

Le centre privé de configuration rassemble les dix départements, paliers de modèles, profils de spécialistes et plafonds de tokens, et renvoie aux formulaires existants. **117 tests ROOT passent**, dont 37 nouveaux et 80 voisins ; 19 empreintes sont stables, Ruff est vert. Les lectures sont bornées, les réponses sans cache, et les droits actuels sont contrôlés avant et après lecture/rendu. Les valeurs de clés, URLs et DSN restent masquées. Cette preuve SQLite fictive distingue profil activé, configuration projetée et tâche exécutée ; elle n’atteste pas encore le consommateur autonome des déclencheurs. Ces tests recouvrent des voisins M10 et ne s’additionnent pas à leurs 68 cas. [Guide](../grs/configuration/CENTRE-CONFIGURATION.md), [vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CONFIGURATION-CENTRE-ROOT-r1/VERIFICATION-ROOT-r1.json).

Le diagnostic PDF réel R3 conserve le refus `PDF_ISOLATION_INDISPONIBLE`. Sur la seule fixture publique de 233 octets, le processus Bubblewrap sort avec le code 1 et un message complet de 210 octets indiquant l’impossibilité de créer un nouvel espace de noms. Ce message ne constitue pas une trace de syscall ni une attribution certaine à seccomp. Les fonctions d’observation ont été restaurées, la commande produit et sa limite stderr de 8 KiB sont inchangées ; aucune extraction réussie, readiness ou installation VPS n’est affirmée. Le conteneur QA exact a été retiré, le conteneur préexistant reste intact et aucun nouvel OOM n’est constaté. [Résultat ROOT R3](/workspace/audit-opsys-2026-09-30/infra/vps-2026-10-02/python-pdf-hybrid-diagnostic-root-r3/RESULTAT-r1.json). La suite privilégie le worker Linux natif existant, sans rendre ce profil Docker permissif.

## Paie préparatoire, PDF natif et contrats cron — qualification suivante

**M5 : 79 cas ROOT uniques passent**, sans échec, erreur ou saut, avec Ruff vert
et 12 copies exactes des sources testées. Le calcul fédéral préparatoire réutilise
la façade publique des cotisations QC et conserve la précision intermédiaire.
Le contexte Decimal de l'impôt QC est explicitement indépendant du contexte
appelant. Le périmètre reste janvier–juin 2026, résident QC déclaré, première des
26 périodes, cumuls nuls et assiettes concordantes. Les références déclarées ne
sont pas authentifiées. Net, DAS, CCQ, bulletin et paie officielle restent ouverts.
Les campagnes 101 et 33 antérieures restent historiques et ne s'additionnent pas
à cette sélection. La [capsule scellée](../research/M5-FEDERAL-COMPOSITION-2026-10-02/README.md)
conserve les sources et les historiques. [Guide fédéral](../../departments/m05-financecore/docs/m54h-impot-federal-qc-regulier-preparatoire.md),
[vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/M5-FEDERAL-COMPOSITION-ROOT-r1/VERIFICATION-ROOT.json).

**PDF natif : 56 tests ciblés ROOT passent**, avec 139 copies unitaires stables.
Une sonde réelle distincte sous UID1000 observe les codes **0 / 3 / 1** : clé
fictive valide, clé absente après réussite du worker, droits invalides refusés
avant le worker. Le document public zéro page produit `PDF_PAGES_BORNEES` dans
bubblewrap ; aucune facture client ou base métier n'est créée. La
[capsule scellée](../research/PDF-NATIF-GEOMETRIE-2026-10-02/README.md) conserve aussi
141 copies du parcours réel. Le raccord natif opt-in et `--pdf-only` existent ;
les [guides d'exploitation](../ops/INGESTION-PDF-DOCKER.md) et
[d'isolation](../architecture/FUSION-PDF-NATIF.md) sont actualisés. Cette sonde
qualifie le gate Linux cloud, pas l'installation complète, un VPS ou l'image
Docker produit. Le refus Docker R3 reste inchangé.

Le centre de configuration ROOT117 dispose de sa
[capsule scellée](../research/CONFIGURATION-CENTRE-2026-10-02/README.md) : projection
privée et permissions SQLite fictives, sans consommateur autonome qualifié.

**Contrats cron : 42 cas CLI ROOT passent**, sans échec, erreur ou saut, avec
608 copies exactes. Les 40 cas du protocole sont une preuve distincte.
[Vérification CLI](/workspace/restructuration-opsys-2026-10-02/agents-cron-remove-cas-root-driver-r1/root-cron-cas-cli-r1/VERIFICATION-ROOT.json).
La qualification du Gateway reste ouverte : les dernières reprises s'arrêtent
sur les gardes mémoire avant les assertions. Le transport des intentions vers
le cron natif reste un design, sans autonomie livrée.

Les **110 cas UI** et les contrôles de qualité ciblés restent verts. Le chargement
ESM du test navigateur est corrigé, mais sa reprise R7 dépasse la borne RSS avant
la capture du rendu ; son nettoyage ne laisse aucun processus détenu actif ou
zombie. [Reçu navigateur](/workspace/poursuite-opsys-2026-10-02-r1/R47-avatar-server/browser-build-r7/browser-root-r7/browser.receipt.json).
Rendu WebGL, build courant, lèvres synchronisées et ACE restent à qualifier.

Le pilote de brouillons fournisseurs chiffrés est en cours : migration additive
0020, citations paginées et révision concurrente, sans nouvelle dépendance PDF,
OCR ou écriture M5 finale. Il conserve SQLite et le quota PDF partagé ; aucune
qualification PostgreSQL ou ingestion comptable massive n'est affirmée.

## Factures fournisseurs : brouillon sourcé et migration AP

La tranche de service AP est maintenant vérifiée par ROOT : **114 cas uniques
passent**, dont sept nouveaux cas AP, sans échec, erreur ou saut. Le cas PostgreSQL
est explicitement désélectionné ; cette campagne qualifie SQLite et des documents
fictifs. Les voisins couvrent PDF natif, console CSV, stockage et migrations. Les
481 copies de sources observées restent identiques pendant la campagne ; pic RSS
198 209 536 octets, aucun nouvel OOM. [Vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/FUSION-AP-ROOT-r1/VERIFICATION-ROOT.json),
[guide](../architecture/FUSION-AP-BROUILLONS.md).

La migration additive 0020 conserve CSV et PDF. Les propositions chiffrées portent
la révision du PDF et des citations de pages/fragments authentifiés. Elles restent
`A_REVOIR` ; la citation ne prouve pas à elle seule que chaque valeur est présente
ou exacte. CAS, rejeu, quota partagé, rotation de clé, corruption, concurrence et
révocation sont contrôlés. Rejouer une ancienne commande indique sa révision
appliquée sans remplacer le brouillon courant. Les journaux n'enregistrent pas les
champs financiers. La revue HTTP/console reste à raccorder ; aucun fournisseur,
compte à payer, écriture finale ou paiement M5 n'est créé par ce service.

La recherche comparative des éditions officielles T4127 janvier/juillet distingue
la couverture actuelle de la cible annuelle. Les paramètres fédéraux Québec
examinés sont inchangés, mais l'édition de juillet et les cumuls avant paie doivent
être pris en compte pour une tranche H2. La seule capture RQ janvier ne prouve pas
l'absence d'une mise à jour provinciale. Le calculateur conserve son périmètre
janvier–juin, première période et cumuls nuls. [Note sourcée H2](/workspace/poursuite-opsys-2026-10-02-r1/M5-H2-T4127-RQ-RESEARCH-2026-10-02.md).


## Revue AP, mandats durables et rendu navigateur — vérifications intégrées

**226 cas uniques ROOT passent**, sans échec, erreur ou saut, sur SQLite fictive :
9 cas de console AP, 7 du service AP, 63 PDF, 20 de console Fusion, 11 de stockage,
13 de migration, 46 d’intentions et 57 d’autorité cron. Le cas PostgreSQL est
explicitement exclu. Ruff passe sur les fichiers Python touchés. La campagne a
conservé 487 copies exactes de sources dans une archive vérifiée avant exécution;
les empreintes restent identiques à la sortie. Pic RSS : 201 187 328 octets;
43,37 secondes, aucun nouvel OOM ni processus du groupe survivant.
[Vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/AP-CRON-INTEGRATION-ROOT-r1/VERIFICATION-ROOT.json).

La console AP garde les valeurs hors des GET. Leur lecture exige un POST privé
avec CSRF; les droits et révisions sont relus après les opérations et après le
rendu. Une revue indépendante a identifié l’acceptation de `%ZZ`, `%` et `%0` par
le parseur urlencoded. Les trois tests refusaient le comportement antérieur
(303 au lieu de 400); ils passent après validation des échappements et prouvent
l’absence de brouillon AP écrit. Le rouge reste conservé.
[Reproduction ROOT](/workspace/poursuite-opsys-2026-10-02-r1/AP-ENCODAGE-CORRECTION-ROOT-r1/red/receipt.json).
Les valeurs saisies et citations restent une préparation humaine; elles ne
prouvent ni l’exactitude d’une extraction ni une dette, dépense payée ou écriture.
Aucun navigateur AP, facture client réelle, OCR ou backend PostgreSQL n’est
qualifié par cette campagne.

Le propriétaire cron privé conserve les capacités par empreinte et contrôle
mandant, profil, instance, déclaration entière, époques, leases, ACK et révocation
sous transaction. Les migrations réelles vont jusqu’à 0021 sans réécrire 0019 ou
0020; les tests historiques gardent leurs oracles intermédiaires et vérifient
ensuite la tête courante. [Contrat et limites](../architecture/AGENTS-CRON-AUTORITE.md).
Ce propriétaire n’est pas encore un raccord Core/admission/provider. La tranche
suivante sépare l’audience opérateur de l’audience des agents; elle devra ensuite
contrôler le grant dans la transaction d’admission et le job natif immédiatement
avant chaque stream. Aucun département autonome complet n’en découle encore.

**Avatar : un cas réel Chromium/WebGL passe** avec le GLB local CC0, sans changement
des onze surfaces épinglées et sans nouvel OOM. ROOT a inspecté la capture PNG :
le robot est effectivement rendu. Pic RSS du groupe : 1 131 286 528 octets.
[Reçu navigateur](/workspace/poursuite-opsys-2026-10-02-r1/R47-avatar-server/browser-build-r9/browser-root-r9/browser.receipt.json),
[capture](/workspace/poursuite-opsys-2026-10-02-r1/R47-avatar-server/browser-build-r9/browser-root-r9/avatar-render.png).
Ce cas ne démontre pas le parcours complet authentifié HTTP → UI, ni voix ou
synchronisation labiale. Le build R9 s’est arrêté à sa garde mémoire; R10 a
refusé de lancer Vite lorsque sa réserve initiale est passée sous 2 GiB. Ces
rouges restent conservés et la compilation demeure non qualifiée.
[Reçu build R10](/workspace/poursuite-opsys-2026-10-02-r1/R47-avatar-server/browser-build-r10/build-root-r10/build.receipt.json).

La revue des composants audio/avatar distingue les licences des moteurs et des
actifs : le robot actuel n’a pas de visèmes, l’exemple TalkingHead brunette est
non commercial, et le MPFB annoncé CC0 n’est pas encore inspecté. Le SDK MIT
Audio2Face ne couvre pas automatiquement les poids. Le catalogue officiel NVIDIA
listé par la CLI annonce 398 compétences; aucune compétence ACE/Audio2Face dédiée
n’a été trouvée dans cette liste. Aucun skill, poids ou service NVIDIA installé.
[Recherche et choix de prochaine preuve](../research/AVATAR-AUDIO-LICENCES-2026-10-02.md).


## Transport opérateur privé et contrat natif — reprise indépendante

Le canal HTTP de préparation et d’ACK est maintenant monté seulement avec son
credential opérateur distinct. **180 cas uniques passent** : 11 du nouveau transport,
24 MCP HTTP, 18 admission, 46 intentions, 57 propriétaire cron, 11 stockage et
13 migration. Ruff ciblé passe. Les 491 sources exactes archivées restent stables.
Les cinq autres cas PostgreSQL échouent avant leurs assertions : `initdb` manque
d’espace disque. Ils restent rouges et ne sont pas qualifiés; un sixième cas PG
était désélectionné. Aucun conteneur QA ne reste après la campagne.
[Vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CRON-OPERATEUR-INTEGRATION-ROOT-r1/VERIFICATION-ROOT.json),
[contrat HTTP](../architecture/AGENTS-CRON-OPERATEUR.md).

Le transport vérifie que la factory et la base canonique désignent le même fichier
SQLite et partagent la même connexion transactionnelle. Changer la base après
montage refuse l’appel. Les agents MCP ne peuvent pas employer ce credential;
le corps ne peut pas fournir de rôle ou d’identité humaine. Cette tranche ne
raccorde pas encore le scheduler Core à l’admission/provider.

La campagne Gateway native R9 termine **270 exécutions sans échec, erreur ou saut**,
dont dix scénarios CAS natifs distincts et une mutation concurrente réelle sous
verrou propriétaire. Le reçu global reste rouge : deux paramètres du test
historique avaient le même libellé JUnit (269 noms distincts). La correction
ajoute seulement l’index au libellé, sans changer données ni assertions. R10 est
ensuite arrêté par la garde de réserve mémoire avant de produire son JUnit;
la variante courante de libellé reste non qualifiée. Les résultats R9 et R10
sont conservés, sans transformer l’un en vert rétroactivement.
[Vérification des cas R9](/workspace/restructuration-opsys-2026-10-02/agents-cron-remove-cas-gateway-driver-r9/verification-root-r9/VERIFICATION-ROOT.json),
[reprise R10](/workspace/restructuration-opsys-2026-10-02/agents-cron-remove-cas-gateway-driver-r10/root-cron-cas-gateway-validation-r10/RESULTAT-ROOT.json).

La revue de raccordement constate deux écarts concrets : Python exigeait une
révision entière alors que Core produit un SHA-256 opaque; activer un job change
cette empreinte. Une migration compatible est en préparation : aucune conversion
inventée des entiers, aucun ACK d’une définition désactivée présenté comme autorité
de sa définition activée. La capacité est générée par l’hôte; Python n’en renvoie
jamais le secret. Sa reprise après redémarrage exige un stockage privé protégé,
encore à qualifier côté Core.

La recherche MPFB a maintenant inspecté uniquement son header GLB et son JSON par
132 596 octets de lectures Range. Le JSON déclare quatorze visèmes, mais aussi
36,8 MB, images/textures et 653 bufferViews : il dépasse le profil fermé actuel.
Aucun BIN complet, hash intégral, géométrie rendue ou actif adopté. La prochaine
preuve envisagée reste un export CC0 conforme, sans relever aveuglément les limites.
[Note mise à jour](../research/AVATAR-AUDIO-LICENCES-2026-10-02.md).


## Révision native opaque et vérification intégrée — 3 octobre UTC

La migration 0022 est maintenant implémentée et **190 cas distincts passent avec
Ruff ciblé**, sur 493 sources exactes archivées et vérifiées avant exécution.
Ventilation : 4 empreintes natives, 17 transport opérateur, 24 MCP HTTP, 18
admission, 46 intentions, 57 autorité cron, 11 stockage et 13 migration.
Pic RSS : 205 443 072 octets; 36,89 secondes; aucune modification des sources,
aucun nouvel OOM et aucun processus du groupe survivant.
[Vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CRON-REVISION-HTTP-INTEGRATION-ROOT-r1/VERIFICATION-ROOT.json).

Les révisions entières historiques restent conservées, avec des colonnes
séparées pour l'empreinte Core `sha256:` et son Base64URL canonique. Aucun ordre
numérique ni conversion inventée entre ces deux types. Le propriétaire accepte
une préimage désactivée et une cible activée distinctes; le rejeu exige la cible
exacte, et le passage entre types requiert une rotation explicite. Le downgrade
refuse les remises contenant une empreinte native; il ne les efface pas. La
migration 0021 reste byte pour byte identique. Cela qualifie le contrat Python
et HTTP; le calcul et le CAS du job cible dans Core ne sont pas encore raccordés
par cette campagne.

La validation HTTP refuse désormais les longueurs démesurées ou incohérentes,
ainsi que les doublons d'en-têtes d'autorisation et de corps. Les cinq nouveaux
cas ont d'abord reproduit le comportement défectueux; leurs logs rouges sont
conservés et ils passent après correction, sans remise créée.
[Preuve RED → GREEN](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HTTP-FRAMING-ROOT-r1/VERIFICATION-ROOT.json).

Le filtre de la campagne intégrée a désélectionné sept cas : six nécessitent
PostgreSQL et le septième compile seulement son DDL hors ligne. Ce dernier a
ensuite été vérifié séparément : **1 cas passe avec Ruff**, sans serveur ni
conteneur. Le schéma utilise une contrainte portable; la validation complète du
format reste également appliquée à la lecture par Python. Les précédents échecs
`initdb` restent conservés; la migration PostgreSQL réelle demeure non qualifiée.
[Contrôle DDL hors ligne](/workspace/poursuite-opsys-2026-10-02-r1/CRON-DDL-POSTGRESQL-OFFLINE-ROOT-r1/VERIFICATION-ROOT.json).
La campagne d'auteur de 108 tests avait encore un Ruff rouge pour une variable
inutilisée; la correction minimale est incluse dans la vérification ROOT actuelle.
Son reçu d'origine n'a pas été modifié ni présenté comme entièrement vert.

La tranche suivante corrige la sauvegarde Git des autorisations privées cron.
Le sidecar doit être expurgé en conservant une marque de récupération, la tâche
restaurée doit être désactivée et le provider doit refuser toute reprise avant
réautorisation. Ce raccord est en cours, sans credential de production ni
activation automatique de département.

## Sauvegardes privées et avatar CC0 — reprise du 3 octobre UTC

La sauvegarde globale `--exclude-secrets` est désormais corrigée : autorisations
cron expurgées, marque de récupération conservée, tâches associées désactivées,
diagnostics de quarantaine privés omis. Les anciennes autorités embarquées ou
les données invalides dans ces chemins font refuser l'export. La source SQL reste
inchangée; les anciens manifestes restent lisibles. **Huit cas natifs passent sur
les sources formatées r14**, dont une restauration SQLite réelle suivie d'une
réactivation forcée et du refus par le vrai garde. 120 sources exactes sont
archivées et identiques avant/après; pic RSS 668 733 440 octets, 6,03 secondes,
aucun nouvel OOM ni processus possédé survivant.
[Qualification ROOT r14](/workspace/poursuite-opsys-2026-10-02-r1/CRON-SNAPSHOT-REDACTION-ROOT-r1/green-r14/execution/VERIFICATION-ROOT.json).

La seconde étape r14 et la tentative séparée r15 ont été refusées avant Node par
le seuil mémoire; leurs reçus restent rouges. **Les cinq cas du garde passent
ensuite en r16**, dans le groupe natif cron et sur 104 sources exactes conservées.
Le parcours lourd scheduler/provider reste non qualifié. Les contrôles de
formatage et syntaxe ciblés passent sur neuf fichiers; le lint conserve un
avertissement de longueur de fichier, sans erreur. La vérification TypeScript
globale n'est pas démontrée par ces commandes.
[Qualification admission r16](/workspace/poursuite-opsys-2026-10-02-r1/CRON-SNAPSHOT-REDACTION-ROOT-r1/helper-r16/execution/VERIFICATION-ROOT.json).

La recherche MPFB a dépassé le stade Range décrit plus haut : source GLB entière
de 36 815 920 octets, SHA-256
`63c645a2a863b9972e9a9c2ed576a1de4c390b8475508e1473e69c87a3ee299c`,
licence CC0 de cet actif vérifiée dans le README amont du commit épinglé. Un export
de 6 582 764 octets conserve la géométrie, le squelette et quatorze visèmes tout
en retirant les textures et les morphs non retenus. Sa structure et ses données
binaires remappées passent la vérification indépendante; il n'est pas adopté.
[Source complète et vérification ROOT](/workspace/poursuite-opsys-2026-10-02-r1/AVATAR-MPFB-CC0-STRUCTURE-ROOT-r1/VERIFICATION-ROOT.json),
[licences et limites](../research/AVATAR-AUDIO-LICENCES-2026-10-02.md).

Le viewer r4 a ensuite réellement lancé Node/Chromium, mais une erreur de
collecte de logs du lanceur a interrompu sa qualification. Aucun rendu ni
synchronisation audio n'est déclaré validé. Son reçu rouge est conservé; le
lanceur est corrigé séparément avant un nouvel essai. Le robot actuel reste le
seul actif intégré. Le chiffrement des autorisations privées est également en
cours dans les propriétaires réels de chargement et de sauvegarde, sans activation
automatique ni credential de production.

### Reprise suivante du 3 octobre : rendu contrôlé et réponse CFO

Le viewer r7 a réellement chargé le candidat MPFB sous Chromium/WebGL2 avec le
GLTFLoader natif. Les captures neutre, visème `aa` et mâchoire sont non vides;
les deux déformations changent respectivement 38 339 et 67 807 pixels au seuil
mesuré. ROOT a inspecté les captures et **refusé l'adoption visuelle** : la
suppression des textures a retiré les iris et pupilles. Le robot demeure au
catalogue. Un export distinct conserve maintenant les couleurs de la texture
originale des yeux dans les sommets, sous le même plafond de 10 MiB; son rendu
reste à qualifier. Ce banc de captures ne prouve aucune synchronisation audio.
[Rendu r7 et décision ROOT](/workspace/poursuite-opsys-2026-10-02-r1/AVATAR-MPFB-CC0-VIEWER-ROOT-r7/execution/VERIFICATION-ROOT.json).

La projection CFO des obligations déclarées de paie et de DAS est en correction.
Le banc réel SQLite r2 a exécuté **37 cas uniques : 35 passent, 2 échouent**,
sans modification des 503 sources épinglées ni nouvel OOM. Les détails ajoutés
dépassent le budget de réponse dans le parcours financier rempli et celui de
13 semaines avec question maximale. La reprise doit compacter leur présentation
sans augmenter le budget, perdre les justificatifs ou affaiblir ces tests.
Ruff et la vérification des manifestes n'ont pas été exécutés après cet échec.
[Résultat rouge conservé](/workspace/poursuite-opsys-2026-10-02-r1/CFO-PAIE-DECLARATIONS-ROOT-r1/execution-r2/VERIFICATION-ROOT.json).

### Avatar humain facultatif : inspection visuelle acceptée

Le rendu r8 de l'export corrigé passe sous Chromium/WebGL2. ROOT a inspecté le
visage neutre et le visème `aa` : iris et pupilles sont visibles. Les déformations
changent 38 329 et 67 806 pixels; le pic RSS est de 977 780 736 octets, sans nouvel
OOM, écart de sources ni processus du banc survivant.
[Qualification visuelle ROOT r8](/workspace/poursuite-opsys-2026-10-02-r1/AVATAR-MPFB-CC0-VIEWER-ROOT-r8/execution/VERIFICATION-ROOT.json).

Cet actif humain stylisé est ajouté aux sources du catalogue comme option
facultative, à côté du robot conservé. Sa déclaration CC0 primaire et sa
provenance accompagnent le GLB. Les tests natifs d'admission et la vérification
de la nouvelle clé du sélecteur sont en préparation. Le build UI et le parcours
Gateway réel ne sont pas requalifiés; aucune animation synchronisée à l'audio
ni intégration ACE n'est démontrée par ces captures.

### Reprise du 3 octobre : CFO déclaratif, révision AP et worker SQLite

Le dossier CFO tient désormais les faits déclarés de paies et DAS dans la rubrique
16 sans relever le budget de sortie : tableau fermé, dates, sources, années et
versions conservées, montant utilisable distinct du montant déclaré. Une valeur
inconnue reste `null`; aucun net de paie, taux fiscal ou paiement n'est calculé.
**38 cas SQLite passent, avec Ruff et vérification des contrats**, sur 503 sources
épinglées. Les essais rouges r2 à r8 sont conservés, y compris les défauts de
budget et les corrections d'oracles de test; leurs reçus ne sont pas réécrits.
[Qualification CFO r9](/workspace/poursuite-opsys-2026-10-02-r1/CFO-PAIE-DECLARATIONS-ROOT-r1/execution-r9/VERIFICATION-ROOT.json).

La console décode cette présentation en libellés français, refuse les structures
incomplètes et revalide identité/session/rôle après la lecture et avant publication.
Le parcours HTTP qui retire effectivement le rôle durant la lecture rend 403 et
n'expose aucun fait financier. La boîte AP `/fusion/pdf/ap/a-revoir` lit seulement
les métadonnées : au plus 16 éléments, sentinelle de dépassement avec refus fermé,
liens révision/hash courants, aucun déchiffrement ni écriture comptable.
Un élément courant reste **à revalider**, pas « vérifié ». Le détail existant
conserve sa vérification explicite des pièces et citations.

La campagne combinée exécute **162 cas uniques avec succès**, dont les 38 CFO
précédents; ces comptes ne s'additionnent donc pas. Un cas PostgreSQL réel de
synthèse est explicitement désélectionné et reste non qualifié dans cette campagne.
La première tentative l'avait lancé par erreur : le conteneur créé par ROOT a été
identifié et supprimé seul, puis la reprise a isolé le périmètre SQLite. Les logs
rouges, les corrections de tests et les préimages sont conservés. Ruff passe
sur les 12 fichiers de code concernés après une correction de mise en forme.
[Campagne SQLite r3](/workspace/poursuite-opsys-2026-10-02-r1/AP-CFO-CONSOLE-SQLITE-ROOT-r1/execution-r3/VERIFICATION-ROOT.json),
[contrôle des sources finales et Ruff](/workspace/poursuite-opsys-2026-10-02-r1/AP-CFO-CONSOLE-SQLITE-ROOT-r1/style-only-r4/VERIFICATION-ROOT.json).

Le worker SQLite en mode source impose maintenant le tsconfig de son paquet
propriétaire, même lorsque le Gateway démarre hors du dépôt. Le chemin compilé
JavaScript garde son chargeur existant. **Les six cas natifs crypto passent avec
le vrai worker SQLite**, sur 10 308 pins, plugins natifs conservés : chiffrement,
perte/altération de clé, rejeu, rattachement à un autre store, snapshot périmé et
répertoire externe. Pic RSS 971 853 824 octets; aucun nouvel OOM ni enfant possédé
survivant. Les deux tests du propriétaire et le formatage passent séparément.
Le test du propriétaire a ensuite reçu une réduction explicite du type
`WorkerOptions.env` et ses deux cas ainsi que le formatage ont repassé.
[Reçus natifs et JUnit complets conservés](/workspace/poursuite-opsys-2026-10-02-r1/NATIVE-WORKER-AVATAR-ROOT-r21/execution-archive-r28/VERIFICATION-ROOT-r29.json).

Précision sur l'ancien garde r16 : ses cinq cas sont une preuve ciblée de helper
avec plugins groupés désactivés, pas une qualification du parcours provider.
La nouvelle campagne crypto conserve les plugins natifs. Elle prouve le stockage
et le worker source; l'installation VPS compilée, le client opérateur Core,
l'activation CAS et l'admission réelle finale restent à raccorder.

L'avatar humain facultatif a passé ses deux tests natifs d'admission; le contrôle
i18n contributeur déterministe vient aussi de réussir sans fournisseur, génération
de traductions ou mutation des sources. Les locales générées et le bundle UI
servi restent à qualifier. Le lint TypeScript approfondi r23/r24 est arrêté par
le plafond mémoire avant diagnostic; cette absence de résultat n'est pas un vert.
Le plan audio propose un raccord au lecteur existant mais le TTS ne fournit pas
encore de cues qualifiées. Aucun lipsync, ACE ou animation audio n'est livré.
[Proposition audio](../research/AVATAR-AUDIO-CONTRAT-2026-10-03.md),
[mesures terrain et précision réelle](../research/M03-MESURES-TERRAIN-2026-10-03.md).

### Qualification complémentaire du 3 octobre : routes privées et calibration

Le canal privé cron expose désormais `valider` et `renouveler`, en plus de la préparation
et de l’ACK. La validation relit l’autorité sans écrire; le renouvellement reprend une
préparation expirée selon les compteurs et limites existants. Le consommateur final Core
et l’activation d’une tâche restent à raccorder. La campagne complète des quatre fichiers
comprend **102 cas passés** : 21 HTTP, 57 propriétaire cron, 16 cohortes M03 et 8 promotion.
Ruff passe après deux corrections de forme; la première sortie Ruff reste dans les preuves.
[Preuve des 102 cas](/workspace/poursuite-opsys-2026-10-02-r1/CRON-OWNER-RPC-M03-P80-QA-ROOT-r1/execution-r1/VERIFICATION-ROOT.json).

M03 expose maintenant aussi `erreur_absolue_minutes_p80`, tout en conservant le P80 signé.
Les barèmes, seuils et candidates inactives sont préservés. Ce champ améliore la lecture
des erreurs; il ne prouve pas un gain de précision terrain.

Après clarification du type `WorkerOptions.env` dans le test, les deux cas du worker SQLite
et les huit contrôles de format passent. La vérification native i18n passe sur 4 170 fichiers
figés, sans génération de traduction, provider ou build UI.
[Preuve native et i18n](/workspace/poursuite-opsys-2026-10-02-r1/NATIVE-OWNER-I18N-ROOT-r33/VERIFICATION-ROOT.json).
Le lint TypeScript avec types reste bloqué par le plafond mémoire : la tentative native
r31 atteint 824 995 840 octets pour une limite de 768 MiB. Aucun diagnostic réussi ni
validation TypeScript globale n’est revendiqué. Les résultats passés de chaque étape et
ce refus restent distincts.

La recherche [GitHub et GitLab pour M03](../research/M03-MESURES-TERRAIN-2026-10-03.md)
conserve les composants adaptés déjà présents. Aucun miroir vieillissant ou DMS complet
n’a été ajouté pour augmenter artificiellement le périmètre.

### Tableau de bord : demandes cron humaines qualifiées

Les fiches agent peuvent maintenant préparer une demande cron ou demander son retrait,
avec session personnelle, CSRF, confirmation, fuseau explicite et révision attendue.
La même garde SQLite est utilisée par la console et le canal opérateur privé.
Les tests vérifient le rejeu, le retrait après désactivation, les refus de rôle/CSRF/révision
et l’absence d’écriture entre deux bases divergentes.

**90 cas passent** : 3 console cron, 46 intentions, 21 HTTP opérateur, 20 console CFO;
Ruff passe sur les 5 fichiers du patch. Les 21 HTTP recouvrent ceux de la campagne de
102 cas précédente : ces totaux ne se cumulent pas en couverture indépendante.
[Preuve ROOT](/workspace/poursuite-opsys-2026-10-02-r1/CONSOLE-CRON-INTENTIONS-ROOT-r1/execution-r2/VERIFICATION-ROOT.json).
Les demandes restent inertes. Le producteur hôte, l’ACK vers Core et le contrôle au
dernier instant avant provider restent à livrer.
