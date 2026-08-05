# PRD — AUDIT-000 : audit exhaustif prouvé du dépôt OPSYS-AI

## 0. TRANCHÉ SUR LES POINTS OUVERTS DE L'ANALYSTE

- **§8.1 (découpage)** : **sept lots par AXE**, confirmé. Justification chiffrée : 7 lots × 3
  reviewers × 1,6 round ≈ **45 appels** ; un découpage par module (10 × 7 = 70 lots) donnerait
  70 × 3 × 1,6 ≈ **336 appels** pour la même couverture — facteur ~7. Une sonde écrite une fois
  s'applique aux 135 fichiers source d'un coup.
- **§8.2 (critères)** : **12 CA** (CA-AUD-01..12), chacun vérifiable par `audit/verif_audit.py` et
  porté par exactement une story.
- **§8.3 (taille de pack)** : plafond dur **50 000 caractères**. Au-delà, scission obligatoire
  journalisée dans un `ROTATION.md` du lot.
- **§8.4 (hypothèses H1..H9)** : chacune devient une **cible de sonde obligatoire**, au même titre
  que les hypothèses du round adverse. Un fait mesuré pendant l'exploration n'est **pas** un
  constat prouvé : il lui manque son témoin RED rejouable. CA-AUD-07 le vérifie.
- **§8.5 (limite d'un constat de sécurité)** : exposition prouvée, **jamais** exploitation.
  `BLOCKED:` avec la commande exacte si confirmer exigerait de franchir T3.

## 1. PERSONAS

- **Nathan (commanditaire, décideur T3)** : veut l'état réel du projet et la liste des écarts, avec
  la gravité calculée et le coût de remédiation. Il tranche seul sur les constats T3.
- **L'Orchestrateur (exécutant, audité)** : construit les sondes, applique, exécute. Il n'émet
  aucun verdict — la sortie de la sonde est le verdict.
- **Le trio d'audit (juges, indépendants)** : vendors à faible exposition historique. Ils jugent ce
  qu'un script ne peut pas juger : le périmètre est-il complet, la rubrique bien conçue, l'énoncé
  sur-interprète-t-il ce que le témoin montre.
- **Le futur lecteur du rapport (tiers)** : doit pouvoir **rejouer** n'importe quel constat sans
  faire confiance à personne.

## 2. PARCOURS PRINCIPAUX

### 2.1 Un constat naît
Une sonde mesure et sort des faits → un témoin `reproduction.py` est écrit et **vérifié rouge sur
le commit gelé** → un `constats/AUD-<id>.json` est produit avec ses entrées de rubrique → la
sévérité est **calculée**, jamais saisie.

### 2.2 Une zone est déclarée propre
Aucun constat sur une cellule (lot × classe) → un `temoins/CLEAN-<lot>-<classe>/mutation.py`
injecte un défaut synthétique de cette classe dans un fichier réel, exige le **rouge avec le motif
attendu**, restaure, vérifie l'identité sha256 → la cellule est close.

### 2.3 Un constat est contesté
Le témoin tranche l'existence : un reviewer qui nie doit produire une **contre-exécution**. Une
objection sans contre-exécution est `mineure` et journalisée. Si l'objection est fondée en classe
mais fausse en exemple, la classe est corrigée et l'exemple réfuté par mesure, dans un
`REFUTATION-PARTIELLE.md` — patron établi par `reviews/m10-s005/`.

### 2.4 Un constat touche T3
Trois écritures obligatoires : entrée au registre, ligne dans `FILE-T3.md`, story `stories/REM-*.md`
gelée à `Tier: T3`. Le pipeline s'arrête. La décision appartient à Nathan seul.

## 3. PÉRIMÈTRE V1 vs HORS PÉRIMÈTRE

### 3.1 Dans l'audit

| Élément | Portée |
|---|---|
| Les 1 278 fichiers suivis, gelés au manifeste | bijection prouvée, zéro orphelin |
| Les 91 identifiants du plan (D/R/REG) + fiches M1..M10 + P0-1..P0-10 | matrice de traçabilité |
| Les instruments de preuve (`ledger_append`, `tally`, `structure_lint`, `statut_lint`, CI) | audités **avant** d'être utilisés |
| Les 644 verdicts scellés | intégrité, sceau, vendors, archives |
| Les 5 classes de défaut | code · plan · sécurité · performance · documentaire |

### 3.2 Hors périmètre, nommé

| Élément | Raison |
|---|---|
| `~/proof-method` | Dépôt distinct. Consigné comme **dépendance externe non versionnée** dont l'audit ne peut garantir l'état — constat de reproductibilité, pas contournement |
| `.claude/worktrees/` | Non suivi par git, structure divergente de `main` |
| Le PDF du plan maître | Étalon, pas objet mesuré |
| **Toute correction de code** | L'audit ne corrige rien (§0 décision 2) |
| Exploitation d'une faille | Exposition prouvée uniquement |

## 4. ÉNUMÉRÉS FERMÉS

Trois énumérés, chacun portant l'échappatoire D-032 `indetermine` :

```python
SEVERITE = ("critique", "majeure", "mineure", "indetermine")

CLASSE = ("defaut-code", "ecart-plan", "faille-securite",
          "goulot-performance", "incoherence-documentaire", "indetermine")

STATUT_CONSTAT = ("ouvert", "confirme", "refute", "arbitrage-humain", "indetermine")
```

`indetermine` est une valeur **explicitement choisie** par l'appelant et **force un arbitrage
humain** — jamais une coercition silencieuse d'une valeur inconnue (leçon M5-S001, dont
l'ambiguïté de libellé avait causé un REJECT 3/3 unanime). Une valeur hors énuméré est un rejet
nommé.

## 5. CONTRATS GELÉS

### 5.1 Le constat — `audit/contrats.py`

```yaml
Constat:
  id: str                    # AUD-<lot>-<nnn>
  lot: str                   # A1..A7
  classe: str                # dans CLASSE
  titre: str                 # une phrase, sans adjectif de gravité
  emplacement: list[str]     # ["fichier:ligne", ...] — au moins un
  temoin: str                # chemin du reproduction.py
  temoin_rc: int             # code retour SUR LE COMMIT GELÉ — doit être != 0
  temoin_sortie_sha256: str  # empreinte de la sortie capturée
  entrees_rubrique:          # MESURÉES, jamais jugées
    frontiere_t3: bool
    gate_couvrant: bool
    rayon: int
    contrat_gele: str        # id D-/R-/REG-/CA- résolvable, ou ""
  severite: str              # CALCULÉE par rubrique.py — recalculée par verif_audit.py
  statut: str                # dans STATUT_CONSTAT
  refutation: dict           # {cmd, sortie, conclusion} — OBLIGATOIRE et non vide
  assume_ref: str | None     # id dans ecarts-assumes.yaml si dérogation
```

### 5.2 La rubrique de sévérité — `audit/rubrique.py`

Quatre entrées, toutes mesurées :

| Entrée | Ce qui la mesure |
|---|---|
| `frontiere_t3` | le constat touche paiement / secret / suppression / publication / engagement |
| `gate_couvrant` | le chemin est-il dans un job CI **sans** `continue-on-error` ? |
| `rayon` | nombre de fichiers/modules atteints par le témoin — **compté**, jamais estimé |
| `contrat_gele` | id D-/R-/REG-/CA- violé, **résolvable** au référentiel, ou `""` |

```
critique  = frontiere_t3
            OU (contrat_gele != "" ET rayon >= 2)
            OU (NON gate_couvrant ET rayon >= 3)
majeure   = contrat_gele != ""  OU  (NON gate_couvrant ET rayon >= 1)
mineure   = sinon
indetermine = une entrée non mesurable → le script REFUSE de deviner → arbitrage humain
```

### 5.3 L'écart assumé — `audit/ecarts-assumes.yaml`

```yaml
- id: str
  constat: str
  doc: str            # chemin d'un document EXISTANT du dépôt
  ancre: str          # chaîne devant être PRÉSENTE dans ce document
  portee_fichiers: [] # liste CLOSE — un constat hors liste ne peut s'en réclamer
  limite: str         # ce que la dérogation NE couvre PAS
```

Trois contrôles automatiques, sinon l'entrée est rejetée : `doc` existe et contient `ancre` ;
`portee_fichiers` est close ; `limite` est renseignée. Le champ `limite` empêche qu'une décision
légitime absolve un défaut différent.

## 6. CRITÈRES D'ACCEPTATION

- **CA-AUD-01** : le périmètre est **clos** — bijection manifeste ↔ lots, zéro fichier orphelin,
  zéro double affectation.
- **CA-AUD-02** : le périmètre est **gelé** — le sha256 de chaque fichier au commit de base est
  identique au sha256 relu ; toute dérive est un écart.
- **CA-AUD-03** : **tout constat porte un témoin RED rejouable** — `reproduction.py` exécuté sur
  le commit gelé sort ≠ 0, sortie capturée, sha256 enregistré.
- **CA-AUD-04** : **aucune sévérité n'est écrite à la main** — `verif_audit.py` recalcule chaque
  `severite` depuis `entrees_rubrique` et rejette toute divergence.
- **CA-AUD-05** : **toute zone déclarée propre est prouvée mordante ET réellement parcourue** —
  chaque cellule (lot × classe) sans constat possède un `mutation.py` qui passe, **et** la sonde
  publie la liste des fichiers qu'elle a effectivement ouverts, qui doit couvrir le périmètre
  déclaré de la cellule. Une mutation qui mord prouve que la sonde voit le motif injecté ; elle ne
  prouve pas qu'elle a regardé ailleurs. Un fichier du périmètre jamais ouvert est un écart.
- **CA-AUD-06** : **les sondes mordent, et la batterie couvre CHAQUE contrôle** —
  `audit/mutation_audit.py` sort `BATTERIE COMPLÈTE`, rc=0, chaque fichier muté restauré et vérifié
  bit-à-bit. En outre, la batterie neutralise tour à tour chaque contrôle (corps remplacé par un
  retour vide) et exige de devenir rouge : un contrôle qu'aucune mutation n'exerce est déclaré MORT
  et fait échouer la batterie. Un compte de mutations ne mesure pas une couverture — mesuré sur le
  gate de ce cadrage : 9 mutations sur 9 mordaient alors que 3 contrôles sur 11 étaient morts.
- **CA-AUD-07** : **aucune hypothèse laissée sans réponse, et une hypothèse peut OUVRIR un lot** —
  chaque hypothèse H1..H9 et chaque hypothèse du round adverse est convertie en constat avec témoin,
  ou réfutée par une mesure. Si une hypothèse adverse n'entre dans aucun lot existant, le lot
  manquant est créé plutôt que l'hypothèse écartée : un round adverse qui ne pourrait que désigner
  où chercher à l'intérieur d'axes déjà figés ne corrigerait pas le biais de découpage.
- **CA-AUD-08** : **les constats T3 sont bloqués, jamais corrigés** — entrée registre + ligne dans
  `FILE-T3.md` + story `REM-*` à `Tier: T3`, et le diff de la branche ne touche aucun chemin T3.
- **CA-AUD-09** : **l'audit ne corrige rien, et n'altère aucune preuve existante** —
  `git diff --name-only <base>..HEAD` n'intersecte le code produit en aucun point (seuls `audit/`,
  `stories/REM-*`, `reviews/`, `registries/ledger/` sont autorisés). Dans ces chemins autorisés,
  seul l'**ajout** est permis : `git diff --diff-filter=MD <base>..HEAD` doit être vide. Autoriser
  un répertoire n'autorise pas à y réécrire un verdict scellé ou une ligne de registre fusionnée.
- **CA-AUD-10** : **traçabilité au registre, vérifiée sans faire confiance à l'instrument** — chaque
  constat a son entrée `preuve` ; `ledger_append.py verify` reste vert, **rapporte un nombre
  d'entrées non nul**, **et** l'audit rejoue la chaîne de hachage par son propre code. H2 établit
  que `verify` affiche `OK (0 entrees)` sur un fichier absent : adosser la complétude de l'audit au
  seul code retour de cet instrument reviendrait à la faire valider par le défaut qu'il documente.
- **CA-AUD-11** : **chaque lot a un verdict scellé dépouillé** — tally rc=0 pour chaque lot. Le
  dépouillement est celui de `~/proof-method`, dont l'empreinte est gelée au manifeste (DA-AUD-10) ;
  si l'audit établit que `scripts/tally.py` du dépôt est inopérant, ce constat ne peut évidemment
  pas être clos par ce même script.
- **CA-AUD-12** : **le rapport ne contient aucune affirmation sans témoin** — chaque affirmation de
  `RAPPORT.md` cite un `AUD-<id>` existant ; toute phrase affirmative sans référence est un écart.
- **CA-AUD-13** : **ce qui ne casse qu'à la jonction est mesuré à la jonction** — pour chaque paire
  de modules reliée par un import, une sonde charge les DEUX côtés dans un sous-processus isolé et
  confronte ce que l'appelant produit à ce que l'appelé accepte. Une paire jamais chargée est un
  écart. Ce critère existe parce qu'aucun des douze autres ne peut être satisfait par une lecture
  de fichiers isolés : le défaut visé n'apparaît nulle part dans un fichier pris seul.

Les 13 critères sont en séquence continue, chacun porté par exactement une story.

## 7. STORIES

Sept lots. Tier selon ce que l'étape **décide** : un lot dont la sortie de sonde EST le constat
(inventaire pur) est T1 ; un lot exigeant un jugement de gravité ou d'interprétation est T2.

### AUD-A1 — Conformité structurelle et méthode

| Attribut | Valeur |
|---|---|
| **Périmètre** | D-038 (arborescence), statuts déclarés vs mesurés, chaîne des registres, no-stub, TODO, tests sans assertion, fichiers non collectés |
| **Cible obligatoire** | H2 (`installations.jsonl` absent, `verify` vert) |
| **Critères portés** | CA-AUD-01, CA-AUD-02 |
| **Tier** | T1 — la sortie de sonde est le constat, sans interprétation |
| **Estimation** | ~50 min |

### AUD-A2 — Intégrité de la preuve

| Attribut | Valeur |
|---|---|
| **Périmètre** | Les 644 verdicts : sceau `prompt_sha256` unique par revue, 3 vendors distincts, archives `round-N/` byte-identiques ; `scripts/tally.py` opérant ou non |
| **Cible obligatoire** | H1 (`tally.py` INVALIDE sur le corpus réel) |
| **Critères portés** | CA-AUD-03, CA-AUD-11 |
| **Tier** | **T2** — juge la validité d'une preuve |
| **Estimation** | ~55 min |

### AUD-A3 — Écart au plan original

| Attribut | Valeur |
|---|---|
| **Périmètre** | D-001..D-045, R-001..R-033, REG-01..13, fiches M1..M10, P0-1..P0-10, cibles chiffrées. Matrice de traçabilité complète |
| **Cibles obligatoires** | H7 (8 services D-010), H8 (P0-9 sans preuve), H9 (D-047, R-034/35/36) |
| **Critères portés** | CA-AUD-07 |
| **Tier** | **T2** — sonde dispatchée au crew (forte exposition de l'Orchestrateur) |
| **Estimation** | ~60 min (cap 3 h, découpage si dépassement) |

### AUD-A4 — Défauts de code

| Attribut | Valeur |
|---|---|
| **Périmètre** | Sémantique d'erreur (exceptions avalées, échec mappé sur succès), invariants critiques (chaîne de hash, fail-closed, idempotence), non-déterminisme |
| **Cibles obligatoires** | H4 (`NotAutorise` → SUCCES), H5 (conformite.py exclut en silence), H6 (`encoder_canonique` convention inverse) |
| **Critères portés** | CA-AUD-04, CA-AUD-05 |
| **Tier** | **T2** — sonde dispatchée au crew |
| **Estimation** | ~60 min |

### AUD-A5 — Sécurité

| Attribut | Valeur |
|---|---|
| **Périmètre** | Secrets (arbre + historique), R-015 (injection indirecte), gates non bloquants, épinglage D-035, P0-9 (RPO/RTO), politiques Loi 25 sans point d'application |
| **Cible obligatoire** | H3 (`continue-on-error` sur les tests de sécurité) |
| **Critères portés** | CA-AUD-08 |
| **Tier** | **T2**, constats T3 possibles → §2.4 |
| **Estimation** | ~55 min |

### AUD-A6 — Performance, robustesse, dette structurelle

| Attribut | Valeur |
|---|---|
| **Périmètre** | Duplication divergente sous nom commun, fonctions surdimensionnées, relectures de registre en boucle, boucles profondes, flakiness, temps CI |
| **Critères portés** | CA-AUD-06 |
| **Tier** | **T2** — la gravité d'une duplication dépend de ce qu'elle duplique ; exécuté **après** A4 |
| **Estimation** | ~50 min |

### AUD-A7 — Cohérence documentaire

| Attribut | Valeur |
|---|---|
| **Périmètre** | docs ↔ code, `Statut:` des README vs mesure, renvois internes, `AGENTS.md`/`CLAUDE.md` vs canon, fichiers `.bak` versionnés |
| **Cible obligatoire** | HA-07 (les `.bak` révèlent-ils un assouplissement des consignes après coup ?) |
| **Critères portés** | CA-AUD-09, CA-AUD-10, CA-AUD-12 |
| **Tier** | T1 — la sortie de sonde est le constat |
| **Estimation** | ~45 min |

### AUD-A8 — Intégration entre modules

Ce lot n'existait pas au premier cadrage. Il est **ouvert par le round adverse**, en application de
la règle qui autorise une hypothèse adverse à créer le lot qui lui manque : les onze modèles
consultés — trois en round adverse, huit en consensus élargi — ont convergé, indépendamment les uns
des autres, sur le même angle mort. Formulé par DeepSeek : « les défauts émergents de l'interaction
entre modules échappent au dispositif, car aucune intégration de bout en bout n'est imposée par le
processus ». Formulé par GLM : « les sondes lisent des fichiers isolément, donc un défaut qui
n'existe qu'à l'intégration est structurellement invisible ».

Cette convergence est le seul motif suffisant pour ouvrir un lot : elle ne vient pas d'une mesure de
l'Orchestrateur, mais d'une critique de son découpage par des parties qui n'y avaient aucun intérêt.

| Attribut | Valeur |
|---|---|
| **Périmètre** | imports entre modules ; signatures appelées vs définies ; formats d'échange (un module produit un digest là où un autre attend une chaîne) ; ordre d'initialisation ; invariants qui ne tiennent qu'à la jonction de deux modules |
| **Cibles obligatoires** | HA-10 (socle recopié divergent), HA-12 (appel inter-modules incompatible), HA-09 (encodage canonique non déterministe entre copies) |
| **Critères portés** | CA-AUD-13 |
| **Tier** | T2 — établir qu'une divergence de format est un défaut, et non une frontière voulue, demande un jugement |
| **Dérogation encadrée** | DA-AUD-07 interdit d'importer le code audité. Ce lot y déroge de façon **bornée** : voir DA-AUD-11. |
| **Estimation** | ~70 min |

## 8. ORDRE D'EXÉCUTION — les instruments avant les mesures

| Vague | Lots | Pourquoi |
|---|---|---|
| **1 — instruments** | A1, A2 | Si le ledger rend un faux vert (H2) et si `tally.py` est inopérant (H1), toute preuve produite jusqu'ici est suspecte. Ces deux lots conditionnent la lecture de tout le reste |
| **2 — fond** | A3, A4 | Écart au plan et défauts de code, sondes dispatchées au crew |
| **3 — transverse** | A5, A6, A7 | A5 croise A1/A2 (gates) ; A6 dépend de A4 (la gravité d'une duplication dépend de ce qu'elle duplique) ; A7 consomme tout |

## 9. PARAMÈTRES

Aucun seuil arbitraire. Les deux seuls chiffres du protocole sont **mesurés** : plafond de pack
50 000 caractères (un pack de 84 k a produit une sortie vide chez un reviewer sur trois) et cap de
story 3 h (D-044, ratifié).

## 10. FRONTIÈRES RATIFIÉES

L'audit ne corrige rien, n'exploite aucune faille, ne franchit aucune frontière T3, ne rouvre aucun
dossier clos sans mesure nouvelle, n'écrit aucune sévérité à la main, et ne prétend jamais prouver
l'absence de défauts.
