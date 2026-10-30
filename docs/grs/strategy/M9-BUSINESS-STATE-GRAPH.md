# M9.2 — graphe d'état et d'impacts

Statut : **DONE_VERIFIED**. [Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) ·
[tissu de données](M9-DATA-FABRIC.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Répondre à « si M6 est en rupture, quels chantiers, devis, leads et finances sont reliés ? » en suivant uniquement des
relations que les producteurs déclarent dans leurs réponses capturées, et dire qui est relié et par quel chemin — jamais
combien, ni quand, ni pourquoi.

## Pourquoi

L'état consolidé historique (`etat_consolide`) ne garde que le dernier fait par module : il ne relie rien. Un graphe
inféré ou causal inventerait des effets ; le cahier exige au contraire des impacts sourcés, sans quantité.

## État actuel

- 15 règles dans `relations_catalogue.REGLES` (version `2026-10-28.1`), chacune avec sa limite écrite dans `LIMITES`
  (garde de construction : une règle sans limite fait échouer l'import).
- Règles par producteur : M6 (2, dont une imbriquée), M4 (6, liste v1, page et cédule), M3 (2), M8 (1), M5 (3), M2 (1).
- `MANQUES` nomme trois liens absents : matériau relié aux devis seulement quand il manque ; lead → devis non exposé
  par M2 ; WCT → lead seulement via l'intervention.
- Graphe recalculé à la demande ; rien n'est stocké comme vérité.

## Architecture

- `graphe_impacts.Regle` : lecture du catalogue, chemin vers une liste de lignes, champ et type de l'objet source, champ
  et type de l'objet cible, `sens` (`de->vers`, `vers->de`, `bidirectionnel`), `sous_lignes` pour une imbrication (un
  champ préfixé `^` est lu sur la ligne parent).
- `construire(captures, regles, connaissance=…)` : pour chaque règle et chaque jeu d'arguments, seule la **dernière**
  capture connue compte. Absente, refusée ou contradictoire : la règle est inconnue, aucune arête. Partielle : les liens
  reçus sont gardés mais la règle est aussi déclarée inconnue (des liens peuvent manquer).
- Chaque arête cite sa règle, sa version, la capture (rang, hash), la page, la ligne et le chemin ; identifiant =
  empreinte de ces éléments. Bornes : `MAX_NOEUDS` = 5 000, `MAX_ARETES` = 20 000 (`REJ-GRAPHE-BORNE`).
- `propager(graphe, kind, id, relations=…, profondeur_max=…)` : parcours en largeur dans le sens d'impact, plus court
  chemin d'abord, déterministe ; profondeur 1 à `MAX_PROFONDEUR` = 8 (`REJ-GRAPHE-PROFONDEUR`). Un objet absent du graphe
  est refusé (`REJ-GRAPHE-NOEUD-INCONNU`) : jamais « aucun impact ». Toute propagation porte la liste des règles
  inconnues : l'absence d'impact n'est pas affirmée tant qu'un lien pertinent est inconnu.

## Fichiers

- [graphe_impacts.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/graphe_impacts.py)
  (module pur)
- [relations_catalogue.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/relations_catalogue.py)
  (règles, limites, manques)
- [outils_graphe.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_graphe.py)
  (adaptateur, lit `captures_strategiques`)

## Outils et pages de console

| Outil | Rôle |
|---|---|
| `m9_apercu_graphe_impacts` | résumé du graphe connu à un instant : nœuds, arêtes, règles actives et inconnues |
| `m9_propager_impacts` | objets atteignables depuis un objet, avec chemins d'arêtes et règles inconnues |

Lecture seule, `exiger_admin_strict`. Aucune page de console dédiée : le graphe n'est pas affiché sous `/direction`
(non livré).

## Données et registres

Lit le registre `captures_strategiques` (chaîne validée avant usage). Types d'objets rencontrés : `devis`, `chantier`,
`materiau`, `intervention`, `lead`, `equipe`, `wct`, `rentabilite`, `po`, `personne`. Aucune quantité, aucun montant,
aucune date n'est propagé.

## Workflows

1. Capturer les lectures utiles (`m6.disponibilite`, `m4.interventions`, `m4.cedule_semaine`, `m3.ecarts`,
   `m8.mesures_chantier`, `m5.rentabilite_chantier`, `m5.comptes_a_payer`, `m2.leads`).
2. Construire le graphe à l'instant de connaissance voulu.
3. Propager depuis l'objet (ex. un matériau manquant, un devis) ; lire les règles inconnues avant de conclure.

## Intégrations

Lectures M2, M3, M4, M5, M6, M8 par le tissu de données. Le graphe n'est consommé que par ses deux outils : ni le
dossier du conseil, ni les scénarios, ni le rapport de décision v2 ne l'importent aujourd'hui (non livré). Les calculs
d'effet restent chez M5 (finance), M4 (capacité), M6 (stock), M8 (mesure). Un filtre `relations` hors catalogue est
refusé (`REJ-GRAPHE-RELATION`).

## Risques

- Un lien est une relation de données déclarée par un producteur, pas une preuve que l'effet se produira.
- Les limites des producteurs bornent le graphe : réservations M6 actives seulement (15 articles par lecture), cédule
  M4 tronquée (`tronque`), rentabilité M5 limitée (`limite`).
- Une règle repose sur un chemin de réponse : un changement de forme chez un producteur rend la règle silencieuse
  (lignes écartées comptées dans `lignes_ecartees`), d'où les tests sur réponses réelles.

## Gates Nathan

Aucun.

## Tests

- `departments/m09-strategic-intelligence/tests/test_graphe_impacts.py` : arêtes justifiées, propagation sans quantité,
  profondeur et filtre, objet inconnu, règle inconnue (absente, refusée, partielle, contradictoire), dernière capture
  décisive, règle imbriquée.
- `tests/test_m9_graphe_reel.py` : règles vérifiées sur captures des vrais outils M2–M8 (rupture M6 déclarée au niveau de
  la réservation du devis, forme paginée de M4, M3/M5/M8 sans lead, M2 sans devis, outils admin seulement).

## Statut

DONE_VERIFIED : graphe et propagation prouvés sur producteurs réels en processus ; aucun impact chiffré par conception.

## Prochaines étapes

1. Raccorder la propagation au dossier du conseil (section `impacts` du rapport v2) comme faits cités.
2. Ajouter une règle seulement quand un producteur expose le champ (ex. devis chez M2) et qu'un test sur réponse réelle
   le constate.
3. Si Nathan le demande, une page `/direction/impacts` en lecture (non livrée aujourd'hui).
