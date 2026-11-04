# M10-memoire

Mémoire Long Terme — non-oubli, PREFLIGHT tracé ; POSTFLIGHT limité au dépôt de faits candidats non promus en vérité (état exigence par exigence : `docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json`).

## Mémoire admin mobile — tranche T4.25 candidate

Les lecteurs natifs de signaux et de statuts confirment l’admin actif avant registre ; la voie interne sans identité reste disponible. Le catalogue `m10_lister_references` expose les derniers états des décisions et révisions du registre Affaires, sous confidentialité, en pages courantes de huit éléments au plus et budget 5400 caractères. Le dossier `m10_lire_revision` montre les deux faits exacts (champs JSON, date, type, référence), sans mémoire développement ni coupe silencieuse. Une pièce privée, une chaîne invalide ou un dossier hors budget refuse tout le dossier.

L’arbitrage appareil confirme l’acteur humain et utilise la réception serveur : nouveau maillon onze champs avec auteur, rôle et source. Les maillons historiques et l’API pure à quatre arguments restent conservés. Le mobile réutilise l’outbox existante : même UUID et arguments persistés avant HTTP, contrôle de cible/personne/choix et hash du reçu, intention incertaine conservée et blocage du nouvel effet sur sa révision. Cache personnel informatif seulement pour signaux/références ; comparaison et statuts relus au serveur avant action.

Source isolée non publiée ; qualification locale mobile 3122 tests/153 suites et TypeScript. Les captures HTTP/SQLite sont réelles avec porte Core Python rejouée ; Gateway Node et CI du prochain commit restent à qualifier séparément. Téléphone, Expo SQLite et Hermes natifs ne sont pas inférés. Cette tranche ne clôt pas la mémoire profonde définie au §7 M10 du produit.

## Bases de connaissances par département — tranche 1 (2026-11-01)

M10 est le gardien des bases de connaissances sourcées et versionnées de chaque département (`src/opsys/connaissances/`,
[CONNAISSANCES.md](../../docs/architecture/CONNAISSANCES.md), migration 0041). Neuf outils : lecture T0/N0
(`m10_rechercher_connaissances`, `m10_lire_connaissance`, `m10_lister_sources_connaissance`), écritures internes N2
(`m10_ingerer_source_connaissance`, `m10_reviser_source_connaissance`, `m10_publier_source_connaissance`,
`m10_retirer_source_connaissance` avec raison obligatoire, `m10_reindexer_connaissances`) et la validation HUMAINE N3
(`m10_valider_source_connaissance`) : seule voie de publication d'un domaine réglementé (comptabilité, fiscalité, juridique,
investissement) ou d'une source dont le texte a déclenché le filtre anti-injection. Les autres départements lisent par
`opsys_connaissances_rechercher` / `opsys_connaissances_lire` (leur base et celles de leurs `dependances`). Recherche hybride
(FTS5 BM25 + similarité exacte + fusion RRF, reranker facultatif), toujours sourcée, avec âge et marque « périmée ».
Compétence : `skills/gerer-les-connaissances`. Aucun appareil. Corpus de mesure fictif : `evals/connaissances-recherche.v1.yaml`.

**Statut honnête.** Le mécanisme est prouvé avec un double déterministe d'embeddings ; aucun vrai modèle ni reranker n'est raccordé ni
mesuré ; aucun contenu fiscal, comptable ou juridique réel n'existe (seule une démonstration fictive). À valider auprès d'un
comptable (CPA) / professionnel qualifié.

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

M10-02, tranche 1 (2026-11-04) consomme aussi les deux ouvertures de transfert de M1 (`m1.transfert_ouvert`,
`m1.plainte_ouverte`) par `transferts.py`. M10 garde UN fait canonique par `transfert_id`, avec une liste blanche :
transfert, lead, type fermé, catégories, niveau et instant. Le pseudonyme de conversation, le canal, le déclencheur,
le contact et tout texte sont validés puis écartés, jamais recopiés. La spécialisation plainte/urgence et l'ouverture
générique du même transfert donnent le même maillon quel que soit l'ordre d'arrivée ; le rejeu est un no-op. Le fait est
`CLIENT_PRIVATE` et ne sort que dans le paquet d'affaire de M1 et M2 ; une consolidation du jour qui en contient un
reste `CLIENT_PRIVATE`. Un transfert dont `lead_id` est nul n'est jamais rattaché par déduction : le consommateur
l'acquitte avec `memorise: False` et `TRANSFERT-SANS-AFFAIRE`, sans écrire de fait. La clôture de transfert, les
promesses humaines et le rattachement ultérieur d'un orphelin ne sont pas livrés par cette tranche.

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

## Mnémo : modèle de soi, graphe de connaissances, apprentissage gouverné (m10-self-graphe)

`soi_graphe.py` (outils et consommateurs), `skills/gerer-le-soi-et-le-graphe/`, `evals/soi-graphe.v1.yaml` ; la logique vit dans
`src/opsys/mnemo/` (socle). Trois pièces : le **modèle de soi** de l'entreprise (énoncés versionnés, sourcés, confirmés par une
personne, dérive = révision proposée), un **graphe d'entités** natif (migration 0052, schéma fermé, arêtes sensibles confirmées par
une personne, port `MoteurGraphe`) et des **leçons** mesurées hors ligne, promues par une personne (canari, retour arrière, aucune
application seule). 21 outils M10 + 2 outils communs, aucun rôle d'appareil (7 outils de plus pour les contradictions et la mémoire d'expérience : voir plus bas). Documentation, mesures et limites :
[docs/architecture/M10-SOI-GRAPHE.md](../../docs/architecture/M10-SOI-GRAPHE.md). Statut : PARTIEL (aucun modèle réel, aucune donnée
réelle ; M3 et M5 consomment les leçons depuis M10-06, sous le minimum d'échantillon VIDE à dessein : aucune correction n'est
proposée tant que la direction ne l'a pas déclaré).

Vector memory, graphe de connaissances INFÉRÉ par un modèle (le graphe de Mnémo est explicite et sourcé), context injector et l'application effective du
PREFLIGHT/POSTFLIGHT (D-014, hook applicatif) restent GATED (hors périmètre v1, cf.
`docs/bmad/02-PRD-PM.md` §3.2 et `docs/research/R4-memory-rag.md`).


Qualification intégrée T4.25 (Toronto,7octobre2026) :3140tests mobiles/154suites,1291Python affectés/1skip, types/Ruff/vérificateur219outils/127déclarations verts ; Gateway Node réelle13phases et Core complet local construits séparément. Socle local4367P/224skips/3F conservé : deux oracles cgroup sans cpu.max ; assertion de test Hermes locale corrigée au jourUTC, puis95P/5skips voisins. CI du futur commit exact requise. Téléphone/ExpoSQLite/Hermes natifs non qualifiés. [Audit](../../docs/reprise/MEMOIRE-M10-2026-10-07/AUDIT-MEMOIRE-M10-2026-10-07-r2.md).

## Consolidation nocturne d'affaires, audit « non-oubli » et KPI — routines planifiées (M10-01, 2026-11-02)

(`routines.py` pur, `routines_outils.py`, exécuteurs `m10.routine.*` : `docs/architecture/PLANIFICATION.md` §10.) La consolidation
d'affaires était un tour d'agent « à construire » (il manquait l'énumérateur), l'audit n'était pas planifié et les cinq KPI du
manifeste n'étaient jamais calculés. Trois routines déclarées au `department.yaml`, **inactives par défaut** :

- `consolidation-affaires` (suit le cron de `consolidation-nocturne`, qu'elle remplace) : `m10_lister_affaires_a_consolider`
  désigne, pour la veille, les affaires touchées dont le fait durable manque ou ne cite pas toutes les sources — exactement celles
  pour lesquelles `m10_consolider_affaire` écrirait un maillon (tri stable, borné ; un identifiant d'affaire forgé dans un événement
  n'est jamais désigné, il est compté). Chaque affaire est consolidée sous son bail : l'échec de l'une n'arrête pas les autres. Un
  événement tardif ajoute un fait qui cite toutes les sources, sans réécrire l'ancien. **Un jour manqué n'est pas rattrapé.**
  `m10_consolider_affaire` passe de N3 à **N2** explicite (le planificateur n'appelle jamais un N3) ;
- `audit-non-oubli` (cron déclaré, lundi 4 h 30, à valider) : `m10_executer_audit_non_oubli` relit l'ATTENDU du bus (événements
  que M10 a reçus comme traités), et répond à cinq questions-tests par des comptes (trace des événements livrés, chaînes intactes,
  jours consolidés, révisions en attente, âge de la dernière mémoire). Aucun score opaque ;
- `kpis-memoire` (cron déclaré 4 h 45, à valider) : `m10_calculer_kpis`. Calculés : affaires consolidées pendant le cycle, oublis du
  dernier audit, taux de révisions arbitrées (s'il y en a). **Dits non calculables avec ce qui manque** : le taux de préflight
  insuffisant (seuls les refus sont tracés) et les références forgées détectées (le rejet n'est pas consigné).

Résultats au registre `rapports_routine` (hash-chaîné, idempotent par genre, fin et empreinte du contenu), lus par
`m10_lire_rapports_routine` (dernier audit, derniers KPI, faits consolidés par jour). Quatre outils de plus, tous internes, agent
seulement. Statut : PARTIEL, prouvé sur SQLite avec horloge injectée, vrai bus et données fictives
(`tests/test_routines_m10_e2e.py`) ; jamais sur PostgreSQL ni sur la boucle réelle pendant des jours.


## Contradictions, ordre de vérité et ingestion de la mémoire de projet (M10-03 et M10-04, 2026-11-02)

Documentation et limites : [docs/architecture/M10-CONTRADICTIONS.md](../../docs/architecture/M10-CONTRADICTIONS.md). Deux mémoires de sources
différentes qui se contredisent ne sont plus tranchées au hasard ni détectées à la main seulement :

- **L'ordre de vérité est une donnée** (`contracts/ordre-verite.v1.json`, lu par `verite.py`) : constitution > décisions du propriétaire > matrice
  vivante > rapports validés > tests et sondes > code > documentation > journaux > mémoires anciennes > hypothèses (l'ordre du condensé de Nathan ; la
  divergence avec l'arbitrage de l'analyse d'écart est dite dans le document). La classe d'une source dépend du canal qui l'a écrite : un agent ne se
  donne pas une autorité haute.
- **Deux registres append-only chaînés**, `affirmations` (faits à clé, sourcés, par domaine) et `contradictions` (détection, marques `retenue` / `dominee` /
  `contestee`, demande d'approbation, décision). Une contradiction non critique de rangs différents est résolue (l'autre source est *marquée*, jamais supprimée) ;
  une contradiction **critique** ouvre une demande au sas N3 dont les arguments sont la proposition ; rejouer la détection n'ajoute rien.
- **Cinq outils** (`contradictions_outils.py`) : `m10_consigner_affirmation` (N2), `m10_declarer_affirmation_humaine` (N3), `m10_lire_contradictions` (N0),
  `m10_rafraichir_contradictions` (N2, écriture réservée au planificateur), `m10_decider_contradiction` (N3) ; aucun droit d'appareil.
- **Une cinquième routine planifiée** `contradictions-memoire` (cron `10 4 * * *`, à valider, **inactive par défaut**, en ombre « aurait » sans rien écrire).
- **Ingestion de la mémoire de projet** (`ingestion_projet.py`, `opsys-metier memoire-developpement ingerer-projet --depot …`) : directives de Nathan (une décision par
  section), ADR (statut, remplacement total lié, partiel consigné), règles d'agent, condensés (prompts versionnés), matrices (une affirmation par exigence), sources
  avec chemin + empreinte + date + sensibilité classée ; idempotente, sans suppression (versions, archives, retraits), bornée ; consultable par le preflight de
  développement existant (module `PROJET`).

Statut : PARTIEL. Prouvé sur SQLite avec le vrai bus, la vraie file d'approbation et le vrai planificateur à horloge injectée
(`tests/test_contradictions_m10_e2e.py`) et par des mutations (voir le compte rendu de la livraison) ; jamais sur PostgreSQL ni avec des données réelles.

## Mémoire d'expérience des agents : jalons J1 et J2 (2026-11-02)

[docs/architecture/MEMOIRE-EXPERIENCE-AGENTS-J1-J2.md](../../docs/architecture/MEMOIRE-EXPERIENCE-AGENTS-J1-J2.md). `experience_outils.py` : `m10_proposer_experience`
(N2) passe la **garde d'admission** (`opsys.mnemo.experience` : schéma fermé, noms vérifiés contre le registre MCP scellé, aucune valeur, aucun chiffre, aucun renseignement
personnel, aucun conseil de contourner l'approbation) ; l'élément reste `candidat`, aucun département ne le lit. `m10_lire_experiences` (N0). Le **banc** « avec / sans mémoire »
(`opsys.evaluation.memoire_experience`, cas `evals/experience.v1.yaml`) se valide par un répondant double sensible à la mémoire. **Aucun modèle réel n'a été mesuré.**

## Leçons consommées par M3 et M5 (M10-06, 2026-11-03)

`src/opsys/mnemo/consommation.py` est le consommateur DÉTERMINISTE commun : il reçoit les leçons que le port
`opsys_lecons_actives` rend actives, vérifie la cible, l'état, le paramètre décimal, les sources et la date, puis n'applique
qu'une seule leçon par clé. L'échantillon (`contenu.chantiers`) doit atteindre le **minimum DÉCLARÉ** dans
`configuration.lecons_consommees.echantillon_minimum` (VIDE dans les manifestes M3 et M5 : sans valeur, aucune correction et la
réponse dit quoi déclarer). Chaque valeur corrigée cite `lecon_id`, `sources`, `date`, `echantillon` et `parametre` ; la
correction est une **proposition N4**, jamais appliquée au registre, au devis, au prix ou à la marge calculée. La valeur
corrigée est arrondie selon la grandeur (cent `ROUND_HALF_UP` pour une marge, 4 décimales pour une quantité). Le canari se
tire sur la version d'estimation (son hash exact), jamais sur le lead ; une marge n'est rendue qu'à un appelant qui déclare
explicitement le droit aux coûts (`droit_aux_couts`). Deux unités pour une même clé sont refusées (`unite_ambigue`) ; l'unité
n'étant pas stockée dans la leçon, la divergence entre deux estimations n'est pas fermée.

- **M3** : `m3_estimer_projet` rend `prevision_materiaux_avec_lecons` à côté des `besoins_materiaux` (quantité de base
  inchangée, facteur proposé) ; `m3_prevoir_materiaux_avec_lecons` la relit pour un devis dont l'estimation d'origine est
  prouvée par son hash exact. La leçon d'écart de matériaux garde sa cible `m06-material-control` (origine des variances) ;
  M3 la lit pour la prévision, sans changer la cible.
- **M5** : la vue détaillée de `m5_lire_rentabilite_chantier` (filtre `devis_id`) rend `prevision_marge_avec_lecons` à côté de
  la marge prévue reçue de M3 (`prix_total - cout_total`), sans modifier ce calcul.
- **Retrait** : après `retour_arriere`, la leçon ne paraît plus dans `opsys_lecons_actives` et la correction disparaît.
- **Preuve** : `tests/test_m10_06_lecons_consommees_e2e.py` (variance et marge réelles → extraction M10 → promotion humaine →
  M3 puis M5), `tests/test_mnemo_consommation.py`, `departments/m03-estimation/tests/test_m3_lecons_materiaux.py`,
  `departments/m05-financecore/tests/test_m5_lecons_marge.py`. **Limites** : peu de chantiers (seuil M10 de 6), facteur non
  ventilé, aucune mesure sur un modèle réel ni sur PostgreSQL, minimum non déclaré par défaut.
