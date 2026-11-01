# M7 : signaux de marché et de performance (données propres, médias payants, veille, GEO/SEO, mesure)

Statut (2026-11-01) : **tranche 1, jamais exécutée contre un vrai service, un vrai moteur d'IA, un vrai site de concurrent ni une vraie
plateforme publicitaire.** Aucun transport réseau n'existe dans ce dépôt : chaque entrée-sortie externe est un PORT (`Transport`,
`TransportPublic`, `PortMoteurIA`) dont la seule implémentation est un refus typé (`…-NON-BRANCHE`) ou un double de test. Tout ce qui suit est
prouvé avec ces doubles et par l'analyse statique ; ce que cela ne prouve pas est dit à la section 12. Rien n'est qualifié, rien n'est
« complet ». Les statuts de la matrice M7 (M7.4 à M7.9, M7.11, M7.12) le disent aussi.

Décisions de départ : feuille de route r2 (« SEO/GEO : données propres du client… GEO mesuré par rapports officiels, journaux de robots IA et panel
via API officielles », « Réseaux/pub », « Mesure marketing : UTM normalisées, conversions hors ligne, tests géo/marche-arrêt »), décisions de
l'architecte r1 §3 (« M7 dépenses : ingestion automatique par connecteurs… + import de relevés en repli »), recherche R4 §3 à §7 et §9. Code :
`departments/m07-marketing/src/m7_marketing/{signaux,medias_payants,veille,geo,mesure}/` et les cinq modules d'outils
`signaux_outils.py`, `medias_outils.py`, `veille_outils.py`, `geo_outils.py`, `mesure_outils.py`. **Aucune migration** : tous les registres sont
des registres de département génériques (`registres_maillons`), déclarés dans `department.yaml` (`memoire.ecriture`).

## 1. Audit de l'existant (avant cette tranche)

| Ce qui existait | État | Ce que la tranche en fait |
|---|---|---|
| `ads/` (`ads_loader`, `intelligence`, règles AD-01 à AD-06) | Refuse toute donnée qui n'est pas marquée `fictif: true` ; fixtures seulement ; M7.7 = SIMULE | **Conservé tel quel** (d'autres tests le gardent). La lecture réelle d'une plateforme passe par `signaux/` ; les règles de dépense par `medias_payants/` (plan, plafonds, DEP-01 à DEP-07). |
| `competitive/` (`loader`, `analyzers`, `compare`, `report`) | Snapshots locaux `fictif: true`, aucun réseau ; M7.9 = SIMULE | **Réutilisé** (`analyze_page`, `analyze_robots`, `analyze_sitemap`) par `veille/` ; le registre de concurrents, le robots.txt, la collecte gouvernée et la comparaison sont nouveaux. |
| `depenses_marketing.py` (`enregistrer_releve`, `lire_depenses`) | Registre de relevés sourcés ; « l'ingestion réelle est une décision produit » ; M9 et M5 le lisent par `m7_lire_depenses_marketing` | **Alimenté** par les connecteurs publicitaires en lecture (source `RELEVE_PLATEFORME`, CAD, hors taxes, jamais converti, comptes réels seulement). Le contrat de lecture n'a pas bougé. |
| `performance_campagnes.py`, `attribution/`, `roi/`, `utm/` | Faits M2/M3/M5 par événements ; attribution et ROI sur fixtures Matomo/CRM ; convention UTM gelée | **Réutilisés** : la convention UTM gelée (`contracts/utm-convention.v1.yaml`, `utm_engine`) fonde `mesure/utm.py` ; l'attribution simple et honnête (`mesure/attribution_simple.py`) lit les dépenses `CONNUE` seulement. |
| `seo/seo_audit.py`, `aeo/aeo_engine.py`, `site/` (schéma `opsys.site/v1`, garde de contenu, QA) | Audits locaux sans réseau ; génération de site statique | **Réutilisés** : les audits alimentent `geo/recommandations.py` (GEO-06) ; `geo/proposition_site.py` propose des changements en BROUILLON validés par le schéma, la garde de contenu et le QA existants. |
| `sas_social/` (annonce payante N4, plafonds durs `PolitiqueSas`), `studio/` (visuels approuvés N3) | Tranche WordPress/social et studio livrées | **Réutilisés** : le plan de campagne emprunte les plafonds durs du sas et n'accepte que des visuels APPROUVÉS du studio ; ses publications Meta préparées sont des entrées du sas, jamais soumises ici. |
| `opsys.recu_calcul_pont` (reçu `recu-calcul.v1` de M5), `opsys.observabilite.pii` (masqueur), `opsys.secrets_coffre`, `journal_chaine`, `evenements` | Établis | **Réutilisés** (reçus de conception statistique rejouables ; minimisation PII ; jetons du coffre le temps d'un appel ; registres à chaîne de hachage ; bus). |

## 2. Architecture en une page

```
 coffre (jeton le temps d'UN appel) ──┐
                                      ▼
 source déclarée (N3, NOM du secret) ─► tour d'ingestion ──► registre signaux_marketing (faits : valeur, période, portée, échantillon,
 [Search Console · PageSpeed · CrUX ·    │  quota local AVANT l'envoi ·            provenance, révisions) ──► m7_lire_signaux_marketing (T0)
  Bing · Umami · Matomo · fiche Google · │  liste blanche de LECTURE ·                      │      (la dépense publicitaire exige la garde financière)
  Google Ads · Meta Ads]                 │  hôtes déclarés · curseur persisté               ├──► événement m7.signaux_marketing_constates ─► M8 (mesures)
                                         │  page = faits + curseur, UNE transaction         ├──► relevés de dépense (comptes réels) ─► m7_lire_depenses_marketing (M9, M5, M8)
 import manuel d'un export (N2) ─────────┘                                                  │       └─► événement m7.depenses_marketing_constatees ─► M5, M8
 [rapports IA, journaux, mapping obligatoire]                                              ▼
                                                                    règles + anomalies (DEP-01 à DEP-07) ─► événement m7.anomalie_depense_detectee ─► M9, M8
 plan de campagne payante (brouillon N2) ─► soumis ─► LANCEMENT approuvé (N4, empreinte exacte) ─► « LANCEMENT_APPROUVE_NON_EXECUTE »
   créatifs = visuels APPROUVÉS du studio ; plafonds durs du sas ; règles d'arrêt PRÉPARÉES ; rien n'est lancé ni dépensé par OPSYS
 veille : concurrents DÉCLARÉS (N3) ─► robots.txt d'abord ─► page publique ─► observation datée, texte tiers « non fiable » ─► comparaison déterministe
 GEO : robots d'IA · journaux (sans IP) · panel par API officielles · recommandations sourcées ─► changement de site en BROUILLON (opsys.site/v1)
 mesure : UTM normalisées · conversions hors ligne ─► m7.conversion_hors_ligne_importee ─► M2, M8 · tests marche-arrêt/géo avec reçu rejouable
```

Principe : **aucun outil d'agent ne lit chez un fournisseur, ne collecte une page, n'appelle un moteur d'IA, ne dépense, ne publie ni ne modifie
une campagne.** Les lectures sont des tours d'ingestion (`signaux.ingestion`, `veille.collecte.tour_veille`, `geo.panel.executer_panel`) que
le planificateur appellera plus tard — ils n'y sont PAS branchés. Les outils déclarent, lisent, brouillonnent, calculent et consignent des décisions
humaines.

## 3. Les connecteurs de lecture des données propres (`signaux/`)

### 3.1 Cadre commun (`base.py`, `quotas.py`, `curseurs.py`, `registre.py`, `minimisation.py`, `fraicheur.py`, `ingestion.py`)

| Exigence | Ce qui la tient (et le test qui la prouve) |
|---|---|
| Lecture seule, au niveau du code | Tout appel passe par `ConnecteurLecture._appeler` : le point d'accès doit être dans la liste blanche `POINTS_ACCES` de la CLASSE (`googleAds:search`, jamais `:mutate`) ; la méthode HTTP ne peut être que `GET` ou `POST` de lecture (`RequeteHttp` refuse le reste à la construction) ; un test AST (`test_signaux_sans_reseau.py`) interdit tout nom de geste d'écriture. |
| Hôtes déclarés | HTTPS, sans identifiant, port 443, hôte dans `HOTES` de la classe — ou, pour Umami et Matomo auto-hébergés, l'hôte que le client a déclaré (nom public ; ni IP, ni `localhost`, ni `.internal`). Une URL tirée d'une réponse n'est JAMAIS suivie (`paging.next` de Meta ignoré). |
| Jetons par le coffre | `with fournisseur() as jeton:` le temps d'UN appel ; le registre des sources ne porte que le NOM du secret ; `Authentification.__repr__` masque la valeur ; toute exception du transport est remplacée par un refus typé SANS son texte (test avec une exception qui contient le jeton) ; le coffre est refermé après chaque appel, même en erreur. |
| Curseurs | `sig:v1:<source>:<charge>` opaque, lié à sa source, 2 Kio au plus ; l'état du flux (fenêtre, curseur ATTEINT, repère, dernière lecture réussie, dernier échec typé, compte de requêtes du jour) est un registre à chaîne de hachage. Le curseur n'avance que dans la transaction qui écrit les faits de la page : un échec rejoue la page, il ne la saute pas. |
| Quotas | `Quota(par_minute, par_jour)` DÉCLARÉ par la classe, `a_verifier=True` partout ; le limiteur refuse AVANT l'envoi (`REJ-SIGNAUX-QUOTA-LOCAL`, reprenable, délai en secondes) ; le compte du jour est persisté avec le curseur et survit à un redémarrage (le plus haut gagne). |
| Idempotence | `fait_id` = identité (source, compte, nature, portée, période) RECALCULÉE à la normalisation ; même valeur relue = aucun changement ; valeur révisée par le fournisseur = révision suivante ; deux valeurs pour le même fait dans une page = page refusée en entier ; événement au bus à identifiant déterministe (instant de lecture inclus). |
| Erreurs typées | Catalogue fermé `REJ-SIGNAUX-*` (`erreurs.py`) : 401 jeton refusé (non reprenable), 403 permission ou quota selon le motif, 429 avec `Retry-After` borné à 24 h, 5xx et délais reprenables, 404 introuvable, réponse non JSON ou trop grosse (5 Mio) refusée, valeur numérique monstrueuse refusée. Le corps de la réponse n'est jamais recopié. |
| Minimisation PII | Requêtes de recherche, chemins de pages, libellés de campagne, extraits d'avis : masqueur d'observabilité (`opsys.observabilite.pii`) AVANT d'entrer dans un fait ; paramètres d'URL retirés ; nom d'un auteur d'avis jamais lu ; texte de tiers conservé seulement avec l'option `extraits_avis`, ≤ 280 caractères, marqué `non_fiable`. Sans masqueur, aucun connecteur ne démarre. |
| Provenance et fraîcheur | Chaque fait porte fournisseur, point d'accès, version d'API DÉCLARÉE, mode (`api_lecture` ou `import_manuel`), empreinte de la réponse et page. La fraîcheur est celle de la dernière LECTURE RÉUSSIE d'une fenêtre complète comparée à la fenêtre déclarée de la source (`a_jour`, `perime`, `jamais_ingere`, `en_echec`) ; la plus stricte entre l'appelant et le producteur s'applique (décision r1 §3). Une absence n'est jamais un zéro. |
| Transport | `Transport` est un port ; le défaut `TransportNonBranche` refuse (`REJ-SIGNAUX-TRANSPORT-NON-BRANCHE`, non reprenable) ; un tour sans transport n'écrit que l'échec. |

### 3.2 Les dix sources (forme d'API rapportée par R4, jamais exercée contre le vrai service)

| Source | Point d'accès de lecture | Flux | Quota local déclaré | Fenêtre de fraîcheur / retard | Particularités |
|---|---|---|---|---|---|
| `search_console` | `searchAnalytics.query` (POST de lecture) | jour, requêtes (100 premières par semaine complète), pages | 60/min, 2 000/j (le fournisseur : 1 200 QPM, R4 « V ») | 72 h / 3 j | requêtes rares anonymisées (`anonymise_partiel`) ; le rapport « IA générative » n'est PAS lu (API non documentée, R4 §10) : import manuel |
| `pagespeed` | `runPagespeed` | mobile, desktop | 10/min, 200/j | 192 h / 0 | clé d'API en paramètre secret ; un tour par SEMAINE ; labo + terrain si présent ; l'absence de terrain n'est pas un zéro |
| `crux` | `records:queryRecord` | phone, desktop | 10/min, 200/j | 192 h / 0 | 404 « pas de donnée » = page vide sans échec (ne distingue pas une origine peu visitée d'une origine mal déclarée) |
| `bing_webmaster` | `GetQueryStats`, `GetPageStats`, `GetRankAndTrafficStats` | jour, requêtes, pages | 30/min, 500/j | 72 h / 2 j | dates `/Date(ms)/` décodées ou refusées ; agrégation hebdomadaire en `Decimal` ; le rapport « AI Performance » n'est PAS lu |
| `umami` | `websites.stats`, `websites.metrics` | jour, référents | 60/min, 1 000/j | 36 h / jusqu'à hier | auto-hébergé ; un jour sans aucune visite n'est PAS écrit (un traceur muet ne se distingue pas d'un jour calme) |
| `matomo` | `VisitsSummary.get`, `Referrers.getWebsites` | jour, référents | 60/min, 1 000/j | 36 h / jusqu'à hier | auto-hébergé ; `token_auth` dans le CORPS ; un jour `[]` est un trou ; une méthode d'écriture (`SitesManager.addSite`) est refusée par la liste blanche |
| `gbp_avis` | `accounts.locations.reviews.list` | principal | 60/min, 3 000/j (le fournisseur : 300 QPM après approbation) | 72 h / 0 | NOM de l'auteur jamais lu ; une ligne par avis (note, réponse oui/non) ; texte seulement avec `extraits_avis` |
| `gbp_insights` | `locations.getDailyMetricsTimeSeries` | principal | 60/min, 3 000/j | 96 h / 3 j | une métrique par appel ; une valeur absente est un TROU |
| `google_ads` | `googleAds:search` (GAQL en lecture) | compte, campagnes | 60/min, 1 500/j | 36 h / jusqu'à hier | jeton développeur = secret annexe ; `costMicros` → CAD exact ; devise non CAD ignorée et comptée |
| `meta_ads` | insights du compte (`act.insights`) | compte, campagnes | 30/min, 1 000/j | 36 h / jusqu'à hier | erreur 400 code 4/17/32/613/80000+ = limite de débit reprenable, code 190 = jeton refusé ; conversions : `lead` sinon la somme des ventilations |

Sources d'import seulement (`import_manuel.py`) : `search_console_ia`, `bing_ai_performance`, `journaux_serveur` — le mapping des colonnes est FOURNI par
l'appelant, jamais deviné ; 2 Mio et 20 000 lignes au plus ; formule de tableur neutralisée ; tout ou rien.

### 3.3 Ingestion dans les registres existants

- Faits : registre `signaux_marketing` (chaîne de hachage, 50 000 maillons au plus, refus au-delà, jamais tronqué).
- Dépenses : un relevé `RELEVE_PLATEFORME` (CAD, `HORS_TAXES`, jamais converti) par jour — le total du compte (`compte_jour`, requête `FROM customer`)
  et le détail par campagne — dans le registre `depenses_marketing` existant, avec la révision suivante quand la plateforme révise un montant. Un
  canal avec tous ses jours devient `CONNUE` pour M5, M8 et M9 ; un jour manquant donne `PARTIELLE`, jamais zéro. **Un compte déclaré `fictif` n'écrit
  JAMAIS de relevé** (une dépense fictive ne doit pas devenir un fait lu par M5, M8 ou M9).
- Les rapports publicitaires se lisent jusqu'à HIER (jour complet) : une dépense du jour en cours serait partielle.

## 4. Médias payants (`medias_payants/`, `medias_outils.py`)

- **Plan de campagne en brouillon** (`plan.py`) : canal (Google Ads, Meta), objectif, budget en CENTS entiers (total, plafond quotidien, durée ≤ 90 j, début au
  moins demain), ciblage GÉOGRAPHIQUE et par mots-clés seulement (tout critère protégé — âge, sexe, origine, religion, santé, revenu… — est refusé
  par nom), créatifs = visuels du studio déjà COMPOSÉS, CONTRÔLÉS et APPROUVÉS par une personne (empreinte vérifiée à la rédaction, à la soumission et à
  la décision), textes français obligatoires (anglais jamais plus long que le français), garde-fou de texte public (prix, lien, superlatif, chiffre non
  sourcé…), aucun nom de concurrent dans un mot-clé ou un texte. Budget borné par les plafonds durs du sas social (`PolitiqueSas`).
- **Cycle** : BROUILLON → PRET_POUR_APPROBATION → `LANCEMENT_APPROUVE_NON_EXECUTE` (ou RETIRE). Réviser un plan prêt le ramène à BROUILLON et rend
  l'ancienne empreinte caduque. **Le lancement est un engagement de dépense : N4, le propriétaire seulement** (`m7_demander_lancement_campagne`) ; l'approbation
  est CONSIGNÉE, rien n'est créé ni dépensé chez la plateforme : la direction lance la campagne avec le dossier de lancement (étapes manuelles, plafonds à
  saisir, publications d'annonce Meta préparées pour le sas existant, qui reste N4 de son côté).
- **Règles de plafond et d'arrêt PRÉPARÉES** (`regles.py`) : plafond quotidien (tolérance 20 %) et plafond total toujours présents (déduits du budget, non
  retirables) ; en plus, coût par conversion maximal, dépense sans conversion, saut de dépense. Leur seule action est `proposer_pause` ; tout constat porte
  `executee: false`. Une règle sans de quoi être jugée (jours manquants, conversions inconnues, échantillon mince) est « non évaluable » avec sa raison.
- **Anomalies par règles transparentes** (`anomalies.py`) : DEP-01 plafond quotidien, DEP-02 dépense sans conversion, DEP-03 saut contre la médiane des 7 jours
  précédents, DEP-04 dépense hors période du plan, DEP-05 jours sans donnée (info : dépense INCONNUE), DEP-06 coût par conversion, DEP-07 budget total dépassé.
  Identifiants déterministes ; événement `m7.anomalie_depense_detectee` (M9, M8) idempotent.
- **Rapport de performance honnête** (`rapport.py`) : couverture et jours manquants, totaux des jours lus (jamais extrapolés), taux de clic et de conversion avec
  intervalle de Wilson (95 %) et effectif, coût par conversion avec intervalle déduit (borne haute « non bornée » si le taux peut valoir zéro), suffisance (sous 100 clics
  ou 5 conversions : ne pas conclure), campagnes dont les intervalles se chevauchent regroupées « indistinguables » SANS classement, `causalite: non_etablie`.
  Conversions fractionnaires (modélisées) : intervalle non calculé, et le dit.
- Évaluation, signalement et rapport lisent de l'argent : même garde que `m7_lire_depenses_marketing` (admin confirmé, propriétaire de console, ou approbation
  serveur du propriétaire), contrôlée avant et après la lecture.

## 5. Veille concurrentielle gouvernée (`veille/`, `veille_outils.py`)

- **Registre de concurrents DÉCLARÉS** par le client (`m7_declarer_concurrent`, N3) : domaine public, au plus 5 sources HTTPS par concurrent, 10 concurrents actifs.
  Plateformes interdites en liste fermée (réseaux sociaux, moteurs de recherche, places de marché, interfaces d'IA…) : `REJ-VEILLE-PLATEFORME-INTERDITE`. Aucun
  identifiant dans l'URL, aucune IP, aucun hôte interne.
- **Collecte** (`collecte.py`) : le PORT `TransportPublic` n'a AUCUN transport réel ; il ne suit pas les redirections et n'a aucun paramètre d'en-tête, de cookie ni
  d'authentification. Avant toute page, `robots.txt` de l'hôte est lu et appliqué selon la RFC 9309 (`robots.py`, correspondance sans regex) avec l'agent déclaré
  `OpsysVeille/1.0` ; un chemin interdit n'est JAMAIS demandé ; un `robots.txt` inaccessible (5xx, 401, 403, délai) interdit tout ; `Crawl-delay` et un délai minimal de 10 s par hôte
  sont respectés en REFUSANT (jamais en dormant) ; trois redirections au plus, chacune revalidée (hôte déclaré + robots) ; 401/403 consigné « accès refusé », jamais contourné ;
  types de contenu et 1 Mio bornés.
- **Faits datés et sourcés** (`observations.py`) : titre, méta-description, titres de niveau 1, nombre de mots, types de schéma, plan de site, robots d'IA autorisés ;
  tout texte de tiers est masqué, coupé à 200 caractères et marqué `non_fiable` / `contenu_tiers` ; une consigne injectée dans la page est détectée, le texte est ÉCARTÉ et
  `injection_detectee` est consigné ; péremption à 90 jours.
- **Comparaison déterministe** (`comparaison.py`) : valeurs et écarts exacts, « inconnu » quand une donnée manque, **aucun score, aucun classement, aucune cause**.
- **Conformité** (`conformite.py`, `m7_controler_texte_contre_concurrents`) : un texte à publier ne nomme ni la marque ni le domaine d'un concurrent déclaré, ne recouvre pas
  20 % de 5-grammes d'un texte observé, et le vocabulaire comparatif porte la mention « À valider auprès d'un professionnel qualifié (avocat) ».

## 6. GEO/SEO sur données propres (`geo/`, `geo_outils.py`, `signaux/import_manuel.py`)

- **Robots d'IA** (`robots_ia.py`) : liste fermée (OAI-SearchBot, ChatGPT-User, GPTBot, PerplexityBot, Perplexity-User, ClaudeBot, Claude-User, Claude-SearchBot,
  Google-Extended, Applebot-Extended, CCBot, Bingbot — `a_verifier`) par catégorie (recherche, récupération à la demande, entraînement). La politique du client est SANS valeur par défaut :
  une catégorie absente est un refus. `llms.txt` : coût faible, preuve d'effet quasi nulle, rien n'est promis.
- **Journaux d'accès du client** (`journaux_bots.py`) : décomptes par robot, jour, classe de statut et groupe de chemins ; **aucune adresse IP n'est conservée ni renvoyée** ; sans
  plages publiées fournies avec leur source et leur date, chaque décompte porte `verification: "agent_seulement"` (un agent utilisateur se falsifie).
- **Panel par API OFFICIELLES** (`panel.py`, `visibilite.py`) : moteurs en liste fermée (`openai_responses_web_search`, `perplexity_sonar`, `gemini_grounding`,
  `anthropic_web_search`) ; toute « interface » est refusée (`REJ-GEO-MOTEUR-INTERFACE`) : jamais de scraping. Le coût mensuel est calculé d'avance à partir du coût déclaré par le client
  (inconnu ≠ 0) et plafonné. Le texte des réponses n'est JAMAIS conservé (donnée non fiable) : seuls `mentionne`, `cite`, les domaines cités et une empreinte. Taux de mention et part de
  citations avec intervalle de Wilson, concurrents sur le même panel, `indistinguable` quand les intervalles se chevauchent, n < 20 → `insuffisant`, et l'avertissement « réponse d'API ≠ interface
  grand public ».
- **Recommandations sourcées et priorisées** (`recommandations.py`) : GEO-01 robot de recherche bloqué contre la politique, GEO-02 pages à fort affichage et taux de clic bas, GEO-03
  requêtes en position 8 à 20, GEO-04 Core Web Vitals lents, GEO-05 absence de robots de recherche autorisés dans les journaux, GEO-06 écarts d'audit SEO/AEO. Priorité = impact ordinal × facilité
  ordinale (tables dans le code) ; chaque recommandation cite les `fait_id`, leurs dates et leur fraîcheur ; une donnée absente ou périmée rend la règle « non évaluable » avec ce qu'il faut importer.
  Aucune promesse de visibilité (Google : aucune optimisation spéciale n'est requise pour les fonctions d'IA ; la manipulation des réponses génératives est du pourriel).
- **Changements de site en BROUILLON** (`proposition_site.py`) : opérations en liste blanche (titre et description d'une page, résumé et description d'un service, ajout d'une FAQ) sur un schéma
  `opsys.site/v1`, original jamais muté, diff exact, validés par `schema_site`, `garde_contenu` et le QA existants, contrôle des marques de concurrents. Rien n'est publié : la publication reste
  `m7_demander_publication_site` (N3).

## 7. Mesure marketing (`mesure/`, `mesure_outils.py`)

- **UTM normalisées** (`utm.py`) : table d'alias explicite sur la convention gelée ; `meta`, `social`, `direct` refusés comme ambigus ; une campagne hors convention est non normalisable ; les
  identifiants publicitaires (gclid, fbclid, msclkid) sont signalés par leur nom et ÉCARTÉS.
- **Conversions hors ligne** (`conversions.py`) : appel, rendez-vous, soumission signée, vente ; liste de champs fermée (aucun nom, courriel, téléphone ni identifiant publicitaire) ; valeur en texte décimal CAD ; source
  normalisée ou `null` (jamais attribuée par défaut) ; lot de 200 au plus, tout ou rien ; événement `m7.conversion_hors_ligne_importee` dans la même transaction. **Aucune conversion n'est envoyée à Google ou Meta.**
- **Conception de tests** (`experiences.py`) : taille d'échantillon et puissance de deux proportions, durée d'un test marche-arrêt (≤ 26 semaines sinon `irrealisable`, calendrier alterné d'une graine par SplitMix64), plan de test
  géographique (< 6 paires → `INSUFFISANT`), lecture de résultat (Newcombe-Wilson). Chaque calcul rend un reçu `recu-calcul.v1` construit par `opsys.recu_calcul_pont` — le format de M5, vérifiable par `m5_verifier_recu_calcul` — et se
  REJOUE (`m7_rejouer_recu_mesure`). Toute la statistique est en `Decimal` (`statistiques.py` : Φ par série de la fonction d'erreur, quantile par Newton, Wilson) ; les tests la comparent à `statistics.NormalDist` et à des exemples publiés.
- **Préenregistrement** : un résultat n'est affirmé que s'il existe un plan préenregistré (reçu, hypothèse, métrique, dates) enregistré STRICTEMENT avant le début, et que la période des données est celle du plan ; sinon il est
  `exploratoire` avec la raison. Aucune sortie ne dit « causé par ».
- **Attribution simple** (`attribution_simple.py`) : « dernière source connue », `sans_source` au dénominateur et jamais redistribué, intervalle de Wilson par source, coût par conversion SEULEMENT quand la dépense du canal est `CONNUE` sur toute la période, sources indistinguables
  regroupées sans classement, `causalite: "non_etablie"` toujours.

## 8. Les outils (33 nouveaux ; aucun rôle d'appareil)

| Module | Outil | Niveau |
|---|---|---|
| Signaux | `m7_enregistrer_source_signaux` | T1 / **N3** (propriétaire) |
| | `m7_desactiver_source_signaux` | T1 / N2 |
| | `m7_lire_sources_signaux`, `m7_lire_signaux_marketing` | T0 (la dépense publicitaire est masquée sans la garde financière) |
| Médias payants | `m7_preparer_plan_media`, `m7_soumettre_plan_media`, `m7_retirer_plan_media`, `m7_signaler_anomalies_depense` | T1 / N2 (le dernier : garde financière) |
| | `m7_demander_lancement_campagne` | T1 / **N4** (propriétaire ; engagement de dépense consigné, jamais exécuté) |
| | `m7_lire_plans_media`, `m7_evaluer_regles_media`, `m7_rapport_performance_media` | T0 (les deux derniers : garde financière) |
| Veille | `m7_declarer_concurrent` | T1 / **N3** (propriétaire) |
| | `m7_retirer_concurrent`, `m7_importer_observation_concurrent` | T1 / N2 |
| | `m7_lire_veille_concurrentielle`, `m7_controler_texte_contre_concurrents` | T0 |
| GEO/SEO | `m7_importer_signaux_manuel`, `m7_proposer_changement_site`, `m7_retirer_proposition_site` | T1 / N2 |
| | `m7_analyser_robots_ia`, `m7_analyser_journaux_robots_ia`, `m7_planifier_panel_visibilite_ia`, `m7_calculer_visibilite_ia`, `m7_recommander_contenu_geo`, `m7_lire_propositions_site` | T0 |
| Mesure | `m7_importer_conversions_hors_ligne`, `m7_enregistrer_plan_test_marketing` | T1 / N2 |
| | `m7_normaliser_utm`, `m7_concevoir_test_marketing`, `m7_analyser_test_marketing`, `m7_rejouer_recu_mesure`, `m7_lire_attribution_simple` | T0 (le dernier : garde financière) |

Les N3 et N4 appelés par un agent attendent la file d'approbation du propriétaire (`_decideur`) ; approuvés, ils CONSIGNENT une décision. Skills compagnons :
`lecture-des-signaux`, `plan-de-campagne-payante`, `veille-concurrentielle`, `mesure-et-tests-marketing`. Le total d'outils sur la ligne passe de 537 à 570 ; le registre MCP est resellé
(`opsys-metier registre-mcp sceller`).

## 9. Événements du bus

| Type | Producteur | Quand | Contenu (jamais de mesure, de texte, de nom ni de donnée personnelle) | Consommateur visé |
|---|---|---|---|---|
| `m7.signaux_marketing_constates` | ingestion, import manuel | une fenêtre de lecture est terminée | source, compte, flux, mode, période, compteurs de faits nouveaux/révisés/inchangés, dernière lecture réussie, fenêtre de fraîcheur, `fictif` | M8 (mesures) |
| `m7.depenses_marketing_constatees` | ingestion (comptes réels) | un relevé TOTAL de canal est inscrit ou révisé | relevé, révision, canal, jour, montant CAD (texte), base de taxes, instant du relevé — aucun nom de campagne | M5, M8 |
| `m7.anomalie_depense_detectee` | `m7_signaler_anomalies_depense` | une règle DEP-0x se déclenche | identifiant, canal, campagne (identifiant technique), règle, sévérité, valeur/seuil (texte décimal), jours | M9, M8 |
| `m7.conversion_hors_ligne_importee` | `m7_importer_conversions_hors_ligne` | une conversion est importée | conversion, `lead_id` de M2, type, jour, source/medium/campagne NORMALISÉS, valeur CAD ou null | M2, M8 |

**Limite** : M7 est le producteur. Les consommateurs de M2, M5, M8 et M9 ne sont PAS écrits par cette tranche (ils appartiennent à leurs lignes de travail) ; aucune lecture de M8 n'a été
exercée sur ces événements. Les lectures par outil (`m7_lire_depenses_marketing`, `m7_lire_signaux_marketing`) sont, elles, exercées de bout en bout.

## 10. Registres durables

`sources_signaux`, `curseurs_signaux`, `signaux_marketing`, `plans_medias`, `concurrents_declares`, `observations_concurrents`, `propositions_site`, `conversions_hors_ligne`,
`plans_tests_marketing` (tous `m07-marketing`, append-only à chaîne de hachage) ; le registre `depenses_marketing` existant reçoit les relevés des connecteurs publicitaires.
Une chaîne de hachage ne détecte PAS la troncature du dernier maillon (documenté et testé, non corrigé).

## 11. Preuves

Suites (Python 3.12, stdlib seulement, SQLite fictive migrée, doubles de fournisseur ; aucun réseau) :

| Suite | Tests | Ce qu'elle prouve |
|---|---|---|
| `tests/signaux` | 534 | modèle de fait, quotas, curseurs, fraîcheur, comptes, registre, base des connecteurs (hôtes, liste blanche de lecture, secrets, statuts), ingestion (reprise au curseur, atomicité, quota persisté, arrêt propre, événements), outils (N3 réservé au propriétaire, masquage de la dépense), et un fichier par connecteur (Search Console, PageSpeed/CrUX, Bing, Umami/Matomo, fiche Google, Google Ads/Meta Ads) |
| `tests/medias_payants` | 309 | règles aux deux côtés de leurs seuils, anomalies DEP-01 à DEP-07, rapport (Wilson, suffisance, aucun classement), plan (chaque refus, révision, empreinte, créatif révoqué entre la soumission et la décision), outils (N4 propriétaire, garde d'argent AVANT lecture), chaîne ingestion → plan → évaluation → bus → rapport |
| `tests/veille` | 445 | robots.txt (RFC 9309), plateformes interdites et hôtes SSRF, collecte (robots avant la page, redirections, délais, 401/403 sans contournement), observations (PII, injection, péremption), comparaison, conformité, outils |
| `tests/geo` | 230 | robots d'IA, journaux sans IP (ReDoS, bornes), panel (moteurs d'interface refusés, coût d'avance, mention/citation exactes), import manuel (formule neutralisée, tout ou rien), recommandations (seuils des deux côtés), propositions de site (liste blanche), outils |
| `tests/mesure` | 279 | UTM, conversions hors ligne (schéma du catalogue, atomicité), statistiques contre `statistics.NormalDist` et des exemples publiés, conception de tests avec reçu vérifié par `recu_calcul_pont` et rejouable, préenregistrement, attribution |
| `tests/test_signaux_sans_reseau.py` | 122 | par la SOURCE : aucun import réseau, aucun `open`/`eval`/`exec`, aucun nom de geste d'écriture chez un fournisseur, listes blanches de lecture |
| `tests/test_evaluation_signaux.py` | 12 | corpus `evals/signaux.v1.yaml` (29 cas) : `reference` 29/29 qualifié, `dangereux` 17/29 non qualifié (11 cas bloquants), `inventif` 0/29, 9 sondes d'autorité tenues |

Suite complète du département M7 (`departments/m07-marketing/tests`, 1 210 tests avant la tranche) : **4 518 passed** (aucun échec, aucun saut). Les tests des modules nouveaux échouent sur la ligne de base
(`ModuleNotFoundError: m7_marketing.signaux` à la collecte) et passent avec le code. Trois tests existants ont dû changer parce que la tranche change ce qu'ils épinglent : la liste des événements publiés par M7
(`test_service_usine`), l'ensemble des outils N4 de M7 (`test_outils_publication` : l'annonce payante ET le lancement d'une campagne) et l'absence d'outil « dépense » autre que la lecture
(`test_depenses_marketing` : `m7_signaler_anomalies_depense`, N2, n'écrit pas le registre des dépenses — le test le vérifie sur la source).

Défauts trouvés PAR les tests puis corrigés (test rouge d'abord) : valeur numérique monstrueuse (`1e999999`) qui sortait en `InvalidOperation` brute du connecteur (désormais refus typé) ; relecture de la même
fenêtre à un autre instant qui levait `ConflitPublication` (l'instant est dans l'identifiant d'événement) ; deux lignes pour un même jour acceptées en silence par le connecteur Search Console (désormais
`REJ-SIGNAUX-REPONSE-INVALIDE`) ; rapports publicitaires lus jusqu'au jour en cours, donc une dépense partielle inscrite comme relevé (désormais jusqu'à hier) ; dans les médias payants : règle de saut qui disait
« aucun saut » malgré des jours manquants, montants non formatés à deux décimales, rapport planté sans aucun jour lu, doublons de créatifs/comptes/mots-clés acceptés, événement d'anomalie rejoué plus tard
en conflit ; code mort (branche IP décimale de `url_base_valide`, déjà refusée par le contrôle de nom d'hôte) supprimé.

Mutations personnelles (script `mutations-signaux.py`, une garde désactivée / une comparaison inversée / une validation retirée à la fois, suite ciblée, fichier restauré) : **30 mutations, 30 tuées**
(base : liste blanche de lecture, hôtes, quota, exception du transport, 401, 403 de quota, taille de réponse, nombre monstrueux ; quotas : borne du jour, minute glissante, compte persisté ; registre :
révision, borne, chaîne, conflit ; ingestion : repère, relevés d'un compte fictif, identifiant d'événement, arrêt ; comptes : http, secret en clair ; modèle : mesure flottante, identifiant ; minimisation PII ;
outils : masquage de la dépense, niveau N3 ; fraîcheur ; médias payants : plafond dur, plafonds obligatoires, seuil de suffisance, garde d'argent). Deux survivantes à la première passe, fermées : l'instant
dans l'identifiant d'événement (test de relecture de la même fenêtre ajouté) et la branche IP décimale (code mort supprimé). En plus, les quatre lignes de travail ont tiré leurs propres mutations sur leurs
modules (veille 14, GEO 12, mesure 13, médias payants 15 ; leurs survivantes — un doublon de drapeau, un ratio masqué par un minimum — sont fermées).

Sûreté vérifiée par exécution : aucun secret dans un `repr`, une exception, un fait, un curseur, un événement, un journal (sentinelles dans chaque suite de connecteur) ; aucune adresse IP en sortie des journaux
d'accès ; aucune écriture chez un fournisseur (méthode, point d'accès, nom) ; aucun texte de réponse de moteur d'IA conservé ; aucun nom d'auteur d'avis conservé ; aucune dépense fictive dans le registre des dépenses ;
vérificateur de cohérence du dépôt `OK : 10 départements, 570 outils` ; registre MCP resellé (révision 10, 591 outils exposés).

## 12. Ce qui n'est PAS prouvé

- **Aucun vrai service.** Les dix formes d'API (chemins, paramètres, corps, pagination, statuts) viennent de la recherche R4 et de connaissances générales ; aucune n'a été revérifiée contre la
  documentation officielle (pas de réseau) ni exercée. Les versions (`webmasters/v3`, `googleads/v17`, `graph/v21.0`, `mybusiness/v4`…) et TOUS les quotas sont `a_verifier`. Le niveau d'accès exigé
  chez chaque fournisseur (revue d'application Meta, niveau Basic de Google Ads, accès sur demande à l'API de la fiche) n'est pas traité : un compte déclaré ne prouve pas qu'il soit accessible.
- **Planificateur** ([PLANIFICATION.md](PLANIFICATION.md)) : `signaux.ingestion.tour_ingestion` et `veille.collecte.tour_veille` sont branchés aux exécuteurs `m7.signaux` et `m7.veille` (inactifs par défaut, plafond d'appels par 24 h) ; sans transport branché, ils disent « en attente de transport » et aucune donnée réelle n'entre. `geo.panel.executer_panel` (payant, N4, non persistant) n'est **jamais** appelé par un planificateur : décision « ne jamais automatiser ». Aucune voie d'import
  manuel d'un rapport publicitaire n'existe : la dépense réelle n'entre aujourd'hui que par un connecteur (non branché) ou par les voies existantes du registre des dépenses.
- **Les doubles ne prouvent rien sur les vrais services** : pas de latence, de concurrence, de dérive de schéma, de limites réelles, de pannes partielles du fournisseur. Le comportement de la pagination
  sur de très gros comptes n'est pas mesuré.
- **Statistique** : approximation normale, observations supposées indépendantes ; une série hebdomadaire autocorrélée ou saisonnière rend la durée d'un test marche-arrêt optimiste. Les seuils de suffisance
  (100 clics, 5 conversions, 20 réponses par moteur, 6 paires géographiques), la tolérance de plafond (20 %), le ratio de saut (300 %) et la péremption (90 jours) sont des choix de prudence internes, pas des faits.
- **Minimisation** : le masqueur à motifs rate les noms propres sans civilité et les adresses écrites en mots. C'est pourquoi aucun texte libre de tiers n'est conservé par défaut. La détection d'injection de la veille est
  par motifs (peut rater ou signaler à tort). Le registre `conversions_hors_ligne` n'est pas borné en taille.
- **Légal** : Loi 25 (ÉFVP avant transfert hors Québec : Google, Meta, moteurs d'IA, analytique), LCAP, Charte de la langue française et publicité comparative sont signalés mais NON validés — **À valider auprès d'un avocat /
  professionnel qualifié**. Les conditions d'utilisation des moteurs d'IA pour un panel de visibilité (R4 §10, 11) restent à lire. Un compte publicitaire sert une marque : aucun avis n'est donné sur le contenu des annonces.
- **Matrice** (`docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M7.json`) : aucun statut passé à FAIT_PROUVE. M7.7 (médias payants) et M7.9 (veille) passent de SIMULE à PARTIEL, ce qui est un JUGEMENT à
  confirmer : M7.7 parce que le plan, ses plafonds, l'approbation N4 consignée et le dossier de lancement manuel s'utilisent sans donnée de plateforme (mais la LECTURE des campagnes reste
  simulée par des doubles) ; M7.9 parce que la saisie humaine d'un fait lu sur une page publique est une voie de données réelle (la collecte automatique reste simulée). Au sens strict de la légende
  (« n'existe qu'à travers un double »), la lecture des comptes publicitaires et la collecte automatique restent SIMULÉES. M7.4, M7.5, M7.6, M7.8, M7.10 et M7.11 restent PARTIEL avec une limite mise à jour.

## 13. Décisions prises (à confirmer par l'architecte)

1. Déclarer une source de données propres est N3 (connexion permanente à un système externe), comme les comptes sociaux ; la lecture n'est jamais un outil d'agent.
2. Le lancement d'une campagne payante est un N4 CONSIGNÉ distinct du N4 d'annonce payante du sas : le sas ne connaît que les réseaux sociaux, pas Google Ads ; aucun des deux n'exécute.
3. Un compte fictif n'écrit jamais au registre des dépenses.
4. Les rapports publicitaires se lisent jusqu'à hier ; le repère de lecture avance seulement quand une fenêtre est entièrement écrite.
5. Aucune migration alembic (registres génériques). Si l'architecte préfère des tables dédiées pour l'indexation des signaux (50 000 faits), ce serait la migration 0051 réservée.
