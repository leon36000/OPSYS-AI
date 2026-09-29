# M10-memoire

Mémoire Long Terme — non-oubli, PREFLIGHT tracé (POSTFLIGHT applicatif hors périmètre v1).

Statut : département OPSYS complet (manifeste, SOUL, 2 skills, outils d'agent) sur le modèle
de M3-estimation, mode `ombre`. Les six stories de domaine S001-S006 du PRD sont livrées et
vertes : contrats gelés, deux registres append-only hash-chaînés distincts (Événements/Affaires,
anciennement Forge/Business — ADR-0010 décision 2), câblés sur le stockage durable de l'instance
(ADR-0009), consommation du Work Completion Trigger de M4 sans recalcul de hash, décisions à
raison obligatoire (statut par relecture), révision sans fusion, prédicat de contexte suffisant
avec trace du refus, référence `memoire_m10` vérifiable, conformité statique (dont la garde
anti-mutation).

PLAN T3.3 ajoute (mêmes garanties, mêmes registres) : consommation de la variance matériaux de M6
(`m6.variance_chantier`, même registre Événements que le WCT, distinguée à la lecture par
`classification.py`) ; paquets de contexte en couches pour une affaire (`paquets.py`,
`m10_paquet_contexte_affaire`) — budget de caractères et troncature calculés par le code, jamais
par un modèle, provenance sur chaque fait ; consolidation nocturne idempotente par jour
(`consolidation.py`, `m10_consolider_affaire`) qui condense les événements d'une affaire en UN
fait durable citant ses sources ; audit « non-oubli » (`audit.py`, `m10_auditer_non_oubli`) qui
vérifie l'intégrité des deux chaînes et la trace de chaque fait attendu (WCT, variance).

PLAN T1.5-d ajoute la consommation de la rentabilité d'un chantier de M5 (`m5.rentabilite_chantier`,
`rentabilite.py`, même registre Événements) : la leçon « marge réelle contre marge prévue » de l'affaire, garde
telle quelle, au niveau `FINANCIAL` — elle ne sort dans aucun paquet de contexte. Un coût réel partiel de M5
n'y porte aucune marge, et M10 n'en calcule jamais.

PLAN T3.3-suite ajoute le dépôt POSTFLIGHT (`faits_candidats.py`, `m10_deposer_faits_candidats`) : après
un tour d'agent, le core transmet ce que les OUTILS ont fait (outil, résultat ok ou refus, code), jamais
ce que le modèle a écrit. Chaque fait devient un maillon `fait_candidat` du registre Affaires, en statut
`candidat` : idempotent par clé de dépôt, lot refusé en entier au premier élément invalide. Ce n'est
pas une vérité : il n'entre ni dans le paquet de contexte ni dans la consolidation nocturne (phase
ultérieure). Tâche interne automatique (T1, N2), fermée aux appareils. La lecture du PREFLIGHT est
`m10_paquet_contexte_affaire` (T0), appelée par le moteur de contexte du core (`core/src/context-engine/`).

PLAN T3.3-suite-b ajoute trois choses. (1) Le cycle de vie des signaux critiques (`signaux.py`) : ouvert,
pris en compte, clos ; seul un HUMAIN identifié (`humain.py`) passe d'un état à l'autre (`m10_prendre_en_compte_signal`,
`m10_clore_signal`, N3, portée `admin`), jamais le modèle seul, même dans un mode sans file d'approbation ; une
seule autre clôture, la règle écrite de réévaluation de M6, qui n'a pas encore de producteur. Le paquet montre
les ouverts, puis les derniers clos avec qui et pourquoi, et porte un décompte (`signaux`) que la troncature ne
touche pas. (2) L'affaire liée à la session (`liaison.py`, `m10_lier_session_affaire`,
`m10_affaire_de_la_session`) : sur un canal client, l'affaire vient de la clé de session, jamais du texte de la
demande. (3) Le filtre de confidentialité du paquet (`confidentialite.py`) : les sept niveaux de la définition,
`CLIENT_PRIVATE` seulement vers M1 et M2 et seulement dans les couches de l'affaire, jamais les niveaux plus
fermés ; le paquet compte ce qu'il retient sans le montrer.

- `department.yaml` — manifeste (`m10_memoire.outils`, aucune dépendance — M10 est la fondation
  mémoire que M9 consomme).
- `SOUL.md` — identité de l'agent.
- `skills/journaliser-une-decision/` et `skills/preflight-contexte-suffisant/` — procédures.
- `src/m10_memoire/outils.py` — outils composés : `m10_journaliser_decision` (validation →
  écriture Affaires → référence), `m10_contexte_preflight` (PREFLIGHT, trace le refus sans
  jamais interrompre l'appelant), `m10_paquet_contexte_affaire`, `m10_consolider_affaire`,
  `m10_auditer_non_oubli` (PLAN T3.3), `m10_deposer_faits_candidats` (PLAN T3.3-suite), + outils unitaires (WCT, révision, statuts, vérification
  de référence). Seul ce module touche `opsys` (stockage, bus) : `classification.py`,
  `variance.py`, `rentabilite.py`, `consolidation.py`, `paquets.py`, `faits_candidats.py` et `audit.py` restent purs (DA-M10-08).
- Correctifs de fiabilité (TDD, tests dans `tests/`) :
  - `revision.py` — l'arbitrage d'une révision qui n'a jamais été signalée était accepté ;
    refusé nommément désormais (`REJ-REVISION-SIGNALEMENT-INTROUVABLE`).
  - `contexte.py` — `verifier_reference` acceptait un champ `registre` incohérent (None, vide,
    mauvais type) et un `hash_tete` positionné AVANT la ligne référencée (impossible
    causalement) dès lors qu'il existait ailleurs dans la chaîne ; les deux sont désormais des
    refus nommés.
  - `validation.py` — `valider_evenement` et `construire_verdict` étaient du code mort, jamais
    appelés par un chemin d'écriture réel ; `contexte.py` délègue désormais réellement sa
    validation du sous-dossier `EvenementMemoire` à `valider_evenement`, et
    `tracer_refus_contexte` trace un `verdict` construit par `construire_verdict`.

Vector memory, graphe de connaissances inféré, context injector et l'application effective du
PREFLIGHT/POSTFLIGHT (D-014, hook applicatif) restent GATED (hors périmètre v1, cf.
`docs/bmad/02-PRD-PM.md` §3.2 et `docs/research/R4-memory-rag.md`).
