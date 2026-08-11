# Disposition des sources rivales — carte d'autorité métier M1-M10

Ce chore ratifie `audit/core-baseline/BUSINESS-AUTHORITY-MAP-M1-M10.csv`,
dérivé de `sources/continuity/matrices/RF01-W11-AUTHORITY-MAP-M1-M10.csv`
du pack (copie locale : `audit/core-baseline/sources/`, sha256
`867969610e9d8a442aeb9879818b9165877952f2ca3cede7d8236d44bb8c3648`). Le
CSV source lui-même interdit littéralement, sur sa propre ligne M10 :
« Must not create a second business authority ». Ratifier une carte sans
statuer sur les 3 autres fichiers du pack qui recoupent le même sujet
recréerait exactement ce risque — ce document statue sur chacun,
individuellement, avec le texte réel cité (pas résumé de mémoire).

## 1. `sources/continuity/matrices/RF01-W11-AUTHORITY-DATA-OWNERSHIP.csv`

Structure : `module,authoritative_writes,forbidden_direct_writes,
reads_via_contracts_from,direct_private_db_access,conflict_rule,status`.

Chaque ligne porte, verbatim, `status=CANONICAL_PROPOSED_FOR_RF12` —
auto-déclaré **proposé**, pas canonique, réservé à un futur travail RF12
distinct. Exemple (ligne M5) :

```
M5,"invoice,payment,AR,AP,ledger,tax,payroll,cashflow,financial profitability","CRM pipeline,field execution,stock quantity","M2,M4,M6",FORBIDDEN,SOURCE_MODULE_WINS_UNLESS_RATIFIED_TRANSFER,CANONICAL_PROPOSED_FOR_RF12
```

Recoupement réel avec la carte ratifiée par ce chore : partiel et à un
grain proche (ex. `invoice,payment,AR,AP,ledger,...` vs notre
`ledger,invoices,payments,AR/AP,...`), mais le découpage diffère (`AR` et
`AP` séparés ici, `AR/AP` un seul agrégat dans la source RF01-W11-MAP —
divergence de tokenisation entre les deux fichiers de recherche
eux-mêmes, pas une erreur de ce chore).

**Disposition : NON ratifiée par ce chore.** Deux raisons indépendantes,
chacune suffisante seule : (a) son propre statut `CANONICAL_PROPOSED_FOR_
RF12` réserve explicitement sa canonisation à un travail futur nommé —
la ratifier maintenant anticiperait un jalon (RF12) hors du périmètre de
ce chore et de C03-002 ; (b) `tasks/C03-002.md` cite en `source_refs`
`59-RF01-W11-INTERMODULE-CONTRACTS-RESEARCH-MAP-v5.5.0.md` (dont
`RF01-W11-AUTHORITY-MAP-M1-M10.csv` est le jumeau CSV structuré, cf.
mémoire opérationnelle) — **pas** ce fichier-ci, qui n'apparaît dans
aucune `source_refs` de tâche C03-*. Si RF12 canonise un jour ce fichier,
cela devra EXPLICITEMENT superséder ou fusionner avec
`BUSINESS-AUTHORITY-MAP-M1-M10.csv` (via un nouveau chore/tâche dédié,
jamais une coexistence silencieuse de deux cartes métier).

## 2. `sources/continuity/matrices/RF01-W7-OWNERSHIP-AUTHORITY-MATRIX.csv`

Structure : `capability,authority,consumers,rule`. Exemples :

```
BRICK_REGISTRY,Core,M1-M10,Native authority
EVENT_TRANSPORT,Core Event Fabric,M1-M10,Provider behind port
CRM_TRUTH,M2,M1/M3/M7/M8/M9/M10,M2 only
FINANCE_TRUTH,M5,M1/M2/M3/M4/M6/M7/M8/M9/M10,M5 only
```

Portée : **capacités techniques/système** (registre de briques, transport
d'événements, routage de modèles, observabilité, secrets, supply chain,
UI mobile, avatar vocal…), pas des agrégats de données métier. Seules 5
des 20 lignes (`CRM_TRUTH`, `FINANCE_TRUTH`, `INVENTORY_TRUTH`,
`ANALYTICS_METRICS`, `STRATEGIC_DECISIONS`) recoupent partiellement notre
sujet, et seulement au niveau MODULE entier (`M5 only`), jamais à la
granularité fine d'un agrégat (`ledger` vs `invoices` vs `payments`).

**Disposition : hors-scope, non concurrente.** Portée orthogonale
(capacités système vs agrégats de données métier) — ce fichier répond à
« quelle capacité technique appartient à quel module/plane Core », pas à
« quel agrégat métier appartient à quel module », la question exacte de
C03-002. Aucune action de ratification requise ; aucun conflit avec la
carte de ce chore (les 5 lignes qui se recoupent sont cohérentes en
substance — M5 possède FINANCE_TRUTH, notre carte donne `ledger`/
`invoices`/`payments`/... à M5 — même autorité, grain différent).

## 3. `sources/continuity/matrices/RF01-W6B-AUTHORITY-BOUNDARIES.csv`

Structure : `domain,authoritative_owner,hermes_role,openclaw_role,
failure_semantics`. Exemples :

```
Finance truth,M5,non-authoritative adapter,non-authoritative adapter,fail closed or explicit degraded state
Identity,OPSYS Identity Plane,non-authoritative adapter,non-authoritative adapter,fail closed or explicit degraded state
Browser,OPSYS Computer Use Port,non-authoritative adapter,non-authoritative adapter,fail closed or explicit degraded state
```

Portée : **frontières d'intégration avec des systèmes externes** (rôles
Hermes/OpenClaw, sémantique d'échec fail-closed/degraded), mélangeant des
domaines M1-M10 (`Finance truth→M5`, `CRM truth→M2`, `Inventory truth→M6`,
`Analytics truth→M8`, `Memory→M10`, `Strategy outcome→M9 + human gate`) et
des domaines de plateforme CORE (Identity, Tenant, Consent, Authorization,
Sessions, Skills, Channels, Browser, Mobile nodes, Success verdict, Audit
evidence). Là où il touche M1-M10, la granularité s'arrête au module
entier (`Finance truth,M5`), jamais à un agrégat fin.

**Disposition : hors-scope, non concurrente.** Même motif que RF01-W7 :
portée orthogonale (frontières d'intégration externe + gouvernance
plateforme CORE), pas d'agrégats métier fins. Les lignes qui recoupent
M1-M10 sont cohérentes en substance avec la carte de ce chore, à un grain
plus grossier — aucun conflit, aucune action requise.

## Conclusion

`audit/core-baseline/BUSINESS-AUTHORITY-MAP-M1-M10.csv` reste la **seule**
carte d'autorité métier à granularité fine (agrégat, pas module) ratifiée
par une revue scellée pour M1-M10 à l'issue de ce chore. Les 3 fichiers
ci-dessus restent, chacun pour un motif distinct et documenté, non
ratifiés — aucun n'est silencieusement ignoré, aucun n'est promu sans
justification.
