# M9 Athéna : radar de risques complété et scénarios chiffrés par les propriétaires (M9-C1, M9-C2)

Statut (2026-11-02, base ligne architecte `ea631e4bc`) : **livré et prouvé sur SQLite avec des données FICTIVES, les vrais outils de M1, M2,
M4, M5, M7, M8, M9 et M10, le vrai bus et une horloge injectée.** Aucun modèle réel n'a été appelé, aucun conseil n'a tourné dans le Core
natif, rien n'a été exercé sur PostgreSQL ni sur un téléphone. Les valeurs de seuil ne sont pas celles de Nathan : le livre ne déclare
AUCUN seuil, la direction les décide depuis l'écran « Réglages de direction ».

Code : `risques.py`, `reglages_radar.py`, `escalade_risques.py`, `outils_escalade.py`, `scenarios_chiffres.py`,
`outils_scenarios_chiffres.py` (département M9) ; `capacite_hypothese.py` et deux outils (M4) ; `lecteurs_m9.CALCULS_AUTORISES` (socle) ;
genre `risque` de `m9.fait_strategique` (catalogue d'événements et `strategique.py` de M10). Aucune migration.

## 1. Le radar : vingt et une règles, des seuils déclarés

Le radar (M9.12) ne sait que ce que les propriétaires ont publié et que M9 a **capturé** : il n'ouvre aucune lecture de plus que celles de la
liste blanche (`opsys.lecteurs_m9`), sauf `m2_scanner_sla` (lecture T0 du filet anti-perte de M2). Chaque risque rend : la **règle**, le
**domaine**, le **sujet**, la **gravité** (grille proposée, non validée), le **statut** (`ACTIF`, `A_RECONFIRMER`, `LEVE`), la **raison**,
la **mesure** du propriétaire, le **seuil** déclaré qu'elle franchit, la **source** (lecture, capture, empreinte, âge), les **preuves**
(adresses de faits) et `origine_etablie: false` : le radar dit quoi, combien, quand et d'où, jamais pourquoi.

| Règle | Domaine | Lecture | Seuil | Gravité |
|---|---|---|---|---|
| `cash_alerte_seuil`, `cash_non_evaluable` (historiques) | cash | `m5.prevision_tresorerie` | celui de M5 | MOYEN / ELEVE (déficit) ; INCONNU |
| `materiaux_reservation_incomplete` (historique) | materiaux | `m6.disponibilite` | aucun | MOYEN / ELEVE |
| `capacite_incident_ouvert`, `capacite_report_en_cours`, `meteo_report_en_cours` (historiques) | capacite, meteo | `m4.retards_incidents` | aucun | ELEVE / FAIBLE ; MOYEN |
| `qualite_ecart_marge_negatif` (historique) | qualite | `m8.mesures_chantier` | aucun | MOYEN |
| `plaintes_afflux` | plaintes | `m1.plaintes_structurees` | `m9.plaintes_seuil_nombre` | ELEVE, CRITIQUE |
| `plaintes_sensibles_ouvertes` | reputation | `m1.plaintes_structurees` | aucun (catégories avocat, sécurité ouvertes) | ELEVE |
| `capacite_surcharge_cedule` | capacite | `m4.capacite_equipe` | `m9.capacite_utilisation_seuil_pct` | ELEVE, CRITIQUE |
| `depense_marketing_plafond` | marketing | `m7.depenses_marketing` | `m9.depense_marketing_plafond_cad` | ELEVE, CRITIQUE |
| `leads_sous_plancher` | ventes | `m2.prevision_pipeline` | `m9.leads_plancher_par_semaine` | MOYEN |
| `estimation_ecart_main_doeuvre` | estimation | `m3.ecarts` | `m9.estimation_ecart_relatif_max` | ELEVE, CRITIQUE |
| `materiaux_variance_critique` | materiaux | `m3.ecarts` | celui de M6 (`signal_critique`) | ELEVE |
| `materiaux_disponible_negatif` | materiaux | `m6.disponibilite` | aucun | ELEVE |
| `chantier_retard_prolonge` | chantiers | `m4.retards_incidents` | `m9.retard_chantier_jours` | ELEVE, CRITIQUE |
| `cash_libre_deficit` | cash | `m8.vue_executive` | aucun (cash libre négatif constaté par M5) | CRITIQUE |
| `cash_libre_non_calculable` | cash | `m8.vue_executive` | aucun | INCONNU |
| `cash_libre_sous_plancher` | cash | `m8.vue_executive` | `m9.cash_libre_plancher_cad` | ELEVE |
| `filet_sla_violation` | ventes | `m2.sla_filet` (`m2_scanner_sla`) | les délais DÉCLARÉS chez M2 | MOYEN ; ELEVE (lead chaud, plainte) |
| `donnees_perimees` | donnees | toutes celles que le radar consomme | `m9.donnees_perimees_jours` | MOYEN |

**Seuils déclarés, jamais inventés.** Les neuf réglages du radar sont déclarés au manifeste de M9 (`reglages:`, chemin
`configuration.radar.<nom>`), sans AUCUNE proposition (aucune source écrite n'en fournit), et lus par la couche unique
(`opsys.reglages.lecture.superposer`, adapté dans `reglages_radar.py`) : valeur adoptée par le propriétaire (N3) > valeur écrite au fichier
> absence. Une valeur refusée par sa déclaration (hors bornes, mauvais type) est traitée comme absente, avec le code du refus. **Une règle
dont un seuil manque n'est pas évaluée** : elle est listée (`SEUIL_NON_DECLARE`) avec les clés à déclarer et, une fois, leur libellé, leur
unité et l'écran où les déclarer (`reglages_a_declarer`). Un radar sans seuil ne dit donc jamais « aucun risque » : il dit « inconnu, déclarez ceci ».
Seuls les faits structurels des propriétaires restent évalués sans réglage (cash libre négatif, plainte de sécurité ouverte, disponible négatif…).

**Critique.** `CRITIQUE` n'existe que (a) quand la mesure atteint le seuil multiplié par `m9.multiple_seuil_critique` (déclaré : sans lui,
aucun dépassement n'est dit critique, et le radar le dit) ou (b) par un fait structurel du propriétaire (cash libre négatif). La comparaison
est exacte en `Decimal`, croisée pour la surcharge (aucune division) ; une équipe planifiée sans heure de quart déclarée dépasse tout seuil.

**Lectures qui ne diffèrent que par leur référence.** Deux captures d'une même lecture dont seuls l'instant ou le jour de RÉFÉRENCE changent
(le jour de la lecture, l'instant de lecture) lisent la même chose à deux moments : la plus récente fait foi, un signal disparu est
**LEVÉ** (les deux preuves citées). Deux périodes ou deux filtres différents restent des lectures distinctes. **Péremption** : l'argument
`perime_apres_jours` l'emporte ; à défaut, l'âge déclaré `m9.donnees_perimees_jours` ; un risque dont la source est plus vieille est
`A_RECONFIRMER`, jamais affirmé.

**Sortie bornée.** La sortie d'un outil est limitée à 6 000 caractères : `m9_radar_risques` pagine UN curseur sur les risques puis sur les
règles non évaluées (`depart`, `prochain_depart`) ; le contexte (règles évaluées, seuils déclarés, réglages à déclarer, limites) n'est
rendu qu'à la première page. Les chiffres de tableau (`m9_tableau_direction`), de salle de guerre et de rapport périodique appliquent
les mêmes seuils (ils relisent la couche des réglages) et la salle de guerre compte les risques critiques actifs.

**Livres de jeu.** `risque_plaintes` (plaintes), `cash` (cash libre), `surcharge` (surcharge, retard prolongé), `rupture`
(disponible négatif) et `roi_marketing_faible` (dépense au-dessus du plafond) se déclenchent par ces règles. `baisse_leads` reste « à
déclarer par la personne » : son cas de référence est scellé dans le corpus d'évaluation M9.23, qui n'est pas réécrit.

## 2. L'escalade interne d'un risque critique

`m9_escalader_risques_critiques` (T1 / N2, admin authentifié, aucun rôle d'appareil) relit le radar à l'instant fourni et, pour chaque risque
ACTIF et CRITIQUE : (1) ajoute un **avis** au registre chaîné `avis_risques` (texte assemblé de codes et de valeurs de propriétaires, qui
dit qu'aucune cause n'est établie et qu'aucun message externe n'est envoyé) ; (2) crée une **tâche** : un plan M9 dont le porteur est la
direction, l'échéance le jour de l'escalade et le seul résultat clé « manuel » (une personne examine) — non doublée tant qu'une tâche de la
même règle et du même sujet est ouverte ; (3) publie la **mémoire** : `m9.fait_strategique` de genre `risque` (statut
`signale_par_le_radar`), que M10 range, FINANCIAL, dans ses faits stratégiques (jamais dans un paquet de contexte).

Rien n'en sort : l'outil n'a aucun port vers un courriel, un SMS ou une publication, ne demande aucune approbation, n'appelle aucun autre
département. Un avis par règle, sujet et jour (rejouer le même jour n'ajoute rien ; le lendemain, un nouvel avis mais pas de seconde tâche).
Un risque inconnu (règle non évaluée) n'est pas escaladé. **L'outil n'est branché à aucun planificateur** : la décision d'exécuter M9 sous un
acteur système est en attente de Nathan ; `m9_lire_avis_risques` relit les avis. Pas d'écran de console pour les avis : la salle de guerre
compte les critiques actifs, la tâche se lit par `m9_lire_plans`.

## 3. Les scénarios chiffrés (M9.8b, M9.9)

`m9_chiffrer_scenario` appelle le moteur du **propriétaire** par le port privé et compose ; **M9 ne calcule rien** (un garde sur le source,
`tests/test_m9_scenarios_chiffres_integre.py`, interdit toute multiplication ou division hors des deux conversions de forme
pourcentage → facteur/fraction, et tout `Decimal` hors validation, conversion et comparaison).

| Choc chiffré | Propriétaire / moteur | Remplace le choc arithmétique |
|---|---|---|
| `retard_paiement_carnet` (part du carnet en %, retard en semaines) | M5 `m5_simuler_tresorerie_monte_carlo` (retard Bernoulli sur les factures clients) | `retard_paiement_client` |
| `hausse_cout_materiaux` (min / probable / max en %) | M5 Monte-Carlo (loi triangulaire déclarée sur les flux fournisseurs) | `hausse_cout_materiaux` |
| `baisse_encaissements` (min / probable / max en %) | M5 Monte-Carlo (loi triangulaire déclarée sur les encaissements) | `saison_morte_faible` |
| `achat_equipement_comparaison` | M5 `m5_comparer_credit_bail_achat` | `achat_equipement` |
| `absences_equipe`, `meteo_jours_bloques`, `hausse_demande_charge` | M4 `m4_projeter_capacite_hypotheses` | `absences`, `meteo`, `trop_de_demandes` |
| `leads_niveau_hypothetique` | M2 `m2_prevoir_pipeline` (intervalle) : position du niveau déclaré | `baisse_leads` |

Les lois, probabilités, graine et nombre de tirages sont **déclarés** par la personne (options exigées, aucun défaut caché). Chaque impact
porte sa **source** (département, outil, arguments exacts), son **reçu** (celui du propriétaire, sans ses entrées) et sa **vérification**
(rejeu par M5 `m5_verifier_recu_calcul`, M4 `m4_verifier_recu_projection_capacite` ou M2 `m2_rejouer_recu_commercial` ; par rappel du
calcul quand le reçu est trop gros pour revenir entier). Un moteur absent, refusé, en erreur ou qui se dit non calculable donne
`NON_CHIFFRE` avec ce qui manque et qui le possède (jamais zéro, jamais un chiffre de M9) ; le texte d'un refus n'est pas recopié, son
code seul l'est. `trésorerie serrée`, `rupture d'inventaire`, `nouvelle ville`, `nouveau service` et les autres chocs sans moteur chez
un propriétaire restent à confier (`A_CALCULER_PAR`).

**M4 : `m4.projection_capacite`.** M4 n'avait pas de « et si » : `capacite_hypothese.py` (calcul pur, reçu rejouable à partir de ses seules
entrées) prolonge `m4.capacite_equipe` sans la modifier. Les absences ne se convertissent en heures d'équipe que par la durée d'un
jour-personne et l'effectif planifié DÉCLARÉS (sinon non calculable, manque nommé) ; les jours bloqués valent un congé de toutes les équipes
(semaine type) ; la hausse de la demande majore les heures planifiées (hypothèse de proportionnalité déclarée). Tout ou rien.

**Port.** `opsys.lecteurs_m9.CALCULS_AUTORISES` ajoute, à part de la liste des lectures, six outils T0/N0 de calcul paramétré (M5 ×3, M4 ×2,
M2 ×1) : seules des HYPOTHÈSES de scénario y passent, jamais la matière d'un producteur (le propriétaire lit lui-même son état). Même
identité admin relue en base ; M5 refuse l'appareil pour son moteur.

## 4. Preuves

* Unitaires : `test_risques_regles.py` (42), `test_reglages_radar.py`, `test_escalade_risques.py`, `test_scenarios_chiffres.py` (53), M4
  `test_capacite_hypothese.py`, M10 `test_strategique.py`.
* Bout en bout, vrais outils, horloge injectée : `tests/test_m9_radar_scenarios_e2e.py` (un mois : T1 sain sans aucun risque, T2 deux
  risques, T3 six risques exacts et deux LEVÉS, T4 neuf risques dont trois CRITIQUES ; escalade : trois avis, trois tâches, trois faits M10, aucune
  approbation, seuls événements nés = `m9.fait_strategique` ; seuils non déclarés) et `tests/test_m9_scenarios_chiffres_integre.py` (M5, M4, M2 réels,
  reçus rejoués par leur propriétaire, moteur absent ou en erreur).

## 5. Ce qui n'est PAS prouvé

* **Aucun modèle réel** ; la qualité du conseil n'est pas établie. Le radar signale, il ne juge pas.
* **Les seuils ne sont pas ceux de Nathan** (fictifs dans les tests) ; **la grille de gravité n'est pas validée** ; faux positifs possibles.
* **Aucune règle de prix de fournisseur** : aucune lecture de prix n'est exposée à M9 (seule la surconsommation de matériaux de M6 l'est).
  M3 et M6 ne sont pas branchés dans le scénario du mois (leurs règles y sont dites « ABSENTE »).
* **Aucune exécution automatique** : le rafraîchissement des lectures et l'escalade ne tournent pas seuls (décision de Nathan en attente) ;
  une escalade que personne n'appelle n'avertit personne. Pas d'écran d'avis, pas de notification poussée, pas de mobile.
* Le Monte-Carlo ne modélise ni corrélation entre flux ni vente future ; l'achat d'équipement n'a aucun effet fiscal ; la projection de
  capacité suppose la proportionnalité de la demande et ne lit aucune présence individuelle.
* SQLite seulement ; PostgreSQL, Core natif et navigateur non exercés pour ces outils.
