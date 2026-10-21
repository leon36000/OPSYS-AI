# R34 — sauvegarde et restauration : corrections locales

ROOT : 30 cas uniques, zéro échec/erreur/skip, 36,701s; Docker réel explicitement désélectionné. 1110 sources sélectionnées stables pendant les tests; 1111 lors du contrôle qualité distinct, aucun cumul. Contrôle courant des seules sources/docs/configs déclarées. Rouges/préimages/exception env conservés. Bash/faux Docker stateful et SQLite WAL réel : orchestration locale, pas SQL PostgreSQL réel, image serveur, sandbox rootless, edge/TLS ni installation VPS. Flock : même inode du même script seulement; pas copies/remplacement atomique/restauration parallèle.

[MANIFEST.json](MANIFEST.json), [SOURCES-FINALES.json](SOURCES-FINALES.json), [QUALIFICATION.json](QUALIFICATION.json), [POST-CHECK.json](POST-CHECK.json).

- [Reçu ROOT](preuves/restructuration-opsys-2026-09-30--preuves--backup-restore-root-r1-2026-10-02-resultat.json--7d4bdf6d399a29983ef7f2736c465df780290dc3e8bb1943a8a75d77ae9f35bf.gz)
- [Qualité ROOT distincte](preuves/restructuration-opsys-2026-09-30--preuves--backup-restore-qualite-root-r1-2026-10-02-resultat.json--3a916222f1ad185c93e3ba54d4515ad69f31f7aef9d8a6613ca4c0445741f566.gz)
- [Rapport ciblé et limites](preuves/audit-opsys-2026-09-30--infra--vps-2026-10-02--rapport-r2-root.md--69fea0af4cbd614ee49dc4817a0328f86d3e07162c506fa8b051780f100c81b0.gz)
[Exploitation](../../ops/EXPLOITATION.md) et [profil rootless non qualifié](../../ops/SERVEUR-ROOTLESS.md).
