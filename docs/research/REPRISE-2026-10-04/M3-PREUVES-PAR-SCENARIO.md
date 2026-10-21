# M3 : conserver les preuves sans rejouer la campagne entière

Le job isolé 111322246294 du run 37163712441 atteint la limite de 90 minutes :
Actions annule l’épreuve et termine trois processus Python. Les sorties des enfants
étant capturées, le log ne permet pas d’identifier l’outil actif au moment de l’arrêt.

Le test agrégé rejoue des comportements déjà présents : **9 mutateurs nominaux,
10 suites rouges (9 mutateurs et l’énumérateur), un module sans garde**, soit 20
invocations séquentielles. Le diagnostic initial RO comptait incorrectement 18 ;
l’archive conserve ce diagnostic et sa correction explicite après relecture.

Une fixture autouse capture maintenant la même arborescence réelle src/tests et
ses SHA256/modes autour de chaque scénario, dans un finally exécuté même si le
test échoue. Les assertions de succès effectif, mutations/contrôles positifs,
phrases de refus et nettoyage des reçus restent présentes. Deux assertions de
nettoyage sont ajoutées à l’énumérateur rouge et sans-garde : elles étaient dans
l’ancien agrégat. La preuve de construction/destruction des copies et le cas
non compilable restent actifs. Seul leur rejeu agrégé est retiré.

La matrice conserve huit parts pour ces gardes, une pour les autres outils, le
délai de 90 minutes et le gate exigeant tous les succès. La collecte est vérifiée
avant la sélection ; une part vide ou une collecte échouée refuse le job.
Aucun comportement métier et aucun garde d’approbation ne sont modifiés.

## Qualification et limites

- `qa-r43` : les cinq nouveaux cas négatifs détectent aussi un défaut d’isolation
  de leurs propres changements de racines ; reçu rouge conservé. Une portée
  explicite monkeypatch.context restaure ces racines avant le teardown externe.
- `qa-r44` : 16 cas ciblés réussis, mais la vérification de partition suivante
  `qa-r45` détecte une collecte sans node IDs (quiet ajouté à l’option existante).
- `qa-r47` : source finale, Ruff/actionlint réussis, **16 tests réussis sans ignoré** :
  fichier entier du contrat CI, deux preuves structurelle/dynamique et cinq cas
  négatifs de la garde (ajout, retrait, contenu, mode, échec du corps du test).
- `qa-r48` exécute le sélecteur Bash réel des neuf entrées : les **38 cas collectés**
  des deux fichiers sont sélectionnés chacun exactement une fois. Une collecte
  fictive qui émet un node ID puis échoue est effectivement refusée.
  Ces 38 cas sont collectés/répartis ; les campagnes lourdes ne sont pas déclarées
  exécutées localement par cette preuve de sélection.
- `qa-r49` : Gitleaks des trois fichiers finaux sans alerte brute.

Sur `43c812233dacb3f57f62e89e8417af68b17dab66`, les jobs des dix départements passent
sur GitHub, dont M10 avec l’installation verrouillée corrigée. Ce succès départemental
exclut les deux fichiers lourds M3, exécutés dans leur propre matrice.
Le socle et les autres campagnes sont encore distincts. Les workflows obsolètes
annulés ne sont jamais comptés comme verts ; leurs observations sont archivées.

L’amélioration de durée de la nouvelle matrice et l’exécution complète des outils
restent à qualifier sur GitHub. Le produit reste PARTIEL, la PR #623 brouillon,
et le gate mobile conserve ses défauts de dépendances documentés.

[Archive](preuves/M3-PREUVES-PAR-SCENARIO-r1.tar.xz) et
[inventaire SHA256](preuves/M3-PREUVES-PAR-SCENARIO-r1.json).
