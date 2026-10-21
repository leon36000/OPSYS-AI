# Rappels importés et prise interne M1

Daté Toronto : 2026-10-09T01:29:47.630881-04:00. Parent `65d7ae862374cf2a6870e326c75e613f20076bc7`. OPSYS-AI reste **PARTIEL**.

L'admin lit les rappels téléphone réellement importés, avec sources, dates, manques et suivi,
choisit un transfert puis prend sa responsabilité interne. Deux outils DEVICE admin : lecture
T0/N0 et prise T1/N2. La console existante garde ses autres gestes ; son outil de suivi reste
fermé au DEVICE. Aucun appel, envoi, clôture ou effet client/financier n'est livré par ce lot.

Les pages sont courantes, keyset exclusif de huit lignes maximum ; elles ne sont pas un
snapshot figé. Le corps de prise contient uniquement transfert_id et snapshot_attendu.
Actor/appareil/UUID/heure viennent du serveur Meta. L'ACK15champs confirme son propre maillon
et préfixe après continuation, fermeture et redémarrage. Autorité SQL, source et quotas
précèdent claim et restitution cache ; un refus préclaim ne termine pas l'intention.
Quatre refus métier certains sans append peuvent être rejoués exactement. Une faute après
append annule la transaction et le claim ; aucun succès ou négation n'est alors fabriqué.

Mobile : même UUID/payload/date/propriétaire/appareil/URL après issue inconnue, effets suivants
bloqués. Copie validée avant await, getters rejetés, callbacks périmés fermés, données masquées
après retrait ou changement de session/focus. Une confirmation/refus exige une nouvelle page.
L'outbox persiste seulement l'intention dans son registre existant, sans contact/message cache.

## Qualification et conservation

27 fichiers rapprochés et préimages conformes, lien node_modules explicitement exclu.
Backend combiné final : **1935 tests**, puis contrôle différé des noms **1 test** ; Root Cap **23 tests**.
Ruff et vérificateur métier **232 outils/140 DEVICE** passent, avec origines B de tous les handlers.
Mobile **5081 tests/221 suites**, TypeScript et export Android JavaScript passent sur les mêmes
576 fichiers. Comptes ciblés recouvrants, non additionnés. SQL13 et Cap16 sont des octets réels
consommés par les tests mobile ; ces captures ne sont pas présentées comme du HTTP ou un téléphone.

Le reçu natif final et ses appels/tablehashes sont intégralement joints au registre : appairage
opaque réel DEVICE→Core→HTTP MCP→SQLite fictif, sources figées, rôles dérivés des manifestes.
Final : **57 requêtes Gateway / 48 appels HTTPMCP**.
Chaque retrait/quota/rollback/rejeu garde sa preuve de tables et d'effet propre. La perte est
injectée par le récepteur du harnais ; le transport réel et le SDK/outbox séparé ont leurs périmètres.
Les archives publiques retiennent aussi les rouges, adaptations d'oracles et essais intermédiaires,
sans réétiquetage. L'unique blanc d'import après le run combiné a une preuve AST identique.
Le finding indépendant succès caché rétrogradé en refus a été reproduit sur quatre codes,
puis corrigé et requalifié : une négation contredisant sa propre preuve DEVICE reste inconnue.
Ancien natif49/40 et captures avant correction gardent leurs sources et leurs limites ; nouveaux
reçus/captures/mobile/natif sur la correction sont conservés séparément.

Claude Code connecté, **Opus5.5 réel**, cinquième mission en lecture seule avec deux auditeurs enfants.
Les risques de conception ont été confrontés aux sources et aux essais ; son rapport n'est pas une
certification du code final. Revue indépendante backend/Cap et revue Root indépendante mobile conservées.

La [CI exacte du parent65d7](https://github.com/leon36000/OPSYS-AI/actions/runs/37878773114) est qualifiée
séparément. Le nouveau commit exige sa propre CI, Core/build compris. Docker local inaccessible et
PostgreSQL runner restent distincts. Core source unchanged ; aucun résultat parent n'est hérité.

Capsule 644 membres sûrs, roundtrip SHA256 conforme : `f48d2988977a0dc2f0f2edd9e853b001ca50058928da0e90811e243fd2eed617`.
OAuth/CLI brut/account/config, bases privées, dépendances et archives CI brutes exclus.
302 sources/124 supports du transfert toujours rapprochés ; **104 références restent indisponibles**.

## Limites et suite

- new exact commit CI pending, parent success not inherited
- current keyset pages, late lower IDs require refresh
- global principal source quota10000 lines/65536 perline/8MiB before decoding
- whole response min5400 Python codepoints, no truncation/artifact
- no phone/Hermes/ExpoSQLite, mobile transport/storage fictive
- native SQLite, PostgreSQL runners separate; local Docker inaccessible
- N2 internal take only, no call/send/closure/customer/provider/stock/cost/M4/M5/M10 effect
- receiver loss simulated on actual Gateway bytes, not production loss
- observed processes and sampled RSS only
- 104 excluded proof references unavailable; supplement/conversations unknown
- N5/OSstorage/memory separation/LiteLLM route/eightdeepalertfamilies remain partial

La suite garde les dix départements profonds, Core OpenClaw, outils déterministes et permissions,
dashboard, mobile quatre profils/hors ligne, avatars et mémoires métier/développement séparées.
Continuer M7→M1→M2→M3→M4/M6→M5→M8/M9/M10 ; lien N4 typé vers variance/classification et révision
source, puis mémoire M10 versionnée restent inscrits avec critères, sans claim de livraison.
Publication normale sur la branche privée existante et PR623 brouillon ; aucun force, fusion ou production.
