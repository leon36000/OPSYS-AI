"""Pont vers les outils BI externes (Superset, Metabase, Grafana, tableur) : EXPORTS EN LECTURE SEULE de l'entrepôt de
M8.

- `jeux` : la liste FERMÉE des jeux de données exportables (vues de l'entrepôt dérivé), colonne par colonne ;
- `formats` : CSV, JSON Lines et OData v4 minimal, en stdlib ; neutralisation des formules de tableur ; minimisation PII
  par le masqueur de `opsys.observabilite` ;
- `service` : jeton de lecture dédié (secret du coffre), quotas, journal d'accès append-only, lecture seule imposée ;
- `http` : le routeur HTTP (GET seulement) ; `cli` : émission et révocation des jetons, réservées à un humain.

Rien ici n'écrit dans l'entrepôt ni dans un registre de département. Voir docs/architecture/M8-OLIVIER.md, § Pont BI.
"""
