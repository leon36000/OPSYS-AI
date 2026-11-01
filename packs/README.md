# Packs sectoriels

Un dossier par pack (`packs/<id>/pack.yaml` + `EMPREINTE.sha256` + gabarits déclarés). Le cœur d'OPSYS-AI est générique PME ;
tout ce qui dépend du secteur d'activité vit ici. Le pack de l'entreprise se choisit dans `entreprise.yaml` (clé `pack`),
sinon `generique-pme`.

- `generique-pme` : pack par défaut, vide de secteur.
- `renovation-exterieure-qc` : le premier client (rénovation extérieure, Québec). Données fictives ou « à fournir par l'entreprise ».

Après toute modification : `opsys-metier pack empreinte <id> --ecrire`, puis `opsys-metier pack valider`.
Guide complet, garanties et limites : [`docs/architecture/PACKS-SECTORIELS.md`](../docs/architecture/PACKS-SECTORIELS.md).
