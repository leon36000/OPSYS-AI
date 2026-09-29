# Économie de tokens — stratégie en couches

> Fondé sur [`docs/research/R3-gateway-tokens.md`](../research/R3-gateway-tokens.md), sur le code
> réellement implémenté : `src/opsys/{jetons,capacites,hermes_plugin,profils,modeles,departements,
> politiques,outils,etat,openclaw,passerelle,serveur_mcp}.py` et `departments/m03-estimation/
> {department.yaml,src/m3_estimation/outils.py}` comme référence vivante (cf.
> [`DEPARTEMENTS.md`](DEPARTEMENTS.md)), et — pour la partie runtime (§2-3, §9) — sur la documentation
> primaire d'OpenClaw lue dans le clone local épinglé (`scratchpad/clones/openclaw/docs/reference/
> {prompt-caching,api-usage-costs}.md`, `docs/gateway/config-agents/heartbeat-compaction-and-
> streaming.md`), au commit `2d39f2f7` correspondant à la release `v2026.9.6`. Décisions fondatrices :
> [ADR-0006](../decisions/ADR-0006-restructuration-v2-core-hermes.md) et
> [ADR-0007](../decisions/ADR-0007-core-openclaw.md) — **OPSYS-CORE = OpenClaw épinglé** (remplace le
> point 1 d'ADR-0006 ; Hermes Agent devient un runtime alternatif optionnel, cf. §2-3 et
> `docs/research/INGREDIENTS.md` §Core). Chaque section distingue **Implémenté** (vérifié dans le code
> de ce dépôt aujourd'hui, ou exécuté — `pytest` réel) de **Prévu** (retenu par R3/ADR-0007, pas encore
> câblé ou pas encore paramétré par OPSYS).

## Vue d'ensemble

| # | Mécanisme | Statut | Où dans le code |
|---|---|---|---|
| 1 | Déterministe d'abord + outils composés | **Implémenté** (contrat général + exemple M3) | `src/opsys/outils.py`, `departments/m03-estimation/src/m3_estimation/outils.py` |
| 2 | Cache de prompt fournisseur (préfixe stable / suffixe volatil) | **Implémenté** (structure des espaces de travail) ; **paramétrage fin (`cacheRetention`) = prévu** | `src/opsys/openclaw.py::generer` (espaces de travail par agent) ; mécanisme natif OpenClaw |
| 3 | Compaction | **Natif OpenClaw, actif par défaut** ; **non paramétré par OPSYS** (aucun réglage écrit par `openclaw.py`) | Mécanisme natif OpenClaw (`agents.defaults.compaction`) — cf. §3 |
| 4 | Limiter les outils vus par un agent | **Non confirmé** pour un équivalent « recherche à la demande » côté OpenClaw ; scoping par département déjà implémenté (`Capacites.__init__(filtre=...)`) | `src/opsys/capacites.py::Capacites.__init__` — voir §4, nuance de runtime |
| 5 | Troncature des sorties + artefacts relisibles | **Implémenté**, indépendant du runtime (stdio ou HTTP) | `src/opsys/jetons.py`, `src/opsys/capacites.py::_tronquer` |
| 6 | Budgets par département (alerte, épuisé) — **deux couches** | **Implémenté** (SQLite OPSYS) + **Implémenté** (plafond dur LiteLLM `tpd_limit`), **testé** | `src/opsys/jetons.py::etat_budget`, `src/opsys/capacites.py::appeler` ; `src/opsys/passerelle.py::ClientLiteLLM` |
| 7 | Paliers local/rapide/standard/fort | **Implémenté** (mécanisme, + alias LiteLLM) ; routage par difficulté = **règle de conception manuelle** | `src/opsys/modeles.py`, `src/opsys/departements.py`, `src/opsys/passerelle.py::alias_palier` |
| 8 | Passerelle LiteLLM — **par défaut** (ADR-0007) | **Implémenté et testé** (9 tests verts, dont un aller-retour MCP réel) | `src/opsys/passerelle.py`, CLI `opsys-metier passerelle {config,cles}` |
| 9 | Métriques visibles au dashboard | **Implémenté** (natif OpenClaw : `/status`, `/usage`, Control UI → Usage) + **Implémenté en CLI/MCP côté OPSYS** ; **console OPSYS dédiée (départements/budgets/approbations) = en cours ailleurs, non vérifiée ici** | Control UI OpenClaw ; `src/opsys/cli.py::cmd_budgets`, outil `opsys_etat_budget` |
| 10 | Règles d'écriture des descriptions d'outils, SOUL, skills | **Implémenté** (partiellement gaté par le code) | `src/opsys/outils.py::Outil.__post_init__`, `src/opsys/profils.py::REGLES_COMMUNES`, `src/opsys/openclaw.py::INSTRUCTIONS` |

---

## 1. Déterministe d'abord + outils composés

**Principe** (repris d'[`ARCHITECTURE.md`](ARCHITECTURE.md) §Principes non négociables) : *« Le code calcule,
le LLM orchestre. »* Un prix, un solde, un score, une cédule ou une date viennent d'une fonction Python
testée, jamais d'une génération de modèle — donc zéro token dépensé pour le calcul lui-même.

**Où dans le code** :
- `src/opsys/outils.py::Outil` est le contrat que respecte chaque outil de département : il enveloppe
  une fonction métier déterministe existante (`fonction=...`). `executer()` l'appelle et traduit un
  refus métier (`ValueError`/`TypeError`/`KeyError`) en réponse structurée `refus_metier`, jamais en
  panne technique opaque à réexpliquer. `depuis_couple()` traduit le patron `(resultat, verdict)` déjà
  utilisé par le métier des départements.
- **Composition** : `departments/m03-estimation/src/m3_estimation/outils.py::estimer_projet` (exposé
  comme l'outil `m3_estimer_projet`) enchaîne en **un seul appel d'outil** cinq contrôles qui seraient
  autrement cinq allers-retours modèle : `qualite_photos.qualifier_photos` → `hierarchie_echelle.
  classifier_niveau_confiance` → `blocage_prix.decider_blocage` → `monte_carlo.simuler_intervalle`
  → `plancher.confronter_au_plancher`. Les outils unitaires (`m3_qualifier_photos`,
  `m3_classifier_confiance`…) restent exposés à côté pour les cas particuliers, mais l'outil composé
  est le chemin par défaut.

**Effet attendu** : chaque aller-retour économisé évite de repayer le contexte complet (system prompt,
description des outils, historique) plus les tokens de raisonnement intermédiaires du modèle entre deux
appels — `DEPARTEMENTS.md` chiffre la règle : *« un outil « de bout en bout »… remplace cinq allers-
retours du modèle. »*

**Comment le mesurer** : comparer, dans `usage_tokens` (SQLite, voir §6), le nombre d'`appels` par
estimation produite avec et sans l'outil composé — aucun calcul agrégé de ce ratio n'existe encore dans
le code (à construire si on veut le chiffrer précisément).

---

## 2. Cache de prompt fournisseur

**Mécanisme réel du runtime (vérifié dans `docs/reference/prompt-caching.md` du clone OpenClaw
`v2026.9.6`, pas seulement rapporté)** : OpenClaw sépare le prompt système en un **préfixe stable**
(définitions d'outils, métadonnées de skills, fichiers de l'espace de travail — ordonnés pour rester
byte-identiques d'un tour à l'autre) et un **suffixe volatil** (horodatage runtime, métadonnées par
tour), à une frontière de cache interne. C'est natif et automatique dès qu'un fournisseur le permet
(Anthropic `cache_control`, OpenAI `prompt_cache_key` + cache automatique, Gemini `cachedContents`,
Bedrock, DeepInfra, Model Studio…) — OPSYS n'a pas à le coder, seulement à ne pas le casser.

**Où OPSYS s'y raccorde** :
- `src/opsys/openclaw.py::generer` écrit, **par département**, un espace de travail (`SOUL.md` +
  `AGENTS.md` + `skills/`) dont le contenu est stable d'une génération à l'autre — exactement le type
  de matière que la frontière de cache d'OpenClaw place dans le préfixe. `SOUL.md` vient de
  `profils.py::rendre_soul` (identité + capacités + `REGLES_COMMUNES`) ; `AGENTS.md` vient du gabarit
  `openclaw.py::INSTRUCTIONS` (formaté avec `code`/`nom`/`mission`/`prefixe`, lui aussi figé par
  département).
- **Paramétrage fin non fait à ce jour** : le réglage natif `cacheRetention`
  (`"none"|"short"|"long"`, configurable par agent/modèle, mergé dans cet ordre : défauts globaux →
  défauts par modèle → agent×modèle → agent) **n'est écrit nulle part** par `openclaw.py::generer()` —
  les entrées `agents.json` ne portent que `{name, workspace, model}` (vérifié en lisant la fonction).
  OpenClaw applique donc son défaut par fournisseur (ex. `"short"` auto-amorcé pour Anthropic direct)
  sans que le budget/l'usage du département (M1 accueil long vs M9 rapport ponctuel) influence la
  rétention. C'est un paramétrage manquant, pas un mécanisme manquant.
- **Règle confirmée par la source, pas seulement par R3** : *« Changing the model always starts a
  different cache lineage »* — le doc amont le dit lui-même. Rien dans le code OPSYS n'empêche
  aujourd'hui de modifier `paliers.yaml` (donc le modèle d'un palier) pendant qu'une session est
  ouverte ; c'est une règle d'exploitation, pas un garde-fou codé.

**Effet attendu** : lecture de cache à un tarif très inférieur à l'input plein sur tout le préfixe
espace-de-travail, à chaque tour d'une session — l'ampleur exacte dépend du fournisseur (Anthropic :
lecture ≈0,1× le prix input ; DeepSeek et assimilés : très forte remise ; OpenAI : automatique, sans
marqueur à poser).

**Comment le mesurer — le runtime expose déjà plus que ce qu'OPSYS trace lui-même** :
- **Natif OpenClaw** (`docs/reference/api-usage-costs.md`) : `/status` (dernier tour), `/usage
  tokens|cost|full` (par message), **Control UI → Usage** — totaux et coût estimé par plage de dates,
  ventilés provider/modèle/**agent**/canal/type de token — c'est directement la ventilation par
  département qu'OPSYS recherchait côté dashboard (§9). `diagnostics.cacheTrace` (désactivé par
  défaut) donne un journal JSONL détaillé par requête (`cacheRead`/`cacheWrite`, empreintes de préfixe/
  suffixe) pour du diagnostic fin.
- **Côté OPSYS** : la colonne `tokens_cache_lus` de `usage_tokens` (`src/opsys/etat.py`) est déjà
  alimentée par `jetons.py::normaliser_usage` (lit `cache_read_tokens`/`cache_read_input_tokens`/
  `cached_tokens` selon le fournisseur) via les hooks du plugin Hermes optionnel — **mais uniquement
  quand le runtime Hermes est utilisé** ; `hermes_plugin.py::post_api_request`/`post_auxiliary_call`
  sont les seuls points qui écrivent dans `usage_tokens` aujourd'hui, et n'existent pas côté OpenClaw
  (aucun hook équivalent branché). Limite déjà connue, toujours vraie : `jetons.py::consommation()`
  (donc le budget, §6) ne somme que `tokens_entree + tokens_sortie`, jamais `tokens_cache_lus` — aucun
  taux de cache-hit n'est calculé par OPSYS lui-même. **Prévu** : soit lire ces chiffres via l'API/
  export d'OpenClaw plutôt que ré-instrumenter un hook, soit ajouter un point d'entrée équivalent côté
  OpenClaw.

---

## 3. Compaction

**Mécanisme réel du runtime par défaut (OpenClaw), vérifié dans
`docs/gateway/config-agents/heartbeat-compaction-and-streaming.md`** : `agents.defaults.compaction`
est **actif par défaut** (`enabled: true`), mode `default` ou `safeguard` (résumé par blocs pour les
longs historiques), avec des défauts précis : `keepRecentTokens: 20000` (budget verbatim conservé en
fin de transcript), `recentTurnsPreserve: 3` (tours user/assistant les plus récents jamais résumés),
`qualityGuard` actif en mode `safeguard` (rejette un résumé invalide plutôt que de stocker un contexte
corrompu). Un `contextPruning.mode: "cache-ttl"` distinct (désactivé par défaut) élague les **résultats
d'outils** anciens en mémoire : garde-début-fin (« soft-trim ») puis remplacement complet par un
texte-témoin (« hard-clear ») — le même principe que la troncature OPSYS elle-même (§5), mais côté
runtime plutôt que côté outil.

**Ce qu'OPSYS paramètre aujourd'hui** : `src/opsys/openclaw.py::generer()` écrit dans `agents.json`
`defaults.contextPruning = {mode: "cache-ttl", ttl: "1h"}` (élagage des anciens résultats d'outils
après inactivité, testé dans `tests/test_openclaw_passerelle.py`), et `passerelle.py` active
`enable_prompt_caching` sur la clé LiteLLM de chaque département. La compaction garde les défauts amont
(`safeguard`). **Limite restante** : pas encore de réglage de compaction différencié par département ;
`profils.py::config_hermes` (toujours présent, runtime optionnel) resserrait explicitement le seuil de
compaction Hermes à 40 % du contexte (au lieu de son défaut 50 %) — aucun réglage équivalent n'existe
encore pour OpenClaw. Le comportement actuel dépend donc entièrement des défauts amont ci-dessus,
identiques pour tous les départements malgré des profils de session très différents (M1 accueil
omnicanal long vs M9 rapport ponctuel).

**Effet attendu** : contexte plafonné automatiquement par le runtime sur les sessions longues, sans
action d'OPSYS ; l'absence de réglage par département signifie que M1 (sessions longues, tours
fréquents) et M9 (peu de tours, contenu dense) subissent la même politique de compaction.

**Comment le mesurer** : la compaction elle-même **consomme des tokens** (le résumé appelle un modèle,
`docs/reference/api-usage-costs.md` le confirme : « Compaction safeguard summarization … invokes
provider APIs when it runs ») — donc visible dans les mêmes totaux `/usage`/Control UI que §2, pas
comme une ligne séparée. Aucun hook OPSYS ne capture un événement de compaction à ce jour ; l'effet ne
se lit qu'indirectement (baisse des tokens d'entrée moyens par appel sur les sessions qui dépassent le
seuil). **Prévu** : réglages de compaction différenciés par département (M1 sessions longues vs M9
rapports ponctuels) dans `openclaw.py::generer()`, sur le modèle de `config_hermes`.

---

## 4. Limiter les outils vus par un agent

**Mécanisme Hermes (runtime optionnel)** : `profils.py::config_hermes` active, dans le `config.yaml`
généré, `"tools": {"tool_search": {"enabled": "auto"}}` — le modèle recherche un outil par besoin
plutôt que de recevoir toute la liste à chaque tour.

**Côté OpenClaw (runtime par défaut) : pas d'équivalent confirmé.** La documentation lue (prompt-
caching, heartbeat/compaction/streaming) ne décrit pas de mécanisme de « recherche d'outil à la
demande » ; elle documente en revanche un **tri déterministe des catalogues d'outils MCP** (« Bundled
MCP tool catalogs are sorted deterministically… so `listTools()` order changes do not churn the tools
block ») — un mécanisme de **stabilité de cache**, pas de **réduction de la liste envoyée**. R10 (§B.2,
non re-vérifié dans le clone pour cette section précise) documente par ailleurs un scoping des outils
**par agent** (`tools`/`disallowedTools`/`permissionMode`) — plus proche d'une liste blanche statique
que d'une recherche dynamique. Marqué **non confirmé** plutôt que supposé.

**Ce qu'OPSYS fait déjà, indépendamment de ce mécanisme** : chaque département n'expose, via son
serveur MCP `opsys`, que ses propres outils + les trois outils communs (`Capacites.__init__` filtre par
`filtre={departement}`) — la liste envoyée à un agent OpenClaw est donc déjà bornée à un seul
département, jamais aux 10 à la fois, quel que soit le mécanisme de recherche du runtime. Chaque
description est bornée à 1024 caractères (§10, gate de code).

**Comment le mesurer** : pas de métrique dédiée aujourd'hui ; l'effet se lit indirectement dans les
tokens d'entrée (`/usage`/Control UI, §2). **Prévu** : confirmer si un mécanisme de recherche d'outils
existe côté OpenClaw avant d'investir dedans, plutôt que de supposer une parité avec Hermes.

---

## 5. Troncature des sorties + artefacts relisibles

**Où dans le code — un mécanisme indépendant du runtime, plus un filet de sécurité optionnel** :

1. **`src/opsys/capacites.py::Capacites._tronquer`** : appliqué à **chaque** réponse d'outil qui passe
   par `Capacites.appeler()` — c'est le point de passage unique de tout appel d'outil OPSYS, que le
   serveur MCP tourne en stdio (Hermes, tests) ou en streamable HTTP (`serveur_mcp.py::application_http`,
   OpenClaw, ADR-0007) : `appeler_outil()` appelle `capacites.appeler(...)` dans les deux cas
   (`serveur_mcp.py`, vérifié). Si le JSON sérialisé de la réponse dépasse `self._limite`
   (`jetons.LIMITE_SORTIE_DEFAUT = 6000` caractères par défaut), il est remplacé par
   `{"ok": ..., "tronque": True, "apercu": <texte tronqué>}` **avant même de quitter le processus
   OPSYS** — la troncature ne dépend donc d'aucune fonctionnalité du runtime.
2. **`src/opsys/hermes_plugin.py::PluginOpsys.transform_tool_result`** : hook Hermes natif, utile
   uniquement **quand le runtime Hermes optionnel est actif** (§2), en filet de sécurité pour des
   outils *non-OPSYS* que Hermes appellerait directement (web_search, terminal…) — sans équivalent
   requis côté OpenClaw puisque tout appel d'outil `opsys_*`/`mN_*` y passe déjà par (1). Garde-fou
   explicite : il ignore les outils dont le nom contient `"opsys"` pour ne jamais re-tronquer la
   lecture d'un artefact déjà tronqué (évite une récursion).

**Mécanique de troncature** (`src/opsys/jetons.py::tronquer`) : garde 70 % de la limite en tête
(`_TETE = 0.7`) et le reste en fin de texte, stocke le texte **complet** dans la table SQLite
`artefacts` (id = `sha256(texte)[:16]`), et renvoie une instruction explicite au modèle :
`« […] N caractères omis — artefact <id> ; lire la suite avec opsys_lire_artefact(id=…, debut=…) »`.
`jetons.py::lire_artefact` relit une tranche (`longueur` par défaut 4000, max 20000) de l'artefact
stocké. Ces deux fonctions sont exposées comme l'outil `opsys_lire_artefact`
(`capacites.py::_outils_communs`), disponible dans **tous** les départements.

**Effet attendu** : le modèle ne paie que ce qu'il lit réellement — une sortie de 50 000 caractères ne
coûte que ~6000 caractères au premier tour, et seulement les tranches relues ensuite si elles sont
nécessaires, au lieu de systématiquement payer l'intégralité d'une sortie verbeuse (ex. un audit SEO
complet, un export de catalogue).

**Comment le mesurer** : nombre de lignes dans la table `artefacts` (fréquence de troncature),
`taille` moyenne (ampleur du texte économisé), et fréquence d'appel de l'outil `opsys_lire_artefact`
dans `usage_tokens` (indique si les artefacts tronqués sont effectivement relus, donc utiles, ou
jamais consultés). Aucune requête agrégée de ce type n'existe encore dans le code — à construire côté
dashboard (§9).

---

## 6. Budgets par département (alerte, épuisé)

**Où c'est déclaré** : chaque `department.yaml` porte un bloc `budget` obligatoire
(`src/opsys/departements.py::lire_manifeste`), validé strictement — `tokens_jour`/`tokens_mois`
entiers strictement positifs, `tokens_mois >= tokens_jour`, `alerte_pct` entier entre 1 et 100 (défaut
80). Exemple réel (`departments/m03-estimation/department.yaml`) :

```yaml
budget: {tokens_jour: 300000, tokens_mois: 4000000, alerte_pct: 80}
```

**Calcul du niveau** — `src/opsys/jetons.py::etat_budget` :
1. `consommation()` somme `tokens_entree + tokens_sortie` de `usage_tokens` pour le département, sur le
   jour courant et depuis le 1er du mois.
2. `pct_jour = 100 * jour_utilise / tokens_jour`, `pct_mois` de même sur `tokens_mois`.
3. `niveau = "epuise"` si `max(pct_jour, pct_mois) >= 100`, sinon `"alerte"` si `>= alerte_pct`, sinon
   `"ok"`.

**Deux comportements distincts pour le même état, à deux endroits du code — c'est le cœur du
mécanisme** :

| Niveau | `hermes_plugin.py::pre_llm_call` (avant **chaque** appel modèle) | `capacites.py::Capacites.appeler` (avant l'exécution d'**un outil**) |
|---|---|---|
| `ok` | Ne renvoie rien (`None`) — aucune interférence | Aucune vérification supplémentaire au-delà du mode d'approbation |
| `alerte` | Injecte `{"context": "[OPSYS] Budget de tokens à N %. Sois bref, évite les outils non indispensables."}` — **avertissement doux**, le modèle reste libre de continuer | Aucun blocage — tous les outils s'exécutent normalement |
| `epuise` | Injecte un avertissement plus ferme : *« Termine en une phrase et escalade à un humain ; n'entame rien de nouveau »* | **Blocage dur** de tout outil dont `autonomie is not Autonomie.T0` : renvoie `{"ok": False, "erreur": "budget_epuise", ...}` **sans exécuter l'outil** ; les outils **T0** (lecture/calcul pur) restent exécutables — le département peut toujours s'expliquer et consulter son état |

**Effet attendu** : dégradation prévisible plutôt qu'un arrêt brutal ou une dérive de coût invisible —
avertissement d'abord (à 80 % par défaut), puis blocage des écritures/actions (T1 et plus) à 100 %,
jamais des lectures.

**Deuxième couche, indépendante — plafond dur à la passerelle (implémenté, ADR-0007 pt.4)** :
`src/opsys/passerelle.py::ClientLiteLLM.enregistrer_departement` crée ou met à jour (idempotent, via
`/key/generate` ou `/key/update` de l'API LiteLLM) une **clé virtuelle par département** portant
`"tpd_limit": dep.budget.tokens_jour` — **le même nombre que le manifeste**, mais appliqué par LiteLLM
lui-même, côté réseau, avant même qu'une requête atteigne un fournisseur. Optionnellement,
`max_budget`/`budget_duration: "30d"` ajoute un plafond en **dollars** sur 30 jours. Contrairement à la
couche SQLite ci-dessus, ce plafond ne distingue pas T0/T1+ : c'est un coupe-circuit dur, pas une
dégradation graduée — les deux couches sont complémentaires (soft+gradué côté OPSYS, hard côté
passerelle), pas redondantes. Câblé par la CLI `opsys-metier passerelle cles` (lit `OPSYS_CLE_<CODE>` par
département dans l'environnement) ; **testé** (`tests/test_openclaw_passerelle.py::
test_cle_departement_creee_puis_mise_a_jour`, contre un faux serveur LiteLLM local — vérifie
notamment que la clé brute ne transite jamais dans l'URL, seulement son empreinte sha256).

**Comment le mesurer** :
- `opsys-metier budgets` (CLI, `src/opsys/cli.py::cmd_budgets`) : affiche `etat_budget()` de chaque
  département en JSON (niveau, jour, mois, limites, pourcentages).
- Outil `opsys_etat_budget` (`capacites.py::_outils_communs`) : le même état, consultable par l'agent
  lui-même en cours de session.
- Table SQLite `usage_tokens` (`src/opsys/etat.py`, clé `(jour, departement, modele)`) : source de
  vérité **du côté OPSYS/Hermes optionnel**, une ligne par jour/département/modèle avec `appels`,
  `tokens_entree`, `tokens_sortie`, `tokens_cache_lus`.
- `passerelle.py::ClientLiteLLM.info(cle)` (`GET /key/info`) : dépense (`spend`) et limites de la clé
  d'un département directement depuis LiteLLM — vérité indépendante de `usage_tokens`, utile pour
  détecter un écart entre ce qu'OPSYS croit avoir consommé et ce que la passerelle a réellement compté.

---

## 7. Paliers local / rapide / standard / fort — quel usage va où

**Où c'est déclaré** : `src/opsys/departements.py::PALIERS = ("local", "rapide", "standard", "fort")`
est la liste fermée des noms de paliers qu'un `department.yaml` peut référencer sous `modeles:` — un
département associe un palier à chaque *usage* qu'il déclare (`defaut` obligatoire, plus des usages
libres). Exemple réel (M3) :

```yaml
modeles:
  defaut: standard    # raisonnement du tour principal (qualification, synthèse)
  extraction: rapide  # sous-tâche d'extraction, moins critique
```

**Où c'est configuré** : les paliers eux-mêmes (quel fournisseur/modèle concret derrière `standard`,
etc.) vivent **hors** des départements, dans `$OPSYS_HOME/paliers.yaml`
(`src/opsys/modeles.py::charger_paliers`/`enregistrer_paliers`), éditable depuis une console OPSYS
(en cours ailleurs, non vérifiée ici — §9) ou la CLI (`opsys-metier paliers definir <palier> --provider …
--model … [--base-url …]`). Un fournisseur `"custom"` (Ollama/vLLM/llama.cpp) **exige** `base_url`
(`modeles.py::valider_palier`). **Deux traductions distinctes du même palier existent maintenant** :
`profils.py::section_modele_hermes()` (runtime Hermes optionnel, section `model:` d'un `config.yaml`)
et `passerelle.py::alias_palier()`/`modele_litellm()` (runtime OpenClaw par défaut : le palier devient
un alias LiteLLM `opsys-<palier>` que `openclaw.py::fournisseur_departement` expose comme modèle du
département) — **changer de fournisseur ne touche donc toujours aucun département**, quel que soit le
runtime actif.

**Fail-closed, dans les deux traductions** : si un département référence un palier non configuré,
`section_modele_hermes()` (Hermes) lève une erreur explicite (« configure-le dans le dashboard ou dans
paliers.yaml ») et `openclaw.py::fournisseur_departement()` (OpenClaw) fait de même — `ValueError` si
`dep.modeles["defaut"]` n'est pas dans les paliers configurés, **testé**
(`test_palier_par_defaut_manquant`). Ni l'un ni l'autre ne retombe sur un modèle par défaut inventé.
`opsys-metier verifier --paliers` (CLI) fait de cette vérification un gate CI : échoue si un palier déclaré
par un département n'est pas configuré.

**Quel usage va où — mécanisme vs politique** : l'assignation d'un palier à un usage est **une
décision éditoriale par département**, écrite à la main dans `department.yaml` — il n'existe **aucun
classifieur automatique de difficulté** dans le code (le concept RouteLLM cité par R3 §2/§8 reste au
stade « à réimplémenter maison », non fait). `opsys-metier verifier --paliers` vérifie que les noms de
paliers référencés existent et sont configurés, **pas** que l'assignation est économiquement
pertinente. La politique recommandée par R3 §8 (à appliquer manuellement en écrivant chaque
`department.yaml`) :

| Palier | Usage recommandé (R3 §8) | Exemple |
|---|---|---|
| `local` | Classification, extraction de champs, embeddings, rerank, résumés courts internes — coût marginal ≈ 0 | (aucun département ne le référence encore) |
| `rapide` | Raisonnement moyen, sous-tâches auxiliaires (extraction) | M3 `extraction` |
| `standard` | Raisonnement principal du tour, qualification, rédaction | M3 `defaut` |
| `fort` | Stratégique/critique — M9 conseil, synthèse M3 (Monte Carlo + narratif), M5 finance | (réservé, override dashboard toujours possible) |

**Comment le mesurer** : `opsys-metier paliers lister` affiche la table palier→{provider, model} actuelle.
**Limite actuelle** : la colonne `modele` de `usage_tokens` enregistre le nom de modèle littéral
renvoyé par le fournisseur (`response_model`/`model` du payload d'usage), **pas** le nom du palier —
calculer une consommation **par palier** exige de croiser `usage_tokens.modele` avec `paliers.yaml`
à la main ; aucune requête du code ne le fait aujourd'hui (prévu).

---

## 8. Passerelle LiteLLM — par défaut (ADR-0007)

**Statut : implémenté et testé.** ADR-0007 (point 4) change son statut par rapport à ADR-0006 (qui la
retenait « optionnelle ») : *« LiteLLM devient la passerelle par défaut. »* Code réel, pas seulement
retenu : `src/opsys/passerelle.py` (131 lignes), câblé dans la CLI, exercé par 6 tests
(`tests/test_openclaw_passerelle.py`) qui passent (`pytest`, exécuté pour cette mise à jour).

**Deux fonctions distinctes, toutes deux implémentées** :

1. **`passerelle.py::config_litellm(paliers)`** — génère le `proxy_config.yaml` de LiteLLM depuis les
   paliers configurés : un `model_list` où chaque palier devient l'alias `opsys-<palier>`
   (`alias_palier`), `litellm_params` traduits par `modele_litellm()` selon le fournisseur (`custom`/
   `ollama` → route locale ; sinon `{fournisseur}/{modele}` + clé lue depuis une variable
   d'environnement par fournisseur, ex. `ANTHROPIC_API_KEY`), cache activé
   (`"cache_params": {"type": "redis", "host": "valkey", "port": 6379}` — nom d'hôte Valkey déjà choisi
   par convention, service pas encore présent dans un `docker-compose.yml`), clé maître et URL de base
   de données lues depuis l'environnement (`master_key`, `database_url`). Exposé par
   `opsys-metier passerelle config --sortie litellm.yaml`.
2. **`passerelle.py::ClientLiteLLM`** — client d'administration minimal (`urllib`, stdlib, pas de
   dépendance HTTP tierce) pour les clés virtuelles par département : `enregistrer_departement()`
   (§6) est idempotent (`GET /key/info` avant d'appeler `POST /key/generate` ou `/key/update`),
   refuse une clé de moins de 24 caractères, et **ne transmet jamais la clé brute dans l'URL** —
   seulement son empreinte sha256 (`empreinte_cle()`), comportement documenté comme recommandation
   LiteLLM dans le docstring du module. Exposé par `opsys-metier passerelle cles [--budget-usd-mois N]`.

**Ce que ça ajoute par rapport à la couche SQLite OPSYS (§6)** — deux couches complémentaires :

| | SQLite OPSYS (implémenté) | LiteLLM (implémenté) |
|---|---|---|
| Unité du budget | **Tokens**, comptés par département | **Tokens/jour** (`tpd_limit`, même valeur que le manifeste) + **dollars/30 jours en option** |
| Où ça s'applique | Dans le tour de l'agent (soft à l'alerte, hard sur T1+ à l'épuisement) | À la passerelle réseau, avant l'appel au fournisseur, indépendamment de l'agent |
| Granularité de blocage | T0 toujours autorisé, T1+ bloqué à l'épuisement | Coupe-circuit dur, sans distinction d'autonomie |
| Portée du cache | Cache natif du fournisseur, même session (§2) | Cache Valkey (`cache: true`, `cache_params.type: "redis"`) — **prévu comme service**, pas encore un conteneur `deploy/` |

**Ce qui reste prévu, pas implémenté** : le service LiteLLM lui-même dans un `docker-compose.yml`
(`deploy/` existe désormais — `Dockerfile`, `entrypoint.sh`, `postgres-init/` — mais sans compose ni
service LiteLLM/Valkey à ce jour) ; l'appel automatique de `opsys-metier passerelle cles` au déploiement
(aujourd'hui une commande manuelle, clés lues depuis `OPSYS_CLE_<CODE>` dans l'environnement).

**Comment le mesurer** : `ClientLiteLLM.info(cle)` (`GET /key/info`, §6) pour la dépense d'un
département ; `opsys-metier passerelle config` pour relire la configuration effective ; Langfuse (toujours
prévu, non câblé) pour des traces coût/latence par appel au-delà de ce que LiteLLM expose lui-même.

---

## 9. Métriques visibles au dashboard

**Deux visibilités distinctes désormais, l'une native au runtime, l'autre propre à OPSYS.**

**Native OpenClaw, réelle et vérifiée (`docs/reference/api-usage-costs.md`)** — sans code OPSYS à
écrire : `/status` (tour courant, coût estimé) ; `/usage tokens|cost|full` (pied de page par message) ;
**Control UI → Usage**, qui fait déjà la ventilation que R3 recherchait : totaux et coût estimé sur une
plage de dates, par **fournisseur, modèle, agent (= département OPSYS), canal et type de token**. C'est
la page « coûts par département » demandée par l'exigence dure #3 du propriétaire, fournie par le core
plutôt qu'à construire.

**Propre à OPSYS, déjà visible sans dashboard graphique** :
- **CLI** : `opsys-metier budgets` (état de chaque département) ; `opsys-metier approbations lister [--statut …]`
  (file d'approbation T1+, cf. `src/opsys/approbations.py`) ; `opsys-metier paliers lister` (mapping
  palier→fournisseur) ; `opsys-metier passerelle config`/`cles` (§8).
- **MCP, en session** : outils communs de `capacites.py::_outils_communs` — `opsys_etat_budget`,
  `opsys_demandes_approbation`, `opsys_lire_artefact` — un agent peut interroger son propre état sans
  passer par un humain.
- **Source de vérité brute** : SQLite `$OPSYS_HOME/etat.db` (`src/opsys/etat.py`), tables
  `usage_tokens`, `artefacts`, `approbations`, `modes_departements` ; `GET /key/info` de LiteLLM pour la
  dépense par clé de département (§6, §8).

**Console OPSYS dédiée (Départements, Budgets, Approbations, Entreprise, Mémoire — ADR-0007 pt.6)** :
un `src/opsys/console/` existe déjà dans l'arbre (`securite.py`, `ressources.py`), ainsi qu'un
`src/opsys/tableau_de_bord.py` (vues/actions indépendantes du transport HTTP, au-dessus des mêmes
modules du socle) — **en cours de développement par un autre chantier, non vérifié pour cette mise à
jour** (un test associé, `tests/test_console.py`, échoue encore à la collecte —
`ImportError: cannot import name 'console' from 'opsys'`). À ne pas citer comme livré avant
vérification indépendante. Le rôle qu'elle jouera : les vues **propres à OPSYS** que Control UI ne
couvre pas (T0-T3, file d'approbation, budgets multi-couches SQLite+LiteLLM, KPIs métier) — pas une
redite de la page Usage d'OpenClaw.

**Métriques que R3 §8 recommande d'exposer, et ce qui est calculable aujourd'hui — mis à jour** :

| Métrique (R3 §8) | Aujourd'hui |
|---|---|
| Tokens in/out cumulés par département/jour | **Oui** — natif OpenClaw (Control UI → Usage, par agent) ; aussi dans `usage_tokens` côté Hermes optionnel |
| Coût $/1000 requêtes, coût $/jour vs budget | **Oui, coût estimé** — natif OpenClaw (`/usage cost`, Control UI) ; le budget OPSYS reste en tokens (§6), pas encore croisé avec ce coût |
| Taux de cache-hit natif-fournisseur | **Oui** — `diagnostics.cacheTrace` OpenClaw (désactivé par défaut, JSONL détaillé) ; côté OPSYS toujours pas agrégé en taux (`tokens_cache_lus`, §2) |
| Taux de cache-hit exact/sémantique (LiteLLM/Valkey) | Non — Valkey référencé par convention dans `config_litellm()` mais pas encore déployé (§8) |
| Répartition local / cloud-bon-marché / cloud-fort | Non sans croiser `modele`/agent avec `paliers.yaml` (§7) — Control UI ventile par agent et par modèle séparément, pas par palier |
| Nombre d'activations de fallback | Non confirmé (pas revérifié dans cette mise à jour) |
| Taille moyenne de contexte au déclenchement de compaction | Non (§3 : aucun hook OPSYS ; possible via `diagnostics.cacheTrace` côté OpenClaw, non exploité) |
| Fréquence/volume de troncature OPSYS | Calculable depuis `artefacts` (nombre de lignes, `taille`), mais aucune requête agrégée n'existe |

---

## 10. Règles d'écriture des descriptions d'outils, SOUL et skills

**Descriptions d'outils — gatées par le code, pas seulement documentées** :
`src/opsys/outils.py::Outil.__post_init__` **lève une erreur** si la description est vide ou dépasse
1024 caractères, et si le nom ne respecte pas le motif `mN_nom_en_snake_case` / `opsys_nom`
(`_NOM_OUTIL`). `DEPARTEMENTS.md` explicite la raison : *« Chaque caractère est payé à chaque tour. »*
Le nom de l'outil sert aussi de garde de namespace : `departements.py::Departement.charger_outils`
vérifie que chaque outil commence par le préfixe du département (`m3_` pour M3) et rejette les
doublons de nom entre départements (`tous_les_outils`).

**SOUL.md/AGENTS.md — convention documentée, pas encore un gate automatique** : `DEPARTEMENTS.md` fixe
la règle *« Une page maximum : identité, ce que l'agent fait, ce qu'il ne fait jamais »* — mais aucune
vérification de longueur n'a été trouvée dans le code (`profils.py`/`openclaw.py`/`departements.py`), à
la différence de la description d'outil. Ce que le code fait en revanche, **dans les deux traductions
de runtime** : `profils.py::rendre_soul` (Hermes) ajoute le bloc `REGLES_COMMUNES` à la fin de chaque
`SOUL.md` ; `openclaw.py::generer` écrit en plus un `AGENTS.md` par agent à partir du gabarit
`INSTRUCTIONS` (5 règles fixes : les outils calculent, vérifier le budget avant une tâche longue, sens
de `en_attente_approbation`, provenance non fiable des entrées externes, ne pas faire le travail d'un
autre département) suivi du même `REGLES_COMMUNES`. Dans les deux cas, l'injection est **unique et
automatique** : aucun département ne recopie ces règles à la main (donc ne paie pas leur poids en
tokens en double au premier tour de chaque session).

**Skills — divulgation progressive, mécanisme natif du runtime (Hermes et OpenClaw)** : format Agent
Skills (`SKILL.md` avec frontmatter `name`+`description`), devenu un standard ouvert adopté par plus de
20 plateformes (R10 §B.1) — `DEPARTEMENTS.md` : *« Seules la description et le nom sont chargés
d'office ; le corps n'est lu qu'à la demande. »* R1 confirme qu'OpenClaw applique la même divulgation
progressive (« Skills = Markdown avec métadonnées… chargées à la demande »). OPSYS ne réimplémente ce
chargement dans aucun des deux cas : il se contente de copier chaque dossier de skill déclaré dans le
manifeste vers l'espace de travail généré (`profils.py::generer_distribution` pour Hermes,
`openclaw.py::generer` pour OpenClaw — même motif `shutil.copytree(dep.racine / "skills" / skill, …)`
dans les deux fonctions). La présence de `skills/<skill>/SKILL.md` est vérifiée à la lecture du
manifeste (`departements.py::lire_manifeste`, motif `_SKILL`) — un skill déclaré sans fichier fait
échouer le chargement, jamais un skill silencieusement absent.

**Effet attendu** : le prompt système d'un département (SOUL + descriptions d'outils + frontmatter des
skills) est le texte le plus répété de tout le produit — il est envoyé à chaque tour, de chaque
session, de chaque département. Chaque caractère économisé ici se multiplie par le nombre de tours ×
sessions × départements ; c'est le levier structurellement le plus rentable de toute la stratégie
d'économie de tokens.

**Comment le mesurer** : longueur (caractères) de chaque `SOUL.md` généré et de chaque description
d'outil — mesurable par simple inspection des distributions produites par `opsys-metier profils`
(`src/opsys/cli.py::cmd_profils`) ; aucun rapport agrégé n'existe encore (ex. un CI qui liste les N
plus longues descriptions par département) au-delà du blocage dur à 1024 caractères déjà en place.
