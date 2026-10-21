# R32 — raccord M3/M4 des cohortes de temps

ROOT indépendant : 80 IDs uniques, zéro échec/erreur/skip, 0,828 s; snapshots 1110 sources stables. Ruff et vérification du catalogue des outils ont réussi (codes 0/0). Le scénario positif traverse les outils M3/M4 et leurs registres/bus mais contient un seul WCT fictif : observation admise, statut de cohorte insuffisant aux minima R30 20 train/10 holdout. Aucun gain terrain ni activation de candidate/barème n’est établi.

[MANIFEST.json](MANIFEST.json) · [SOURCES-FINALES.json](SOURCES-FINALES.json) · [QUALIFICATION.json](QUALIFICATION.json) · [POST-CHECK.json](POST-CHECK.json).

[Contrat R30](../../architecture/CALIBRATION-COHORTES-TEMPS.md) · [lot R30](../../programme/LOT-COHORTES-TEMPS.md) · [raccord R32](../../programme/LOT-RACCORDEMENT-COHORTES.md).

Dépendance pure R30 conservée dans [son archive](../R30-2026-10-02/README.md), sans recopier son histoire.

- [departments/m03-estimation/src/m3_estimation/calibration_raccord.py](sources-r32/departments--m03-estimation--src--m3_estimation--calibration_raccord.py--4a811b2044e2fc458d01093b8c8ecd2cf443a7a451a0c66769b7a0d4094695a6.gz)
- [departments/m03-estimation/src/m3_estimation/outils.py](sources-r32/departments--m03-estimation--src--m3_estimation--outils.py--100f888817846372b15a3fee2dc37760b818aff6d0e44d6d08c66a021d07c4e4.gz)
- [departments/m03-estimation/tests/test_calibration_raccord.py](sources-r32/departments--m03-estimation--tests--test_calibration_raccord.py--65ac5553b66980605adbd5f24793a5f619ea13d9036098adfe5a19a84b57ea10.gz)
- [departments/m04-field-ops/src/m4_field_ops/calibration_projection.py](sources-r32/departments--m04-field-ops--src--m4_field_ops--calibration_projection.py--c5818b65c3dad37933db175f6eb359b3e28fde38521974ead342a50f556d88a6.gz)
- [departments/m04-field-ops/src/m4_field_ops/outils.py](sources-r32/departments--m04-field-ops--src--m4_field_ops--outils.py--7303a22f610c8a6bd9b1e7454e99d0bd3f0b5427882c2fe10370ea9d3f68cfad.gz)
- [departments/m04-field-ops/tests/test_evenements_m4.py](sources-r32/departments--m04-field-ops--tests--test_evenements_m4.py--022a0d39cb7b40e1ccd48e0836cbb2e519ed5de3114ffa82509a4b245db8353b.gz)
- [docs/architecture/CALIBRATION-COHORTES-TEMPS.md](docs/docs--architecture--CALIBRATION-COHORTES-TEMPS.md--505464065c76a41aee679fafba776400b5c71a783e26cea21c9a9810ec1addd5.gz)
- [docs/programme/LOT-COHORTES-TEMPS.md](docs/docs--programme--LOT-COHORTES-TEMPS.md--ea7e1afb048796e7f3b4ef246e261fb635290f4559cd0759775d9bec61992595.gz)
- [docs/programme/LOT-RACCORDEMENT-COHORTES.md](docs/docs--programme--LOT-RACCORDEMENT-COHORTES.md--9fccc952861c4794c7aef263931f2f83bdef39c3f41369e9502f895b2a8be820.gz)
- [cohortes-raccord-qualite-root-r1-2026-10-02.log](preuves/restructuration-opsys-2026-09-30--preuves--cohortes-raccord-qualite-root-r1-2026-10-02.log--011be23053e1c7ebb11d429f9141c8e7a10816523eb24bec5c60b737a692c386.gz)
- [cohortes-raccord-root-r1-2026-10-02.log](preuves/restructuration-opsys-2026-09-30--preuves--cohortes-raccord-root-r1-2026-10-02.log--7aab9d03d5aad3ae7953c0ac55e01a47a25a852128e93ee579eb4dadf81d7df0.gz)
- [cohortes-raccord-root-r1-2026-10-02.xml](preuves/restructuration-opsys-2026-09-30--preuves--cohortes-raccord-root-r1-2026-10-02.xml--b51dfd512c98e3ead98f3aca714bda4c41c2cfe14a03b19fbbfe9413a6b9cdcb.gz)
