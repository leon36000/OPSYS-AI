# Cahier consolidé de l’ambition OPSYS-AI — transmission du 5 octobre 2026

Ce cahier consolide les instructions effectivement reçues de Nathan pour changer de conversation/infrastructure. Il complète [la définition détaillée](DEFINITION-PRODUIT.md), [le périmètre adapté](PERIMETRE-MODULES.md), [les directives](DIRECTIVES-NATHAN.md) et [l’entreprise apprenante](VISION-ENTREPRISE-APPRENANTE.md). **Exigences cible**, pas statut de livraison ni copie mot pour mot des anciens longs prompts. Aucune exhaustivité des conversations privées/non reçues n’est revendiquée.

Demande actuelle conservée : « est ce que tout les informations de OPSYS-AI ce trouve dans le dépôt l’ambitions ainsi que la profondeur des module M (départements virtuel) […] chaque Modules M octrois des capacités et l’efficaciter du domaine viser au Agents […] je veux continuer le travaille sur mon infra qui est connecter a github fais moi un pack complet ainsi qu’un prompt […] codex de mon infra ».

## Produit de premier ordre, capacités réelles

OPSYS-AI doit donner à une PME les ressources d’une grande entreprise : dix départements complets, plusieurs agents spécialisés, une vérité partagée, des opérations interconnectées et une autonomie gouvernée. La sophistication visée porte sur les résultats du métier, pas le nombre de modèles ou frameworks. Chaque module fournit outils déterministes, logiciels spécialisés, APIs, connaissances du domaine, permissions, workflows durables, mémoire, traces, interfaces et critères de qualité aux agents. Modèles/avatars/prompts orchestrent ces capacités; ils ne remplacent pas logiciels ou sources.

Le chef de projet évalue technologies de pointe et briques matures GitHub/GitLab/littérature avant réécriture. Licences code/poids/avatars/voix, version, qualité, maintenance, sécurité, maturité, coût total et intégration sont qualifiés. OpenClaw déjà forké constitue le cœur maintenu OPSYS; Hermes et d’autres composants sont des candidates. Aucune course aux dépendances ni synchronisation aveugle amont.

## Dix départements, aucune réduction à une façade

| Département | Capacité et responsabilité cible |
|---|---|
| M1 Front Office | Réception/adjointe omnicanale/vocale, interactions et conversations persistées, collecte/qualification, récupération appels manqués et voicemail, inbox/email/SMS, plaintes/urgence/escalade, rendez-vous/rappels, transferts contextualisés, scripts/politiques versionnés et boucle qualité |
| M2 CRM | Client/lead/propriété/dossier, pipeline et opportunités, tâches/activités/photos, qualification, soumissions/relances/conversion, prochain suivi, provenance marketing, permissions et interfaces; ne pas reconstruire le pilier utile |
| M3 Estimation | Vision/qualité photo, segmentation/géométrie/échelle/annotation humaine, géospatial/contextes, estimateurs gouttières/revêtement/soffite-fascia/réparation, matériaux/main-d’œuvre, risque/incertitude/P50/P80, coût/prix/marge/minimum rentable, soumission préparatoire, validation, RAG construction QC et calibration sur réel |
| M4 Équipes/terrain | Planning/capacité/équipes/tâches/routage, agenda et exécution, pointages/preuves/checklist/photos/matériaux/imprévus, statut fiable, réorganisation et événements de complétion; temps écoulé distingué des heures-personnes |
| M5 FinanceCore | Département comptable, paie/fiscalité préparatoires Québec/Canada, contrôleur, CFO stratégique, projections/réserves, investissements/emprunts/actifs, audits et dossier CPA; vérité financière et actions humaines protégées |
| M6 Inventaire | Catalogue/fournisseurs/stock/prix sourcés/réservations, besoins depuis estimation, achats proposés/PO/réception/consommation/pertes/retours/substitutions, coût réel/variance/logistique et mémoire; M5 paie, M6 ne paie pas |
| M7 Marketing & Croissance | Département CMO multicanal complet, visibilité/notoriété/crédibilité/audience/engagement/leads/conversion/réputation/rentabilité; SEO/PPC sont des parties du département |
| M8 Analytics | Métriques financières/commerciales/terrain/marketing gouvernées et sourcées, qualité/fraîcheur/incertitude, rapports/alertes; ne réinvente pas les calculs financiers M5 |
| M9 Intelligence stratégique | Direction/scénarios/priorités/capacité/risques/opportunités, décisions fondées sur faits CMO/CFO/terrain/mémoire et suivi d’impact; critique multi-modèles facultative et budgétée |
| M10 Mémoire & intelligence | Mémoire premium d’entreprise ET développement, domaines isolés, événement/source/relation/révision/permissions, contexte et connaissances évaluables; aucun travail partant du vide ou promesse mémoire magique |

Les listes détaillées M2/M3/M4/M6/M8/M9 et leurs critères restent dans DEFINITION-PRODUIT. Cette table ne réduit aucun sous-module.

## M1 : profondeur front-office conservée

Périmètre : intake omnicanal (téléphone/SIP/SMS/email/webform/webchat/social/voicemail/portail/manuelle), voice agent progressif, qualification par service, missed-call rescue, smart voicemail, triage email, réponses SMS/messages, bureau plainte/escalade, agenda/rappels, réponses de statut client autorisées, adjointe/digest/tâches, handoff humain avec contexte, boucle d’intelligence. Intégrations CRM/marketing/estimation/cédule/finance/mémoire, dashboard/mobile, scripts versionnés, consentement audio et SMS, vérification webhooks/rejeu, traces/latences, tests négatifs et E2E.

Voix : audit → voicemail intelligent → sandbox → after-hours → assisté → production contrôlée. STT/TTS/VAD/barge-in/interruptions/silence/handoff/repli à qualifier. Pipecat/LiveKit/Twilio/SIP et STT/TTS locaux/cloud sont des candidates/adaptateurs, pas tous installés par l’exigence. Pas de prix/délai/garantie inventés, rendez-vous sans cédule, remboursement/promesse légale, divulgation financière sans identité, messages de masse non autorisés. L’employé alimente le dossier, pas publication finale.

## M5 : profondeur comptable, fiscale et CFO conservée

Périmètre prioritaire consolidé des extensions Nathan :

1. Opérations comptables, grand livre/plan comptable/périodes/corrections/sources/audit.
2. Facturation complète liée CRM/soumission/chantier, PDF, AR/AP/aging/relances/fournisseurs/dépenses.
3. Banque/CSV/Stripe/Plaid/QuickBooks/CCube : normalisation, rapprochement proposé, confiance, doublons/splits/frais/idempotence/conflits et validations.
4. Paie et obligations employeur : heures/taux/temps supplémentaire/vacances/fériés/primes/allocations/avantages, retenues fédéral/QC, RRQ/RQAP/AE, FSS/normes/CNESST, DAS, talons, T4/RL-1/ROE préparatoires; taux annuels versionnés/sourcés, données manquantes bloquantes.
5. Fiscalité Québec/Canada : TPS/TVQ/GST-HST applicables, impôt société/acompte/DAS, calendrier/délais/périodes/obligations/documents/anomalies et préparation des paiements, sources officielles.
6. CPA/fin d’année : pièces, balances, états, taxes/rapprochements/AR-AP/anomalies/notes/validations/exports.
7. Cashflow : aujourd’hui/7-14-30 jours/13 semaines/6-12-24 mois et 5 ans pour décisions majeures, prudent/normal/optimiste/stress tests et sensibilités; hypothèses explicites, pas forecast inventé.
8. Contrats/cédule : backlog signé/probable, dépôts/jalons/capacité/équipe/date/matériel/marge/retards et risques de rentrée d’argent.
9. Rentabilité : chantier/service/ville/équipe, coût matériau/main-d’œuvre/sous-traitance/déplacement/frais/marketing et variance estimation/réel.
10. Achats capital : timing, budget, ROI/break-even, affordabilité, CCA préparatoire et service de dette.
11. Camion/équipement : cash/finance/location, taxes/mise de fonds/taux/durée, assurance/entretien/carburant/utilisation/productivité, cashflow et risques de saison faible.
12. Bâtisse : hypothèque/DSCR/rent-vs-own, coûts d’occupation/zonage/travaux/assurances, stress revenus -20%/taux +2%, liquidité, prêteur et questions CPA/fiscaliste/avocat/notaire.
13. Dette/financement/investissement : cash vs emprunt, remboursement, allocation marketing/équipement/inventaire/embauche et risque/rendement/working capital.
14. Épargne/réserves : taxes/impôt/paie/DAS/CNESST/AP/dette/urgence/saison morte/équipement/marketing/croissance. Solde bancaire ≠ cash libre réel; obligations ne sont pas double-comptées.
15. Conseiller fiscal/comptable préparatoire : salaire/dividendes/bonus/timing/CCA/avantages/déductibilité potentielle/structure/holding/subventions/fin d’année et questions professionnelles, sources/hypothèses/données manquantes.
16. CFO Decision Engine : rapport de décision structuré (faits/manquants/hypothèses/scénarios/13 semaines/6-12-24 mois/taxes/paie/dette/marge/croissance/risques/conditions/questions/plan/validation).
17. Risques/contrôle/pré-audit : erreurs, documents manquants, doublons/anomalies/fraudes présumées, Loi 25/RBAC/PII/rétention/audit/approvals/observabilité, aucune accusation inventée.
18. RAG/datasets fiscal-comptable : sources officielles RQ/ARC/CNESST/datées, décisions CPA validées, données internes séparées, licences/anonymisation/golden set; datasets pour OCR/extraction/classification, jamais vérité fiscale locale par entraînement seul.
19. Dashboard CFO/mobile quatre profils : réserves/cash libre/AR-AP/paies/taxes/DAS/backlog/marges/dettes/capacité/risques/décisions; données coûts/marges internes jamais au client.
20. Mémoire financière M10 : décisions/mappings/corrections/anomalies/règles/exceptions/prompts/plans/validations et liens sources.

Réutiliser et durcir M5 existant, pas recréer CRM/compta ni backend parallèle. Adapters QuickBooks/CCube/Sage/Acomba/Xero/CSV selon accès réel; read-only, sandbox, dry-run, mapping/audit/conflits puis écriture autorisée. OCR avec provenance, validation arithmétique/confiance/humain; signature/rejeu/idempotence des webhooks. Les préparations stratégiques disent « Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle ». Aucun paiement, dépôt employé, déclaration/remise/T4/RL-1 officiel, virement/remboursement, clôture/écriture finale, contrat/achat/emprunt/investissement seul sans validations applicables. Les noms de tables/routes historiques sont des exigences adaptées, pas preuve de présence.

## M7 : profondeur CMO conservée

Onze sous-domaines métier : identité/brand voice/règles et audit contenu; social command center multicanal/calendrier/brouillons/adapters/approbations; content factory depuis chantier/photos autorisées/avis/FAQ/CRM, brief/variantes/repurposing/media; croissance légitime et mesure audience/engagement/formats/heures/séries; réputation/avis/demandes/brouillons/escalade; SEO local/Search Console/SerpBear/pages/FAQ/rank/maillage; Ads Intelligence Google/Meta/autres selon API réelle, lecture/analyse/simulations; attribution/ROI/marge marketing liés leads→ventes→profit via CRM/M5/Matomo/UTM; concurrence/sources publiques conformes; marketing terrain/offline/références/pancartes/partenaires/camions; conseiller CMO stratégie saisonnière et plans 30/60/90 jours.

Dashboard/calendrier/previews/validations/ROI/reputation/CMO, mobile admin/vendeur/employé, workflow chantier→contenu→qualité/consentement→brouillon→validation→publication/export→mesure→mémoire, rapport hebdo/campagne saisonnière/avis→réponse et tâche. Mode export réel si API/OAuth indisponible. Pas de faux likes/followers/spam/DMs interdits/scraping contournement, budgets/dépenses/actions publiques sensibles sans validation. Ne jamais fabriquer garanties/prix/témoignages/consentement ni inférer ROI réel de données démo.

## M10 : profondeur mémoire premium conservée

Couches : événements append-only; canon structuré transactionnel; recherche lexicale/vectorielle; entités/relations/graphe; checkpoints/workflows durables; registres prompts exacts/plans/décisions/ADR/code/fichiers/routes/dépendances/tests/bugs/gotchas; mémoire métier; self-model d’identité/mission/limites/état; retrieval/router/ranking/fraîcheur/autorité/validation/permissions; context packs courts→détaillés; injection avant action et capture après; audit/consolidation/contradictions/orphelins/obsolescence; gouvernance/rétention/révision/effacement/PII; évaluation et dashboard/CLI/API/mobile autorisés.

Relier prompt→plan→changement→fichier→test→preuve→décision. Garder qui/quoi/pourquoi/date/source/version/dépendances/risque/statut/confiance/coût/corrélation/prochaine action. Une petite modification peut affecter une décision future; elle doit être récupérable, pas oubliée parce qu’elle est petite. Domaines développement et entreprise séparés par scope/tenant/permission et confidentialité; pas de code/project-memory visible au client/employé. Sources canon et instruction explicite actuelle de Nathan prioritaires, mais état du système établi par code/tests/runtime; contradiction enregistrée, ancien statut « terminé » ne remplace pas une preuve.

Pas une simple similarité vectorielle : faits/sources/relations/temporalité/décisions/tests/risques adaptés à la tâche. Contexte must-know court, sources consultables et deep dive à la demande. Révision active/stale/superseded/contradicted/archived, trace originale et règles d’effacement légales; aucun secret en clair, références seulement. Pas de stockage éternel ou rappel 100% garantis. Questions avec citations, métriques recall/precision/fraîcheur/contradiction/couverture/coût/latence et tests adverses; connaissances candidates distinguées des faits validés. PostgreSQL/Qdrant/Cognee/LlamaIndex/LangGraph/Langfuse/OTel/Temporal/n8n sont des moyens à choisir selon la jonction utile, pas une pile obligatoire.

## Agent, dashboard, avatar, ingestion et apprentissage

Profils par département/rôle/responsabilité : identité, modèle/provider/repli, outils/capabilities, scope, politique mémoire, budget/context/output/tours/retries/concurrence, triggers et escalade. Secrets en références; version et admission avant activation. Communication IDs/tenant/version/corrélation/statut/artifact/prochaine action, pas diffusion de tous les dossiers à tous. Résultat inconnu après RPC externe ne déclenche pas un replay aveugle. Budget/capacité réservé avant appel LLM puis consommation réconciliée.

Dashboard Connecteurs par métier : API/fournisseur/adaptateur/scopes/référence secret/permission d’export/coût/état observé/dernier contrôle/limites/repli. Présence de config ≠ authentification ≠ intégration prouvée ≠ écriture autorisée. Avatar 3D/audio/vidéo de chaque département relié à la même session/outils/dossier, microphone→STT→contexte/intention→outil→réponse→TTS→animation/rendu, interruption/repli/sous-titres/prise en charge humaine. ACE/Audio2Face/LiveKit/Pipecat/WebGL sont candidates, licences/voix/poids/performance QC et budget requis; texte reste utilisable sans GPU.

Fusion opérationnelle : onboarding/assimilation initiale massive autorisée puis continue, inventaire/fichiers protégés/empreintes/extraction/classification/ambiguïtés humaines/dédupe/source canon ou candidate/indexation/évaluation/disponibilité. Jobs durables avec curseur/quota/idempotence/reprise/quarantaine/annulation/rétention/effacement propagé. PDF/images/CSV/docs/compta/contrats/cédule/photos selon format et droits. Instructions dans les documents sont des données non fiables, jamais autorité d’un agent. Progression par corpus choisi, validés/erreurs/couverture/questions de contrôle, sans note générale d’assimilation inventée.

Apprentissage : données terrain validées→jointure devis/chantier/équipe/temps/matériaux/costs→analyse d’écarts→proposition segmentée→validation indépendante→promotion versionnée→surveillance/rollback. Calibration déterministe d’abord, fine-tuning contrôlé plus tard seulement si justifié. Pour photo/géospatial : échelle/unité/SCR/date/provenance/droits/mesures indépendantes; qualité photo ou routage OSRM ne mesure pas un bâtiment. Mesurer erreur absolue/relative et couverture/refus par usage avant dire « précision exceptionnelle ».

## Responsabilité du chef de projet et critères

Audit réel puis décision et livraison progressive, sans gros refactor aveugle ni reconstruction de CRM/compta utiles. Retirer les règles de consensus obligatoire/attente d’un modèle extérieur contre-productives; garder sécurité du produit et preuves adaptées au risque. Déléguer utilement avec contrats et surfaces séparées, contrôler la jonction, traiter les échecs au lieu de les masquer. Temps/tokens/ressources mesurés; les décisions courantes/réversibles avancent sans solliciter Nathan.

Pour chaque capacité : données/sources, contrats et API/outils réellement exposés, permissions, workflow durable et reprise, test négatif et intégration réelle/fictive explicitée, dashboard/mobile applicables, traces, docs et état honnête. OAuth/API manquant = gate précis et repli fonctionnel documenté, pas FAIT_VÉRIFIÉ artificiel ni arrêt total. Aucun 100%, autonomie permanente, avatar/vision client ou gain de tokens/qualité revendiqué sans preuve. L’argent/fiscal/légal/paie/achats/publications sensibles gardent les validations humaines/professionnelles.

## Transmission

Voir [guide et prompt](../reprise/TRANSFERT-INFRA-2026-10-05/README.md), [audit de conservation](../reprise/TRANSFERT-INFRA-2026-10-05/AUDIT-TRANSMISSION.md) et [état/priorités](../reprise/TRANSFERT-INFRA-2026-10-05/ETAT-ET-SUITE.md). Le snapshot contient les fichiers versionnés et modifications préparées, pas l’ensemble des conversations ou configurations personnelles. Les commits synthétiques du bundle sont seulement un mécanisme de transport; rapprocher l’état GitHub réel avant publication.
