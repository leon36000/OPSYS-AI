# Corpus FICTIF de mesure des embeddings (français québécois)

Données du banc [`install/qualification/embeddings_fr/`](../../../install/qualification/embeddings_fr/). Tout est inventé :
entreprise, clients, fournisseurs, numéros, montants, règles de métier (`fictif: true` exigé par le chargeur ; les seuls
courriels sont en `.test`). Les prix, délais et règles sont des énoncés de fiction pour tester la recherche, **pas** des
références techniques, tarifaires, fiscales ni juridiques.

- `passages_*.yaml` : 255 passages courts en huit catégories (préfixe d'identifiant : G, R, S, U, P, F, V, N).
- `requetes.yaml` : 104 requêtes (92 avec réponse, 12 sans) avec `pertinents` (gain 2) et `partiels` (gain 1). Version 1
  des jugements écrite avant toute mesure ; version 2 après revue par mise en commun (13 partiels ajoutés), voir l'en-tête
  du fichier et le rapport.
- `consigne_juge.txt` : consigne du juge de reclassement ; son empreinte est épinglée par les tests (la changer rend les
  preuves publiées non rejouables).

Les données vivent ici (et non sous `install/`) parce que la garde de généralisation des packs interdit le vocabulaire du
secteur dans le cœur. Rapport : [`../MESURE-EMBEDDINGS-FR-2026-11.md`](../MESURE-EMBEDDINGS-FR-2026-11.md).
