# BRIEF ANALYSTE — MODULE M10 (MÉMOIRE LONG TERME & CONSCIENCE OPÉRATIONNELLE)

Module au statut PARTICULIER dans ADR-0003 Q2 : il ne figure pas dans la séquence
M7→M1→M2→M4→M3→M6→M8→M5→M9, mais la ratification précise « **M10 : shim en Phase 0 (déjà fait),
build complet APRÈS M8** ». M8, M5 et M9 étant livrés (EPICs J, K, L fermées), M10 est le module
dû. Fiche source : `GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf`, « Fiche M10 — Mémoire Long
Terme & Conscience Opérationnelle » ; `PACK_CONSENSUS_GRS_v2.md` ligne 47 ; D-014 (contrat gelé) ;
ADR-0003 Q6 (shim suffisant Phase 0, compléments au backlog).

## 0. DÉCISION DE FONDATION (avant ce brief, consultation `architecte`, citations VÉRIFIÉES)

M10 pose une question que les neuf modules précédents n'ont jamais posée : **la mémoire décrite
par la fiche source est-elle un module produit, ou la méthode de développement elle-même ?** Le
« shim M10 » de Phase 0 n'est en effet PAS du code produit — mesuré : `departments/m10-memoire/` ne
contient que des `.gitkeep`, `core/src/` n'a que `auth/`, `authz/`, `config/`, et la preuve P0-6
au registre décrit des hooks, des registres jsonl et la Sentinelle, tous hors paquet produit.

**Décision retenue : M10 v1 EST un paquet Python produit** (`m10_memoire`), et ce n'est PAS une
coquille cérémonielle — parce que **deux appelants l'attendent déjà dans du code mergé, testé et
en production** :

1. **`m4_field_ops/outbox.py:24`** (vérifié) :
   ```python
   # L'ordre exact des tuples ci-dessous fait partie du contrat Ratifié WorkCompletionTriggerV1.
   CONSOMMATEURS_CIBLES = ("M6", "M5", "M2", "M7", "M8", "M10")
   ```
   **M10 est un consommateur DÉCLARÉ du Work Completion Trigger, sans implémentation.** C'est
   exactement la situation qu'a connue M6 avant son cadrage, résolue par
   `m6_material_control/validation.py:17-19` (`CONSOMMATEUR_ATTENDU` + rejet nommé).

2. **`m9_strategic_intelligence/contrats.py`** : `memoire_m10` est l'une des 15 clés gelées d'un
   rapport stratégique, et la validation de son CONTENU est explicitement parquée en attente de
   ce module (`M9/docs/bmad/03-ARCHITECTURE.md` §7.2 : « Validation du CONTENU de `memoire_m10` |
   Dépend de la construction de M10 »).

**Correction factuelle majeure actée** (l'analyste avait supposé le contraire) : **D-014
(PREFLIGHT 16 étapes / POSTFLIGHT) est déclaré « loi du harnais » et n'est implémenté NULLE
PART** — mesuré : zéro occurrence de `preflight`/`postflight` dans `~/proof-method/` (0 fichier),
zéro dans les scripts du dépôt. C'est une **loi sans exécutant**. Le cadrage doit le reconnaître
explicitement plutôt que de prétendre l'implémenter (même discipline que DA-M9-02, où l'absence
d'énuméré a été documentée au lieu d'être fabriquée) : M10 v1 code le **prédicat calculable** et
la **trace du refus** ; l'APPLICATION (interrompre un agent) est un hook de méthode, story GATED
nommée, hors périmètre d'un paquet produit.

## 1. BESOIN MÉTIER

Nathan a besoin que rien de ce qui peut influencer une décision future ne se perde, et que cette
mémoire soit **vérifiable** plutôt que déclarative. Concrètement, en v1 : que le Work Completion
Trigger de M4 trouve enfin son consommateur M10 (aujourd'hui déclaré et manquant), que toute
décision porte sa raison et son statut de façon append-only, que rien ne soit jamais écrasé
silencieusement, et qu'un rapport stratégique M9 puisse enfin référencer une mémorisation réelle
plutôt qu'un champ vide.

Le risque nommé par la fiche source : une mémoire qui accumule aveuglément est aussi inutile
qu'une mémoire vide — d'où la cinquième règle (« la mémoire est révisable »). Mais réviser ne
veut PAS dire fusionner : le dépôt a déjà tranché ce point (§2.6).

M10 v1 n'est PAS un RAG, ne calcule aucun embedding, n'appelle aucun LLM, et ne « comprend » rien :
c'est la couche qui rend le non-oubli **structurellement prouvable**.

## 2. CONTRAINTES NON NÉGOCIABLES

### 2.1 Rien n'est écrasé sans mémoire — append-only + dérivation pure

Règle 3 de la fiche source. Forme codable mesurée dans le dépôt :
`m9_strategic_intelligence/etat_consolide.py:14` — `faits_par_module[module_source] = maillon` :
l'écrasement n'a lieu QUE dans la vue dérivée, jamais dans la chaîne. Le « rollback » de la fiche
devient **reconstruire l'état à l'index N**, jamais « restaurer un backup ». Corollaire
structurel : aucune méthode `modifier`/`supprimer` sur le registre — contrôlable statiquement, le
dépôt sait le faire (`m4_field_ops/outbox.py`, `garde_ecriture_unique`).

### 2.2 Deux mondes séparés par permissions = DEUX REGISTRES, jamais un champ

Forge Memory (l'usine : code, agents, décisions techniques, infra) et GRS Business Memory
(clients, procédures, prix, chantiers). **Deux registres distincts**, aucune fonction n'acceptant
les deux en argument. Un *champ* `permission` sur un maillon serait la mauvaise réponse : dans un
registre append-only, un maillon mal classé est **indélébile** — raisonnement déjà tenu dans
`m2_revenue_crm/frontieres.py:8-11` (« un faux négatif indélébile »).

### 2.3 M10 v1 ne consomme PAS `core/src/authz/` — mesure, pas dogme

Mesuré : **aucun module du dépôt n'importe `core`** (`grep -rE "^\s*(from|import)\s+core"` sur
`Modules M/` → 0). Le précédent est déjà écrit et sourcé dans `M5/docs/bmad/01-BRIEF-ANALYSTE.md`
(le moteur `DomainAuthz` existe, aucun module ne l'importe, la migration vers un Approval Engine
central est un ADR distinct et futur).

**Risque concret mesuré, qui tranche la question** : `.github/workflows/ci.yml` — le job `e2e`
porte `continue-on-error: true`, et c'est CE job qui exécute `pytest "core/src/authz/tests"`. Les
tests d'`authz` **ne sont donc pas bloquants**, alors que les tests de module le sont (job
`gates`). Adosser la frontière la plus sensible de M10 à `authz` ferait reposer une garantie de
confidentialité sur une CI qui peut virer au rouge sans bloquer un merge. **NO-GO en v1.**

Le patron du dépôt pour la visibilité est « **l'autorisation est FOURNIE par l'appelant** » :
`m8_analytics/rapports.py` filtre sur une liste blanche passée en argument, le module ne décide
jamais. M10 v1 applique le même patron.

### 2.4 Le WCT ne se recalcule jamais — le consommateur VÉRIFIE, il ne re-signe pas

Patron mesuré `m6_material_control/validation.py:4-19` : `valider_wct` contrôle les clés exactes
(ni plus ni moins) et la présence de son propre identifiant dans `consommateurs_cibles`, avec un
verdict nommé distinct par catégorie. La garde anti-recalcul de hash (`m6/conformite.py`,
`verifier_non_recalcul_hash_wct`) empêche un consommateur de reforger la preuve qu'il consomme.
M10 copie-adapte ce patron, en substituant `"M6"` par `"M10"`.

### 2.5 Toute décision a une raison — énuméré fermé AVEC échappatoire D-032

Règle 4 de la fiche source : statut `proposee`/`validee`/`remplacee`/`annulee`. Contrairement à
M9 (qui n'avait aucun énuméré de domaine), **M10 en a de vrais** : l'échappatoire D-032 est donc
OBLIGATOIRE ici (patron `m5_financecore/contrats.py`, garde `m8_analytics/conformite.py`). Le
gate de cohérence du cadrage doit l'EXIGER — et surtout **ne pas copier
`M9/docs/bmad/verif_coherence.py`**, dont le contrôle `check_absence_enum_documentee` exige
l'ABSENCE d'énuméré : appliqué à M10, ce serait un faux négatif garanti, symétrique exact du
risque nommé en `M9/03-ARCHITECTURE.md` §8.3.

### 2.6 Réviser n'est JAMAIS fusionner — le piège central de ce module

Règle 5 (« fusion des doublons, vérités obsolètes marquées »). Le dépôt a tranché l'inverse,
explicitement, dans du code mergé : `m2_revenue_crm/doublons.py:1-8` —

> « Ce module ne regroupe jamais deux leads : il détecte les ressemblances, inscrit un
> signalement dans le registre append-only hash-chaîné, puis consigne l'arbitrage humain. […] les
> seuls états d'arbitrage existants sont `en_attente` et `distincts_confirmes`. »

Une fusion irréversible dans un registre append-only est structurellement **pire** que le doublon
qu'elle prétend corriger. M10 v1 : **détecter, signaler, consigner l'arbitrage — jamais
fusionner**. Idem pour « vérités obsolètes marquées » : marquer = écrire un NOUVEAU maillon,
jamais muter l'ancien.

### 2.7 v1 = stdlib pur ; vecteur/graphe inféré/LLM = GATED tracé

Patron appliqué à M8 (DuckDB) et M9 (Council d'agents). Mesuré : `registries/frameworks.yaml`
contient `frameworks: []` et `scripts/structure_lint.py` exige la bijection registre↔disque avec
un `FRAMEWORK.md` par framework — **toute dépendance vectorielle ferait rougir le build**. Vector
memory, context injector, code memory et evaluation harness sont GATED, nommés en roadmap, jamais
approximés par une prose qui se ferait passer pour une implémentation.

## 3. FRONTIÈRES DU MODULE

### 3.1 Ce que M10 fait (v1)

- Valide et consomme le Work Completion Trigger émis par M4 (le consommateur manquant, §2.4).
- Tient un registre d'événements append-only hash-chaîné (Forge et Business, deux registres).
- Tient un registre de décisions avec raison obligatoire et statut à énuméré fermé (§2.5).
- Détecte et signale les doublons de mémoire, consigne l'arbitrage — sans jamais fusionner (§2.6).
- Marque une vérité comme obsolète par un NOUVEAU maillon, jamais par mutation.
- Calcule le prédicat « contexte suffisant » et TRACE le refus — sans interrompre personne (§0).
- Produit la référence `memoire_m10` que M9 pourra enfin valider.
- Applique une conformité statique transversale (anti-invention, anti-import, déterminisme,
  absence de méthode de mutation sur les registres).

### 3.2 Ce que M10 ne fait JAMAIS (v1)

- Ne FUSIONNE jamais deux souvenirs, ne supprime jamais un maillon, ne mute jamais un maillon
  existant.
- N'INTERROMPT jamais un agent : il rend le refus calculable et tracé, l'application est un hook
  (GATED).
- N'appelle JAMAIS un LLM, ne calcule aucun embedding, n'infère aucune arête de graphe.
- N'importe aucun paquet `mX_*` de domaine, ni `core/` (§2.3).
- Ne purge jamais : la purge Loi 25 est une suppression définitive = frontière T3 Nathan.
- Ne recalcule jamais le hash d'un WCT qu'il consomme (§2.4).
- Ne décide jamais seul de la visibilité Forge/Business : l'appelant fournit le registre cible.

## 4. CONTRAT D'ENTRÉE — CE QUI EST MESURÉ, PAS SUPPOSÉ

- **Work Completion Trigger** : forme gelée par `m4_field_ops/outbox.py` (12 champs, dont
  `consommateurs_cibles` contenant `"M10"`). M10 le REÇOIT de l'appelant, ne le construit jamais.
- **Événement de mémoire** : fourni par l'appelant, avec les champs de la règle 1 (trace complète).
- **Décision** : fournie par l'appelant, avec sa raison et son statut.
- **Horodatage** : fourni par l'appelant à chaque écriture — M10 n'a pas d'horloge (patron
  transversal des 9 modules).

## 5. CONTRAT DE SORTIE — ESQUISSE (le PRD et l'architecture trancheront la forme gelée)

Un maillon de mémoire porte son `ligne_id`, son `type_entree`, son contenu et son chaînage. Une
référence `memoire_m10` (celle que M9 attend) désigne de façon vérifiable un ou plusieurs maillons
réellement écrits — jamais un texte libre non vérifiable.

## 6. MODE OMBRE ET MODE GATED

### 6.1 En périmètre v1 (mode ombre, prouvable en CI Python, stdlib pur)

Event log immuable · structured memory · decision registry · workflow checkpoints (dérivation
pure) · prompt & plan registry (stockage + empreinte, jamais jugement) · Forge/Business memory
(deux registres) · retrieval router RESTREINT (routage par prédicat déclaré) · knowledge graph
PARTIEL (arêtes explicites fournies par l'appelant, fermeture transitive déterministe) · memory
auditor (validation de chaîne + contradiction sans cause) · governance PARTIELLE (classe de
rétention obligatoire) · self model (état dérivé du registre).

### 6.2 Repoussé GATED/T3

- **Vector memory** : exige une base vectorielle et des embeddings LLM — build rouge garanti
  (§2.7).
- **Arêtes de graphe INFÉRÉES** : inférence = jugement, hors périmètre déterministe.
- **Context injector** : produit un prompt destiné à un LLM.
- **Code memory** : aucun appelant produit ; lire l'arbre git n'est pas reproductible en CI.
- **Evaluation harness** : hors stdlib.
- **PREFLIGHT/POSTFLIGHT appliqués** (D-014) : le prédicat est v1, l'APPLICATION est un hook de
  méthode — hors dépôt produit, story GATED nommée.
- **Purge Loi 25** : suppression définitive = T3 Nathan.
- **Fusion réelle de doublons** : écartée par conception, pas reportée (§2.6).

## 7. CE QUE L'ANALYSTE PROPOSE ET QUE LE PM TRANCHERA

### 7.1 Quel patron de registre — générique M5 ou spécifique M8 ?

Proposition : **patron générique M5** (`type_entree`/`ligne_id`/`precedent_ligne_id`), car M10 a
au moins TROIS familles de maillons (événement, décision, signalement de révision), là où M8/M9
n'en avaient qu'une. Le critère est écrit dans `M9/03-ARCHITECTURE.md` §4 (DA-M9-01). À trancher
explicitement, sinon un reviewer appliquera DA-M9-01 par mimétisme.

### 7.2 Combien de registres exactement — deux, ou deux fois trois ?

Proposition : deux instances du MÊME type de registre (`registre_forge`, `registre_business`),
les trois familles de maillons cohabitant dans chacune via `type_entree`. À confirmer.

### 7.3 Le prédicat « contexte suffisant » : quels champs le composent ?

Proposition : un dossier de contexte est suffisant s'il porte les éléments de la règle 1 (event,
résumé, preuves, impact, prochaine action) et référence au moins une décision. À trancher — la
liste doit être fermée et testable, jamais « au jugé ».

### 7.4 La référence `memoire_m10` : quelle forme exacte ?

Proposition : un dict portant le `ligne_id` du maillon et l'empreinte de la chaîne au moment de
l'écriture, vérifiable par relecture. À geler, car M9 en dépend.

### 7.5 Que faire du fait que D-014 n'a aucun exécutant ?

Proposition : le documenter comme un écart RÉEL et nommé (pas un oubli du cadrage), avec une
story GATED explicite pour le hook. Alternative écartée : prétendre que M10 v1 « implémente la loi
du harnais » — ce serait exactement l'erreur que DA-M9-02 a évitée.
