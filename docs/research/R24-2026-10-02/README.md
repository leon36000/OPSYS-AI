# R24 — transcription locale de clip et annulation explicite

La consolidation de campagnes ROOT sélectionnées contient **481 cas JUnit effectifs**, sans failure, erreur ou skip, dans cinq campagnes distinctes. Chaque testcase est compté une fois; les compteurs imbriqués de suites ne sont pas additionnés. Les preuves auteur et reprises historiques sont conservées sans addition au total ROOT.

[Sélection ROOT](voix-r24/preuves-selection-root-r1.json--d5552ad24916760c8a292f5ad643919d1439bf1720e6b7e309d1fd00093576e4.gz), [auteur originel](voix-r24/rapport-r24-auteur.md--24301d8af85f39db3f143fa23812e6d203f098d862c19835993614ccf66e7999.gz), [amendement auteur r2](voix-r24/rapport-r24-auteur-r2.md--605bbbdc7f1b81a5ae124d83be712d06939c002dd7ece367dd47697e019f67df.gz). Les quinze empreintes auteur résultent de ces deux rapports distincts; l’amendement remplace uniquement des chemins présents dans le reçu initial. Chaque campagne reste liée à son reçu original; aucun run n’est renommé. Oxlint et oxfmt finaux sont vérifiés avec codes retour et SHA des journaux. Le run r3 conserve son rejet de shard WebSocket sans cas; sa campagne extension antérieure aux dernières corrections ne compte pas dans cette consolidation.

Le provider voice-call-local-clip est sélectionné explicitement. Il finalise un clip au Stop; le contrat discardAudio/cancel porte l’annulation entre UI, protocole, Gateway et provider. Les tests ciblent aussi la compatibilité WebSocket legacy.

**Limites :** cette QA ne qualifie ni un moteur ASR réel ni sa précision fr-CA, ni la latence terrain, ni du streaming de transcription live. Aucun service ASR externe n’est contacté par l’archiveur; il ne lance aucun test, build ou navigateur. Les transports testés par la campagne restent des endpoints/fixtures de test locaux.

## Campagnes ROOT sélectionnées

- `gateway` : 320 cas, [JUnit](voix-r24/core-voix-r24-root-r3-gateway.xml--0cc138d69a9122c62a1eab9f718cc2af4eae2da385ce7f7079f1ecd637e4fade.gz), [reçu original](voix-r24/core-voix-r24-root-r3-resultat.json--843a7eea4bffb62784b0baa410b7de398b3835aeb9c02b45e78a467c2bb2650a.gz).
- `protocol` : 2 cas, [JUnit](voix-r24/core-voix-r24-root-r3-protocol.xml--a2d15500fbb4aedda8d7aae43ca49fdefb55d12b1e5e3de69dd0151bbb6cafca.gz), [reçu original](voix-r24/core-voix-r24-root-r3-resultat.json--843a7eea4bffb62784b0baa410b7de398b3835aeb9c02b45e78a467c2bb2650a.gz).
- `ui` : 63 cas, [JUnit](voix-r24/core-voix-r24-root-r3-ui.xml--8be0d4dc988b37e0aecc8b333bcdc67a52d758aaca8a8913a44ccf75fd625277.gz), [reçu original](voix-r24/core-voix-r24-root-r3-resultat.json--843a7eea4bffb62784b0baa410b7de398b3835aeb9c02b45e78a467c2bb2650a.gz).
- `ws` : 29 cas, [JUnit](voix-r24/core-voix-r24-root-r4-ws.xml--bfb4abef0afb457de0be962fcf533b6805030be1dbf4e191791deaa2f34980cb.gz), [reçu original](voix-r24/core-voix-r24-root-r4-resultat.json--eba31d35751fbeaff9f0109efeb7fc55fd893bfb74a8d5c6425df194647d497b.gz).
- `extension` : 67 cas, [JUnit](voix-r24/core-voix-r24-root-r5-extension.xml--4e86344f641ea3192e40fe4e888147eb03bf6952d2d2d88e764f285afe8a04c5.gz), [reçu original](voix-r24/core-voix-r24-root-r5-resultat.json--6f8160d0beca7339a2d49e838cb3a7f79e86dd8d63ff49dc62150534f5b61a8b.gz).

## Sources et conservation

Les 35210 empreintes Core/liaison finales sont dans [SOURCES-FINALES.json](SOURCES-FINALES.json), contrôlées contre les fichiers actuels. Seules les 15 sources finales du lot sont copiées. Le scratch voix, les préimages présent/absent et les preuves ROOT closes sont conservés hors caches/SQLite. Les historiques R19–R23 et R25 sont vérifiés, sans modification.

Le contrôle frais de sources porte sur le scope Core plus liaison_cibles.py du snapshot R24. Les empreintes Python de R25 demeurent historiques, sans union présentée comme une nouvelle campagne Python. Les écarts inter-runs sont limités aux chemins extension explicitement autorisés; extension et qualité finales correspondent exactement au snapshot final.

[MANIFEST.json](MANIFEST.json) décrit tailles et SHA-256 brut/gzip. [QUALIFICATION.json](QUALIFICATION.json) est créée après le README, la vérification de tous les gzip et des liens. [POST-CHECK.json](POST-CHECK.json) consigne le dernier contrôle après existence de la qualification.

## Documents sélectionnés

- [docs/programme/LOT-DICTEE-LOCALE-CORE.md](docs/docs--programme--LOT-DICTEE-LOCALE-CORE.md--70d990d91c9a33356090d1684fcf24a01f64bbb016f133ebdc4e082b95f349e6.gz)
- [docs/architecture/DICTEE-LOCALE-CORE.md](docs/docs--architecture--DICTEE-LOCALE-CORE.md--607839b471e476b511ee1941719ef5ab803acb827d7a986d256fa36ca352ed8e.gz)
- [docs/programme/REPRISE-PLAN-2026-10-02.md](docs/docs--programme--REPRISE-PLAN-2026-10-02.md--a880e349436f8b92c0d067bd72a8259d02d26ed6a27dbe828acecd50f6cf467f.gz)
- [docs/programme/BILAN-RESTRUCTURATION-2026-09-30.md](docs/docs--programme--BILAN-RESTRUCTURATION-2026-09-30.md--fd82272de78ae59fea4b5cca62831b560b830ae0d56957d43f482b483cf883fb.gz)
- [docs/programme/REPRISE-DICTEE-BILAN-R24.md](docs/docs--programme--REPRISE-DICTEE-BILAN-R24.md--2baaa9a7649a0aca6ba8e6aa3e168127f63dcd4c21fabd2f15302900ae83ef82.gz)
