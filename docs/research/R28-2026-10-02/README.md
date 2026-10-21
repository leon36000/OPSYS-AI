# R28 — ingestion PDF native et console admin

R28 qualifie le backend PDF natif et sa console admin dans le même instantané. Les 122 cas ROOT backend et les 145 cas ROOT intégrés sont deux campagnes différentes; les 65 cas auteur backend et 43 cas auteur UI sont des preuves séparées, non additionnées. Les rouges et reprises sont préservés comme historique, pas présentés comme verts. La réception PDF est préparatoire; extraction locale par worker isolé, aucun OCR, modèle, corpus client ni garantie comptable. Déconnexion ne garantit pas annulation immédiate. Consultation réservée aux admins de la même base SQLite; aucune qualification PostgreSQL.

[MANIFEST](MANIFEST.json) · [SOURCES-FINALES](SOURCES-FINALES.json) · [QUALIFICATION](QUALIFICATION.json) · [POST-CHECK](POST-CHECK.json)

Documents gelés :
- [FUSION-PDF-NATIF.md](docs/docs-architecture-FUSION-PDF-NATIF.md-63a559ccdb94-045ec08f1ad11e9dd2bd0c8aceaae007f9bfe293f310394d3fbe0d44f206f20b.gz)
- [LOT-FUSION-PDF-NATIF.md](docs/docs-programme-LOT-FUSION-PDF-NATIF.md-e2abf0e4135b-fd9959c4aa756031cafaf9080c25017d6b0c9ff809eb98a05c9224aaf8bfff56.gz)
- [REPRISE-PLAN-2026-10-02.md](docs/docs-programme-REPRISE-PLAN-2026-10-02.md-47113b327657-e17605844fd4df4c6e489fe63789dcb89b49cd4651bda75bbad422208fd48d92.gz)
- [INGREDIENTS.md](docs/docs-research-INGREDIENTS.md-4bbf4f338e8d-78bf474306a536d5d69aae1e4e478b04619f626ccd0d6966757526a54ff331c8.gz)

Preuves qualifiantes :
- [backend_root](preuves/poursuite-opsys-2026-10-02-r1-ingestion-pdf-backend-root-r1.xml-2195b1d312cd-785f169fb09a631f7901d5bd83bfeae67d70e7c131e93c33b5e189403b8976c0.gz)
- [integree_root](preuves/poursuite-opsys-2026-10-02-r1-ingestion-pdf-pdf-ui-integre-root-r1.xml-3356538f1af1-9c8bc5cc26a837f1aefff8a0b9c5586289cb6aac1b7ceb4b10a07a7bd54209ef.gz)
- [backend_auteur](preuves/poursuite-opsys-2026-10-02-r1-ingestion-pdf-backend-r1-corpus-cible-r5.xml-c1360f994485-1b02d123312c87e931097a51206617e69f8f88284ce3420456001b1531f4632d.gz)
- [ui_auteur](preuves/poursuite-opsys-2026-10-02-r1-ingestion-pdf-ui-r1-author-integration-r3.xml-4ab9f343e0b4-375b290a9cf06d33d4764b36a592a783a56f928a0d1b5b651bbcac3d1b431e4d.gz)
