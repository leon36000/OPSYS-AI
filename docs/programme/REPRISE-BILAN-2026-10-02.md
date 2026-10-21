# Reprise du 2 octobre 2026 — bilan R22

Suite qualifiée : [bilan R23 — préparation CSV en une action](REPRISE-PREPARATEUR-BILAN-R23.md).
Le présent bilan conserve la portée historique de R22.

Le prompt récupéré est conservé à l’identique dans le [registre des directives](../produit/DIRECTIVES-NATHAN.md). La base Git reste `2e56c0d5605dfe575bde9244f38924d5390f2674`, sur `codex/restructuration-2026-09-30`, avec ses modifications locales préexistantes. L’analyse historique des commits Claude reste celle de [R21](../research/R21-2026-10-02/README.md) : les noms et messages Git ne permettent pas d’authentifier le modèle qui a produit le code. L’autre checkout n’a pas été modifié.

## Capacités livrées et limites

| Tranche | Résultat local vérifié | Limite actuelle |
|---|---|---|
| Connecteurs STT M1 | Configuration durable, références de secrets, révision concurrente, historique et diagnostic manuel borné | Aucun audio envoyé au diagnostic; fournisseur réel, qualité fr-CA et production vocale non qualifiés |
| Fusion CSV M5/M10 | Upload privé, chiffrement AES-GCM, préparation durable par tranches, reprise, déduplication, quotas et provenance documentaire | Pilote SQLite; traitement encore manuel par tranche dans R22; ni comptabilisation ni paiement |
| C02 : création de devis M3 | Ticket lié aux arguments finaux, au lead M2 et au contexte M10 actif; parcours HTTP MCP réel local | C02 reste partiel pour les autres outils; un ticket ne certifie pas la provenance des coûts |
| Trace de calibration M3 | Attributs exacts du barème et du calcul de durée conservés dans une trace versionnée | Sémantique de temps `non_qualifiee`; aucune calibration apprise ni amélioration empirique revendiquée |

Guides : [STT](../architecture/CONNECTEURS-STT.md), [Fusion CSV](../architecture/FUSION-CSV.md), [C02](LOT-C02-CREATION-DEVIS-M3.md), [calibration](CALIBRATION-TEMPS-PREPARATION.md). Les migrations `0016` et `0017` prolongent la chaîne existante. Le pilote CSV réutilise le parseur M5 et ajoute le genre documentaire M10 `m5.releve_bancaire_csv`; il ne crée pas une affaire fictive pour représenter un document.

`cryptography==50.0.2` est l’unique brique cryptographique ajoutée à l’extra optionnel `ingestion`. Le hash du wheel a été comparé au verrou; les notices Apache/BSD et celles de ses dépendances sont conservées. Les clés restent dans l’environnement sous référence, jamais dans les tables ou les preuves. La rotation de référence exige de conserver les anciennes clés pour relire les anciens lots.

## Qualification indépendante ROOT

La campagne Python finale s’est déroulée du **2 octobre 2026, 03:35:39 au 03:37:04 UTC** : **467 tests, zéro échec, erreur ou skip**, durée JUnit 82,830 s. Les **1 092 sources sélectionnées** sont identiques avant/après. Ce total comprend les 19 cas Fusion, les 16 E2E de clôture de chantier et un parcours HTTP MCP de création de devis avec le client officiel et un serveur local. Ce dernier n’est pas un appel LLM réel du Gateway.

La campagne Core finale qualifie séparément **405 tests dans neuf fichiers**, zéro échec, erreur ou skip, avec **35 209 empreintes sélectionnées** identiques avant/après. Ce périmètre comprend les sources/configurations Core retenues par le harnais et quelques métadonnées générées déjà présentes; il ne correspond pas à une compilation générale du dépôt. Oxlint sur les quatre fichiers Core concernés, Ruff sur les 24 fichiers Python concernés, `uv lock --check --offline`, le catalogue et `git diff --check` passent. Le catalogue déclare 10 départements, 207 outils et 116 capacités d’appareils; ces déclarations ne prouvent pas leur exécution externe.

Les [preuves R22](../research/R22-2026-10-02/README.md) conservent commandes, dates, logs, XML, empreintes et campagnes rouges. Les campagnes intermédiaires de 151 cas STT, les répétitions Python et les résultats auteurs ne s’ajoutent pas aux comptes finaux. Les cas PostgreSQL sont explicitement exclus de cette campagne.

La revue ROOT a fait corriger des défauts concrets : contournement CSRF par JSON sur un formulaire HTML, entrées non bornées, fermeture des uploads, attribution de l’acteur d’audit, reparsage à chaque tranche, chaîne documentaire multi-lots et lectures M2/M10 sans contrôle d’intégrité. Les empreintes de chaîne détectent les altérations incohérentes; elles ne protègent pas contre un opérateur privilégié qui réécrit toute une chaîne cohérente.

Les préimages initiales complètes du premier patch CSV n’ont pas été capturées. Les préimages des reprises suivantes et la comparaison d’empreintes ROOT entre la fin STT et l’intégration sont conservées; elles ne remplacent pas cette préimage manquante. Certains noms de premiers logs auteurs contiennent une heure construite manuellement : leurs noms ne sont pas des preuves d’heure d’exécution.

## Limites qui restent ouvertes

PostgreSQL refuse explicitement le pilote CSV avec `STOCKAGE_NON_QUALIFIE`. Une tentative auteur de fixture PostgreSQL a échoué pendant `initdb` faute d’espace disque; elle ne qualifie pas ce backend. Aucun nouveau démarrage Docker n’a été lancé ensuite. Les limites de stockage du pilote sont 64 lots et 64 MiB de ciphertext binaire, hors surcoût base64 et métadonnées; la politique de purge gouvernée reste à construire.

Les avatars 3D, la voix fr-CA réelle, les mesures géospatiales, l’apprentissage sur des chantiers réels, le rappel mémoire longitudinal et l’installation VPS de bout en bout ne sont pas qualifiés par R22. La recherche Pipecat/LiveKit/Audio2Face/TalkingHead reste une sélection documentaire : code, modèles, actifs et services ont des licences et prérequis distincts. Aucun de ces composants n’a été intégré par ce lot.

La matrice conserve les statuts partiels des départements et les 47 constats historiques. Aucun module complet, autonomie générale ou pourcentage de complétion globale n’est annoncé. Aucun commit, push, merge, déploiement ou action financière/publique réelle n’a été effectué.

## Suite engagée

La tranche CSV en une action privée a été qualifiée ensuite dans [R23](REPRISE-PREPARATEUR-BILAN-R23.md) : vingt transactions maximum, budget coopératif entre tranches et reprise du même lot. Elle ne faisait pas partie de R22 et ne constitue pas un worker d'arrière-plan. Le [plan](REPRISE-PLAN-2026-10-02.md) conserve les lots de connecteurs, mémoire premium, ingestion multi-format, autonomie et apprentissage mesuré, avec leurs critères de sortie propres.
