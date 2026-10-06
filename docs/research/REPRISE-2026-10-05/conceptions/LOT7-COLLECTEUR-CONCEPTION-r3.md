# Lot 7 — conception r3 (lecture seule)

## Seam et autorité

`run-entry.ts` est le propriétaire logique des candidats/fallbacks, mais sa branche `acceptedTerminal` (vers 655+) décrit l’issue du tour, pas la réalité des outils. Il ne faut donc pas filtrer les observations sur succès terminal, statut fournisseur, abort ou `promptError`. Chaque résultat d’outil vérifié doit être journalisé au moment où il est observé, indépendamment de l’usage fournisseur et de l’issue ultérieure.

Le seam exact d’observation est `agent-bundle-mcp-runtime.ts`, après retour de l’appel MCP réel, validation du résultat et nouvelle assertion de run courant; l’ACK de ticket ciblé est une preuve de ciblage, jamais une preuve de succès métier. Le callback doit rester par-exécution et transporter seulement le `toolCallId` réel, cible ticket vérifiée et `CallToolResult` structuré. Le propriétaire du journal/enqueue est `run-entry.ts` (ou un writer privé qu’il crée et passe à chaque candidat), afin que les retries partagent un même journal sans donner l’autorité au runtime MCP de session. L’enqueue doit arriver avant que le run puisse effacer/abandonner l’essai; les faits valides d’un candidat restent acquis si l’essai suivant ou le fournisseur échoue.

L’identité DB manque encore au seam actuel. Le seul ancrage sûr déjà disponible est le reçu `TranscriptTurnAdmission` du `UserTurnTranscriptRecorder`: `attempt-finalize.ts:214-224` l’obtient puis valide une ancre transcript avec `agentId/sessionId/sessionKey/storePath`; `context-engine-turn-attempt.ts:200-209` ouvre la DB depuis `boundary.admission.agentId/storePath`. R3 doit faire capturer ce reçu par l’hôte avant le premier dispatch d’outil et le fournir au writer run-owned; il doit vérifier `run/session/sessionKey` contre l’identité de l’entrée et le `sessionTarget`. Il ne faut ni reconstruire un chemin depuis config, ni utiliser un `storePath` de prompt, ni ouvrir une seconde base. Si aucun reçu canonique n’existe avant l’effet, désactiver/refuser la collecte avant dispatch. Le writer ouvre la même base via `openOpenClawAgentDatabase({agentId, path: admission.storePath})`, puis utilise `enqueueOpsysPostflightLots`; son contrôle propriétaire et l’admission d’écriture restent actifs.

## Échecs et bornes

Les refus métier structurés observés sont des faits et peuvent être persistés. Erreur MCP/transport, `isError`, résultat illisible ou `approval_pending` demeure inconnu et ne fabrique pas un résultat. Une erreur d’enqueue après effet ne doit ni effacer le résultat du modèle, ni rejouer l’outil/fournisseur: garder le même envelope en mémoire pour une seule reprise locale bornée/idempotente si l’autorité DB est encore courante; sinon émettre une erreur opérationnelle explicite et ne pas annoncer la complétude. Crash avant commit outbox peut perdre un fait; sans idempotence/réconciliation de l’outil distant, l’éviter par replay est dangereux et exactly-once est hors garantie.

Le plafond 20 du collecteur actuel silencieusement abandonne le 21e fait. Avant chaque appel admissible, réserver/contrôler la capacité; à saturation, refuser le dispatch métier suivant explicitement. Une collision de clé tc-40 identique et identique en payload est idempotente; même clé avec contenu/cible divergent est un conflit dur: garder le premier fait, refuser d’ajouter l’observation conflictuelle, alerter, et bloquer les prochains appels avec cet identifiant. Ne pas déduire `serverName` du département: comparer le serveur réel routé par le runtime avec le serveur attesté par le ticket et la whitelist, puis conserver le département du reçu d’admission comme dimension indépendante.

R1 reste rejeté/non intégrable; cette note ne change aucun code et aucun test/QA n’a été lancé. Elle n’établit pas la disponibilité du reçu transcript au moment précis où le runtime appelle l’outil: ce point doit être démontré par le propriétaire avant toute implémentation.

## Sources (SHA-256)

- `core/src/agents/embedded-agent-runner/run-entry.ts`: `c70c72a327d94403a5bd3add523d15308f15926407ed42bbd0846cb4ceb29d42`
- `core/src/agents/agent-bundle-mcp-runtime.ts`: `d2a33ba0ca6294eba40f03bbcdbcc05233aa6abff9c9b2a206f96676ee9f7356`
- `core/src/agents/embedded-agent-runner/run/attempt-finalize.ts`: `14da0aa22d1a9a53f9ca58b4192b06d11fdbc3d83b0a361edd08d89200304509`
- `core/src/sessions/user-turn-transcript.ts`: `c11dc7f334129a8dc971a0c88c9f54919d8f904d93e67f85cef16495af0b7427`
- `core/src/agents/harness/context-engine-turn-attempt.ts`: `2cf023ce90dbcd21422bb6b737c06258031b59d562604747d03fe9674578ba51`
- `core/src/config/sessions/session-accessor.transcript-target.ts`: `6b2ea699b4b874d37a624c057fa3f8fa3eaaac66484256ffe752f967f54ba700`
- `core/src/agents/harness/opsys-postflight-outbox.ts`: `38e5b3e4241cd4581dd6df246d4f0682e5ccc5d5c59e834d8643c6c49c8e6525`
- `core/src/agents/harness/opsys-postflight-outbox.worker.ts`: `24ac7540eaefc51b4b4b367d93d9ca8cb4148e36f044baf9d9f65c4f0b848705`
- `core/src/agents/embedded-agent-runner/run/attempt.ts`: `f6cb86cd9c27cb7aee6e8b397e5a71d0091026475107549638125bf838e7fcf4`
