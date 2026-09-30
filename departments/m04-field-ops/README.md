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
`version` `matrice-distances-v1`). Aucun outil ne l'expose seul : `m4_proposer_cedule` (T4.1-d) la fabrique.

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

Les verdicts `REJ-MATRICE-*` sont inscrits au catalogue de `verdicts.py` (T4.1-d). Limites connues :
l'adaptateur n'a été testé que contre un faux serveur (forme de réponse d'après la documentation d'OSRM, à
confirmer sur un vrai sidecar) ; aucun sidecar n'est déployé, donc `m4_proposer_cedule` reste au palier 0 (mode
bridé) tant que `outils(fournisseur_matrice=...)` ne reçoit pas un fournisseur ; la distance entre un point et la
route où OSRM l'accroche n'est pas contrôlée.

## Tournées

PLAN T4.1-c (conception : `docs/research/R15-cedule-vrp.md` §1 et §4). `tournees.py` (pur, sans horloge ni
aléa) propose un plan de tournées à partir des équipes, des chantiers et de la matrice de T4.1-b. Le solveur
PROPOSE ; il n'écrit pas la vérité. Les outils `m4_proposer_cedule` et `m4_appliquer_cedule` (T4.1-d, section
suivante) l'appellent. `cedule.py` reste le repli « sans coordonnées ».

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

Les verdicts `REJ-TOURNEES-*` sont inscrits au catalogue de `verdicts.py` (T4.1-d). `empreinte_entree(entree)`
rend l'empreinte que le plan porte, sans relancer le solveur (l'application d'un plan s'en sert). Limites connues :
les chantiers de plusieurs jours, la météo, les capacités de véhicule et l'ETA client restent hors périmètre (R15
§4) ; PyVRP n'a été exécuté qu'en Python 3.11 sur x86_64 (l'égalité entre plateformes n'est pas vérifiée) ; le DP
est exponentiel : pire cas mesuré à 12 chantiers de 30 à 45 min sur 8 véhicules, environ 2 s ; au-delà de 12
chantiers, PyVRP est requis. La CI (`ci.yml`, job `departement`) installe l'extra `tournees` pour M4, et l'image
(`deploy/Dockerfile`) aussi.

## Cédule par tournées

PLAN T4.1-d (conception : `docs/research/R15-cedule-vrp.md` §4 ; skill `optimiser-la-cedule`).
`cedule_tournees.py` (pur : ni `opsys`, ni horloge, ni aléa, ni flottant, ni réseau, gardé par analyse du code)
assemble l'entrée du solveur, le fait résoudre et range le plan au registre. Deux outils, réservés à l'`admin`
(portée : `docs/architecture/ROLES.md`) :
- `m4_proposer_cedule` (T1, niveau N1 : un brouillon, automatique) : lit au registre les interventions au statut
  `planifiee` (et, depuis T4.12, les `a_planifier` dont la préparation est prête), leur `urgence_declaree` et les
  coordonnées CONFIRMÉES (`outils.lire_localisation_confirmee`), et lit le reste dans le PROFIL DES ÉQUIPES de
  l'entreprise (section « Profil des équipes »), ou en arguments (surcharge tracée). Range le maillon `cedule_proposee` (plan complet, entrée sans matrice donc
  sans coordonnée de chantier, état des interventions, trois empreintes : entrée, sortie, état) et rend `plan_id`,
  `mode_distance`, `mode_bride` et un `avertissement` « mode bridé » quand les distances sont approximatives, les
  `non_cedulees` et leurs raisons. Aucune assignation. Même entrée : même plan, même `plan_id`, rien d'écrit de
  plus (`deja_proposee`).
- `m4_appliquer_cedule` (T1, N3 : voir le commentaire de l'outil) : applique un plan par son `plan_id` avec
  `etats.assigner_technicien` (maillon `assignation_technicien`), puis écrit `cedule_appliquee`. Toutes les
  vérifications précèdent la première écriture : (1) l'état actuel des interventions (statut, type, urgence,
  technicien assigné, version de la localisation) doit être celui de la proposition ; (2) l'entrée du solveur,
  reconstruite avec les coordonnées d'AUJOURD'HUI, doit avoir la même empreinte ; (3) `tournees.verifier_plan`
  doit accepter le plan (fenêtres, quarts, compétences, créneaux figés). Sinon `REJ-CEDULE-ENTREE-CHANGEE` (le
  détail nomme ce qui a bougé : proposer de nouveau) ou `REJ-TOURNEES-PLAN-INVALIDE`. Idempotent : le même
  `plan_id` deux fois n'écrit rien de plus (`deja_appliquee`) ; un technicien déjà assigné n'est pas ré-assigné
  (`effet: deja_assignee`). `confirme_par` est la personne authentifiée pour un appel d'appareil.

Ce que M4 SAIT (jamais fourni) : les interventions à planifier, leur nature de travaux (`type_travaux` d'un lead v1
ou `service` d'un lead v2, jamais l'un déduit de l'autre), leur urgence déclarée, le
technicien déjà assigné, les coordonnées confirmées. Depuis T4.12, ce qui suit vient du profil des équipes quand
l'appelant ne le donne pas ; ce que ni le profil ni un argument ne donne est UN verdict `REJ-CHAMP-MANQUANT` qui liste
tout ce qu'il faut fournir et où le déclarer, aucune valeur par défaut : `equipes` (`id`,
`competences`, `depot` : `id`, `latitude_microdegres`, `longitude_microdegres`, `quarts`), `durees_par_type_travaux`,
`competences_par_type_travaux` (leads v1 ; `{}` s'il n'y en a pas dans le lot), `durees_par_service` et
`competences_par_service` (leads v2, exigés seulement si le lot en contient : une clé par service déclaré par
l'entreprise), `chantiers` (une entrée par intervention : `fenetre` du client et `creneau_fige`,
`null` seulement si aucun créneau n'est confirmé au client) et `parametres` (`facteur_detour_milliemes`,
`vitesse_moyenne_kmh`, `marge_par_trajet_secondes`, `iterations`, `cout_non_cedule_m`). Seule exception, technique
et non métier : la `graine` du solveur, 0 si omise (PyVRP est amorcé par l'empreinte de l'entrée de toute façon).
L'`id` d'une équipe EST le `technicien_id` de l'assignation ; `jour` est un numéro de journée de la cédule.

**Urgence.** `urgence_declaree` (booléen du LeadQualifie) devient l'entier 0 à 3 du solveur par une règle écrite,
`cedule_tournees.REGLE_URGENCE` : vrai vaut 1, faux vaut 0, source absente ou non booléenne est un verdict. Un chantier
urgent coûte le double à laisser de côté (`cout_non_cedule_m` x (1 + urgence)). Un test relit les sources citées
(DEFINITION-PRODUIT M4.7, audit M4 risque 10, `contrats.py`, R15 §4, `tournees.py`). Les crans 2 et 3 restent libres
pour une source plus fine (score d'urgence de M1) : aucun n'est inventé. Le champ n'était lu par personne avant.

**Créneau figé.** Un créneau déjà confirmé au client (`creneau_fige`) est tenu à la minute, ou l'entrée est
refusée (`REJ-TOURNEES-CRENEAU-FIGE-INCOMPATIBLE`) : il n'est jamais déplacé. Le solveur, puis `verifier_plan` à
l'application, le contrôlent.

Preuve (scénario fictif de Repentigny à Joliette, `tests/fixtures/scenario_cedule_repentigny_joliette.json`, six
chantiers, deux équipes qui partent de leur dépôt, positions confirmées par `m4_confirmer_localisation`) : le plan
proposé fait 26 785 m (11 794 m pour l'équipe de Repentigny, 14 991 m pour celle de Joliette) contre 187 601 m pour le
tourniquet de `cedule.py` avec le sel de référence, sur la même matrice, soit 85 % de moins. Sur treize sels, le
tourniquet va de 28 806 m (le hasard forme les mêmes grappes, dans un autre ordre) à 343 133 m, en moyenne 199 422 m :
le plan est meilleur pour chacun. Deux chantiers proches vont à la même équipe, l'un après l'autre ; un créneau figé à
10 h chez l'équipe de Joliette est tenu (mais coûte : un chantier de plus reste non cédulé, « journées pleines ») ;
une coordonnée modifiée entre la proposition et l'application refuse l'application sans rien écrire ; un appel
d'appareil `employee` est hors portée.

Limites connues : le jour et l'heure de chaque visite restent dans le maillon du plan, l'écran « chantiers du jour »
ne les lit pas encore (`fenetre_planifiee` reste `null`) ; une intervention non cédulée garde l'assignation qu'elle
avait (aucun outil de désassignation) ; en `supervise` et `autonome`, un N3 s'exécute sans file (`ROLES.md`, « Ce qui
reste ») ; aucun sidecar de routage : distances approximatives (« mode bridé »), à calibrer sur 30 paires réelles ;
le dépôt est gardé en clair au maillon du plan (c'est un lieu de l'entreprise : ne pas y mettre un domicile) ; une
adresse modifiée après la confirmation des coordonnées n'est pas vue par la cédule (M4 ne connaît pas l'adresse,
seulement la version de la confirmation) ; un plan proposé n'expire pas, seul un changement d'état l'invalide.

## Une soumission acceptée fait naître une intervention à planifier (PLAN T4.10-b)

DEFINITION-PRODUIT §6 (« soumission acceptée → M4 planifie ») et §7 M4.5, M4.6. Avant, M4 n'avait aucun état avant
`planifiee` et personne ne lui disait qu'un devis venait d'être accepté. Trois pièces :

- **`a_planifier`, un état additif** (`etats.py`). Il s'ajoute EN FIN de `ETATS` ; les huit états et les seize couples
  d'avant sont intacts (test d'épinglage), et la table complète, 18 couples, est balayée dans les deux sens
  (`test_etats.py`). Deux couples s'ajoutent : `a_planifier → annulee` (sans condition) et `a_planifier → planifiee`,
  qui exige un verdict de préparation `pret` (voir plus bas) : vérifié dans `etats.transitionner`, à la source, pour
  tenir quel que soit l'outil (`empreinte_preparation` : un verdict modifié après coup ne passe pas). Une intervention
  inscrite par `m4_planifier_intervention` naît toujours `planifiee`, inchangé ; la cédule par tournées ne planifie
  toujours que `planifiee` (`STATUT_PLANIFIABLE`).
- **Le consommateur de `m3.devis_accepte`** (`department.yaml`, `_recevoir_devis_accepte` dans `outils.py`, sans import de
  M2 ni de M3). Le devis porte `devis_id` et `lead_id`, pas le service, la ville ni l'urgence : M4 les relit **à la source
  du bus**, dans le `m1.lead_qualifie` de ce lead (`evenements.charge_publiee`, même patron que M3 pour
  `m2.lead_assigne`), jamais d'un argument ni d'une valeur par défaut. `etats.inscrire_depuis_devis` valide ce lead comme
  partout dans M4 (frontières, contrat v2, service déclaré au profil d'entreprise) et écrit le maillon
  `intervention_inscrite` : `statut: a_planifier`, `source: m3.devis_accepte`, l'heure de l'acceptation (jamais une
  horloge de M4), le service, l'urgence, la ville **tokenisée** avec un sel d'instance tenu au coffre du socle
  (`opsys.cles_chiffrement`, portée `m04-field-ops/sel-ville`). Aucun contact, aucune ville en clair, aucun identifiant
  de conversation, aucun prix, aucune date ni aucun créneau n'entrent au registre. Idempotent : une intervention qui porte
  déjà ce `devis_id` (rejeu, autre `evenement_id`, ou intervention planifiée à la main avant) est reconnue avant toute
  lecture, `deja_applique`. Un fait absent lève, le répartiteur réessaie puis met en quarantaine (`opsys-metier evenements etat`) :
  `FaitDeLeadManquant` (aucun `m1.lead_qualifie` pour ce lead : un lead saisi directement dans M2 se planifie par
  `m4_planifier_intervention`, avec son contrat complet) ou `InscriptionDevisRefusee` (service retiré du profil, horodatage
  invalide). Un lead qui arrive après le devis (ordre inversé) est repris au réessai, sans doublon.
- **La préparation** (`preparation.py`, M4.6, pur, gardé par analyse du code) et son outil `m4_verifier_preparation` (T0,
  admin seulement, lecture seule). Le verdict est une liste de volets : `soumission` (le devis qui a fait naître
  l'intervention), `adresse` (coordonnées CONFIRMÉES, lues comme la cédule les lit : le chantier est le `lead_id`),
  `equipe`, `materiel`, `meteo`. Chaque volet est `ok` (lu à sa source), `manque` (attendu et absent : le champ `manque`
  dit quoi fournir) ou `non_verifiable` (M4 n'a pas de quoi le lire). Depuis T4.13, aucun volet n'est plus sans source
  (l'équipe l'était avant T4.12, le matériel avant T4.14-b, la météo avant T4.13) : le verdict d'ensemble est `pret`
  SEULEMENT si tous les volets sont `ok`, sinon `bloque` ou `non_verifiable` ; la porte `a_planifier → planifiee` s'ouvre
  pour une intervention dont M6 dit le matériel prêt et dont le service a ses règles météo. Le verdict ne rend ni
  coordonnée, ni contact, ni prix.

Preuve : `tests/test_consommer_devis_accepte.py` (bus réel, M4 seul), `tests/test_etats_a_planifier.py`,
`tests/test_preparation.py`, la table de `tests/test_etats.py`, et `tests/test_cascade_devis_accepte.py` du socle (M1 → M2
→ M3, puis M2 converti, M4 à planifier, M5, M6 et M8 comme avant, rejeu et ordre inversé sans doublon).

Limites connues : le mobile (`StatutInterventionM4`) ne connaît pas `a_planifier` (un employé ne le voit jamais : rien
ne lui est assigné). Levées par T4.12 (section suivante) : la sortie de `a_planifier` (`m4_appliquer_cedule`), le volet
« équipe » (vérifié depuis le profil) et la garde contre le doublon de `m4_planifier_intervention`.

## Profil des équipes, admissibilité et sortie de `a_planifier` (PLAN T4.12)

DEFINITION-PRODUIT §7 M4.2, M4.3 et M4.7 ; limite de T4.1-d (« tout est argument »). Avant, l'agent recopiait équipes,
dépôt, quarts et durées à chaque cédule. Quatre pièces :

- **Le profil des équipes** (`opsys.equipes`, socle ; clé `equipes` de `$OPSYS_HOME/entreprise.yaml`, même mécanisme et
  même signature au journal d'audit que les services et la zone desservie ; forme et règles dans
  `docs/architecture/TAXONOMIE.md`). `opsys-metier equipes lister` et `opsys-metier equipes declarer --depuis equipes.yaml --par
  nathan`. Équipes (membres = personnes OPSYS existantes, compétences, dépôt, quarts), durée et compétences par service,
  réglages de la cédule, fenêtre par défaut d'un chantier `a_planifier`. Aucune donnée de ressources humaines, de santé
  ni d'évaluation : le schéma est fermé. Sans profil : verdict qui dit quoi déclarer, jamais un repli ; profil invalide :
  `REJ-PROFIL-INVALIDE`, jamais lu comme absent.
- **L'admissibilité** (`admissibilite.py`, pur, gardé par analyse du code). Une équipe est admissible pour un service si
  elle détient TOUTES ses compétences et si l'un de ses quarts est assez long pour sa durée ; chaque équipe écartée dit
  pourquoi. C'est une condition nécessaire : le solveur ajoute trajets, fenêtre du client et charge des journées. Elle
  devient le volet `equipe` de `preparation.py` : `ok` (les équipes admissibles sont nommées), `manque` (sans profil, avec
  un profil invalide, sans durée pour ce service, sans équipe admissible : le volet dit quoi déclarer ou ajuster), ou
  `non_verifiable` pour un lead v1 (le profil est par service). Le matériel se lit depuis T4.14-b et la météo depuis
  T4.13 (sections suivantes).
- **`m4_proposer_cedule` lit le profil sans argument.** Un argument donné REMPLACE la clé entière du profil (jamais une
  fusion) : c'est une surcharge, tracée (`provenance` : `profil` ou `surcharge`, par clé et, pour `chantiers`, par
  intervention ; `empreinte_profil` au maillon). Une intervention `a_planifier` sans entrée dans `chantiers` prend la
  fenêtre par défaut du profil et AUCUN créneau figé : avant toute cédule, aucun créneau n'a pu être promis (T3). Une
  intervention `planifiee` exige toujours son entrée et son `creneau_fige` explicite. Les tables par type de travaux
  (leads v1, gelés) restent des arguments. Même valeurs, que le profil les donne ou que l'appelant les écrive : mêmes
  octets de plan, même `plan_id`.
- **La sortie de `a_planifier` passe par la cédule** (choix : `m4_appliquer_cedule`, pas un outil dédié). La cédule est
  l'endroit où l'équipe est choisie et vérifiée ; un outil « planifier » à part permettrait de sortir de `a_planifier`
  sans équipe, ou d'en assigner une sans passer la préparation. `m4_proposer_cedule` ne prend une `a_planifier` que si son
  verdict de préparation est « prêt » (les autres sont rendues dans `non_pretes`, avec ce qui leur manque ; une
  intervention demandée par `intervention_ids` et non prête est refusée, `REJ-CEDULE-PREPARATION-NON-PRETE`).
  `m4_appliquer_cedule` recalcule le verdict d'aujourd'hui pour chaque intervention qu'il place, la fait passer
  `a_planifier → planifiee` par `etats.transitionner` (la porte d'empreinte de T4.10 : le verdict est recalculé et sa
  propre empreinte vérifiée, un verdict truqué ou périmé ne passe pas), puis l'assigne. Toutes les vérifications
  précèdent la première écriture : préparation toujours prête, état et empreinte de préparation inchangés, profil
  inchangé si le plan en a lu des valeurs (`REJ-CEDULE-ENTREE-CHANGEE`), entrée du solveur inchangée, plan valide, et
  l'équipe qui reçoit une intervention sortante est admissible SELON LE PROFIL, même si le plan a été proposé avec des
  équipes en surcharge (`REJ-TOURNEES-PLAN-INVALIDE`). Une intervention que le plan laisse de côté reste `a_planifier`.
  Les membres d'une équipe agissent sur ses interventions (`docs/architecture/ROLES.md`) ; celui qui part devient le
  technicien.
- **Plus de doublon.** `etats.inscrire_intervention` (donc `m4_planifier_intervention`) refuse un `devis_id` qui a déjà
  une intervention, née du bus ou non, annulée ou non (un devis n'a qu'une intervention : `REJ-TRANSITION-ILLEGALE`, qui
  nomme l'intervention et dit de la préparer et de la céduler) ; sans `devis_id`, il refuse un lead qui a déjà une
  intervention active née du bus (fournir le `devis_id` d'un AUTRE devis lève le refus). L'autre ordre existait déjà : le
  consommateur du bus reconnaît une intervention planifiée à la main pour ce devis (`deja_applique`). Les deux ordres sont
  prouvés par le vrai bus, à M4 seul et sur les dix départements (`tests/test_cascade_devis_accepte.py`).

Preuve : `tests/test_equipes.py` et `tests/test_cli_equipes.py` du socle (profil et commande), `test_admissibilite.py`,
`test_preparation.py`, `test_cedule_tournees_profil.py` (module pur, profil injecté), `test_equipes_cedule.py` (vrais
outils, vrai bus, vrai fichier : la démonstration Repentigny-Joliette de T4.1-d rejouée depuis le profil seul, 26 785 m, les
mêmes octets de plan que les mêmes valeurs en arguments, y compris sur une seconde instance), `test_acces_par_equipe.py`.
Le fixture `tests/fixtures/equipes_repentigny_joliette.json` est FICTIF (`fictif: true`) et un test vérifie qu'aucun
chiffre n'a dérivé du scénario de T4.1-d.

Limites connues : à l'époque de T4.12, **matériel et météo étaient sans source : aucune intervention née du bus ne sortait de
`a_planifier`** (levé par T4.14-b et T4.13, sections suivantes) ; les tests de sortie de `test_equipes_cedule.py` SIMULENT
encore ces deux volets pour ne prouver que la plomberie de la cédule, un test prouve que la porte reste fermée sans eux. Et
comme un devis n'a qu'une intervention, le repli `m4_planifier_intervention` est fermé pour un devis dont l'intervention existe : le propriétaire
tranche s'il veut une attestation humaine d'un volet non vérifiable (aucune n'existe). `jour` est le numéro de journée du
solveur : pas de calendrier, pas de quarts par jour de la semaine ; les bornes des réglages de la cédule sont vérifiées par
M4 à l'usage, pas à la déclaration ; une planification à la main SANS `devis_id`, faite avant le devis accepté du même lead,
n'est pas reconnue par le bus (deux interventions : test épinglé) ; un membre n'est que d'une équipe ; le plan proposé avec des arguments complets ne lit pas le profil, donc un
changement du profil ne le périme pas (l'admissibilité, elle, reste jugée à l'application).

## Matériel prêt de M6 (PLAN T4.14-b)

DEFINITION-PRODUIT §7 M6 (« fournit à M4 : matériel prêt ou à commander ») et M4.6 (« matériel connu »). Avant, le volet
`materiel` de la préparation était `non_verifiable` : M4 ne recevait rien de M6. Trois pièces :

- **M4 consomme `m6.materiel_pret`** (`department.yaml`, `evenements.consomme` ; fonction `_recevoir_materiel_pret` dans
  `consommateurs()`), sans importer M6 ni lire son stock (un test le prouve par analyse du code). Le catalogue est celui de
  `src/opsys/evenements/catalogue/m6.materiel_pret.json` : une **révision** par changement de la réservation d'un devis
  accepté. Par `devis_id`, M4 retient la charge de **plus grande révision**, quel que soit l'ordre d'arrivée : une révision
  plus petite ou égale à celle déjà retenue n'écrit rien (`ignoree`), la même révision sous un autre `evenement_id` non
  plus. La charge peut arriver avant le devis (ordre inversé) : la préparation la relit à l'inscription. Le maillon
  `materiel_pret_recu` garde le `devis_id`, la révision, le statut, `reservation_active`, le déclencheur, les
  `lignes_manquantes` et l'heure du fait de M6 (jamais une horloge de M4) ; `chantier_id` (nullable) n'est **ni lu ni
  gardé**, et le détail des lignes reste chez M6.
- **`materiel.py`** (pur, gardé par analyse du code) : `charge_retenue`, `etat_du_materiel`, `lignes_manquantes_en_texte`.
  « Prêt » = `statut == "pret"` ET `reservation_active` ET `lignes_manquantes` vide ; un « pret » que le reste de la charge
  contredit (réservation libérée, ligne manquante) n'est jamais prêt.
- **Le volet `materiel` de `preparation.py`** : `ok` si prêt (« matériel prêt et réservé (M6, révision N) ») ; `manque`
  sinon, avec `detail` = `partiel` ou `a_commander` et les lignes manquantes (« matériau : quantité unité manquantes sur
  besoin ») ; aucune charge reçue, ou une intervention sans `devis_id` : `non_verifiable`. Aucun prix, aucun coût. M6 ne
  crée jamais de bon de commande seul : l'admin le demande à M6.

Preuve : `tests/test_materiel.py` (module pur : ordres d'arrivée, table d'états, analyse du code),
`tests/test_preparation.py` (`TestVoletMateriel`), `tests/test_materiel_pret_recu.py` (bus réel : M4 seul avec des charges
fictives, puis M4 et le VRAI M6 : devis accepté → `a_commander`, réception partielle → `partiel`, réception qui complète →
`pret`, libération → `a_commander` ; le volet suit chaque révision).

Limites connues : le stock de M6 ne déclare pas d'unité (M6 recopie celle du prévu) ; un prévu vide ne publie rien (M6
« ne dit rien plutôt que prêt ») donc le volet reste `non_verifiable` ; M4 ne re-publie ni ne demande jamais l'état à M6 : une
charge perdue reste perdue jusqu'à la prochaine révision.

## Météo des créneaux (PLAN T4.13)

DEFINITION-PRODUIT §6 (un chantier de revêtement sous un vent fort se reporte), §7 M4.10 (météo) et M4.21 (report). Avant,
le volet `meteo` de la préparation était `non_verifiable` et rien ne jugeait la météo d'une cédule. Six pièces :

- **Le profil météo** (`opsys.meteo`, socle ; clé `meteo` de `$OPSYS_HOME/entreprise.yaml` ; `opsys-metier meteo lister|declarer` ;
  forme et règles dans `docs/architecture/TAXONOMIE.md`). Par service, des seuils (vent, rafales, pluie, probabilité de
  pluie, gel, verglas, chaleur) à deux niveaux (`validation`, `blocage`) ou le risque déclaré `sans_objet` ; le fuseau ; le
  fournisseur ouvert. **Aucune valeur par défaut** : le propriétaire décide (GATE NATHAN), sinon « seuil à configurer ».
- **`meteo.py`** (pur, gardé par analyse du code : ni `opsys`, ni horloge, ni aléa, ni flottant, ni réseau) : le port
  `FournisseurMeteo` (sur le patron de `FournisseurMatrice` : des points de prévision horaires, une citation), et
  `evaluer_creneau`, qui juge un créneau contre les règles du service. Résultat : `bloquant` (un seuil de blocage franchi),
  `validation_requise` (un seuil de validation franchi), `ok`, ou `inconnu` (règle sans décision, mesure absente ou heure
  sans donnée : « inconnu » n'est **jamais** « ok »). Un blocage observé l'emporte même sur une prévision incomplète. Le
  résultat cite la valeur, l'heure, le seuil, la source et **l'heure d'émission de la prévision** (jamais l'horloge de M4).
- **Les fournisseurs** (fermés par défaut) : `meteo_manuelle.py` (l'admin saisit la prévision, avec sa source et son heure
  d'émission ; toujours disponible, prioritaire), `meteo_geomet.py` (MSC GeoMet, ECCC : usage commercial permis, attribution
  rendue ; ne donne ni rafales, ni quantité de pluie, ni verglas fiable : ces règles restent `inconnu`),
  `meteo_open_meteo.py` (API gratuite non commerciale : **fermé deux fois**, forfait commercial déclaré ET clé d'API dans
  l'environnement : décision du propriétaire) ; `meteo_fournisseurs.py` les ouvre selon le profil ; `meteo_http.py` est le
  seul module qui parle au réseau (hôtes d'une liste fermée, sans redirection, sans URL ni message d'exception dans les
  verdicts). Seule la position générale d'un chantier (dixième de degré) quitte le serveur (Loi 25). Licences et conditions
  lues le 2026-09-29 : `docs/research/INGREDIENTS.md`.
- **`meteo_creneaux.py`** (pur) : la météo de chaque créneau d'un plan proposé (`cedule_proposee`) : le jour numéroté de la
  cédule est relié à une date par le `calendrier` que l'appelant fournit (M4 ne tient pas de calendrier : un jour sans date
  est `inconnu`, jamais deviné). Un créneau `bloquant` donne un **report proposé** (motif `meteo`, jamais appliqué : le geste
  `m4_signaler_report` pour une intervention planifiée, ou le retrait du jour de la fenêtre pour une `a_planifier`) et une
  **nouvelle proposition de cédule** pour les jours restants (arguments de `m4_proposer_cedule` et aperçu calculé sur une
  copie du registre : les mêmes arguments donnent le même `plan_id`). Un jour fermé pour un service l'est pour tous les
  chantiers de ce service ; un créneau confirmé au client ne se déplace jamais tout seul. Un plan **périmé** pour une
  intervention (un autre plan appliqué la tient) est jugé mais ne compte ni dans le statut, ni dans les reports.
- **L'outil `m4_verifier_meteo_creneau`** (T0, admin seulement, lecture seule ; `plan_id`, `calendrier`, `previsions_saisies`
  facultatif, `jours` facultatif) : n'écrit rien, ne change aucun statut, ne range ni n'applique rien (`m4_appliquer_cedule`
  reste N3). Sans prévision ni fournisseur ouvert : `inconnu`, sans réseau. `previsions_saisies.saisi_par` nomme la personne
  authentifiée (sinon `REJ-IDENTITE-FOURNIE-DIFFERENTE`). La réponse d'un appareil est bornée (6 000 caractères) : elle est
  résumée (`detail_reduit` : créneaux `ok` sans détail, puis par jour), puis refusée avec la consigne `jours`, jamais
  tronquée. Aucune coordonnée, aucun prix.
- **Le volet `meteo` de `preparation.py`** : `ok` si le service a ses règles (chaque risque jugé ou sans objet) ; `manque`
  sinon (« seuil à configurer pour le service … », avec la commande) ; `non_verifiable` pour un lead v1 (les règles sont par
  service). **La préparation n'a pas de date : ce volet certifie que la météo SE JUGE, jamais qu'il fera beau** ; la
  prévision d'un créneau se juge avec l'outil ci-dessus.

Preuve : `tests/test_meteo.py` et `tests/test_cli_meteo.py` du socle (profil et commande), `test_meteo.py`,
`test_meteo_manuelle.py`, `test_meteo_http.py`, `test_meteo_geomet.py`, `test_meteo_open_meteo.py`,
`test_meteo_fournisseurs.py` (adaptateurs : sockets bloqués, transport fictif, réponses `fictif: true`),
`test_meteo_creneaux.py` (module pur), `test_preparation.py` (`TestVoletMeteo`), `test_meteo_outil.py` (vrais outils, vrai
bus, vrais fichiers de profil : sans prévision `inconnu`, vent fort bloquant, report proposé, cédule relancée au même
`plan_id`, lecture seule, panne d'un fournisseur, refus d'identité) et `tests/e2e/test_meteo_bloquante_appareil.py` (par la
porte d'appareil, avec le VRAI M6 pour le matériel : devis accepté, matériel à commander, réception, prêt, plan, vent
fort, report proposé, cédule relancée appliquée par l'admin en N3, report N3 d'une intervention planifiée, plan périmé,
réseau coupé, employé refusé). Les fixtures sont FICTIVES (`fictif: true`).

Limites connues : la préparation n'a pas de date, donc son volet météo ne promet rien sur le temps qu'il fera ; **M4 ne
tient pas de calendrier** (le `calendrier` est un argument) ; la vérification est une lecture : **elle n'est pas rangée au
registre** (aucun outil T1 ne garde « météo vérifiée pour ce plan » ; un plan appliqué se revérifie à la demande) ; MSC GeoMet
ne donne ni rafales, ni quantité de pluie, ni verglas fiable (ces règles restent `inconnu` tant que l'admin ne saisit pas la
prévision ou que le propriétaire n'ouvre pas Open-Meteo avec un forfait commercial) ; les alertes météo d'ECCC ne sont pas
reproduites ; la licence MSC GeoMet a été lue dans la documentation en ligne d'ECCC (aucun fichier `LICENSE` à lire), sans
relecture juridique ; la transition `reportee → planifiee` existe dans la machine à états, mais aucun outil ni aucune cédule ne la porte
(un report appliqué n'a pas de replanification outillée) ; le report d'une `a_planifier` n'a pas de geste (le jour est retiré de sa fenêtre dans la nouvelle proposition) ;
un client déjà informé d'un créneau se prévient par M1, jamais d'ici (frontière T3).

## Lectures pures du propriétaire (PLAN T4.27-a)

DEFINITION-PRODUIT §9.5 (l'app du propriétaire : dispatch du jour, météo, ce qui va mal). Trois lectures, toutes T0 :
aucun maillon, événement, approbation ni entrée de journal n'est écrit. Deux modules purs (`pagination_interventions.py`,
`retards.py`) et une fonction de plus dans `meteo_creneaux.py`, tous gardés par analyse du code (ni `opsys`, ni horloge, ni
aléa, ni réseau, ni flottant).

- **`m4_lister_interventions` par pages.** Le contrat v1 de la liste est gelé : `curseur` et `taille_page` sont des clés
  SŒURS additives. Ni l'une ni l'autre : la liste v1, telle qu'avant (le socle la coupe à 6 000 caractères, environ vingt
  interventions ; la réponse coupée est alors `{ok, tronque: true, apercu}`, pas une liste). L'une des deux, même nulle :
  une page `{interventions, page}`. `interventions` porte les mêmes lignes que la liste v1. Ordre stable : `intervention_id`
  croissant. `curseur` : le `curseur_suivant` de la page précédente (64 caractères hexadécimaux minuscules ; `null` ou
  absent pour la première). `taille_page` : de 1 à 50, sinon la plus grande page qui tient. La page ne dépasse jamais la
  borne du socle : le code la mesure (au moins une intervention par page ; une seule qui ne tiendrait pas est refusée,
  `total` (toutes celles de la liste : le statut demandé et le droit de voir déjà appliqués, avant le curseur),
  `reste` (celles qui viennent APRÈS la page), `curseur_suivant` (`null` quand `reste` vaut 0) et `borne_atteinte` (la page
  a été raccourcie par la borne, non par `taille_page`). Même contrôle d'accès que la liste v1 : le statut demandé, puis ce
  que l'appelant a le droit de voir (l'employé : ses interventions et celles de ses équipes) filtrent AVANT la pagination ;
  `total`, `reste` et `curseur_suivant` ne comptent jamais celles des autres, et un curseur pris ailleurs ne révèle rien.
- **`m4_lire_meteo_intervention`** (admin seulement ; `intervention_id`, `date` AAAA-MM-JJ facultative,
  `previsions_saisies` facultatif) : la météo du créneau d'UNE intervention, sans `plan_id`. Le créneau est celui que le
  dernier plan APPLIQUÉ qui la place lui donne, tant qu'elle est `planifiee` ou `en_route` ; l'évaluation est celle de
  `m4_verifier_meteo_creneau` (`meteo_creneaux._creneau`, T4.13), la même, pas une seconde ; la source des prévisions se
  choisit de la même façon (saisie de l'admin d'abord, sinon le fournisseur que le profil ouvre). Réponse : `intervention_id`,
  `statut_intervention`, `statut` (`bloquant`, `validation_requise`, `ok` ou `inconnu`), `plan_id` (celui du plan qui la
  tient, sinon `null`), `cause` (pourquoi il n'y a aucun créneau, sinon `null`), `attributions` et `creneaux` (zéro ou un :
  équipe, jour, date, minutes, service, règles `{risque, statut, detail}` qui citent la valeur, l'heure et le seuil, et la
  citation de la prévision : source, heure d'émission, auteur d'une saisie). Donnée absente = `inconnu`, jamais `ok` :
  intervention `a_planifier` ou `reportee`, planifiée sans plan appliqué, jour sans `date`, prévision ou seuil absent,
  fournisseur en panne. Aucun report ni aucune cédule n'est proposé (`m4_verifier_meteo_creneau` le fait, avec un
  `plan_id`). Une intervention inconnue, ou dans un statut où la météo n'a plus de sens (`sur_site`, `en_revue`,
  terminée, annulée), est refusée (`REJ-TRANSITION-ILLEGALE`) ; une date impossible aussi (`REJ-CONTRAT-INVALIDE`).
- **`m4_lire_retards_incidents`** (admin seulement ; `horodatage_reference` requis, l'heure de l'appareil : M4 n'a pas
  d'horloge) : ce que le registre enregistre déjà. Les REPORTS en cours (`reportee` : motif `client_absent`, `meteo` ou
  `decision_admin`, depuis quand) et les INCIDENTS ouverts (les demandes de revue sans résolution : écart métier ou anomalie
  de pointage), chacun avec son âge en heures pleines ; « bloquée » dès 24 h, le seuil du digest (jamais un second). Chaque
  liste est bornée à 8, du plus ancien au plus récent ; `reste` compte les autres et `suite` dit où les lire
  (`m4_lister_interventions`, `m4_lister_pending_review`). **`retard_sur_cedule` vaut `non_mesurable`** avec la raison :
  le plan d'une cédule numérote ses jours sans date civile et le registre ne garde aucune fenêtre planifiée ; « aucun
  retard » n'est jamais écrit. Aucun texte libre du terrain, aucun contact. **Chaque ligne dit `origine_heure`**
  (T4.27-a2, section suivante) : `serveur` ou `appelant`.

Preuve : `tests/test_pagination_interventions.py` et `tests/test_retards.py` (modules purs, analyse du code),
`tests/test_meteo_intervention.py` (fonction pure : même créneau que `verifier`, `meteo.evaluer_creneau` appelée avec
les mêmes arguments), `tests/test_lister_interventions_pages.py`, `tests/test_meteo_intervention_outil.py` et
`tests/test_retards_outil.py` (vrais outils, base migrée, vraies personnes, borne du vrai socle),
`tests/e2e/test_lectures_admin_m4_appareil.py` (par la porte d'appareil : 200 sans rien écrire pour l'admin, 403 pour
l'employé et le vendeur sur la météo et les retards, 45 interventions par pages sans troncature alors que la liste v1 est
coupée, l'employé ne voit que les siennes). Les fixtures sont FICTIVES (`fictif: true`).

Limites connues : le retard sur la cédule n'est pas mesurable (M4 ne tient aucun calendrier) ; une intervention
planifiée par `m4_planifier_intervention` n'a aucune fenêtre au registre, donc aucun créneau à juger ; la liste v1 sans
clé reste coupée par le socle. L'heure d'un report et d'une demande d'écart, limite de T4.27-a, est levée par T4.27-a2 :
voir la section suivante, qui dit aussi ce qui reste.

## L'heure d'un report et d'une demande d'écart (PLAN T4.27-a2)

Avant, `m4_signaler_report` et `m4_creer_demande_ecart` inscrivaient l'heure que l'appelant écrit. L'âge d'un retard ou
d'un incident (`m4_lire_retards_incidents`, « bloquée » dès 24 h) en héritait : un téléphone à l'heure fausse faussait
l'âge. Les deux outils suivent maintenant le patron du pointage (T1.4-d, R12 §4 : « les deux heures sont conservées »,
`docs/architecture/IDEMPOTENCE.md` §5).

- **Pendant un appel d'appareil**, l'heure du fait est celle de RÉCEPTION du serveur (`opsys.contexte.
  horodatage_reception()`, posée par la plateforme pour une mutation à clé d'idempotence, jamais par l'appelant ni par un
  modèle ; M4 ne consulte aucune horloge, CA-M4-15). Le `horodatage` que l'appelant écrit n'est pas lu. Le contrat v1 le
  demande encore et il est gelé : l'app et les agents l'envoient, un ancien appel reste valide, et le refuser casserait
  l'app. Il n'est ni validé ni gardé : même illisible ou énorme, il n'entre pas dans un registre immuable où il n'aurait
  aucun usage (l'heure de l'appareil, elle, vient de `_meta`, validée par le socle).
- **L'heure de l'appareil reste à part** : clé sœur `horodatage_appareil`, sur le maillon (de la demande, et de la
  transition `en_revue` qu'elle provoque) et sur l'accusé. Affichage seulement, jamais lue pour un calcul : ni l'âge, ni
  l'ordre, ni `demande_id` (l'empreinte de l'intervention et de l'heure du serveur). L'accusé d'une demande d'écart rend
  aussi `horodatage` (celui du serveur), pour qu'un renvoi rejoué le rende.
- **Idempotence.** Un renvoi de la même clé rend la réponse enregistrée (`rejoue: true`), donc la même heure, celle de la
  première réception, sans rien écrire (le socle ne ré-exécute rien). Une autre clé pour le même report est refusée
  (`REJ-TRANSITION-ILLEGALE`, l'heure du premier ne bouge pas) ; la même clé avec d'autres arguments est un conflit nommé
  (`mutation_conflit`).
- **Hors appel d'appareil** (agent, console, demande approuvée puis exécutée : le socle ne leur pose aucune heure de
  réception) : comme avant, `horodatage` fait foi et doit être lisible (`REJ-HORODATAGE-INVALIDE`), sans clé sœur. Le
  maillon et l'accusé sont alors ceux d'avant, octet pour octet : les empreintes du test ont été calculées avec le code
  d'avant.
- **Les faits d'avant gardent leur heure** : le registre est immuable, rien n'est réécrit ni corrigé. Le relevé dit
  d'où vient chaque heure avec `origine_heure` : `serveur` quand le fait porte l'heure de l'appareil à côté (son
  `horodatage` est alors celui du serveur, comme le pointage depuis T1.4-d), `appelant` sinon (un fait d'avant, d'un agent
  ou de la console : son âge dépend de l'horloge de celui qui l'a écrit, et le relevé ne la corrige pas). Une anomalie de
  pointage prend l'origine de son pointage (`pointage_ligne_id`), donc se lit `serveur` même si elle date d'avant ; sans
  pointage retrouvé, `appelant`, jamais `serveur` sans preuve (`horodatage.origine`).

Limites connues : (1) l'âge se compte depuis la RÉCEPTION : un geste fait hors ligne et envoyé plus tard est daté à
l'envoi (R12 §4 : c'est le prix d'une horloge de serveur qui fait foi) ; l'heure de l'appareil reste à part, de quoi
mesurer ce délai plus tard, mais rien ne l'affiche. (2) `horodatage_reference` reste l'heure de l'appareil de l'admin qui
lit : une lecture n'a pas d'heure de réception du socle (aucune clé d'idempotence), donc un téléphone d'admin à l'heure
fausse fausse encore l'âge affiché ; M4 n'a pas d'horloge. (3) Le digest (`m4_produire_digest`, forme gelée) profite de
l'heure du serveur pour ses demandes bloquées mais ne dit pas l'origine. (4) Deux gestes de l'admin gardent encore
l'heure que leur appelant écrit : `m4_resoudre_demande` et `m4_resoudre_revue_completion`, qui datent la résolution et
l'issue qu'elle provoque (la transition, et l'identifiant du Work Completion Trigger d'un écart validé). Ils n'entrent
pas dans l'âge d'un retard (une demande résolue sort du relevé) : à traiter à part, comme ce lot l'a fait pour le report
et l'écart.
`m4_annuler_intervention` et `m4_planifier_intervention` sont fermés aux appareils.

Preuve : `tests/test_origine_heure.py` (modules purs : règle, empreintes d'avant, refus, relevé),
`tests/test_heure_du_serveur_outils.py` (vrais outils, base migrée : heure du serveur, heure écrite ignorée, appareil qui
retarde ou avance de trois jours, faits d'avant, anomalies de pointage, digest), `tests/test_heure_du_serveur_rejeu.py`
(`Capacites.appeler` avec `_meta` réel et horloge de test : même clé, même heure, rien d'écrit) et
`tests/e2e/test_heure_du_serveur_appareil.py` (par la porte d'appareil : vrai moteur, HTTP MCP). Fixtures FICTIVES
(`fictif: true`).
