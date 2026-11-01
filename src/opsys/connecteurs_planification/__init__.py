"""Planificateur des connecteurs : de la capacité livrée à l'agent qui s'en sert (voir
docs/architecture/CABLAGE-CONNECTEURS.md).

Ce paquet ne contient AUCUN second opérateur cron : il tourne dans le processus du serveur MCP, à côté de la boucle du
répartiteur d'événements (même cycle de vie, même arrêt propre), comme le réconciliateur du coût certifié. Il porte :

- `journal`, `bail` : journal append-only du planificateur et bail (verrou à expiration, jeton de fencing) par
  ressource : un seul exécuteur à la fois pour un compte courriel, un site WordPress ou un compte social ;
- `etat` : les exécuteurs connus et leur mode (`inactif` par défaut, `ombre`, `actif`), activés SEULEMENT par un
  admin de
  la console, avec expiration (90 jours) et motif ;
- `planificateur` : un tour borné, sous l'acteur système `opsys-systeme` (portée `planificateur`) ;
- `exec_courriel`, `exec_m7` : les exécuteurs (synchronisation incrémentale, envoi approuvé, brouillons et publications
  WordPress, publications sociales) ; `hote` : l'assemblage de production (ports).

Règle d'or : l'acteur système n'exécute JAMAIS une action de niveau N3 ou plus sans une approbation humaine consommée
(envoi : jeton lié à l'empreinte dans le sas ; publication : approbation consignée, non expirée, à usage unique).
"""
