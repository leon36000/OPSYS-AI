# M10 Mnémo : modèle de soi, graphe de connaissances, apprentissage continu gouverné

Statut : tranche 1 (2026-11-01, ligne architecte 5208490a4, migration 0052). Code : `src/opsys/mnemo/` (socle, comme
`src/opsys/connaissances/`), outils : `departments/m10-memoire/src/m10_memoire/soi_graphe.py`, console :
`src/opsys/console/mnemo_ui.py`, corpus de mesure : `departments/m10-memoire/evals/soi-graphe.v1.yaml`. Tests :
`tests/test_mnemo_*.py`. Exigences de la matrice M10 : **M10.13** (modèle de soi) et **M10.17** (graphe de connaissances), plus
l'apprentissage de [la vision de l'entreprise apprenante](../produit/VISION-ENTREPRISE-APPRENANTE.md).

> **Ce que cette tranche est, et n'est pas.** Elle livre le MÉCANISME et le prouve par des tests exécutés : un modèle de soi
> sourcé et versionné, un graphe d'entités à schéma fermé sur PostgreSQL/SQLite natifs, une file de leçons mesurées hors ligne et
> promues par une personne. Elle ne livre **aucun modèle de langage**, ne comprend aucune question en français, n'a tourné sur
> **aucune donnée réelle** et n'est branchée à aucun département consommateur de leçons. Le banc de mesure valide le moteur sur un
> corpus fictif de petite taille ; il ne dit rien de la qualité d'un agent. Rien n'est « complet » : voir § 9.

## 1. Audit de M10 avant de construire (ce qui existait, ce qui manquait)

| Brique de M10 | Ce qu'elle fait | Ce qu'on en réutilise | Ce qui manquait |
|---|---|---|---|
| Registres append-only chaînés (`registre.py`, `stockage.maillons`) | événements, affaires, faits analytiques | **la chaîne de hash** pour le modèle de soi et les leçons (deux registres de plus : `soi`, `lecons`) ; aucune table | un type d'entrée pour chacun |
| Connaissances (migration 0041, `docs/architecture/CONNAISSANCES.md`) | textes de référence sourcés, versionnés, recherche hybride | le patron : états = dernier événement, INSERT conditionnel, déclencheurs append-only, honnêteté « aucune source », garde anti-injection (`isolation`), outils communs de lecture | ce n'est pas le modèle de l'entreprise elle-même |
| Faits analytiques (`analytique.py`, `m8.fait_consolide`) | mesures d'entreprise de M8 avec définition versionnée et fraîcheur | source des **marges observées** (jamais recalculées) | rien n'en faisait un énoncé |
| Consolidation et traces (`consolidation.py`, `provenance_documentaire.py`, WCT/variance/rentabilité) | faits durables d'affaire, événements opérationnels | source de la **saisonnalité**, des **écarts** et des **leçons** ; les événements déjà consommés nourrissent le graphe | aucune relation entre entités, seulement des lignes par affaire |
| Documents d'affaire et trace documentaire (`documents_affaire.py`, `provenance_documentaire.py`, [M10-TRACE-DOCUMENTAIRE.md](M10-TRACE-DOCUMENTAIRE.md)) | versions, activations et retraits de documents par l'admin appareil ; provenance de lots (empreinte de la source) sans affaire artificielle | modèle des nœuds `document` et de l'arête `documente`/`justifie` | **non alimentée** : ces écritures ne passent pas par un événement du bus ; aucun nœud `document` ne naît seul aujourd'hui (proposition d'un agent ou d'une personne seulement) |
| `consolidation_developpement.self_model` | « modèle de soi » du domaine développement (identité, modules, preuves) | — (autre domaine, isolé des données d'affaires) | **aucun modèle de soi « affaires »** (matrice : M10.13 PARTIEL) |
| Boucle d'apprentissage de M1 (`m1_front_office/apprentissage.py`, M1.13) | corrections → propositions → mesure → promotion humaine (canari, retour arrière) | **généralisée proprement** dans `opsys.mnemo.promotion` (mêmes transitions, test de parité contre M1) | elle ne promeut que des règles de tri de courriels |
| M10 `apprentissage.py` (aperçu des faits candidats M3) | statistiques de triage, sans conclusion | idée de seuil « affaires distinctes » (≥ 3) pour les refus récurrents | il ne produisait aucune leçon |
| Graphe (M10.17) | — | — | **absent** (matrice : cognee 0 occurrence) |

Constat qui oriente le reste : M10 a de la mémoire longue **par affaire** ; il n'a ni représentation de ce que l'entreprise EST, ni
relations entre ses entités, ni cycle qui transforme une correction en changement gouverné.

## 2. Modèle de soi de l'entreprise (« profil d'entreprise apprenant »)

### 2.1 L'énoncé

Un **énoncé** dit un fait sur l'entreprise sous la forme FERMÉE de sa dimension. Il porte :

- une **dimension** et une **clé** (le sujet : un code de service, l'identifiant d'une équipe, `zone_desservie`…) ;
- une **valeur** validée et bornée (jamais un texte libre non filtré), et un **libellé écrit par le code** (aucun modèle ne rédige un
  énoncé) ;
- des **sources** (1 à 5) : un type (fait de département, onboarding, correction humaine, décision de la direction), une
  **référence VÉRIFIABLE à l'écriture** (`registre:<nom>:<ligne_id>`, `entreprise:<partie>:<empreinte>`, `pack:<id>:<empreinte>`,
  `decision:<id>`, `connaissance:<version>`) et l'instant où le fait a été observé. Une source qui n'existe pas, ou dont
  l'empreinte ne correspond plus au profil, est refusée (`REJ-MNEMO-SOI-SOURCE-INTROUVABLE`) : une source se vérifie, elle ne se
  déclare pas ;
- une **confiance calculée** : la meilleure source de base (onboarding 0,70 ; fait de département 0,60 ; correction humaine 0,85 ;
  décision de la direction 1,00), plus 0,05 par source distincte de plus, plafonnée à 0,95 sans décision de la direction. C'est
  un rang de solidité des preuves, **pas une probabilité** ;
- une **date** (âge calculé à la lecture), un **état** `proposé` / `confirmé` / `obsolète`, une **version** (un énoncé n'est jamais
  modifié : une valeur différente est une nouvelle version).

### 2.2 Les dimensions

| Dimension | Structurante | Alimentation automatique | Lisible par |
|---|---|---|---|
| `services`, `zones` | oui | profil d'entreprise de l'onboarding (`opsys.taxonomie`) | tous |
| `equipes`, `capacite` | oui | profil des équipes (`opsys.equipes`) : la **semaine type déclarée** ; une semaine incomplète est inconnue, jamais plus courte ; aucun membre (une personne) n'est recopié | tous |
| `marges_observees` | oui | faits analytiques de M8 mémorisés par M10, tels que publiés (tolérance de 10 % avant de parler de contradiction ; un changement de définition en est toujours une) | M3, M5, M8, M9, M10 (FINANCIAL) |
| `saisonnalite` | non | travaux terminés mémorisés (≥ 30 sur ≥ 6 mois distincts, sinon inconnue) | tous |
| `vocabulaire` | non | pack sectoriel actif | tous |
| `clients_types`, `ton_marque` | non | **aucune** : déclaration de la direction ou proposition sourcée ; sinon « inconnu » | tous |
| `preferences_direction`, `regles_direction` | oui | **aucune** : seule la direction les déclare | tous |

Une dimension sans source est **« inconnu »** dans la couverture : elle n'est jamais inventée. Le cœur ne suppose aucun secteur :
le vocabulaire sectoriel vient du pack.

### 2.3 Qui peut quoi (autonomie et validation)

| Geste | Outil | Niveau | Qui |
|---|---|---|---|
| lire | `m10_lire_soi` (M10), `opsys_soi_lire` (commun à tous les départements) | T0 / N0 | l'agent ; jamais un appareil |
| construire / proposer | `m10_construire_soi`, `m10_proposer_enonce_soi` | T1 / **N2** | l'agent M10 : rien n'est confirmé |
| confirmer, rejeter, retirer | `m10_confirmer_enonce_soi`, `m10_rejeter_enonce_soi`, `m10_retirer_enonce_soi` | T1 / **N3** | une **personne** (admin ou propriétaire) : approbation ou jeton d'appareil admin |
| déclarer une règle ou corriger | `m10_declarer_enonce_direction` | T1 / **N3** | la direction ; l'énoncé naît confirmé, source = la décision |

La confirmation d'un énoncé structurant est humaine (N3) ; nous l'avons étendue à tous les énoncés : plus strict que l'exigence.
Un agent en mode « supervisé » ou « autonome », où un N3 s'exécute sans file, reçoit `REJ-MNEMO-HUMAIN-REQUIS` (même garde que
`m10_clore_signal`).

### 2.4 La dérive : proposition de révision, jamais écrasement

- Un fait nouveau qui **contredit un énoncé confirmé** (valeur différente) devient une **version proposée** qui désigne l'énoncé
  qu'elle réviserait (`revise`). L'énoncé confirmé n'est pas touché. La direction **confirme** la révision (l'ancien devient
  obsolète dans la même écriture) ou la **rejette** (l'ancien reste).
- Une **source qui disparaît** (le service n'est plus au profil) ouvre un signal de dérive, sans toucher l'énoncé ; il se lève si la
  source revient. Un profil **illisible** ne fait rien disparaître (« je ne sais pas lire » n'est pas « il n'existe plus »).
- Une nouvelle proposition remplace la précédente encore proposée (rien n'est perdu : append-only). Une proposition identique
  ajoute sa source (corroboration) et relève la confiance.
- Événement publié : `m10.soi_revision_proposee` (ids, dimension, clé, nature ; aucun contenu d'énoncé).

### 2.5 Droits de lecture

Tous les départements lisent le modèle de soi (`opsys_soi_lire`, `roles_appareil` vide). La dimension **financière** n'est ni
rendue ni nommée pour un département qui n'a pas le droit de marge : elle est seulement comptée (`retenus_confidentialite`).
La console d'administration lit tout. Les réponses sont bornées (5 700 caractères, par énoncés entiers, `suivant` pour
paginer).

## 3. Graphe de connaissances d'entités

### 3.1 Décision (r1) : natif, derrière un port

Un graphe d'entités **natif** SQL (SQLite aujourd'hui, PostgreSQL pour le SaaS), **pas Neo4j** : une PME, des requêtes de 1 à
4 sauts, de la provenance et des transactions avec le reste de l'instance (le même `COMMIT` que l'événement qui l'a fait naître).
Une base de graphe séparée ajouterait un service, une sauvegarde et un second contrôle d'accès pour un gain que la mesure n'a pas
montré. Tout moteur passe par le port `MoteurGraphe` (`graphe/port.py`).

### 3.2 Schéma fermé

Nœuds : `client`, `propriete`, `intervention`, `materiau`, `fournisseur`, `equipe`, `document`, `decision`. Arêtes (sens fixe) :

| Arête | De → vers | Sensible |
|---|---|---|
| `possede` | client → propriété | oui |
| `demande` | client → intervention | oui |
| `realisee_sur` | intervention → propriété | oui |
| `realisee_par` | intervention → équipe | non |
| `utilise` | intervention → matériau | non |
| `fourni_par` | matériau → fournisseur | non |
| `documente` | document → intervention / client / propriété | non, oui, oui |
| `justifie` | document → décision | non |
| `concerne` | décision → client, propriété, intervention, matériau, fournisseur, équipe | oui si l'extrémité est personnelle |
| `precede` | intervention → intervention | non |

Une arête hors schéma est refusée (`REJ-MNEMO-GRAPHE-ARETE-NON-AUTORISEE`), de même qu'une boucle. Ajouter un type est une
décision d'architecture (le fichier de schéma, la contrainte `CHECK` de la migration, les tests), jamais un paramètre d'appel.

### 3.3 Tables natives (migration 0052, `down_revision` 0049)

`graphe_noeuds`, `graphe_aretes`, `graphe_aretes_etats` : **append-only** (déclencheurs SQLite et PostgreSQL). L'état d'une arête
n'est jamais un champ modifiable : c'est le **dernier événement** (`brouillon` → `confirmee` → `fermee`, ou `rejetee`), écrit par un
`INSERT` conditionnel à l'état courant (deux confirmations simultanées n'en appliquent qu'une). La **validité dans le monde** est
`valide_de` (inclus) et `valide_a` (exclu), posé par l'événement de fermeture ; rien ne rouvre une arête fermée (une nouvelle
relation est une nouvelle arête). La **provenance** est obligatoire : type de source, référence, origine (bus, agent, humain,
système), confiance, auteur, instant. La rétrogradation est **refusée** dès qu'une ligne existe (suppression définitive =
frontière humaine). Plafonds : 200 000 nœuds, 500 000 arêtes (`REJ-MNEMO-PLAFOND`).

### 3.4 Requêtes bornées, en SQL

`voisinage(nœud, k ≤ 4, à_la_date)`, `chemin(de, vers, k_max ≤ 4)`, `pourquoi(arête)` (provenance, états, qui a confirmé, avec une
phrase construite par le code). Une lecture SQL par niveau du parcours, jamais une par nœud ; plafonds de 200 nœuds et 400 arêtes
(`tronque: true` dit que le plafond a coupé) ; sortie triée, donc reproductible. Deux temps distincts : la **date demandée** est
celle du monde ; l'**état** est ce que nous savons aujourd'hui (seules les arêtes confirmées ou fermées répondent ; un brouillon ne
répond que sur demande expresse et se dit tel ; une arête rejetée ne répond jamais). « Aucun chemin » est une réponse valable : le
graphe ne devine aucun lien.

### 3.5 Loi 25

Un client et une propriété ne sont connus que par leur **pseudonyme stable** (l'empreinte que M2 publie : `client_id`,
`propriete_id`) ; le libellé de leur nœud est calculé du pseudonyme, jamais fourni. Un libellé non personnel passe le
garde-fou de texte du socle (ni lien, ni adresse, ni courriel, ni téléphone, ni nom de client) ; un secret (clé, jeton, en-tête)
est refusé dans un libellé, une clé de nœud ou une source. **Aucun refus ne répète la donnée reçue** (le message dit la règle,
pas l'extrait). Le graphe contient des pseudonymes de clients (`CLIENT_PRIVATE` pour M10) : il n'est lu que par les outils
`m10_graphe_*` et la console d'administration, jamais par un paquet de contexte, et n'est ouvert à aucun appareil. Une empreinte
n'anonymise pas son contact (M2 le dit lui-même) : c'est une pseudonymisation, pas une anonymisation.

### 3.6 Alimentation par le bus

Après avoir mémorisé (inchangé), M10 nourrit le graphe depuis les événements qu'il consomme déjà : `m2.client_associe` (nœud),
`m4.travaux_termines` (intervention ; `demande` client → intervention si le client du lead est connu), `m6.variance_chantier`
(`utilise` pour les matériaux réellement utilisés) et `m2.profil_propriete_confirme` (`possede`, nouveau consommateur qui ne
nourrit que le graphe). Les arêtes **non sensibles** sont confirmées par le système (écriture interne réversible) ; les arêtes
**sensibles** restent en **brouillon** jusqu'à la confirmation d'une personne (N3) et publient `m10.arete_en_attente` (identifiants
seulement). Un identifiant hors schéma est un refus nommé dans le résultat du consommateur, **jamais** une panne : la
mémorisation de l'événement, elle, a réussi. `m10_synchroniser_graphe` rattrape le graphe depuis les événements déjà mémorisés
(idempotent, par pages). Ni technicien, ni ville, ni texte libre ne passe de la charge au graphe.

### 3.7 Adaptateurs et parité

`GrapheSql` (référence) et `GrapheMemoire` (double) partagent les règles (`graphe/regles.py` : transitions, validité, parcours en
largeur). Un test de parité rejoue des graphes aléatoires (3 graines) sur les deux moteurs et exige des réponses identiques. Le
même test a révélé, sur PostgreSQL réel, que `rowcount` d'un `INSERT … SELECT` vaut -1 avec psycopg : l'adaptateur utilise
`RETURNING`. **Le même motif (`rowcount != 1`) existe dans `opsys/connaissances/etats.py::ajouter_etat` : il n'a pas été vérifié
sur PostgreSQL et n'a pas été modifié ici (hors périmètre) ; à qualifier.**

## 4. Plan LightRAG (MIT) — documenté, NON exécuté

La décision r1 prévoit un pilote LightRAG derrière le port M10. Rien n'en est installé, importé ni exécuté. Ce que la lecture de
son dépôt (2026-11-01, lecture partielle de la page publique) permet d'affirmer : licence **MIT** annoncée (à relire dans le fichier
`LICENSE` avant tout pilote, AGENTS.md) ; graphe de connaissances extrait **par un LLM** à partir de documents, avec des
stockages interchangeables (NetworkX en mémoire par défaut, Neo4j, PostgreSQL avec AGE et pgvector) ; LLM et embeddings
appelés en HTTPS sortant dans ses configurations types.

Conditions pour qu'un pilote soit autorisé : (1) un adaptateur `GrapheLightRag` qui n'**implémente que** le port `MoteurGraphe`
(lecture) et ne reçoit jamais d'écriture de confirmation ; (2) l'extraction d'entités par LLM ne reçoit **aucun** texte contenant
une donnée personnelle (le pseudonymiseur passe d'abord) et ses sorties n'entrent que comme **brouillons d'arêtes** (jamais
confirmées sans personne) ; (3) les fournisseurs LLM/embeddings viennent du registre de fournisseurs (licence, quota, coût), pas de
la configuration de LightRAG ; (4) il rejoue `mesure.py` et le test de parité et n'est retenu que s'il **égale ou dépasse** le
moteur SQL natif sur le corpus (exactitude, rappel, abstentions, aucune réponse inventée) à coût et latence mesurés ; (5) son
stockage PostgreSQL est celui de l'instance, pas un service de plus. Tant que ces mesures n'existent pas, le moteur SQL natif est
le seul moteur. Aucune des conditions n'est vérifiée aujourd'hui.

## 5. Apprentissage continu gouverné

### 5.1 Le cycle

    événements et registres de M10 ─(code déterministe)─► leçon PROPOSÉE ─► ÉVALUATION hors ligne (mesure + garde du gabarit)
        ─► décision HUMAINE (N3) : canari (1 à 50 %) ─► promotion complète │ retour arrière │ refus ─► lecture par le département visé

Cinq genres, tirés de ce que M10 a déjà mémorisé, **jamais d'un modèle** : `ecart_materiau` (quantité réelle contre prévue, M6),
`ecart_marge` (marge réelle contre prévue, M5), `refus_recurrent` (un outil refusé avec le même code dans ≥ 3 affaires distinctes),
`rejets_soi` (≥ 3 propositions de la même dimension rejetées par la direction : une correction humaine),
`apprentissage_marketing` (M7-MEMOIRE : un contenu gagnant ou faible, un signal d'objection ou des avis défavorables qui reviennent sur ≥ 3
**semaines distinctes**, d'après les observations minimales `m7.apprentissage_marketing_constate` rangées au registre `faits_marketing` ;
cible `m07-marketing`, texte-gabarit sans chiffre, aucune mesure chiffrée hors ligne : dit ; voir [M7-MARQUE-RAPPORT](M7-MARQUE-RAPPORT.md) §4). Les « résultats de
décisions » sont couverts par les refus récurrents ; l'annulation d'une décision validée n'est pas encore une source de leçon.

### 5.2 Le texte d'une leçon ne porte aucun chiffre

Le **paramètre** (facteur, décalage en CAD) est une donnée structurée, calculée en `Decimal` par le code. Le **texte destiné à
l'agent** est un gabarit du code, sans chiffre ni identifiant : un chiffre dans une réponse d'agent doit venir d'un outil, jamais
d'une phrase apprise (AGENTS.md).

### 5.3 Évaluation hors ligne en deux parties

1. **La mesure** (genres chiffrés) : le paramètre est ajusté sur les chantiers d'entraînement (médiane, signe cohérent ≥ 70 %,
   écart ≥ 5 %, au moins 6 chantiers, 4 d'entraînement et 2 de test) puis mesuré sur des chantiers **tenus à l'écart** (partage
   par hachage de l'identifiant du chantier). Il faut une baisse d'au moins 10 % de l'erreur ET qu'aucun chantier ne perde plus de
   la moitié de l'erreur moyenne d'avant. Un genre sans mesure chiffrée possible le dit (`amelioration_mesurable: false`).
2. **La garde du gabarit commun** : le texte de la leçon est ajouté aux réponses de référence du corpus du département visé, et le
   rapport est comparé à celui sans la leçon (`rapport.comparer`) : aucune régression, aucun cas bloquant échoué de plus. Elle
   monte une instance fictive : elle **ne peut pas tourner dans un appel d'outil**. Elle se lance par
   `opsys-metier mnemo garde-lecon --lecon ID --par NOM` et écrit son verdict, avec l'empreinte du corpus de garde courant.

### 5.4 Promotion (généralisation de M1)

`opsys.mnemo.promotion` reprend les états et transitions de la boucle de M1 (proposée → canari → complète, retour arrière, refus ;
un canari à la fois ; hachage stable de la clé d'application). Un test de parité rejoue 4 + 16 + 64 + 256 suites de décisions
dans les deux moteurs. Deux différences voulues : le retour arrière d'une leçon complète n'exige pas qu'elle soit la dernière
promue (une leçon nocive se retire tout de suite), et le canari est tiré par le hachage de (leçon, clé) pour que deux leçons
n'exposent pas les mêmes cas. `m10_decider_lecon` est un **N3 humain** ; canari et promotion exigent une évaluation favorable des
deux parties, **sur le corpus de garde courant** (sinon `REJ-MNEMO-LECON-NON-EVALUEE`). Événement : `m10.lecon_decidee`
(identifiants, genre, département visé, étape ; ni paramètre ni texte).

### 5.5 Aucune leçon ne s'applique seule

Promouvoir rend la leçon **lisible** par le département visé (`opsys_lecons_actives`, avec le tirage du canari) ; c'est ce
département qui décide de s'en servir. `m10_surveiller_lecons` rejoue chaque leçon chiffrée promue sur les chantiers terminés
depuis sa promotion et dit si elle améliore, régresse ou manque de données ; elle ne retire rien (une personne décide du retour
arrière).

### 5.6 Consommation par M3 puis M5 (M10-06)

Depuis M10-06, deux départements consomment réellement les leçons, par `src/opsys/mnemo/consommation.py` (socle, calcul en
`Decimal`, aucune horloge, aucun modèle) :

- **M3 estimation**, pour l'écart de quantités de matériaux (leçon de cible `m06-material-control`, que M3 lit parce que c'est
  M3 qui prévoit la quantité) : `m3_estimer_projet` ajoute la clé sœur `prevision_materiaux_avec_lecons` (la quantité de base
  reste celle des `besoins_materiaux` ; la correction par `facteur` est proposée, attribuée et jamais appliquée au registre ni au
  prix), et `m3_prevoir_materiaux_avec_lecons` la relit pour un devis dont l'estimation d'origine est prouvée par son hash exact ;
- **M5 finance**, pour l'écart de marge (leçon de cible `m05-financecore`) : la vue détaillée de `m5_lire_rentabilite_chantier`
  ajoute `prevision_marge_avec_lecons` (la marge prévue reste `prix_total - cout_total` de M3 ; la correction par `decalage_cad`
  est proposée et attribuée, jamais appliquée à la marge calculée).

Chaque valeur corrigée cite `lecon_id`, `sources`, `date`, `echantillon`, `parametre` et la décision humaine ; sans leçon active,
avec un échantillon sous le **minimum DÉCLARÉ** (`configuration.lecons_consommees.echantillon_minimum`, vide dans les deux
manifestes), ou sans minimum déclaré, la valeur de base est conservée et le verdict dit pourquoi. La correction est une
**proposition de niveau N4** : la promotion de la leçon ne déclenche aucun geste de facturation, d'envoi ni de prix. La valeur
corrigée suit l'arrondi de la grandeur (cent `ROUND_HALF_UP` pour une marge, 4 décimales pour une quantité) ; le canari se tire
sur la version d'estimation, jamais sur le lead ; une marge exige un `droit_aux_couts` explicite dans le consommateur, sinon
elle n'est ni calculée ni rendue ; deux unités pour une même clé sont refusées (`unite_ambigue`). Depuis la correction du
4 novembre 2026, une leçon d'écart de matériau porte l'unité EXACTE de ses observations dans `contenu.unite` et dans son
identité (sans changer la clé `materiau`) ; deux unités du même matériau forment deux cohortes et deux leçons. L'évaluation et
la surveillance ne comparent que la même unité. La consommation M3 exige que l'unité de l'entrée et celle de la leçon soient
présentes et exactement égales ; une leçon d'une autre unité ne masque pas une leçon compatible, et deux leçons valides du
même couple restent ambiguës (`plusieurs_lecons_actives`). Une leçon historique sans unité reste lisible et inchangée, mais
n'est ni évaluable (`unite_absente`) ni applicable (`unite_lecon_absente`), sans migration ni promotion héritée. Le facteur
`ecart_materiau` n'est pas ventilé par service, saison, fournisseur ni équipe (voir §9 et
[LIMITES-CONNUES](../utilisation/LIMITES-CONNUES.md) §7 bis).

## 6. Console, CLI, événements

- **Console** : `/plateforme/mnemo` et `/api/plateforme/mnemo`, en lecture seule (aucun formulaire), session et rôle d'administration
  relus avant ET après la lecture, `no-store`, tout échappé, pseudonymes courts seulement. Elle montre la couverture par dimension, les
  révisions à trancher (avec l'ancien et le nouvel énoncé), les sources disparues, les arêtes sensibles en attente et les leçons
  avec leur évaluation.
- **CLI** `opsys-metier mnemo …` : `etat` (lecture), `mesurer --corpus FICHIER [--sortie DOSSIER] [--avec-gabarit]` (base
  temporaire, rapport jamais écrasé), `garde-lecon` (écrit au registre des leçons). Aucune commande ne confirme ni ne promeut.
- **Événements publiés** : `m10.soi_revision_proposee`, `m10.lecon_decidee`, `m10.arete_en_attente` (schémas fermés,
  identifiants seulement). **Consommé en plus** : `m2.profil_propriete_confirme`.
- **Outils** (21 outils M10 + 2 communs, aucun rôle d'appareil) : voir `ROLES.md`.

## 7. Ce qui a été mesuré (exécuté)

Banc `opsys-metier mnemo mesurer` sur `soi-graphe.v1.yaml` (31 questions multi-sauts, 7 cas de leçons ; fictif, plans écrits à la
main avant exécution ; **aucun modèle de langage**) :

| Mode | Exactitude | Rappel moyen | Précision moyenne | Abstentions correctes | Réponses inventées |
|---|---|---|---|---|---|
| graphe (SQL natif) | 31/31 = 1,0000 | 1,0000 | 1,0000 | 2/2 | 0 |
| témoin « un saut » (voisinage immédiat) | 21/31 = 0,6774 | 0,6667 | 0,6667 | 2/2 | 0 |

Par catégorie : un saut 5/5, temporel 6/6, chemin 3/3, « pourquoi » 2/2, négatifs 6/6 (brouillon et arête rejetée ne reviennent
jamais), **multi-sauts 9/9 contre 1/9 pour le témoin** (c'est ce que le parcours apporte). Les moteurs SQL natif et double
concordent sur toutes les questions. Cas de leçons : 7/7 conformes (support insuffisant, signe incohérent, écart négligeable,
valeur aberrante sans effet, leçon qui dégrade les chantiers de test refusée, décalage de marge négatif). Un moteur volontairement
défectueux (validité ignorée, brouillons admis) **échoue** au banc.

Gabarit commun (M10 passe de 12 à 22 cas, dix écrits avant exécution depuis le SOUL.md et les outils réels ; répondants simulés) :
`reference` 22/22 (qualifié, sondes d'autorité 3/3) ; `dangereux` 12/22 (0,4474, non qualifié, sondes tenues 3/3) ; `inventif` 0/22.
Rien de tout cela ne mesure un vrai modèle.

## 8. Fichiers

Socle : `src/opsys/mnemo/` (`soi*.py`, `lecons.py`, `promotion.py`, `garde_gabarit.py`, `mesure.py`, `outils.py`, `service.py`,
`vie_privee.py`, `cli.py`, `lecture.py`, `registres.py`, `graphe/`), migration `0052_graphe_connaissances.py`, tables dans
`stockage/schema.py`. M10 : `soi_graphe.py`, `registre.py` (7 types d'entrée de plus), `outils.py` (consommateurs enveloppés),
`department.yaml`, `SOUL.md`, `skills/gerer-le-soi-et-le-graphe/`. Événements : `catalogue/m10.*.json`. Registre MCP scellé
(révision 10).

## 9. Limites, dites sans euphémisme

1. **Aucun vrai modèle.** Les répondants du gabarit sont des doubles ; le banc du graphe n'interroge pas en français. Le fait qu'un
   agent réel utilise bien ces outils n'est pas mesuré.
2. **Aucune donnée réelle, aucun client.** Tout le corpus et tous les tests sont fictifs. Une PME réelle aura des identifiants,
   des volumes et des profils que le banc ne représente pas.
3. **La consommation des leçons est réelle mais étroite.** M3 (quantités de matériaux) et M5 (marge prévue) lisent les leçons
   promues et n'en proposent qu'une correction attribuée ; leur minimum d'échantillon est VIDE à dessein dans les manifestes, donc
   aucune correction n'est proposée tant que la direction ne l'a pas déclaré. Aucun autre département ne consomme une leçon ; le
   facteur d'écart de matériaux n'est pas ventilé par service, saison, fournisseur ni équipe ; l'unité est stockée et comparée
   exactement, sans conversion, et une correction n'est jamais appliquée automatiquement à un prix, un devis ou une marge.
4. **La garde du gabarit prouve que le TEXTE d'une leçon est inoffensif pour les contrôles universels**, pas qu'un agent se
   comportera mieux avec elle.
5. **Les leçons de quantités et de marge reposent sur peu de chantiers** (seuil de 6 ; 2 de test). Un seuil bas est un choix de PME
   assumé ; il donne des mesures larges. Le facteur n'est pas ventilé par service ou saison.
6. **Le graphe n'est alimenté que par quatre événements** ; équipes, fournisseurs, documents et décisions ne s'y ajoutent que par
   proposition d'un agent (source vérifiable) ou d'une personne. Le lien intervention → équipe ne vient d'aucun événement
   consommé aujourd'hui.
7. **Le client d'une intervention dépend de `m2.client_associe`** mémorisé avant le WCT ; sinon le lien manque (rattrapage par
   `m10_synchroniser_graphe`). Les deux événements ne sont pas ordonnés par le bus.
8. **Lecture complète des registres** : l'état du modèle de soi et des leçons est rejoué depuis le registre à chaque appel
   (O(n)) ; sans index, adapté à des centaines d'énoncés, pas à des centaines de milliers.
9. **PostgreSQL** : le graphe a été exercé une fois sur PostgreSQL 17 éphémère (Docker local), pas en CI ; la montée de la
   migration sur PostgreSQL est testée, les registres (`soi`, `lecons`) n'ont pas de variante PostgreSQL propre. Le motif
   `rowcount` de `connaissances/etats.py` est à vérifier (§ 3.7).
10. **La détection de consigne et de donnée personnelle est un jeu de motifs** (filtre de M1, garde-fou de texte) : elle ne prouve
    pas qu'une consigne inconnue serait reconnue. La barrière réelle est que rien d'irréversible ne s'exécute sans personne (N3).
11. **Numérotation** : la migration 0052 a `down_revision` 0049 (la tête réelle de la ligne) ; l'architecte la réaligne sur 0051.
12. **Pas de purge** : retirer un nœud ou effacer une donnée sur demande (Loi 25) est une suppression définitive, donc une
    frontière humaine, non outillée ici.

## 10. Suites proposées (non faites)

Brancher la leçon d'écart de quantités dans le bloc de prévision de M3 et la leçon de marge dans la prévision de M5 (avec leurs
gardes) ; événements d'équipe et de fournisseur pour alimenter le graphe ; mesure d'un vrai modèle sur le corpus de questions
(passerelle) avant tout pilote LightRAG ; index des registres ; qualification PostgreSQL de `connaissances/etats.py`.
