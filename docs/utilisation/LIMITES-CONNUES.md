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
| **Ingestion massive** | Aucun modèle de lecture de factures raccordé ; Docling non installé ; PostgreSQL/DBOS non faits ; apprentissage du profil et choix automatique du pack non faits. | [INGESTION-ONBOARDING](../architecture/INGESTION-ONBOARDING.md) §9 |
| **Connaissances et recherche (M10)** | Aucun vrai modèle d'embeddings ni de reranker mesuré ; contenu fiscal, comptable ou juridique réel absent ; corpus de mesure fictif. | [CONNAISSANCES](../architecture/CONNAISSANCES.md) §13 |
| **Observabilité et registre MCP** | Jamais testés contre un vrai Langfuse, un vrai Presidio ni le Core. **Les installateurs ne posent pas** `OPSYS_MCP_REGISTRE` ni `OPSYS_TRACES` : sans ces variables, rien n'est vérifié. | [OBSERVABILITE-MCP](../architecture/OBSERVABILITE-MCP.md) §8 |
| **Application mobile** | Les tests Jest ne prouvent ni le rendu sur téléphone ni le pont natif ; aucun test sur téléphone ou émulateur. Les parcours d'appareil sont rejoués par un harnais Python, pas par le Core natif. | [MOBILE](../architecture/MOBILE.md), matrices |
| **Concurrence et charge** | Prouvées pour des fils d'un seul processus sur SQLite ; aucun essai multi-machines, aucune mesure sous charge. | CABLAGE §11 |
| **Rétention et effacement (Loi 25)** | **Livré sur doubles et sur SQLite, inactif par défaut** : purge du courriel d'ingestion, adresse des courriels reçus par M1 (clé détruite), enregistrements vocaux (aucun worker n'en produit), traces. La première activation exige l'aperçu à blanc et la validation d'un admin. **Non couvert** : le texte neutralisé et le contact du lead dans le registre de M1, les lignes écrites avant le changement, les sauvegardes et exports existants, l'effacement d'une propriété ou d'une identité (M2). | [PLANIFICATION](../architecture/PLANIFICATION.md) §5, [M2](../architecture/M2-VICTOR.md) §8 |
| **Planification autonome** | Treize tours de plus au planificateur durable (M8, M5, M10, M7 signaux/veille/studio, vérification des sauvegardes, péremptions, rétention) : prouvés sur doubles, inactifs par défaut. Signaux, veille, générateurs d'images, embeddings : **aucun transport réel**, ils disent « en attente de transport ». Aucune alerte n'est poussée à un humain en cas d'échec ; la console le montre seulement. **Neuf constats pour M8** (M1, M2 ×2 dont le filet anti-perte, M4, M5 ×3 dont le cash libre, M6, M7) sont déclarés par les manifestes des départements et déclenchés par le même planificateur (cadence dérivée du catalogue de M8, `ombre` ne publie rien) : prouvés avec horloge injectée sur SQLite puis sur PostgreSQL 17 réel (rejeux et vrais processus : créneau, bail, idempotence, deuxième instance, SIGKILL), **inactifs par défaut**, jamais sur la boucle réelle pendant des jours. | [PLANIFICATION](../architecture/PLANIFICATION.md) §9. **Sept routines de plus pour M1 et M10** (digest quotidien et alertes internes de la réception — rappel échu, conversation sans suivi, urgence non prise en charge —, consolidation nocturne des affaires par un énumérateur déterministe, audit « non-oubli » hebdomadaire, KPI des deux manifestes) : déclarées par les manifestes, inactives par défaut, prouvées sur SQLite avec horloge injectée, vrai bus et données fictives ; **rien ne pousse une alerte vers un téléphone ou un courriel** (« À voir » se lit dans l'app), aucun accusé de réception n'est envoyé au client, un jour de consolidation manqué n'est pas rattrapé (l'audit le dit), trois KPI de M10/M1 sur sept sont dits non calculables faute de source. `m10_consolider_affaire` est passé de N3 à N2. |
| **Marque v2, score de conformité, rapport hebdomadaire et mémoire marketing de M7** | Prouvés sur SQLite, vrai bus, vrais outils (M7, M8, M10), planificateur à horloge injectée et données fictives (2 novembre 2026) ; **jamais sur PostgreSQL, ni contre un service externe, ni avec une publication réelle** (la publication reste un geste humain, aucun modèle de langage n'écrit ni ne note). **Le profil réel de la marque n'existe pas : Nathan doit déclarer puis valider ses énoncés** (promesse, mots et messages interdits, voix, mentions) ; sans eux, les dimensions de conformité qui en dépendent sont « non évaluables » et seule la porte binaire du socle s'applique. Un motif ne comprend pas le sens (un mot interdit cité pour être nié est refusé), un énoncé non validé n'est vu que cité mot pour mot, les gabarits du code sont au vouvoiement. **Le rapport hebdomadaire est un exécuteur inactif par défaut** : tant qu'un admin ne l'active pas, aucun rapport n'existe ; il n'affiche aucun ROI calculé (la finance reste à M5) ; « leads par contenu » est cumulatif depuis l'export (M8 n'a pas de fenêtre) ; le coût par lead exige la correspondance des canaux et des relevés de dépense ; les tâches n'ont pas d'outil de clôture. Les leçons marketing exigent trois semaines distinctes et une décision humaine ; le signal d'objection vient des catégories d'avis, pas de leur texte. `m7_proposer_contenu` (fabrique historique) n'applique pas la porte v2. | [M7-MARQUE-RAPPORT](../architecture/M7-MARQUE-RAPPORT.md) §8 |
| **Entrepôt analytique de M8 (interdépartements)** | 40 mesures de plus (58 au catalogue fermé) alimentées par les constats de M1, M2, M3, M4, M5, M6 et M7 par le bus : prouvées sur le vrai bus et SQLite avec des **charges conformes au catalogue** (chaque outil de constat est prouvé dans la suite de son département ; un scénario les enchaîne via le planificateur, sur SQLite et rejoué sur PostgreSQL 17 réel depuis la vague 8), jamais sur un écran réel. **La dépense publicitaire relevée n'est que la somme des relevés reçus** ; son écart avec la dépense comptabilisée par M5 (D1) est un écart de DÉFINITION (relevés HORS_TAXES seulement, brouillons non validés dits). **Les neuf constats de la phase 2 (M5 ×3, M7, M4, M2 ×2, M6, M1) sont déclenchés par le planificateur durable, mais seulement une fois qu'un admin les a activés (inactifs par défaut)** : tant qu'ils ne le sont pas, une mesure reste non calculable puis périmée. La péremption des mesures de M7 et des factures suit l'âge du fait sous-jacent, pas celui du constat ; « clics, impressions, visites du site » sont cumulatifs depuis le premier résumé. Le coût par lead n'existe qu'avec la correspondance `canaux_marketing` déclarée par le propriétaire. Coût réel de M5 chez M8 : **non** (D4). Le bus n'authentifie pas le producteur d'un événement. Une valeur à couverture partielle le dit en texte, pas dans une colonne. | [M8-ENTREPOT-SOURCES](../architecture/M8-ENTREPOT-SOURCES.md) |
| **Barème et mesure déclarés de M3 (M3-C1, M3-C2)** | Le barème, la quantité, le plancher rentable et les taux de marge d'une estimation viennent maintenant d'un barème **déclaré** par une personne (versionné, chaîné, en vigueur) et d'une mesure **déclarée** (valeur, bornes, méthode, confiance, pièces) : un agent qui passe un barème libre est refusé, sans référence aussi, avec ce qu'il faut déclarer. Prouvé en processus Python sur SQLite avec les vrais outils, l'horloge injectée et des **valeurs fictives**. **Limites** : **aucune valeur réelle** (le barème de Nathan n'est pas dans le dépôt : sans lui M3 ne chiffre rien) ; **aucun écran** pour déclarer un barème ou une mesure (appareil `admin`/`seller` apparié, ou le futur écran des réglages de direction) ; jamais exercé sur PostgreSQL ni sur un appareil réel ; l'auteur repose sur l'identité d'appareil d'OPSYS-CORE ou la session de console, revérifiée en base mais non établie par M3 ; la chaîne n'a pas d'ancre externe ; la voie d'essai (variable d'environnement du serveur `OPSYS_M3_VOIE_LIBRE`) ne doit jamais être posée en production et rien ne le vérifie au démarrage ; **`m3_creer_devis` reste libre** (coûts de lignes et taux d'un devis viennent de l'appelant, la revue N4 de l'envoi est la garde) ; l'incertitude de la mesure élargit l'intervalle et le prix recommandé, pas P50/P80, les scénarios ni les besoins en matériaux ; aucune calibration de durée n'est appliquée à une estimation déclarée ; les phrases de soumission à gabarit fixe sont à faire valider. **Aucune vision, aucun géospatial.** | [M3-BAREME-MESURE-DECLARES](../architecture/M3-BAREME-MESURE-DECLARES.md) |
| **Filet anti-perte de M2 (SLA, intégrité des données, plan de réparation)** | Quatre outils sans droit d'appareil (agent ou admin) : scan de sept règles SLA, audit de huit contrôles d'intégrité, plan de réparation (actions **proposées**, jamais exécutées ; une action N3 demande l'approbation d'une personne), constat planifié vers M8 (deux mesures, wallboard « ventes et clientèle »). Prouvé sur SQLite, vrais outils, horloge injectée, douze leads fictifs, planificateur et bus réels. **Aucun délai de SLA n'est livré** : `configuration.sla` est vide à dessein, donc chaque règle à délai est « non évaluée » (la mesure des violations non calculable, jamais zéro) tant que Nathan n'a pas déclaré ses sept délais d'heures. M2 n'a ni tâche ni accusé d'envoi : « contacté » et « escaladé » se lisent à la note d'une personne ; « photos demandées » se lit à l'arrivée des photos. Les clients importés à l'onboarding ne sont pas audités. Jamais exercé sur PostgreSQL, sur la boucle réelle du serveur pendant des jours ni sur des données réelles ; le seuil de faux positifs sur de vrais carnets n'est pas mesuré. Une relance préparée mais jamais notée au dossier ne retarde plus la suivante, mais M2 ne sait alors pas qu'elle a eu lieu. | [M2 README](../../departments/m02-revenue-crm/README.md), [M8-ENTREPOT-SOURCES](../architecture/M8-ENTREPOT-SOURCES.md) |
| **Cash libre rafraîchi automatiquement** | **Livré sur SQLite avec horloge injectée, inactif par défaut** : le constat planifié `m5.constat.cash-libre` (variante N2 de l'outil N3 de l'admin) alimente le cash libre, le solde, les comptes à payer et les taxes à remettre de M8, donc la composante « finance » du score de santé (qui reste indéterminée tant que le propriétaire n'a pas déclaré les bornes). Un admin doit le passer en `ombre` puis `actif`. **Fraîcheur** : M8 date le jour d'un constat de M5 à minuit **local** de l'entreprise (correctif D0 : avant, minuit UTC, ce qui périmait les quatre mesures de 19 h à minuit) ; la fenêtre de 24 h est inchangée ; jamais éprouvé sur PostgreSQL ni plusieurs jours en production. | [M5-CASH-LIBRE-PLANIFIE](../../departments/m05-financecore/docs/M5-CASH-LIBRE-PLANIFIE.md) |
| **Interconnexion : consentement de suivi, créance, constats contradictoires** | Trois défauts de la revue adverse sont fermés par des événements du catalogue (aucun droit de plus) et **prouvés sur le vrai bus, SQLite et le vrai sas d'envoi, avec le vrai producteur M4 pour le retrait** : le retrait du consentement de suivi (`m4.consentement_suivi_retire`) refuse et neutralise les brouillons de M1 qui ne sont pas partis ; une facture payée ou annulée lève la relance de créance de M2 (`m5.facture_emise_constatee` réutilisé) ; un constat rejoué avec la même clé mais un contenu différent est dit par M2, M5 et M8 (le premier état reste). **Limites** : le retrait vaut à la livraison de l'événement par le répartiteur, pas à l'instant de l'inscription chez M4 (fenêtre non mesurée) ; un message déjà réservé, envoyé ou incertain ne se rappelle pas ; la demande N3 déjà ouverte reste dans le sas (elle ne peut plus s'exécuter, la file de la direction le dit) ; aucun outil n'annule encore une facture client ; la contradiction est rangée et dite, jamais notifiée ni acquittée (M3, M4, M6, M9 gardent l'ancien rejeu silencieux) ; jamais exercé sur PostgreSQL ni sur un écran réel. | [INTERCONNEXION §2, §2 bis, §7](../architecture/INTERCONNEXION.md) |
| **Réglages de direction (CFG-1)** | Les seuils de direction de M2 (trois délais, bandes de valeur) et les bornes du score de santé de M8 se décident depuis l'écran « Réglages de direction » (geste N3 du propriétaire, retour arrière, journal chaîné). **Prouvé sur le vrai sas, les vrais outils de M2 et de M8 et le client HTTP de test, sur SQLite et sur un PostgreSQL 17 éphémère (magasin, lecture, geste) ; jamais joué dans un vrai navigateur ni sur un téléphone** (aucun écran mobile). **Aucune valeur réelle n'existe** : tant que Nathan n'adopte rien, M2 reste inerte (« à configurer ») et le score de santé indéterminé, comme avant. Les trois délais proposés pour M2 sont les exemples du manifeste (« recommandation, non validée », jamais calibrés) ; M8 ne propose aucune borne. Pas de péremption des valeurs adoptées, pas de niveau N4, `ponderations_validees_par` non branché, M3/M4/M5 non branchés. | [REGLAGES-DIRECTION](../architecture/REGLAGES-DIRECTION.md) §6, §8 |

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
- **Les valeurs des réglages de direction** (écran « Réglages de direction » de la console) : trois délais de M2 (dormance, devis périmé, fréquence des relances) et les bandes de valeur du score de lead ; six couples « pire / cible » du score de santé de M8. Une valeur proposée est une recommandation non validée ; sans votre geste, rien ne s'applique ([REGLAGES-DIRECTION](../architecture/REGLAGES-DIRECTION.md)).

## 7. Ce que disent les matrices

Les matrices d'exigences de `docs/reprise/MATRICES-20261031/` (et celle de M9) datent du 31 octobre 2026 et ne suivent pas toujours les
livraisons des vagues 2 à 4 : la ligne la plus récente de chaque département est dans son document `docs/architecture/`. Les nombres
ci-dessous sont recopiés par un script et vérifiés par un test.

<!-- matrices:debut -->

*Bloc généré par `scripts/docs/synthese_matrices.py --ecrire` ; ne pas le modifier à la main (un test le compare aux matrices).*

### Où en sont les exigences de chaque département

| Code | Département | Exigences | Statuts (matrice) |
|---|---|---:|---|
| M1 | Front Office (Léa) | 20 | FAIT_PROUVE 0 · PARTIEL 18 · SIMULE 1 · ABSENT 1 |
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
| M1.19 | Bac à sable vocal | ABSENT | Aucun faux appel ni pipeline STT/TTS : seule la machine à états des phases (cf. M1.2) est testée. |
| M3.3 | Pipeline de vision | SIMULE | Contrat du pipeline (photo avec provenance -> candidats avec incertitude, masque, version du modèle), port DetecteurVision, gouvernance (un candidat n'est jamais une mesure : seuil de confiance et tolérance déclarés, mesure de référence ou personne N3), harna… |
| M3.5 | Détection et segmentation (Grounding DINO + SAM2) | SIMULE | Registre des modèles (capacité « vision » du registre de fournisseurs, migration 0049) : Grounding DINO et SAM 2 (pile visée), Florence-2 et OWLv2 (replis), YOLO écarté (AGPL), drapeaux de licence, statut honnête « contrat prêt, aucun modèle qualifié ». |

### Décisions que les matrices attendent de Nathan

**M1 (16)**
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

**M2 (8)**
- Définition du profil de propriété avec M3 (M3.2) : champs et énumérés initiaux déclarés par M2, à confirmer
- Durée de conservation et procédure d'effacement des propriétés (Loi 25)
- Poids et seuils du scoring : valeurs initiales déclarées par l'architecte (scoring.FACTEURS), à confirmer ; bandes de valeur (configuration.scoring.bandes_valeur_cents) à configurer ; feu vert profilage
- Délais de relance (configuration.relances vide à dessein)
- Politique de consentement SMS en PROPOSITION (validation écrite de Nathan)
- Validation écrite de la politique de consentement et de l'identification de l'expéditeur avant tout envoi réel (hors de ce lot : l'envoi reste au sas courriel N3)
- Seuils dormant_lead et quote_stale (configuration.segments vide à dessein)
- Seuils d'échantillon (20 résolus, 10 convertis, 12 semaines, 20 événements) : valeurs initiales déclarées dans previsions.SEUILS, relevables par l'appelant, à confirmer

**M3 (7)**
- Budgets API géospatiaux
- Validation de la politique photos
- GPU et budgets pour SAM2
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

**M3 (8)**
- Budgets d'API externes (géocodage, Street View)
- Politique photos non contractuelles : STATUT_VALIDATION = proposition (aucune collecte réelle tant que non valide)
- SAM2 en production sur GPU
- Budgets d'API externes
- Barème, seuils de revue, taux et minimum rentable vides à dessein (configuration M3)
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
