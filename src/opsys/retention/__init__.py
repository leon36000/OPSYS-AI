"""Rétention Loi 25 : ce que la loi demande de ne plus conserver, effacé SANS réécrire un registre chaîné.

Trois mécanismes, du moins au plus invasif :

- `echeances` : l'index des clés de chiffrement à détruire à une date donnée (pseudonymes seulement) et la destruction
  elle-même par `opsys.cles_chiffrement.demander_effacement` (crypto-effacement : la ligne chiffrée reste dans sa chaîne
  d'audit, valide, mais son contenu est illisible pour toujours) ;
- `voix` : le contrat de conservation des enregistrements vocaux (clé par session, échéance, retrait du consentement) ;
- `courriel` : la rétention du courriel d'ingestion (originaux scellés, brouillons sortants, archives déposées), dont
  les
  tables ne sont PAS chaînées : le contenu scellé est rendu illisible et les empreintes sont gardées, car elles
  empêchent de réingérer un courriel déjà vu.

Rien ici ne s'exécute seul. L'exécution périodique appartient au planificateur (`connecteurs_planification`,
exécuteurs `retention.*`), qui exige, avant la première purge automatique, la validation humaine d'un aperçu à blanc
(docs/architecture/PLANIFICATION.md §5). Le droit d'effacement d'une personne qui retire son consentement reste, lui,
immédiat et humain (`voix.retirer`).
"""
