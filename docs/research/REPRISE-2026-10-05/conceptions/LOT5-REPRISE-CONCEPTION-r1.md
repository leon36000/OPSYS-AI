# Lot 5 — scénario et raccords de reprise

**Verdict : PARTIEL, aucun cycle cron→mémoire après panne n’est prouvé.** Scénario fictif à qualifier : profil M03 explicitement synchronisé, déclencheur cron interne autorisé, outil unique `m3_lire_devis` sur un devis de test; M10 lie la session à la même affaire et fournit son paquet. L’outil est catalogue réel T0/N0, lecture seule. Le garde Core est branché au hook `before-tool-call`, mais les niveaux N0 ne constituent pas un gate M10; ici le contexte nourrit le tour, il ne prétend pas l’autoriser. Une admission de cycle borne tours/reprises/concurrence et vérifie profil, révision, outil et département. La capture M10 ne contient que l’issue/code de l’outil, avec clé stable dérivée de session+toolCallId.

**Preuves actuelles.** Les tests Python vérifient lease/epoch/fencing, ACK durable simulé (`job-fictif-1`), révocation et rejeu; la projection cron et les déclarations restent `execute:false`. L’intégration Core→serveur MCP Python/SQLite, fournisseur factice, prouve réserve, usage reçu, budget insuffisant, refus du même cycle sans second dispatch et refus d’un outil révoqué sur ancienne révision. Les tests M10 prouvent qu’un dépôt rejoué avec la même clé ne duplique pas le fait. `opsys-contexte-engine.afterTurn()` journalise l’échec/refus puis abandonne : pas d’outbox durable ni reprise après redémarrage. Ces preuves séparées ne prouvent ni exécution d’un vrai cron Core, ni cycle Core complet avec M10 réel.

**Plus petit dossier de fermeture.** Deux raccords observables restent nécessaires au parcours demandé : (1) consommer l’ACK/lease cron dans un vrai déclenchement Core avec cycle d’admission; (2) outbox POSTFLIGHT persistante, bornée et cloisonnée contenant seulement l’affaire autorisée, département, outil, issue/code, clé et état/âge d’essai — aucun texte utilisateur, sortie brute, secret ou prompt. Premier test ciblé : partir du test d’intégration Python HTTP d’admission, invoquer une fois le chemin Core configuré M10; faire réussir le dépôt serveur puis perdre la réponse, redémarrer le Core et rejouer l’outbox. Critère : exactement un fait M10 via la même clé, aucune seconde invocation provider sur le même cycle; faible budget/révocation pré-dispatch refusent sans effet; usage fournisseur inconnu reste réservé et requiert rapprochement humain. Le raccord cron réel doit être qualifié séparément avant de déclarer le scénario exécuté.

**Sources — SHA-256**

```text
docs/programme/PROGRAMME-24H-2026-10-04.md  61a264d08d593f11808ded4c89ac514d34675e376df07526841f8b1c105b702e
docs/programme/AUDIT-DIRECTION-2026-10-04.md  e8f49c59e3713e4b65bc2106ca392e0dc96c2dcf65fda2c4c20c43824f155bea
src/opsys/agents_cron_autorite.py  b5bd72745274259cf10ac73d2a089babf9302af2ebb1978680c4d13ee90ba554
src/opsys/agents_declencheurs.py  bed85a862c25189058f7876c2a3e28aac064cb38c1150a2cbcfa56cc9cc6fb5a
src/opsys/admission_agents.py  97b34be72ad6aa8653dc707da7b9ee2c22a5ebd6165b8a6685787eae7b7b3b00
tests/test_agents_cron_autorite.py  0878b62499b64d307f4c74a86d91909b53a205bf67c92c5cdf5ff50955de33ee
tests/test_agents_declencheurs.py  a5ac9ce2ca50fde54f0726a0b36e077f64a1216c64a50dc901164b8e9691341c
tests/test_admission_agents.py  c202e6ca284f719df2c499a06169ef0838e366a144a02a6c88be26d22d284e50
core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts  f5a1a4279c3c2ef0f67bab7f17dda8c2a9f53b6f9eb837a0e238278d06b578d5
core/src/agents/embedded-agent-runner/opsys-runtime-admission.python-http.integration.test.ts  c63667a5cb9758994254f1341cc0386c817ffc4e88f328d3d1d655b71f4ad7ba
core/src/context-engine/opsys-contexte-engine.ts  e5c2c2d6d9013d92eda66665932aa584ddb258d6093c706c5ef6f7a2355dac8f
core/src/context-engine/opsys-contexte-depot.ts  68ee9b5b0e15b3f5595973cef4926399b6162ce918d0d44936f4ef31fc7a6359
core/src/context-engine/opsys-contexte-garde.ts  06eddb9bb0754dcafd62b240acb41ee5482c867b2414583f011c7d457a9d68bb
core/src/agents/agent-tools.before-tool-call.policy.ts  dcbe69694d5ac987e5c73f7d2717e371eff14f83c3e7671ad997a05678595804
departments/m10-memoire/tests/test_outils_agent.py  b13da0820096e07c1794bb81b5cd2c01a0015e25ad3198cd6a378cdb79406f11
```
