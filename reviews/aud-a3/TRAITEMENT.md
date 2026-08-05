# Revue scellée du lot A3 — REJECT 3/3, et ils avaient raison

## Dépouillement

```
APPROVE 0/3 | vendors distincts: 3 ['minimax', 'tencent', 'xiaomi'] | objections critiques: 1
```

Les trois relecteurs rejettent. C'est le premier rejet unanime de cet audit, et il porte sur des
défauts réels de ma part — dont un chiffre publié faux.

## L'objection critique : un chiffre faux publié dans le pack

**Tencent-Hy3** : « Contradiction numérique. Le pack affirme "le plan fige 91 identifiants",
la sortie du témoin indique "référentiel du plan : 324 identifiants". »

**Confirmée immédiatement.** Le témoin faisait `REFERENTIEL.read_text().split()` : il prenait
chaque MOT du fichier de référentiel pour un identifiant. Or ce fichier porte deux sections — la
liste des 91 identifiants, puis le texte de la décision D-010 que j'y avais ajouté pour la sonde.
Les 233 mots de ce texte étaient comptés.

Le résultat du témoin restait juste : les identifiants réels figuraient bien dans l'ensemble, donc
le test « cité mais absent du référentiel » donnait la bonne réponse. Mais le chiffre publié était
faux, et **un audit qui publie un chiffre faux se disqualifie sur le reste** — c'est précisément
ce qu'il reproche au dépôt lorsqu'il en trouve.

Corrigé : le témoin filtre par le motif d'identifiant, jamais par découpage en mots.
`référentiel du plan : 91 identifiants`.

Cette objection est la deuxième de l'audit à porter sur une donnée fausse que j'ai moi-même
produite — après « lignes source : 0 ». Le point commun des deux : une commande dont la sortie
n'a pas été relue avant d'être publiée.

## L'objection majeure convergente : cité n'est pas défini

**MiMo-Pro-V2** et **MiniMax-M3**, indépendamment : « D-047 est cité dans `ADR-0003`, il ne
devrait pas être compté comme non résolu. Le pack se contredit — il dit à la fois que les quatre
identifiants ne sont définis nulle part, et que D-047 a été repris dans un ADR ratifié. »

La contradiction est apparente, non réelle : **citer n'est pas définir**. ADR-0003 écrit « Le
roster D-040/D-047 est adopté tel quel » — cela mentionne D-047 sans dire ce qu'il est. Un lecteur
qui chercherait à le résoudre ne trouverait toujours rien.

Mais que deux relecteurs sur trois aient buté au même endroit rend la formulation fautive, même si
le fond est juste. Le témoin affiche désormais explicitement, pour chaque identifiant concerné :
`CITÉ dans une décision sans y être DÉFINI : docs/decisions/ADR-0003-RATIFICATION.md`.

## L'objection sur la sévérité

**MiMo-Pro-V2** : « L'écart sur les services transversaux est réel, mais la sévérité critique est
surévaluée compte tenu du statut PARTIAL des modules et de l'absence de mise en production. »

L'objection porte sur la **rubrique**, pas sur le constat — et c'est là qu'elle doit porter, car
aucune sévérité n'est saisie dans cet audit : elle est calculée depuis quatre entrées mesurées.
Ici : `contrat_gele = D-010` et `rayon = 4`, ce qui donne `critique` par la règle
« contrat gelé violé ET rayon ≥ 2 ».

Contester ce résultat revient donc à contester soit une entrée mesurable — le rayon est-il
vraiment de 4 ? oui, cinq services examinés, quatre non conformes — soit la rubrique elle-même,
ce qui est un amendement de cadrage et non une objection de lot. L'objection est **enregistrée
comme désaccord sur la rubrique**, et non traitée en corrigeant le constat : céder ici reviendrait
à écrire une sévérité à la main, ce que le cadrage interdit.

## L'objection de forme

**Tencent-Hy3** : « Le témoin AUD-A3-001 est absent du pack ; seul AUD-A3-002 y figure. »

Exact, et c'est une faute de construction du pack : on ne peut pas demander de juger un constat
sans fournir l'instrument qui l'établit. Le pack du prochain tour portera les deux témoins.

## Ce que la revue n'a pas contesté

Aucun des trois ne conteste que les quatre identifiants ne résolvent nulle part, ni que trois
d'entre eux ne viennent que de sorties de modèles, ni que deux modules réimplémentent
l'approbation là où D-010 la voulait dans le core.

Sur Q4 — les 18 identifiants du référentiel jamais cités —, **MiMo valide l'arbitrage** de ne pas
en faire un constat : « un identifiant non cité peut ne pas être applicable, être respecté de
manière implicite, ou ne pas encore être pertinent. Sans preuve de non-respect, ce n'est pas un
écart. » C'est exactement le raisonnement retenu.
