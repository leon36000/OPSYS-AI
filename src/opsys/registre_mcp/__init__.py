"""Registre MCP interne en liste blanche : empreinte d'outil (dérive / « rug pull »), politique N0–N5, Rule of Two.

- `registre` : définitions d'outils, empreinte sha256 du triplet nom + description + schéma, scellement (révisions,
  historique, sceau), vérification, garde de démarrage et d'appel ;
- `rule_of_two` : table déclarative par surface non fiable et règle « données sensibles + contenu non fiable + action
  externe → approbation N3 » ;
- `inventaire` : énumère les outils réellement exposés par `opsys.serveur_mcp` (départements, contexte, runtime) ;
- `cli` : `opsys-metier registre-mcp sceller | verifier | lister | rule-of-two`.

Voir docs/architecture/OBSERVABILITE-MCP.md.
"""
