M7-marketing

Marketing & Croissance IA — PREMIER MODULE (D-008)

Statut: PARTIAL (mode ombre : le pilote M7-S000 a été suivi des vagues 2 et 3 — site Quadruple A,
content factory, données saisonnières, competitive engine, grille AEO/GEO, convention UTM,
attribution, ROI. 432 tests. Le statut du registre est la source de vérité, gate statut_lint.)

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

  **Trou documenté, jamais caché — retrait de consentement (Loi 25)** : le catalogue
  `src/opsys/evenements/catalogue/m4.travaux_termines.json` ne porte aucun champ de retrait, et
  **aucun registre de retrait de consentement marketing n'existe aujourd'hui** dans ce dépôt
  (ni côté M1/M2 où un client pourrait le signaler, ni côté M7). Ce module ne prétend donc jamais
  savoir qu'un consentement autrefois accordé a été retiré depuis — seul l'état
  `consentement_marketing` tel que reçu du WCT fait foi. Construire un registre de retrait
  (source de vérité, canal de signalement, effet rétroactif sur un brouillon déjà préparé) reste
  un travail à faire, hors périmètre de ce correctif.

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
