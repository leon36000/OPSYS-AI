# Consolidation OPSYS-AI — plan d'exécution

**Objectif :** conserver le travail utile, corriger les invariants de l'audit et atteindre la
profondeur métier demandée en réutilisant des briques qualifiées.
**Architecture :** fork OPSYS-CORE existant, socle métier transactionnel et app Expo ; un propriétaire
par donnée/capacité, départements reliés par événements et mémoire autorisée. Agents spécialisés
configurables et limites fournisseur vérifiées avant appel.
**Stack actuelle :** TypeScript, Python, SQLite/PostgreSQL, MCP, Expo ; autres briques après essai.
**Spécification :** [directives Nathan](../produit/DIRECTIVES-NATHAN.md),
[périmètre complet](../produit/PERIMETRE-MODULES.md), ADR-0012. Le plan historique est [PLAN](PLAN.md).

## Contraintes communes

- Pas de reconstruction du core, CRM ou finance utile sans défaut/besoin démontré et plan de migration.
- Pas de nouveau backend `grs_api/`, deuxième vérité financière ni infrastructure Forge obligatoire.
- Pas de consensus de trois modèles ni de fournisseur extérieur imposé pour développer ou fusionner.
- Authentifier et revalider le principal, objet, args, droits, état et approval juste avant l'effet.
- L'argent, la paie finale, le fiscal officiel, le légal et les actions sensibles restent humains.
- Code déterministe pour chiffres/dates/quantités ; taux/obligations fiscaux sourcés par année/version.
- Credentials absents : export/brouillon explicite, pas faux résultat ni blocage des travaux internes.
- Core : vérification locale ciblée permise, dépendances verrouillées sans scripts tiers implicites
  (`core/AGENTS.md`) ; CI avant intégration. Pas de push/merge/deploy implicite.
- Chaque lot produit comportement, régression utile, interface, traces, docs et statut avec limites.

## État de départ et priorité

**Publication du 4 octobre :** la [PR de reprise #623](https://github.com/leon36000/OPSYS-AI/pull/623)
est ouverte en brouillon sur la base de Claude. Le [bilan de CI et ses preuves](../research/REPRISE-2026-10-04/CI-PUBLICATION.md)
confirme la construction complète du premier core publié et documente les corrections d'installation,
M3/M4/M5/M10 et E2E. Le mobile natif du commit `d2669fa` est désormais vert :
17 régressions des dépendances, 2 607 tests Jest et 118 suites passent; l'audit reste à
13 alertes modérées, sans alerte haute/critique. Le socle natif du commit `d943c5d`
passe 3 773 tests avec 17 skips explicitement conservés. Ces preuves portent sur
leurs commits respectifs, pas sur une tranche ultérieure. Aucune fusion ni promotion globale.
La [reprise M10 des imports internes](../grs/memory/M10-IMPORT-LOTS-REPRISE-2026-10-04.md)
consolide le parcours PostgreSQL/console; l'ingestion universelle et l'assimilation
sur corpus client restent à qualifier.

Base auditée : `2e56c0d5605dfe575bde9244f38924d5390f2674`, branche récente de Claude.
18 815 tests locaux passés et 78 sautés lors de l'audit ; core/mobile CI verts sur l'arbre consulté,
CI socle expirée au délai de 20 minutes et gates rouges au HEAD. Ces résultats sont **historiques**,
pas des exécutions du présent lot documentaire. 47 constats : 14 P1, 30 P2, 3 P3.
Le [registre d'audit](REGISTRE-AUDIT-2026-09-30.md) les conserve tous, avec niveau et origine.

Le travail de Claude constitue une base utile : vrai fork, contrats, cascades métier, approbations,
registre mémoire, données terrain et mobile. L'écart principal est entre preuve technique locale
et fiabilité métier complète ; la documentation et les cases cochées n'ont pas suivi tous les défauts.
Conserver cette base et corriger les frontières avant multiplication des agents et connecteurs.

## Suivi détaillé de l'exécution

Les quatre blocs de l'interface de suivi étaient des regroupements, jamais une réduction du
périmètre. Le suivi comporte désormais douze entrées, reliées aux lots techniques ci-dessous.
Le nombre d'entrées ne mesure ni la profondeur d'un département ni son degré de complétion.

| Entrée | Périmètre | Lot de référence | État actuel |
|---|---|---|---|
| 1 | Audit, historique Claude, directives et profondeur des dix modules | 0 | Livré localement ; limites d'audit conservées |
| 2 | Accès, finance, stock, rejeux, migrations, restauration | 1A–1C | Régressions locales et corrections réalisées ; frontières hôte et restauration VPS complète encore à qualifier |
| 3 | Raccord core–M10, origine, affaire cible, configuration | 1A–1B | Route interne et tickets transactionnels pour huit mutations M2/M3 vérifiés ; provenance N4 humaine intégrée avec 254 tests ciblés, autres cibles à compléter |
| 4 | Providers natifs, installation autonome et VPS | 1C | Configuration native et CLI réelle du fork vers Python testées ; installateurs avec Docker factice qualifiés, puis sandbox standard local C01 r4 exercé via les factories TS natives sur session synthétique ; C01 reste PARTIEL, image serveur complète, Gateway/tour LLM, SaaS multi-tenant et VPS non validés |
| 5 | Agents configurables et admission des coûts/tokens | 2 | Intégration MCP root sur 7 chemins, test HTTP portable distinct sur 1 chemin; Core r3 130/130 et 1 135 chemins de l’ensemble surveillé stables. Un parcours Core→MCP HTTP Python exerce un ticket de grant CFO à usage unique avec fixture synthétique. Probe séparée sur PostgreSQL 17.11 observe revalidation sur la même connexion et refuse l’appel devenu tardif après révision 2→3. Pas de ticket CFO PostgreSQL ni de fournisseur réel; cette couverture ciblée ne rend pas C02 universel |
| 6 | Mémoire développement et métier M10 | 3 | Registres, preflight/postflight, API/CLI et consolidation locale ; sélection par chemins structurés, liens de remplacement réellement stockés et fraîcheur liée au hash du fichier. Qualification active : 974 tests dans une commande (959 M10 + 11 console-jobs + 4 cron), sans échec/erreur/skip ; correction de mise en forme ultérieure avec AST identique et Ruff global vert. L'évaluation synthétique historique garde huit scénarios pris en charge, deux absents et un rappel 30/32 ; collecte générale, déploiement et évaluation à l'échelle à compléter |
| 7 | Réception omnicanale et voix progressive M1 | 4 | Import manuel WAV vers M1/M2; consentements, rappel et révocation STT testés. [Port privé d’appel manqué](../grs/reception/M1-APPELS-HOTE-2026-10-03.md) qualifié le 3 octobre : 205 cas, provenance réservée, rejeu et rollback. Raccord Core intégré localement : 164 tests natifs, HMAC Twilio local sur clé fictive. Deux scénarios natifs distincts qualifient le vrai transport Core→Python HTTP→SQLite (import/rejeu/refus/retrait). Build/exports/profilage, recovery Gateway, téléphonie réelle et qualité québécoise non qualifiés |
| 8 | Marketing et croissance M7 | 5 | R19 : M7.4a intégré sur sept chemins à 18:01:32 UTC; lecture privée des observations déclarées par admin/owner actuel, bornée et sans saisie humaine prouvée. Campagne ROOT close à 18:03:51 UTC : 1 436 cas (1 066 M7 + 279 console + 82 socle + 9 E2E), 0 échec/erreur/skip; 59 Growth inclus, deux cas PostgreSQL désélectionnés, 1 070 chemins sélectionnés stables. Marque, calendrier/export et performance M2/M3/M5 réutilisés. Au jalon R18, médias privés M7.3a intégrés sur 11 chemins : import JPEG/PNG préparé humainement, aperçu CAS vérifié, revue propriétaire et remise manuelle liée au texte et au créneau approuvés. Campagne root 1 377 cas (1 038 M7 + 248 console + 82 socle sélectionnés + 9 E2E MCP SQLite), 0 échec/erreur/skip, 128,406 s, 1 066 chemins sélectionnés stables; deux cas PostgreSQL désélectionnés. Les 7 tests de pliage et 19 tests console média sont inclus. Pas de publication, transformation automatique, mobile dédié ou concurrence médias PG qualifiée; attribution exhaustive/ROI/connecteurs à compléter |
| 9 | FinanceCore/CFO M5, paie et fiscalité préparatoires | 6 | M5.8a reste intégré sur 9 chemins. Au jalon R17, M5.3a moteur et console sont intégrés (3 + 6 chemins); campagne root : 2 444 cas (2 182 M5, incluant le moteur 24, et 262 socle sélectionnés, incluant la console 19), sans échec/erreur/skip, 234,923 s, 1 140 chemins stables. Les cas PostgreSQL sont désélectionnés par `-k not postgresql`; aucune concurrence bancaire PG n’est qualifiée. Allowlist `configuration.banque_csv.comptes_internes` absente : les routes bloquent tant que non déclarée. Aucun fournisseur, paiement ou approbation finale. Les 9 PDF de paie restent `NON_QUALIFIEE`; aucun barème/licence n’est validé. Le brut régulier, les échéanciers clients et le rapprochement bancaire sont des fonctions préparatoires distinctes; pas de retenues, cotisations, net ou déclaration officielle. CFO complet et production non qualifiés |
| 10 | Parcours M2/M3/M4/M6/M8/M9 et échanges | 7 | M2 complet après APR 1 795 tests ; M3 complet avant APR 2 165 réussites/un skip, puis ordinaire après APR 2 133 réussites/même skip ; M4/M6/M8/M9 verts au jalon antérieur, sous-matrices et scénarios complets à poursuivre |
| 11 | Dashboard, mobile hors ligne, profils, approbations | 1C, 2, 7 | Correctifs de capture/file/identité et écrans agents testés ; réception/marketing/finance/mémoire dans console, essais appareil réel à effectuer |
| 12 | Validation intégrée, documentation et matrice réelle | Tous | R19 M7.4a : 1 436 réussites dans sa commande distincte, 1 070 chemins sélectionnés stables; Ruff sept fichiers et catalogue 10/207/116 passent séparément. Documentation synchronisée; comptes sans addition à R18. 47 constats préservés : 42 corrections locales et cinq partiels. M5.3a R17 : 2 444 cas sur son arbre daté. M7.3a R18 : 1 377 cas dans une commande distincte, 1 066 chemins sélectionnés stables, deux cas PostgreSQL désélectionnés. Ces campagnes ne s’additionnent pas. Ruff M7 ciblé (10 fichiers) et vérificateur catalogue passent séparément; 10 départements, 207 outils, 116 déclarés aux appareils. Rouges historiques conservés. Aucun nouveau socle global vert, CI distante, qualification bancaire/médias PG ou VPS revendiqués |

**R19 M7.4a — lecture déclarée non vérifiée.** Le lecteur et les routes privées intégrés par ROOT R6 réutilisent les maillons `growth`; la personne active doit avoir le rôle actuel `nathan_owner` ou `admin`, vérifié avant lecture et à nouveau dans une transaction fraîche avant réponse. Les observations sont validées avant filtrage : une corruption hors période refuse aussi la lecture. Le budget porte sur le registre complet : **1 000 maillons, 32 Ki caractères par maillon, 1 Mi caractères au total**, pas des octets. Filtre fermé d’au plus **366 jours inclusifs**, observation entièrement comprise; pagination fraîche sans instantané multipages. Aucune saisie humaine n’est prouvée, auteur/provenance et source externe restent inconnus ou non vérifiés; aucune croissance, causalité, ROI ou publication n’est produite. Les plans historiques ne sont exclus qu’après contrôle de leur forme top-level, sans validation sémantique de leur contenu. La campagne ROOT est close à 18:03:51 UTC : 1 436 réussites, 137,133 s JUnit, sans échec/erreur/skip; les 59 cas Growth sont inclus. Les 1 070 chemins sélectionnés restent stables, deux cas PostgreSQL sont désélectionnés. La documentation R19 est synchronisée avec ces preuves, sans addition aux comptes R18. Voir le [document M7.4a](../../departments/m07-marketing/docs/M7-4A-GROWTH-LECTURE.md) et la [matrice M7](../grs/marketing/M7-MATRICE-CAPACITES-2026-09-30.md).

Preuves ROOT closes : [résultat](../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-resultat-json-39d3b4870b.gz) · [JUnit](../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-xml-c8db58b5f3.gz) · [journal](../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-log-8c7e9f181c.gz) · [promotion R6](../research/R20-2026-10-01/preuves/r19-m74a-integration-root-r6--resultat-json-1909dc8172.gz) · [Ruff](../research/R20-2026-10-01/preuves/r19-preuves--m74a-ruff-root-r1-2026-10-01-resultat-json-3fb7557c96.gz) · [catalogue](../research/R20-2026-10-01/preuves/r19-preuves--m74a-verifier-root-r1-2026-10-01-resultat-json-032e699528.gz) · [lecture indépendante](../research/R20-2026-10-01/preuves/r19-m74a-cloture-independante-r1--rapport-json-190e148f67.gz). Ces preuves sont conservées dans les archives R20, sans modifier le R19 scellé du 30 septembre.

**Qualification M7.3a R18 (1er octobre, 16:54 UTC).** La campagne intégrée root du 1er octobre 2026, exécutée de **16:52:48 à 16:54:58 UTC**, passe **1 377 cas**, sans échec, erreur ni skip, en **128,406 s JUnit** : **1 038 M7**, **248 console**, **82 fichiers/stockage/idempotence** et **9 E2E chantier par MCP sur SQLite**. Les sept cas du pliage média sont inclus dans M7 et les dix-neuf cas de console média dans la console; aucun de ces sous-comptes ne s’ajoute au total. Deux cas PostgreSQL ont été désélectionnés par `-k not postgresql`, ce ne sont pas des skips. L’ensemble surveillé de **1 066 chemins sources sélectionnés** est identique avant/après; il ne constitue pas une fermeture de tout le dépôt. Les dix-neuf cas média comprennent des tests HTTP, un test direct du parseur ASGI et un oracle de garde substituée; ils ne sont pas dix-neuf parcours complets de bout en bout. La tranche demeure **PARTIELLE** : aucune publication ou connexion fournisseur, transformation automatique des images, analyse des pixels, suppression EXIF, surface mobile M7 dédiée, essai navigateur réel ou qualification VPS. Les attestations de préparation et de revue restent humaines. Les nouvelles écritures médias refusent PostgreSQL; aucune concurrence PostgreSQL pour ce registre n’est qualifiée. Le catalogue reste à **10 départements, 207 outils et 116 outils déclarés aux appareils**; aucun outil MCP n’a été ajouté. Voir le [point R18 du bilan](BILAN-RESTRUCTURATION-2026-09-30.md), la [matrice M7](../grs/marketing/M7-MATRICE-CAPACITES-2026-09-30.md) et les preuves : [résultat](../research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-resultat-json-aab3d9c2e7.gz) · [JUnit](../research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-xml-d4c76cecab.gz) · [journal](../research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-log-1c43560d7a.gz) · [lecture indépendante](../research/R20-2026-10-01/preuves/r18-m73a-cloture-independante-root-r1--verification-json-061d6a4c0f.gz) · [promotion R4](../research/R20-2026-10-01/preuves/r18-m73a-integration-root-r4--resultat-json-f24b78b5dc.gz) · [Ruff](../research/R20-2026-10-01/preuves/r18-preuves--m73a-ruff-root-r1-2026-10-01-resultat-json-8bb466cbf1.gz) · [catalogue](../research/R20-2026-10-01/preuves/r18-preuves--m73a-verifier-root-r1-2026-10-01-resultat-json-5e77c4ab23.gz).

**Qualification intégrée root r1 (1er octobre).** La commande M1/M4/M5/runtime passe 6 723/6 723
cas en 400,435 s : 1 578 M1 + 2 865 M4 + 2 100 M5 + 180 socle accès/runtime, sans échec, erreur
ou skip; 1 080 chemins identiques avant/après ([JUnit](../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01.xml.gz),
[résultat](../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01-resultat.json.gz)). Elle est distincte du socle global root r2, qui a fini
en INTERNALERROR ENOSPC (2 255 tests attribués/2 256 effectifs; 135F/154E/84S) et n'est pas vert.
Le [lecteur Core runtime r2](../research/R20-2026-10-01/preuves/runtime-core-lecteur-root-r2-2026-10-01.json.gz)
constate 73/73 tests sur huit fichiers et 10 081 fichiers stables autour de Vitest; le typecheck natif
précède la capture initiale ([chronologie](../research/R20-2026-10-01/preuves/agent-profile-active-check-r1-chronologie-r2.md.gz)). La commande root r1 M7/CMO/bootstrap passe
1 261/1 261 tests en 73,076 s avec 1 094 chemins stables, couvrant M7, consoles CMO/marque/calendrier/
performance/paie, bootstrap/instance/profils/rôles/canaux et un E2E appareil M4; ce n'est pas le socle
complet ([JUnit](../research/R20-2026-10-01/preuves/m7-bootstrap-forme-integres-root-r1-2026-10-01.xml.gz),
[résultat](../research/R20-2026-10-01/preuves/m7-bootstrap-forme-integres-root-r1-2026-10-01-resultat.json.gz)).
Les intégrations touchent un fichier M4 test-only, six fichiers CMO et sept chemins Compose
([M4](../research/R20-2026-10-01/preuves/m4-forme-basetemp-integration-root-r1-2026-10-01-resultat.json.gz),
[CMO](../research/R20-2026-10-01/preuves/m7-cmo-integration-root-r1-2026-10-01-resultat.json.gz),
[Compose](../research/R20-2026-10-01/preuves/compose-bootstrap-integration-root-r1-2026-10-01-resultat.json.gz)).
Les fixtures temporaires ont été supprimées sans archive restaurable. Le socle root r3 initial compte
2 478 cas (2 363P/1F/30E/84S), 1 223,835 s; ses 31 cas rouges PostgreSQL mentionnent ENOSPC.
La reprise exacte des mêmes 31 nodeids/sources passe 31/31. Le lecteur valide l'union de 2 478 cas
uniques (2 394P/84S), sans rouge résiduel, mais cela ne constitue pas une commande globale unique verte.
Les skips et la fermeture de 1 094 chemins restent limités. Ces campagnes précèdent la modification
ultérieure de pyproject.toml; aucune validation globale n'est revendiquée sur l'arbre postérieur.
Après le changement de configuration, le bootstrap ciblé sans override passe 29/29 en 9,027 s, sans échec/erreur/skip, avec 1 094 chemins stables ([résultat](../research/R20-2026-10-01/preuves/pytest-retention-bootstrap-root-r1-2026-10-01-resultat.json.gz)). Cette commande ciblée ne qualifie pas le socle global. Voir [résultat initial](../research/R20-2026-10-01/preuves/socle-integre-root-r3-2026-10-01-resultat.json.gz),
[reprise](../research/R20-2026-10-01/preuves/socle-reprise-postgresql-root-r1-2026-10-01-resultat.json.gz),
[union](../research/R20-2026-10-01/preuves/socle-union-root-r1-2026-10-01.json.gz) et [Ruff](../research/R20-2026-10-01/preuves/ruff-socle-departements-root-r1-2026-10-01-resultat.json.gz).

Nathan a confirmé que PC1/LiteLLM n'est pas accessible depuis ce cloud et demandé l'utilisation
des sous-agents GPT-6 Luna disponibles. Les tâches sont attribuées par propriétaire de fichiers,
avec régression avant correction, résultats persistés et contrôle d'intégration par le chef de
projet. Aucun besoin de disponibilité d'un modèle extérieur ne suspend ce programme.

## Points de vérification prioritaires

1. Client/affaire A et B dans un même run : jamais mélange de capture, d'autorisation ou de mémoire.
2. Désactivation/retrait de rôle après connexion : effet refusé même avec cookie/CSRF anciens.
3. Même objet/opération via nouvelle clé de transport : pas de double stock ni facture réécrite.
4. Crash/échec entre poses/migrations : instance cohérente, révision réelle vérifiée avant bascule.
5. Deux appels LLM concurrents/retry/compaction : admission budget et facturation sans double débit.

## Lot 0 — livré dans cette branche : direction, règles, sources

- [x] Directive durable et ADR-0012 ; supprimer l'obligation de revue extérieure de développement.
- [x] Règles AGENTS/CLAUDE/digest/boucle proportionnées ; validations humaines métier conservées.
- [x] Périmètre M1.1–20, M5.1–20, M7.1–15, M10 complet et six autres départements conservés.
- [x] Recherches primaires GitHub/GitLab par domaine, licences/commits/risques et sélection R16.
- [x] Documents d'entrée, architecture, tokens et catalogue corrigés ; audits précédents datés.
- [x] Vérification du diff, liens locaux, JSON et couverture du périmètre ; résultat dans
      [VERIFICATION-RESTRUCTURATION](../research/R16-2026-09-30/VERIFICATION-RESTRUCTURATION.json).

La recherche ne livre aucun nouveau connecteur réel. Les dépendances candidates ne sont pas installées.
Le résultat est un lot de gouvernance/documentation exploitable, pas M1/M5/M7/M10 terminés.
Le [bilan du lot](BILAN-RESTRUCTURATION-2026-09-30.md) rassemble changements, preuves et limites.

## Lot 1 — frontières et invariants, avant exposition élargie

### 1A — Autorité vivante et affaire cible

Fichiers : `src/opsys/console/application.py`, `console/securite.py`, `tableau_de_bord.py`,
`identite.py`, `capacites.py`, `contexte.py`, core `opsys-contexte-*.ts`.
Contrat : principal résolu par transport authentifié ; affaire des arguments reliée à la session
et au contexte ; config active invalide refusée. Un champ texte `agent`/`--par` ne vaut pas identité.

- [x] DON-01 : tests console employé, session ouverte puis désactivation et retrait de rôle ;
      refus des modes/modeles/budgets administratifs et projection privée, sans mutation en base.
- [ ] C02/C03 : tests core de contexte A/tool B et fragment actif corrompu ; N3+ refusé, audit
      explicite. Mode volontairement désactivé distingué d'un échec d'activation.
- [ ] C01 : séparer CLI opérateur et environnement d'exécution agent par une vraie frontière de
      processus/droits ; test sans `OPENCLAW_SHELL`, refus même si le marqueur est retiré. Pas de
      « correction » par une autre variable effaçable. Faille conditionnée à l'accès hôte documentée.

Jalon C01 local **PARTIEL** acquis : image sandbox standard construite, factories TS natives
`resolveSandboxContext` puis `createExecTool(...).execute(...)` exerçant bash sous configuration
synthétique et garde OPSYS. Le [résultat r4](../research/R20-2026-10-01/preuves/c01-os-sandbox-run-2ec9a897-a635-4302-aa31-301822bf1766.json.gz)
et le [lecteur root](../research/R20-2026-10-01/preuves/c01-os-sandbox-lecteur-root-r1-2026-10-01.json.gz)
qualifient UID/GID 1000, root RO, réseau `none`, NNP=1, seccomp=2, capabilities effectives nulles;
workspace privé RW et skills RO sont deux montages Core, sans bind supplémentaire configuré
ni montage du workspace hôte choisi. Le marqueur hôte choisi est absent et les noms `OPSYS_*`
fictifs sont retirés explicitement; aucun retrait automatique universel n'est revendiqué.
Ce jalon ne coche pas le critère global : image serveur complète, Gateway/tour LLM, SaaS
multi-tenant et VPS restent non prouvés. [R20 r9](../research/R20-2026-10-01/README.md) garde r1–r3
rouges : r1 a créé/inspecté un conteneur avant l'erreur de schéma au nettoyage, contrairement au
récit « avant Docker »; script r2 exact absent, fichier de base r1 sans association d'exécution
prouvée. Seul le script r4 est lié à la preuve positive par son hash et le lecteur indépendant.

Preuves : suites d'autorisation Python ciblées ; CI core du diff applicable. Les outils N0 autorisés
et décisions humaines signées continuent à fonctionner ; captures A/B ne peuvent se mélanger.

### 1B — Finance, matériel, mémoire

Fichiers : M5 `facturation.py`/`devis_recus.py`, M6 `outils.py`/`materiel.py`, M10
`outils.py`/`confidentialite.py`/`consolidation.py`, socle `memoire/store.py`/`jetons.py`.

- [x] DEP-001 : test facture envoyée F pour devis D1, nouvel événement D2 utilisant F → conflit
      explicite, facture et AR inchangés. Un même événement identique reste idempotent.
- [x] DEP-003 : ancien outil de consommation M6 contrôlé ou retiré avec migration ; WCT inconnu,
      intervention divergente et replay par autre clé refusés, stock inchangé au second passage.
- [x] DEP-002 : identité destinataire M10 dérivée du principal serveur ; nomination d'un autre
      agent ne révèle aucun `CLIENT_PRIVATE`. Tester tous les adaptateurs exposés.
- [x] DON-05/06, DEP-006 : artefact inter-département refusé, RAG ne reclasse ni ne retire rétention
      par hash seul, écriture tardive d'une période déjà consolidée reprise sans perte.
- [x] DEP-014 : contexte Decimal reproductible pour le comportement audité, couvert par sa
      régression locale ; aucun simple test de forme présenté comme preuve métier.
- [ ] Poursuivre les sous-matrices de validation de chiffres/dates/temps de chaque capacité.

Chaque régression compare aussi les états persistés avant/après ; les refus ne doivent pas modifier
finance, stock, consentement ou classification. Les IDs de constat ne sont fermés qu'avec cette preuve.

### 1C — Installation, restauration et mobile

Fichiers : `src/opsys/exportation.py`, migrations/stockage, `deploy/backup.sh`, `restore.sh`,
`Dockerfile`, scripts `install/`, mobile `src/m4/`, capture terrain, identité et file sortante.

- [x] DON-02/03 : revision SQLite ≠ manifeste et panne pendant deuxième pose/migration → refus
      avant bascule ou rollback cohérent base+config ; ancienne instance encore lisible.
- [x] INFRA-R01 / INFRA-R03 : noms des volumes cohérents, volume absent refusé, archive réellement restaurée,
      image sans secrets/backups ; restauration démontrée sur instance jetable.
- [x] INFRA-R02 : désinstallation protège les alias physiques, chemins partagés et données ; aucune
      action destructive d'essai sur une vraie instance.
- [x] MOB-01/02/09 : capture A conservée A après navigation B, WCT canon persiste après ack, réponse
      incomplète n'acquitte pas la commande ; redémarrage/appareils/compte changés exercés.
- [x] ECO-001 : le générateur et les deux installateurs utilisent les providers natifs par défaut,
      avec références de secrets et option LiteLLM explicite. Configuration cloud/local, absence
      de clés, ancienne configuration et option LiteLLM couvertes par tests locaux; les 63 tests
      d’installation passent avec vraie CLI Python et core fictif. La CLI du fork compilé appelle
      aussi réellement Python (`verifier`). Aucun appel à un fournisseur réel ni installation
      sur VPS neuf n’est prouvé par ces tests.
- [x] C04 : compteur retry indépendant d'un démarrage lent, régression à horloge simulée.
- [ ] CI distante : configurations et cibles corrigées localement; exécution distante de cette
      branche non effectuée, aucune suite ignorée pour obtenir un vert.

Les 47 constats sont conservés dans le registre : au jalon R17, 42 corrections locales prouvées
et 5 constats partiels. Les coches ci-dessus renvoient à ces comportements précis et à leurs
[preuves](../research/R17-2026-09-30/README.md), sans clôture des lots ni validation de production.

## Lot 2 — agents configurables et budget fournisseur

Fichiers existants : `departements.py`, `openclaw.py`, `modeles.py`, `jetons.py`, `console/`,
`stockage/schema.py`, core `agents/embedded-agent-runner/run/attempt-llm-boundary.ts`, sous-agents
et compaction. Modules implémentés : `src/opsys/agents.py`, `src/opsys/admission_agents.py`,
tests `test_agents_configurables.py` et `test_admission_agents.py` ; migrations `0010` à `0012`.
Le raccord réel passe par `core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts`
et `run/attempt-prompt-submit.ts`. Les profils historiques, appels de plugins et compaction ne
doivent pas être déclarés couverts avant une preuve de leur chemin fournisseur.

Le premier jalon est implémenté : profils révisés et administrés par une personne active dans
`agents.py`, réservations `reserver`/`admettre_cycle_runtime`, conciliation `concilier` et libération
`liberer` dans `admission_agents.py`, migrations `0010`–`0012` et export Core depuis la même source.
Les classes de tests profils (13 cas) et admission (18 cas) passent individuellement dans le socle
CFO rouge; cela ne rend pas cette suite complète verte. Les [preuves R17](../research/R17-2026-09-30/README.md)
documentent le premier raccord avec fournisseur contrôlé, sans appel LLM de production.

- [ ] Consolider la sous-spécification budget/principal et les liens de types Python/TS au-delà
      des migrations et contrôles déjà livrés.
- [ ] Compléter le parcours composé deux rôles/modèles/budgets distincts; profils multiples,
      outils limités, révisions et refus d'acteurs non autorisés ont déjà des preuves ciblées.
- [ ] Étendre l'admission à tous les sous-agents/retry/plugins/legacy et coûts inconnus.
      Le raccord avant `StreamFn` couvre les profils configurables; leur compaction est refusée
      tant que son coût n'est pas comptabilisé.
- [ ] Compléter crash/reprise et changements de droits/configuration sur tous les chemins
      fournisseur; réservation concurrente et rejeu sont déjà exercés localement.
- [ ] Compléter la vue coût/réservation/refus/escalade autour de la console de profils existante
      et mesurer les appels au repos, plutôt que les déduire de la configuration.

Banc avant ajout : native/Hermes composant, puis lossless-claw adapté au slot unique si gain ;
Bifrost/LiteLLM uniquement si un besoin mesuré reste insatisfait. Aucune économie chiffrée promise.

## Lot 3 — M10 développement et mémoire d'entreprise

Réutiliser journal, decisions, candidats, contexte et consolidation M10. Nouveau domaine développement
avec permissions et collecte configurable : Git/diff/symboles/routes, prompts/plans, décisions,
tests/CI/erreurs et snapshots de preuve ; résolveur source avec rétention connue.

- [ ] Modèle d'entités/relations temporelles + lineage/révision ; recherche SQL/FTS/pgvector selon backend.
- [x] Registres locaux prompt/plan/postflight versionnés, liens et références de fichiers/tests/rapports
      expurgés; leurs captures sont explicites, pas une collecte automatique de tous les outils.
- [x] Preflight humain tâche/module/fichiers et postflight structuré, API/CLI et audit des liens/sources.
- [x] Job développement avec grant révocable, reprise/late arrivals et rapport durable avec modèle de soi
      limité aux sources; cron Core réel sur SQLite même hôte, preuves [R18](../research/R18-2026-09-30/README.md).
- [ ] Collecte automatique de tous les prompts/diffs/tests, injection généralisée aux agents,
      consolidation à grande échelle et nuits récurrentes de production.
- [x] Premier jalon CLI/API/console du domaine développement et des jobs, sur les instantanés R18/R19.
- [x] Évaluation synthétique ciblée : huit scénarios pris en charge et deux absents; E05 garde
      précision 30/30, rappel 30/32 et cible 0/1. Ce résultat historique n'est pas un score général.
- [x] Sélection développement bornée : ancres de chemins structurés, lignage de remplacement stocké,
      distinction cycle/convergence et fraîcheur par chemin/hash. Les limites de 30 entrées, 30 liens
      et 1 000 visites exposent les omissions et frontières; elles ne bornent pas toute la lecture du
      journal. Les 974 tests intégrés sont une preuve locale distincte de l'évaluation E05 historique.
- [ ] Parcours mémoire mobiles/généralisés, évaluation à l'échelle et accès inter-domaines/inter-clients.
- [ ] E2E des cinq rappels de l'ancien prompt + accès dev→finance/client A→B refusés.

SQLite local reste possible ; PostgreSQL/FTS/pgvector et relations sont un palier autonome, sans
Qdrant/Cognee/Neo4j obligatoires. Hindsight/Graphiti/Cognee sont des bancs optionnels après mesure.
Voir [recherche M10](../research/R16-2026-09-30/recherche-m10.md) pour contraintes réelles de backend/licence.

## Lot 4 — M1 omnicanal puis vocal progressif

- [ ] Réutiliser transports existants core/SMS/email, un intake idempotent persistant M1→M2 ;
      appels manqués/voicemail/tasks, plainte/transfert, statut financier avec identité, disponibilité M4.
- [ ] Intégrer **un** runtime Pipecat ou LiveKit en mode test, STT/TTS CPU/remote local évalué ;
      barge-in, silence/erreurs, consentement, transcription/CRM/M10 et latence.
- [ ] Dashboard et quatre profils mobiles ; inbox/unanswered/digest et qualité source→M7/M8.
- [ ] E2E soumission, email, missed-call, plainte, facture et sandbox ; fallback manuel sans credential.
- [ ] Production hors heures puis live selon preuve et autorisation des canaux, jamais par simulation.

Pas de Google Business Messages retiré. Pipecat BSD-2/LiveKit Apache-2 ne rendent pas leurs modèles,
TTS ou toutes dépendances permissives. Voir [M1](../research/R16-2026-09-30/recherche-m1.md).

## Lot 5 — M7 CMO réel, contenu puis mesure

- [x] Usine existante chantier→brief→contenu→contrôles→approbation→export, withdrawal/permissions
      et séparation consentement/client/job ; corriger DEP-005 avant enrichissement.
- [ ] Calendrier/social/offline, bibliothèque, brand book ; Postiz comme service optionnel ou
      adapters officiels, scopes réels, statut et export manuel par plateforme.
- [ ] Réputation : demande neutre non sélectionnée sur satisfaction, réponses approuvées,
      alertes négatives et preuve de droit d'usage du témoignage.
- [ ] Analytics Matomo/SerpBear/Search Console puis attribution CRM→M5 marge ; simuler Ads,
      aucune dépense/write sans approval ; données absentes visibles.
- [x] Première performance campagne canonique M2/M3/M5 dans la console, cohortes UTC, exclusions
      et couverture explicites; dépenses et ROI inconnus, sans seconde vérité financière.
- [x] M7.4a : code de consultation privée des observations déclarées intégré par ROOT R6, bornes et refus; campagne ROOT de 1 436 cas close. Documentation R19 synchronisée; aucune saisie humaine ni vérification externe prouvée.
- [ ] Growth et CMO 30/60/90 jours fondés sur sources, concurrence autorisée, SEO local, dashboard/mobile.
- [ ] E2E chantier Repentigny multi-plateformes + permission/rétractation/rejeu/mesure et rapport.

Voir [M7](../research/R16-2026-09-30/recherche-m7.md). Marketing complet, pas SEO/PPC seulement.

## Lot 6 — M5 opérations puis CFO complet

- [ ] Grand livre/plan comptable/transactions : essai Python Accounting dans session OPSYS, Ledger
      oracle possible ; pas ERP parallèle. Cycle facture/AR/AP/OCR et banque/rapprochement fiables.
- [ ] CPA pack, tax period et calendrier officiel ; Stripe signé/idempotent, QBO OAuth/read/dry-run,
      CSV fallback, conflits explicites ; credentials manquants ne bloquent pas les calculs internes.
- [ ] Paie Québec/Canada : tables officielles Jan/Jul et RQ chargées avec version/source, calcul
      de brouillon comparé à jeux CPA, DAS/T4/RL-1 préparatoires, dépôt/transmission bloqués.
- [ ] Étendre au-delà de la projection capital M5.10.a limitée aux flux explicitement saisis : réserves/cash libre,
      contrats/cédule→13 semaines/6/12/24 mois, scénarios et stress.
- [ ] Camion/équipement/bâtisse, emprunt/cash/location/investissement, DSCR/ROI et risques,
      sources/hypothèses et questions professionnelles ; CFO Decision Report 25 rubriques.
- [ ] RAG fiscal séparé des données privées, sources versionnées, gold set extraction/classification.
- [ ] Dashboard CFO/mobile/M10 et tous E2E M5.1–20 ; official actions toujours humainement validées.

**Jalon ACTIF M4/M5 — sources horaires intégrées.** M4 conserve les heures régulières approuvées
par un humain N4, leurs références et le contrôle de la validation précédente attendue (CAS).
M5 conserve le contrat salarial individuel privé en CAD, déclaré avec source/date humaines et
contrôle de révision/tête attendues; le document salarial n'est pas authentifié par cette déclaration.
La commande combinée root r3 passe **4 962 cas = 2 854 M4 + 2 074 M5 + 34 socle CFO**,
0 échec/erreur/skip, en 294,638 s JUnit, avec **1 033 chemins sélectionnés stables** avant/après.
Le [JUnit](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r3-2026-10-01.xml.gz),
le [résultat](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r3-2026-10-01-resultat.json.gz),
la [réconciliation](../research/R20-2026-10-01/preuves/m54-m4-m5-reconciliation-root-r1-2026-10-01.json.gz)
et la [ventilation](../research/R20-2026-10-01/preuves/m54-m4-m5-ventilation-root-r1-2026-10-01.json.gz)
figurent dans [R20 r10](../research/R20-2026-10-01/README.md). Les cinq écarts de catalogue/ordre
du [rouge r2](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r2-2026-10-01.xml.gz)
sont corrigés, assertions fermées et permissions conservées; les mêmes 4 962 identifiants passent.
L'[erreur de collecte root r1](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r1-2026-10-01-resultat.json.gz)
est conservée séparément, sans échec métier. Le pont M4→M5, le brouillon brut et sa page UI
sont historiques. Le run intégré root r1 décrit ci-dessus confirme le raccord actif du brut
préparatoire, sans paie complète ni complétion globale M4/M5. Ce nouveau run garde son propre
compte; il ne s'ajoute pas aux suites antérieures.

Voir [M5](../research/R16-2026-09-30/recherche-m5.md). NumPy Financial actuel exige Python 3.13 :
pas de hausse implicite du minimum OPSYS 3.11. Aucun conseil officiel créé par fine-tuning.

## Lot 7 — profondeur M2/M3/M4/M6/M8/M9 et intégration finale

Chaque département reprend son périmètre dans la définition et ajoute un sous-plan de parcours
manquants, avec code existant et briques qualifiées. OR-Tools pour contraintes cédule, InvenTree
comme source de patrons inventaire, DuckDB pour analyse et SimPy pour scénarios sont candidates,
sans deuxième vérité transactionnelle. Les décisions globales M9 utilisent les services CFO/CMO.

- [ ] De la demande M1 au chantier, stock, facture, paiement, contenu, metrics et mémoire, faire
      traverser les événements réels et les états ; nouveaux modules ne réécrivent pas le CRM/compta.
- [ ] Reprise hors ligne/redémarrage, identité et changement permissions, isolation deux clients,
      absence credentials et outils échoués ; coûts/latence et traces de bout en bout.
- [ ] Installation VPS neuve, migration ancienne instance, backup/restauration cohérente,
      rollback, mise à jour OPSYS et secrets ; licence/provenance de chaque ingrédient livré.
- [ ] Matrice finale par capacité : critère, fichier/API/UI, test et démonstration, statut et limite.

## Règle de clôture

Cocher avec une preuve identifiant la révision ou les sources gelées et l'environnement.
Une correction locale non commitée peut être vérifiée; aucun commit ou déploiement n'est exigé
pour rendre cette correction concrète. Les statuts des anciennes tranches restent historiques.
Une capacité en mock/export n'est pas une publication ou un connecteur production. Une licence
vérifiée et une recherche approfondie ne prouvent pas une intégration. Le lot 0 se clôture localement
après vérification ; les lots 1–7 ont des tranches livrées et un périmètre restant explicite,
avec contrôles proportionnés et sans vote de modèles.

## Mise à jour R13 — contrôle root clos au 1er octobre, 10:14 UTC

Les changements de plan ci-dessous restent bornés aux chemins promus et aux suites exécutées. La table de jalons précédente décrit les suites qui l’ont produite; elle n’est pas remplacée par une somme des comptes. Au jalon 10:14, le catalogue `opsys-metier verifier` reconnaît 10 départements, 203 outils et 116 outils déclarés aux appareils (commande séparée, exit 0, 1 115 chemins stables).

- **M5/M10/admission** : la commande root passe 3 294 tests (2 127 M5, 968 M10, 199 socle), sans échec, erreur ni skip, en 239,031 s; les 1 099 chemins sélectionnés sont identiques avant/après. Les tests PostgreSQL M10 et quatre scénarios d’admission réussissent dans cette campagne locale. Le contrôle séparé E09 réussit 15/15 vérifications sur SQLite durable et processus Python séparés; il vérifie un corpus précis et ne constitue pas un rappel général. M10 conserve comme limites les assertions d’auteur non vérifiées, la collecte non générale et les tests E05 historiques.
- **Accès et bootstrap** : la suite root passe 286/287 avec un skip `actionlint` absent en 160,989 s; 1 115 chemins sont stables. Elle vérifie le parcours local EUID 1000 et les modes privés 700/600. Les cas d’ancien propriétaire de volume simulent les métadonnées, sans build d’image ni qualification VPS. La commande r1 à chemin erroné, 0 test/code 4, reste une collecte invalide séparée.
- **Qualité de sources** : Ruff r2 était rouge sur trois `I001`; les changements d’espacement d’imports ont conservé l’AST. Ruff r3 est vert sur 1 115 chemins. Aucun test fonctionnel n’a été rejoué pour ce changement purement formatif.
- **CFO** : M5.4.c répertorie des références de sources ARC/RQ, toutes encore `NON_QUALIFIEE`; aucun calcul de retenue/net/fiscalité officielle n’en découle. La sortie reste le brut préparatoire décrit dans le jalon précédent.

La vérification globale du socle reste celle de R12 : run initial rouge à cause de cas PostgreSQL ENOSPC, reprise exacte des 31 cas rouges et union dédupliquée; aucune commande globale unique verte n’est démontrée. Les nouvelles suites ciblées ne ferment pas ce point, ne prouvent pas un service distant ni une image livrée. La qualification documentaire des références/vecteurs de paie reste ouverte; aucune mission CPA n’est engagée, et la revue professionnelle concerne les actions officielles. Réconciliation des agents et qualification complète Compose restent hors de cette révision.


## Reçus R14 — état au 1er octobre 2026, 11:58 UTC

Les compteurs des campagnes ci-dessous se recouvrent possiblement par leurs fichiers ou parcours; ils ne sont pas additionnés pour former une suite globale. Les 47 IDs et statuts de constats restent inchangés.

- **M5 et admissions** : M5.4.d, admission et compteurs 64 bits passent 2 316/2 316 (2 128 M5, 188 socle), zéro F/E/S, 193,837 s et 1 120 chemins inchangés. Une tentative intégrée précédente reste 2 273P/1F; sa correction de trace possède 21/21 cas ciblés. `actionlint` réussit ensuite son cas unique, 1/1, sur l’environnement où l’outil est présent.
- **M1** : la suite de réutilisation STT passe 1 628/1 628; la vérification ciblée de normalisation/rejeu passe 47/47. Aucun de ces décomptes ne certifie une sémantique exactly-once universelle.
- **Comptage PostgreSQL** : la migration `0014 → 0015` passe sur PostgreSQL 17 éphémère, avec cinq tables, huit lignes legacy préexistantes conservées, onze champs `BIGINT` et idempotence; un autre test confirme la limite de budget et le refus avant dépassement. La concurrence à la borne signée 64 bits aboutit à un seul enregistrement et un refus, avec somme Python exacte. Le cas historique `rowcount=-1` est conservé et la correction emploie `RETURNING`. Aucune donnée de fournisseur ni dépense réelle n’est impliquée.
- **Catalogue** : le vérificateur de manifestes compte maintenant 10 départements, 204 outils et 116 outils déclarés aux appareils; il s’agit d’un contrôle séparé, pas d’un nombre de tests.
- **Économie des jetons** : un document d’architecture a été promu au jalon 11:58:08 UTC; il documente que le SHA-256 de la clé contribue au digest final, sans empreinte isolée persistée. La promotion porte sur le document, pas sur une qualification générale du dispatch.
- **Lint** : `ruff check src tests departments` passe exit 0 avec 1 120 chemins stables; les tests ne sont pas relancés par cette vérification statique.

Ces résultats ciblés ne ferment pas la qualification rootless/VPS et ne démontrent pas une campagne globale verte. Les chemins d’authentification du dispatch et l’environnement de déploiement restent à qualifier séparément. Voir les reçus détaillés liés dans le bilan R14 et la [suite M5/admission/jetons R2](../research/R20-2026-10-01/preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01-resultat.json.gz).


## R15 — vérification rootless ciblée (jalon 12:12 UTC)

Root a promu quatre chemins rootless (Compose, préflight, tests, guide). La suite locale passe 69/69 en 0,959 s, sans échec/erreur/skip; Ruff passe séparément. Chaque commande rapporte 1 124 chemins stables dans l’ensemble de sources surveillées. Les quatre états antérieurs du reçu de promotion sont `null` : les chemins étaient absents, et il n’y a pas quatre contenus préimages à restaurer. La génération de profil garde `runtime_verifie=false`; le préflight réussi retourne `preflight_verifie=true`, tandis que `runtime_sandbox_verifie=false` et `vps_qualifie=false` restent explicitement faux.

Le profil v2 exige une empreinte de clé hôte publique épinglée. Les tests refusent une configuration SSH divergente/ProxyCommand, un hôte connu ou une empreinte incorrecte avant l’appel du runner Docker/SSH; les cas utilisent des runners synthétiques, sans accès réel à un daemon rootless, un démarrage de service ou SSH. Voir le [reçu de promotion](../research/R20-2026-10-01/preuves/r15-rootless-integration-root-r1--resultat.json.gz), le [résultat 69 tests](../research/R20-2026-10-01/preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01-resultat.json.gz), le [JUnit](../research/R20-2026-10-01/preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01.xml.gz), le [Ruff](../research/R20-2026-10-01/preuves/r15-preuves--rootless-ruff-root-r1-2026-10-01-resultat.json.gz) et le guide [SERVEUR-ROOTLESS](../ops/SERVEUR-ROOTLESS.md).

Après append R15, le registre R20 comptera **1 057 archives** : le [reçu R14](../research/R20-2026-10-01/preuves/r15-r20-append-r14-root-capture--append-r14-receipt.json.gz) et le [lecteur indépendant](../research/R20-2026-10-01/preuves/r15-preuves--r20-independant-root-r14-2026-10-01.json.gz) vérifient le point de départ de 1 035 archives; la [revue root R14](../research/R20-2026-10-01/preuves/r15-programme-r14-revue-root-r1--coherence.json.gz) confirme quatre documents et 199 liens locaux.

C01 reste **PARTIEL**; runtime et VPS demeurent **NON QUALIFIÉS**. Aucun démarrage rootless, échange SSH, déploiement VPS, image serveur complète ou parcours Gateway n’a été exercé par cette suite. Les six chemins de correction TOCTOU restent candidats en attente de révision, de preuves closes et de revue root; ils ne sont pas affirmés dans ce jalon.
