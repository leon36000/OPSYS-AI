# M9.12 — radar de risques

Statut : **DONE_VERIFIED** (grille de gravité proposée, non validée par Nathan).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [salle de guerre](M9-DAILY-WAR-ROOM.md) ·
[playbooks](M9-STRATEGIC-PLAYBOOKS.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Dire à Nathan quels risques sont **déjà mesurés** par les départements propriétaires (trésorerie M5, matériaux M6,
incidents et reports M4, marge M8), avec leur gravité, leur source exacte, leur âge et ce qui a changé depuis la veille,
sans jamais inventer un seuil, une cause ni un « aucun risque » faute de données.

## Pourquoi

Un radar qui calcule ses propres seuils ou qui explique un risque produirait des chiffres et des causes non vérifiables.
Le code se borne à appliquer des règles versionnées sur des captures complètes ; une règle qu'il ne peut pas évaluer est
un risque inconnu, jamais un risque nul.

## État actuel

`risques.py` (version `2026-10-28.1`) déclare **sept règles** (`REGLES`) :

| Règle | Domaine | Lecture | Signal (gravité) |
|---|---|---|---|
| `cash_alerte_seuil` | cash | `m5.prevision_tresorerie` | alerte de seuil M5 (`ELEVE` si première semaine en déficit, sinon `MOYEN`) |
| `cash_non_evaluable` | cash | `m5.prevision_tresorerie` | prévision non calculable ou seuil à configurer (`INCONNU`) |
| `materiaux_reservation_incomplete` | materiaux | `m6.disponibilite` | réservation `partiel` (`MOYEN`) ou `a_commander` (`ELEVE`) |
| `capacite_incident_ouvert` | capacite | `m4.retards_incidents` | incident (`ELEVE` si bloqué, sinon `FAIBLE`) |
| `capacite_report_en_cours` | capacite | `m4.retards_incidents` | report hors météo (`FAIBLE`) |
| `meteo_report_en_cours` | meteo | `m4.retards_incidents` | report pour météo (`MOYEN`) |
| `qualite_ecart_marge_negatif` | qualite | `m8.mesures_chantier` | `m8_ecart_marge_cad` négatif (`MOYEN`) |

- **Grille** : `GRILLE_STATUT = "PROPOSEE_NON_VALIDEE_PAR_NATHAN"`, grades `FAIBLE`, `MOYEN`, `ELEVE`, `INCONNU` ; la
  gravité ne dépend que de la nature du signal, jamais d'une mesure de dommage. La grille est rendue avec chaque radar.
- **Absence de cause** : chaque risque porte `origine_etablie: false` et `explication` = « origine non établie par M9 ».
  La garde statique `verifier_aucune_cause_signalee` (`conformite.py`) refuse une clé de cause dans le paquet.
- **Non évaluées** : une règle dont la lecture est `ABSENTE`, `REFUSEE`, `PARTIELLE` ou `CONTRADICTOIRE` va dans
  `regles_non_evaluees` avec sa raison.
- **Statuts** : `ACTIF`, `A_RECONFIRMER` (source plus vieille que `perime_apres_jours`, si une péremption est demandée),
  `LEVE` (signal présent dans une version plus ancienne de la même lecture, absent de la plus récente : faux positif
  possible, les deux preuves citées dans `elements_contraires`).

## Architecture

- `evaluer(captures, connaissance, perime_apres_jours=None)` : ne voit que les captures connues à l'instant
  (`capture_strategique.connues_a`), groupées par empreinte d'arguments ; rend `RADAR_RISQUES` avec `radar_id`
  (empreinte du contenu). Péremption hors 0–3650 : `REJ-RISQUE-PEREMPTION`. La fraîcheur n'est évaluée que si
  `perime_apres_jours` est fourni.
- `delta(captures, connaissance, jours=1)` : deux radars calculés sur ce que M9 connaissait à `connaissance − jours` et à
  `connaissance` ; rend `apparus`, `leves`, `gravite_changee`, `inchanges`. Jours hors 1–31 ou instant sans fuseau :
  `REJ-RISQUE-DELTA`. Limite écrite dans la sortie : c'est la comparaison de deux états connus de M9, pas du monde.
- Preuves : adresse `lecture#index:pN.chemin[rang].champ` vers la capture citée.

## Fichiers

[risques.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/risques.py),
[outils_radars.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_radars.py),
`capture_strategique.py` (connaissance, contradictions, extraction), `outils_direction.py` (salle de guerre),
[direction_ui.py](../../../src/opsys/console/direction_ui.py).

## Outils et pages de console

| Outil | Accès | Rôle |
|---|---|---|
| `m9_radar_risques` (`connaissance`, `perime_apres_jours`, `depart`) | admin strict (`exiger_admin_strict`), T0/N0 | radar paginé sous `budget_sortie` ; `REJ-RADAR-DEPART`, `REJ-TISSU-BORNE` |
| `m9_salle_de_guerre` | admin strict | résumé du radar et `changements_depuis_la_veille` (`risques.delta`) |

Pages : panneau « Risques » de `/direction` et page `/direction/risques` (péremption facultative, pagination `depart`).
Il n'existe pas de route `/api/strategy/risks`.

## Données et registres

Lecture seule du registre `captures_strategiques` ; une chaîne altérée est refusée (`REJ-CAPTURE-CHAINE-INVALIDE`).
Aucun risque n'est stocké : le radar est recalculé à la demande et rejouable (même entrée, même `radar_id`).

## Workflows

1. L'admin capture les lectures M4, M5, M6, M8 (`m9_capturer_producteur`, voir M9.1).
2. Il demande le radar pour un instant donné ; il peut fixer une péremption.
3. La salle de guerre compare la veille et le jour ; un playbook se déclenche sur les risques `ACTIF` (M9.15).

## Intégrations

Producteurs lus par le port privé `lecteurs_m9` : M4 (`m4.retards_incidents`), M5 (`m5.prevision_tresorerie`), M6
(`m6.disponibilite`), M8 (`m8.mesures_chantier`). Consommateurs : salle de guerre (`outils_direction`) et
`m9_evaluer_playbook` (`playbooks.declenchement`) ; le cadrage de décision (M9.10) ne lit pas le radar.

## Risques

- Les risques non couverts par une lecture (réputation, ventes, capacité d'équipe) sont absents du radar, pas nuls.
- La grille est un réglage proposé ; ses grades ne sont pas des seuils d'affaires validés.
- Le delta peut montrer un risque « apparu » simplement parce qu'une règle n'était pas évaluée la veille.

## Gates Nathan

Valider ou amender la grille de gravité (`PROPOSEE_NON_VALIDEE_PAR_NATHAN`) et décider des domaines à ajouter quand un
producteur exposera la mesure.

## Tests

`departments/m09-strategic-intelligence/tests/test_risques.py` (quatre domaines, risque inconnu, faux positif levé,
source périmée, lectures refusée/partielle/contradictoire, delta apparu/levé/gravité, capture future ignorée) ;
`tests/test_m9_radars_integre.py` (monde réel : réservation partielle M6 active, cash M5 `INCONNU`, péremption, refus
non-admin et agent, salle de guerre) ; `tests/test_console_direction_m9.py` (page risques, tableau de bord).

## Statut

DONE_VERIFIED en processus (SQLite, producteurs réels via le port privé, HTTP console) ; grille non validée.

## Prochaines étapes

1. Faire valider la grille par Nathan ou la remplacer par des seuils déclarés par les propriétaires.
2. Ajouter une règle seulement quand un producteur publie le signal (pas de signal calculé par M9).
