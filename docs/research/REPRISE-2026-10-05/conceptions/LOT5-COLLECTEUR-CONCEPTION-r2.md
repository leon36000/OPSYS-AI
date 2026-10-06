# Lot 5 — collector / M10 key compatibility r2

## Décisions de contrat

**Admission et usage sont deux états.** `reserveCapturedOpsysRuntimeAdmission()` ne retourne une capture qu’après l’ACK neuf et le rapprochement du reçu admission (runtime-admission.ts:179–224). C’est la preuve bornée que la réservation a été admise; l’usage fournisseur est ensuite mesuré/réconcilié séparément. Si `stream.result()` ne fournit pas de compte fiable, le code laisse la réservation ouverte et lève une erreur (l.419–438). Le collecteur doit conserver « admission acceptée, comptage inconnu/en attente », sans convertir cela en refus ni effacer la capture. L’incertitude d’usage ne prouve pas qu’un outil a été appelé. Seul un résultat d’outil réellement observé peut donner un fait candidat; refus d’admission/ticket = aucun fait, résultat illisible/attente/transport = inconnu, résultat métier explicite = capture ok/refus.

**Fenêtre crash irréductible.** Un outil distant peut committer son effet puis le Core tomber avant l’écriture SQLite locale. Une outbox enregistrée seulement après réponse réduit la fenêtre, mais ne garantit pas la récupération ni « exactly-once ». Sans idempotence du dispatch métier avec la même clé que le journal, ou endpoint de rapprochement distant par clé stable, le redémarrage ne peut distinguer « effet appliqué, réponse perdue » de « effet non appliqué ». Ne pas rejouer automatiquement ce dispatch et ne pas inventer un fait; marquer inconnu/à examiner. L’idempotence actuelle M10 couvre le dépôt du fait, pas l’effet initial de l’outil.

**Le conflit de longueur est interne à Core, pas à M10.** M10 `_CLE` accepte tout identifiant de 1–128 caractères `[A-Za-z0-9._:-]` (faits_candidats.py:52, 72–80); sa déduplication porte sur la chaîne exacte, même affaire et même contenu, et une réutilisation divergente est refusée (l.122–143). Donc `tc-` + 40 hex du collecteur courant (opsys-contexte-depot.ts:80–83) et `tc-` + 64 hex passent tous deux côté M10. C’est le worker outbox Core qui n’accepte que `tc-` + 64 (opsys-postflight-outbox.worker.ts:30). Changer silencieusement la dérivation 40→64 crée une nouvelle clé pour le même appel et peut dupliquer un ancien fait, puisque le registre M10 n’a pas d’alias de clé.

## Points de raccord exacts

1. Au wrapper d’admission, enregistrer le reçu séparément du statut d’usage; l’exposition au collecteur doit rester une API Core typée, jamais un champ du prompt/DTO. La révision est la valeur du binding hôte envoyé et acceptée par l’admission; le reçu peut omettre son écho. La présenter comme telle, pas comme révision renvoyée par le serveur.
2. `agent-bundle-mcp-materialize.ts:478–489` détient le `toolCallId`, le nom réel et la réponse brute; `runtime.callTool()` n’a pas actuellement le `toolCallId`. Après ticket cible validé, le chemin runtime/ticket connait `sessionKey` et `state.affaireId` (ticket.ts:108–145). Une fonction interne liée au run doit associer ces valeurs au vrai résultat d’outil, sans ticket/secret ni args.
3. Le lot outbox reçoit seulement les faits normalisés après cette jointure; l’API outbox est stockage fermé, elle n’authentifie ni la provenance ni n’envoie à M10 (opsys-postflight-outbox.ts:72–83). `afterTurn` est un rapprochement possible, mais il ne couvre pas le crash avant cette phase.

## Première tranche codable

Garder la clé Core v1 existante `tc-` + 40 hex; élargir le validateur outbox à la forme v1 40 **et** v2 64 tout en conservant son dériveur 64 pour les données v2 déjà préparées. Ne pas modifier le validateur M10 ni réécrire les faits existants. La première intégration enregistre admission, ticket validé, `toolCallId` et résultat réel dans un petit collecteur par run puis enqueue les lots; elle ne prétend pas fermer la fenêtre effet distant→journal. Si une bascule globale en 64 devient nécessaire, elle exige une stratégie explicite de transition/reconciliation et tests de non-duplication sur données M10 historiques, pas un simple remplacement du hash.

Test ultérieur ciblé: résultat outil réel, arrêt après effet distant avant enqueue => état inconnu/revue sans rejouer l’outil; arrêt après enqueue et commit M10 mais avant ACK local => rejouer le **dépôt** avec la même clé, M10 répond déjà déposé; compter le provider une fois. Révoquer route/profil avant reprise => conserver la ligne en revue et ne rerouter ni rappeler l’outil/provider. Ces scénarios ne démontrent pas une garantie exactly-once.

## SHA-256 sources lues

- `departments/m10-memoire/src/m10_memoire/faits_candidats.py` `c3fec43a473dbfc53c7264f01ea599e09d950be50be77c26a4e5a4c612b4f901`
- `departments/m10-memoire/src/m10_memoire/outils.py` `ff4e9a79889a37617ebe24c79cdba8fc388f645ce1f1d4ba5ca80d9cbf7f947c`
- `core/src/context-engine/opsys-contexte-depot.ts` `68ee9b5b0e15b3f5595973cef4926399b6162ce918d0d44936f4ef31fc7a6359`
- `core/src/agents/harness/opsys-postflight-outbox.worker.ts` `910c6a544a20b105968a7a6593d82a7b040fc7072a0e0953b52d1d007fc6a668`
- `core/src/agents/harness/opsys-postflight-outbox.ts` `38e5b3e4241cd4581dd6df246d4f0682e5ccc5d5c59e834d8643c6c49c8e6525`
- `core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts` `cae5c085a07c53f10daaef70b35de4b57014fb4d27202e9d27d70388e1ad2a8c`
- `core/src/agents/agent-bundle-mcp-materialize.ts` `93254b9d7c7deac6ee2fc488b20a5df00bd7354a8d0097b12f155cf6e6eba29a`
- `core/src/context-engine/opsys-contexte-cible-ticket.ts` `58df5e0f8f881c90702ad50666e06651fc1893d5a36327e74aed82c9ee90d605`

Lecture seule; aucun code, test, build, QA, Git, réseau ou écriture live.
