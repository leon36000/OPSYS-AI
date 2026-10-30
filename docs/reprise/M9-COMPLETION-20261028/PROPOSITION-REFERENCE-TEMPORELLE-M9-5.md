# Proposition M9.5 — référence temporelle injectée par le code, par la frontière runtime existante

**Proposition seulement : rien n'est activé, aucun outil ni grant n'est ajouté.** Elle touche Core et le socle
(`serveur_mcp.py`, `contexte.py`), fichiers communs : à coordonner par Root, en commits séparés, avec une admission
distincte. Le gate natif / PostgreSQL / hôte opérateur de M9.5 reste ouvert.

## Problème
Le mandat cron natif est un tour d'agent à message fixe (`payload.kind = agentTurn`). Core ajoute au message une heure
calculée par le code (`resolveCronStyleNow`, `core/src/agents/current-time.ts:23-32`, appelé par
`core/src/cron/isolated-agent/run-prepare.ts:520-567`), mais le modèle doit la RECOPIER dans l'argument `maintenant`
de `m9_produire_briefing_matin`. Une heure recopiée par un modèle n'est pas une référence serveur vérifiée.

## Frontière existante réutilisée
Core pose déjà, sur chaque appel MCP d'un profil d'agent, des clés `_meta` liées au runtime :
`opsys/runtimeProfileId`, `opsys/runtimeProfileRevision`, `opsys/runtimeServer`
(`core/src/agents/agent-bundle-mcp-runtime.ts:141-145`). Le serveur MCP Python les lit et les valide strictement
(`src/opsys/serveur_mcp.py:165-185`). Le socle sait déjà porter une heure SERVEUR dans un contexte d'appel
(`contexte.receptionne_de` / `horodatage_reception`, `src/opsys/contexte.py:136-161`, utilisé par
`src/opsys/capacites.py:973-980`).

## Proposition
1. **Core** : pour un tour lancé par le CronService (et seulement lui), ajouter `opsys/runtimeScheduledAt` au même
   ensemble de clés `_meta`, valeur = instant planifié du déclenchement calculé par le code (`job.state.nextRunAtMs`
   capturé au lancement, déjà utilisé par `core/src/cron/isolated-agent/delivery-dispatch-policy.ts:201-202`), formaté
   RFC 3339 UTC. Jamais une valeur venant du modèle ni du message.
2. **Socle** : `serveur_mcp.py` valide la clé avec les autres `opsys/runtime*` (présente seulement avec une liaison de
   profil valide ; RFC 3339 à fuseau explicite ; sinon refus `REJ-RUNTIME-REFERENCE-INVALIDE`) et la pose dans un
   `ContextVar` dédié (`reference_planifiee()`), comme `receptionne_de`.
3. **M9** : `m9_produire_briefing_matin` et `m9_lire_suite_briefing`, quand `reference_planifiee()` existe, exigent
   `maintenant == reference_planifiee()` (même instant) et refusent sinon (`REJ-BRIEFING-REFERENCE-DIVERGENTE`) ; hors
   d'un tour planifié (console, admin), le comportement actuel est inchangé. Variante plus stricte à trancher : ignorer
   l'argument du modèle et utiliser la référence injectée.

## Ce qui reste à prouver avant activation
Tests Core (clé posée seulement pour un tour cron, absente sinon, non falsifiable par le message), tests socle
(validation, liaison avec `opsys/runtimeProfileId`, refus), tests M9 (égalité exigée, refus de divergence, chemin
console inchangé), puis la qualification native sur l'hôte opérateur. Aucun de ces changements n'est fait ici.
