# ADR-0009 — Socle métier : une base par instance, événements, approbations N0–N5, rôles et audit

- Statut : **Accepté** (ingénieur en chef, 2026-09-28).
- Complète : [ADR-0008](ADR-0008-fork-openclaw-opsys-core.md), décision 6 (données).
- Fondé sur : [R13](../research/R13-socle-metier.md) et les audits `docs/departements/M*-audit.md`.

## Contexte

Les audits le montrent dans chaque département : les registres métier vivent en mémoire et
disparaissent au redémarrage. La cascade entre départements n'a pas de destinataire réel. Un seul
mot de passe signe toutes les décisions. Et quatre échelles d'autonomie coexistent sans lien : N0–N5
(définition), T0–T3 (socle), F0–F7 (M5), niveaux 0–6 (M7).

R13 recommande PostgreSQL obligatoire, au motif que le compose le rend déjà obligatoire. Ce motif
vient de l'ancienne pile (ADR-0007). La directive du propriétaire est « s'installe partout comme
OpenClaw ». Le vrai besoin technique de R13 : l'écriture métier, son événement et sa trace d'audit
dans **une seule transaction, sur un seul moteur**. Une base SQLite unique par instance le satisfait
aussi.

## Décisions

1. **Une base par instance, possédée par le moteur métier Python.**
   - SQLite (WAL, `busy_timeout`) par défaut : aucun serveur, sauvegarde et export d'un seul
     fichier, isolation naturelle entre clients SaaS.
   - PostgreSQL en option pour les grosses installations.
   - Le même code sert les deux : SQLAlchemy 2 **Core** (pas l'ORM déclaratif) et migrations
     Alembic. La CI teste les deux moteurs.
   - Tables préfixées par département (`m4_jobs`, `m6_po`), pas de schémas SQL, pour rester portable.
   - Le core TypeScript n'ouvre jamais cette base : il passe par le moteur métier (MCP pour les
     agents, API pour les interfaces). Règle de R13, conservée : jamais deux runtimes sur le même
     fichier.
2. **Tout dans la même base** : données métier, registres append-only (chaîne de hash conservée,
   non-régression contre les fixtures actuelles), outbox, approbations, journal, audit, rôles. Le
   plan de contrôle actuel (`etat.db`) y migre. Une transaction couvre : ligne métier + événement
   sortant + trace d'audit.
3. **Événements** : on durcit l'outbox que M4 a prototypée, sans nouvelle brique.
   - Deux tables : `evenements_sortants` et `evenements_recus`, avec `UNIQUE(evenement_id,
     consommateur)` pour l'idempotence.
   - Un répartiteur dans le moteur métier livre les événements : réveil après commit, plus un
     sondage de secours toutes les 2 à 5 s. Sous PostgreSQL, il utilise aussi `LISTEN/NOTIFY`.
   - Catalogue versionné `opsys.evenement/v1`, en JSON Schema, validé en entier par `jsonschema`
     (Draft 2020-12), objets et tableaux imbriqués compris (le validateur minimal des outils ne
     regarde que le premier niveau).
   - Consommateurs directs de la fin de travaux : M6, M5, M2, M7, M8, M10.
   - M3 et M9 la reçoivent en second ordre, conformément aux boucles de §6 de la définition :
     - M3 par la variance de M6 et le coût réel de M5 ;
     - M9 par les preuves de M8.
4. **Une seule échelle d'autonomie : N0–N5 de la définition.** Chaque outil déclare son niveau N.
   Les autres échelles deviennent des correspondances :

   | N (définition) | T (socle) | F (M5) | M7 | Règle |
   |---|---|---|---|---|
   | N0 lecture · N1 brouillon · N2 tâche interne | T0 | F0 · F1 · F2 | 0–2 | automatique |
   | N3 action externe à faible risque, interne non finale | T1 | F3 | 3 | validation humaine au départ |
   | N4 engagement (dépense, prix, envoi sensible, écriture finale) | T2 | F4 · F5 | 4 · 5 | Nathan |
   | N5 argent réel, fiscal, légal, paie, RH, achat majeur | T3 | F6 · F7 | 6 | Nathan **et** attestation du professionnel concerné ; jamais automatique |

   Les modes ombre, supervisé et autonome gardent leurs seuils actuels, exprimés en N. N5 exige
   deux pièces : la signature de `nathan_owner`, plus l'attestation du professionnel (nom,
   profession, document joint).
5. **Rôles (P8)** : `nathan_owner`, `admin`, `finance`, `manager`, `seller`, `employee`, `client`,
   `system_agent`. Les tables `personnes`, `roles`, `appareils` (appairés à une personne) portent
   l'identité. Chaque département déclare dans `department.yaml` quels rôles peuvent approuver quel
   niveau N. Toute décision est signée par une personne : fini le mot de passe partagé. Les vues
   filtrent par rôle : l'employé ne voit ni coût ni marge ; le client ne voit aucune donnée interne.
6. **Audit (P3)** : table `audit_trace`. Elle enregistre qui, quoi, pourquoi, source, modèle,
   confiance, coût, risque et statut, plus l'avant et l'après des modifications sensibles. Elle est
   écrite au point de passage unique `Capacites.appeler` et à chaque écriture métier sensible. Les
   renseignements personnels sont masqués dans les journaux.
7. **Workflows** : aucun moteur externe en v1 (outbox, approbations et planificateur suffisent).
   - DBOS Transact (MIT, bibliothèque) : porte de sortie pour les sagas longues.
   - LangGraph (MIT) : graphes internes à un département si un besoin se présente.
8. **Observabilité** : OpenTelemetry, exportateur optionnel. Le core trace les appels de modèles
   par agent de département (prompt, sortie, coût, latence). Langfuse seulement en profil optionnel.

## Conséquences

- Nouvelles dépendances : SQLAlchemy 2 et Alembic (MIT), à inscrire dans `INGREDIENTS.md`.
- La mémoire d'entreprise (PostgreSQL + pgvector aujourd'hui) doit fonctionner sur SQLite (FTS5 +
  sqlite-vec) pour l'installation par défaut. Détail : ADR-0010.
- Premier chantier : T1.0 du plan. Registres des départements persistants, en commençant par M4,
  puis la cascade de fin de travaux de bout en bout.
- Postgres et Valkey sortent du chemin par défaut du déploiement et restent des options serveur.

## Addendum T1.4-h (2026-09-28) — §4 : la validation humaine au départ, faite par la personne qui agit

- Statut : **Proposé** (PLAN T1.4-h) ; relecture humaine requise avant mise en service (approbations :
  code critique, AGENTS.md).
- Précise : décision 4 (échelle N0–N5). Ne change ni les seuils des modes ni les niveaux des outils.

### Constat

La décision 4 définit N3 comme « validation humaine au départ ». Les dix départements sont en mode
`ombre` : tout outil N3 et plus part en file d'approbation du propriétaire. C'est voulu pour ce qu'un
**agent propose**. Mais depuis T1.4-c4, un appel d'appareil porte l'identité **authentifiée** de
l'humain qui agit lui-même (`opsys/personne`, `opsys/role`, `docs/architecture/IDEMPOTENCE.md` §7 bis).
Mettre son pointage (`m4_pointer`) ou sa complétion (`m4_completer_intervention`) en attente du
propriétaire rendait l'application inutilisable, alors que la validation « au départ » est faite : c'est
lui qui lance l'action.

### Règle

Pour un appel d'appareil (mutation portant un `_meta` d'idempotence) dont l'approbation serait requise
par le mode du département, l'action **s'exécute sans file d'attente** si et seulement si les quatre
conditions suivantes sont réunies :

1. le niveau effectif de l'outil est **N3 au plus** ;
2. l'appel porte une identité de jeton d'appareil (personne, rôle) que **la base confirme à l'instant de
   l'appel** : la personne existe, est active et porte toujours ce rôle ;
3. l'outil est **dans la portée de ce rôle**, au sens de `openclaw.roles_outils` — la fonction qui
   génère `roles.json` pour le core, appelée telle quelle : une seule source ; hors portée, refus nommé
   `hors_portee_role`, ni exécuté ni mis en attente ;
4. l'appel vient d'un appareil (il n'y a rien à valider au départ pour ce qu'un agent propose).

Dans tous les autres cas, **rien ne change** : N4 et N5 vont toujours au propriétaire (N5 exige toujours
l'attestation du professionnel, jamais automatique) ; un appel sans identité (agent, secret partagé)
suit la file ; une identité invalide, désactivée ou dont le rôle a été retiré ne donne aucun passe-droit
(chemin normal, fail-closed).

Les rôles que `department.yaml` déclare sous `approbations.n3`/`n4` (décision 5) gouvernent **qui décide
une demande en file**. Ils ne gouvernent pas l'action que la personne lance elle-même : là, la portée
est celle du rôle de son appareil (condition 3).

### Trace

Chaque exécution ainsi validée écrit, dans le même point de sauvegarde que l'outil, donc atomiquement
avec lui :

- une ligne du **journal des approbations existant** (`approbations`, statut `executee`) : qui
  (`decide_par`, `decide_role`), quoi (`outil`, `arguments`, `niveau`), quand (`cree_le`, `decide_le`),
  pourquoi (`motif_decision` : « validation humaine au départ par la personne qui agit, ADR-0009 §4 ») ;
- l'entrée `approbation.valider_au_depart` du journal d'audit que `decider` alimente déjà (appareil,
  empreinte des arguments réels).

Pas de table ni de journal nouveaux. Une exécution refusée ou en panne ne laisse aucune trace (rien n'a
changé) ; une panne d'écriture de la trace annule l'exécution. La trace ne copie jamais en clair une
donnée personnelle que le département garde chiffrée avec une clé destructible : le fix GPS d'un
pointage y figure masqué (POLITIQUE-geolocalisation §5, décision 6 : renseignements personnels masqués
dans les journaux). L'idempotence d'appareil (T1.4-b) est intacte : un renvoi de la même clé rejoue la
réponse sans ré-exécuter ni écrire une seconde trace.

### Limites

- **L'authenticité vient du core, pas du socle.** Le socle relit la personne et le rôle en base ; il ne
  peut pas authentifier l'appareil. La règle suppose que seul OPSYS-CORE, après vérification du jeton
  d'appareil (T1.4-c4), écrit `opsys/personne`/`opsys/role` dans le `_meta` : le canal MCP
  (`OPSYS_MCP_JETON`) doit lui rester réservé. Les tests vitest de cette chaîne ne tournent qu'en CI.
- **La sûreté dépend de la finesse de `roles_outils`, aujourd'hui grossière.** `employee` couvre tous
  les outils M4 et M6 hors T3, dont plusieurs que la file du propriétaire filtrait jusqu'ici :
  `m6_approuver_po`, `m4_resoudre_demande`, `m4_definir_consentement_gps`, `m4_lire_position_gps`. Une
  portée par outil, déclarée dans les manifestes, est à faire avant la mise en service ; elle profitera
  d'elle-même à cette règle puisque la source est unique.
- **Les modes `supervise` et `autonome` ne changent pas** : un N3 s'y exécute déjà sans approbation, et
  donc sans cette trace.
- **Un `nathan_owner` n'a pas d'appareil** (décision 5 et `appareils.ROLES_APPAREIL`) : l'appareil du
  propriétaire est appairé `admin`, et ses N4/N5 vont en file comme ceux de tout autre appareil.
