# Périmètre cible des départements — adaptation au dépôt OPSYS-AI

Date : 2026-09-30. Source : prompts retransmis par Nathan, [directives](DIRECTIVES-NATHAN.md),
[définition produit](DEFINITION-PRODUIT.md), code `2e56c0d` et recherches
[R16](../research/R16-2026-09-30/README.md). Ce document conserve l'ambition ; il ne certifie pas
que les capacités ci-dessous sont livrées. L'état initial du 30 septembre est historique;
le [registre actualisé](../programme/REGISTRE-AUDIT-2026-09-30.md) distingue les corrections
locales des constats partiels. Les critères de profondeur ci-dessous restent le périmètre cible.

## Adaptations communes

| Héritage | Application à OPSYS |
|---|---|
| Forge/GRS/Andromeda et `grs_api/modules/` | Fork TypeScript `core/`, socle `src/opsys/`, dix packages dans `departments/`, application `mobile/` ; pas de backend parallèle |
| M7 nommé `module8_seo`, M4 nommé `module6_equipes` | Codes métier M1–M10 et chemins actuels ci-dessous ; préserver les interfaces utilisées lors des migrations |
| Tables, routes et volumes annoncés en juin | Exigences ou inventaire historique ; recenser modèles/outils/API réellement présents avant d'ajouter un alias ou une table |
| PostgreSQL + Qdrant + Cognee + LangGraph + n8n + Temporal imposés | Capacités requises, technologies candidates : données transactionnelles, recherche, relations, reprise, planification, traces ; choisir la brique utile, sans tout installer |
| Plusieurs registres d'approbation par département | Socle N0–N5 et audit commun ; les règles financières/publications spécialisent le contrat, elles ne créent pas un chemin de contournement |
| « Rien ne peut être oublié » | Capture explicite, références, révisions, rétention et évaluations mesurées ; aucune garantie absolue de rappel ou de stockage éternel |
| Constitution avant décision Nathan | Directive actuelle pour les exigences ; preuves du commit pour l'état réel ; contradictions enregistrées |
| « FAIT_VÉRIFIÉ » hérité, nombres de tests | Critères de sortie de la capacité : données, outils/API, permissions, parcours, interface, documentation, traces et limites |

Une absence de credentials laisse un mode export/brouillon réellement utilisable. Elle ne justifie
ni faux appel distant réussi, ni blocage des moteurs internes. La mémoire respecte confidentialité,
consentement, rétention et effacement requis ; « non-oubli » n'autorise pas la copie de secrets.

## M1 — Front Office IA

Chemin : `departments/m01-front-office/src/m1_front_office/`.
Base actuelle : réception, qualification, conversations, consentement, suivi, plaintes, transferts,
photos, scripts/questions et phases vocales. Ces fondations sont à réutiliser. Les transports vocaux
réels, la notification en production et les jonctions complètes ne sont pas déduits de leur existence.

| ID | Capacité cible et preuve attendue |
|---|---|
| M1.1 | Intake omnicanal : téléphone, SMS, email, formulaires, webchat, social autorisé, portail, voicemail et saisie ; interaction persistée, identité et déduplication |
| M1.2 | Voice agent : streaming STT/LLM/TTS, interruption, silence, faible confiance, supervision et repli humain ; latence mesurée |
| M1.3 | Qualification par service : adresse/ville, photos, accès, urgence, bâtiment, délai ; informations manquantes et lead prêt pour M2/M3 |
| M1.4 | Appel manqué : tâche rappel durable, message brouillon avec consentement, déduplication et suivi jusqu'à résolution |
| M1.5 | Voicemail : audio autorisé, transcription, résumé, contacts/service/urgence, tâches et sources |
| M1.6 | Triage email : nouvelle demande, client, facture, fournisseur, plainte, spam, emploi, partenariat, document ; réponse brouillon et routage |
| M1.7 | Assistant SMS/messages : photos, rappels, suivi, paiement fourni par M5 ; opt-in, STOP, message exact approuvé et résultat d'envoi inconnu sans rejeu |
| M1.8 | Plaintes/urgences : empathie, preuves, priorité, escalade ; aucune admission légale ou promesse de remboursement inventée |
| M1.9 | Cédule/rappels : disponibilité M4 vérifiée, conflit, replanification/annulation en demande ; événement réellement créé avant confirmation |
| M1.10 | Statut client : interrogation CRM/estimation/cédule/finance après vérification d'identité ; aucune donnée financière d'un autre client |
| M1.11 | Adjointe : digest quotidien, tâches, leads sans suivi, messages urgents, documents/photos manquants |
| M1.12 | Handoff : humain/rôle cible, résumé, historique, coordonnées autorisées, manquants, prochaines actions, lien conversation/CRM |
| M1.13 | Intelligence réception : délais, pertes, conversion, objections, services/villes, scripts, sources marketing ; métriques sourcées |
| M1.14 | CRM M2 : client/lead/activité/tâche/transcription/photos via contrats existants, sans nouveau CRM |
| M1.15 | Boucle M7 : campagne/UTM → lead → qualité/conversion/raison de perte, avec attribution explicite |
| M1.16 | M10 : événements, préférences utiles, plaintes, promesses humaines, erreurs et contexte avant action complexe |
| M1.17 | Dashboard : inbox, appels, tâches, intake, handoffs, scripts/politiques, connecteurs et laboratoire vocal |
| M1.18 | Mobile : admin prend en charge/approuve, vendeur reçoit dossier, employé signale, client fournit demande/photos ; droits séparés |
| M1.19 | Voice sandbox : faux appel, STT/TTS, interruptions, transfert, consentement et écritures CRM démontrés |
| M1.20 | E2E : soumission gouttières, appel manqué, email revêtement, plainte, facture avec identité et sandbox vocal |

Production vocale progressive : voicemail → sandbox → hors heures → assistance humaine → live
contrôlé. Les phases se prouvent ; elles ne sont pas sautées par un adaptateur mock. Google Business
Messages a été retiré en 2024 : ne pas construire un connecteur à une API disparue. Les canaux
disponibles sont vérifiés dans les documentations actuelles et éligibilités de plateforme.

## M5 — FinanceCore, CFO IA complet

Chemin : `departments/m05-financecore/src/m5_financecore/`.
Base septembre : registre, taxes sourcées, soldes, facturation, comptes à payer, coûts/variance,
calendrier fiscal, cash libre, prévision et outils. Ce n'est pas le M5 Forge décrit comme 238 routes.
La collision de facture DEP-001 relevée dans l'audit initial est corrigée localement selon le
[registre](../programme/REGISTRE-AUDIT-2026-09-30.md). Cette correction ne suffit pas à qualifier
tout le cycle facture, les connecteurs externes ou le CFO IA complet.

La numérotation retenue est l'extension prioritaire **M5.1–M5.20**. M5 possède les calculs et analyses
financières ; M9 les consomme pour des arbitrages globaux. Un service partagé ne réduit pas le CFO
à un simple export ni ne crée un second grand livre.

| ID | Capacité cible et preuve attendue |
|---|---|
| M5.1 | Accounting Operations : grand livre/partie double, plan comptable, écritures proposées/finales, périodes, corrections sourcées, intégrité, multi-entités |
| M5.2 | Facturation/AR/AP : client/estimate/chantier, taxes, numérotation, PDF, draft→validation→envoi→paiement, aging, litiges, relances, bills/OCR/échéances/doublons |
| M5.3 | Banque : imports CSV/Stripe/QBO/Plaid autorisé, transactions normalisées, matching partiel/split/frais, score, inconnues, validation, idempotence |
| M5.4 | Paie préparatoire : heures, overtime/vacances/fériés/primes/avantages, fédéral/Québec/RRQ/RQAP/AE/FSS/CNESST/normes, DAS, T4/RL-1/RE, paystub et projection |
| M5.5 | Fiscalité QC/Canada : TPS/TVQ/GST-HST applicable, acomptes société, remises paie, obligations et échéances sourcées/versionnées, anomalies et alertes |
| M5.6 | CPA/fin d'année : période, documents sources, ledger/balances, AR/AP, taxes, rapprochements, anomalies, notes et validations, export préparatoire |
| M5.7 | Prévisions : aujourd'hui/7/14/30 jours, 13 semaines, 6/12/24 mois, 5 ans pour décisions majeures ; prudent/normal/optimiste/stress et incertitude explicite |
| M5.8 | Contrats/cédule : carnet signé/probable, dépôts/jalons, dates, capacité équipe, matériel, retards, marge, paiements et carte revenus |
| M5.9 | Rentabilité : chantier/service/ville/équipe, matériel et temps réels, sous-traitance, déplacement, frais, publicité attribuée, variance et leçons |
| M5.10 | Capital : demande d'achat, budget, affordability, timing, ROI, cash/finance/location et réserves protégées |
| M5.11 | Camion/équipement : assurance, entretien, énergie, utilisation/productivité, revenus/économies, seuil rentabilité, impact 13 semaines/12/24 mois et questions CPA/prêteur |
| M5.12 | Bâtisse : hypothèque, coûts occupation, rent vs own, DSCR, taux +2 points/revenus -20 %, liquidité, zonage/risques documentés, dossier prêteur et questions professionnelles |
| M5.13 | Dette/financement/investissement : service dette, fonds de roulement, allocation capital, ROI ajusté au risque, emprunter/payer cash/rembourser/investir/attendre |
| M5.14 | Réserves : TPS/TVQ, impôt, paie/DAS/charges, fournisseurs/dette, urgence/saison/équipement/marketing/croissance ; cash libre réel, pas simple solde bancaire |
| M5.15 | Conseiller fiscal/comptable : salaire/dividendes, fin d'année, CCA, avantages, structure et crédits comme analyses sourcées, scénarios et questions CPA |
| M5.16 | CFO Decision Engine : question, sources/manquants/hypothèses, scénarios et horizons, impacts taxes/paie/dette/marge, recommandation, conditions, questions et validation |
| M5.17 | Risque/pré-audit : pièces manquantes, paiement/facture, anomalies taxes, doublons, modification inhabituelle, accès, audit, risque liquidité/fiscal |
| M5.18 | Knowledge/RAG/datasets : sources ARC/RQ/CNESST versionnées, décisions CPA et documents privés isolés ; jeux publics/licences pour OCR/extraction/classification, golden set anonymisé |
| M5.19 | Dashboard CFO : cash/réserves/AR/AP/obligations, prévisions/backlogs/marges/dettes, décisions/achats/risques, santé et sources |
| M5.20 | M10 : décisions, mappings, validations, rapports, corrections, erreurs, calculs/version des sources, contexte financier autorisé |

Toutes les sorties stratégiques portent la mention d'analyse préparatoire. Données/tables de paie
absentes ou périmées : calcul officiel bloqué, liste exacte des manquants. Aucune constante fiscale
copiée sans année/source/version. Connecteurs QuickBooks/CCube/Sage/Acomba/Xero/Stripe/Plaid :
déclarer capacités réelles, limitations, credentials, mapping, read-only, dry-run et sandbox.

Le journal, les montants Decimal, dates et ratios se calculent par code déterministe ; les modèles
expliquent les scénarios. Argent réel, paie finale, fiscal officiel, écriture finale, achat/emprunt
ou engagement restent validés par Nathan et les professionnels applicables.

E2E requis : chantier→facture→paiement→rapprochement ; facture fournisseur→OCR→AP ; taxe/période ;
paie draft et dépôt bloqué ; calendrier fiscal ; réserves ; camion 95 000 $, équipement 40 000 $,
bâtisse et question d'investissement 50 000 $ comme fixtures explicites, sans achat réel.

## M7 — Marketing & Croissance IA

Chemin : `departments/m07-marketing/src/m7_marketing/`.
Réutiliser `brand/`, `content/`, `usine/`, `social/`, `reputation/`, `ads/`, `roi/`, `seo/`,
`competitive/`, `utm/` et les workflows. L'usine déterministe est une base ; les simulations Postiz
et jeux de métriques ne prouvent pas publication, OAuth ou attribution de marge en réel.

| ID | Capacité cible et preuve attendue |
|---|---|
| M7.1 | Brand Core : promesse validée, ton fr-CA, services/zones/valeurs, objections, garanties, preuves sociales, messages interdits, règles par plateforme, brand book |
| M7.2 | Social : comptes/scopes, calendrier, brouillons, variantes, médias, approbation, planification/publication/export, historique et performance |
| M7.3 | Content Factory : briefs et bibliothèque, chantier/photos/avis/FAQ→multi-formats, repurposing, droits d'usage, validation marque/exactitude/privacy et sources |
| M7.4 | Growth : audience/engagement, formats et horaires, hashtags, collaborations/concours conformes, séries/rétention et plan 30 jours ; pas faux likes, spam ou bots |
| M7.5 | Réputation : avis, réponses brouillon, escalade négative, demande neutre d'avis, témoignages autorisés, sentiment et suivi qualité |
| M7.6 | SEO local : Search Console/SerpBear/GBP disponible, audit/pages locales/FAQ/titles/meta/maillage/cannibalisation, positions et alertes |
| M7.7 | Ads : lecture campagnes/coûts/conversions/search terms permis, gaspillage, landing/creative, budget simulation, qualité lead, demande d'approbation de toute écriture |
| M7.8 | ROI/attribution : source→lead→vente→revenu/marge M5, UTM, coûts/CPL/CPA, rentabilité canal/service/ville, fenêtres et incertitude |
| M7.9 | Concurrence : sources publiques autorisées/API, sites/offres/avis/messages/positions, écarts marché, provenance et confiance |
| M7.10 | Offline/local : camions/pancartes/flyers/partenariats/commandites/événements/références/voisinage, coût et attribution suivis |
| M7.11 | CMO : diagnostic fondé CRM/compta/analytics, plans 30/60/90 jours, saison/expansion/prix-offres, campagnes, risques, priorités et rapport hebdo |
| M7.12 | Dashboard : calendrier, briefs, bibliothèque, qualité, approbations, avis, campagnes, ROI, recommandations et connecteurs |
| M7.13 | Mobile : admin valide, vendeur et employé fournissent photos/notes/autorisation ; aucun employé ne publie directement |
| M7.14 | E2E : chantier Repentigny→variantes→contrôles→approval Facebook/GBP→export ou publication réelle explicitement qualifiée→metrics→rapport |
| M7.15 | Docs/traces : outils/API, sources et permissions, workflows, tests, limites OAuth/plateforme, coûts et statut fin |

Ne pas solliciter seulement les clients satisfaits : Google interdit la sélection des avis positifs.
Séparer traitement privé d'un incident et éligibilité à une demande d'avis neutre. Les réponses
négatives restent humainement validées. M7 réutilise les transactions M5 au lieu de recalculer une
« marge » depuis des conversions déclarées par une plateforme publicitaire.

## M10 — Mémoire long terme, intelligence et conscience opérationnelle

Chemins : `departments/m10-memoire/src/m10_memoire/`, `src/opsys/memoire/`,
greffe `core/src/context-engine/opsys-contexte-*.ts`. Deux domaines : affaires et développement.
Réutiliser registres hash-chaînés, décisions, confidentialité, preflight, faits candidats, contexte
à quatre couches, consolidation et audit. La base vectorielle n'est jamais l'autorité métier.

| ID | Capacité cible et preuve attendue |
|---|---|
| M10.1 | Événements append-only : tâche/prompt/plan/code/test/bug/décision/runtime, auteur, horodatage, source, résultat, statut, impact et prochaine action |
| M10.2 | Entités/relations : modules/services/fichiers/routes/tests/agents/clients/chantiers, dépendances, implements/fixes/tests/supersedes/contradicts, temporalité et preuves |
| M10.3 | Prompt registry : exact ou référence protégée, hash, version, auteur, but, module, résultats et liens ; prompts contenant secrets expurgés |
| M10.4 | Plan registry : objectifs/étapes/responsables/fichiers/risques/écarts, statut et liens prompt→plan→changes |
| M10.5 | Décisions/ADR : contexte/options/raisons/conséquences/autorité/source, révision et remplacement, contradictions proposées |
| M10.6 | Code memory : repo/Git, symboles/routes/imports/diffs, snapshots hashés, tests, dépendances et analyse d'impact ; collecte incrémentale |
| M10.7 | Erreurs/validation : symptôme/cause/fix/prévention/test, commandes/env/résultats, evidence refs et gotchas récupérables |
| M10.8 | Recherche : lexical+sémantique+relations, module/domaine/permission/fraîcheur/statut/autorité, citations, classement évalué |
| M10.9 | Paquets de contexte : must-know, important, preuves, deep-dive ; budget explicite et sources consultables |
| M10.10 | Preflight : directives, module, décisions/plans, fichiers, gotchas, tests, dépendances/risques/gates, go/no-go motivé |
| M10.11 | Postflight : changements, tests, erreurs, décisions, snapshots, relations et candidats ; aucune sortie LLM promue d'elle-même à vérité canon |
| M10.12 | Consolidation : scan incrémental, doublons/obsolescence/contradictions/orphelins, rapports et tâches ; reprise après crash sans perdre écritures tardives |
| M10.13 | Self model : identité OPSYS et mémoire développement, mission/modules/limites/règles, état sourcé, erreurs et prochaines priorités |
| M10.14 | Gouvernance : principal authentifié, domaines/tenant/objets, confidentialité, rétention/révision/effacement, secrets références, audit accès ; aucune autorité fournie par champ `agent` |
| M10.15 | API/MCP/CLI/UI/mobile et évaluation : recherche/registries/context/audit, événements récents, contradictions, qualité des sources ; tests recall/precision/fraîcheur avec résultats mesurés |

Les 30 critères de l'ancien prompt sont couverts par ces capacités : capture (1–8), stores/relations
(9–11), contexte/pre/post/consolidation/audit/self models (12–18), gouvernance/sourcing/révision
(19–24), CLI/API/docs/dashboard/E2E/matrice (25–30). Les noms de collections Qdrant représentent
des domaines/filtres ; ils ne justifient pas quinze services ou indexes obligatoires. Un graphe
relationnel dans la base existante est un premier palier ; graphiti/Cognee restent évaluables.

Tests de rappel : prompt ayant produit un plan ; contexte M7 avant modification ; bug/fix/test
historique ; ancienne déclaration contredite par preuve actuelle ; petite config modifiée ; refus
client A→B, agent désactivé et domaine développement→finance. Ne pas promettre un rappel parfait.

## Les six autres départements restent profonds

| Département | Chemin actuel | Périmètre à préserver et jonctions |
|---|---|---|
| M2 CRM | `departments/m02-revenue-crm/` | Contacts/dossiers, pipeline/activities/tâches, doublons, suivi/conversion, soumissions, droits client ; M1/M3/M5/M7/M10 |
| M3 Estimation | `departments/m03-estimation/` | Mesures incertaines/photos, matériaux/prix/coûts/taxes/marge, variantes, besoin d'infos, devis et autorisation d'envoi ; M2/M4/M5/M6 |
| M4 Terrain | `departments/m04-field-ops/` | Équipes/capacité/compétences/cédule/déplacements/météo, punch/WCT, preuves chantier et clôture ; identité, mobile, M3/M5/M6/M7 |
| M6 Matériel | `departments/m06-material-control/` | Catalogue/fournisseurs/stock/emplacements/lot/coût, réservations/PO/réceptions/sorties/retours, matériel prêt, variance/doublons ; M3/M4/M5 |
| M8 Analytics | `departments/m08-analytics/` | Métriques gouvernées financières/commerciales/terrain/marketing, fraîcheur/qualité/sources, indicateurs, rapports, alertes et dashboard ; M5 garde les calculs financiers |
| M9 Stratégie | `departments/m09-strategic-intelligence/` | Direction, scénarios/priorités/capacité/risques, décisions sourcées et suivi d'impact ; consomme CFO/CMO/terrain/mémoire, critique multi-modèles facultative sous budget |

## Contrat d'autonomie et d'économie des agents

Le dashboard cible configure un **profil d'agent** lié à un département et à une responsabilité :
identité interne, rôle, modèle/provider/repli, capabilities autorisées, scope données, politique
mémoire, budget/context/output/max-tours/retries/concurrence, déclencheurs et escalade.
La configuration est versionnée et validée avant activation ; une configuration active invalide
échoue fermée. Les secrets sont des références, jamais contenus dans le profil exportable.

Un coordinateur reçoit un événement métier durable ; il appelle seulement les spécialistes utiles.
Les outils composés traitent le calcul sans conversation coûteuse. Messages inter-agents : IDs,
version, objet/tenant, corrélation, statut, référence d'artefact et prochaine action. Pas de diffusion
du dossier complet à tous les agents. Contrats/outbox garantissent reprise et déduplication ; ils
ne promettent pas un effet externe exactement une fois quand le fournisseur ne le permet pas.

Le budget est réservé **avant appel LLM**, réglé sur consommation réelle ensuite et réconcilié après
crash ; il couvre sous-agents, retries et compaction. Les compteurs MCP seuls ne prouvent pas un
plafond fournisseur. Les sorties chiffrées restent déterministes même si un modèle fort explique.

## Qualification de livraison

`PARTIEL` signifie logique réelle avec parcours ou intégrations incomplets ; `GATED_EXTERNAL_API`
précise une permission/credential et son repli ; `NEEDS_HARDENING` signale un défaut/invariant
reproduit. `DONE_VERIFIED` exige le parcours métier et ses cas négatifs, interface utilisable,
données persistées, droits, traces, docs et critères de la capacité. Le nombre de fichiers ou de
tests ne qualifie pas un département entier. La matrice détaillée évolue avec les patches prouvés,
sans réécrire les résultats historiques.
