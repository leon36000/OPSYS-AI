# M10 : contradictions, ordre de vérité et ingestion de la mémoire de projet

Statut au 2026-11-02 (ligne de base `ea631e4bc`) : **livré en ombre par défaut, éprouvé en processus Python sur SQLite avec le vrai
bus, la vraie file d'approbation et le vrai planificateur à horloge injectée ; aucune donnée réelle, aucun modèle, aucun PostgreSQL
rejoué.** Chantiers M10-03 et M10-04 de l'analyse d'écart ANALYSE-M10 (voir « Sources » plus bas). Rien de
ce document n'écrit « complet » : la matrice M10 reste `PARTIEL` sur les lignes concernées.

## 1. Le problème

Deux mémoires de sources différentes peuvent se contredire (un ancien rapport contre la matrice vivante, deux décisions
incompatibles, un fait remplacé). Avant ce chantier, M10 ne détectait une contradiction qu'à la main (`m10_signaler_revision`) ou dans le
preflight du développement. Règle du condensé de Nathan : **on ne tranche pas au hasard** ; on range la contradiction, on marque les
mémoires, on propose selon l'ordre de vérité, une personne valide ce qui est critique, et rien n'est supprimé.

## 2. L'ordre de vérité est une DONNÉE

`departments/m10-memoire/contracts/ordre-verite.v1.json` (schéma fermé, validé par `verite.py`, refus `REJ-VERITE-ORDRE-INVALIDE`) :

| Rang | Classe | Peut être émise par |
|---|---|---|
| 1 | `constitution` | ingestion d'un fichier du dépôt (domaine développement) |
| 2 | `decision_proprietaire` | ingestion (développement) ; une personne (affaires, N3) |
| 3 | `matrice_vivante` | ingestion (développement) |
| 4 | `rapport_valide` | ingestion ; une personne (affaires, N3) |
| 5 | `test_sonde` | ingestion |
| 6 | `code` | ingestion |
| 7 | `documentation` | ingestion ; un agent (affaires) |
| 8 | `journal` | ingestion ; un agent (affaires) |
| 9 | `memoire_ancienne` | ingestion ; un agent (affaires) |
| 10 | `hypothese` | ingestion ; un agent (affaires) |

C'est l'ordre du condensé de Nathan (`M10-MEMOIRE.md`, « Résolveur de vérité canonique »). **Divergence connue, non tranchée** : l'analyse
d'écart (ANALYSE-M10 §3 point 5) recommande de placer la preuve exécutée (tests et sondes, code) *au-dessus* de l'étiquette d'une matrice,
comme `DEFINITION-PRODUIT` §7. Comme l'ordre est une donnée, changer d'avis = changer ce fichier : son empreinte est consignée dans
chaque contradiction, on sait toujours selon QUEL ordre une proposition a été faite. Décision de Nathan en attente.

La logique (`verite.py`, `contradictions.py`) ne connaît aucune classe par son nom : elle lit la position, les classes critiques, les
familles de sujet par domaine et les motifs de fichiers du dépôt. Les tests inversent l'ordre dans le fichier et vérifient que la
proposition suit (`test_l_ordre_est_une_donnee_la_logique_suit_le_fichier_pas_les_noms`).

**Une autorité haute ne se déclare pas.** La classe d'une affirmation dépend du canal qui l'a écrite : un agent ne peut émettre que les
classes que l'ordre admet pour `affaires:agent` ; la constitution et la matrice ne viennent que de l'ingestion d'un fichier du dépôt dont
la **place** dicte la classe (`sources_fichiers`) ; une décision du propriétaire dans les affaires passe par un N3 humain. Un bloc
d'affirmations glissé dans un fichier de documentation ne prend jamais la classe « constitution » (la classe vient du chemin, pas du contenu).

**Criticité** (donnée aussi) : une contradiction est critique si l'une des deux classes est `constitution` ou `decision_proprietaire`, ou si
l'attribut est `gate_humain`, `regle_permanente`, `niveau_approbation` ou `confidentialite`.

## 3. Ce qui est rangé : deux registres append-only chaînés

Registres durables de M10 (sans migration : `stockage.maillons('m10-memoire', <nom>)`) :

- **`affirmations`** : `affirmation_enregistree` (domaine, sujet « famille:identifiant » à famille fermée, attribut, **valeur = un jeton**, classe, émetteur,
  référence **vérifiable** : `registre:<evenements|affaires>:<ligne_id>` qui existe, ou `projet:<chemin>@<sha256>`), `affirmation_retiree`. Aucun champ libre : une valeur ne peut être ni un numéro de téléphone ou de carte, ni un courriel, ni une forme de clé ou de jeton (détecteur du coffre de secrets, plus les formes collées à un préfixe et les longues suites aléatoires). La même source
  (même clé, même classe, même émetteur) qui se réexprime *remplace* sa version précédente (supersede : l'ancienne reste au registre) ; ce n'est pas
  une contradiction.
- **`contradictions`** : `contradiction_detectee` (les deux côtés, la proposition, l'empreinte de l'ordre), `contradiction_marque` (une par mémoire),
  `contradiction_demande` (la demande d'approbation), `contradiction_decidee` (la décision humaine). L'identifiant d'une contradiction est une
  empreinte de (clé, deux affirmations) : **rejouer la détection n'ajoute rien**.

L'état (`ouverte`, `resolue_auto`, `en_attente_humain`, `decidee`, `caduque`) et la marque de chaque mémoire (`retenue`, `dominee`, `contestee`, `valide`) sont **rejoués**
depuis les maillons, jamais des champs qu'on positionne. Une contradiction dont l'une des deux affirmations est remplacée ou retirée devient `caduque`.

## 4. Résolution

1. Rangs différents, non critique : la classe de plus haute autorité est **retenue**, l'autre est marquée **dominée** (`resolue_auto`). Les deux
   affirmations restent lisibles : la trace d'origine n'est jamais perdue.
2. **Critique** (même avec un gagnant clair) : les deux mémoires sont **contestées**, la proposition est consignée, et le planificateur ouvre **une demande au sas
   d'approbation** (`approbations.creer_demande`, N3, `m10_decider_contradiction`) dont les arguments sont la proposition de l'ordre. Rien n'est appliqué tant que
   personne n'a approuvé. Plafonds : 5 demandes par passage, 20 ouvertes en tout (le sas n'est pas inondé).
3. Même rang : aucune proposition, les deux mémoires sont contestées ; une égalité *critique* n'ouvre pas de demande (rien à proposer), elle est comptée
   (`sans_proposition`) pour qu'une personne la voie dans la file.
4. Décision humaine (N3 : `retenir_a`, `retenir_b`, `coexistence_valide`, `fausse_alerte`) : définitive, motivée, au nom de la personne (jeton admin ou approbation) ;
   jamais de fusion, jamais de suppression.

Les domaines `affaires` et `developpement` ne se croisent jamais (le domaine fait partie de la clé de détection) ; le domaine développement n'a aucune voie d'agent.

## 5. Outils et routine

| Outil | Niveau | Rôle |
|---|---|---|
| `m10_consigner_affirmation` | T1/N2 | un fait à clé, sourcé, domaine affaires, classes admises à l'agent |
| `m10_declarer_affirmation_humaine` | T1/N3 | classes d'autorité haute dans les affaires, par une personne |
| `m10_lire_contradictions` | T0/N0 | la file (à traiter par défaut) ou les affirmations avec leur marque, par domaine, paginée |
| `m10_rafraichir_contradictions` | T1/N2 | détecte, range, marque, propose, ouvre les demandes ; `ecrire` faux = calcul à blanc ; écriture réservée au planificateur |
| `m10_decider_contradiction` | T1/N3 | la décision humaine |

Aucun droit d'appareil (une personne passe par la file d'approbation de la console). La routine `m10.routine.contradictions-memoire`
(`routines_planifiees` du manifeste, cron `10 4 * * *` à valider par la direction, **inactive par défaut**, en ombre elle journalise « aurait » avec des compteurs et
n'écrit rien) appelle uniquement `m10_rafraichir_contradictions`. Inventaire : `connecteurs_planification/inventaire.py`.

## 6. M10-03 : ingestion de la mémoire de projet (domaine développement)

`opsys-metier memoire-developpement ingerer-projet --depot <chemin>` (identité humaine interactive, comme tout le domaine développement ; `ingestion_projet.ingerer`).
Lit les fichiers **suivis par Git** du périmètre de l'ordre de vérité (directives, ADR, `AGENTS.md`/`CLAUDE.md`, matrices, condensés `PROMPTS-NATHAN-ANCIENS` quand ils sont sur la ligne, documentation produit et
architecture) et range, de façon déterministe :

- une **source** par fichier : chemin, empreinte sha256, dernier commit et sa date, classe d'autorité, extrait expurgé ;
- directives et règles d'agent : une **décision par section** `##` (autorité = la classe du fichier) ; ADR : une décision (statut lu de l'en-tête ; « Accepted (… qui supersede) » reste accepté) ;
  la ligne « Remplace : … » lie l'ADR remplacé à son successeur (`superseded_by`) pour un remplacement **total** ; un remplacement partiel (« le point 1 de… ») n'est que consigné ;
  condensés : un **prompt versionné** (module lu du nom, `M7-…` -> `M7`) ; matrices : une **affirmation par exigence** (`matrice_vivante`) ; tout fichier peut porter un bloc
  ```` ```m10-affirmations ```` (JSON strict) dont les affirmations prennent la classe de son chemin ;
- **sensibilité** classée par fichier (`aucune` ou `masquee`, avec le nombre de secrets, courriels et téléphones, jamais leur valeur) ; tout ce qui est rangé passe par l'expurgation existante.

**Idempotente** (la clé est l'empreinte du contenu : rejouer, ou un commit qui ne touche pas le fichier, n'ajoute ni événement ni maillon) ; **jamais de suppression** (un fichier modifié ajoute une version, une section ou un
fichier retiré reçoit une version « archivée », une affirmation dont la source a disparu est *retirée* par une entrée) ; **bornée** (200 fichiers, 256 Ko par fichier, 4 Mo, aucun lien symbolique, aucun chemin privé).
Les décisions et prompts ingérés portent le module `PROJET` : le **preflight de développement existant** les voit pour n'importe quel module quand ils sont pertinents pour la tâche
(directive en vigueur, ADR remplacé -> successeur, ancre de fichier exacte, fraîcheur par empreinte).

## 7. Preuves exécutées

| Preuve | Où |
|---|---|
| Logique pure : affirmations hostiles (25 refus typés), supersede, détection, marques, états rejoués, décisions | `departments/m10-memoire/tests/test_contradictions.py`, `test_verite.py` |
| Outils sur SQLite : niveaux, canaux, isolation des domaines, planificateur seul, sas, plafonds, lecture bornée | `departments/m10-memoire/tests/test_contradictions_outils.py` |
| Ingestion : dépôt Git fictif, idempotence, secrets et PII, versions, archives, remplacements, preflight, CLI | `departments/m10-memoire/tests/test_ingestion_projet.py` |
| **Scénario de bout en bout** : vrai bus, vraie file d'approbation, vrai planificateur à horloge injectée, ombre puis actif, rejeu, approbation, aucun contenu personnel dans les journaux | `tests/test_contradictions_m10_e2e.py` |
| Console Mnémo privée : files `affaires` et `developpement` séparées, projection bornée sans valeurs ni références, lecture seule après garde admin, repli indisponible sans fuite | `tests/test_mnemo_console.py` (13 tests, 7 novembre 2026) |

Limites dites sans euphémisme : **dans le canal agent, la classe est déclarée par l'agent parmi les quatre classes basses** (documentation, journal, mémoire ancienne, hypothèse) : l'ordre entre elles est indicatif (un agent peut en dominer un autre en choisissant une classe plus haute que sa source réelle ; la marque est informative, rien n'est supprimé), seule l'usurpation d'une classe haute est impossible, et tout ce qui touche une classe ou un attribut critique reste à une personne ; SQLite seulement (le domaine développement est SQLite par conception, ADR-0012) ; horloge injectée ; aucune donnée réelle ; l'ingestion est un analyseur de structure (titres, en-têtes, ligne
« Remplace ») qui ne comprend pas le sens d'une directive : une directive qui change de sens sans changer de section est une nouvelle version, pas une contradiction (seule une affirmation à clé en est une) ;
la détection ne porte que sur ce qui a été *affirmé à clé* (par un agent, une personne ou un fichier à bloc) : elle ne lit pas le texte libre des mémoires ; aucun détecteur automatique ne tire de clés des registres existants
(événements, faits analytiques) : c'est une extension ; la console Mnémo montre désormais les deux files à traiter mais aucune valeur d'affirmation ni action de décision (décision par la file d'approbation) ; l'accès mobile admin n'est pas ouvert
(aucun droit d'appareil, pour ne pas élargir les portées) ; `rapport_valide`, `test_sonde` et `code` n'ont pas de producteur en production (seuls les canaux existent) ; l'ordre de vérité attend la décision de Nathan sur le point 5.

## Sources

Condensé de Nathan `M10-MEMOIRE.md` et analyse d'écart `ANALYSE-M10.md` (chantiers M10-03 et M10-04), branche `claude/analyse-prompts-nathan` ; ADR-0012 (isolation des deux domaines) ; `docs/architecture/PLANIFICATION.md` §10 (routines planifiées).
