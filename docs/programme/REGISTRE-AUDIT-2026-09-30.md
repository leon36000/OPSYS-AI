# Registre complet des constats — audit du 30 septembre 2026

## Complément R22 — périmètres nouveaux qualifiés localement

Les 47 IDs et leurs états historiques restent inchangés. Le [bilan R22](REPRISE-BILAN-2026-10-02.md) qualifie la configuration STT durable, le pilote CSV privé/chiffré et sa provenance M10, la trace de durée M3 et l’extension C02 à `m3_creer_devis`. C02 reste **PARTIEL** : neuf mutations ont une cible explicitement qualifiée, pas toutes les capacités du catalogue. Les coûts d’un devis ne deviennent pas fiables par la seule émission d’un ticket.

ROOT a vérifié 467 cas Python et, séparément, 405 cas Core, sources sélectionnées stables et contrôles de qualité verts. PostgreSQL, fournisseurs réels, voix/avatar, VPS et amélioration des estimations sur données réelles restent hors de cette qualification. Les rouges et limites sont conservés dans [R22](../research/R22-2026-10-02/README.md); ces résultats ne s’ajoutent pas aux comptes des campagnes précédentes.

Base d’audit : `2e56c0d5605dfe575bde9244f38924d5390f2674`. Les **47 constats et leurs IDs** sont conservés sans fusion ni suppression; DEP-009 reste attribué à M10. Le statut est maintenant fondé sur les preuves visibles sur la branche, pas sur l’historique « tous ouverts » du registre précédent.

État mécanique au R17 : **42 CORRIGÉ LOCAL, 5 PARTIEL, 0 OUVERT, 0 À VÉRIFIER**. « Corrigé local » signifie qu’un test et le code couvrent le comportement visé sur l’environnement local; cela ne certifie ni la production ni toute la surface du département. « Partiel » conserve une limite documentée. « Corrigé local » ne certifie ni un module entier ni une intégration réelle.

Le [registre de preuves JSON R17](../research/R17-2026-09-30/ETAT-CONSTATS.json) donne pour chaque ID le rapport auteur éventuel, les sources/tests précis, la portée et le statut de vérification indépendante. Les suites mentionnées dans les rapports auteurs sont distinguées des preuves root indépendantes. Les preuves nommées pour M3 et Core sont conservées avec date et SHA-256 dans le JSON. R17 n’a pas exercé les systèmes distants.

Sources d’audit initiales : [JSON R16](../research/R16-2026-09-30/audit/CONSTATS-RECENTS.json), [core](../research/R16-2026-09-30/audit/core.md), [départements](../research/R16-2026-09-30/audit/departements.md), [données](../research/R16-2026-09-30/audit/donnees.md), [infra](../research/R16-2026-09-30/audit/infra.md), [mobile](../research/R16-2026-09-30/audit/mobile.md).

Une clôture ultérieure exige une preuve ciblée, l’état persistant après parcours, les limites et une décision de clôture explicite. Aucun statut local ne vaut validation d’intégration réelle.

| ID | Niveau | Constat | État R17 |
|---|---|---|---|
| DEP-001 | P1 | Collision de facture et créance masquée | CORRIGÉ LOCAL |
| DEP-002 | P1 | Identité de destinataire privé M10 fournie par l’appelant | CORRIGÉ LOCAL |
| DEP-003 | P1 | Ancien chemin M6 : WCT affirmé, mauvaise intervention et rejeu | CORRIGÉ LOCAL |
| DEP-004 | P2 | Pauses après départ et durée WCT négative sous revue | CORRIGÉ LOCAL |
| DEP-005 | P2 | Retrait marketing antérieur au WCT sans rattachement ultérieur au lead | CORRIGÉ LOCAL |
| DEP-006 | P2 | Consolidation journalière ne couvrant pas les événements tardifs | CORRIGÉ LOCAL |
| DEP-007 | P2 | Texte nan converti en métrique sans alerte qualité | CORRIGÉ LOCAL |
| DEP-008 | P2 | Contradiction masquée par représentations temporelles équivalentes | CORRIGÉ LOCAL |
| DEP-009 | P2 | WCT changé dédupliqué sans conflit de contenu | CORRIGÉ LOCAL |
| DEP-010 | P2 | Conversation forgée acceptée sans historique canonique | CORRIGÉ LOCAL |
| DEP-011 | P2 | Primitive M7 : auteur et contenu approuvés depuis objet mutable | CORRIGÉ LOCAL |
| DEP-012 | P2 | Script injectable par couleur CSS de configuration locale | CORRIGÉ LOCAL |
| DEP-013 | P2 | Seuil photo NaN permissif au répartiteur Python | CORRIGÉ LOCAL |
| DEP-014 | P2 | Exactitude financière dépendante du contexte Decimal ambiant | CORRIGÉ LOCAL |
| DEP-015 | P3 | Débordement numérique M3 et exception publique non nommée | CORRIGÉ LOCAL |
| DEP-016 | P3 | Montant extrême M5 et exception Decimal non nommée | CORRIGÉ LOCAL |
| DEP-017 | P3 | Chaîne vide validée malgré ancre extérieure non vide | CORRIGÉ LOCAL |
| DON-01 | P1 | Autorisations et révocation console insuffisantes | CORRIGÉ LOCAL |
| DON-02 | P1 | Restauration échouée sans retour cohérent | CORRIGÉ LOCAL |
| DON-03 | P1 | Révision déclarée non comparée à la base réelle | CORRIGÉ LOCAL |
| DON-04 | P2 | Import historique interrompu non repris automatiquement | CORRIGÉ LOCAL |
| DON-05 | P2 | Artefact lisible depuis autre département connaissant son ID | CORRIGÉ LOCAL |
| DON-06 | P2 | Déduplication RAG reclassant fragment et rétention après ajout approuvé | CORRIGÉ LOCAL |
| MOB-01 | P1 | Captures de A transformées et envoyées au nom de B | CORRIGÉ LOCAL |
| MOB-02 | P1 | Accusé WCT utile non persisté hors écran | CORRIGÉ LOCAL |
| MOB-03 | P2 | Reprise serveur non réconciliée avec état fichier local | CORRIGÉ LOCAL |
| MOB-04 | P2 | Enfilage partiel des blocs non réparable | CORRIGÉ LOCAL |
| MOB-05 | P2 | Préparations concurrentes et indices dupliqués | CORRIGÉ LOCAL |
| MOB-06 | P2 | Timeout ne couvrant pas lecture du corps HTTP | CORRIGÉ LOCAL |
| MOB-07 | P2 | Corps HTTP 200 interrompu traité comme échec permanent | CORRIGÉ LOCAL |
| MOB-08 | P2 | Session changée pendant purge non revalidée après attente | CORRIGÉ LOCAL |
| MOB-09 | P1 | Accusé métier inconnu accepté | CORRIGÉ LOCAL |
| INFRA-R01 | P1 | Noms incompatibles des archives de volumes backup/restore | CORRIGÉ LOCAL |
| INFRA-R02 | P1 | Garde de désinstallation textuelle et chemins physiques protégés | CORRIGÉ LOCAL |
| INFRA-R03 | P1 | Contexte image pouvant inclure sauvegardes et secrets locaux | CORRIGÉ LOCAL |
| INFRA-R04 | P2 | Backup et restore positifs malgré éléments requis manquants | CORRIGÉ LOCAL |
| INFRA-R05 | P2 | Modèle env VPS requis absent du dépôt | PARTIEL |
| INFRA-R06 | P2 | Permissions des sauvegardes conditionnellement publiques sur hôte | CORRIGÉ LOCAL |
| INFRA-R07 | P2 | Gate Python et absence de CI générale complète au HEAD | PARTIEL |
| INFRA-R08 | P2 | Avis de sécurité npm et absence de scan dans workflows racine | PARTIEL |
| INFRA-R09 | P2 | Installations Python et outils sans verrou reproductible | CORRIGÉ LOCAL |
| C01 | P1 | Frontière CLI humain/agent reposant sur environnement effaçable | PARTIEL |
| C02 | P1 | Garde contexte non liée à cible des arguments métier | PARTIEL |
| C03 | P2 | Configuration sélectionnée invalide ouvrant la garde | CORRIGÉ LOCAL |
| C04 | P2 | Démarrage long inclus dans durée saine de reprise | CORRIGÉ LOCAL |
| C05 | P2 | Documentation de référence non réconciliée avec architecture | CORRIGÉ LOCAL |
| G01 | P2 | CODEOWNERS conserve les anciens chemins | CORRIGÉ LOCAL |
Preuve G01 : [vérification du lot](../research/R16-2026-09-30/VERIFICATION-RESTRUCTURATION.json),
cibles existantes de CODEOWNERS et diff de branche. La correction locale ne modifie pas les
protections de branche du dépôt hébergé et n'a pas été fusionnée.

## Écarts supplémentaires relevés pendant la restructuration

**ECO-001 — installation autonome / providers.** Le chemin actuel sélectionne les fournisseurs natifs par défaut; LiteLLM exige le mode explicite et une URL. Les rapports `installation-native-resultat.md` et `core-native-profils-cli-resultat.md` consignent les tests locaux et le refus d’URL seule. Statut corrigé localement, hors des 47 IDs. Aucun appel fournisseur, build Core complet ou déploiement VPS n’a été exercé.

**MKT-001 — sélection des demandes d’avis.** La demande actuelle est neutre et dépend du consentement; le harnais couvre les cas satisfait, insatisfait et non évalué sans sélectionner les positifs. `harnais-identite-avis.xml` contient 49 tests passés le 2026-09-30 à 17:40:36 UTC. Statut corrigé localement, hors des 47 IDs; aucun avis externe n’a été sollicité.

## Preuves R17 et portée

- DEP-003 et DON-06 : rapport auteur [DEP003-DON06-resultat.md](/workspace/restructuration-opsys-2026-09-30/DEP003-DON06-resultat.md). Il rapporte les tests M6 et un probe PostgreSQL 17 + pgvector éphémère, avec données fictives. Aucun rejeu root indépendant de ces parcours n’est revendiqué.
- DEP-005 et DEP-011 : rapport auteur [DEP005-011-resultat.md](/workspace/restructuration-opsys-2026-09-30/DEP005-011-resultat.md), suite complète M7 rapportée passante; aucun effet externe n’a été exécuté.
- DEP-013/015 : preuve root `preuves/m3-numerique-public.xml`, 172/172 le 2026-09-30 à 18:06:12 UTC; mutations photos 15/15 et Monte Carlo 10/10. Les deux mutations de bornage déclarées inertes sont seulement observées comme telles sur ce harnais.
- C03/C04 : preuve root `preuves/core-frontieres.json`, 244/244; tests ciblés de configuration/garde et de superviseur. C01 reste partiel à cause de la frontière du compte OS; C02 reste partiel; C05 conserve les écarts documentaires.
- APR-001 est suivi comme écart supplémentaire, hors des 47 IDs : preuve root `preuves/approbations-verdict-integration.xml`, 47/47 le 2026-09-30 à 17:34:35 UTC; un verdict métier refusé imbriqué n’est plus tracé comme exécuté.

Les SHA-256 des preuves root et rapports auteurs utilisés sont consignés dans [ETAT-CONSTATS.json](../research/R17-2026-09-30/ETAT-CONSTATS.json). Les déploiements VPS, la CI distante et le build de l’image Docker officielle Core ne sont pas validés. L’artefact Docker QA est distinct et ne constitue pas cette preuve.

## Raccords supplémentaires R19, hors du décompte initial

- **C01 : garde intégrée, frontière OS encore partielle.** Le générateur et Core imposent désormais
  un sandbox pour les agents OPSYS, y compris `main` et les anciennes sessions optées-out.
  Les refus de cible hôte, d'absence de session et de configuration relâchée sont testés;
  la génération Python a passé 153 cas et Core élargi 101, incluant les 63 anciens cas. Les
  25 observations TypeScript passent (neuf graphes R1 non affectés + seize R2), sans revendication
  d'une commande globale unique. Les corrections de typage de nos fixtures gardent les assertions.
  Les installateurs intégrés vérifient le daemon Linux et construisent l'image standard si elle
  manque; ces tests installateurs locaux emploient un Docker factice. La qualification C01 r4
  a ensuite construit l'image sandbox standard et lancé bash par les factories TS natives
  `resolveSandboxContext` et `createExecTool(...).execute(...)`, en session/configuration synthétiques
  sous la garde OPSYS. [Résultat r4](../research/R20-2026-10-01/preuves/c01-os-sandbox-run-2ec9a897-a635-4302-aa31-301822bf1766.json.gz)
  et [lecteur root](../research/R20-2026-10-01/preuves/c01-os-sandbox-lecteur-root-r1-2026-10-01.json.gz) :
  UID/GID 1000, root RO, réseau `none`, NNP=1, seccomp=2, capabilities effectives nulles; deux
  montages Core privés, workspace RW et skills RO, aucun bind supplémentaire configuré ni
  montage du workspace hôte synthétique. Marqueur hôte choisi absent et noms `OPSYS_*` fictifs
  retirés explicitement, pas d'épuration automatique universelle démontrée.
  **Le statut C01 PARTIEL et le décompte des 47 constats restent inchangés** : image serveur
  complète, Gateway/tour LLM, SaaS multi-tenant et VPS non qualifiés; vrais E2E Mac/Windows à faire.
  La [chronologie R20 r9](../research/R20-2026-10-01/README.md) conserve r1–r3 rouges. R1 a créé
  et inspecté son conteneur puis rencontré l'erreur de schéma au nettoyage; le récit « avant
  Docker » du rapport brut est contredit par son JSON. Harness r2 exact indisponible; fichier
  de base r1 présent sans empreinte d'exécution prouvant son association. Seul r4 est positif.
- **CI-INSTALL-002 : label de runner privé inconnu du linter.** Le contrôle réel avec le binaire
  `actionlint` 1.7.7 et le hash épinglé de la CI a refusé deux emplois du nouveau label
  `opsys-docker-linux`. La configuration déclare désormais exactement ce label, sans ignorer
  de diagnostic; le contrôle statique passe. La première tentative complète du socle du
  1er octobre a été interrompue après 60 cas et reste un résultat incomplet avec code 1;
  la reprise complète sur sources gelées passe 2 302 cas, avec 83 skips, aucun échec ni erreur;
  1 022 sources et cinq fichiers CI/sandbox complémentaires sont inchangés. Les skips sont
  82 cas PowerShell absent du PATH et un Docker réel. Shellcheck et pyflakes étaient
  indisponibles et explicitement désactivés dans ce contrôle statique séparé.
- **QA-INSTALL-003 : journal incomplet du faux Node.** La reprise PowerShell Linux a trouvé une
  assertion d'ordre cherchant `gateway install` dans un journal que le stub Node n'alimentait pas.
  Le stub journalise désormais son appel; assertions, ordre attendu et code d'installation restent
  inchangés. Après ce correctif de test, les 87 cas ciblés passent sous PowerShell Microsoft 7.6.6,
  en 374,041 s, avec sources copiées comparées à l'actif avant/après. Le résultat initial 86/87
  et les deux reprises interrompues restent distincts. Docker/gateway factices, aucun Windows réel.
- **APR002 : provenance des demandes N4 humaines.** Le patch cumulatif et sa revue indépendante
  de 33 cas ont été intégrés après la capture complète M3, avec identité active et rôle relus en
  base, hash des arguments, journal/demande/idempotence atomiques. Le ciblé actif passe 254/254
  avec 1 022 empreintes identiques avant/après. M2 complet après APR passe 1 795 tests sans skip,
  en 196,855 s, avec 1 022 empreintes identiques; M3 ordinaire après APR passe 2 133 tests avec un
  skip de garde CI; les deux harnais lourds appartiennent à la preuve complète pré-APR. Le patch ne
  change pas les modes N4 existants et n'attribue pas un rôle retiré comme auteur humain.
- **CFO-INT-001 : lecture d'une chaîne altérée.** Le probe root a modifié un montant dans une
  SQLite fictive sans recalculer le hash; le dossier CFO acceptait alors le montant altéré.
  Correction intégrée : vérifier les trois snapshots avant les calculs et refuser sans montant
  ni écriture (`REJ-CFO-CHAINE-INVALIDE`). Suite M5 après correction : 2 028/2 028;
  interfaces CFO : 15/15. Ce contrôle est limité au dossier CFO; un accès privilégié capable de
  réécrire toute la chaîne n'est pas empêché par ses hashes non signés.
- **M4/M5 — jalon ACTIF des sources horaires.** Les heures régulières M4 sont approuvées par
  un humain N4 avec sources recalculées et validation précédente attendue (CAS). M5 conserve
  le contrat salarial individuel privé, son taux CAD déclaré, source/date humaines et contrôle
  de révision/tête attendues; la source déclarée n'est pas un document salarial authentifié.
  Le [JUnit root r3](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r3-2026-10-01.xml.gz)
  passe **4 962 cas : 2 854 M4 + 2 074 M5 + 34 socle CFO**, 0 échec/erreur/skip, en 294,638 s.
  Le [résultat](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r3-2026-10-01-resultat.json.gz)
  conserve 1 033 chemins sélectionnés identiques avant/après; la
  [réconciliation](../research/R20-2026-10-01/preuves/m54-m4-m5-reconciliation-root-r1-2026-10-01.json.gz)
  et la [ventilation](../research/R20-2026-10-01/preuves/m54-m4-m5-ventilation-root-r1-2026-10-01.json.gz)
  sont archivées dans [R20 r10](../research/R20-2026-10-01/README.md). Les cinq écarts de
  catalogue/ordre du [rouge r2](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r2-2026-10-01.xml.gz)
  sont corrigés avec assertions fermées et permissions maintenues; les mêmes 4 962 cas passent.
  L'[erreur de collecte root r1](../research/R20-2026-10-01/preuves/m54-m4-m5-integres-root-r1-2026-10-01-resultat.json.gz)
  reste séparée, sans échec métier. Root a promu le 1er octobre le pont M4→M5, le contrat salarial
  privé et l'interface de brut préparatoire dans l'arbre actif; les preuves R10 décrivent un état
  antérieur. Le run root r1 passe 6 723/6 723 (1 578 M1 +
  2 865 M4 + 2 100 M5 + 180 socle accès/runtime), sans échec/erreur/skip; 1 080 chemins stables
  ([JUnit](../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01.xml.gz),
  [résultat](../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01-resultat.json.gz)).
  La capacité reste limitée au brut régulier, sans QC, retenues/cotisations, net, paiement,
  déclaration ou action. Le diagnostic global M54 r1 compte 303 cas ENOSPC + un rôle fermé corrigé;
  le socle global root r2 s'est terminé en INTERNALERROR ENOSPC (135F/154E/84S), pas vert.
  Le root r3 initial compte 2 478 cas (2 363P/1F/30E/84S), 1 223,835 s et 1 094 chemins sans delta;
  ses 31 cas rouges PostgreSQL mentionnent ENOSPC. La reprise exacte passe 31/31 en 199,136 s;
  l'union unique compte 2 478 cas (2 394P/84S), sans rouge résiduel, mais aucune commande globale
  unique verte. Les preuves précèdent une modification ultérieure de pyproject.toml; aucune campagne
  globale n'est revendiquée pour l'arbre postérieur. Voir [run](../research/R20-2026-10-01/preuves/socle-integre-root-r3-2026-10-01-resultat.json.gz), [reprise](../research/R20-2026-10-01/preuves/socle-reprise-postgresql-root-r1-2026-10-01-resultat.json.gz) et [union](../research/R20-2026-10-01/preuves/socle-union-root-r1-2026-10-01.json.gz).
  Ces suites ne changent pas le statut des 47 IDs ni n'établissent la complétion de M4/M5.
- **Core runtime r2** : [lecteur indépendant](../research/R20-2026-10-01/preuves/runtime-core-lecteur-root-r2-2026-10-01.json.gz), 73 tests sur huit fichiers; le typecheck natif avait fini avant la capture initiale.
- **M7 / bootstrap / forme appareil — intégré root r1.** Le contrôle root passe 1 261/1 261 cas,
  sans échec/erreur/skip, en 73,076 s, avec 1 094 chemins stables avant/après. Il couvre les tests
  M7 et les fichiers CMO/marque/calendrier/performance/paie, bootstrap, instance, profils, rôles,
  canaux et un E2E appareil M4; la portée ne remplace pas le socle complet ([JUnit](../research/R20-2026-10-01/preuves/m7-bootstrap-forme-integres-root-r1-2026-10-01.xml.gz),
  [résultat](../research/R20-2026-10-01/preuves/m7-bootstrap-forme-integres-root-r1-2026-10-01-resultat.json.gz)). Le correctif M4 est
  test-only; CMO porte six chemins et Compose sept. Les fixtures temporaires ont été supprimées et
  aucune archive restaurable n'est conservée. Après ces campagnes, `pyproject.toml` a reçu le réglage
  natif `tmp_path_retention_policy='failed'`; le test bootstrap ciblé sans override passe 29/29 en
  9,027 s sur 1 094 chemins stables ([résultat](../research/R20-2026-10-01/preuves/pytest-retention-bootstrap-root-r1-2026-10-01-resultat.json.gz)).
- **M10-EVAL-001 : rappel borné mesuré.** Le corpus synthétique relève 30 prompts rendus parmi
  32 pertinents et une cible ancienne omise. Précision de cette fenêtre : 30/30; rappel : 30/32;
  rappel de la cible : 0/1. Une réévaluation indépendante après r4 compte 8 scénarios pris en charge
  réussis et 2 non pris en charge; P30/30, R30/32 et cible 0/1 restent seulement comparables aux
  métriques E05 historiques. Ces résultats ne sont pas une mesure générale du rappel ni une preuve
  d'amélioration globale. Les scénarios de permissions inter-domaines et de taxonomie bug/fix dédiée
  restent non pris en charge. Aucun score de non-oubli global n'est attribué.
- **M10-PREFLIGHT-002 : omissions silencieuses et contradiction hors fenêtre.** Le preflight
  intégré conserve 30 `must_know`, annonce ses omissions et cherche les contradictions parmi les
  candidats pertinents avant de borner leur sortie. L'oracle compte 93 preuves disponibles,
  60 rendues et 33 omises. Vérification historique après APR : 948 tests M10, 11 console-jobs et quatre cron
  réussis (963 dans cette commande), 1 022 empreintes identiques. Le rappel lexical n'est pas
  amélioré par ces compteurs; `available` ne signifie pas exhaustif.

- **M10-SEL-003 : sélection structurée et temporelle.** La sélection actuelle emploie les chemins
  structurés, les liens de remplacement stockés et la fraîcheur par hash, avec distinction entre
  cycle et convergence. Elle expose ses omissions aux limites de 30 éléments essentiels,
  30 liens et 1 000 visites. La qualification intégrée passe 974 cas (959 M10 + 11 console-jobs
  + quatre cron), sans échec/erreur/skip, en 38,959 s; les 1 029 sources sélectionnées sont stables.
  La correction d'espacement d'import ultérieure conserve l'AST et passe Ruff global, sans
  revendiquer une nouvelle exécution. Le rappel historique 30/32 et la cible omise 0/1 demeurent
  distincts de cette preuve : aucune promesse de non-oubli exhaustif.
- **QA-SOCLE-004 : reprise complète M5/M10 intégrés.** Le
  [JUnit courant](../research/R20-2026-10-01/preuves/socle-m5-m10-integres-root-r1-2026-10-01.xml.gz)
  compte 2 324 réussites, 84 skips, aucun échec/erreur, en 1 322,698 s. Les 1 037 chemins de
  plusieurs formats sélectionnés sont identiques avant/après. La
  [réconciliation](../research/R20-2026-10-01/preuves/socle-m5-m10-reconciliation-root-r1-2026-10-01.json.gz)
  retrouve les 38 anciens échecs/erreurs en réussite et les 82 skips PowerShell dans l'ancien
  compagnon Linux de 87 réussites. Le skip actionlint est qualifié par une reprise distincte
  d'un cas réussi; le skip Docker par une reprise sur cinq volumes réels, fichiers synthétiques,
  SQL et `compose stop/up` simulés. Ces compagnons ne changent pas le JUnit du socle et ne prouvent
  ni Windows, ni restauration SQL/VPS, ni lancement d'un fournisseur réel.

Les preuves et instantanés restent distincts dans [R19](../research/R19-2026-09-30/README.md).
Ces raccords ne changent pas les 47 IDs ni les cinq statuts partiels d'origine.

**INFRA-R08 — portée mobile actualisée.** L'audit du lock du 1er octobre conserve 13 entrées
de paquets modérées issues de deux advisories, sans modification des dépendances. Le chemin
`xcode` inspecté appelle uniquement UUID v4; le linking Expo Router standard inspecté utilise
`URL.searchParams`. Le parser parallèle qui consomme `query-string` reste disponible, sans
appelant applicatif trouvé. Ces observations bornées ne ferment pas les advisories ni ne
prouvent tous les parcours tiers. Aucun override compatible ou build natif corrigé n'est livré;
[la qualification](../exploitation/MOBILE-DEPENDANCES-2026-10-01.md) conserve sources et limites.

**C05 — références courantes.** Les trois documents signalés (INGREDIENTS, ARCHITECTURE, ADR-0010) décrivent le fork, Expo et le hook réel, avec état courant daté distinct de leur historique. La [revue documentaire](../research/R17-2026-09-30/COHERENCE-DOCUMENTAIRE.md) ferme ce défaut précis; elle ne certifie pas chaque page historique. Les corrections supplémentaires MEM-DEV-001/002, FIN-COUV-001 et CI-ADM-001 restent hors des 47 IDs et sont détaillées dans le JSON R17.

## Addendum R13 — preuves root postérieures, sans changement des 47 constats

Les 47 identifiants, leurs libellés et leurs états ne sont pas modifiés par cet addendum. Les preuves nouvelles prolongent certains périmètres sans fermer des constats supplémentaires. La lecture indépendante root du R20 R12 valide 862/862 archives, 336 liens locaux, zéro source absente/erreur et R19 scellé; ce contrôle porte sur l’archive, pas sur le produit.

- **M5/M10/admission**, reçu root du 1er octobre 10:04:37–10:08:37 UTC : 3 294/3 294, zéro erreur/skip, 239,031 s, 1 099 chemins stables (2 127 M5, 968 M10, 199 socle). Le rapport donne un cas PostgreSQL M10 et quatre tests d’admission; la portée reste celle des fixtures/environnements locaux de la commande.
- **M10 E09**, expérience persistante distincte : 15/15 assertions prédéfinies passent en écriture et lecture SQLite depuis deux processus. Le corpus ne contient qu’une source fictive connue. Le lecteur root indépendant a vérifié 22 artefacts et l’intégrité SQLite (`ok`), sans rejouer le corpus. `confirmed` est une assertion d’auteur non vérifiée; E09 ne mesure pas le rappel général, ne démontre ni mémoire complète ni absence d’oubli, et ne change pas les métriques historiques E05.
- **Permissions/bootstrap** : 286/287, un skip dû à `actionlint` absent, 160,989 s, 1 115 chemins stables; le chemin d’écrivain Core/Python observe EUID 1000 et les modes 700/600. Le test d’ancien propriétaire de volume est une simulation de métadonnées, pas un test d’image/VPS. La commande r1 a collecté 0 test/code 4 car son chemin était inexistant; elle est conservée comme erreur de commande, pas comme résultat métier.
- **Catalogue** : `opsys-metier verifier` au jalon 10:11:19 UTC valide 10 départements, 203 outils et 116 outils appareil, exit 0, sans delta dans 1 115 chemins. Ruff r2 échoue sur trois importations `I001`; après correction de mise en forme AST-identique, Ruff r3 passe sur le même ensemble. Les tests métier n’ont pas été relancés pour le changement formatif.

Les enregistrements du registre R17/R19 restent les seuls porteurs des statuts de constats. L’intégration de neuf chemins M5.4.c atteste la présence d’un catalogue de références ARC/RQ et de captures vérifiées; toutes restent `NON_QUALIFIEE`, avec intervalles et vecteurs restant à qualifier; aucune revue CPA n’est engagée et la validation professionnelle concerne les actions officielles appropriées. Elle ne change pas la portée brute préparatoire du CFO et ne clôt pas un ID. Les réservations UI ne se libèrent pas automatiquement. La qualification des références et vecteurs reste à compléter, sans CPA engagé; la revue professionnelle s’applique avant les actions officielles. La réconciliation des agents et le sandbox Compose restent en cours et hors de cet addendum. Les rouges PostgreSQL ENOSPC de R12 demeurent des résultats distincts et inchangés. Les reçus correspondants sont le [M5/M10/JUnit](../research/R20-2026-10-01/preuves/m5-m10-admission-integres-root-r1-2026-10-01.xml.gz), le [lecteur E09](../research/R20-2026-10-01/preuves/m10-e09-persisted-lecteur-root-r1-2026-10-01.json.gz), le [bootstrap r2](../research/R20-2026-10-01/preuves/permissions-bootstrap-integres-root-r2-2026-10-01-resultat.json.gz) et la [qualification M5.4.d](../research/R20-2026-10-01/preuves/m5-4d-paie-qualification-r1.md.gz).


## Addendum R14 — tests ciblés clos, sans révision des 47 constats

Cet addendum conserve les 47 IDs, descriptions et états du registre. Les nombres suivants sont des résultats par campagne, sans somme artificielle.

- **M5/admission/jetons** : la campagne R2 passe 2 316/2 316 (2 128 M5 + 188 socle), 0 échec/erreur/skip, 193,837 s et 1 120 chemins stables. La R1 2 273P/1F lexicale et le correctif ciblé de trace 21/21 restent des exécutions séparées. Le cas actionlint réussit 1/1 après disponibilité effective de l’outil.
- **M1** : 1 628/1 628 pour la suite de réutilisation STT, puis 47/47 pour normalisation/rejeu. La portée ne démontre pas une garantie exactly-once face à tout crash ou toute concurrence.
- **PostgreSQL** : une migration éphémère 0014→0015 préserve cinq tables, les huit lignes legacy préexistantes et chaque valeur des onze colonnes élargies en `BIGINT`, puis est rejouable. Le contrôle de concurrence près de la borne signée aboutit à un accepté, un refusé et une somme Python exacte de `18446744073709551615`; le retour du `UPSERT` est basé sur `RETURNING`. Les fixtures sont fictives; aucune dépense/provider n’est exercée.
- **Catalogue courant** : 10 départements, 204 outils, 116 outils appareil, commande de vérification séparée.
- **Économie des jetons** : le document `docs/architecture/ECONOMIE-TOKENS.md` est promu sur un chemin; il indique que le SHA-256 de clé participe au digest final et qu’aucune empreinte isolée n’est persistée. Cela ne ferme aucun constat produit.

Les tests PostgreSQL locaux ne démontrent pas un serveur distant ni un déploiement. Rootless R2 est figé mais n’est pas encore promu ni qualifié par root; le dispatch TOCTOU reste candidat. Le VPS demeure hors des preuves closes de ce paquet. Ce prolongement ne ferme aucun ID. Reçus principaux : [M5/admission/jetons R2](../research/R20-2026-10-01/preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01-resultat.json.gz), [M1 STT](../research/R20-2026-10-01/preuves/r14-preuves--m1-reutilisation-stt-integres-root-r1-2026-10-01-resultat.json.gz), [M1 normalisation/rejeu](../research/R20-2026-10-01/preuves/r14-preuves--m1-normalisation-rejeu-root-r1-2026-10-01-resultat.json.gz), [migration PG](../research/R20-2026-10-01/preuves/r14-preuves--budgets-pg64-migration-root-r2-2026-10-01-resultat.json.gz), [concurrence jetons](../research/R20-2026-10-01/preuves/r14-preuves--jetons-pg-concurrence-root-r1-2026-10-01-resultat.json.gz), [vérificateur manifestes](../research/R20-2026-10-01/preuves/r14-preuves--m54d-verifier-root-r1-2026-10-01-resultat.json.gz).
