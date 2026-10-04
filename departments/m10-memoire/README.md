# M10-memoire

Mémoire Long Terme — non-oubli, PREFLIGHT tracé (POSTFLIGHT applicatif hors périmètre v1).

## Provenance PDF Finance — tranche 26 qualifiée localement

**M10 global et Fusion restent PARTIEL.** Le raccord inscrit des métadonnées
candidates `FINANCIAL` dans le registre documentaire existant, sans copier
texte/citations ou indexer le contenu. Le PDF reste leur autorité ; contrat
CSV conservé, SQLite seulement, ancien lot absent sans backfill GET/rejeu.
ROOT r156 : **1 401/1 401 sur 52 fichiers complets**, sans échec/erreur/skip,
179,504 s JUnit, Ruff/vérificateur verts, 1 247 sources sans dérive/OOM.
Rouges r152/r153 conservés. La campagne inclut un test M10 de développement
sur PostgreSQL réel en RAM, sans qualifier le raccord financier PDF sur PG.
[Design](../../docs/grs/memory/M10-PROVENANCE-PDF-DESIGN-2026-10-04.md)
et [rapport](../../docs/grs/memory/M10-PROVENANCE-PDF-RAPPORT-2026-10-04.md).
Aucun classement universel, ancre externe ou apprentissage n’est déclaré.

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

PLAN T4.18 ajoute l'AMONT d'une affaire, du lead au devis (`etapes.py`, `amont.py`) : M10 consomme
`m1.lead_qualifie`, `m2.client_associe`, `m3.devis_accepte` et `m3.devis_sans_reponse` et les garde au même registre
Événements. Il ne garde que des identifiants et des faits d'étape, extraits un par un de la charge : jamais le
contact du lead, la ville, les empreintes du correspondant, les lignes d'un devis ni un texte de client (Loi 25).
Le client associé est `CLIENT_PRIVATE` (M1 et M2 seulement) ; le prix et le coût d'un devis accepté sont un maillon
compagnon `FINANCIAL`, absent de tout paquet. L'instant de chaque fait est celui de l'événement. Un rejeu ne crée
rien ; un fait reçu avant celui qui le précède est gardé sans bloquer l'autre ; un lead inconnu n'est jamais inventé
(le reçu du fait dit `origine_recue` et `verdict`). Le paquet montre l'historique (source, heure), la consolidation
nocturne et l'audit « non-oubli » couvrent ces faits. `m3.devis_envoye` (T4.7) s'ajoute par une entrée de la table de
`etapes.py` et une ligne du manifeste.

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

PLAN T4.18-b ajoute une forme d'affaire COMMUNE et deux blocs au paquet, sans toucher aux quatre couches.
1. **Une seule forme d'affaire** (`affaire.py`). Une affaire est un lead, ou l'opportunité `<lead>~opp~<wct_id>` que M2 ouvre quand un
   client revient. Forme bornée (64 + 5 + 128 = 197 caractères, lettres, chiffres et `._:-`), écrite mot pour mot dans M10 et dans le
   core (`AFFAIRE_ID` et `AFFAIRE_LINE`, `opsys-contexte-paquet.ts`) ; le core (vitest) et M10 (pytest) rejouent la MÊME liste de cas
   (`core/src/context-engine/opsys-contexte.affaires.json`). Le lien de session, le dépôt POSTFLIGHT, le paquet et les faits de
   l'amont la partagent ; M1 garde la forme du lead seul (il ne publie jamais d'opportunité). Une chaîne d'opportunités
   (`<lead>~opp~a~opp~b`) n'est pas admise : M2 rattache toute opportunité au lead racine (PLAN T4.18-c).
2. **Le bloc `affaire`** du paquet : `{connue, origine_recue, origine, verdict}`. Une affaire dont M10 n'a reçu aucun fait est dite
   INCONNUE (`AMONT-AFFAIRE-INCONNUE`) au lieu de quatre couches vides ; une affaire dont l'étape qui l'ouvre manque est dite sans origine
   (`AMONT-ORIGINE-NON-RECUE`). L'étape qui ouvre un lead est le lead qualifié de M1, celle qui ouvre une opportunité le client associé de
   M2 (`etapes.py`, champ `ouvre`). Vocabulaire fermé, sans renseignement personnel. Bloc additif plutôt qu'un outil
   `m10_dossier_affaire` : les quatre couches et leur ordre, que le core valide, ne bougent pas ; un second appel par tour coûterait un
   aller-retour de plus et pourrait échouer seul, alors que le verdict doit arriver avec les couches qu'il qualifie.
3. **Le bloc `consolidation`** : quand la couche des événements omet des faits, les jours de ces faits qu'aucun fait durable ne résume,
   au plus 10 jours (`NB_JOURS_A_CONSOLIDER_MAX`), les plus anciens d'abord, avec l'affaire : chaque entrée `{affaire_id, jour}` est l'argument exact de
   `m10_consolider_affaire`, et le jour sort de la liste dès que l'outil l'a consolidé. `nb_a_consolider` dit le total. Un fait retenu par
   confidentialité ne donne pas son jour.
4. **Le budget du paquet** (`paquets.py`), tel que le code le calcule. Le paquet a 4 000 caractères (`BUDGET_CARACTERES_DEFAUT`) de
   faits, partagés également entre les quatre couches : 1 000 caractères chacune (`budget_par_couche`), et au plus 5 faits par couche
   (`NB_FAITS_MAX_PAR_COUCHE_DEFAUT`). Une couche garde ses faits du plus récent au plus ancien et s'arrête au premier plafond atteint ; son
   premier fait est toujours gardé, même trop gros. Avec des identifiants de 64 caractères, un fait de l'historique pèse 180 à 270
   caractères : quatre tiennent presque toujours (cinq avec les faits les plus courts), et c'est le plafond de caractères qui coupe.
   Une affaire complète (lead, client, devis envoyé, accepté, sans réponse, travaux terminés, variance) compte six à huit faits
   visibles selon l'agent et le nombre de devis : les plus anciens sont omis, et le plus ancien est son ORIGINE. Le cadrage (les deux
   blocs, les titres du core) ne compte pas dans le budget.

- `department.yaml` — manifeste (`m10_memoire.outils`, aucune dépendance — M10 est la fondation
  mémoire que M9 consomme).
- `SOUL.md` — identité de l'agent.
- `skills/journaliser-une-decision/` et `skills/preflight-contexte-suffisant/` — procédures.
- `src/m10_memoire/outils.py` — outils composés : `m10_journaliser_decision` (validation →
  écriture Affaires → référence), `m10_contexte_preflight` (PREFLIGHT, trace le refus sans
  jamais interrompre l'appelant), `m10_paquet_contexte_affaire`, `m10_consolider_affaire`,
  `m10_auditer_non_oubli` (PLAN T3.3), `m10_deposer_faits_candidats` (PLAN T3.3-suite), + outils unitaires (WCT, révision, statuts, vérification
  de référence). Seul ce module touche `opsys` (stockage, bus) : `classification.py`,
  `variance.py`, `rentabilite.py`, `etapes.py`, `amont.py`, `consolidation.py`, `paquets.py`, `faits_candidats.py` et `audit.py` restent purs (DA-M10-08).
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
