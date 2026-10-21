# R26 — procédures internes sourcées pour M3

Le backend corrigé et sa console privée sont **vérifiés localement le 2 octobre 2026**.
Cette tranche prolonge la
mémoire PostgreSQL existante sans créer un second store.

## Résultat du backend

Admission durable UTF-8, versions exactes, indexation transactionnelle, activation
humaine distincte avec CAS, recherche de la seule version active, citations
vérifiées et effacement des admissions/versions sont implémentés. Quotas,
idempotence, réserve du namespace et limites des sorties sont appliqués côté
store. L'architecture et ses limites figurent dans
[le contrat documentaire](../architecture/INGESTION-PROCEDURES-M3.md).

Huit chemins backend sont concernés : `schema.sql`, `store.py`,
`ingestion_procedures.py`, `outils.py`, le manifeste M03 et trois suites mémoire.
Les préimages existent pour chaque fichier, avec état absent des deux nouveaux.
Les essais rouges et reprises ont été conservés. La revue a corrigé notamment
les citations multiples, l'oubli avant indexation, les filtres combinés,
l'expiration d'une version courante et la normalisation d'un chunk terminé par LF.

## Qualification indépendante ROOT

Campagne finale backend r2 : **06:55:53 à 06:56:18 UTC**, **103 cas**, zéro
échec, erreur ou skip; durée JUnit **25,501 s**. Les 1 096 empreintes sélectionnées
sont stables, dont le SQL ajouté explicitement à la capture avant/après.

La sélection réunit les six suites ingestion, store, outils mémoire, embeddings,
configuration OpenClaw et fixture PostgreSQL. Le store et l'ingestion emploient
PostgreSQL 17.11/pgvector réel avec PGDATA tmpfs. Les tests embeddings utilisent
des doubles; aucun modèle n'a évalué le corpus de procédures. Les 82 R25 et les
101 r1 sont recouverts par cette sélection et ne s'additionnent pas à 103.

Ruff sur les six fichiers Python touchés passe. Le catalogue vérifie dix
départements, 207 outils et leurs contrats. Le conteneur préexistant est seul
avant et après les campagnes fermées; le reçu de nettoyage est une observation
postérieure, sans suppression du conteneur préexistant.

Les artefacts de travail sont sous
`/workspace/poursuite-opsys-2026-10-02-r1/memoire-r26` : `FREEZE-r2.json`,
`PREFLIGHT-ROOT-r2.json`, `integration-root-r2.xml`, `NETTOYAGE-ROOT-r2.json`
et `CLOTURE-REVUE-r3.md`. Les reçus/logs ROOT sont sous
`/workspace/restructuration-opsys-2026-09-30/preuves`, préfixes
`memoire-ingestion-integre-root-r2-2026-10-02` et
`memoire-ingestion-qualite-root-r2-2026-10-02`.

La campagne ROOT console finale passe séparément **85 cas**, zéro échec, erreur
ou skip, entre **07:34:42 et 07:35:04 UTC**, durée JUnit **21,095 s**. Les
1 099 empreintes surveillées sont stables. Cette sélection réunit la nouvelle
console documentaire, les jobs mémoire, la console générale et Fusion CSV.
Les huit nouveaux cas console incluent des parcours PostgreSQL réels et des
contrôles de corps/authentification; les autres portent sur les composants
existants. Ruff ciblé et le contrôle du diff passent aussi.

Ses artefacts sont `console-root-r1.xml`, `PREFLIGHT-UI-ROOT-r1.json` et
`NETTOYAGE-UI-ROOT-r1.json`; les reçus/logs portent les préfixes
`memoire-procedures-console-root-r1-2026-10-02` et
`memoire-procedures-console-qualite-root-r1-2026-10-02`. Le gel UI final est
`ui-freeze-r2.json`. Le pilote PDF en préparation était suspendu et n'est pas
qualifié par cette campagne. Surveiller une source ne signifie pas l'avoir testée.

La capture initiale des deux préimages console avait été écrasée par une
recapture intermédiaire. Les octets initiaux ont été récupérés exactement :
`application.py` depuis l'archive R22, `memoire_ui.py` depuis une copie de travail
indépendante, avec les mêmes SHA que les snapshots ROOT antérieurs. Les fichiers
intermédiaires, la note et la récupération datée restent conservés. Le diff final
garde seulement le montage du routeur et le lien dans ces deux fichiers.

Les 103 cas backend et 85 console sont deux sélections disjointes. Leurs comptes
ne s'ajoutent pas aux campagnes auteur ou historiques recouvrantes.

Les sources, préimages, reprises et reçus sélectionnés sont réunis dans
l'[archive R26](../research/R26-2026-10-02/README.md), avec empreintes et index
de qualification. L'archive n'exécute aucun test supplémentaire.

## Prochaine sortie et limites

La console démontre admission, reprise, indexation, activation CAS et oubli
confirmé, ainsi que refus de droits, retrait pendant parsing/lecture, CSRF,
upload borné, fermeture du fichier et erreurs expurgées. SQLite pour l'identité
et PostgreSQL pour les procédures n'offrent pas de révocation atomique : un
retrait après commit peut produire un refus HTTP après l'écriture, cas testé.

PDF/OCR, assimilation massive, corpus représentatif, isolation SaaS, qualité
sémantique, durabilité et exploitation VPS restent des qualifications distinctes.
M10 et le [lot mémoire premium](REPRISE-PLAN-2026-10-02.md) restent partiels.
