# Story P0-8 — Phase C LIVE : consensus outillé 12 modèles
Tier: T2 (méthode)
Statut: READY — clé tournée (P0-4 DONE 2026-07-24), PACK_CONSENSUS_GRS_v2.md présent à la racine.
GO = décision Nathan (D-017 : arbitrage humain si blocage après 1 débat ciblé).
Portée : distribution du pack aux 12 modèles via la passerelle (consensus_run.py mode live — nécessite
d'implémenter la distribution HTTP réelle, aujourd'hui BLOCKED-by-design dans le script), collecte des
verdicts scellés dans registries/verdicts/phaseC-live/, dépouillement scripts/tally.py, débat ciblé si
REJECT, ratification Nathan (rôles, briques, trous M7, ordre modules — questions Q1-Q9 du pack).
Critères : ≥12 verdicts scellés conformes au schéma ; tally APPROVED ou arbitrage documenté ;
entrée ledger decision « PHASE_C_RATIFIEE ».
