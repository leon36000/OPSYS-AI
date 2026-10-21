# BRIEF COMMUN — Recherche de briques open source pour OPSYS-AI (sept. 2026)

## Produit
OPSYS-AI (ex-« GRS ») = « core d'entreprise autonome clé en main » pour PME. Client 1 : entreprise de
rénovation extérieure au Québec (FR, CAD, TPS/TVQ, Loi 25 vie privée). Ensuite SaaS/licence pour PME QC.
10 départements (« organes ») pilotés par des agents IA :
- M1 Front Office : réception omnicanale (appels voix, SMS, courriel, chat web, WhatsApp), qualification, interdits absolus, digest.
- M2 Revenue CRM : Client 360, pipeline, scoring, relances, anti-doublons, SLA, readiness vers M3.
- M3 Estimation : vision sur photos (mesures, échelle), prix plancher, Monte Carlo, estimé-vs-réel ; prix bloqué sans référence d'échelle.
- M4 Field Ops : cédule/VRP, météo, GPS, pointage, « Work Completion Trigger » vers M5/M6/M2/M7/M8/M10.
- M5 FinanceCore : compta, banque (lecture seule → dry-run → écriture approuvée), taxes QC, prévisions 5 ans, états financiers.
- M6 Material Control : catalogue, bons de commande, stock localisé, écarts, réapprovisionnement.
- M7 Marketing : CMO IA, SEO/GEO/AEO, site, Google Business Profile, réseaux sociaux (Postiz), réputation/avis, pub (lecture), Matomo/UTM, contenu.
- M8 Analytics : métriques-as-code, DuckDB/Parquet, XmR, dashboards, MMM.
- M9 Strategic Intelligence : conseil stratégique multi-agents, scénarios, veille, décision.
- M10 Mémoire : mémoire d'entreprise, PREFLIGHT/POSTFLIGHT des agents, journal de décisions.

## Exigences dures du propriétaire
1. Installable sur un VPS (mono-nœud, docker compose, script d'installation).
2. Dashboard pour TOUT gérer/configurer, dont connecter les modèles nécessaires, cloud ou locaux.
3. Économie de tokens maximale (routage, cache, compression, budgets…).
4. Core basé sur le code source d'un agent open source mature : candidats OpenClaw (« openclaw2 ») ou Hermes Agent (NousResearch) — fork/vendorisation assumés, lourdes modifications acceptées.
5. Mémoire exceptionnelle : RAG premium obligatoire (une doc de conception est le prérequis).
6. Chaque département octroie aux agents les capacités requises pour exceller.
7. Réutiliser au maximum GitHub/GitLab/bibliothèques open source matures : les briques sont des INGRÉDIENTS à adapter/fusionner/homogénéiser, pas à empiler.
Code existant : Python 3.12 (règles métier des 10 modules, ~24k LOC + ~41k LOC de tests), PostgreSQL (psycopg).

## Contraintes de licence (produit commercial)
MIT/Apache-2.0/BSD/MPL = OK. LGPL = OK en dépendance dynamique. GPL/AGPL = seulement comme service séparé
non modifié derrière une frontière réseau (sinon obligation de publier le code) → à signaler clairement.
Licences « source-available »/BSL/Elastic/Sustainable Use = à signaler comme risque.

## Règles de recherche
- Faits vérifiés sur sources (fichier LICENSE du repo, README, docs officielles, API GitHub : https://api.github.com/repos/OWNER/REPO donne stars, pushed_at, license). Jamais de mémoire non vérifiée : marquer « NON VÉRIFIÉ » sinon.
- Outils : WebSearch, WebFetch, curl (api.github.com, raw.githubusercontent.com), git clone --depth 1 dans <scratchpad>/clones/ si inspection de code nécessaire.
- NE JAMAIS modifier /home/user/OPSYS-AI (lecture seule autorisée).
- Pour chaque brique : nom, URL, licence (vérifiée), langage, maturité (stars, dernier push/release), apport concret pour OPSYS, mode d'intégration (source vendorisée / dépendance pip / service sidecar docker / serveur MCP / simple patron), effort d'adaptation (S/M/L), risques.
- Conclure par « INGRÉDIENTS RETENUS » classés + « RECETTE » : comment les adapter/fusionner dans OPSYS (Python-first, docker compose VPS, dashboard central, économie de tokens).

## Livrable
1. Rapport COMPLET (markdown, sources en liens) écrit dans le fichier indiqué dans ta mission.
2. Réponse finale ≤ 400 mots : recommandations clés + chemin du rapport. Termine par `PREUVE:` (sources principales) ou `BLOCKED:`.
