# Identité de paquet par module — fin de la collision inter-modules

Issue : #109. Portée : `Modules M/M1-front-office/`, `Modules M/M2-revenue-crm/`, `pytest.ini`,
`tests/e2e/conftest.py`.

## Le défaut

M1 et M2 exposaient des modules Python de **même nom de premier niveau** : `registre`,
`horodatage`, `verdicts`, `encodage`, `contrats`, `digest`, `adaptateurs`. Chaque fichier de test
insérait le `src/` de son module dans `sys.path` puis importait à plat.

Dans un **processus pytest partagé**, `sys.modules` conserve le premier module chargé.
L'identité d'un module dépendait donc de l'ordre de collecte, pas de l'arbre auquel il appartient.

Mesure d'origine (M2-S002, collecte combinée M1 puis M2) :

```
sys.modules['verdicts']   -> M1-front-office/src/verdicts.py     <-- mauvais arbre
sys.modules['horodatage'] -> M1-front-office/src/horodatage.py   <-- mauvais arbre
sys.modules['registre']   -> M1-front-office/src/registre.py     <-- mauvais arbre
21 tests M2 en échec
```

Les tests de M2 exerçaient le code de M1 **sans qu'aucun signal ne le révèle**. La CI ne l'a
jamais vu parce qu'elle lance un `pytest` distinct par module : **l'isolation tenait par accident
de configuration, pas par construction.**

Le défaut s'était aggravé entre-temps : le chore #111 a ajouté
`M1-front-office/tests/test_adaptateurs.py`, qui collisionnait avec son homonyme de M2.

## Le correctif

**1. Identité de paquet unique par module.** Les sources vivent désormais dans un paquet dont le
nom est unique au dépôt :

```
Modules M/M1-front-office/src/m1_front_office/{__init__.py, registre.py, ...}
Modules M/M2-revenue-crm/src/m2_revenue_crm/{__init__.py, registre.py, ...}
```

- imports **internes** au module : relatifs (`from . import verdicts`) ;
- imports depuis les **tests** : qualifiés (`from m2_revenue_crm import registre`) ;
- `sys.path` reçoit toujours `src/` — le **parent** du paquet, c'est lui qui rend le nom
  qualifié résoluble.

Les fichiers ont été déplacés par `git mv` : l'historique est conservé.

**2. `--import-mode=importlib` dans `pytest.ini`.** Nécessaire en plus du point 1 : `test_registre.py`
existe dans les tests de M1 **et** de M2, et le mode d'import historique refuse deux modules de
test de même basename (« not the same as the test file we want to collect »). Le mode `importlib`
dérive le nom du **chemin complet**.

**3. `tests/e2e/conftest.py`.** Conséquence du point 2 : le mode `importlib` n'ajoute plus
implicitement le dossier du test à `sys.path`, ce qui cassait `from _harness import ...`. L'ajout
est désormais explicite dans un `conftest.py`, chargé avant la collecte du dossier.

## Preuve

Critère d'acceptation de l'issue — tout en **un seul processus** :

```
pytest scripts/tests tests/e2e "Modules M/M7-marketing/tests" \
       "Modules M/M1-front-office/tests" "Modules M/M2-revenue-crm/tests"
-> 1311 passed
```

Et chaque module reste vert **isolément** (ce que fait la CI) : `scripts/tests` 10,
`tests/e2e` 10, M7 432, M1 328, M2 529.

Identités après correctif, les deux arbres chargés dans le même processus :

```
m1.registre -> m1_front_office        m2.registre -> m2_revenue_crm
m1.verdicts -> m1_front_office        m2.verdicts -> m2_revenue_crm
distincts : True
noms à plat dans sys.modules : []
```

## Garde-fous

Le détecteur existant (`test_isolation_modules.py`, livré avec M2-S002) est **conservé** : il ne
prouve plus la même chose de la même façon, mais il prouve toujours l'**appartenance**. Il a été
étendu : chaque module doit provenir du paquet, et son `__name__` doit être qualifié.

Deux gardes ont été **ajoutées après mesure** :

- `test_aucun_module_m2_a_plat_dans_sys_modules` — aucun module de M2 n'occupe un nom de premier
  niveau ;
- `test_aucun_module_a_plat_sous_src` (M1 et M2) — contrôle **structurel** : aucun `.py`
  directement sous `src/`, exactement un paquet.

Ce dernier vient d'un **NON-DÉTECTÉ** en mutation : copier `verdicts.py` à plat sous `src/` ne
faisait rougir aucun test, parce qu'un fichier que personne n'importe est inerte, donc invisible
pour un test qui n'observe que les modules chargés. Après ajout, la mutation est détectée sur les
deux modules.

## Pièges rencontrés dans la migration

Le script de migration était déterministe, mais trois de ses substitutions étaient fausses — et
chacune a été trouvée par l'exécution des tests, pas par relecture :

**Auto-référence.** La substitution `_SRC / "` → `_PKG / "` s'appliquait aussi à la ligne
`_PKG = _SRC / "..."`, produisant `_PKG = _PKG / "..."`. Toute substitution doit exclure la ligne
qui définit sa propre cible.

**Indentation perdue.** La conversion des imports utilisait `strip()` pour reconnaître la ligne
mais écrivait le remplacement sans l'indentation d'origine : un import local à une méthode
devenait un `IndentationError`.

**Regex trop étroite.** `parents[1] / "src" / "` exigeait un guillemet, donc
`parents[1] / "src" / nom_fichier` (variable) n'était pas couvert ; de même `_SRC / nom_fichier`,
`SRC_DIR`, et `import verdicts      # noqa` (commentaire séparé par plusieurs espaces, qui
laissait des espaces en fin de corps et faisait échouer le `fullmatch`).

**Deux rôles pour un même chemin.** `_SRC` servait à la fois au `sys.path` (doit rester `src/`) et
au **scan** des fichiers sources (doit viser le paquet). La séparation en `_SRC` / `_PKG` est
explicite dans chaque fichier de test concerné. Symétriquement, les programmes lancés en
sous-processus doivent insérer le **parent** du paquet, pas le paquet.

## Conséquence pour la suite

Tout nouveau module doit naître avec son paquet : `src/<mNN_nom_module>/`. Les gardes
structurelles échouent si un fichier est déposé à plat, donc le patron ne peut plus se propager
en silence.
