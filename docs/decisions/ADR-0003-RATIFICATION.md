# ADR-0003 — Ratification du consensus Phase C (décisions Nathan, T3)

**Statut :** Accepted (T3 — autorité Nathan)
**Date :** 24 juillet 2026
**Contexte :** consensus Phase C APPROVED 11/11, 9 vendors, 0 objection critique. Ce document
tranche les 9 questions et devient l'autorité de décision pour la suite (immuable — toute
révision = nouvel ADR).
**Transcription :** à verser au registre PROJET par l'Orchestrateur via `ledger_append.py`
(type=decision), après quoi les stories qui en découlent peuvent s'ouvrir.

---

## Décisions ratifiées

### Q1 — Roster / CIV : RATIFIÉ avec règle anti-deadlock
Le roster D-040/D-047 est adopté tel quel. **Ajout obligatoire (objection DeepSeek, légitime) :**
règle d'escalade documentée — si les 3 reviewers non-Kimi requis pour une revue sont
simultanément indisponibles, le pipeline N'EST PAS bloqué : il escalade à Nathan (arbitrage T3
sur pièces) plutôt que d'attendre indéfiniment ou de violer le CIV. La table de substitution
(quel modèle remplace quel rôle en cas d'indisponibilité) est pinnée au registre avant la
première story de M7. Correction de nommage : « MiMo-Pro-V2 » et « MiMo 2.5 Pro » désignent le
même modèle — nom canonique à fixer au registre.

### Q2 — Ordre des modules : RATIFIÉ
M7 → M1 → M2 (rehaussé) → M4 → M3 → M6 → M8 → M5 → M9. M10 : shim en Phase 0 (déjà fait),
**build complet après M8** (position Qwen — mémoire stabilisée avant analytique avancée, la plus
prudente). Sans impact Phase 0.

### Q3a — WhatsApp/SMS : INCLUS derrière feature-flag OFF par défaut
Position Grok. Le canal SMS/WhatsApp officiel est implémenté (code réel, testé, prouvé — jamais
un stub), mais livré derrière un feature-flag désactivé par défaut. Aucun déploiement ne l'active
sans décision explicite. Applique D-009 (payant OFF par défaut) à un canal. Justification :
crédibilité PME + taux de réponse SMS rénovation QC, sans imposer la complexité réglementaire
A2P/consentement à tout hôte.

### Q3b — Annuaires NAP : RATIFIÉ (unanime)
Campagne ponctuelle + audit trimestriel.

### Q3c — Local Falcon : RATIFIÉ
Local Falcon prioritaire (source payante autorisée D-009). OneGlanse = secondaire optionnel,
activable si licence OK, jamais prérequis.

### Q3d — Metabase vs dashboards maison : dashboards M7.12 NATIFS d'abord
Décision alignée sur la contrainte de portabilité (voir Décision transversale ci-dessous) :
Metabase est un service lourd supplémentaire pour l'hôte. Les dashboards natifs légers vivent
DANS le produit, se déploient partout, lisent la couche sémantique M8. Metabase reste une brique
optionnelle qu'un hôte puissant peut activer pour l'exploration interne — jamais un prérequis.
Évite la dette d'infrastructure (objection LongCat).

### Q3e — CRO/PostHog : RATIFIÉ
Alternative légère d'abord (Plausible/Umami self-host ou events server-side). PostHog tardif
(post-ROI, vague 3+) car sa charge 4 vCPU/16 GB est à éviter en Phase 0.

### Q4 — Frameworks additionnels : AUCUN ajout bloquant
Les 41 candidats M7 (D-009) suffisent. Suggestions notées comme enrichissements NON bloquants,
versées au backlog d'évaluation Q1-Q6 : Pact (contract testing — pertinent vu D-015), OpenCV
(prétraitement M3), OpenTelemetry (déjà D-016), Pipecat/LiveKit (déjà D-023), Depth Pro (déjà
D-024), DuckDB+PyMC (déjà D-012/D-029). Aucune approbation conditionnée à un ajout.

### Q5 — Risques manquants : 3 RISQUES AJOUTÉS au registre
- **R-037 — Coût/token LLM non plafonné** (5 reviewers). Mitigation : coupe-circuit dur au niveau
  de la passerelle, budgets par clé, escalade à 100 %. Déjà prévu (D-016) — rendu explicite et
  vérifié pour TOUS les appelants (pas seulement l'Orchestrateur).
- **R-038 — Indisponibilité des modèles du roster** (5 reviewers). Mitigation : table de
  substitution pinnée (Q1) + fallbacks déclarés par rôle + swap journalisé (déjà démontré en
  pratique : GLM→Kimi, LongCat→Qwen).
- **R-039 — SPOF humain Nathan / charge d'arbitrage** (4 reviewers). Mitigation : budget de
  validation borné dans le temps (un créneau quotidien pour vider la file T3, pas de vigilance
  permanente) ; file T3 priorisée par impact (argent/légal remontent, le reste attend) ; droit
  explicite de laisser la file s'accumuler — le système échoue-fermé, il attend, il ne se dégrade
  pas. Aucune IA ne porte une frontière T3 à la place de Nathan : c'est le point entier.

### Q6 — Shim M10 suffisant Phase 0 : RATIFIÉ (unanime)
Compléments versés au backlog Phase 0 (enrichissements, non bloquants) : checksum d'intégrité des
context packs, rétention/purge Loi 25, budget token coupe-circuit au Preflight, schéma de
migration shim → module complet.

### Q7 — Licence : PROPRIÉTAIRE (unanime)
Licence propriétaire. Clause duale (frameworks non-cœur) évaluable après PMF, pas avant M7 vague 2.
Justification : SaaS PME QC + Loi 25 + protection PI.

### Q8 — PROOF-Team : RATIFIÉ (unanime)
Profil PROOF-Team confirmé. Solo interdit sauf matrice de dégradation explicite et journalisée.

### Q9 — Stories triviales : NON TRANCHÉE DANS CETTE SYNTHÈSE
La synthèse générée s'arrête à Q8 ; Q9 n'y figure pas. **Décision Nathan par défaut, indépendante
du consensus :** créer une classe « story triviale » objective = docs/config uniquement, zéro
logique exécutable, ≤ 20 lignes changées. Revue réduite (1 reviewer vendor-distinct au lieu de
3x3) MAIS gates déterministes complets maintenus (lint, secrets, no-stub, ledger). Jamais
applicable à du code, une migration, un schéma, ou quoi que ce soit touchant argent/légal/sécurité.
Le seuil et la classification sont eux-mêmes vérifiés par script, pas déclarés par un modèle.

---

## Décision transversale — PORTABILITÉ (autorité Nathan, réaffirmée)

**OPSYS-AI ne dépend de RIEN de l'infrastructure personnelle de Nathan.** Le produit doit
fonctionner sur n'importe quelle infrastructure IA cochant les prérequis (passerelle LLM 3 tiers,
RAG/vectordb, PostgreSQL, stockage). Conséquences contraignantes, vérifiées en CI :
- Zéro chemin absolu local (`/media/pc1/...`) dans le cœur du produit — uniquement dans les
  scripts d'amorçage propres à la machine de Nathan, jamais dans `core/` ou les modules.
- Zéro `docker inspect` ou commande Docker locale pour obtenir un secret ou un endpoint dans le
  cœur : tout accès à la passerelle passe par `config.ini` + coffre OS fournis par l'HÔTE.
- Le profil « infra-existante » (ADR-0002) est le mode de référence ; le profil « starter »
  (auto-déploiement) reste une commodité, jamais une dépendance.
- Un test de portabilité (installation sur machine vierge, aucun artefact de la machine de Nathan)
  fait partie de la définition de complétion (rappel : SIM-4 du plan).

---

## Ce que cet ADR débloque

Une fois transcrit au registre : ouverture des stories P0-2b (digest LiteLLM + SBOM), P0-5
(dashboard, à découper), P0-7 (EFVP Loi 25), P0-9 (backups + IdP), P0-10 (harnais e2e), puis M7
vague 1. Ordre recommandé inchangé : ratification → P0-2b → P0-10 → P0-5/P0-7/P0-9 en parallèle
contrôlé → M7 vague 1.
