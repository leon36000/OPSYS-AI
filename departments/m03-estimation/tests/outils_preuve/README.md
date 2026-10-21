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

    python3 -B "departments/m03-estimation/tests/outils_preuve/enumerer_gardes.py" . <module>

Neutralise chaque `if` produisant un rejet, un par un, et exige le ROUGE. Sort non-zéro si
une garde reste verte, si une neutralisation est sans effet, ou si une garde n'est tenue
que par un PLANTAGE au lieu d'un refus nommé.

Trois propriétés, chacune née d'une objection mesurée : aucune exclusion (neutralisation
par bornes de nœud AST, jamais par texte) ; total ventilé entre gardes de rejet,
englobantes et décisions de blocage ; ROUGE qualifié en refus nommé ou plantage.

## `muter_<module>.py`

    python3 -B "departments/m03-estimation/tests/outils_preuve/muter_<module>.py" .

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

## `lecture_junit.py` — la seule chose extraite des batteries

Les cinq batteries lisaient le rapport JUnit de pytest avec la même fonction, recopiée cinq
fois. `bandit` la signalait cinq fois (`B314`, MEDIUM) : une analyse XML non durcie est classée
VULNERABILITY par les analyseurs statiques, et une seule vulnérabilité suffit à faire tomber
une note de sécurité. La copie est donc remplacée par un module partagé, durci une fois.

**On n'a extrait QUE la lecture.** La logique de mutation reste dans chaque batterie, et chaque
batterie garde son extracteur textuel `_echecs_sortie`, indépendant, dont elle unit le résultat
avec celui-ci. C'est délibéré : un tronc commun est un point unique de défaillance, et le
saboter ferait mentir les cinq batteries d'un coup. Ici, si la lecture partagée devenait
défaillante, l'extracteur textuel de chaque batterie tient encore, et le cas où les deux
rendent le vide sur une suite rouge reste signalé comme ROUGE NON ATTRIBUABLE. La redondance
qui protège est préservée ; seule la copie inutile disparaît.

Le durcissement ferme l'expansion d'entités externes et l'expansion récursive dite « billion
laughs », par trois gestionnaires expat qui refusent DTD, déclarations d'entité et références
externes. Il ne borne PAS la taille du rapport, ne refuse PAS une imbrication profonde sans
entités, et ne vérifie PAS que le rapport correspond à l'exécution qu'on croit mesurer.

Éprouvé par `tests/test_lecture_junit.py`, sept tests. Le test central neutralise la
configuration expat et exige que le comportement CHANGE — mesuré : trois tests tombent alors
par assertion nommée. Un durcissement que rien ne fait rougir en son absence n'est pas un
durcissement, c'est une intention.

## Les gardes des outils sont éprouvées par des TESTS

    pytest "departments/m03-estimation/tests/test_gardes_des_outils.py"

Un script `verifier_les_outils.py` de 350 lignes jouait ce rôle. Sept rondes de revue scellée
l'ont amélioré — et à chaque itération il gagnait un défaut propre : deux variantes d'un même
identifiant, une variable hors portée, un motif présent dans la sortie normale. **Sa
complexité était devenue le goulot.**

Les mêmes propriétés s'expriment en dix tests courts : chaque batterie refuse une suite déjà
rouge, l'énumérateur refuse aussi un module sans garde, les deux abandons sont DISTINCTS,
chaque outil est SAIN avant sabotage (rc nul ET phrase d'abandon absente), une mutation non
compilable est signalée par sa propre phrase, et aucune trace ne subsiste — empreinte, mode
d'accès, chemins apparus ou disparus.

Une PHRASE, jamais un mot. Le motif « ROUGE » avait été retenu puis rejeté : il apparaît dans
la sortie normale des batteries, où chaque mutation qui mord imprime `-> ROUGE`. C'est le
contrôle « sain avant sabotage » qui l'a démasqué, dès sa première exécution.

### Coût de la batterie de hiérarchie

`muter_hierarchie_echelle.py` conserve ses 12 mutations et ses deux redondances déclarées.
La référence verte et les deux redondances exécutent toujours la suite complète. Seules les
12 exécutions attendues rouges portent `--maxfail=1` : après une référence complète verte,
le prédicat exige déjà au moins un nouvel échec identifié par JUnit ou la sortie pytest.
Compilation, ancres uniques, différence des ensembles d'échecs et nettoyage restent inchangés.
Il n'y a aucun arrêt anticipé du pytest parent ni exclusion supplémentaire de tests.

Le reçu décrit cette politique par les descripteurs de phase `MUTATIONS:--maxfail=1` et
`REFERENCE_ET_REDONDANCES:suites-completes` dans `options_pytest` ; ces descripteurs sont des
métadonnées, jamais des arguments exécutés. La fermeture inclut les octets du script modifié :
un reçu d'avant cette modification ne peut pas être réutilisé pour la nouvelle entrée.
Le diagnostic exhaustif des échecs d'un mutant devient celui de son premier échec seulement.
Le contrat reste une comparaison à une référence verte, sans table de test attendu par mutation :
un échec environnemental nouveau ou une suite instable ne constitue pas une preuve de causalité.
Le gain de temps doit être mesuré sur la batterie réelle, avec source et environnement identifiés.

### L'épreuve elle-même travaille sur une copie (PLAN T0.12-suite)

Pour éprouver les gardes, `test_gardes_des_outils.py` doit faire échouer les outils sur
COMMANDE : un test déjà rouge, un module sans aucun `if`, une mutation non compilable. Jusqu'à
T0.12-suite, ces trois artefacts étaient écrits DIRECTEMENT dans les vrais dossiers du
département (`departments/m03-estimation/tests`, `.../tests/outils_preuve` et
`.../src/m3_estimation`), puis retirés dans un `finally` — le même schéma « écrire puis
restaurer » dont l'incident du 2026-09-28 avait déjà montré le risque pour les outils de
mutation eux-mêmes (T0.12, ci-dessus) : une exécution interrompue (délai dépassé, processus
tué) laisse le fichier en place, la suite suivante échoue, et un `git add -A` le commiterait.

L'épreuve utilise désormais la MÊME `EnvironnementMutation` que les outils qu'elle éprouve,
plutôt qu'un second mécanisme : chaque artefact est écrit dans une copie jetable du
département, et l'outil à éprouver est lancé avec cette copie comme racine — il y construit à
son tour SA PROPRE copie interne (le même « chaque appelant obtient une copie complète et
jetable » que documente `_environnement_mutation.py`), si bien que l'artefact n'est jamais
visible que depuis des dossiers temporaires, imbriqués mais tous jetables. Un `kill -9` en
cours de route laisse au pire un dossier orphelin sous le répertoire temporaire du système ;
jamais une trace dans le dépôt.

Deux preuves, dans l'esprit de celles de T0.12 mais portant sur l'épreuve elle-même plutôt que
sur les outils : `test_l_epreuve_des_gardes_n_ecrit_jamais_sous_la_vraie_racine_du_departement`
vérifie STRUCTURELLEMENT (AST, résolution des affectations simples) qu'aucun appel d'écriture
du fichier ne cible les constantes désignant le vrai dépôt ou le vrai département ;
`test_empreinte_de_src_et_tests_identique_apres_confection_d_une_epreuve` fabrique réellement
les deux artefacts et compare l'empreinte SHA-256 (et le mode d'accès) de CHAQUE fichier sous
`src/` ET `tests/` avant et après : identiques. Volontairement sans sous-processus, pour isoler
la seule opération qui écrivait sur disque de la confection d'une batterie complète, déjà
éprouvée par ailleurs dans ce même fichier.

## `bilan_preuves.py` — le bilan des gates, produit par un instrument

    python3 -B "departments/m03-estimation/tests/outils_preuve/bilan_preuves.py" .

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
