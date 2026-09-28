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
   - Catalogue versionné `opsys.evenement/v1`, en JSON Schema, validé par
     `outils.valider_arguments`.
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
