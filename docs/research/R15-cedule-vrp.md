# R15 — Cédule M4 : solveur de tournées, distances et géocodage (PLAN T4.1)

> Recherche pour [PLAN T4.1](../programme/PLAN.md) : la cédule de M4 trie sur un hachage de ville.
> Date de constat : 2026-09-28. Chaque licence est lue dans le fichier `LICENSE` du dépôt amont (lien
> exact) ; sinon elle est marquée « non vérifiée ». Les mesures ont été exécutées dans un venv jetable
> (Python 3.11.15, Linux x86_64) ; « estimé » = extrapolation, jamais mesurée. Les instances de test
> sont fictives (`fictif: true`).

## 0. Constat et contraintes

- `departments/m04-field-ops/src/m4_field_ops/cedule.py` trie sur `(jeton_ville, type_travaux,
  lead_id)`, puis répartit en tourniquet (`idx % nb_techniciens`, `idx // nb_techniciens` pour la
  fenêtre). Aucune distance, aucune durée, aucune compétence ; `urgence_declaree` n'est pas lue
  ([audit M4](../departements/M4-audit.md) M4.7, M4.8, risques 9 et 10).
- Le contrat d'entrée (LeadQualifie : 7 clés gelées + 3 optionnelles) ne porte que `ville`. Le
  registre M4 est append-only et hash-chaîné ; il garde `ville_tokenisee`, jamais la ville en clair.
- Taille visée : 2 à 8 chantiers par jour, quelques équipes, VPS 4 vCPU / 8–16 Go sans GPU
  ([INSTALLATION-VPS.md](../ops/INSTALLATION-VPS.md)). Le terrain est hors ligne d'abord (P14) : le
  calcul se fait sur le serveur, le téléphone garde le plan du jour.
- Les modules M4 sont purs (stdlib). `numpy` n'est pas dans le venv du projet (vérifié : 46 paquets,
  aucun `numpy`). Tout solveur tiers l'ajoute (73 Mo installés).
- L'adresse d'un chantier de client est un renseignement personnel : par défaut, rien ne quitte le
  VPS (Loi 25, §3).

## 1. Solveur VRP

### Comparaison (4 candidats)

| | **PyVRP 0.14.0** | **OR-Tools 9.15.6755** | **VROOM / pyvroom 1.15.2** | **Heuristique maison (stdlib)** |
|---|---|---|---|---|
| Licence (source) | MIT — [LICENSE.md](https://github.com/PyVRP/PyVRP/blob/main/LICENSE.md) | Apache-2.0 — [LICENSE](https://github.com/google/or-tools/blob/stable/LICENSE) | VROOM BSD-2 — [LICENSE](https://github.com/VROOM-Project/vroom/blob/master/LICENSE) ; pyvroom BSD-2 — [LICENSE](https://github.com/VROOM-Project/pyvroom/blob/main/LICENSE). **La roue pyvroom embarque `libglpk` (GPL-3.0+)** | aucune (code du dépôt) |
| Règle AGENTS.md | OK | OK (roue : Cbc/Clp en EPL-2.0, voir note 1) | **Non en processus** (GPL) ; service séparé non modifié seulement | OK |
| Roue PyPI (cp311/cp312, Linux) | 1,2 Mo x86_64 · 1,1 Mo arm64 (+ musllinux) | 29,8 Mo x86_64 · 27,6 Mo arm64 | 4,7 Mo x86_64 · 4,3 Mo arm64 (glibc ≥ 2.34) | aucune |
| Installé, net du venv nu (mesuré) | +173 Mo (matplotlib déclarée) ; **+76 Mo** avec `--no-deps` (numpy seul : import et calcul vérifiés) | +233 Mo (numpy ≥ 2, pandas, protobuf, absl) | +160 Mo (numpy, pandas) | 0 |
| Python | ≥ 3.11 (colle au projet) | ≥ 3.9 | ≥ 3.10 | 3.11+ |
| Fenêtres, durées de service, quarts | oui | oui | oui | oui (DP) |
| Compétences | **pas natif** : « vehicle-client compatibility » est réservé à PyVRP **Enterprise** ([README](https://github.com/PyVRP/PyVRP/blob/main/README.md)). Contournement dans la version libre : un profil de matrice par jeu de compétences, arêtes interdites (« access restrictions ») | natif (`VehicleVar`) | natif (`skills`) | oui (ensemble d'équipes admissibles) |
| Capacités | oui, multidimensionnelles | oui | oui | non |
| Chantier non cédulé | clients optionnels avec prix (`required=False`) | disjonctions avec pénalité | liste `unassigned` (sans raison) | oui (pénalité) |
| Déterminisme (mesuré) | `seed` + `MaxIterations` : sortie identique sur 3 processus (`PYTHONHASHSEED` 1, 2, 3) ; RNG xorshift interne ; coûts entiers. `MaxRuntime` lit l'horloge : à proscrire | identique sur 3 processus, avec `time_limit` 1 s et avec `solution_limit` 300 ; pas de graine documentée (non vérifié) ; `time_limit` dépend de l'horloge | identique sur 6 exécutions pour chacune de 3 configurations (threads 1 ou 4, exploration 1 ou 5) | exact, sans aléa |
| Maturité | 0.14.0 (2026-08-20), 702 ★ ; éditeur Applied Routing (offre Enterprise) | 9.15 (2026-01-14), 14 112 ★ ([R7](R7-m3-m4.md)) | pyvroom 2026-04-22 ; VROOM 1 871 ★ (R7) | à écrire et à tenir (≈ 60 lignes) |

Note 1. La roue OR-Tools embarque `libCbc`, `libClp` (EPL-2.0 : [Cbc](https://github.com/coin-or/Cbc/blob/master/LICENSE), [Clp](https://github.com/coin-or/Clp/blob/master/LICENSE)), HiGHS ([MIT](https://github.com/ERGO-Code/HiGHS/blob/master/LICENSE.txt)) et SCIP ([Apache-2.0](https://github.com/scipopt/scip/blob/master/LICENSE)). L'EPL-2.0 n'est pas dans la liste d'AGENTS.md : décision humaine si OR-Tools devient le choix.

Note 2. pyvroom : `libglpk-*.so`, `libgmp`, `libamd`, `libcolamd` sont dans `pyvroom.libs/` (`ldd` du `.so` et SBOM auditwheel de la roue) ; GLPK est « GPL version 3 ou ultérieure » ([en-tête glpk.h](https://github.com/ferrandi/glpk/blob/master/src/glpk.h), miroir ; la page gnu.org est bloquée ici). Le `makefile` de VROOM active `USE_LIBGLPK` dès que `glpk.h` existe ([makefile](https://github.com/VROOM-Project/vroom/blob/master/src/makefile)). La métadonnée de la roue dit BSD-2 : elle ne mentionne pas GLPK. Le binaire de l'image Docker officielle de VROOM : non vérifié.

### Mesures croisées

- **Instance de démonstration** (6 chantiers fictifs Repentigny–Terrebonne–Joliette, 2 équipes, un chantier de 200 min réservé à l'équipe A, journée 8 h–17 h, distances haversine × 1,3 en mètres) : les 4 méthodes trouvent le même optimum (107 392 m et 1 chantier non cédulé faute de place dans la journée).
- **5 instances aléatoires** (n = 8, 8, 10, 12, 14 chantiers, 3 équipes, fenêtres client, visites optionnelles) : PyVRP (2 000 itérations, graine 1) égale l'optimum exact dans les 5 cas (écart 0), en 0,12 à 0,27 s.
- **DP exact maison** (sous-ensembles + Pareto coût/heure de fin, par équipe) : 0,01 s (n = 8), 0,03 s (10), 0,2 s (12), 0,9 s (14). Croissance exponentielle : plafond pratique ≈ 14 à 16 chantiers sur un même horizon ; un horizon d'une semaine (20 à 40 chantiers) le dépasse.

### Recommandation : **PyVRP**, derrière une interface étroite

Raisons : licence MIT sans piège, roue de 1,2 Mo, graine explicite, coûts entiers, chantiers optionnels (= « non cédulé » sans bricolage), assez de marge pour une semaine et pour les futurs clients SaaS. Deux garde-fous maison, stdlib :

1. le **DP exact** reste en repli sans dépendance (≤ 12 chantiers) et sert d'**oracle de test** (PyVRP ne doit jamais coûter plus que l'optimum + ε sur les petites instances) ;
2. un **validateur indépendant** du plan (fenêtres, compétences, durées, retour au dépôt) : on ne fait jamais confiance à la sortie du solveur.

Pourquoi pas OR-Tools, retenu par l'audit M4 : mêmes résultats ici, mais 30 Mo, pandas, bibliothèques EPL-2.0 dans la roue, arrêt par horloge par défaut. Il reste l'alternative documentée si les contraintes deviennent riches (compétences natives). Risques de PyVRP : API instable (en 0.14, `add_depot(x=…)` n'existe plus, on passe par des objets `Location` : épingler `pyvrp==0.14.0` et couvrir par des tests) ; compétences par profils (une matrice par profil, négligeable jusqu'à quelques dizaines de chantiers) ; éditeur unique avec une offre payante (surveiller le déplacement de fonctions vers « Enterprise ») ; égalité x86_64/arm64 non vérifiée (aucune machine arm64 ici).

## 2. Distances et durées

| | **Haversine × détour** | **OSRM** | **Valhalla** | **GraphHopper** |
|---|---|---|---|---|
| Licence du logiciel | code du dépôt (`pointage.distance_km` existe) | BSD-2 — [LICENSE.TXT](https://github.com/Project-OSRM/osrm-backend/blob/master/LICENSE.TXT) | MIT — [COPYING](https://github.com/valhalla/valhalla/blob/master/COPYING) | Apache-2.0 — [LICENSE.txt](https://github.com/graphhopper/graphhopper/blob/master/LICENSE.txt) |
| Données | aucune | OSM, ODbL 1.0 | OSM, ODbL 1.0 | OSM, ODbL 1.0 |
| Matrice | calcul direct | service `Table` (durées et distances) | matrice et isochrones ([README](https://github.com/valhalla/valhalla)) | l'API Matrix est listée parmi les API hébergées ([README](https://github.com/graphhopper/graphhopper/blob/master/README.md)) ; présence dans le serveur libre : non vérifiée |
| Exploitation | 0 | conteneur ([image officielle](https://github.com/Project-OSRM/osrm-backend/blob/master/README.md)) ; voir chiffres ci-dessous | tuiles, « petite empreinte mémoire, hors ligne, extraits régionaux » ; chiffres non vérifiés | JVM ; chiffres non vérifiés |
| Déterminisme | total | oui à données figées | oui à données figées | oui à données figées |

**Données OSM.** ODbL 1.0 : attribuer « © OpenStreetMap contributors » et, si l'on bâtit sur les données et qu'on distribue le résultat, le faire sous la même licence ([copyright OSM](https://www.openstreetmap.org/copyright)). Conséquence à valider par un juriste (interprétation, non vérifiée) : ne pas livrer de graphe OSRM préconstruit dans l'image ; chaque installation le construit depuis l'extrait.

**Extrait Québec** ([Geofabrik](https://download.geofabrik.de/north-america/canada/quebec.html)) : `quebec-latest.osm.pbf` = 1,1 Go (1 161 149 703 octets pour l'instantané `quebec-260927`, avec `.md5` ; ODbL 1.0). Instantanés datés : à épingler.

**Coût OSRM.** Le [wiki OSRM](https://github.com/Project-OSRM/osrm-backend/wiki/Disk-and-Memory-Requirements) (v5.26, planète de 2021) donne, pour 61 GiB de `.pbf` en profil voiture : 123 GiB de RAM en service, 415 GiB à l'extraction, ≈ 300 Go de disque, « tailles à peu près linéaires ». Extrapolation linéaire pour le Québec (≈ 1,8 % de la planète) : **≈ 2 Go de RAM en service, ≈ 7 Go au pic d'extraction, ≈ 5 Go de disque** (estimé, non mesuré). Trop pour un VPS de 8 Go partagé avec Postgres, le Core et LiteLLM : découper à la région de service (Lanaudière et voisines ; environ dix fois moins, estimé). Outil de découpe (osmium-tool) : licence non vérifiée.

**Haversine.** Sur plus de 66 000 trajets vers des hôpitaux américains, distance routière et distance en ligne droite sont très corrélées (r² > 0,9), avec « d'importantes exceptions locales près des rives et des obstacles physiques » ([Boscoe et al. 2012](https://doi.org/10.1080/00330124.2011.583586), résumé lu ; l'article complet et un coefficient de détour ne sont pas vérifiés). Les cours d'eau de Lanaudière (rivière L'Assomption, rivière des Mille Îles, fleuve) sont ce genre d'exception : calibrer sur au moins 30 paires réelles avec OSRM. Le VRP s'en sert d'abord pour **ordonner** ; les fenêtres de temps exigent une marge.

### Recommandation par paliers

- **Palier 0 (défaut, tout poste)** : haversine en mètres entiers × facteur de détour, vitesse moyenne, marge fixe par trajet. Trois paramètres d'entreprise **obligatoires** (pas de valeur cachée : absents, le verdict les demande) ; valeurs de départ proposées à l'installation : 1,3 ; 50 km/h ; 10 min (non sourcées, à calibrer). La sortie porte `mode_distance: "approximatif"` et l'écran de dispatch affiche « mode bridé » (P10, audit M4 §2.8).
- **Palier 1 (option serveur)** : sidecar OSRM local sur extrait régional épinglé, `Table` pour durées et distances. La matrice est figée et hachée dans l'entrée du calcul. Sidecar indisponible : retour au palier 0 avec badge. Jamais de serveur de démonstration tiers (coordonnées de clients).
- **Palier 2** : Valhalla, seulement si des isochrones (zones de service) deviennent un besoin.

## 3. Géocodage des adresses de chantier

### Options

| Option | Licence (source) | Données et exploitation | Loi 25 | Verdict |
|---|---|---|---|---|
| **RQA — Référentiel québécois des adresses** | données CC-BY 4.0 ([MRNF](https://mrnf.gouv.qc.ca/repertoire-geographique/adresses-quebec-referentiel-quebecois-adresses/), [Données Québec](https://www.donneesquebec.ca/recherche/dataset/referentiel-quebecois-des-adresses)) | toutes les adresses municipales du Québec avec latitude et longitude (NAD83 SCRS, EPSG:4617) ; CSV 596 Mo, GPKG 887 Mo ; mensuel ; champs `adresse_formatee`, `numero_municipal`, `code_municipalite`, `etat`, `numero_lot`, `qualite_positionnement_geometrique` (Bâtiment, Front lot, Centre lot, Site, Accès propriété, Géocodée, Incertaine) ([guide](https://diffusion.mern.gouv.qc.ca/diffusion/RGQ/Vectoriel/Theme/Local/RQA/Document/Guide_d_utilisation_RQA.pdf)). Index local filtré par MRC : petit | rien ne quitte le VPS | **retenu** |
| Adresses Québec (ancienne gamme) | CC-BY 4.0 ([Données Québec](https://www.donneesquebec.ca/recherche/dataset/adresses-quebec)) | transition en cours jusqu'à la fin de 2026 ; RQA (adresses) et RQTT (réseau) sont les nouveaux référentiels | idem | remplacé par RQA |
| Base de données ouvertes d'adresses (Statistique Canada) | Licence du gouvernement ouvert — Canada ([StatCan](https://www.statcan.gc.ca/en/lode/databases/oda)) | v1.0 de 2021, « expérimentale » | idem | non retenu (RQA plus frais) |
| Nominatim 5.3.2 auto-hébergé | **GPL-3.0** ([COPYING](https://github.com/osm-search/Nominatim/blob/master/COPYING)) : service séparé non modifié | PostgreSQL + PostGIS + osm2pgsql ; 2 Go de RAM minimum ([doc](https://nominatim.org/release-docs/latest/admin/Installation/)) ; couverture d'adresses OSM au Québec non mesurée ; recherche floue | local | non retenu v1 (lourd, flou) |
| Photon | Apache-2.0 ([LICENSE](https://github.com/komoot/photon/blob/master/LICENSE)) | exploitation non vérifiée | local | non retenu v1 |
| Pelias | MIT ([LICENSE](https://github.com/pelias/pelias/blob/master/LICENSE)) | multi-services + Elasticsearch ; exploitation non vérifiée | local | non retenu v1 |
| Nominatim public (OSMF) | politique d'usage | « ne soumettez pas de renseignements personnels », 1 requête/s max, géocodage en masse déconseillé ([politique](https://operations.osmfoundation.org/policies/nominatim/)) | hors Québec | **interdit** pour nous |
| Google, Mapbox, autres API tierces | conditions de service : non vérifiées | — | hors Québec : **art. 17** | désactivé (voir ci-dessous) |
| Géocodeur du gouvernement du Québec (REST MRNF) | — | RQA : service Web « en développement », lancement annoncé à l'été 2026 ; non confirmé en ligne le 2026-09-28 | au Québec, mais un service public gratuit n'est pas un mandat (art. 18.3) | désactivé, à trancher |

### Loi 25 (texte lu sur [Légis Québec](https://www.legisquebec.gouv.qc.ca/fr/document/lc/p-39.1), version du 2026-09-28)

- **Art. 17** : avant de communiquer un renseignement personnel à l'extérieur du Québec, l'entreprise fait une évaluation des facteurs relatifs à la vie privée (sensibilité, finalité, mesures de protection dont les contractuelles, régime juridique de l'État). La communication n'a lieu que si la protection est adéquate, et elle fait l'objet d'une **entente écrite**. Même règle si l'on confie la tâche à un tiers hors Québec. Le gabarit existe : [GABARIT-EFVP.md](../compliance/efvp/GABARIT-EFVP.md) §5.
- **Art. 18.3** : communication sans consentement seulement si nécessaire à un mandat ou à un contrat de service **confié par écrit**, avec mesures de confidentialité (le 2° ne s'applique pas à un organisme public).
- Le consentement au suivi GPS des employés ([POLITIQUE-geolocalisation.md](../compliance/politiques/POLITIQUE-geolocalisation.md)) ne couvre pas l'adresse d'un client : c'est un autre flux.

### Recommandation fail-closed

1. **Local seulement** : index RQA restreint aux MRC de service (import du CSV mensuel), zéro appel réseau. Un géocodeur externe n'existe pas dans le code tant qu'une EFVP n'est pas signée (T3, Nathan).
2. **Correspondance exacte** sur l'adresse normalisée (numéro, suffixe, odonyme, municipalité). Zéro résultat ou plusieurs : verdict « **coordonnées manquantes : à confirmer** », avec les candidats en aide, sans jamais en choisir un.
3. **Qualité** : `Bâtiment`, `Accès propriété`, `Front lot`, `Centre lot` donnent une *proposition* ; `Géocodée`, `Incertaine`, `Site` ou `etat` non actif donnent « à confirmer sur place ».
4. **Aucune coordonnée n'entre dans le solveur avant une confirmation humaine unique** (rôle `manager`/`admin`), gardée sur le chantier, versionnée, corrigeable (source `rqa` ou `manuel`).
5. Attribution CC-BY affichée là où l'adresse est validée. Écran de confirmation : un fond de carte externe est un flux hors Québec à évaluer à part ; sans lui, confirmer = valider l'adresse formatée et la coordonnée en texte.

## 4. Conception proposée pour M4

**Où vivent les coordonnées.** M2 possède l'adresse ; M4 possède l'« adresse validée » (produit M4.6). Le contrat LeadQualifie v1 est gelé : on n'y touche pas. Nouveau type de maillon **additif** `localisation_chantier` dans le registre M4 (ajout à `_TYPE_ENTREE_VALIDES`), clé `chantier_id` (v1 : égal à `lead_id`). Champs : `version` (entier croissant), `action` (`confirmee` | `retiree`), `coordonnees_chiffrees` (microdegrés entiers), `empreinte_adresse` (HMAC avec sel), `source` (`rqa` | `manuel`), `rqa_identifiant` et `rqa_version`, `precision`, `confirme_par` (rôle et identifiant), `horodatage`. Le dernier maillon gagne (patron `consentement.py`) ; l'historique reste lisible. Chiffrement et destruction : patron T4.2 (`retention.py`, clé par chantier dans `opsys.cles_chiffrement`, effacement cryptographique). Aucune adresse ni ville en clair dans le registre. Plus tard : clé sœur optionnelle `adresse_chantier` dans LeadQualifie v1, ajoutée d'abord côté M2 (précédent T2.2 pour `source`/`utm`) ; d'ici là, l'adresse est un argument de l'outil de localisation.

**Module `cedule`.** `cedule.py` est **gardé** comme repli « sans coordonnées » (couvert par les tests M4 existants, appelé à l'inscription par `m4_planifier_intervention`), étiqueté mode bridé, jamais utilisé pour un ordre géographique. Nouveaux modules purs `localisation.py`, `distances.py`, `tournees.py`. Le solveur **propose** ; il n'écrit pas la vérité.

**Entrée du solveur** (JSON canonique, entiers) : `equipes[]` (id, compétences, dépôt, quart en minutes), `chantiers[]` (id, coordonnées confirmées, durée en minutes par type de travaux, fenêtre client, compétences requises, urgence, créneau figé s'il est déjà confirmé au client), `matrice` (mode, version, mètres et secondes, empreinte), `params` (graine, itérations, pénalité de non-cédule, détour, vitesse, marge). **Sortie** : `plan[]` (équipe, jour, visites avec arrivée, début, fin), `non_cedulees[]` (chantier, raison, action requise), `meta` (solveur et version, graine, itérations, empreinte d'entrée, empreinte de sortie, `mode_distance`).

**Déterminisme exigé** (le code calcule, les tests se reproduisent). Entrées triées par identifiant ; entiers seulement (microdegrés, mètres, minutes) ; `MaxIterations`, jamais `MaxRuntime` ; graine dérivée de l'empreinte d'entrée (aucune horloge, aucun `random`, garde AST comme le reste de M4) ; sortie canonicalisée (tri par équipe, jour, heure ; départage par identifiant). La matrice est une entrée figée et hachée, donc le calcul ne dépend pas de la plateforme flottante. Un plan accepté est **stocké** (maillon `cedule_proposee`, puis appliqué par `assigner_technicien` sous approbation N3) et n'est jamais recalculé pour l'audit.

**Donnée manquante (fail-closed).** Sans coordonnées confirmées : `non_cedulees` avec « coordonnées manquantes : à confirmer » (jamais le centre de la ville). Sans durée pour le type de travaux, sans compétence connue, sans dépôt ou sans paramètres de distance : verdict qui dit quoi fournir. Les raisons de non-cédule sont calculées par notre code après la résolution (coordonnées, durée, compétence, fenêtre inatteignable depuis le dépôt, journées pleines), pas par le solveur. Un plan qui échoue au validateur est refusé.

**Hors périmètre T4.1** : chantiers de plusieurs jours (visites), météo, capacités de véhicule et de matériel, ETA client.

### Découpage

| Tâche | Contenu | Critères de preuve |
|---|---|---|
| **T4.1-a** Localisation | `localisation.py` (normalisation d'adresse, index RQA en SQLite), maillon `localisation_chantier` chiffré et versionné, outils `m4_proposer_localisation` (T0) et `m4_confirmer_localisation` (T1, rôle `manager`/`admin`) | mini-RQA fictif (`fictif: true`) ; correspondance unique = proposition ; doublon ou absence = verdict « coordonnées manquantes : à confirmer » ; **aucun accès réseau** (test avec socket interdit) ; dernier maillon gagne, historique lisible ; effacement de la clé rend la position illisible et la chaîne reste valide ; `opsys verifier` |
| **T4.1-b** Matrice | `distances.py` (haversine entier, détour, vitesse, marge, `mode_distance`) et port `FournisseurMatrice` avec adaptateur OSRM optionnel vers un sidecar local | propriétés (symétrie, entiers, reproductibilité) ; paramètres absents = verdict ; adaptateur OSRM testé contre un faux serveur ; repli palier 0 avec badge ; fixture d'étalonnage documentant l'erreur haversine × détour |
| **T4.1-c** Solveur et validateur | `tournees.py` : interface, adaptateur PyVRP (extra `tournees`, `pyvrp==0.14.0`), DP exact de repli, `verifier_plan`, diagnostic des non-cédulées | mêmes octets sur deux exécutions et sur sous-processus avec `PYTHONHASHSEED` différents ; écart 0 avec le DP exact sur ≥ 5 instances fictives (n = 8 à 12) ; compétence rare jamais donnée à une équipe non admissible ; le validateur refuse un plan hors fenêtre ; n = 8 en moins de 1 s ; garde AST (ni horloge ni `random`) |
| **T4.1-d** Outils et E2E | `m4_proposer_cedule` (T1, brouillon) et `m4_appliquer_cedule` (N3, refuse si l'empreinte d'entrée a changé) ; skill mis à jour ; PLAN et INGREDIENTS | scénario « optimisation d'une journée » (§7 M4) sur chantiers fictifs Repentigny–Joliette : deux chantiers proches vont à la même équipe avant un chantier éloigné, et les kilomètres baissent par rapport au tourniquet sur la même fixture ; créneau figé respecté ; M4, socle, `ruff`, `opsys verifier` verts |

Option hors des quatre : sidecar OSRM dans `deploy/` (profil compose `routage`, extrait régional épinglé), à décider selon la RAM du VPS.

## 5. À inscrire dans INGREDIENTS.md

Section `## M4 — Field Ops` : remplacer la ligne « Google OR-Tools ou PyVRP » et la ligne OSRM par les cinq lignes suivantes.

```markdown
| **PyVRP** | MIT (`LICENSE.md` du dépôt PyVRP/PyVRP, lu le 2026-09-28) | Solveur de tournées avec fenêtres, quarts, flotte hétérogène, clients optionnels ; remplace le tourniquet de `cedule.py`. Compétences par profils de matrice (le natif est réservé à PyVRP Enterprise, non utilisé). Graine explicite, `MaxIterations` seulement | Extra `tournees` (`pyvrp==0.14.0`, numpy) ; roue 1,2 Mo cp311/cp312 x86_64 et arm64 ; toujours derrière `verifier_plan`, avec repli DP exact stdlib | Phase 2 | R15 |
| **Google OR-Tools** | Apache-2.0 (`LICENSE`, branche `stable`, lu) ; la roue embarque Cbc/Clp en EPL-2.0 (non listée dans AGENTS.md : décision humaine avant adoption), HiGHS (MIT), SCIP (Apache-2.0) | Alternative documentée si les contraintes de cédule deviennent riches (compétences natives) | Aucune dépendance aujourd'hui ; roue 30 Mo, exige numpy ≥ 2 et pandas | Référence | R15 |
| **OSRM** | BSD-2-Clause (`LICENSE.TXT`, lu) ; données OSM en ODbL 1.0 (attribution ; graphe dérivé non distribué) | Palier 1 optionnel : matrice routière (`Table`) sur extrait régional épinglé ; le palier 0 est l'haversine × détour, en mode bridé affiché | Sidecar Docker local ; estimé ≈ 2 Go de RAM pour tout le Québec (extrapolation du wiki OSRM), donc extrait régional | Phase 2 | R7 · R15 |
| **RQA — Référentiel québécois des adresses** | Données CC-BY 4.0 (fiche MRNF et Données Québec, lues 2026-09-28 ; attribution à afficher) | Géocodage local et hors ligne des adresses de chantier ; `qualite_positionnement_geometrique` gouverne « proposée » ou « à confirmer » ; confirmation humaine unique | Import mensuel du CSV (596 Mo) filtré par MRC dans l'index de l'instance ; aucun appel réseau | Phase 2 | R15 |
| **Haversine × détour** (patron maison, `pointage.distance_km`) | Code du dépôt | Palier 0 de la matrice de durées ; paramètres d'entreprise obligatoires (détour, vitesse, marge) | `distances.py` (T4.1-b) | Référence | R15 |
```

Section `## Refusées` :

```markdown
| pyvroom / VROOM **en processus** | M4 | La roue pyvroom embarque `libglpk` (GPL-3.0+, vérifié dans l'en-tête glpk.h) et libgmp, alors que sa métadonnée dit BSD-2 : contraire à AGENTS.md hors service séparé non modifié ; binaire de l'image Docker officielle non vérifié | R15 |
| Nominatim public (OSMF) et API de géocodage tierces hors Québec | M4 | La politique OSMF interdit de soumettre des renseignements personnels ; les autres imposent l'art. 17 de la Loi sur le privé (EFVP et entente écrite). Le géocodage reste local (RQA) | R15 |
```

Nominatim auto-hébergé (GPL-3.0, service séparé), Photon (Apache-2.0) et Pelias (MIT) : « Référence, non retenus en v1 » (lourds, recherche floue contraire au fail-closed). Décompte à ajuster : M4 passe de 4 à 6 retenues (5 en phase 2 ou référence à préciser) et de 1 à 3 refusées ; total 137 → 139 retenues, 38 → 40 refusées.

## 6. Ce qui a été vérifié, et ce qui ne l'a pas été

**Exécuté** (venv jetable, Python 3.11.15, x86_64) : `pip install` de `pyvrp` 0.14.0, `ortools` 9.15.6755, `pyvroom` 1.15.2 ; instance de 6 chantiers, 3 solveurs, 3 processus chacun ; 5 instances aléatoires contre le DP exact ; PyVRP sans matplotlib ; inspection de `pyvroom.libs/` et de l'SBOM de la roue. Les scripts sont jetables et non versionnés : T4.1-c les refait comme tests.

**Lu à la source** : les fichiers de licence cités (dépôts amont), le code de `solve.py`, `RandomNumberGenerator.h`, le stub `_pyvrp.pyi` de PyVRP, les métadonnées PyPI (`requires_python`, roues), la page Geofabrik, le wiki OSRM, les pages RQA (dont le guide PDF), la politique Nominatim, l'art. 17 et l'art. 18.3 de la Loi sur le privé.

**Non vérifié** : égalité des résultats x86_64/arm64 et Python 3.12 (roues présentes, non exécutées) ; chiffres de RAM d'OSRM (extrapolés), de Valhalla, de GraphHopper, de Photon, de Pelias ; matrice dans le serveur libre de GraphHopper ; couverture d'adresses d'OSM au Québec ; licence d'osmium-tool ; conditions de service de Google et de Mapbox ; GLPK dans l'image Docker de VROOM ; état du service Web RQA ; fraîcheur des étoiles GitHub d'OR-Tools et de VROOM (reprises de R7, l'API GitHub est bloquée ici) ; article complet de Boscoe et coefficient de détour pour le Québec.

## 7. Décisions à trancher

1. **Confirmation humaine systématique ou automatique pour une correspondance RQA « Bâtiment »** (une touche par chantier, recommandée en v1).
2. **EPL-2.0** : seulement si OR-Tools remplace PyVRP.
3. **Sidecar OSRM** : RAM et disque du VPS cible ; extrait régional à définir avec Nathan.
4. **Juriste** : graphe OSRM dérivé (ODbL), attribution CC-BY, base légale d'un géocodeur gouvernemental.
5. **Où loger le géocodeur** : dans M4 (v1, plus simple) ou en capacité commune, puisque M3.7 aura besoin de la normalisation d'adresse. L'interface pure permet de le déplacer.
6. **Fond de carte** pour confirmer sur carte : flux externe à évaluer (EFVP §5).
