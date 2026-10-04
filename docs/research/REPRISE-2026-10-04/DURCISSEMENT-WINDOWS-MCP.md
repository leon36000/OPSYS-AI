# Durcissement Windows, lectures MCP et tests d'installation — 4 octobre 2026

Suite de la [PR #623](https://github.com/leon36000/OPSYS-AI/pull/623), après le commit
`c6422b1ece5b7b0c77c1d759cb58e5ec96dcfa8c`. La tranche corrige les propriétaires existants,
sans nouvelle dépendance, porte d'authentification ou opération financière.

## ACL Windows

Le [job 111331084455](https://github.com/leon36000/OPSYS-AI/actions/runs/37166738659/job/111331084455)
refuse sept cas : `icacls /inheritance:r /grant:r` garde des ACE explicites étrangères.
Les assertions restent strictes. Le helper `src/opsys/instance.py` prépare en mémoire une
DACL protégée avec une seule autorisation FullControl au SID du processus courant, puis
l'applique avec un seul `Set-Acl`. Il conserve le propriétaire, transmet OI/CI pour les
dossiers et relit la DACL pour vérifier le résultat. Aucun `/reset` ou élargissement
intermédiaire écrit. Le chemin est transmis par l'environnement sans interpolation de script.
Absence de PowerShell, refus, expiration et erreur système arrêtent la protection.

Le test Windows ajoute réellement une ACE Everyone explicite, vérifie sa présence puis
exige son retrait et le contenu inchangé. Les tests d'export vérifient qu'un échec de protection
ne laisse aucune archive, empreinte ni résidu. Les dossiers préexistants ignorés par
`_preparer_dossiers` restent une limite distincte ; aucun durcissement récursif général
des installations existantes n'est annoncé.

## Lectures MCP authentifiées et supervision

Le parcours E2E sur `df76940f` atteint le Gateway mais refuse sa première lecture M4 :
le runtime exigeait les cinq champs d'une écriture pour toute identité appareil. Le
propriétaire HTTP émet pourtant volontairement personne/rôle pour une lecture authentifiée.
Le runtime reconnaît cette paire complète. Dès qu'un champ d'idempotence est présent,
les trois champs et l'identité complète sont exigés. Identité partielle, rôle vide,
enveloppe partielle ou enveloppe sans identité restent refusés avant tout appel métier.

La paire reste produite par le contexte authentifié du Gateway, jamais par les arguments
d'outil. Les gardes de rôle, approbation, rejeu et revalidation Python sont conservées ;
le catalogue mémoire appareil reste fermé. Le test de transport couvre une lecture sans
idempotence et le retrait d'une liaison de profil falsifiée ; six cas négatifs protègent
les refus avant appel métier ou ticket privé.

Le test de supervision attendait le handle brut alors que le propriétaire enregistre un
wrapper fermant aussi l'accès cron privé. Il vérifie désormais le comportement : moteur
actif avant l'arrêt du propriétaire, puis `engine.stop()` appelé exactement une fois.
Le superviseur de production reste inchangé.

## Tests Linux d'absence de Docker

Le [job 111327787742](https://github.com/leon36000/OPSYS-AI/actions/runs/37165617213/job/111327787742)
se termine après environ 17 min 40 avec cinq échecs. Deux tests supprimaient leur faux Docker
mais gardaient `/usr/bin:/bin` : le vrai Docker du runner était trouvé. Ces tests isolent
maintenant PATH, avec seulement les faux outils et les utilitaires système indispensables,
et vérifient que Docker est réellement introuvable avant de lancer le script. Les refus
précoces restent exigés. Le scénario PowerShell sous Linux demande une nouvelle CI,
car PowerShell manque localement.

La description d'une erreur de commande dans le rapport R20 est reformulée pour distinguer
l'appel historique erroné de la commande à utiliser. Les preuves r1/r2 exactes restent intactes.

## Qualification et limites

- `qa-r17` : trois fichiers Python entiers, **116 réussis, aucun ignoré**, et Ruff réussi.
  Linux réel ; les branches Windows simulées ne qualifient pas la DACL native.
- `qa-r19` : installateur Bash et commandes métier, deux fichiers entiers,
  **74 réussis, aucun ignoré**, avec Ruff réussi sur les deux fichiers de tests modifiés.
  Le contrôle des invocations documentaires couvre l'index local conservé ; la CI vérifie
  l'ensemble des chemins publiés. Le scénario PowerShell sous Linux n'est pas exécuté ici.
- `qa-r14` : format et lint des quatre fichiers TypeScript réussis après formatage.
  Ce contrôle n'exécute pas leurs tests.
- `qa-r13` : tests Gateway non qualifiés, arrêt par plancher mémoire brut de 256 MiB.
- `qa-r15` : JUnit vide et erreur de parsing avant sauvegarde de l'étape ; aucun résultat
  de test ni cause exacte de terminaison déduits de cette étape perdue.
- `qa-r18` et sa reprise `qa-r20` : une alerte Gitleaks brute sur le marqueur fictif inchangé du test d'export.
  Aucune règle ou baseline modifiée ; aucun scan brut sans alerte annoncé.

Les anciennes reprises et les contrôles rouges restent conservés. Les compteurs OOM
demeurent `10/3/0`. La qualification native Windows, le parcours Gateway et la CI sur le
nouveau commit restent obligatoires avant intégration. Le gate mobile demeure rouge.

[Archive de preuves](preuves/DURCISSEMENT-r1.tar.xz) et
[inventaire SHA256](preuves/DURCISSEMENT-r1.json) : reçus ROOT, JUnit, sources figées,
contrôles interrompus et extraits identifiés des échecs GitHub. La PR reste en brouillon.

## Publication et dernière relecture

La tranche ci-dessus est publiée dans `31dba4efff8f764592375b1b72c9ca8427d23a31`, arbre
`16dd277952bb28f4ea451b8f259fe390b2d008b5`, vérifié identique à l'index de publication.
La dernière relecture retire l'apostrophe typographique d'un message littéral PowerShell,
car ce caractère peut servir de délimiteur de chaîne. Les trois fichiers Python repassent
sur cette source corrigée : `qa-r21`, 116 réussis, aucun ignoré, Ruff réussi. Cela ne
remplace pas l'analyse et l'exécution PowerShell natives attendues de CI.
Cette reprise dispose d'une [archive distincte](preuves/POWERSHELL-LITTERAL-r1.tar.xz)
et de son [inventaire](preuves/POWERSHELL-LITTERAL-r1.json) ; la preuve précédente reste intacte.
