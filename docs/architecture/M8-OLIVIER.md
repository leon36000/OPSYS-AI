# M8 Analytics (Olivier) : la couche analytique d'entreprise

Statut : tranche 1 (2026-11-01). Exigences : M8.2, M8.8, M8.11, M8.12, M8.14, M8.18 de `docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M8.json`
(toutes passées d'ABSENT à PARTIEL, avec preuve et limites ; aucune n'est « complète »). Code : `departments/m08-analytics/src/m8_analytics/`
(`catalogue_mesures`, `moteur_mesures`, `fraicheur_mesures`, `synthese`, `entrepot`, `entrepot_stockage`, `wallboards`, `sante`, `copilote`,
`memoire`, `analytique_outils`, `jeux_fictifs`), socle (`src/opsys/pont_bi/`, `src/opsys/console/wallboards_*`), migration `0046`, M10
(`analytique.py`). Tests : voir « Preuves » plus bas.

> **Ce que cette tranche est, et n'est pas.** Elle livre le mécanisme et le prouve sur des données FICTIVES, avec SQLite, le vrai bus, la
> vraie console (FastAPI) et le vrai coffre chiffré. Elle ne touche aucun service externe : aucun Metabase, Superset, Grafana ni navigateur
> n'a lu un export ; aucun écran de télé n'a affiché un wallboard ; aucune donnée d'entreprise réelle n'existe ; les bornes du score de
> santé et les fenêtres de fraîcheur des chantiers sont des décisions du propriétaire que M8 n'invente pas.

## 1. Le principe : UN catalogue fermé, UNE lecture, UNE règle de fraîcheur

```
registres des départements (faits_chantier, faits_entonnoir, faits_contenus, faits_cash_libre)      ← la vérité, inchangée
        │  moteurs gouvernés existants (entonnoir, contenus, mesures_chantier, cash_libre) + synthese.py (4 mesures d'entreprise)
        ▼
moteur_mesures.lire(registres, catalogue)  →  18 mesures : valeur exacte (texte) | « non calculable », source, version de définition,
        │                                        instant du dernier fait qui la porte, fenêtre de fraîcheur DÉCLARÉE
        ├── fraicheur_mesures  : a_jour | perime | inconnu | manquant | non_applicable   (la plus stricte des fenêtres)
        ├── wallboards (M8.8)  ├── sante (M8.11)  ├── copilote (M8.12)  ├── memoire → M10 (M8.18)
        └── entrepot (M8.2, DÉRIVÉ, versionné) ── pont BI (M8.14, lecture seule)
```

Toutes les surfaces lisent les mêmes mesures par le même moteur : une mesure n'a donc qu'une valeur, qu'une provenance et qu'une fraîcheur,
quelle que soit la surface qui la montre. M8 ne calcule rien de plus que ses moteurs gouvernés (règle du dépôt : « le code calcule, le LLM
orchestre ») ; l'entrepôt n'est lu par aucune surface de lecture sauf le pont BI et l'historique (les wallboards, le score et le copilote ne
dépendent pas de lui : détruire l'entrepôt ne change aucune de leurs réponses, test à l'appui).

### Le catalogue fermé (`definitions/m8-catalogue.v1.yaml`)

Dix-huit mesures d'ENTREPRISE (aucune personne : ni technicien, ni client, ni contact), chacune référençant une métrique gouvernée d'un
registre existant (`m8-entonnoir`, `m8-contenus`, nouveau `m8-synthese`) : nom, unité, propriétaire et version de définition viennent d'elle,
une seule fois. Le catalogue est validé en mode fermé (clé inconnue, énuméré hors liste, doublon, synonyme partagé, fenêtre invalide,
métrique non définie : refus `REJ-CATALOGUE-…`). Sa `version_catalogue` est l'empreinte de sa forme canonique.

| Domaine | Mesures |
|---|---|
| ventes | leads reçus et qualifiés, devis envoyés, acceptés, sans réponse, taux d'acceptation, carnet signé (financier) |
| clientele | délai du lead à l'acceptation (indicateur indirect : aucune mesure de satisfaction n'existe, M1 plaintes n'est pas consommé par M8) |
| marketing | contenus exportés, leads / devis envoyés / devis acceptés par contenu, impressions et clics (aucune source : toujours « non calculable ») |
| operations | chantiers terminés, écart de durée de l'équipe (agrégat existant, jamais par technicien) |
| qualite | chantiers avec signal critique de matériaux (le verdict de M6, compté) |
| finance | cash libre (le dernier constat de M5, tel quel ; financier) |

Les quatre mesures de synthèse (`synthese.py`, `metrics/m8-synthese.v1.yaml`) reprennent des résultats existants : aucun montant de M5 n'est
recalculé. Une donnée absente est « non calculable, manque X », jamais un zéro (par exemple l'absence de `m3.devis_sans_reponse` rend ce compte
non calculable : M8 ne peut pas dire si le bus n'a rien livré ou s'il n'y a rien à constater).

### La fraîcheur (`fraicheur_mesures.py`)

Décision d'architecte r1 (« fraîcheur M8 ») appliquée mesure par mesure : le catalogue déclare une fenêtre (vue exécutive : 24 h = 86 400 s) ou
`terminale` (mesure cumulée de chantiers terminés : non applicable une fois le chantier terminé). Le propriétaire peut resserrer ou fixer une
fenêtre (`department.yaml`, `configuration.fraicheur_mesures_s`, vide à la livraison : valeur invalide refusée ET dite, clé inconnue dite).
**Précédence : la plus stricte** entre le producteur (configuration, sinon catalogue) et l'appelant (`fraicheur_max_s`). L'âge est celui du
dernier fait qui porte la mesure, face à `maintenant`, que l'APPELANT donne (M8 n'a pas d'horloge : le garde statique `HORLOGE_INTERNE` couvre
tous les nouveaux modules).

| Statut | Sens | Montrable comme à jour ? |
|---|---|---|
| `a_jour` | âge ≤ fenêtre (borne incluse) | oui |
| `non_applicable` | mesure terminale, sans fenêtre demandée | oui, étiquetée « cumul de chantiers terminés » |
| `perime` | âge > fenêtre | **non** : dernière valeur connue, étiquetée |
| `inconnu` | aucun instant de fait lisible, fait daté dans le futur | **non** |
| `manquant` | mesure non calculable | **non** (aucune valeur) |

La règle réutilise le module existant `fraicheur_lectures` (mêmes bornes : entier de secondes de 1 à 3650 jours ; même refus d'une valeur invalide, dite et
jamais corrigée ; même idée : M8 déclare la fenêtre, le consommateur compare à l'âge) et l'étend de la LECTURE (`m8_lire_vue_executive`, `m8_lire_mesures_chantier`) à
la MESURE du catalogue. Les clés `fraicheur_attendue_s` de ces deux lectures ne changent pas.

**Limite assumée** : M8 ne distingue pas « l'entreprise n'a rien fait » de « le bus n'a rien livré ». Un fait trop ancien rend donc la mesure
périmée ; c'est au propriétaire de choisir des fenêtres qui conviennent à son rythme. Les mesures de chantiers terminés échappent à cette règle
par décision d'architecte, et le dire est tout ce que M8 fait de plus.

## 2. M8.2 Entrepôt de données (`entrepot.py`, `entrepot_stockage.py`, migration 0046)

Couche analytique DÉRIVÉE : jamais une source de vérité, reconstructible depuis les quatre registres, versionnée, avec fraîcheur et provenance par
mesure. Schéma en étoile dans la base de l'instance (SQLAlchemy Core, **portable SQLite et PostgreSQL**) :

| Table | Rôle | Écriture |
|---|---|---|
| `m8_ent_constructions` | journal des constructions : `version_schema`, `version_catalogue`, `empreinte_registres`, instant, comptes | append |
| `m8_ent_mesures_courantes` | mart : les 18 mesures, source, version de définition, dernier fait, fenêtre déclarée | remplacée en bloc |
| `m8_ent_mesures_hist` | historique d'une mesure par construction | append |
| `m8_ent_dim_chantier` | dimension : durées, verdict de matériaux, marge réelle de M5 (aucun technicien) | remplacée en bloc |
| `m8_ent_dim_lead`, `m8_ent_fait_devis`, `m8_ent_mart_contenus` | dimension, fait, mart | remplacées en bloc |

* **Dérivé et reconstructible** : `reconstruire` repart des registres ; mêmes registres + même catalogue + même schéma = mêmes lignes
  (`inchange`, rien n'est écrit). Détruire l'entrepôt ne perd rien (testé) ; une construction est atomique (savepoint) : un échec en cours
  d'écriture ne laisse ni ancien état perdu ni nouvel état partiel (testé).
* **Versionné** : `version_schema`, `version_catalogue` (empreinte) et `empreinte_registres` ; `etat` dit `absent`, `a_jour` ou `en_retard`
  (et pourquoi) face aux registres actuels.
* **Le statut de fraîcheur n'est pas figé** dans l'entrepôt (il dépend de l'heure de la lecture) : seul l'instant du dernier fait et la fenêtre
  déclarée le sont.
* **Sans personne** : aucune colonne `technicien`, `client`, `contact` (le fait de chantier en porte un : il n'est pas repris). Test.
* **Portabilité PostgreSQL** : tous les DDL se compilent pour PostgreSQL ; la migration 0046 est montée sur un PostgreSQL éphémère (Docker) par
  `tests/test_m8_migration.py` quand Docker est disponible. Le *constructeur* n'a pas été exécuté sur PostgreSQL (limite).
* **DuckDB** : non installé, donc non utilisé (stdlib uniquement). Parquet/DuckDB restent « GATED » (hors périmètre v1).
* **Outils** : `m8_construire_entrepot` (N2), `m8_lire_entrepot` (N0). Planification : `entrepot-et-memoire` (jours ouvrables, 6 h 30).
* **Retard assumé** : les consommateurs du bus n'écrivent pas dans l'entrepôt (la voie de la vérité reste intacte et rapide) ; l'entrepôt
  rattrape à la construction suivante et le dit (`en_retard`). Les surfaces de lecture vivantes n'en souffrent pas (elles lisent les registres).

## 3. M8.8 Wallboards en direct (`wallboards.py`, `console/wallboards_ui.py`)

**Définition déclarative** (`departments/m08-analytics/wallboards/<id>.v1.yaml`, format `opsys.m8.wallboard/v1`, validation fermée) :

```yaml
schema: opsys.m8.wallboard/v1
id: direction                  # = nom du fichier
version: 1
titre: "Pouls de l'entreprise"
roles: [admin]                 # sous-ensemble de {admin, nathan_owner} ; la console relit le rôle en base
rafraichissement: {intervalle_s: 30, flux_max: 120}   # 5..3600 s ; 1..1000 envois par flux
rotation: {actif: false, intervalle_s: 20}            # pages ; inactive par défaut, avec bouton de pause
tuiles:                        # 1..12, mesures du CATALOGUE FERMÉ seulement
  - {id: taux-acceptation, mesure: m8_taux_acceptation_pct, titre: "Taux d'acceptation", page: 1,
     seuils: {sens: au_dessous, attention: "40", critique: "25"}}   # facultatif, texte décimal (jamais un flottant)
```

Deux wallboards livrés (`direction`, `marketing`), **sans seuil** (aucun seuil inventé : une tuile sans seuil n'a ni couleur ni alerte).

**Fraîcheur d'abord** : une tuile dont la mesure n'est pas `a_jour`/`non_applicable` porte `perimee`, son libellé EN TOUTES LETTRES (« PÉRIMÉE »,
« Fraîcheur inconnue », « Non calculable »), son âge ; son seuil est `indetermine` (aucune couleur, aucune alerte fondée sur un chiffre dont on
ignore l'âge) ; la bannière n'est **jamais « ok »** tant qu'une tuile est périmée, inconnue ou non calculable. Le formatage (« 25 000,00 $ »,
« 50,00 % ») vient du TEXTE exact de la mesure, jamais d'un flottant.

**Servi par la console** (`/wallboards`, `/wallboards/{id}`, `?tv=1`, `/api/wallboards/{id}`, `/api/wallboards/{id}/flux`) : session obligatoire,
rôle `admin` relu en base avant ET après chaque lecture (et à chaque envoi du flux), `Cache-Control: no-store`, aucune écriture. La lecture
passe par l'outil `m8_lire_wallboard` (T0/N0, `roles_appareil={"admin"}`, admin revérifié en base : `REJ-IDENTITE-APPAREIL-INVALIDE` sinon).
**Rafraîchissement borné** : SSE (`event: instantane` puis `event: fin`, `retry:` donné) qui se ferme de lui-même après `flux_max` envois (le
navigateur se reconnecte) ou dès que session/rôle sont perdus ; repli par interrogation périodique sans `EventSource`. Le script détecte la
perte de connexion (trois intervalles sans succès) et le DIT : tuiles marquées « non rafraîchies », bannière « ne vous y fiez pas ».

**Accessibilité (WCAG 2.2 AA visée)** : rendu serveur complet (la page sert sans script), `lang="fr-CA"`, un seul `h1`, tuiles `article` titrées,
une seule région `aria-live` (la bannière), lien d'évitement, bouton de pause (2.2.2) avec `aria-pressed`, cibles ≥ 44 px, focus visible, mouvement
réduit, `forced-colors`, mode TV agrandi, aucun script ni style en ligne (CSP `script-src 'self'`). L'état n'est jamais porté par la couleur seule
(texte + symbole + motif hachuré/biffé pour le périmé). **Les contrastes sont calculés** (rapport WCAG ≥ 4,5:1) sur les paires de couleurs que le CSS
sert réellement, clair et sombre. **Sans donnée personnelle superflue** : les tuiles ne portent que des mesures d'entreprise.

**Navigateur réel (banc `install/qualification/navigateur`, Chromium 156, 2026-11-01)** : le flux SSE, la péremption poussée sans rechargement,
la pause, le mode télé et la « Connexion perdue » (réseau coupé) sont joués dans un vrai navigateur et passent
(`docs/qualification/QUALIFICATION-NAVIGATEUR.md`). Ce passage a révélé un défaut que le faux DOM ne pouvait pas voir : la CSP de la console
(`default-src 'none'`, sans `connect-src`) bloquait `fetch` et `EventSource` — la page restait figée sur « Rendu initial » en affichant
« à jour » alors que les mesures étaient périmées. Corrigé : `connect-src 'self'` sur les seules pages `/wallboards/{id}` (aucune origine externe).
La détection de perte de connexion est lente par construction : la page ne le dit qu'après 3 × l'intervalle + 5 s (95 s pour un wallboard à 30 s).

**Non prouvé** : aucun lecteur d'écran, aucun écran de télé, ni Firefox/WebKit/Safari/mobile natif pour les wallboards ; le script est aussi exercé sous
Node avec un faux DOM (mise à jour par `textContent` seulement — le faux DOM jette si `innerHTML` est touché —, flux, repli, perte de connexion, pause).

## 4. M8.11 Score de santé de l'entreprise (`sante.py`, `definitions/m8-sante.v1.yaml`)

Indice composite transparent : cinq composantes (finance, ventes, opérations, qualité, clientèle), chacune sourcée par des mesures du catalogue.

* **Pondérations DÉCLARÉES** (entiers, somme 100 à chaque niveau ; finance 25, ventes 25, opérations 20, qualité 15, clientèle 15) : une PROPOSITION
  de l'architecte, montrée avec `validee: false` tant que le propriétaire n'a pas écrit `configuration.sante.ponderations_validees_par`.
* **Échelle d'un indicateur** : la borne « pire » vaut 0 point, « cible » 100, interpolation linéaire bornée. **Les bornes sont des seuils
  d'affaires du propriétaire** (`configuration.sante.bornes`, vide à la livraison) : M8 n'en invente jamais. Bornes à contre-sens du « mieux » ou
  égales : refusées et dites.
* **Explication par composante** : valeur exacte, source, fraîcheur, bornes, points, pondération et contribution de chaque indicateur ; la somme
  des contributions est le score (à l'arrondi du centième près). Texte décimal, jamais un flottant.
* **Indéterminé plutôt qu'un faux score** : une mesure non calculable, périmée, de fraîcheur inconnue, ou des bornes absentes/invalides rendent la
  composante PUIS le score `indetermine`, avec la liste de ce qu'il faut corriger ; les composantes déterminables restent montrées ; jamais une
  moyenne de ce qui reste. **Livré tel quel, sans bornes déclarées, le score est donc indéterminé** : c'est voulu.
* **Historique** : `m8_enregistrer_sante_entreprise` (N2) range le jugement (statut, score, score par composante, version de définition,
  empreinte des registres, pondérations validées ou non) au registre append-only `historique_sante`, sans bruit si c'est le même jugement.
* **Indicateur préparatoire** : mention « À valider auprès d'un comptable (CPA) / professionnel qualifié » sur chaque résultat.

**Calibration et sensibilité, sur données FICTIVES** (`sante.calibrer`, `jeux_fictifs.SCENARIOS_SANTE_FICTIFS`, bornes de démonstration
`BORNES_SANTE_FICTIVES`, jamais une recommandation) :

| Entreprise fictive | Score | Observation |
|---|---|---|
| saine | 96.82 | ordre attendu respecté |
| correcte | 69.18 | |
| fragile | 11.29 | |
| sans constat de cash | indéterminé | refuse de noter, nomme la composante finance |

* Écart entre entreprises : plus de 20 points entre chaque niveau.
* **Sensibilité aux mesures** : déplacer une mesure de 10 % de l'étendue pire→cible vers le mieux bouge le score global d'au plus 10 % de la
  pondération globale de cet indicateur (finance : +2,50 points au plus pour 25 % de pondération) ; jamais à la baisse.
* **Sensibilité aux pondérations** : transférer 5 points de pondération entre deux composantes ne change jamais l'ORDRE des trois entreprises
  (toutes les paires, dans les deux sens, testées).
* Ces mesures disent ce que le score fait sur des cas de forme connue, pas qu'il est « juste » : la validité d'affaires reste au propriétaire.

## 5. M8.12 Copilote analytique (`copilote.py`)

Des questions en français vers le catalogue fermé ; **aucun SQL libre généré**, aucun modèle de langage dans cette couche (déterministe), aucun calcul
de tête (chaque nombre du texte est un texte déjà produit par le moteur, vérifié par test).

Pipeline : validation (2 à 400 caractères, aucun caractère de contrôle ou invisible) → refus typés dans l'ordre **injection** (`REJ-COPILOTE-INJECTION`),
**SQL** (`-SQL-REFUSE`), **secrets** (`-SECRET-REFUSE`), **personnes** (`-DONNEE-PERSONNELLE`, aussi les classements), **écriture** (`-ACTION-REFUSEE`) → intention
fermée (valeur, fraîcheur, tendance, santé, liste) → résolution de la mesure par formulations déclarées au catalogue (racines de mots,
accents/casse/ponctuation insensibles). Hors catalogue : refus (`-HORS-CATALOGUE`) ; plusieurs mesures sans conjonction ou aucune reconnue mais des
mots communs : `precision_requise` (au plus cinq propositions) au lieu de deviner.

Réponse : valeur exacte, unité, source, version de définition, fraîcheur ; une mesure périmée est dite « PÉRIMÉE… ne vous y fiez pas », inconnue « INCONNUE »,
non calculable « non calculable (il manque : …). Aucune valeur n'est donnée ». Les mesures financières portent « À valider auprès d'un comptable (CPA) /
professionnel qualifié ». **La question n'est jamais recopiée** dans la réponse et le texte libre d'un fait (détail d'un manque venu d'un autre
département) non plus : seuls des NOMS de manques, qui appartiennent au code, sont cités.

**Reçu** (`opsys.m8.copilote.recu/v1`) : empreinte de la question normalisée (pas son texte), du catalogue, des valeurs lues, de leur fraîcheur, de l'instant
et de l'empreinte des registres. `verifier_recu` recalcule (un reçu modifié, tronqué ou forgé est faux) ; `recu_correspond` dit s'il décrit encore les mesures
actuelles. Un refus a aussi un reçu.

**Évaluation** : (1) le corpus du copilote lui-même, `departments/m08-analytics/evals/copilote.v1.yaml` (82 questions rédigées avant exécution : 30 valeurs,
tendance/fraîcheur/santé/liste, précision, hors catalogue, 11 injections, 6 SQL, 7 écritures, 6 personnes, 3 secrets), mesure la reconnaissance et les refus :
82/82 ; (2) le gabarit commun (`docs/architecture/EVALUATION.md`) : dix nouveaux cas M8 (appels d'outils réels, refus SQL/jeton BI/faux score/écriture dans l'entrepôt,
injection par un billet, honnêteté sur le périmé, mention CPA, français québécois), M8 22/22 avec le répondant `reference`.
**Limites** : le corpus a un seul auteur et suit les règles du module qu'il teste ; la reconnaissance est lexicale (une paraphrase sans aucun mot du catalogue est
refusée ou demande une précision — c'est le comportement voulu, pas une compréhension) ; aucun modèle réel n'a été mesuré (voir EVALUATION.md, « Ce qui manque »).

## 6. M8.14 Pont vers les outils BI externes (`src/opsys/pont_bi/`)

**Lecture seule, par construction et par épreuve.**

* **Surface** (montée dans la console, sans session) : `GET /pont-bi/v1/jeux`, `GET /pont-bi/v1/jeux/{jeu}.csv|.jsonl?limite&depart`, OData v4 minimal
  `GET /pont-bi/odata/`, `$metadata`, `/pont-bi/odata/{Entité}?$top&$skip&$select&$count`. Tout autre verbe : **405**, journalisé, l'entrepôt reste identique (test).
  Options OData non prises en charge (`$filter`, `$orderby`, `$expand`…) : **501 en format d'erreur OData**, jamais ignorées en silence.
* **Jeux** (`jeux.py`, liste fermée, colonne par colonne) : mesures courantes et historique, chantiers, devis, leads, contenus, constructions. Colonnes FINANCIÈRES
  (marge réelle, prix, verdict de marge) et lignes des mesures financières absentes sans la portée `financier` du jeton.
* **Jeton de lecture dédié** : un secret du **coffre** (`pont-bi.<id>`), jeton `opsys-bi:v1:<id>.<secret>` en en-tête `Authorization: Bearer` SEULEMENT (dans l'URL :
  400, même valide). Secret comparé en temps constant ; jamais en base, journal ni réponse. Échec d'authentification = le même 401, sans oracle.
  **L'émission est un geste humain (N3)** : `opsys-metier pont-bi jeton-emettre --par …` exige une personne admin/propriétaire authentifiée **au clavier**
  (terminal interactif : un agent ou un script est refusé) ; aucun outil d'agent n'émet, ne lit ni ne révoque un jeton (test de surface).
  La révocation est immédiate (coffre + table).
* **Quotas par jeton** : requêtes par heure et lignes par jour (comptés dans le journal) ; dépassement : **429 avant toute donnée**, `Retry-After`.
* **Minimisation PII** : réutilise `MasqueurMotifs` de `opsys.observabilite`. Une colonne de forme connue (identifiant, instant, décimal, code) est VÉRIFIÉE et, si la
  valeur n'a pas la forme (un courriel dans un identifiant), masquée ; un texte libre est toujours masqué ; sans masqueur : refus 500, jamais d'export non masqué. CSV :
  cellules de formule (`= + - @ tab CR`) neutralisées par une apostrophe, sauf un nombre exact.
* **Journal d'accès** `pont_bi_acces` : append-only par déclencheurs (SQLite et PostgreSQL), qui/quoi/combien/refus et code, jamais le secret ni le contenu.
* **Lecture seule imposée** : l'export se lit dans une transaction `PRAGMA query_only` (SQLite) / `SET TRANSACTION READ ONLY` (PostgreSQL, non exécuté ici).
* **Provenance** : en-têtes `X-OPSYS-Entrepot-Construction` / `-Construit-Le`, `X-OPSYS-Total-Lignes`, `X-OPSYS-Cellules-Masquees`. Le pont sert l'entrepôt tel que construit :
  pour savoir s'il est en retard, `m8_lire_entrepot`.

**Non prouvé** : aucun Metabase/Superset/Grafana réel n'a lu un export (CSV/JSON/OData validés par des tests de format seulement) ; l'exposition réseau (TLS, pare-feu) est
l'affaire du déploiement ; l'adresse du client n'est pas journalisée (Loi 25, minimisation) donc pas de limitation par adresse ; OData n'est « minimal » que dans le sens ci-dessus.

## 7. M8.18 Intégration mémoire (`memoire.py`, `m10_memoire/analytique.py`)

* **Publier vers M10** : `m8_publier_faits_consolides` (N2) publie UN événement `m8.fait_consolide` (catalogue du socle, schéma fermé) : les 18 mesures (valeur ou null,
  unité, propriétaire, version de définition, dernier fait, fraîcheur), les **changements de définition** et les **anomalies** (`devenue_non_calculable`, `perimee`)
  depuis la consolidation précédente, avec l'empreinte des registres. Identifiant lié à l'état des registres et au catalogue : republier le même état rejoue la
  première enveloppe. **Aucune personne** (le catalogue du socle refuse un champ de plus).
* **M10 mémorise** (`analytique.py`, consommateur `m8.fait_consolide`) dans son registre `faits_analytiques` (append-only, chaîné), par liste blanche et formes fermées ;
  entrée **FINANCIAL** (jamais dans un paquet de contexte), une fois par `evenement_id`. Lecture : `m10_lire_faits_analytiques` (N0, admin confirmé pour un appareil).
* **Lire la mémoire** : `m8_contextualiser_mesure` interroge la base de connaissances de M8 par le service existant (`opsys.connaissances`, droits existants, M8 ne lit que
  SA base) avec une requête FABRIQUÉE par le code (nom gouverné + domaine) ; passages bornés, sourcés, datés, **non fiables et neutralisés** ; `aucune_source` sinon.
  Un appareil est refusé. **Limite** : le filtre anti-injection de la base de connaissances est à motifs (il remplace le segment reconnu, le reste du passage reste marqué non fiable).
* **Limite** : M8 ne lit pas directement les registres de M10 (aucun droit n'est élargi) ; la mémoire « d'entreprise » PostgreSQL (`opsys_memoire_rechercher`) n'est pas utilisée
  (PostgreSQL seulement).

## 8. Autonomie et niveaux

| Outil | Niveau | Qui |
|---|---|---|
| `m8_lire_mesures`, `m8_lire_sante_entreprise`, `m8_lire_entrepot`, `m8_repondre_question`, `m8_contextualiser_mesure`, `m8_lire_pont_bi` | T0 / N0 | agents ; fermés à tout appareil, y compris admin (refus dans le code) |
| `m8_lire_wallboard` | T0 / N0 | agents ; appareil `admin` revérifié en base ; la console |
| `m8_construire_entrepot`, `m8_enregistrer_sante_entreprise`, `m8_publier_faits_consolides` | T1 / N2 | agents, automatique (dérivé, append-only, événement interne) |
| `m10_lire_faits_analytiques` | T0 / N0 | agents ; appareil `admin` confirmé en base |
| émission / révocation d'un jeton BI | **N3 humain** | une personne, en ligne de commande, authentifiée ; aucun outil d'agent |

Aucun droit d'appareil n'est élargi au-delà de `m8_lire_wallboard` (ROLES.md). Le registre MCP est resellé (11 outils ajoutés). La Rule of Two les traite comme « hors table »
(approbation requise pour une session exposée à du contenu non fiable).

## 9. Configuration (`department.yaml`, `configuration`)

```yaml
fraicheur_mesures_s: {m8_leads_recus: 3600}          # secondes, par mesure ; vide à la livraison
sante:
  bornes:
    m8_taux_acceptation_pct: {pire: 20, cible: 60}   # seuils d'affaires du propriétaire ; vides à la livraison
  ponderations_validees_par: "Nom du propriétaire"
```

## 10. Preuves

* **Tests écrits avant le code et rouges sans lui** : les 14 fichiers de tests nouveaux échouent contre la base `1b58f4e6c` (13 sur 14 à la collecte — modules absents —, et
  `test_m8_migration.py` sur ses assertions : tête 0044, tables absentes, PostgreSQL).
* **Suites rejouées** (SQLite temporaire migrée, vrai bus, vrai coffre, vrai FastAPI, PostgreSQL éphémère pour la migration) : voir le rapport de livraison pour les comptes exacts.
  Les 9 échecs de `test_provenance_m5_appareil.py` sont **préexistants** (les tables `connaissances_fts*` de la migration 0041 diffèrent d'une liste de tables attendue), identiques
  à la base.
* **Mutations personnelles** (31, script hors dépôt : remplacement d’un fragment de code, suites ciblées, restauration) : frontière de fraîcheur (≤ → <), précédence de la fenêtre, seuil évalué sur du périmé, bannière « ok » malgré
  du périmé, note d'un score malgré une mesure périmée ou un manque, borne 0–100, injection / écriture / reçu du copilote, neutralisation des formules CSV, comparaison du secret,
  quota de requêtes (≥ → >), jeton révoqué dans la table seulement, transaction en lecture seule, lignes financières, masquage PII, idempotence de l'entrepôt, confidentialité M10,
  rôle de la page, borne du flux SSE, anomalie de péremption, doublon de catalogue, garde d'appareil, `innerHTML` côté script, changement de définition, seuils mal ordonnés,
  pondérations hors 100, fait dans le futur, cohérence valeur/statut. **Les 31 sont tuées.** Trois ont d'abord SURVÉCU (jeton révoqué dans la table seulement, export hors transaction
  en lecture seule, rôle de la page non relu par la page elle-même) : un test chacun les a fermées ; deux motifs ne correspondaient plus au texte après reformatage (corrigés).
* Fichiers de tests : `departments/m08-analytics/tests/` (`test_catalogue_mesures`, `test_fraicheur_mesures`, `test_entrepot`, `test_wallboards`, `test_sante`, `test_copilote`,
  `test_outils_analytiques`), `departments/m10-memoire/tests/test_analytique.py`, `tests/test_pont_bi.py`, `tests/test_pont_bi_cli.py`, `tests/test_m8_migration.py`,
  `tests/test_m8_memoire_m10.py`, `tests/test_console_wallboards.py`, `tests/test_wallboard_js.py`.

## 11. Ce qui reste (suivi explicite)

* Lecture réelle par Metabase/Superset/Grafana ; exécution du constructeur de l'entrepôt et des exports sur PostgreSQL ; DuckDB/Parquet (non installé).
* Wallboard sur un écran de télé ; test avec lecteur d'écran ; autres navigateurs (le parcours Chromium réel est fait, voir ci-dessus).
* Bornes du score de santé, pondérations validées et fenêtres de fraîcheur des mesures de chantiers : décisions du propriétaire.
* Source des impressions et des clics (connecteur à décider) ; mesure de satisfaction (M1 plaintes) pour une vraie composante « clientèle ».
* Mesure d'un vrai modèle sur le gabarit d'évaluation et sur le copilote ; paraphrases non lexicales.
* Réalignement de `down_revision` de la migration 0046 (« 0044 » sur cette branche ; « 0045 » à l'intégration si M2 est déjà fusionné).
