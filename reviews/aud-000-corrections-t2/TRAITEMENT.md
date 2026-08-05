# Revue scellée des corrections du tour 2 — trois objections, toutes confirmées

## Dépouillement

| Reviewer | Vendor | Verdict | Objections | Critiques |
|---|---|---|---|---|
| MiMo-Pro-V2 | xiaomi | **APPROVE** | 0 | 0 |
| MiniMax-M3 | minimax | **REJECT** | 3 (1 majeure, 2 mineures) | 0 |
| Kimi-K3 | moonshot | — | route épuisée, HTTP 500 après 3 essais | — |

Sceau `1378fbfb1a7a885c6e19…` identique sur les deux verdicts déposés.

**Le trio est incomplet : 2 verdicts sur 3, deux vendors distincts.** REG-05 en exige trois. Cette
revue ne vaut donc pas approbation ; elle vaut **détection**, et c'est à ce titre qu'elle est
exploitée. Les trois objections ont été reproduites par mesure avant d'être traitées, ce qui les
rend indépendantes du dépouillement.

Kimi-K3 est le second échec de route consécutif du trio d'audit (Grok-4.5 en 408 lors du sondage,
Kimi-K3 en 500 ici). La composition du trio devra être reprise avant le premier lot.

## Les trois objections, reproduites

### 1 (majeure) — le double régime de CA-AUD-09 ne couvre pas la disparition

« La relation de préfixe ne protège que contre la modification du contenu d'un fichier EXISTANT,
pas contre sa suppression, son renommage, ou son changement de type. »

Fondé, et le raisonnement se vérifie sans expérience : si `registries/ledger/preuves.jsonl`
disparaît entre la base et HEAD, il n'y a plus de contenu à comparer, et une règle qui compare des
contenus n'a rien à dire. La correction du tour 2 avait appliqué `MDTR` aux preuves figées et
**oublié** que les registres avaient besoin, en plus du préfixe, de la même garantie d'existence.

Correction : deux conditions **cumulées** sur les chemins de registre — `DTR` vide (le fichier n'a
été ni supprimé, ni renommé, ni changé de type) **et** relation de préfixe exact. Aucune ne suffit
seule : `DTR` seul autoriserait la réécriture d'une ligne, le préfixe seul autoriserait
l'effacement du fichier.

### 2 (mineure) — un nombre quelconque après une virgule devient un critère

Mesuré :

```
_extraire_criteres_cellule('CA-AUD-01, 02, audit de 2023, 45')
  ->  ['CA-AUD-01', 'CA-AUD-02', 'CA-AUD-45']
```

`CA-AUD-45` n'existe pas : il vient du nombre « 45 » d'une phrase. Le drapeau `prefixe_vu` n'est
jamais remis à zéro, si bien que toute occurrence ultérieure de `, NN` est lue comme une
abréviation, quelle que soit la distance au dernier identifiant complet.

### 3 (mineure) — une mention en prose vaut affectation

Mesuré :

```
_extraire_criteres_cellule('Description, voir CA-AUD-01 pour le contexte')
  ->  ['CA-AUD-01']
```

Une cellule qui MENTIONNE un critère est traitée comme une cellule qui l'AFFECTE.

## Portée réelle de ces deux mineures

Sur les documents actuels, aucune des deux ne produit d'erreur : le gate est vert et les cinq
formes réellement employées (`CA-AUD-01, 02`, `CA-AUD-09, 10, 12`, `CA-AUD-13`) sont lues
correctement. Ce sont des fragilités **latentes** — elles se déclencheraient à la première cellule
d'architecture contenant de la prose ou un nombre.

Elles sont corrigées malgré leur absence d'effet actuel, pour une raison mesurée dans ce dépôt :
une objection mineure laissée en place sur un composant de vérification revient plus tard en
critique, avec son exploit. Le contrôle de cohérence entre documents est précisément ce qui a
rattrapé la contradiction du tour 2 ; le laisser lire de la prose reviendrait à saper l'instrument
qui vient de prouver son utilité.

## Ce que la revue confirme par ailleurs

MiMo-Pro-V2, en APPROVE, a vérifié indépendamment les trois points que la story demandait de
juger — la séparation forme/contenu des deux contrôles est réelle, le double régime ne laisse pas
d'altération de contenu possible, et aucune correction n'a introduit de défaut nouveau parmi ceux
qu'il a cherchés. Son accord ne vaut pas preuve, mais il ne contredit aucune des mesures.
