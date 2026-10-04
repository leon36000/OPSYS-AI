# Reprise de l'installateur Windows — 4 octobre 2026

La [PR #623](https://github.com/leon36000/OPSYS-AI/pull/623) contient déjà la reprise et le
correctif CI `df76940ff3fce10670f4e195a7228a89ca5e4028`. Le job Windows
[111327787937](https://github.com/leon36000/OPSYS-AI/actions/runs/37165617213/job/111327787937)
révèle quatorze échecs : modes POSIX utilisés comme droits Windows, attentes de chemins
sans lettre de lecteur et assertions d'extras devenues obsolètes.

## Correctif

- PowerShell consomme sa constante d'extras `tournees,soumission` pour ses deux commandes
  `uv sync --locked`. Le PDF natif reste propre à `install.sh` sous Linux ; cette limite est
  explicitée dans l'en-tête, sans annoncer une capacité Windows inexistante.
- Les tests de confidentialité inspectent réellement les droits : `0600/0700` sous POSIX,
  DACL protégée, absence d'ACE héritée ou destinée à un autre SID, contrôle complet du compte
  courant et transmission OI/CI des dossiers sous Windows. PowerShell est obligatoire pour
  cette inspection Windows ; aucun saut de test faute d'inspecteur.
- Les cas qui simulent POSIX sur Windows vérifient l'appel à `chmod`, et les cas natifs
  vérifient séparément la protection effective. Les chemins HOME suivent la résolution
  absolue propre à l'OS, avec priorité HOME et normalisation conservées.
- L'archive d'export et son fichier d'empreinte sont tous deux vérifiés privés. Le calcul
  SHA256 réel, les exclusions, l'absence de résidus et les gardes existantes sont conservés.

Le code de protection de production `src/opsys/instance.py` n'est pas modifié ici.
Les dossiers Windows préexistants ne sont actuellement ni inspectés ni resserrés par
`_preparer_dossiers` : limite explicitement conservée et non assimilée à une garantie d'ACL.
Le correctif ne garantit pas non plus la suppression de toute ACE explicite étrangère sur
un chemin arbitraire préexistant ; les tests natifs imposent cette propriété aux fixtures
qu'ils créent et doivent la confirmer sur le runner Windows.

## Preuves et limites

ROOT : trois fichiers de tests entiers, **113 réussis, aucun ignoré**, sous Linux ; Ruff
réussit sur les quatre fichiers Python modifiés. Sources stables, environnement de test
sans secrets hérités, aucun nouvel OOM (`10/3/0`). Le premier contrôle Ruff rouge est gardé
avec sa reprise. Ni les ACL Windows natives ni l'exécution PowerShell ne sont qualifiées
localement ; leur résultat doit venir de la nouvelle CI Windows.

Le scan Gitleaks brut conserve une alerte sur `MARQUEUR_SECRET` du test d'exportation :
fixture explicitement fictive, littéral identique à l'arbre publié précédent, aucune règle
ou baseline modifiée. Aucun résultat brut sans alerte n'est revendiqué.

[Archive des preuves](preuves/WINDOWS-ACL-r1.tar.gz),
[inventaire SHA256](preuves/WINDOWS-ACL-r1.json) : reçus ROOT, JUnit, contrôles rouges,
classification du scan et métadonnées GitHub horodatées. Le log Windows est complet ;
les nouveaux échecs core/E2E sont conservés sous forme d'extraits identifiés.

## Résultats distants sur `df76940f`

La construction du core et son profil mémoire vocal après construction fraîche réussissent,
ainsi que ses **six partitions unitaires**, l'analyse de l'installateur et son job macOS.
L'audit général des dépendances réussit ; le gate mobile demeure rouge.

Le job supplémentaire `tests-opsys` échoue sur une assertion d'identité du superviseur de
moteur (un échec sur 791 cas du projet gateway-server). Le parcours E2E atteint le Gateway
construit et refuse l'appel appareil pour métadonnées authentifiées incomplètes. Ces deux
défauts restent à corriger et ne sont pas couverts par les 113 tests de cette tranche.
Le job Linux est encore en cours et le workflow Python est en attente à l'observation
conservée dans l'archive. Aucun workflow global ni produit complet n'est déclaré vert.
