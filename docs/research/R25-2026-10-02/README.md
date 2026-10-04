# R25 — PostgreSQL pgvector réel en fixture tmpfs

La campagne ROOT sélectionnée contient **82 cas JUnit effectifs**, sans failure, erreur ou skip. Les éléments testcase sont comptés une seule fois; les sommes de suites parentes et enfants ne sont pas cumulées. Les suites historiques/auteurs et leurs reprises sont conservées, sans addition aux cas ROOT.

[Reçu ROOT](preuves-root/memoire-pg-integre-root-r2-2026-10-02-resultat.json--790d71f798353ecb7587c3aa0ea06a7f356654ead0a1728dd9ef57105fa29885.gz), [JUnit ROOT](memoire-r25/integration-root-r2.xml--910b2efd4cbe865de44f6bb176ed4ef9d90832e552775226f06f0bd9506cff95.gz), [reçu qualité](preuves-root/memoire-pg-qualite-root-r2-2026-10-02-resultat.json--ec9aa447a7de9cae78d05e356888e8e410884f333acd3c4fc66ee8dd17129f98.gz).

Le store et les outils mémoire utilisent un vrai PostgreSQL avec pgvector, dans un PGDATA tmpfs jetable plafonné à 256 MiB et un conteneur plafonné à 512 MiB, avec image locale sans pull. Les embeddings sont simulés; les tests de cycle Docker de la fixture utilisent des doubles. Ces deux types de preuve restent distingués.

**Limites :** aucune qualification CSV sur PostgreSQL, aucune preuve de durabilité disque, crash/reprise de production, fournisseur d’embeddings réel, parcours Core, ni qualification complète de la mémoire premium. Cette campagne qualifie le périmètre de tests sélectionné, pas tout le produit.

## Sources, preuves et conservation

Les 1093 empreintes finales sont dans [SOURCES-FINALES.json](SOURCES-FINALES.json), vérifiées contre les fichiers actuels. Seules les quatre sources de test/fixture modifiées sont copiées dans les gzip. Le scratch mémoire et les préfixes ROOT memoire-pg sont conservés hors caches/SQLite; les sources générales et Core ne sont pas recopiés. Les six chemins Core explicitement ajoutés au snapshot sont contrôlés par empreintes seulement; aucune suite Core n’est relancée pour R25.

[MANIFEST.json](MANIFEST.json) décrit les gzip, SHA-256 et tailles. [QUALIFICATION.json](QUALIFICATION.json) est créée après le README et après la vérification des gzip, liens documentaires, sources et historiques R19–R23.

### Répartition de la campagne sélectionnée

- `test_memoire_embeddings` : 11 cas.
- `test_memoire_outils` : 14 cas.
- `test_memoire_store` : 26 cas.
- `test_openclaw_memoire` : 20 cas.
- `test_postgres_fixture_doubles` : 11 cas.

### Documents sélectionnés

- [docs/programme/LOT-QUALIFICATION-MEMOIRE-PG.md](docs/docs--programme--LOT-QUALIFICATION-MEMOIRE-PG.md--6c8c66a6269f9d68ef5bdc8b04c20e9826c9aebb4cdeb79f6ca8a261d6823f1e.gz)
- [docs/programme/REPRISE-PLAN-2026-10-02.md](docs/docs--programme--REPRISE-PLAN-2026-10-02.md--5d2a1afb2d34c3153c458f8b9076cadeed7a54bee59220055510e97ee5a3456c.gz)
- [docs/programme/BILAN-RESTRUCTURATION-2026-09-30.md](docs/docs--programme--BILAN-RESTRUCTURATION-2026-09-30.md--ea2fda27e7573efd88352ba9c3f6c1b31ca01a6260b694320a5b9f9796b5d8fa.gz)
- [docs/produit/PERIMETRE-MODULES.md](docs/docs--produit--PERIMETRE-MODULES.md--1eefefad1dda514b851c18b25a332543740f5709e1fa5ddc6e329542e961aa37.gz)
- [docs/produit/VISION-ENTREPRISE-APPRENANTE.md](docs/docs--produit--VISION-ENTREPRISE-APPRENANTE.md--88e7824afe178a89a5158600cccc475ca208cd7ad069ade2b7a059f16fb14e73.gz)
