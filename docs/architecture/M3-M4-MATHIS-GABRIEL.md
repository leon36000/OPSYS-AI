# M3 Estimation (Mathis) et M4 Field Ops (Gabriel) : les exigences absentes ou simulées

Statut : tranche 1 (2026-11-01, base 1b58f4e6c). Code : `departments/m03-estimation/src/m3_estimation/` et
`departments/m04-field-ops/src/m4_field_ops/`. Matrices : `docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M3.json` et `…-M4.json`.
Migration : `0049` (une CHECK élargie, aucune table). Rien de ce qui suit n'est branché à un service réel.

**Suite (vague 10, M3-C1 et M3-C2)** : le barème, la quantité, le plancher rentable et les taux de marge d'une estimation ne sont plus des arguments libres ; ils viennent d'un barème **déclaré** (versionné, chaîné, en vigueur) et d'une mesure **déclarée** par une personne. Voir [`M3-BAREME-MESURE-DECLARES.md`](M3-BAREME-MESURE-DECLARES.md). Les lignes ci-dessous qui disent « barème fourni par l'appelant » décrivent l'état d'avant.

## En une table : ce qui existe, ce qui est prouvé, ce qui ne l'est pas

| Exigence | Statut visé | Ce qui existe (exécuté, avec tests) | Ce qui n'est PAS prouvé |
|---|---|---|---|
| M3.2 Contexte du site | PARTIEL | agrégation sourcée et versionnée de huit facteurs, « inconnu » explicite, conflit non tranché, permis « à vérifier », règles météo lues de `opsys.meteo`, hypothèses d'estimation structurées, journal chaîné, événement `m3.contexte_site_pret`, branchement à `m3_estimer_projet` | aucun profil de propriété de M2 n'existe encore (M2.3 : port seulement) ; la distance et l'historique du site ne sont pas dans le contexte ; aucune donnée de site réelle |
| M3.3 Pipeline de vision | SIMULÉ | contrat (photo avec provenance → candidats), port `DetecteurVision`, quatre doubles, gouvernance (candidat ≠ mesure), journal des candidats et des décisions, harnais IoU / erreur de surface | **aucun modèle** ; aucune photo réelle (politique photos encore « proposition ») ; le harnais ne mesure que des rectangles synthétiques |
| M3.5 Détection / segmentation | SIMULÉ | registre des modèles (Grounding DINO, SAM 2, Florence-2, OWLv2, YOLO écarté) avec drapeaux de licence, par `opsys.fournisseurs`, statut honnête « contrat prêt, aucun modèle qualifié » | aucun poids téléchargé ni qualifié ; licences lues de mémoire, **toutes à vérifier** ; aucune mesure sur de vraies photos |
| M3.7 Géospatial (Québec) | PARTIEL | modèle de données et trois ports (cadastre, rôle d'évaluation, imagerie) avec doubles ; aire et périmètre d'un polygone par le lacet en `Decimal`/`Fraction`, projection locale GRS 80 documentée, reçu rejouable ; sept sources publiques candidates marquées « à vérifier » | aucune donnée réelle, aucun adaptateur ; projection **non vérifiée contre PROJ ni MTM** (seulement contre la forme fermée d'une cellule de graticule) ; distance et région non faites |
| M4.11 Adéquation d'équipe | PARTIEL | indice transparent (capacité de la semaine type, charge, distance, qualité agrégée), filtre par compétence, explication par critère, refus des attributs protégés, calibration sur cas fictifs, brouillon d'affectation (N2) et approbation d'un engagement client (N3) | poids **non déclarés** (vides à dessein) ; aucune donnée d'historique réelle ; la calibration ne prouve que la mécanique ; l'assignation effective reste `m4_appliquer_cedule` |
| M4.14 ETA client | PARTIEL | fenêtre d'arrivée (jamais une heure unique), trajet par le port de routage (mode bridé : **aucun** routeur installé), consentement de suivi Loi 25 (N3 par une personne, retrait N2, expiration), brouillon de message publié à M1 (`m4.message_client_brouillon_pret`), plafond de messages, rétention bornée | **pas de lien sécurisé, pas de rôle `client` côté serveur, pas de SMS** (M1/Twilio) ; aucun routeur OSRM/Valhalla testé ; durées de validité et de conservation à valider par un juriste |

« Adopté » dans le catalogue des fournisseurs veut dire « pile visée par la définition du produit », jamais « qualifié ».
Un candidat de vision validé, un score d'équipe ou une fenêtre d'arrivée calculés ici ne prouvent rien sur le terrain : ils
prouvent la mécanique, les refus et la gouvernance.

## Principes communs

1. **Ports et doubles.** Toute entrée externe (modèle de vision, cadastre, rôle d'évaluation, imagerie, routeur) passe par un
   port ; seuls des doubles déterministes, à données FICTIVES (`fictif: true`), existent. En production, le port est absent et
   le dit (`non_configure`, `REJ-VISION-MODELE-INCONNU`), il ne rend jamais une valeur.
2. **Le code calcule.** Le détecteur ne rend que de la géométrie ; la surface et la longueur sont calculées en `Decimal` depuis
   le masque et l'échelle. L'aire d'un polygone vient d'un moteur à reçu. L'indice d'équipe est une moyenne pondérée de
   `Fraction`. Aucun chiffre n'est écrit par un modèle.
3. **Fail-closed et « inconnu » explicite.** Une donnée manquante produit un verdict qui dit quoi déclarer. Les seuils de
   confiance, les tolérances, les poids et les réglages de fenêtre sont **vides dans `department.yaml`** (décisions de
   l'entreprise, jamais un défaut inventé ; un agent ne se les donne pas).
4. **L'humain décide l'irréversible et le sensible.** N2 automatique : contexte, candidats, validation par mesure de
   référence, brouillon d'affectation, retrait de consentement, brouillon de message. N3 par une décision approuvée dans la file
   (la personne et l'heure viennent de l'approbation, les arguments exacts sont rejoués) : validation d'un candidat par une
   personne, affectation qui engage le client, consentement du client. Aucune action externe n'est exécutée.
5. **Aucun droit d'appareil élargi.** Les 19 outils sont fermés aux appareils (`roles_appareil` vide).

## M3.2 Contexte de la propriété et du site

`contexte_site.py` (pur) agrège : accès, hauteur, pente (rapport sur 12), âge, matériaux existants, contraintes saisonnières,
règles météo de l'entreprise pour le service (lues par l'adaptateur dans `opsys.meteo` : les seuils déclarés, **pas une
prévision**) et permis municipaux. Trois sources : le profil de propriété de M2 (port, forme `{identifiant, version, recu_le,
faits}`), un profil géospatial (même forme) et des déclarations qui citent leur auteur et leur date.

- Un facteur sans source est `inconnu` ; une valeur sans `declare_par`/`declare_le` est refusée (`REJ-CONTEXTE-SOURCE-ABSENTE`) ;
  deux sources qui se contredisent donnent `conflit` (les deux valeurs sont montrées, aucune n'est retenue).
- **Permis municipaux** : données à vérifier. Sans preuve (`verifie_par`, `verifie_le`, `reference`), « requise » ou « non requise »
  est refusé ; le facteur reste `a_verifier`, `exhaustif: false`. Ce n'est pas un avis juridique : À valider auprès de la
  municipalité et d'un professionnel qualifié.
- Sortie versionnée (`m3.contexte_site/v1`) : `version` ne change que si le contenu change (`empreinte_contenu`), `precedent` chaîne
  les versions, `hypotheses_estimation` liste, par facteur, `donnee_retenue`, `a_collecter`, `conflit_a_trancher` ou `a_verifier`.
  Le contexte ne chiffre aucun effet sur le prix et ne bloque rien.
- Journal `site_vision` (`opsys.stockage.maillons("m03-estimation", "site_vision")`), hash-chaîné, qui refuse tout flottant ; une
  chaîne altérée bloque l'écriture et la lecture (`REJ-SITE-JOURNAL-ALTERE`).
- **Alimentation de l'estimation** : `m3_estimer_projet` accepte `contexte_site_empreinte` (facultatif) ; les hypothèses de CE
  lead accompagnent la réponse en clé sœur `contexte_site`, hors d'`EstimationV1` et du registre. Une empreinte inconnue est
  refusée avant tout calcul ; le contexte ne débloque jamais un prix (la garde photos/échelle reste seule).
- Outils : `m3_construire_contexte_site` (T1/N2), `m3_lire_contexte_site` (T0).

## M3.3 et M3.5 Pipeline de vision, détection et segmentation

**Contrat** (`vision_contrat.py`). Entrée : une photo décrite par son empreinte SHA-256, ses dimensions, sa provenance (`jeu_synthetique`,
`client`, `employe`, `estimateur`) et son échelle (m/px, source, incertitude relative). Aucun octet d'image n'entre. Une photo
**réelle** exige la politique « photos non contractuelles » validée (aujourd'hui `proposition` : refus), une référence de
consentement et un modèle **qualifié et activé** (aucun) ; un jeu synthétique doit se déclarer fictif. Sortie : des **candidats**
(`candidate_non_validee`) avec valeur calculée, incertitude mécanique (quantification des pixels + échelle déclarée, `calibree:
false`), masque en plages, boîte, modèle et version, reçu. Une sortie de modèle est une donnée non fiable : objet non demandé,
boîte ou masque hors image, confiance hors [0, 1], masque hors de sa boîte, trop de détections, type inattendu sont rejetés avec
leur motif, jamais corrigés. Une photo sans échelle ne donne que des pixels (« plage ou hypothèse »).

**Port et doubles** (`vision_doubles.py`) : `DetecteurScripte`, `DetecteurPerturbe` (masques décalés), `DetecteurHostile`
(sorties illégales, texte d'injection), `DetecteurEnPanne`. Aucun poids, aucun réseau. En production aucun détecteur n'est
branché : `m3_executer_pipeline_vision` refuse avec « contrat prêt, aucun modèle qualifié ».

**Gouvernance** (`vision_gouvernance.py`) — la règle : *une mesure issue de la vision n'est jamais prise comme vérité*.

1. politique déclarée par l'entreprise (`configuration.vision_gouvernance` : seuil de confiance dans ]0, 1], tolérance absolue
   et/ou relative, qui l'a déclarée et quand) ; sans elle, rien ne se valide (`REJ-VISION-POLITIQUE-ABSENTE`) ;
2. sous le seuil : `rejetee_confiance` ; sans échelle : `sans_echelle` ; sinon `candidate` ;
3. validation par une **mesure de référence** de même unité (manuelle, plan, mesure plane M3.6) : toutes les tolérances déclarées
   doivent tenir, sinon `rejetee_ecart_reference` ; ou par la **décision approuvée d'une personne** (valider, refuser, corriger) ;
4. une décision par candidat, immuable ; rejouée à l'identique : no-op ; différente : `REJ-VISION-DECISION-CONFLIT` ; un candidat
   retouché est refusé (empreinte) ;
5. seule une décision validée publie `m3.mesure_vision_validee` (M8) ; elle ne débloque pas un prix (garde photos/échelle).

**Harnais** (`vision_evaluation.py`) : jeu synthétique **fictif** de rectangles (générateur congruentiel, graine fournie), IoU par
fusion de plages, erreur de surface relative du pipeline, taux de détection, comparaison à des seuils déclarés. Un rapport est
toujours `fictif` et `non_qualifie` : il prouve la mécanique du harnais (détecteur parfait = IoU 1, détecteur décalé moins bon,
détecteur vide = 0), jamais un modèle.

**Registre des modèles** (`vision_modeles.py`, `m3_lister_modeles_vision`) : réutilise `opsys.fournisseurs` (capacité `vision`,
migration 0049). Cinq entrées, toutes `a_mesurer`, licence `a_lire`, sans point d'accès. Statut global :
`contrat_pret_aucun_modele_qualifie`. Un modèle actif n'est pas qualifié : la qualification exigerait des photos réelles
consenties annotées par des personnes, une politique photos validée et des seuils décidés — rien de cela n'existe.

| Modèle | Rôle | Licence présumée (de mémoire, **à vérifier**) | Statut |
|---|---|---|---|
| Grounding DINO | détection guidée par texte | Apache-2.0 (code et poids, par jeu de poids) | adopté (pile visée) |
| SAM 2 | segmentation par invite | Apache-2.0 | adopté (pile visée) |
| Florence-2 | détection et segmentation | MIT | repli |
| OWLv2 | détection à vocabulaire ouvert | Apache-2.0 | repli |
| Ultralytics YOLO | détection / segmentation | AGPL-3.0 | écarté (copyleft) |

## M3.7 Estimation géospatiale (Québec)

**Données et ports** (`geospatial.py`) : `Adresse` (clé de recherche sans accents ni casse), `LotCadastral`, `UniteEvaluation`
(année de construction, étages, superficies, usage), `ReferenceImagerie`, avec leur source (millésime, réception, licence,
fictif) ; ports `PortCadastre`, `PortRoleEvaluation`, `PortImagerie`. `PortAbsent` (production) répond « non configuré ». Les
doubles refusent toute donnée non fictive. `agreger` n'est jamais bloqué par un port en panne, ne recopie pas l'erreur d'un port,
calcule la surface du lot par le moteur (jamais la superficie que le rôle affirme), traite l'imagerie comme du **contexte
seulement** et produit des `faits_pour_contexte` que M3.2 confronte à M2. La recherche d'adresse du RQA reste celle de M4.

**Sources publiques candidates** (`m3_lister_sources_geospatiales`, toutes `lue_par: null`) :

| Source | Donnée | Licence présumée | Statut |
|---|---|---|---|
| Rôles d'évaluation foncière (MAMH, Données Québec) | unités d'évaluation | CC-BY 4.0 | à vérifier |
| Cadastre du Québec (lots rénovés) | lots et géométrie | CC-BY 4.0 présumée ; Infolot / Registre foncier : autres conditions | à vérifier |
| Référentiel québécois des adresses (RQA) | adresses géocodées | CC-BY 4.0 (fiche lue le 2026-09-28, `INGREDIENTS.md`) | déjà documentée (M4) |
| Orthophotographies aériennes du Québec | imagerie | CC-BY 4.0 présumée | à vérifier |
| OpenStreetMap | bâtiments, voirie | ODbL 1.0 (partage à l'identique : analyse avant usage) | à vérifier |
| Données ouvertes de la Ville de Montréal | évaluation, bâtiments | CC-BY 4.0 présumée | à vérifier |
| Google Street View / Maps | imagerie de rue, géocodage | conditions commerciales, budget non décidé | fermé (contexte seulement) |

**Aire et périmètre** (`geometrie_polygone.py`, `m3_calculer_aire_polygone`) : formule du lacet en `Decimal` à 60 chiffres, tests
d'intersection exacts en `Fraction`, sommets en textes décimaux (un flottant est refusé). Deux systèmes : `plan_metrique` (aire de
grille, facteur d'échelle de grille déclaré, jamais supposé égal à 1) et `geographique`. Projection `tangent-local-grs80-v1` :
plan tangent local autour de la moyenne des sommets sur l'ellipsoïde GRS 80, `x = Δλ·N0·cos φ0`, `y = Δφ·M0` (sinus et cosinus par
série de Taylor, racine par `Decimal.sqrt`). Approximation du **premier ordre** : tout polygone de plus de 2 000 m d'étendue est
refusé. Contrôle indépendant : l'aire d'une cellule de graticule a une forme fermée sur l'ellipsoïde (latitude authalique) ; l'écart
mesuré est d'environ 10⁻⁷ en relatif pour des cellules de 200 m à 1,3 km (test : tolérance 10⁻⁶), et une projection sphérique naïve
s'écarterait de plus de 0,2 %. Non vérifié contre PROJ ni la projection MTM officielle. Refus : polygone non simple (nœud
papillon, pointe, sommet répété, arêtes colinéaires qui se chevauchent), moins de 3 ou plus de 500 sommets, hors du rectangle de
vraisemblance du Québec (garde grossière contre l'inversion latitude/longitude), étendue excessive. Le reçu (`recu-geometrie.v1`)
porte moteur, version, méthode, paramètres, empreinte des entrées, résultat, avertissements et empreinte ; `rejouer` refait le
calcul et attrape un reçu retouché même si son empreinte a été recalculée. L'incertitude d'aire d'ordre un (périmètre × σ) n'est
donnée que si la source déclare σ.

## M4.11 Indice d'adéquation équipe ↔ intervention

`adequation_equipe.py` (pur). Il répond à « quelle équipe est la mieux placée pour CE chantier ? », jamais à « qui est bon ? ».

- **Conciliation avec R-020** (SOUL.md M4 : « ni score, ni classement, ni pénalité de performance d'un technicien »). L'indice porte
  sur un **couple (équipe, intervention)**, l'historique de qualité est un **agrégat d'équipe** utilisé seulement si l'historique
  atteint un minimum déclaré **et** que l'équipe compte au moins deux membres déclarés, il n'expose aucun nom ni aucun nombre de
  membres, et aucune sanction ne s'y rattache. La garde statique R-020 de M4 (`digest.garde_conformite_r020`) reste intacte : le
  vocabulaire du code est « indice », « ordre », « adéquation » (jamais « score » ni « classement » dans un identifiant).
- **Filtres** (pas de note) : toutes les compétences du service (profil) ; capacité libre de la semaine (heures de quart à la
  SEMAINE TYPE moins ce que la cédule appliquée a déjà planifié, par `capacite_equipe.calculer`) ≥ durée du service. Capacité non
  calculable : « non évaluable », jamais zéro.
- **Critères** dans [0, 1], en `Fraction` : `capacite` = (libre − durée) / libre ; `charge` = 1 − planifié / disponible ;
  `distance` = 1 − min(d, d_ref) / d_ref (distance droite dépôt → chantier confirmé) ; `qualite` = 1 − écarts / chantiers vérifiés.
  Indice = Σ poids actifs × sous-indices / Σ poids actifs, arrondi à 4 décimales à l'affichage.
- **Équité.** Un critère n'est actif que si la donnée existe pour **toutes** les équipes comparées (sinon il est écarté pour toutes
  et le dit) : aucune équipe n'est avantagée ou pénalisée par une donnée manquante. L'entrée est une liste fermée de champs ; tout
  champ dont un mot est un attribut protégé (âge, sexe, genre, origine, religion, langue, état civil, handicap, santé, opinions,
  syndicat, famille…) ou une personne est refusé (`REJ-ADEQUATION-ATTRIBUT-INTERDIT`), à toute profondeur, accents et casse
  ignorés. L'indice est invariant à l'ordre et aux noms des équipes ; les ex aequo sont signalés et départagés par l'identifiant
  seulement (« sans signification »).
- **Explication** : par critère, valeur brute, sous-indice, poids effectif et contribution, plus une phrase fixe. Aucun texte de
  modèle.
- **Calibration** (`calibrer_poids`, `m4_calibrer_poids_adequation`) : grille exacte de poids ; exige `fictif: true` sur chaque cas
  (`REJ-ADEQUATION-DONNEES-REELLES-REFUSEES`) ; départage les poids à accord égal par la proximité de l'uniforme. Elle ne fixe
  aucun poids : les adopter est une décision de l'entreprise (`configuration.adequation`, vide).
- **Humain** : `m4_proposer_adequation_equipes` (T0) propose ; `m4_enregistrer_brouillon_affectation` (T1/N2) inscrit un brouillon
  interne (refuse `engagement_client: true`) ; `m4_approuver_affectation_engageante` (T1/N3) approuve, par une personne et sur un
  brouillon, une affectation qui engage le client (une seule par intervention). Aucun des deux n'assigne : l'affectation effective
  reste `m4_appliquer_cedule`.

## M4.14 Fenêtre d'arrivée du client

- **Fenêtre** (`eta_client.py`) : `bas = max(début du créneau daté, départ + trajet)`, `haut = max(début, départ + trajet × (100 + incertitude) / 100) + retards déclarés`,
  largeur minimale déclarée, arrondi vers l'extérieur à la granularité déclarée. Jamais une heure unique (prouvé par balayage), jamais
  une promesse (`promesse: false`), jamais une fenêtre déjà passée (`REJ-ETA-FENETRE-DEPASSEE`). Le trajet vient de
  `distances.obtenir_matrice` (palier 0 approximatif, « mode bridé », signalé ; un routeur OSRM/Valhalla se branche par le port
  existant, **aucun n'est installé ici**). La sortie ne contient ni position, ni point de départ, ni nom, ni adresse.
- **Consentement de suivi** (`suivi_client.py`, Loi 25) : finalité unique, un chantier, un canal (SMS ou courriel), durée bornée (au
  plus 30 jours, plafond du code, valeur déclarée), recueilli par une **personne** (N3 approuvé, jamais un agent), énoncé versionné,
  preuve par référence. Retrait (STOP, client, équipe, administration) immédiat (N2) ; un consentement antérieur ou égal au retrait
  ne le lève pas ; expiré, il ne permet plus rien. Aucun contact ni position n'est gardé (M1 détient le contact par `lead_id`).
  Le retrait est DIT à M1 par `m4.consentement_suivi_retire` (même transaction ; `lead_id`, canal, instant, maillon terminé ; ni contact
  ni source) : M1 refuse alors les brouillons visés et neutralise ceux qui ne sont pas partis (voir `INTERCONNEXION.md` §2). Politique
  SMS (`POLITIQUE-consentement-sms.md` §4) : « appliqué dans les 48 heures » ; le code l'applique à la livraison de l'événement, plus sévère
  (même choix que le STOP de M1, ADR-0011).
- **Message** : `m4_preparer_message_eta_client` (T1/N2) compose un texte FIXE (une fenêtre, « estimation, pas une promesse », le
  moyen de se retirer), le fait passer par le garde-fou de texte du socle (aucune adresse, coordonnée, nom, lien, prix…), enregistre
  la fenêtre (empreinte du texte, `conserve_jusqu_au`) et publie `m4.message_client_brouillon_pret` à M1. **Rien n'est envoyé** :
  l'envoi est une décision N3 de M1. Plafond de messages par chantier et canal (`REJ-ETA-QUOTA-MESSAGES`) ; republier la même
  fenêtre est un no-op.
- **Rétention bornée** : le registre M4 est append-only ; il ne reçoit que des identifiants, la fenêtre et des empreintes. La ligne
  subsiste (sa destruction est une suppression définitive, N5) mais ne contient aucune donnée sensible. Les durées sont à valider
  auprès d'un juriste (Loi 25).

## Interconnexion

| Événement (catalogue) | Producteur | Consommateur visé | Câblé ? |
|---|---|---|---|
| `m3.contexte_site_pret` | M3 (`m3_construire_contexte_site`) | M2 (profil de propriété, M2.3), M10 | oui, M2 (comptes par statut, dits au coach) ; M10 non, justifié ([INTERCONNEXION.md](INTERCONNEXION.md)) |
| `m3.mesure_vision_validee` | M3 (validation par référence ou par une personne) | M8 (mesures) | oui, M8 (registre `faits_operations`, sans photo ni modèle) |
| `m4.message_client_brouillon_pret` | M4 (`m4_preparer_message_eta_client`) | M1 (brouillon de message, envoi N3) | oui, M1 : brouillon du sas d'envoi (courriel) ou « sms à reprendre » ; jamais envoyé |
| `m3.besoins_materiaux` (existant) | M3 | M6 | oui (inchangé) : les quantités du matériel restent celles de l'estimation |

> Mise à jour de l'interconnexion (2026-11-01, [INTERCONNEXION.md](INTERCONNEXION.md)) : les consommateurs ci-dessus existent maintenant, prouvés sur le vrai bus ; M3 reprend aussi le profil de propriété CONFIRMÉ de M2 (`m2.client_associe` + `m2.profil_propriete_confirme`) dans son contexte de site, et M4 le dit à la préparation (bloc `contexte_propriete`, hors verdict). L'ancien texte ci-dessous décrit l'état de la tranche d'origine.

M1 / M2 / M8 / M10 sont d'autres lignes de travail : leurs consommateurs ne sont pas touchés ici (aucun import entre
départements, aucun droit élargi). Les schémas JSON sont dans `src/opsys/evenements/catalogue/`.

## Configuration à déclarer par l'entreprise (vide dans `department.yaml`)

| Clé | Département | Sert à | Sans elle |
|---|---|---|---|
| `configuration.vision_gouvernance` (`seuil_confiance`, `tolerance_absolue`/`tolerance_relative`, `declaree_par`, `declaree_le`) | M3 | valider un candidat de vision | `REJ-VISION-POLITIQUE-ABSENTE` |
| `configuration.adequation` (`poids`, `distance_reference_km`, `historique_minimum`) | M4 | ordonner les équipes | `REJ-ADEQUATION-PARAMETRES-ABSENTS` |
| `configuration.eta_client` (incertitude, largeur minimale, granularité, validité du consentement, conservation, plafond de messages) | M4 | estimer et préparer une fenêtre | `REJ-ETA-PARAMETRES-ABSENTS` |

## Outils (19 nouveaux, aucun droit d'appareil)

M3 : `m3_construire_contexte_site` (T1/N2), `m3_lire_contexte_site` (T0), `m3_executer_pipeline_vision` (T1/N2),
`m3_lire_candidats_vision` (T0), `m3_valider_candidat_par_reference` (T1/N2), `m3_valider_candidat_par_humain` (T1/N3),
`m3_lister_modeles_vision` (T0), `m3_calculer_aire_polygone` (T0), `m3_agreger_donnees_geospatiales` (T0),
`m3_lister_sources_geospatiales` (T0). M4 : `m4_proposer_adequation_equipes` (T0), `m4_calibrer_poids_adequation` (T0),
`m4_enregistrer_brouillon_affectation` (T1/N2), `m4_approuver_affectation_engageante` (T1/N3), `m4_estimer_eta_client` (T0),
`m4_enregistrer_consentement_suivi_client` (T1/N3), `m4_retirer_consentement_suivi_client` (T1/N2),
`m4_lire_consentement_suivi_client` (T0), `m4_preparer_message_eta_client` (T1/N2). Table des rôles : [ROLES.md](ROLES.md).

## Migration 0049

`0049_capacite_vision` ajoute « vision » aux capacités admises de `fournisseurs_configurations` (CHECK remplacée en place sur
SQLite, `batch_alter_table` sur PostgreSQL ; même technique que 0040 et 0044). Aucune table. La descente est refusée si un
fournisseur « vision » est configuré. **`down_revision` est « 0044 » dans cette branche** (la tête réelle de la ligne de base) : les
numéros réservés 0045 à 0048 y n'existent pas ; l'architecte le réaligne sur « 0048 » à l'intégration (une ligne). La variante
PostgreSQL n'a pas été exécutée.

## Ce qui reste, sans euphémisme

- Aucun modèle de vision n'est installé, téléchargé ni qualifié ; le harnais est synthétique. La route vers « qualifié » : photos
  réelles consenties annotées par des personnes, politique photos validée, GPU, seuils décidés, lecture des licences.
- Aucune source géospatiale réelle ; licences des sources et des modèles non lues ; projection non vérifiée contre PROJ/MTM ; la
  distance et la région du site ne sont pas dans le contexte.
- Le profil de propriété de M2 existe (M2.3) et ses consommateurs sont câblés (voir [INTERCONNEXION.md](INTERCONNEXION.md)) ; une propriété ambiguë (plusieurs propriétés confirmées d'un client) n'est jamais devinée. Rien n'est prouvé contre un vrai service externe.
- Poids, tolérances et réglages de fenêtre non déclarés : les outils correspondants refusent tant que la direction ne les a pas
  décidés. Aucune donnée d'historique d'équipe réelle.
- Lien de suivi sécurisé et expirant, rôle `client` côté serveur, notification SMS (M1/Twilio) : absents (M4.14 reste PARTIEL).
- Durées de validité du consentement et de conservation, plafond de messages : décisions et avis juridique (Loi 25) à obtenir.
- Variante PostgreSQL de la migration et des tests de journal : non exécutée ici.
