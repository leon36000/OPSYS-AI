# Story P0-9 — Chaîne de sauvegarde + IdP
Tier: T2
Statut: DRAFT — à découper (D-044)
Portée (PDF §16, D-021, D-022) : pgBackRest opérationnel (complet hebdo + différentiel + WAL, dépôt
HORS hôte chiffré aes-256-cbc, règle 3-2-1) + PREMIER exercice de restauration chronométré prouvé au
ledger (durée mesurée = RTO réel ; échec = Sev1) ; IdP Zitadel déployé (service séparé, OIDC), MFA
admin actif. Critères : restauration PROUVÉE (pas documentée) ; RPO ≤ 15 min (WAL) ; ledger.
