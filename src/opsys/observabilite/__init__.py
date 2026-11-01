"""Observabilité d'OPSYS : traces d'exécution des agents, masquage des renseignements personnels, export derrière un
port.

- `pii` / `pii_detecteurs` : masquage déterministe (NAS, cartes, téléphones, courriels, adresses, RAMQ, NEQ, secrets),
  jetons stables HMAC, mode irréversible ou réversible dans le coffre, port `MasqueurPII` (Presidio plus tard) ;
- `traces` : span d'agent et d'appel d'outil, journal local append-only à chaîne HMAC, rétention bornée, masquage AVANT
  écriture ;
- `destinations` : port `DestinationTraces`, double de test, adaptateur Langfuse (jamais exécuté ici) ;
- `tableaux` : coûts et latences par département, lecture seule (CLI et console).

Aucun appel réseau ici. Voir docs/architecture/OBSERVABILITE-MCP.md.
"""
