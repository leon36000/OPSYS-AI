# M9.1 — tissu de données stratégique

Statut : **DONE_VERIFIED**. [Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) ·
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Conserver, sous forme de captures chaînées, ce que les producteurs ont réellement répondu à M9 ; dire pour chaque
lecture attendue si elle est présente, absente, refusée, partielle, contradictoire ou future ; fournir aux autres
sous-modules un dossier de faits citables en texte exact.

## Pourquoi

Avant ce lot, M9 n'avait aucun port de lecture vers M1–M7 : seuls des snapshots poussés (`m9_etat_consolide`, sans
authentification du producteur) et deux événements M8. Sans trace de ce qui a été lu, quand et de qui, aucune revue ni
recommandation ne peut citer une source ou dire ce qui manque.

## État actuel

- Catalogue `catalogue_producteurs` version `2026-10-28.1` : 19 lectures (1 M1, 2 M2, 1 M3, 4 M4, 4 M5, 1 M6, 1 M7,
  3 M8, 2 M10), égales à `LECTURES_AUTORISEES` du socle.
- Aucun calculateur (outil qui calcule à partir de données fournies par l'appelant) n'est une lecture.
- La couche historique reste : registre `snapshots` (`m9_etat_consolide`, `m9_lire_etat_consolide`) et alertes M8 reçues
  par le bus (`alertes_m8`).

## Architecture

- `capture_strategique` (pur) construit une capture à **quatre temps distincts** : instants métier déclarés par le
  producteur (chemins du catalogue, min/max/nombre), `reference` demandée, `recu_a` (connaissance de M9, monotone dans la
  chaîne) et un âge signé informatif (référence − dernier instant métier), jamais un SLA.
- Verdicts `ACCEPTEE`, `REFUSEE`, `ERREUR` ; un refus est conservé comme preuve de manque. Une page suivante non lue, ou
  une troncature déclarée par le producteur (`Marqueur`), rend la capture `PARTIELLE`.
- Pagination suivie jusqu'à `MAX_PAGES` = 50 ; au-delà du budget (`MAX_OCTETS_DEFAUT` = 900 000) : refus
  `REJ-CAPTURE-BORNE`, jamais de troncature.
- **Contradiction** (règle `meme_lecture_memes_arguments_meme_revision_meme_instant_empreinte_differente/v1`) : deux
  captures acceptées, même lecture, mêmes arguments, même révision et même instant métier max, réponses différentes ;
  les deux preuves sont citées, aucune n'est choisie. Une nouvelle révision est une correction, pas une contradiction.
- **Couverture** (`evaluer_couverture`) : statut par lecture attendue parmi `ABSENTE`, `REFUSEE`, `PARTIELLE`,
  `CONTRADICTOIRE`, `TEMPS_METIER_NON_DECLARE`, `FUTURE`, `PRESENTE`, calculé sur ce que M9 connaissait à
  `connaissance` (`connues_a`). `PRESENTE` ne veut dire ni « vrai » ni « frais ».
- **Péremption** : la fraîcheur n'est évaluée que si une péremption est demandée (`perime_apres_jours`, 1 à 3 650 jours) :
  par `m9_couverture_strategique`, par `m9_cadrer_decision` (une lecture plus ancienne devient un manque
  `HORS_FENETRE_DE_FRAICHEUR` et le conseil n'est pas prêt), et par le radar de risques, les prévisions et les
  playbooks. Sans péremption demandée, la couverture rend `NON_EVALUEE` : M9 n'invente aucune fenêtre par défaut.
- **Dossier stratégique** (`dossier_strategique`) : faits citables `<lecture_id>#<rang>:<chemin>` en texte exact, bornés à
  `MAX_FAITS` = 400 (excédent compté dans `faits_non_retenus`). Sont citables les captures acceptées présentes, à temps
  métier non déclaré, ou partielles (les faits reçus sont réels ; la lecture reste nommée dans `lectures_partielles` et
  les manques). Absente, refusée, contradictoire ou future : aucun fait, un manque nommé. `dossier_id` = empreinte.

## Fichiers

- [capture_strategique.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/capture_strategique.py),
  [catalogue_producteurs.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/catalogue_producteurs.py),
  [dossier_strategique.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/dossier_strategique.py)
- Adaptateur : [outils_tissu.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_tissu.py) ;
  aperçu du dossier dans `outils_conseil.py`.
- Port : [lecteurs_m9.py](../../../src/opsys/lecteurs_m9.py).

## Outils et pages de console

| Outil | Rôle | Autonomie |
|---|---|---|
| `m9_capturer_producteur` | lit un producteur par le port et ajoute la capture | T1 / N2 |
| `m9_lister_captures` | pages bornées, plus récente d'abord, `vue` = tête de chaîne | T0 |
| `m9_lire_capture` | une page de réponse par tranches de 4 000 caractères au plus | T0 |
| `m9_couverture_strategique` | couverture à une référence et une connaissance | T0 |
| `m9_verifier_captures` | validation de la chaîne | T0 |
| `m9_apercu_dossier_strategique` | dossier d'une question, sans écriture | T0 |

Tous exigent `exiger_admin_strict`. Page : `/direction/sources` (couverture puis captures paginées, filtre `lecture_id`
conservé à la page suivante, vue périmée → recommencer depuis le début).

## Données et registres

Registre `captures_strategiques` (schéma `opsys.m9.capture/v1`) : arguments admis, pages, empreintes d'arguments et de
réponse, temps, verdict, complétude, hash chaîné. Écriture interne seulement, sans effet métier.

## Workflows

1. L'admin choisit une lecture du catalogue et ses arguments libres ; les arguments `fixes` sont imposés.
2. Le port vérifie liste blanche, T0/N0 et identité, puis le producteur revérifie ses portées.
3. La capture est ajoutée avec `rang_attendu` ; une chaîne invalide bloque toute lecture (`REJ-CAPTURE-CHAINE-INVALIDE`).
4. Couverture et dossier se recalculent à la demande pour un instant de connaissance donné ; une arrivée tardive ne
   réécrit pas ce qui était connu avant.

## Intégrations

Producteurs : `m1_produire_digest`, `m2_lister_leads`, `m2_lister_relances`, `m3_lire_ecarts_estime_reel`,
`m4_lister_interventions`, `m4_lire_cedule_semaine`, `m4_lire_retards_incidents`, `m4_lire_meteo_intervention`,
`m5_prevoir_tresorerie`, `m5_lire_rentabilite_chantier`, `m5_lire_comptes_a_recevoir`, `m5_lister_comptes_a_payer`,
`m6_lire_disponibilite`, `m7_lire_performance_campagnes`, `m8_lire_vue_executive`, `m8_lire_mesures_chantier`,
`m8_lister_definitions_metriques`, `m10_statut_decision`, `m10_paquet_contexte_affaire`.

## Risques

- Une lecture que le producteur n'expose pas n'existe pas pour M9 (ex. cash libre réel de M5, capacité M4).
- Une lecture sans chemin d'instant déclaré reste `TEMPS_METIER_NON_DECLARE` : l'âge n'est pas connu.
- Authenticité : la capture prouve ce que le serveur a répondu au moment fourni, pas la vérité métier.

## Gates Nathan

Aucun gate propre. L'ajout d'une lecture à la liste blanche est un changement du socle à relire par son propriétaire.

## Tests

`departments/m09-strategic-intelligence/tests/test_capture_strategique.py` (quatre temps, refus conservés, partielle,
bornes, arrivée tardive, contradiction vs correction), `test_dossier_strategique.py`, `tests/test_lecteurs_m9.py`
(liste blanche égale au catalogue, T0/N0 réels, rôle retiré relu en base), `tests/test_m9_producteurs_a.py`,
`tests/test_m9_producteurs_b.py` (vrais producteurs), `tests/test_console_direction_m9.py` (pagination des sources).

## Statut

DONE_VERIFIED (SQLite et producteurs réels en processus ; PostgreSQL en CI seulement).

## Prochaines étapes

1. Proposer à Nathan des fenêtres de péremption par lecture (politique à valider) plutôt qu'une seule valeur demandée à l'appel.
2. Ajouter les lectures manquantes chez leurs propriétaires (capacité, cash libre réel) avant d'en parler en direction.
