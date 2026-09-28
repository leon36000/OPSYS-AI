# BRIEF ANALYSTE — MODULE M9 (STRATEGIC INTELLIGENCE)

Neuvième et DERNIER module de l'ordre ratifié ADR-0003 (M7→M1→M2→M4→M3→M6→M8→M5→**M9**). Fiche
source : `GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf`, « Fiche M9 — Strategic Intelligence OS »,
page 9-10 ; `PACK_CONSENSUS_GRS_v2.md`, ligne 46 ; frontières nettes inter-modules, page 9.

## 0. DÉCISION DE FONDATION (avant ce brief, consultation `architecte`, citations vérifiées)

M9 est fondamentalement différent des huit modules précédents : sa fiche source décrit un
« Council d'agents (CEO, COO, liaisons CFO/CMO, Sales, Ops, Risk, Data, Execution) orchestré par
un Strategic Supervisor déterministe » — un contenu délibératif qui, contrairement à TOUT ce qui
a été construit jusqu'ici (100% stdlib, zéro réseau, zéro LLM, zéro horloge), semble intrinsèquement
nécessiter de vrais appels LLM pour produire une analyse, un diagnostic, des recommandations.

**Décision retenue (architecte, citations vérifiées)** : le mot « déterministe » de la fiche
source s'applique à l'ORCHESTRATION (séquencement des agents, assemblage des traces, formule de
score, quorum, validation du schéma des sorties d'agents), PAS au raisonnement individuel des
agents (qui EST un appel LLM). **v1 = le HARNAIS déterministe uniquement** : Strategic Data
Fabric (agrégation pure de snapshots), Business State Graph (détection de contradictions),
validation structurelle des 15 éléments obligatoires, garde anti-invention. **Tout contenu
délibératif reste GATED** : le Council d'agents lui-même, les scénarios narratifs, les playbooks,
le Decision Intelligence Engine, l'Action Orchestrator, la stack LangGraph/Temporal/Langfuse/
Ragas/DeepEval réelle. v1 ne revendique AUCUNE « intelligence » — seulement structure, fraîcheur,
détection de contradiction, validation, points d'approbation.

**Correction factuelle actée** (l'analyste avait initialement supposé le contraire) :
`conformite.py` n'est PAS hérité automatiquement par tout module — mesuré : seuls M3/M5/M6/M8 le
portent ; M1/M2/M4/M7 ne l'ont pas. M9 doit le CONSTRUIRE explicitement, comme un choix délibéré
(cohérent avec le patron des modules les plus récents), pas une garantie acquise.

## 1. BESOIN MÉTIER

Nathan a besoin d'une couche qui consolide les faits déjà enregistrés par M1-M8 (et bientôt M5)
en un état d'entreprise unique, détecte quand deux sources se contredisent, et fait respecter
STRUCTURELLEMENT qu'aucune sortie stratégique ne puisse jamais omettre l'un des 15 éléments
obligatoires (état, diagnostic, preuves, hypothèses, incertitudes, scénarios, recommandations,
priorités, impacts, risques, actions, validation, tâches par département, suivi, mémoire M10) —
sans jamais fabriquer elle-même un chiffre, un revenu ou une capacité. Le risque nommé
explicitement par la fiche source : un « cerveau stratégique » qui invente une analyse plausible
mais fausse serait pire qu'une absence d'analyse.

M9 n'est PAS un chatbot stratégique et ne fait AUCUNE analyse en v1 : c'est la couche qui rend les
faits des huit modules précédents consolidés, cohérents (ou signale leur incohérence), et qui
REFUSE STRUCTURELLEMENT toute sortie stratégique incomplète — avant qu'un futur Council d'agents
(LLM, GATED) ne produise le contenu réel.

**Risque nommé et déjà mitigé par l'ordre de construction** : la fiche source dit elle-même « un
cerveau stratégique sans données réelles M1-M8 lirait du vide (même logique que R-009) ». M9 est
positionné en DERNIER dans l'ordre ratifié précisément parce que M1-M8 et M5 ont déjà chacun un
registre réel à consolider — le risque résiduel (encore peu d'historique sur certains modules
récents comme M5/M8) est traité par le patron fail-closed déjà mesuré (M8 :
`valeur: null, n: 0` plutôt qu'une valeur inventée), pas ignoré.

## 2. CONTRAINTES NON NÉGOCIABLES

### 2.1 Jamais de chiffre, revenu ou capacité inventés (règle d'or de la fiche source)

Identique en esprit à M8 (« le LLM ne calcule jamais un chiffre »), mais plus stricte encore :
toute valeur numérique visible dans l'état consolidé DOIT tracer un `snapshot_id`/`ligne_id`
source consommé — jamais une estimation, jamais une moyenne devinée, jamais une extrapolation
narrative. v1 ne calcule RIEN de nouveau : il cite ce que les modules sources ont déjà déclaré.

### 2.2 Les 15 éléments obligatoires sont un CONTRAT, pas de la prose

Mesuré et à répliquer : `contrats.CHAMPS_DEFINITION_METRIQUE` de M8 (7 champs texte, frozenset)
prouve qu'un contrat de sortie riche se valide structurellement, jamais en espérant qu'un texte
libre les contienne tous. Les 15 éléments (état, diagnostic, preuves, hypothèses, incertitudes,
scénarios, recommandations, priorités, impacts, risques, actions, validation,
`taches_par_departement`, suivi, `memoire_m10`) sont un `frozenset` de noms de champs ; un rapport
qui n'en contient pas EXACTEMENT 15 est rejeté par un verdict nommé — v1 valide la PRÉSENCE
structurelle, jamais la QUALITÉ du contenu de chaque champ (le contenu réel est un GATED futur).

### 2.3 Frontière nette : M9 interprète et arbitre, ne remplace ni ne court-circuite les départements

Citation directe de la fiche source (page 9) : « M5 = CFO financier ; M8 = métriques ; M10 =
mémoire ; M9 = interprétation, arbitrage, stratégie — au-dessus des départements sans les
remplacer ni les court-circuiter. » M9 ne modifie JAMAIS un registre d'un autre module ; il ne
consomme que des faits déjà déclarés.

### 2.4 Réutilisation du patron d'agrégation déjà mesuré, jamais réinventé, jamais importé

**Fait mesuré, pas supposé** (architecte) : `m8_analytics.registre.RegistreSnapshots` (registre
générique hash-chaîné indexé par `module_source`) et le contrat `CHAMPS_SNAPSHOT_MODULE`
(`module_source, horodatage, valeurs`) SONT déjà le patron d'agrégation multi-module dont M9 a
besoin pour sa Strategic Data Fabric. M9 ne peut PAS `import m8_analytics` (`#109`,
`verifier_aucun_import_domaine` de M8 l'interdirait explicitement) : M9 copie-adapte ce patron
localement, exactement comme chaque module précédent a copié-adapté `registre.py`/`encodage.py`
d'un voisin plutôt que de l'importer.

### 2.5 Fraîcheur déterministe, jamais une horloge interne

Patron déjà mesuré : `m8_analytics.semantique.deriver_metrique` calcule la fraîcheur depuis un
`horodatage_reference` INJECTÉ par l'appelant, jamais `datetime.now()`. M9 calque ce patron pour
toute notion de fraîcheur/péremption d'un fait consolidé.

### 2.6 Détection de contradictions = comparaison pure, jamais un jugement

v1 détecte une SEULE catégorie de contradiction, déterministe et sans ambiguïté : deux snapshots
du MÊME `module_source` portant le MÊME `horodatage` mais des `valeurs` différentes pour une même
clé (incohérence interne d'une source, pas encore une contradiction sémantique inter-modules — ex.
« M2 dit 10 conversions, M8 dit 8 » exigerait un mapping métier entre concepts de modules
différents, hors périmètre v1, proposé au PM en §7).

### 2.7 v1 = mode ombre stdlib-only ; LangGraph/Temporal/Council = décision tracée, jamais une substitution silencieuse

Patron déjà appliqué à M8 (DuckDB) et M5 (adapters réels) : v1 prouve la STRUCTURE et les contrats
gelés en stdlib pur. LangGraph/Temporal/Langfuse/Ragas/DeepEval et le contenu réel du Council
d'agents deviennent des stories GATED explicites et nommées en roadmap — jamais une prose générée
qui se ferait passer pour une analyse validée.

## 3. FRONTIÈRES DU MODULE

### 3.1 Ce que M9 fait (v1)

- Agrège des snapshots fournis par l'appelant (patron `SnapshotModule` réutilisé) en un état
  consolidé indexé par `module_source` — Business State Graph minimal.
- Détecte les contradictions internes déterministes (§2.6).
- Valide qu'un rapport stratégique contient EXACTEMENT les 15 éléments obligatoires — structure
  seulement, jamais le contenu.
- Calcule la fraîcheur de chaque fait consolidé depuis un horodatage de référence fourni.
- Applique une conformité statique transversale : aucun chiffre codé en dur, zéro réseau, zéro
  horloge interne, zéro aléa non ensemencé, aucun import de module de domaine.

### 3.2 Ce que M9 ne fait JAMAIS (v1)

- Ne produit AUCUN contenu délibératif (pas de diagnostic rédigé, pas de recommandation, pas de
  scénario narratif) — v1 valide la structure d'un rapport, il ne le RÉDIGE jamais.
- N'invoque JAMAIS un LLM (le Council d'agents est GATED, hors périmètre déterministe).
- N'écrit jamais dans le registre d'un autre module ; ne remplace ni ne court-circuite un
  département (§2.3).
- Ne construit pas le rythme exécutif (War Room quotidien, rapports hebdo/mensuels, board memo)
  — nécessite un ordonnanceur externe, hors périmètre stdlib pur (patron M8 : appel manuel prouve
  le contrat).
- Ne déclenche aucune action réelle ni notification Nathan — v1 ne produit qu'une structure de
  données validée, pas un effet de bord.
- Ne construit pas l'Approval Engine unifié (D-010, pas encore un service central du core, comme
  déjà noté pour M5) — v1 ne produit aucune action risquée à approuver.

## 4. CONTRAT D'ENTRÉE — CE QUI EST MESURÉ, PAS SUPPOSÉ

- **Snapshot d'un module source** : réutilise EXACTEMENT la forme `SnapshotModule` de M8
  (`module_source: str, horodatage: str, valeurs: dict`) — patron déjà prouvé, pas réinventé.
  Fourni par l'appelant à chaque agrégation (M9 ne connaît structurellement aucun module de
  domaine, comme M8).
- **Horodatage de référence** : fourni par l'appelant à chaque calcul de fraîcheur — M9 n'a pas
  d'horloge, patron `deriver_metrique`.

## 5. CONTRAT DE SORTIE — ESQUISSE (le PRD et l'architecture trancheront la forme gelée)

Un état consolidé porte au minimum : les derniers snapshots connus par `module_source`, la liste
des contradictions détectées (chacune nommant les deux snapshots en conflit, jamais une cause),
et la fraîcheur de chaque fait. Un rapport stratégique (structure seulement en v1) porte les 15
clés obligatoires, chacune `None`/vide tant qu'aucun Council (GATED) ne les remplit — v1 prouve
que la validation REJETTE une clé manquante, pas que le contenu est pertinent.

## 6. MODE OMBRE ET MODE GATED

### 6.1 En périmètre v1 (mode ombre, prouvable en CI Python, stdlib + PyYAML)

- Contrats gelés : `SnapshotModule` (réutilisé), 15 éléments obligatoires d'un rapport
  stratégique.
- Registre append-only hash-chaîné des snapshots consolidés (copie-adaptation).
- Business State Graph : agrégation pure + détection de contradictions internes déterministes.
- Validation structurelle d'un rapport stratégique (15/15 clés, rejet nommé sinon).
- Conformité statique transversale (anti-invention, anti-import de domaine, déterminisme).

### 6.2 Repoussé GATED/T3

- **Council d'agents réel** (CEO, COO, liaisons CFO/CMO, Sales, Ops, Risk, Data, Execution) :
  nécessite de vrais appels LLM, hors périmètre déterministe.
- **Strategic Supervisor (orchestration du Council)** : la MÉCANIQUE de séquencement pourrait
  être v1 si elle n'invoque aucun LLM réellement ; question ouverte pour le PM en §7.
- **Scénarios narratifs** (7j/30j/90j/6mois/12mois + stress tests), **playbooks** (croissance,
  crise, cashflow, saisonnier), **Decision Intelligence Engine**, **Action Orchestrator**.
- **LangGraph/Temporal/Langfuse/Ragas/DeepEval réels** : stack alignée au squelette mais hors
  stdlib, story GATED tracée.
- **Rythme exécutif** (War Room, rapports, board memo, briefing mobile) : nécessite un
  ordonnanceur, hors périmètre stdlib pur.
- **Notification Nathan sur risque critique** et **Approval Engine unifié réel** : infra/service
  central pas encore construits.
- **Détection de contradictions sémantiques inter-modules** (ex. mapper « leads convertis » M2 à
  une métrique M8 différente) : v1 ne détecte que les incohérences internes déterministes (§2.6).

## 7. CE QUE L'ANALYSTE PROPOSE ET QUE LE PM TRANCHERA

### 7.1 Le Supervisor (mécanique de séquencement) : v1 ou entièrement GATED ?

L'architecte distingue l'orchestration (déterministe) du raisonnement (LLM). Proposition : v1
construit une mécanique de séquencement MINIMALE (ex. valider qu'un ensemble de « contributions
d'agents » fourni par l'appelant respecte un schéma attendu et calculer un score/quorum pur sur
des valeurs déjà fournies) — SANS jamais invoquer un agent réel. Alternative plus prudente :
reporter même cette mécanique à une story GATED distincte, v1 se limitant à la Data Fabric +
validation des 15 éléments. À trancher explicitement, pas supposé.

### 7.2 Forme exacte de la détection de contradiction

Proposition (§2.6) : un seul cas déterministe en v1 (même `module_source` + même `horodatage`,
`valeurs` différentes). Une contradiction inter-modules nécessiterait un mapping sémantique
(métier) hors périmètre — à confirmer au PM comme hors v1, pas comblé silencieusement.

### 7.3 Faut-il un fichier déclaratif pour les 15 éléments, ou une constante `contrats.py` suffit ?

Proposition : une constante `CHAMPS_RAPPORT_STRATEGIQUE` (frozenset) dans `contrats.py`, comme
`CHAMPS_DEFINITION_METRIQUE` de M8 — pas un fichier YAML séparé (les 15 éléments sont fixes,
gelés par la fiche source, pas une déclaration par module comme les métriques M7).

### 7.4 Comment M9 obtient les snapshots des modules déjà livrés

Même réponse que pour M8/M5 (patron désormais établi 3 fois) : M9 ne doit PAS importer
`m1_front_office`...`m8_analytics`. M9 reçoit un snapshot déjà construit ; la construction à
partir du registre réel d'un module source est un service d'intégration distinct, hors périmètre
de M9 lui-même.

### 7.5 M10 (mémoire) n'existe pas encore — que fait le champ `memoire_m10` en v1 ?

La fiche source exige que chaque rapport référence sa propre mémorisation dans M10, qui n'est pas
encore construit (position tardive, comme M9). Proposition : le champ `memoire_m10` fait partie
du contrat structurel (présence obligatoire) mais sa VALEUR reste `None`/texte libre non validé
en v1 — la validation de son CONTENU (référence réelle à un événement M10) est un GATED futur,
dépendant de la construction de M10.
