# M5 — Audit fiscalité, paie et calendrier des obligations

## Actualisation 2026-10-04 — brouillon fournisseur et contrôles M5

Une [vérification privée AP en lecture seule](M5-AP-VERIFICATION-REPRISE-2026-10-04.md)
relie maintenant le brouillon PDF `A_REVOIR` aux contrôles canoniques M5. L'humain
choisit le PO reçu/fournisseur et atteste leur correspondance; le code relit
PDF/citations/révisions, chaîne AP et taux versionnés, puis compare montants et
doublons courants. Aucune dette, facture, validation durable ou écriture n'est
créée. Les **363 tests ciblés ROOT r119** passent sur dix fichiers complets;
droits, révocation au rendu, intégrité et absence d'effet sont vérifiés.

| Sous-capacité M5.2 | État de cette tranche |
|---|---|
| Proposition chiffrée PDF/AP et reprise | Existant conservé, `A_REVOIR` |
| Vérification préalable PO/fournisseur/taxes/total/doublons | QUALIFIÉE LOCAL — SQLite, PDF natif fictif, contrôle explicite privé |
| Saisie AP depuis Fusion avec provenance et approbation | À CONSTRUIRE — parcours séparé, aucune dette créée ici |
| OCR/image, factures réelles représentatives, ingestion massive | PARTIEL / À QUALIFIER |

La CI de la tranche doit être suivie sur son propre commit. M5 complet, fiscalité
officielle, paie et CFO ne sont pas certifiés par cette vérification.

## Actualisation R22 — import bancaire préparatoire

Le [pilote Fusion CSV](../../architecture/FUSION-CSV.md) réutilise le parseur et les propositions M5 existants. La source et le résultat normalisé sont chiffrés, les tranches de 100 lignes reprenables et les snapshots M5 revalidés avant chaque traitement et lecture terminale. Un snapshot périmé masque les propositions; aucun rapprochement, journal, paiement ou écriture fiscale n’est appliqué. L’interface est privée admin/owner, avec identité vivante et CSRF pour les mutations.

Les 19 cas Fusion et les tests M5 concernés passent dans la [campagne ROOT R22](../../research/R22-2026-10-02/README.md) de 467 cas Python. Ce résultat qualifie le pilote SQLite, pas PostgreSQL, ni la paie ou l’ensemble CFO. La préparation multi-tranches en une action est le lot suivant; R22 nécessite encore une action par tranche. Les validations humaines des actions réelles restent requises.

Date de l’audit initial : 2026-09-30; actualisé le 2026-10-01. Portée : état réel du département M5 et tranches préparatoires décrites ici. Les ambitions CFO M5.1–M5.20 restent celles du [périmètre produit](../../../docs/produit/PERIMETRE-MODULES.md); ce rapport ne certifie pas le M5 complet.

## Audit de l’existant

M5 sait calculer les taxes de vente à partir des taux versionnés de [taux_fiscaux.v1.yaml](../../../departments/m05-financecore/contracts/taux_fiscaux.v1.yaml) et traiter le calendrier TPS/TVQ avec [calendrier_fiscal.v1.yaml](../../../departments/m05-financecore/contracts/calendrier_fiscal.v1.yaml). Ce dernier contient des tables datées 2025 et 2026, leurs sources officielles, versions et dates de consultation; elles portent toutes le statut `A_VALIDER` par le CPA. L’outil existant `m5_lire_echeances_fiscales` réutilise les échéances transcrites et calcule le net des taxes à chaque échéance. Une année absente du contrat est refusée : aucune règle n’extrapole les dates 2027.

Les deux taux actuellement configurés sont TPS 5 % et TVQ 9,975 %, version `2026-v1`. Le contrat identifie la source institutionnelle, mais n’encode pas l’intervalle d’effet ni un hash de la publication; ces éléments doivent être renforcés avant d’élargir ou d’automatiser les mises à jour de taux.

Le brouillon de brut régulier individuel est livré (M5.4 et pont M4, voir les tranches ci-dessous). Le calcul des retenues/cotisations, le net, les cumuls fiscaux et la paie réelle restent à construire et qualifier; aucun moteur de paie complète n’est livré. Le cash libre lit les composantes `paies`, `das` et `dettes` dans `configuration.obligations_declarees`, avec montant, source et date déclarés par le propriétaire; absent ou invalide, le montant est inconnu. La prévision utilise les dates explicites `configuration.prevision.echeances_obligations`, mais ne portait jusque-là aucune métadonnée de période, d’autorité, de source/version ou de validité de la date. M4 conserve des durées de travail sans montants salariaux; le coût réel M5 calcule les minutes WCT multipliées par un taux horaire d’équipe déclaré. Ce coût de chantier ne constitue pas la paie réelle ni les cotisations employeur.

L’inventaire R16 et les fichiers de preuve sont conservés dans [recherche-m5.md](../../../docs/research/R16-2026-09-30/recherche-m5.md) et [m5-preuves.json](../../../docs/research/R16-2026-09-30/m5-preuves.json). Les empreintes historiques `fe89856203fec4252ae6f7447d2ac368e2a608c680be2015e4bd200356da485c` et `cbd818498f172c7ec16b97acf06d29cfb5e74f5663edbb6d343894a756418c9d` désignent les pages HTML sauvegardées sous `preuves-m5/officiel/7.html` et `8.html`; elles ne sont pas les empreintes des PDFs T4127. Une capture documentaire root du 1er octobre vérifie par hash 21 éléments, dont les neuf PDFs annoncés : les deux PDFs ARC T4127 ont respectivement les SHA-256 `c715b8e6d33e0887119e0462b9a4cf8915370c56381932f1d7ba3a32385ddd8c` et `69d86d952cb14c786fdcc0321ec293f66db1529276ef310217b3ade47db25671`; sept PDFs RQ sont aussi capturés. Toutes ces entrées restent `NON_QUALIFIEE`. La comparaison établit une différence d’octets entre anciennes pages HTML et nouveaux PDFs, pas la validité juridique des règles, l’exhaustivité des tables ou une licence de redistribution. Les pages de source RQ testées ont répondu 403; ce résultat ne prouve ni leur absence ni leur obsolescence. Aucun barème QC, CNESST, CCQ, RE ou fichier RL-1 ne doit être codé sur cette seule base; aucune licence ou autorisation d’usage des barèmes n’est qualifiée.

## Tranche livrée

`m5_lire_calendrier_obligations` (T0, lecture seule) rend les trois lignes fixes `paies`, `das` et `dettes`. Il reprend les montants/sources canoniques des obligations déclarées, les dates de prévision déjà consommées par M5, et les nouvelles métadonnées de `configuration.calendrier_obligations`. Le contrat [calendrier_obligations.v1.yaml](../../../departments/m05-financecore/contracts/calendrier_obligations.v1.yaml) exige l’autorité, les bornes de période, la référence de la source d’échéance, la date de consultation, sa fenêtre de validité, l’année et la version.

Les données manquantes produisent une ligne `INCOMPLETE` avec des verdicts nommés; aucun montant, taux, autorité, période, échéance ou fréquence n’est inventé. Une fenêtre déclarée qui ne couvre pas toute la période rend la ligne `SOURCE_PERIMEE` et son `montant_utilisable` nul, tout en laissant le montant brut et sa provenance visibles. Il n’y a pas de durée de fraîcheur arbitraire : la validité repose sur les dates explicitement déclarées par la source. Une date échue devient `ECHEANCE_PASSEE_A_VERIFIER`; elle ne signifie pas qu’un versement ou une déclaration manque.

L’outil compose cette projection avec le calendrier TPS/TVQ existant. Son argument `aujourd_hui` est requis; `limite`, `role` et `autorise_couts` sont optionnels et le schéma refuse les propriétés supplémentaires. Si les taxes ne sont pas calculables, le sous-résultat TPS/TVQ l’indique sans masquer les lignes paie/DAS/dettes. Les appelants sans droit de voir les coûts reçoivent les montants masqués. La réponse porte la mention d’analyse préparatoire et ses limites. La garde AST `verifier_aucun_decaissement` surveille désormais intégralement le module pur et l’adaptateur; les tests vérifient le mode T0, les manques, une source périmée, une échéance passée, la réutilisation du calendrier fiscal et l’absence d’écriture dans les registres de mouvements et de constats.

Le contrat ne fait ni calcul de paie, retenue, cotisation, intérêt ou pénalité, ni dépôt, transmission, paiement ou écriture comptable. Aucune source externe n’est interrogée au moment de l’appel; les sources sont des métadonnées explicitement déclarées à valider. Les exemples dans `department.yaml` sont des commentaires de forme fictifs, pas des données de production.

## Garde d’intégrité du dossier CFO et portée des accès (mise à jour 2026-10-01)

`m5_preparer_dossier_decision_cfo` valide maintenant, avant le calcul des soldes, provisions, références de tête et rubriques du rapport, les chaînes des trois instantanés financiers qu’il a déjà lus : registre `principal`, `factures` et `comptes_a_payer`. La validation réutilise `Registre.valider_chaine()` sur ces listes capturées; elle n’effectue pas une seconde lecture. Un maillon altéré ou malformé produit le refus nommé `REJ-CFO-CHAINE-INVALIDE`. Le refus ne compose aucune rubrique monétaire, ne répare pas les registres et ne modifie pas la base. Le rôle et le droit de consulter les coûts sont contrôlés avant la première lecture financière.

Le défaut a été reproduit avec des données fictives dans une vraie base SQLite temporaire : après peuplement d’une fixture connue, une corruption locale privilégiée a modifié par SQL le premier montant du registre `principal`, sans recalculer les hashes. La chaîne devenait invalide, mais l’ancienne version acceptait le rapport et faisait passer le cash libre de 16 301 $ à 26 301 $ CAD. Cette reproduction démontre une corruption locale accidentelle ou privilégiée, pas une exploitation distante. Après le correctif, les tests vérifient aussi les corruptions des comptes à payer et des factures, un lien précédent incorrect, un hash absent et le type de mouvement absent; chaque refus est nommé et ne produit pas de rapport financier. Les comparaisons SQLite portent sur l’état après la corruption volontaire de la fixture : le parcours CFO n’ajoute aucune mutation et ne restaure pas les données corrompues. La preuve brute du probe et le rapport de revue sont archivés dans [les preuves d’intégrité CFO R19](../../../docs/research/R19-2026-09-30/preuves/cfo-integrite/cfo-integrite-source-probe.json.gz) et [la revue indépendante](../../../docs/research/R19-2026-09-30/preuves/cfo-integrite/revue-cfo-integrite-independante.md.gz).

Cette protection couvre uniquement ces trois chaînes dans le dossier de décision CFO. Elle n’est pas une validation générale appliquée à tous les outils M5, au catalogue fiscal ou aux autres départements. Les hashes de la chaîne ne sont pas signés et ne sont pas ancrés dans une racine indépendante : la vérification détecte notamment une corruption sans rehash, mais ne protège pas contre un acteur privilégié qui réécrit les données puis recalcule de façon cohérente tous les hashes. Une telle garantie exigerait un ancrage externe ou une signature, qui n’est pas livré ici.

La suite complète de `departments/m05-financecore/tests` compte historiquement **2 028 tests passés, 0 échec, 0 erreur et 0 skip en 117,119 s**. Cette preuve R19 est postérieure au premier raccord des droits CFO et antérieure à M5.10.a; elle reste une mesure d’un arbre antérieur, pas un compte à additionner à la vérification intégrée actuelle. Les manifestes avant/après couvraient 189 fichiers de M5 et `src/opsys` sans delta de source. Le test séparé de la vraie application HTTP CFO compte **15 tests passés en 4,867 s**; il inclut deux cas de registre SQLite altéré soumis par formulaire/API, qui reçoivent HTTP 409 sans montant CFO et sans delta supplémentaire en base. Ces 15 cas recouvrent le parcours CFO; ils ne s’ajoutent pas au résultat historique M5. Les journaux, rapports JUnit, manifestes et commandes sont archivés dans [les preuves M5 d’intégrité](../../../docs/research/R19-2026-09-30/preuves/cfo-integrite/m5-cfo-integrite-active-resultat.json.gz) et [les preuves console](../../../docs/research/R19-2026-09-30/preuves/cfo-integrite/cfo-console-integrite.json.gz).

### Accès des profils agents

Le 1er octobre, le premier [droit CFO des profils d’agents](M5-PROFILS-AGENTS-DROITS.md) est intégré
localement : personne active admin/propriétaire en console, profil M5 actif et révision précise,
instance, deux outils préparatoires explicitement choisis, échéance et quota de tickets. Le Core
obtient un ticket privé lié aux arguments; le backend revalide l’autorité et le consomme dans la
transaction de lecture SQLite. Sans ticket ou identité humaine valide, le serveur MCP refuse
avant lecture. L’agent ne devient ni `admin` ni `nathan_owner`; le budget de modèle ne confère
aucun droit financier. La voie console/appareil humaine conserve ses contrôles.

Après le premier raccord des droits, FinanceCore complet passe **2 028 tests**, sans échec/erreur/skip,
en 117,113 s; console/générateur passe quatre tests et Core douze, dont transport HTTP Python réel.
Cette preuve est historique et distincte de la campagne M5.10.a ci-dessous. La passe complète du
socle après raccord se termine avec 2 282 réussites, trois échecs, 35 erreurs et 83 skips.
Deux fixtures périmées sont corrigées et les cinq fichiers concernés passent ensuite 45/45;
36 cas PostgreSQL avaient été indisponibles après quatre arrêts de conteneur avec le code 1.
La fixture de diagnostic/nettoyage corrigée passe ensuite 47/47 cas ciblés, sans erreur ni skip,
en 20,426 s JUnit. Une comparaison indépendante des identifiants confirme la réussite des
36 anciens cas affectés. La cause des arrêts historiques reste inconnue; ces reprises ciblées
ne remplacent pas une nouvelle suite complète.
Les [archives R20](../../../docs/research/R20-2026-10-01/README.md)
conservent les prototypes, RED et reprises sans fusion de leurs comptes.

### Scénarios de capital M5.10.a — intégré localement le 1er octobre

`m5_preparer_decision_capital` accepte une entrée facultative de scénario. Elle peut fournir jusqu'à huit sorties datées
par option et déclare jusqu'à quelle date l'échéancier couvre la projection (horizon configuré de 1 à 26 semaines). Les dates,
montants, sources, hypothèses et couverture sont saisis par l'appelant et restent des références manuelles non vérifiées.
Le montant total de prix comptant, la mise de fonds et chaque montant de paiement cité sont rapprochés des données d'offre;
un écart ou une entrée incomplète empêche d'afficher un solde chiffré pour l'option. Aucun paiement mensuel n'est converti en
calendrier, et aucun taux, impôt, intérêt ou frais n'est calculé.

Les trois projections réutilisent le solde du registre et les flux connus/datés du même snapshot; les obligations de base ne
sont ajoutées qu'une fois par scénario et les réserves/cash libre ne sont pas retranchés une seconde fois. Le résultat présente
le solde de fin et le minimum des soldes en fin de semaine seulement, pas un creux intra-semaine. Sans le champ optionnel,
l'ancienne forme de réponse `m5_preparer_decision_capital` est conservée. Avec lui, cette réponse compacte n'inclut plus le
contexte AR/AP/devis détaillé. Elle reste un outil séparé du dossier CFO en 25 rubriques. Si les projections dépassent le budget,
leurs chiffres deviennent inconnus; le rapport est re-mesuré et fait l'objet d'un refus nommé s'il reste trop grand.

La qualification intégrée antérieure est conservée séparément de la preuve historique 2 028 : **2 037 tests M5 et 34 tests du
socle, soit 2 071 tests dans une commande**, 0 échec, 0 erreur, 0 skip, en 134,333 s JUnit. Les 1 029 sources sélectionnées
sont identiques avant/après (delta vide); le JUnit est [m5-scenarios-integres-root-r1-2026-10-01.xml](../../research/R20-2026-10-01/preuves/m5-scenarios-integres-root-r1-2026-10-01.xml.gz)
et le [résultat machine](../../research/R20-2026-10-01/preuves/m5-scenarios-integres-root-r1-2026-10-01-resultat.json.gz) est archivé avec la preuve. Le compte
2 071 inclut les 2 037 tests M5 et les 34 cas socle; il ne s'ajoute ni aux 2 028 historiques ni aux 15 tests HTTP d'intégrité.

Les registres financiers actuels sont à la portée de l’instance et ne démontrent pas d’isolation durable par `tenant_id`/entreprise. Ce garde ne rend donc pas le dossier CFO compatible multi-tenant et n’établit aucun périmètre entreprise au sein de l’instance. Tant que chaque source financière et sa transaction de lecture ne sont pas isolées par tenant, aucun grant agent transversal ou multi-tenant ne doit être accordé.

## Raccord M54 intégré — portée préparatoire

Au jalon root du 1er octobre à 09:34 UTC, `opsys-metier verifier` compte 10 départements,
202 outils et 116 outils déclarés aux appareils; les 1 044 chemins mesurés sont stables. Ce compte
est daté et ne prétend pas décrire un arbre modifié après ce jalon. La commande intégrée root r1 inclut 2 100 cas M5 parmi 6 723
réussites (M1/M4/M5 et accès/runtime), 0 échec/erreur/skip, en 400,435 s, avec 1 080 chemins stables
([JUnit](../../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01.xml.gz),
[résultat](../../research/R20-2026-10-01/preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01-resultat.json.gz)).
Root a promu le 1er octobre le pont qui apporte les heures régulières approuvées N4 et les contrats
salariaux privés au brouillon préparatoire de brut régulier. La source salariale est déclarée et révisée,
mais non authentifiée par cette seule déclaration.

La sortie reste du brut régulier seulement : aucun calcul QC, retenue, cotisation, net, dépôt,
paiement, déclaration, homologation ou action de paie. La paie complète n'est pas livrée et cette
qualification ne change pas le statut global M5. Le socle global root r2 a fini en INTERNALERROR
ENOSPC, pas en réussite; les anciens comptes 195/111 restent historiques. Le socle root r3 initial
compte 2 478 cas (2 363P/1F/30E/84S); les 31 cas rouges PostgreSQL signalent ENOSPC. La reprise
exacte passe 31/31, puis le lecteur réconcilie l'union unique à 2 478 cas (2 394P/84S), sans rouge
résiduel mais sans commande globale unique verte. Ces campagnes précèdent une modification ultérieure
de pyproject.toml; aucun run global n'est revendiqué sur le nouvel arbre. [Résultat initial](../../research/R20-2026-10-01/preuves/socle-integre-root-r3-2026-10-01-resultat.json.gz), [reprise](../../research/R20-2026-10-01/preuves/socle-reprise-postgresql-root-r1-2026-10-01-resultat.json.gz) et [union](../../research/R20-2026-10-01/preuves/socle-union-root-r1-2026-10-01.json.gz).

## Tests et limites restantes

La suite complète `departments/m05-financecore/tests` passe dans les preuves historiques et dans la campagne M5.10.a actuelle; leurs arbres et décomptes restent distincts. Les tests ciblés comprennent `test_calendrier_obligations.py`, `test_cash_libre_outils.py`, `test_prevision_outils.py`, `test_cash_libre_sans_decaissement.py`, `test_constat_cash_libre_sans_decaissement.py`, `test_prevision_sans_decaissement.py` et `test_analyse_mention.py`; les tests de refus N5/N4 confirment aussi la réponse valide (`ok: true`, `accepte: false`) sans mutation financière. La conformité AST a d’abord signalé des corpus de copies qui n’incluaient pas le nouveau module; les listes de fichiers et la surveillance ont été étendues, puis les suites ont passé. `ruff check` passe sur les fichiers touchés et `ruff format --check` confirme les deux nouveaux fichiers. Une vérification de manifeste antérieure couvrait 193 outils. Le contrôle antérieur après raccords CFO/M7 et M5.10.a comptait 10 départements, 195 outils et 111 outils déclarés aux appareils; ce compte est historique. Au jalon root du 1er octobre à 09:34 UTC, `opsys-metier verifier` compte 10 départements, 202 outils et 116 outils déclarés aux appareils, avec manifestes/événements/portées valides et zéro delta sur 1 044 chemins. Ce n’est pas un nombre de tests et ce compte est borné à ce jalon.

Les prochaines étapes sont un dossier employé, la validation CPA des règles ARC/RQ versionnées et des cas officiels, les exports T4/RL-1/RE préparatoires avec schémas annuels approuvés, puis la couverture des échéances 2027 après vérification des publications officielles. Le pont des heures M4 est livré. Les déclarations d’obligations actuelles restent des entrées manuelles dont l’exactitude et la fraîcheur dépendent de leur auteur. Aucune banque rapprochée, retenue QC, cotisation, net de paie, déclaration officielle ou homologation n’est démontrée ici. Le calendrier ne constitue donc pas un calculateur fiscal, un logiciel de paie homologué ou un CFO complet.

Le [guide des droits CFO](M5-PROFILS-AGENTS-DROITS.md) décrit la configuration, la révocation et
les limites du raccord SQLite. Les dates bornent la date du rapport, pas les lignes historiques;
les rapports exposent les sources de l’instance entière. PostgreSQL, séparation SaaS, identité
cryptographique des métadonnées humaines et isolation OS réelle restent non qualifiés. Aucun
droit N4/N5, paiement, écriture finale ou conseil officiel n’est ajouté.

## Mise à jour de preuve R13 — sources et accès, 1er octobre 2026

Le jalon actif ajoute l’inventaire M5.4.c des sources de paie sur neuf chemins intégrés le 1er octobre à 10:03 UTC. Il expose des références ARC T4127, éditions 122 (janvier) et 123 (juillet), et sept PDF Revenu Québec datés 2026-01 : TP-1015.F, .G, .TI, .TI.26, .TR, .TR.26 et .TA. Le rapprochement documentaire en lecture seule trouve sept captures RQ dont les SHA concordent avec le catalogue et deux nouveaux PDF ARC dont les SHA diffèrent des deux valeurs historiques R16, qui correspondent aux captures HTML `7.html` et `8.html`, pas à des PDFs; les nouveaux PDF ne sont pas intégrés au catalogue. La note de qualification en lecture seule et les manifestes de capture sont archivés : [note M5.4.d](../../research/R20-2026-10-01/preuves/m5-4d-paie-qualification-r1.md.gz), [rapport RQ](../../research/R20-2026-10-01/preuves/paie-quebec-references-2026-r1.md.gz), [rapport ARC](../../research/R20-2026-10-01/preuves/paie-quebec-references-2026-r2.md.gz), [checksums RQ](../../research/R20-2026-10-01/preuves/SHA256SUMS.gz) et [checksums ARC](../../research/R20-2026-10-01/preuves/ARC-SHA256SUMS-r2.txt.gz). Les neuf entrées demeurent `NON_QUALIFIEE`; les captures ne servent à aucun calcul. Voir la [note de qualification documentaire](../../research/R20-2026-10-01/preuves/m5-4d-paie-qualification-r1.md.gz), les [références RQ](../../research/R20-2026-10-01/preuves/paie-quebec-references-2026-r1.md.gz) et [ARC](../../research/R20-2026-10-01/preuves/paie-quebec-references-2026-r2.md.gz). La qualification des intervalles d’effet/couverture et des vecteurs reste à compléter pour toute analyse de calcul; la validation professionnelle s’applique avant les actions officielles appropriées, sans bloquer les analyses préparatoires autorisées. T4127 ne couvre pas l’impôt provincial du Québec; aucune édition RQ 2026-07 n’a été trouvée dans les pages vérifiées. Cet inventaire ne valide pas toutes les règles applicables et n’est utilisé pour aucun calcul.

La commande root M5/M10/admission du 1er octobre 10:04:37–10:08:37 UTC passe **3 294 cas** (2 127 M5, 968 M10, 199 socle), zéro échec/erreur/skip en 239,031 s, avec **1 099 chemins stables**. JUnit et manifestes root bornent les tests; ils ne qualifient pas les PDF en règles de calcul ni ne remplacent une qualification des sources et des vecteurs. Une revue professionnelle s’applique avant les actions officielles, sans empêcher les analyses préparatoires. M10 E09/observatoire et les admissions sont des intégrations séparées : leurs contrôles de mémoire/admission n’étendent pas la capacité paie. Les réservations d’admission UI ne sont pas libérées automatiquement.

`opsys-metier verifier` rapporte 10 départements, 203 outils et 116 outils déclarés aux appareils à 10:11 UTC. La suite permissions/bootstrap r2 passe 286/287, avec un skip parce qu’`actionlint` était absent; les modes 700/600 et EUID 1000 sont observés dans un parcours local Core→Python. Le cas d’ancien volume simule des métadonnées de propriétaire; aucune image Docker livrée ni VPS n’est ainsi qualifié.

La sortie M5 demeure un brouillon de brut régulier préparatoire fondé sur heures M4 approuvées et données salariales déclarées. Elle ne calcule pas les retenues QC, cotisations, DAS, net, paiement, déclaration officielle ou homologation. L’intégration M5.4.c ne change pas ce périmètre. La qualification des références et des vecteurs de paie reste à compléter; aucune revue CPA n’est engagée. La validation professionnelle est requise avant les actions officielles, pas comme précondition aux analyses préparatoires. La réconciliation des agents reste un travail en cours et n’est pas incluse à ces preuves. Le run global de R12 et ses 31 cas PostgreSQL ENOSPC restent inchangés : les suites R13 ci-dessus sont ciblées et ne forment pas une campagne globale verte. Voir les reçus du [run M5/M10/admission](../../research/R20-2026-10-01/preuves/m5-m10-admission-integres-root-r1-2026-10-01-resultat.json.gz), de la [suite bootstrap](../../research/R20-2026-10-01/preuves/permissions-bootstrap-integres-root-r2-2026-10-01-resultat.json.gz) et du [vérificateur catalogue](../../research/R20-2026-10-01/preuves/verifier-departements-integres-root-r3-2026-10-01-resultat.json.gz).


## M5.4.d — admission, jetons et limites de la préparation

La campagne root R2 du 1er octobre passe **2 316/2 316** (2 128 cas M5 et 188 socle), sans échec, erreur ni skip, en 193,837 s sur 1 120 chemins stables. Elle couvre l’admission et les nouveaux compteurs PostgreSQL `BIGINT`; elle inclut toute la suite M5 actuelle et les tests socle sélectionnés, sans qualifier le département CFO complet ou sa mise en production. Le dossier WebRAS est un export privé destiné à une saisie humaine dans WebRAS ou PDOC, sans appel à ces services. Le propriétaire déclare la date de paie, la période, le fuseau et la fréquence annuelle (12, 24, 26 ou 52); le calcul source revérifie les heures M4 et le contrat M5 épinglés. L’assiette imposable peut être saisie avec une référence humaine, mais reste `UNKNOWN` si elle est absente et OPSYS ne la qualifie pas. Le dossier WebRAS reprend seulement la date de paie, la période et la fréquence déclarées; le calendrier fiscal existant est distinct et reste non qualifié pour des règles/échéances officielles. Le dossier ne calcule pas les échéances fiscales, retenues QC, cotisations, DAS, net, paiement ou déclaration officielle. Voir le [dossier M5.4.d](../../../departments/m05-financecore/docs/m54d-dossier-webras-manuel.md).

Les budgets `BIGINT` ont été exercés sur PostgreSQL 17 éphémère avec données fictives. Le contrôle de migration `0014 → 0015` convertit onze colonnes dans cinq tables, préserve huit lignes préexistantes et tous leurs champs, vérifie le rejeu idempotent et confirme le refus d’une admission lorsque le solde est épuisé. Deux incréments d’usage concurrents près de la limite signée 64 bits produisent un enregistrement accepté et un refus. La somme exacte des lignes, `18446744073709551615`, est calculée en Python sans dépassement. Le correctif du retour de ligne d’`UPSERT` s’appuie sur `RETURNING`; la reproduction précédente où `rowcount=-1` empêchait d’identifier le changement reste conservée. Aucun fournisseur réel, service distant, calcul de dépense réelle ou paiement n’est concerné. La console privée des profils, accessible au propriétaire ou à l’administrateur avec CSRF, affiche les réservations actives et permet un rapprochement manuel : l’utilisateur confirme le total exact et fournit une référence courte après avoir consulté le relevé final et vérifié que l’appel est terminé. OPSYS ne vérifie ni le relevé ni cette déclaration. Tant que total ou finalité reste inconnu, la réservation demeure active; aucun déblocage automatique n’a lieu.

Les références sont la [campagne R2](../../research/R20-2026-10-01/preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01-resultat.json.gz), son [JUnit](../../research/R20-2026-10-01/preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01.xml.gz), la [migration PostgreSQL](../../research/R20-2026-10-01/preuves/r14-preuves--budgets-pg64-migration-root-r2-2026-10-01-resultat.json.gz), la [concurrence 64 bits](../../research/R20-2026-10-01/preuves/r14-preuves--jetons-pg-concurrence-root-r1-2026-10-01-resultat.json.gz), le [retour de ligne `RETURNING`](../../research/R20-2026-10-01/preuves/r14-preuves--pg-upsert-rowcount-root-r1-2026-10-01-resultat.json.gz) et la [revue de présence WebRAS](../../research/R20-2026-10-01/preuves/r14-m54d-webras-integration-root-r1--resultat.json.gz). Le catalogue vérifié à ce jalon compte 10 départements, 204 outils et 116 outils déclarés aux appareils ([résultat](../../research/R20-2026-10-01/preuves/r14-preuves--m54d-verifier-root-r1-2026-10-01-resultat.json.gz)). Les sources et vecteurs restent à qualifier; la validation professionnelle s’applique avant les actions officielles. Aucune validation CPA n’est engagée.


## Mise à jour R16 — qualification ciblée du 1er octobre 2026

La campagne root R2 couvre toute la suite M5 actuelle avec des tests socle sélectionnés : **2 210 réussites, 0 échec/erreur/skip**, en 165,471 s, sur 1 135 chemins de l’ensemble surveillé stables. La ventilation est 2 158 tests M5, 8 accès trésorerie, 24 HTTP MCP, 2 révisions de profil et 18 admission. Cinq cas PostgreSQL ont été désélectionnés, sans apparaître comme skips. M5.8a (échéanciers de contrats clients et classement) est présent dans cet arbre; cette preuve ne qualifie ni la mise en production du CFO, ni les sources officielles comme règles de calcul. Un échéancier lié à un devis est bloqué si une facture non annulée existe, y compris `ENVOYEE` ou `PAYEE`; les champs ou références HT M3 manquants ou incohérents gardent le flux inconnu ou refusé. L’horizon est hebdomadaire, de 1 à 26 semaines; il ne couvre ni 12/24 mois ni les échéanciers M4. Voir la [spécification M5.8a](../../../departments/m05-financecore/M5.8a-echeanciers-contrats.md). La [réconciliation root des profils et contrats](../../research/R20-2026-10-01/preuves/r16-preuves--tranche-profils-contrats-reconciliation-root-r1-json-b45c23b63c.gz) complète le lien entre les états annoncés et les références contractuelles; elle ne constitue pas une preuve de source externe.

Le brouillon de paie salarié produit du brut régulier à partir des heures M4 approuvées et des données salariales déclarées; les contrôles revérifient les références de contrat/heures épinglées. Ces contrats salariaux sont distincts des échéanciers de contrats clients M5.8a, qui alimentent uniquement une prévision de trésorerie préparatoire. Le calendrier fiscal déjà présent reste une déclaration datée dont les règles et échéances officielles ne sont pas qualifiées. Il n'y a pas de calcul de retenues QC, cotisations, DAS, net, paiement ou dépôt, et aucune validation CPA n'est engagée. Les neuf références PDF capturées restent `NON_QUALIFIEE`; la vérification de hash atteste les octets capturés, pas le contenu applicable ou les droits de redistribution.

Le dispatch runtime des profils a un résultat Core r3 distinct (130/130, sans échec/erreur/skip, 1 135 chemins de l’ensemble surveillé stables). La probe PostgreSQL séparée atteste le verrouillage de révision et le refus d'un appel tardif avec un handler synthétique; elle ne teste pas la consommation des tickets CFO sur PostgreSQL, car le registre CFO reste SQLite. Les reçus [campagne M5 R2](../../research/R20-2026-10-01/preuves/r16-preuves--m58a-finance-runtime-integres-root-r2-2026-10-01-resultat-json-9573718f4e.gz) et [capture documentaire](../../research/R20-2026-10-01/preuves/r16-preuves--sources-officielles-verification-root-r1-json-d9dbb33c26.gz) seront rattachés à R20 après append root.


## Mise à jour R17 — M5.3a rapprochement bancaire (1er octobre 2026, 15:28 UTC)

Le moteur CSV CAD et l’adaptateur privé de console sont intégrés. La campagne root passe 2 444 cas sans échec, erreur ni skip en 234,923 s (2 182 M5 et 262 socle sélectionnés); les 24 cas du moteur sont déjà compris dans M5 et les 19 cas de console dans le groupe socle. Les 1 140 chemins surveillés sont restés identiques. La commande a exclu les tests PostgreSQL avec `-k not postgresql`; la concurrence bancaire PostgreSQL n’est pas qualifiée. Le [résultat](../../research/R20-2026-10-01/preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-resultat-json-ecb703a783.gz) et sa [clôture indépendante](../../research/R20-2026-10-01/preuves/r17-m53a-cloture-independante-root-r2--verification-json-cde5e4f5ab.gz) permettent de relire le périmètre.

La console expose une page privée de lecture à `/opsys/finance/rapprochement-bancaire`, un POST HTML `/opsys/finance/rapprochement-bancaire/proposer` et un POST JSON `/opsys/api/finance/rapprochement-bancaire/proposer`. Seuls propriétaire ou administrateur actifs relus en base peuvent y accéder; le formulaire applique CSRF. `configuration.banque_csv.comptes_internes` doit déclarer les identifiants de comptes internes CAD. Cette allowlist est absente de la configuration actuellement suivie : l’appel est donc bloqué tant qu’elle n’est pas ajoutée. Les identifiants dans les fixtures sont fictifs.

L’adaptateur valide la chaîne complète des factures puis consomme une vue des créances versionnée et hashée. Il affiche le détail des lignes et ne propose que la référence exacte de facture avec le montant dû complet. Il conserve dans un registre append-only distinct une projection avec empreintes et métadonnées, jamais le CSV brut. Le rejeu retourne explicitement le résultat historique et son snapshot d’origine; identité, version/tête source, idempotence et rang attendu sont revérifiés avant écriture. Un conflit CAS est refusé sans append. Le corps HTTP est limité à 64 Kio; le moteur pur accepte au plus 1 Mio et 2 000 lignes, mais cette limite supérieure n’élargit pas celle de l’API.

Le lot reste préparatoire et **PARTIEL** : il ne vérifie pas l’origine du relevé ni la présence d’un dépôt, ne modifie aucune facture/mouvement/solde et ne paie pas. Il n’y a ni connecteur bancaire, ni décision finale d’approbation, ni écran d’historique; les paiements partiels, splits, frais et rapprochements par montant seul ne sont pas pris en charge. Aucun nouvel outil MCP n’est créé. La [revue ciblée](../../research/R20-2026-10-01/preuves/r17-m53a-console-revue-root-r3--revue-md-a4507cf71a.gz) couvre CSRF, échappement, revalidation du rôle, rejeu, conflit et chaîne M5 sur SQLite.


## Déclarations paie/DAS privées — tranche du 3 octobre

La première tranche du [calendrier privé de déclarations humaines](M5-OBLIGATIONS-PRIVEES-2026-10-03.md)
a qualifié 26 cas (14 existants + 12 nouveaux), avec Ruff sur trois fichiers. Le
[rapprochement humain et le cash CFO privé](M5-RAPPROCHEMENT-CFO-PRIVE-2026-10-03.md)
sont maintenant intégrés et qualifiés localement : 93 cas uniques, sans échec, erreur ou skip,
sur SQLite/HTTP/AES-GCM et le calculateur M5 existant, avec données fictives. Une confirmation
explicite des sources et un snapshot privé courant restent nécessaires; les manques ou sources
périmées rendent le cash privé `INCONNU`. Le cash du dossier principal, la prévision principale
et le MCP ne consomment pas ces déclarations privées. Ce n'est ni une paie nette, ni une remise
fiscale, ni un paiement réel. Le statut global M5 demeure **PARTIEL**.
