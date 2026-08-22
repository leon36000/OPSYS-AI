# Politique qualité NO-STUB

Le gate `scripts/quality/no_stub_gate.py` protège les racines Python déclarées
dans `core/quality-scopes.toml`.

## Exécution CI

Le gate est exécuté par le job requis `types` de
`.github/workflows/core-ci.yml` :

```sh
python3 scripts/quality/no_stub_gate.py --repo . --base-ref origin/main
```

Le checkout de ce job récupère l'historique complet puis exécute :

```sh
git fetch origin main --quiet
```

La référence `origin/main` est donc disponible pour les contrôles diff-aware.
Le gate ne doit jamais être exécuté avec `continue-on-error`, `|| true` ou une
neutralisation équivalente de son code de retour.

## Frontière Git des contrôles diff-aware

Le chemin relatif utilisé pour calculer les lignes modifiées est validé avant la
frontière `subprocess`. Il doit être relatif au dépôt, composé uniquement de
segments alphanumériques, `_`, `.`, `-` et `/`, sans segment `.` ou `..`. Les
commandes Git reçoivent ensuite un `argv` sans chemin dynamique : elles listent
les chemins suivis et produisent le diff complet, filtré en mémoire sur le
chemin validé. La référence de base suit la même liste blanche et ne peut pas
commencer par `-` ; `--end-of-options` la protège aussi côté Git. Un
pathspec ambigu ou contenant un métacaractère est refusé en mode fail-closed ;
il ne peut donc pas devenir une option Git ou une expression de pathspec.

Cette propriété est verrouillée par
`scripts/tests/test_no_stub_gate_base_ref_unittest.py`, qui vérifie qu’un nom
de fichier contenant des métacaractères est rejeté avant tout appel à
`subprocess` et qu’un chemin nominal n’apparaît pas dans les `argv` Git.

## Contrôles refusés

Le gate refuse notamment :

- les corps exécutables réduits à `pass`, `...`, `return` ou `return None`,
  **dans une fonction comme dans un corps de CLASSE** ;
- les levées de `NotImplementedError` ou `NotImplemented`, directes, importées
  ou qualifiées, **dans une fonction comme hors de toute fonction** ;
- les tests modifiés sans oracle et les assertions trivialement vraies ;
- les sauts de tests ajoutés, y compris conditionnels (`skipif`, `skipIf`,
  `skipUnless`, `xfail`, `importorskip`) ;
- les marqueurs de dette ajoutés et les suppressions de contrôles non justifiées ;
- toute suppression de typage **ajoutée**, justifiée ou non (`NEW_TYPE_IGNORE`) ;
- les jobs CI requis qui absorbent un échec shell, y compris par une garde
  `if !` dont la branche ne propage pas l'échec, ou par `set +e` ;
- les jobs CI requis conditionnels ou avec `continue-on-error`, y compris sous
  ses formes **numériques** (`1`, `2`, `-1`, `1.0`) ;
- les jobs requis de forme invalide, notamment une définition non mapping ou un
  champ `steps` qui n'est pas une liste ;
- les jobs requis qui n'exécutent aucune étape, y compris lorsqu'ils délèguent
  la totalité de leur travail à une action composite locale sans étape ;
- les jobs requis qui délèguent à une action locale **absente du dépôt**
  (`LOCAL_ACTION_INTROUVABLE`) ;
- l'absence globale d'un id déclaré dans `target_required_job_ids`.

Un id requis peut être déclaré dans un workflow différent des autres ids :
la couverture est vérifiée sur l'ensemble de `.github/workflows/`, ce qui
permet notamment la répartition actuelle entre `ci.yml` et `core-ci.yml`.

### L'absence TOTALE de CI est le défaut maximal, jamais une dispense

La seule borne de `REQUIRED_JOB_ABSENT` est le **contrat**, jamais la présence
d'une CI. Un dépôt qui déclare des jobs requis et n'en exécute aucun est le
défaut maximal : les trois formes de cette absence livrent exactement la même
CI — aucune — et sont donc jugées à l'identique.

| Forme | Verdict |
|---|---|
| `.github/workflows/` inexistant | refusé |
| `.github/workflows/` existant mais vide | refusé |
| `.github/workflows/` sans fichier `.yml` ni `.yaml` | refusé |
| `target_required_job_ids` ne déclare aucun id | rien signalé |

Sans identifiant requis déclaré, aucun contrôle n'est promis et rien ne peut
être reproché.

Les trois derniers contrôles portent les codes `REQUIRED_JOB_STRUCTURE_INVALIDE`,
`REQUIRED_JOB_SANS_ETAPE` et `REQUIRED_JOB_ABSENT`. Ils ne s'appliquent qu'aux
ids listés dans `target_required_job_ids` : un job facultatif de forme inattendue
reste ignoré, pour qu'un durcissement ne se paie pas en faux positifs sur le
reste du dépôt.

## `continue-on-error` — les formes réellement vraies

`REQUIRED_JOB_SOFT_FAILURE` juge la valeur telle que **PyYAML la rend**, non
telle qu'elle est écrite. MESURÉ avec PyYAML 6.0.1 : `yes`, `on` et `true`
deviennent le booléen `True` ; `y` et `Y` restent des chaînes ; mais `1` devient
l'**entier** 1, que ni le test booléen ni le test de chaîne n'attrapaient — la
tolérance passait alors inaperçue et le job requis restait vert avec son contrôle
rouge.

La forme numérique est donc jugée sur sa **valeur**, jamais sur son type :

```yaml
continue-on-error: true    # refusé — booléen
continue-on-error: yes     # refusé — booléen (PyYAML)
continue-on-error: '1'     # refusé — chaîne vraie
continue-on-error: 1       # refusé — entier non nul
continue-on-error: 0x1     # refusé — PyYAML rend l'entier 1
continue-on-error: 1.0     # refusé — flottant non nul
continue-on-error: -1      # refusé — nombre non nul
continue-on-error: ${{ … }} # refusé — valeur dynamique, par principe

continue-on-error: false   # accepté
continue-on-error: 0       # accepté — zéro ne tolère rien
continue-on-error: 0.0     # accepté
```

`False` échoue à la comparaison numérique et poursuit sans violation, comme il
le doit. Les formes dont la vérité n'est pas décidable ici — `.nan`, `.inf` —
restent refusées en fail-closed : aucune ne désigne un contrôle obligatoire.

La même lecture par la valeur s'applique aux scalaires **quotés**. La liste des
chaînes vraies est fermée (`true`, `yes`, `on`, `y`, `1`) et ne couvrait aucun
autre numérique quoté : MESURÉ, `'2'` était accepté quand `2` non quoté et
`'true'` étaient refusés — un seul caractère de quote suffisait à tolérer les
erreurs d'un job requis.

```yaml
continue-on-error: '2'     # refusé — deux vaut vrai, quoté ou non
continue-on-error: "-1"    # refusé — nombre non nul
continue-on-error: '1.5'   # refusé — flottant non nul

continue-on-error: '0'     # accepté — zéro ne tolère rien, quoté ou non
continue-on-error: "0.0"   # accepté
continue-on-error: "false" # accepté
```

Le contrôle numérique est placé **après** la liste des chaînes vraies, si bien
que `'1'`, déjà couvert par elle, conserve son message d'origine.

### Sur un scalaire QUOTÉ, c'est la FAUSSETÉ qui doit être écrite

La lecture décimale n'a pas suffi, et l'échec était mesurable : elle **échoue**
sur les bases non décimales et retombait silencieusement sur « faux ».

```yaml
continue-on-error: '0x1'   # MESURÉ accepté avant correction — float('0x1') lève
continue-on-error: '0o7'   # MESURÉ accepté avant correction — même cause
continue-on-error: '2'     # refusé — la lecture décimale aboutit
```

Deux options se présentaient : apprendre les bases, ou **inverser la règle**.
La première ne ferme qu'une orthographe à la fois — `'0x1'` fermé, `'0x0'`,
`'enabled'` et `'oui'` restaient ouverts —, et l'énumération des orthographes
vraies ne converge pas, exactement comme celle des replis absorbants. C'est donc
l'inversion qui est retenue : **un scalaire quoté tolère les erreurs, sauf si sa
fausseté est écrite.**

Trois écritures disent la fausseté sans ambiguïté et restent acceptées : le
scalaire **vide**, un mot-clé faux de YAML (`false`, `no`, `off`, `n`), et un
zéro **décimal** (`0`, `0.0`, `-0`).

```yaml
continue-on-error: '0x1'   # refusé — base non décimale
continue-on-error: '0o7'   # refusé
continue-on-error: '0b1'   # refusé
continue-on-error: '0x0'   # refusé — un zéro hexadécimal n'écrit la fausseté de personne
continue-on-error: 'oui'   # refusé — chaîne quelconque
continue-on-error: '.nan'  # refusé — vérité non décidable, fail-closed
continue-on-error: '  '    # refusé — des blancs ne sont pas le scalaire VIDE

continue-on-error: ''      # accepté — scalaire vide
continue-on-error: 'false' # accepté
continue-on-error: 'no'    # accepté
continue-on-error: 'off'   # accepté
continue-on-error: 'n'     # accepté
continue-on-error: '-0'    # accepté — zéro décimal
```

Les branches numériques restent **avant** cette fermeture, afin de garder leur
message chiffré, plus précis pour l'auteur du workflow ; elles ne décident plus
seules de l'acceptation.

Cette lecture est plus stricte que la sémantique nominale de YAML, et le doit :
d'après le contrat GitHub Actions — rappelé au mandat de cette correction, non
exécutable depuis ce dépôt et donc rapporté comme tel — toute chaîne non vide y
est convertie en vrai, y compris `'false'` et `'0'`. Accepter les quatre
mots-clés et le zéro décimal est une **concession assumée à l'intention**, qu'ils
écrivent sans équivoque, et aux cas déjà couverts par la suite de tests. Le
scalaire non quoté ne connaît pas ce doute : PyYAML en rend un booléen ou un
nombre, jugé plus haut.

## Jobs requis qui n'exécutent rien

Un job requis peut être parfaitement valide au sens YAML et n'exécuter aucun
contrôle. La protection de branche est alors satisfaite par un job vert qui n'a
rien vérifié : un gate désarmé est plus dangereux qu'un gate absent, puisque
rien ne le signale. Le code `REQUIRED_JOB_SANS_ETAPE` refuse ces formes :

```yaml
jobs: {gates: {runs-on: ubuntu-latest, steps: []}}       # refusé — aucune étape
jobs: {gates: {runs-on: ubuntu-latest, steps: [null]}}   # refusé — étape nulle
```

Une étape ne compte que si elle exécute réellement un `run` ou désigne un
`uses` non vide : une étape réduite à un `name` décoratif n'exécute rien. Un
`run` vide, blanc ou composé uniquement de commentaires shell n'exécute aucun
contrôle et ne compte donc pas comme étape effective. Le même critère s'applique
aux étapes des actions composites locales appelées par un job requis. Un job
requis dépourvu à la fois de `steps` et de `uses` est refusé pour la même raison.

```yaml
- run: '# commentaire seulement'   # aucune étape effective — refusé
- run: python3 -m pytest           # commande réelle — effectif
- uses: actions/checkout@v5        # action désignée — effectif
```

**La présence de la CLÉ ne suffit pas : la VALEUR est lue.** MESURÉ avant
correction — les deux formes suivantes satisfaisaient l'exigence d'étape
effective alors qu'aucune commande n'est exécutée :

```yaml
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - run: ''        # refusé désormais — commande vide
      - run: '   '     # refusé désormais — commande blanche
      - uses: '  '     # refusé désormais — aucune action désignée
```

Une valeur **non-chaîne** ne compte pas non plus, et ce choix est FAIL-CLOSED :
`run: 42`, `run: null` et `run: []` sont ignorés par l'analyse des commandes, qui
ne lit que des chaînes. Les compter comme effectifs laisserait un job requis
satisfaire l'exigence avec une valeur qu'aucune règle du gate ne sait lire — la
seule forme de désarmement qu'un job non vide pouvait encore prendre. Le critère
est identique pour les étapes des **actions composites locales**, jugées par le
même prédicat.

L'appel d'un workflow réutilisable reste légitime et n'est pas signalé, bien
qu'il n'ait aucune clé `steps` :

```yaml
jobs:
  gates:
    uses: ./.github/workflows/reutilisable.yml    # accepté
```

### `success()` cesse d'être une garantie dès qu'un `needs` est déclaré

Un job requis ne peut porter que les conditions dont la vérité est garantie.
`always()` et `success()` l'étaient toutes deux — c'était incomplet, et le code
`REQUIRED_JOB_CONDITIONNEL` refuse désormais la seconde en présence d'un `needs`.

`success()` SEUL est la condition par défaut et ne saute rien. Dès qu'une
dépendance est déclarée, la même écriture change de sens : GitHub Actions évalue
alors le statut de cette dépendance. Un job dont on dépend **sauté** — ce qu'une
simple condition fausse sur un job NON requis suffit à provoquer, puisque rien ne
contraint les jobs facultatifs — ou en échec rend `success()` faux, et le job
requis est sauté à son tour. La protection de branche est satisfaite sans qu'un
seul contrôle ait tourné.

```yaml
jobs:
  precheck:
    if: ${{ false }}            # job NON requis, libre de ne jamais tourner
    runs-on: ubuntu-latest
    steps: [{run: echo rien}]
  gates:
    needs: precheck
    if: success()               # refusé — precheck sauté ⇒ gates sauté
```

`always()` reste accepté **malgré** un `needs`, et c'est un choix fondé sur le
comportement réel : `always()` vaut vrai quel que soit le sort des dépendances,
si bien que le job requis s'exécute même quand celui dont il dépend a échoué ou a
été sauté. Le danger corrigé — un contrôle requis rapporté vert sans avoir tourné
— n'existe pas sous cette condition, et l'interdire supprimerait la seule
écriture qui force un gate à tourner en toutes circonstances.

```yaml
jobs:
  gates:
    if: success()               # accepté — aucun needs, rien ne peut la rendre fausse
jobs:
  gates:
    needs: precheck
    if: always()                # accepté — tourne même si precheck a échoué ou sauté
```

La détection retient la **présence** de la clé `needs`, sans juger son contenu :
la forme varie (chaîne, liste, valeur dynamique) et une déclaration illisible
n'apporte aucune garantie. Au pire, un `needs` dégénéré oblige à écrire
`always()`, qui exécute le contrôle — le repli est donc fail-closed.

La contrainte s'arrête au niveau **job**. Une ÉTAPE n'a pas de `needs` : son
`success()` ne dépend que des étapes précédentes du même job, dont l'échec rend
le job — donc le contrôle requis — rouge. Aucun saut silencieux n'y est possible.

### Actions composites locales sans étape

Déléguer à une action locale ne dispense pas de l'exigence : un job requis dont
la seule étape est `uses: ./.github/actions/…` n'exécute rien de plus que ce que
l'action exécute. La même règle, et le même code `REQUIRED_JOB_SANS_ETAPE`,
s'appliquent donc au descripteur de l'action, où la violation est rapportée :

```yaml
runs: {using: composite, steps: []}                 # refusé — aucune étape
runs: {using: composite, steps: [{name: decor}]}    # refusé — étape décorative
runs: {using: composite}                            # refusé — pas même une clé steps
runs: {using: composite, steps: [{run: verif}]}     # accepté — un contrôle réel
```

Trois formes restent volontairement hors de cette règle :

- une action composite dont la seule étape est un `uses` vers une **autre**
  action locale : le `uses` est une étape effective, et l'action appelée est à
  son tour analysée en profondeur — la cascade est jugée là où elle se termine ;
- une action `using: node20` ou `using: docker`, qui n'a par nature aucune clé
  `steps` et n'est donc jamais une composite vide ;
- une action locale illisible ou introuvable, déjà traitée par les règles de
  chargement (`FICHIER_NON_ANALYSABLE`) et de résolution
  (`LOCAL_ACTION_INTROUVABLE`) : la règle d'étape effective ne les double pas.

### Action locale introuvable

Une action locale **référencée mais absente** est un contrôle qui n'existe pas,
et le job requis qui la délègue reste vert sans avoir rien vérifié — la même
faille qu'un job sans étape, à ceci près qu'elle survit à toute lecture du
workflow, qui paraît complet. Le code `LOCAL_ACTION_INTROUVABLE` la refuse ; la
violation est rapportée dans le fichier **qui porte la référence**, workflow ou
descripteur d'action, puisque c'est là qu'elle se corrige.

```yaml
- uses: ./.github/actions/absente     # refusé  — aucun action.yml ni action.yaml
- uses: ./.github/actions/controle    # accepté — le descripteur existe
- uses: actions/checkout@v4           # accepté — action externe, hors du dépôt
```

Une action **externe** n'est jamais tenue pour absente : elle ne vit pas dans le
dépôt, et son absence locale est la normale. La distinction est portée par le
préfixe `./`, seul point de décision, et la règle reste bornée aux ids de
`target_required_job_ids` comme les autres règles de jobs requis.

Le code est délibérément distinct de `FICHIER_NON_ANALYSABLE` : celui-ci
qualifie un fichier **présent** dont le contenu résiste à l'analyse — lecture,
encodage, syntaxe — alors qu'ici rien n'a été lu et rien n'a échoué à l'analyse.
Le défaut est dans la **référence**, comme pour `LOCAL_ACTION_CYCLE` et
`LOCAL_ACTION_DEPTH_EXCEEDED`, dont il rejoint la famille ; les confondre
rendrait le message trompeur et la correction ambiguë (créer l'action, ou
retirer la référence, plutôt que réparer un fichier).

La détection suit la **cascade** : une action composite qui délègue à une action
locale absente est refusée exactement comme le job qui l'appelle.

## Chaînes et commentaires shell

Toutes les règles shell lisent la commande **après neutralisation** des chaînes
et des commentaires : un motif écrit entre quotes ou après un `#` est une donnée
ou un texte, jamais du code exécuté. Cette lecture décide donc de ce que chaque
règle voit, et un commentaire ouvert trop tôt rend muets tous les contrôles.

Un `#` n'ouvre un commentaire que s'il est en **début de mot**, comme dans un
shell réel : précédé du début de la commande, d'une espace, d'une tabulation,
d'un retour à la ligne, ou de l'un des séparateurs `;`, `|`, `&`, `(`, `)`.
Collé à un mot, c'est un caractère ordinaire :

```sh
python3 gate.py x#note || true   # refusé  — « x#note » est un mot, le repli s'exécute
python3 gate.py $# || true       # refusé  — « $# » est le nombre d'arguments
gate.py  # commentaire || true   # accepté — commentaire réel, sa fin de ligne est morte
gate.py;# commentaire || true    # accepté — « ; » ouvre un mot, donc un commentaire
echo "couleur #ff0000" || true   # refusé  — le # entre quotes reste une donnée
```

Traiter tout `#` comme une ouverture de commentaire effaçait la fin de la ligne :
`python3 gate.py x#note || true` passait pour un contrôle sans repli, alors qu'il
force un succès.

### L'antislash suit les trois règles du shell, mesurées avant d'être codées

Ne pas traiter l'échappement laissait une quote **échappée** ouvrir une chaîne
qui n'existe pas, et cette fausse chaîne effaçait tout ce qui suivait — donc le
repli. MESURÉ dans bash : `f gate.py \"|| echo REPLI` passe `gate.py` puis un
guillemet littéral en arguments, et écrit bien `REPLI` ; le job requis restait
pourtant vert avec son contrôle rouge.

| Contexte | Rôle de `\` | Mesure |
|---|---|---|
| Hors quotes | rend littéral le caractère suivant | `f gate.py \"\|\| echo REPLI` → argv `[gate.py]["]`, puis `REPLI` |
| Quotes **simples** | aucun — caractère ordinaire | `printf '%s' '\"'` écrit deux octets, `5c 22` |
| Guillemets **doubles** | échappe `"`, `\`, `$` et `` ` `` | la position du guillemet fermant est la seule qui compte ici |

```sh
gate.py \" || true      # refusé  — la quote est littérale, le repli s'exécute
gate.py \"|| true       # refusé  — sans espace : « || » reste un opérateur
gate.py \\ || true      # refusé  — antislash littéral, le repli s'exécute
gate.py 'motif\' || true # refusé — entre quotes simples, « \ » n'échappe rien
gate.py --motif "a\" || true" --strict   # accepté — le repli est CITÉ, jamais exécuté
```

Hors quotes, les deux caractères sont neutralisés **ensemble** : ils ne portent
aucune syntaxe. La consommation est d'exactement deux caractères — un de plus
couperait un `||` collé à la quote et rouvrirait la brèche par l'autre bout.
Entre guillemets doubles, la distinction entre échappement réel et antislash
littéral est sans effet observable : l'intérieur d'une chaîne est neutralisé de
toute façon.

## Replis après `||` : une LISTE BLANCHE de formes qui propagent

La règle est **inversée**. Dans un job **requis**, tout opérateur `||` est tenu
pour absorbant **par défaut** ; sa branche de droite n'est acceptée que si elle
PROUVE qu'elle rend l'échec au job. C'est un fail-closed structurel : il ferme la
classe entière au lieu de ses instances.

### Pourquoi l'énumération des formes absorbantes ne converge pas

L'ancienne règle listait les formes qui **absorbent** : `|| true`, `|| :`,
`|| echo`, `|| printf`, `|| exit 0`, `|| { … }`, `|| ( … )`, `|| sh -c '…'`,
`|| if … fi`, `|| case … esac`, avec préfixes de chemin et `command`. Quatre
tours de revue indépendante consécutifs n'ont produit que des variantes de cette
même liste, et trois d'entre elles ont été MESURÉES en défaut :

```sh
python3 gate.py || exit 00     # était accepté — le motif exigeait le texte exact « exit 0 »
python3 gate.py || env true    # était accepté — « env » n'était pas un préfixe reconnu
python3 gate.py || nice true   # était accepté — idem ; la liste des porteurs est OUVERTE
```

`env`, `nice`, `timeout`, `xargs`, `env -i`, … : l'ensemble des programmes qui
lancent `true` n'est pas énumérable, et l'orthographe d'une sortie nulle non plus
— `exit 00`, `exit 000`, `exit 256` rendent tous 0 (MESURÉ dans bash, dash et
sh, le shell tronquant modulo 256). Chaque tour fermait une instance et laissait
la classe ouverte. Seule l'exigence INVERSE la ferme.

### Les formes admises, établies par mesure

Une branche propage l'échec si, et seulement si, sa **dernière commande** — seule
à fixer le code de retour — est l'une des formes suivantes :

| Forme admise | Mesure |
|---|---|
| `exit N` / `return N`, `N` littéral décimal **entier**, `N % 256 ≠ 0` | `exit 1` → 1 ; `exit 00`, `exit 000`, `exit 256` → 0 ; `exit 0x0`, `exit 1x` → 2 (erreur d'usage) |
| `false`, y compris `/bin/false` et `command false` | `false` → 1 |
| `sh -c '<script>'` dont le script propage, **récursivement** | `sh -c 'exit 1'` → 1 |
| groupe `{ … }` / `( … )` dont le corps propage, **récursivement** | le corps décide du statut du groupe |
| `if` / `case` dont **chaque** branche exécutable propage, **récursivement** | la branche prise décide du statut |

Tout le reste est **refusé** : commande inconnue, `env true`, appel de script,
branche vide, forme non analysable, profondeur d'imbrication dépassée. Un
argument non décimal n'est jamais lu par son préfixe : `exit 1x` serait sinon
certifié propageant alors que le shell le rejette (MESURÉ à 2).

### Un repli vers une commande EXTERNE est refusé

C'est la conséquence la plus visible de l'inversion, et elle est **délibérée**.
`|| bash recuperation.sh`, `|| true_story`, `|| /usr/bin/true_story`,
`|| :mon_label` sont refusés dans un job requis : ce sont des programmes dont le
gate ne peut pas décider statiquement le code de retour.

La raison n'est pas la méfiance mais l'**absence de critère** : rien ne sépare
`bash recuperation.sh` de `env true`. Les deux sont un exécutable externe lancé
après `||`. Toute exemption de cette classe rouvre l'énumération des porteurs de
commande — `env`, `nice`, `timeout`, `xargs`, … — qui ne converge pas. La borne
de mot reste correcte par ailleurs (`true_story` n'est pas `true`, `:mon_label`
n'est pas `:`) : ces formes ne sont pas signalées comme « succès forcé », elles
sont signalées comme **non prouvées**.

Dans un job requis, un repli doit DIRE ce qu'il fait de l'échec. La réécriture
tient en une accolade et une sortie, et elle est prouvée VERTE :

```sh
python3 gate.py || bash recuperation.sh              # refusé  — sortie non prouvée
python3 gate.py || { bash recuperation.sh; exit 1; } # accepté — la sortie est écrite
```

```sh
python3 gate.py || exit 1                             # accepté — sortie non nulle littérale
python3 gate.py || false                              # accepté — échoue toujours
python3 gate.py || { echo "échec" >&2; exit 1; }      # accepté — le groupe propage
python3 gate.py || { echo "échec" >&2; false; }       # accepté — statut non nul
python3 gate.py || sh -c 'exit 1'                     # accepté — le script propage
python3 gate.py || if a; then exit 1; else exit 2; fi # accepté — chaque branche propage
python3 gate.py --motif '|| true'                     # accepté — cité, donc donnée
python3 gate.py && /usr/bin/true                      # accepté — « && » n'est pas un repli

python3 gate.py || true                # refusé — succès forcé
python3 gate.py || /usr/bin/true       # refusé — même binaire, même repli
python3 gate.py || command true        # refusé — « command » ne fait que lancer true
python3 gate.py || exit 00             # refusé — la VALEUR est 0, pas l'orthographe
python3 gate.py || exit 0x0            # refusé — pas un littéral décimal entier
python3 gate.py || env true            # refusé — porteur de commande
python3 gate.py || /usr/bin/env true   # refusé — le chemin ne change rien
python3 gate.py || nice true           # refusé — idem
python3 gate.py || timeout 1 true      # refusé — idem
python3 gate.py || outil_maison        # refusé — l'inconnu bloque
python3 gate.py || bash recuperation.sh # refusé — un script ne prouve pas sa sortie
python3 gate.py || { :; }              # refusé — échec absorbé
python3 gate.py || { echo "gate ignoré" >&2; } # refusé — journalise puis réussit
python3 gate.py || ( : )               # refusé — sous-shell équivalent
python3 gate.py || { echo "toléré"; exit 0; } # refusé — sortie nulle
```

Les parenthèses internes d'une substitution `$( … )` sont traversées sans
refermer le groupe prématurément ; un motif écrit dans une chaîne shell reste une
donnée, jamais du code ; et la dernière commande d'une suite est lue **composés
traversés entiers**, si bien qu'un corps terminé par `if … fi` n'est pas réduit
au mot `fi`.

La branche doit enfin être **terminale** : rien ne doit s'enchaîner derrière elle
autrement que par `;`, un retour à la ligne, `&&` ou `||`. Dans un tube, c'est le
dernier maillon qui fixe le statut, pas la branche — MESURÉ dans bash :

```sh
python3 gate.py || false | true       # refusé — le tube rend 0
python3 gate.py || { exit 1; } | true # refusé — le groupe propage, le tube l'annule
python3 gate.py || false              # accepté — la branche décide seule
```

Un `||` dans un job **non requis** n'est pas concerné : ces jobs n'attestent rien,
et y interdire le repli ferait du durcissement une interdiction générale.

### Ce que l'inversion coûte, sciemment

Outre les commandes externes traitées ci-dessus, elle refuse `|| exit $?` et
`|| foo | bar`, qui propagent réellement sans le **prouver**. Le remède est
toujours le même : écrire la sortie.

La règle s'applique à **tout** `||` de l'étape, y compris hors position de
repli, et deux formes légitimes en font MESURÉMENT les frais :

```sh
if [ -f a ] || [ -f b ]; then exit 1; fi   # refusé — « || » en CONDITION
VAL=$(a || b); python3 gate.py             # refusé — « || » en SUBSTITUTION
```

Ni l'un ni l'autre n'absorbe l'échec d'un contrôle, mais les exempter rouvrirait
la brèche : `if gate.py || true; then echo ok; else exit 1; fi` rend l'étape
VERTE avec son gate rouge — le `|| true` force la condition à vrai, le `then` est
pris, et la branche `else` que le gate mesure n'est jamais exécutée. Exempter la
condition rendrait cette forme acceptable. Le refus reste donc entier ; l'écrire
autrement le lève (`if [ -f a ]; then exit 1; elif [ -f b ]; then exit 1; fi`).

C'est le prix assumé du fail-closed : un refus se corrige à l'écriture, une
absorption silencieuse se découvre en production. Le contrôle a été mesuré à
`rc=0` sur les workflows réels du dépôt, qui n'emploient aucun `||` : aucune
étape réelle n'est refusée à tort aujourd'hui.

### Conditionnelle de repli : `|| if … fi` et `|| case … esac`

Une conditionnelle placée derrière `||` est un repli comme un autre : elle ne
s'exécute que si le contrôle a échoué, et son code de retour devient celui de
l'étape. MESURÉ, elle échappait à tous les motifs — le `||` exempte la gauche de
l'`errexit`, le `fi` rend 0, et l'étape passe au vert avec son contrôle rouge.

Le critère est celui des groupes : **chaque branche exécutable doit se terminer
par une sortie non nulle prouvée**.

```sh
python3 gate.py || if true; then :; fi                 # refusé — le fi rend 0
python3 gate.py || if true; then exit 1; else echo x; fi # refusé — le else absorbe
python3 gate.py || case x in *) : ;; esac              # refusé — même absorption
python3 gate.py || if verifier; fi                     # refusé — aucune branche lisible

python3 gate.py || if true; then exit 1; fi            # accepté — la branche propage
python3 gate.py || if a; then exit 1; elif b; then exit 2; else exit 3; fi  # accepté
python3 gate.py || case x in *) exit 1 ;; esac         # accepté
python3 gate.py --motif '|| if true; then :; fi'       # accepté — repli cité, non exécuté
```

Le `case` est traité au même critère que le `if`, et non laissé de côté : le gate
les tokenise déjà comme la même conditionnelle, si bien que fermer le seul `if`
rendrait le contournement disponible au mot-clé voisin.

Deux textes ne sont **pas** des branches et ne sont donc jamais jugés : la
condition d'un `if`/`elif`, qui est évaluée et non exécutée en repli, et le motif
d'un `case`, qui filtre. Les juger refuserait un repli qui propage pourtant
l'échec par chacune de ses branches.

Une conditionnelle dont **aucune** branche ne se laisse isoler est refusée. Elle
ne prouve rien du sort de l'échec, et la traiter comme propageante rendrait le
contrôle muet devant la première syntaxe que le lecteur de jetons ne sait pas
suivre — soit le contournement suivant tout trouvé.

### Shell lancé en repli : `|| sh -c '…'`

Un shell appelé en repli exécute le script passé à `-c`, et ce script devient le
code de retour de l'étape. La neutralisation des quotes — celle qui empêche de
signaler un repli simplement **cité** — effaçait aussi ce script, si bien
qu'aucun motif ne s'appliquait plus : la forme était acceptée alors qu'elle
repeint en vert n'importe quel contrôle requis.

Le critère est celui de la liste blanche, appliqué **récursivement** au script :
c'est la commande qui fixe son code de retour qui doit prouver la propagation.

```sh
python3 gate.py || sh -c 'exit 0'          # refusé  — le repli réussit toujours
python3 gate.py || bash -c 'exit 0'        # refusé  — même forme, autre shell
python3 gate.py || /bin/sh -ec 'echo ko'   # refusé  — options groupées, echo réussit
python3 gate.py || sh -c 'verif || true'   # refusé  — repli imbriqué
python3 gate.py || sh -c 'exit 1'          # accepté — l'échec est propagé
python3 gate.py || bash recuperation.sh    # refusé  — un script ne prouve pas sa sortie
echo "gate || sh -c 'exit 0'"              # accepté — cité, donc donnée
```

L'appel est repéré sur le texte **neutralisé** — un repli écrit dans une chaîne y
est effacé, donc jamais signalé — puis le script est lu à la même position dans
le texte d'origine, la neutralisation conservant les positions.

## Gardes `if !` et désarmement d'errexit

Une commande testée par `if !` est **exempte d'`errexit`** : ce n'est plus elle
mais la branche `then` qui fixe le code de retour de l'étape. Le critère est donc
exactement celui des groupes de repli — la branche propage-t-elle l'échec ?

```sh
if ! python3 gate.py; then :; fi                  # refusé — l'échec est avalé
if ! python3 gate.py; then echo ko >&2; fi        # refusé — journalise puis réussit
if ! test -f rapport.json; then exit 1; fi        # accepté — l'échec est propagé
```

Seule la **première** branche d'un `if !` est jugée : elle seule s'exécute quand
la commande gardée échoue. Une branche `elif`/`else` du même bloc s'exécute au
contraire quand la commande a réussi, et n'absorbe donc aucun échec. Les formes
non niées relèvent de la règle suivante, qui sépare la sonde du contrôle.

`set +e` désarme `errexit` pour **tout le reste de l'étape** : tout échec ultérieur
devient invisible. La forme longue `set +o errexit` est traitée à égalité. Les
autres options restent libres, car elles ne changent rien à la propagation :

```sh
set +e            # refusé — plus aucun échec n'interrompt l'étape
set +o errexit    # refusé — même effet, écrit autrement
set -e            # accepté — c'est la bonne pratique
set +x            # accepté — couper la trace ne masque aucun échec
```

Cette règle est indépendante de la garde sur les `exit 0` nus décrite plus haut :
elle couvre notamment la forme dont la sortie nulle est conditionnelle, que la
garde précédente accepte à juste titre alors que le groupe, lui, réussit quand
même.

```sh
python3 gate.py || ( if true; then exit 0; fi )    # refusé par la règle des groupes
```

## Contrôle du dépôt en condition `if` sans négation

Retirer le `!` ne rend pas la forme sûre. Quand le contrôle échoue, la branche
`then` n'est pas prise : sans `else`, **rien** ne s'exécute, le `fi` rend 0 et
l'étape est verte avec un contrôle rouge. La branche jugée est donc celle qui
s'exécute à l'échec — le `else` — et le critère de propagation reste exactement
celui des groupes de repli.

```sh
if python3 gate.py; then :; fi                      # refusé — rien ne s'exécute à l'échec
if python3 gate.py; then echo ok; fi                # refusé — la trace ne propage rien
if bash scripts/verifier.sh; then echo ok; fi       # refusé — script du dépôt en condition
if python3 gate.py; then echo ok; else exit 1; fi   # accepté — le `else` propage l'échec
```

Une chaîne `elif` ne dispense d'aucune branche. Quand le contrôle échoue, le
shell évalue les conditions suivantes puis exécute **le corps** retenu — celui
d'un `elif` vrai, sinon le `else`, sinon rien. Toutes ces issues sont mesurées :

```sh
if gate.py; then echo ok; elif c; then exit 1; else echo x; fi  # refusé — le `else` absorbe
if gate.py; then echo ok; elif c; then echo x; else exit 1; fi  # refusé — le corps d'`elif` absorbe
if gate.py; then echo ok; elif c; then exit 1; fi               # refusé — sans `else`, le `fi` rend 0
if gate.py; then echo ok; elif c; then exit 1; else exit 2; fi  # accepté — toutes propagent
```

MESURÉ avant correction : la seule branche relevée était la **condition** du
premier `elif`, tenue pour propageante dès qu'elle s'écrivait `false`, et le
corps du `else` n'était jamais lu. Un `elif` suffisait à rendre la garde muette.
Une condition n'est pas une branche : seuls les corps ouverts par `then` et
`else` en sont.

Sur une garde **niée** `if ! contrôle`, la frontière reste inchangée : seule la
première branche `then` s'exécute quand le contrôle échoue, et un `elif`
propageant du même bloc ne rachète rien.

La règle ne vise que les **contrôles versionnés ici** : un chemin suffixé `.py`
ou `.sh`, ou situé sous `scripts/`, `core/scripts/`, `tools/`. Une **sonde**
shell (`[`, `[[`, `test`, `command`, `grep`, `git`) interroge un état : son code
de retour EST la question posée, jamais le verdict d'un contrôle. Citer un chemin
du dépôt en ARGUMENT d'une sonde ne l'exécute pas.

```sh
if [ -z "$CODE_CHANGE" ]; then exit 0; fi       # accepté — aiguillage réel du job proof-sealed
if command -v docker; then echo présent; fi     # accepté — sonde de présence
if git diff --quiet; then echo rien; fi         # accepté — sonde d'état
if [ -f core/scripts/verify.py ]; then :; fi    # accepté — le chemin est un argument, pas un appel
```

### Limites

Ce que la règle **ne couvre pas**, et pourquoi elle n'a pas été fermée :

- **Un outil installé mis en condition.** `if mypy core/; then :; fi` absorbe
  réellement l'échec, mais `mypy` n'est pas un chemin du dépôt : rien ne le
  distingue d'une sonde comme `if command -v mypy`. Une liste blanche d'outils
  « qui comptent » refuserait des sondes légitimes nommant un binaire et se
  périmerait à chaque outil ajouté. Non fermé, sciemment.
- **Un contrôle appelé indirectement.** `CTRL=scripts/x.py; if $CTRL; then …` :
  le nom du script n'apparaît pas dans la condition, seule une variable.
- **Une propagation différée.** `if ctrl; then S=ok; else S=ko; fi` suivi de
  `[ "$S" = ok ] || exit 1` est refusé alors que l'échec finit par sortir :
  suivre un statut à travers une variable demanderait un interpréteur shell. La
  règle `if !` a la même limite depuis son origine (mesuré sur le motif nié
  équivalent) ; écrire `else exit 1` lève le refus.
- **Un repli qui propage sans le prouver.** `|| bash recuperation.sh`,
  `|| true_story`, `|| exit $?` sortent parfois en non nul, mais aucune lecture
  statique ne le démontre. Ce n'est PAS une limite subie : c'est la règle
  décidée — la liste blanche des replis. Refus conservateur, jamais silence, et
  corrigeable en écrivant la sortie (`|| { bash recuperation.sh; exit 1; }`).

Le principe tenu : refuser ce qui est prouvé absorbant, et **nommer** ce qui
passe. Un manque nommé se corrige ; un manque implicite se découvre en production.

## Conditionnelles shell et `exit 0`

Un `exit 0` situé dans une branche conditionnelle est légitime : il exprime une
sortie choisie, pas un contournement. Le gate distingue les deux en lisant les
ouvertures (`if`, `case`), les fermetures (`fi`, `esac`) et les sorties **dans
leur ordre d'apparition**, y compris plusieurs fois sur une même ligne.

```sh
if true; then exit 0; fi        # accepté — la sortie est conditionnelle
if false; then :; fi; exit 0    # refusé  — la sortie est après le `fi`
```

Raisonner ligne par ligne ne suffit pas : sur la seconde forme, la présence d'un
`if` quelque part sur la ligne couvrirait à tort tout ce qui suit.

Les mots-clés ne comptent qu'en **position de commande** (début de ligne, ou
après `;`, `|`, `&`, `(`, `then`, `do`, `else`). Sans cette borne, une option
longue ouvrirait une garde imaginaire et masquerait un contournement réel :

```sh
grep --ignore-case motif fichier; exit 0    # refusé — `case` n'ouvre rien ici
```

### La sortie NUE se juge sur sa VALEUR, comme la sortie d'un repli

Les deux chemins qui lisent une sortie posent la même question — *ce littéral
rend-il le statut 0 ?* — et ils consomment désormais le **même prédicat**
(`_sortie_litterale_est_nulle` : `N % 256 == 0`). Avant unification, le chemin de
repli jugeait la VALEUR pendant que le chemin direct exigeait l'ORTHOGRAPHE
exacte `0`, si bien que la même écriture recevait deux verdicts opposés :

| Commande dans un job requis | Avant | Après |
|---|---|---|
| `gate.py; exit 0` | refusé | refusé |
| `gate.py; exit 00` | **accepté** | refusé |
| `gate.py; exit 000` | **accepté** | refusé |
| `gate.py; exit 256` | **accepté** | refusé |
| `gate.py \|\| exit 00` | refusé | refusé |

MESURÉ dans bash, dash et sh : `exit 00`, `exit 000`, `exit 256` et `exit 0512`
rendent tous `0` — le statut est le littéral modulo 256. Ajouter un cas
particulier pour `00` aurait laissé la classe entière ouverte ; c'est le prédicat
qui est partagé, pas la liste des orthographes.

Élargir la **capture** sans élargir le **verdict** est ce qui préserve les deux
gardes. `exit 1` est maintenant reconnu comme sortie puis laissé passer sur sa
valeur, et une sortie nulle reste licite sous une garde conditionnelle, quelle
que soit son orthographe :

```sh
gate.py; exit 1                 # accepté — 1 % 256 ≠ 0, l'étape échoue bien
if true; then exit 00; fi       # accepté — la garde vaut pour toutes les orthographes
```

**Ce que les deux chemins font de l'INCONNU diverge, et c'est voulu.** Un
argument qui n'est pas un littéral décimal — `exit 0x0`, `exit 1x`, `exit 12abc`
— rend `2` dans bash, dash et sh (erreur d'usage) : il ne force donc aucun
succès, et le chemin direct, qui **détecte** le succès forcé, ne le signale pas.
Le chemin de repli le refuse au contraire, non par un autre prédicat de valeur
mais parce qu'il pose la question INVERSE : il exige la **preuve** que la branche
propage l'échec du contrôle, et un statut 2 d'erreur d'usage ne prouve rien de
tel. Liste noire d'un côté, liste blanche de l'autre — même prédicat au centre.

```sh
gate.py; exit 0x0               # accepté  — le shell rend 2, l'étape échoue
gate.py || exit 0x0             # refusé   — la propagation n'est pas prouvée
```

## Périmètre déclaré des lanceurs

`SCOPE_ROOT_OMITTED` protège les lanceurs `core/scripts/run_*.py` contre le
rétrécissement silencieux du périmètre défini par `python_roots`. Une collection
littérale de chaînes est comparée aux racines contractuelles, et toute racine
manquante est refusée.

Le contrôle ne dépendait autrefois que du **reste** : il exigeait qu'au moins une
racine survive à côté des manquantes. Cette condition ouvrait la sortie
exactement inverse de son intention — retirer TOUTES les racines d'un coup
rendait la règle muette, alors que c'est la façon la plus complète de désarmer un
scan :

```python
argv = ["bandit", "-r", "core/src", "core/scripts", "tools/proof"]  # refusé — 1 racine omise
argv = ["bandit", "-r", "core/src"]                                 # refusé — 3 racines omises
argv = ["bandit", "-r", "src"]                                      # refusé — toutes omises
MESSAGES = ["analyse terminee", "aucun defaut releve"]              # accepté — pas un périmètre
```

Ce qui autorise le jugement d'une collection sans aucune racine survivante n'est
pas son contenu mais son **contexte**, seul capable de prouver qu'elle déclare un
périmètre. Sans cette preuve, la moindre liste de messages ou de drapeaux d'un
lanceur deviendrait un faux positif. Quatre contextes valent preuve :

| Contexte | Exemple |
|---|---|
| affectation à un nom de périmètre | `argv = [...]`, `cibles = [...]` |
| affectation à un attribut de périmètre | `configuration.racines = [...]` |
| affectation annotée | `cibles: list[str] = [...]` |
| argument nommé, ou argument d'un appel qui l'annonce | `lancer(scopes=[...])`, `definir_racines([...])` |

Un nom « de périmètre » est reconnu **mot à mot** après découpage sur ses
séparateurs — `argv`, `cible`, `perimetre`, `racine`, `root`, `scope`, `target`,
au singulier comme au pluriel — jamais par sous-chaîne, pour qu'un mot qui
contient ces lettres par hasard ne déclenche rien. `python_roots` et `cibles`
sont donc des déclarations de périmètre ; `MESSAGES` n'en est pas une.

Limite assumée : une collection **anonyme** dont toutes les racines ont été
retirées reste non jugée, faute de tout indice de son rôle. La borne est celle du
nommage, et elle est mesurée — l'auto-scan du dépôt reste à zéro violation, ce
qui prouve qu'aucun lanceur existant n'est faussement signalé. Conséquence pour
les contributeurs : dans un `run_*.py`, une commande littérale sans rapport avec
le périmètre ne doit pas être liée à un nom de périmètre.

### Périmètre dérivé des racines sans valeur décidable

Le contrôle des omissions ne sait lire que les collections **littérales** : toute
autre valeur le rendait muet. Or retirer des racines ne demande alors qu'une
transformation opaque de leur source, qui réduit le périmètre d'un contrôle
requis sans qu'aucune règle ne s'applique. Ces déclarations sont désormais
refusées par `SCOPE_FILTRE_INDECIDABLE`.

```python
racines = charger_racines_qualite()[:1]          # refusé — troncature indécidable
racines = list(charger_racines_contractuelles())[:1]  # refusé — le wrapper ne change rien
racines = python_roots[1:]                       # refusé — même retrait, autre écriture
racines = charger_racines_qualite()              # accepté — délégation au contrat
racines = contrat.get("python_roots")            # accepté — le contrat fait foi
racines = [c for c in python_roots if c.exists()]  # accepté — filtre décidable
argv = [str(interpreteur), "-m", "pytest", *args]  # accepté — étranger aux racines
```

Le critère est l'**indécidabilité**, jamais la forme du wrapper : déplier
`list(…)` puis `sorted(…)` puis le suivant serait une course sans fin, et chaque
forme oubliée un trou. Trois exclusions bornent la règle à ce qu'elle sait
juger : la **source** elle-même — décidable par délégation au contrat, c'est la
forme attendue d'un lanceur ; les **compréhensions** sur les racines, qui ont
leurs juges dédiés et seraient sinon condamnées deux fois ; les **valeurs
littérales**, déjà jugées par la règle des omissions.

#### La CLÉ contractuelle prouve la source, pas le nom de l'appelé

Une source de racines se reconnaissait à son NOM : celui de la collection
(`racines`, `python_roots`, `scopes`…) ou celui de l'appelé, qui devait contenir
« racine » ou « root ». Or un lanceur lit le contrat par une méthode d'accès
générique, dont le nom — `get` — ne contient ni l'un ni l'autre. La troncature
échappait donc au contrôle, alors que le témoin par appel nommé était bien
signalé. MESURÉ avant correction :

```python
racines = contrat.get("python_roots")[:1]        # NON signalé — angle mort
racines = charger_racines_qualite()[:1]          # signalé — témoin
```

Le porteur de sens est la **clé demandée**, seule à nommer le champ contractuel
des racines dans `core/quality-scopes.toml`. Deux formes d'accès sont retenues,
et ce sont celles que le dépôt écrit : l'**indexation** `contrat["python_roots"]`
et l'**appel dont le premier argument est la clé** — `contrat.get("python_roots")`
avec ou sans valeur par défaut, la forme employée par `run_security_scan`,
`run_pack_validation` et `run_codeql_scan`. Le **déballage**
`[*contrat.get("python_roots")]` n'a besoin d'aucune règle propre : l'accès qu'il
enveloppe est retrouvé par le parcours de l'expression.

```python
racines = contrat.get("python_roots")[:1]        # refusé — troncature de la lecture
racines = contrat["python_roots"][:1]            # refusé — même retrait, autre accès
racines = contrat.get("python_roots", [])[:1]    # refusé — la valeur par défaut ne change rien
racines = [*contrat.get("python_roots")][:1]     # refusé — le déballage ne masque rien
racines = contrat["python_roots"]                # accepté — lecture intégrale
racines = contrat.get("python_roots", [])        # accepté — lecture intégrale
```

Une **tranche** n'est pas une clé littérale : `[:1]` ne peut jamais être pris
pour la lecture qu'il réduit. Le nom de l'appelé est délibérément ignoré — c'est
la clé qui décide, jamais l'orthographe de la méthode d'accès.

#### CodeQL : l'inclusion doit d'abord exclure

`core/scripts/run_codeql_scan.py` transmet le périmètre au CLI CodeQL via
`LGTM_INDEX_FILTERS`. Le filtre commence par `exclude:**/*`, puis ajoute une
ligne `include:<racine>/**` pour chaque racine du contrat. Les cinq racines
doivent toutes exister : une racine absente fait échouer le chargeur en
fail-closed au lieu de réduire silencieusement le périmètre. Cette forme est
volontaire : une liste composée uniquement d'inclusions laisse le reste de
l'arbre indexable par le CLI et produit des findings hors contrat.
Le test `core/tests/bootstrap/test_security_tool_scope.py` capture
l'environnement réellement passé à l'exécuteur et verrouille l'ordre ainsi que
les cinq racines. Le scan CodeQL local doit ensuite être rejoué ; tout finding
dans les racines autorisées reste un résultat à corriger ou à justifier
individuellement, jamais une raison d'élargir silencieusement le périmètre.

Le rôle est prouvé **deux fois** : par le contexte de déclaration, et par la
présence de la source des racines dans l'expression. MESURÉ sur ce dépôt : le
seul contexte de déclaration retient **16 expressions légitimes** des lanceurs —
chemins du dépôt, lectures du contrat, lignes de commande — que juger produirait
autant de faux positifs, soit la pression exacte qui fait désarmer un gate.

Limite assumée, symétrique de celle du nommage : une indirection qui ne nomme ni
racine ni source (`ARGV = [UNE_CONSTANTE]`) reste hors de portée du contrôle
statique. Le rejugement du dépôt entier, chaque fichier traité comme un ajout,
confirme **0 fichier réel nouvellement signalé** par cette règle.

## Oracles de test reconnus

`TEST_WITHOUT_ORACLE` exige qu'un test ajouté ou modifié vérifie quelque chose.
Comptent comme oracles : `assert`, `pytest.raises`, `pytest.fail` et les méthodes
`assert…` d'`unittest`.

Cette dernière forme n'est reconnue que **prouvée**. Accepter tout appel dont
l'attribut commence par `assert` suffisait à fabriquer un oracle de façade : il
suffisait de nommer ainsi une méthode métier pour faire passer un test qui ne
vérifie rien.

```python
class Silencieux:
    def assert_rien(self) -> int:
        return 1

def test_c() -> None:
    Silencieux().assert_rien()        # REFUSÉ — aucun oracle, malgré le nom
```

Deux preuves sont désormais exigées ensemble : l'appel est porté par le
**receveur** de la méthode (son premier paramètre, `self` par convention mais
librement renommable) **et** la classe hérite réellement d'`unittest.TestCase`.
L'héritage est résolu comme ailleurs dans le gate — alias d'import compris — et
**transitivement**, afin qu'un socle de tests partagé reste reconnu :

```python
import unittest
class Suite(unittest.TestCase):
    def test_ok(self) -> None:
        self.assertEqual(1, 1)        # accepté — héritage prouvé

from unittest import TestCase as Cas
class Suite(Cas): ...                 # accepté — alias prouvé

class Base(unittest.TestCase): ...
class Suite(Base): ...                # accepté — héritage transitif

class Suite:                          # aucun import unittest
    def test_ok(self) -> None:
        self.assertEqual(1, 1)        # REFUSÉ — `self` seul ne prouve rien
```

L'`assert` nu et `pytest.raises` restent les oracles de référence du dépôt,
inchangés : le durcissement ne retire que ce qui n'était jamais prouvé.

### Un oracle ne compte que dans la portée PROPRE du test

MESURÉ : la recherche parcourait tout l'arbre, si bien que l'`assert` d'une
fonction interne **jamais appelée** comptait comme oracle du test qui l'entoure.
Le test ne vérifiait pourtant rien à l'exécution.

```python
def test_x() -> None:
    def oracle() -> None:
        assert False          # REFUSÉ — portée jamais exécutée
    return
```

Fonctions, lambdas et classes imbriquées ouvrent leur propre portée et sont
écartées. Un **bloc** n'en ouvre aucune : son oracle appartient au corps du test
et compte comme lui.

```python
def test_boucle() -> None:
    for valeur in [1]:
        assert valeur         # accepté — la boucle est le corps du test

def test_contexte() -> None:
    for cas in [1, 2]:
        with pytest.raises(ValueError):
            calculer(cas)     # accepté — bloc, jamais portée
```

Boucle, condition, gestionnaire de contexte, `try` et `match` sont donc traités
à égalité avec le premier niveau. Le parcours réutilise l'utilitaire de portée
déjà employé pour les liaisons `global` : deux parcours de portée seraient deux
règles à maintenir, donc deux occasions de diverger.

La conséquence est assumée : un test dont l'oracle est déporté dans une fonction
auxiliaire **appelée** est désormais refusé lui aussi. Distinguer l'auxiliaire
appelé de l'auxiliaire mort demanderait de suivre les appels, ce que le gate ne
fait pas ; l'incertitude se tranche en faveur du contrôle, et l'oracle
s'écrit dans le test.

Les **alias d'import** y sont résolus par le même mécanisme que pour les sauts :
renommer l'import ne change rien à ce que l'oracle vérifie, et refuser un test
légitime pousse les contributeurs à désarmer le gate.

```python
import pytest        ->  with pytest.raises(ValueError):   # accepté
import pytest as pt  ->  with pt.raises(ValueError):       # accepté — alias prouvé
import pytest as pt  ->  pt.fail('chemin jamais atteint')  # accepté — alias prouvé
import mon_module    ->  with mon_module.raises(...):      # aucun oracle — origine non prouvée
```

La qualification par l'origine est conservée en sens inverse : un `raises` porté
par un module dont l'import ne prouve pas qu'il s'agit de pytest ne vérifie rien
et ne vaut pas oracle.

#### L'oracle importé directement

`from pytest import raises` est la forme courante de l'oracle, et le gate la
refusait. MESURÉ : `TEST_WITHOUT_ORACLE` était émis sur cet idiome alors que
`import pytest` puis `pytest.raises` était accepté — et alors que le gate traçait
DÉJÀ les imports directs de `skip` et de `mark` pour détecter les sauts. Un faux
positif sur une forme aussi répandue coûte autant qu'un angle mort : il se paie
du désarmement du gate par ceux qu'il gêne.

Le nom nu est désormais reconnu par le même mécanisme que les sauts — l'origine
est prouvée par l'import, jamais par l'orthographe.

```python
from pytest import raises      ->  with raises(ValueError):  # accepté
from pytest import fail        ->  fail('jamais atteint')    # accepté
from pytest import raises as leve -> with leve(ValueError):  # accepté — alias prouvé

from mon_module import raises  ->  with raises(ValueError):  # aucun oracle — origine non prouvée
from pytest import raises
raises = mon_module.raises     ->  with raises(ValueError):  # aucun oracle — preuve détruite
```

L'**asymétrie des positions** est celle de l'exécution et vaut pour les deux
formes : `raises` n'est lu qu'en tête d'un `with`, `fail` qu'en appel. Un
`raises(...)` écrit hors d'un `with` n'entre jamais dans le gestionnaire de
contexte et ne vérifie donc rien.

```python
from pytest import raises  ->  raises(ValueError)            # aucun oracle — hors `with`
import pytest              ->  pytest.raises(ValueError)     # aucun oracle — même raison
```

## Corps de classe réduit à un stub

Le corps d'une classe s'exécute à la création de la classe : réduit à `pass` ou à
une ellipse, il ne déclare rien de plus que son en-tête et relève exactement de
la même dette qu'un corps de fonction vide. La règle des fonctions s'y applique
à l'identique, docstring seule comprise — documenter un vide ne le remplit pas.

```python
class Service:            pass         # refusé — EXECUTABLE_PASS
class Service:            ...          # refusé — EXECUTABLE_ELLIPSIS
class Service:            """Doc."""   # refusé — DOCSTRING_ONLY_BODY
class Service(Base):      pass         # refusé — hériter n'implémente rien
```

**Un type d'exception en est exempté, et lui seul.** `class Panne(ValueError):
pass` est du code COMPLET : l'identité du type est tout son contenu, puisqu'elle
se lève et se rattrape sélectivement — il n'y a rien d'autre à écrire.

```python
class MonErreur(ValueError):   pass            # accepté — type d'exception
class MonErreur(RuntimeError): """Doc."""      # accepté — même idiome, documenté
class Racine(ValueError):      """Doc."""
class Fille(Racine):           pass            # accepté — héritage transitif
```

MESURÉ sur les racines contractuelles de ce dépôt au moment de l'ajout de la
règle : **21 des 99 classes** ont un corps vide, et **toutes** sont des types
d'exception. Les signaler produirait 21 faux positifs sur un idiome Python
courant, ce qui pousserait à désarmer le gate au lieu de le respecter.

L'exemption tient à la NATURE du type, jamais au simple fait d'hériter : les
noms d'exceptions sont lus dans `builtins` à l'import du gate — jamais recopiés,
donc jamais incomplets — et l'héritage est résolu transitivement dans le module.

Elle est attachée à la **définition** exempte, repérée par sa position, et non à
son nom. Exempter par nom faisait dépendre la règle d'une collision entre
portées : une classe déclarée ailleurs, n'héritant de rien, devenait exempte du
seul fait qu'un type d'exception du module portait le même nom — un
contournement d'un seul renommage.

```python
class Panne(ValueError):
    pass                  # accepté — type d'exception du module

def configurer() -> None:
    class Panne:
        pass              # refusé — n'hérite de rien, l'homonymie ne prouve rien
```

Les noms restent l'unité de **résolution** des bases, faute d'autre lien statique
entre une base et sa définition ; ils ne sont plus l'unité d'**exemption**. La
même correction vaut pour les cas de test `unittest` : les oracles `self.assert…`
ne sont reconnus que dans la sous-classe réellement dérivée de `TestCase`.

### Le nom d'une exception ne prouve rien à lui seul

Lire les noms dans `builtins` garantit la LISTE, pas que le nom écrit dans un
fichier désigne encore ce qu'il nomme. Les deux formes de base exigent donc une
preuve supplémentaire.

**Forme qualifiée : c'est le PORTEUR qui doit être prouvé**, jamais l'orthographe
de l'attribut. Une classe déclarant un attribut homonyme suffisait à exempter
n'importe quel corps vide derrière un porteur inventé en deux lignes.

```python
class Faux:
    ValueError = object

class Service(Faux.ValueError):
    pass                     # refusé — Faux.ValueError EST object
```

```python
import builtins
class MonErreur(builtins.ValueError): pass   # accepté — porteur prouvé par import
import builtins as b
class MonErreur(b.ValueError):        pass   # accepté — l'alias prouve autant
class Service(builtins.ValueError):   pass   # refusé  — aucun import ne lie le nom
```

**Forme nue : le nom ne doit pas avoir été relié localement.** Une affectation du
module comme un import détournent le nom vers autre chose, et l'exemption tombe
avec l'origine.

```python
ValueError = object
class Service(ValueError): pass              # refusé — hérite en réalité d'object

from transport import ValueError
class Service(ValueError): pass              # refusé — origine inconnue

from builtins import ValueError
class MonErreur(ValueError): pass            # accepté — l'origine est prouvée
```

Le retrait par import est réservé aux noms d'exception : ailleurs, un import est
justement ce qui PROUVE l'alias, et l'y appliquer effacerait la preuve qu'il vient
d'établir.

### La base d'une classe se résout dans SA portée, jamais sur tout l'arbre

L'exemption est attachée à la **définition** exempte, repérée par sa position, et
non à son nom. Cela ne suffisait pas : la **résolution** de la base, elle,
cherchait le nom sur tout l'arbre. MESURÉ, une classe locale héritant d'un
homonyme LOCAL restait exemptée parce que la résolution lui prêtait l'héritage du
type d'exception du module.

```python
class Panne(ValueError):
    pass

def configurer() -> None:
    class Panne:                 # classe ORDINAIRE, locale
        marqueur = 1

    class Service(Panne):
        pass                     # refusé — hérite du Panne LOCAL, qui n'exempte rien
```

Une base nommée est désormais résolue **du plus proche au module**, comme à
l'exécution, et la preuve d'origine par les imports n'est consultée qu'à défaut
de toute liaison locale.

```python
class Panne(ValueError): pass
def configurer() -> None:
    class Service(Panne): pass        # accepté — aucun homonyme local, repli au module

def configurer() -> None:
    class ValueError:                 # usurpe un nom builtin
        marqueur = 1
    class Service(ValueError): pass   # refusé — la définition locale l'emporte

def configurer() -> None:
    ValueError = charger()            # liaison OPAQUE
    class Service(ValueError): pass   # refusé — le nom est lié, l'origine inconnue

class Panne(ValueError): pass
def configurer(Panne) -> None:        # le PARAMÈTRE masque le module
    class Service(Panne): pass        # refusé
```

Une liaison locale **opaque** arrête la résolution sans jamais retomber sur les
imports : le nom désigne alors quelque chose d'inconnu, et consulter les imports
reviendrait à exempter sur la foi d'une orthographe. Un nom déclaré `global` puis
affecté tombe sous cette même règle, et le doit — il réécrit le nom du module
avec une valeur inconnue.

Les **imports** ne comptent pas parmi les liaisons de portée : ils sont ce qui
PROUVE les alias, et les compter ferait passer `from unittest import TestCase`
pour un écrasement du nom, soit un faux positif sur l'idiome le plus courant du
dépôt.

La chaîne des portées suit la règle de Python, pas une approximation : le corps
de classe qui contient **directement** la définition en fait partie, les corps de
classes plus **lointains** n'y participent pas.

```python
class Enveloppe:
    class Panne(ValueError): pass
    class Service(Panne): pass        # accepté — sœur du même corps de classe

class Enveloppe:
    class Panne(ValueError): pass
    def monter(self) -> None:
        class Service(Panne): pass    # refusé — NameError à l'exécution, rien n'est hérité
```

Cette résolution sert les DEUX questions posées à la même fonction : quelle
classe est un type d'exception, et quelle classe est un cas de test `unittest`.
Le même défaut laissait un `TestCase` local usurpé fabriquer un receveur
d'oracles, si bien qu'un `self.assertVrai(...)` passait pour une vérification
héritée de la bibliothèque standard.

#### Le même résolveur tranche aussi `Protocol` et `abstractmethod`

Deux exemptions consultaient encore l'alias du MODULE sans tenir compte du
masquage lexical. L'alias dit ce qu'un nom désigne au niveau du module ; il ne
dit jamais ce qu'il désigne à l'endroit où la base — ou le décorateur — est
écrite. MESURÉ, les quatre formes suivantes étaient acceptées alors que le code
n'hérite de rien et n'abstrait rien.

```python
from typing import Protocol
def f() -> None:
    class Protocol:                    # classe ORDINAIRE, locale
        marqueur = 1
    class C(Protocol):
        def manque(self) -> None: ...  # refusé — hérite du Protocol LOCAL

from typing import Protocol
def f(Protocol) -> None:               # le PARAMÈTRE masque le module
    class C(Protocol):
        def manque(self) -> None: ...  # refusé

from abc import abstractmethod
def f() -> None:
    def abstractmethod(g):             # décorateur local homonyme
        return g
    class C:
        @abstractmethod
        def manque(self) -> None: ...  # refusé — le décorateur n'abstrait rien

import typing as t
def f() -> None:
    class t:                           # le PORTEUR est masqué
        Protocol = object
    class C(t.Protocol):
        def manque(self) -> None: ...  # refusé — t.Protocol vaut object
```

Aucun second résolveur n'a été écrit : la chaîne de portées construite pour les
bases d'exception répond mot pour mot à la même question, et un décorateur
s'évalue exactement là où s'évalueraient les bases d'une classe écrite au même
endroit. En dupliquer un second garantirait de le corriger à moitié.

La garde INVERSE est tenue : sans homonyme, la classe locale reste un protocole
et le décorateur importé garde son exemption.

```python
from typing import Protocol
def fabriquer() -> type:
    class Depot(Protocol):
        def lire(self) -> str: ...     # accepté — aucun homonyme ne masque le nom
    return Depot
```

### Le protocole déclaré par une ellipse

Un **protocole prouvé** dont le corps entier est une ellipse est exempté : il
déclare une interface, exactement comme l'ellipse acceptée méthode par méthode
juste au-dessous. Contrôler le corps des classes avait pour effet de bord de
refuser cette déclaration, alors que la même ellipse restait licite un cran plus
bas — une incohérence interne à la règle.

```python
class Depot(Protocol): ...          # accepté — déclaration d'interface
class Depot(Protocol):
    def lire(self) -> str: ...      # accepté — inchangé
class Depot(Protocol): pass         # refusé  — « pass » ne déclare rien
class Depot(Protocol): """Doc."""   # refusé  — documenter un vide ne le remplit pas
class Service: ...                  # refusé  — classe ordinaire, aucune interface
```

L'exemption s'arrête exactement où s'arrête celle des méthodes : elle exige
l'ellipse — jamais `pass`, jamais une docstring seule — et le **vrai**
`typing.Protocol`, prouvé par les imports du module. Un homonyme local du nom
`Protocol` ne l'obtient pas.

### `typing_extensions` compte à ÉGALITÉ avec `typing`

MESURÉ avant correction : seul le module `typing` était reconnu. Les quatre
écritures du rétroportage étaient signalées `EXECUTABLE_ELLIPSIS` quand le témoin
`from typing import Protocol` passait.

```python
from typing_extensions import Protocol                  # accepté
from typing_extensions import Protocol as Interface     # accepté — alias
import typing_extensions                                # accepté
import typing_extensions as te                          # accepté — alias de module

from typing_extensions import Protocol, runtime_checkable
@runtime_checkable
class Service(Protocol):
    def calculer(self) -> int: ...                      # accepté
```

`typing_extensions` est l'écriture **normale** d'un protocole sur les versions de
Python où `typing` ne l'expose pas encore, et le repli d'import entre les deux
modules est l'idiome courant. Un gate qui refuse du code normal finit désarmé par
ceux qu'il gêne : le faux positif coûte aussi cher que l'angle mort.

La parité est obtenue en versant les deux origines dans les **mêmes ensembles de
preuve**. Toutes les révocations déjà en place s'y appliquent donc sans qu'aucune
ait à être dupliquée — et c'est bien ce qui est vérifié :

```python
from typing_extensions import Protocol
Protocol = object                   # refusé — nom réaffecté

from typing_extensions import Protocol
del Protocol                        # refusé — nom supprimé

import typing_extensions as te
te.Protocol = object                # refusé — attribut prouvant réécrit

import typing_extensions as te
del te.Protocol                     # refusé — attribut prouvant supprimé

from typing_extensions import Protocol
def monter() -> None:
    class Protocol:                 # homonyme local
        marqueur = 1
    class Service(Protocol):
        def calculer(self) -> int: ...   # refusé — masquage lexical
```

**`abc` n'a pas d'équivalent à traiter, et l'absence est mesurée**, pas
supposée : `hasattr(typing_extensions, "abstractmethod")` vaut `False`. Le module
rétroporte `typing`, jamais `abc`. La liste des modules `abc` reste donc
singleton, écrite à la même place et sous la même forme que celle des modules
`typing`, pour qu'un rétroportage futur n'ait qu'un seul endroit à modifier.

## Absence d'implémentation

La sentinelle `NotImplemented` et l'exception `NotImplementedError` sont
refusées à égalité, sous leurs formes nue, appelée, importée sous alias et
qualifiée par attribut. Un attribut du même nom qui n'est pas levé n'est pas
concerné.

### Sous la forme QUALIFIÉE, c'est le PORTEUR qui décide

MESURÉ : la levée de l'attribut **homonyme** porté par un module métier était
refusée sur la seule orthographe de cet attribut, alors qu'un module est libre
de nommer ainsi son propre type d'erreur — qui n'a rien d'un stub. Voir le bloc
ci-dessous pour la forme exacte. La règle voisine sur les
**bases** d'exception exigeait déjà, elle, un porteur prouvé : les deux sont
désormais alignées, et un seul point du code répond à la question pour les deux
chemins qui la posent.

```python
import mon_module
def calculer() -> int:
    raise mon_module.NotImplementedError   # accepté — porteur non prouvé  # proof:allow — exemple de la règle

import builtins
def calculer() -> int:
    raise builtins.NotImplementedError     # refusé — porteur prouvé  # proof:allow — exemple de la règle

import builtins as b
def calculer() -> int:
    raise b.NotImplementedError            # refusé — alias du module prouvé  # proof:allow — exemple de la règle

def calculer() -> int:
    raise NotImplementedError              # refusé — forme NUE, cas principal inchangé  # proof:allow — exemple de la règle
```

La forme **nue** ne dépend d'aucun porteur : elle reste reconnue par la liste des
noms de l'interpréteur, sans qu'aucun import ait à la prouver. C'est le cas
principal, et il n'est pas touché.

Le chemin des **alias construits par affectation** exige le même porteur, sans
quoi le faux positif se déplacerait simplement d'une ligne :

```python
import mon_module
Absence = mon_module.NotImplementedError   # proof:allow — exemple de la règle
def calculer() -> int:
    raise Absence                          # accepté — l'origine n'est pas builtins
```

L'alias construit par **affectation** l'est aussi : le gate résolvait l'alias
d'import, mais le même nom obtenu depuis l'attribut d'un module échappait
entièrement à la règle.

```python
import builtins
Absence = builtins.NotImplementedError  # proof:allow — exemple de la règle, ce motif EST le sujet

def calculer() -> None:
    raise Absence            # refusé — alias prouvé, stub explicite
```

L'exigence de **preuve d'origine** est conservée : seul un nom construit à
partir de `NotImplemented`/`NotImplementedError` est concerné, si bien qu'un
`Absence = mon_module.PanneMetier` reste hors sujet. Cette preuve est appliquée
**après** l'invalidation générale des noms réaffectés : l'affectation qui la
porte est elle-même une réaffectation, et l'appliquer plus tôt reviendrait à
l'effacer avec elle.

#### La destructuration est appariée POSITION par POSITION

La preuve n'était lue que sur une affectation à cible unique. Le tuple de droite
n'étant lui-même ni un nom ni un attribut, MESURÉ, la même absence
d'implémentation passait pour un objet quelconque. Deux erreurs symétriques
étaient possibles, et l'appariement les écarte toutes les deux : ne rien prouver
laissait le stub passer ; tout prouver dès qu'UNE valeur convient ferait de la
position voisine un stub qu'elle n'est pas.

```python
import builtins
A, B = builtins.NotImplementedError, builtins.NotImplemented  # proof:allow — exemple de la règle, ce motif EST le sujet

def f() -> None:
    raise A                     # refusé — la position 0 est prouvée

import builtins, metier
A, B = builtins.NotImplementedError, metier.Erreur  # proof:allow — exemple de la règle, ce motif EST le sujet

def f() -> None:
    raise B                     # accepté — la preuve ne déteint pas sur B

import mon_module, autre_module
A, B = mon_module.Erreur, autre_module.Valeur

def f() -> None:
    raise A                     # accepté — aucune position n'est prouvée
```

L'**étoile** absorbe un nombre variable de valeurs : les positions qui la
précèdent restent alignées par la gauche, celles qui la suivent par la droite.
L'étoile elle-même lie une LISTE, jamais l'exception, et n'est appariée avec
rien. Une longueur incompatible n'apparie rien du tout : la forme échouerait à
l'exécution, et en déduire une preuve serait inventer.

```python
import builtins
*debut, Absence = 1, 2, builtins.NotImplementedError  # proof:allow — exemple de la règle, ce motif EST le sujet

def f() -> None:
    raise Absence               # refusé — alignement par la droite
```

L'appariement n'a lieu que lorsque les DEUX côtés énumèrent leurs éléments :
`A, B = fabriquer()` ne dit rien de ce que chaque nom reçoit, et la lecture
globale de la valeur reprend alors la main, inchangée.

#### La chaîne d'alias est résolue jusqu'au POINT FIXE

Un alias d'alias est le même stub que la levée directe : `Alias` vaut bien
l'exception de l'interpréteur à l'exécution. S'arrêter au premier cran laissait
la chaîne entière échapper à la règle.

```python
import builtins
Absence = builtins.NotImplementedError  # proof:allow — exemple de la règle, ce motif EST le sujet
Alias = Absence

def f() -> None:
    raise Alias                 # refusé — chaîne transitive

import metier
Racine = metier.Erreur
Alias = Racine

def f() -> None:
    raise Alias                 # accepté — la propagation s'arrête à une origine inconnue
```

La propagation ignore l'**ordre** des lignes, comme le reste de la collecte des
liaisons. Ce n'est pas une précaution théorique : MESURÉ, la collecte visite le
`finally` d'un bloc AVANT ses gestionnaires, si bien qu'un repli d'import
ordinaire présente son maillon consommateur avant son maillon source.

```python
import builtins
try:
    import module_optionnel
except ImportError:
    Absence = builtins.NotImplementedError  # proof:allow — exemple de la règle, ce motif EST le sujet
finally:
    Alias = Absence

def f() -> None:
    raise Alias                 # refusé — un seul tour de propagation le manquerait
```

Le parcours s'arrête dès qu'un tour n'ajoute plus rien, ce qui le borne : le
nombre de noms liés par un module est fini.

La règle ne s'arrête **pas** au corps des fonctions. Levée au niveau d'un module
ou dans un corps de classe, l'exception fait échouer le module **à l'import**, et
elle échoue précisément parce que le code n'est pas écrit : c'est le stub le plus
visible qui soit. Les blocs module — `if`, `for`, `while`, `with`, `try`, `match`
— et les corps de classes sont donc parcourus, jamais les corps de fonctions, qui
sont déjà jugés par ailleurs : un seul défaut ne produit jamais deux violations.

## Sauts de tests ajoutés

`NEW_SKIP_OR_XFAIL` couvre toutes les façons d'ajouter un test qui ne s'exécute
pas : `pytest.mark.skip`, `pytest.mark.skipif`, `pytest.mark.xfail`,
`pytest.skip()`, `pytest.xfail()`, `pytest.importorskip()`, `unittest.skip`,
`unittest.skipIf` et `unittest.skipUnless`. Un saut conditionnel saute
exactement comme un saut inconditionnel dès que sa condition est vraie ; le
distinguer laisserait un test ajouté ne jamais s'exécuter tout en paraissant
présent dans la suite.

Les décorateurs sont lus sur les **fonctions comme sur les classes** : pytest
applique une marque de classe à chacune de ses méthodes de test, si bien qu'un
seul décorateur déplacé d'un cran vers le haut désertait une suite entière.

Les **alias d'import** sont résolus par le même mécanisme que `Protocol` et
`abstractmethod` : renommer l'import ne change rien à ce qui est exécuté.

```python
import pytest as pt        ->  @pt.mark.skip          # refusé
import pytest as p         ->  p.skip('x')            # refusé
from pytest import mark    ->  @mark.xfail            # refusé
from pytest import skip    ->  skip('x')              # refusé — forme appelée
from unittest import skip  ->  @skip / @skip('x')     # refusé
import unittest as ut      ->  @ut.skipIf(True, '')   # refusé
```

La règle reste **qualifiée par l'origine** : elle exige que le nom soit prouvé
par un import de `pytest` ou de `unittest`. Un homonyme porté par un objet métier
(`lecteur.skipIf(…)`), par une instance (`self.skip(…)`), ou importé d'un autre
module (`from mon_module import skip`) ne saute rien et n'est pas concerné.

Les noms canoniques `pytest` et `unittest` restent reconnus **sans condition**.
Ce sens est délibéré et inverse de celui des alias `Protocol` : là-bas, perdre la
preuve rend le gate plus strict ; ici, elle ne doit jamais pouvoir être désarmée
par une réaffectation du nom du module.

## Protocoles génériques

`Protocol[T]` est un `ast.Subscript` : la base souscrite est dépliée avant la
preuve d'origine du nom. Un protocole paramétré est la même abstraction que sa
forme nue, et ses méthodes réduites à `...` sont donc légitimes — les refuser
était un faux positif sur du code courant.

```python
class Depot(Protocol[T]): ...          # accepté — protocole générique
class Depot(typing.Protocol[T]): ...   # accepté — forme qualifiée
class Depot(Generic[T], Protocol[T]):  # accepté — combinaison usuelle
class Depot(Generic[T]): ...           # refusé  — Generic seul n'abstrait rien
```

La preuve d'origine de l'alias est inchangée : une classe locale qui usurpe le
nom `Protocol` reste refusée, y compris sous la forme paramétrée `Protocol[int]`.

### Portée de la preuve d'alias

Un alias n'est prouvé que tant que rien ne l'écrase dans le namespace du module.
Les **blocs module-level** — `if`, `for`, `while`, `with`, `try`, `try`/`except*`
et `match` — sont parcourus dans les DEUX sens : leurs imports lient le module,
leurs affectations le délient. Les scruter seulement pour les imports laissait
une réaffectation cachée d'un cran conserver un alias que l'exécution avait déjà
détruit :

```python
from typing import Protocol
if True:
    Protocol = object      # écrase l'alias — la classe hérite en réalité d'object

class C(Protocol):
    def f(self) -> None: ...   # refusé — plus aucun protocole ne le justifie
```

Les **corps de fonctions** ne sont jamais parcourus par la collecte du MODULE,
dans les deux sens également : leur portée est locale, si bien qu'un import local
ne crée aucune exemption globale et qu'une affectation locale n'invalide aucun
alias du module. Une **réaffectation** ne tient pas compte de l'**ordre** :
écrite avant l'import, elle compte autant qu'écrite après lui. Un **second
import**, lui, est ordonné — voir la section suivante.

Ce que le module ignore n'est pourtant pas inexistant : un import local lie un
alias RÉEL dans sa propre portée, et il est désormais lu là — voir « Un import
LOCAL prouve un alias, dans SA portée seulement » plus bas.

Cette limite vaut pour les **noms**, et pour eux seuls. Les **attributs de
module** sont collectés à toute profondeur — voir « Un attribut de module n'est
lié à aucune portée » plus bas : un nom est lié à une portée, un attribut ne
l'est pas.

#### Un import REBINDE un nom : la liaison la PLUS PROCHE décide

Un import n'est pas seulement une preuve, c'est une **liaison** — au même titre
qu'une affectation. Les imports ne comptaient pourtant pas parmi les
réaffectations : le second n'écrasait jamais la preuve établie par le premier.
Une seule cause, **deux effets opposés**, tous deux MESURÉS.

```python
from typing import Protocol
from module_tiers import Protocol   # le nom ne désigne plus typing

class C(Protocol):
    def f(self) -> None: ...        # accepté à tort — refusé désormais

import builtins as b
import module_tiers as b            # le porteur ne désigne plus builtins

def f() -> None:
    raise b.NotImplementedError     # refusé à tort — accepté désormais
```

La même incohérence portait sur les **sauts de test** : `import pytest as pt`
puis `import module_tiers as pt` puis `pt.skip(…)` était signalé, alors que
`import module_tiers as pt` SEUL — qui désigne pourtant le même objet — ne
l'était pas.

La résolution est celle de l'exécution : **le dernier import qui lie le nom dans
la portée considérée**. Lier commence donc par DÉLIER — les noms que l'import
relie perdent d'abord ce qu'un import antérieur leur prouvait, puis l'import
ajoute le sien. L'ordre des deux gestes est ce qui distingue « rebinder » de
« effacer » :

```python
from module_tiers import Protocol
from typing import Protocol         # le dernier import RÉTABLIT la preuve

class C(Protocol):
    def f(self) -> None: ...        # accepté — l'origine est de nouveau prouvée
```

**Rebinder vers un module PROUVANT ne retire rien**, et c'est ce qui préserve
l'idiome de rétroportage : `typing` et `typing_extensions` prouvent à égalité,
si bien que passer de l'un à l'autre — dans les deux sens, y compris par le
repli `try: … except ImportError: …` — laisse l'exemption intacte.

Un seul ensemble échappe à cette révocation, et l'exception est structurelle :
les **noms d'exception de l'interpréteur** ne sont pas prouvés par un import
mais SEMÉS depuis `builtins` au démarrage du gate. Les y inclure ferait perdre à
`from builtins import ValueError` la preuve que cet import vient précisément
d'apporter ; leur amputation reste donc réglée par la règle dédiée — « Le nom
d'une exception ne prouve rien à lui seul ».

La règle vaut **dans chaque portée**, module comme fonction. La collecte d'une
portée locale rendait ses nœuds à REBOURS de l'ordre écrit — sans conséquence
tant que lier ne faisait qu'ajouter, décisif dès lors qu'un import révoque : les
imports d'une portée sont donc désormais liés dans l'ordre du **source**, comme
au niveau module.

```python
def fabriquer() -> type:
    from typing import Protocol
    from module_tiers import Protocol      # rebind LOCAL, honoré comme au module

    class Depot(Protocol):
        def lire(self) -> str: ...         # refusé désormais
    return Depot
```

Limite assumée, MESURÉE et inchangée par ce correctif : l'apport d'une portée
locale au socle du module reste **purement additif** (voir « Un import LOCAL
prouve un alias, dans SA portée seulement »). Un import de fonction qui rebinde
un nom déjà prouvé PAR LE MODULE ne révoque donc pas la preuve du module. Pour
les **détections** c'est fail-closed — `import builtins as b` au module puis
`import module_tiers as b` dans la fonction reste signalé. Pour les
**exemptions**, c'est le sens inverse, et cette limite est ouverte : le même
enchaînement sur `Protocol` conserve l'exemption. Fermer ce dernier cas suppose
de rendre l'apport local soustractif, ce qui touche toutes les règles à la fois
et relève d'un chantier propre.

#### Toutes les FORMES d'écriture d'un nom, pas seulement l'affectation

Une instruction lie un nom de trois façons distinctes, et n'en lire qu'une
laissait à chaque fois un contournement ouvert : par sa **cible** déclarée, par
une **expression** d'affectation, par une **capture** de filtrage. Les formes
suivantes ont été MESURÉES comme ignorées, et sont désormais toutes collectées.

```python
from typing import Protocol

(Protocol := object)                       # walrus — expression, jamais instruction
_c = [(Protocol := object) for _e in range(1)]   # walrus de compréhension
_c = (Protocol := object) if charger() else None # walrus d'expression conditionnelle
Protocol += ()                             # affectation augmentée
match object:
    case Protocol: pass                    # capture de filtrage
try: charger()
except ValueError as Protocol: ...         # nom du gestionnaire
del Protocol                               # suppression du nom
```

La **capture de filtrage** est le contournement le plus sérieux du lot, parce
qu'il est valide à l'exécution : MESURÉ à l'interpréteur, après `match object:` /
`case Protocol:`, le nom vaut `object` et la classe qui en hérite a bien `object`
dans son MRO. Les autres formes lèvent une erreur à l'import, mais sont
collectées au même titre : la règle est fail-closed sur la CERTITUDE de
l'origine, jamais sur l'exploitabilité de chaque cas.

Deux formes voisines sont au contraire **écartées, mesures à l'appui** :

- **La cible d'une compréhension** ne lie pas la portée englobante. MESURÉ à
  l'interpréteur : après `[Protocol for Protocol in ('A', 'B')]`, le nom vaut
  encore ce que l'import lui a donné. La retenir serait un faux positif pur.
  Le walrus d'une compréhension, lui, fuit bien vers l'extérieur — d'où la
  différence de traitement entre les deux.
- **Le walrus d'un corps de classe** ne lie pas davantage le module. MESURÉ :
  `class Boite: _v = (Protocol := object)` crée `Boite.Protocol` et laisse le
  nom du module intact — même divergence, et même raison, que pour
  l'affectation ordinaire écrite dans un corps de classe.
- **Le recouvrement par un import étranger** — `from transport import Protocol`
  ou `import os as Protocol` — n'ouvre en pratique aucun contournement. MESURÉ :
  employé seul, il ne prouve RIEN et la classe est déjà refusée. La seule forme
  atteignable est le double import du même nom, qui est exactement l'idiome
  légitime `typing` / `typing_extensions` selon la version de Python. Le
  retenir échangerait un faux positif corrigé contre un faux positif nouveau.

Deux liaisons échappaient encore à ce parcours, chacune suffisant à usurper une
exemption d'un seul point.

**La réécriture d'un attribut de module.** Surveiller les seules cibles nommées
laissait `t.Protocol = object` intact : le module survit, mais l'attribut par
lequel l'exemption est prouvée ne désigne plus le protocole standard.

```python
import typing as t
t.Protocol = object

class Service(t.Protocol):
    def calculer(self) -> str: ...   # refusé — l'origine n'est plus prouvée
```

Le retrait vise l'**attribut prouvant**, pas le module entier : `t.TYPE_CHECKING
= True` ne fait disparaître aucune preuve valide. Seules les preuves qui
**exemptent** sont invalidées ainsi — `typing.Protocol`, `abc.abstractmethod` —
car retirer une preuve qui sert à *détecter* (marques de saut, absences
d'implémentation) rendrait le gate muet, donc fail-open.

**La SUPPRESSION d'un attribut de module** détruit la même preuve, et plus
radicalement encore : après `del t.Protocol`, la classe qui prétend en hériter
échoue à l'import sur une `AttributeError`. Ne lire que les affectations
laissait donc exempter un code qui ne s'importe même pas. La symétrie avec le
`del` d'un NOM, déjà collecté, est ainsi rétablie pour les attributs.

```python
import typing as t
del t.Protocol

class S(t.Protocol):
    def f(self) -> None: ...     # refusé — l'attribut prouvant n'existe plus

import abc
del abc.abstractmethod

class Socle:
    @abc.abstractmethod
    def calculer(self) -> str: ...   # refusé — même raison

import typing as t
del t.TYPE_CHECKING              # attribut sans rapport

class Service(t.Protocol):
    def calculer(self) -> str: ...   # accepté — la preuve visée est intacte
```

##### Le chemin ATTRIBUT lit les mêmes formes d'écriture que le chemin NOM

Le vrai défaut n'était pas une règle manquante mais une **asymétrie** : deux
collectes parallèles — l'une pour les noms nus, l'autre pour les attributs de
module — ne lisaient pas les mêmes formes d'écriture. Chaque forme a été
MESURÉE, à l'interpréteur puis contre le gate, avant d'être retenue ou écartée.

| Forme d'écriture sur `t.Protocol` | Attribut réellement écrasé ? | Chemin NOM | Chemin ATTRIBUT (avant) | Verdict |
| --- | --- | --- | --- | --- |
| `t.Protocol = object` | oui | lu | lu | conforme |
| `t.Protocol: object = object` (`AnnAssign`) | oui | lu | lu | conforme |
| `del t.Protocol` | oui (attribut absent) | lu | lu | conforme |
| `for t.Protocol in (object,)` | oui | lu | lu | conforme |
| `with cm as t.Protocol` | oui | lu | lu | conforme |
| `t.Protocol += ()` (`AugAssign`) | oui | lu | **ignoré** | **EN DÉFAUT — corrigé** |
| `[1 for t.Protocol in (object,)]` | oui | écarté à dessein | **ignoré** | **EN DÉFAUT — corrigé** |
| `def f(): t.Protocol = object` | oui, à l'appel | portée locale, écarté | **ignoré** | **EN DÉFAUT — corrigé** |
| `class Boite: t.Protocol = object` | oui, à l'import | portée de classe, écarté | **ignoré** | **EN DÉFAUT — corrigé** |
| `case t.Protocol:` | non — motif de VALEUR, il lit sans lier | lu (capture) | ignoré | correct, aucun changement |
| `except … as t.Protocol` | forme refusée par la grammaire | lu (nom nu) | sans objet | correct, aucun changement |
| `(t.Protocol := object)` | forme refusée par la grammaire | lu (nom nu) | sans objet | correct, aucun changement |

**L'affectation augmentée d'un attribut** écrit le module aussi sûrement qu'une
affectation simple — un module n'a pas d'`__iadd__`, l'opération retombe sur
`__add__` puis réaffecte la cible. Le témoin sur le NOM était déjà refusé ; seul
le chemin attribut laissait passer.

```python
import typing as t
t.Protocol += ()

class Service(t.Protocol):
    def calculer(self) -> str: ...   # refusé — l'attribut prouvant a été réécrit

import typing as t
t.Any += ()                          # attribut sans rapport

class Service(t.Protocol):
    def calculer(self) -> str: ...   # accepté — la preuve visée est intacte
```

**La cible de compréhension est le seul point où les deux chemins doivent
DIVERGER**, et ne pas diverger était précisément le défaut. La portée d'une
compréhension confine le NOM qu'elle lie — raison pour laquelle il est écarté
plus haut, mesures à l'appui — mais elle ne confine rien pour un ATTRIBUT :
elle ne protège que son dictionnaire local, jamais l'objet module visé.

```python
import typing as t
x = [1 for t.Protocol in (object,)]   # écrase bien t.Protocol — MESURÉ

class Service(t.Protocol):
    def calculer(self) -> str: ...    # refusé

import typing as t
f = lambda: [1 for t.Protocol in (object,)]   # portée PROPRE : rien n'est écrit

class Service(t.Protocol):
    def calculer(self) -> str: ...    # accepté — `f` n'est jamais appelée
```

Les sous-expressions sont parcourues, une compréhension n'étant jamais une
instruction : `x = [...]` la cacherait sinon derrière une affectation dont la
cible est un simple nom. La cible d'un **générateur** est retenue sans exiger la
preuve qu'il soit consommé : l'analyse est fail-closed, comme l'est déjà son
mépris de l'ORDRE des instructions.

Le second exemple ci-dessus n'est plus qu'une **frontière résiduelle**, et elle
s'est déplacée : depuis que la collecte lit chaque instruction de l'arbre (voir
la section suivante), un corps de fonction ou de classe ne protège plus rien.
Seul le corps d'un **lambda** — une expression, qu'aucun parcours d'instructions
n'atteint — reste hors du champ.

#### Un attribut de module n'est lié à aucune portée

C'est la **distinction structurante** entre les deux chemins. Un nom est lié à la
portée où il est écrit : `def f(): Protocol = object` ne touche pas le module, et
révoquer là serait un faux positif. Un attribut de module ne l'est pas :
`t.Protocol = object` écrit sur l'objet `typing` **où que la ligne soit
rédigée**. La collecte des révocations d'attributs lit donc l'arbre ENTIER,
corps de fonctions, de méthodes et de classes compris.

MESURÉ avant correction — les deux formes suivantes étaient acceptées à tort :

```python
import typing as t

def desarmer() -> None:
    t.Protocol = object     # mutile réellement typing.Protocol

desarmer()

class S(t.Protocol):
    def manque(self) -> None: ...   # refusé désormais — S hérite d'object
```

```python
import typing as t

class Boite:
    t.Protocol = object     # PAS un attribut de classe : la cible est un attribut
                            # de module, `Boite.Protocol` n'est jamais créé

class S(t.Protocol):
    def manque(self) -> None: ...   # refusé désormais
```

Le second cas — signalé jusqu'ici comme non couvert — est fermé par **le même
correctif** : c'est un parcours par nœuds, pas une exception ajoutée à un cas
particulier. Le `del` d'attribut et la cible de compréhension suivent la même
règle, à la même profondeur.

La distinction avec les noms est conservée intacte, et deux gardes la tiennent :

```python
def configurer() -> None:
    Protocol = object       # NOM local — l'exemption du module tient

class Boite:
    Protocol = object       # attribut de CLASSE — l'exemption du module tient
```

**Conséquence FAIL-CLOSED assumée, et mesurée.** Une fonction qui réécrit
l'attribut sans être jamais appelée révoque elle aussi la preuve : le gate ne
suit pas les appels. Une analyse de flot serait de toute façon incomplète
(décorateur, appel indirect, import tiers), et écrire une fonction qui mutile
`typing.Protocol` sans jamais l'appeler n'a aucun usage légitime — quand l'angle
mort inverse rend l'exemption entièrement contournable.

```python
import typing as t

def desarmer() -> None:
    t.Protocol = object     # jamais appelée — la preuve tombe quand même

class S(t.Protocol):
    def manque(self) -> None: ...   # refusé
```

La portée du retrait, elle, n'est pas élargie : seul l'attribut **prouvant** —
`Protocol`, `abstractmethod` — révoque, et seulement sur son **porteur**. Une
écriture profonde sur `t.TYPE_CHECKING`, ou sur le `Protocol` d'un objet
quelconque, ne détruit aucune preuve.

**L'affectation déclarée `global`.** L'exemption des affectations locales repose
sur leur portée ; `global` la supprime explicitement, et la liaison atteint alors
le module. La déclaration seule ne suffit pas : le nom doit aussi être affecté
dans la même portée.

```python
def desarmer() -> None:
    global Protocol
    Protocol = object      # délie le module — l'exemption tombe

def inspecter() -> str:
    global Protocol
    return Protocol.__name__   # aucune affectation — l'exemption tient
```

#### Un import LOCAL prouve un alias, dans SA portée seulement

C'est le **miroir exact** du cas précédent. Un attribut de module est écrit sur
l'objet module d'où qu'on l'écrive : sa collecte lit l'arbre entier. Un import,
lui, lie un nom — donc une portée, et une seule. Le lire au niveau module
seulement laissait échapper tout ce qui est écrit une ligne plus bas ; le lire
partout ferait signaler des noms qui désignent autre chose ailleurs.

MESURÉ avant correction — refusé au niveau module, accepté dans une fonction :

```python
def livrer() -> None:
    from builtins import NotImplementedError as NI
    raise NI                    # refusé désormais — l'alias local est réel

def test_c() -> None:
    import pytest as pt
    pt.skip('desarme')          # refusé désormais — la suite est bien désarmée
    assert 1 == 1
```

Les **deux familles** d'alias suivent la règle : l'absence d'implémentation —
nue, qualifiée par un `builtins` importé localement, ou construite par
AFFECTATION dans la portée — et les sauts de test, en appel comme en marque
(`@pt.mark.skip` sur une définition imbriquée), pour pytest comme pour unittest.

La contrepartie EXEMPTANTE suit la même loi, faute de quoi le gate signalerait du
code correct : un `Protocol`, un `abstractmethod`, un `TestCase` ou un oracle
`raises` importé dans la fonction qui déclare la classe ou le test prouve son
origine exactement comme au niveau module.

```python
def fabriquer() -> type:
    from typing import Protocol
    class Depot(Protocol):
        def lire(self) -> str: ...   # accepté — protocole réellement importé
    return Depot
```

**La portée est la limite, et elle est prouvée dans les deux sens.** L'alias ne
déborde jamais sur une portée sœur, et la chaîne des portées englobantes est
lue en entier, comme une fermeture à l'exécution :

```python
def fabriquer() -> object:
    import pytest as pt              # visible dans la fonction imbriquée
    def test_interne() -> None:
        pt.skip('desarme')           # refusé — la fermeture porte l'alias
    return test_interne

def prepare() -> None:
    import pytest as pt

def test_calcul(pt: object) -> None:
    pt.skip('rien')                  # accepté — ici `pt` est un paramètre
    assert 1 == 1
```

La résolution réutilise l'**unique** table de portées lexicales, celle qui tranche
déjà les bases d'exception, `Protocol` et `abstractmethod` : les corps de classes
lointains en sont exclus, comme à l'exécution. Un nom écrit dans un en-tête —
base de classe, décorateur — se résout dans la portée qui CONTIENT la définition,
jamais dans son corps.

L'apport d'une portée locale est **purement additif**, et cette asymétrie est
voulue. Une réaffectation locale ne retire aucune preuve de DÉTECTION — `import
pytest as pt` suivi de `pt = objet` laisse le saut refusé, en fail-closed. Pour
l'EXEMPTION, c'est le **masquage lexical** qui tranche, et il refuse déjà
l'exemption dès qu'une liaison locale rend le nom incertain :

```python
def fabriquer() -> type:
    from typing import Protocol
    Protocol = object
    class Depot(Protocol):
        def lire(self) -> str: ...   # refusé — le nom est masqué localement
    return Depot
```

La graine des noms d'exception de l'interpréteur n'est **jamais** réintroduite par
une portée locale : une portée n'apporte que ce que ses imports prouvent. Sans
cette précaution, une classe locale aurait récupéré une exemption que le module
venait de révoquer en détournant le nom (`from transport import ValueError`).

**Limite connue, mesurée, non fermée** : un import local qui DÉTOURNE un nom
d'exception vers un autre module ne révoque pas l'exemption dans sa portée, alors
que le même import au niveau module la révoque. Fermer ce cas demande une
destruction par portée, symétrique de l'apport ; il est signalé ici plutôt que
laissé implicite.

#### `except*` est un nœud distinct, pas un `try` ordinaire

`ast.TryStar` n'est **pas** une sous-classe d'`ast.Try` : l'omettre rendait
`except*` invisible au parcours des liaisons, alors que le parcours des
instructions hors fonction le traitait déjà. Une réaffectation d'un seul cran y
survivait donc à l'invalidation.

```python
from typing import Protocol
try:
    pass
except* ValueError:
    Protocol = object          # écrase l'alias, comme dans un except ordinaire

class Depot(Protocol):
    def lire(self) -> str: ...  # refusé — plus aucun protocole ne le justifie
```

Les quatre corps du bloc sont parcourus — `try`, gestionnaires, `else`, `finally`
— et dans les DEUX sens : un import porté par un `except*` PROUVE l'alias, sans
quoi corriger le seul sens destructeur aurait fait d'un repli d'import légitime
un faux positif.

Le **corps de classe** est la seule divergence conservée entre les deux parcours,
et elle est voulue. `_instructions_hors_fonction` y descend parce qu'un corps de
classe s'exécute à l'import ; le parcours des liaisons ne le fait pas, parce
qu'une classe est un espace de noms propre :

```python
from typing import Protocol

class Boite:
    Protocol = object          # attribut de classe — ne réaffecte AUCUN nom du module

class Depot(Protocol):
    def lire(self) -> str: ...  # accepté — l'alias du module est intact
```

Aligner les deux parcours sur ce point créerait un faux positif au lieu de fermer
un contournement : c'est ce qui distingue cette divergence de celle d'`except*`.

## Suppressions de contrôles

### Où une directive agit réellement

MESURÉ sur les outils eux-mêmes — mypy 2.1.0, ruff 0.15.20, bandit 1.9.4 — une
directive n'agit que si elle suit **directement un `#`**. La borne du gate est
donc ce `#`, ni « n'importe où dans le commentaire » (faux positif), ni « au
début du jeton » (angle mort) :

```python
valeur = 1  # Ne pas utiliser type: ignore ici     # accepté — mypy signale encore
valeur = 1  # Voir le nosec B101 pour les détails  # accepté — bandit signale encore
import os   # import hérité  # noqa: F401          # jugé — ruff supprime vraiment
```

Le troisième cas est celui qui interdit de borner la règle au début du jeton :
`tokenize` rend UN seul commentaire pour toute la ligne, alors que ruff et bandit
honorent la directive qui suit le second `#`.

### `type: ignore` — refus inconditionnel des ajouts

Un `type: ignore` **ajouté** est refusé, avec ou sans justification, sous le code
`NEW_TYPE_IGNORE`. Masquer une erreur de typage n'est pas une dette justifiable :
c'est exactement la baseline que ce gate interdit, et le gate mypy du dépôt est à
zéro erreur pour zéro baseline — aucun besoin légitime ne subsiste. L'orthographe
compacte `# type:ignore`, que mypy accepte, est traitée à égalité.

La règle est **diff-aware** : elle ne juge que les lignes ajoutées. Le seul
`# type: ignore` réellement présent dans les racines contractuelles
(`core/scripts/verify_proof_sealed.py`) n'est donc pas rouvert tant qu'il n'est
pas retouché.

### `noqa` et `nosec` — justification structurée obligatoire

Ces deux directives conservent la règle existante, car elles ont des usages
légitimes documentés : marqueur, identifiants de règles éventuels, puis un
séparateur (`—`, `-`, `:`) suivi d'une justification humaine non vide.

```python
valeur = 1  # nosec B310 — schéma validé par liste blanche   # accepté
valeur = 1  # noqa: E501,W503 — gabarit hérité, découpage prévu   # accepté
valeur = 1  # nosec B310                                      # refusé
valeur = 1  # noqa: E501                                      # refusé
```

Les identifiants de règles — précédés ou non de `:`, séparés par des virgules —
décrivent CE QUI est supprimé, jamais POURQUOI : ils sont consommés avant de
chercher la justification. Sans cette consommation, `# noqa: E501` passait pour
justifié par son seul `:`. Chaque directive d'un même commentaire est jugée.

## Fichier inanalysable

Ce qui ne peut pas être analysé est une violation, jamais un silence. Le code
`FICHIER_NON_ANALYSABLE` couvre la lecture impossible, l'encodage invalide,
l'erreur de syntaxe **et l'échec de tokenisation** : un fichier accepté par
`ast.parse` mais refusé par `tokenize` ne rend aucun commentaire lisible, donc
aucune des règles de commentaire ne peut y être prouvée. Le gate signale la
position rendue par le tokeniseur au lieu de rendre un résultat vide.

## Partage délibéré du périmètre entre les règles

Les règles Python n'ont **pas** toutes la même portée, et cette asymétrie est un
choix, pas une incohérence à corriger.

| Règle | Portée | Pourquoi |
|---|---|---|
| `_analyser_stubs` | état du dépôt, fichier entier | un stub est un défaut de l'état livré ; le filtrer par le diff laisserait vivre indéfiniment tout stub déjà commité |
| `_analyser_omissions_racines` | état du dépôt, fichier entier | une racine contractuelle absente d'un lanceur est un trou de périmètre permanent, invisible dès le commit suivant s'il était réduit au diff |
| `_analyser_ast_diff` | lignes ajoutées | test sans oracle, assertion triviale et skip sont des ajouts de dette ; juger l'acte du contributeur sans bloquer sur l'historique |
| `_analyser_commentaires` | lignes ajoutées | marqueur de dette et suppression de contrôle sont des ajouts de même nature, jugés à la même borne |

Le dépôt étant à zéro violation, les deux règles d'état ne coûtent rien
aujourd'hui et garantissent qu'il en reste ainsi.

Ce partage est **verrouillé par des tests qui le nomment**, dans
`scripts/tests/test_no_stub_gate.py` :

- `test_un_stub_preexistant_non_modifie_reste_refuse_choix_delibere` ;
- `test_une_racine_omise_preexistante_non_modifiee_reste_refusee_choix_delibere` ;
- `test_un_marqueur_de_dette_preexistant_non_modifie_reste_accepte_choix_delibere`.

Chacun commite sa fixture par la plomberie Git puis la laisse intacte : le
silence de la règle diff-aware sur le même fichier prouve qu'aucune de ses
lignes n'appartient au diff mesuré. Aligner l'une des deux règles d'état sur le
diff — ou étendre une règle diff-aware à tout le dépôt — fait rougir ces tests.
