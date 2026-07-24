# Story P0-2b — Épinglage LiteLLM par digest (R-028 / D-035)
Tier: T2
Statut: DRAFT — infra Serveur (hors repo), exécution avec Nathan
Portée : le conteneur serveur-litellm tourne sous le tag MUTABLE ghcr.io/berriai/litellm:main-latest ;
hash courant journalisé (sha256:f792e404f0db3…). Remplacer le tag par le digest immuable dans
/media/pc1/Storage/Serveur/stack/compose/docker-compose.yml + procédure de mise à jour délibérée
(cooldown D-035). Critères : compose référence un digest ; docker inspect .Image == digest déclaré ;
entrée ledger avec l'empreinte ; redémarrage prouvé sans changement de comportement (preuves A/B rejouées).
