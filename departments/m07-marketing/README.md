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
- `m7_marketing.content.contenu_public` + l'outil `m7_preparer_contenu_public` (T1) :
  prépare un brouillon flouté avec la preuve du consentement et le rapport de floutage. Refuse
  (fail-closed, aucun brouillon) si `consentement_marketing` est absent/faux/retiré, ou si le
  profil de marque n'est pas configuré. Une détection sous le seuil de confiance fourni ne
  bloque pas la préparation (le floutage est déjà appliqué par prudence) mais marque le
  brouillon `revue_humaine_requise: true` avec le motif — jamais un passage silencieux. Jamais
  une publication : la publication réelle reste N5 (approbation signée du socle), hors de ce
  module.

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
