# Revue ciblée du raccord collecteur / outbox — r2

Lecture seule, aucune QA. Cette révision corrige les nuances sur le retour MCP et les plafonds; r1 reste inchangée. Les risques désignent les contrats du futur raccord, pas une défaillance générale du runtime existant.

## Risques et tests discriminants

1. **Admission à lier avant le premier effet.** Le reçu canonique est créé avec la persistance de l’entrée (`core/src/sessions/user-turn-transcript.ts:371-380,506-511`), et la lecture propriétaire le refuse si bloqué ou déjà envoyé au provider (`core/src/sessions/user-turn-transcript-admission.ts:35-45`). L’admission est raccordée avant dispatch (`core/src/agents/harness/context-engine-turn-attempt.ts:97-125`). L’API outbox accepte toutefois seulement un lot fermé et précise qu’elle n’authentifie pas sa provenance (`core/src/agents/harness/opsys-postflight-outbox.ts:72-83`; payload `...outbox.worker.ts:41-48`). Le nouveau raccord doit lier son observation/réservation à ce reçu, agent, session et store; aucune donnée d’outil ne doit produire un effet avec reçu absent ou étranger. **Test :** reçu absent/ancienne autre-session → aucun appel MCP/provider ni écriture; reçu courant → une admission.

2. **Ne pas confondre département admis et cible ticketée.** Le runtime d’admission capture profil/révision/département (`core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts:192-224`). Pour les tools couverts, le runtime bundle demande un ticket avec session-agent, serveur/outil, affaire, arguments figés; `createOpsysCibleTicketMeta` refuse mismatch outil/serveur et transmet au call MCP le même snapshot d’arguments (`core/src/context-engine/opsys-contexte-cible-ticket.ts:56-75,91-139`; `core/src/agents/agent-bundle-mcp-runtime.ts:1140-1207`). Le collecteur postflight courant, lui, dérive son `departement` du `sessionKey` et filtre les résultats via liste de noms/config (`core/src/context-engine/opsys-contexte-engine.ts:437-447`, `.../opsys-contexte-depot.ts:22-29`). Préserver séparément dans l’observation l’admission département et la cible réellement ticketée/outillée, corrélées au même call; ne pas reconstruire la cible depuis le seul nom suffixé. **Test :** outil/serveur/arguments/cible ticket non concordants ou call d’un autre serveur, rien ne peut être reclassé sous la source admise.

3. **Retour MCP connu malgré l’issue ultérieure du run.** Le collector lit l’issue structurée de chaque `toolResult` (`core/src/context-engine/opsys-contexte-depot.ts:51-77,93-115`) et `afterTurn` collecte les messages du tour sans utiliser terminal/usage du provider (`.../opsys-contexte-engine.ts:429-465`). Un résultat MCP connu doit donc rester capturable même si le run se termine ensuite par abort/erreur/fallback ou usage inconnu. En revanche, une issue d’outil vraiment indéterminée (`isError` transport, contenu illisible, approbation pending) n’est pas un fait `ok/refus` et les tests le vérifient (`.../opsys-contexte-depot.test.ts:96-112`); journaliser ces inconnues serait un futur périmètre séparé. **Test :** résultat MCP connu suivi d’un terminal abort/usage inconnu reste une seule observation/fait; erreur transport ou pending ne devient jamais `ok` ou `refus`.

4. **20 appels en mémoire avant effet ≠ capacité durable garantie.** Le contrat amont de collecteur réserve le quota mémoire de 20 appels avant effet; ce plafond doit rester pré-effet et testable. La base outbox a des limites distinctes: au plus 20 faits par lot, 256 lots et 1 MiB (`core/src/agents/harness/opsys-postflight-outbox.worker.ts:21-24,127-171,311-410`). Ce dernier quota est vérifié à l’enqueue, pas réservé globalement pour tous les effets futurs; une saturation DB ultérieure reste possible. Le moteur courant envoie M10 par paquets de 20 après collecte (`core/src/context-engine/opsys-contexte-engine.ts:443-465`). **Test :** 21e appel mémoire refusé avant effet; séparer ce cas de DB pleine à 256/1 MiB, où aucune promesse de réservation durable préalable n’est faite.

5. **Une erreur post-call ne doit jamais relancer l’effet.** `callTool` attend la réponse distante, puis appelle `validateResult` et peut encore échouer avant retour (`core/src/agents/agent-bundle-mcp-runtime.ts:1193-1209`); `runMcpRequest` vérifie aussi abort après résolution distante (`.../agent-bundle-mcp-runtime.ts:635-659`). Le résultat distant ou l’effet peuvent donc exister même si l’appelant reçoit une exception. De même, l’enqueue refuse contenu divergent/collision (`.../opsys-postflight-outbox.worker.ts:347-360`) et peut échouer à écrire; ne pas re-dispatcher tool/provider à la suite de ces erreurs. **Test :** un seul appel distant si abort post-retour, validation échoue, collision ou panne DB; observation gardée en état de reprise/revue, sans replay d’effet.

## Clés M10

Conserver strictement `depositKey`: SHA-256 tronqué à 40 hex (`core/src/context-engine/opsys-contexte-depot.ts:79-83`). La clé namespace de l’outbox est 64 hex; son schéma accepte 40 ou 64 et un test persiste/réouvre/rejoue les deux (`core/src/agents/harness/opsys-postflight-outbox.worker.ts:30,197-210`; `.../opsys-postflight-outbox.test.ts:321-363`). Ne recalculer ni migrer ces clés/ACK.

## SHA-256 des sources

- `core/src/agents/agent-bundle-mcp-runtime.ts` d2a33ba0ca6294eba40f03bbcdbcc05233aa6abff9c9b2a206f96676ee9f7356
- `core/src/context-engine/opsys-contexte-cible-ticket.ts` 58df5e0f8f881c90702ad50666e06651fc1893d5a36327e74aed82c9ee90d605
- `core/src/agents/harness/opsys-postflight-outbox.ts` 38e5b3e4241cd4581dd6df246d4f0682e5ccc5d5c59e834d8643c6c49c8e6525
- `core/src/agents/harness/opsys-postflight-outbox.worker.ts` 24ac7540eaefc51b4b4b367d93d9ca8cb4148e36f044baf9d9f65c4f0b848705
- `core/src/agents/harness/opsys-postflight-outbox.test.ts` 0894250db3a59d68d927a531422943265c7b93b4fa9d63b8ca5d6acacb2d86d2
- `core/src/context-engine/opsys-contexte-engine.ts` e5c2c2d6d9013d92eda66665932aa584ddb258d6093c706c5ef6f7a2355dac8f
- `core/src/context-engine/opsys-contexte-depot.ts` 68ee9b5b0e15b3f5595973cef4926399b6162ce918d0d44936f4ef31fc7a6359
- `core/src/context-engine/opsys-contexte-depot.test.ts` 76628d2d92fd2eaf31587b1e4ec85a7d369f738cd3050bc1a48dbb3213b0a3fd
- `core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts` cae5c085a07c53f10daaef70b35de4b57014fb4d27202e9d27d70388e1ad2a8c
- `core/src/sessions/user-turn-transcript.ts` c11dc7f334129a8dc971a0c88c9f54919d8f904d93e67f85cef16495af0b7427
- `core/src/sessions/user-turn-transcript-admission.ts` e059fb43376be9f4d7da612025476808227bb59a25f337a5d41aac45d34a1c0f
- `core/src/gateway/server-methods/chat-user-turn-recorder.ts` 92b90c245e3ea5481562cdb347aaabef3807d451538dd7817ffa5e15d82c3ccc
- `core/src/agents/harness/context-engine-turn-attempt.ts` 2cf023ce90dbcd21422bb6b737c06258031b59d562604747d03fe9674578ba51
