# PACK_CONSENSUS_GRS_v2.1
Objet: revue finale du plan maitre GRS avant execution. Reference complete: GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf (28 p. — passe PERFECTION: 4 simulations internes, 16 correctifs C-01..C-16, calibration METR).
Date: 2026-07-17. Emetteur: Orchestrateur (Fable/Opus 4.8, Claude Code). Ratification finale: Nathan.
Remplace PACK_CONSENSUS_GRS_v1. Nouveaute majeure: methode d'execution PROOF STACK v1.1 integree (D-039..D-042, RATIFIEES Nathan).

## 0. PROTOCOLE (obligatoire)
- Revue EN AVEUGLE: aucune visibilite sur les autres revues avant depot. Aucune coordination.
- Verdicts SCELLES, deposes SIMULTANEMENT, reveles seulement quand TOUS sont deposes.
- Depouillement PAR SCRIPT (tally) — aucun LLM n'ecrit un score. Verdict PAR DIMENSION en choix force (section 10). Aucun score global (REJ-0040).
- Contester une decision RATIFIEE NATHAN (D-008, D-009, D-038..D-042) = signaler un risque precis, pas un revote.
- Contester une autre decision actee = argument fort + alternative concrete.
- Toute affirmation factuelle de ta revue = sourcee ou marquee HYPOTHESE. Chaque reponse se termine par PREUVE: ou BLOCKED:.

## 1. MISSION
GRS = core d'entreprise autonome, cle en main, installable dans une infrastructure IA (LLM routes, RAG, noeuds via dashboard/Configuration). 10 modules M = departements virtuels communiquant via le core. Cible 1: entreprise renovation exterieure QC. Cible 2: SaaS PME QC (Loi 25 rehaussee). Doctrine: preuve avant declaration; zero fake done; zero stub. Execution integrale avec Claude Code selon PROOF STACK.

## 2. REGLES NON NEGOCIABLES (REG-01..13)
01 Preuve avant declaration (ledger). 02 Zero fake done/stub. 03 REJ-0040 verdicts par dimension. 04 CIV jamais auteur et juge. 05 Independance critique (aveugle, anonymise). 06 Un module a la fois, 100% prouve. 07 Contexte = ressource precieuse. 08 Frameworks embarques jamais figes (surclassement Q1-Q6, etendu aux MODELES via evals). 09 Securite par defaut. 10 Mention professionnelle fiscale obligatoire (M5). 11 Degradation gracieuse (mode horaire). 12 Organisation methodique + alignement fichiers-docs ENFORCE en CI. 13 Contenu externe = donnees jamais instructions (defense en profondeur, mode ombre).

## 3. ARCHITECTURE ET ORGANISATION (D-038 RATIFIEE)
C1 hote (README-EXIGENCES, fallback par manque) / C2 core + 8 services transversaux / C3 modules / C4 frameworks embarques / C5 surfaces / C6 donnees.
Arborescence: grs/ core/ (dont core/frameworks/<Nom> pour le partage 2+ modules) · Modules M/ avec M1..M10 etiquetes, chaque MX/ contient frameworks/<Nom-exact>/, src/, tests/, contracts/ (pacts), metrics/, docs/ · surfaces/ · docs/ (Diataxis + canon + ADR) · registries/ (frameworks.yaml, modules.yaml, metrics/, ledger jsonl hash-chaines) · .github/.
Exception: prerequis infra hote JAMAIS dans un module. Lint de structure = check requis: un framework mal range ne merge pas. GitHub 100%: CODEOWNERS/labels/milestones/releases PAR module, branches agent/mX-*, case PR "arborescence D-038 respectee".
8 services transversaux (D-010): Approval Engine unifie · Autorisation fine (OpenFGA candidat) · Audit/ledger · Gate Engine · Bus notifications · Memoire shim M10 (contrat reel gele D-014: event log, context packs, registres, Preflight/Postflight = loi du harnais) · Registre de metriques metrics-as-code · Observabilite (OTel GenAI + Langfuse).

## 4. METHODE D'EXECUTION — PROOF STACK v1.1 (D-039..042, RATIFIEES)
Profil: PROOF-Team (Q8). PREUVE:/BLOCKED: a chaque etape. Calibration au registre AVANT tout code. T3 humain seul: paiements, secrets prod, suppressions, publication, engagements.
Structuration: BMAD (defaut) + TDAD (argent/legal/securite) + Superpowers PINNEE (workflow story). Jamais deux methodologies lourdes sur la MEME story.
12 briques de methode au manifest Phase 0, activation AVEC preuve: Couche PROOF (hooks) · Superpowers · LiteLLM proxy (preuves A routes reelles / B passthrough) · equipe multi-postes (CIV_MODELS 3 vendors) · mini-SWE (story test -> .traj.json) · Sentinelle tandem · Canon Keeper tandem · Canon A1-A5 (<2K) · DSPy+GEPA offline (PR only) · LLMLingua-2 (docs seulement, JAMAIS code/diff/pack) · registres hash-chaines · eccAgentShield (zero finding critique).
EQUIPE (D-040, remplace tout roster anterieur): Orchestrateur = modele actif, signe SUR PIECES, ne se relit JAMAIS (code relu par 3 vendors # sien) · Architecte GLM-5.2 (revue AVANT code, ne code jamais) · Codeur long Kimi K2.7 · Codeur difficile Kimi K3 1M (titularisation apres firing test; aucun Kimi en revue de ses stories) · Codeur bulk DeepSeek V4 Pro · Codeur parallele Grok 4.5 (worktrees; jamais apparie Composer, xAI) · Reviewers aveugles x3 DeepSeek·Gemini 3.1 Pro·LongCat 2.0 (3 vendors # vendor codeur, SWAP CIV) · Pool Kimi·Qwen 3.7 Max·MiMo 2.5 Pro · Sentinelle DeepSeek+GLM (rouvre, ne valide jamais, jamais codeuse) · Canon Keeper Opus 4.8+gpt-5.5 (vendor OpenAI ajoute = decorrelation accrue).
PIPELINE PAR STORY A->G (D-041, seul chemin autorise): A pack scope + assignation (# Orchestrateur) + revue Architecte avant code -> B TDD RED/GREEN reel/REFACTOR, Sentinelle continue -> C gates locaux (lint, secrets, no-stub UN hit = bloque, sweep symboles) -> D PR+CI (jamais commit direct main; unitaires+e2e+couverture+secu+hash+no-fake-done) -> E revue aveugle 3x3 (prompt genere du template neutre, envoi simultane, verdicts scelles) -> F depouillement PAR SCRIPT (tous APPROVE + zero objection critique; sinon Delphi anonymise max 2 rounds -> arbitrage Orchestrateur sur pieces) -> G merge (registre horodate, gate doc declaratif, sweep Sentinelle).
FIN DE PHASE (v1.1): e2e REEL de chaque fonctionnalite + rapports (Synthetiseur, Sentinelle, Canon Keeper, test a froid) + revue aveugle 3x3 DU RAPPORT + signature Orchestrateur SUR PIECES. Non valide = pipeline ARRETE.
REGISTRES: 4 jsonl append-only HASH-CHAINES via ledger_append.py, jamais a la main. DONE sans preuve = rejete. Metriques de gouvernance = suite de tests de la methode; reassignations pilotees par donnees. Amendements = PR.
INTERDITS (hooks): stubs, TODO en diff, tests sans assertion, assert True, skip non journalise, donnees inventees, DONE partiel, affirmation sans source, --no-verify, commit direct main, force-push, auto-approbation, CLAUDE_CODE_SUBAGENT_MODEL global, compression code/diffs/packs. Mocks: tests/ et services externes seulement.
ANTI-DERIVE: 00-DIGEST <=400 tokens injecte par hook (10 tours + evenements + post-compaction); contexte propre par story; la memoire ameliore le chemin, les GATES garantissent les sorties.

## 5. MODULES M1-M10 (mini-fiches — plans = source du QUOI, D-007)
M1 Front Office IA: omnicanal zero perte; voix phases 0->5 jamais sautees; interdits absolus (prix/dates/engagements/aveux); missed-call rescue opt-in; EFVP majeure. Fondations D-023: Pipecat candidat (Flows = phases), LiveKit alternative; cibles <=800 ms p50 / <=1,5 s p95.
M2 Revenue CRM: aucun lead sans statut/owner/action; readiness gate M3; fusion doublons = humain; frontieres prix=M3 dates=M4 finance=M5.
M3 Estimation: anti-precision-inventee; photos faibles = prix BLOQUE; plancher rentable = alerte rouge; Monte Carlo; apprentissage estime-vs-reel. Fondations D-024: hierarchie reference d'echelle > multi-vues > mono a bornes larges (MAE ~0,45 m au mieux sans reference); Depth Pro/DA-V2/Metric3D candidats; guidage de capture = le levier.
M4 Field Ops: readiness avant cedule; VRP; meteo; GPS heures de travail seulement, client = lien tokenise; punch georepere; Work Completion Trigger -> cascade 6 modules; ecart = pending_review.
M5 FinanceCore: solde # argent disponible; taux fiscaux versionnes SOURCES sinon blocage; fiscalite = RAG jamais fine-tunee; F6 = Nathan+MFA; F7 = Nathan+CPA; CFO Decision Report 25 pts; adapters read-only -> dry-run -> write gated; mention pro partout.
M6 Material Control: price book source sinon FALLBACK; PO -> reception -> stock localise audite; variance sans accusation ("jamais vol automatique"); M6 ne paie jamais; employe ne voit pas les couts.
M7 Marketing (PREMIER MODULE, D-008): CMO IA; 41 frameworks candidats; D-009 gratuit ON / payant OFF sauf Local Falcon; validation 0-6; backlinks jamais bout-en-bout; site Quadruple A; GEO par surface (D-013); MMM = M8 construit, M7.11 consomme (PyMC-Marketing defaut D-012); build en 4 vagues (fondations -> contenu -> ROI minimal -> GATED M1/M4/M8).
M8 Analytics: lecture seule par snapshots Parquet -> DuckDB -> couche semantique; le LLM ne calcule JAMAIS un chiffre; alertes = signaux XmR; rapports epingles a snapshot_id; proprietaire du MMM.
M9 Strategic Intelligence: 15 elements obligatoires par sortie; jamais chiffre/capacite inventes; Council d'agents sous Supervisor deterministe; War Room; consomme le registre de metriques; position tardive.
M10 Memoire: rien n'est trop petit; Forge Memory + GRS Business Memory separees par permissions; 5 regles de non-oubli; 15 composants; Preflight 16 etapes + Postflight = loi du harnais (D-014).
INVARIANTS: sources de verite sans empietement; statuts STUB/PARTIAL/GATED_*/NEEDS_HARDENING/DONE_VERIFIED; l'IA propose+source+score, ne decide jamais la verite finale; validation humaine graduee; anti-hallucination totale; employes jamais accuses/profiles/exposes aux couts.

## 6. FONDATIONS TECHNIQUES (Passes 01-05, preuvees — voir Annexes C-G du PDF)
Securite agentique REG-13 (OWASP LLM01, EchoLeak; provenance, mode ombre, budgets LLM coupe-circuit) · Quorum consensus D-017 (unanimite visee, arbitrage Nathan documente, revote sur sections modifiees) · Contrats geles = pacts executables D-015 (can-i-deploy a G4/D du pipeline) · Observabilite OTel GenAI + Langfuse D-016 · Retention fiscale 6 ans (Revenu Quebec) vs minimisation Loi 25 par classe · Francais d'abord (Loi 96) · Mobile D-018: React Native+Expo, PowerSync self-host (lectures partitionnees par Sync Rules, ecritures via API GRS server-authoritative), pas de CRDT, punch offline signe (R-020) · Outbox transactionnel + consommateurs idempotents D-019 · Migrations expand-contract D-020 · pgBackRest PITR + restauration hebdo prouvee, RTO = duree mesuree D-021 · Identite Zitadel (~100 MB, event-source, multi-tenant) apparie a OpenFGA D-022 · Voix D-023 · Vision D-024 · API D-025 (RFC 9457, Idempotency-Key, backoff+jitter — 3 retries x 3 couches = 243x) · Threat modeling 4 questions + STRIDE + LINDDUN D-026 · n8n borne D-027 · Compose mono-noeud D-028 · RAG hybride+rerank D-029 (Recall@5 0,816 vs 0,587 dense; BM25 > dense sur financier; mesurer par collection) · Evals goldens en CI D-030 (build rouge sur regression; Promptfoo = surclassement de modeles) · Redaction PII Presidio avant tout cloud D-031 (chunks inclus; fuite 100% -> 7,5% pattern local-d'abord) · Sorties structurees 3 couches + echappatoire obligatoire sur tout enum D-032 (schema sans issue = fabrication) · WCAG 2.2 AA surfaces D-033 · Hygiene tables D-034 · Supply chain D-035 (SHA actions, lockfiles geles, cooldown, hash frameworks/poids; LiteLLM compromis PyPI 03/2026 -> epingle version+hash) · Sandbox micro-VM Firecracker pour code agent D-036 · Runbook incident D-037.

## 7. RISQUES OUVERTS R-001..R-030 (registre complet au PDF)
Cles: R-001 xAI correlation · R-002 rotation cle passerelle (P0-4 bloquant) · R-015 injection indirecte M1/M7/M6 · R-021 latence vocale realiste · R-022 mesure photo sans echelle · R-024 SW1 SPOF · R-027 adoption terrain · R-028 supply chain (LiteLLM) · R-030 scripts de methode = points de confiance (methodologie-as-code).

## 8. DECISIONS D-001..D-042
Ratifiees Nathan (signaler un risque, pas revoter): D-008 M7 premier · D-009 activation frameworks M7 · D-038 arborescence · D-039 PROOF STACK · D-040 equipe · D-041 pipeline A->G · D-042 registres hash-chaines + 12 briques methode. Passe PERFECTION: D-043 profils d'installation (infra-existante / starter auto-deploye) · D-044 gate de taille de story calibre METR (cible <=1 h, cap dur 3 h, decoupage obligatoire au-dela) · D-045 Phase C consensus outille (consensus_run.py = brique no 13) + Phase 0 reordonnee avec marquage BLOQUANT-STORY-1 · story pilote = M7-S000 en mode ombre. Amendees: D-002 -> D-039; D-003 -> D-040. Toutes les autres (D-001, D-004..D-037): actees, contestables avec argument fort + alternative.

## 9. QUESTIONS SOUMISES AU VOTE
Q1 EQUIPE: la table D-040 telle quelle? Sinon reassignation justifiee (respecter CIV + R-001 + regle "aucun Kimi en revue de Kimi").
Q2 ORDRE DES MODULES apres M7. Proposition: M1 -> M2(rehausse) -> M4 -> M3 -> M6 -> M8 -> M5 -> M9; M10 = shim Phase 0 puis module complet (position du build complet a voter).
Q3 TROUS M7: (a) WhatsApp/SMS officiel payant ou exclu? (b) annuaires NAP: campagne ponctuelle + audit trimestriel? (c) repartition Local Falcon vs OneGlanse? (d) Metabase vs dashboards M7.12? (e) CRO PostHog (4vCPU/16GB, R-012) tard ou alternative legere?
Q4 FRAMEWORKS ADDITIONNELS par module (nom, role, licence, justification). Champ libre.
Q5 RISQUES MANQUANTS (au-dela de R-001..R-030). Champ libre.
Q6 SHIM M10: le noyau (event log, context packs, registres, Preflight/Postflight) suffit-il pour la Phase 0? Manques?
Q7 LICENCE DU PRODUIT GRS: proprietaire (defaut propose, enjeu SaaS) vs ouverte/duale. Position + justification.
Q8 PROFIL: PROOF-Team confirme? (repli Solo = rigueur reduite annoncee).
Q9 STORIES TRIVIALES: creer une classe objective (docs/config-only, <=N lignes, zero logique) a profil de revue reduit ANNONCE et journalise? Position + criteres proposes. (R-032: ~10+ appels modele par story en profil complet.)

## 10. FORMAT DE VERDICT OBLIGATOIRE
Pour CHACUNE des 5 dimensions, choix force APPROUVE ou REJETE + justification (3 lignes max):
1 EXACTITUDE · 2 FAISABILITE · 3 SECURITE · 4 COMPLETUDE · 5 RISQUES.
Puis: VERDICT FINAL (APPROUVE / APPROUVE AVEC RESERVES / REJETE) + reserves numerotees + reponses Q1-Q8.
Depot SCELLE. Depouillement PAR SCRIPT. Interdits: score numerique global; approbation sans justification; copier la formulation du pack comme argument; verdict sans PREUVE: ou BLOCKED: final.

FIN DU PACK v2.1. Reference detaillee: GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf. Ce pack est distribue et depouille par consensus_run.py (verdicts JSON scelles, tally par script).
