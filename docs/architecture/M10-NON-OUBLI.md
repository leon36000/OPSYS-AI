# M10 : batterie de questions-tests « non-oubli » (M10-05)

Statut au 4 novembre 2026 : **tranche bornée livrée, PARTIELLE**. Elle mesure, par du code
déterministe et sur un corpus **entièrement fictif**, si les faits qu'une question déclare attendus
sont encore retrouvables dans le registre Événements de M10, avec leurs sources. Aucun modèle,
aucun réseau, aucun service extérieur, aucune donnée réelle. Aucun outil, aucun droit d'appareil et
aucune planification ne sont ajoutés : la batterie est un banc pur, appelé par ses tests.

## 1. Le problème

Le rapport hebdomadaire existant (`routines.rapport_audit`) répond à cinq questions de **traçabilité
du bus** : un événement que le bus dit avoir livré a-t-il sa trace ? Les chaînes sont-elles intactes ?
Les jours sont-ils consolidés ? Combien de révisions attendent ? Quel est l'âge de la dernière
mémoire ? Il ne mesurait pas la **récupération d'un ensemble de faits attendus** par une question, ni
la précision de ce qui est retourné, ni la couverture des sources. C'est ce manque que cette tranche
comble, sans refaire l'audit existant.

## 2. Ce que la batterie contient

`departments/m10-memoire/evals/non-oubli.v1.yaml` (schéma `opsys.m10.non_oubli/v1`, `fictif: true`) :

- **documents** : des sources fictives, chacune avec un `id`, un `domaine` (`affaires` ou
  `developpement`) et un `texte` qui ne doit jamais sortir dans un rapport ;
- **faits** : des clés publiques du registre Événements (`type_evenement` + `identifiant`), l'affaire
  à laquelle elles appartiennent (`affaire_id`) et les documents qui les sourcent ;
- **questions** : un texte fictif, une affaire, une portée fermée (`types_evenement`), les faits
  attendus (`attendus`) et, facultativement, les faits interdits (`interdits`).

Le corpus livré contient huit documents, huit faits et six questions sur deux affaires fictives :
une gouttière menée du lead au devis accepté, aux travaux terminés, à la variance et à la
rentabilité ; un revêtement resté au devis sans réponse. Tous les faits attendus y sont présents :
la mémoire intacte donne 100 % de rappel et de précision.

La validation est fermée (`batterie.valider_batterie`, `BatterieInvalide`) : champ inconnu,
`fictif` absent, identifiant dupliqué, source inconnue ou dupliquée, document d'un domaine inconnu,
fait attendu inconnu, fait hors de l'affaire ou des types de sa question, fait à la fois attendu et
interdit, texte ou volume hors bornes : refus typé, jamais un cas ignoré.

## 3. Les mesures

`batterie.evaluer_batterie(corpus, maillons_evenements, maillons_affaires=None,
documents_disponibles=None)` rend un rapport complet, jamais une note composite :

| Mesure | Numérateur | Dénominateur | Si le dénominateur manque |
|---|---|---|---|
| **rappel** | occurrences de faits attendus retrouvés (une par question évaluable) | occurrences de faits attendus (une par question évaluable) | `evaluable: false` + `raison` |
| **précision** | occurrences de faits attendus retrouvés (une par question évaluable) | occurrences de faits retournés par la portée (une par question évaluable) | `evaluable: false` + `raison` |
| **couverture** | questions évaluables | questions de la batterie | `evaluable: false` + `raison` |
| **couverture des sources** | occurrences de sources attendues uniques d'une question et disponibles | occurrences de sources attendues uniques d'une question (questions évaluables) | `evaluable: false` + `raison` : `AUCUN_INVENTAIRE_SOURCES` si l'inventaire est absent et qu'une question évaluable attend une source, `AUCUN_FAIT_EVALUABLE` si aucune question n'est évaluable, `AUCUNE_SOURCE_ATTENDUE` si les questions évaluables n'attendent aucune source |

**Les agrégats sont des sommes d'occurrences par question, pas une couverture d'ensemble.** Si deux
questions partagent un fait, il compte deux fois au numérateur et au dénominateur du rappel ; si
elles partagent une source, elle compte deux fois dans la couverture des sources ; si la portée de
deux questions retourne le même événement, il compte deux fois au dénominateur de la précision. Le
rapport le déclare dans `semantique_agregation` (`unite: occurrence_par_question`,
`couverture_ensemble: false`). Exemple fictif : deux questions `Q-PARTAGEE-1` et `Q-PARTAGEE-2`
attendent le même fait `F-A`, sourcé par `DOC-A` ; avec `["DOC-A"]`, la couverture des sources vaut
`2/2` pour **une** source unique, et avec `[]` elle vaut `0/2` avec **deux** entrées
`sources_absentes` (une par question). Ce n'est pas un pourcentage de faits uniques retrouvés : pour
une couverture d'ensemble, il faudrait un autre calcul, qui n'est pas fait ici.

`sources_absentes` est nommé au grain `(question, fait, source)`. Une même source absente citée par
deux faits d'une même question, ou par deux questions, apparaît donc plusieurs fois ; le
dénominateur de `couverture_sources`, lui, ne compte qu'une fois par question une source attendue
unique. La précision suit la même convention : un événement retourné par la portée de deux questions
compte deux fois à son dénominateur, et n'est au numérateur que dans les questions où il est attendu.

**Contrat des maillons.** `maillons_evenements` et `maillons_affaires` sont des séquences de
mappings portant un `type_entree` de l'énuméré de `registre.types_entree()`. Un conteneur mapping,
un maillon non-mapping, un conteneur binaire (`str`, `bytes`, `bytearray`, `memoryview`) ou un
`type_entree` absent ou inconnu est refusé (`REJ-BATTERIE-FORME`) : ce n'est pas une absence de
faits.

Pour un **événement reconnu** (un type opérationnel que `classification.py` classe), la clé
publique (`devis_id`, `wct_id`, `evenement_id`, `fait_id`, `lead_id`) doit être une chaîne de la
forme réelle du type : absente, `None`, mal typée ou non hashable, elle est refusée au lieu de
produire un faux oubli, une fausse précision ou un `TypeError`. C'est le cas notamment d'un
`m3.devis_accepte` sans `devis_id`, d'un WCT sans `wct_id`, d'un `devis_id: 42` ou d'une liste.
Une relation de portée **présente** mais malformée (`lead_id` d'un WCT ou d'un fait de l'amont,
`wct_id` d'une variance ou d'une rentabilité) est refusée pour la même raison. Une relation
**absente** reste acceptée : des maillons historiques incomplets existent réellement (le test WCT
en fige un : `wct_id` + `duree_reelle_minutes`, sans `lead_id`) et refuser tout le registre pour
eux serait abusif. Un tel maillon n'est alors rattaché à aucune affaire, et la batterie n'invente
jamais son affaire.

Deux maillons typés `m2.client_associe` et `m1.lead_qualifie` ont une clé publique qui est une
**affaire**, pas un identifiant technique : M1 ne publie qu'un lead (`affaire.est_lead`), tandis
que M2 peut ouvrir l'opportunité `<lead>~opp~<wct_id>` (`affaire.valide`, jusqu'à 197 caractères).
Le tilde n'est **pas** élargi aux devis, aux WCT, aux variances, aux rentabilités ni aux `fait_id`.

Un maillon valide hors du périmètre de la batterie (autre type d'entrée, événement du bus non
modélisé, compagnon financier d'un devis) est accepté et non classifié, pour ne pas confondre
« hors périmètre » et « malformé ». La validation de lecture est ciblée : elle ne vérifie ni la
provenance, ni la chaîne de hash, ni l'appartenance à un registre précis, ni l'ACL. La batterie ne
lit aucun stockage et ne certifie ni l'ACL ni la présence réelle des sources.

Les sous-objets `Mapping` non-`dict` du corpus (`MappingProxyType`, `UserDict`) sont normalisés en
`dict` **avant** `deepcopy` et avant l'empreinte. Une empreinte SHA-256 canonique ne dépend donc
pas de l'ordre d'insertion des clés et n'invente aucune représentation par `default=str` ; une
valeur non sérialisable en JSON (dont `NaN`/`Infinity`) est un refus typé, pas une chaîne
fabriquée.

`documents_disponibles` est un **inventaire explicite** : la liste des identifiants réellement
présents dans le magasin de sources. `None` (le défaut) signifie « inventaire non fourni », jamais
« tout le corpus est présent » : la couverture des sources est alors `evaluable: false` avec
`raison: AUCUN_INVENTAIRE_SOURCES`, et aucune source n'est déclarée présente ou absente. Une liste
vide est un **zéro connu** (`0/N`) ; une liste complète est un **100 % connu**. Le rapport affiche
`mode_sources: inventaire_explicite` ou `mode_sources: inventaire_absent`. Aucun mode
« corpus-inline » implicite n'existe : les documents déclarés dans le corpus ne sont jamais
présumés présents dans le magasin.

Une question est **non évaluable** quand elle ne déclare aucun fait attendu
(`AUCUN_FAIT_ATTENDU`) ou quand un fait attendu n'est sourcé que par un document du domaine
`developpement` (`SOURCE_HORS_DOMAINE`). Elle n'entre alors dans aucun dénominateur : aucun zéro
n'est inventé. Le rapport nomme chaque question non évaluable avec sa raison, et son entrée
`par_question` conserve ses faits manquants, ses sources absentes et ses trois mesures non
évaluables. Les listes globales `manquants` et `sources_absentes` restent au grain des
dénominateurs : elles ne listent **que** les questions évaluables, pour ne pas réclamer un fait
ou un document du domaine `developpement` dans un bilan qui l'exclut. Les `fuites`, elles, restent
un signal par question, y compris pour une question non évaluable : une source de développement
retournée est signalée, mais elle ne compte dans aucun dénominateur.

Le rapport contient les comptes, les identifiants des faits manquants et des sources absentes, les
fuites (fait interdit retourné, ou fait retourné dont une source est hors du domaine des affaires),
la liste par question et une empreinte SHA-256 du corpus. Il ne contient **jamais** le texte d'un
document. Les bornes (200 documents, 500 faits, 100 questions, 10 sources par fait, textes bornés)
sont des limites de sécurité, pas des objectifs de qualité.

## 4. Suppression d'un fait, source absente, document interdit

- **Suppression d'un fait** : le fait n'est plus dans le registre. Le rappel baisse, le fait est
  nommé dans `manquants`, et la question concernée dit `trouves: []`. Si le fait disparu est un WCT,
  la variance et la rentabilité qui ne portent pas de `lead_id` ne sont plus rattachables à
  l'affaire : elles manquent aussi, ce qui est le comportement réel de `classification.py`.
- **Source absente** : un inventaire **explicite** (`documents_disponibles`) ne contient pas un
  document déclaré. Le fait peut rester retrouvé (le rappel ne baisse pas), mais la couverture des
  sources baisse et `sources_absentes` nomme le couple fait/source. Une source absente n'est pas un
  fait oublié.
- **Inventaire absent** : `documents_disponibles=None`. La couverture des sources est non évaluable
  (`AUCUN_INVENTAIRE_SOURCES`) ; `sources_presentes` et `sources_absentes` restent vides, car ni la
  présence ni l'absence ne sont prouvées. Le rappel et la précision, qui ne dépendent pas du
  magasin, restent calculés.
- **Document interdit** : un fait attendu sourcé d'un document `developpement` rend la question non
  évaluable ; un fait retourné dans la portée dont une source est `developpement` est une fuite,
  comptée au dénominateur de la précision et jamais au numérateur. Les deux mémoires ne sont pas
  mêlées, et le texte du document n'est jamais recopié.

## 5. Preuves exécutées

- `departments/m10-memoire/tests/test_non_oubli.py` : **27 tests**, dont le scénario de bout en bout
  avec les vrais outils `amont.memoriser`, `wct.memoriser_wct`, `variance.memoriser_variance` et
  `rentabilite.memoriser_rentabilite` dans des registres réels en mémoire ; mémoire intacte à
  100 %, suppression d'un WCT, source absente, inventaire absent, inventaire vide, inventaire
  complet, question sans fait, document de développement, fuite d'un fait interdit, fuite de texte,
  zéros, bornes exactes, idempotence et ordre du registre.
- `departments/m10-memoire/tests/test_non_oubli_correction.py` : **19 tests** de correction (R2 :
  conteneurs mapping, maillons non-mapping, `type_entree` absent/inconnu, mapping d'inventaire
  refusés ; maillons valides hors périmètre acceptés ; `None` non évaluable vs `[]` = 0/N), plus
  l'illustration R1 de deux questions partageant un fait et une source et la précision par
  occurrence.
- `departments/m10-memoire/tests/test_non_oubli_correction2.py` : **30 tests** du second passage
  (DF1 : clé publique absente, mal typée ou non hashable, relations présentes malformées, forme
  historique incomplète du WCT acceptée mais non attribuée, événements inconnus et documents
  historiques acceptés ; DF2 : listes globales restreintes aux questions évaluables, raison
  `AUCUN_FAIT_EVALUABLE`, informations conservées par question ; DF3 : `Mapping` non-`dict`
  normalisés, empreinte canonique, `NaN` refusé ; DF4 : `bytearray`/`memoryview` refusés ;
  DF5 : opportunité M2 jusqu'à 197 caractères retrouvée, tilde toujours refusé ailleurs). La
  première version du fichier (28 tests) donnait **21 rouges et 7 verts** avant le code ; deux
  tests supplémentaires, ajoutés pour tuer deux mutants survivants, visent la relation `lead_id`
  d'un devis et le refus de `NaN`.
- **Mutation** : `mutkit.py sweep` sur `batterie.py`, avec bytecode désactivé et cache supprimé,
  **128 mutants / 128 tués, 0 survivant**. Les constantes de bornes, les branches non évaluables,
  l'inventaire absent, les mesures vides, l'empreinte canonique, la validation des événements
  reconnus, les relations, les sources et les fuites sont couvertes.
- **Département** : suite complète `departments/m10-memoire/tests` verte, **1836 tests**.
- **Intégration** : `tests/test_routines_m10_e2e.py`, `tests/test_cascade_amont_m10.py` et
  `tests/test_m8_memoire_m10.py` verts, **25 tests** ; `tests/test_coherence_documentaire.py` et
  `tests/test_fichiers.py` verts, **76 tests**.
- **Ruff et manifestes** : `./ruff.sh` et `./verif.sh` verts.

## 6. Limites, dites sans euphémisme

- La batterie ne couvre que les **faits d'événements du bus** (amont, WCT, variance, rentabilité).
  Les décisions, les leçons, les documents métier, le modèle de soi et les faits analytiques ou
  stratégiques ne sont pas encore des faits attendus ici. Le registre Affaires est accepté et son
  nombre de maillons est reporté (`nb_maillons_affaires`), mais aucun fait durable `fait_consolide`
  n'est encore attendu par cette tranche.
- Le corpus est **écrit par un seul auteur** : biais de rédaction non mesuré. Un second rédacteur
  reste nécessaire avant de lire ces scores comme autre chose qu'une mesure interne.
- Ce n'est **pas** une mesure de la qualité de réponse d'un agent, ni un rappel général de la
  mémoire, ni une preuve d'absence d'oubli exhaustif. C'est la présence, dans le registre
  Événements, des faits qu'une batterie fictive déclare attendus.
- **Aucun objectif, seuil ou valeur d'affaires** n'est fixé par ce chantier. Une baisse du rappel
  est un signal à lire, jamais une note de conformité.
- La batterie n'est **pas branchée** au rapport hebdomadaire ni à un outil MCP : elle vit dans
  `batterie.py` et ses tests. Son branchement (qui fournit le corpus en production, à quelle
  cadence, avec quel magasin de sources) est une décision ultérieure, non prise ici.
- L'**inventaire du magasin** reste fourni par l'appelant. Sans lui, la couverture des sources est
  dite non évaluable, jamais présumée à 100 % ; la présence réelle des documents n'est pas lue par
  ce module, qui ne touche à aucun stockage.
- **Aucun test PostgreSQL, mobile, navigateur ou modèle réel ; aucune ACL ni aucun stockage réel
  n'est certifié.** Le module est pur, ne lit ni n'écrit aucun stockage ; les maillons, l'inventaire
  des sources et le corpus sont fournis par l'appelant. Une source « disponible » est une entrée
  d'inventaire, pas une preuve d'accès ni de présence physique.
- **La validation de lecture n'est pas une preuve de provenance.** Elle ne vérifie ni la chaîne de
  hash (`registre.valider_chaine`), ni l'`horodatage`, ni l'appartenance à un registre précis, ni
  l'ACL. Elle refuse seulement les formes qui empêchent de distinguer un fait d'une absence de
  fait : conteneur, maillon, `type_entree`, clé publique d'un événement reconnu et relations
  présentes. Un maillon valide d'un autre type connu reste accepté et non classifié.
- **Maillon historique incomplet.** Une relation de portée absente (`lead_id` d'un ancien WCT, par
  exemple) est acceptée pour ne pas rejeter tout le registre ; ce maillon n'est rattaché à aucune
  affaire et peut donc manquer au rappel. La batterie ne devine pas son affaire : c'est une limite
  de la donnée historique, pas une couverture silencieuse. Un maillon reconnu dont la **clé
  publique** manque est, lui, refusé.
- **Listes globales et questions non évaluables.** `manquants` et `sources_absentes` globaux ne
  listent que les questions évaluables, au grain des dénominateurs. Une question non évaluable
  conserve ses faits manquants, ses sources absentes et sa raison dans `par_question` ; elle ne
  pollue pas le bilan global. `fuites` reste un signal par question, y compris non évaluable.
- Aucune donnée réelle. Le banc ne déclenche aucun service extérieur.

## 7. Décisions pour Nathan

Aucune n'est nécessaire pour cette tranche : elle n'ajoute ni droit, ni seuil, ni valeur d'affaires.
Deux questions restent ouvertes pour la suite, sans réponse inventée :

1. Faut-il brancher cette batterie au rapport hebdomadaire, et qui fournit alors le corpus et le
   magasin de sources ? La tranche actuelle ne le fait pas.
2. Qui rédige le second corpus indépendant ? Sans lui, le biais d'un auteur unique reste.

## Sources

`docs/reprise/PROMPTS-NATHAN-ANCIENS/ANALYSE-M10.md` §4 (M10-05), `M10-MEMOIRE.md` (audit
hebdomadaire et scores), `DEFINITION-PRODUIT.md` §7 M10, `docs/architecture/PLANIFICATION.md` §10
(audit existant), ADR-0012 (séparation des deux mémoires).
