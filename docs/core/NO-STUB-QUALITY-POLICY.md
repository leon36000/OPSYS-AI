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

## Jobs requis qui n'exécutent rien

Un job requis peut être parfaitement valide au sens YAML et n'exécuter aucun
contrôle. La protection de branche est alors satisfaite par un job vert qui n'a
rien vérifié : un gate désarmé est plus dangereux qu'un gate absent, puisque
rien ne le signale. Le code `REQUIRED_JOB_SANS_ETAPE` refuse ces formes :

```yaml
jobs: {gates: {runs-on: ubuntu-latest, steps: []}}       # refusé — aucune étape
jobs: {gates: {runs-on: ubuntu-latest, steps: [null]}}   # refusé — étape nulle
```

Une étape ne compte que si elle porte `run` ou `uses` : une étape réduite à un
`name` décoratif n'exécute rien. Un job requis dépourvu à la fois de `steps` et
de `uses` est refusé pour la même raison.

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

## Groupes de repli après `||`

Un groupe `{ … }` ou `( … )` placé derrière `||` ne s'exécute que si la commande
gardée a échoué, et devient alors le code de retour de l'étape. Il absorbe donc
l'échec par construction, sauf s'il se termine par une sortie non nulle prouvée.

```sh
python3 gate.py || { :; }                            # refusé — échec absorbé
python3 gate.py || { echo "gate ignoré" >&2; }       # refusé — journalise puis réussit
python3 gate.py || ( : )                             # refusé — sous-shell équivalent
python3 gate.py || { echo "toléré"; exit 0; }        # refusé — sortie nulle
python3 gate.py || { echo "échec" >&2; exit 1; }     # accepté — l'échec est propagé
python3 gate.py || { echo "échec" >&2; false; }      # accepté — statut non nul
```

Le critère est la **dernière commande du groupe**, seule à fixer son code de
retour : `exit`/`return` avec un littéral non nul, ou une commande qui échoue
toujours. Les parenthèses internes d'une substitution `$( … )` sont traversées
sans refermer le groupe prématurément, et un motif écrit dans une chaîne shell
reste une donnée, jamais du code.

Les motifs de repli sont bornés par la **fin du nom de commande** : `true`, `:`,
`echo` et `printf` ne sont reconnus que lorsqu'ils sont bien ces commandes-là.
Un exécutable dont le nom commence par l'un d'eux reste un appel légitime :

```sh
python3 gate.py || true_story     # accepté — « true_story » est un exécutable
python3 gate.py || :mon_label     # accepté — nom de commande, pas la commande vide
python3 gate.py; true_story       # accepté — même borne sur la forme séquentielle
python3 gate.py || true; echo ok  # refusé  — ici « true » est bien la commande shell
```

Le nom de commande est lu **après les préfixes qui ne changent pas ce qui
s'exécute** : un chemin désigne le même binaire que son nom nu, et le builtin
`command` ne fait que le lancer en court-circuitant fonctions et alias du shell.
Renommer le chemin d'accès au repli n'a jamais changé le code de retour rendu au
job requis, et le laisser passer suffisait à repeindre en vert un contrôle
échoué :

```sh
python3 gate.py || /usr/bin/true       # refusé  — même binaire, même repli
python3 gate.py || /bin/true           # refusé  — autre emplacement, même binaire
python3 gate.py || /usr/bin/:          # refusé  — la commande vide reste elle-même
python3 gate.py || command true        # refusé  — « command » ne fait que lancer true
python3 gate.py || /usr/bin/true_story # accepté — la borne de nom survit au préfixe
python3 gate.py && /usr/bin/true       # accepté — « && » n'est pas un repli
```

### Shell lancé en repli : `|| sh -c '…'`

Un shell appelé en repli exécute le script passé à `-c`, et ce script devient le
code de retour de l'étape. La neutralisation des quotes — celle qui empêche de
signaler un repli simplement **cité** — effaçait aussi ce script, si bien
qu'aucun motif ne s'appliquait plus : la forme était acceptée alors qu'elle
repeint en vert n'importe quel contrôle requis.

Le critère est le **succès forcé**, jamais l'appel d'un shell : le script est
jugé sur la commande qui fixe son code de retour, avec la liste déjà utilisée
pour les replis directs (`true`, `:`, `echo`, `printf`, `exit 0`).

```sh
python3 gate.py || sh -c 'exit 0'          # refusé  — le repli réussit toujours
python3 gate.py || bash -c 'exit 0'        # refusé  — même forme, autre shell
python3 gate.py || /bin/sh -ec 'echo ko'   # refusé  — options groupées, echo réussit
python3 gate.py || sh -c 'verif || true'   # refusé  — repli imbriqué
python3 gate.py || sh -c 'exit 1'          # accepté — l'échec est propagé
python3 gate.py || bash recuperation.sh    # accepté — un script peut échouer
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
- **Une chaîne `elif`.** La branche mesurée est la première atteinte à l'échec,
  donc la *condition* du `elif`, qui ne propage rien par elle-même. Une chaîne
  dont toutes les issues sortent en non nul est refusée à tort — refus
  conservateur, jamais silence.

Le principe tenu : refuser ce qui est prouvé absorbant, et **nommer** ce qui
passe. Un manque nommé se corrige ; un manque implicite se découvre en production.

## Conditionnelles shell et `exit 0`

Un `exit 0` situé dans une branche conditionnelle est légitime : il exprime une
sortie choisie, pas un contournement. Le gate distingue les deux en lisant les
ouvertures (`if`, `case`), les fermetures (`fi`, `esac`) et les `exit 0` **dans
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

## Absence d'implémentation

La sentinelle `NotImplemented` et l'exception `NotImplementedError` sont
refusées à égalité, sous leurs formes nue, appelée, importée sous alias et
qualifiée par attribut. Un attribut du même nom qui n'est pas levé n'est pas
concerné.

L'alias construit par **affectation** l'est aussi : le gate résolvait l'alias
d'import, mais le même nom obtenu depuis l'attribut d'un module échappait
entièrement à la règle.

```python
import builtins
Absence = builtins.NotImplementedError

def calculer() -> None:
    raise Absence            # refusé — alias prouvé, stub explicite
```

L'exigence de **preuve d'origine** est conservée : seul un nom construit à
partir de `NotImplemented`/`NotImplementedError` est concerné, si bien qu'un
`Absence = mon_module.PanneMetier` reste hors sujet. Cette preuve est appliquée
**après** l'invalidation générale des noms réaffectés : l'affectation qui la
porte est elle-même une réaffectation, et l'appliquer plus tôt reviendrait à
l'effacer avec elle.

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

Les **corps de fonctions** ne sont jamais parcourus, dans les deux sens
également : leur portée est locale, si bien qu'un import local ne crée aucune
exemption globale et qu'une affectation locale n'invalide aucun alias du module.
La règle ne tient pas compte de l'**ordre** : une réaffectation écrite avant
l'import compte autant qu'une réaffectation écrite après lui.

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
