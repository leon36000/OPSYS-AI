# Hermes comme source de greffes pour OPSYS-CORE

Recherche primaire, lecture seule, 30 septembre 2026. **Recommandation : conserver le core OPSYS importé d’OpenClaw et reprendre des contrats étroits de Hermes, avec adaptation aux propriétaires existants.** Aucun résultat consulté ne démontre qu’une migration vers Hermes améliorerait les estimations, la coordination des chantiers, les permissions ou le coût total d’OPSYS. Les gains de rappel et de tokens restent à mesurer sur ces tâches.

## Source et fraîcheur

- Dépôt : [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), branche `main` observée par API GitHub.
- Commit fixé : [`f42f579cf8bac4918ac9599bece71618afadd846`](https://github.com/NousResearch/hermes-agent/commit/f42f579cf8bac4918ac9599bece71618afadd846), date du committer **2026-09-30T04:59:14Z**, message « Merge pull request #128011 from rroverin/fix/escape-drift-newline-doubling ».
- Acquisition commencée à **2026-09-30 11:40 UTC**. Les métadonnées observées indiquent `pushed_at=2026-09-30T11:39:23Z`. Un push peut concerner une autre branche ; il ne remplace pas le commit fixé ci-dessus.
- Dernière release retournée : `v2026.9.24`, publiée `2026-09-24T10:09:38Z`. La présente analyse porte sur le commit de `main`, **pas sur cette release**.
- [LICENSE fixé](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/LICENSE) lu intégralement : **MIT, © 2025 Nous Research**, modification et redistribution commerciale autorisées en conservant l’avis. Aucun autre `LICENSE`/`COPYING` trouvé sous les zones `agent/`, `tools/`, `hermes_cli/`, `plugins/memory/` du tree interrogé. Cela ne constitue pas une vérification des licences de tous les skills, plugins ni dépendances.
- Preuves locales : [acquisition](preuves-hermes/acquisition.json), [métadonnées dépôt](preuves-hermes/repository.json), [commit](preuves-hermes/commit.json), [tree non tronqué](preuves-hermes/tree.json), [releases](preuves-hermes/releases.json), [manifest des 34 fichiers acquis](preuves-hermes/source-manifest.json). Les textes téléchargés sont sous `preuves-hermes/sources/`, avec leurs chemins d’origine.

OPSYS examiné : `2e56c0d5605dfe575bde9244f38924d5390f2674`. Son [core/PROVENANCE.md](../../../core/PROVENANCE.md#L3) fixe `openclaw/openclaw`, tag `v2026.9.6`, commit importé `eb377ac59e6c9fd6c7705028034812becf00271b`, puis greffes OPSYS. **« OpenClaw2 » est le vocabulaire des documents produit OPSYS ; la provenance ne désigne pas un dépôt différent.** Le README Hermes traite d’OpenClaw et d’une migration depuis `~/.openclaw`, sans identifier « OpenClaw2 » comme projet distinct. Ce constat est limité aux sources lues, pas à tous les projets publics portant un nom voisin.

## Ce que la comparaison du 27 septembre simplifie trop

La recherche OPSYS [R2](../R2-core-hermes.md#L1) cite le commit Hermes `68fa7e9f840d24c72774508cc4dc99e8fcceb26f`. Quatre fichiers ont été récupérés à ce commit et comparés au commit frais :

| Fichier | Résultat |
|---|---|
| `agent/memory_provider.py` | Identique, octet pour octet |
| `agent/subagent_lifecycle.py` | Identique |
| `agent/prompt_caching.py` | Identique |
| `agent/memory_manager.py` | Seule différence de cet échantillon : instrumentation des appels de provider mémoire |

[Preuve de comparaison](preuves-hermes/comparison-2026-09-27.json). Les contrats riches ci-dessous existaient déjà au commit cité : **ils ne sont pas des nouveautés apparues depuis le 27 septembre**. R2 évoque déjà le squelette `MemoryProvider`/`MemoryManager`, mais une comparaison réduite aux fichiers de notes et à Honcho ne rend pas compte de leurs capacités ni de leurs limites.

Autre correction : l’intervalle `requires-python=">=3.11,<3.15"` ne prouve pas que le runtime moderne Hermes est supporté sur le Python 3.12 d’OPSYS. Le [pyproject L10–15](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/pyproject.toml#L10-L15) dit explicitement que **seul Python 3.14 est supporté**, les bornes plus anciennes laissant les installations existantes passer leur mise à jour. Cette même explication est aussi présente dans le [pyproject au commit du 27 septembre](https://github.com/NousResearch/hermes-agent/blob/68fa7e9f840d24c72774508cc4dc99e8fcceb26f/pyproject.toml#L10-L15), récupéré séparément. Les dépendances modernes portent des marqueurs `python_version >= '3.14'`. Une adoption complète demande donc une décision sur le runtime Python, ses environnements et ses dépendances ; elle ne se résume pas à réutiliser la venv OPSYS existante.

## Contrats réellement présents et intérêt pour OPSYS

### Mémoire : notes personnelles et providers sont deux surfaces différentes

La mémoire native demeure `MEMORY.md` et `USER.md`, avec des limites documentées de **2 200 et 1 375 caractères**, chargées dans le prompt, plus la recherche de sessions SQLite/FTS5. La [documentation native L11–32](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/user-guide/features/memory.md#L11-L32) déconseille deux processus écrivains partageant le même home. Ces notes ne remplacent pas la vérité d’entreprise M2/M5/M6/M10.

Le [MemoryProvider L84–206](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/agent/memory_provider.py#L84-L206) fournit un contrat plus riche :

- texte statique séparé du rappel `prefetch(query, session_id)` ; rappel anticipé en arrière-plan et indication déterministe de ce qui a été rappelé ;
- persistance d’un tour avec `turn_author`, identité et workspace au démarrage ;
- changement, reprise ou reset de session explicite ;
- observation parentale d’un résultat de délégation ;
- notification d’une écriture mémoire réussie avec provenance et contenu remplacé ;
- hook avant compression et déclaration versionnée d’un checkpoint durable.

Le [MemoryManager L447–500](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/agent/memory_manager.py#L447-L500) borne le rappel externe et évite de lancer une nouvelle requête tant qu’une précédente reste bloquée. Les échecs de rappel y sont non fatals. Pour OPSYS, cela peut inspirer les lectures ordinaires, mais **ne doit pas décider à lui seul qu’une estimation, une écriture financière ou une action critique peut continuer sans son contexte métier**.

### Checkpoint avant compression : contrat utile, disponibilité limitée

La [documentation APIv2 L199–271](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/developer-guide/memory-provider-plugin.md#L199-L271) et le [manager L718–766](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/agent/memory_manager.py#L718-L766) décrivent `compression.checkpoint_required` : sans checkpoint réussi d’un provider compatible, la réécriture avec perte est bloquée et le transcript conservé. Les autres autorités de compression doivent être neutralisées lorsque cette garantie est armée.

Deux limites déterminantes :

1. `checkpoint_required` vaut **false par défaut** ; **aucun provider bundlé n’annonce APIv2**, selon le document fixé. Ce n’est donc pas une archive durable prête à activer sans développer de provider.
2. L’évidence remise aux providers APIv2 filtre les résultats d’outils, `tool_calls`, messages système et anciens résumés. OPSYS exige précisément des faits produits par des outils déterministes : il faut conserver ces preuves dans un canal métier durable, lié à l’affaire et à l’action. Copier ce filtre risquerait de ne garder que le récit.

La présence de `tests/agent/test_pre_compress_checkpoint_contract.py` est confirmée dans le tree ; ce test n’a pas été exécuté durant cette recherche.

### Mémoire procédurale et skills : reprendre la gouvernance, borner la promotion

Hermes assemble des procédures `SKILL.md` et références à la demande ; [`/learn`](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/agent/learn_prompt.py#L1-L6) passe par les outils du tour courant. Il ne constitue pas un moteur indépendant de distillation. Ses principes utiles sont le petit index, les références séparées, la provenance d’origine et une commande de vérification.

Les [guards L164–223](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/tools/skill_manager_guards.py#L164-L223) limitent la curation autonome aux skills dont la provenance indique une propriété du curateur ; skills épinglés, externes, bundlés, hub ou utilisateur sont protégés dans ce chemin. L’origine [foreground/background_review](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/tools/skill_provenance.py#L1-L44) est indépendante du caractère supervisé de la revue. Ce sont des distinctions à reprendre.

La [documentation des écritures](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/user-guide/features/memory.md#L293-L323) et [des skills](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/user-guide/features/memory.md#L480-L505) propose staging, diff, approbation et refus si une cible a changé. **Les deux gates d’écriture sont désactivés par défaut.** OPSYS devrait générer des procédures candidates, les relier aux faits et tests, puis promouvoir une version selon ses propres rôles. Une règle de prix, un solde, une quantité ou un droit ne doit pas devenir vrai parce qu’un modèle l’a inscrit dans un skill.

### Compression et cache : bons points d’appui, économies à prouver

Le [cache planner](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/agent/prompt_caching.py#L1-L167) sépare préfixe statique et suffixe variable, place des marqueurs adaptés au transport, et choisit un TTL en fonction de la cadence. Les sources machine utilisent 5 minutes dans `auto`, les conversations humaines 1 heure, sous réserve des capacités du fournisseur. Le commentaire donnant un gain de coût concerne **une installation**, pas OPSYS.

Les [frontières déclarées par le constructeur](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/agent/prompt_cache_boundary.py) évitent de deviner par des délimiteurs où commence le contenu variable. Le [scope logique de cache](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/agent/prompt_cache_scope.py#L1-L171) conserve la lignée d’une conversation à travers compression, tout en séparant les forks et les nouveaux échanges. OPSYS peut appliquer ces principes aux prompts de département et paquets M10 avec leur version, identité et périmètre de permissions.

La [compression documentée L264–277](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/developer-guide/context-compression-and-caching.md#L264-L277) conserve des identifiants, messages utilisateur et pointeurs de récupération, avec une queue bornée et une politique configurable. Les résultats chiffrés de rappel mentionnés sont des résultats amont sur ses propres sessions, non reproduits ici. La taille actuelle de `context_compressor.py` et `conversation_compression.py` (environ 328 Ko et 255 Ko) déconseille leur copie globale. Reprendre un invariant ou une fonction pure ciblée, en le testant sur une affaire réelle anonymisée, est plus concret.

### Délégation : état explicite et autorité resserrée

L’[API publique lifecycle](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/developer-guide/subagent-lifecycle-api.md) expose lancement, état, attente, annulation, résultat et reconnexion par handle opaque. Elle distingue `CANCEL_REQUESTED` d’une fin effective ; résultats bornés, immuables et hachés ; rejet des toolsets qui élargissent ceux du parent. Cependant ses handles et résultats résident en processus une heure et **ne survivent pas au redémarrage**. Une reconnexion échouée ne lance pas un enfant de remplacement.

[`delegate_task`](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/user-guide/features/delegation.md#L80-L105) crée des enfants à conversation fraîche ; le parent doit fournir les objectifs et données. Les [réglages de construction L17–59](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/tools/delegate_tool_config.py#L17-L59) indiquent 10 enfants concurrents par défaut, profondeur 1, absence de timeout mural par défaut, et refus des commandes dangereuses de sous-agent CLI par défaut. Ces limites ne sont pas des budgets économiques globaux.

Pour OPSYS : reprendre le contrat de résultat et d’annulation, l’autorité enfant comme sous-ensemble, la corrélation et le coût agrégé. Prévoir une reprise durable distincte pour une cascade « travaux terminés » ; des threads d’agents en mémoire ne remplacent pas les états métier ni les validations M5/M6. La [portée d’exécution enfant](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/agent/delegation_context.py#L102-L118) précise elle-même que le marquage coopératif n’enferme pas du code ayant un accès direct SQLite.

### Permissions, gateway et mise à jour

La [sécurité documentée L24–62](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/user-guide/security.md#L24-L62) combine autorisation d’accès à l’agent, pairing, approbation de commandes, protections de fichiers et isolement de terminal. Le mode par défaut `smart` recourt à un modèle auxiliaire pour classifier le risque d’une commande. Les règles shell ne prouvent pas les permissions métier par affaire, personne, client et palier N0–N5 ; elles ne remplacent donc pas les capacités OPSYS. Les [limitations explicites des deny rules L183–185](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/user-guide/security.md#L183-L185) sont utiles comme contrat de sécurité honnête.

L’[admission d’update L82–146](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/hermes_cli/update_contract.py#L82-L146) distingue arbre mutable, image gérée, Nix/APT et desktop scellé ; marqueur d’image présent mais invalide signifie refus, pas permission de muter. La [mise à jour L132–159](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/website/docs/getting-started/updating.md#L132-L159) prévoit préparation d’environnement, validation, promotion du desktop par staging et drainage des tours avant redémarrage.

Ce sont de bons invariants pour l’installateur et le superviseur OPSYS. Les chemins, manifests, PM, gateways multiplexées, environnement Python et processus de completion sont propres à Hermes : copier l’updater crée un nouveau propriétaire concurrent. La documentation distingue aussi snapshot de fichiers et rollback de code ; le snapshot préalable reste best-effort et un plugin incompatible peut être désactivé, notamment un provider mémoire. Pour OPSYS, toute dégradation d’une mémoire obligatoire doit devenir un état visible et gouverné, pas une raison de laisser agir sans contexte.

## Greffes proposées, sans ajouter le runtime Hermes

| Greffe | Propriétaire OPSYS à étendre | Preuve exigée avant activation |
|---|---|---|
| Checkpoint durable avant compression, digest et clé idempotente ; preuves outils conservées séparément | Contrat `ContextEngine`, propriétaire de transcript et M10 ; workers SQLite | Arrêt entre dépôt et compression ; reprise sans doublon ; indisponibilité d’archive conservant les preuves ; aucune autorité de compression ne court-circuite le gate |
| Procédures candidates avec provenance, version, diff, rôle de promotion et cible inchangée | M10 + surfaces skills existantes du core | Une leçon sur un chantier devient candidate ; tentative de modifier une règle publiée refusée ; promotion révisable ; aucun prix ou droit reconstruit depuis le texte |
| Préfixes statiques explicitement déclarés ; contexte d’affaire variable après la frontière ; scope/version par permissions | Constructeur de prompt et wrappers de provider déjà présents | Deux clients/départements séparés ; changement de droits invalide la réutilisation ; compteurs de tokens/caches réels ; coût total mesuré sur appels et revues auxiliaires |
| Handles de délégation, annulation reconnue, résultats bornés, coûts enfants agrégés, droits comme sous-ensemble | Propriétaire de sous-agents existant + traces OPSYS | Enfant incapable d’élargir son rôle ; annulation ne déclare pas un succès ; redémarrage sans double action ; résultat relié à la bonne affaire |
| Admission d’update par provenance, staging, reçu durable, drainage | Installateur/superviseur OPSYS et propriétaire d’update du core | Installation existante reprise ; échec laissant la version courante utilisable ; reçu distinguant promotion/activation ; aucune bascule vers l’amont OpenClaw/Hermes |

Le core actuel possède déjà [ContextEngine](../../../core/src/context-engine/types.ts#L353) avec `ingest`, `ingestBatch`, `afterTurn`, `commitTurn`, `compact`, `prepareSubagentSpawn` et `onSubagentEnded`. Le moteur [opsys-contexte](../../../core/src/context-engine/opsys-contexte-engine.ts#L120) réutilise la compaction du runtime et injecte M10. Les wrappers de cache Anthropic, mémoire native et outils de sous-agents sont déjà présents. **L’entrée naturelle est donc l’extension de ces propriétaires, pas l’installation de Hermes derrière un second agent.** Le contrat exact d’un checkpoint doit être raccordé à toutes les autorités de compaction avant de promettre la garantie.

Le `MemoryProvider` Hermes est Python et piloté par son `MemoryManager`. La délégation publique charge `tools.delegate_tool` et exige un parent Hermes actif. La découverte de providers utilise sa configuration et son `HERMES_HOME`. Ces surfaces ne s’installent pas comme bibliothèques autonomes dans la boucle Node d’OPSYS. Trois voies sont distinctes : **adapter les idées en TypeScript** ; **porter une petite fonction pure avec licence/provenance** ; ou **adopter le runtime Hermes complet**. Seules les deux premières répondent au souhait d’ingrédients sans deuxième runtime d’agent.

Le [migrateur décrit dans le README L189–215](https://github.com/NousResearch/hermes-agent/blob/f42f579cf8bac4918ac9599bece71618afadd846/README.md#L189-L215) importe persona, notes, skills, allowlist, messagerie, certaines clés et instructions. Il ne promet pas de migrer les greffes OPSYS, le MCP privé, les approbations, M2/M5, paquets M10, mobile hors ligne ni contrats de chantier. Une migration complète demanderait une validation distincte de toutes ces surfaces.

## Limites de cette preuve

34 fichiers primaires téléchargés, lectures complètes de petits contrats et lectures ciblées du reste ; tree complet de 18 083 entrées utilisé pour localiser les sources. Aucun code Hermes ou OPSYS exécuté, aucune installation, aucun benchmark, aucune certification de tous les tests ou dépendances. L’existence de tests n’est pas leur réussite. Les sources marketing et chiffres de popularité n’ont pas servi au verdict.

Cette recherche n’a modifié aucune source OPSYS. Ses seules écritures sont ce rapport et les preuves externes. Le dépôt était propre à l’acquisition ; la vérification finale voit deux documents non suivis créés par les travaux parallèles (`ADR-0012-reutilisation-profondeur-productivite.md` et `DIRECTIVES-NATHAN.md`). **Statut : PREUVE documentaire et statique ; gains de qualité, de rappel, de coût et sûreté d’une greffe non démontrés avant son implémentation et ses tests.**
