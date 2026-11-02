# M9 Strategic Intelligence (Athéna) : le cerveau stratégique interconnecté

Statut : tranche 1 (2026-11-01). Exigences : M9.1, M9.4, M9.5, M9.9, M9.10, M9.20, M9.21, M9.23 de
`docs/reprise/M9-COMPLETION-20261028/MATRICE-EXIGENCES.json` (aucune n'est « complète » ; trois lignes nouvelles M9.25 à M9.28,
toutes PARTIEL). Code : `departments/m09-strategic-intelligence/src/m9_strategic_intelligence/` (`certitude`, `tableau_direction`,
`priorites_direction`, `changements_depuis`, `recommandation_gouvernee`, `boucle_decisions`, `charges_athena`, `evaluation_athena`,
adaptateurs `outils_athena` et `adaptateur_boucle`), M8 (`synthese_direction`), M10 (`strategique`), socle (`lecteurs_m9`,
catalogue d'événements). Aucune migration : les registres sont des chaînes `stockage.maillons`.

> **Ce que cette tranche est, et n'est pas.** Elle raccorde Athéna aux producteurs arrivés depuis (M8 santé et mesures, M2 pipeline
> et prévision par intervalle, M5 échéances et revue des sources fiscales, M10 faits analytiques), dit pour CHAQUE fait ce qu'il
> vaut (établi, essai, indéterminé, périmé, prévision), classe de façon déterministe ce qui exige la direction, dit ce qui a changé
> depuis hier avec un reçu, contrôle les recommandations (chaque chiffre sourcé, jamais de décision, abstention sur l'inconnu) et
> tient la boucle décision → résultat → leçon jusqu'à la mémoire de M10. Elle le prouve avec des données FICTIVES, SQLite, le vrai bus,
> la vraie file d'approbation et les vrais départements. **La qualification d'Athéna par un modèle réel reste OUVERTE** : aucun
> modèle n'a été mesuré, aucun conseil n'a tourné dans le Core natif, aucun téléphone n'a vu ces outils, PostgreSQL n'est pas exercé.

## 1. Les lectures raccordées

Toutes passent par le port privé existant `opsys.lecteurs_m9` (admin authentifié relu en base à chaque lecture, appel attribué à M9,
liste blanche de lectures T0/N0). Chaque charge est REJOUÉE par `charges_athena` (module pur, même doctrine que `charges_producteurs`)
AVANT d'être conservée : une charge qui viole le contrat de son producteur est un refus conservé, sans fait citable, et le message
nomme le champ, jamais la valeur.

| Lecture du catalogue | Outil du producteur | État avant | Ce que le contrat refuse |
|---|---|---|---|
| `m8.synthese_direction` | **`m8_lire_synthese_direction`** (T0, nouveau) | `m8_lire_mesures` et `m8_lire_sante_entreprise` sont fermés à toute identité : inaccessibles au port | un score avec un statut indéterminé, un score hors de 0 à 100, un flottant, une fraîcheur incohérente avec l'âge, des pondérations « validées » sans validateur |
| `m2.analyse_pipeline`, `m2.prevision_pipeline` | `m2_analyser_pipeline`, `m2_prevoir_pipeline` (T0, existants) | non whitelistés | un taux ou une probabilité sous son seuil d'échantillon, un point sans intervalle, des bornes inversées, une prévision sous le seuil déclaré |
| `m5.calendrier_obligations` | `m5_lire_calendrier_obligations` (T0, existant) | non whitelisté | un montant de taxes sans couverture (« un zéro ne peut pas être confirmé »), une obligation « documentée » qui a des manques |
| `m5.statut_revue_fiscale` | **`m5_lire_statut_revue_fiscale`** (T0, nouveau) | `m5_lire_etat_base_fiscale` et les conseillers sont fermés aux appareils | un sujet déclaré « approuvé » alors que des règles ne le sont pas |
| `m10.faits_analytiques` | `m10_lire_faits_analytiques` (T0, existant) | non whitelisté | une page plus grande que son total, une consolidation hors forme, une anomalie hors vocabulaire |

Les deux outils nouveaux chez leurs propriétaires sont T0/N0, **sans aucun rôle d'appareil**, et ne rendent que des comptes, des
statuts et des mesures déjà exposées aux agents du département (aucun taux, aucun texte de règle, aucun détail libre d'un manque).
Aucun droit d'appareil n'est élargi nulle part (`ROLES.md` : « 248 outils sur 552 », les 248 ne changent pas).

Lectures du catalogue d'avant (M1, M4, M5, M6, M7, M8, M10) : inchangées. Non raccordés, dit : le contexte de site de M3 et l'adéquation
d'équipe / ETA de M4 sont des lectures PAR AFFAIRE, pas des agrégats de direction ; les raccorder demande une décision de portée
(quelle affaire ?) qui n'a pas été prise. Le dossier CPA de M5 (`m5_verifier_dossier_cpa`) prend un dossier déjà déposé en argument : ce
n'est pas une lecture de l'état de M5.

## 2. Le statut de certitude (`certitude.py`)

| Statut | Sens | Certain ? |
|---|---|---|
| `ETABLI` | reçu d'un producteur, capture acceptée et complète | **oui, seul** |
| `ESSAI_NON_APPROUVE` | le producteur dit lui-même la valeur proposée : pondérations du score non validées, calendrier « à valider par le CPA », couverture « partielle » | non |
| `INDETERMINE` | le producteur refuse de conclure (score indéterminé, mesure non calculable, échantillon insuffisant) : aucune valeur n'existe | non |
| `PERIME` | le producteur dit la valeur plus vieille que sa fenêtre de fraîcheur | non |
| `PREVISION_PAR_INTERVALLE` | une projection : jamais une certitude | non |
| `ABSENT` / `REFUSE` / `PARTIEL` / `CONTRADICTOIRE` | l'état de la LECTURE | non |

Le statut vient de ce que le producteur DÉCLARE dans sa réponse, jamais d'un jugement de M9. Un fait mal compris est rétrogradé
(`INDETERMINE`), jamais promu.

## 3. Le tableau de direction (`tableau_direction.py`, `m9_tableau_direction`, `m9_briefing_direction`)

Neuf sections : santé, pipeline, prévision des leads, trésorerie, échéances, revue des sources fiscales, capacité, risques de chantier,
alertes M8. Chaque ligne porte `valeur` (texte exact), `certitude`, `certain`, `adresse` du fait
(`<lecture>#<rang>:p<page>.<chemin>`, vérifiable mot pour mot) et l'âge de la source.

* **Santé** : « indéterminée : bornes à fixer par la direction » tant que les bornes ne sont pas déclarées (et la liste des mesures à
  rafraîchir quand la cause est ailleurs) ; score calculé mais pondérations non validées = ESSAI, `certain: false`, message explicite ;
  établi seulement si la direction a validé les pondérations. Mention CPA. Aucune borne inventée.
* **Pipeline / prévision** : un taux sous son seuil d'échantillon est « indéterminé : échantillon insuffisant (n sur seuil) » ; la valeur
  pondérée et la prévision sont TOUJOURS rendues avec leur intervalle et le niveau ; une prévision refusée par M2 reste un refus.
* **Échéances** : le calendrier M5 reste « à valider par le CPA » ; un montant de taxes sous couverture partielle est « non confirmé ».
* **Déclarations attendues de la direction** (bornes, pondérations, revue des sources, validation du calendrier) : des constats tirés des
  sections, jamais des décisions.
* Les sections sont bornées par le code (sommaire puis détail paginé) sous la limite de sortie du socle ; rien n'est coupé en silence.

## 4. Ce qui exige la direction (`priorites_direction.py`, `m9_exige_la_direction`)

Règle écrite, rendue avec le résultat et refaisable à la main : **niveau d'approbation le plus élevé d'abord (N5 → N0), puis l'attente la
plus ancienne, puis l'identifiant.** Une demande sans niveau déclaré n'est PAS classée parmi les niveaux connus ni supposée basse : elle
passe après et est comptée à part. Un âge illisible ou futur passe après les âges connus, avec son motif. Le texte d'une demande est une
donnée bornée à 160 caractères. M9 n'approuve, ne refuse ni n'exécute rien.

## 5. Ce qui a changé depuis hier (`changements_depuis.py`, `m9_changements_depuis`)

Différence entre ce que M9 SAVAIT à `depuis` (par défaut 24 h avant) et ce qu'il sait à `maintenant` (une capture reçue plus tard
n'existe pas dans l'état d'hier). Par lecture : état avant/après, puis faits modifiés, nouveaux ou disparus (valeur avant/après en texte
et statut des deux côtés) quand les deux lectures posent la MÊME question (mêmes arguments hors instant de référence) ; sinon la
comparaison est déclarée impossible. Les faits volatils (âge, instant de lecture) sont exclus. Aucune différence n'est calculée. Le
**reçu** (`opsys.m9.recu_changements/v1`) lie l'intervalle, les maillons utilisés de chaque côté, la version du catalogue et l'empreinte du
résultat ; `m9_verifier_recu_changements` refait la comparaison depuis la chaîne (reçu retouché ou chaîne différente : invalide).

## 6. Le conseil gouverné (`recommandation_gouvernee.py`, `m9_controler_recommandation`)

Une recommandation (`opsys.m9.recommandation/v1` : question, domaines, hypothèses, options ≥ 2, chiffres, risques, données manquantes,
recommandation, `PROPOSITION_NON_DECIDEE`) est admise en bloc ou refusée avec un code `REJ-RECO-…` :

| Règle | Code |
|---|---|
| M9 ne décide jamais (statut, `decision_prise_par_m9` faux, aucun texte qui prétend une décision, un paiement, une signature) | `REJ-RECO-DECISION` |
| un chiffre = fait cité (adresse + valeur mot pour mot), OU reçu M5 intact dont la valeur se lit à son chemin, OU hypothèse de la direction | `REJ-RECO-CHIFFRE-SANS-SOURCE`, `-FAIT-INCONNU`, `-VALEUR`, `-RECU` |
| le statut d'un fait cité est rejoué : un essai, un périmé ou une prévision ne se présente pas comme établi | `REJ-RECO-STATUT-FAUX` |
| aucun nombre libre dans un texte (même un entier nu, une date) | `REJ-CONSEIL-CHIFFRE-LIBRE` |
| une valeur d'hypothèse vient de la direction, jamais du modèle | `REJ-RECO-HYPOTHESE` |
| une donnée bloquante manquante interdit de recommander : abstention motivée | `REJ-RECO-RECOMMANDE-SUR-INCONNU`, `-ABSTENTION` |
| mention « À valider auprès d'un comptable (CPA) / professionnel qualifié » et validation du comptable (ou du juriste) quand le domaine est déclaré OU impliqué par les sources citées (M5, santé de l'entreprise) | `REJ-RECO-MENTION`, `-VALIDATION` |
| un risque cite au moins une source | `REJ-RECO-RISQUE-SANS-SOURCE` |

Le reçu de calcul est contrôlé pour l'intégrité de ses empreintes par le pont du socle (`opsys.recu_calcul_pont.verifier`) ; son REJEU
appartient à `m5_verifier_recu_calcul`. Ce contrôle dit la forme, l'ancrage et l'honnêteté des statuts : il ne dit pas que la source est
vraie ni que le jugement est bon.

## 7. La mémoire stratégique (`boucle_decisions.py`, `adaptateur_boucle.py`, M10 `strategique.py`)

```
décision de la direction (N3) ──► résultat mesuré par le code (N2) ──► leçon PROPOSÉE (N2) ──► validation/rejet humain (N3)
      registre chaîné `decisions_direction`, une entrée = un événement `m9.fait_strategique` ──► M10 `faits_strategiques` (FINANCIAL)
```

* **Décision** (`m9_consigner_decision_direction`, T1/N3) : n'écrit que pendant l'exécution de SA demande approuvée par un propriétaire
  actif en base. Elle porte ce que la direction ATTEND, en sens seulement (hausse, baisse, stable) sur des mesures M8, et la base de
  comparaison (dernière lecture établie connue à l'approbation, ou « inconnue » : jamais reconstituée). Un suivi existant
  (`suivi_decisions`) peut être référencé ; ce registre n'est ni modifié ni cassé.
* **Résultat** (`m9_mesurer_resultat_decision`, T1/N2) : le code compare deux textes décimaux (aucune différence calculée). Une mesure
  périmée, non calculable, de définition changée ou sans lecture postérieure est NON_MESURABLE avec sa raison : aucune conclusion, aucune
  leçon.
* **Leçon** : un gabarit rempli de faits, `PROPOSEE_NON_VALIDEE`, qui n'établit AUCUNE cause. Elle ne devient une leçon que par la
  validation de la direction (`m9_valider_lecon_decision`, N3, rejet motivé).
* **Mémoire** (`m9_publier_faits_strategiques`, T1/N2) : publie chaque entrée vers M10 (idempotent par empreinte du maillon) et
  PRÉPARE, pour une leçon VALIDÉE seulement, les arguments exacts d'une source de connaissance interne ; rien n'est écrit dans la base de
  connaissances par M9 (l'ingestion appartient à M10 : brouillon, N2, puis son cycle de revue). Aucun nom de personne ne voyage :
  seulement le rôle du signataire.
* M10 (`m10_lire_faits_strategiques`, T0) range l'événement tel quel, par liste blanche et formes fermées, au niveau FINANCIAL (jamais
  dans un paquet de contexte) ; le texte est rendu comme DONNÉE non fiable. Depuis M9-C1, le genre `risque` (statut `signale_par_le_radar`)
  y range aussi l'escalade INTERNE d'un risque critique du radar (texte seul : ni leçon, ni attendus, ni signataire ; voir M9-RADAR-SCENARIOS).

## 8. Évaluation

Le gabarit commun (`opsys-metier evaluer lancer`) lit `evals/gabarit.v1.yaml` : 12 cas de départ + 18 cas Athéna (30). Les trois corpus
existants (`corpus-v1`, `corpus-metier-v1`, `corpus-metier-v2`) gardent leurs empreintes (testé) ; un NOUVEAU fichier,
`evals/corpus-athena-v1.json` (66 cas : contrat des charges 15, certitude 13, tableau 9, recommandation 20, boucle 6, priorité 3), est
référencé par empreinte et exécuté par `m9_strategic_intelligence.evaluation_athena:evaluer` (`--avec-references`). Les attentes sont
écrites à la main avant l'exécution (outil de rédaction : `evals/generer-corpus-athena.py`).

| Répondant (simulé, aucun modèle réel) | Gabarit M9 | Qualifié | Sondes d'autorité |
|---|---|---|---|
| `reference` | 29/29 (le cas `m9-injection-veille` porte le pack rénovation) | oui | 4/4 |
| `dangereux` | 20/29 | non | 4/4 tenues |
| `inventif` | 0/29 | non | 4/4 tenues |

Corpus référencés avec `reference` : `corpus-v1` 61/61, `corpus-metier-v1` 58/60, `corpus-metier-v2` 75/77, `corpus-athena-v1` 66/66.
**Rouges connus conservés tels quels** : `mkt-A07` (le type d'action est déclaré par le modèle) et `rep-V02` (un entier nu écrit en
hypothèse reste admis par la couche du conseil historique). Le contrôle de recommandation d'Athéna est plus strict que cette couche : aucun
nombre libre, entier nu compris (`rg-entier-libre`) ; la limite du texte écrit en lettres (« trois mois ») reste.

## 9. Droits, registre MCP, niveaux

| Outil | Niveau | Qui |
|---|---|---|
| `m9_briefing_direction`, `m9_tableau_direction`, `m9_exige_la_direction`, `m9_changements_depuis`, `m9_verifier_recu_changements`, `m9_controler_recommandation`, `m9_lire_boucle_decisions` | T0 / N0 | admin authentifié (console ou appareil relu en base) ; **aucun rôle d'appareil** |
| `m9_rafraichir_lectures_direction`, `m9_mesurer_resultat_decision`, `m9_publier_faits_strategiques` | T1 / N2 | admin authentifié ; effet interne seulement (captures, résultat, événement interne) |
| `m9_consigner_decision_direction`, `m9_valider_lecon_decision` | T1 / **N3** | sous LEUR demande approuvée par un propriétaire actif ; un appel direct n'a aucun mandat |
| `m8_lire_synthese_direction`, `m5_lire_statut_revue_fiscale`, `m10_lire_faits_strategiques` | T0 / N0 | lectures T0 ajoutées chez les producteurs, fermées aux appareils |
| `m9_chiffrer_scenario`, `m9_lister_scenarios_chiffres`, `m9_lire_avis_risques` | T0 / N0 | admin authentifié (console) ; aucun rôle d'appareil — voir [M9-RADAR-SCENARIOS](M9-RADAR-SCENARIOS.md) |
| `m9_escalader_risques_critiques` | T1 / N2 | admin authentifié (console) ; avis, tâche et mémoire INTERNES, aucun message externe |
| `m4_projeter_capacite_hypotheses`, `m4_verifier_recu_projection_capacite` | T0 / N0 | calculs de M4 appelés par le port de M9 (`CALCULS_AUTORISES`), fermés aux appareils |

Compteur d'outils : 537 → 552 (+15). Registre MCP resellé (`opsys-metier registre-mcp sceller`). Le garde statique
`tests/test_m9_acces_strict.py` couvre `outils_athena.py` (chaque outil appelle `exiger_admin_strict`).

## 10. Preuves

Voir le rapport de livraison (comptes exacts des suites, mutations, rouges avant/après) : tests écrits avant le code et rouges sans lui
(les modules n'existaient pas) ; `departments/m09-strategic-intelligence/tests/` (`test_charges_athena`, `test_tableau_direction`,
`test_recommandation_gouvernee`, `test_boucle_decisions`, `test_evaluation_athena`), `departments/m08-analytics/tests/test_synthese_direction.py`,
`departments/m10-memoire/tests/test_strategique.py`, `tests/test_m9_athena_raccord.py` (vrais départements M8, M5, M2, M10),
`tests/test_m9_boucle_decisions_integre.py` (vraie file d'approbation et vrai bus).

## 11. Ce qui n'est PAS prouvé (suivi explicite)

* **Aucun modèle réel** : ni le conseil, ni le briefing, ni la boucle n'ont été mesurés avec un modèle ; la qualification d'Athéna reste
  OUVERTE. Le contrôle de recommandation ne juge pas la qualité d'un raisonnement.
* **Pas de planification** (décision confirmée par l'inventaire de [PLANIFICATION.md](PLANIFICATION.md) : « ne jamais automatiser ») : aucun cron ne rafraîchit les lectures ; un agent de planification n'a pas d'identité d'admin, donc le port
  le refuse (hôte opérateur de M9.5 : toujours ouvert). Le rafraîchissement est un geste de l'admin (console, app).
* **Aucun écran mobile** : ces outils n'ont aucun rôle d'appareil (décision de ne rien élargir) ; l'écran admin de M9.22 reste à faire.
* **Données fictives seulement** ; la santé de l'entreprise reste indéterminée tant que la direction n'a pas déclaré les bornes et validé les
  pondérations (décisions du propriétaire : `configuration.sante` de M8).
* **PostgreSQL** non exercé ; **Core natif** non exercé ; le vrai bus et la vraie file d'approbation le sont (SQLite).
* **Fraîcheur du pipeline M2** : M2 ne déclare aucun instant métier ; la couverture le dit (`TEMPS_METIER_NON_DECLARE`), M9 ne l'invente pas.
* **Nombres écrits en lettres** dans une recommandation : non détectables.
* **Reçus M5** : intégrité des empreintes vérifiée, rejeu non fait par M9 (appartient à `m5_verifier_recu_calcul`).
* Lectures par affaire (M3 contexte de site, M4 ETA / adéquation) et dossier CPA : non raccordés (voir § 1).

## 12. Radar complété, escalade interne et scénarios chiffrés (2026-11-02)

Le radar de risques compte 21 règles aux seuils déclarés par la direction (les lectures M1, M2, M3, M4, M7 et le cash libre y sont
consommées), un risque critique crée un avis, une tâche et une trace de mémoire INTERNES, et les scénarios « et si » sont chiffrés par
les moteurs des propriétaires (M5, M4, M2) avec leurs reçus : [M9-RADAR-SCENARIOS.md](M9-RADAR-SCENARIOS.md). Les limites du § 11 restent
vraies, notamment : rien ne tourne seul (aucun cron, décision de Nathan en attente) et aucune qualité de conseil n'est établie.
