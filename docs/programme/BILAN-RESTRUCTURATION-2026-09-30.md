# Bilan de restructuration — lot du 30 septembre, actualisé le 2 octobre 2026 UTC

Branche locale : `codex/restructuration-2026-09-30`, base `2e56c0d5605dfe575bde9244f38924d5390f2674`.
Les corrections et raccords locaux prolongent maintenant le lot documentaire initial. Aucun push,
fusion ou déploiement n'a été effectué. Les départements complets et l'installation de production
restent à construire et à démontrer.

## Rapport privé d’acquisition sourcée M7 — 2 octobre 2026 UTC

ROOT qualifie le rapport privé CMO par **1 261 cas passés**, sans échec, erreur ni skip, en **85,835 s JUnit**, avec **1 134 chemins sélectionnés stables**, dont les huit du gel R2. Le département M7 et neuf fichiers console/socle sont exécutés ensemble ; les ciblés 44 et deux fixtures corrigées sont inclus, sans addition aux jalons M7 précédents. Les associations M2/M3/M5 disponibles sont rapprochées des lectures actuelles par SDK public M2/M5/M8 sous identité DB réelle, avec revalidation avant retour, références et manques explicites. Les montants viennent de M5 ; dépenses publicitaires, CPL, ROI et causalité restent inconnus. L’historique M7 est **non scellé** : son empreinte de lecture n’authentifie pas le passé. Les dates métier, arrivée SQL et lecture sont séparées ; une correction tardive peut changer une ancienne période, sans instantané historique ni photographie atomique multidépartement. Le rouge ROOT **1 259 passés / deux échecs** est conservé ; le raccord de deux fixtures à SQLite migré maintient les assertions. Qualification **SQLite locale, données fictives**, sans PostgreSQL de ce parcours, navigateur réel, fournisseur, publication ou VPS. Cette tranche ne complète pas M7. [Résultat ROOT](/workspace/restructuration-opsys-2026-09-30/preuves/marketing-acquisition-root-r2-20261002-resultat.json), [JUnit](/workspace/restructuration-opsys-2026-09-30/preuves/marketing-acquisition-root-r2-20261002.xml), [guide](../grs/marketing/M7-RAPPORT-ACQUISITION-SOURCEE.md) et [matrice](../grs/marketing/M7-MATRICE-CAPACITES-2026-09-30.md). Ruff sur les sept fichiers Python modifiés passe séparément.

## Point R24 — dictée locale Core (2 octobre UTC, clôture après R25)

Le fournisseur local de clip et son annulation sont qualifiés par **481 cas ciblés ROOT**,
sans échec/erreur/skip, dans cinq campagnes distinctes. Extension finale 67, Gateway 320,
WebSocket 29, protocole 2 et UI 63 : les essais auteur ou historiques ne s'y ajoutent pas.
Les sources Gateway/protocole/UI restent identiques, et les quatre amendements d'extension
sont requalifiés par la campagne finale. Les 35 210 empreintes sélectionnées Core/liaison sont
vérifiées; lint et format passent, avec un avertissement de longueur du composeur.
[Bilan et limites](REPRISE-DICTEE-BILAN-R24.md), [guide](../architecture/DICTEE-LOCALE-CORE.md).

Le serveur HTTP des tests est réel mais sa transcription est fictive; l'UI est testée sous
jsdom. Aucun moteur ASR réel, micro navigateur, accent fr-CA, TTS, avatar ou VPS n'est qualifié.
La suite WebSocket vide r3 est conservée avec son refus et sa reprise r4. Le prochain travail
relie des procédures internes à la mémoire PostgreSQL déjà qualifiée; l'ingestion R26 commence.

## Point R25 — mémoire documentaire PostgreSQL (2 octobre UTC)

La suite ciblée passe **82 cas sans échec, erreur ni skip**, avec le vrai PostgreSQL/pgvector
pour le store et les outils mémoire, et des embeddings déterministes fictifs. Elle vérifie
recherche française/hybride, provenance, filtres départementaux, rétention, effacement et
budget de sortie. Les 1 093 empreintes sélectionnées sont stables; Ruff ciblé et diff passent.
[Bilan et limites](LOT-QUALIFICATION-MEMOIRE-PG.md). Ce mode de test en tmpfs ne qualifie pas
la durabilité sur VPS ni les autres backends métier; les refus PostgreSQL du CSV et des tickets
restent actifs. Au moment de cette qualification R25, la dictée R24 était encore en revue;
sa clôture ciblée figure au point précédent.

## Point R23 — préparation CSV en une action (2 octobre UTC)

Le lot financier durable avance désormais jusqu'à vingt tranches de cent lignes depuis une
action privée, avec arrêt coopératif et reprise sur la révision courante. **496 tests Python
intégrés passent**, dont 29 nouveaux cas, sans échec/erreur/skip; 1 093 empreintes sélectionnées
sont stables. Ruff ciblé et contrôle du diff passent. [Bilan](REPRISE-PREPARATEUR-BILAN-R23.md)
et [preuves R23](../research/R23-2026-10-02/README.md).

Les budgets 2/8 secondes sont contrôlés entre transactions; aucun délai HTTP dur ni débit réel
n'est certifié. Le parcours de 2 000 lignes emploie une horloge injectée. PostgreSQL, ingestion
multi-format massive, apprentissage financier et écritures finales restent hors de cette tranche.
Les 405 tests Core de R22 restent une campagne historique distincte, sans nouvelle exécution R23.

## Point R22 — connecteur persistant, ingestion durable et cible M3 (2 octobre UTC)

Quatre tranches sont qualifiées localement : configuration STT par références et contrôle manuel
de disponibilité, CSV financier chiffré/reprenable avec provenance M10, création d'un brouillon M3
liée au dossier M10, et capture des entrées qui ont produit la durée estimée M3. Le
[bilan de reprise](REPRISE-BILAN-2026-10-02.md) décrit leurs interfaces et limites; les
[preuves R22](../research/R22-2026-10-02/README.md) conservent aussi les rouges et corrections.

**467 tests Python intégrés passent**, dont 19 Fusion, 16 clôture de chantier et un parcours
MCP HTTP réel de création M3. **405 tests Core ciblés passent** dans une campagne distincte.
Les comptes historiques ou auteurs ne s'ajoutent pas à ces chiffres. Ruff, oxlint ciblé,
vérification hors ligne du verrou et catalogue passent; la campagne Python garde 1 092 empreintes
sélectionnées identiques avant/après, celle Core 35 209 dans sa portée déclarée.

PostgreSQL pour le pilote CSV et l'autorité de tickets est refusé explicitement; aucun fournisseur,
Gateway/tour LLM, appareil vocal fr-CA, avatar ou VPS n'est qualifié par ces essais. Les traces M3
préparent la calibration sans changer les prix ni apprendre un nouveau barème. Les lots complets
du [plan](REPRISE-PLAN-2026-10-02.md) restent ouverts. Aucun commit, push ou déploiement.

## Point R21 — reprise et Connecteurs (2 octobre UTC, 1er octobre au Québec)

L'[audit de reprise](REPRISE-AUDIT-2026-10-02.md) fait le point sur la base Claude et les dix
départements; la [vision](../produit/VISION-ENTREPRISE-APPRENANTE.md) conserve les exigences
audio/3D, mesure photo/géospatial, apprentissage et Fusion opérationnelle. Le premier catalogue
Connecteurs privé est livré localement : prérequis existants, présence déclarée, identité relue,
secrets masqués. Il ne configure pas les fournisseurs.

**312 tests intégrés passent**, dont 17 Connecteurs et 16 E2E chantier; cinq PostgreSQL
désélectionnés. Après correction du commentaire M3 périmé, **149 tests M3 ciblés passent**,
avec logique AST identique hors docstring. Durée estimée et comparaison existaient déjà;
calibration des paramètres futurs, ingestion massive et avatar restent non livrés.
Les [preuves R21](../research/R21-2026-10-02/README.md) datent ces campagnes séparément;
leurs comptes ne s'ajoutent pas à R19 ou aux campagnes historiques. Le
[plan de reprise](REPRISE-PLAN-2026-10-02.md) ordonne les neuf lots restants avec critères de sortie.


## Point R19 — M7.4a lecture privée des observations Growth (1er octobre 2026)

**Qualification locale R19.** Le code M7.4a est intégré sur sept chemins par la promotion ROOT R6 du **1er octobre à 18:01:32 UTC**. Cette tranche réutilise le registre `growth` existant pour consulter les observations déclarées via `GET /marketing/growth` et `GET /api/marketing/growth`. Elle ne fournit aucune saisie humaine prouvée : la référence de preuve reste textuelle, son existence externe n’est pas vérifiée et la provenance de l’auteur demeure inconnue.

La console vérifie la personne active et son rôle actuel `nathan_owner` ou `admin` avant lecture, puis dans une nouvelle transaction avant réponse. Le lecteur vérifie la forme exacte et l’empreinte des observations, les nombres finis, les dates et les identifiants uniques avant de filtrer : une observation corrompue hors période refuse aussi la lecture. Les anciens plans sont ignorés seulement après contrôle de leur forme historique top-level; leur contenu sémantique n’est pas qualifié. L’empreinte ne prouve ni l’auteur ni une chaîne inviolable.

Le registre complet est limité à **1 000 maillons**, **32 Ki caractères par maillon** et **1 Mi caractères au total**, avant décodage; ce sont des caractères de texte JSON, pas des octets. Le filtre fermé est limité à **366 jours inclusifs** et retient les observations entièrement comprises dans la période. La pagination, fraîche à chaque requête, n’offre aucun instantané multipages. La lecture ne crée ni observation ni plan, ne calcule ni croissance, causalité ou ROI, et n’effectue aucune publication. Une page vide ne prouve pas zéro activité.

Le document du [lecteur M7.4a](../../departments/m07-marketing/docs/M7-4A-GROWTH-LECTURE.md) détaille les bornes, refus et limites. Les preuves ROOT ci-dessous datent le code intégré; cette actualisation décrit les sources ROOT qualifiées localement. Aucun résultat auteur/QA n’est converti en campagne ROOT. M7 demeure **PARTIEL**.

La campagne intégrée ROOT du 1er octobre 2026, de **18:01:32 à 18:03:51 UTC**, passe **1 436 cas**, sans échec, erreur ni skip, en **137,133 s JUnit** : **1 066 M7**, **279 console**, **82 fichiers/stockage/idempotence** et **9 E2E chantier MCP SQLite**. Les **59 cas Growth (28 lecteur + 31 console)** sont inclus dans ces groupes, sans addition. Deux cas PostgreSQL sont désélectionnés par `-k not postgresql`; ce ne sont pas des skips. Les **1 070 chemins sources sélectionnés** sont identiques avant/après; cet ensemble n’est pas une fermeture de tout le dépôt. Ruff sur sept fichiers et le catalogue (**10 départements, 207 outils, 116 déclarés aux appareils**) passent dans des commandes distinctes. Les qualifications R18 et antérieures gardent leurs arbres; leurs comptes ne s’ajoutent pas à 1 436.

Preuves ROOT closes : [résultat](../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-resultat-json-39d3b4870b.gz) · [JUnit](../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-xml-c8db58b5f3.gz) · [journal](../research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-log-8c7e9f181c.gz) · [promotion R6](../research/R20-2026-10-01/preuves/r19-m74a-integration-root-r6--resultat-json-1909dc8172.gz) · [Ruff](../research/R20-2026-10-01/preuves/r19-preuves--m74a-ruff-root-r1-2026-10-01-resultat-json-3fb7557c96.gz) · [catalogue](../research/R20-2026-10-01/preuves/r19-preuves--m74a-verifier-root-r1-2026-10-01-resultat-json-032e699528.gz) · [lecture indépendante](../research/R20-2026-10-01/preuves/r19-m74a-cloture-independante-r1--rapport-json-190e148f67.gz). Ces preuves sont conservées dans les archives R20, sans modifier le R19 scellé du 30 septembre.



## Point R18 — M7.3a médias privés de chantier (1er octobre 2026, 16:54 UTC)

La promotion root R4 du **1er octobre à 16:51:59 UTC** intègre onze chemins : six fichiers de production, quatre fichiers de tests et un document. Le lot réutilise le CAS, les maillons, le calendrier et la console OPSYS existants. Le propriétaire peut importer une variante JPEG/PNG préparée par un humain, voir les octets privés vérifiés, attester sa revue puis effectuer une remise manuelle liée à l’export texte.

La campagne intégrée root du 1er octobre 2026, exécutée de **16:52:48 à 16:54:58 UTC**, passe **1 377 cas**, sans échec, erreur ni skip, en **128,406 s JUnit** : **1 038 M7**, **248 console**, **82 fichiers/stockage/idempotence** et **9 E2E chantier par MCP sur SQLite**. Les sept cas du pliage média sont inclus dans M7 et les dix-neuf cas de console média dans la console; aucun de ces sous-comptes ne s’ajoute au total. Deux cas PostgreSQL ont été désélectionnés par `-k not postgresql`, ce ne sont pas des skips. L’ensemble surveillé de **1 066 chemins sources sélectionnés** est identique avant/après; il ne constitue pas une fermeture de tout le dépôt. Les dix-neuf cas média comprennent des tests HTTP, un test direct du parseur ASGI et un oracle de garde substituée; ils ne sont pas dix-neuf parcours complets de bout en bout.

Le snapshot épingle le **WCT M4 reçu complet**, le profil de marque, la révision et le SHA des octets UTF-8 du texte courant, les photos sources vérifiées et le consentement actif. Il ne contient pas le créneau : celui-ci est contrôlé à la remise et à la lecture des octets remis, et son identifiant est lié au reçu. Un changement de source ou de consentement invalide l’ancienne revue; une nouvelle préparation avant remise ouvre une révision sans effacer l’historique. Le propriétaire actif est revalidé aux frontières du parsing et de l’effet. La remise exige les approbations courantes de texte, créneau et média; les références du reçu sont exactement celles des variantes préparées, triées et dédupliquées. Une réémission du même dossier ne crée ni maillon ni export supplémentaires.

La revue a corrigé le refus erroné d’une deuxième remise, le contrôle trop tardif d’un texte réellement modifié et l’acceptation de références CAS étrangères dans un reçu. Les rouges correspondants sont conservés. Une suspicion de fuite de fichiers temporaires a été retirée après lecture du parseur Starlette 1.7.0 réellement verrouillé; un test direct ASGI vérifie séparément la fermeture lors du dépassement de flux sans `Content-Length`. Le préflight R3 a aussi relevé deux tris d’imports Ruff dans les tests; R4 corrige uniquement ces imports, sans changement d’AST hors imports ni de code métier.

La tranche demeure **PARTIELLE** : aucune publication ou connexion fournisseur, transformation automatique des images, analyse des pixels, suppression EXIF, surface mobile M7 dédiée, essai navigateur réel ou qualification VPS. Les attestations de préparation et de revue restent humaines. Les nouvelles écritures médias refusent PostgreSQL; aucune concurrence PostgreSQL pour ce registre n’est qualifiée. Le catalogue reste à **10 départements, 207 outils et 116 outils déclarés aux appareils**; aucun outil MCP n’a été ajouté.

Preuves : [résultat](../research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-resultat-json-aab3d9c2e7.gz) · [JUnit](../research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-xml-d4c76cecab.gz) · [journal](../research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-log-1c43560d7a.gz) · [lecture indépendante](../research/R20-2026-10-01/preuves/r18-m73a-cloture-independante-root-r1--verification-json-061d6a4c0f.gz) · [promotion R4](../research/R20-2026-10-01/preuves/r18-m73a-integration-root-r4--resultat-json-f24b78b5dc.gz) · [Ruff](../research/R20-2026-10-01/preuves/r18-preuves--m73a-ruff-root-r1-2026-10-01-resultat-json-8bb466cbf1.gz) · [catalogue](../research/R20-2026-10-01/preuves/r18-preuves--m73a-verifier-root-r1-2026-10-01-resultat-json-5e77c4ab23.gz). La [revue finale](../research/R20-2026-10-01/preuves/r18-m73a-revue-finale-root-r1--revue-json-d709afba6b.gz) sépare les défauts confirmés des suspicions retirées. Ruff porte sur dix fichiers Python; le catalogue et Ruff sont des commandes distinctes, chacune avec 1 066 chemins sélectionnés stables. La lecture indépendante vérifie les trois clôtures et les onze empreintes au jalon de code; l’actualisation documentaire présente est postérieure. Les qualifications Brand 79 et M7/CMO/bootstrap 1 261 restent historiques et ne s’additionnent pas à 1 377. Le registre conserve ses 47 identifiants, 42 corrections locales et cinq constats partiels; ce lot ne déclare ni M7 ni OPSYS-AI complets.

## Point R17 — M5.3a rapprochement bancaire préparatoire (1er octobre 2026, 15:28 UTC)

Après l’intégration du moteur M5.3a (14:48:58) et de son adaptateur privé de console (15:23:34), la campagne root est close à 15:28:30 avec **2 444/2 444** cas, sans échec, erreur ni skip, en 234,923 s. Le JUnit répartit les cas en **2 182 M5** et **262 tests socle sélectionnés**; les 24 tests du moteur CSV sont inclus dans le premier groupe et les 19 tests de console dans le second. Ce ne sont pas des comptes à ajouter au total. La commande exclut les cas dont le nom correspond à `-k not postgresql`; elle ne qualifie donc pas la concurrence bancaire PostgreSQL. Les 1 140 chemins de l’ensemble surveillé sont identiques avant et après.

Le moteur prévisualise uniquement les rapprochements exacts par `facture_id` et montant dû complet. L’adaptateur privé lit la chaîne complète des factures, affiche le détail des lignes, puis inscrit une projection hashée dans un registre séparé; les octets CSV bruts ne sont pas persistés. Le rejeu d’un lot est explicitement signalé comme historique avec le snapshot d’origine. L’écriture revérifie le rôle humain actif et le snapshot, utilise l’idempotence et le rang attendu, et refuse un conflit sans append. La configuration `configuration.banque_csv.comptes_internes` doit contenir une allowlist de comptes internes; absente, l’usage est bloqué. Les comptes des fixtures sont fictifs et ne sont pas une configuration active.

Cette étape reste **PARTIELLE** : routes privées de propositions préparatoires, pas de fournisseur bancaire ni de connexion externe, paiement, approbation finale ou écran d’historique; pas de qualification de concurrence PostgreSQL. Les entrées partielles, splits, frais ou associations au montant seul restent refusées. Aucune nouvelle capacité MCP n’est ajoutée. Ce point ne comporte aucune qualification M7.

Preuves : campagne [résultat](../research/R20-2026-10-01/preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-resultat-json-ecb703a783.gz) · [JUnit](../research/R20-2026-10-01/preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-xml-cfcc4c08f3.gz) · [journal](../research/R20-2026-10-01/preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-log-fa1f35f466.gz); clôture indépendante [vérification](../research/R20-2026-10-01/preuves/r17-m53a-cloture-independante-root-r2--verification-json-cde5e4f5ab.gz); [Ruff](../research/R20-2026-10-01/preuves/r17-preuves--m53a-ruff-root-r1-2026-10-01-resultat-json-3e10e6ab0b.gz) et [vérificateur de catalogue](../research/R20-2026-10-01/preuves/r17-preuves--m53a-verifier-root-r1-2026-10-01-resultat-json-c2d98b6da7.gz) sont des commandes séparées, chacune avec 1 064 chemins surveillés stables. Le catalogue compte 10 départements, 207 outils et 116 outils déclarés aux appareils. Les reçus de promotion du [moteur](../research/R20-2026-10-01/preuves/r17-m53a-moteur-integration-root-r1--resultat-json-bb3f5d4811.gz) et de la [console](../research/R20-2026-10-01/preuves/r17-m53a-console-integration-root-r3--resultat-json-79ecb98ca1.gz) identifient respectivement 3 et 6 chemins intégrés.

## Point R16 — état ciblé après intégrations root (1er octobre 2026, 14:04 UTC)

Le registre conserve ses 47 constats et le jalon R15 précédent; les comptes ci-dessous sont des preuves ciblées, non additionnées à celles d'autres arbres. Le R20 de départ de ce paquet compte 1 057 archives; R19 reste scellé et inchangé.

- **Entrée 5 — profils et dispatch.** Le raccord root porte sur sept chemins, le test HTTP portable sur un chemin. Le Core r3 passe 130/130, sans échec, erreur ni skip, sur 1 135 chemins de l’ensemble surveillé stables. Son test de bout en bout traverse Core puis le MCP HTTP Python réel pour un grant CFO à usage unique avec une fixture synthétique. Une probe PostgreSQL distincte (assertions de script, pas tests JUnit) sous PostgreSQL 17.11 observe l'attente de verrou, la vérification/transaction sur une même connexion, la révision 2→3 et le refus de l'appel devenu tardif. Elle utilise un handler espion; aucune consommation de ticket CFO sur PG ni aucun fournisseur de production n'est exercé.
- **Entrée 9 — M5.** M5.8a est intégré sur six chemins et la correction de classement sur trois autres. La campagne root R2 passe 2 210 cas (2 158 M5, 8 accès trésorerie, 24 MCP HTTP, 2 révisions de profil, 18 admission), 0 échec/erreur/skip en 165,471 s, avec 1 135 chemins de l’ensemble surveillé stables. Cinq cas PostgreSQL ont été désélectionnés par `-k not postgresql`; ils ne sont pas des skips. C'est la suite M5 actuelle avec quatre familles de tests socle sélectionnées, pas une validation de production ou un compte global. Le vérificateur de catalogue indique 10 départements, 207 outils, 116 outils déclarés aux appareils. Les neuf PDFs de référence paie restent `NON_QUALIFIEE`; l'empreinte ancienne `fe898…`/`cbd818…` est celle de deux HTML sauvegardés, pas celle des PDF ARC récents.
- **Entrée 12 — validation.** Ruff Python ciblé et vérificateur de catalogue passent séparément sur leurs périmètres root. Le socle complet n'a pas de nouvelle campagne verte sur cet arbre; les erreurs ENOSPC documentées restent distinctes. Les épreuves rouges de dispatch/M5 sont conservées avec leur statut initial et ne sont pas effacées par les reprises.

Preuves centrales : [Core r3](../research/R20-2026-10-01/preuves/r16-preuves--runtime-dispatch-core-root-r3-2026-10-01-resultat-json-45b1b9d928.gz), [probe PostgreSQL](../research/R20-2026-10-01/preuves/r16-preuves--profile-runtime-toctou-pg-root-r3-2026-10-01-resultat-json-d686cbefe7.gz), [campagne M5 R2](../research/R20-2026-10-01/preuves/r16-preuves--m58a-finance-runtime-integres-root-r2-2026-10-01-resultat-json-9573718f4e.gz) et [vérification documentaire paie](../research/R20-2026-10-01/preuves/r16-preuves--sources-officielles-verification-root-r1-json-d9dbb33c26.gz). Les preuves de lint, vérificateur, corrections de chemins et reprises initiales sont référencées dans le paquet R16.

## Instantané historique R15–R20 et preuves distinctes

Cette section conserve les qualifications de ce jalon. Les points R21 et suivants en tête
du document et le [plan de reprise](REPRISE-PLAN-2026-10-02.md) décrivent les tranches ajoutées
ensuite; les nombres de campagnes et listes d'outils ci-dessous ne sont pas un état courant.

État de référence R15 arrêté au 1er octobre 2026 à 09:34 UTC; les points R16 à R18 ci-dessus datent les promotions et preuves root closes ensuite. L’actualisation documentaire R19 référence le code ROOT promu et la campagne close à 18:03:51 UTC. Les reprises de tests et promotions restent datées dans chaque entrée. Les reçus de relocation de stockage postérieurs sont explicitement séparés et ne modifient pas ce jalon de code.

Le [registre d'audit](REGISTRE-AUDIT-2026-09-30.md) conserve les 47 constats : 42 corrigés localement
avec leurs preuves et cinq partiels. C01 (frontière OS), C02 (couverture universelle des cibles),
l'image Docker Core/VPS, la CI distante du diff et les dépendances mobile restent ouverts dans leur
portée. Les épreuves historiques sont archivées dans [R17](../research/R17-2026-09-30/README.md) et
[R18](../research/R18-2026-09-30/README.md); les raccords courants sont suivis dans
[R19](../research/R19-2026-09-30/README.md); [R20](../research/R20-2026-10-01/README.md), en cours,
conserve les reprises M3 et les droits CFO. Ne pas additionner leurs comptes : des suites se recoupent
et les arbres exécutés diffèrent.

- C02 : tickets privés à usage unique pour huit mutations M2/M3, cible et liaison M10 revérifiées
  dans la transaction SQLite; demande N4 humaine conservée même en mode autonome. Revue backend
  ciblée 177/177 et Core 98/98 (91 unités + shard de sept). M2 complet après APR : 1 795/1 795
  en 196,855 s, 1 022 empreintes identiques; M3 complet
  avant APR : 2 165 réussites et un skip de garde CI, 7 377,883 s, 99 empreintes identiques.
  Après APR, M3 ordinaire : 2 133 réussites et ce même skip, sans les deux harnais lourds déjà
  exécutés. PostgreSQL pour le ticket, batch/multi-cibles et protection OS ne sont pas certifiés. Le
  [lecteur runtime Core r2](../research/R20-2026-10-01/preuves/runtime-core-lecteur-root-r2-2026-10-01.json.gz)
  établit 73/73 tests sur huit fichiers et 10 081 sources identiques autour de Vitest. Le
  [chronogramme r2](../research/R20-2026-10-01/preuves/agent-profile-active-check-r1-chronologie-r2.md.gz)
  précise que le typecheck natif a réussi avant la capture initiale; l'immutabilité pendant ce
  typecheck n'est donc pas démontrée.
- C01 : configuration générée et garde Core imposent désormais le sandbox Docker, y compris
  pour `main` et les anciennes sessions ayant désactivé le sandbox. Génération Python : 153/153;
  Core élargi : 101/101, dont les 63 anciens cas, et 25 observations TypeScript réussies
  (neuf graphes R1 non affectés et seize R2, aucune commande globale unique revendiquée).
  Les corrections de typage concernent nos fixtures et conservent leurs assertions. Le daemon et l'image standard sont
  requis avant chaque tour; les installateurs vérifient le daemon Linux et préparent l'image
  standard si elle manque. Le patch cumulatif est intégré; les parcours scratch utilisent un
  Docker factice (84 tests installateurs et 37 bout-en-bout, suites distinctes).
  La qualification locale r4 a ensuite construit l'image sandbox standard et exercé les factories
  TS natives `resolveSandboxContext` puis `createExecTool(...).execute(...)`, avec bash et une
  configuration/session synthétiques conformes à la garde OPSYS. Le
  [résultat r4](../research/R20-2026-10-01/preuves/c01-os-sandbox-run-2ec9a897-a635-4302-aa31-301822bf1766.json.gz)
  et le [lecteur root](../research/R20-2026-10-01/preuves/c01-os-sandbox-lecteur-root-r1-2026-10-01.json.gz)
  établissent UID/GID 1000, root RO, réseau `none`, NNP=1, seccomp=2 et capabilities effectives nulles.
  Deux montages privés existent : workspace RW et skills RO, aucun bind supplémentaire configuré
  ni montage du workspace hôte synthétique. Le marqueur hôte choisi est absent; les noms `OPSYS_*`
  fictifs sont retirés explicitement, sans preuve d'épuration automatique de l'environnement.
  **C01 reste PARTIEL** : pas d'image serveur complète, Gateway/tour LLM, SaaS multi-tenant ou VPS.
  [R20 r9](../research/R20-2026-10-01/README.md) conserve les échecs r1–r3 : r1 a créé/inspecté
  un conteneur avant son erreur de schéma au nettoyage, malgré le récit « avant Docker »;
  le harness exact r2 manque et l'association du fichier de base r1 à son exécution n'est pas prouvée.
- M1 : acquisition manuelle WAV dans la console montée, consentements, import canonique et rejeu.
  Le [rapport de réconciliation r2](../research/R20-2026-10-01/preuves/m1-rejeu-contradictoire-r2-reconciliation.md.gz)
  attribue séparément 82 tests à une passe ciblée antérieure, 78 à rejeu/bus + UTM et 1 578 à la
  suite complète M1. Le run intégré root r1 contient 1 578 tests M1 parmi ses 6 723
  réussites. Le [JUnit intégré](../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01.xml.gz)
  et son [résultat](../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01-resultat.json.gz)
  documentent ce passage. Un STT CPU a transcrit une seule phrase publique FLEURS; cela n'authentifie
  pas l'enveloppe fournisseur/webhook et ne prouve pas la téléphonie ou la voix de production.
- M5 : dossier CFO préparatoire en 25 rubriques, source unique, données inconnues explicites,
  console admin et réponses sous le budget. Le dossier refuse les trois registres altérés avant
  calcul. Les preuves après le premier raccord des droits, mais avant M5.10.a, sont historiques :
  deux runs FinanceCore de **2 028 tests** (enregistrés respectivement à 117,119 et 117,113 s),
  test HTTP CFO 15/15, console/générateur 4/4 et Core 12/12. Ces portées se recoupent et ne
  s'additionnent pas.
  Après intégration de M5.10.a, la vérification au jalon antérieur compte **2 037 tests M5 + 34 tests du
  socle = 2 071 tests dans une commande**, 0 échec, 0 erreur, 0 skip, en 134,333 s; 1 029 sources
  sélectionnées identiques avant/après. Le [JUnit](../research/R20-2026-10-01/preuves/m5-scenarios-integres-root-r1-2026-10-01.xml.gz)
  et le [résultat machine](../research/R20-2026-10-01/preuves/m5-scenarios-integres-root-r1-2026-10-01-resultat.json.gz)
  sont archivés ensemble.
  Les comptes 2 028 et 2 071 décrivent des arbres distincts et ne sont pas additionnés.
  `m5_preparer_decision_cfo` reste le dossier en 25 rubriques; `m5_preparer_decision_capital`
  est un comparateur séparé, avec échéanciers optionnels. L'ancienne forme est préservée sans
  option; l'extension bornée à huit sorties datées par option demande une couverture manuelle
  jusqu'à l'horizon, sans fabriquer de calendrier, taux ni frais. Le calcul reprend le solde du
  registre et les obligations une fois; le minimum est hebdomadaire. La paie, la fiscalité officielle,
  le rapprochement bancaire, les contrats signés, le DSCR et les projections 12/24 mois restent
  partiels ou absents. Le droit CFO demeure distinct, révocable et limité à deux rapports
  préparatoires sur SQLite; aucun
  fournisseur LLM réel ni séparation SaaS n'est certifié.
- **M4/M5 — jalon ACTIF des sources horaires.** Les heures régulières M4 sont validées par
  un humain N4, avec sources recalculées et contrôle de la validation précédente attendue (CAS).
  M5 conserve séparément le contrat individuel et le taux horaire privé déclaré en CAD, avec
  source/date humaines et contrôle de révision/tête attendues; cette déclaration n'authentifie
  pas le document salarial. La suite combinée root r3 passe **4 962 cas : 2 854 M4 + 2 074 M5
  + 34 socle CFO**, sans échec, erreur ni skip, en 294,638 s JUnit; les **1 033 chemins
  sélectionnés** restent identiques avant/après. Le
  [JUnit](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r3-2026-10-01.xml.gz),
  le [résultat](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r3-2026-10-01-resultat.json.gz),
  la [réconciliation](../research/R20-2026-10-01/preuves/m54-m4-m5-reconciliation-root-r1-2026-10-01.json.gz)
  et la [ventilation](../research/R20-2026-10-01/preuves/m54-m4-m5-ventilation-root-r1-2026-10-01.json.gz)
  sont archivés dans [R20 r10](../research/R20-2026-10-01/README.md). Les cinq écarts de
  catalogue/ordre du [rouge r2](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r2-2026-10-01.xml.gz)
  ont été corrigés en conservant assertions fermées et permissions; les mêmes 4 962 identifiants
  passent en r3. L'[erreur de collecte root r1](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r1-2026-10-01-resultat.json.gz)
  reste distincte, sans échec métier. La nouvelle passe intégrée root r1 couvre 6 723 cas : 1 578 M1,
  2 865 M4, 2 100 M5 et 180 tests socle accès/runtime; 6 723 réussites, 0 échec/erreur/skip,
  400,435 s JUnit et 1 080 chemins identiques avant/après ([JUnit](../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01.xml.gz),
  [résultat](../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01-resultat.json.gz)).
  Le pont M4→M5, les contrats salariaux privés et l'interface de brut préparatoire ont été promus
  dans l'arbre actif par root le 1er octobre. La sortie est limitée au
  brut régulier : aucun calcul QC, retenue, cotisation, net, paiement, déclaration ni action de paie.
  Le diagnostic M54 global r1 est incomplet (303 cas ENOSPC + un cas de rôle fermé corrigé, 304
  touchés). Le socle root r2 reste un résultat antérieur incomplet (INTERNALERROR ENOSPC : 2 255
  tests attribués sur 2 256, 135 échecs, 154 erreurs, 84 skips); 163 erreurs ENOSPC explicites,
  124 SQLite « database or disk is full » et deux autres cas. Un chemin basetemp M4 est confirmé;
  le code Git 128 contemporain n'a pas de causalité établie.
  Le ciblé root r1 M7/CMO/bootstrap passe
  1 261/1 261, sans échec/erreur/skip, en 73,076 s, avec 1 094 chemins identiques. Son périmètre
  couvre M7 et les consoles CMO/marque/calendrier/performance/paie, bootstrap/instance/profils/rôles/
  canaux et un test appareil M4; il ne représente pas le socle complet ([JUnit](../research/R20-2026-10-01/preuves/m7-bootstrap-forme-integres-root-r1-2026-10-01.xml.gz),
  [résultat](../research/R20-2026-10-01/preuves/m7-bootstrap-forme-integres-root-r1-2026-10-01-resultat.json.gz)).
  Le correctif de forme M4 est test-only ([résultat](../research/R20-2026-10-01/preuves/m4-forme-basetemp-integration-root-r1-2026-10-01-resultat.json.gz));
  les changements CMO ([résultat](../research/R20-2026-10-01/preuves/m7-cmo-integration-root-r1-2026-10-01-resultat.json.gz))
  portent six chemins et bootstrap/Compose sept ([résultat](../research/R20-2026-10-01/preuves/compose-bootstrap-integration-root-r1-2026-10-01-resultat.json.gz)).
  Les fixtures temporaires ont été retirées; aucune archive restaurable ne les conserve. Le fullsocle
  root r3 a terminé rouge : 2 478 cas, 2 363P/1F/30E/84S, 1 223,835 s, 1 094 chemins sans delta.
  Les 31 cas rouges PostgreSQL signalent explicitement ENOSPC. La reprise exacte sur les mêmes
  sources passe 31/31 en 199,136 s, sans échec/erreur/skip et sans delta sur ces 1 094 chemins.
  Le lecteur root réconcilie l'union dédupliquée à 2 478 tests uniques : 2 394 réussites et 84 skips,
  aucun rouge restant dans l'union, mais aucune commande globale unique verte. Les 84 skips restent
  non certifiés et les 1 094 chemins ne forment pas une fermeture complète de dépendances. Ces
  campagnes précèdent une modification ultérieure d'une ligne de `pyproject.toml`; aucune validation
  globale n'est revendiquée sur le nouvel arbre. Le bootstrap ciblé sans override passe ensuite 29/29
  en 9,027 s, sans échec/erreur/skip, avec 1 094 chemins stables ([résultat](../research/R20-2026-10-01/preuves/pytest-retention-bootstrap-root-r1-2026-10-01-resultat.json.gz)).
  Résultats séparés : [run initial](../research/R20-2026-10-01/preuves/socle-integre-root-r3-2026-10-01-resultat.json.gz),
  [reprise PostgreSQL](../research/R20-2026-10-01/preuves/socle-reprise-postgresql-root-r1-2026-10-01-resultat.json.gz),
  [union dédupliquée](../research/R20-2026-10-01/preuves/socle-union-root-r1-2026-10-01.json.gz).
  Ruff global (`src tests departments`) réussit séparément, exit 0, avec les mêmes 1 094 chemins
  mesurés stables ([résultat](../research/R20-2026-10-01/preuves/ruff-socle-departements-root-r1-2026-10-01-resultat.json.gz)).
  La passe M1/M4/M5 ciblée n'achève pas les départements.
- M7 : profil de marque courant configurable dans la console réelle, par les outils et le
  registre existants. Le propriétaire actif est revérifié après lecture de la requête; l'admin
  consulte le profil. Montage commun antérieur de six interfaces : 79/79, 1 021 sources contrôlées sans
  changement. Il recoupe notamment les 15 cas CFO; aucune somme entre suites. Les cinq champs,
  la révision et le signataire ne constituent pas un brand book complet ni un historique UI.
- Socle avant raccord CFO : passe complète après APR/M10/marque/installateur : **2 302 réussites,
  83 skips, aucun échec ni erreur**, sur 2 385 cas, en 1 271,146 s. Les 1 022 empreintes source
  et les cinq fichiers CI/sandbox complémentaires restent identiques avant/après. Les exclusions
  sont 82 cas PowerShell absent du PATH et un test Docker réel. La passe antérieure
  **2 252 réussites, quatre échecs, 78 skips** et son raccord ciblé 98/98 restent historiques.
  La première tentative du 1er octobre a été interrompue
  par le chef de projet après 60 cas pour déclarer un label de runner oublié : `actionlint` réel
  refusait ce label. Le label précis est maintenant déclaré, sans diagnostic ignoré; cette analyse
  statique passe. La tentative interrompue, son code 1 et son erreur de teardown restent conservés.
  `actionlint` a été exécuté dans la nouvelle passe. Le test PowerShell observant l'ordre
  build Docker → gateway a ensuite reçu une correction de son faux Node, sans modifier les
  assertions ni l'installateur. La reprise distincte sous PowerShell Microsoft 7.6.6/Linux passe
  **87/87**, sans skip, en 374,041 s, sur la copie comparée à l'actif avant/après. Docker et
  gateway y sont factices; Windows réel et Windows PowerShell 5.1 restent à qualifier. Les deux
  tentatives intermédiaires interrompues sont conservées, sans les additionner au résultat final.
- APR002 : journalisation atomique de l'auteur actif des demandes N4 intégrée exactement après
  le gel M3. Revue isolée 33/33; raccord actif approbations/cibles/rejeu : 254/254, 1 022 sources
  identiques avant/après. Une première commande à chemin de test inexistant (zéro test, code 4)
  est conservée séparément. Les modes N4 existants ne sont pas modifiés; une personne révoquée
  n'est pas attribuée comme auteur humain.
- M10 : première évaluation synthétique de développement, huit scénarios pris en charge réussis
  et deux non pris en charge. Sur la fenêtre de 32 prompts pertinents, précision 30/30, rappel
  30/32; la cible ancienne omise a un rappel 0/1. Cette mesure locale ne certifie ni le rappel
  général ni la mémoire d'affaires. Le correctif intégré déclare les omissions et détecte les
  contradictions hors fenêtre; il ne prétend pas améliorer ce rappel. La vérification après APR
  de 963 tests (948 M10 + 11 console-jobs + quatre cron) est historique. La sélection actuelle
  utilise les chemins structurés, les liens de remplacement stockés et la fraîcheur par hash;
  cycles et convergence sont distingués, les omissions sont exposées aux limites 30/30/1 000.
  La suite intégrée actuelle passe **974 tests** (959 M10 + 11 console-jobs + quatre cron),
  sans échec/erreur/skip, en 38,959 s JUnit, avec 1 029 sources sélectionnées identiques avant/après.
  Le [JUnit archivé](../research/R20-2026-10-01/preuves/m10-selection-integree-root-r2-2026-10-01.xml.gz)
  suit un rouge conservé : espace disque PostgreSQL épuisé et fixture de console exécutée avant
  son horaire de Toronto. L'horloge du test est désormais explicite, sans changement de l'horaire
  de production. Une correction ultérieure d'espacement d'import conserve l'AST et passe Ruff
  global; elle n'est pas présentée comme une nouvelle exécution des 974 tests.
- Core : les six groupes couvrent exactement les **158 fichiers** du manifeste, sans manque ni
  doublon. Les 22 fichiers de la reprise finale passent : 570 tests, quatre skips Windows sous
  Linux. Le manager global de la fixture ticket est recréé entre les cas après une reproduction
  du décalage de générations de modules; code de production et assertions conservés. Sept tests
  ciblés passent après le seul formatage final. Les quatre premiers projets proviennent des
  rapports JSON R3, dont le collecteur global s'est arrêté ensuite; aucune commande complète unique
  des 158 cibles n'est revendiquée. Les cinq skips de cette union concernent tous Windows :
  quatre dans la reprise finale et un dans les quatre projets R3. La
  [relecture des sources et cibles](../research/R20-2026-10-01/preuves/core158-lecteur-independant-root-r5-2026-10-01.json.gz)
  contrôle 34 029 empreintes Core, sans transformer ces groupes en une commande globale.
- Socle après intégration M5.10.a/M10 : **2 324 réussites, 84 skips, aucun échec ni erreur**, sur
  2 408 cas, en 1 322,698 s JUnit. Les 1 037 chemins sélectionnés de plusieurs formats
  (1 029 du socle/départements/installateurs et huit Core explicites) restent identiques.
  Le [JUnit](../research/R20-2026-10-01/preuves/socle-m5-m10-integres-root-r1-2026-10-01.xml.gz)
  et la [réconciliation indépendante](../research/R20-2026-10-01/preuves/socle-m5-m10-reconciliation-root-r1-2026-10-01.json.gz)
  établissent que les 38 anciens échecs/erreurs sont présents et réussis. Les 82 skips PowerShell
  correspondent tous à des cas réussis dans l'ancien compagnon Linux de 87 tests; ce compagnon
  conserve son propre arbre et ses simulations Docker/gateway. Le skip actionlint a une reprise
  distincte d'un cas réussi en 0,235 s; le skip Docker opt-in a ensuite une reprise réelle des
  cinq volumes jetables, réussie en 382,729 s. Les marqueurs de fichiers sont restaurés et les
  cinq volumes nettoyés; SQL et `compose stop/up` sont simulés, sans restauration complète VPS.
  Aucune de ces reprises n'est ajoutée aux 2 324 ni convertie en succès dans le JUnit original.

Les sous-capacités et limites sont aussi détaillées dans la
[matrice M7](../grs/marketing/M7-MATRICE-CAPACITES-2026-09-30.md) et
[l'audit M10](../grs/memory/M10-AUDIT-INITIAL.md). Les tests qu'ils citent indiquent où contrôler les
comportements; leur présence seule ne vaut pas exécution ni capacité complète.

Le générateur emploie maintenant les providers natifs par défaut et LiteLLM sur option explicite;
la CLI du fork compilé appelle réellement le moteur Python. Les tests d'installation et la
consolidation M10 par commande cron démontrent des parcours locaux, pas un VPS neuf ni un provider
de production. Les agents configurables disposent d'admission et de réservations de budget;
les autres chemins d'exécution et leurs coûts restent à qualifier.

L'audit mobile du 1er octobre confirme 13 entrées de paquets modérées liées à deux avis, sans
modification du lock. Les appelants UUID/URL inspectés réduisent la portée démontrée, sans fermer
les avis ni certifier l'absence d'autres chemins. Aucun override compatible ni build appareil
réel n'est prouvé; le [rapport de portée](../exploitation/MOBILE-DEPENDANCES-2026-10-01.md) conserve
les versions, sources et limites.

Un profil autorisé à appeler un outil ne reçoit pas implicitement le droit de lire les finances.
Le [raccord de droits financiers](../grs/compta/M5-PROFILS-AGENTS-DROITS.md) exige une autorisation
humaine distincte et révocable, liée au profil et à l'instance. Sans ticket CFO privé ou identité
humaine valide, le MCP refuse les deux rapports avant lecture. Aucun accès multi-tenant ni droit
N4/N5 supplémentaire n'est livré. La passe complète historique après raccord CFO se termine avec
**2 282 réussites, trois échecs, 35 erreurs et 83 skips**, sur 2 403 cas, en 1 743,215 s;
les 1 034 sources contrôlées restent identiques. Deux fixtures périmées (chemin du helper CFO,
liste des outils runtime) sont corrigées; le raccord des cinq fichiers concernés passe ensuite
**45/45**, sans skip, en 13,691 s JUnit. Ce ciblé précède la nouvelle passe complète ci-dessus.
Les 36 cas PostgreSQL avaient été indisponibles après quatre conteneurs arrêtés avec le code 1;
leurs journaux ont été perdus par l'auto-suppression Docker. La pression disque/VFS reste une
hypothèse, sans cause certaine ni conversion de ces erreurs en skips. Ruff global passe.
Après correction du diagnostic et nettoyage de la fixture, **47/47 cas ciblés** passent,
sans erreur ni skip, en 20,426 s JUnit. Les mêmes identifiants des 36 anciens cas PostgreSQL
sont tous présents et réussis; la nouvelle passe complète ci-dessus contient également ces cas.
Le hook Core partagé avait donné 8/9 : l'ancienne fixture omettait personne/rôle désormais requis.
Elle est corrigée sans assouplir la garde de production; les 158 fichiers sont désormais couverts
par les groupes locaux documentés ci-dessus. La CI distante reste à exécuter.

Le récit ci-dessous conserve le **lot documentaire initial R16**. Ses chiffres de tests, ses
comptes de constats ouverts et son absence d'installation de candidates se rapportent à cet
instantané historique, remplacé pour l'état courant par les preuves ci-dessus.

## Direction enregistrée et règles modifiées

[DIRECTIVES-NATHAN](../produit/DIRECTIVES-NATHAN.md) conserve dans les fichiers du dépôt le principe de réutilisation
prioritaire, les ambitions des départements, le fork maintenu, l'installation VPS, plusieurs agents
configurables et l'économie de tokens. Cela ne vaut pas ingestion M10 ni mémoire personnelle
permanente d'un modèle ; le lot n'est pas encore commité. [ADR-0012](../decisions/ADR-0012-reutilisation-profondeur-productivite.md)
fait primer cette instruction sur les règles historiques contraires.

AGENTS, CLAUDE, digest et boucle emploient des contrôles proportionnés. Aucun vote de trois modèles,
fournisseur extérieur ou format administratif n'est nécessaire pour développer ou intégrer un
changement. Les approbations humaines d'argent réel, paie finale, fiscal officiel, légal, achats
majeurs, campagnes payantes et actions publiques sensibles sont conservées. La règle locale du
core de construire/tester en CI est conservée ; ce lot n'exécute pas ses scripts tiers.

Les documents d'entrée, l'architecture, l'économie de tokens, CODEOWNERS, la définition produit,
le catalogue et les consignes départementales sont réconciliés. Les anciens audits, plans et ADR
restent datés, avec l'autorité courante indiquée ; leur historique n'est pas réécrit en faux succès.

## Profondeur préservée, adaptée au code actuel

Le [périmètre adapté](../produit/PERIMETRE-MODULES.md) couvre M1.1–20, M5.1–20, M7.1–15 et les
15 couches M10, plus les autres départements. Les tables et routes Forge deviennent des exigences
à traduire dans les contrats OPSYS existants, pas un second backend.

- M1 : intake, adjointe, voix progressive, appels manqués, plainte/transfert, agenda et liens CRM.
- M5 : comptabilité et CFO complet, paie préparatoire, obligations QC/Canada, réserves, contrats,
  prévisions, camion/équipement/bâtisse, dette/investissement, sources et questions CPA.
- M7 : département CMO complet, contenu/social, croissance, réputation, SEO, Ads, ROI, offline.
- M10 : événements, prompts/plans/décisions/code/tests/erreurs, sources et révisions, contexte,
  relations, temporalité, consolidation et évaluations ; développement et affaires isolés.

Chaque capacité exige données, contrat, permissions, workflow, interface, preuves, documentation
et limites. Plusieurs agents disponibles ne sont pas tous appelés à chaque tour. Admission avant
appel, réservations de budget sous concurrence, contexte ciblé, outils composés, cache isolé et
déclencheurs événementiels font partie du plan, avec mesure de coûts/qualité plutôt qu'économie
annoncée sans benchmark.

## Recherche de briques

[R16](../research/R16-2026-09-30/README.md) réunit six volets et les notes Hermes détaillées.
L'index conserve 123 observations et 120 identifiants hôte/dépôt (107 GitHub, 13 GitLab) ; miroirs
et renommages peuvent désigner un même projet. Ce décompte ne mesure ni maturité ni gain de temps.
Les sources sont fixées à des commits avec licences primaires, interfaces et limites dans les
rapports. Aucune candidate, dépendance ou poids de modèle n'a été installé ou exécuté.

Choix initial : garder le fork OpenClaw ; emprunts Hermes ciblés, un moteur vocal Pipecat/LiveKit,
OCR Docling/Tesseract, Python Accounting à essayer dans la session OPSYS, API/SDK officiels pour
connecteurs, PostgreSQL/relations comme palier mémoire possible, social en export d'abord.
OR-Tools, InvenTree, DuckDB, NetworkX et SimPy sont des candidates transversales, pas une nouvelle
stack automatiquement imposée. Hindsight mérite un banc temporel isolé, sans devenir canon métier.

Corrections de qualification : Piper maintenu GPL, modèles LiveKit distincts de la licence SDK,
conditions Meta/LinkedIn, dépendance eSpeak de Kokoro, Google Business Messages retiré, sollicitation
neutre d'avis Google et NumPy Financial actuel incompatible avec le minimum Python 3.11.

## Appréciation du travail de Claude

L'audit a comparé l'ancienne révision `fcb65bcf` et la récente `2e56c0d`. La récente est la base
utile : fork, contrats, données métier, approbations, cascade terrain, mémoire et mobile. Les
tests et la structuration constituent un travail substantiel ; refaire tout perdrait cette valeur.
Les trailers Git attribuent le travail à Claude/Opus, sans authentifier le modèle réellement exécuté.

La fiabilité du produit est moins avancée que ne le suggèrent certains labels et cases cochées.
L'audit récent contient 47 constats : 14 P1, 30 P2, 3 P3, avec préconditions et reproductions.
Les suites vertes ne couvrent pas tous les invariants d'autorité, cible métier, finance, stock,
mémoire, reprise mobile ou restauration. Corriger ces frontières avant d'ajouter agents/connecteurs
est le meilleur usage de cette base. Ce jugement porte sur les résultats vérifiables du dépôt.

## Vérification et limites du présent lot

[VERIFICATION-RESTRUCTURATION](../research/R16-2026-09-30/VERIFICATION-RESTRUCTURATION.json)
contient les contrôles de liens locaux, JSON/TOML, sous-périmètres, 47 constats conservés,
CODEOWNERS, provenance d'import et empreintes du diff. `git diff --check` passe ; le test ciblé
existant `tests/test_taxonomie_plaintes.py` a passé ses 38 cas pendant ce lot. Ce test ne valide
pas les nouvelles capacités décrites dans les plans.

Les 18 815 tests passés, 78 sautés, CI core/mobile vertes, expiration CI socle et gates rouges
sont les preuves datées de l'audit précédent, pas des exécutions du lot documentaire. G01 est
corrigé localement par les chemins CODEOWNERS ; 46 constats restent ouverts, plus ECO-001/MKT-001.
Les protections de branche GitHub et la CI du diff n'ont pas été modifiées ni exécutées.

## Suite prévue au lot documentaire initial (historique R16)

Le [plan de restructuration](RESTRUCTURATION-2026-09-30.md) ordonne les lots 1–7 : autorité/cible,
facture et stock idempotents, confidentialité/reclassement mémoire, restauration/mobile ; puis
profils d'agents/budgets, M10 et profondeur métier. ECO-001 suit le générateur encore LiteLLM alors
que les providers natifs sont la cible : l'installateur local demande une gateway qu'il n'installe
pas. Une installation sans gateway supplémentaire doit être démontrée, avec migration et repli.

Le lot de direction/recherche est livré ; ces lots d'implémentation et la validation finale VPS
restent à exécuter. Aucun label de complétion fonctionnelle n'est promu par ce bilan.

## Reçus root postérieurs au jalon R12 — R13 (1er octobre 2026, 10:14 UTC)

Cette mise à jour ajoute des vérifications closes après le jalon documentaire R12 de 09:34 UTC. Elle ne modifie ni les 47 IDs ni leurs statuts de registre. Les compteurs de suites distinctes restent séparés. La lecture root du manifeste R20 a validé les 862 archives, les 336 liens README, les sources et hashes, sans erreur, et les deux hashes scellés de R19 ([lecteur indépendant](../research/R20-2026-10-01/preuves/r20-independant-root-r12-2026-10-01.json.gz)). Cette vérification d’archives ne compte pas comme un test produit.

Root a promu à 10:03–10:09 UTC les patches M5.4.c (neuf chemins), M10 E09 (quatre chemins de code) et son document (un chemin), observatoire/admission (quatre chemins) et bootstrap Compose (sept chemins). Les reçus nomment les hashes source par patch : [M5.4.c](../research/R20-2026-10-01/preuves/m54c-paie-sources-integration-root-r1--resultat.json.gz), [M10 E09](../research/R20-2026-10-01/preuves/m10-e09-integration-root-r1--resultat.json.gz), [observatoire/admission](../research/R20-2026-10-01/preuves/admission-observatoire-integration-root-r1--resultat.json.gz) et [bootstrap Compose](../research/R20-2026-10-01/preuves/permissions-compose-integration-root-r1--resultat.json.gz). La promotion de M5.4.c confirme l’intégration d’un inventaire versionné de références ARC T4127 et Revenu Québec, pas un moteur de retenues. La revue documentaire en lecture seule rapproche sept captures RQ de leurs SHA du catalogue; les deux nouveaux PDF ARC (éditions 122 et 123) ont des SHA différents de ceux conservés dans le catalogue depuis R16. Les neuf entrées restent `NON_QUALIFIEE`; aucun intervalle, vecteur ou calcul n’est validé.

La campagne root M5/M10/admission passe **3 294/3 294**, 0 échec/erreur/skip, en 239,031 s, sur **1 099 chemins stables** : 2 127 cas M5, 968 M10 et 199 socle. Son JUnit inclut les cas PostgreSQL M10 sélectionnés et quatre scénarios d’admission réels; cette suite de test locale ne vaut pas preuve de service PostgreSQL distant. Le [résultat](../research/R20-2026-10-01/preuves/m5-m10-admission-integres-root-r1-2026-10-01-resultat.json.gz) et le [JUnit](../research/R20-2026-10-01/preuves/m5-m10-admission-integres-root-r1-2026-10-01.xml.gz) donnent la commande et les cas. E09 a séparément réussi **15/15 vérifications** après écriture puis lecture dans deux processus sur une base SQLite fictive durable. Cette expérience porte sur un corpus fixé et une seule source; `confirmed` et ses assertions de contenu restent non vérifiés indépendamment. Elle ne mesure pas le rappel général et ne s’ajoute ni à E05, ni aux 968 tests M10. Voir le [rapport E09](../research/R20-2026-10-01/preuves/rapport-final-r1.md.gz), son [résultat](../research/R20-2026-10-01/preuves/verify-result.json.gz) et la [lecture root indépendante des 22 artefacts](../research/R20-2026-10-01/preuves/m10-e09-persisted-lecteur-root-r1-2026-10-01.json.gz), qui relève SHA bundle `f411d2e4…`, zéro erreur et `integrity_check: ok`; ce lecteur n’a pas rejoué les assertions.

La vérification de permissions/bootstrap root passe **286/287** avec un skip, en 160,989 s, sur **1 115 chemins stables**. Le skip provient de l’absence d’`actionlint`. Le cas d’écrivain Core→Python vérifie les modes 700/600 et EUID 1000 dans le parcours local. Le cas d’ancien propriétaire de volume simule les métadonnées et ne construit pas une image Docker ni un VPS. La première commande r1 a collecté zéro test et quitté avec le code 4 à cause d’un chemin invalide; cet incident de commande reste conservé séparément et n’est pas un échec produit. Voir le [résultat r2](../research/R20-2026-10-01/preuves/permissions-bootstrap-integres-root-r2-2026-10-01-resultat.json.gz) et le [JUnit r2](../research/R20-2026-10-01/preuves/permissions-bootstrap-integres-root-r2-2026-10-01.xml.gz).

`opsys-metier verifier` a ensuite validé **10 départements, 203 outils et 116 outils déclarés aux appareils**, exit 0, avec 1 115 chemins stables; cette commande contrôle le catalogue et ne compte pas des tests. Ruff r2 a signalé trois `I001`; la correction suivante a ajouté seulement des lignes de séparation autour des imports dans trois fichiers, avec AST identique. Ruff r3 passe ensuite, exit 0, sur les mêmes 1 115 chemins. Aucun test fonctionnel n’a été relancé pour cette seule mise en forme. Les reçus de vérification et Ruff sont référencés dans le manifeste R13.

Les réservations d’admission ne sont pas libérées automatiquement par l’interface; leur rapprochement ou libération suit les commandes et contrôles explicites. Le dossier brut reste préparatoire : pas de retenues QC, cotisations, calcul net, paiement, déclaration officielle ou homologation. La qualification des références et des vecteurs de paie reste à compléter; aucune revue CPA n’est engagée. Une revue professionnelle est à prévoir avant les actions officielles, sans bloquer les analyses préparatoires autorisées. La réconciliation des agents et la qualification complète du sandbox Compose restent hors de cette actualisation R13. Les cas PostgreSQL ENOSPC et résultats incomplets antérieurs du socle restent conservés dans leurs preuves R12; ils ne sont pas réécrits en succès par ces suites ciblées.


## R14 — preuves root closes au 1er octobre 2026, 11:58 UTC

Cette mise à jour conserve les décomptes de chaque campagne à part et les 47 identifiants du registre. Elle ne constitue pas une commande globale verte ni une preuve d’exploitation VPS.

Le contrôle de manifeste `opsys-metier verifier` reconnaît **10 départements, 204 outils et 116 outils pour appareils** (exit 0; 1 116 chemins stables). La suite M5/admission/jetons R2 passe **2 316/2 316** (2 128 M5 et 188 socle), sans erreur ni skip, en 193,837 s; ses 1 120 chemins sont identiques avant/après. La tentative R1 est conservée séparément : 2 273 réussites et un échec lexical. Le correctif de retour de trace a sa propre suite de 21/21 réussites. La campagne R2 corrige le rouge précédent sans fusionner les compteurs.

La suite M1 de réutilisation STT passe séparément **1 628/1 628**; un parcours ciblé de normalisation et rejeu passe **47/47**. Ces tests bornés ne démontrent pas une exécution exactly-once face à toute panne, concurrence ou reprise. Ruff passe aussi sur `src`, `tests` et `departments` (exit 0, 1 120 chemins stables), sans relance de tests fonctionnels. Le cas `actionlint` passe **1/1** après présence effective de l’outil; cela remplace le skip antérieur dans ce cas ciblé, sans requalifier la suite bootstrap de R13.

Sur PostgreSQL 17 éphémère avec données fictives, la migration `0014 → 0015` convertit onze colonnes de compteurs réparties sur cinq tables de `INTEGER` vers `BIGINT`, conserve huit lignes préexistantes et chaque champ présent, et passe le contrôle d’idempotence. Une admission au-delà de 32 bits est enregistrée puis la suivante est refusée quand la limite est atteinte. La preuve de concurrence commence près de la borne positive 64 bits : deux incréments d’usage concurrents donnent une acceptation et un refus, et l’agrégat Python exact est `18446744073709551615`; plusieurs valeurs de mauvais type sont refusées avant écriture. Le retour de ligne PostgreSQL du `UPSERT` utilise `RETURNING`; un résultat antérieur `rowcount=-1` est gardé comme reproduction rouge, pas comme preuve finale. Ces essais ne portent pas sur un fournisseur, une facture, une dépense réelle ni un service PostgreSQL distant.

Les preuves, commandes et portées restent distinctes : [suite M5/admission/jetons R2](../research/R20-2026-10-01/preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01-resultat.json.gz), [JUnit R2](../research/R20-2026-10-01/preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01.xml.gz), [R1 historique](../research/R20-2026-10-01/preuves/r14-preuves--m54d-admission-integres-root-r1-2026-10-01-resultat.json.gz), [correction de trace 21 cas](../research/R20-2026-10-01/preuves/r14-preuves--admission-trace-retour-root-r1-2026-10-01-resultat.json.gz), [M1 STT 1 628 cas](../research/R20-2026-10-01/preuves/r14-preuves--m1-reutilisation-stt-integres-root-r1-2026-10-01-resultat.json.gz), [normalisation/rejeu 47 cas](../research/R20-2026-10-01/preuves/r14-preuves--m1-normalisation-rejeu-root-r1-2026-10-01-resultat.json.gz), [migration PostgreSQL R2](../research/R20-2026-10-01/preuves/r14-preuves--budgets-pg64-migration-root-r2-2026-10-01-resultat.json.gz), [concurrence 64 bits](../research/R20-2026-10-01/preuves/r14-preuves--jetons-pg-concurrence-root-r1-2026-10-01-resultat.json.gz), [retour `RETURNING`](../research/R20-2026-10-01/preuves/r14-preuves--pg-upsert-rowcount-root-r1-2026-10-01-resultat.json.gz), [actionlint 1 cas](../research/R20-2026-10-01/preuves/r14-preuves--actionlint-installer-root-r1-2026-10-01-resultat.json.gz), et [catalogue à 204/116](../research/R20-2026-10-01/preuves/r14-preuves--m54d-verifier-root-r1-2026-10-01-resultat.json.gz).

Le document [Économie des jetons R1](../architecture/ECONOMIE-TOKENS.md) a été promu sur un chemin au jalon 11:58:08 UTC. Il précise que le SHA-256 de clé contribue au digest final; aucune empreinte isolée n’est persistée. Cette promotion documentaire ne vaut pas validation générale du dispatch. Reçu de promotion : [résultat](../research/R20-2026-10-01/preuves/r14-economie-tokens-doc-integration-root-r1--resultat.json.gz), [préparation](../research/R20-2026-10-01/preuves/r14-economie-tokens-doc-integration-root-r1--preparation.json.gz), [patch](../research/R20-2026-10-01/preuves/r14-economie-tokens-doc-integration-root-r1--patch.diff.gz), [manifest root](../research/R20-2026-10-01/preuves/r14-economie-tokens-doc-r3-root--manifest-root.json.gz), et [carte des liens](../research/R20-2026-10-01/preuves/r14-economie-tokens-doc-integration-root-r1--liens.json.gz).

Rootless R2 est figé mais n’est pas encore promu ni qualifié par root; le dispatch TOCTOU reste candidat. La qualification VPS n’est pas incluse. Ruff est indiqué plus haut et reste un contrôle statique, sans relance fonctionnelle.

Aucun calcul de retenues, cotisations, net, DAS ou paiement n’est couvert.


## R15 — préflight rootless local promu, portée bornée (1er octobre 2026, 12:12 UTC)

Root a promu le lot rootless R3 sur quatre chemins : overlay Compose, préflight Python, tests et guide serveur. La suite `tests/test_deploy_rootless.py` passe 69/69, zéro échec/erreur/skip, en 0,959 s; 1 124 chemins de l’ensemble de sources surveillées demeurent identiques. Ruff sur le module et sa suite passe séparément avec exit 0, également sur 1 124 chemins. Le reçu de promotion donne quatre états antérieurs `null` : ces chemins n’existaient pas avant la promotion et aucune préimage de contenu n’est revendiquée. Les résultats archivés sont le [reçu de promotion](../research/R20-2026-10-01/preuves/r15-rootless-integration-root-r1--resultat.json.gz), le [résultat de qualification](../research/R20-2026-10-01/preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01-resultat.json.gz), son [JUnit](../research/R20-2026-10-01/preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01.xml.gz) et son [log](../research/R20-2026-10-01/preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01.log.gz), ainsi que le [résultat Ruff](../research/R20-2026-10-01/preuves/r15-preuves--rootless-ruff-root-r1-2026-10-01-resultat.json.gz) et son [log Ruff](../research/R20-2026-10-01/preuves/r15-preuves--rootless-ruff-root-r1-2026-10-01.log.gz).

Le profil généré exige une empreinte SHA-256 de clé hôte SSH et porte `version=2`. La réponse de génération conserve `runtime_verifie=false`. Le préflight réussi peut rendre `preflight_verifie=true`, mais garde `runtime_sandbox_verifie=false` et `vps_qualifie=false`. Dans les tests locaux, les octets de la configuration SSH, l’hôte connu et l’empreinte épinglée sont comparés avant l’appel du runner Docker/SSH; les variantes ProxyCommand, nom d’hôte ou clé divergents sont refusées avec zéro appel. Le runner conforme est une fixture synthétique. Les tests et guides comprennent des helpers Docker internes, mais aucun daemon rootless réel, conteneur de service, échange SSH ou VPS n’a été exercé. Le guide [SERVEUR-ROOTLESS](../ops/SERVEUR-ROOTLESS.md) détaille les prérequis.

Après l’append R15, R20 contiendra **1 057 archives**. Le [reçu d’append R14](../research/R20-2026-10-01/preuves/r15-r20-append-r14-root-capture--append-r14-receipt.json.gz) et le [lecteur indépendant R14](../research/R20-2026-10-01/preuves/r15-preuves--r20-independant-root-r14-2026-10-01.json.gz) vérifient la base de 1 035 archives; la [revue root de cohérence R14](../research/R20-2026-10-01/preuves/r15-programme-r14-revue-root-r1--coherence.json.gz) confirme quatre documents et 199 liens locaux.

C01 reste **PARTIEL**. Ces changements et tests ne prouvent pas un démarrage réel, le comportement runtime complet, l’image serveur, la révocation pendant un déploiement, une passerelle avec modèle ni l’isolation SaaS. Le lot TOCTOU runtime de six chemins est encore candidat : il attend sa révision corrigée, la preuve fermée et la revue root; il n’est pas inclus dans ce jalon. Aucun statut du registre n’est modifié.
