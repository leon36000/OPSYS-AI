# Lot 5 — raccord minimal du collecteur (lecture seule)

Le chemin ne transporte pas de provenance fiable au dépôt. `createOpsysRuntimeAdmissionStreamFn` (admission.ts:377–439) détient une capture vérifiée, mais locale au wrapper; la réservation réussie vérifie profil/department/cycle et l’ID (l.179–222), tandis que `afterTurn` ne reçoit aujourd’hui que session/messages (lifecycle.ts:280–293). `OpsysContexteEngine.deposit()` résout encore l’affaire avec `collectUserText()` (engine.ts:452–457): ce chemin prompt/session ne peut pas prouver la cible d’un appel.

**Trois jonctions minimales, données internes uniquement :**

1. Dans le propriétaire d’essai qui compose l’admission (attempt-prompt-submit.ts:139+), créer un reçu typé par cycle et ne l’enregistrer qu’après `accord_neuf` + `reservationMatchesCapture`. Conserver `profilId`, révision capturée, département serveur, run/cycle/attempt; aucun reçu sur refus ou erreur/usage inconnu. Le reçu courant expose département retourné par le serveur; la révision vient de la config validée envoyée au serveur, car la réponse n’exige `revision_profil` que si ce champ est présent (admission.ts:111, 208). Ne pas la présenter comme un écho serveur.
2. À l’exécution, materialize possède déjà le vrai `toolCallId` et le nom outil (materialize.ts:478–489), mais ne passe pas l’ID à `runtime.callTool`. Passer ces valeurs en paramètre interne; dans runtime (runtime.ts:1140–1149) et `createOpsysCibleTicketMeta` (ticket.ts:108–145), émettre un reçu cible non secret seulement après ticket valide, à partir de `sessionKey`, `state.affaireId` et de l’outil autorisé. Le secret `_meta` reste exclu. Joindre le résultat réseau réel au même reçu/call-id; ne pas reconstituer l’affaire depuis texte utilisateur.
3. Le collecteur par run accepte les résultats sûrs (`collectDepositFacts`, depot.ts:51–115: refus explicite / succès structuré; illisible, attente approbation ou erreur transport = inconnu), puis `afterTurn` persiste le lot fermé via `enqueueOpsysPostflightLots` (outbox.ts:72–83) avant envoi M10. Pour couvrir crash après l’effet outil mais avant `afterTurn`, le collecteur doit aussi journaliser le résultat dans l’outbox au point 2; `afterTurn` ne sera qu’un filet de rapprochement, sans synthèse de réussite. Passer `sessionIdUsed` depuis la finalisation hôte (lifecycle.ts:283), jamais depuis le prompt.

**Blocage contrat de clé :** `collectDepositFacts` produit `tc-` + 40 hex (depot.ts:79–83), mais l’outbox exige `tc-` + 64 hex et fournit `deriveOpsysPostflightFactKey(sessionId, toolCallId)` (worker.ts:22, 80–89). Il faut une source canonique unique (la clé pleine et domain-separated de l’outbox) avant raccord; garder deux clés casserait déduplication M10. L’outbox ne valide pas provenance et n’appelle pas M10 (outbox.ts:72), donc elle ne doit recevoir que le reçu interne joint, jamais un DTO provenant du modèle.

**État trié :** refus d’admission/ticket → aucun fait; exception/transport/texte illisible/approbation en attente → `unknown`, aucun succès; résultat structuré + reçu admission/cible cohérents → capture durable candidate. Le test d’intégration doit compter un seul appel provider et outil, perdre l’ACK de dépôt après commit M10, redémarrer worker puis rejouer la même clé (un fait, réponse déjà déposé, outbox vidée); révoquer ensuite la route avant reprise et vérifier `needs_review`/conservation sans nouvel appel provider ni reroutage. Ce dessin ne prouve pas l’appel actuel de l’outbox ni un parcours complet.

Sources SHA-256 :
- `core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts` `cae5c085a07c53f10daaef70b35de4b57014fb4d27202e9d27d70388e1ad2a8c`
- `core/src/agents/embedded-agent-runner/run/attempt-prompt-submit.ts` `17a7123fc7984dc6aa2eea21f0313338927af0ea65983fa62a63812bdaea3c9c`
- `core/src/agents/agent-bundle-mcp-materialize.ts` `93254b9d7c7deac6ee2fc488b20a5df00bd7354a8d0097b12f155cf6e6eba29a`
- `core/src/agents/agent-bundle-mcp-runtime.ts` `d2a33ba0ca6294eba40f03bbcdbcc05233aa6abff9c9b2a206f96676ee9f7356`
- `core/src/context-engine/opsys-contexte-cible-ticket.ts` `58df5e0f8f881c90702ad50666e06651fc1893d5a36327e74aed82c9ee90d605`
- `core/src/context-engine/opsys-contexte-engine.ts` `e5c2c2d6d9013d92eda66665932aa584ddb258d6093c706c5ef6f7a2355dac8f`
- `core/src/context-engine/opsys-contexte-depot.ts` `68ee9b5b0e15b3f5595973cef4926399b6162ce918d0d44936f4ef31fc7a6359`
- `core/src/agents/harness/context-engine-lifecycle.ts` `d717ef83c78543cb64ec43165c77f6df4031ba8836f2f2e45f68007b14ed0f79`
- `core/src/agents/harness/opsys-postflight-outbox.ts` `38e5b3e4241cd4581dd6df246d4f0682e5ccc5d5c59e834d8643c6c49c8e6525`; `opsys-postflight-outbox.worker.ts` `910c6a544a20b105968a7a6593d82a7b040fc7072a0e0953b52d1d007fc6a668`

Lecture seule : aucun code modifié, test/QA, Git, installation ou réseau.
