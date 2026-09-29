# M4-field-ops

Field Operations OS — cedule, dispatch, GPS prive, Work Completion Trigger

Statut: PARTIAL (EPIC G — vague 1 livrée en mode ombre : encodage canonique injectif, registre
append-only hash-chaîné, contrats et frontières, machine à états 7 statuts, cédule déterministe,
pointage horodaté et géolocalisé, écarts et file pending_review, Work Completion Trigger en
maillon composite atomique, digest et gardes de conformité. 427 tests.)

PLAN T1.4-k — contrôle d'accès par personne et par intervention (`acces.py`, pur ; détail et limites
dans `docs/architecture/ROLES.md`). Pour un appel d'appareil, l'identifiant de technicien EST celui de la
personne OPSYS authentifiée (`opsys.contexte.identite_appelante()`, revérifiée en base à chaque appel).
Un `employee` n'agit que sur les interventions qui lui sont assignées (`REJ-INTERVENTION-NON-ASSIGNEE`) et
sous son propre identifiant (`REJ-IDENTITE-FOURNIE-DIFFERENTE`, jamais remplacé en silence) : `m4_pointer`,
`m4_demarrer_route`, `m4_signaler_report`, `m4_creer_demande_ecart`, `m4_completer_intervention` ;
`m4_lister_interventions` et `m4_statut_intervention` ne lui montrent que les siennes. L'`admin` garde
toutes les interventions ; un appel sans identité d'appareil (agent, console) se comporte comme avant.
L'assignation entre au registre à la planification (maillon `assignation_technicien`,
`etats.assigner_technicien`) : sans elle, aucune intervention n'était « à quelqu'un » avant son départ.
`m4_definir_consentement_gps` est ouvert à l'employé pour SA personne seulement (retrait du consentement
GPS, POLITIQUE-geolocalisation §4) ; `accede_par` de `m4_lire_position_gps` doit être la personne
authentifiée.

## Localisation des chantiers

PLAN T4.1-a — localisation des chantiers (`localisation.py`, pur ; conception : `docs/research/R15-cedule-vrp.md`
§3 et §4). Sans coordonnées CONFIRMÉES, un chantier n'entre pas dans une tournée : il reste « coordonnées
manquantes : à confirmer ». Deux outils, réservés à l'`admin` (portée : `docs/architecture/ROLES.md`) :
- `m4_proposer_localisation` (T0, lecture seule) : normalise l'adresse (accents, `œ`, `St-`, abréviations de
  génériques, point cardinal) et la cherche par correspondance EXACTE dans l'index local du Référentiel
  québécois des adresses (RQA, CC-BY 4.0). Une correspondance unique de qualité `Bâtiment`, `Accès propriété`,
  `Front lot` ou `Centre lot` donne une PROPOSITION (microdegrés entiers, précision, identifiant et version RQA).
  Aucune, plusieurs, `Géocodée`, `Incertaine`, `Site` ou adresse non certifiée : verdict
  `REJ-COORDONNEES-A-CONFIRMER` avec la raison et les candidats, jamais une position choisie ni le centre d'une
  ville. Index non importé : `REJ-INDEX-RQA-ABSENT`. Aucun accès réseau (un test bloque les sockets).
- `m4_confirmer_localisation` (T1, N3 : voir le commentaire de l'outil) : écrit le maillon `localisation_chantier`,
  clé `chantier_id` (v1 : le `lead_id`), `version` croissante, `action` `confirmee` ou `retiree`, `source` `rqa`
  (coordonnées lues dans l'index par `rqa_identifiant`, jamais des arguments) ou `manuel` (saisie de l'humain,
  marquée telle). Le dernier maillon gagne, l'historique reste. Les coordonnées sont chiffrées avec une clé par
  chantier (`opsys.cles_chiffrement`, portée `m04-field-ops/localisation`) : détruire la clé rend la position
  illisible, la chaîne reste valide. L'adresse n'entre jamais au registre, seulement `empreinte_adresse` (HMAC
  d'une clé dérivée de celle du chantier). `confirme_par` est la personne authentifiée pour un appel d'appareil ;
  l'heure du serveur fait foi. Un motif est exigé pour remplacer, retirer ou confirmer une position faible.
  Pour la suite (T4.1-c) : `outils.lire_localisation_confirmee(registre, chantier_id)` rend les coordonnées
  confirmées ou le verdict « à confirmer ».

Importer le RQA (à refaire chaque mois, l'ancien index est remplacé de façon atomique) :
`python -m m4_field_ops.localisation importer --csv RQA.csv --index "${OPSYS_HOME:-$HOME/.opsys}/rqa/index.sqlite"
[--mrc CODE_OU_NOM ...] [--version AAAA-MM-JJ]`. Les colonnes lues sont celles du guide d'utilisation du RQA v1.2
(2026-09-01) ; le CSV réel (596 Mo) n'a pas pu être téléchargé depuis le bac à sable, donc le format est celui du
guide, non celui d'un fichier vu. Les adresses détruites, sans numéro ou aux coordonnées illisibles ou hors du
Québec sont écartées et comptées dans le rapport ; un import qui ne donne rien laisse l'index en place.
L'attribution CC-BY 4.0 est le champ `attribution` de la réponse de `m4_proposer_localisation` : l'écran de
confirmation de l'app admin doit l'afficher là où l'adresse est validée.

## Distances

PLAN T4.1-b (conception : `docs/research/R15-cedule-vrp.md` §2 et §4). `distances.py` (pur) fabrique la
matrice de trajets entre chantiers que le solveur de tournées recevra en entrée (T4.1-c) : carrée, triée par
identifiant, en mètres et en secondes ENTIERS, hachée avec ses paramètres (`empreinte`, SHA-256 canonique,
`version` `matrice-distances-v1`). Aucun outil MCP ici : T4.1-d les ajoutera.

- **Palier 0, par défaut** : haversine entière × détour. Les coordonnées sont des microdegrés entiers
  (45,742° = `45742000`). Le calcul est en virgule fixe sur des entiers Python, sans flottant : même matrice et
  même empreinte sur toute plateforme (testé contre une référence `Decimal` et sur trois graines de hachage).
  La matrice porte `mode_distance: "haversine_detour"` et `mode_bride: true` : l'écran de dispatch affiche
  « mode bridé ».
- **Trois paramètres d'entreprise obligatoires**, sans valeur par défaut : `facteur_detour_milliemes` (1300 pour
  1,3 ; 1000 à 3000), `vitesse_moyenne_kmh` (10 à 110), `marge_par_trajet_secondes` (0 à 3600). Absents, non
  entiers ou hors bornes : un verdict qui dit quoi fournir. Les bornes sont des limites d'acceptation, pas des
  valeurs de départ. R15 propose 1,3 ; 50 km/h ; 10 min pour démarrer, non sourcés : à calibrer.
- **Palier 1, optionnel** : le port `FournisseurMatrice` et, dans `distances_osrm.py`, un adaptateur du service
  `table` d'un sidecar OSRM LOCAL (`creer_fournisseur_osrm(url_base, version_donnees)`). Il n'est jamais appelé
  sans que l'appelant le passe à `obtenir_matrice`. L'URL doit être locale (boucle locale, réseau privé, nom de
  service sans point) : les coordonnées d'un chantier ne quittent pas le serveur (Loi 25). Aucune redirection ni
  mandataire suivis ; délai de 1 à 30 s.
- **Repli explicite** : si OSRM est injoignable, trop lent ou répond de travers, `obtenir_matrice` rend la matrice
  du palier 0 avec `mode_bride: true` et `repli: {depuis, code, detail}`, dans l'empreinte. Jamais silencieux.
  Un trajet que OSRM dit introuvable (cellule `null`, `NoSegment`) n'est PAS une panne : verdict
  `REJ-MATRICE-TRAJET-INTROUVABLE`, sans repli, car le palier 0 inventerait une route.
- **Étalonnage** : `ecart_etalonnage` mesure l'écart du modèle à une distance routière de référence.
  `tests/fixtures/etalonnage_lanaudiere.json` est FICTIVE (`fictif: true`) : elle montre la mécanique et le genre
  d'écart attendu près d'un cours d'eau. Le vrai détour se calibre sur au moins 30 paires réelles mesurées avec
  OSRM (R15 §2).

Limites connues : les verdicts `REJ-MATRICE-*` sont hors du catalogue gelé de `verdicts.py` (T4.1-d les y
inscrira) ; l'adaptateur n'a été testé que contre un faux serveur (forme de réponse d'après la documentation
d'OSRM, à confirmer sur un vrai sidecar) ; la distance entre un point et la route où OSRM l'accroche n'est pas
contrôlée.

## Tournées

PLAN T4.1-c (conception : `docs/research/R15-cedule-vrp.md` §1 et §4). `tournees.py` (pur, sans horloge ni
aléa) propose un plan de tournées à partir des équipes, des chantiers et de la matrice de T4.1-b. Le solveur
PROPOSE ; il n'écrit pas la vérité. Aucun outil MCP ici : T4.1-d ajoutera `m4_proposer_cedule` et
`m4_appliquer_cedule`. `cedule.py` reste le repli « sans coordonnées ».

- **Interface** : `resoudre(entree, moteur="auto")` rend `(sortie, None)` ou `(None, verdict)`. Tout est entier
  (minutes depuis minuit, mètres). L'entrée porte `version` (`tournees-entree-v1`), `equipes` (`id`,
  `competences`, `depot`, `quarts` : `jour`, `debut_min`, `fin_min`), `chantiers` (`id`, `duree_min`,
  `fenetre` : `jours`, `debut_min`, `fin_min` ; `competences_requises`, `urgence` de 0 à 3, `creneau_fige` :
  `null` ou `equipe`, `jour`, `debut_min`), `matrice` (celle de `distances.obtenir_matrice`, revérifiée) et
  `parametres` (`graine`, `iterations`, `cout_non_cedule_m`).
- **Modèle** : un véhicule est un couple (équipe, jour). La fenêtre du client dit les jours permis et
  l'intervalle où le chantier doit être ENTIÈREMENT réalisé. Une équipe ne reçoit un chantier que si elle a
  TOUTES ses compétences. Le trajet est le plafond en minutes des secondes de la matrice (marge comprise).
  Objectif : mètres parcourus + `cout_non_cedule_m` x (1 + urgence) par chantier laissé de côté.
- **Fail-closed** : durée par type de travaux, fenêtre, compétences, dépôt, quarts, graine, itérations et coût de
  non-cédule sont des ENTRÉES. Absents, le verdict liste tout ce qu'il faut fournir (`REJ-CHAMP-MANQUANT`) ; jamais
  de valeur par défaut. Un chantier sans coordonnées (absent de la matrice) n'entre pas au solveur : il sort en
  `non_cedulees` avec « coordonnées manquantes : à confirmer ». Exception voulue : un créneau figé sans
  coordonnées refuse toute l'entrée, car un créneau promis au client ne se perd pas. Un créneau figé intenable
  (équipe, jour, compétence, fenêtre, quart, ou conflit avec un autre figé) refuse l'entrée
  (`REJ-TOURNEES-CRENEAU-FIGE-INCOMPATIBLE`) ; un créneau figé n'est jamais déplacé.
- **Deux moteurs** : PyVRP 0.14.0 (MIT, extra `tournees`, import paresseux, `MaxIterations` seulement, graine
  dérivée de l'empreinte d'entrée ; compétences et jours par profils de matrice, arêtes interdites) et un DP exact
  en bibliothèque standard, repli sans dépendance jusqu'à 12 chantiers entrés au solveur et oracle des tests.
  Sans PyVRP (absent ou autre version que l'épinglée) : le DP jusqu'à 12 chantiers, sinon « solveur de tournées
  non installé : installer l'extra tournees » (`REJ-TOURNEES-SOLVEUR-ABSENT`). Installation :
  `pip install -e ".[tournees]"` (la roue de PyVRP tire numpy, matplotlib, tqdm et vrplib, toutes sous licence
  permissive).
- **Sortie** : `plan` (une route par équipe et jour : `depart_min`, `retour_min`, `distance_m`, `visites` avec
  `arrivee_min`, `debut_min`, `fin_min`), `non_cedulees` (`chantier`, `code`, `raison`, `action`), `totaux` et
  `meta` (solveur et version, graine, itérations, empreintes d'entrée, de sortie et de matrice, `mode_distance`,
  `mode_bride`). Triée par équipe, jour, heure, puis identifiant : mêmes octets pour la même entrée, quel que
  soit `PYTHONHASHSEED`.
- **Raisons de non-cédule** calculées par NOTRE code après la résolution, jamais reprises du solveur :
  `coordonnees_manquantes`, `competence_indisponible`, `duree_trop_longue`, `fenetre_inatteignable`,
  `journees_pleines` (aucune insertion valide sans bousculer le plan), `cout_superieur_au_cout_non_cedule` (avec
  le supplément exact en mètres) et `insertion_possible_non_retenue`.
- **Validateur** : `verifier_plan(entree, sortie)` rend `(True, [])` ou `(False, violations)`. Il ne reprend rien du
  solveur et refuse une fenêtre, un quart, une compétence, un jour ou un créneau figé violés, un chantier visité
  deux fois, inventé, sans coordonnées ou oublié, un trajet ou une distance faux, une raison qui diffère du
  diagnostic recalculé et une empreinte qui ne correspond plus à la sortie. `resoudre` l'applique à son propre plan
  avant de le rendre (`REJ-TOURNEES-PLAN-INVALIDE` sinon), et à celui d'un moteur défaillant
  (`REJ-TOURNEES-SOLVEUR-ECHEC`).

Preuve : sur six instances fictives de 8 à 12 chantiers (Repentigny à Joliette, coordonnées approximatives), PyVRP
(2 000 itérations) égale le DP exact (écart 0) ; le DP égale une énumération exhaustive indépendante sur douze
instances aléatoires ; 8 chantiers se résolvent en moins d'une seconde (mesuré : 0,002 s au DP ; PyVRP 0,15 s au
premier appel, import compris, puis 0,08 s) ; une compétence rare n'est jamais donnée à une équipe non admissible.

Limites connues : les verdicts `REJ-TOURNEES-*` sont hors du catalogue gelé de `verdicts.py` (T4.1-d les y
inscrira) ; les chantiers de plusieurs jours, la météo, les capacités de véhicule et l'ETA client restent hors
périmètre (R15 §4) ; la cédule n'est pas encore branchée sur les coordonnées confirmées (T4.1-a) ni sur un outil ;
PyVRP n'a été exécuté qu'en Python 3.11 sur x86_64 (l'égalité entre plateformes n'est pas vérifiée) ; le DP est
exponentiel : pire cas mesuré à 12 chantiers de 30 à 45 min sur 8 véhicules, environ 2 s ; au-delà de 12 chantiers,
PyVRP est requis. La CI (`ci.yml`, job `departement`) n'installe que `.[dev]` : tant que `.[dev,tournees]` n'y figure pas,
les tests de PyVRP y sont sautés et seul le DP est exercé.
