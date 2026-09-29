M7-marketing

Marketing & Croissance IA — PREMIER MODULE (D-008)

Statut: PARTIAL (mode ombre : le pilote M7-S000 a été suivi des vagues 2 et 3 — site Quadruple A,
content factory, données saisonnières, competitive engine, grille AEO/GEO, convention UTM,
attribution, ROI, puis l'usine à contenu de chantier de T4.17. 889 tests (dossier `tests/` de M7). Le
statut du registre est la source de vérité, gate statut_lint.)

## M7-S000 — Brand Core minimal

Le fichier `src/brand/profile.yaml` est un **GABARIT initial** ; les valeurs proposées
(name, tagline, tone, colors, langue) sont à faire valider par Nathan.

### Endpoint

`GET /brand`

- **200** — `application/json; charset=utf-8` : le profil validé et normalisé.
- **500** — `application/problem+json` (RFC 9457) : profil invalide, YAML malformé,
  ou tag YAML interdit. Le `detail` ne contient jamais le chemin disque du fichier.
- **404** — `application/problem+json` : chemin inconnu ou `/brand/`.
- **405** — `application/problem+json` : méthode non autorisée ; l'en-tête
  `Allow: GET` est renvoyé.
- Les champs inconnus du profil sont tolérés SEULEMENT s'ils sont JSON-sérialisables
  (sinon 500).
- Les query strings sont ignorées sur `/brand`.
- Toutes les réponses portent l'en-tête `X-Contract-Version` indiquant la version
  du contrat gelé en vigueur (actuellement `1`).

### Lancement manuel

```bash
python3 brand_server.py [port]
```

Le serveur se bind sur `127.0.0.1` et affiche le `host:port` réel.

### Tests

```bash
python3 -m pytest "departments/m07-marketing/tests" -q
```

## Demande d'avis : le consentement du client, recueilli à « Terminer » (PLAN T1.5-d)

DEFINITION-PRODUIT §6 : à « travaux terminés », M7 « propose une demande d'avis ». La demande naît du
**consentement explicite du client à être contacté pour un avis**, que l'employé recueille auprès de lui dans
l'app (écran « Terminer », `mobile/src/m4/consentementClient.ts`, cases non cochées par défaut, texte fr-CA
versionné).

- **Deux consentements distincts** (Loi 25, `POLITIQUE-photos-non-contractuelles.md` §3) : `consentement_demande_avis`
  (être contacté pour un avis, ce qui suit) et `consentement_marketing` (l'usage de photos, section suivante).
  L'un n'est jamais déduit de l'autre.
- **M4 le porte avec sa preuve**, posée par le serveur (`consentement_recueilli_par` : la personne authentifiée ;
  `consentement_recueilli_le` : l'heure de réception du serveur ; `consentement_version_texte` : le texte présenté).
  Clés additives de `m4.travaux_termines`. M7 les lit dans le WCT reçu par le bus, jamais dans un argument.
- **Fail-closed** (`reputation/demande_avis.py`) : consentement absent, faux ou sans sa preuve, ou
  `client_satisfait = false` : aucun brouillon. Le WCT reste quand même enregistré (`wct_recus`).
- **Le brouillon** (`demandes_avis`, gabarit fixe, jamais un texte de modèle) porte la preuve du consentement.
  Nature des travaux (T0.13-b) : `type_travaux` pour un lead v1, le **libellé du service** déclaré par l'entreprise
  (`opsys.taxonomie`) pour un lead v2 ; jamais l'un déduit de l'autre. Service non déclaré : texte générique et
  `avertissements` le dit.
- **Jamais envoyé** : `approval_status` reste `PROPOSE`. L'envoi au client est un engagement externe (T3), une
  décision humaine qu'aucun outil de M7 ne prend. L'admin relit les brouillons par `m7_lister_demandes_avis`
  (T0, `admin`, huit au plus par appel).
- **Limite** : `client_satisfait = false` refuse encore la demande (règle de T1.2-c). Les plateformes d'avis interdisent de
  ne solliciter que les clients satisfaits (P9) : décision à confirmer par Nathan.

## Contenu public : consentement + floutage (PLAN T4.3)

- `m7_marketing.brand.profil_client` : chargement fail-closed du profil de marque du CLIENT
  (`brand/profile.yaml`, versionné). Tant que `name` porte le repère `PLACEHOLDER_NOM`
  (« À CONFIGURER (GATE NATHAN) »), le profil est refusé — le nom commercial exact reste une
  décision de Nathan, jamais deviné ici.
- `m7_marketing.moderation.{image,detection,floutage}` : floutage déterministe (pixellisation
  par bloc) de visages et de plaques, détecteur injectable (`Detecteur`, protocole), testé par
  des images synthétiques. Briques retenues pour l'implémentation réelle (voir
  [`docs/research/INGREDIENTS.md`](../../docs/research/INGREDIENTS.md) § M7) : OpenCV
  (Apache-2.0) + YuNet (MIT) pour les visages, cascade Haar OpenCV (Apache-2.0) pour les
  plaques — `cv2` n'étant pas installé dans ce dépôt, `detecteur_opencv_par_defaut()` échoue
  avec `DetecteurIndisponible`, un refus nommé et testé, jamais un faux vert.
- `m7_marketing.content.contenu_public` + l'outil `m7_preparer_contenu_public(wct_id, photos,
  seuil_confiance)` (T1) : prépare un brouillon flouté avec la preuve du consentement et le
  rapport de floutage. **Ni le consentement ni l'identité de marque ne sont des arguments** de
  cet outil (relecture 0a7aaef, AGENTS.md « le LLM orchestre, il ne fournit jamais un fait ») :
  - le consentement vient du WCT `m4.travaux_termines` déjà reçu par le bus pour `wct_id`,
    enregistré tel quel dans le registre durable `wct_recus` par le consommateur d'événements
    (`outils.py::_recevoir_travaux_termines`/`_enregistrer_wct_recu`) — **quel que soit** le sort
    de la demande d'avis associée (un refus de demande d'avis n'empêche jamais d'enregistrer le
    fait). `wct_id` inconnu de ce registre → `statut: "wct_inconnu"`, jamais un brouillon ;
  - l'identité de marque vient du profil client configuré (`brand.profil_client`, non configuré
    → `statut: "profil_marque_non_configure"`).

  Refuse (fail-closed, aucun brouillon) si `wct_id` est inconnu, si `consentement_marketing` est
  absent/faux dans le WCT reçu, ou si le profil de marque n'est pas configuré. Une détection sous
  le seuil de confiance fourni ne bloque pas la préparation (le floutage est déjà appliqué par
  prudence) mais marque le brouillon `revue_humaine_requise: true` avec le motif — jamais un
  passage silencieux. Jamais une publication : la publication réelle reste N5 (approbation
  signée du socle), hors de ce module.

  **Retrait de consentement (Loi 25)** : depuis T4.17, le registre `retraits_consentement_marketing`
  existe (voir « Usine à contenu » ci-dessous). `m7_preparer_contenu_public` le consulte avant tout, y compris
  avant de rendre un brouillon déjà déposé (`statut: "consentement_retire"`). Le consentement exige aussi sa
  **preuve** (`consentement_recueilli_par`, `consentement_recueilli_le`, `consentement_version_texte`, posées par M4) :
  `consentement_marketing` vrai sans preuve refuse (`REFUS_PREUVE_ABSENTE`), pour cet outil comme pour l'usine.

## Usine à contenu : un chantier terminé donne cinq contenus et un paquet manuel (PLAN T4.17)

DEFINITION-PRODUIT §7 M7.3 (chantier → contenu) et M7.2 (« paquet manuel : texte, mots-clics, média, heure,
instructions »). Code : `src/m7_marketing/usine/` ; outils : `outils.py` (enveloppes minces sur `usine.service`).

**D'où naissent les contenus.** Du WCT `m4.travaux_termines` déjà reçu par le bus (registre `wct_recus`) et du profil de
marque du client (`brand/profile.yaml`, fail-closed tant que le nom porte « À CONFIGURER »). Jamais d'un fait fourni
par l'appelant : `m7_proposer_contenus_chantier(wct_id, textes?)` ne prend ni consentement, ni marque, ni ville.
Le consommateur du bus les propose lui-même à la réception du WCT ; l'outil sert à relancer (profil configuré après
coup) ou à proposer des textes rédigés par le modèle.

**Cinq contenus, un par plateforme** (`plateformes.py`) : publication Facebook, publication Instagram, mise à jour de
la fiche Google, script de vidéo courte, demande de témoignage (message privé au client). Chacun est `PROPOSE`, jamais
publié, avec la preuve du consentement (qui, quand, quel texte), ses mots-clics (termes du service, ville du WCT,
mots-clics du profil) et **son lien de suivi UTM** (`utm_source`/`utm_medium` de l'énuméré gelé du contrat S012 ;
`utm_campaign = contenu-<service>-<année>`, `utm_content = <plateforme>-<empreinte du chantier>` : aucun identifiant
interne dans une URL publique). Sans `site_url` au profil, ou avec un site non HTTPS, le contenu est proposé sans lien
et `avertissements` le dit ; la vidéo courte prend `tiktok`, seule source vidéo de l'énuméré ; la demande de témoignage
n'a pas de lien.

**Le code compose ou le modèle rédige, le code contrôle toujours.** Par défaut, les gabarits fixes du code
(`gabarits.py`) : la marque, l'accroche du profil, la nature des travaux, la ville seulement si le WCT en porte une.
`textes` (facultatif, par plateforme) : le texte rédigé par le modèle, après `m7_lire_matiere_chantier` (marque,
accroche, nature, ville, note du chantier si elle passe le contrôle, plafonds, règles). Dans les deux cas, chaque
texte passe `controle_texte.controler_texte` et un texte refusé n'est **jamais enregistré** ; le refus nomme la règle. Les
motifs ne sont plus écrits dans M7 (PLAN T4.17-c) : ils vivent dans le socle (`opsys.garde_fou_texte`, familles nommées), avec
ceux du garde-fou de M1 ; `controle_texte.py` choisit les familles d'un texte public (`PROFIL_TEXTE_PUBLIC`) et garde les noms
d'avant (`controler_texte`, `ContexteControle`, `REGLE_*`). Les règles d'un texte public (une réponse à un client, chez
M1, a d'autres familles) :

| Règle | Refuse |
|---|---|
| `REJ-ADRESSE` | numéro civique + voie, voie nommée, code postal, coordonnées GPS, unité |
| `REJ-COORDONNEES` | courriel, téléphone |
| `REJ-NOM-CLIENT` | civilité + nom, « la famille X », « chez X Y », « client : X », @mention, noms fournis |
| `REJ-IDENTIFIANT-INTERNE` | les identifiants du WCT (chantier, intervention, lead, devis, technicien) |
| `REJ-PRIX` | montant, tarif, prix, rabais, « gratuit », financement |
| `REJ-CHIFFRE-NON-SOURCE` | tout chiffre avec unité (pieds, heures, jours, ans, %) : les chiffres viennent d'un outil |
| `REJ-GARANTIE-NON-VALIDEE` | « garanti », « à vie », « satisfait ou remboursé »… sauf un énoncé de `garanties_validees` au profil, mot pour mot |
| `REJ-PROMESSE-DE-DATE` | date, « demain », « d'ici », « dans N jours », « au plus tard »… |
| `REJ-EXAGERATION` | « meilleur », « numéro 1 », « imbattable », « 100 % »… |
| `REJ-LIEN`, `REJ-LONGUEUR`, `REJ-TEXTE-VIDE` | lien dans le texte (le code ajoute le sien), plafond de la plateforme, texte vide |

Le nom de marque est masqué pour la garantie et l'exagération (une marque peut contenir « Garantie »). **Limites,
jamais cachées** : le WCT ne porte pas le nom du client, le contrôle reconnaît donc les FORMES qui désignent un client
(un prénom seul dans une phrase ordinaire n'est pas détectable) : la revue du propriétaire (N3) reste la dernière
barrière. Un motif ne comprend pas le sens (« meilleur » est refusé même dans une phrase inoffensive). Le garde-fou
de M1 (`garde_fou`) couvre d'autres familles (messages à un client) et n'est pas importé (aucun import entre
départements) : un module du socle qui réunirait les deux est une évolution possible.

**Refus de départ, RIEN d'écrit** (dans cet ordre) : un retrait du consentement de ce chantier ; le consentement
marketing absent, faux ou sans preuve ; un client insatisfait (`client_satisfait = false`) ; la nature des travaux
inconnue (un lead v2 dont le service n'est pas déclaré à l'entreprise : `opsys.taxonomie`, jamais recopiée) ; le
profil de marque non configuré. Sans consentement : aucun contenu, la demande d'avis (un autre consentement) est
inchangée.

**Sans ville, sans invention.** M4 ne publie pas la ville dans le WCT (`ville_tokenisee`, Loi 25) : les contenus
d'un chantier réel n'ont donc pas d'ancrage local, et chacun le dit (`avertissements`). Décision à prendre (rapport de
T4.17) : que M4 publie une ville au niveau municipal avec le consentement marketing.

**Approbation du propriétaire par « À voir » (N3).** `attentes()` déclare un `contenu_a_approuver` (N3) par contenu
`PROPOSE` ; l'app du propriétaire le lit (`m9_lister_demandes_approbation`), lit le texte entier
(`m7_lister_contenus_chantier`) puis décide (`m7_decider_contenu`, `approuver` ou `rejeter` avec son motif). La
décision est celle d'un HUMAIN identifié, jamais du modèle : l'identité d'un jeton d'appareil confirmée en base, la
PERSONNE portant `nathan_owner` (un gestionnaire `admin` est refusé) ; ou l'exécution d'une demande que le propriétaire
vient d'approuver dans la file du socle. Un agent sans propriétaire reçoit `REJ-HUMAIN-REQUIS`. La décision porte
l'empreinte du texte décidé, et le contrôle du texte est rejoué à l'approbation. Un contenu rejeté n'est pas rouvert :
un nouveau texte (`textes`) crée une révision, l'ancienne reste au registre.

**Le paquet manuel** (`m7_exporter_paquet_manuel`, seulement pour un contenu approuvé) : texte, mots-clics, lien de
suivi, `texte_a_copier`, médias, heure suggérée, instructions de publication de la plateforme, `approuve_par`.
M7 ne publie jamais et n'appelle aucune API de plateforme (l'adaptateur Postiz est refusé par les tests). **Sans
détecteur réel** de visages et de plaques (OpenCV absent), tout média est `a_flouter_a_la_main` : aucun fichier flouté
n'existe (le floutage de T4.3 rend un rapport, pas un fichier), le rapport du détecteur est joint à titre
d'information avec sa réserve, et le paquet ne dit jamais « flouté » ni « sûr ». L'heure vient du profil de marque
(`heures_publication`) ; sans elle, `a_configurer` le dit et aucune heure n'est inventée. La demande de témoignage
dit `contact_client.autorise` : elle ne s'envoie que si le client a consenti à être contacté (`consentement_demande_avis`,
preuve à l'appui).

**Retrait du consentement marketing (Loi 25)** : `m7_enregistrer_retrait_consentement_marketing(wct_id, canal,
horodatage)`, registre `retraits_consentement_marketing` (append-only, durable). Le retrait est un fait, sans texte libre
(canal, personne, heure) ; il prend effet à l'instant (N2) et bloque, pour ce chantier et pour tout autre chantier du même
lead, **toute tâche de contenu** : proposer, décider, exporter, `m7_preparer_contenu_public` ; un contenu déjà proposé,
approuvé ou exporté devient `CONSENTEMENT_RETIRE`, et la réponse liste les paquets déjà exportés à retirer à la main. Un
retrait précède parfois son WCT : il est enregistré quand même (`wct_connu: false`) et bloque le WCT à sa réception. Il ne
se lève pas ; un client qui consent de nouveau le fait par un nouveau « Terminer ». Deux voies de signalement : le
propriétaire ou son gestionnaire, depuis l'app admin (`m7_enregistrer_retrait_consentement_marketing`), et le STOP du client
à M1 (ci-dessous).

**Le STOP de M1 est un retrait (PLAN T4.17-c).** M7 consomme `m1.retrait_consentement` (`consommateurs()`, `dependances`
`m01-front-office`) : M1 y dit quels `lead_id` il avait ouverts pour le correspondant qui a écrit STOP. M7 inscrit **un retrait
par lead** dans `retraits_consentement_marketing`, sans `wct_id` (`retrait.construire_retrait_de_lead`, identifiant déterministe,
`source` et `enregistre_par` = `bus:m1.retrait_consentement`, canal et heure du STOP). Le lien est le `lead_id`, que le WCT de M4
porte : **aucun contact n'est lu ni écrit**. Le retrait d'un lead vaut pour ses opportunités (`<lead>~opp~<wct_id>`, que M2 ouvre
pour un client qui revient : `retrait.lead_d_origine`). Tout chantier de ces leads est bloqué, celui déjà reçu comme celui qui arrivera :
proposer, décider, exporter, photo ; un paquet approuvé et déjà exporté l'est aussi, et le résumé du consommateur liste ce qui
se retire à la main (`contenus_deja_exportes`, `a_faire`). Idempotent ; une charge illisible lève (rejeu, puis quarantaine
visible) : un retrait n'est jamais ignoré en silence. **Limites** : la demande d'avis naît d'un consentement distinct
(`consentement_demande_avis`, T1.5-d) que le STOP ne touche pas (elle reste un brouillon, jamais envoyé sans approbation) ; un
même client qui écrit d'un autre numéro est un autre correspondant pour M1.

**Profil de marque** : champs optionnels, tolérés par le contrat gelé v1 (champs supplémentaires JSON), à fournir par
le client : `site_url` (lien de suivi), `hashtags`, `garanties_validees` (énoncés approuvés, recopiés mot pour mot),
`heures_publication` (`{plateforme: "HH:MM"}`).

**Registres** (`m07-marketing`) : `contenus_chantier` (propositions, une par contenu et par révision),
`decisions_contenu`, `exports_paquet`, `retraits_consentement_marketing`. L'état d'un contenu est le pliage de ces
maillons ; le retrait l'emporte sur tout.

**Preuve.** `tests/usine/` (contrôle, gabarits, registre, décision, chantier, paquet, service sur base durable) et
`tests/e2e/test_usine_contenu_appareil.py` (moteur réel, porte d'appareil) : « Terminer » avec consentement, cinq
contenus en attente, texte avec prix refusé, approbation, paquet exporté, sans consentement rien, retrait bloqué. Le STOP de
M1 par le vrai bus : `tests/usine/test_retrait_du_bus.py` (M7 seul) et `tests/test_stop_retire_consentement_marketing.py` à la
racine du dépôt (SMS, lead, « Terminer », approbation, export, STOP : tout est bloqué).

## Contrat gelé v1

- **Source unique de vérité** : [contracts/brand-contract.v1.yaml](contracts/brand-contract.v1.yaml)
  définit le schéma du profil, les réponses HTTP attendues et la version du contrat.
- **Aucune duplication** : `brand_schema.py` charge le contrat pour obtenir
  `REQUIRED_FIELDS`, les types et les contraintes. Le serveur lit la version directement
  depuis le contrat.
- **Évolution** : toute modification structurelle nécessite un **nouveau** fichier
  `contracts/brand-contract.v2.yaml`, un bump de `schema_version`, la mise à jour
  du hash de gel dans `test_contract_consumer.py` et une revue d'architecture
  (conformément à D-015).
- **Hash de gel** : le test `test_contract_consumer.py` épingle le SHA-256 binaire
  du contrat. Toute altération du fichier v1 sans suivre la procédure ci-dessus
  rendra le test **ROUGE**.
