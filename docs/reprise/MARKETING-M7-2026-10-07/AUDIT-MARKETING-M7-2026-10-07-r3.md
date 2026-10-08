# Régression console M7 — Toronto, 7 octobre 2026, r3

OPSYS-AI reste PARTIEL. Parent exact a3853e8ae126f0d3fc5a00850e0fa1349f01e042.

La CI du parent termine rouge : 77 échecs / 4465 réussites / 17 skips / 1 warning du socle, gate en échec dérivé. Cinq autres workflows réussissent. Les 77 échecs sont reproduits :59 dans les cinq suites console marketing initialement choisies,18 dans la suite médias omise. Les rouges sont conservés, pas remplacés par les verts du candidat. Capsule CI rouge759membres : `0c202a9e6f48f0a4e08dd6eb2aa8cede3b674fd11fa4d3e48e62d1c08d75caa7`.

Cause : la console transmet le rôle réel `nathan_owner`, confirmé en base, tandis que la nouvelle garde de lecture M7 exigeait uniquement `admin`. Le propriétaire console pouvait décider mais ne plus relire les contenus. La correction accepte uniquement la provenance serveur `console` avec rôle propriétaire actif et porté en base ; elle ne transforme personne en admin. Les identités appareil/MCP restent soumises à la garde admin. Source forgée par arguments ou `_meta`, personne inactive, rôle retiré et rôle non porté sont refusés avant registre.

Deux fichiers de code/test rapprochés de leurs préimages exactes ; nouvelles preuves et audit séparés. Les164tests candidats couvrent les quatre fichiers rouges CI, voisins coûts/performance et garde native M7 ; Ruff et diff check verts. Qualification principale obtenue :164tests, Ruff global pertinent et vérificateur10départements/217outils/125déclarations, même digest avant/après pour les trois reçus. Nouveau commit/CI restent à obtenir. Aucun code M10 candidat n’est intégré par ce correctif.

La CI Core du parent conserve40phases sansskip,38paires d’empreintes,8comparaisons sources aux blobs exacts,47tables métier identiques et journal initial+1audit instance.export. Artefact `f2e42ce8e8b190d59de615d455764f3402b11a4574f671221d0dd4a525d8a3a5`. Ce résultat ne rend pas le socle rouge qualifié.

Le registre r2 conserve l’inventaire exhaustif du transfert (426contenus,302sources/124supports). Les104preuves exclues et supplément généré restent absents ; références conservées, jamais attribuées à cette réexécution. Le présent registre r3 ajoute les deux dispositions du correctif. Téléphone/ExpoSQLite/Hermes natifs et départements profonds restent ouverts. Aucun force-push, fusion ni déploiement.
