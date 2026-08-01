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
doit faire virer la suite au ROUGE. Les mutations qui NE MORDENT PAS sont DÉCLARÉES avec leur
raison mesurée, et le script échoue dans les DEUX sens : si une redondance déclarée se mettait
à mordre, l'hypothèse serait tombée.

Deux natures de déclaration, et le README ne doit pas les confondre — une revue scellée a
relevé cette contradiction :

- **redondance STRUCTURELLE** — l'inertie se démontre. Exemple : la borne `nombre_photos >= 3`
  de MULTI_VUES est impliquée par `angles_distincts >= 3`, puisque le cardinal d'un ensemble
  de valeurs prises sur les photos ne peut excéder leur nombre.
- **inertie EMPIRIQUE** — l'inertie s'observe, elle ne se prouve pas. Exemple : le bornage au
  barème de Monte Carlo, 0 déclenchement sur 300 graines et 0 excursion sur 2 500 000 tirages,
  mais la documentation CPython avertit que la borne haute de `uniform` peut ou non être
  incluse selon l'arrondi. Un échantillon, même large, ne démontre pas une impossibilité.

Écrire « ne peuvent pas mordre » pour les deux affirmait plus que la mesure.

## `verifier_les_outils.py` — l'instrument qui vérifie les instruments

    python3 -B "Modules M/M3-estimation/tests/outils_preuve/verifier_les_outils.py" .

Une revue scellée a rendu QUATRE objections critiques convergentes : les preuves que « les
gardes des outils mordent » venaient d'extraits Python écrits DANS le pack de revue, pas
d'un instrument versionné. Elles étaient donc irreproductibles — exactement la classe de
défaut que ces outils servent à débusquer, commise dans le pack qui les présente.

Ce script crée la condition de déclenchement de chaque garde, lance l'outil concerné, et
exige un code de retour non nul. Il relève l'empreinte sha256 de tous les fichiers source et
de tous les outils AVANT, et la confronte APRÈS chaque manipulation : un vérificateur qui
laisse une trace est un vérificateur qui ment. Il abandonne s'il n'a pu éprouver aucune
garde.

## `bilan_preuves.py` — le bilan des gates, produit par un instrument

    python3 -B "Modules M/M3-estimation/tests/outils_preuve/bilan_preuves.py" .

Une objection critique de revue a relevé que la section « gates » des packs affichait une
sortie assemblée par du shell écrit DANS le pack : barre de progression pytest, `rc_gate=0`,
`STATUT_LINT: VERT`. Aucun instrument versionné ne la produisait — elle n'était donc pas
rejouable.

Ce script exécute les cinq contrôles du dépôt, chacun par son propre exécutable, et imprime
le nom, la commande RÉELLE, le code de retour et la dernière ligne significative. Aucun
verdict n'est écrit d'avance : chacun vient du code de retour observé. Un exécutable
introuvable est un ÉCHEC nommé, jamais un saut silencieux.

Mesuré : gate retirée du disque -> `contrôles exécutés=4 échoués=2`, rc=1. Test saboté ->
`exécutés=5 échoués=1`, rc=1.

## Un outil n'accompagne que des cibles qui existent

Une revue scellée a rendu APPROVE 0/3 sur une première version de ce dossier : elle
embarquait `muter_plancher.py`, dont le module cible n'existait pas encore sur la branche.
Le script plantait sur `FileNotFoundError`, et les sorties du pack — produites sur une AUTRE
branche — étaient irreproductibles là où on les présentait.

La règle qui en sort : **un outil de preuve ne vit dans le dépôt qu'avec la cible qu'il
mesure.** `test_outils_de_preuve.py` la fait respecter — il exige que chaque
`muter_<module>.py` ait son module, et que chaque outil s'annonce par un docstring.

## La limite résiduelle, déclarée

Le vérificateur exige un contrôle NÉGATIF (l'outil doit rendre zéro à l'état sain), le MOTIF
attendu de chaque garde, et une DISCRIMINATION (deux sabotages différents doivent produire
deux messages différents). Cela rend le trucage plus coûteux que la chose réelle.

**Cela ne le rend pas impossible.** Un instrument ne peut pas prouver qu'un autre instrument
n'est pas un leurre : un outil qui simulerait exactement les messages attendus, dans le bon
ordre, passerait. La limite est déclarée ici plutôt que tue — c'est ce que la méthode exige
d'une frontière connue.

## Discipline

Un script de preuve qui ne peut pas échouer ne prouve rien. Chacun sort non-zéro sur défaut,
et refuse de conclure quand son extracteur ne trouve rien — un scanner vide passe toujours.
