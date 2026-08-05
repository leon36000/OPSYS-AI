# ARCHITECTURE — AUDIT-000 : audit exhaustif prouvé du dépôt OPSYS-AI

## 0. PRINCIPE FONDATEUR

Le dépôt juge par la mesure. Un audit qui **affirme** dans ce dépôt serait réfuté au premier
contre-exemple. L'audit est donc **un programme qui s'exécute**, et son rapport est **généré**
depuis des données, jamais rédigé.

Trois règles de la constitution du dépôt, transposées :

| Règle du dépôt | Transposition |
|---|---|
| DONE-avec-preuve **ou** BLOCKED-avec-raison | Chaque cellule finit sur un verdict **mesuré** ou sur `indetermine` **avec sa raison**. « Probablement conforme » n'existe pas |
| No-stub : un seul hit bloque | Aucune sonde ne peut retourner vide en silence — ce serait reproduire le défaut audité (H5) |
| L'Orchestrateur ne se relit jamais | Les sondes sont **elles-mêmes mutées** : on injecte le défaut connu, on exige le rouge |

## 1. ARBORESCENCE DU PAQUET `audit/`

Tout vit sous `audit/`. **Aucun fichier du produit n'est modifié** (CA-AUD-09).

| Fichier | Rôle | Lot |
|---|---|---|
| `MANIFESTE.sha256` | Périmètre GELÉ : 1 278 fichiers suivis + sha256 chacun | — (fait) |
| `contrats.py` | Schéma gelé du constat, trois énumérés fermés avec échappatoire D-032 | A1 |
| `rubrique.py` | Calcul **déterministe** de la sévérité depuis 4 entrées mesurées | A1 |
| `perimetre.py` | Bijection manifeste ↔ lots ; sort ≠ 0 sur tout orphelin ou double affectation | A1 |
| `ecarts-assumes.yaml` | Dérogations documentées : doc probant + portée CLOSE + limite opposable | A1 |
| `sondes/a1..a7.py` | Une sonde par lot — mesure et sort des faits, **ne classe jamais** | A1..A7 |
| `temoins/AUD-<id>/reproduction.py` | Témoin RED d'un constat — rc ≠ 0 sur le commit gelé | par constat |
| `temoins/CLEAN-<lot>-<classe>/mutation.py` | Preuve qu'une zone déclarée propre est mordante | par cellule vide |
| `constats/AUD-<id>.json` | Données, jamais de prose | par constat |
| `mutation_audit.py` | Batterie prouvant que les SONDES mordent | A1 |
| `verif_audit.py` | Gate de complétude — les 12 CA | A7 |
| `run_audit.sh` | Point d'entrée unique, rejoue tout de zéro | A7 |
| `FILE-T3.md` | Vue régénérée des constats T3 | A5 |
| `RAPPORT.md` | **GÉNÉRÉ** depuis `constats/` | A7 |
| `docs/bmad/verif_coherence.py` | Gate du cadrage (patron M10) | cadrage |
| `docs/bmad/mutation_gate.py` | Batterie prouvant que le gate du cadrage mord | cadrage |
| `tests/test_audit_structure.py` | Sentinelle de l'audit — exécutée par `run_audit.sh`, **hors CI** (DA-AUD-09) | cadrage |

## 2. SCHÉMAS DE DONNÉES

### 2.1 Le constat (`constats/AUD-<id>.json`)

```yaml
Constat:
  id · lot · classe · titre
  emplacement: list[str]        # "fichier:ligne", au moins un
  temoin: str                    # chemin du reproduction.py
  temoin_rc: int                 # != 0 EXIGÉ sur le commit gelé
  temoin_sortie_sha256: str
  entrees_rubrique:              # MESURÉES
    frontiere_t3 · gate_couvrant · rayon · contrat_gele
  severite: str                  # CALCULÉE, recalculée au gate
  statut · refutation · assume_ref
```

### 2.2 Énumérés fermés — trois, chacun avec échappatoire D-032

```python
SEVERITE       = ("critique", "majeure", "mineure", "indetermine")
CLASSE         = ("defaut-code", "ecart-plan", "faille-securite",
                  "goulot-performance", "incoherence-documentaire", "indetermine")
STATUT_CONSTAT = ("ouvert", "confirme", "refute", "arbitrage-humain", "indetermine")
```

`indetermine` est fourni **explicitement** par l'appelant et **force un arbitrage humain**. Une
valeur hors énuméré est un rejet nommé, jamais une coercition silencieuse (leçon M5-S001).

### 2.3 Matrice de complétude — 7 lots × 5 classes = 35 cellules

Chaque cellule est close par **soit** ≥ 1 constat avec témoin RED, **soit** ≥ 1 mutation prouvant
que la sonde mord sur cette classe. Aucune cellule vide. C'est la définition opérationnelle
d'« exhaustif », et elle est comptable.

## 3. DÉCISIONS D'ARCHITECTURE TRANCHÉES

### DA-AUD-01 — Lots par AXE, jamais par module

**Décision** : sept lots transversaux (A1..A7), pas soixante-dix lots module × axe.

**Justification** : une sonde écrite une fois s'applique aux 135 fichiers source d'un coup. Le
coût de revue est le facteur limitant : 7 × 3 × 1,6 ≈ **45 appels** contre 70 × 3 × 1,6 ≈ **336**
pour la même couverture — facteur ~7. Ce n'est pas une préférence esthétique : c'est ce qui rend
l'audit soutenable sans dégrader la rigueur.

### DA-AUD-02 — Le constat est une donnée, jamais un texte

**Décision** : schéma gelé dans `contrats.py` ; `RAPPORT.md` est **généré** depuis `constats/*.json`.

**Justification** : REG-12 (« généré bat maintenu »). Une prose saisie à la main peut affirmer ce
qu'aucune mesure ne soutient — c'est précisément ce que l'audit reproche au dépôt quand il le
trouve. Le rapport doit être reproductible bit-à-bit, hors horodatage.

### DA-AUD-03 — La sévérité est calculée, jamais votée

**Décision** : `rubrique.py` dérive la sévérité de quatre entrées mesurées ; `verif_audit.py` la
recalcule et rejette toute divergence (CA-AUD-04).

**Justification** : invariant « aucun LLM n'écrit un score ». Effet de bord recherché : **le
désaccord sur la gravité disparaît par construction** — contester revient soit à contester une
entrée mesurable (on remesure), soit à contester la rubrique (amendement de cadrage, nouveau
consensus). Il n'y a plus de place pour un débat d'opinion.

### DA-AUD-04 — L'audit ne corrige rien

**Décision** : séparation stricte constat / remédiation. Aucune modification du code produit dans
une branche d'audit.

**Justification** : un constat n'existe que par son témoin RED rejouable **sur le commit gelé**.
Corriger pendant l'audit ferait passer le témoin au vert et **détruirait la preuve du constat**.
Ce n'est pas de la prudence procédurale, c'est une nécessité logique.

### DA-AUD-05 — Zéro chemin absolu, zéro dépendance au répertoire courant

**Décision** : toute sonde et tout témoin déduisent leur base de `Path(__file__).resolve()`.

**Justification** : ADR-0003 (portabilité). Un script non rejouable ailleurs ne prouve rien. Leçon
déjà payée : le `mutation_gate.py` de M10 portait un chemin absolu, corrigé avant merge et vérifié
en le rejouant depuis un autre `cwd`.

### DA-AUD-06 — Sonde ≠ juge

**Décision** : une sonde **mesure et sort des faits**. Elle ne classe pas, ne qualifie pas, n'émet
aucune sévérité. La classification vient de `rubrique.py`, l'interprétation du trio.

**Justification** : sépare l'instrument du jugement. Une sonde qui classerait porterait le biais de
son auteur — lequel est l'audité.

### DA-AUD-07 — Aucun import du code audité

**Décision** : les sondes **lisent des fichiers** (AST, texte) ; elles n'importent jamais
`m1_front_office` & consorts.

**Justification** : un import créerait un couplage entre l'instrument et l'objet mesuré, et
exposerait l'audit aux effets de bord d'import (le dépôt a un précédent documenté : issue #109,
21 tests de M2 exerçaient le code de M1 via `sys.modules`). Corollaire : les sondes fonctionnent
même sur un fichier syntaxiquement invalide — ce qui est exactement le cas que H5 signale.

### DA-AUD-08 — Muter sur copie jetable, jamais dans l'arbre de travail

**Décision** : les mutations opèrent sur une copie (`git archive HEAD | tar -x -C "$TMPDIR/..."`),
pas en place.

**Justification** : `mutation_gate.py` de M10 mute **en place** puis restaure — cela fonctionne,
mais laisse une fenêtre où l'arbre est altéré, et dépend de la bonne exécution du `finally`. Sur un
audit qui doit prouver **n'avoir rien modifié** (CA-AUD-09), la copie jetable supprime le risque à
la racine. Le patron de vérification (rouge **avec le motif attendu** → restauration → contrôle
sha256) est repris tel quel.

### DA-AUD-09 — L'audit ne touche pas la CI qu'il mesure

**Décision** : aucun step n'est ajouté à `.github/workflows/ci.yml`. La sentinelle de l'audit
(`audit/tests/test_audit_structure.py`) est exécutée par `audit/run_audit.sh` et à chaque étape
locale, jamais par un job CI.

**Justification** : le lot A5 mesure précisément ce que la CI bloque ou ne bloque pas (hypothèse
H3 : `continue-on-error: true` sur les jobs qui exécutent les tests de sécurité). **Modifier la CI
pendant qu'on la mesure fausserait la mesure** et créerait un conflit d'intérêt — l'auditeur
deviendrait partie prenante de l'objet audité. Le gel du périmètre prime sur la commodité d'un
step automatique.

Conséquence assumée, à dire plutôt qu'à masquer : la sentinelle de l'audit n'a **pas** de filet CI.
Elle est donc exécutée explicitement à chaque étape, et `run_audit.sh` la rejoue de zéro. Si un
step CI dédié devait être ajouté, ce serait une story **postérieure à la clôture** de l'audit,
jamais pendant.

### DA-AUD-10 — La dépendance externe est gelée par empreinte, pas par confiance

**Décision** : `~/proof-method` reste hors du périmètre mesuré, mais l'audit enregistre au
manifeste le sha256 de chacun des scripts qu'il utilise (`civ_review.py`, `crew_dispatch.py`,
`tally_reviews.py`, `sentinelle.py`, les hooks git) au moment du gel, et les revérifie à la
clôture. Toute dérive entre les deux relevés invalide les revues conduites entre-temps.

**Justification** : deux relecteurs indépendants (MiMo-Pro-V2, MiniMax-M3) ont relevé que
l'essentiel de la chaîne de preuve réellement utilisée vit dans un dépôt distinct, non versionné
avec le produit et non gelé — de sorte qu'« hors périmètre » revenait à dire « non vérifié, et
libre de changer sous nos pieds ». On ne peut pas auditer ce dépôt sans sortir du périmètre fixé ;
on peut en revanche rendre toute modification **détectable**. Geler l'empreinte sans auditer le
contenu est la seule position à la fois honnête et tenable : elle ne prétend pas que ces scripts
sont corrects, elle prouve qu'ils n'ont pas changé pendant l'audit.

**Ce que la décision NE couvre PAS** : la correction de ces scripts. Un instrument faux au moment
du gel restera faux, et l'empreinte le certifiera identique à lui-même.

### DA-AUD-11 — Le lot A8 déroge à DA-AUD-07, de façon bornée et déclarée

**Décision** : le lot A8 (intégration entre modules) peut importer le code audité, **uniquement**
dans un sous-processus isolé, avec un délai maximal, et jamais dans le processus qui produit les
constats. Chaque import est journalisé dans la sortie de la sonde. Tous les autres lots restent
strictement sous DA-AUD-07.

**Justification** : DA-AUD-07 protège l'audit du couplage à l'objet mesuré, et sa justification
tient toujours. Mais onze modèles ont convergé sur le fait qu'elle crée un angle mort : un défaut
qui n'existe qu'à la jonction de deux modules — un appelant qui produit un digest là où l'appelé
attend une chaîne — est invisible à toute lecture de fichier isolé. Interdire l'import garantit
qu'on ne verra jamais cette classe de défauts.

L'isolement en sous-processus conserve l'essentiel de la protection : un effet de bord d'import,
un `sys.modules` pollué ou une boucle infinie n'atteignent pas le processus d'audit, et un module
syntaxiquement invalide produit un échec mesuré au lieu de faire tomber la sonde. Le précédent du
dépôt (issue #109 : 21 tests de M2 exerçaient le code de M1 via `sys.modules`) est un accident de
processus partagé ; il ne traverse pas une frontière de processus.

**Ce que la dérogation NE couvre PAS** : elle n'autorise aucun lot autre qu'A8 à importer, et
n'autorise pas A8 à exécuter du code métier au-delà de l'import et de l'inspection de signatures.
Faire tourner un scénario métier serait un test d'intégration — donc du développement, ce que
DA-AUD-04 interdit à l'audit.

## 4. CE QUE CHAQUE LOT PROUVE

| Lot | Ce qu'il prouve | CA | Tier |
|---|---|---|---|
| **A1** | Le périmètre est clos et gelé ; les instruments de méthode disent-ils vrai | CA-AUD-01, 02 | T1 |
| **A2** | Les 644 verdicts sont-ils des preuves ou des artefacts | CA-AUD-03, 11 | T2 |
| **A3** | Écart mesuré entre le plan ratifié et le livré | CA-AUD-07 | T2 |
| **A4** | Les défauts de code, chacun avec témoin rouge | CA-AUD-04, 05 | T2 |
| **A5** | Ce qui est exposé, et ce qui n'est pas couvert par un gate bloquant | CA-AUD-08 | T2 |
| **A6** | Dette structurelle et goulots, gravité pondérée par A4 | CA-AUD-06 | T2 |
| **A7** | Cohérence docs ↔ code ; l'audit lui-même est complet et n'a rien corrigé | CA-AUD-09, 10, 12 | T1 |
| **A8** | Ce qui ne casse qu'à la jonction de deux modules — invisible à toute lecture isolée | CA-AUD-05, 06 | T2 |

## 5. GOUVERNANCE — qui juge quoi

| Étape | Consensus | Justification |
|---|---|---|
| Cadrage BMAD | **Panel élargi** (`consensus_run.py`) — 8 modèles / 8 vendors obtenus sur 12 sollicités | Le cadrage définit ce qui compte comme preuve : une erreur ici contamine tout |
| Round d'hypothèses adverses | 3 appels, 1 tour, **pas de verdict** | C'est une collecte, pas un jugement |
| `contrats.py` + `rubrique.py` | T2 trio | C'est le juge ; le juge se relit en trio |
| Sonde + sa batterie de mutation | **T1 — la batterie est mesurée, pas crue** | voir ci-dessous |
| Lot d'inventaire (A1, A7) | T1 | La sortie de sonde est le constat |
| Lot avec interprétation (A2..A6, A8) | T2 trio | Existence + gravité |
| Constat T3 | T3 | Trio + Nathan seul |
| Rapport final | T2 trio | La conclusion |

**Pourquoi la batterie n'est plus en T0.** Le premier cadrage plaçait sonde et batterie en T0, au
motif qu'« aucun LLM n'a à approuver un instrument qui prouve sa propre morsure ». Quatre
relecteurs sur onze ont attaqué ce point, et la mesure leur a donné raison : le gate de ce cadrage
affichait « BATTERIE COMPLÈTE : 9/9 mutations mordent » alors que **3 de ses 11 contrôles pouvaient
être supprimés sans qu'elle s'en aperçoive**. Une batterie co-écrite avec sa sonde prouve la
sensibilité aux motifs que son auteur a imaginés, et rien de plus.

La parade n'est pas de faire approuver la batterie par un modèle — un relecteur n'aurait pas vu
davantage que son auteur. Elle est **mécanique** : la batterie neutralise tour à tour chaque
contrôle et exige de devenir rouge (CA-AUD-06), et chaque sonde publie la liste des fichiers
qu'elle a réellement ouverts, confrontée au périmètre déclaré de sa cellule (CA-AUD-05). Le passage
en T1 acte que cette double preuve doit être **produite et lue**, non pas supposée acquise.

**Le levier de coût est structurel, pas une dilution** : parce que chaque constat porte un témoin
exécutable, **vérifier un constat coûte zéro appel modèle** — on lance le script. Le trio ne juge
que ce qu'un script ne peut pas juger.

**Trio d'audit** : vendors à faible exposition historique, mesurée sur les 644 verdicts —
Gemini-3.1-Pro 163, Qwen3.7-Max 145, DeepSeek-V4-Pro 112 ont signé la quasi-totalité des 168 PR.
Candidats : **MiniMax-M3** (minimax, 47 % de rejet), **Kimi-K3** (moonshot), **Grok-4.5** (xai).
R-001 respecté : Grok et Composer jamais appariés. Le choix final est **sondé sur le pack réel**
avant usage et journalisé (`ROTATION.md`).

## 6. PARAMÈTRES CONFIGURABLES

Aucun seuil arbitraire. Deux chiffres, tous deux **mesurés** : plafond de pack 50 000 caractères
(un pack de 84 k a produit une sortie vide chez un reviewer sur trois — `reviews/m3-cadrage-A/
ROTATION.md`) ; cap de story 3 h (D-044, ratifié).

## 7. RISQUES DU PROTOCOLE LUI-MÊME

| # | Risque | Contre-feu | Résiduel |
|---|---|---|---|
| P-01 | Le découpage en axes crée un angle mort | Round adverse + bijection CA-AUD-01 | **Assumé** — la bijection garantit qu'aucun *fichier* n'échappe, pas qu'aucune *question* n'échappe |
| P-02 | Sonde verte parce que cassée | Batterie de mutation (CA-AUD-05/06) | Faible |
| P-03 | Pack trop gros → sortie vide chez un reviewer | Plafond 50 k mesuré, scission journalisée | Faible |
| P-04 | Trio d'audit non indépendant | Rotation mesurée, décision au registre | Faible |
| P-05 | Constat T3 enterré | Trois artefacts obligatoires + CA-AUD-08 | Faible |
| P-06 | Dérive vers la correction | CA-AUD-09 (contrôle du diff) | Faible |
| P-07 | Coût réel > estimation | Suivi ; au-delà de 80 appels → point d'arrêt avec Nathan | Moyen |

## 8. RISQUES MESURÉS DANS LE CODE LU — vigilance en implémentation

1. **Ne pas faire confiance à un gate vert.** `structure_lint` est vert sur une bijection **vide**
   (`frameworks: []` et `core/frameworks/` vide — l'ensemble vide satisfait trivialement la
   bijection) ; `ledger verify` est vert sur un fichier **absent** (H2). Toute réutilisation d'un
   gate existant doit s'accompagner d'une mesure de son angle mort.
2. **Ne pas laisser un pipe masquer un code retour.** Mesuré : `python3 scripts/tally.py … | head`
   affiche `rc=0` alors que le script sort en **2**. Toute sonde capture le rc **sans pipeline**,
   ou pose `set -o pipefail`.
3. **Ne pas rouvrir les dossiers clos.** `except-silencieux-122.md` documente une classe
   **légitime** d'`except` (3 occurrences `log_message`) ; `sonar-duplication-patrons-socle.md`
   endosse la duplication de socle avec une **portée close** dans `.sonarcloud.properties`. Les
   recompter en écarts ferait tomber l'audit au premier contre-exemple. Ces entrées doivent être
   dans `ecarts-assumes.yaml` **avant** l'exécution des lots A4 et A6.
4. **Séparer duplication assumée et divergence sémantique.** La dérogation couvre la **copie**,
   jamais la **contradiction de contrat**. `encoder_canonique` (M2 rend un digest, les 6 autres une
   chaîne) tombe dans le second cas et reste un écart réel. Sans cette séparation, A6 produit
   ~1 250 lignes de faux positifs et se fait légitimement réfuter.
5. **Ne pas conclure REG-06 depuis l'état terminal.** « 10 modules PARTIAL, 0 DONE_VERIFIED » ne
   prouve pas la violation : REG-06 interdit d'**ouvrir** le module suivant avant que le précédent
   soit prouvé. Seule la chronologie git (`git log --diff-filter=A --format=%aI -- "Modules M/<m>/"`)
   tranche. Sans cette mesure, le constat est réfutable — et il le sera.
6. **`BLOCKED` n'est pas un écart.** Les trois briques D-042 bloquées (mini-SWE, DSPy+GEPA,
   eccAgentShield) sont un état **valide** de la méthode, avec raison consignée.
