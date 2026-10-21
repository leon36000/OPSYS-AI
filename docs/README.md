# Documentation OPSYS-AI — points d'entrée actuels

Mise à jour : 1er octobre 2026. Les documents historiques restent disponibles ; les directives
actuelles, la définition et les preuves du périmètre concerné déterminent la suite du travail.
Une vérification locale peut identifier des sources gelées avant leur commit.

| Besoin | Document |
|---|---|
| Direction durable de Nathan | [DIRECTIVES-NATHAN](produit/DIRECTIVES-NATHAN.md) |
| Ambition et fonctionnement des dix départements | [Définition produit](produit/DEFINITION-PRODUIT.md) |
| Profondeur M1/M5/M7/M10 et adaptation des prompts | [Périmètre des modules](produit/PERIMETRE-MODULES.md) |
| Décisions courantes et historique | [Index ADR](decisions/README.md) ; ADR-0008 core, 0009 socle, 0010 mémoire, 0012 réutilisation/productivité |
| Architecture et limites connues | [ARCHITECTURE](architecture/ARCHITECTURE.md) |
| Cibles transactionnelles M2/M3 et provenance N4 vérifiées localement | [Liaison des cibles](architecture/LIAISON-CIBLES.md), [raccords et limites R19](research/R19-2026-09-30/README.md) |
| Économie de tokens, mécanismes et manques | [ECONOMIE-TOKENS](architecture/ECONOMIE-TOKENS.md) |
| Contrats d'un département | [DEPARTEMENTS](architecture/DEPARTEMENTS.md), [TAXONOMIE](architecture/TAXONOMIE.md) |
| App Expo à quatre profils | [MOBILE](architecture/MOBILE.md) et `mobile/` |
| Avis de sécurité mobile et portée des appelants | [Audit du lock du 1er octobre](exploitation/MOBILE-DEPENDANCES-2026-10-01.md) ; avis ouverts, pas d'override certifié |
| Sélection fraîche de briques GitHub/GitLab | [R16 — recherches du 30 septembre](research/R16-2026-09-30/README.md) |
| Catalogue et provenance des ingrédients | [INGREDIENTS](research/INGREDIENTS.md) ; R1–R15 sont des recherches datées |
| Consolidation et prochaines livraisons | [RESTRUCTURATION-2026-09-30](programme/RESTRUCTURATION-2026-09-30.md), [BOUCLE](programme/BOUCLE.md) |
| Corrections et raccords vérifiés localement | [BILAN-EXECUTION](programme/BILAN-EXECUTION-2026-09-30.md), [preuves R17](research/R17-2026-09-30/README.md), [raccords M7/M10 R18](research/R18-2026-09-30/README.md) |
| Résultat du lot de direction/recherche | [BILAN-RESTRUCTURATION](programme/BILAN-RESTRUCTURATION-2026-09-30.md) et ses preuves ; implémentations futures distinguées |
| Historique des tranches déjà exécutées | [PLAN](programme/PLAN.md) ; une case cochée ne remplace pas un invariant métier vérifié |
| Mémoire : architecture et gouvernance | [RAG-PREMIUM](memory/RAG-PREMIUM.md), ADR-0010, ADR-0012 et recherche M10 R16 |
| Consolidation mémoire développement et contrôle humain | [Guide M10](grs/memory/M10-CONSOLIDATION-PLANIFIEE.md), [console jobs](grs/memory/M10-CONSOLIDATION-DASHBOARD.md) ; SQLite sur le même hôte |
| Performance marketing issue du CRM et de M5 | [M7 performance campagne](grs/marketing/M7-ROI-CANONIQUE-PLAN.md) ; couverture et exclusions, dépenses/ROI inconnus |
| Import manuel de message vocal dans la console | [Audit M1 actuel](grs/reception/M1-AUDIT-INITIAL-QUADRUPLE-A.md) ; WAV vers M1/M2 testé, STT réel local CPU sur une phrase publique seulement, aucun canal téléphonique certifié |
| Rapport stratégique FinanceCore et droits des agents | [Plan de dossier CFO](grs/compta/M5-CFO-DECISION-RACCORDEMENT-PLAN.md), [droits CFO](grs/compta/M5-PROFILS-AGENTS-DROITS.md) ; deux outils préparatoires, droit humain révocable, SQLite et périmètre de l'instance |
| Nouvelles reprises et droits CFO | [R20](research/R20-2026-10-01/README.md), collecte en cours ; résultats terminés distingués des campagnes en cours |
| Profondeur marketing et mémoire | [Matrice des quinze capacités M7](grs/marketing/M7-MATRICE-CAPACITES-2026-09-30.md), [audit des quinze couches M10](grs/memory/M10-AUDIT-INITIAL.md) ; sources, tests pertinents et manques, sans certification globale |
| Installation hôte autonome | [INSTALLATION](exploitation/INSTALLATION.md), `install/` |
| Option VPS Compose et exploitation | [INSTALLATION-VPS](ops/INSTALLATION-VPS.md), [EXPLOITATION](ops/EXPLOITATION.md), `deploy/` |
| Protection des renseignements personnels | [Politiques](compliance/politiques/README.md), [ÉFVP](compliance/efvp/GABARIT-EFVP.md) |
| Provenance du fork et composants tiers | [core/PROVENANCE](../core/PROVENANCE.md), [core/NOTICE](../core/NOTICE) |
| Règles de développement | [AGENTS](../AGENTS.md), [CLAUDE](../CLAUDE.md), [digest](../00-DIGEST.md) |
| Ancienne restructuration et décisions retirées | [Historique](history/README.md), ADR-0001–0007 |

Le cœur est un fork modifié d'OpenClaw, maintenu par OPSYS. Le générateur configure les fournisseurs
natifs par défaut; LiteLLM est réservé au mode de compatibilité explicite. Les paliers peuvent nommer
les variables d'environnement contenant les clés, et leurs valeurs secrètes ne sont pas écrites dans
la configuration JSON. Le readiness bloque sur des clés requises absentes; des tests sans credentials
ne prouvent pas les appels réels aux fournisseurs. Le mobile est une application Expo propre à OPSYS.
Le socle métier utilise SQLite par défaut et PostgreSQL en option. M10 inclut la mémoire d'affaires
et celle du développement, avec séparation des données et droits. Un index documentaire n'est pas
une certification de production.

Les audits M1–M10 sous `departements/` datent du 28 septembre ; les recherches R16 indiquent les
évolutions et écarts examinés au 30 septembre. Les volumes de Forge et ses anciennes routes ne
prouvent pas l'inventaire d'OPSYS. Le plan maître PDF reste une source historique de l'ambition.
