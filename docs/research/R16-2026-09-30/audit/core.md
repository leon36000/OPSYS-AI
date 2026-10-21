# Audit ciblé OPSYS-CORE — état récent

**Statut : PREUVE, avec limites explicites.** Audit en lecture seule du commit `2e56c0d5605dfe575bde9244f38924d5390f2674`, réalisé le 30 septembre 2026. Aucune modification de `/workspace/OPSYS-AI-recent`, aucune installation de dépendances, construction, exécution de tests ou lancement du core local. Les artefacts de cet audit sont hors dépôt. PREUVE signifie ici que les observations et leur portée sont traçables ; cela ne signifie pas que le produit est prêt à être déployé.

Le travail propre à OPSYS apporte une intégration réelle : CLI métier, supervision du processus Python, identité d'appareil dans MCP, contexte M10, garde avant outil, migrations d'instance et marque française. La CI du même arbre core est verte. Deux frontières restent insuffisantes : l'interdiction de la CLI opérateur depuis un agent repose sur une variable d'environnement modifiable, et l'autorisation contextuelle d'une action ne vérifie pas son affaire cible. Une configuration invalide désactive également cette garde, conformément à un choix documenté mais contraire au principe général fail-closed. Le superviseur peut traiter un long démarrage comme une période de bonne santé. Les documents de référence ne sont pas tous à jour.

## Périmètre et méthode

Les instructions racine, `core/AGENTS.md`, les règles des agents et du Gateway, la définition produit (§1, §5 et §6), ADR-0008/0010 et la provenance ont guidé la lecture. Le skill `codex-engineering-guardrails:code-verification` a servi de méthode de qualification. Les recherches larges sont partagées avec les autres volets de l'audit ; ce rapport concerne les greffes du core et leurs contrats Python immédiats.

L'inventaire inventory.json (archive : `/workspace/audit-opsys-2026-09-30/docs-audit/recent/inventory.json`) contient **36 289 fichiers, 478 695 639 octets**. Il décrit la présence des fichiers, pas leur audit complet. La base amont n'a pas été relue ligne par ligne. [changes.txt](changes.txt) contient les **420 fichiers core modifiés depuis l'import**. La lecture approfondie privilégie les chemins d'exécution OPSYS et leurs tests : contexte/config/paquet/dépôt/MCP/garde, CLI métier et environnement, supervision, métadonnées/roles/appareils/routage MCP, instance/migration ; les propriétaires hérités (politiques d'outils, exec, HTTP, update, service) sont lus aux points de raccordement. Les nombreux fichiers d'i18n et tests voisins sont examinés comme changements de surface, sans prétendre une lecture exhaustive. [lectures.json](lectures.json) donne un registre conservateur des surfaces examinées.

La preuve des défauts ci-dessous est **statique** : branches, entrées, données effectivement transmises, contrats et tests existants. Les scénarios métier proposés n'ont pas été exécutés. Un seul témoin shell inoffensif, hors dépôt, démontre la suppression d'une variable ; il n'appelle aucun programme OPSYS. Les scénarios TypeScript doivent être ajoutés puis exécutés en CI pour constituer une reproduction dynamique autorisée.

## Volume importé et travail propre

Le commit d'import `ba19ccc5a9dcf8d96df8414d2e603efd0c959854`, du 28 septembre 2026, s'intitule « core : import du fork dur OPSYS-CORE (OpenClaw v2026.9.6 élagué) ». Son diff core ajoute **10 667 597 lignes**, supprime 69 lignes et touche 36 216 fichiers, dont 140 binaires. Ces millions de lignes sont essentiellement un instantané tiers ; ce volume ne mesure pas du code original écrit pendant la session Claude.

Entre cet import et le HEAD audité : **28 796 lignes ajoutées, 4 964 supprimées, 420 fichiers touchés**, dont un binaire. La répartition utile est :

| Zone core | Fichiers | Ajouts | Suppressions |
|---|---:|---:|---:|
| `src/` | 184 | 14 700 | 1 714 |
| `ui/` | 157 | 11 469 | 2 563 |
| `docs/` | 27 | 1 560 | 0 |
| `test/` | 9 | 275 | 410 |
| `PROVENANCE.md` | 1 | 543 | 5 |
| Autres | 42 | 249 | 272 |

Ces chiffres incluent des traductions, restaurations de ressources amont et suppressions de tests devenus incompatibles avec l'élagage. Ils ne constituent pas une mesure d'originalité algorithmique. La pièce [arbres-et-volumes.json](preuves/arbres-et-volumes.json) conserve les résultats Git et leur ventilation complète. `pnpm-lock.yaml` et `pnpm-workspace.yaml` n'ont pas changé après l'import ; la seule modification de `package.json` est l'ajout de l'alias binaire `opsys`.

## Preuve CI et sa portée

La consultation fraîche GitHub donne le run [core 36628215473](https://github.com/leon36000/OPSYS-AI/actions/runs/36628215473), terminé avec succès le 29 septembre à 21:15:30 UTC, au commit `7189c9197e301391769f737b4dfbcb0f1f95698e`. Les **huit jobs réussissent** : construction, six shards de tests, et `tests-opsys`. Les métadonnées brutes sont conservées dans [ci-core-run.json](preuves/ci-core-run.json) et [ci-core-jobs.json](preuves/ci-core-jobs.json).

L'arbre Git `core/` est **strictement identique** entre ce commit CI et le HEAD audité : `687aeae2d9a9be98ef2f6a781e55571342fbbc03`. Le blob `.github/workflows/core.yml` est également identique : `64aa58b67b5c6f154174863de456ccb542f2c741`. Cette égalité permet de rattacher la CI à la version des fichiers core examinés. Elle ne prouve pas un déploiement réel ni l'intégration de toutes les modifications Python/mobile survenues ensuite. Le dernier run général au HEAD était annulé lors de la consultation ; il ne doit pas être présenté comme vert.

Le workflow utilise Node 24, Ubuntu 24.04 et le pnpm de `packageManager`, avec installation frozen, `pnpm build`, tests rapides en six shards et une liste dédiée de tests OPSYS (`core/test/opsys-tests-cibles.txt`). Cette dernière couvre les greffes et leurs voisins Gateway/agents qui ne sont pas tous dans les shards rapides. La construction réussie ne permet pas, à elle seule, de déclarer un lint ou un contrôle TypeScript exhaustif : le workflow n'exécute pas explicitement `pnpm check`.

**Limite des journaux :** `gh run view --job --log` a renvoyé un flux vide et le téléchargement API a échoué avec Forbidden. Aucun nombre de tests, couverture ou détail d'assertions n'est déduit des métadonnées. [limite-journaux-ci.txt](preuves/limite-journaux-ci.txt) conserve cette limite. Un job vert peut parfaitement valider le comportement vulnérable choisi par ses assertions, comme pour la configuration invalide ci-dessous.

## Constats qualifiés

| ID | Gravité | Confiance sur le code | Effet principal |
|---|---|---|---|
| C01 | Élevée, conditionnelle à l'accès exec hôte | Élevée | Un agent peut retirer le refus CLI opérateur puis déclarer une identité humaine |
| C02 | Élevée, garde contextuelle | Élevée ; effet métier non rejoué | Le contexte de A autorise un outil visant B |
| C03 | Moyenne, conception documentée | Élevée | Une configuration invalide ouvre la garde N3+ |
| C04 | Moyenne, disponibilité | Élevée ; scénario dynamique à ajouter | Un long démarrage remet à zéro le budget de redémarrages |
| C05 | Moyenne pour la documentation de gouvernance | Élevée | Des documents actuels décrivent encore une architecture retirée |

### C01 — La CLI opérateur n'est séparée du shell d'agent que par un marqueur effaçable

**Preuve.** [opsys-metier-cli.ts](../../../../core/src/cli/opsys-metier-cli.ts#L197) affirme que les décisions humaines sont refusées depuis le shell d'agent « whatever the exec policy allows ». Le seul test d'origine est `env.OPENCLAW_SHELL === "exec"` à la ligne 200. Sinon la CLI lit sa configuration et lance la commande Python avec les arguments reçus à la ligne 223. [bash-tools.exec-runtime.ts](../../../../core/src/agents/bash-tools.exec-runtime.ts#L664) place cette variable dans l'environnement du shell ; ce shell peut la supprimer. Le témoin [temoin-variable-shell.txt](preuves/temoin-variable-shell.txt) vaut `OPENCLAW_SHELL=None` après un `unset` effectué dans un shell créé avec le marqueur. Aucun code OPSYS n'a été exécuté pour ce témoin.

Le garde indépendant `exec-control-command-guard.ts` traite notamment les approbations exec et `channels login`, mais ne protège pas les mutations `metier`. Son test [exec-control-command-guard.test.ts](../../../../core/src/infra/exec-control-command-guard.test.ts#L40) laisse explicitement passer `opsys metier base etat`. L'exécutable Python `opsys-metier` et `python -m opsys.cli` ne contiennent pas de refus équivalent d'origine agent.

La commande d'approbation Python [cli.py](../../../../src/opsys/cli.py#L195) transmet directement `args.par` à `approbations.decider`; `--par` est une chaîne fournie sur la ligne de commande (ligne 601). [approbations.py](../../../../src/opsys/approbations.py#L200) vérifie utilement que la personne est active et porte un rôle autorisé, mais ces vérifications n'authentifient pas l'appelant comme cette personne. Le changement de mode [fixer_mode](../../../../src/opsys/approbations.py#L392) exige seulement un mode connu et un `par` non vide avant l'écriture et l'audit.

**Préconditions exactes.** L'agent doit disposer d'un exec hôte autorisé permettant un shell ou l'interpréteur approprié, sous un compte capable de lancer le moteur et d'accéder en écriture à l'instance. La CLI/configuration doit être installée. Pour approuver, la demande doit exister et l'identifiant choisi doit être une personne active autorisée. N5 conserve son exigence d'attestation professionnelle. Un sandbox sans accès au moteur/à la base, une identité système distincte ou une politique exec qui refuse ces commandes coupe cette voie. Il ne s'agit pas d'une compromission distante anonyme.

**Scénario à reproduire en environnement de test isolé, non exécuté ici :** depuis un exec autorisé, supprimer le marqueur puis appeler `opsys metier approbations approuver <demande> --par <personne-autorisée>`. Le code ne distingue alors plus cet appel d'un appel opérateur. Un appel direct au Python ignore également le marqueur. Un changement de mode avec une signature textuelle arbitraire élargit en plus les actions futures permises au département, selon les règles de canal applicables.

**Impact.** Les frontières humaines P1/T3 et la traçabilité P3 peuvent être contournées par un agent disposant du shell de l'instance ; une trace nominative ne prouve plus la décision de la personne nommée. Les contrôles métier de rôle et d'attestation restent présents, mais ne séparent pas les deux acteurs partageant le compte système.

**Tests et correction.** Les tests `opsys-metier-cli.test.ts:304` vérifient le refus lorsque le marqueur est conservé et l'autorisation de `tui-local`, sans vérifier sa suppression ou l'entrée Python directe. La correction doit établir une frontière effective : séparer l'identité/les permissions du processus agent et réserver les mutations d'opérateur à une authentification ou capacité liée à l'humain et vérifiée au point d'écriture. Ajouter un autre marqueur d'environnement ne résout pas cette propriété lorsque l'agent possède le même accès OS à la base.

### C02 — La garde M10 ne lie pas l'autorisation à l'affaire de l'outil

**Preuve.** Le moteur [opsys-contexte-engine.ts](../../../../core/src/context-engine/opsys-contexte-engine.ts#L372) valide le paquet pour l'affaire résolue et stocke `affaireId`, le nombre de signaux ouverts et l'heure par session (ligne 400). Le raccord [agent-tools.before-tool-call.policy.ts](../../../../core/src/agents/agent-tools.before-tool-call.policy.ts#L174) appelle la garde avec le nom d'outil, la session et l'agent, sans arguments métier. [evaluateGuard](../../../../core/src/context-engine/opsys-contexte-garde.ts#L128) n'a aucun paramètre de cible. Pour un outil N3+, un état prêt, frais, à zéro signal conduit à `block:false` à la ligne 155, quelle que soit l'affaire visée par les arguments.

Le chemin métier est concret : [m3_estimer_projet](../../../../departments/m03-estimation/src/m3_estimation/outils.py#L957) reçoit `contrat.lead_id` (schéma ligne 109), est T1 donc N3 (ligne 1007), et [estimer_projet](../../../../departments/m03-estimation/src/m3_estimation/outils.py#L420) appelle l'orchestrateur et le registre durable. Les contrôles Python de capacité valident outil, arguments, mode et éventuelle approbation ; ils ne reçoivent pas l'affaire/les signaux de cette garde. Ils n'offrent donc pas un second contrôle du même invariant M10.

**Préconditions.** Le moteur et l'agent doivent être activés, le niveau de l'outil être N3+, et la session avoir un paquet prêt et frais pour A sans signal critique ouvert. Un appel du même tour vise B, dont le contexte est absent ou comporte des signaux. Les autres validations métier doivent accepter B. En mode `ombre`, l'appel crée encore une demande humaine plutôt que d'exécuter seul la mutation ; en `supervise` ou `autonome`, N3 peut s'exécuter directement. N4/N5 conservent les approbations selon le mode. Ce défaut ne supprime pas toutes les autres portes métier.

**Scénario statique.** Enregistrer `ready(affaireId=A, nbOuverts=0, atMs=maintenant)` pour une session ; invoquer l'outil N3 avec `contrat.lead_id=B`. Changer B ou ses signaux ne change aucun argument de `evaluateGuard`, donc ne peut changer son verdict. Ce peut être une erreur d'orchestration du modèle, sans intention malveillante.

**Impact.** P4 demande la mémoire avant la modification critique. Ici une lecture de A peut servir de preuve de contexte pour B. Le POSTFLIGHT [engine.ts](../../../../core/src/context-engine/opsys-contexte-engine.ts#L445) résout à nouveau l'affaire depuis le texte utilisateur/la session et dépose les résultats sous cette affaire à la ligne 474, sans lier cette cible aux arguments d'outil ; une attribution de candidats à A après une action sur B est également possible. Ces candidats ne deviennent pas automatiquement la vérité durable : ne pas confondre attribution erronée et consolidation définitive.

**Tests et correction.** `opsys-contexte-garde.test.ts:115` et `agent-tools.before-tool-call.opsys-contexte.test.ts:166` couvrent niveaux, signaux, fraîcheur et sessions, mais pas la divergence entre affaire du paquet et cible de l'outil. Le propriétaire doit définir une extraction déterministe de la cible par contrat d'outil, la comparer au contexte avant l'effet, refuser une cible absente/ambiguë pour les mutations concernées et conserver cette même cible pour le dépôt. Le contrôle final doit tenir compte des arguments après les politiques/hooks capables de les réécrire.

### C03 — Une configuration de contexte invalide autorise les actions gardées

**Preuve.** [opsys-contexte-config.ts](../../../../core/src/context-engine/opsys-contexte-config.ts#L202) classe notamment un bloc `niveaux` absent comme invalide ; JSON illisible et erreurs de lecture sont également `invalid` (ligne 229). Le moteur sélectionné affiche alors « configuration invalide » [engine.ts:330](../../../../core/src/context-engine/opsys-contexte-engine.ts#L330), mais [garde.ts:136](../../../../core/src/context-engine/opsys-contexte-garde.ts#L136) autorise tout résultat de configuration autre que `enabled`, donc aussi `invalid`.

**Ce choix est explicite.** `opsys-contexte-garde.test.ts:139` attend `block:false` pour une configuration impossible à croire, même avec quatre signaux ouverts ; ADR-0010:174 dit « inactif […] s'il est invalide ». Ce n'est donc pas une divergence accidentelle avec ce test/ADR. C'est un **écart de conception documenté** avec la règle racine fail-closed et P4, lorsque l'opérateur a sélectionné le moteur OPSYS pour protéger ses actions.

**Préconditions et impact.** Le slot du moteur reste `opsys`, mais son fragment actif est corrompu, incomplet, inaccessible ou issu d'une version sans `niveaux`. Le tour dit qu'il n'a pas son contexte ; la garde ne bloque plus un N3+. Les autres restrictions d'outil et approbations subsistent, avec la même distinction de modes que C02. Une configuration volontairement absente/désactivée est un cas différent et n'est pas qualifiée comme défaut ici.

**Correction.** Distinguer « désactivé intentionnellement » et « activé mais invalide » ; dans le second cas, conserver une portée de garde fiable ou refuser les outils OPSYS concernés. Le chemin d'exception de la garde sait déjà refuser les noms de forme OPSYS (lignes 185–188), mais le résultat `invalid` normal n'emprunte pas ce chemin. Ajouter un test où le moteur sélectionné, sa configuration invalide et l'appel N3 sont raccordés ensemble.

### C04 — Le démarrage est compté comme bonne santé pour réinitialiser les reprises

**Preuve.** [supervisor.ts:194](../../../../core/src/gateway/opsys-metier-supervisor.ts#L194) démarre la mesure avant le lancement. `becameReady` devient vrai à la première sonde réussie (ligne 269). À la fin, `ranMs` mesure toute la vie du processus depuis ce lancement (ligne 336). La boucle remet le compteur à zéro si `becameReady && ranMs >= stableRunMs` (ligne 348), alors que son commentaire exige une période réellement saine. `stableRunMs` vaut par défaut le plafond de backoff, 60 secondes ; le délai de préparation par défaut est de 120 secondes (`opsys-metier-config.ts:42`).

**Scénario non rejoué.** Un moteur prend 61 secondes à démarrer, répond une fois sain, puis plante aussitôt. Chaque exécution dépasse 60 secondes et a `becameReady=true` : chaque sortie réinitialise les reprises, puis repart au premier délai. Avec le budget par défaut de dix redémarrages, une répétition de ce scénario n'atteint jamais l'état `failed`. Le moteur peut être indisponible presque en permanence tout en ayant un budget apparemment renouvelé.

**Impact et limites.** Défaut de disponibilité/observabilité, pas une suppression de contrôle d'accès. Il demande un démarrage long mais encore autorisé, puis des crashes rapides après la première sonde. Un processus qui n'est jamais prêt est correctement borné par le délai et le budget ; cette voie est testée.

**Tests et correction.** `opsys-metier-supervisor.test.ts:314` couvre l'épuisement des reprises sans bonne santé ; le test ligne 346 couvre une reprise après un run supposé sain. Aucun n'isole un démarrage long suivi d'une très courte période saine. Enregistrer l'heure de première disponibilité, calculer la durée saine continue, puis tester avec l'horloge injectée un démarrage de plus de 60 secondes et une durée saine inférieure au seuil.

### C05 — Des documents de référence décrivent encore le modèle vendorisé retiré

**Preuve.** [INGREDIENTS.md:23](../../INGREDIENTS.md#L23) et sa ligne OpenClaw déclarent encore un vendor épinglé par image publique, « extension exclusivement par interfaces publiques », « aucun patch amont à ce jour » et des apps officielles iOS/Android/Wear OS intégrées. Ce texte renvoie au fichier `core/UPSTREAM.md`, retiré lors de l'import. La provenance actuelle dit fork dur modifié, apps natives retirées, app OPSYS Expo. Les 420 fichiers modifiés et les greffes directes contredisent matériellement le catalogue courant.

De même, [ADR-0010:185](../../../decisions/ADR-0010-memoire.md#L185) dit que la greffe `before_tool_call` n'est pas appliquée et que le core ne bloque pas encore ; [ARCHITECTURE.md:106](../../../architecture/ARCHITECTURE.md#L106) reprend ce manque. Le raccord existe pourtant à `agent-tools.before-tool-call.policy.ts:174`, est décrit correctement dans la provenance et a des tests de raccord.

**Impact.** Un développeur ou responsable de release peut choisir le mauvais artefact, croire disponibles des apps retirées, ou mal évaluer les portes humaines. Les décisions historiques archivées ne sont pas en cause ; ces phrases restent dans des documents présentés comme références actuelles. Gravité moyenne pour la préparation produit et la gouvernance, sans preuve d'un effet d'exécution autonome.

**Correction.** Réécrire la ligne core du catalogue autour d'ADR-0008 et de `PROVENANCE.md`, distinguer les capacités importées des applications réellement livrées et actualiser les sections de garde, avec les limites C02/C03. Les mentions internes `openclaw` et `OPENCLAW_*` sont un lot de migration explicitement différé ; leur seule présence n'est pas un défaut supplémentaire.

## Contrôles utiles observés et pistes écartées

**Contexte et MCP.** Le paquet est validé strictement : affaire demandée, couches, budget, compteurs de signaux, confidentialité et blocs additifs. Le core refuse plutôt que tronquer/corriger un paquet incohérent. Les appels MCP sont bornés, les diagnostics masqués et les transports réutilisent les configurations/jetons existants. Le dépôt utilise les résultats d'outils autorisés plutôt que du texte libre du modèle ; ses candidats restent séparés des faits consolidés. Le choix d'un moteur dans le core, plutôt qu'une extension, est expliqué par les limites du SDK client MCP actuel dans ADR-0010 ; il n'est pas présenté comme une absence de justification.

**Identité d'appareil.** Les métadonnées MCP sont ajoutées côté hôte via AsyncLocalStorage (`mcp-call-meta.ts`), sans prendre l'identité de la charge utilisateur. Les fichiers de rôles/appareils sont lus avec refus en l'absence de déclaration ; les propriétés propres et les portées sont vérifiées. Le chemin privé sélectionne le serveur MCP exact, applique les refus Gateway et recherche le nom d'outil brut sur ce seul serveur (`opsys-device-mcp-target.ts`). Le HTTP lie le deviceId au résultat d'authentification et refuse une identité différente dans le corps. Ces contrôles donnent des garanties réelles, indépendantes du défaut CLI.

La révocation des rôles/appareils pendant un `await` reste une piste de l'audit transversal mobile/Gateway, sans constat supplémentaire établi ici : l'authentification HTTP est revalidée avant l'effet, mais cette revalidation n'est pas automatiquement une relecture des rôles métier. Ne pas confondre cette interrogation avec une preuve de contournement.

**Supervision et migration.** Le superviseur limite sondes/reprises, masque son jeton dans les lignes, termine l'arbre de processus puis attend la sortie avant de remplacer le moteur. Les environnements CLI/moteur filtrent les secrets du core. La migration du profil OPSYS de `~/.openclaw-opsys` vers `~/.opsys/core` refuse les états conflictuels, utilise rename et rollback, puis préserve la compatibilité de l'ancien chemin via lien. Le core n'utilisant pas `OPSYS_HOME` est un contrat explicitement expliqué par R14/provenance ; ce n'est pas une perte de données démontrée. Les systèmes Windows/macOS demandent leurs preuves d'installateur, hors de cette seule CI Ubuntu core.

**Affaire inconnue, outil sans niveau et dépôts best-effort.** Les comportements permissifs sont explicités dans ADR-0010/provenance : une affaire inconnue n'ouvre pas à elle seule un signal critique, un outil absent du tableau `niveaux` n'est pas gardé, et un dépôt indisponible n'arrête pas le tour. Ce sont des limites produit à décider ; ils ne sont pas ajoutés comme bugs cachés. Les bornes de 4 secondes portent sur un appel, pas sur la somme des résolutions/dépôts d'un tour.

## Fork dur, mises à jour et licences

**Provenance positive et limites.** `core/PROVENANCE.md` identifie l'amont, le tag annoté `ce5bbdc244ee937246cc1700d1b224d020c3b599`, le commit source `eb377ac59e6c9fd6c7705028034812becf00271b`, la date, les suppressions et les greffes. Le script d'élagage lu (`outils/fork/elaguer_core.py`) conserve une liste fermée de 42 extensions, restaure les ressources nécessaires à la construction et vérifie la fermeture des dépendances de workspace. Il n'a pas été exécuté pour cet audit. Les suppressions de tests liés à l'historique OpenClaw et aux pages retirées sont motivées ; la CI du fork assure la construction actuelle. La provenance byte-for-byte avec une nouvelle copie du tag amont n'a pas été reconstituée ici : les identifiants amont restent des éléments déclarés et vérifiables, pas un nouveau contrôle cryptographique indépendant.

**Mise à jour : risque conditionnel, pas remplacement natif confirmé.** Les propriétaires hérités conservent `openclaw@latest`/les tags npm publics (`update-check-package-target.ts:77`), `github:openclaw/openclaw#main` (`update-global.ts:72`) et le clone `https://github.com/openclaw/openclaw.git` (`cli/update-cli/shared.ts:163`). La CLI `opsys update` existe par alias et le canal dev peut déclencher une conversion package vers Git. Cela ne réalise pas, en soi, le contrat « nos propres versions, sans synchronisation amont ».

Cependant le chemin natif documenté installe le dépôt OPSYS complet puis son sous-dossier `core/` ; le détecteur Git exige que la racine Git soit la racine du package. L'updater le traite donc comme package et `resolveGlobalManager` (`shared.ts:510`) refuse un dossier source sans gestionnaire global propriétaire, avant le clone/remplacement. La mise à jour officiellement documentée est de relancer `install/install.sh` sur le dépôt OPSYS (`INSTALLATION.md:287`), qui utilise son propre origin. Aucune substitution silencieuse par OpenClaw sur ce chemin supporté n'est démontrée. Avant de publier une distribution npm/global ou un core autonome Git, il faut bloquer/remplacer ces cibles publiques et tester installation existante, dry-run, canal dev et provenance du candidat. Ne pas qualifier ce risque conditionnel comme une exploitation actuelle sur l'installation native.

**Licences.** La licence MIT originale `core/LICENSE`, le copyright OpenClaw et les notices ont été conservés. `NOTICE` annonce le dérivé OPSYS et l'absence d'affiliation ; `THIRD_PARTY_NOTICES.md` couvre notamment les apports Pi et Octicons sous MIT. La licence MIT permet modification et redistribution commerciale sous conservation des avis ; l'attribution locale est cohérente avec ce besoin. Aucun ajout de dépendance externe n'est visible dans le diff post-import. Le workspace applique délai de publication strict, blocage de sous-dépendances exotiques et liste de scripts de build autorisés ; ses exceptions datées méritent un entretien avant la prochaine régénération.

Cette inspection **n'est pas un audit de licences/vulnérabilités des 1 687 entrées de lockfile** : pas de SBOM exhaustif, scan SCA distant ni vérification de chaque archive/native binary. La mention « licence vérifiée » du catalogue pour OpenClaw ne doit pas être étendue à toutes ses dépendances transitives. Aucun fichier manifestement dépourvu de licence n'est démontré dans les greffes lues ; cela ne donne pas un certificat de redistribution de toute la chaîne.

## Conditions de fermeture

Pour passer ces surfaces à un état vérifié prêt à livrer : établir la séparation opérateur/agent au point de mutation (C01), lier le contexte et le dépôt à la cible métier effective (C02), traiter une activation invalide comme indisponible (C03), mesurer la période saine du superviseur (C04), actualiser les références (C05), puis fournir les tests de régression raccordés en CI. Une preuve E2E avec le vrai core, le serveur Python et une instance jetable doit vérifier les effets et refus attendus ; aucun effet réel de paiement/publication/approbation n'est nécessaire pour ces tests.

Le rapport est complet pour son **périmètre ciblé** et ses preuves statiques/CI disponibles. L'exécution locale core et les reproductions TypeScript sont **BLOCKED par `core/AGENTS.md`, section Exécution** : « Le bac à sable de développement n'exécute pas le code du core […] La preuve vient de la CI ». Cette restriction a été respectée, avec CI d'arbre identique utilisée en remplacement. La lecture ne justifie ni « tout le core audité », ni « tous les scénarios passent », ni « conformité SaaS/Loi 25 établie ».
