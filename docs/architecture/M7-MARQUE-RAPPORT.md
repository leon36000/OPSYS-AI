# M7 : marque v2, score de conformité, rapport hebdomadaire et mémoire marketing

Statut (2 novembre 2026, base `e0424b040`) : **prouvé en processus** sur SQLite, avec le vrai bus, les vrais outils (M7, M8,
M10), le vrai planificateur durable à horloge injectée et des données fictives. **Aucune preuve** contre un service externe
réel, aucune publication réelle exécutée, **PostgreSQL non exercé** pour ces chantiers (aucune migration, aucune garde « SQLite
seulement » ajoutée : les registres sont des maillons génériques). Les statuts des matrices restent `PARTIEL` : la validation du
profil réel par Nathan est une décision qui n'est pas prise (voir §10).

Trois volets, une seule règle : **le code calcule, le modèle n'invente rien, une donnée absente est dite absente.**

| Volet | Ce qui est livré | Où |
|---|---|---|
| M7-MARQUE | Brand Core v2 déclaré par le propriétaire ; score de conformité déterministe intégré à la porte qualité ; audit d'un contenu existant ; guide de ton généré | `brand/profil_v2.py`, `brand/conformite.py`, `brand/guide.py`, `marque_outils.py`, `usine/chantier.py`, `usine/service.py`, `contracts/brand-contract.v2.yaml` |
| M7-RAPPORT-HEBDO | Rapport marketing hebdomadaire (boucle B) planifié, recommandations sourcées, tâches internes de niveau bas, plan de croissance organique dérivé des données | `rapport_hebdo/`, `rapport_outils.py`, `growth.py`, `src/opsys/connecteurs_planification/exec_m7_rapport.py` |
| M7-MEMOIRE | Événement minimal `m7.apprentissage_marketing_constate` ; mémoire de M10 ; leçons GOUVERNÉES de genre `apprentissage_marketing` | `rapport_hebdo/memoire.py`, `m10_memoire/apprentissage_marketing.py`, `opsys/mnemo/lecons.py` |

## 1. Brand Core v2 : déclaré, validé, jamais inventé

Le contrat gelé v1 (`brand-contract.v1.yaml`, cinq champs) n'est pas touché. `contracts/brand-contract.v2.yaml` l'**étend de façon
additive** : un profil v1 est lu tel quel, c'est un profil v2 dont aucun champ étendu n'est déclaré (`profil_v2.version_de_lecture`).

Champs étendus, tous DÉCLARÉS par le propriétaire (`m7_configurer_profil_marque`, réservé au propriétaire actif) :

| Famille | Champs | Effet |
|---|---|---|
| Énoncés positifs | `promesse`, `avantages`, `zones_desservies`, `valeurs`, `objections_frequentes`, `preuve_sociale`, `mentions_requises` | repris (guide, mentions ajoutées par les gabarits) **seulement si VALIDÉS** par le propriétaire (`validation_champs`) ; sinon « à valider par Nathan » |
| Restrictions | `mots_interdits`, `messages_interdits`, `garanties_a_valider` | en vigueur dès leur déclaration (la prudence n'attend pas de validation) |
| Règles | `voix` (vouvoiement/tutoiement, exclamations, majuscules, émojis), `style_plateforme` (longueur min/max, mots-clics, émojis) | idem |
| Déjà acceptés | `garanties_validees` (mot pour mot), `site_url`, `hashtags`, `heures_publication` | inchangés |

- **Absent = dit absent.** `profil_v2.completude` rend l'état de chaque champ (`absent`, `declare_a_valider`, `valide`, `declare`) et,
  pour chaque champ absent, la question à poser au propriétaire (`a_fournir`). Aucune valeur par défaut. Une dimension de
  conformité qui dépend d'un champ absent est **non évaluable** (score `None`), jamais notée.
- **Validation signée.** `registre.enregistrer` refuse une validation (`statut: valide`) dont `par` n'est pas la personne qui
  configure, et la validation d'un énoncé absent. Un énoncé non validé qu'un texte cite mot pour mot est refusé
  (`REJ-MARQUE-PROMESSE-NON-VALIDEE`) : c'est la garde « garantie non validée » étendue aux énoncés du profil.
- **Une donnée, pas une instruction.** Chaque valeur est une ligne de texte bornée, sans saut de ligne ni caractère de format
  (un champ qui voudrait glisser une consigne dans le guide est refusé à la déclaration, le message nomme le champ, jamais la valeur).
- **Relecture tolérante.** Une révision enregistrée avant le contrat v2 sous un nom devenu champ étendu (`voix` en texte libre)
  ne casse pas le registre : `profil_v2.assainir` retire le champ de la LECTURE, le dit en avertissement et ne l'applique jamais.
  Toute NOUVELLE révision est validée strictement.

## 2. Score de conformité : verdict, sous-scores, raisons

`brand/conformite.py` (module pur, aucune horloge, aucun modèle, aucune entrée-sortie) : `evaluer(texte, profil, plateforme)`.

**La porte binaire existante reste la loi.** `usine.controle_texte` (familles nommées du socle `opsys.garde_fou_texte`) est appelée
telle quelle ; chacune de ses violations devient une raison **bloquante** rattachée à une dimension. Le score ne peut jamais
faire passer un texte que la porte refuse (invariant testé sur un corpus et sur des profils dépouillés), ni refuser un texte que la
porte accepte sans qu'une règle déclarée par le propriétaire le dise.

| Dimension | Poids | Bloquante | D'où elle vient |
|---|---|---|---|
| `mots_interdits` | 15 | oui | `mots_interdits` du profil (mot entier, casse, accents, pluriel simple, lettres imitées) |
| `messages_interdits` | 10 | oui | `messages_interdits` |
| `promesses_non_validees` | 15 | oui | socle : garantie non validée, exagération ; profil : énoncé cité mot pour mot et non validé |
| `prix_et_chiffres` | 15 | oui | socle : prix/offre, chiffre sans source, promesse de date |
| `confidentialite` | 15 | oui | socle : adresse, coordonnées, nom de client, identifiant interne, lien |
| `ton` | 10 | tutoiement/vouvoiement fort | `voix` : adresse (bloquant), exclamations, majuscules, émojis (réserves) |
| `longueur_plateforme` | 5 | plafond | plafond interne de la plateforme (socle) + `longueur_max` déclaré (bloquants), `longueur_min` (réserve) |
| `style_plateforme` | 5 | non | mots-clics et émojis déclarés pour la plateforme (réserves) |
| `mentions_requises` | 10 | oui | `mentions_requises`, contenu public seulement |

- **Verdict** : `refuse` (au moins une raison bloquante), `conforme_avec_reserves` (aucune, mais une réserve), `conforme`.
  Un verdict `conforme` ne dit **rien** des dimensions listées dans `non_evaluables` (profil incomplet).
- **Score global** : moyenne des sous-scores ÉVALUÉS pondérée par des poids fixes (somme 100), arrondie au demi supérieur. Tout
  sous-score inférieur à 100 porte au moins une raison nommée ; le score se recalcule à la main (testé).
- **Fail-closed** : profil absent, sans nom ou non configuré -> `profil_marque_non_configure`, verdict `refuse`, aucun score.

Intégration à l'usine (`usine/chantier.py::evaluer_texte`, `usine/service.py::_refus_texte`) : le texte du **gabarit du code** comme le
texte **du modèle** passe la porte à la proposition ; un texte refusé n'est jamais enregistré (le refus nomme chaque règle et
porte le score) ; la porte est rejouée à l'**approbation** et à l'**export** (un profil durci après la proposition bloque
l'approbation) ; la proposition range `conformite` (verdict, score, sous-scores) et le compte rendu de proposition le montre ; la file de
lecture (`m7_lister_contenus_chantier`) ne le porte pas (sa lecture tient déjà de justesse sous la borne de 6 000 caractères) :
le score d'un contenu se relit avec `m7_auditer_contenu_marque`. Les mentions requises VALIDÉES sont ajoutées par les gabarits aux textes
publics et masquées de la porte binaire (un numéro de licence ressemble à une coordonnée) ; non validées, elles ne sont pas
ajoutées et les textes publics sont refusés avec la raison. `m7_lire_matiere_chantier` donne à la rédaction les règles du profil
(`regles_marque`), jamais un énoncé positif non validé.

**Audit d'un contenu existant** : `m7_auditer_contenu_marque` (T0, agent seulement) évalue jusqu'à 30 textes par appel (8 par page,
`reprendre_a`), rend verdict, score, sous-scores et raisons, n'écrit rien, ne répète jamais une coordonnée ou une adresse
détectée (valeur non répétée). **Guide de ton** : `m7_guide_de_ton_marque` projette le profil (voix, énoncés validés, à ne jamais
dire, style par plateforme, mentions, ce qui reste à fournir) ; un énoncé non validé n'y figure que par son nom.

## 3. Rapport marketing hebdomadaire (boucle B)

**Sources** (aucune n'est recalculée) : mesures de l'entrepôt de M8 (`m8_lire_mesures` : coût par lead, leads publicitaires,
dépense comptabilisée de M5, signaux ; `m8_lire_mesures_contenus` : leads et devis par `utm_content`) lues par l'exécuteur du
planificateur (N0, liste fermée de deux outils, aucun droit d'appareil élargi) ; performance des campagnes de M7 (leads de M2, devis de
M3, marge constatée de M5), calendrier, avis et observations de croissance, lus dans le dossier de M7. M7 n'importe jamais le code
d'un autre département.

**Sections** : `leads_par_canal`, `cout_par_lead` (valeur de M8 telle quelle), `conversion` (rapport de comptes entiers, seuil de 5
leads), `roi`, `croissance_engagement`, `contenus` (meilleurs et pires, seuils de 3 contenus mesurables et 14 jours), `calendrier`,
`reputation`, `plan_croissance`, `mesures_m8`. Chaque section est `calcule`, `donnees_insuffisantes` ou `source_absente` et **dit ce
qui manque** ; un jour sans fait n'est pas un zéro.

**ROI honnête.** Le rapport affiche la marge constatée par M5 et la dépense comptabilisée de M5 (via M8), mais `roi` vaut `null`
et la raison le dit : les deux ne couvrent pas forcément les mêmes canaux ni la même période, et M7 ne recalcule pas la finance.
À valider auprès d'un comptable (CPA) / professionnel qualifié.

**Recommandations** (`rapport_hebdo/recommandations.py`) : des règles lisibles et nommées ; chacune porte ses `sources` (mesure de
M8, contenu, observation, section de M7) **ou** `hypothese: true`, sinon elle est refusée à la construction ; `verifier_liaison`
vérifie que chaque source figure dans les références du rapport. Priorité = impact x facilité (1 à 25) ; ordre déterministe ; au
plus douze recommandations ; les cinq mieux classées qui sont actionnables deviennent des **tâches internes de niveau bas** (N1,
registre `taches_marketing`, section « À voir »), valables jusqu'au rapport de la semaine suivante. Aucune ne déclenche une
publication, une dépense ou un envoi.

**Plan de croissance** (`rapport_hebdo/croissance.py`, utilisé aussi par `m7_generer_plan_growth_30j`) : remplace « poursuivre la mesure ».
Les observations dont la campagne est étiquetée `format:…`, `creneau:…` ou `serie:…` sont comparées (trois observations par
étiquette au moins, deux étiquettes au moins, écart de 20 % au moins entre la première et la deuxième) ; sinon le plan dit
exactement ce qui manque. La garde `verifier_legitimite` refuse tout texte qui parlerait d'achat d'abonnés, de faux engagement, de
pods, de spam, de messages massifs, de bots ou de contournement des limites (même si le libellé vient d'une donnée piégée).

**Planification** : exécuteur `m7.rapport-hebdo` (N2, famille « departements », passage quotidien par défaut, **inactif par défaut**).
Ombre : constate la semaine visée et si le rapport existe, sans lire M8, sans écrire, sans publier. Actif : la semaine est la dernière
semaine ISO complète avant la date locale du jour (Toronto) ; tous les passages d'une même semaine visent donc la même semaine et le
rapport est écrit **une seule fois** (un passage de plus ne relit même pas M8). Si M8 ne répond pas, **rien n'est écrit** (un rapport
dégradé ne doit pas verrouiller la semaine) et le tour suivant reprend. Le rapport, ses tâches et ses observations d'apprentissage
sont écrits dans **une transaction**. Ce n'est pas un `constats_planifies` déclaratif (un seul outil, un résumé publié pour M8) :
le rapport compose deux départements, ce qu'un constat à outil unique ne peut pas faire.

## 4. Mémoire marketing : `m7.*` -> M10 -> leçons gouvernées

`m7.apprentissage_marketing_constate` (catalogue `src/opsys/evenements/catalogue/`) : `observation_id` déterministe, `semaine`
(lundi), `genre_observation` (`contenu_gagnant`, `contenu_faible`, `objection_frequente`, `avis_constate`), `canal` (liste fermée),
`cle_mesure` (`utm_content`, catégorie d'avis ou `semaine`), des comptes entiers ou `null`, l'empreinte du rapport. **Aucun texte de
contenu ni d'avis, aucune coordonnée, aucun identifiant de lead ou de chantier.** Le signal d'objection est tiré des **catégories**
d'avis (litige, urgence), pas d'un texte de client.

Consommateur de M10 (`apprentissage_marketing.py`, registre `faits_marketing`, `INTERNAL`) : liste blanche stricte, une observation par
`observation_id`, même identifiant avec un autre contenu = contradiction nommée (la première reste). Les cinq garanties sont rejouées
sur le vrai bus (`tests/test_interconnexion_consommateurs.py`, cas `m10-apprentissage-marketing`) : livré, idempotent sous un autre
`evenement_id`, panne puis reprise unique, charge hors catalogue refusée, rien de personnel au reçu.

**Leçons** (`opsys/mnemo/lecons.py`, genre `apprentissage_marketing`, cible `m07-marketing`) : le code propose une leçon quand une même
observation (genre, canal, catégorie) revient sur **trois semaines distinctes** (jamais trois observations de la même semaine) ;
le texte est un gabarit sans chiffre ni nom (`TEXTES_MARKETING`) ; le genre n'a pas de mesure chiffrée hors ligne (dit) ; la garde du
gabarit réel de M7 est rejouée ; la décision (canari, promotion, retour arrière) est **humaine** et `opsys_lecons_actives` la rend
lisible par M7, qui décide s'il l'applique. Rien ne s'applique seul.

## 5. Outils ajoutés (trois, agent seulement, aucun droit d'appareil)

| Outil | Autonomie / niveau | Rôle |
|---|---|---|
| `m7_auditer_contenu_marque` | T0 / N0 | audit de conformité de textes existants |
| `m7_guide_de_ton_marque` | T0 / N0 | guide de ton généré du profil |
| `m7_lire_rapport_hebdomadaire` | T0 / N0 | lecture du rapport composé par le planificateur (montants : admin confirmé) |

Aucun outil n'écrit un contenu public, ne publie, ne dépense ni n'envoie. Le registre MCP est rescellé (`registre-mcp sceller`).
Aucune migration.

## 6. Preuve

Voir le tableau des tests et des mutations au §9 ; les commandes et résultats exacts sont dans le rapport de livraison.

## 7. Ce qui est volontairement hors périmètre

Pas de modèle de langage pour noter ; pas de publication ; pas de campagne payante ; pas de nouveau droit d'appareil ; pas de
calcul de ROI ni de marge ; pas de lecture directe d'un registre d'un autre département.

## 8. Limites connues (sans euphémisme)

- **Un motif ne comprend pas le sens.** « Pas cher » cité pour être nié est refusé ; un mot interdit est cherché au mot entier avec
  pluriel/féminin simples (s, x, e, es), pas par racine ; les marqueurs de tutoiement ambigus (« ton », « ta », « te ») ne sont
  qu'une réserve ; « ton » comme nom commun la déclenche.
- **Gabarits du code au vouvoiement.** Un profil qui déclare le tutoiement fait refuser les gabarits (« vous ») : les textes doivent
  alors être fournis (`textes`).
- **Un énoncé non validé n'est détecté que cité mot pour mot** (après pliage des accents et de la casse) ; une paraphrase passe.
- **Le nom d'un client** n'est détecté que par les formes connues du socle (civilité + nom, « la famille X »…).
- **M8 n'a pas de fenêtre de période pour les contenus** : « leads par contenu » est cumulatif depuis l'export ; le rapport le dit.
  Le coût par lead n'existe que si le propriétaire a déclaré la correspondance des canaux et si des relevés de dépense existent.
- **L'objection n'est pas tirée du texte des avis** mais de leur catégorie (litige, urgence) : un signal de friction, pas un thème.
- **Les tâches** n'ont pas d'outil de clôture : elles disparaissent au rapport de la semaine suivante.
- **Le rapport est écrit une fois par semaine** : le premier fait foi, même si une donnée arrive ensuite ; aucune révision.
- **Plan de croissance** : l'étiquetage `format:`/`creneau:`/`serie:` de la campagne d'une observation est une convention ; sans elle,
  rien n'est comparé. Observationnel, jamais causal.
- **Les listes de familles du socle** ne sont pas modifiées : un nouveau mot interdit se déclare au profil, pas dans le socle.
- **Autres chemins de contenu** : `m7_proposer_contenu` (fabrique de contenu historique) n'applique pas encore la porte de marque v2 ;
  seule l'usine de chantier, l'audit et le guide l'appliquent.
- **PostgreSQL**, un vrai service externe, une publication réelle, un vrai modèle de langage : non exercés.
