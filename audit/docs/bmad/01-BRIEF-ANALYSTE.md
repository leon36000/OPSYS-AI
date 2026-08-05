# BRIEF ANALYSTE — AUDIT-000 : audit exhaustif prouvé du dépôt OPSYS-AI

Premier audit transversal du dépôt. Commit gelé : **`f4707977526dbdbe4df2d1077a37c58d875b0b28`**,
arbre propre, trois gates déterministes VERTS au départ (`structure_lint`, `statut_lint`,
`ledger_append verify`).

## 0. POURQUOI MAINTENANT

La vague 1 des dix modules est close (décision `SQUELETTE-VAGUE-1-COMPLETE` au registre). État
mesuré :

| Grandeur | Mesure | Commande |
|---|---|---|
| Fichiers suivis par git | **1 278** | `git ls-files \| wc -l` |
| Commits · merges | 563 · **168** | `git log --merges \| wc -l` |
| Dossiers de revue · verdicts scellés | 199 · **644** | `find reviews -name '*.verdict.json' \| wc -l` |
| Tests dans les modules | **2 840** | `pytest "Modules M/<M>/tests" -q --co` par module |
| Statut des modules | **10 × PARTIAL**, 0 `DONE_VERIFIED` | `registries/modules.yaml` |
| Registres | 28 décisions · 49 preuves · 24 exécutions | `ledger_append.py verify` |

**Aucun audit transversal n'a jamais été conduit.** Le seul précédent proche, `reviews/cloture-
squelette/`, est une revue de clôture portant sur un pack de synthèse — elle n'a examiné ni le
code des dix modules, ni les instruments de preuve, ni la conformité au plan original.

Trois explorations en lecture seule ont précédé ce brief et ont trouvé des défauts réels. L'audit
n'est donc pas une formalité de gouvernance : il y a matière.

## 1. BESOIN

Nathan demande de savoir **où en est réellement le projet**, dans ses moindres détails : ce qui a
été fait depuis le début, si le projet a dévié du plan original, et toute incohérence, tout bug,
toute faille, toute erreur de code, tout goulot d'étranglement, tout problème d'optimisation et
tout problème de sécurité.

L'enjeu n'est pas la conformité cérémonielle. Il est qu'après 168 PR fusionnées et 644 verdicts
scellés, **personne n'a vérifié les vérificateurs**. Or trois mesures prises pendant l'exploration
suggèrent que certains instruments de preuve rendent des verts qui ne prouvent rien (§4). Si c'est
confirmé, la valeur probante de tout ce qui a été « prouvé » jusqu'ici doit être réévaluée — c'est
la raison d'être de cet audit, et ce qui commande son ordre d'exécution.

## 2. PÉRIMÈTRE

### 2.1 Dans le périmètre — le dépôt OPSYS-AI, intégralement

Les **1 278 fichiers suivis par git**, gelés dans `audit/MANIFESTE.sha256` (sha256 par fichier,
empreinte du manifeste : `8f3a91cf9009870b7aa24b0843ac6b68035bd1c5a1af5ff151ecaf5b50aa713c`).
Répartition : `reviews/` 688 · `Modules M/` 438 · `registries/` 34 · `docs/` 24 · `core/` 17 ·
`stories/` 16 · `surfaces/` 11 · `scripts/` 9 · `tests/` 8 · `.github/` 4 · racine 20 · divers.

**Aucun fichier suivi n'échappe à l'audit** — c'est vérifié par bijection, pas promis (CA-AUD-01).

### 2.2 Hors périmètre, nommé

- **`~/proof-method`** — dépôt distinct. Il héberge pourtant `civ_review.py`, `crew_dispatch.py`,
  `tally_reviews.py`, `sentinelle.py` et les hooks git, c'est-à-dire l'essentiel de la chaîne de
  preuve réellement utilisée. L'audit ne peut donc pas garantir l'état de ces outils : **c'est en
  soi un constat de reproductibilité**, à consigner comme tel, pas à contourner.
- **`.claude/worktrees/`** — arbres de travail, non suivis par git, structure divergente de `main`.
- **Le PDF du plan maître** — c'est la SOURCE du référentiel, donc l'étalon, pas l'objet mesuré.

### 2.3 Non-buts explicites

**L'audit ne corrige rien.** Aucune modification du code produit dans une branche d'audit. Raison
technique, pas de principe : un constat n'existe que par son témoin RED rejouable **sur le commit
gelé** ; si l'audit corrigeait, le témoin passerait au vert et la preuve du constat s'évaporerait.
Les corrections seront des stories de remédiation séparées, pipeline PROOF normal.

L'audit ne prétend pas non plus prouver qu'aucun défaut n'existe (§7).

## 3. RÉFÉRENTIEL — ce contre quoi on mesure

Sources de vérité, par ordre d'autorité :

1. **`docs/GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf`** (28 p.) — **91 identifiants** extraits
   et vérifiés : D-001..D-045 (45), R-001..R-033 (33), REG-01..REG-13 (13), plus les fiches M1..M10
   et la Phase 0 P0-1..P0-10. Extraction `pdftotext -layout` prouvée reproductible.
2. **`docs/decisions/ADR-0001/0002/0003`** — ADR-0003 porte la ratification T3 de Nathan
   (Q1..Q9), dont l'ordre des modules M7→M1→M2→M4→M3→M6→M8→M5→M9 puis M10.
3. **`PACK_CONSENSUS_GRS_v2.md`** — pack de la Phase C.
4. **`docs/canon/REGLES.md`**, **`docs/canon/CHECKLIST-PROOF-STACK.md`** — état vivant déclaré.

Les décisions ratifiées T3 (D-008, D-009, D-038, D-039, D-040, D-041, D-042) ne se contestent pas :
elles se mesurent.

## 4. HYPOTHÈSES D'ENTRÉE — mesurées, à confirmer ou réfuter, jamais acquises

Ces neuf faits ont été mesurés pendant l'exploration. Ils sont déclarés ici comme **hypothèses**,
pas comme conclusions : chacun devra recevoir un témoin RED ou être réfuté par l'audit.

| # | Fait mesuré | Commande |
|---|---|---|
| H1 | `scripts/tally.py` retourne `INVALIDE : champ manquant 'reviewer'` sur un dossier de revue réel — les 2 schémas des 644 verdicts ne portent ni `reviewer` ni `vendor` | `python3 scripts/tally.py reviews/M1-S005 deepseek` |
| H2 | `registries/ledger/installations.jsonl` **n'existe pas**, et `verify` affiche `OK (0 entrees)` | `ls registries/ledger/` + `ledger_append.py verify` |
| H3 | `.github/workflows/ci.yml:47,68` — `continue-on-error: true` sur les jobs qui exécutent `authz`, le coffre à secrets, le MFA et le e2e | `grep -n continue-on-error .github/workflows/ci.yml` |
| H4 | `Modules M/M7-marketing/src/workflows/chantier_social.py:174-182` — `except NotAutorise` produit `statut: "SUCCES"` ; les deux autres `except` du fichier donnent `ECHEC` | lecture directe |
| H5 | Les 6 copies de `conformite.py` excluent silencieusement tout fichier illisible du contrôle (`except (OSError, UnicodeError, SyntaxError): continue`) | grep AST |
| H6 | `encoder_canonique` : 7 copies, **M2 rend un digest sha256**, les 6 autres une chaîne | index AST |
| H7 | D-010 exige 8 services transversaux dans le core ; `gate_engine`, `otel`, `langfuse`, `duckdb`, `presidio`, `pgbackrest`, `zitadel` = **0 fichier** | `git grep -lIE` par motif |
| H8 | P0-9 : entrée ledger avec `preuve = None`, story `DRAFT — à découper` | `registries/ledger/preuves.jsonl` |
| H9 | `ADR-0003` cite **D-047**, absent du PDF (qui s'arrête à D-045) ; R-034/035/036 sautés | comparaison ensembliste |

**H1, H2 et H3 commandent l'ordre de l'audit** : si un instrument de preuve rend un faux vert,
toute donnée qu'il a produite est suspecte. Les lots portant sur les instruments passent donc avant
les lots portant sur le code.

## 5. CONTRAINTES NON NÉGOCIABLES

### 5.1 Un constat n'existe que par son témoin

`audit/temoins/AUD-<id>/reproduction.py` doit sortir **≠ 0** sur le commit gelé, sortie capturée,
en nommant le défaut. Pas de témoin rouge ⇒ **pas de constat**, quelle que soit la prose. C'est
exactement le critère qui a fait basculer l'objection critique de M10-S005 : le témoin avait été
écrit et vérifié rouge **avant** toute modification du code.

### 5.2 Une zone déclarée propre doit prouver qu'elle aurait vu

« J'ai regardé, rien trouvé » est indistinguable d'une sonde cassée. Pour chaque cellule
(lot × classe) sans constat, une mutation injecte un défaut synthétique dans un fichier **réel**,
exige le rouge **avec le motif attendu**, restaure, et vérifie l'identité **sha256**. Le dépôt a
déjà l'outil et la leçon : `Modules M/M10-memoire/docs/bmad/mutation_gate.py` a révélé **deux
défauts réels** d'un gate qui était vert.

Deux pièges déjà payés par cette batterie, à reprendre : muter **toutes** les occurrences d'un
motif répété (sinon vert à juste titre) ; ne jamais laisser une sonde **se replier sur le document
entier** quand elle ne trouve pas sa cible (elle trouverait n'importe quoi dans la prose).

### 5.3 Aucun LLM n'écrit une sévérité

La sévérité est **calculée** par `audit/rubrique.py` depuis des entrées mesurables
(`frontiere_t3`, `gate_couvrant`, `rayon`, `contrat_gele`). `verif_audit.py` la **recalcule** et
rejette toute divergence. Contester une sévérité, c'est contester une entrée mesurable — donc on
remesure — ou la rubrique elle-même — donc on amende le cadrage.

### 5.4 L'audit ne rouvre pas les dossiers clos

Le dépôt documente plusieurs décisions mesurées : duplication de socle assumée
(`docs/incidents/sonar-duplication-patrons-socle.md` + `.sonarcloud.properties`), `except`
légitimes (`except-silencieux-122.md`), identité de paquet (`identite-paquet-par-module.md`), et
trois briques D-042 en `BLOCKED` **avec raison** — un état valide de la méthode, pas un écart.

Chaque dérogation est enregistrée dans `audit/ecarts-assumes.yaml` avec un document probant, une
**portée close** et une **limite opposable**. La limite fait le travail décisif : « on assume la
copie de socle » ne peut pas absoudre « M2 rend un digest quand les 6 autres rendent une chaîne ».

### 5.5 Frontières T3

Un constat T3 se prouve **jusqu'à la frontière et pas au-delà** : on montre l'exposition
(fichier:ligne, portée), jamais on n'exploite, on ne tourne pas une clé, on ne modifie pas la CI.
Si confirmer exigeait de franchir, le résultat est `BLOCKED:` **avec la commande exacte** que
l'humain aurait à lancer — jamais une supposition.

## 6. CE QUI PROTÈGE CONTRE L'AUTO-COMPLAISANCE

L'Orchestrateur a piloté les dix modules **et** pilote cet audit. L'invariant « ne se relit
jamais » exige un dispositif qui ne repose pas sur sa bonne foi :

1. **Il est instrumentiste, pas juge** — son livrable est une sonde ; le verdict est la sortie de
   la sonde, rejouable par quiconque.
2. **La batterie de mutation** rend l'omission bruyante — l'angle mort d'un auteur qui s'audite
   n'est pas le mensonge, c'est la sonde qui ne cherche pas au bon endroit.
3. **Le trio d'audit est indépendant de celui qui a approuvé le code.** Mesuré sur les 644
   verdicts : Gemini-3.1-Pro 163, Qwen3.7-Max 145, DeepSeek-V4-Pro 112 — ils ont signé la
   quasi-totalité des 168 PR. Taux de rejet : DeepSeek **5,4 %** contre 19 % (Nemotron), 23 %
   (Gemini), 27 % (Qwen), **47 %** (MiniMax-M3). Les reprendre reviendrait à leur faire réviser
   leurs propres approbations.
4. **Le round d'hypothèses adverses** (étape 3) : le trio reçoit le périmètre **sans aucun
   résultat** et désigne où chercher. L'audité ne choisit plus ce qu'on regarde.
5. **Les sondes des axes à forte exposition (A3 écart au plan, A4 défauts de code) sont
   dispatchées au crew**, vendor ≠ anthropic.

**Résiduel assumé** : l'Orchestrateur choisit le découpage en axes. La bijection manifeste↔lots
garantit qu'aucun *fichier* n'échappe — pas qu'aucune *question* n'échappe. Le round adverse est
le contre-feu, et il reste imparfait. À inscrire au registre comme risque du protocole.

## 7. CE QUE L'AUDIT NE PRÉTENDRA PAS ÊTRE

Il ne prouvera **pas** qu'OPSYS-AI est exempt de défauts — cette proposition n'est pas
vérifiable. Il prouvera que, pour chaque zone du périmètre gelé et chaque classe de défaut
retenue, **une mesure a été exécutée et a démontré sa capacité à détecter**. Le rapport final
devra l'énoncer dans ces termes exacts.

## 8. CE QUE L'ANALYSTE PROPOSE ET QUE LE PM TRANCHERA

1. **Sept lots par AXE, pas par module.** Une sonde écrite une fois couvre les 135 fichiers source
   d'un coup ; un découpage par module coûterait ~336 appels de revue contre ~45 pour la même
   couverture. À confirmer, avec le chiffre.
2. **Combien de critères d'acceptation, et lesquels ?** Proposition : 12 CA vérifiables par script,
   chacun porté par exactement une story.
3. **Le seuil de taille de pack.** Mesuré : un pack de 84 k caractères a produit une sortie vide
   chez un reviewer sur trois (`reviews/m3-cadrage-A/ROTATION.md`). Proposition : plafond dur
   50 000 caractères, scission journalisée au-delà.
4. **Que fait-on des hypothèses H1..H9 ?** Proposition : chacune devient une cible de sonde
   obligatoire, au même titre que les hypothèses du round adverse — un fait mesuré par
   l'exploration n'est pas encore un constat prouvé.
5. **Où s'arrête un constat de sécurité ?** Proposition : exposition prouvée, jamais exploitation ;
   `BLOCKED:` avec la commande exacte si confirmer exige de franchir T3.
