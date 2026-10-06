# Lot 5 — sous-tranche outbox POSTFLIGHT

**Réemploi.** Le propriétaire est la base agent SQLite (`OpenClawAgentDatabase`), Kysely et son magasin-worker `openOpenClawAgentSqliteWorkerStore`; opérations worker, transactions synchrones sans `await`. Le harnais a `context_engine_turn_outbox`, reprise au démarrage et tests redémarrage/échec. Ne pas mélanger son payload/sa clé : il avance les tours et peut stocker transcript/messages. Ajouter une table compagnon au même propriétaire via Kysely worker, colonnes explicites, aucun fichier JSON/JSONL.

**Contrat proposé, non implémenté.** Lot fermé (M10 accepte au plus 20 faits) : `affaire_id`, département, profil/révision d’admission vérifiés au dispatch, outil allowlisté, issue/code, `engine_id`, clé, état/tentatives/horodatages. Clé Core `tc-` dérivée de `sessionId + toolCallId`; liaison M10 pour l’affaire. M10 valide affaire/département/clé/outil/résultat/code et refuse contenu divergent sous la même clé. Exclure texte utilisateur, prompt, sortie modèle brute, arguments métier et secrets. L’affaire reste linkable; DB agent en mode fichier 0600, sans preuve de chiffrement applicatif. Au retry, recharger config et appelant/secret MCP M10 existants; route ou autorité absente => revue, sans élargir le profil ni rejouer son outil.

Gap provenance : `afterTurn` expose messages/session, pas le reçu d’admission profil/cycle. Le Core doit propager ce reçu déjà vérifié par le runtime; ne pas le reconstruire depuis prompt/config. Sans lui, ne pas marquer le fait comme profil-authentifié.

Quota à valider : 256 lots/1 MiB par DB agent; saturation = santé dégradée et refus des prochains runs concernés avant dispatch. Backoff : 1, 5, 15, 60 min, puis quotidien, maximum 8; à 7 jours, `needs_review`, aucune suppression automatique. Après ACK M10, supprimer la ligne; perte de réponse après commit => rejouer même clé, accepter « déjà déposé », retirer la ligne. Aucun replay d’outil/fournisseur. Si crash avant capture durable, aucun succès n’est connu; l’outbox ne l’invente pas.

**Premier test.** Nouveau test Core voisin de `opsys-contexte-engine`: reprendre le serveur HTTP Python/SQLite réel et son fixture M10 du test cible-ticket Core, ajouter l’outil de dépôt; provider factice déclaré comme au test d’admission. Un appel outil, commit M10 puis réponse perdue, redémarrage worker et drain : une seule ligne M10, même `tc-*`, « déjà déposé », outbox vidée, provider appelé une fois. Crash avant capture : aucun succès fictif.

**Sources — SHA-256**

```text
core/AGENTS.md a516c31ecf85672bfb91718637f896d9cfc52b30bb83f409ccba48d7f88f90b3
core/src/agents/harness/context-engine-turn-outbox.ts e3c595b16207ae20a2dda968abf86ed001002da7e7243b9597f469c0f2148ff6
core/src/state/openclaw-agent-worker-store.ts 7b5e9673fc01418dc719cb7b7f6e86fb7590e5d6f1fb74a394e166bfea97aee1
core/src/state/openclaw-agent-execution-domain.ts 92ab9875ccbdd1499b2432300f3be11b9d54000addc747dca6a547c0595211cf
core/src/state/openclaw-agent-schema.sql 60fa92411e350c5c6007518a51334541bc1824c93c1e17053314f998f8f686e6
core/src/context-engine/opsys-contexte-engine.ts e5c2c2d6d9013d92eda66665932aa584ddb258d6093c706c5ef6f7a2355dac8f
core/src/context-engine/opsys-contexte-depot.ts 68ee9b5b0e15b3f5595973cef4926399b6162ce918d0d44936f4ef31fc7a6359
src/opsys/openclaw.py 9a8dfcdb26d4491e146671537fe0027622d9c1f4209ec94dee408e3d5d2335ab
departments/m10-memoire/src/m10_memoire/faits_candidats.py c3fec43a473dbfc53c7264f01ea599e09d950be50be77c26a4e5a4c612b4f901
departments/m10-memoire/tests/test_outils_agent.py b13da0820096e07c1794bb81b5cd2c01a0015e25ad3198cd6a378cdb79406f11
core/src/agents/embedded-agent-runner/opsys-runtime-admission.python-http.integration.test.ts c63667a5cb9758994254f1341cc0386c817ffc4e88f328d3d1d655b71f4ad7ba
core/src/agents/agent-bundle-mcp-runtime.opsys-cible-ticket.python-http.integration.test.ts dc18dce4a10e0dac8fd6863175cb7743be378e6caf09be427e3bc7e287c0450a
core/test/opsys-target-ticket-fixture.py ac4672a86fe76c667111499dc778852c9dd9104a9988fc7f2ad9327f3ab76b0e
```
