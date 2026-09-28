# M10 — Mémoire : audit sans modification

> Audité le 2026-09-28. Portée : `departments/m10-memoire/`, `src/opsys/memoire/`,
> `docs/memory/RAG-PREMIUM.md`, `docs/research/R4-memory-rag.md`, `docs/produit/DEFINITION-PRODUIT.md`
> §1/§5/§6/§7(M10)/§8/§9/§13.5, `AGENTS.md`, ADR-0006, ADR-0007, ADR-0008, et le clone superficiel
> d'OpenClaw `openclaw/openclaw` (branche principale, lu le 2026-09-28 ; à recontrôler contre
> `v2026.9.6` avant mise en production — même réserve que RAG-PREMIUM.md).
>
> **Décision d'architecture la plus récente (à respecter, remplace ADR-0007) : ADR-0008 (2026-09-28,
> mandat « carte blanche » du propriétaire) — OPSYS-CORE devient un *fork dur* d'OpenClaw importé en
> instantané dans `core/`, avec « greffe native des services OPSYS », pas seulement une configuration
> externe par `$include`/MCP.** Conséquence directe pour cet audit : `core/UPSTREAM.md` et
> `src/opsys/openclaw.py` sont désignés **explicitement obsolètes** par l'ADR « à mesure que les
> greffes natives arrivent » — ce que `docs/memory/RAG-PREMIUM.md` (écrit sous ADR-0007) ne reflète
> pas encore. Cet audit note les deux endroits où ça compte et propose la mise à jour en §2. L'ADR-0008
> annonce aussi ADR-0009 (SQLite ou PostgreSQL pour le moteur métier, après l'étude R13 — pas encore
> écrite) et ADR-0010 (mémoire : RAM par moteur de contexte, gouvernance M10, RAG d'entreprise)
> **« après l'audit M10 »** : ce document est censé nourrir directement ADR-0010, §2 en est un projet.
>
> Méthode : lecture de code (pas d'exécution du core), `grep` ciblés pour vérifier qui appelle
> réellement quoi entre départements, et la seule commande d'exécution autorisée :
> `/opt/opsys-venv/bin/python -m pytest departments/m10-memoire/tests -q --import-mode=importlib
> -p no:cacheprovider` → **188 tests, 0 échec** (détail en fin de document).

## 1. Inventaire

### 1.1 Les dix règles (définition §7, section M10)

| # | Règle | Statut | OpenClaw apporte | OPSYS apporte | Ce qui manque (fichiers/tests) |
|---|---|---|---|---|---|
| 1 | Toute tâche laisse une trace | **PARTIEL** | Tiers épisodique persistant (`memory/AAAA-MM-JJ.md`, transcriptions de session indexées), provenance SQLite écrite à chaque tour (`memory-architecture.md`) | `m10_memoire.registre.Registre` : chaîne append-only, hash SHA-256 chaîné (`encodage.py::empreinte`), testée par `test_registre.py` (18 tests) et `test_revision.py` | **Les deux registres (`_REGISTRE_FORGE`, `_REGISTRE_BUSINESS` dans `m10_memoire/outils.py:24-25`) sont des singletons Python en mémoire du processus MCP — perdus à chaque redémarrage.** Aucun département autre que M4 (WCT) n'appelle M10 en pratique : `grep -rn "m10_journaliser_decision\|m10_memoriser_wct" --include=*.py .` hors `m10-memoire/` et `tests/` ne retourne rien. |
| 2 | Aucun agent n'agit sans contexte | **ABSENT** (application) ; **PRÉSENT** (prédicat) | Hook réel `before_tool_call` (bloque/exige approbation) documenté dans `docs/plugins/hooks.md` — jamais câblé par OPSYS | `m10_contexte_preflight` (`contexte.py::tracer_refus_contexte`) calcule le verdict (5 champs + ≥1 référence de décision) et **trace le refus au registre sans jamais interrompre l'appelant** — explicite dans le code, le SOUL.md et le PRD §3.2 (« D-014, loi sans exécutant ») | Le hook (`before_prompt_build` ou `before_tool_call`) qui appelle réellement le prédicat et peut bloquer une action T1+ |
| 3 | Rien n'est écrasé sans mémoire | **PRÉSENT** (registre M10) ; **exception voulue** (Couche B) | Dreaming : pré-image de `MEMORY.md` conservée avant toute réécriture, verrou optimiste sur le hash de contenu, résumé dans `DREAMS.md` (`memory-architecture.md` §« Write safety ») | `revision.py` : réviser = **ajouter** un maillon de signalement puis d'arbitrage, jamais fusionner/muter un maillon existant (`CA-M10-08`, testé) ; `registre.py::valider_chaine` détecte toute altération | `src/opsys/memoire/store.py::oublier` (Couche B) est un vrai `DELETE` SQL — cohérent avec la règle **seulement** parce que c'est un outil T3 (approbation humaine systématique) ; voir tension en §5 |
| 4 | Toute décision a une raison | **PRÉSENT** | — | `decisions.py::enregistrer_decision` refuse `REJ-DECISION-RAISON-ABSENTE` si `raison` vide, `REJ-DECISION-STATUT-INCONNU` hors énuméré ; `test_decisions.py` (12 tests) | — |
| 5 | Révisable (remplacer, archiver, expurger, pierre tombale), pas de suppression dure par défaut | **PARTIEL** | `openclaw memory forget` : suppression réelle mais ciblée par lignée de session, jamais un tombstone visible dans le fichier | `revision.py` : signalement + arbitrage humain, 4 statuts fermés dont l'échappatoire `indetermine` (D-032) — **aucune valeur « fusion »** (par conception) | Vocabulaire produit « archiver » / « expurger » / « pierre tombale » absent des énumérés `STATUT_REVISION` (`contrats.py:60-65`) ; Couche B `oublier` reste une suppression dure au sens SQL (§5) |
| 6 | Tout est sourcé | **PARTIEL** | Provenance `owner`/`agent`/`untrusted`/`system` en colonnes SQLite non éditables par le modèle (`memory-architecture.md` §Provenance) | Couche B : `source` obligatoire et non vide sur chaque fragment (`store.py::valider_meta`) | **`DecisionMemorisee` (M10) n'a aucun champ de provenance** : `contrats.py::CHAMPS_DECISION = {decision_id, raison, statut, options_ecartees}` — ni auteur, ni département, ni session. Le registre business le plus « officiel » de M10 est, lui, non sourcé. |
| 7 | Le système se connaît lui-même (modèle de soi) | **ABSENT** | Plugin bundlé `memory-wiki` : pages de synthèse par agent avec « claims, evidence, contradiction and freshness tracking » — non activé, et de toute façon **par agent**, pas au niveau du système des 10 départements | Rien : `grep -rln "modele_de_soi\|modèle de soi\|self_model\|SELF.md"` hors la définition produit elle-même est vide | Un modèle de soi **système** (identité OPSYS-AI, 10 départements, règles, portes) — voir §2 |
| 8 | Mémoire avant génération (P4) | **PARTIEL** | Injection bootstrap `MEMORY.md`/`USER.md` automatique en tête de session, voie 1 sans appel modèle | `m10_contexte_preflight` existe, callable à la demande | Rien n'appelle le prédicat automatiquement avant une tâche T1+ inter-département (Couche B + registre M10) |
| 9 | Mémoire après action (P4) | **PARTIEL** | Flush mémoire avant compaction ; dreaming nocturne planifié par défaut (`0 3 * * *`) | `m10_journaliser_decision`, `m10_memoriser_wct` existent et sont testés | Aucun `after_tool_call`/`agent_end` ne les déclenche ; aucune écriture automatique vers Couche B après une action T1+ approuvée |
| 10 | Pas de mémoire magique (explicite, testée, auditable) | **PRÉSENT** | Portes déterministes (score ≥ 0,75 par défaut, `minRecallCount` ≥ 3, `minUniqueQueries` ≥ 3 — `extensions/memory-core/openclaw.plugin.json`) avant toute promotion ; jamais un jugement de modèle seul | 188 tests verts (domaine M10, ce jour) ; `conformite.py` (802 lignes) : garde AST anti-stub, anti-import inter-domaine, anti-mutation, anti-invention de coût | — |

### 1.2 Statuts, confidentialité, couches, paquets, récupération, ordre de vérité

| Exigence (définition §7 M10) | Statut | OpenClaw apporte | OPSYS apporte | Manque |
|---|---|---|---|---|
| **Statuts de mémoire** (`active, draft, verified, stale, superseded, contradicted, archived, rejected, sensitive, requires_review` — 10 valeurs) | **ABSENT** (vocabulaire exact) | Aucun statut nommé ainsi ; dreaming a son propre cycle interne (candidat → gated → promu) sans exposer ces mots | `STATUT_DECISION` = 5 valeurs (`proposee, validee, remplacee, annulee, indetermine`), `STATUT_REVISION` = 4 valeurs (`en_attente, distincts_confirmes, obsolete_marquee, indetermine`) — **aucune des 10 valeurs produit n'existe telle quelle** | Extension ou remappage des énumérés `m10_memoire/contrats.py` vers le vocabulaire produit (ou un ADR qui documente le mapping et le gèle) |
| **Confidentialité** (`PUBLIC_INTERNAL, INTERNAL, SENSITIVE, FINANCIAL, CLIENT_PRIVATE, SECRET_REF, LEGAL_LOCKED` — 7 niveaux) | **PARTIEL** (sous-ensemble) | Provenance owner/agent/untrusted/system est un axe **différent** (confiance à l'écriture, pas confidentialité de lecture) | Couche B : `SENSIBILITES = (publique, interne, confidentielle, personnelle)` — 4 valeurs, contrainte SQL `CHECK` (`schema.sql:45`) | 3 niveaux manquent explicitement (`FINANCIAL`, `SECRET_REF`, `LEGAL_LOCKED`) ; `CLIENT_PRIVATE` recouvre approximativement `personnelle`. M5 (comptable) et le legal-locked n'ont pas de traitement distinct de `confidentielle` générique. |
| **13 couches** (journal d'événements immuable · mémoire structurée relationnelle · mémoire vectorielle · graphe de connaissances avec repli relationnel · points de reprise de workflows · registre de décisions · mémoire d'affaires · modèle de soi · routeur de récupération · injecteur de contexte · auditeur de mémoire · gouvernance · banc d'évaluation) | **PRÉSENT** : 4/13 · **PARTIEL** : 5/13 · **ABSENT** : 4/13 | Vectorielle (SQLite+sqlite-vec par agent) **PRÉSENT** côté Couche A, non configuré par OPSYS ; journal d'événements **PARTIEL** (épisodique persistant côté A, registre M10 non persisté côté B) | Structurée relationnelle **PRÉSENT** (`opsys/memoire`, PostgreSQL) ; vectorielle **PRÉSENT** (pgvector) ; registre de décisions **PRÉSENT** (M10, non persisté) ; mémoire d'affaires **PRÉSENT** (Couche B) ; gouvernance **PARTIEL** (portées + sensibilité + Loi 25 documentées, pas les statuts/contradictions) ; banc d'évaluation **PARTIEL** (jeu d'or FR, 9 questions fictives, `tests/fixtures/memoire/jeu_or_fr.json` — cible produit ≥ 200) | **ABSENT** : graphe de connaissances (aucune table de relations, aucun Graphiti) ; points de reprise de workflows (aucun mécanisme trouvé, ni côté M10 ni ailleurs) ; modèle de soi (voir 1.1 règle 7) ; injecteur de contexte (aucun `assemble()`/hook câblé — voir §2) ; auditeur de mémoire au sens rapport (`valider_chaine()` est le seul primitif, jamais exécuté en tâche planifiée) |
| **Paquets de contexte en couches** (« doit savoir », important, preuves, approfondissement — par département, chargés avant toute action critique, pour l'économie de tokens P11) | **ABSENT** | `systemPromptAddition` de `assemble()` et `buildMemorySystemPromptAddition()` sont le point d'injection technique idéal — non utilisés par OPSYS (`docs/concepts/context-engine.md`) | Couche B `opsys_memoire_rechercher` rend une **liste plate** triée par score RRF (≤ 4000 caractères, ≤ 10 résultats) — aucune classification en 4 niveaux | La fonction qui prend un résultat de recherche + le registre M10 et le range en 4 paquets ; le point de branchement sur `assemble()` (§2) |
| **Récupération multi-signaux** (sémantique, mots-clés, module, fraîcheur, importance, statut, autorité de la source, voisinage dans le graphe, permissions) | **PARTIEL** : 4/9 présents en Couche B (dont 2 comme filtres durs, pas comme signaux de rang) | Côté Couche A seule : sémantique + mots-clés (hybride), **fraîcheur** (demi-vie 30 jours), **importance** (1-10, écrite une fois), MMR — mais siloté par agent, invisible de Couche B (`memory-search.md`) | Couche B (`store.py::rechercher`, confirmé par lecture directe) : sémantique ✓, mots-clés ✓, module/portée ✓ (**filtre**, pas un signal de rang), permissions ✓ (**filtre**, cloisonnement obligatoire) — **fraîcheur, importance, statut, autorité de la source, voisinage dans le graphe : absents du calcul de score**, seul `score = Σ 1/(60+rang)` (RRF pur) | Pondération recency/importance/statut dans `store.py::rechercher` — RAG-PREMIUM ne la planifie que pour la Couche A (`memory_search`, §2.1) ; rien d'équivalent n'est prévu pour la Couche B, à ajouter explicitement au plan (§4) ; aucun signal de graphe tant que 1.2-graphe est absent |
| **Ordre de vérité en cas de contradiction** (constitution → décisions Nathan → matrice de complétion → rapports validés → tests/sondes → code actuel → documentation → journaux récents → mémoires anciennes → hypothèses, 10 niveaux) | **ABSENT** | Aucun équivalent : le dreaming résout les doublons par score/fraîcheur, pas par une hiérarchie d'autorité de sources | Rien n'implémente cette hiérarchie. `revision.py` gère « deux maillons se ressemblent », pas « quelle source l'emporte » | Un module `ordre_verite.py` qui prend deux affirmations sourcées et rend le niveau d'autorité de chacune — actuellement nulle part |
| **Consolidation nocturne** | **PRÉSENT** (Couche A) · **ABSENT** (M10/Couche B) | Dreaming complet : light → REM → deep, cron `0 3 * * *` par défaut, seuils déterministes (`minScore` 0,75, `minRecallCount` 3, `minUniqueQueries` 3), pré-image + `DREAMS.md` (`dreaming.md`) | `digest-memoire` (`department.yaml:18-24`) est une planification qui **résume** l'activité de la veille (« ne journalise aucune décision, ne signale aucune révision ») — ce n'est pas une consolidation qui fusionne/rétrograde/promeut des entrées du registre M10 ou de Couche B | Aucun équivalent dreaming pour le registre M10 ou pour Couche B (pas de job qui relit `opsys.memoire`, détecte doublons/péremption et propose fusion/expiration) |
| **Audit « non-oubli »** | **PARTIEL** (primitif) · **ABSENT** (job/rapport) | — | `registre.py::valider_chaine()` prouve qu'aucun maillon n'a été altéré silencieusement — testé (`test_registre.py`) | Rien n'appelle `valider_chaine()` en tâche planifiée ni ne produit un rapport ; et puisque le registre n'est pas persisté (règle 1), l'audit « non-oubli » est aujourd'hui **trivialement faux au premier redémarrage du processus** — c'est la lacune la plus sérieuse de l'inventaire |
| **Contradictions** | **PARTIEL** (arbitrage) · **ABSENT** (détection) | `memory-wiki` (bundlé, non activé) a une « contradiction and freshness tracking » nommée dans ses capacités, par agent | `revision.py::signaler_revision` + `arbitrer_revision` couvrent l'arbitrage **une fois qu'un humain ou un agent a déjà repéré** deux `ligne_id` en conflit — aucun statut `contradicted` explicite (le plus proche est `obsolete_marquee`) | Aucune détection automatique (similarité, contradiction logique) ; `memory-wiki` en bridge mode est un candidat partiel mais reste par-agent, pas cross-département (§2, §3) |

## 2. Architecture cible

**Principe directeur (ADR-0008, greffe native) : M10 devient la couche de *gouvernance* qui s'assoit sur
deux magasins physiques, pas un troisième magasin.** Aujourd'hui il y en a trois de fait (SQLite par
agent côté OpenClaw, PostgreSQL Couche B, registre M10 en mémoire) : le troisième doit disparaître en
tant que magasin séparé et devenir un **adaptateur de validation** au-dessus de Couche B.

### 2.1 Unifier sans doublon

- **Couche A (agent, par département)** reste `MEMORY.md`/`USER.md`/épisodique/dreaming, **telle
  quelle**, une base SQLite par agent OpenClaw (`~/.openclaw/agents/<id>/agent/openclaw-agent.sqlite`,
  confirmé dans `memory-builtin.md`). C'est une mémoire de *travail* de l'agent, jamais la source de
  vérité d'un fait d'entreprise (règle déjà posée par RAG-PREMIUM §2.3, à conserver).
- **Couche B (entreprise)** reste `src/opsys/memoire`, exposée en MCP, gouvernée par portée/sensibilité/
  rétention. **Le registre M10 (décisions, révisions, préflight) doit devenir des lignes de Couche B**,
  pas un objet Python séparé : ajouter à `memoire.fragments` (ou une table sœur `memoire.registre`) les
  colonnes `precedent_id` et `hash_maillon` pour porter la chaîne hash-chaînée que `m10_memoire.registre`
  implémente aujourd'hui en mémoire — même moteur, même transaction, même sauvegarde, mêmes portées/
  sensibilité que le reste de la mémoire d'affaires. `m10_memoire/registre.py`, `decisions.py`,
  `revision.py`, `contexte.py` restent la **couche de validation pure** (raison obligatoire, énumérés
  fermés, append-only prouvé) — mais leur `Registre.ajouter()` doit appeler `MemoireEntreprise.ajouter()`
  au lieu d'une liste Python, et leur `.lire()` une requête filtrée par `type_entree`. C'est un
  changement d'adaptateur, pas de logique métier : les 188 tests actuels testent la logique pure et
  restent valides avec un faux registre en mémoire pour les tests unitaires (patron déjà en place),
  seul un nouveau test d'intégration vérifie la persistance réelle.
- **M10 (le département)** n'est alors plus un magasin : c'est (a) le validateur ci-dessus, (b) le
  PREFLIGHT/POSTFLIGHT (2.3), (c) le calcul des paquets de contexte en couches (2.2), (d) l'ordre de
  vérité et la détection de contradictions (roadmap §4 phase 3).

### 2.2 Où vit la « RAM » (moteur de contexte OPSYS)

La demande du propriétaire (« une RAM composée à chaque tour par un moteur de contexte OPSYS ») a un
point de branchement **déjà documenté et réel** côté OpenClaw : le slot `plugins.slots.contextEngine`
(`docs/concepts/context-engine.md`, vérifié — cycle `ingest → assemble → compact → afterTurn`, plus
`bootstrap`/`maintain` optionnels). Sous ADR-0007 (pin-and-extend), la seule option aurait été un plugin
installé séparément (`openclaw plugins install -l ./opsys-context-engine`). **Sous ADR-0008 (fork dur),
la bonne implémentation est une greffe native** : un dossier `core/extensions/opsys-context-engine/`
au même niveau que `extensions/memory-core` et `extensions/active-memory`, enregistré par défaut dans la
configuration OPSYS livrée (pas une étape d'installation séparée). Il doit :

1. **`assemble()`** : appeler Couche B (`opsys_memoire_rechercher`, portées de lecture du département) et
   le registre M10 (décisions/révisions récentes pertinentes), classer le résultat en 4 paquets (« doit
   savoir » = préflight insuffisant + décisions bloquantes ; important = faits à haute fraîcheur/
   importance ; preuves = citations sourcées ; approfondissement = reste, chargé seulement sur demande
   explicite d'un outil), et rendre un `systemPromptAddition` borné en tokens (réutiliser les constantes
   `TEXTE_SORTIE_MAX`/`EXTRAIT_MAX` de `opsys/memoire/outils.py` comme budget de départ). C'est la « RAM »
   au sens strict : composée à chaque tour, jamais stockée entre les tours.
2. **`ownsCompaction: false`**, `compact()` délègue à `delegateCompactionToRuntime(...)` (SDK) — ne pas
   réinventer la compaction, seulement l'assemblage.
3. **`afterTurn()`** : c'est le point POSTFLIGHT (§2.3), pas un hook séparé à inventer.

`hostRequirements: { "agent-run": { requiredCapabilities: ["assemble-before-prompt"] } }` doit être
déclaré (agents natifs OpenClaw/Codex uniquement — cohérent avec le runtime cible d'ADR-0008).

### 2.3 PREFLIGHT / POSTFLIGHT : de prédicat à hook réel

Les hooks existent et sont documentés avec permissions explicites (`docs/plugins/hooks.md`, vérifié
mot pour mot, pas une extrapolation de RAG-PREMIUM) :

| Hook | Rôle PREFLIGHT/POSTFLIGHT | Permission requise |
|---|---|---|
| `before_prompt_build` | Appelle `contexte_suffisant()` ; injecte le paquet (2.2) | `hooks.allowConversationAccess` + `allowPromptInjection` |
| `before_tool_call` | Pour un outil T1+ : si `contexte_suffisant()` est faux, `{ outcome: "block", reason }` au lieu de tracer-et-laisser-passer comme aujourd'hui | `hooks.allowConversationAccess` |
| `after_tool_call` | Observe résultat/erreur/durée ; déclenche `m10_journaliser_decision` + `opsys_memoire_ajouter` (avec `source = outil + id d'approbation`, comme prévu par RAG-PREMIUM §8) | — (observation) |
| `agent_end` | Flush final, métriques vers M8 | `hooks.allowConversationAccess` |

C'est une greffe native (bundlée avec `opsys-context-engine` ou un plugin `opsys-memory-bridge` distinct,
`kind` libre côté SDK) — pas un patch du core. Elle lève le GATED documenté dans le PRD M10 §3.2 et le
README (« D-014, loi sans exécutant »). C'est la tâche la plus structurante de la phase 2 (§4).

### 2.4 SQLite ou PostgreSQL pour Couche B ?

**Les deux, par palier — pas un remplacement.** Trois faits convergent :

1. Couche A (le core lui-même) tourne déjà en SQLite + FTS5 + sqlite-vec, par agent, **sans serveur**.
2. ADR-0008 §6 fixe explicitement la philosophie du moteur métier : « moteur **sans serveur par défaut**,
   pour s'installer partout ; serveur de base de données pour les grosses installations et le SaaS » —
   et renvoie le choix précis à ADR-0009 (après l'étude R13, pas encore écrite).
3. La définition produit elle-même écrit « graphe de connaissances (**avec repli sur relations en
   base**) » — un repli suppose un défaut plus simple que le graphe, cohérent avec un défaut plus simple
   que PostgreSQL+pgvector pour toute la Couche B.

**Recommandation pour M10/Couche B, à faire valider dans ADR-0009/ADR-0010** : SQLite + FTS5 +
`sqlite-vec` (MIT/Apache-2.0, déjà dans l'arbre de dépendances du core forké — zéro nouvelle brique côté
licence) comme moteur **par défaut**, avec un schéma portable (le SQL de `opsys/memoire/schema.sql` est
déjà écrit en évitant les extensions Postgres exotiques hors `vector`/`unaccent`/GIN — la RRF, les
contraintes `CHECK`, l'idempotence sur `(source, empreinte)` se portent). PostgreSQL + pgvector +
pgvectorscale reste une **option déclarée** pour le SaaS multi-tenant et le RLS (RAG-PREMIUM §5 phase 2).
Ne pas faire porter cette décision par M10 seul : elle doit être la même pour tout le moteur métier
(ADR-0009), sans quoi une installation minimale a deux bases de données au lieu d'une.

### 2.5 Embedding local (GGUF) partagé

Un seul service d'embeddings pour les deux couches, confirmé possible côté OpenClaw : `memory.search`
accepte `provider: "openai-compatible"` avec une base URL et un modèle arbitraires (`memory-search.md`,
vérifié) — **à ne pas confondre avec `provider: "local"`**, qui est un serveur `llama.cpp` **géré par
OpenClaw lui-même** avec son propre GGUF par défaut (`~0,3 Go`, un modèle d'embedding différent de
bge-m3). Configuration cible :

```json5
{ memory: { search: { provider: "openai-compatible", model: "<valeur de OPSYS_EMBEDDINGS_MODELE>",
    remote: { baseUrl: "<valeur de OPSYS_EMBEDDINGS_URL>", apiKey: "${OPSYS_EMBEDDINGS_CLE}" } } } }
```

> Corrigé le 2026-09-28 (T0.14) : l'exemple d'origine utilisait une clé `openaiCompatible` qui
> n'existe pas. Le schéma du fork place `model` à côté de `provider` et l'URL dans `remote`
> (`core/src/config/zod-schema.memory-search.ts:29-45`). La configuration réelle est écrite par
> `src/opsys/openclaw.py` depuis `OPSYS_EMBEDDINGS_{URL,MODELE,CLE}`.

pointée sur le **même** service (`Ollama`/`llama-server`, bge-m3) que `OPSYS_EMBEDDINGS_URL` en Couche
B. Aujourd'hui **aucune des deux configurations n'est écrite par OPSYS** : `grep -rl "memory.search\|
memoryPolicy\|dreaming\|contextEngine" --include=*.py --include=*.json .` (hors le clone du core) ne
retourne rien. `src/opsys/openclaw.py::generer()` (lu en entier) écrit `models.json`, `agents.json`,
`mcp.json`, `automatisations.sh` — jamais de fragment mémoire. C'est un ABSENT net, distinct de tout ce
qui précède : la Couche A n'est aujourd'hui configurée par OPSYS d'**aucune façon** (ni dreaming, ni
provenance, ni cloisonnement `tools.agentToAgent`), alors que RAG-PREMIUM §2.1 la décrit comme déjà
gouvernée. À corriger tôt (phase 2, §4) car `tools.agentToAgent.enabled` par défaut à `true` laisse
aujourd'hui, en théorie, un agent de département lire la mémoire d'un autre.

### 2.6 Graphe de connaissances

Suivre la formulation produit : **un repli sur relations en base est le défaut, le graphe est
l'option mesurée.** Repli (phase 2, aucune nouvelle brique) : une table `memoire.relations` (sujet,
prédicat, objet, source, confiance, valide_de, valide_a) dans le même moteur que 2.4, interrogée par
jointures simples — couvre « le client a changé d'adresse », « le prix a changé le X » sans dépendance
externe. Option (phase 3, si le repli sature) : Graphiti + Neo4j Community, déjà retenus et licenciés
par R4/RAG-PREMIUM — voir §3.

### 2.7 Nommage à corriger

`m10_memoire/registre.py` et `outils.py` appellent les deux registres « Forge » et « Business ». Or le
« Forge » de M10 contient le Work Completion Trigger de M4 — un événement **produit**, pas un événement
d'outillage de développement. Le point ouvert n°5 de la définition (« la moitié “usine” de M10 est de
l'outillage de développement ») est déjà tranché par ADR-0008 (« hors produit, vit dans le dépôt, pas
dans le M10 livré ») : le nom `registre_forge` prête aujourd'hui à confusion avec ce concept qu'il ne
représente pas. Renommer en `registre_evenements`/`registre_operationnel` avant que d'autres
départements ne s'y accrochent (aucun ne le fait encore — bon moment pour renommer sans casser un
contrat, cf. P5 et le point ouvert n°7).

## 3. Briques (par écart)

| Écart | Candidat(s) | Dépôt | Licence vérifiée | Dernière version (date) | Maturité | Verdict |
|---|---|---|---|---|---|---|
| Persistance du registre M10 (§2.1) | **SQLite (stdlib)** ; `sqlite-vec` si un jour un tri vectoriel y est ajouté | intégré Python / github.com/asg017/sqlite-vec | stdlib (aucune) ; sqlite-vec : **MIT/Apache-2.0 double licence** (raw LICENSE) | — ; sqlite-vec `v0.1.10-alpha.4` (18 mai 2026, encore *alpha* en tag mais déjà en production dans le cœur d'OpenClaw lui-même) | Élevée (stdlib) ; correcte mais taguée alpha (mainteneur historique moins actif, un fork communautaire est apparu mi-2026 selon Reddit — à surveiller, pas bloquant vu l'usage par le core) | **Retenu** pour le schéma portable (§2.4). Pas de nouvelle brique à approuver pour la seule persistance du registre : stdlib suffit tant qu'aucun vecteur n'y est stocké. |
| Graphe de connaissances (§2.6, si l'option est activée) | **Graphiti** (Zep) + **Neo4j Community** ; **Cognee** en complément | github.com/getzep/graphiti ; github.com/neo4j/neo4j ; github.com/topoteretes/cognee | Graphiti **Apache-2.0** (vérifié R4) ; Neo4j Community **GPLv3**, sidecar non modifié = OK (AGENTS.md) ; Cognee **Apache-2.0** (vérifié R4) | Graphiti : dernière release `v0.30.2` « FalkorDB updates » (dépôt très actif, commits quotidiens observés jusqu'au 27 sept. 2026) ; Cognee : dernière release `v1.6.1` « Google Sync & Visualization » (commits quotidiens observés jusqu'au 24 sept. 2026) | Élevée pour les deux, en forte croissance | **Confirmé (déjà retenu par R4/RAG-PREMIUM), reporté en phase 3.** Note : le serveur MCP du dépôt Graphiti a basculé son défaut de Kùzu vers FalkorDB (SSPL, refusé par AGENTS.md) — sans conséquence pour OPSYS qui consomme `graphiti-core` avec Neo4j, pas ce serveur MCP par défaut ; le confirmer à l'adoption. |
| Ingestion de documents (Loi 25, local) | **Docling** | github.com/docling-project/docling | **MIT** (vérifié R4) | dernière release `v2.130.0` ; paquet `docling` sur PyPI publié le 18 sept. 2026, cadence très rapprochée (9 versions mineures entre `v2.122.0` et `v2.130.0` observées), projet LF AI & Data | Élevée, très active | **Confirmé (déjà retenu).** Écosystème `docling-serve`/`docling-mcp` mûr, exécution locale possible (air-gap, pertinent Loi 25). |
| Reranker ouvert | **BAAI/bge-reranker-v2-m3** | huggingface.co/BAAI/bge-reranker-v2-m3 | **Apache-2.0** (fiche HF, vérifié R4) | Poids stable, pas de cycle de release au sens logiciel | Élevée, standard de facto multilingue | **Confirmé (déjà retenu).** Aucun candidat mieux positionné trouvé sur licence pour le FR : les rerankers Jina restent CC-BY-NC (refusés), Cohere Rerank reste propriétaire (option cloud de secours seulement). |
| Évaluation RAG | **RAGAS** ; **TruLens** | ~~github.com/explodinggradients/ragas~~ **github.com/vibrantlabsai/ragas** (dépôt renommé/transféré, même historique) ; github.com/truera/trulens | RAGAS **Apache-2.0** (à revérifier sous le nouveau nom avant d'inscrire `INGREDIENTS.md`) ; TruLens **MIT** | RAGAS docs stables `v0.4.3` (docs.ragas.io, sept. 2026) ; TruLens maintenu (racheté par Snowflake, toujours open-source, R4) | Élevée | **Confirmé (déjà retenu par R4, sous M9 « proof-eval »), à réutiliser aussi pour le banc M10 (RAG-PREMIUM §9).** **Action** : le dépôt `explodinggradients/ragas` a été renommé `vibrantlabsai/ragas` — mettre à jour `INGREDIENTS.md` avec le nouveau nom et revérifier le fichier `LICENSE` sous cette organisation avant adoption effective (pas encore fait, ni par R4 ni par R10). |
| RAM / moteur de contexte OPSYS (§2.2) | *Pas une brique tierce* | — | — | — | — | Code OPSYS natif sur l'API `ContextEngine` du core forké (SDK public, documenté). Aucun candidat externe : les moteurs de contexte tiers trouvés en recherche (LightRAG, Haystack, LlamaIndex…) résolvent le RAG, pas l'assemblage de prompt par tour d'un agent OpenClaw — hors sujet ici. |

## 4. Plan par phases

### Phase 1 — Tranche verticale « travaux terminés → M10 (avec provenance) → paquet injecté à M3 »

Objectif : un seul chemin réel, testé de bout en bout, sans toucher aux hooks OpenClaw (reporté phase 2).

1. **Persister le registre M10** (§2.1) : `Registre.ajouter()`/`.lire()` s'appuient sur
   `opsys.memoire.MemoireEntreprise` (portées `decisions`, `evenements`, `revisions` nouvelles dans
   `department.yaml` de M10), avec les colonnes `precedent_id`/`hash_maillon` ajoutées au schéma.
   **Test** : écrire 5 maillons, fermer et rouvrir la connexion, `valider_chaine()` toujours vraie.
2. **Ajouter la provenance manquante** (règle 6, §1.1) : `decision_id, raison, statut,
   options_ecartees, departement_appelant, session_id` — refus si `departement_appelant` absent, sur
   le patron déjà en place pour `raison`. **Test** : refus nommé, cas nominal.
3. **Adaptateur M4→M10→M3** : à réception d'un WCT (déjà câblé, `memoriser_wct`), calculer l'écart
   estimé/réel (durée réelle vs prévue, matériaux utilisés vs prévus — champs déjà portés par le WCT
   et le `devis_id`) et journaliser une décision M10 « estimation recalibrée » dont la `raison` est
   l'écart mesuré. **Test** : écart faible (aucune action) vs écart fort (décision journalisée).
4. **Paquet de contexte « doit savoir »** : fonction pure `paquet_contexte_estimation(type_travaux,
   n=5)` qui relit le registre business filtré par sujet, borné en caractères (réutiliser
   `TEXTE_SORTIE_MAX`/`EXTRAIT_MAX`). **Test** : bornage respecté, tri par fraîcheur, vide si rien.
5. **Outil `m10_paquet_contexte_estimation`** (T0, lecture) dans `m10_memoire/outils.py`. **Test** :
   `test_outils_agent.py`, manifeste chargé, cas nominal/vide.
6. **Câblage côté M3** : avant `m3_estimer_projet`, appel *best-effort* (jamais bloquant si M10
   indisponible — distinct du fail-closed sur les prix eux-mêmes) au paquet, injecté comme donnée non
   fiable dans la justification de l'estimation. **Test** : M10 indisponible → M3 continue sans lui,
   tracé comme dégradation, pas une erreur.
7. **Démonstration bout en bout** scriptée, fixtures `fictif: true` : un WCT → décision M10 avec
   raison → paquet lu par l'estimation suivante du même `type_travaux`. `pytest` (M3 + M10) et
   `opsys verifier` verts.
8. **Documentation** : `SOUL.md`/`README.md` des deux départements, contrat de l'outil et forme du
   paquet.

### Phase 2 — Brancher les hooks, gouverner Couche A, lever les GATED structurels

- Greffe native `opsys-context-engine` (§2.2) + `opsys-memory-bridge` (§2.3) dans le fork.
- Configuration Couche A par OPSYS (§2.5) : `memory.search.provider: "openai-compatible"` partagé,
  `plugins.entries.memory-core.config.dreaming`, `memoryPolicy.excludeSessions`,
  `tools.agentToAgent.enabled: false` par défaut (cloisonnement inter-département).
- Extension du vocabulaire : `STATUT_DECISION`/`STATUT_REVISION` → 10 statuts produit (mapping documenté
  dans un ADR) ; `SENSIBILITES` → 7 niveaux produit (`FINANCIAL`, `SECRET_REF`, `LEGAL_LOCKED` ajoutés,
  M5 en premier consommateur).
- Auditeur « non-oubli » planifié (cron OPSYS, pas dreaming) : exécute `valider_chaine()` sur les deux
  registres persistés, publie un rapport consultable par l'admin (écran mobile « recherche mémoire,
  décisions à valider, contradictions », définition §9.5).
- Écran mobile employé minimal : « chose à ne pas oublier » (définition §9.3) = un outil T1 unitaire
  vers la portée `notes_chantier`, déjà couvert par le contrat Couche B existant.
- Repli relationnel du graphe (§2.6) sans dépendance externe.

### Phase 3 — Profondeur

- Graphe de connaissances optionnel (Graphiti + Neo4j) si le repli relationnel sature un cas réel
  mesuré (pas par anticipation — règle du banc, RAG-PREMIUM §9).
- Ordre de vérité en cas de contradiction : module dédié + détection (au minimum une similarité
  vectorielle entre nouvelles décisions et décisions actives de même sujet, avant l'écriture).
- Modèle de soi système : document vivant en Couche B (portée `modele_de_soi`, lecture par tous,
  écriture par M10 seul), pas seulement les wikis par agent de `memory-wiki`.
- Ingestion Docling + jeu d'or réel ≥ 200 questions + RAGAS/TruLens en CI hebdomadaire (RAG-PREMIUM §11
  phase 2, déjà planifiée, reste à faire).
- RLS PostgreSQL si l'option serveur (§2.4) est activée pour une installation SaaS multi-tenant.

## 5. Risques et points ouverts

- **Point ouvert n°5 (mémoire usine vs affaires) : tranché par ADR-0008** (« hors produit, vit dans le
  dépôt, pas dans le M10 livré »), mais le code n'a pas suivi — voir §2.7 (renommage `registre_forge`).
- **Empoisonnement de la mémoire.** OpenClaw défend structurellement Couche A (provenance non
  falsifiable, quarantaine du contenu `untrusted`, propagation de la souillure dans tout le tour —
  `memory-architecture.md` §« security model »). **Couche B n'a aucun équivalent** : `opsys_memoire_
  ajouter` (T1) n'a pas de colonne de provenance/confiance — un extrait de page web ramené par M7 et
  un fait dit par le patron s'écrivent avec la même autorité une fois approuvés. Le garde-fou actuel
  est uniquement le mode `ombre` (approbation humaine T1 systématique) : suffisant tant que ce mode
  tient, fragile s'il est un jour relâché sans ce contrôle. À corriger avant toute promotion de
  département en mode `supervise`/`autonome` qui touche la mémoire.
- **Suppression dure interdite par défaut vs droit à l'oubli Loi 25.** Tension réelle entre la règle 5
  (§1.1) et `opsys_memoire_oublier` (T3, `DELETE` réel journalisé). Résolue *pour l'instant* par le
  T3 (frontière humaine, AGENTS.md) — mais une fois le registre M10 persisté dans le même moteur
  (§2.1), il faut décider explicitement si `oublier` doit **aussi** écrire un maillon M10 documentant
  l'effacement (sans effacer ce maillon-là) : sinon l'effacement lui-même échappe à la règle 1 (« toute
  tâche laisse une trace ») et devient un point aveugle de l'audit non-oubli.
- **Trois taxonomies de confidentialité coexistent déjà** dans le dépôt : les 7 niveaux du produit, les
  4 `SENSIBILITES` de Couche B, et les 4 classes de provenance OpenClaw (`owner/agent/untrusted/system`
  — un axe de *confiance à l'écriture*, pas de *confidentialité à la lecture*, à ne pas confondre). Les
  clarifier et les faire correspondre avant d'écrire davantage de code qui les suppose alignées.
- **Deux architectures documentées en parallèle.** `docs/memory/RAG-PREMIUM.md` décrit encore le monde
  ADR-0007 (OpenClaw consommé de l'extérieur par `$include`/MCP) ; ADR-0008 (plus récent, même jour) le
  remplace par un fork dur avec greffes natives. Le contenu technique de RAG-PREMIUM (schéma, API,
  Loi 25, budgets) reste valide — c'est le **mécanisme de branchement** (§2.2, §2.3, §2.5) qui doit être
  réécrit pour ne pas laisser un lecteur implémenter le mauvais modèle.
- **ADR-0009 non tranché.** Le choix SQLite/PostgreSQL pour tout le moteur métier attend l'étude R13
  (pas encore écrite à la date de cet audit). La recommandation §2.4 est spécifique à la mémoire et ne
  doit pas être décidée en silo si ADR-0009 choisit l'inverse pour le reste du moteur métier.
- **`opsys openclaw configurer` et `core/UPSTREAM.md` obsolètes par construction** (ADR-0008), donc
  toute tâche de phase 2 qui les modifierait doit plutôt créer leur remplaçant natif — pas prolonger un
  mécanisme que l'ADR déclare sortant.

---

**PREUVE :**
- `find departments/m10-memoire src/opsys/memoire -type f` puis lecture intégrale de
  `departments/m10-memoire/src/m10_memoire/{__init__,contrats,registre,decisions,wct,revision,contexte,
  validation,encodage,outils}.py`, lecture ciblée de `conformite.py` (802 lignes), et de
  `src/opsys/memoire/{outils,store}.py`, `schema.sql`.
- `/opt/opsys-venv/bin/python -m pytest departments/m10-memoire/tests -q --import-mode=importlib
  -p no:cacheprovider` → 3 lignes de points, code de sortie `0`, aucun `F`/`E` ; total confirmé par
  `--collect-only -q` : 27+29+10+12+7+5+10+18+16+36+18 = **188 tests collectés = 188 passés**.
- `grep -rn "memoire_m10\|m10_journaliser_decision\|m10_memoriser_wct\|opsys_memoire_ajouter"
  --include=*.py --include=*.yaml .` (hors `m10-memoire/`, `tests/`) pour vérifier qui appelle
  réellement M10 depuis les autres départements (réponse : personne, hors M4→WCT et la déclaration de
  portée `memoire_m10` dans le contrat de rapport de M9, qui est un nom de **champ**, pas un appel).
- `grep -n "memory\|dreaming\|contextEngine" src/opsys/openclaw.py` (0 résultat) et lecture intégrale du
  fichier (178 lignes) pour confirmer l'absence de configuration Couche A par OPSYS.
- Lecture de `docs/concepts/{memory,memory-architecture,memory-provenance,memory-search,memory-builtin,
  active-memory,context-engine,dreaming}.md` et `docs/plugins/hooks.md` (+ `hooks/reference.md`,
  `hooks/tool-policy.md`) dans le clone superficiel d'OpenClaw ; manifestes
  `extensions/{memory-core,active-memory,memory-wiki}/openclaw.plugin.json` lus en entier pour les
  schémas de configuration cités en §1 et §2. Aucun code amont exécuté.
- `docs/decisions/ADR-0007-core-openclaw.md` et `ADR-0008-fork-openclaw-opsys-core.md` lus en entier ;
  `docs/programme/PLAN.md` et `BOUCLE.md` lus pour situer cet audit dans T0.3/T0.9/T0.10.
- Recherche web (Firecrawl) pour les versions/dates de §3 : GitHub `getzep/graphiti` (releases),
  `topoteretes/cognee` (releases), `docling-project/docling` (releases), `vibrantlabsai/ragas` (ex-
  `explodinggradients/ragas`, transfert d'organisation confirmé par la redirection GitHub), et
  `asg017/sqlite-vec` (VERSION + licence).
