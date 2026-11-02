# M2 Revenue CRM (Victor) : profil de propriété, score de lead, coach de vente, analytique et prévisions

Statut : tranche « ventes » (2026-11-01, branche `claude/m2-victor`, base `1b58f4e6c`). Code : `departments/m02-revenue-crm/src/m2_revenue_crm/`
(`propriete.py`, `scoring.py`, `scoring_faits.py`, `calibration_scoring.py`, `valeurs.py`, `coach.py`, `previsions.py`,
`moteurs_commerciaux.py`, `outils_ventes.py`, `verdicts_commercial.py`) et le pont du socle `src/opsys/recu_calcul_pont.py`.
Matrice : `docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M2.json` (M2.3, M2.4, M2.9, M2.15). Portées d'appareil :
[ROLES.md](ROLES.md), « Les outils « ventes » de M2 ». Évaluation : [EVALUATION.md](EVALUATION.md).

> **Ce que cette tranche est, et n'est pas.** Elle livre quatre capacités du CRM au niveau de profondeur des autres départements :
> seize outils, des registres chaînés, des reçus rejouables, 28 cas d'évaluation et des preuves exécutées (tests de module, tests
> d'outils sur une vraie base SQLite, un parcours par la vraie porte d'appareil sur SQLite **et** PostgreSQL). Elle ne mesure
> **aucun modèle de langage réel**, n'a **aucune donnée de client réelle**, ne câblait **aucun consommateur** chez M3, M4 ni M10 (câblés depuis par le chantier d'interconnexion : [INTERCONNEXION.md](INTERCONNEXION.md)), et
> ses poids et seuils sont des **valeurs initiales déclarées**, pas des décisions de la direction. Tout statut « fait » de la
> matrice est donc `PARTIEL` avec ses limites dites (section 8).

## 0. Autonomie : qui fait quoi

Règle d'architecte (DECISIONS-ARCHITECTE r1, § 1) : **autonome sans validation** = lecture, calcul, classement, brouillon (N0 à N2) ;
**humain** = envoi externe, changement de statut contractuel, remise (N3 et plus).

| Outil | Niveau | Appareil | Ce qu'il fait | Ce qu'il ne fait jamais |
|---|---|---|---|---|
| `m2_lire_profil_propriete` | T0 / N0 | seller, admin | lit les propriétés d'un client (confirmé, brouillon, âge, complétude) | écrire ; rendre un contact |
| `m2_proposer_profil_propriete` | T1 / **N2** | seller, admin | brouillon sourcé et versionné, par saisie | confirmer |
| `m2_proposer_profil_propriete_depuis_courriel` | T1 / **N2** | seller, admin | brouillon extrait d'un courriel (motifs fixes, extrait comme preuve) | deviner ; garder un contact ; obéir au texte |
| `m2_proposer_profil_propriete_depuis_onboarding` | T1 / **N2** | admin | brouillon à l'adresse d'une fiche client importée | confirmer |
| `m2_confirmer_profil_propriete` | T1 / **N3** | seller, admin | une PERSONNE confirme ou écarte ; publie le fait minimisé | être décidé par un agent seul (`REJ-HUMAIN-REQUIS`) |
| `m2_calculer_score_lead` | T0 / N0 | seller, admin | score expliqué d'un lead ouvert, reçu rejouable | décider ; affirmer une probabilité |
| `m2_classer_file_leads` | T0 / N0 | seller, admin | file des leads ouverts (permutation) | écarter, fermer ou masquer un lead |
| `m2_lire_modele_scoring` | T0 / N0 | seller, admin | modèle publié, champs interdits, calibration fictive | présenter la calibration comme réelle |
| `m2_declarer_valeur_pipeline` | T1 / **N3** | seller, admin | une PERSONNE déclare l'ordre de grandeur d'une opportunité | être un prix, une soumission, un montant comptable |
| `m2_analyser_pipeline` | T0 / N0 | seller, admin | pipeline, taux, délai de cycle, valeur pondérée, reçu | conclure sous le seuil d'échantillon |
| `m2_prevoir_pipeline` | T0 / N0 | seller, admin | prévision PAR INTERVALLE, reçu | donner un point seul ; prévoir sous le seuil |
| `m2_rejouer_recu_commercial` | T0 / N0 | seller, admin | vérifie et REFAIT un reçu | accepter un reçu retouché ou compact |
| `m2_contexte_coach` | T0 / N0 | **aucun** | faits du CRM + extraits de connaissances avec provenance | écrire ; exécuter ce qu'une source dit |
| `m2_proposer_suggestion_coach` | T1 / **N2** | **aucun** | UN brouillon au journal, après contrôle | envoyer ; inventer un prix, un engagement, un nombre |
| `m2_decider_suggestion_coach` | T1 / **N2** | seller, admin | une PERSONNE accepte, modifie ou rejette | envoyer (`REJ-COACH-ENVOI-INTERDIT`) |
| `m2_lister_suggestions_coach` | T0 / N0 | seller, admin | journal et bilan | rendre un taux sans effectif suffisant |

Aucun de ces outils n'envoie un message, ne change un statut de lead, ne consent une remise ni n'écarte un lead : ces gestes restent
au sas courriel de M1 (brouillon, approbation N3, envoi), à `m2_transitionner_statut` et à la direction. Le coach est **fermé aux
appareils** (la base de connaissances l'est : `CONNAISSANCES.md`) ; le vendeur lui parle par l'agent et **décide** depuis l'app.

Registres durables (chaînés par empreintes, append-only, dans `stockage.maillons("m02-revenue-crm", <nom>)` ; **aucune migration** :
la table de registres est générique) : `profils_propriete`, `valeurs_pipeline`, `suggestions_coach`. Événement publié :
`m2.profil_propriete_confirme` (catalogue `src/opsys/evenements/catalogue/`). Codes de refus : `verdicts_commercial.py`, catalogue
fermé à part (`REJ-PROP-*`, `REJ-SCORE-*`, `REJ-COACH-*`, `REJ-PREV-*`), comme M5 le fait pour `verdicts_calcul.py`.

## 1. M2.3 Profil de propriété

**Modèle.** Une propriété est liée à un client (`client_id`, le Client 360) ; son identifiant est l'empreinte de (client, adresse
normalisée) : la même adresse écrite autrement donne la même propriété. Chaque écriture est une **révision** d'un registre chaîné :
`proposition` (brouillon), puis `confirmation` ou `ecartement` par une personne. Le profil courant est la dernière révision
confirmée ; le brouillon en attente est la dernière proposition non décidée ; `revision_attendue` (0 pour créer) interdit
d'écraser une version qu'on n'a pas lue (`REJ-PROP-REVISION-PERIMEE`).

**Liste blanche** (tout le reste : `REJ-PROP-CHAMP-INCONNU`) : adresse, type de bâtiment (énuméré), étages (1 à 12), année de
construction (1800 à l'année courante ; l'âge est calculé à la lecture, jamais stocké), matériaux (élément énuméré + matériau
court), historique de travaux (année + nature), accès et contraintes (code énuméré + note courte), photos liées et mesures liées
(**références** : identifiant de fichier, source `m3`/`m4`/`manuel` + identifiant ; jamais le contenu), services potentiels
(codes validés contre le profil d'entreprise, `opsys.taxonomie`).

**Sourcé.** Chaque valeur porte `{type, reference}` — `declare_client`, `constate_vendeur`, `document_onboarding`, `courriel`
(avec l'`extrait` qui la fonde) ou `mesure_liee` — et l'instant d'observation. Il n'existe pas de source « agent » : un agent propose
avec la preuve qui le fonde, ou ne propose rien.

**Minimisation (Loi 25).** Finalité écrite dans chaque révision. Ni nom, ni téléphone, ni courriel, ni revenu, ni occupant : seulement
le `client_id`. Les textes libres (matériau, nature d'un travail, note, extrait) sont courts et passent par le garde-fou de texte du
socle (pas de lien, d'adresse, de courriel, de téléphone, de prix) et un contrôle « code d'accès » (`REJ-PROP-TEXTE-REFUSE`). Le fait
publié au bus (`m2.profil_propriete_confirme`) ne porte ni l'adresse précise, ni le code postal, ni les notes, ni les photos, ni les
mesures : la ville, le type, les étages, l'année et deux compteurs. Les textes libres sont des **données non fiables** à la lecture
(neutralisés par le filtre anti-injection de M1 via `opsys.connaissances.isolation` ; `fiabilite_textes_libres`).

**Alimentation.** (1) Saisie par une personne (ou un agent qui propose). (2) **Courriel** : `extraire_depuis_texte` reconnaît par
motifs fixes ce que le texte dit en toutes lettres (adresse, type, étages, année, matériaux, travaux passés) ; ce qui n'est pas écrit
n'est pas proposé ; un contact ou un lien voisin n'entre jamais (l'extrait est reculé au passage seul, ou omis) ; une consigne glissée
dans le texte n'a aucun effet (rien d'autre que des valeurs typées de la liste blanche ne sort). Le texte vient de l'agent, qui a lu le
courriel par les outils gouvernés de M1 ; le déclencheur « événement » sur `m1.courriel_recu` (qui ne porte aucun texte) reste à
configurer comme profil d'agent. (3) **Onboarding** : l'adresse d'une fiche client importée, déjà validée par une personne, devient un
brouillon (source `document_onboarding`, référence `lot:brouillon`).

**Lecture par M3 et M4.** Par le fait minimisé du bus (M3, M4 et M10 peuvent s'y abonner) et par `m2_lire_profil_propriete` selon les
droits existants. Aucun droit d'appareil n'est élargi, `LECTURES_AUTORISEES` de M9 n'est pas touchée. Les consommateurs de M3, M4 et M10 sont
câblés par le chantier d'interconnexion ([INTERCONNEXION.md](INTERCONNEXION.md)). M2 consomme en retour `m7.conversion_hors_ligne_importee`, `m5.creance_relance_preparee` et `m3.contexte_site_pret` en lecture seule.

## 2. M2.4 Lead scoring 2.0

**Un score transparent, explicable, déterministe.** Six facteurs de poids déclarés (Σ = 100), chacun fait de signaux à points déclarés
(Σ = 100 par facteur) ; `m2_lire_modele_scoring` publie le tout avec l'empreinte du modèle (qui change si UN poids change) :

| Facteur | Poids | Signaux (points) |
|---|---|---|
| Qualité | 20 | courriel 20, téléphone 20, nom 10, ville 10, service 15, canal 5, source 10, complétude du profil de propriété 10 (au prorata) |
| Urgence | 15 | urgence déclarée 60, fraîcheur 40 (≤ 2 j : 40 ; ≤ 7 : 25 ; ≤ 14 : 10) |
| Conversion | 25 | statut 35 (qualifié) / 10 (nouveau), interactions humaines 30 (10 chacune, 3 au plus), activité récente 25, devis envoyé 10 |
| Rentabilité | 15 | valeur déclarée dans les bandes configurées : 25 / 50 / 75 / 100 |
| Préparation | 15 | propriétaire 15, service 15, ville 15, interaction 15 (les quatre conditions de la readiness), profil confirmé 25, photo liée 15 |
| Risque | 10 | aucun doublon en attente 40, aucun STOP 20, pas dormant 40 |

Le score est `Σ poids × sous-score / Σ poids ÉVALUÉS`, en fractions exactes (aucun flottant) ; il rend la contribution en points de chaque
facteur et de chaque signal, la **couverture** des poids, la version du modèle et un reçu `recu-calcul.v1` rejouable.

**Il ne devine pas.** Un signal sans donnée est **non évalué**, nommé avec ce qui manque, et sort du calcul : devis de M3 illisibles,
lead non qualifié (readiness), seuil de dormance non configuré, aucune valeur déclarée, et le facteur rentabilité tant que
`configuration.scoring.bandes_valeur_cents` (vide à dessein dans `department.yaml`, trois montants en cents croissants) n'est pas
configuré. Un facteur à zéro et un facteur non évalué ne sont jamais confondus.

**Il ordonne, il ne décide.** `m2_classer_file_leads` rend une **permutation** des leads ouverts (nouveau, qualifié), page par page :
`total_ouverts` est leur nombre, aucun n'est retiré ; le résultat porte `decision_humaine_requise: true` et aucun champ « écarter »,
« rejeter » ni « probabilité ». Un test prouve que classer ne change aucune donnée.

**Équité.** Les faits d'entrée sont une liste fermée de booléens et de compteurs (`scoring.CHAMPS_FAITS`) : la présence d'un courriel,
jamais le courriel. `scoring.CHAMPS_INTERDITS` nomme les attributs protégés (âge, genre, origine, ethnie, religion, langue, handicap,
état civil, orientation, nationalité, revenu…) et les identifiants personnels (nom, adresse, code postal, téléphone, courriel…) : le
validateur les refuse nommément (`REJ-SCORE-CHAMP-INTERDIT`, insensible à la casse et aux accents), un test vérifie que la liste ne
recoupe ni les faits ni les signaux, et un test prouve que trois leads identiques aux noms, téléphones et courriels différents ont le
même score, au signal près. La ville n'est qu'un booléen de présence. *Limite* : l'absence d'attribut protégé ne prouve pas l'absence
de proxy (ex. le canal d'arrivée) ; aucune mesure de disparité sur de vraies données n'existe.

**Calibration mesurée sur un jeu FICTIF** (`calibration_scoring.py`, stdlib seulement). Jeu synthétique à graine (entiers seulement :
même graine, même jeu, sur toute machine), propension de conversion « vraie » écrite à la main et **différente** du modèle (elle ignore
la valeur et les photos, elle ajoute du bruit) ; rangs pairs = entraînement du calibrateur (régression isotone PAV, paliers d'au moins
30 leads), rangs impairs = test. Résultats à la graine par défaut (2 000 leads) : AUC 0,6875 (Mann-Whitney, ex æquo à demi) ; Brier
calibré 0,1926 contre 0,2096 pour le taux de base (gain 8,1 %) et 0,2773 pour le score brut lu comme probabilité ; ECE 0,0314 calibré
contre 0,2908 brut. Sur cinq graines : AUC de 0,63 à 0,71, ECE calibré de 0,028 à 0,045. **Ce que cela prouve** : l'outil de mesure est
exact (valeurs connues calculées à la main, invariances, monotonie), le calibrateur est monotone, le score ordonne mieux que le hasard
sur un jeu où la structure existe. **Ce que cela ne prouve pas** : la moindre capacité à prédire de vrais clients. Tant que la mesure
n'est pas refaite sur des conversions réelles consenties (EFVP Loi 25 d'abord), le score est un **rang**, jamais une probabilité
(`probabilite_calibree: null`).

**Gates restés ouverts** (matrice) : (a) la politique de profilage Loi 25 n'est pas rédigée — ce score ne prend aucune décision à
effet sur la personne (un humain décide), mais la qualification juridique est à valider auprès d'un professionnel qualifié (juridique) ;
(b) poids et seuils : les poids et les paliers ci-dessus sont des valeurs initiales déclarées par l'architecte pour rendre le modèle
lisible et testable, à confirmer par Nathan ; les bandes de valeur sont à configurer.

## 3. M2.9 Coach de vente IA, gouverné

```
agent (modèle) --lit--> m2_contexte_coach --> faits du CRM (id + phrase fixe) + extraits M10 (provenance)
agent --propose--> m2_proposer_suggestion_coach (faits_cites, empreinte_contexte, sources_citees)
                     |- garde-fou de texte (prix, offre, date, engagement, aveu, avis légal, garantie, exagération, lien,
                     |  contact, nom du client, identifiant interne)  |- remise / pourcentage  |- envoi présenté comme fait
                     |- tout nombre du texte doit figurer dans un fait cité  |- fait inconnu / sans fait / contexte périmé
                     '--> journal chaîné `suggestions_coach` (niveau N2, envoye: false)
vendeur --décide--> m2_decider_suggestion_coach (accepter | modifier + mêmes contrôles | rejeter)  [N2, personne]
envoi au client : jamais ici -> sas courriel de M1 : brouillon -> demande d'approbation N3 -> envoi
```

**Matière.** Les faits sont : statut, règle de prochaine action (`suggestions.suggerer`, M2.6), score et facteurs dominants, relances
dues et canaux permis (consentement), profil de propriété confirmé, devis, trois dernières interactions humaines. Chaque fait a un
identifiant (`genre-hash8`) et une phrase **fixe** ; l'`empreinte_contexte` change dès qu'un fait change, et une suggestion bâtie sur un
dossier périmé est refusée (`REJ-COACH-CONTEXTE-PERIME`). Les extraits de la base de connaissances (celle de M2 et celles de ses
`dependances`, le droit de lecture inter-départements existant) portent leur **provenance** (éditeur, référence, version, dates,
licence, péremption) ; « aucune_source » veut dire que le coach ne répond pas de mémoire. Une source citée doit être publiée, lisible
par M2 et non périmée à la date de la suggestion (`REJ-COACH-SOURCE-INCONNUE`) ; sa provenance est copiée au journal.

**Garde-fous (preuves).** Aucun prix, aucune remise (mot ou pourcentage), aucune date promise, aucun engagement, aucune garantie, aucun
contact, aucun nom de client, aucun identifiant interne, aucun nombre absent d'un fait cité, aucun envoi présenté comme fait : 18 cas
d'abus du module pur, 15 d'outil. Le texte d'une interaction ou d'une source est neutralisé avant d'atteindre le modèle ; un test a
attrapé un trou réel (le champ `resume` n'était pas neutralisé) avant livraison.

**Journal et acceptation.** `suggestions_coach` garde chaque suggestion (texte, faits cités avec leur phrase, sources citées avec
provenance, auteur) et chaque décision (qui, quand, texte final, motif). `m2_lister_suggestions_coach` rend le bilan : décisions par
type et taux d'acceptation (accepter + modifier) / décidées, **rendu seulement à partir de 20 décisions**. Une suggestion ne se décide
qu'une fois ; un vendeur ne décide que sur SES leads ; l'agent ne peut pas décider (`REJ-HUMAIN-REQUIS`).

**Évaluation par le gabarit commun** (`src/opsys/evaluation`, [EVALUATION.md](EVALUATION.md)) : 16 cas ajoutés au corpus de M2 (12 → 28),
écrits avant exécution : lecture du profil, refus de confirmer, injection par courriel, file de leads, refus d'écarter par le score,
refus d'attribut protégé, honnêteté sur la probabilité, refus d'envoi direct, refus de remise, contexte du coach, injection par une
note d'interaction, honnêteté sans source, analyse, prévision, refus de prévision ponctuelle, refus de valeur inventée. Résultats avec
les répondants simulés : `reference` 28/28 (27/27 sans le cas du pack sectoriel), qualifié, 5/5 sondes d'autorité tenues ;
`dangereux` 15/27 (non qualifié, 11 cas bloquants échoués, 5/5 sondes tenues) ; `inventif` 0/27. Aucun vrai modèle n'a été mesuré.

## 4. M2.15 Analytique et prévisions commerciales

**Reçu rejouable par le moteur de calcul de M5.** `moteurs_commerciaux.py` donne aux quatre calculs la forme des moteurs de M5
(`moteur(entrees, parametres) -> (sortie, None) | (None, verdict)`) et construit leur reçu avec le format `recu-calcul.v1` de
`m5_financecore.recu_calcul`, **par le pont du socle** `opsys.recu_calcul_pont` (M2 n'importe pas M5 : #109). Un reçu de M2 est donc
vérifié tel quel par `m5_verifier_recu_calcul` (testé) et **rejoué** par `m2_rejouer_recu_commercial` : même moteur, mêmes entrées,
mêmes paramètres, mêmes empreintes — ou le refus d'un reçu retouché, compact (sans entrées : vérifiable, non rejouable) ou d'un moteur
inconnu. Un résultat forgé dont les empreintes ont été refaites est **découvert par le rejeu** (test). Aucun flottant n'entre dans un
reçu (entiers et fractions exactes, texte décimal).

**Analytique** (`previsions.analyser`, sur des enregistrements ANONYMES : ni identifiant, ni contact) : pipeline par statut ; entonnoir ;
taux de qualification ; taux de conversion des leads **résolus** (convertis ou perdus : un lead ouvert n'est ni gagné ni perdu) ; délai
de cycle (jours, quantiles au rang le plus proche : p25, médiane, p75, moyenne) ; probabilité de conversion par étape ; **valeur
pondérée** = Σ valeur déclarée × P(conversion | étape), avec intervalle par bootstrap des leads résolus (graine déclarée).

**Seuils d'échantillon déclarés** (dans chaque reçu ; relevables, jamais abaissables) : 20 leads résolus (taux de conversion), 20 leads
ingérés (taux de qualification), 10 convertis (délai de cycle), 20 résolus par étape (probabilité qui pondère la valeur), 12 semaines
complètes et 20 événements (prévision). Sous le seuil, la mesure rend `valeur: null`, son effectif `n`, son seuil et un `refus` qui dit
ce qu'il manque ; la prévision refuse avec `REJ-PREV-ECHANTILLON-INSUFFISANT`. Sans valeur déclarée, la valeur pondérée est « non
calculable ». La valeur est déclarée par une PERSONNE (`m2_declarer_valeur_pipeline`, N3) : estimation commerciale, jamais un prix de
M3 (M2 « n'est pas source financière »).

**Prévision** (`previsions.prevoir`) : séries hebdomadaires de comptes (blocs de 7 jours qui se terminent à l'instant de référence, la
semaine en cours et l'avant-CRM exclus, 104 semaines au plus) de leads ingérés, qualifiés, convertis ou perdus ; **moyenne mobile**
(fenêtre 2 à 12) ou **lissage exponentiel** simple (alpha de 0,001 à 1) ; **intervalle** à 80, 90 ou 95 % par bootstrap des résidus à
un pas (200 à 5 000 tirages, `random.Random(graine)`, valeurs simulées bornées à zéro), pour le total de l'horizon et par période ;
le « centre » est un repère, pas une promesse. Refus typés : série constante (`REJ-PREV-SERIE-DEGENEREE`), horizon au-delà du tiers de
l'historique, fenêtre au-delà de sa moitié, moins de 8 résidus. Un intervalle de largeur nulle (historique récent entièrement nul)
porte un avertissement. *Limite* : modèle de niveau sans tendance ni saison, résidus supposés échangeables.

## 5. Intégration

- **Manifeste** (`department.yaml`) : quatre skills (`profil-de-propriete`, `scorer-et-classer-les-leads`, `coacher-un-vendeur`,
  `analyser-et-prevoir-le-pipeline`), l'événement publié, `configuration.scoring: {}` (bandes à configurer). `SOUL.md` : quatre
  paragraphes et trois interdits ; l'empreinte pinned dans `tests/test_packs_generalisation.py` est mise à jour (aucun terme sectoriel).
- **Registre MCP** : 16 outils ajoutés, `opsys-metier registre-mcp verifier` puis `sceller --par m2-victor`.
- **Pas de migration** (les registres sont génériques) ; la migration 0045 réservée n'est pas utilisée.
- **Base de connaissances** : lecture seule par `opsys.connaissances` (`rechercher_pour`, `lire_version`), jamais d'écriture, jamais ouverte aux appareils.

## 5 bis. Le filet anti-perte (M2-C1) : SLA, intégrité, réparation, constat vers M8

Autonomie : tout est **lecture (N0)** sauf le constat (T1/N2, agent seulement) ; aucun outil n'a de droit d'appareil ; rien n'est envoyé,
changé, fusionné ni supprimé. `sla.py` (sept règles, délais DÉCLARÉS dans `configuration.sla`, jamais inventés : un délai absent rend la règle
« non évaluée » et dit quoi déclarer), `integrite.py` (huit contrôles ; doublons en lecture seule avec le MÊME critère et la MÊME fenêtre que
l'ingestion), `reparation.py` (actions proposées, `execute: false` ; une action dont l'outil réel est N3 demande l'approbation d'une
personne ; la prochaine meilleure action existante accompagne chaque lead), `constat_filet.py` (comptes seulement, `null` pour ce qui n'est pas
évalué) : quatre modules purs, une couture (`outils_integrite.py`). Le constat est déclaré dans `constats_planifies` (exécuteur
`m2.constat.filet`) : inactif par défaut, `ombre` ne publie rien, un même créneau ne publie rien de plus
([PLANIFICATION §9](PLANIFICATION.md)) ; M8 en tire `m8_violations_sla_commercial` et `m8_anomalies_integrite_crm`
([M8-ENTREPOT-SOURCES](M8-ENTREPOT-SOURCES.md)). Les cinq nombres de M2 sont lus par une seule fonction (`outils._bloc_configuration`) pour
qu'un mécanisme de réglages de direction n'ait qu'elle à brancher. Détail et limites : [README de M2](../../departments/m02-revenue-crm/README.md).

M2-C5 : `client_satisfait` (M4) et le devis envoyé (M3) sont gardés et lus (segments `referral_candidate`, `complaint_risk`, `quote_sent`) ; une
relance préparée que personne n'a notée au dossier ne retarde plus la suivante (la note d'une personne date la fréquence).

## 6. Preuves exécutées

Suite du département rejouée (`pytest departments/m02-revenue-crm/tests`) : **2 269 réussis, 0 échec, 0 sauté** (1 926 avant cette
tranche : 343 tests ajoutés). Gardes d'intégration et parcours d'appareil (portées, paquets, garde-fou de texte, commande métier,
registre MCP, packs sectoriels, évaluation, matrices, accès par propriétaire, événements, cascades M2, connaissances, e2e M2 sur SQLite
et PostgreSQL) : 890 réussis. Les nouveaux tests échouent AVANT le code (ImportError : aucun module, aucun outil) et passent après.
Suites : tests purs (`test_propriete`, `test_scoring`,
`test_previsions`, `test_coach`, `test_moteurs_commerciaux`), tests d'outils sur une vraie base SQLite migrée avec de vraies personnes
(`test_*_outils`), parcours par la vraie porte d'appareil, SQLite **et** PostgreSQL (`tests/e2e/test_ventes_vendeur_appareil.py`),
garde d'intégration (portées, paquets, garde-fou de texte, commande métier, packs sectoriels, évaluation, registre MCP).
**Mutations** : 35 mutations personnelles (désactiver une garde, inverser une comparaison, retirer une validation, relâcher un seuil,
décaler une frontière) ; 33 tuées du premier coup, 2 survivantes (une frontière de semaine exacte, le choix de la dernière confirmation
d'un profil) qui ont donné deux tests de plus et sont tuées à leur tour : 35 sur 35.

## 7. Cas d'abus couverts

Entrée hostile (champs hors liste blanche, valeurs hors bornes, caractères de contrôle, texte de 8 000+ caractères, montants mal
formés, alpha/graine/horizon hors bornes) ; double soumission (révision périmée, décision répétée, rejeu d'une confirmation idempotente
= un seul fait publié) ; injection dans les données (courriel, note d'interaction, source de connaissances, texte libre d'un profil) ;
dépassement de quota (10 propriétés par client, 200 révisions par propriété, 200 suggestions par lead) ; secret ou contact dans un
journal (aucun courriel ni téléphone ne se retrouve dans les registres) ; accès d'un autre vendeur, de l'employé, de l'agent seul sur
un geste humain ; refus sans écriture (toutes les tables de la base comparées avant et après).

## 8. Limites : ce qui n'est PAS prouvé

- **Aucun modèle réel.** La qualité des textes du coach n'est jamais mesurée ; le gabarit d'évaluation n'a été exécuté qu'avec des
  répondants simulés. Les garde-fous sont des motifs : un texte qui contourne les motifs sans être sobre n'est pas exclu (la barrière
  réelle reste l'approbation humaine N3 de tout envoi et la décision du vendeur).
- **Aucune donnée réelle.** Calibration, taux, délais, probabilités et prévisions n'ont été calculés que sur des jeux fictifs ou sur des
  leads d'essai. Aucune capacité prédictive n'est affirmée.
- **Poids, paliers, seuils** : valeurs initiales déclarées ; décision de Nathan requise (poids et seuils du scoring, bandes de valeur,
  seuils d'échantillon). Politique de profilage Loi 25 non rédigée.
- **Consommateurs.** `m2.profil_propriete_confirme` est publié mais ni M3, ni M4, ni M10 ne le consomment encore ; le déclencheur « un
  courriel arrive → extraire le profil » est à configurer comme profil d'agent ; la lecture des courriels passe par M1.
- **Effacement et rétention.** Les registres sont append-only : aucun outil d'effacement d'une propriété (Loi 25, droit à l'effacement)
  ni de purge à échéance n'est livré ; à traiter avec la procédure d'effacement de la plateforme avant une mise en production.
- **Proxys** : l'absence d'attribut protégé ne prouve pas l'absence de proxy ; aucune mesure de disparité.
- **Prévision** : modèle de niveau, ni tendance ni saison ; 12 semaines d'historique minimum seulement ; la valeur pondérée suppose
  une valeur déclarée par le vendeur (biais d'optimisme possible, non mesuré).
- **Passerelle et core natif.** Le parcours d'appareil est le harnais Python (`tests/fixtures/harnais_e2e.py`), pas le core
  TypeScript natif ni l'app mobile.
- **Documents.** Les photos et les mesures ne sont que des références : aucun contrôle que le fichier ou la mesure existe chez M3/M4.
- **Filet anti-perte (M2-C1).** Les délais de SLA sont une décision de Nathan : aucun n'est livré, donc sans déclaration les règles à délai sont
  non évaluées. M2 n'a ni entité « tâche » ni accusé d'envoi : « contacté » et « escaladé » se lisent à la note d'une personne, « tâche en retard »
  est la prochaine action échue sans activité humaine postérieure. Les clients importés à l'onboarding ne sont pas audités. SQLite, données fictives,
  horloge injectée seulement ; faux positifs sur de vrais carnets non mesurés.
