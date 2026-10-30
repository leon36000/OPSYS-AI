# M9.5 — raccord à la planification existante et qualification fictive isolée

**Aucun grant réel, aucune activation sur l'hôte opérateur.** M9.5 reste PARTIEL.

## Raccord
Le travail planifié est le briefing du matin historique (`m9_produire_briefing_matin`, `m9_lire_suite_briefing`) : voie
agent conservée, lecture pure. Les outils de la salle de guerre (`outils_*`) exigent un admin authentifié ; un job
planifié sans cette identité est refusé à l'appel. Le mandat suit le propriétaire existant `ProprietaireCron`
(`docs/architecture/AGENTS-CRON-AUTORITE.md`) : `preparer` → `accuser` → `valider`, `renouveler`, `tourner`, `revoquer`.

## Qualification sur base fictive (`tests/test_m9_planification_cron_fictive.py`, 7 tests)
| Exigence | Preuve |
|---|---|
| Autorisation | préparation, acquittement, validation ; validation avant acquittement refusée (`NON-ACQUITTEE`) |
| Rejeu sans double effet | préparation et acquittement rejoués = même résultat, journal inchangé ; validation sans écriture |
| Révocation | `revoquer` durable, rejeu identique, validation refusée (`REVOQUEE`) ; retrait du mandant refuse sans écrire |
| Reprise | lease échue : acquittement refusé, `renouveler` (rejeu sans nouvelle prise), ancienne lease fencée |
| Exécution répétée | trois tirages du briefing au même instant : réponses identiques, registres et file d'approbation inchangés |
| Pas de contournement d'identité | `m9_salle_de_guerre` sans admin authentifié : `REJ-IDENTITE-APPAREIL-INVALIDE` |

## Ce qui n'est PAS qualifié
Le CronService natif de Core et son admission runtime ; une base PostgreSQL ; l'hôte opérateur ; un déclenchement réel.
Instant de référence : le briefing prend `maintenant` en argument (M9 n'a pas d'horloge). Le mandat natif est un tour
d'agent (`payload.kind = agentTurn`, message fixe) ; Core ajoute au message deux lignes d'heure calculées par le code
(`resolveCronStyleNow`, `core/src/agents/current-time.ts:23-32`, appelé par `core/src/cron/isolated-agent/run-prepare.ts:520-567`) :
`Current time: …` au fuseau de la configuration (`agents.defaults.userTimezone`) et `Reference UTC: AAAA-MM-JJ HH:MM UTC`,
à la minute.
L'agent RECOPIE cet instant : M9 refuse un format invalide mais ne peut pas détecter une recopie erronée d'un instant
bien formé. Limite assumée et à constater à la qualification Core (comparer `maintenant` reçu et heure du déclenchement
dans la trace).
