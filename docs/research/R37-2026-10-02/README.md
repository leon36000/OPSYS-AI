# R37 — synthèse privée Fusion

ROOT58 : 58 cas uniques verts, zéro échec/erreur/skip; 1 111 sources stables. Ruff cinq fichiers vert. Le scénario PostgreSQL M03 est entièrement synthétique : 51 séries/52 versions paginées. Les préimages R37-r2 ne concernent que synthèse et test; application/PDF UI récupérés byte-à-byte de R28 après édition, donc explicitement pas des préimages prépatch. Le dashboard n’expose ni contenu, titre, montant, SHA, URI ni citation. La base financière et les pilotes CSV/PDF restent SQLite seuls; aucun PostgreSQL pilote qualifié. Aucune qualification métier/entreprise n’est inférée.

- [src/opsys/console/fusion_synthese.py](sources-r37/42e5c85c79e8ea10--fusion_synthese.py.gz)
- [tests/test_console_fusion_synthese.py](sources-r37/4100931904a36317--test_console_fusion_synthese.py.gz)
- [src/opsys/console/application.py](sources-r37/7c99c96cf2f1daad--application.py.gz)
- [src/opsys/console/fusion_pdf_ui.py](sources-r37/1c7a330152022f9f--fusion_pdf_ui.py.gz)
- [Préimage R37 r2 — fusion_synthese.py](origines-et-recuperations/3dee4592bc4f7348--fusion_synthese.py.gz)
- [Préimage R37 r2 — test_console_fusion_synthese.py](origines-et-recuperations/a71323c9744f9876--test_console_fusion_synthese.py.gz)
- [R28 récupéré après édition — application.py](origines-et-recuperations/b57c57506e26815e--application.py.gz)
- [R28 récupéré après édition — fusion_pdf_ui.py](origines-et-recuperations/e22c63df6a8ff0dd--fusion_pdf_ui.py.gz)
- [FREEZE-R37-r1.json](preuves/39c7eb4695cc3592--FREEZE-R37-r1.json.gz)
- [FREEZE-R37-r2.json](preuves/df989fda64da0d76--FREEZE-R37-r2.json.gz)
- [rouge-r1.json](preuves/bb6248cbf6d5e2d8--rouge-r1.json.gz)
- [rouge-refus-pages-r1.json](preuves/18eebc6039d517fa--rouge-refus-pages-r1.json.gz)
- [rouge-refus-pages-r1.log](preuves/9e462d235a0f8f4e--rouge-refus-pages-r1.log.gz)
- [receipt-tests-r2-2026-10-02.json](preuves/f7db14a9633f599f--receipt-tests-r2-2026-10-02.json.gz)
- [tests-r2-2026-10-02.log](preuves/b53866f7a853267d--tests-r2-2026-10-02.log.gz)
- [tests-r2-2026-10-02.xml](preuves/49f67b0d851472b3--tests-r2-2026-10-02.xml.gz)
- [receipt-ruff-r2-2026-10-02.json](preuves/bdbf707f12ed4829--receipt-ruff-r2-2026-10-02.json.gz)
- [ruff-r2-2026-10-02.log](preuves/82b3e6a6c090a576--ruff-r2-2026-10-02.log.gz)
- [fusion-synthese-root-r1-2026-10-02-resultat.json](preuves/ec148fdddad85917--fusion-synthese-root-r1-2026-10-02-resultat.json.gz)
- [fusion-synthese-root-r1-2026-10-02-avant.json](preuves/f1c748365516155e--fusion-synthese-root-r1-2026-10-02-avant.json.gz)
- [fusion-synthese-root-r1-2026-10-02-apres.json](preuves/1372ccd8f0358e25--fusion-synthese-root-r1-2026-10-02-apres.json.gz)
- [fusion-synthese-root-r1-2026-10-02.log](preuves/b53866f7a853267d--fusion-synthese-root-r1-2026-10-02.log.gz)
- [fusion-synthese-root-r1-2026-10-02.xml](preuves/ac4f50ef549e3aa6--fusion-synthese-root-r1-2026-10-02.xml.gz)
- [fusion-synthese-qualite-root-r1-2026-10-02-resultat.json](preuves/29acf6322361e668--fusion-synthese-qualite-root-r1-2026-10-02-resultat.json.gz)
- [fusion-synthese-qualite-root-r1-2026-10-02-avant.json](preuves/18c3e14eebeb3da7--fusion-synthese-qualite-root-r1-2026-10-02-avant.json.gz)
- [fusion-synthese-qualite-root-r1-2026-10-02-apres.json](preuves/ace838b8e452c4d9--fusion-synthese-qualite-root-r1-2026-10-02-apres.json.gz)
- [fusion-synthese-qualite-root-r1-2026-10-02.log](preuves/82b3e6a6c090a576--fusion-synthese-qualite-root-r1-2026-10-02.log.gz)
- [REPRISE-BILAN-R32-R42-2026-10-02.md](docs/e4910e340a43cff9--REPRISE-BILAN-R32-R42-2026-10-02.md.gz)

R28 et R26 sont conservés par index/hash qualifiés, sans recopier leurs archives.
