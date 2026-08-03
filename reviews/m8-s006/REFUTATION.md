# Réfutation d'objection — M8-S006, DeepSeek-V4-Pro (mineure)

**Objection** : `_argument_graine_fournie` utiliserait le mauvais mot-clé (`"x"` au lieu de
`"seed"`) pour `random.Random(...)`, causant un faux positif `RANDOM_NON_ENSEMENCE` sur un appel
« légitime » `random.Random(seed=12345)`.

**Mesure directe** (pas d'hypothèse) :

```
$ python3 -c "
import inspect, random
print(inspect.signature(random.Random.__init__))
print(inspect.signature(random.Random.seed))
random.Random(seed=12345)
"
(self, x=None)
(self, a=None, version=2)
TypeError: Random.__init__() got an unexpected keyword argument 'seed'
```

**Verdict** : objection réfutée. Le paramètre réel du constructeur `random.Random` est `x`
(pas `seed`) ; celui de la méthode `.seed()` est `a`. L'appel `random.Random(seed=12345)` cité
par le reviewer comme « légitime » lève en réalité une `TypeError` — ce n'est pas du Python
valide. Le code de `_argument_graine_fournie` (`mot_cle = "x" if suffixe == "Random" else "a"`)
correspond déjà exactement aux vrais noms de paramètres ; aucune correction appliquée.

Aucun autre tour de revue requis : la seule objection était mineure, non critique
(objections critiques: 0, APPROVE 3/3), et réfutée par mesure directe plutôt que par
désaccord d'opinion.
