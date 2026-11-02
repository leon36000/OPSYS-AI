# Planification autonome : brancher au planificateur durable ce qui était livré mais jamais déclenché

Statut (2026-11-01) : **branché et qualifié contre des DOUBLES seulement.** Aucun test de cette tranche n'a touché un
fournisseur, un modèle, un réseau social, une boîte courriel, un serveur de sauvegarde ni un vrai service. **Rien n'est actif
par défaut** : chaque tour est `inactif` tant qu'un admin ne l'a pas activé depuis la console. Ce document dit ce qui est branché,
ce qui ne l'est pas et pourquoi, comment c'est gouverné, et ce qui n'est PAS prouvé.

**Mise à jour (2026-11-01, constats planifiés)** : les sept constats de la phase 2 de l'entrepôt de M8 sont maintenant
déclenchés par ce même planificateur, déclarés par les manifestes des départements (§9). Même statut : prouvé sur SQLite,
avec une horloge injectée et des données fictives, **inactif par défaut**, rien contre PostgreSQL ni un service externe.

Un système « autonome » travaille sans qu'un humain lance chaque tour. Le planificateur durable existait
([CABLAGE-CONNECTEURS.md](CABLAGE-CONNECTEURS.md) : modes `inactif`/`ombre`/`actif`, baux avec jeton de fencing, journal
append-only, coupe-circuit, acteur système `opsys-systeme` à portée « planificateur ») et pilotait cinq exécuteurs
(courriel, WordPress, réseaux sociaux). Plusieurs rapports disaient « aucun planificateur n'appelle X ». Cette tranche
**étend le même planificateur** (aucun second cron) avec treize exécuteurs (puis, §9, sept constats déclarés par les manifestes), des purges de rétention Loi 25, un inventaire
exécutable et l'écran de gestion.

## 1. Ce qui est branché

`python scripts/planification/inventaire_tours.py` imprime l'inventaire (module, fonction, niveau, idempotence, transport,
décision justifiée) ; `--verifier` contrôle qu'il est cohérent avec le code (tests : `tests/test_planification_inventaire.py`).
Les données vivent dans `src/opsys/connecteurs_planification/inventaire.py`.

| Exécuteur | Niveau | Transport | Ce qu'il fait quand il est actif |
|---|---|---|---|
| `m8.entrepot` | N2 | aucun | Reconstruit l'entrepôt dérivé de M8 (`inchange` si les registres n'ont pas bougé), publie les faits consolidés pour M10, enregistre la santé. Trois outils N2. |
| `m5.cycle` | N2 | aucun | Cycle d'opérations de M5 : brouillons d'écriture, relances de créances **préparées**, flux fournisseurs, préclôture du **mois écoulé**, mesures pour M8. Aucun paiement, envoi de relance ni clôture. Une politique de relance non déclarée est **dite** (`REJ-OPS-CONFIGURATION-A-DECLARER`), jamais inventée. |
| `m10.mnemo` | N2 | aucun | Le « mnemo-quotidien » du manifeste de M10 : modèle de soi (propositions), synchronisation paginée du graphe, leçons candidates, surveillance. Rien n'est confirmé. |
| `m10.connaissances.reindexation` | N2 | embeddings | Bascule une base dont le fournisseur d'embeddings a changé vers le nouvel espace (atomique). **Sans adaptateur d'embeddings : en attente de transport.** |
| `m7.signaux` | N2 | signaux | Lecture des sources déclarées (Search Console, analytique, publicité) : curseur persisté, quota par source. **Aucun transport réel : en attente de transport.** |
| `m7.veille` | N2 | veille | Pages publiques déclarées des concurrents (robots.txt, délai par hôte). **Aucun transport réel : en attente de transport.** |
| `m7.studio.fonds` | N2 (local) | studio | Exécute les demandes de fond dont le modèle est **local**. Un modèle par API (payant, invite hors Québec) n'est **jamais** exécuté ici. **Aucun adaptateur livré : en attente de transport.** |
| `sauvegarde.verification` | N0 | sauvegarde | Authentifie en entier la plus récente archive chiffrée, dit son âge. Ne crée ni ne supprime rien. |
| `peremptions.balayage` | N0 | aucun | Constate les sources de connaissances périmées (dont les sources fiscales) et les échéances de rétention en retard ; ne corrige rien. |
| `retention.courriel` | N3 humain | aucun | Voir §5. |
| `retention.cles` | N3 humain | aucun | Voir §5. |
| `retention.traces` | N3 humain | local | Voir §5. |
| `retention.effacements` | N2 | aucun | Termine le nettoyage de fichiers d'un effacement de clé **déjà autorisé** ; ne détruit aucune clé. |

Décisions pour ce qui n'est pas branché (détail et justification dans l'inventaire) :

- **À brancher quand le transport existera** : ingestion de sources de connaissances M10 (aucun collecteur de sources),
  génération de fond par un modèle payant (aucune approbation de dépense ni plafond de coût mensuel), création de sauvegarde
  (la garde de la clé hors de l'instance est une décision humaine).
- **À ne jamais automatiser** : le panel de moteurs d'IA de M7 (dépense par appel, hors Québec), le rafraîchissement des lectures
  de M9 (exige l'identité d'un admin humain ; un acteur système n'est pas une personne), la purge de la rétention GPS de M4
  (N5 : propriétaire **et** attestation du professionnel).
- **À construire** : la consolidation nocturne d'une affaire de M10 (il manque l'énumérateur des affaires touchées la veille ;
  aujourd'hui un tour d'agent le fait, livré en pause).
- **Déjà périodique hors planificateur** : la purge des fragments expirés de la mémoire (PostgreSQL), par la boucle d'entretien de
  l'image.
- **Évalué à la lecture, rien à balayer** : statut des sources fiscales M5, licences des fournisseurs, consentement de suivi M4,
  jetons d'approbation de courriel, fraîcheur des mesures M8. Ces péremptions sont calculées à chaque lecture ou à chaque usage ;
  le constat planifié est `peremptions.balayage`.

## 2. Les règles (et où elles sont prouvées)

| Règle | Mécanisme | Preuve |
|---|---|---|
| (a) `inactif` par défaut, `ombre`/`actif` posés par un admin humain avec expiration | `etat.appliquer` : session console serveur, rôle relu en base, motif, 90 jours ; refusé depuis le MCP, un département ou un appareil | `test_cablage_planificateur.py`, `test_planification_departements.py` (cycle inactif → ombre → actif → expiration → arrêt) |
| (b) un seul exécuteur à la fois par ressource | créneau réservé par comparaison-échange, bail par ressource avec jeton de fencing | `test_planification_processus.py` : 6 **processus** se disputent un tour / un bail ; un seul travaille |
| (c) idempotent, reprenable | idempotence propre à chaque outil ; bail expiré repris avec un jeton plus grand | `test_planification_processus.py` : SIGKILL au milieu d'un tour de M8, reprise sans refaire l'étape faite |
| (d) jamais N3+ sans approbation consommée | `appeler_outil` : liste fermée par exécuteur ET niveau N0 à N2 ET `frontiere_humaine` faux, **avant** tout appel ; envoi/publication : approbation consommée (déjà prouvé) | `test_planification_departements.py` (N3, N4, N5, hors liste, frontière), `test_planification_transport.py` (modèle payant) |
| (e) quotas, plafonds, arrêt propre | plafond d'appels par 24 h glissantes (journal) ; quota de chaque source ; arrêt propre ; durée maximale d'un tour | `test_planification_transport.py::test_le_plafond…` |
| (f) journal sans contenu ni secret | liste blanche de détails (clés scalaires courtes), masquage | `test_planification_transport.py` (jeton absent), `test_planification_retention.py` |
| (g) transport absent = « en attente de transport » | `EnAttenteTransport` → statut `attente_transport`, code typé, visible à la console même pour un exécuteur inactif | `test_planification_transport.py` |
| coupe-circuit | `OPSYS_PLANIFICATEUR_CONNECTEURS=0` | `test_planification_departements.py`, `test_planification_retention.py` |

Le plafond d'appels (`Definition.plafond_appels_jour`) ne s'applique qu'aux exécuteurs qui comptent leurs appels (`appels` dans
leur compte rendu) : signaux, veille, studio, réindexation. Les cinq exécuteurs de connecteurs gardent leurs propres quotas.

Les outils de département sont appelés **directement** (`executer_atomique`, une transaction par outil), pas par le répartiteur
`Capacites`, qui poserait l'identité d'un département et fermerait l'acteur système. Ce qu'on perd : le budget de jetons, la
cloison par département et l'audit d'usage attribué à un département. Ce qu'on garde : la liste fermée, le contrôle de niveau,
le journal du planificateur et, pour M10, l'attribution `par=agent:m10-memoire` **figée dans le code de M10** (l'écriture est
attribuée à l'agent, pas à `opsys-systeme` : limite connue).

## 3. L'état d'un tour à la console

`/plateforme/connecteurs` (admin seulement : session, rôle relu en base avant et après chaque lecture, CSRF sur chaque écriture,
`no-store`) montre **tous** les tours par famille : libellé, niveau, **état** (mode effectif, « expiré », « en attente de
transport » avec le transport manquant, « plafond atteint », « sans décision humaine valide »), expiration, dernier passage
(date, statut, code), échecs sur 24 h, prochain passage, formulaire de réglage. Une seconde table liste les **tours non
branchés** avec la décision et sa raison. L'API JSON (`/api/plateforme/connecteurs`) porte les mêmes champs et l'inventaire.
Accessibilité et responsive comme les autres pages Plateforme : un seul `h1`, sous-navigation commune, tableaux dans un
conteneur qui défile, en-têtes `scope="col"`, légendes, champs étiquetés, état écrit (jamais la couleur seule).

## 4. Variables d'environnement

| Variable | Effet |
|---|---|
| `OPSYS_PLANIFICATEUR_CONNECTEURS=0` | Coupe-circuit : plus aucun tour (existant). |
| `OPSYS_TRACES_RETENTION_JOURS` | Rétention des traces (1 à 3650, défaut 30). Une valeur invalide est **refusée**, jamais lue comme le défaut. |
| `OPSYS_PLANIF_SAUVEGARDES_DOSSIER` + `OPSYS_SAUVEGARDE_CLE_FICHIER` | Les deux, ou `sauvegarde.verification` reste « en attente de transport ». Donner la clé de sauvegarde au processus du serveur contredit la politique « clé hors de l'instance » : **choix d'exploitation explicite**, jamais un défaut. |

## 5. Rétention Loi 25 : purger sans réécrire un registre chaîné

Les registres chaînés (`stockage.maillons`, journaux hash-chaînés) ne perdent jamais une ligne : la chaîne se romprait. Trois
mécanismes, du moins au plus invasif, tous testés :

1. **Crypto-effacement** (`opsys.cles_chiffrement`, déjà utilisé pour la rétention GPS de M4) : le contenu est chiffré avec une
   clé propre à l'élément ; la chaîne couvre le **chiffré** ; à l'échéance la clé est détruite (`demander_effacement`, fichiers
   nettoyés ensuite). La chaîne reste valide, le contenu est irrécupérable.
   - **Adresse de l'expéditeur et objet d'un courriel reçu par M1** (`m1_front_office.courriel_pii`) : la ligne
     `reception_courriel_connecteur_v1` porte une enveloppe AES-GCM liée au signal ; `expediteur` et `objet` valent `null`.
     Échéance = date de réception + `retention_jours` du compte. Après la destruction : l'adresse est illisible, on ne peut plus
     répondre à ce courriel (`REJ-M1-COURRIEL-EFFACE`), la chaîne est valide.
   - **Enregistrements vocaux** (`opsys.retention.voix`) : clé par session et par portée (`audio`, `transcription`), fichier
     chiffré 0600 au nom pseudonyme, rétention de 1 à 90 jours (refus typé sinon). Le retrait du consentement efface **tout de
     suite** (droit de la personne), sans attendre le planificateur. **Aucun worker vocal n'existe** : rien n'est enregistré
     aujourd'hui ; ce module est l'ordre exécutable que le worker appellera.
2. **Contenu scellé rendu illisible, empreintes gardées** (`opsys.retention.courriel`) pour les tables qui ne sont pas des
   registres chaînés : originaux et résultats d'étapes de l'ingestion (`nonce`/`chiffre` à NULL), brouillons non décidés
   (vidés, `ECARTE` avec la décision `retention_loi25`), brouillons sortants terminés (vidés), archives déposées en clair
   (écrasées puis retirées). `courriel_messages` garde ses hachages (sans eux un nouvel amorçage réingérerait le courriel) ; le
   lien vers le lot est mis à NULL. Un lot n'est purgé que lorsque **tous** ses messages sont échus. Un brouillon `VALIDE` (donnée
   d'affaires confirmée) et un brouillon en cours d'approbation ne sont jamais touchés.
3. **Rétention par segments** (traces d'observabilité) : segments entiers plus vieux que la rétention, jamais le segment du jour,
   consignés dans `purges.jsonl`. Ce n'est pas une donnée d'affaires (télémétrie masquée).

### Gouvernance : N3 humain à la première activation, puis automatique

1. L'exécuteur est `inactif`. L'admin le passe en **ombre** : le tour dresse l'aperçu et le journalise sans rien effacer.
2. Pour le passer en **actif**, l'admin voit l'**aperçu à blanc** (références seulement : identifiants, noms de segment, jamais un
   contenu ni une adresse) puis confirme expressément. La décision est consignée dans `planificateur_approbations`
   (append-only) avec **l'empreinte de la liste vue**, le nom de l'admin et l'expiration ; si la liste a changé entre-temps,
   elle est refusée (`APERCU_CHANGE`) : on n'approuve que ce qu'on a vu. Sauter l'ombre ou la confirmation est refusé.
3. Ensuite la purge est **automatique selon la politique approuvée** (rétention du compte, échéance inscrite à l'écriture,
   rétention des traces) jusqu'à l'expiration de 90 jours. Le renouvellement exige de repasser par l'ombre et un nouvel aperçu.
4. La décision est liée à la **révision** de l'exécuteur : toute modification de l'état l'invalide. Sans décision valide,
   l'exécuteur n'efface rien même s'il est inscrit `actif` ; le contrôle est fait par le planificateur **et** par l'exécuteur.
5. La liste des clés détruisibles est **fermée** (voix, adresses de courriel M1) : la rétention GPS de M4 reste un geste humain N5.

### Limites de la rétention (dites sans euphémisme)

- **Le texte neutralisé du courriel (`contenu_filtre` du signal) et le contact du lead publié à M2 restent au registre de M1.**
  Ils appartiennent au pipeline commun à tous les canaux et à la qualification ; le lead est une donnée d'affaires. Seuls
  l'adresse et l'objet de la ligne de réception sont scellés. Leur effacement est une décision distincte, non prise.
- **Les lignes du registre de M1 écrites avant ce changement portent l'adresse en clair** : elles ne sont pas purgeables (on ne
  réécrit pas une chaîne). Aucune donnée réelle n'existe encore ; à l'installation du premier client le problème ne se pose pas.
- **Le fichier SQLite peut garder des pages libérées** : `PRAGMA secure_delete=ON` les écrase à la suppression ; `VACUUM` et
  le nettoyage du WAL ne sont faits que pour les clés détruites (`finaliser_effacement`, `retention.effacements`). Les
  **sauvegardes, exports et copies existants contiennent encore** les clés et les contenus (`exportation.py` embarque les clés) :
  l'effacement ne les atteint pas.
- La purge du courriel est qualifiée sur SQLite. PostgreSQL : migration 0055 éprouvée sur PostgreSQL éphémère, mais pas les
  exécuteurs de rétention ni `demander_effacement` (état « non qualifié » par construction).
- `purges.jsonl` des traces n'est pas chaîné ; le dossier de traces n'est pas dans l'export d'instance.
- Une rétention de compte raccourcie après coup raccourcit aussi, rétroactivement, celle des courriels déjà ingérés (pas celle des adresses déjà scellées chez M1, dont l'échéance est fixée à la réception).
- « À valider auprès d'un professionnel qualifié (avocat / conseiller en protection des renseignements personnels) » : ce document
  décrit un mécanisme, pas un avis juridique ; les durées et la finalité restent celles que le client déclare.

## 6. Ce qui n'est PAS prouvé

- Aucun exécuteur n'a parlé à un vrai service : Search Console, publicité, sites concurrents, générateurs d'images, embeddings,
  serveur de sauvegarde, Gmail/Graph. Ils tournent sur des doubles ; sans transport, ils disent « en attente de transport ».
- Les exécuteurs de départements appellent les outils réels de M5, M8 et M10 sur une base SQLite vide ou presque : l'idempotence
  est prouvée (rejeu sans écriture), pas le comportement sur des mois de données réelles ni sur PostgreSQL.
- La synchronisation du graphe de M10 recommence à 0 à chaque passage (le curseur n'est pas persisté) et relit les événements :
  coût linéaire par page ; borné à 200 pages et à la durée maximale du tour.
- Le plafond d'appels est une garde de budget, pas une mesure de coût en dollars ; aucun prix n'est calculé.
- Aucune charge, aucun essai multi-machines. La concurrence est prouvée pour des processus d'une machine, sur SQLite.
- Aucune alerte n'est envoyée à un humain quand un tour échoue ou qu'une sauvegarde est trop vieille : c'est visible à la
  console, rien ne pousse une notification.

## 7. Procédure d'exploitation

1. Console > Plateforme > Connecteurs : lire l'état de chaque tour ; un tour « en attente de transport » nomme ce qui manque.
2. Activer en **ombre**, laisser passer un ou deux tours, lire le journal (« aurait »). Puis **actif** (motif obligatoire,
   90 jours). Désactiver est immédiat.
3. Purge : ombre, puis « Actif » : lire l'aperçu, confirmer. Revenir tous les 90 jours (nouvel aperçu, nouvelle décision).
4. Aucun outil d'agent ne crée, active ni déclenche un tour : le registre MCP n'a pas changé (629 outils, révision 12 ;
   `opsys-metier registre-mcp verifier` : OK).

## 8. Migration et fichiers

Migration **0055** (`0055_planification_autonome.py`, `down_revision = "0052"`, réalignement par l'architecte à l'intégration) :
`planificateur_approbations` (append-only, déclencheurs SQLite et PostgreSQL) et `retention_echeances` (pseudonymes seulement).
La descente est refusée dès qu'une ligne existe. Aucune table existante n'est touchée.

| Chemin | Rôle |
|---|---|
| `src/opsys/connecteurs_planification/{etat,planificateur}.py` | définitions, gouvernance, plafonds, attente de transport, aperçu |
| `.../exec_departements.py`, `exec_m7_lecture.py`, `exec_retention.py` | les exécuteurs de cette tranche |
| `.../inventaire.py`, `scripts/planification/inventaire_tours.py` | inventaire exécutable |
| `src/opsys/retention/{echeances,voix,courriel}.py` | rétention |
| `departments/m01-front-office/src/m1_front_office/courriel_pii.py` | adresse de courriel scellée |
| `src/opsys/console/cablage_ui.py` | écran de gestion |
| `tests/test_planification_*.py`, `tests/fixtures/planif_qa.py` | preuves |
| `src/opsys/connecteurs_planification/constats.py`, `departements.py` (bloc `constats_planifies`) | constats planifiés (§9) |
| `departments/m08-analytics/src/m8_analytics/cadence_constats.py` | cadence par défaut dérivée du catalogue de M8 |
| `tests/test_constats_planifies.py`, `tests/test_entrepot_m8_planifie.py`, `tests/fixtures/planif_m8_monde.py` | preuves des constats |

## 9. Constats planifiés pour M8 : un département déclare, le planificateur déclenche

**Le problème.** La phase 2 de l'entrepôt de M8 ([M8-ENTREPOT-SOURCES](M8-ENTREPOT-SOURCES.md)) a livré sept outils de constat
(T1/N2, agent seulement, aucun droit d'appareil) : `m5_constater_depense_publicitaire`, `m5_constater_factures_emises`,
`m7_constater_performance_signaux`, `m4_constater_capacite_equipe`, `m2_constater_pipeline`, `m6_constater_disponibilite`,
`m1_constater_plaintes`. Rien ne les lançait : sans geste d'agent, les mesures de M8 étaient non calculables puis périmées.

**Décision d'architecture : l'hôte existant convient, aucun second mécanisme.** Les constats sont des appels déterministes
d'outils N2 : c'est ce que font déjà `m8.entrepot` et `m5.cycle`. Les `planifications:` du manifeste (cron d'un AGENT avec
consigne) ont été écartées : elles passent par un modèle (jetons, non-déterminisme, un agent pourrait « oublier » un outil) alors
qu'un constat n'a rien à interpréter. Le planificateur durable apporte ce qu'il faut : mode `inactif` par défaut, bail,
réservation de créneau, journal, arrêt propre, coupe-circuit, console.

**Où est la déclaration.** Dans le manifeste du département PRODUCTEUR, bloc `constats_planifies` (schéma fermé, validé à la
lecture et par `opsys-metier verifier`). Le socle ne contient aucun horaire ni nom de département : `constats.py` lit les
manifestes, en tire un exécuteur `<mN>.constat.<nom>` par déclaration (famille « constats », niveau N2) et le journal, la
console et l'activation les traitent comme les autres tours.

| Exécuteur | Outil appelé | Mesures de M8 alimentées | Appels par passage | Intervalle par défaut |
|---|---|---|---|---|
| `m5.constat.depense-publicitaire` | `m5_constater_depense_publicitaire` | dépense comptabilisée, écart avec les relevés | 1 : du début du mois à aujourd'hui | 12 h |
| `m5.constat.factures-emises` | `m5_constater_factures_emises` | factures émises, facturation avant taxes | 1 | 12 h |
| `m7.constat.performance-signaux` | `m7_constater_performance_signaux` | clics, impressions, visites du site | 2 : mois précédent, mois en cours | 12 h |
| `m4.constat.capacite-equipe` | `m4_constater_capacite_equipe` | heures disponibles, heures planifiées, charge | 1 : semaine ISO en cours | 24 h (borné) |
| `m2.constat.pipeline` | `m2_constater_pipeline` | leads ouverts, taux de conversion, valeur pondérée | 1 | 12 h |
| `m6.constat.disponibilite` | `m6_constater_disponibilite` | ruptures, sur-réservés, réservations incomplètes | 1 | 12 h |
| `m1.constat.plaintes` | `m1_constater_plaintes` | plaintes de la période | 1 : période par défaut de l'outil | 12 h |

Les périodes sont des **mois civils entiers** pour M7 parce que M8 refuse de sommer deux résumés d'une même source qui se
chevauchent ; M7 refait le mois précédent à chaque passage pour que sa dernière version tienne compte des faits arrivés après
sa fin. M5 constate du début du mois à aujourd'hui, comme l'étape 6 de `m5.cycle` (qui lançait DÉJÀ ces deux constats avant ce
chantier, à son propre intervalle) : les deux exécuteurs donnent la même période, la même version et la même `sequence`, donc
aucun doublon si les deux tournent (prouvé) ; l'exécuteur dédié permet de n'activer que les constats, sans les brouillons ni les
relances du cycle. M8 ne retient que le constat de plus grand `sequence`.

**La cadence par défaut est dérivée, pas recopiée** (`m8_analytics.cadence_constats`). Pour un constat :
1. chaque mesure qu'il alimente a une fenêtre de fraîcheur de producteur : `max(fenetre_s, cadence_s)` du catalogue de M8, ou ce
   que le propriétaire a déclaré (`configuration.fraicheur_mesures_s`, `configuration.cadences_mesures_s` du manifeste de M8) ;
2. la plus **stricte** commande ;
3. le constat passe `PASSAGES_PAR_FENETRE` = 2 fois par fenêtre (une marge d'ingénierie, pas un rythme d'affaires : un passage
   manqué ne périme pas la mesure ; à 1, une panne d'un passage la périmerait) ;
4. le résultat est borné aux valeurs que le planificateur accepte (15 s à 86 400 s). La capacité d'équipe (cadence de source de
   7 jours) est donc planifiée au jour, ce qui est plus fréquent que nécessaire, jamais moins.
L'admin règle l'intervalle à l'activation comme pour tout tour ; une mesure ou une cadence déclarée par le propriétaire change le
défaut au prochain tour, sans toucher au code. Une mesure inconnue du catalogue ou sans fenêtre est refusée (`verifier`).

**Idempotence.** Les arguments d'un appel sont calculés sur le **créneau** : le multiple de l'intervalle, compté depuis minuit
local (fuseau de l'entreprise), qui contient l'instant. Deux déclenchements du même créneau (redémarrage en cours de cycle,
deuxième instance, réservation perdue) donnent donc les mêmes bornes de dates et le même instant de constat, donc le même
identifiant d'événement déterministe de l'outil, que le bus absorbe : un seul constat publié. Le créneau suivant est un constat de
plus, voulu (M4, M2, M6 : « un événement par constat » ; le dernier publié fait foi). Aligné sur le jour local, le créneau de 12 h
ou de 24 h porte toujours la date du jour (la mesure n'est pas datée de la veille).

**Modes.** `inactif` (défaut) : rien. `ombre` : l'exécuteur vérifie que l'outil existe et qu'il est de niveau N0 à N2, calcule les
arguments du créneau et journalise « aurait » ; **il n'appelle aucun outil, donc ne publie rien** (l'outil publie au bus : l'ombre
n'a pas d'effet, comme `m8.entrepot` et `m5.cycle`). `actif` : bail par exécuteur, puis l'outil, un jeu d'arguments après l'autre.
Le mode `ombre|supervise|autonome` du département et ses niveaux d'approbation ne changent pas : tous les départements restent
livrés en `ombre`, et un outil N3 ou plus n'est jamais appelé (liste fermée à l'outil déclaré, niveau relu avant l'appel,
`frontiere_humaine` refusée).

**Pas de rattrapage.** Le créneau est réservé par comparaison-échange à `maintenant + intervalle` ; un serveur arrêté cinq jours
fait UN passage au redémarrage, pas dix (prouvé).

**Échecs.** Un jeu d'appels qui échoue (exception, refus rendu par l'outil, département absent) n'empêche ni les jeux suivants ni
les autres constats : le tour est « erreur » avec le code typé (`REJ-PLAN-DEFAUT-EXECUTEUR`, `REJ-PLAN-DEPARTEMENT-ABSENT`, le
code du refus de l'outil…), visible à la console Connecteurs (dernier statut, code, échecs sur 24 h) et au journal. La mesure
devient périmée seulement après DEUX passages manqués (prouvé) puis redevient à jour dès que le constat repasse.

**Ce qui est prouvé** : `tests/test_entrepot_m8_planifie.py` (19 cas de bout en bout : vrais outils, vrai bus et répartiteur,
vrai moteur, wallboards de la vraie console, copilote, mémoire de M10, consolidation vue par M9), `tests/test_constats_planifies.py`
(manifeste, grammaire, créneaux, changement d'heure, garde-fous), `departments/m08-analytics/tests/test_cadence_constats.py`.

**Ce qui n'est PAS prouvé, sans euphémisme.**
- SQLite seulement : aucun de ces tests n'a tourné sur PostgreSQL (aucune migration ni table nouvelle, mais les exécuteurs et les
  outils de constat n'y ont pas été exercés).
- Horloge injectée : la boucle réelle du serveur (`_boucle_planificateur`, tour toutes les 15 s) n'a pas été observée sur plusieurs
  jours ; les jours de changement d'heure ne sont éprouvés que par le calcul du créneau.
- La péremption d'une mesure de M7 (observation du signal) et des factures (jour d'émission) suit l'âge du FAIT sous-jacent, pas
  celui du constat : un constat qui repasse ne rend pas « fraîche » une donnée que personne n'a mise à jour. Seules les mesures de
  M4, M2, M6 et M1 sont datées de l'instant du constat.
- M8 somme TOUS les résumés mensuels de M7 qu'il a reçus (périodes sans chevauchement) : « clics du site » est cumulatif depuis le
  premier constat, pas « du mois ». C'est la définition de M8 (phase 2), non modifiée ici.
- Un événement de plus par créneau pour M2, M4 et M6 (environ cinq par jour à la cadence par défaut) : le bus et le registre de M8
  grossissent sans purge.
- La fenêtre de M5 (mois en cours) donne un écart avec les relevés très partiel en début de mois ; la couverture le dit.
- Les constats ne s'activent jamais seuls : un admin doit les passer en `ombre` puis `actif` (90 jours), département par département.
