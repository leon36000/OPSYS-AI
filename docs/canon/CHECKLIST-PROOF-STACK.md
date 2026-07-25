# Checklist PROOF STACK §9 — état vivant (P0-10b)

> Vue d'état assemblée depuis les registres (`registries/ledger/*.jsonl`) — v1 manuelle, générateur
> automatique au backlog (REG-12 : les vues devraient être générées). Chaque ligne renvoie à une
> preuve au ledger ou à une PR mergée. Statuts admis : DONE-avec-preuve / BLOCKED-avec-raison.
> Dernière mise à jour : 2026-07-25 (P0-10b).

## Calibration
| Item | Statut | Preuve |
|---|---|---|
| Calibration au registre AVANT tout code | DONE | decision `CALIBRATION` (PR #2) |
| Profil PROOF-Team confirmé | DONE | ADR-0003 Q8 (ratifié Nathan) |

## Les 12 briques du manifest (D-042)
| # | Brique | Statut | Preuve |
|---|---|---|---|
| 1 | Couche PROOF (hooks git + session, registres) | DONE | hooks globaux actifs, guard rc=2 prouvé (P0-3/P0-6), 4 chaînes vérifiées en CI |
| 2 | Superpowers (workflow épinglé) | DONE | actif côté Orchestrateur (brainstorming/plans/TDD) ; overrides proof-review/proof-done appliqués sur toutes les stories |
| 3 | LiteLLM proxy — preuves A (routes réelles) / B (passthrough crew-*) | DONE | preuve `P0-2` + complément 5 routes (consensus) ; image épinglée par digest (P0-2b, PR #27) |
| 4 | Équipe multi-postes (CIV 3 vendors) | DONE | 8 revues scellées, sceau prompt_sha256, tally déterministe ; 4 REJECT round-1 fondés = la revue mord |
| 5 | mini-SWE (exécuteur hors-session) | BLOCKED | non installé — l'appel-direct `crew_dispatch` couvre le besoin ; réévaluer si stories >1 fichier simultanés |
| 6 | Sentinelle tandem | DONE | daemon actif (DeepSeek+Qwen3.7, ADR-0003), redémarrée post-rotation, findings traités (ex. cli.py ForgeAI) |
| 7 | Canon Keeper / Documentaliste | DONE (partiel) | Qwen3.8-Max opérationnel contexte court ; 408 gros contexte → swap R-038 vers Qwen3.7 journalisé (preuve P0-7) |
| 8 | Canon A1-A5 (<2K, digest) | DONE | 00-DIGEST ≤400 tokens + hooks inject (kit) ; docs/canon/ instancié (REGLES + cette checklist) |
| 9 | DSPy + GEPA (offline, PR only) | BLOCKED | non installé — Optimization Lab = chantier PROOF-IDE System (dépôt séparé), jamais bloquant Phase 0 |
| 10 | LLMLingua-2 (docs seulement) | DONE | pack_build opérationnel ; packs de revue JAMAIS compressés (PROOF_COMPRESS=0 systématique, piège journalisé) |
| 11 | Registres hash-chaînés | DONE | `ledger_append.py verify` = 4 chaînes OK, vérifié à chaque CI ; falsification testée (R-030) |
| 12 | eccAgentShield (scan findings critiques) | BLOCKED | non installé — couverture partielle par gitleaks+GitGuardian+SonarCloud+guard hooks ; évaluation au backlog |

## Équipe — firing tests & titularisations (sur stories réelles)
| Poste | Modèle | Statut | Preuve |
|---|---|---|---|
| Codeur facile/bulk | Kimi-2.7 | TITULARISÉ | 5 stories RED→GREEN (P0-1, M7-S000, P0-8, P0-10a, P0-7) |
| Architecte | Kimi-K3 | TITULARISÉ (réserve codeur gros volume : 2 timeouts mesurés) | avis M7-S000 + P0-10a (8 ajustements intégrés) |
| Reviewers scellés ×3 | DeepSeek-V4-Pro · Gemini-3.1-Pro · Qwen3.7-Max | TITULARISÉS | 8 revues, 4 REJECT fondés vérifiés |
| Synthétiseur / pool | MiMo-Pro-V2 | OK | avis P0-8, synthèse Phase C |
| Documentaliste | Qwen3.8-Max | OK contexte court (408 gros contexte — R-038) | passe P0-7 |
| 5e front async | GitHub Copilot coding agent | **TITULARISÉ (T0/T1 bornés)** | issue #29 → PR #30 : 8/8 critères, trio 3/3, merge 660b95f |
| Écartés (données) | GLM-5.2 (architecte), LongCat-2.0 (gros packs) | ÉCARTÉS | fuite reasoning ×2 ; 408 ×2 |

## Gates & anti-dérive
| Item | Statut | Preuve |
|---|---|---|
| Harnais e2e (C-11) | DONE | P0-10a (PR #28) : e2e réel + selftest RED automatisé + k6 seuils OK |
| Gates doc (docs-drift) | DONE | hook pre-commit actif (a bloqué 2 commits → docs produites) |
| Digest + hooks anti-dérive | DONE | kit .claude/settings.json + hooks globaux ; conformance_audit ✓ |
| Test à froid no 1 | DONE | onboarding lane Cursor sans intervention (CURSOR-CALIBRATION.md) |
| Budget/coûts mesurés | DONE (outillé) | traces Langfuse (:3100) par appel ; coupe-circuits par clé = R-037 (à câbler passerelle — backlog) |

## Reste ouvert (honnête)
mini-SWE (br. 5), DSPy/GEPA (br. 9), eccAgentShield (br. 12), générateur automatique de cette vue,
coupe-circuits budgets par clé (R-037), politiques tracking/profilage/photos (backlog P0-7),
P0-9a/b (session infra Nathan), validation légale finale des documents P0-7 (Nathan, T3).
