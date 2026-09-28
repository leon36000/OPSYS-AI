# Audit M2 — Revenue CRM

Auditeur : Claude (session `session_01V5Nu4HTRqHAjT1HJqArVEa`), 28 septembre 2026. Portée : lecture
et exécution de commandes seulement, aucune modification hors ce fichier. Références : `docs/produit/
DEFINITION-PRODUIT.md` §1, §5, §6, §7 (M2), §8, §9, §10, §13 ; `AGENTS.md` ; `docs/architecture/
ARCHITECTURE.md` et `DEPARTEMENTS.md` ; `departments/m03-estimation/` comme référence vivante ;
`docs/research/R6-m1-m2.md` et `INGREDIENTS.md`.

**Constat de départ.** Le statut `FAIT_VÉRIFIÉ` de DEFINITION-PRODUIT §7/§11 décrit le **M2 de
l'ancien dépôt Forge** (API `/api/crm` complète), aujourd'hui inaccessible (§13 point 7). Le code
présent dans `departments/m02-revenue-crm/` est une **reconstruction à neuf** sous OPSYS-CORE,
livrée par un cycle BMAD daté de juillet 2026 (gels du 2026-07-29 visibles dans le code) et importée
dans ce dépôt v2 en un commit unique (`ec973b6`, 28 septembre 2026 — tout le dépôt n'a qu'un commit).
Cette reconstruction est volontairement étroite : un « vague 1 » qui prouve un noyau minimal en mode
ombre, pas une reprise du périmètre Forge. Le contrat `/api/crm` cité par §7 n'est **pas encore
retenu ni construit** ici.

**Légende de statut.** ABSENT = rien n'existe. PARTIEL = une brique existe mais ne couvre pas tout le
besoin du prompt produit. PRÉSENT = couvert et testé conformément au besoin décrit.

---

## 1. Inventaire de l'existant

### 1.1 Méthode et preuve d'exécution

```
/opt/opsys-venv/bin/python -m pytest departments/m02-revenue-crm/tests -q --import-mode=importlib -p no:cacheprovider
→ 559 tests, exit code 0, aucun échec (compté deux fois : somme des dots de sortie ET somme du
  --collect-only par fichier — les deux comptes concordent à 559)
```

Décompte par fichier de test (`--collect-only -q`) : `test_adaptateurs.py` 41, `test_conformite_m1.py`
16, `test_digest.py` 31, `test_doublons.py` 43, `test_ingestion.py` 127, `test_isolation_modules.py`
12, `test_outils_agent.py` 16, `test_readiness.py` 64, `test_registre.py` 32, `test_statuts.py` 58,
`test_utilitaires.py` 119. Plus deux scripts hors pytest : `preuve_cas_limites.py`, `preuve_manuelle.py`.

Code source : 15 modules + `__init__.py`, **2 064 lignes** (`src/m2_revenue_crm/`). 8 outils d'agent
exposés par `outils.outils()`, tous validés par le contrat `opsys.outils.Outil` (préfixe `m2_`,
schéma JSON, autonomie déclarée) :

| Outil | Autonomie |
|---|---|
| `m2_ingerer_lead` | T1 |
| `m2_transitionner_statut` | T1 |
| `m2_detecter_doublons` | T0 |
| `m2_signaler_doublon` | T1 |
| `m2_arbitrer_doublon` | T1 |
| `m2_enregistrer_interaction` | T1 |
| `m2_evaluer_readiness` | T0 |
| `m2_produire_digest` | T0 |

Note lint (hors mandat, exécuté en diagnostic complémentaire, aucune modification) : le vrai gate
CI `ruff check src tests` (racine) est **vert** (« All checks passed ! »), mais il **ne couvre pas**
`departments/`. `ruff check departments/m02-revenue-crm` seul remonte 134 signalements, à 95 %
cosmétiques (E501 lignes longues ×43, I001 tri d'imports ×36, E402 ×14 dû au motif délibéré
d'ajout de `sys.path` en tête des fichiers de test, F401 imports inutilisés ×13, alias `UP0xx`) —
aucun bogue fonctionnel détecté. Point ouvert de gouvernance en §5.

### 1.2 Cœur existant (leads, clients, contacts, pipeline, kanban, tâches, activités, tags,
produits/services, soumissions, doublons, dossier client, import en lot, rapports)

| Entité / fonction | Statut | Fichiers | Tests |
|---|---|---|---|
| Lead (enveloppe `LeadM2` minimale) | PARTIEL — 7 champs gelés seulement, aucun champ commercial enrichi | `ingestion.py`, `contrats.py`, `statuts.py` | `test_ingestion.py` (127), `test_statuts.py` (58) |
| Client (post-conversion) | ABSENT — le statut `converti` ne crée aucun dossier client | — | — |
| Contact | PARTIEL — sous-objet du contrat (nom/téléphone/courriel), pas d'entité contact propre, pas de multi-contact | `contrats.py` | `test_utilitaires.py` |
| Pipeline | PARTIEL — FSM fermée à 4 statuts, aucun stage configurable, aucune valeur de deal, aucune probabilité | `statuts.py` | `test_statuts.py` (58) |
| Kanban (vue) | ABSENT | — | — |
| Tâches | PARTIEL — un seul champ `prochaine_action` par lead (pas d'entité `Task`, pas de multi-tâches, pas d'assignation multiple) | `statuts.py` | `test_statuts.py` |
| Activités | PRÉSENT — auteur/résumé/horodatage, append-only, bien testé, mais limité aux leads actifs (pas d'activité sur dossier clos) | `interactions.py` | intégré à `test_ingestion.py`, `test_readiness.py`, `test_outils_agent.py` |
| Tags | ABSENT | — | — |
| Produits/services (catalogue) | ABSENT | — | — |
| Soumissions (entité) | ABSENT — seule une référence opaque `reference_devis_m3` (chaîne non vide, non validée, jamais de montant) marque la conversion | `statuts.py` | `test_statuts.py` |
| Doublons (détection, signalement, arbitrage) | PRÉSENT — jamais de fusion, architecturalement inexprimable | `doublons.py` | `test_doublons.py` (43) |
| Dossier client (Client 360) | ABSENT | — | — |
| Import en lot | ABSENT | — | — |
| Rapports | PARTIEL — digest texte quotidien seulement (en attente / orphelins / doublons en attente) | `digest.py` | `test_digest.py` (31) |

### 1.3 Fonctions M2.1 à M2.15

| # | Fonction | Statut | Fichiers / tests | Note |
|---|---|---|---|---|
| M2.1 | Intégrité et audit du CRM | PARTIEL | `digest.py` (orphelins > 48 h) ; `test_isolation_modules.py` (12) et `test_conformite_m1.py` (16) font office de garde anti-régression (paquet isolé, empreintes SHA256 gelées de `horodatage.py`/`verdicts.py`) | Aucun contrôle générique « champs requis » au-delà de la validation d'ingestion |
| M2.2 | Client 360 | ABSENT | — | Aucune fiche agrégée n'existe |
| M2.3 | Profil de propriété | ABSENT | — | Rien sur bâtiment, étages, matériaux, accès |
| M2.4 | Lead Scoring 2.0 | ABSENT | recommandation scikit-learn documentée dans `docs/research/R6-m1-m2.md` §3.3, non codée | — |
| M2.5 | Préparation à l'estimation (readiness gate) | PRÉSENT | `readiness.py` | `test_readiness.py` (64, le fichier le plus couvert) — marqueur signé et recalculable sans confiance ; module le plus mûr du département |
| M2.6 | Prochaine meilleure action + explication | PARTIEL | `statuts.py` — stockage d'une action fournie par un humain seulement, jamais générée | Aucun moteur de suggestion (cohérent avec « jamais halluciné », mais la fonction produit n'existe pas) |
| M2.7 | Relances (séquences, dormants, saisonnier, avis, référence) | ABSENT | `digest.py` ne signale que l'orphelin à 48 h, pas de séquence | Aucun champ opt-in dans le contrat (voir §5) |
| M2.8 | Intelligence des soumissions | PARTIEL | `statuts.py` (motif de perte obligatoire, référence devis obligatoire) | Pas de probabilité, pas d'objections structurées, pas de transmission effective à M4/M5 |
| M2.9 | Coach de vente IA | ABSENT | — | — |
| M2.10 | Attribution des sources → M7 | ABSENT | `canal` capté à l'ingestion (`contrats.py`), aucun retour vers M7 | — |
| M2.11 | Segmentation (14 segments : `hot_lead`…`seasonal_opportunity`) | ABSENT | — | Aucun des 14 segments n'est calculé |
| M2.12 | Graphe d'identité et doublons | PARTIEL | `doublons.py` | `test_doublons.py` (43) — détection + signalement + arbitrage solides, mais la seule décision possible est `distincts_confirmes` : **il n'existe aucun chemin pour un humain qui confirme un vrai doublon** (pas de lien conservé, pas de statut « confirmé même entité ») |
| M2.13 | SLA et prévention de perte de leads | PARTIEL | `digest.py` — seuil fixe 48 h, non configurable | `test_digest.py` — pas d'escalade, pas de notification, juste un texte |
| M2.14 | Références et affaires répétées | ABSENT | — | — |
| M2.15 | Analytique et prévisions commerciales | ABSENT | — | — |

**Skills (3/3 déclarées, cohérentes avec les outils) :** `ingerer-un-lead`, `faire-progresser-vers-m3`,
`arbitrer-un-doublon` — chacune une procédure courte, alignée sur les outils réels, sans sur-promesse.

**Manifeste** (`department.yaml`) : mode `ombre`, dépendance déclarée `[m01-front-office]` (mais
**aucun appel réel** — voir §2.3), budget 220 000 tokens/jour, 2 KPI définis (aucun encore mesuré en
production, faute de déploiement).

---

## 2. Écarts

### 2.1 Modèle de données

Champs clés actuellement gelés dans le contrat `LeadQualifie` (liste blanche stricte, tout le reste
est rejeté à l'ingestion) : `lead_id, conversation_id, type_travaux, ville, canal, contact,
urgence_declaree`. L'enveloppe `LeadM2` y ajoute `statut, owner, prochaine_action,
interactions_humaines, readiness, motif_perte, reference_devis_m3, disponibilite_declaree,
signalements`. **Absents du modèle, requis par §7 et §8 :** client (entité propre), propriété,
soumission (entité, pas une référence), tâche (entité multiple), tag, produit/service, **champ
consentement/opt-in** (aucun, alors que les relances futures en dépendent), segment M2.11, score.
Statuts présents : les 4 de la FSM (`nouveau, qualifie, converti, perdu`) — corrects et bien gardés.
Segments M2.11 : 0/14.

### 2.2 API — compatibilité `/api/crm`

Recherche exhaustive (`grep -r "api/crm"`, `grep -rl "fastapi\|Flask\|APIRouter\|@app.route"`) :
**aucune route HTTP n'existe pour M2**, dans le département ni ailleurs dans le dépôt. Le seul usage
de FastAPI du projet sert la console OPSYS générique (`src/opsys/console/`), pas un `/api/crm`.

| Route attendue (§7) | Statut |
|---|---|
| `/api/crm/leads` | ABSENT |
| `/api/crm/clients` | ABSENT |
| `/api/crm/kanban` | ABSENT |
| `/api/crm/pipeline` | ABSENT |
| `/api/crm/soumissions` | ABSENT |
| `/api/crm/products` | ABSENT |
| `/api/crm/tasks` | ABSENT |
| `/api/crm/reports` | ABSENT |

Comme rien n'existe, la contrainte « ne doit pas être cassée » (§7) est techniquement respectée par
vide — mais le contrat à **honorer dès la construction** reste entier et non commencé.

### 2.3 Événements émis et consommés (§6)

Aucun bus d'événements n'existe au niveau OPSYS-CORE (`grep` sur `evenement|event_bus|EventBus` dans
`src/opsys/` et les départements : rien hors un mot-clé isolé dans la console). Le principe « les
départements se parlent par événements » (DEFINITION-PRODUIT §1) n'est câblé nulle part techniquement
à ce stade — ni pour M2 ni pour aucun autre département vérifié. Concrètement pour M2 :

- **M1 → M2** : convention de schéma partagée uniquement (les deux modules valident indépendamment
  la même forme `LeadQualifie`, avec suite de conformité rejouée — bonne discipline), mais **aucun
  outil M1 n'appelle `m2_ingerer_lead`** (`grep` sur `m2_ingerer_lead` dans `departments/
  m01-front-office/src` : aucune occurrence). Le flux §6 « M1 capte → M2 structure » n'est câblé nulle
  part.
- **M2 → M3** : `readiness.verifier_marqueur()` est conçu pour que M3 recalcule sans confiance, mais
  **M3 ne l'appelle pas** (`grep` sur `readiness|verifier_marqueur|hash_tete_registre` dans
  `departments/m03-estimation/src` : aucune occurrence). Rien n'empêche aujourd'hui `m3_estimer_projet`
  de tourner sur un lead qui n'a jamais franchi la readiness gate M2.
- **M2 → M5, M2 → M7, M2 → M8, M2 → M10** : aucun outil, aucune trace.

### 2.4 Outils d'agent

8 outils couvrent le cycle interne (ingestion, transition, doublons, interaction, readiness, digest).
**Manquants :** scoring de lead, segmentation, programmation de relance, export vers un CRM externe
réel (le `Protocol AdaptateurCRM` existe et est testé, mais `MODES = ("ombre",)` — aucune
implémentation concrète hors simulation mémoire), rapport structuré (JSON) au-delà du texte du digest.

### 2.5 Écrans mobiles par profil (§9)

| Profil | Attendu (§7, §9.4-9.6) | Statut |
|---|---|---|
| Admin | pipeline, leads chauds, relances, doublons | ABSENT |
| Vendeur | ses leads, prochaine action, Client 360, soumissions, coach de vente, pipeline personnel | ABSENT |
| Client | statut de la demande, soumission, rendez-vous | ABSENT |
| Employé | remonter des notes du terrain | ABSENT |

Rien n'est surprenant tant que l'API (§2.2) n'existe pas. Mais **`docs/architecture/MOBILE.md`**
révèle un écart plus profond : la stratégie mobile actuelle repose sur les apps officielles OpenClaw
(nœud, MIT) avec des écrans de phase 2 prévus pour les profils **Patron, Estimateur, Chef d'équipe,
Réception** — **le profil Vendeur et le profil Client n'y figurent pas du tout**, alors qu'ils sont
centraux pour M2. C'est une reformulation du point ouvert n° 9 de DEFINITION-PRODUIT §13, pas encore
réconciliée. Phase 1 (« sans développement ») ne prévoit qu'un canal de conversation avec l'agent M2
via l'app OpenClaw, pas des écrans dédiés.

### 2.6 Vues dashboard

Le tableau de bord OPSYS (`src/opsys/console/pages.py`, `tableau_de_bord.py`, 589 lignes) est
**entièrement générique** : cartes de département (mode, outils, planifications), file
d'approbations, jauges de budget, sélection de paliers de modèles. **Zéro vue spécifique à M2**
(aucune mention de `pipeline`, `kanban`, `crm`, `m2` dans ce code) : pas de liste de leads, pas de
tableau de pipeline, pas de rendu du digest en JSON/HTML.

### 2.7 E2E exigés

Intra-département : PARTIEL — `TestCycleDeVieComplet` (`test_outils_agent.py`) couvre un scénario
complet réaliste (ingestion → refus sans owner → qualification → readiness refusée puis acceptée →
conversion → refus de réouverture) et un scénario de perte. C'est un bon socle mais ce n'est pas
étiqueté E2E et ne couvre ni le lead incomplet multi-motifs ni Client 360 ni le lead dormant au sens
du digest orphelin combiné à une relance.
Inter-département : ABSENT — aucun test ne fait traverser un lead M1 → M2 → M3, conforme au constat
de câblage nul en §2.3.

---

## 3. Briques candidates

Licences vérifiées en lecture directe des fichiers `LICENSE` amont (recoupées avec
`docs/research/R6-m1-m2.md` §3 et §10, puis re-vérifiées en direct pour la fraîcheur au 28 septembre
2026). Toutes respectent la règle de licence de `AGENTS.md`.

### 3.1 Modèle CRM / UI pipeline-kanban (pour combler §1.2 kanban, Client 360, catalogue)

| Brique | Licence | Dernière version connue | Maturité | Verdict |
|---|---|---|---|---|
| [Twenty](https://github.com/twentyhq/twenty) | AGPL-3.0 + fichiers `@license Enterprise` propriétaires | v2.41.0 ; dépôt très actif (commits à la minute au 28-09-2026) ; fichier LICENSE retouché le 30-07-2026 (« clarify licensing/trademark ») | Très mature, ~55 k★ | **Écarté du vendoring** (AGPL). Réutilisable seulement comme inspiration gratuite de schéma (Client 360, timeline). Si envisagé en sidecar, **relire `LICENSE` avant toute décision** vu la clarification récente |
| [EspoCRM](https://github.com/espocrm/espocrm) | AGPLv3 | 10.0.8, publiée le 08-09-2026 | Mature, « 50 000+ entreprises » revendiquées, PHP | **Retenu comme sidecar Docker non modifié, optionnel** : façade kanban/pipeline/calendrier pour les représentants qui la préfèrent. Le registre M2 (append-only, hash-chaîné) **reste l'unique source de vérité** ; EspoCRM ne reçoit que des écritures via un futur `AdaptateurEspoCRM` implémentant le `Protocol AdaptateurCRM` déjà en place |
| SuiteCRM, Frappe CRM | AGPLv3 | matures | — | Écartés : redondants avec EspoCRM (plus lourds ou Python-natif mais AGPL quand même — l'affinité de langage ne lève pas la contrainte de licence) |
| Odoo CRM (Community) | LGPL-3 | très mature | — | Licence la plus favorable du lot mais ERP disproportionné pour le seul besoin CRM ; écarté par surdimensionnement |

### 3.2 Déduplication / graphe d'identité (pour M2.12)

| Brique | Licence | Dernière version connue | Maturité | Verdict |
|---|---|---|---|---|
| [Splink](https://github.com/moj-analytical-services/splink) | MIT | `5.0.0dev5`, 18-09-2026 ; commit le plus récent daté du 22-09-2026 | Très active (UK Ministry of Justice), DuckDB embarqué (zéro serveur additionnel), la plus rapide des trois testées dans R6 | **Retenu.** Passage asynchrone/batch qui alimente `doublons.signaler()` existant comme **second détecteur** — l'invariant « jamais de fusion automatique » n'est pas touché |
| [recordlinkage](https://github.com/J535D165/recordlinkage) | BSD-3-Clause | dernier commit **20-07-2023** (vérifié en direct aujourd'hui) | Stagnant depuis plus de 3 ans | **Écarté** : trop stagnant pour une adoption en septembre 2026, malgré la licence favorable |
| [dedupe](https://github.com/dedupeio/dedupe) | MIT | — | Fiabilité opérationnelle en question (fuite disque relevée sur benchmark récent, apprentissage actif lourd à opérer) | **Écarté** |

Le « graphe » d'identité n'a pas besoin d'une base de données graphe dédiée à cette échelle : la
table de signalements (`lead_id_a, lead_id_b, critere, arbitrage`) **est déjà** le repli relationnel
prévu par DEFINITION-PRODUIT pour Cognee absent (§10). Une traversée multi-sauts future resterait
un calcul Python pur sur cette table.

### 3.3 Scoring de lead explicable (M2.4)

**[scikit-learn](https://github.com/scikit-learn/scikit-learn)** — BSD-3-Clause, standard de facto,
très mature. **Retenu** : régression logistique ou gradient boosting léger sur les features déjà
présentes dans `LeadM2` (canal, ville, urgence, délai avant première interaction). Module
`scoring.py` pur (`score = f(features) -> float`), jamais un LLM pour ce calcul (cohérent avec le
principe « le code calcule »). Coefficients/feature importance = explicabilité native, sans coût
d'inférence.

### 3.4 Relances / SLA programmés (M2.7, M2.13)

**[APScheduler](https://github.com/agronholm/apscheduler)** — MIT. **Retenu** pour cadencer les
vérifications d'échéance à partir de `prochaine_action`, déjà stocké. Aucune brique de « séquence »
dédiée n'est nécessaire : le patron actuel (description + échéance ISO-8601) suffit à représenter une
relance programmée. **Préalable bloquant, pas une brique** : ajouter un champ de consentement/opt-in
au modèle de données avant tout envoi automatisé (voir §5).

### 3.5 API `/api/crm`

Pas une nouvelle brique à évaluer : **FastAPI 0.133.1 (MIT)** est déjà une dépendance du projet
(`pyproject.toml`, groupe `console`), déjà choisie et sous licence vérifiée pour le socle OPSYS.
Recommandation : réutiliser la même dépendance plutôt que d'introduire un second framework web.

### 3.6 Rapports agrégés (§1.2, M2.15)

**DuckDB** (MIT, déjà embarqué en dépendance transitive de Splink §3.2) peut servir de moteur de
lecture pour des rapports agrégés ponctuels sur le registre exporté, sans service additionnel sur le
VPS mono-nœud. Non urgent tant que M2.15 n'est pas amorcé.

---

## 4. Plan de construction par phases

### Phase 1 — tranche verticale « M1 capte → M2 structure → M3 estime » (§6)

Objectif : qu'un lead réel puisse traverser M1 → M2 → M3 sans intervention manuelle de recopie, avec
une readiness gate qui bloque effectivement M3, et une première fenêtre de lecture externe sur M2.

| # | Tâche | Taille | Critère de preuve |
|---|---|---|---|
| 1 | Câblage M1 → M2 : un outil ou une skill M1 appelle réellement `m2_ingerer_lead` avec la sortie de `m1_qualifier_signal`/`m1_transitionner_phase` | S | Test d'intégration nouveau (`tests/test_integration_m1_m2.py` à la racine ou dans `departments/`) : une sortie M1 réelle est ingérée par M2 sans transformation manuelle, verdict `accepte: true` |
| 2 | Câblage M2 → M3 : `m3_estimer_projet` refuse de calculer un prix si `readiness.verifier_marqueur()` est absent, invalide, ou ancré sur une tête de chaîne périmée | S | Test dans `departments/m03-estimation/tests` : un lead sans marqueur, puis avec marqueur falsifié, sont tous deux rejetés **avant** tout calcul de prix (verdict explicite, pas d'exception muette) |
| 3 | `/api/crm/leads` en lecture seule (T0) : liste filtrable par statut/owner, détail par `lead_id`, brancher directement sur `_registre` existant via FastAPI | M | Test httpx : `GET /api/crm/leads?statut=qualifie` retourne les leads attendus, aucune route d'écriture exposée |
| 4 | `/api/crm/reports/digest` : le digest existant exposé en JSON structuré (pas seulement le texte) | S | Test httpx : la réponse JSON contient les mêmes leads que `m2_produire_digest` pour les mêmes paramètres, égalité vérifiée |
| 5 | Entité `ClientM2` minimale créée automatiquement à la transition `qualifie → converti` (référence au lead d'origine, jamais un enregistrement libre) | S | Test : après conversion, un dossier client existe, porte la référence du lead et du devis, et son historique remonte à l'ingestion d'origine |
| 6 | Segmentation M2.11 minimale et pure, calculable sans nouvelle donnée : `hot_lead` (urgence_declaree + statut nouveau), `dormant_lead` (réutilise le seuil orphelin existant), `quote_stale` (converti attendu mais `reference_devis_m3` absente après délai configurable) | S | Fonction pure `segmenter(lead) -> tuple[str, ...]`, testée sur les trois cas + cas négatif (aucun segment) |
| 7 | Persistance : adaptateur `RegistrePostgres` implémentant l'interface exacte de `Registre` (`ajouter/lire/tete/valider_chaine`), sans toucher `statuts.py`/`doublons.py`/`readiness.py` | M | Suite `test_registre.py` rejouée telle quelle contre l'implémentation Postgres, verte à l'identique ; test de redémarrage de processus prouvant la survie des données |

Chaque tâche reste petite, testable isolément, et respecte l'ordre du flux principal : sans la tâche 7,
tout le reste reste un jouet en mémoire qui perd ses données au moindre redémarrage (voir §5).

### Phase 2 — durcissement et intelligence (dépend de la phase 1)

Champ opt-in dans le contrat + `programmer_relance` (APScheduler) + arbitrage « doublon confirmé, non
fusionné » (M2.12) + `calculer_score_lead` (scikit-learn) + routes `/api/crm/clients`, `/pipeline`,
`/tasks` en écriture T1/T2 avec approbation + sidecar EspoCRM optionnel branché via
`AdaptateurCRM.ecrire()` + import en lot + Client 360 complet.

### Phase 3 — analytique et coach de vente (dépend des phases 1 et 2)

M2.9 (coach de vente), M2.14 (références/affaires répétées), M2.15 (prévisions, DuckDB), attribution
M2.10 → M7, écrans mobiles Vendeur/Client natifs une fois la décision d'app (phase 2 MOBILE.md)
amorcée et l'API stabilisée.

---

## 5. Risques et points ouverts

1. **Persistance absente — risque le plus élevé.** `Registre` est une liste Python en mémoire, dans
   un singleton module-level (`_registre` dans `outils.py`). Le principe « historique jamais écrasé »
   est prouvé **à l'intérieur d'un même processus** (registre.py, 32 tests), mais **tout redémarrage
   efface tout**. En l'état, M2 ne peut pas tourner en production. La migration Postgres est déjà
   conçue par `docs/research/R6-m1-m2.md` §5 (même interface, zéro changement dans la logique métier)
   mais non commencée — tâche 7 de la phase 1.
2. **Concurrence non traitée.** Le même singleton en mémoire, sans verrou, ne supporte pas des appels
   d'outils concurrents une fois exposé en serveur MCP réel. La migration Postgres (point 1) résout
   les deux problèmes ensemble via les transactions de la base.
3. **Loi 25 / opt-in.** Le contrat `LeadQualifie` ne porte **aucun champ de consentement**. Les
   relances futures (M2.7) ne doivent jamais s'activer avant qu'un champ de consentement explicite
   existe dans le modèle — sans quoi la règle dure « opt-in respecté » (§7 M2) est invérifiable par
   construction. À traiter comme préalable bloquant de la phase 2, pas comme un détail
   d'implémentation.
4. **Fusion jamais automatique — tenue, mais incomplète.** La garantie est architecturale (aucune
   fonction de fusion n'existe dans l'arbre du module, prouvé par lecture intégrale des 15 fichiers) :
   c'est le bon choix et il ne doit pas bouger. Mais l'absence symétrique d'un chemin « doublon confirmé
   (lien conservé, deux historiques intacts) » laisse un humain qui a vraiment identifié un doublon sans
   action possible autre que laisser le signalement en attente indéfiniment. À combler en phase 2, sans
   jamais introduire de fusion réelle des données.
5. **Incohérence mobile.** DEFINITION-PRODUIT §9 exige des écrans natifs par profil (admin, employé,
   **vendeur**, client), hors ligne d'abord. `docs/architecture/MOBILE.md` prévoit une app OpenClaw en
   nœud, phase 1 sans écran natif, et une phase 2 qui ne liste que Patron/Estimateur/Chef
   d'équipe/Réception — sans Vendeur ni Client. Cette incohérence (point ouvert n° 9 de
   DEFINITION-PRODUIT §13) doit être tranchée avant toute tâche d'écran mobile M2 ; elle ne bloque pas
   la phase 1 de ce plan (API d'abord).
6. **Bus d'événements inexistant au niveau OPSYS-CORE.** Le principe fondateur « les départements se
   parlent par événements » n'a aucune implémentation technique observée, ni pour M2 ni pour les
   départements voisins inspectés (M1, M3). Le câblage proposé en phase 1 (tâches 1 et 2) est un appel
   direct d'outil à outil, pas un bus : suffisant pour prouver le flux, pas une solution générale à
   dix départements. Sujet à traiter au niveau architecture, hors du seul M2.
7. **Dette de duplication M1/M2 assumée.** `encodage.py`, `horodatage.py`, `registre.py` sont
   dupliqués depuis M1 par décision explicite (empreintes SHA256 gelées + suite de conformité
   rejouée dans `test_conformite_m1.py`), pas par accident. Bien géré aujourd'hui ; toute correction
   future d'un bogue commun devra être répercutée consciemment des deux côtés, sans quoi la CI
   échouera d'elle-même (comportement voulu).
8. **Lint des départements hors gate CI.** `ruff check src tests` (le gate réel de `AGENTS.md`) ne
   scanne pas `departments/`. Les 134 signalements relevés dans `m02-revenue-crm` (cosmétiques)
   passent aujourd'hui inaperçus de la CI. À clarifier : élargir le gate ou documenter explicitement
   que les départements ont leur propre gate à définir.
9. **Licence Twenty à revérifier avant toute décision.** Le fichier `LICENSE` du dépôt a été retouché
   le 30-07-2026 (« clarify application licensing and add trademark policy »). Le verdict actuel
   (inspiration seulement, jamais vendorisé) tient quel que soit le résultat, mais toute décision
   d'adoption même en sidecar doit relire ce fichier à ce moment-là, pas se fier à ce rapport.
10. **Portée SaaS multi-tenant.** `ARCHITECTURE.md` pose « une installation = une entreprise = un
    VPS » : le singleton actuel est cohérent avec ce principe mono-tenant. Si l'ambition SaaS
    multi-instances de DEFINITION-PRODUIT §1 se précise, l'isolation entre clients (mentionnée comme
    garde-fou recommandé en §14) devra être vérifiée au moment de la migration Postgres, pas supposée
    acquise.

---

PREUVE:
- Fichier écrit : `docs/departements/M2-audit.md` (ce fichier), aucun autre fichier du dépôt modifié.
- Commande de démonstration exigée par le mandat, exécutée telle quelle :
  `/opt/opsys-venv/bin/python -m pytest departments/m02-revenue-crm/tests -q --import-mode=importlib -p no:cacheprovider`
  → 559 tests collectés (confirmé par `--collect-only -q`, somme des 11 fichiers), 559 passés, exit
  code 0, aucun échec, aucun skip.
- Commandes complémentaires exécutées en lecture/diagnostic seul (aucune écriture, aucune
  installation de brique) : `find`/`wc -l` sur `departments/m02-revenue-crm` (2 064 lignes src, 15
  modules) ; `grep` exhaustifs pour `api/crm`, `fastapi/Flask`, `kanban`, `evenement/event_bus`,
  `m2_ingerer_lead` (côté M1), `readiness`/`verifier_marqueur` (côté M3) — tous confirmant des
  absences réelles, pas de simples suppositions ; `git log` (un seul commit dans tout le dépôt) ;
  `ruff check` (racine vert, département 134 signalements cosmétiques) — cité en §1.1 et §5.8 comme
  preuve complémentaire au mandat, sans modification de fichier ; recherches web datées (Firecrawl)
  pour Splink (5.0.0dev5, 18-09-2026), EspoCRM (10.0.8, 08-09-2026), Twenty (v2.41.0, LICENSE modifié
  30-07-2026), recordlinkage (dernier commit 20-07-2023) — sources citées en §3.
- Aucune brique tierce installée ou exécutée ; toutes les licences citées en §3 proviennent des
  fichiers `LICENSE` déjà vérifiés dans `docs/research/R6-m1-m2.md`/`INGREDIENTS.md`, recoupés en
  direct pour la fraîcheur des versions.
