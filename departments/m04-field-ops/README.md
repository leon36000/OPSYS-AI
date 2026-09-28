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
