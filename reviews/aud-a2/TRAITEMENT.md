# Revue scellée du lot A2 — le fond confirmé, la formulation corrigée

## Dépouillement

```
APPROVE 1/3 | vendors distincts: 3 ['minimax', 'tencent', 'xiaomi'] | objections critiques: 4
```

| Reviewer | Vendor | Verdict | Ce qu'il dit |
|---|---|---|---|
| MiMo-Pro-V2 | xiaomi | **APPROVE** | rien à redire sur le fond ; signale une mesure manquante en Q4 |
| Tencent-Hy3 | tencent | REJECT | ses deux « objections critiques » **reformulent les deux constats** et les valident comme critiques |
| MiniMax-M3 | minimax | REJECT | attaque la **méthode et la formulation** des témoins, pas leur conclusion |

Lecture d'ensemble : **aucun des trois ne conteste le fond**. Tencent confirme les deux constats
mot pour mot ; MiniMax attaque la manière dont ils sont établis — ce qui est exactement le rôle
d'un relecteur sur un lot T2.

## Objection RÉFUTÉE par mesure

**MiniMax, critique** : « `_hachages_disparus()` ne compte que les lignes de diff préfixées par
`-` sans tenir compte des `+`. Un hachage retiré puis réintroduit serait compté à tort. »

Reproduit dans un dépôt jetable : une entrée est ajoutée, retirée, puis réajoutée à l'identique.

```
hachages ajoutés puis disparus : 0
CONSTAT NON REPRODUIT : aucun registre n'a perdu d'entrée.
```

Le témoin porte la garde `if hachage in courant: continue` — il ne retient un hachage que s'il
est absent du contenu courant. L'objection décrivait un défaut réel en principe ; le code ne l'a
pas.

## Objections FONDÉES — je sur-affirmais

### « Le témoin confond incohérence de chaîne et retrait » (MiniMax, critique)

« Par construction, une chaîne de hachage ne peut pas voir un retrait. »

**Fondé, et important.** Le témoin concluait « la disparition est INVISIBLE à toute vérification
de chaîne ». C'est faux tel quel : retirer une entrée **sans recalculer** casse la chaîne, et
`verify` le verrait — c'est même précisément à quoi il sert. Ce qui échappe, c'est le couple
**retrait + recalcul**, et lui seul.

La correction n'affaiblit pas le constat, elle le rend exact : le défaut n'est pas que le hachage
en chaîne serait faible, c'est que le dépôt s'appuie sur `verify` comme **seule** garantie
d'ajout-seul, alors que cette garantie ne couvre pas ce couple. Il manque une ancre hors du
fichier, que rien dans le dépôt ne fournit.

### « La réfutation énonce une propriété générale, pas un défaut du dépôt » (MiniMax, majeure)

Même racine. Écrire « c'est structurel, verify validerait n'importe quelle réécriture cohérente »
décrit le fonctionnement normal d'une chaîne de hachage — pas un manquement de ce dépôt-ci. La
formulation est reprise pour désigner ce qui est réellement en défaut : l'absence d'ancre externe.

### « Le témoin A2-003 n'énumère pas les 12 racines cherchées » (MiniMax, majeure)

Fondé : « 0/691 » ne dit ni si toutes les racines ont été cherchées, ni laquelle aurait pu
répondre. Le témoin les liste désormais une par une avec leur résultat :

```
commit -> aucune clé      sha1 -> aucune clé      diff_sha -> aucune clé
head -> aucune clé        branche -> aucune clé   branch -> aucune clé
revision -> aucune clé    tree -> aucune clé      arbre -> aucune clé
base -> aucune clé        merge -> aucune clé     sha256_diff -> aucune clé
```

La mesure est maintenant vérifiable sans relire le code.

## Ce que la revue demande et qui reste ouvert

**Q4, les deux relecteurs convergent** : le périmètre annoncé du lot A2 comprenait la vérification
que les archives de tours (`round-N/`) sont **byte-identiques** entre relecteurs. Elle n'a pas été
faite. MiMo l'énonce, MiniMax l'énonce, et ils ont raison : c'est une mesure annoncée, non rendue.

Elle est inscrite comme reste du lot, plutôt que réputée acquise. Le sceau `prompt_sha256` prouve
déjà que les relecteurs ont vu le même prompt ; ce qui manque est la vérification que les archives
conservées le reflètent — deux choses distinctes que la clôture ne doit pas confondre.

MiniMax demande aussi la distribution des motifs de REJECT par relecteur. C'est une mesure utile
au lot A2, mais elle éclaire la qualité des revues, non leur intégrité : elle est notée pour le
rapport final plutôt que traitée ici.

## Conclusion

Deux constats critiques **maintenus** — leur fond n'a été contesté par personne, et l'un des trois
relecteurs les a reformulés à l'identique. Trois formulations corrigées, une objection réfutée par
mesure, une mesure manquante inscrite au reste plutôt que passée sous silence.
