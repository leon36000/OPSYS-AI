# Limites connues et ce qui reste à valider

État au 1er novembre 2026 (base `5208490a4`, ligne architecte ; la ligne « Marque v2… de M7 » est du 2 novembre 2026, base `e0424b040`). Cette page existe pour qu'**aucune lectrice ni aucun lecteur ne croie
qu'une fonction est prête alors qu'elle ne tourne que sur des doubles** (des simulations de test), qu'elle est « prévue », ou
qu'elle attend une décision. Elle s'appuie sur les matrices d'exigences, les rapports de qualification et les sections « Limites »
des documents d'architecture. Quand deux documents se contredisent, la matrice et le rapport de qualification, qui citent des tests,
l'emportent sur un en-tête de présentation.

## 1. Comment lire les mots

| Mot | Ce que ça veut dire ici |
|---|---|
| **Prouvé sur le vrai logiciel** | Un test ou un banc a exécuté le vrai code OPSYS-AI, avec des données fictives, de bout en bout. Ne dit rien des services externes. |
| **Prouvé sur doubles** | Le code tourne, mais ses entrées et sorties externes (courriel, SMS, modèle, réseau social, banque) sont remplacées par des simulations de test. Ça démontre la logique et les refus, pas le contact avec le vrai service. |
| **Prévu** | Décrit, parfois configuré, mais aucun code ne le fait fonctionner. Un avatar « voix » est prévu, pas disponible. |
| **Non qualifié** | Personne n'a rejoué le parcours sur la vraie cible (un vrai serveur, un vrai téléphone, un vrai service). |
| **À valider** | Une personne qualifiée (avocate ou avocat, CPA, vous) doit lire, décider ou signer. Le système ne tranche pas. |

Aucun département n'est déclaré « terminé » : tous les départements sont en mode `ombre` à l'installation (le département propose, vous
approuvez), et aucune instance de production n'existe.

## 2. Ce qui est réellement prouvé

- **Le moteur Python d'OPSYS-AI a été installé, démarré, sauvegardé (chiffré), détruit, restauré et mis à jour dans des conteneurs
  fictifs**, sans réseau (banc `install/qualification/`, [rapport](../qualification/QUALIFICATION-CONTENEUR.md)). Formule exacte
  autorisée : « moteur Python installé, démarré, sauvegardé, détruit, restauré et mis à jour dans des conteneurs fictifs ; VPS non
  qualifié ».
- Les suites de tests des départements passent sur SQLite avec des données fictives (voir le tableau des matrices plus bas pour les
  nombres), et le vérificateur de cohérence (`opsys-metier verifier`) valide les manifestes, les outils, les droits d'appareil et les avatars.
- Les approbations N3 à N5 sont appliquées par le code : un agent qui tente un geste de ce niveau est refusé tant qu'une personne n'a pas décidé.

## 3. Ce qui ne tourne que sur des doubles, n'a jamais tourné, ou n'est pas qualifié

| Sujet | État réel | Source |
|---|---|---|
| **Un serveur réel (VPS)** | Aucun n'a reçu OPSYS-AI. TLS/Caddy, DNS, certificats, `fail2ban`, `ufw`, journald, charge, redémarrage de la machine : jamais éprouvés. | [Qualification conteneur §9](../qualification/QUALIFICATION-CONTENEUR.md) |
| **Le Core (TypeScript) et les tours d'agent** | Non construit ni démarré par le banc. La sandbox Docker des agents n'est pas qualifiée ; un « vert » du Gateway ne prouve pas qu'un agent peut travailler. | [Exploitation](../ops/EXPLOITATION.md), qualification §9 |
| **L'installateur public** (`install/install.sh`) | N'a jamais terminé avec succès au banc (Node, réseau, `uv`, `pnpm` absents). Le manque de mémoire vu sur la VM ARM64 n'est pas reproduit. | Qualification §2, §9 |
| **Installation des dépendances avec empreintes** (`pip --require-hashes`) | Non exécutée (réseau). Les empreintes du verrou ne sont pas vérifiées par le banc. | Qualification §9 |
| **Copie de sauvegarde hors site** | Plan écrit, jamais exécuté. La garde de la clé de sauvegarde hors serveur est humaine. | [Plan](../qualification/PLAN-COPIE-HORS-SITE.md) |
| **PostgreSQL en exploitation** | SQLite est le défaut. Rejoués contre un vrai PostgreSQL 17 (1er novembre 2026) : le socle, les bases de connaissances M10 (recherche lexicale comprise), le graphe M10, le sas d'approbation, le bail, les créneaux, l'idempotence, l'envoi unique, la chaîne de migrations, `pg_dump`/`pg_restore`. Portés ensuite (portage du 1er novembre 2026, preuve par point de contrôle) : les consoles de saisie M1 à M7, les services M4, le cron opérateur, la liaison de cibles, les grants CFO, les documents d'affaire. **Non porté** : 3 gardes « SQLite seulement » (export du fichier de l'instance, nettoyage physique des clés, déclaration du cron M10 qui mettrait l'URL de la base, mot de passe compris, dans la configuration de la Gateway) : correctes par construction, chacune avec sa preuve sur PostgreSQL réel ; la quatrième (jobs de consolidation du magasin de développement M10) est portée depuis le 2 novembre 2026. **Vague 8 (2 novembre 2026)** : les constats planifiés, le planificateur durable, le bus (retrait de consentement M4→M1, créance levée par paiement M5→M2, constats contradictoires M2/M5/M8) et l'entrepôt M8 phase 2 sont rejoués sur PostgreSQL 17 réel et en vrais processus ; quatre défauts propres à PostgreSQL ont été trouvés et corrigés (constat rangé deux fois, code de refus trop long, mise à jour perdue entre deux admins, identifiant trop long dans l'entrepôt). Ces preuves portent sur des exécutions en conteneur jetable, sans fsync : aucune mesure de charge ni de durabilité. Fichiers de test encore rouges sur PostgreSQL : 29 sur 1263 (16 préexistants sur les deux moteurs, 3 gardes légitimes, 10 tests liés à SQLite). Ni charge, ni durabilité, ni pool externe, ni multi-client ; un verrou d'écriture de console sérialise les écritures humaines d'une base (plafond de débit non mesuré). PostgreSQL reste obligatoire avant toute offre hébergée. | [Qualification PostgreSQL §16 et §17](../qualification/QUALIFICATION-POSTGRESQL.md), [CABLAGE §11](../architecture/CABLAGE-CONNECTEURS.md) |
| **Modèles de langage réels** | Aucun appel réel prouvé par les tests (sans clé, rien n'appelle un fournisseur). La qualité des textes n'est mesurée par aucun modèle réel ; le gabarit d'évaluation n'a tourné qu'avec des répondants simulés. | [README](../../README.md), [M2](../architecture/M2-VICTOR.md) §8, [EVALUATION](../architecture/EVALUATION.md) |
| **Passerelle de modèles LiteLLM, rôles et politique d'économie** | Prouvés contre un **faux serveur compatible OpenAI** (rôles, appel routé, plafonds, replis, escalade, retour arrière, secrets jamais écrits) et par un essai **opt-in** contre la vraie passerelle de test (appels minuscules). La configuration générée est chargée par un vrai conteneur LiteLLM (opt-in, aucun appel de modèle). **Jamais fait** : installation chez un client ou sur un VPS, image `litellm-database` épinglée de `docker-compose.yml` (l'overlay du coffre est vérifié contre `main-latest` seulement), vLLM/Ollama sur GB10, OCR et vision-langage réels, mesure de qualité ou de coût réel (« non mesuré » partout ; un coût rapporté à 0 est « non déclaré »), PostgreSQL pour les tables de la migration 0086 (schéma portable, aucun test PostgreSQL lancé). La politique d'économie est une **recommandation non validée** ; STT, TTS, vision-langage et image ont un rôle et un test mais aucun consommateur ; les embeddings de M10 n'ont aucun repli et exigent une dimension mesurée ; dans une transaction d'outil le secret est résolu dans un point de sauvegarde (journal annulé avec la transaction). | [PASSERELLE-DE-MODELES](../architecture/PASSERELLE-DE-MODELES.md) |
| **Courriel (Gmail, Microsoft 365, IMAP)** | Prouvé sur doubles seulement. Aucun compte réel branché ; l'envoi et la synchronisation planifiés n'ont jamais parlé à un vrai serveur ; le serveur de réception « de confiance » n'est pas déclaré. | [CABLAGE](../architecture/CABLAGE-CONNECTEURS.md) §10-11, [M1-M6](../architecture/M1-M6-LEA-ROSALIE.md) §12 |
| **SMS** | Désactivé par défaut ; aucun essai contre le vrai opérateur ; la politique de consentement est une proposition non validée. | [Exploitation](../ops/EXPLOITATION.md) |
| **Voix et visage des avatars** | Seule la **messagerie** est disponible. Voix temps réel et audiovisuel sont **prévus** : aucun son n'a été produit, aucun worker, aucune ligne SIP. | [AVATARS-VOIX](../architecture/AVATARS-VOIX.md), [AVATARS](../architecture/AVATARS.md) |
| **WordPress et réseaux sociaux** | Le plugin n'a jamais été exécuté (ni PHP, ni WordPress). Aucun transport WordPress ni adaptateur de réseau réel : en production ces connexions sont « non raccordées ». | [M7-WORDPRESS-SOCIAL](../architecture/M7-WORDPRESS-SOCIAL.md) §10 |
| **Création d'images, logos, impression** | Aucun vrai modèle n'a produit d'image ; aucun OCR réel ; aucune police réelle ; aucun PDF/X ni CMJN ; aucune vidéo. | [M7-STUDIO-CREATIF](../architecture/M7-STUDIO-CREATIF.md) §14 |
| **Détection sur photos (M3)** | Aucun modèle de vision installé ni qualifié ; photos réelles et politique photos non validées. | [M3-M4](../architecture/M3-M4-MATHIS-GABRIEL.md) |
| **Fiscalité, paie, subventions (M5)** | **Aucune règle fiscale approuvée** (« 0 approuvée ») ; aucun cas officiel WebRAS/PDOC rejoué ; moteur de paie limité à 2026, Québec, bihebdomadaire, paie régulière ; catalogue de subventions vide. | [BASE-FISCALE](../architecture/BASE-FISCALE.md), [M5-SOPHIE](../architecture/M5-SOPHIE.md) |
| **Facturation par jalons, numérotation, PDF (M5)** | Prouvés sur SQLite avec le vrai bus, le vrai sas d'approbation et des données **fictives** ; **jamais sur PostgreSQL** (la garde de concurrence repose sur la clé primaire du registre et `relire_si_conflit`, non rejouées), ni avec QuickBooks, Stripe ou un vrai client. **Rien n'est envoyé** : le PDF est écrit dans `exports/factures/` et l'envoi au client reste une décision humaine non raccordée à M1. Le plan, la numérotation, les conditions de paiement et les numéros de TPS/TVQ sont des **déclarations du propriétaire** (forme validée, existence non vérifiée) ; les taxes des jalons sont arrondies facture par facture et peuvent différer de quelques cents des taxes du total (écart dit) ; le traitement comptable d'un acompte (produit ou dépôt de client) n'est pas tranché ; aucun outil n'annule une facture client (un numéro émis reste dans la suite) ; un devis déjà facturé en bloc ne reçoit plus de plan ; le rendu PDF dépend de la version de ReportLab ; aucune mention légale n'a été validée par un CPA. | [M5-FACTURATION](../architecture/M5-FACTURATION.md) |
| **QuickBooks** | Exports manuels seulement : pas d'API QuickBooks Online réelle. | `departments/m05-financecore/docs/import-quickbooks.md` |
| **Conseillers C1/C2 de M5 (camion/équipement, bâtiment commercial)** | **Dossiers chiffrés déterministes prouvés sur SQLite avec les vrais outils MCP, données fictives** (suite du département, reçus rejouables, mensualité C1 1194.99 $ / DSCR 1.7921, mensualité C2 1791.46 $ / occupation 2191.46 $ / écart −391.46 $ / DSCR 0.8214, idempotence, abus titres refusé, identité appareil refusée). **Limites** : liquidités et loyer **déclarés par l'appelant**, jamais lus d'un registre (absents = non calculable, jamais zéro) ; **aucune projection de prévision jointe** au dossier (la prévision M5.7 existe mais n'est pas consommée : l'impact trésorerie « depuis la prévision existante » reste à brancher) ; **DPA/CCA absente** (« NON_RENSEIGNEE », source officielle requise, aucun taux en dur) ; aucune valeur de marché estimée ; pénalités du prêteur non modélisées ; jamais exercé sur PostgreSQL ni sur un écran réel ; aucune décision ni recommandation n'en découle (CPA et prêteur à valider). | [README M5](../../departments/m05-financecore/README.md) |
| **Ingestion massive** | Aucun modèle de lecture de factures raccordé ; Docling non installé ; PostgreSQL/DBOS non faits ; apprentissage du profil et choix automatique du pack non faits. | [INGESTION-ONBOARDING](../architecture/INGESTION-ONBOARDING.md) §9 |
| **Connaissances et recherche (M10)** | Aucun vrai modèle d'embeddings ni de reranker mesuré ; contenu fiscal, comptable ou juridique réel absent ; corpus de mesure fictif. | [CONNAISSANCES](../architecture/CONNAISSANCES.md) §13 |
| **Contradictions de la mémoire et ordre de vérité (M10-04) ; ingestion de la mémoire de projet (M10-03)** | Prouvés sur SQLite avec le vrai bus, la vraie file d'approbation et le planificateur à horloge injectée (données fictives), **jamais sur PostgreSQL ni avec des données réelles**. Routine `contradictions-memoire` **inactive par défaut**. La détection ne porte que sur les faits **affirmés à clé** (par un agent, une personne ou un fichier à bloc `m10-affirmations`) : elle ne lit pas le texte libre des mémoires ni ne tire de clés des registres existants. **L'ordre de vérité suit le condensé de Nathan ; l'analyse d'écart recommande de placer la preuve exécutée au-dessus de l'étiquette d'une matrice : décision de Nathan en attente** (c'est une donnée à changer). Les classes `rapport_valide`, `test_sonde` et `code` n'ont pas de producteur. Aucun écran de revue des contradictions, aucun accès mobile admin ; une égalité de rang critique est comptée mais n'ouvre pas de demande. L'ingestion est un analyseur de structure (titres, en-têtes, ligne « Remplace ») : elle ne comprend pas le sens d'une directive. | [M10-CONTRADICTIONS](../architecture/M10-CONTRADICTIONS.md) |
| **Mémoire d'expérience des agents (J1 et J2)** | Garde d'admission et banc « avec / sans mémoire » livrés et prouvés par des tests ; **aucun modèle réel n'a été mesuré**, les répondants du banc sont des doubles déterministes (ils prouvent que le banc sait mesurer, pas que la mémoire aide un petit modèle, ni en français). 15 cas d'un seul auteur et d'un seul département. Un élément admis reste `candidat` : aucun département ne le lit, aucune promotion, aucun canari (J6), aucun signal de production (J7), pas de fiche déterministe (J3), pas d'enseignant (J5). Seuils non calibrés. | [MEMOIRE-EXPERIENCE-AGENTS-J1-J2](../architecture/MEMOIRE-EXPERIENCE-AGENTS-J1-J2.md) |
| **Observabilité et registre MCP** | Jamais testés contre un vrai Langfuse, un vrai Presidio ni le Core. **Les installateurs ne posent pas** `OPSYS_MCP_REGISTRE` ni `OPSYS_TRACES` : sans ces variables, rien n'est vérifié. | [OBSERVABILITE-MCP](../architecture/OBSERVABILITE-MCP.md) §8 |
| **Application mobile** | Les tests Jest ne prouvent ni le rendu sur téléphone ni le pont natif ; aucun test sur téléphone ou émulateur. Les parcours d'appareil sont rejoués par un harnais Python, pas par le Core natif. | [MOBILE](../architecture/MOBILE.md), matrices |
| **Concurrence et charge** | Prouvées pour des fils d'un seul processus sur SQLite ; aucun essai multi-machines, aucune mesure sous charge. | CABLAGE §11 |
| **Rétention et effacement (Loi 25)** | **Livré sur doubles et sur SQLite, inactif par défaut** : purge du courriel d'ingestion, adresse des courriels reçus par M1 (clé détruite), enregistrements vocaux (aucun worker n'en produit), traces. La première activation exige l'aperçu à blanc et la validation d'un admin. **Non couvert** : le texte neutralisé et le contact du lead dans le registre de M1, les lignes écrites avant le changement, les sauvegardes et exports existants, l'effacement d'une propriété ou d'une identité (M2). | [PLANIFICATION](../architecture/PLANIFICATION.md) §5, [M2](../architecture/M2-VICTOR.md) §8 |
| **Rapports financiers, budget déclaré et pré-audit (M5)** | **Brouillons préparatoires tirés du grand livre, prouvés sur SQLite avec le vrai bus, le vrai sas (N3/N4/N5), le vrai planificateur à horloge injectée et M8 réel, sur des données fictives ; jamais sur PostgreSQL ; aucun CPA n'a rien validé.** État des résultats (résultat **avant impôts**), bilan (résultat cumulé non clos : aucune écriture de clôture d'exercice), budget contre réel, rapport mensuel. Pas de flux de trésorerie, d'amortissement, de provisions, d'impôt sur le résultat ni de clôture ; les chiffres sont incomplets tant que les brouillons du grand livre ne sont pas validés (le rapport les compte et le dit). **Le budget n'existe que si Nathan le déclare** ; les comptes de coûts directs (marge brute) et les trois seuils du pré-audit (transaction hors norme, fenêtre de doublon, historique de changement de compte) non plus : sans eux la ligne ou la règle est « non calculable / non évaluée » et dit quoi déclarer. **Rentabilité par service et par ville : « non calculable » tant que le coût complet certifié M4→M5 n'est pas routé** (décision 2) ; aucune dimension d'équipe ; les chantiers reçus avant ce chantier n'ont pas gardé leur ville ni leur service. Le pré-audit ne voit ni les coordonnées bancaires des fournisseurs, ni les relevés importés hors rapprochement, ni la Loi 25 ; un constat est une question, pas un verdict ; « changement de compte inhabituel » vise le compte de charge, pas le compte bancaire. **Le constat planifié est inactif par défaut** et n'a jamais tourné plusieurs jours sur la boucle réelle ; M8 le date du début du jour UTC (même limite de fraîcheur du soir que le cash libre). | [M5-RAPPORTS-PREAUDIT](../architecture/M5-RAPPORTS-PREAUDIT.md) |
| **Planification autonome** | Treize tours de plus au planificateur durable (M8, M5, M10, M7 signaux/veille/studio, vérification des sauvegardes, péremptions, rétention) : prouvés sur doubles, inactifs par défaut. Signaux, veille, générateurs d'images, embeddings : **aucun transport réel**, ils disent « en attente de transport ». Aucune alerte n'est poussée à un humain en cas d'échec ; la console le montre seulement. **Onze constats pour M8** (M1, M2 ×2 dont le filet anti-perte, M4, M5 ×5 dont le cash libre, le pré-audit et la trésorerie prévue, M6, M7) sont déclarés par les manifestes des départements et déclenchés par le même planificateur (cadence dérivée du catalogue de M8, `ombre` ne publie rien) : prouvés avec horloge injectée sur SQLite puis sur PostgreSQL 17 réel (rejeux et vrais processus : créneau, bail, idempotence, deuxième instance, SIGKILL), **inactifs par défaut**, jamais sur la boucle réelle pendant des jours. | [PLANIFICATION](../architecture/PLANIFICATION.md) §9. **Sept routines de plus pour M1 et M10** (digest quotidien et alertes internes de la réception — rappel échu, conversation sans suivi, urgence non prise en charge —, consolidation nocturne des affaires par un énumérateur déterministe, audit « non-oubli » hebdomadaire, KPI des deux manifestes) : déclarées par les manifestes, inactives par défaut, prouvées sur SQLite avec horloge injectée, vrai bus et données fictives ; **rien ne pousse une alerte vers un téléphone ou un courriel** (« À voir » se lit dans l'app), aucun accusé de réception n'est envoyé au client, un jour de consolidation manqué n'est pas rattrapé (l'audit le dit), trois KPI de M10/M1 sur sept sont dits non calculables faute de source. `m10_consolider_affaire` est passé de N3 à N2. |
| **Marque v2, score de conformité, rapport hebdomadaire et mémoire marketing de M7** | Prouvés sur SQLite, vrai bus, vrais outils (M7, M8, M10), planificateur à horloge injectée et données fictives (2 novembre 2026) ; **jamais sur PostgreSQL, ni contre un service externe, ni avec une publication réelle** (la publication reste un geste humain, aucun modèle de langage n'écrit ni ne note). **Le profil réel de la marque n'existe pas : Nathan doit déclarer puis valider ses énoncés** (promesse, mots et messages interdits, voix, mentions) ; sans eux, les dimensions de conformité qui en dépendent sont « non évaluables » et seule la porte binaire du socle s'applique. Un motif ne comprend pas le sens (un mot interdit cité pour être nié est refusé), un énoncé non validé n'est vu que cité mot pour mot, les gabarits du code sont au vouvoiement. **Le rapport hebdomadaire est un exécuteur inactif par défaut** : tant qu'un admin ne l'active pas, aucun rapport n'existe ; il n'affiche aucun ROI calculé (la finance reste à M5) ; « leads par contenu » est cumulatif depuis l'export (M8 n'a pas de fenêtre) ; le coût par lead exige la correspondance des canaux et des relevés de dépense ; les tâches n'ont pas d'outil de clôture. Les leçons marketing exigent trois semaines distinctes et une décision humaine ; le signal d'objection vient des catégories d'avis, pas de leur texte. `m7_proposer_contenu` (fabrique historique) n'applique pas la porte v2. | [M7-MARQUE-RAPPORT](../architecture/M7-MARQUE-RAPPORT.md) §8 |
| **Entrepôt analytique de M8 (interdépartements)** | 44 mesures de plus (62 au catalogue fermé : +3 du chantier C5) alimentées par les constats de M1, M2, M3, M4, M5, M6 et M7 par le bus : prouvées sur le vrai bus et SQLite avec des **charges conformes au catalogue** (chaque outil de constat est prouvé dans la suite de son département ; un scénario les enchaîne via le planificateur, sur SQLite et rejoué sur PostgreSQL 17 réel depuis la vague 8), jamais sur un écran réel. **La dépense publicitaire relevée n'est que la somme des relevés reçus** ; son écart avec la dépense comptabilisée par M5 (D1) est un écart de DÉFINITION (relevés HORS_TAXES seulement, brouillons non validés dits). **Les onze constats (M5 ×5, M7, M4, M2 ×2, M6, M1) sont déclenchés par le planificateur durable, mais seulement une fois qu'un admin les a activés (inactifs par défaut)** : tant qu'ils ne le sont pas, une mesure reste non calculable puis périmée. La péremption des mesures de M7 et des factures suit l'âge du fait sous-jacent, pas celui du constat ; « clics, impressions, visites du site » sont cumulatifs depuis le premier résumé. Le coût par lead n'existe qu'avec la correspondance `canaux_marketing` déclarée par le propriétaire. Coût réel de M5 chez M8 : **non** (D4). Le bus n'authentifie pas le producteur d'un événement. Une valeur à couverture partielle le dit en texte, pas dans une colonne. **C5** : l'horizon, le seuil et les délais de la prévision sont GATE NATHAN (jamais inventés) ; la prévision n'est gardée qu'en version publiée (l'écart prévu-réel compare la S1 de l'ancienne prévision au PREMIER cash libre dont le jour atteint la fin de cette S1 ; il vaut réel moins prévu, sa fraîcheur est celle du plus ancien des trois faits et son empreinte les couvre tous, jamais une prévision recomputée) ; le constat planifié `tresorerie-prevue` est inactif par défaut comme les autres. Le schéma du catalogue et la règle `Q-TRESORERIE-PREVUE-COHERENTE` refusent un constat forgé (minimal qui n'est pas le minimum de la série, statut d'alerte incohérent, semaine hors horizon, doublon, semaine NON_CALCULABLE qui porte un montant). | [M8-ENTREPOT-SOURCES](../architecture/M8-ENTREPOT-SOURCES.md) |
| **Barème et mesure déclarés de M3 (M3-C1, M3-C2)** | Le barème, la quantité, le plancher rentable et les taux de marge d'une estimation viennent maintenant d'un barème **déclaré** par une personne (versionné, chaîné, en vigueur) et d'une mesure **déclarée** (valeur, bornes, méthode, confiance, pièces) : un agent qui passe un barème libre est refusé, sans référence aussi, avec ce qu'il faut déclarer. Prouvé en processus Python sur SQLite avec les vrais outils, l'horloge injectée et des **valeurs fictives**. **Limites** : **aucune valeur réelle** (le barème de Nathan n'est pas dans le dépôt : sans lui M3 ne chiffre rien) ; **aucun écran** pour déclarer un barème ou une mesure (appareil `admin`/`seller` apparié, ou le futur écran des réglages de direction) ; jamais exercé sur PostgreSQL ni sur un appareil réel ; l'auteur repose sur l'identité d'appareil d'OPSYS-CORE ou la session de console, revérifiée en base mais non établie par M3 ; la chaîne n'a pas d'ancre externe ; la voie d'essai (variable d'environnement du serveur `OPSYS_M3_VOIE_LIBRE`) ne doit jamais être posée en production et rien ne le vérifie au démarrage ; **`m3_creer_devis` reste libre** (coûts de lignes et taux d'un devis viennent de l'appelant, la revue N4 de l'envoi est la garde) ; l'incertitude de la mesure élargit l'intervalle et le prix recommandé, pas P50/P80, les scénarios ni les besoins en matériaux ; aucune calibration de durée n'est appliquée à une estimation déclarée ; les phrases de soumission à gabarit fixe sont à faire valider. **Aucune vision, aucun géospatial.** | [M3-BAREME-MESURE-DECLARES](../architecture/M3-BAREME-MESURE-DECLARES.md) |
| **Filet anti-perte de M2 (SLA, intégrité des données, plan de réparation)** | Quatre outils sans droit d'appareil (agent ou admin) : scan de sept règles SLA, audit de huit contrôles d'intégrité, plan de réparation (actions **proposées**, jamais exécutées ; une action N3 demande l'approbation d'une personne), constat planifié vers M8 (deux mesures, wallboard « ventes et clientèle »). Prouvé sur SQLite, vrais outils, horloge injectée, douze leads fictifs, planificateur et bus réels. **Aucun délai de SLA n'est livré** : `configuration.sla` est vide à dessein, donc chaque règle à délai est « non évaluée » (la mesure des violations non calculable, jamais zéro) tant que Nathan n'a pas déclaré ses sept délais d'heures. M2 n'a ni tâche ni accusé d'envoi : « contacté » et « escaladé » se lisent à la note d'une personne ; « photos demandées » se lit à l'arrivée des photos. Les clients importés à l'onboarding ne sont pas audités. Jamais exercé sur PostgreSQL, sur la boucle réelle du serveur pendant des jours ni sur des données réelles ; le seuil de faux positifs sur de vrais carnets n'est pas mesuré. Une relance préparée mais jamais notée au dossier ne retarde plus la suivante, mais M2 ne sait alors pas qu'elle a eu lieu. | [M2 README](../../departments/m02-revenue-crm/README.md), [M8-ENTREPOT-SOURCES](../architecture/M8-ENTREPOT-SOURCES.md) |
| **Cash libre rafraîchi automatiquement** | **Livré sur SQLite avec horloge injectée, inactif par défaut** : le constat planifié `m5.constat.cash-libre` (variante N2 de l'outil N3 de l'admin) alimente le cash libre, le solde, les comptes à payer et les taxes à remettre de M8, donc la composante « finance » du score de santé (qui reste indéterminée tant que le propriétaire n'a pas déclaré les bornes). Un admin doit le passer en `ombre` puis `actif`. **Fraîcheur** : M8 date le jour d'un constat de M5 à minuit **local** de l'entreprise (correctif D0 : avant, minuit UTC, ce qui périmait les quatre mesures de 19 h à minuit) ; la fenêtre de 24 h est inchangée ; jamais éprouvé sur PostgreSQL ni plusieurs jours en production. | [M5-CASH-LIBRE-PLANIFIE](../../departments/m05-financecore/docs/M5-CASH-LIBRE-PLANIFIE.md) |
| **Qualité des données branchée sur les mesures (QUALITY_FAIL)** | **Livré sur SQLite, données fictives, horloge injectée.** Des règles d'invariants (compte ou montant d'activité négatif, taux hors 0–100, créances de 90 jours et plus au-delà du total, clics au-delà des impressions, total des créances ≠ somme de ses tranches, total de facture ≠ avant taxes + taxes, drapeau de déficit contraire au signe du cash libre) **bloquent** la mesure (non calculable, raison nommée, aucune valeur), la tuile (pastille `QUALITY_FAIL`), le copilote (refus expliqué, aucun chiffre), le score de santé (composante indéterminée) et sont mémorisées par M10 ; la mesure se rétablit quand la source est corrigée. Les pastilles FRESH, STALE, PARTIAL, MISSING, QUALITY_FAIL et GATED sont dérivées des états existants ; **pas de `LIVE`** (aucune source n'est temps réel). **Limites** : seuls les contrôles que les faits reçus permettent (unicité, intégrité référentielle, « le chantier a une adresse » ne sont pas évaluables) ; une valeur plausible mais fausse passe (le bus n'authentifie pas le producteur) ; une règle sur deux mesures bloque les deux ; aucun historique daté des échecs hors de la mémoire de M10 ; jamais éprouvé sur PostgreSQL ni dans un navigateur réel. | [M8-ENTREPOT-SOURCES](../architecture/M8-ENTREPOT-SOURCES.md) §9 ter |
| **Alertes métier de M8** | **Livré sur SQLite, avec horloge injectée ; actif seulement une fois le tour `m8.entrepot` activé par un admin ET des seuils adoptés par la direction.** Huit règles déclaratives (trésorerie, créances de 90 jours et plus, taux d'acceptation, soumissions sans réponse, rupture de matériel, pipeline bas, donnée périmée, qualité en échec) : action d'un gabarit fermé, département propriétaire nommé, jamais de cause ; cycle de vie ouverte / accusée / reportée / résolue dans un registre append-only, UNE alerte par épisode ; proposée à M9 par `m8.alerte_proposee` (extension additive) et lue dans « À voir ». **Aucun seuil n'est livré** (six réglages de direction N3, sans proposition) : sans seuil la règle est « non évaluée » et le dit. **Rien n'est poussé vers un téléphone ni un courriel** (décision du propriétaire, en attente). **Limites** : pas de « baisse de leads » en variation (les comptes sont cumulatifs ; seul le niveau du pipeline est surveillé) ; pas d'écran pour accuser ou reporter (outils d'agent seulement) ; résolution automatique seulement ; pas d'hystérésis ; PostgreSQL non rejoué. | [M8-ENTREPOT-SOURCES](../architecture/M8-ENTREPOT-SOURCES.md) §9 quater |
| **Interconnexion : consentement de suivi, créance, constats contradictoires** | Trois défauts de la revue adverse sont fermés par des événements du catalogue (aucun droit de plus) et **prouvés sur le vrai bus, SQLite et le vrai sas d'envoi, avec le vrai producteur M4 pour le retrait** : le retrait du consentement de suivi (`m4.consentement_suivi_retire`) refuse et neutralise les brouillons de M1 qui ne sont pas partis ; une facture payée ou annulée lève la relance de créance de M2 (`m5.facture_emise_constatee` réutilisé) ; un constat rejoué avec la même clé mais un contenu différent est dit par M2, M5 et M8 (le premier état reste). **Limites** : le retrait vaut à la livraison de l'événement par le répartiteur, pas à l'instant de l'inscription chez M4 (fenêtre non mesurée) ; un message déjà réservé, envoyé ou incertain ne se rappelle pas ; la demande N3 déjà ouverte reste dans le sas (elle ne peut plus s'exécuter, la file de la direction le dit) ; aucun outil n'annule encore une facture client ; la contradiction est rangée et dite, jamais notifiée ni acquittée (M3, M4, M6, M9 gardent l'ancien rejeu silencieux) ; jamais exercé sur PostgreSQL ni sur un écran réel. | [INTERCONNEXION §2, §2 bis, §7](../architecture/INTERCONNEXION.md) |
| **Durée d'un chantier, chantiers de plusieurs jours, fin de chantier avec réserves (M4)** | La cédule de M4 planifie avec la durée sur site de l'estimation M3 du devis (correction apprise comprise, dite), sinon un repli dit, sinon « durée à déclarer » ; un chantier plus long qu'une visite déclarée se découpe en visites d'une même équipe sur des jours distincts ; une fin de chantier à la preuve incomplète passe en attente de revue avec ses réserves et **rien n'est publié (ni facture) avant la revue humaine**. **Prouvé sur le repli exact, SQLite, le vrai bus et les vrais outils M3, M4, M2, M5, M6, avec horloge injectée et données fictives ; PyVRP ne résout pas ces chantiers (absent de la machine) ; au plus 12 visites ; « même équipe » est une règle dure ; l'absence individuelle d'un membre n'entre pas dans la cédule ; ni note ni couleur sur une visite ; M5 ne reçoit pas le motif « coût provisoire » ; le mobile n'a pas de case « réserves » ni de lecture de la journée (P4-03) ; volets matériel et météo simulés dans le scénario ; jamais éprouvé sur PostgreSQL.** | [M3-M4](../architecture/M3-M4-MATHIS-GABRIEL.md), [README M4](../../departments/m04-field-ops/README.md) |
| **Réglages de direction (CFG-1)** | Les seuils de direction de M2 (trois délais, bandes de valeur) et les bornes du score de santé de M8 se décident depuis l'écran « Réglages de direction » (geste N3 du propriétaire, retour arrière, journal chaîné). **Prouvé sur le vrai sas, les vrais outils de M2 et de M8 et le client HTTP de test, sur SQLite et sur un PostgreSQL 17 éphémère (magasin, lecture, geste) ; jamais joué dans un vrai navigateur ni sur un téléphone** (aucun écran mobile). **Aucune valeur réelle n'existe** : tant que Nathan n'adopte rien, M2 reste inerte (« à configurer ») et le score de santé indéterminé, comme avant. Les trois délais proposés pour M2 sont les exemples du manifeste (« recommandation, non validée », jamais calibrés) ; M8 ne propose aucune borne. Pas de péremption des valeurs adoptées, pas de niveau N4, `ponderations_validees_par` non branché, M3/M4 non branchés ; M5 branché pour les trois seuils de son pré-audit (aucune proposition). | [REGLAGES-DIRECTION](../architecture/REGLAGES-DIRECTION.md) §6, §8 |
| **Profil de réception du pack « rénovation extérieure » (M1-A)** | **Livré sur SQLite, tout `a_valider`, rien d'actif tant qu'une personne n'a pas adopté** : le pack propose les questions de qualification des quatre services, le vocabulaire des plaintes et des urgences, les destinataires de transfert (des rôles), la fenêtre de conversation (30 min) et les poids du score (30/50/20, recommandations illustratives) ; `opsys-metier pack adopter ÉLÉMENT --par NOM` les écrit un à un dans `entreprise.yaml`, signé au journal, sans jamais écraser une valeur du propriétaire. Prouvé avec le vrai bus et le vrai M2 sur des SMS fictifs. **Jamais mesuré sur de vrais messages** (corpus fictif de 26 plaintes et 15 demandes ordinaires, écrit par l'auteur du pack) ; l'adoption est un geste de ligne de commande, pas une approbation N3 de la console ; M1 ne pose les questions qu'avec une fenêtre adoptée ; la demande de photos reste fermée tant que la politique photos n'est pas validée ; le budget du client n'est pas proposé. Voir `docs/architecture/PACKS-SECTORIELS.md`. |
| **Bac à sable vocal textuel (M1-D)** | **Politique de dialogue seulement, aucune voix** : des faux appels écrits d'avance exercent des règles (garde-fou en boucle, redemander sur faible confiance, repli sur deux échecs de suite, colère, danger, sujet légal ou financier, messagerie sans personne, transfert avec résumé) sur les vrais morceaux de M1 et la session voix du socle. Aucun audio, VAD, STT, TTS, ligne ou fournisseur ; latence et accent non mesurés ; le canal voix reste « prévu » ; M1.2 reste SIMULE et M1.19 passe d'ABSENT à SIMULE, jamais FAIT_PROUVE. Les seuils (confiance, échecs) sont à décider par Nathan (aucune valeur par défaut), les échecs comptés sont consécutifs (à confirmer), le lexique générique est une proposition, et sans vocabulaire de plaintes adopté ni colère ni danger ne sont reconnus (précondition de tout appel réel). Un seul appel opt-in à un vrai modèle a été fait : il n'a pas dérapé. Voir `docs/architecture/M1-BAC-A-SABLE-VOIX.md`. |
| **Appel manqué complet et messagerie vocale intelligente (M1-C, M1-F)** | **Livré et prouvé sur SQLite, vrai registre, vrai bus, vrai sas N4, données fictives** : brouillon SMS « Nous avons manqué votre appel » préparé à l'import, demande d'envoi N4 avec le texte exact, STOP qui annule, rejeu sans second brouillon, clôture humaine `m1_consigner_contact_reussi` avec `delai_rappel_s` mesuré ; résumé déterministe et extraction bornée nom/téléphone/service/ville/adresse/urgence, tâche de rappel quand le message le demande, confiance faible ou texte non consenti → aucun lead inventé, `audio_ref` = lien seulement. **Limites** : aucun transport SMS/téléphone réel (la livraison n'est jamais prouvée) ; aucun STT réel ni mesure de qualité fr-CA ; extraction lexicale, pas sémantique (formules explicites seulement, faux positifs possibles, adresse sans type de voie non reconnue ; les défauts D1–D9 de la relecture sont corrigés, mais aucun corpus réel fr-CA n'est mesuré) ; **la déduplication STT n'est pas branchée** (`empreinte_requete_stt` et les helpers `rechercher/enregistrer_rejeu_voicemail_stt` existent, aucun chemin réel ne les appelle : deux uploads identiques re-transcrivent et paient à nouveau ; décision de l'architecte sur le coût/consentement) ; l'adresse personnelle n'est pas couverte par la rétention/effacement Loi 25 du registre ; le contact réussi est une déclaration humaine, OPSYS ne passe aucun appel ; aucun envoi automatique, même le brouillon d'appel manqué exige la politique SMS et une approbation N4. Voir [M1-APPEL-MANQUE-VOICEMAIL](../architecture/M1-APPEL-MANQUE-VOICEMAIL.md). |
| **Matériaux M6 : sortie par article, bon de commande commandable, écran « Commandes » (C1-C3)** | **Livré et prouvé sur SQLite, vrai bus, vrai sas, M1 sur double de Gmail, données fictives** (suite du département, scénario d'un seul tenant estimation M3 → PO multi-fournisseurs → courriel M1 → réception → fin de chantier M4 → variance → coût réel M5, mutations). **Le coût de sortie est dit, jamais inventé** : un article sans réception ni prix applicable (même unité) est accepté avec un coût INCONNU et une attente à l'admin, jamais refusé ; un prix du livre sans document est `FALLBACK_PRICE_BOOK`, rien n'est « validé ». **M5 ne lit pas ce coût** : il valorise au livre de prix (tarif, pas prix payé), donc un article sans tarif est « prix non disponible » chez M5 même si M6 en connaît le coût de réception (C14 non fait). Le stock peut devenir négatif par cette voie (achat sur place : il n'entre pas au stock, C6 non fait) : l'admin le voit, rien n'est corrigé seul. **Le PO est commandable mais rien n'est commandé pour de vrai** : aucun fournisseur réel (Gentek, Royal Solution de Bâtiment, O.A.M. et Kaycan n'ont aucune fiche ni courriel fournis : l'écran « Fournisseurs » ne les montre que comme NOMS « à fournir », avec ce qu'il faut leur demander), aucun courriel réel, serveurs de réception « de confiance » non déclarés, politique d'envoi permanente non décidée (`autonome` reste interdit). La quantité à commander n'est PAS arrondie à l'unité de commande (feuille, boîte : règle non déclarée) ; le facteur de perte n'est celui du barème de M3 que si l'estimation a été reçue pour ce devis ; l'unité d'un prix du livre reste facultative (un prix sans unité s'applique mais le PO le dit `prix_unite_confirmee` faux). Un PO d'avant C2 (sans date ni unité) n'est ni approuvé ni envoyé : à annuler et refaire. La prise d'acte de l'envoi exige que M1 rapporte l'empreinte du courriel et son intégrité (changement additif du schéma `m1.commande_courriel_envoyee`) ; un texte modifié au sas laisse l'attente N4. Brouillon de PO et courriel sont maintenant N2 : **le test du core TypeScript `agent-bundle-mcp-runtime.opsys-m6-po-authority.python-http.integration.test.ts` et sa fixture Python figent l'ANCIEN comportement (création N3, PO sans conditions) : non rejoués ici, à re-baseliner en CI du core**. Les seuils de variance et de prix sont des réglages de direction (« recommandation, non validée » : valeurs d'un agent), pas des décisions de Nathan. L'écran « Commandes » n'a été joué que par le client HTTP de test ; aucun écran mobile des commandes ; les réceptions enrichies (substitution, dommage, photo, prix du bon de livraison), l'achat sur place complet, l'apprentissage vers M3 et les ajustements d'inventaire restent à faire. | [README M6](../../departments/m06-material-control/README.md), [M1-M6](../architecture/M1-M6-LEA-ROSALIE.md) §8, [ROLES](../architecture/ROLES.md), [REGLAGES-DIRECTION](../architecture/REGLAGES-DIRECTION.md) |
| **Matériaux M6 : ajustements d'inventaire audités et alertes planifiées (C9-C10)** | **Livré et prouvé sur SQLite, registres durables réels et bus réel, données fictives** : `m6_ajuster_stock` (N3) écrit un mouvement `AJUSTEMENT` hash-chaîné avec motif typé, avant/après exacts, preuve CAS facultative et niveau d'approbation ; au-delà du seuil DÉCLARÉ (ou seuil absent), il exige un admin ou le propriétaire. Un ajustement sur un emplacement nommé écrit aussi le transfert audité qui corrige le lieu. Les maillons antérieurs gardent leur empreinte à l'octet près. Le constat planifié `m6.constat.disponibilite` calcule en plus des alertes neutres (répétitions par article et par équipe déclarée, commande reçue mais stock disparu, déclaration d'usage manquante, réception de PO en retard) : **inactif par défaut**, aucun nom d'employé, aucun prix, aucun texte libre. **Limites** : pas de clôture d'inventaire physique en lot (article par article) ; un transfert refusé n'écrit plus l'ajustement (tout-ou-rien) et un ajustement global qui rendrait `inconnu` négatif est refusé ; la quantité auditée est un `Decimal` exact (l'audit égale le stock réel) ; la fenêtre 1..365 est appliquée au module pur et à la configuration, et borne `commande_recue_stock_disparu` pour les réceptions DATÉES — un maillon de stock sans horodatage (forme historique) reste compté et une entrée `non_evaluees` le dit, donc les registres antérieurs ne sont pas entièrement bornés ; une quantité illisible n'est jamais comptée (règle dépendante `non_evaluees`) ; le seuil d'ajustement est une quantité, pas un montant ; rien n'est poussé à un humain (« À voir » se lit dans l'app) ; seuils, fenêtre et délais fournisseur restent à déclarer par la direction ; aucun test PostgreSQL ni mobile, aucun navigateur réel. | [M6-AJUSTEMENTS-ALERTES](../architecture/M6-AJUSTEMENTS-ALERTES.md), [README M6](../../departments/m06-material-control/README.md) |
| **Matériaux M6 : seuils de variance déclarés (C7) et cycle de vie du PO (C4)** | **Livré et prouvé sur SQLite, vrais outils/registres/bus, client HTTP de test, données fictives** : seuil par matériau, par catégorie déclarée ou global (matériau > catégorie > global), planchers obligatoires en quantité et en dollars (décimal exact, cent, `ROUND_HALF_UP`), édition par l'admin (ou le propriétaire) à l'écran « Seuils matériaux » avec registre append-only chaîné (avant/après, auteur, rôle, motif, version attendue) ; un rapprochement M5 `CONCORDANT` sur un PO reçu propose `invoiced` (N3, jamais appliqué seul), `closed`/`disputed` restent des gestes N3 avec motif, et l'envoi constaté par M1 ne demande plus de second clic N4. **Limites** : aucune valeur réelle (seuils, planchers et table des catégories vides tant que la direction ne les déclare pas ; 0.30/0.15 restent des recommandations d'agent) ; sans valeur unitaire, le plancher en dollars n'est pas évalué et l'écart reste critique ; le prix utilisé est le coût de sortie (réception ou livre), pas le prix payé ; aucune variance de coût ; la chaîne d'audit n'a pas d'ancre externe ; une décision C7 rend le seuil global de CFG-1 inopérant sans fusion des deux journaux ; aucun navigateur réel, aucun mobile, PostgreSQL non rejoué ; `invoiced` reste une proposition, aucune politique permanente de facturation. | [M6-SEUILS-VARIANCE-C7](../architecture/M6-SEUILS-VARIANCE-C7.md), [README M6](../../departments/m06-material-control/README.md) |
| **Radar de risques complété, escalade interne et scénarios chiffrés de M9 (M9-C1, M9-C2)** | Le radar compte 21 règles aux seuils **déclarés par la direction** (neuf réglages `m9.*`, aucune proposition) ; sans seuil, la règle n'est pas évaluée et dit quoi déclarer. Un risque critique crée un avis, une tâche et une trace de mémoire INTERNES (jamais un message externe), et les « et si » sont chiffrés par les moteurs de M5 (Monte-Carlo, achat/crédit-bail), M4 (projection de capacité, ajoutée) et M2 (intervalle), avec leurs reçus rejoués par leur propriétaire ; un moteur absent donne « non chiffré ». Prouvé sur SQLite, vrais outils M1, M2, M4, M5, M7, M8, M10, vrai bus, horloge injectée, données fictives. **Limites** : aucun modèle réel, qualité du conseil non établie ; seuils fictifs, grille de gravité non validée ; **rien ne tourne seul** (ni rafraîchissement, ni escalade : décision de Nathan en attente), aucun écran d'avis, aucune notification, aucun mobile ; aucune règle de prix de fournisseur (aucune lecture exposée) ; M3 et M6 non branchés dans le scénario du mois ; le Monte-Carlo ne modélise aucune corrélation ni vente future, la projection de capacité suppose une demande proportionnelle ; jamais exercé sur PostgreSQL ni sur un écran réel. | [M9-RADAR-SCENARIOS](../architecture/M9-RADAR-SCENARIOS.md) |

## 4. À valider par une avocate ou un avocat

La liste complète et sourcée est dans [QUESTIONS-AVOCAT](../compliance/QUESTIONS-AVOCAT.md). En bref : licences de modèles à seuil de revenu
quand OPSYS-AI génère pour plusieurs PME ; protection d'un logo généré ; seuil de « français nettement prédominant » ; licence du dépôt
lui-même (Apache-2.0 ou propriétaire) ; une dépendance GPL-3.0 (`libsignal`) dans le verrou du core ; LGPL et MPL en dépendance ; plugin
WordPress GPL ; voix, visages et banque de caractéristiques biométriques (déclaration à la CAI) ; politiques Loi 25 (SMS, appels, photos,
suivi GPS, rétention) et ÉFVP avant tout transfert de renseignements personnels hors Québec.

## 5. À valider par un comptable (CPA) ou un professionnel qualifié

- Toutes les valeurs de la base fiscale (aucune n'est approuvée) et les cas de paie contre les outils officiels ; la remise des
  déclarations (TPS/TVQ, retenues) est faite par une personne.
- La frontière de la compilation réservée aux CPA au Québec : le système prépare des brouillons et un dossier pour le CPA, il ne certifie rien.
- Le plan comptable proposé, la correspondance QuickBooks, les provisions, amortissements et jugements comptables.
- Aucune recommandation de placement personnalisée : le système ne donne que de l'information générale. Mention exigée partout :
  « À valider auprès d'un comptable (CPA) / professionnel qualifié ».

## 6. À décider ou à fournir par Nathan

- Fusions, déploiements, passage en production, paiements et achats, données réelles, GitLab : réservés à Nathan (décisions de l'architecte, §8).
- **La cible du premier serveur** : sans elle, aucune qualification de VPS n'est possible.
- Licence du dépôt ; décision sur `libsignal` ; lecture des licences de modèles marquées « à lire » avant toute activation.
- Les décisions et portes ouvertes des matrices, ci-dessous.
- **Le contenu du profil de réception de M1** (corriger puis adopter, un élément à la fois : `opsys-metier pack propositions`, `pack adopter`) et **les seuils du dialogue vocal** (confiance minimale d'une transcription, nombre d'échecs avant repli, échecs consécutifs ou cumulés), avant tout essai réel.
- **Les valeurs des réglages de direction** (écran « Réglages de direction » de la console) : trois délais de M2 (dormance, devis périmé, fréquence des relances) et les bandes de valeur du score de lead ; six couples « pire / cible » du score de santé de M8, six seuils d'alerte métier (`m8.seuil_alerte_*`, sans proposition) trois seuils du pré-audit de M5 et neuf seuils du radar de risques de M9 (sans proposition). Une valeur proposée est une recommandation non validée ; sans votre geste, rien ne s'applique ([REGLAGES-DIRECTION](../architecture/REGLAGES-DIRECTION.md)).

## 7. Ce que disent les matrices

Les matrices d'exigences de `docs/reprise/MATRICES-20261031/` (et celle de M9) datent du 31 octobre 2026 et ne suivent pas toujours les
livraisons des vagues 2 à 4 : la ligne la plus récente de chaque département est dans son document `docs/architecture/`. Les nombres
ci-dessous sont recopiés par un script et vérifiés par un test.

<!-- matrices:debut -->

*Bloc généré par `scripts/docs/synthese_matrices.py --ecrire` ; ne pas le modifier à la main (un test le compare aux matrices).*

### Où en sont les exigences de chaque département

| Code | Département | Exigences | Statuts (matrice) |
|---|---|---:|---|
| M1 | Front Office (Léa) | 20 | FAIT_PROUVE 0 · PARTIEL 18 · SIMULE 2 · ABSENT 0 |
| M2 | Revenue CRM (Victor) | 15 | FAIT_PROUVE 1 · PARTIEL 14 · SIMULE 0 · ABSENT 0 |
| M3 | Estimation (Mathis) | 18 | FAIT_PROUVE 1 · PARTIEL 15 · SIMULE 2 · ABSENT 0 |
| M4 | Field Ops (Gabriel) | 24 | FAIT_PROUVE 2 · PARTIEL 22 · SIMULE 0 · ABSENT 0 |
| M5 | FinanceCore (Sophie) | 18 | FAIT_PROUVE 0 · PARTIEL 18 · SIMULE 0 · ABSENT 0 |
| M6 | Material Control (Rosalie) | 21 | FAIT_PROUVE 0 · PARTIEL 21 · SIMULE 0 · ABSENT 0 |
| M7 | Marketing (Chloé) | 15 | FAIT_PROUVE 0 · PARTIEL 15 · SIMULE 0 · ABSENT 0 |
| M8 | Analytics (Olivier) | 18 | FAIT_PROUVE 0 · PARTIEL 18 · SIMULE 0 · ABSENT 0 |
| M9 | Strategic Intelligence (Athéna) | 28 | DONE_VERIFIED 16 · PARTIEL 11 · PHASE_MOBILE_FINALE 1 |
| M10 | Mémoire (Mnémo) | 20 | FAIT_PROUVE 0 · PARTIEL 20 · SIMULE 0 · ABSENT 0 |

Pour M1 à M8 et M10 : 169 exigences, dont **4** seulement `FAIT_PROUVE`. M9 suit son propre vocabulaire (`DONE_VERIFIED` = prouvé sur les doubles et les parcours du dépôt, pas en production). `PARTIEL` veut dire qu'une partie seulement de la cible est prouvée.

### Capacités qui n'existent que sous forme de double, ou pas du tout

| Exigence | Titre | Statut | Limite (première phrase) |
|---|---|---|---|
| M1.2 | Agent vocal de réception | SIMULE | Statut revérifié le 2026-11-01 sans changement : aucun runtime STT/TTS/SIP/VAD n'existe dans le dépôt ; avatars.CANAUX_REALISES = {messagerie} (la politique refuse tout canal vocal « disponible ») ; phases_voix.py ne fait que consommer des événements fournis … |
| M1.19 | Bac à sable vocal | SIMULE | Bac à sable TEXTUEL seulement (SIMULE, jamais FAIT_PROUVE) : des faux appels écrits d'avance (tours de texte, confiance de transcription injectée, horloge simulée) exercent la POLITIQUE DE DIALOGUE (garde-fou en boucle, redemander sur faible confiance, repli … |
| M3.3 | Pipeline de vision | SIMULE | Contrat du pipeline (photo avec provenance -> candidats avec incertitude, masque, version du modèle), port DetecteurVision, gouvernance (un candidat n'est jamais une mesure : seuil de confiance et tolérance déclarés, mesure de référence ou personne N3), harna… |
| M3.5 | Détection et segmentation (Grounding DINO + SAM2) | SIMULE | Registre des modèles (capacité « vision » du registre de fournisseurs, migration 0049) : Grounding DINO et SAM 2 (pile visée), Florence-2 et OWLv2 (replis), YOLO écarté (AGPL), drapeaux de licence, statut honnête « contrat prêt, aucun modèle qualifié ». |

### Décisions que les matrices attendent de Nathan

**M1 (18)**
- Où publier le formulaire et son récepteur public (M1-canaux §13.7)
- Identifiants des canaux réels
- Validation de la politique d'enregistrement d'appels
- Fournisseur SIP/STT/TTS
- Services, zone, fenêtre de conversation, questions et poids de score du profil d'entreprise
- Validation de la politique photos
- Politique SMS de rappel
- Comptes courriel à brancher
- Validation de la politique de consentement SMS
- Envoi réel T2.1-c
- Vocabulaire des plaintes
- Pseudonymisation des plaintes pour M9 (Loi 25)
- Règle de vérification d'identité du correspondant
- destinataires_transfert du profil d'entreprise
- Garder les utm le temps de la visite (Loi 25)
- Borne de longueur des utm
- Seuil de confiance de transcription et nombre d'échecs avant repli (SeuilsDialogue : aucune valeur par défaut)
- Lexique générique (sujets légal et financier, demande d'une personne, prix, date) et ordre de préséance

**M2 (8)**
- Définition du profil de propriété avec M3 (M3.2) : champs et énumérés initiaux déclarés par M2, à confirmer
- Durée de conservation et procédure d'effacement des propriétés (Loi 25)
- Poids et seuils du scoring : valeurs initiales déclarées par l'architecte (scoring.FACTEURS), à confirmer ; bandes de valeur (configuration.scoring.bandes_valeur_cents) à configurer ; feu vert profilage
- Délais de relance (configuration.relances vide à dessein)
- Politique de consentement SMS en PROPOSITION (validation écrite de Nathan)
- Validation écrite de la politique de consentement et de l'identification de l'expéditeur avant tout envoi réel (hors de ce lot : l'envoi reste au sas courriel N3)
- Seuils dormant_lead et quote_stale (configuration.segments vide à dessein)
- Seuils d'échantillon (20 résolus, 10 convertis, 12 semaines, 20 événements) : valeurs initiales déclarées dans previsions.SEUILS, relevables par l'appelant, à confirmer

**M3 (9)**
- Budgets API géospatiaux
- Validation de la politique photos
- GPU et budgets pour SAM2
- Valeurs réelles des estimateurs par service (coefficients signés, facteurs de conversion, minimum de quantité, temps minimum) : déclarées par le propriétaire, jamais fournies par le code.
- Ouverture éventuelle de m3_calculer_estimation_service aux appareils seller/admin : décision d'architecte (outil aujourd'hui fermé aux appareils).
- Confirmation de l'unité des prix M6
- minimum_rentable_cad, taux et scénarios de prix
- Seuils de validation obligatoire
- Décision 2 : routage du coût certifié

**M4 (4)**
- Décision 6 : calendrier hebdomadaire et conversion des heures d'équipe
- Validation de la politique de géolocalisation
- Décision 2 : routage et qualification du coût certifié
- Décision 3 : déclaration des matériaux par équipe

**M5 (5)**
- Décision build vs intégration (QuickBooks) pour la comptabilité générale
- Confirmation de l'unité des prix M6
- Fréquence de production et fin d'exercice (configuration vide)
- Horizon de prévision (configuration vide)
- Décision 2 : routage du coût certifié

**M6 (4)**
- Déclaration de l'unité des prix
- Autorisation d'envoi des commandes et identité du correspondant
- Décision 3 : déclaration par équipe
- Seuils de réapprovisionnement

**M7 (2)**
- Validation du profil de marque
- Décision 6 : qui saisit les dépenses marketing

**M8 (1)**
- Fenêtres de fraîcheur attendue (décision 6)

**M10 (1)**
- Rétention et effacement par sujet

### Portes encore fermées (gates)

**M1 (9)**
- Identifiants Twilio / SIP / STT réels non fournis (gate DEFINITION §10)
- Politiques Loi 25 (SMS, enregistrement d'appels, photos) : toutes en PROPOSITION, validation écrite de Nathan (T3) non faite
- Politique d'enregistrement d'appels non validée
- Profil d'entreprise (services, zone, vocabulaire, destinataires) vide par défaut : à renseigner par le propriétaire
- Politique photos non contractuelles en PROPOSITION : la demande de photos reste fermée
- Consentement d'enregistrement : politique non validée
- Comptes IMAP de test
- Mécanisme d'identité du correspondant inexistant
- Phase mobile finale (directive du 21 octobre 2026)

**M2 (3)**
- Politique de profilage Loi 25 « à venir » non rédigée : le score n'a aucun effet sur la personne (un humain décide), mais la qualification juridique reste à valider auprès d'un professionnel qualifié
- Politique de consentement SMS en PROPOSITION (validation écrite de Nathan)
- Envoi réel T2.1-c inexistant

**M3 (10)**
- Budgets d'API externes (géocodage, Street View)
- Politique photos non contractuelles : STATUT_VALIDATION = proposition (aucune collecte réelle tant que non valide)
- SAM2 en production sur GPU
- Budgets d'API externes
- Barème, seuils de revue, taux et minimum rentable vides à dessein (configuration M3)
- Coefficients, conversions, minimums de quantité et temps minimums des estimateurs par service non fournis (valeurs de Nathan)
- Intégration de l'estimation composite à m3_estimer_projet (Monte Carlo, plancher, scénarios, registre des estimations, contrat gelé) non faite
- Unité des prix M6 non déclarée
- Coût réel certifié M4→M5 non routé en production
- Cognee en production (non décidé)

**M4 (7)**
- Extra pyvrp absent de l'environnement local
- Fournisseurs de routage payants (Google, Mapbox) : gate Nathan
- Politique de géolocalisation en PROPOSITION
- Rôle client inexistant côté serveur (ROLES.md)
- Notifications SMS via M1 (Twilio)
- Phase mobile reportée à la fin (DEFINITION P14) ; aucun appareil
- Coût certifié M4→M5 non routé en production : service_recalcul_m4.ouvrir / service_lecture_m4.ouvrir lèvent *_NON_QUALIFIE

**M5 (5)**
- Unité des prix M6 non confirmée (réserve REJ-AP-UNITE-PRIX-NON-CONFIRMEE sur tout rapprochement)
- OCR de factures fermé (repli saisie manuelle)
- OAuth QuickBooks / CCube / Stripe / Plaid non fournis (gate DEFINITION §7 M5)
- Validation du CPA requise pour tout ce qui est officiel (calendriers 2025/2026 en A_VALIDER)
- Coût certifié M4→M5 non routé en production (coût partiel / marge inconnue)

**M6 (4)**
- Fournisseurs réels (Gentek, Royal, O.A.M., Kaycan) : gate manuel ; aucun envoi de commande sans politique
- Unité des prix non déclarée (GATE) ; prix en float dans les registres (contrat gelé)
- Politique d'envoi réel des commandes
- Seuils de réapprovisionnement et de variance vides à dessein (configuration M6)

**M7 (4)**
- Validation de la marque par Nathan : profile.yaml est un GABARIT
- OAuth Google Ads / Search Console / GBP / Meta / TikTok / LinkedIn / YouTube non fournis (gates DEFINITION §7 M7)
- Coût certifié M4→M5 non routé en production
- Phase mobile finale (DEFINITION P14)

**M8 (3)**
- Qualification PostgreSQL M8 autorisée mais non rapportée comme terminée (checkpoint M8_PG_global_admission)
- Seuils d'entonnoir/chantier et fenêtres de fraîcheur vides à dessein (configuration M8)
- Phase mobile finale (DEFINITION P14)

**M9 (17)**
- Ports et authenticité des producteurs à qualifier
- Publication M8 de l'historique et de la preuve par mesure (Root, commits séparés)
- Raccord commun : lecture au catalogue et au port privé, consommation par m9_rapprocher_metriques
- Exécution du protocole sur PC1 (verdict COMPLETE attendu)
- Activation réelle sur l'hôte opérateur (non autorisée par cette réponse)
- Ports de simulation métier existants à qualifier
- Prévisions réellement produites par propriétaires
- Source canonique absente : arbitrage retenu par délégation, révisable
- Accès externes autorisés seulement ; repli import/export explicite
- Ports cibles et raccords partagés à intégrer
- Mesures et coûts réellement fournis
- Port M10 et intégration native à qualifier
- Raccord console partagé en commit distinct
- PHASE_MOBILE_FINALE après grandes exigences serveur ; contrat seul ne clôt pas la ligne
- Qualification réelle conseil séparée des doubles de protocole
- Producteurs sans donnée : M7 (dépense), M4 (capacité), M1 (plaintes structurées)
- Qualification par un modèle réel (OUVERTE)

**M10 (4)**
- Cognee en production : non décidé (gate DEFINITION §10)
- Planification native de la consolidation non démarrée (departmental_scheduler runtime_GO:false au checkpoint)
- Politique de rétention et d'effacement par sujet à décider (Loi 25)
- Pilote LightRAG (MIT) derrière le port MoteurGraphe : plan documenté (M10-SOI-GRAPHE.md § 4), NON exécuté ; conditions d'adoption non vérifiées

<!-- matrices:fin -->

## 7 bis. Leçons consommées par M3 et M5 (M10-06, 3 novembre 2026)

- **M3** : `m3_estimer_projet` rend une prévision de quantités de matériaux corrigée par une leçon promue, et
  `m3_prevoir_materiaux_avec_lecons` la relit pour un devis dont l'estimation d'origine est prouvée par son hash exact. La
  correction est une **proposition N4**, jamais appliquée au registre, aux besoins publiés à M6, au prix ni au devis. Le minimum
  d'échantillon est **vide à dessein** dans `department.yaml/configuration/lecons_consommees` : aucune correction n'est proposée
  tant que la direction ne l'a pas déclaré. Le facteur d'écart de matériaux n'est pas ventilé par service, saison, fournisseur ni
  équipe ; tout repose sur des chantiers **fictifs** (seuil de 6), sans modèle réel ni PostgreSQL.
- **M5** : la vue détaillée de `m5_lire_rentabilite_chantier` affiche une marge prévue corrigée par une leçon promue d'écart de
  marge, avec son attribution. La marge de base reste `prix_total - cout_total` du devis accepté ; la correction ne modifie ni le
  devis, ni la marge calculée, ni un prix, et reste une **proposition N4**. Même minimum vide à dessein, mêmes limites de
  données (peu de chantiers fictifs, aucun modèle réel, aucun PostgreSQL). À valider auprès d'un comptable (CPA) / professionnel
  qualifié.
- **M10** : la cible de la leçon d'écart de matériaux reste `m06-material-control` (origine des variances) ; M3 la lit pour la
  prévision sans changer la cible. Si deux leçons applicables existent pour la même clé, la consommation les refuse toutes
  (`plusieurs_lecons_actives`) au lieu d'en choisir une en silence. Rien de tout cela n'a été exécuté avec un vrai modèle, de
  vraies données ni sur PostgreSQL.
- **Unité des leçons d'écart de matériau (corrigé le 4 novembre 2026)** : une nouvelle leçon retient l'unité EXACTE non vide de
  ses observations dans `contenu.unite` et dans son identité (la clé `materiau` ne change pas) ; deux unités du même matériau
  forment deux cohortes et deux leçons. L'évaluation et la surveillance ne comparent que les observations de la même unité.
  La consommation M3 ne corrige que si l'unité de l'entrée et celle de la leçon sont présentes et exactement égales ; une leçon
  d'une autre unité ne masque pas une leçon compatible, et deux leçons valides du même couple (matériau, unité) restent ambiguës
  (`plusieurs_lecons_actives`). Deux unités dans une même entrée restent refusées (`unite_ambigue`). Une leçon historique sans
  unité reste lisible et inchangée, mais elle est non évaluable (`unite_absente`) et non applicable (`unite_lecon_absente`) ;
  aucune migration ni promotion héritée. Aucune conversion ni synonyme (`pi` ≠ `pi2` ≠ `pied`) ; le contrat du bus M6 est
  inchangé. Limites restantes : aucune donnée réelle, aucun PostgreSQL rejoué pour cette correction, et les leçons historiques
  sans unité ne peuvent pas être rattachées automatiquement (il faudrait une nouvelle observation sourcée).
- **Droit aux coûts de la marge corrigée** : le consommateur refuse par défaut de calculer une marge sans `droit_aux_couts`
  explicite (`droit_aux_couts_absent`) ; M5 ne le passe que dans sa vue détaillée déjà autorisée. La politique de qui peut
  voir la marge corrigée, par quels canaux et avec quelle trace reste à trancher par la direction ; aucun écran employé n'a
  été testé avec cette valeur.
- **Arrondi et proposition** : les valeurs corrigées sont arrondies au cent (`ROUND_HALF_UP`, marge) ou à 4 décimales
  (quantité), mais restent des propositions N4 : aucune n'est écrite dans un registre, un devis, un prix ou une marge calculée.

## 7 ter. Estimateurs par service M3 (M3.8b, 3 novembre 2026)

- **M3** : `m3_calculer_estimation_service` compose la quantité d'un service (gouttières, revêtement, soffite/fascia,
  réparation) à partir de mesures déclarées et de coefficients **déclarés** dans `parametres.estimateurs` du barème ;
  aucun prix, taux ni coefficient n'est dans le code. Il rend des coûts min/probable/max au cent (`ROUND_HALF_UP`), un
  prix recommandé seulement si le mode et le taux normal sont déclarés, et un reçu vérifiable par recalcul.
- **Non branché à `m3_estimer_projet`** : le Monte Carlo, le plancher, les scénarios, le registre des estimations et le
  contrat gelé `EstimationV1` restent ceux de la voie mono-mesure. La quantité composée doit encore être déclarée comme
  mesure par une personne avant l'estimation gouvernée ; l'intégration directe est un chantier suivant.
- **Une seule ligne d'ouvrage par service** : les composantes sont agrégées dans l'unité de cette ligne ; des coûts
  unitaires distincts par élément (gouttière, descente, coin) exigeraient plusieurs lignes d'ouvrage, ce que le registre
  interdit encore.
- **Aucune valeur réelle, aucun écran, PostgreSQL non éprouvé** : les estimateurs se déclarent par `m3_declarer_bareme`
  (appareil admin) ; le reçu n'est pas signé (son empreinte détecte une modification interne, pas une réécriture
  cohérente des registres).
- **Facteurs absents** : distance, déplacement, saison, urgence et pertes de main-d'œuvre ne sont pas dans la
  composition ; le modèle de perte reste celui des lignes de matériau (`taux_perte`).

## 7 quater. Transfert enrichi, statut client et métriques de réception (M1-E/G/H, 4 novembre 2026)

- **M1-E** : les champs « informations manquantes » et « prochaine action » sont calculés par les règles de M1 ; le
  profil d'entreprise incomplet les dit `non_evalues`, jamais « manquants ». Les événements `m1.transfert_ouvert` et
  `m1.plainte_ouverte` sont publiés avec un schéma gelé, mais **aucun consommateur M2/M10 n'est livré sur cette
  branche** : les agents de la vague 14 les branchent sur leurs propres branches. Un schéma consommé doit être traité
  comme un contrat : le changer cassera leur lecture.
  Si le lead ne prouve pas que ses signaux couvrent ceux de la conversation, ou si ses champs ne correspondent plus
  au profil actuel, le service et la ville restent non évalués et une vérification du dossier est demandée ; même un
  nouveau message neutre peut entraîner cette vérification. Les faits rappellent alors que le lead est historique.
- **M1-G** : le statut client est prouvé sur SQLite avec le vrai M1, le vrai M2 et le vrai M3 ; les chemins M4 et M5
  sont prouvés avec un port contrôlé et, pour M5, un plan absent (repli). **Aucun vrai client, vrai devis, vraie
  visite, vraie facture, aucun écran client, aucun PostgreSQL.** M5 n'a pas de lecture d'une facture par son seul
  numéro : il faut le `devis_id` qui la porte. M4 ne retrouve une visite que dans ses 10 premières pages de 50
  interventions ; au-delà, repli. La matrice d'abus couvre l'usurpation de vérification, l'énumération de références,
  le niveau insuffisant, le lead ambigu et l'injection dans une référence ; elle ne couvre pas un attaquant qui
  obtiendrait un jeton d'appareil `admin` (hors M1-G).
- **M1-H** : le délai, les appels manqués rappelés et les leads par service/ville sont calculés sur le registre de M1 ;
  **hors zone et photos reçues ne sont pas tracés** et restent `NON_EVALUEE` (jamais zéro). La raison de perte reste à
  M2. Le constat n'est **pas planifié** : aucune mesure de réception n'existe dans le catalogue fermé de M8 ; il
  s'appelle à la demande. Aucun objectif de délai ni cible de rappel n'est fixé : ce sont des réglages de direction
  (CFG-1) non déclarés ici.
- **Arrondis** : les pourcentages sont au centième (`ROUND_HALF_UP`) ; les délais sont des secondes entières. Une
  période sans source rend `null`, jamais 0.

## 7 quinquies. M6 C7/C4 — correction de la revue adverse (3 novembre 2026)

- **Chaîne d'audit retouchée** : elle ne sert plus aucun seuil et l'écran « Seuils matériaux » ne peut pas la réparer.
  L'attente admin et le POST de réparation le disent ; le seul remède est une intervention d'administrateur de base,
  hors outil et tracée. Aucun outil de reconstruction de genèse ni de réécriture de maillon n'est livré.
- **Maillons incomplets en base** : un maillon d'audit sans version lisible est sauté à l'écran (avec un bandeau qui
  compte les entrées ignorées) ; un maillon de rapprochement M5 incomplet est ignoré et compté
  (`rapprochements_recus.compter_ignores`), sans faire tomber la file d'attentes M6. Ces lectures robustes ne
  « réparent » rien : un administrateur de base doit constater et corriger la donnée hors outil.
- **Transitions de PO hostiles** : `bons_commande.lire` rejoue la machine à états et ignore une transition illégale
  rangée hors outil ; elle ne ressuscite pas un PO fermé. Aucun outil ne signale cet événement au-delà de l'état
  inchangé, et PostgreSQL n'a pas été rejoué pour cette correction.
- **Retouche en test** : les maillons durables décodent à chaque accès et n'ont pas de `__setitem__` ; une affectation
  Python (`registre[0][...] = ...`) ne modifie PAS la base. Toute preuve de retouche passe donc par un `UPDATE` SQL
  direct, sinon elle prouve un faux négatif.

## 7 sexies. Retard sur la cédule et replanification M4 (P4-04/P4-05, 4 novembre 2026)

- **Aucune valeur de tolérance n'est livrée.** `configuration.retard_cedule.tolerance_minutes` vaut `null` : sans
  déclaration de la direction (CFG-1, `0..480`, N3), `retards_cedule` est « non évalué » et dit quoi déclarer ; il
  n'écrit jamais « 0 en retard ». 481 est refusé par le calcul et par la lecture CFG-1.
- **Un plan appliqué non daté n'est pas un zéro** : ses interventions sont comptées `sans_date` ; un calendrier civil
  illisible rend `REJ-REGISTRE-INVALIDE`. La clé historique `retard_sur_cedule` n'est plus servie quand le bloc mesure :
  un consommateur doit lire `retards_cedule`.
- **Aucun geste ne déplace un créneau confirmé.** `m4_replanifier_intervention` refuse une `planifiee` à créneau daté
  confirmé ; pour la déplacer, il faut d'abord la reporter (geste distinct), et aucun outil ne promet un nouveau
  créneau au client. Le refus est atomique (point de sauvegarde) ; sur un registre EN MÉMOIRE fourni par un test, la
  transaction durable n'existe pas, donc l'atomicité n'est prouvée que sur le registre adossé à la base.
- **Non rejoué sur PostgreSQL, ni sur un appareil réel** : la preuve P4-04/P4-05 est SQLite, données fictives, horloge
  injectée. Le mobile n'a pas d'écran « retards » dédié ; la replanification reste un outil admin N3, pas un parcours
  d'appareil.

## 7 septies. État de la vérification de la vague 14 (4 novembre 2026)

- **Relecture adverse par un autre modèle** : faite pour M1-F (muse), M3 estimateurs (muse), M4 P4-04/05 (deepseek), M6 C7/C4 et C9/C10 (muse) et M5→M8 C5 (Gemini Flex) ; les défauts prouvés ont été corrigés. **Pas faite** pour M1-E/M1-G/M1-H (livraison de la vague 14) : M1-G, qui décide ce qu'un client voit de son dossier après vérification d'identité, a des tests d'abus (usurpation, énumération, niveau insuffisant) et 83 mutants tués sur 83, mais aucun autre modèle ne l'a attaquée.
- **Corrections reprises sans rapport d'agent** : le budget de la clé LiteLLM d'essai a été épuisé pendant les corrections de M4, M6 (deux fois) et M8 ; leurs dossiers ont été repris tels quels et revérifiés par exécution (départements complets, suite du socle, balayages de mutation indépendants des modules nouveaux). Deux défauts introduits par ces corrections ont été trouvés et corrigés à l'intégration (garde « instant avec fuseau » inversée dans les alertes M6 ; fraîcheur de l'écart M8 prise sur des faits historiques).
- **Non intégré** : les prévisions financières à 6/12/24 mois de M5 (branche locale `claude/ds-w14-m5`, ~2 600 lignes, tests de l'agent verts, mutations et relecture adverse non faites) et la tâche M10 (consolidation nocturne, mémoire des plaintes, audit non-oubli) n'ont pas pu être menées à terme.
- **Mutations** : balayages ciblés par module (tests du module), pas la suite entière par mutant ; les survivants jugés équivalents l'ont été avec un exemple d'entrée, jamais par principe.

## 8. Écarts de documentation connus et non corrigés

- Les décisions d'architecture (ADR) 0002, 0006, 0007 et 0008 citent `core/UPSTREAM.md` et un outil `scripts/tally.py` qui n'existent pas dans ce
  dépôt. Les ADR sont des archives de décision : rien n'a été modifié.
- Beaucoup de rapports historiques (`docs/grs/`, `docs/programme/`, `docs/research/`) renvoient à des preuves rangées hors du dépôt
  (`/workspace/...`) : leurs liens sont cassés par construction et sont listés dans `docs/utilisation/liens-historiques-connus.json`.
- En mode `autonome`, la politique de code (`src/opsys/politiques.py`) n'exige l'approbation qu'à partir de N5, alors que les décisions de
  l'architecte (r1, §1) parlent de validation obligatoire de N3 à N5. Le défaut est `ombre` (N3 et plus approuvés) ; **ne pas passer un
  département en `autonome` avant d'avoir tranché**.
- Le catalogue de fournisseurs déclare 21 lignes « vérifiées » dont la source ne porte pas de preuve primaire : voir le
  [registre des licences](../compliance/REGISTRE-FOURNISSEURS-LICENCES.md).
