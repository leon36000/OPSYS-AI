# Audit M7 — Marketing & Croissance IA (CMO IA)

> Audit historique du 28 septembre 2026, conservé pour traçabilité. Les évolutions ultérieures
> ne sont pas inventoriées ici. Consulter le [plan de consolidation](../programme/RESTRUCTURATION-2026-09-30.md)
> et les [recherches actuelles](../research/R16-2026-09-30/README.md) pour M1/M5/M7/M10. Un statut
> ancien et un nombre de tests ne certifient pas le périmètre cible complet.


**Date de l'audit :** 2026-09-28. **Portée :** `departments/m07-marketing/` seulement, en lecture.
**Référence produit :** `docs/produit/DEFINITION-PRODUIT.md` §1, §5 (P9), §6, §7 (M7), §8, §9, §10, §13.
**Méthode :** lecture intégrale des 13 sous-paquets de `src/m7_marketing/`, des contrats, fixtures,
skills et tests ; une seule commande exécutée (voir PREUVE) ; recherche web ciblée pour compléter
`docs/research/R9-m7-m8.md` (vidéo courte, API officielles). Aucun fichier modifié hors ce document.

**Verdict global.** M7 est le département le plus avancé en volume de code (~5 057 lignes Python,
13 sous-paquets, 485 tests, tous verts) mais reste `PARTIEL` au sens de la section 6 (Preuve de
complétion) de la définition produit : les moteurs déterministes unitaires (UTM, attribution, ROI,
SEO/AEO, réputation, veille concurrentielle, ads en lecture seule) sont solides et bien testés ;
mais la **chaîne visible dans le produit** — chantier terminé → 5 contenus → approbation mobile →
publication/export → mesure — n'existe pas de bout en bout, aucun écran mobile n'existe (aucune app
mobile n'est présente dans le dépôt), aucun tableau de bord marketing n'existe, et le profil de
marque par défaut expose encore l'identité d'OPSYS-AI plutôt que celle d'un client. Les 4 défauts
documentés dans `docs/research/R9-m7-m8.md` §1.1–§1.4 (jointure canal↔plateforme, `nb_leads_attribues`
figé à 0, devise EUR résiduelle, contradiction `Organization`/`LocalBusiness`) sont **déjà corrigés**
dans le code actuel — vérifié ligne par ligne, voir §1 et §3.

---

## 1. Inventaire M7.1 – M7.11

Une seule commande de test couvre tous les fichiers cités (voir PREUVE) : 485/485 verts. Le statut
« PRÉSENT » signifie présent **dans le périmètre voulu par la mission** (ex. M7.7 est lecture seule
par conception, pas un défaut).

| # | Fonction (définition produit) | Statut | Fichiers clés | Tests |
|---|---|---|---|---|
| M7.1 | Identité de marque (voix, promesse, zones desservies, messages interdits, garde-fous) | **PARTIEL** | `brand/brand_schema.py`, `brand_server.py`, `profile.yaml` ; `contracts/brand-contract.v1.yaml` | `tests/test_brand_schema.py`, `test_brand_e2e.py`, `test_contract_consumer.py` |
| M7.2 | Centre de commande réseaux sociaux (calendrier, brouillons, publication assistée, paquet manuel) | **PARTIEL** | `social/postiz_adapter.py`, `social/config.yaml`, `content/factory.py`, `content/approval.py` | `tests/test_postiz_adapter.py`, `tests/content/*` |
| M7.3 | Usine à contenu (chantier → contenu, 1 chantier → N contenus, contrôle marque/confidentialité) | **PARTIEL** | `workflows/chantier_social.py`, `fixtures/chantiers/*/chantier.yaml` | `tests/workflows/test_chantier_social.py` |
| M7.4 | Moteur de croissance organique (jamais faux abonné/like/pod/spam) | **ABSENT** | — | — |
| M7.5 | Réputation (avis Google, demandes d'avis, réponses brouillon, alerte avis négatif) | **PARTIEL** | `reputation/{ingestion,classifier,response_builder,metrics}.py` | `tests/reputation/*` |
| M7.6 | SEO local et contenu SEO (Search Console, suivi de positions, pages locales) | **PARTIEL** | `seo/seo_audit.py`, `aeo/aeo_engine.py`, `site/{generator,guardrail}.py`, `docs/seo-knowledge.v1.yaml` | `tests/test_seo_audit.py`, `tests/aeo/*`, `tests/test_site_*.py` |
| M7.7 | Médias payants et intelligence publicitaire (lecture + recommandations seulement) | **PRÉSENT** (périmètre voulu) | `ads/{ads_loader,intelligence}.py`, `fixtures/ads/*` | `tests/ads/test_ads_intelligence.py` |
| M7.8 | ROI et attribution (marketing → leads → ventes → profit) | **PARTIEL** | `utm/utm_engine.py`, `attribution/attribution_engine.py`, `roi/roi_engine.py`, `contracts/{roi-mapping,utm-convention}.v1.yaml` | `tests/utm/*`, `tests/attribution/*`, `tests/roi/*` |
| M7.9 | Veille concurrentielle (sources publiques légales, niveau de confiance) | **PRÉSENT** (périmètre voulu, snapshots locaux) | `competitive/{loader,analyzers,compare,report}.py`, `fixtures/concurrents/*` | `tests/competitive/*` |
| M7.10 | Marketing local hors ligne (lettrage camions, pancartes, dépliants, référence, partenariats) | **ABSENT** | — | — |
| M7.11 | Conseiller CMO stratégique (plans 30/60/90, rapport hebdomadaire, campagnes saisonnières) | **PARTIEL** | `workflows/campagne_saisonniere.py`, `data/saisons/calendrier-quebec.v1.yaml` ; planification `digest-marketing` (manifeste, sans outil déterministe dédié) | `tests/workflows/test_campagne_saisonniere.py` |

Compléments transverses présents : Brand Core exposé en HTTP (`GET /brand`, contrat RFC 9457),
contrat de content-item gelé (D-015, hash épinglé), convention UTM gelée (S012), 9 outils d'agent
+ 1 outil T3 gated dans `outils.py`, dictionnaire de métriques `m7-metrics.v1.yaml` (14 métriques
`m7_*`, toutes en CAD depuis le correctif R9 §1.3), 3 skills (`audit-seo-local`,
`plan-de-contenu-saisonnier`, `reponse-aux-avis`).

---

## 2. Écarts

### 2.1 Modèle de données

- **Marque** : le contrat gelé `brand-contract.v1.yaml` ne porte que 5 champs (`name`, `tagline`,
  `tone`, `colors`, `langue`). Aucun champ « zones desservies » ni « messages interdits / garde-fous
  de marque », pourtant exigés par M7.1. Aucun NAP (adresse, téléphone) dans le contrat, alors que
  la règle AEO A-08 (`aeo_engine.py`) et le JSON-LD `HomeAndConstructionBusiness` du site généré en
  ont besoin — ces valeurs sont aujourd'hui codées en dur dans `site/content.yaml`, pas dans le
  profil de marque.
- **Marque — donnée réelle absente** : `src/m7_marketing/brand/profile.yaml` (le fichier chargé par
  défaut par `chantier_social.py` et `campagne_saisonniere.py`) contient littéralement
  `name: "OPSYS-AI"` et le tagline du produit lui-même. `site/content.yaml` (le site que
  `m7_auditer_seo_site`/`m7_evaluer_aeo` valident par défaut) décrit aussi OPSYS-AI comme produit
  (`canonical: https://opsys-ai.ca/`), pas un client de rénovation extérieure. Le README documente
  que ce fichier est un « GABARIT initial » à valider — mais rien dans le code n'empêche aujourd'hui
  de composer et auditer du contenu sous l'identité d'OPSYS-AI, ce que `SOUL.md` interdit
  explicitement (« Recopier l'identité d'OPSYS-AI… »). Aucun modèle de « profil de marque par
  installation/client » n'existe (pas de table, pas d'endpoint d'écriture — `GET /brand` seulement).
- **Calendrier de contenu** : aucune entité de calendrier (dates de publication planifiées, statut
  par plateforme) n'existe. `content/approval.py` est une file plate (`_QUEUE = {}`, dict Python en
  mémoire de processus) sans horodatage de publication prévue, sans persistance — perdue à chaque
  redémarrage, invisible à un futur dashboard ou app mobile qui tournerait dans un autre processus.
- **Contenus** : le contrat `content-item.v1.yaml` est solide (id, version, refs sha256, statut
  0-6) mais ne porte ni champ média (image/vidéo générée ou photo source), ni plateforme cible
  explicite (seulement `surface` IA et `type`), ni date de publication.
- **Campagnes** : `fixtures/ads/*.yaml` et `roi-mapping.v1.yaml` couvrent Google Ads/Meta en lecture,
  mais il n'existe aucune entité « campagne » interne à M7 (nom, budget, dates, propriétaire) —
  seulement des snapshots de faits mesurés.
- **Avis** : modèle correct (`id`, `note`, `plateforme`, `date`, `texte`) mais lecture seule sur
  fixture (`fictif: true`), aucune clé de dédoublonnage vs une ingestion réelle future.
- **Attribution** : `visitor_id` optionnel côté lead (`fixtures/crm/leads.v1.yaml`) — cohérent avec
  la métrique `m7_part_non_attribuables`, mais **aucun département en amont (M1, M2) ne porte
  aujourd'hui de champ `utm_source`/`utm_campaign`/`utm_medium`** (grep vide sur
  `departments/m01-front-office/src` et `departments/m02-revenue-crm/src`) : le modèle
  d'attribution de M7 n'a rien à lire tant que M1/M2 ne captent pas l'UTM à la création du lead.

### 2.2 API

- Seul point d'entrée HTTP réel : `GET /brand` (`brand_server.py`, serveur `http.server` minimal,
  lancement manuel `python3 brand_server.py [port]`, non branché à `serveur_mcp.py` ni à un
  processus supervisé du Core).
- Aucune route MCP dédiée n'est visible dans `src/opsys/serveur_mcp.py`/`capacites.py` au-delà du
  mécanisme générique `/mcp/m07-marketing` qui charge `m7_marketing.outils.outils()` — cohérent avec
  l'architecture (un point d'accès par département), mais rien de spécifique à M7 n'y a été ajouté
  (pas de webhook entrant pour Postiz/GBP, pas de callback OAuth).
- Aucun client HTTP réel dans `social/postiz_adapter.py` : ni `requests` ni `httpx`, aucun appel
  réseau nulle part dans le paquet (cohérent avec la doctrine « zéro réseau » actuelle, mais cela
  signifie que même en `dry_run=True` l'adaptateur ne parle jamais à un vrai service Postiz — c'est
  un simulateur de payload, pas un client testé contre une API).
- Aucun adaptateur GATED écrit pour Search Console, GBP (au-delà du canal `gbp` de l'enum Postiz),
  Meta Graph, TikTok, LinkedIn ou YouTube — seuls `Canal.GBP/FACEBOOK/INSTAGRAM` existent dans
  `postiz_adapter.py`. TikTok, LinkedIn et YouTube, explicitement cités en M7.2, sont absents du
  code.

### 2.3 Événements (§6)

- **Chantier terminé → contenu (le plus important)** : M4 possède déjà un contrat d'événement,
  le « Work Completion Trigger » (`departments/m04-field-ops/src/m4_field_ops/outbox.py`), dont
  `CONSOMMATEURS_CIBLES = ("M6", "M5", "M2", "M7", "M8", "M10")` **nomme explicitement M7** comme
  consommateur cible. Mais **rien côté M7 ne lit cet outbox** (grep `wct|outbox|m4_field_ops` dans
  `departments/m07-marketing` : aucune occurrence). `chantier_social.py` lit un fichier
  `chantier.yaml` posé à la main dans `fixtures/`, complètement déconnecté du cycle de vie réel
  d'un chantier M4. De plus, le WCT de M4 (`wct_id, intervention_id, lead_id, technicien_id,
  horodatage_completion, fix_gps_completion, duree_reelle_minutes, ecart_signale, revue_id,
  hash_maillon, consommateurs_cibles, devis_id`) **ne porte aucun des champs dont M7 a besoin** :
  pas de ville, pas de type de travaux, pas de photos, pas de description factuelle, pas de
  consentement client, pas de signal de qualité (« client satisfait oui/non »). Le contrat WCT
  devra être étendu (ou complété par un appel à M2/M6) avant qu'un vrai événement puisse déclencher
  l'usine à contenu.
- Aucun bus d'événements partagé n'existe dans `src/opsys/` (aucun `event_bus`/`EventBus` trouvé) :
  chaque département a son propre registre local (M4 : `registre.py`+`outbox.py`). L'architecture
  documentée (`docs/architecture/ARCHITECTURE.md`) ne décrit que des appels d'outils MCP par agent,
  pas de publication/abonnement inter-départements — un choix à trancher avant de brancher M4→M7.
- **`department.yaml` de M7 déclare `dependances: [m02-revenue-crm]`** mais pas `m04-field-ops`,
  alors que l'événement central de M7.3 vient de M4, pas de M2. Le manifeste ne reflète pas la
  dépendance réelle du workflow `chantier_social.py`.
- **Leads vers M1 avec UTM** : `m7_generer_lien_utm` produit des liens valides, mais aucun outil ne
  transmet la campagne/l'UTM à M1 au moment de la création d'un lead ; à l'inverse, aucun événement
  M1/M2 n'alimente aujourd'hui `m7_calculer_roi` autrement que par fixture statique.
- **ROI avec M2 et M5** : `roi_engine.py` consolide coût publicitaire ↔ leads (attribution), mais
  s'arrête au coût par lead. Rien ne relie une vente gagnée (M2) ou une marge réelle encaissée (M5)
  au canal d'origine — le mot « profit » de la mission M7 (M7.8 : « marketing → leads → ventes →
  profit ») n'est pas encore mesurable, seul le coût d'acquisition l'est.

### 2.4 Outils d'agent

`outils.py` est bien construit (patron `m3_estimer_projet` répliqué, outils composés de bout en
bout, autonomie T0-T3 posée correctement : `m7_publier_post_social` est le seul T3, les 3 outils
de contenu/réponse sont T1, le reste T0). Manques :
- Aucun outil `m7_recevoir_chantier_termine` (ou équivalent) qui consommerait un WCT M4 réel.
- Aucun outil de génération de visuel/vidéo (M7.3 « variantes par plateforme » implique un média,
  `content/factory.py` ne produit que du texte).
- Aucun outil pour composer un « paquet manuel » exportable (texte + mots-clics + média + heure +
  instructions) quand l'API ne permet pas la publication — alors que c'est une exigence dure de
  P10 et de la preuve de complétion M7.
- Aucun outil de digest composé (`m7_generer_digest_marketing`) malgré la planification
  `digest-marketing` du manifeste : la consigne texte existe, mais rien ne calcule déterministement
  le résumé (contrevient à P7 « le LLM ne calcule jamais »), même si l'agent peut aujourd'hui
  l'assembler manuellement à partir de `m7_lister_file_approbation` + `m7_calculer_metriques_reputation`
  + `m7_calculer_roi`.

### 2.5 Écrans mobiles admin/vendeur/employé (§9)

**Aucune app mobile n'existe dans ce dépôt** (recherche `*.tsx`, `app.json`, `expo*` : aucun
résultat). `docs/architecture/MOBILE.md` documente une stratégie en 2 phases : Phase 1 = app
officielle OpenClaw générique (chat/voix/approbations natives, aucun écran métier) ; Phase 2 = fork
avec écrans par profil, mais la liste de Phase 2 ne cite que **Patron, Estimateur, Chef d'équipe,
Réception** — **M7 n'a aucun écran prévu, ni en Phase 1 ni en Phase 2**, alors que la définition
produit exige explicitement (§9.3, §9.4, §9.5) :
- **Employé** : après-chantier — photos, notes, **autorisation du client**, qualité, « client
  satisfait oui/non », « potentiel de contenu » ; **l'employé ne publie pas**. Aucun de ces champs
  n'existe dans `fixtures/chantiers/*/chantier.yaml` (seuls `ville`, `type_travaux`, `date_fin`,
  `description_factuelle`, `photos`) ni dans aucun contrat M7 — le modèle de données de la source
  ne porte même pas de place pour le consentement.
- **Vendeur** : suggestions de contenu, demande de photos avant/après, mini-témoignage, signaler un
  client satisfait — aucun outil ni écran.
- **Admin/propriétaire** : approbation des contenus et réponses aux avis, tableau de bord marketing,
  rapport hebdomadaire — `m7_lister_file_approbation`/`m7_proposer_reponse_avis` existent côté
  outil, mais rien ne les expose à un écran mobile ; l'approbation reste aujourd'hui un appel de
  fonction Python (`content_approval.approve(item, acteur, ts)`), jamais un geste humain sur un
  appareil.

### 2.6 Tableau de bord marketing

Absent. `src/opsys/console/` (Flask/HTTP minimal) n'a que des pages génériques
(`departements`, `approbations`, `budgets`, `modeles`) construites depuis les manifestes — aucune
page spécifique à M7 (file de contenu, ROI par canal, avis à traiter). `src/opsys/tableau_de_bord.py`
et `console/pages.py` ne contiennent aucune référence à `m7`/`marketing`. La preuve de complétion
M7 exige un tableau de bord marketing fonctionnel ; il n'a pas commencé.

### 2.7 Portes OAuth et paquet manuel

- Portes documentées (§10) : OAuth Google Ads (lecture seule prévue), Search Console, Google
  Business Profile, approbations Meta/TikTok/LinkedIn/YouTube. **Aucune n'est amorcée en code** —
  ni flux OAuth, ni stockage de jeton chiffré, ni page de configuration dans la console (qui existe
  pourtant en générique pour les modèles LLM, `contenu_modeles`).
- Recherche web (2026-09) : Meta exige une app en revue Business + permissions publiées ; TikTok
  Content Posting API exige une approbation « production » distincte du sandbox et limite à
  6 requêtes/minute/jeton ; LinkedIn permet la publication personnelle en self-service mais exige
  le programme partenaire « Marketing Developer Platform » pour publier au nom d'une page
  entreprise ; YouTube exige le scope `youtube.upload` avec jetons d'accès ~1 h. GBP (déjà
  documenté dans R9) exige un profil vérifié 60+ jours avant l'accès API. **Conclusion : le paquet
  manuel n'est pas une option secondaire, c'est le chemin principal réaliste pour la Phase 1**
  (délais d'approbation de plusieurs semaines à mois sur 4 des 5 plateformes).
- Le « paquet manuel » lui-même (texte, mots-clics, média, heure, instructions — exigé par M7.2 et
  P10) n'a **aucune trace de code** : pas de fonction d'export, pas de gabarit imprimable/copiable,
  pas de test. C'est un écart net entre ce que le produit promet en repli et ce qui existe.

### 2.8 E2E exigé (chantier de gouttières terminé à Repentigny → 5 contenus → approbation → publication ou export → mesure)

Ce scénario précis **ne peut pas s'exécuter aujourd'hui**, pour des raisons concrètes et vérifiées :
1. Aucune fixture ni ville « Repentigny » n'existe dans M7 (`grep -rn Repentigny` : 0 résultat) ; les
   deux chantiers fixtures sont à Lévis et Québec.
2. `chantier_social.py` valide `type_travaux` contre l'ensemble
   `{renovation_totale, extension, ravalement, isolation_thermique}` — **aucune valeur « gouttières »
   n'existe dans cet énuméré**. Le mot « gouttières » n'apparaît que dans le calendrier saisonnier
   (thèmes) et les avis fictifs, jamais comme type de chantier exploitable par le workflow.
3. `orchestrer_chantier_vers_social()` compose et propose **exactement un** content-item
   (`post_social`, surface `google_aio`) par appel — jamais 5, et jamais plusieurs types/plateformes
   pour un même chantier.
4. L'« approbation » du workflow est un second appel Python dans la même fonction
   (`approval.approve(item, acteur_approuve, timestamp)`), pas un geste humain différé sur mobile —
   ce qui satisfait la règle « acteur différent du proposeur » du code mais pas l'esprit d'une
   validation humaine réelle en Phase 1 (aucune latence, aucun écran, aucun rejet possible en
   pratique).
5. La « publication ou export » se limite à l'appel `PostizAdapter.publier` (GATED, `NotAutorise` en
   écriture réelle) — il n'y a pas de branche « export manuel » alternative dans le workflow.
6. La « mesure » finale n'est pas rebouclée : le workflow ne produit aucune métrique de suivi
   (impressions, clics) rattachée au content-item publié/exporté ; `m7_calculer_roi` reste un appel
   séparé, sur des fixtures indépendantes du chantier.

---

## 3. Briques

### 3.1 Publication sociale multi-canal + GBP (M7.2)

| Brique | Dépôt | Licence (vérifiée) | Dernière version / date | Maturité |
|---|---|---|---|---|
| **Postiz** | gitroomhq/postiz-app | AGPL-3.0 | push 2026-09-28 (quotidien) | 36 421⭐, très actif |
| API officielle Google Business Profile / My Business v4 | `mybusiness.googleapis.com` | Google, gratuite | active 2026 | Onboarding lent (60+ j) |

**Verdict : garder Postiz**, en sidecar Docker non modifié (AGPL respecté — jamais forké/vendorisé,
conforme AGENTS.md « GPL/AGPL seulement en service séparé non modifié »). `postiz_adapter.py` a déjà
le bon patron (`enabled`/`dry_run`/`NotAutorise`) ; il manque uniquement le branchement HTTP réel
derrière `enabled=True`, à faire seulement après un Approval Engine réel (pas avant — c'est
justement ce que le code refuse aujourd'hui, correctement). GBP reste une API à part (Reviews) hors
du périmètre de posting de Postiz : intégrer `google-api-python-client` (Apache-2.0) directement.

### 3.2 Analytics web (source de l'attribution/UTM)

| Brique | Licence (vérifiée) | Maturité | Verdict |
|---|---|---|---|
| **Matomo** | GPL-3.0 | 21 905⭐, push 2026-09-28 | **Retenu** — déjà le nom câblé dans `fixtures/matomo/visites.v1.yaml` ; sidecar non modifié ; `attribution_engine.py` ne fait déjà que consommer un export, donc conforme GPL par construction |
| Umami | MIT | 39 052⭐, actif | Repli si l'empreinte VPS de Matomo (PHP+MySQL) est jugée trop lourde |
| Plausible | AGPL-3.0 | actif | Écarté — Matomo a un reporting UTM plus riche pour le même statut copyleft-service-séparé |

### 3.3 SEO technique et suivi de position (M7.6)

| Brique | Licence | Maturité | Apport | Verdict |
|---|---|---|---|---|
| **SerpBear** | MIT (vérifiée) | 2 016⭐, actif 2026 | Suivi de position par mot-clé, auto-hébergé | **Retenu**, sidecar Docker + Postgres partagé |
| **Unlighthouse** | MIT (vérifiée) | actif 2026 | Lighthouse site entier (Core Web Vitals réel) — `seo_audit.py` actuel ne mesure aucune performance réelle | **Retenu**, CLI/sidecar |

### 3.4 Génération d'images et de vidéos courtes (piste explicitement demandée, absente de R9 pour la vidéo)

`content/factory.py` est 100 % texte aujourd'hui (gabarits `str.format`, zéro média). Recherche
complémentaire (2026-09) :

| Brique | Licence (vérifiée) | Type | Apport |
|---|---|---|---|
| FLUX.1-schnell (Black Forest Labs) | Apache-2.0 | image | Déjà retenu par R9 ; sorties commerciales sans condition |
| Qwen-Image / Z-Image-Turbo | Apache-2.0 | image | Bon rendu de texte intégré à l'image (visuels promo FR) |
| **Wan 2.2** (Alibaba) | Apache-2.0 | vidéo courte texte/image→vidéo | Variante 5B exécutable sur 8 Go VRAM ; le plus versatile des modèles vidéo ouverts en 2026 |
| Mochi 1 (Genmo) | Apache-2.0 | vidéo courte | Bon texte→vidéo, image→vidéo plus limité |
| HunyuanVideo 1.5 (Tencent) | Apache-2.0 | vidéo courte | Qualité correcte, usage commercial explicitement permis |
| SDXL/SD 1.5, FLUX.1-dev | RAIL-M / commerciale payante | image | **Exclus** : RAIL non-OSI, ou licence payante hors budget |

**Verdict : Wan 2.2 (vidéo) + FLUX.1-schnell (image)**, les deux Apache-2.0 sans condition,
exécutables en local (VPS avec GPU ou service loué ponctuel) — jamais un modèle RAIL/commercial non
payé en production. Intégration : un outil `m7_generer_visuel`/`m7_generer_video_courte` qui
alimente `sujet.description`/un futur champ média du content-item, **jamais un contournement du
gabarit texte déjà validé** (même doctrine que R9 §2.10).

### 3.5 Contrôle de marque et de confidentialité (floutage visages/plaques) — écart de recherche

**Aucune brique n'est actuellement inscrite dans `INGREDIENTS.md` pour cette fonction, et le code
n'a aucun garde-fou de ce type** (voir §2.5). C'est un vrai trou, pas seulement d'implémentation :

| Brique | Licence (vérifiée) | Apport |
|---|---|---|
| **YOLOv8/YOLO11 (Ultralytics) + un modèle de détection de visages/plaques entraîné (ex. classes COCO + fine-tune plaques QC)** | AGPL-3.0 (dépôt Ultralytics) **ou** licence entreprise payante | Détection en local, rapide, mature |
| **OpenCV (déjà une brique acceptée pour M3, replis BSD)** + un détecteur de visages léger (Haar/DNN inclus) | BSD-3 (OpenCV) | Floutage déterministe (gaussian blur / pixelisation) une fois la boîte détectée, zéro dépendance réseau |

**Verdict : détection avec un modèle sous licence permissive (éviter Ultralytics AGPL en
dépendance directe vendorisée ; utiliser un modèle ONNX pré-entraîné librement distribuable, ou un
service séparé non modifié si un modèle AGPL est retenu) + floutage déterministe OpenCV (BSD,
patron déjà accepté par M3)**, exécuté comme une étape obligatoire dans `content/factory.py` avant
tout média entrant dans un content-item — avec refus fail-closed (`donnees_insuffisantes` /
verdict de blocage) si le floutage échoue ou si le consentement du client est absent, jamais un
passage silencieux. Ce composant doit être choisi et documenté dans `INGREDIENTS.md` avant
d'écrire le premier outil qui manipule une photo de chantier réelle.

### 3.6 Emailing (avis, infolettre — hors périmètre strict M7.1-M7.11 mais cité en R9)

**Listmonk** (AGPL-3.0, sidecar non modifié) reste le meilleur candidat pour les demandes d'avis et
infolettres (M7.5) — déjà retenu par R9, pas de nouvelle recherche nécessaire.

---

## 4. Plan par phases

### Phase 1 — Tranche verticale « chantier terminé → usine à contenu → approbation mobile → export manuel ou publication → mesure »

Objectif : faire marcher l'E2E exigé, avec un vrai chantier de gouttières et une vraie ville de
la zone desservie, sans dépendre d'aucune porte OAuth.

1. **Corriger le profil de marque par défaut** : remplacer `brand/profile.yaml` par un profil GRS
   réel (ou un mécanisme de configuration par installation, même minimal — un fichier par client,
   jamais le gabarit OPSYS-AI comme défaut de production). Test : `m7_lire_profil_marque` refuse
   `name: "OPSYS-AI"` sur un flag de configuration explicite, ou charge le profil du client actif.
2. **Ajouter `gouttières` au type_travaux et une fixture Repentigny** : étendre l'énuméré de
   `chantier_social.py`, ajouter `fixtures/chantiers/repentigny-2026/chantier.yaml` avec les champs
   manquants (`consentement_client: bool`, `client_satisfait: bool`, `potentiel_contenu: bool`,
   `qualite: str`) — ce sont exactement les champs de l'écran employé §9.3.
3. **Étendre `orchestrer_chantier_vers_social` pour produire 5 contenus** (au minimum : post GBP,
   post Facebook, post Instagram, page SEO courte, fiche GBP) au lieu d'un seul — en réutilisant
   `build_content_item` pour chaque `(surface, type)`, refuser (fail-closed) si le
   `consentement_client` est absent. Test : un chantier fictif produit exactement 5 items PROPOSE,
   traçables par un même `chantier_slug`.
4. **Bloquer la composition sans consentement/floutage** : ajouter la vérification de §3.5 comme
   étape obligatoire avant `approval.propose()` pour tout content-item portant un média ; sans
   media, vérifier au minimum la présence explicite de `consentement_client: true`.
5. **Persister la file d'approbation** : remplacer le dict en mémoire de `content/approval.py` par
   une table (SQLite, cohérent avec `src/opsys/approbations.py` qui utilise déjà sqlite3) — sans
   quoi aucun dashboard ni app mobile ne peut lire la file depuis un autre processus.
6. **Écrire le « paquet manuel »** : un outil `m7_exporter_paquet_manuel(content_item)` qui rend un
   objet texte+mots-clics+média+heure+instructions, pour les 4 plateformes sans accès API en
   Phase 1 (Meta, TikTok, LinkedIn, YouTube) ; test : sortie déterministe, jamais vide.
7. **Brancher un consommateur du WCT M4** (même simulé, sur le registre local de M4 en test) :
   un outil/fonction qui transforme un WCT + les champs manquants (ville, type, photos, consentement
   — à demander explicitement si absents, jamais inventés) en appel à
   `orchestrer_chantier_vers_social`. Déclarer `m04-field-ops` dans les `dependances` du manifeste.
8. **Fermer la boucle mesure** : à l'export/publication, écrire un enregistrement
   `roi_snapshot`/`contenu_publie` minimal (id du content-item, canal, date) que `m7_calculer_roi`
   peut retrouver — même sans clics/impressions réels au départ (mode `MISSING` explicite, jamais
   un zéro fabriqué).

### Phase 2 — Écrans mobiles et tableau de bord

1. Écran admin (Phase 2 de `MOBILE.md`, à étendre) : file d'approbation M7 (voir/approuver/rejeter),
   avis à répondre, rapport hebdomadaire — consommant les outils déjà écrits
   (`m7_lister_file_approbation`, `m7_calculer_metriques_reputation`).
2. Écran employé : formulaire après-chantier (photos, consentement, qualité, potentiel de contenu)
   — alimente le WCT étendu de Phase 1, **jamais un bouton publier**.
3. Écran vendeur : suggestion de contenu, signalement client satisfait.
4. Page console `m7` (dans `src/opsys/console/pages.py`) : ROI par canal, contenus en attente,
   avis négatifs non traités — même patron que `contenu_departements`/`contenu_budgets` existants.

### Phase 3 — Portes OAuth et branchement réel

1. GBP Reviews API (lecture puis réponse gated) — lancer la demande d'accès dès le client pilote
   (délai 60+ j, goulot d'étranglement documenté en R9 et confirmé ici pour TikTok/LinkedIn/YouTube).
2. Postiz en sidecar réel, `enabled=True`/`dry_run=True` d'abord (prévisualisation), puis écriture
   réelle seulement après qu'un Approval Engine (au sens D-010) signe chaque publication.
3. Matomo en sidecar, remplacer les fixtures par un export réel ; SerpBear + Unlighthouse pour le
   SEO technique à l'échelle.
4. Générateur d'images/vidéos (Wan 2.2, FLUX.1-schnell) branché derrière le floutage obligatoire de
   §3.5, jamais avant.
5. M7.4 (croissance organique) et M7.10 (marketing hors ligne) : à spécifier — aucune brique
   n'est nécessaire, ce sont des fonctions de recommandation/suivi propres au département, à
   concevoir comme une extension de M7.11 (conseiller CMO) plutôt que comme un nouveau sous-paquet.

---

## 5. Risques et points ouverts

- **P9 (conformité aux plateformes)** : le code respecte P9 par construction là où il touche le
  réseau (`PostizAdapter` refuse toute écriture réelle sans Approval Engine, aucun crawl réseau
  dans `competitive/*`). Risque à surveiller en Phase 3 : la limite TikTok (6 requêtes/minute/jeton,
  `spam_risk_too_many_posts`) et la revue Meta Business doivent être respectées par tout futur appel
  réel — à documenter dans l'adaptateur au moment de son branchement, pas après.
- **Consentement photo** : c'est le trou le plus grave trouvé dans cet audit. Le modèle de données
  de chantier ne porte **aucun champ de consentement**, et rien ne bloque la composition d'un
  content-item à partir d'une photo de chantier sans autorisation explicite du client. Tant que
  §4-Phase 1 n'est pas fait, tout branchement réel de la publication (même en dry-run visible par
  un humain) expose un risque Loi 25 et P8 réel, pas théorique.
- **Jamais de faux avis** : le code actuel est propre sur ce point — `reputation/ingestion.py` ne
  lit que des fixtures marquées `fictif: true` avec avertissement explicite, `response_builder.py`
  ne fabrique jamais un avis, seulement une réponse à un avis existant, toujours `PROPOSE`. Point
  ouvert : aucune garde de code n'empêche explicitement un futur outil de créer un avis — à
  ajouter comme test de garde (« aucun outil `m7_*` ne peut écrire dans `fixtures/avis/` ») avant
  de brancher une vraie ingestion GBP.
- **Confusion d'identité produit/client** : le site statique de démonstration (`site/content.yaml`,
  `site/static/index.html`) et le profil de marque par défaut exposent tous deux l'identité
  d'OPSYS-AI. Risque concret si ce site était un jour déployé tel quel comme « site du client » —
  à corriger avant toute démo client, pas seulement avant la production.
- **Floutage visages/plaques** : aucune recherche de licence n'a encore été inscrite dans
  `INGREDIENTS.md` pour cette fonction (voir §3.5) — à faire avant d'écrire le premier outil qui
  touche une photo réelle, conformément à AGENTS.md (« avant d'adopter une brique… l'inscrire dans
  docs/research/INGREDIENTS.md »).
- **Bus d'événements inter-départements** : absent au niveau du Core (§2.3). Ce n'est pas un
  problème propre à M7, mais M7 est le département dont la fonction centrale (M7.3) en dépend le
  plus directement ; un choix d'architecture (webhook interne, table `evenements` partagée, ou
  appels d'outils directs orchestrés par l'agent) doit être pris avant la Phase 1, tâche 7.
- **Manifeste incomplet** : `department.yaml` ne déclare pas `m04-field-ops` en dépendance malgré
  le rôle central de M4 dans M7.3 — à corriger en même temps que la tâche 7 de la Phase 1.
- **Dette déjà résorbée (à ne pas re-corriger)** : les 4 défauts de `R9-m7-m8.md` §1.1–§1.4
  (jointure canal↔plateforme, `nb_leads_attribues` figé à 0, devise EUR résiduelle, contradiction
  `Organization`/`LocalBusiness`) sont vérifiés corrigés dans le code actuel — ne pas rouvrir ce
  travail, seulement le garder sous test de non-régression.

---

PREUVE: `/opt/opsys-venv/bin/python -m pytest departments/m07-marketing/tests -q --import-mode=importlib -p no:cacheprovider`
→ exit code 0, 485 tests exécutés (485 points de succès comptés, aucun échec, aucune erreur) sur
32 fichiers de tests. Inventaire de code lu intégralement : `department.yaml`, `SOUL.md`, `README.md`,
tous les fichiers de `src/m7_marketing/{brand,seo,aeo,utm,attribution,roi,content,reputation,ads,
competitive,social,site,workflows}/*.py` (13 sous-paquets, ~5 057 lignes), `outils.py`, les 4
contrats gelés, `metrics/m7-metrics.v1.yaml`, `data/saisons/calendrier-quebec.v1.yaml`,
`docs/seo-knowledge.v1.yaml`, les 3 skills, les fixtures chantiers/avis/matomo/crm/ads/concurrents.
Recherche croisée dans `departments/m04-field-ops/src/m4_field_ops/outbox.py` (contrat WCT),
`departments/m01-front-office` et `departments/m02-revenue-crm` (absence de champs UTM),
`src/opsys/{approbations,outils,console/pages,tableau_de_bord}.py` (absence de bus d'événements et
de page M7), `docs/architecture/MOBILE.md` (absence d'écrans M7), `docs/research/{INGREDIENTS,
R9-m7-m8}.md`, `core/UPSTREAM.md`. Recherche web ciblée (2026-09) pour les modèles vidéo courte
open source (Wan 2.2, Mochi 1, HunyuanVideo 1.5 — Apache-2.0) et l'état des API TikTok/LinkedIn/
YouTube en complément de R9 (déjà à jour pour GBP/Matomo/Postiz/SerpBear).
