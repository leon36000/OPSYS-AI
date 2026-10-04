# Traductions locales curatées du Control UI

`fr-CA.r47.json` est une source revue pour deux messages précis de
`chat.sessionRoute`. Les formulations ont été fournies dans la session de travail ;
la provenance `curated-local` ne désigne ni un modèle IA ni une traduction humaine
certifiée. Les hashes portent sur le texte anglais courant, avec la normalisation
du générateur officiel. Une modification de ce texte invalide l'import.

Depuis `core/`, la commande suivante vérifie le document et affiche le plan sans
écriture, sans clé, sans OAuth et sans appel à un fournisseur :

```sh
node --import ./scripts/tsx.mjs scripts/control-ui-i18n-curated.ts
```

`--check` est équivalent. Un code de sortie nul signifie que le plan local est
valide ; il ne qualifie pas tous les catalogues, un bundle UI, ni une installation
OPSYS. Le résumé déclare les autres clés encore en anglais ; il ne les traduit pas.

Après revue du plan et des tests, l'application exige un répertoire de preuves
local **nouveau**, extérieur à l'arbre `core/`, dont le parent existe :

```sh
node --import ./scripts/tsx.mjs scripts/control-ui-i18n-curated.ts \
  --write --evidence-dir /chemin/local/existant/import-fr-ca-r47
```

L'outil n'accepte ni clé supplémentaire, ni autre locale, ni chemin de source
arbitraire. Les deux textes doivent correspondre à leurs hashes actuels ; une
traduction existante différente est refusée. Il réutilise le plan officiel et son
renderer pour créer les seuls records manquants, triés, puis les ajoute au fichier
`.i18n/fr-CA.tm.jsonl`. Tous les anciens octets restent identiques. Il n'élague ni
ne réordonne le corpus historique. Une seconde application n'ajoute aucun record.

Les métadonnées `fr-CA.meta.json` sont calculées avec le même matérialiseur que le
module de locale virtuel, après ajout. Les autres clés manquantes et les anciens
fallbacks déclarés restent visibles. Le fichier de référence global
`catalog-fallbacks.json` et les autres locales ne sont pas modifiés : les contrôles
globaux peuvent donc encore signaler une dérive indépendante. Le parcours
`pnpm ui:i18n:verify` vérifie les sources ; `pnpm ui:i18n:check` contrôle les
catalogues générés globaux et peut nécessiter leur maintenance séparée.

Avant toute substitution, l'outil crée les deux préimages, un plan et leurs hashes
dans le répertoire de preuves. Il utilise des fichiers temporaires exclusifs,
`fsync`, une substitution atomique **par fichier** et une vérification des octets
appliqués. En cas d'échec ultérieur, il restaure les fichiers qu'il a changés tant
qu'aucun autre writer ne les a modifiés ; il conserve un reçu d'échec et les
préimages. Deux fichiers ne forment pas une transaction atomique unique. Une
erreur de création du reçu de succès déclenche aussi le rollback. Si le stockage
refuse même le reçu d'échec, le code de sortie reste non nul et le plan préparé
ainsi que les préimages restent la référence ; aucun succès n'est annoncé. Une
interruption brutale entre leurs substitutions peut exiger la restauration
manuelle des préimages ; les vérifications d'entrée ne remplacent pas l'exclusivité
de l'auteur. Le répertoire de preuves contient `prepared.json`, `result.json` et
les fichiers `*.before` ; ses hashes permettent de contrôler ou restaurer les
octets exacts après arrêt des autres writers.

Ne modifiez pas la mémoire générée à la main et ne remplacez pas l'adaptateur
`locales/fr-CA.ts`. Celui-ci continue d'exporter le module virtuel normal. Un bundle
construit avant l'import reste inchangé : il faut reconstruire/recharger le UI par
son parcours habituel pour constater ces deux messages dans l'application.
