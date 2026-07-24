# RECONCILIATION.md — Traçabilité des corrections au paquet v0.2

Ce paquet ForgeAI PROOF IDE System v0.2-DRAFT a été corrigé et complété le 23 juillet 2026 avec
« l'équipe de modèle la plus à jour » (mandat explicite de Nathan). Chaque changement listé ici,
avec sa source — rien de silencieux.

## Corrections factuelles

| Élément | Brouillon v0.2 disait | Corrigé en | Source |
|---|---|---|---|
| Modèle canon keeper | Gemini 3.5 Flash | **Gemini Flash 3.6** | Confirmation directe et répétée de Nathan dans la conversation source : « Gemini 3.6 flash est un modèle puissant à ne pas sous-estimer et il s'occupe de la gestion de la docs et canon » |
| Statut du paquet | Brouillon à valider | **Validé** | Instruction explicite de Nathan : « règle le tout » |

## Rôles ajoutés (absents du brouillon v0.2, présents dans l'équipe établie de Nathan)

| Rôle | Modèle | Vendor | Pourquoi absent du brouillon |
|---|---|---|---|
| `forge-bulk-coder` | Kimi Code 2.7 | Moonshot AI | Le brouillon n'avait qu'un seul rôle codeur (`hard_coder`). Nathan distingue explicitement par difficulté : Kimi K3 = compliqué, Kimi Code 2.7 = facile/standard. Rôle ajouté en respectant le patron existant (gateway_alias, required_capabilities) plutôt que de forcer Kimi Code 2.7 dans `hard_coder`. |
| `forge-sentinelle-a` / `forge-sentinelle-b` | DeepSeek V4 Pro + GLM-5.2 (tandem) | DeepSeek + Zhipu | Le brouillon mentionnait « Sentinelle : tandem de modèles distincts configuré » (§8.2 FORGE_METHOD.md) sans jamais préciser lesquels. Le tandem DeepSeek+GLM était déjà établi par Nathan pour ce rôle précis (contrôle continu, peut rouvrir une story, ne valide jamais) — comblé, pas inventé. |
| `forge-parallel` | Grok 4.5 | xAI | Rôle de parallélisme/worktrees absent du schéma du brouillon. Ajouté avec la note CIV obligatoire : Grok 4.5 sert aussi de modèle natif Cursor — double rôle qui exige une exclusion de sa propre revue quelle que soit la porte d'entrée. |
| Pool de rotation | + MiniMax M3 | MiniMax | Absent du brouillon. Rôle établi par Nathan : données synthétiques, tests E2E, tâches volume — ajouté au pool plutôt qu'un rôle dédié séparé, cohérent avec sa nature d'utilitaire plutôt que de spécialiste unique. |

## Question laissée ouverte dans le plan GRS — résolue ici

Le plan maître GRS (section 16bis.2, Annexe J) avait flaggé explicitement une question NON RÉSOLUE :
Gemini Flash 3.6 (gestion docs/canon) et un tandem imaginé « Canon Keeper Opus 4.8 + gpt-5.5 »
touchaient tous deux le canon — répartition proposée (bibliothécaire/comité) mais jamais confirmée
par Nathan.

**Ce brouillon ForgeAI tranche la question autrement**, et de façon plus propre : il n'a qu'UN SEUL
rôle `forge-canon-keeper`, assigné à Gemini Flash 3.6, `write_policy = proposal_only` (ne fusionne
jamais seul). La fonction d'arbitrage cross-story que le tandem imaginé devait couvrir est déjà
assurée par le mini-agent `forge-drift-checker` (FORGE_METHOD.md §7.1), qui tourne après compactage
et avant merge — l'Orchestrateur natif (Claude Code) joue ce rôle dans sa propre session, sans alias
séparé.

**Résolution retenue :** un seul Canon Keeper (Gemini Flash 3.6), pas de tandem. Le concept de
« Canon Keeper Opus+gpt-5.5 » du plan GRS est retiré au profit de cette architecture plus propre
(une seule autorité par fonction, principe §0.1 du FORGE_METHOD.md). À faire : mettre à jour le plan
GRS (Annexe J, section 16bis.2) pour refléter cette résolution lors de la prochaine passe.

## Décision produit : GitHub Copilot natif remplace VS Code

Recherche effectuée le 23 juillet 2026 : GitHub Copilot a deux surfaces distinctes — le **mode
agent** (synchrone, dans l'éditeur VS Code/JetBrains) et le **coding agent / cloud agent**
(asynchrone, natif sur github.com, déclenché par l'assignation d'une issue à `@copilot`, tourne en
sandbox GitHub Actions, lit `.github/copilot-instructions.md`, ouvre une PR).

Décision : le 4e adaptateur cible GitHub Copilot natif (github.com) plutôt qu'une installation VS
Code locale. Deux usages distincts documentés dans `IMPLEMENTATION_SPEC.md` §8.4 :
- **Gouvernance** (cockpit) : Copilot Chat web, revue de PR, suivi des checks — zéro installation.
- **Coding agent** (construction, optionnel) : traité comme un 5e front sous les mêmes règles PROOF
  que Cursor ou Claude Code — jamais un passe-droit.

## Ce qui N'A PAS été touché

`VISION.md` (hors la ligne de version modèle), la structure complète d'`IMPLEMENTATION_SPEC.md`
(modules A-K, phases 0-8, matrice de tests, threat model), et l'intégralité de la méthode dans
`FORGE_METHOD.md` (invariants, cycle de vie de story, TDD/TDAD, contexte C0-C3, gates, ledger)
restent tels que reçus — c'est un travail de conception déjà rigoureux, les corrections ci-dessus
sont chirurgicales, pas une réécriture.

## Ce qui reste à Nathan

1. Ajouter les clés LiteLLM réelles (`forge secrets set litellm`) — jamais dans ce paquet.
2. Remplir les `model_id` exacts (alias LiteLLM propres à son infrastructure) dans `config.ini` —
   les `vendor` sont renseignés, les `model_id` ne le sont pas : ce sont des détails d'infrastructure
   que je n'ai pas et n'invente pas.
3. Les 10 décisions humaines listées à IMPLEMENTATION_SPEC.md §22 (nom final, licence, stratégie
   Superpowers fork/overlay, etc.) restent ouvertes — ce paquet ne les tranche pas à sa place.
4. Confirmer ou corriger la résolution Canon Keeper ci-dessus avant que le plan GRS soit mis à jour
   en conséquence.
