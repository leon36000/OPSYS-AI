# IMAP cursor mailbox guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Refuser la réutilisation silencieuse d’un curseur IMAP appartenant à une autre boîte.

**Architecture:** Ajouter la boîte à l’identité du curseur existant, sans réinitialisation ou migration implicite. Refuser la lecture/avance ambiguë avant tout effet de réception.

**Tech Stack:** TypeScript, Vitest, stores natifs du fork; aucune dépendance nouvelle.

**Spec:** `docs/grs/crm/CRM06-AUDIT-SUIVI-COURRIELS.md`

## Global Constraints

- Root seul writer; pas de production, droits nouveaux, connexion réelle, purge ni envoi.
- Curseur ancien sans boîte : conservation et refus explicite, pas de supposition INBOX.
- Comparaison exacte de boîte; même boîte/UIDValidity reprend; même boîte/nouvelle UIDValidity garde reset.
- QA privée bornée, sources RO, reçus exclusifs, rouges conservés.

## Review Focus

- Boîte changée avec même UIDValidity : refus avant FETCH et aucun écrasement du curseur.
- Historique sans boîte : refus conservant le contenu intégral.
- Écriture d’avance avec boîte incohérente : refus sans écriture.
- UIDValidity légitimement changée : reset natif conservé dans la même boîte.
- Fixture de packaging initialisée avant watcher : provenance de boîte explicite, pas de passe-droit legacy.

### Task 1: Garde natif et raccord watcher

**Files:** `core/extensions/imap/src/state.ts`, `state.test.ts`, `watcher.ts`, `watcher.test.ts`, `core/test/scripts/imap-packaged-service.test-support.mjs`.

**Interfaces:** `initializeImapCursor(state, accountId, uidValidity, uidNext, mailbox)` et `advanceImapCursor(state, accountId, uidValidity, uid, mailbox)`; mailbox chaîne exacte non vide, max 1024 caractères, sans NUL/CR/LF. `ImapCursor` ajoute mailbox pour les écritures courantes; données historiques doivent être contrôlées à l’exécution.

- [x] Ajouter régressions boîte différente et legacy; vérifier qu’elles échouent avant correction.
- [x] Implémenter la liaison de boîte et le refus explicite; relire avant avance.
- [x] Passer la boîte ouverte depuis watcher; mettre à jour les fixtures natives.
- [x] Exécuter tests ciblés et protocole compatible, conserver les limites de prérequis.
- [x] Revue indépendante du diff, docs/résultats, commit local; publication seulement après réconciliation de la CI précédente.

## Exécution et limites

Source/Root : tranche native déterministe, pas le suivi complet. Tests 3 rouges initiaux, puis revue
P2 reproduite par 4 rouges (dont UIDValidity), correction en une passe. Suite finale `imap-v7` :
47 PASS, format/lint OK. Ajout du test natif SQLite/reopen avec entête réelle et coordinateur privé.
Le test de transport séparé est mocké; TCP/packaging réels restent non qualifiés. Aucun refus de
revue écarté ni minor différé; les prérequis de harnais restent dans leurs reçus. Commit local et
réconciliation de CI avant publication; aucune activation de l’ancien état ambigu.
