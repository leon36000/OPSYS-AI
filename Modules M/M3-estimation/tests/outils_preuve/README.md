# Outils de preuve — M3 Estimation

Ces scripts ne sont pas des tests. Ce sont les **instruments qui mesurent la valeur des
tests**. Ils ont été écrits pendant les stories S002 à S006, chacun en réponse à une
objection de revue scellée qui avait trouvé un défaut réel.

Ils vivent ici, versionnés, pour trois raisons :

1. **Rejouables par quiconque.** Une preuve qui n'existe que dans un scratchpad n'est pas
   une preuve — c'est une affirmation. Deux relecteurs ont refusé un pack pour ce motif.
2. **Ils ne gonflent plus les paquets de revue.** Recopiés dans chaque pack, ils pesaient
   21 ko par ronde ; une fois sur `main`, ils sortent des diffs de story.
3. **Ils ont eux-mêmes des défauts.** Chacun en a livré au moins un — documenté dans son
   propre docstring. Les cacher reviendrait à faire confiance à l'outil de mesure.

## `enumerer_gardes.py`

    python3 -B "Modules M/M3-estimation/tests/outils_preuve/enumerer_gardes.py" . <module>

Neutralise chaque `if` produisant un rejet, un par un, et exige le ROUGE. Sort non-zéro si
une garde reste verte, si une neutralisation est sans effet, ou si une garde n'est tenue
que par un PLANTAGE au lieu d'un refus nommé.

Trois propriétés, chacune née d'une objection mesurée : aucune exclusion (neutralisation
par bornes de nœud AST, jamais par texte) ; total ventilé entre gardes de rejet,
englobantes et décisions de blocage ; ROUGE qualifié en refus nommé ou plantage.

## `muter_<module>.py`

    python3 -B "Modules M/M3-estimation/tests/outils_preuve/muter_<module>.py" .

Batterie de mutations MÉTIER : chaque mutation est une erreur de conception plausible qui
doit faire virer la suite au ROUGE. Les mutations qui ne PEUVENT PAS mordre — redondances
structurelles — sont DÉCLARÉES avec leur raison mesurée, et le script échoue dans les DEUX
sens : si une redondance déclarée se mettait à mordre, l'hypothèse serait tombée.

## `neutralite_renommage.py`

    python3 -B "Modules M/M3-estimation/tests/outils_preuve/neutralite_renommage.py" . <commit>

Prouve qu'un renommage de constantes est sémantiquement neutre : extrait la version d'avant
depuis git, importe RÉELLEMENT les deux, et compare. Abandonne bruyamment si un fichier
manque au commit de référence, et vérifie que chaque module « avant » a bien été chargé
depuis le dossier temporaire — sinon il comparerait la version courante avec elle-même en
annonçant « neutre ».

## Discipline

Un script de preuve qui ne peut pas échouer ne prouve rien. Chacun sort non-zéro sur défaut,
et refuse de conclure quand son extracteur ne trouve rien — un scanner vide passe toujours.
