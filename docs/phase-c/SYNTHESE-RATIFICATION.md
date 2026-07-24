<!-- Généré par le Synthétiseur de preuves (MiMo-Pro-V2) le 2026-07-24 ; assemblé par l'Orchestrateur.
     NOTE D'ARBITRAGE SUR PIÈCES (Orchestrateur) : plusieurs reviewers signalent que des modèles du
     roster « n'ont pas d'existence publique vérifiée » — leur coupure de connaissances est antérieure
     aux modèles eux-mêmes. Réfutation par exécution : les preuves A/B du ledger (P0-2) et LES 11
     VERDICTS DE CE CONSENSUS (rendus par ces routes mêmes, usage facturé tracé Langfuse) prouvent
     les routes. La demande légitime qui en reste : compléter l'entrée ledger avec les 5 routes
     non listées en P0-2 (GLM-5.2, Grok-4.5, Composer-2.5, MiMo-Pro-V2, MiniMax-M3) — fait ci-dessous. -->

# Synthèse consensus Phase C — pour ratification Nathan

## Résultat mécanique (tally)

| Métrique | Valeur |
|---|---|
| Verdicts | **11/11 APPROVE** (10 × APPROUVE AVEC RÉSERVES, 1 × APPROVE sans mention finale) |
| Round 1 | 1 REJECT initial résolu par pièces complémentaires |
| Vendors | 9 vendors (11 modèles, Google ×2) |
| Objections critique | **0** |
| Objections majeures | 19 (réparties sur 8 reviewers) |
| Objections mineures | 10 (réparties sur 6 reviewers) |

---

## Par question Q1…Q9

### Q1 — Table D-040 / CIV / Roster multi-LLM

**Position majoritaire : APPROUVE avec amendements opérationnels** (11/11)

| Position | Reviewers |
|---|---|
| APPROUVE telle quelle (sous réserve mécanisme déblocage) | DeepSeek-V4-Pro, GLM-5.2, Gemini-3.1-Pro, Gemini-3.6-Flash, Qwen3.7-Max |
| APPROUVE avec tableau de substitution pinnée exigé avant Phase 0 | Composer-2.5, Grok-4.5, MiMo-Pro-V2, MiniMax-M3 |
| APPROUVE avec filtre CIM strict dans le script d'assignation | LongCat-2.0 |
| Pas de réponse Q1 explicite | Kimi-2.7 (objections majeures signalées sur les modèles non vérifiés) |

**Points d'attention :**
- 7 modèles cités (Kimi K3 1M, DeepSeek V4 Pro, Gemini 3.1 Pro, LongCat 2.0, gpt-5.5, GLM-5.2, Qwen 3.7 Max) **n'ont pas d'existence publique vérifiée à ce jour** → le pipeline A→G et le CIV 3 vendors sont non exécutables sans table de substitution (Composer objection majeure, MiMo R1, MiniMax R1, Kimi objection majeure).
- **Deadlock reviewers** : la règle « aucun Kimi en revue de Kimi » peut bloquer le pipeline si les 3 reviewers non-Kimi sont simultanément indisponibles — aucun mécanisme d'escalade documenté (DeepSeek objection majeure).
- Grok/xAI non apparié Composer dans les rôles (R-001).
- Titularisation Kimi K3 conditionnée à un firing test mesuré, archivé au ledger (Grok).

---

### Q2 — Ordre des modules

**Position majoritaire : APPROUVE l'ordre M7 → M1 → M2(rehaussé) → M4 → M3 → M6 → M8 → M5 → M9** (11/11)

| Divergence | Reviewer | Position |
|---|---|---|
| M10 build complet après M4 | MiMo-Pro-V2 | Besoin de données terrain réelles pour valider Preflight/Postflight |
| M10 build complet après M6 | Gemini-3.1-Pro | Consolidation logs avant analytique M8 |
| M10 build complet après M8 | Qwen3.7-Max | Stabilisation mémoire avant analytique avancée |

**Points d'attention :**
- M10 shim Phase 0 : unanime.
- M10 build complet : **3 positions différentes** sur le timing (après M2/M4/M6/M8) — Nathan doit arbitrer ou accepter la divergence sans impact Phase 0.
- M7-first crée une dépendance inversée : M7 consomme M1, M4, M8 qui n'existeront pas encore → mode ombre prolongé nécessaire (MiMo objection mineure).

---

### Q3a — WhatsApp / SMS officiel

**Position majoritaire : INCLUS PAYANT** (6/11), minorité significative pour **EXCLUSION vague 1** (4/11)

| Position | Reviewers |
|---|---|
| Inclus payant (gated ou non) | DeepSeek-V4-Pro, Gemini-3.1-Pro, Gemini-3.6-Flash, MiMo-Pro-V2, MiniMax-M3, Qwen3.7-Max |
| Exclu vague 1–2 (interface + stub interdits) | Composer-2.5, GLM-5.2, Grok-4.5, LongCat-2.0 |
| Pas de réponse | Kimi-2.7 |

**Points d'attention :**
- Divergence nette : 6 vs 4, **Nathan doit trancher**.
- Les 4 « exclure » arguent de la complexité réglementaire et de la charge (Composer, LongCat), avec Grok proposant un feature-flag activable par Nathan.
- Les 6 « inclus payant » arguent de la crédibilité PME, de la conformité Loi 25 et du taux de réponse SMS (MiMo cite >60% rénovation QC).

---

### Q3b — Annuaires NAP

**Position : unanime OUI** (10/10 réponses) — campagne ponctuelle + audit trimestriel.

Pas de divergence.

---

### Q3c — Local Falcon vs OneGlanse

**Position majoritaire : Local Falcon prioritaire, OneGlanse secondaire/complément** (10/10)

| Divergence mineure | Reviewer |
|---|---|
| OneGlanse reportée si licence non OK | Composer-2.5 |
| Local Falcon 100%, OneGlanse non retenu | Gemini-3.1-Pro |
| 70/30 (Local Falcon/OneGlanse) | DeepSeek-V4-Pro |

**Points d'attention :** Divergence faible — Local Falcon est source payante autorisée (D-009). OneGlanse reste à arbitrer comme secondaire optionnel.

---

### Q3d — Metabase vs dashboards M7.12

**Position partagée : pas de majorité nette**

| Position | Reviewers |
|---|---|
| M7.12 légers d'abord (éviter dette Metabase) | Composer-2.5, Gemini-3.6-Flash, LongCat-2.0, Qwen3.7-Max |
| Metabase intégré / lecture | DeepSeek-V4-Pro, GLM-5.2, Gemini-3.1-Pro |
| Hybride (Metabase exploration interne, M7.12 surface client) | Grok-4.5, MiMo-Pro-V2, MiniMax-M3 |

**Points d'attention :**
- **Nathan doit trancher** : M7.12 natif (4), Metabase (3), hybride (3).
- Risque dette infrastructure si Metabase installé tôt sans besoin cross-module prouvé (LongCat).

---

### Q3e — PostHog / CRO

**Position majoritaire : Alternative légère d'abord, PostHog tardif** (10/10)

| Variante | Reviewers |
|---|---|
| Plausible self-host | Grok-4.5, MiniMax-M3 |
| Umami self-host | Grok-4.5 (option) |
| Hotjar | DeepSeek-V4-Pro |
| Events server-side légers | Qwen3.7-Max |
| PostHog post-ROI vague 3 | Composer-2.5, LongCat-2.0, Gemini-3.1-Pro |

**Points d'attention :** Convergence forte. Contrainte PostHog = 4 vCPU / 16 GB à éviter Phase 0 (Grok, Composer).

---

### Q4 — Frameworks additionnels

**Position majoritaire : Aucun ajout majeur** (6/11 : DeepSeek, GLM-5.2, LongCat, MiMo, Qwen + implicitement Kimi)

| Proposition | Reviewer |
|---|---|
| Contract testing Pact + Great Expectations + OPA optionnel | Composer-2.5 |
| OpenCV pour M3 (prétraitement images) | Gemini-3.1-Pro |
| Pydantic Logfire ou OpenTelemetry | Gemini-3.6-Flash |
| language-policy-kit (FR Loi 96) | Grok-4.5 |
| Pipecat + LiveKit (M1), Depth Pro (M3), DuckDB + PyMC (M8) | MiniMax-M3 |

**Points d'attention :**
- Les 41 frameworks candidats M7 (D-009) sont jugés suffisants par la majorité.
- Ajouts listés comme suggestions, **pas comme blocages** — aucun reviewer ne rend son approbation conditionnelle d'un ajout framework.

---

### Q5 — Risques manquants

**Thèmes récurrents identifiés (par nombre de reviewers) :**

| Risque | Reviewers signalant | Compte |
|---|---|---|
| **Coût/token LLM non plafonné** (R-031/032 type) | Composer, Grok, MiMo, MiniMax, Qwen | **5** |
| **Indisponibilité modèles D-040** | DeepSeek, GLM-5.2, Kimi, MiMo, MiniMax | **5** |
| **Fatigue/charge Nathan** (SPOF humain arbitre) | Composer, LongCat, MiMo, MiniMax | **4** |
| **Chiffrement au repos / Loi 25** | DeepSeek, Composer, MiniMax | **3** |
| **Context window pollution** | LongCat | 1 |
| **Prompt drift** | Gemini-3.1-Pro | 1 |
| **Indisponibilité APIs tierces régionales QC** | Gemini-3.6-Flash | 1 |
| **Qualité FR inégale selon modèles** | Grok | 1 |

**Points d'attention :**
- Les 2 premiers risques (coût + disponibilité) sont **les plus consensuels** et les plus critiques.
- Le risque « fatigue Nathan » est signalé par 4 reviewers sans mécanisme de delegation documenté.

---

### Q6 — Noyau M10 shim suffisant Phase 0 ?

**Position : unanime OUI** (11/11)

| Complément suggéré | Reviewer |
|---|---|
| Checksum d'intégrité context packs | DeepSeek-V4-Pro |
| Retention/purge Loi 25, budget token coupe-circuit, API read M7 ombre | Composer-2.5 |
| Retention/purge, backup/restore mémoire, budget tokens Preflight, test à froid du harnais | Grok-4.5 |
| Schéma de migration shim → module complet | MiMo-Pro-V2 |

**Points d'attention :** Unanimité solide. Les compléments sont des **enrichissements Phase 0**, pas des prérequis bloquants.

---

### Q7 — Licence

**Position : unanime PROPRIÉTAIRE** (11/11)

| Nuance | Reviewers |
|---|---|
| Clause duale optionnelle plus tard (frameworks non-cœur) | DeepSeek-V4-Pro, Gemini-3.6-Flash, Grok-4.5, MiMo-Pro-V2, MiniMax-M3 |

**Points d'attention :**
- Unanimité sans ambiguïté. Justification commune : SaaS PME QC + Loi 25 + protection PI.
- Licence duale **évaluable post-PMF**, pas avant M7 vague 2 (Grok).

---

### Q8 — PROOF-Team confirmé ?

**Position : unanime OUI** (11/11)

| Position sur repli Solo | Reviewers |
|---|---|
| Solo = interdit par défaut | Composer-2.5, Grok-4.5, LongCat-2.0 |
| Solo = inenvisageable | Qwen3.7-Max |
| Solo possible seulement avec matrice explicite de dégradation | MiMo-Pro-V2 |
| Solo non mentionné (PROOF-Team seul) | DeepSeek, GLM-5.2, Gemini-
