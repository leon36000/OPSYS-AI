# Audit M6 — Material Control

**Date :** 28 septembre 2026. **Auditeur :** agent d'audit (lecture seule + recherche web, aucun
code tiers exécuté). **Source de vérité produit :** `docs/produit/DEFINITION-PRODUIT.md` §1, §5,
§6, §7 (M6), §8, §9.3/9.5/9.7, §10, §13.10. **Règles du dépôt :** `AGENTS.md`,
`docs/architecture/ARCHITECTURE.md`, `docs/architecture/DEPARTEMENTS.md` (référence vivante :
`departments/m03-estimation/`).

## 0. Méthode

Lu : les 4 fichiers ci-dessus, `departments/m06-material-control/` en entier (16 modules `src/`,
2 086 lignes ; 18 fichiers `tests/`, 3 627 lignes ; 3 `SKILL.md` ; `README.md`, `SOUL.md`,
`department.yaml`, les 3 documents BMAD — brief, PRD, architecture, 1 257 lignes), le noyau
`src/opsys/` pertinent (`departements.py`, `approbations.py`, `console/application.py`,
`tableau_de_bord.py`, `memoire/`), `docs/architecture/MOBILE.md`, `docs/research/R8-m5-m6.md`,
`docs/research/INGREDIENTS.md`. Vérifié par recherche web : licences et fraîcheur d'InvenTree et
d'ERPNext (recoupement avec R8, daté d'aujourd'hui). Exécuté uniquement la commande autorisée
(résultat en fin de document). Aucun autre fichier que celui-ci n'a été modifié.

## 1. Verdict global

L'état déclaré par le produit (`STUB`, « thin, à concevoir ») est **dépassé par les faits** : un
noyau métier réel, pur et testé existe déjà (158 tests verts), construit selon le même patron que
M3/M4/M5 (fonctions pures, registre append-only hash-chaîné, contrats gelés, conformité AST). Mais
ce noyau couvre une **tranche étroite** de M6 : réception → stock → consommation → comptage →
digest, sur un registre **entièrement en mémoire, rejoué par l'appelant à chaque appel** (aucune
base de données). Il n'existe **aucun** fournisseur, **aucun** bon de commande persistant avec
statuts, **aucune** consommation du besoin matériaux de M3, **aucun** emplacement hors
`chantier_id`, **aucune** réservation, **aucune** alerte, **aucun** pont M8/M9/M10, **aucune** API
ni écran spécifiques à M6. Le § 3 détaille chaque écart ; le constat central est que **la
persistance elle-même est le prérequis bloquant** avant toute tranche verticale crédible (§5,
Phase 0).

## 2. Inventaire M6.1 – M6.21

| # | Fonction | Statut | Fichiers | Preuve |
|---|---|---|---|---|
| M6.1 | Catalogue de matériaux (SKU) | **PARTIEL** | `catalogue.py` (28 l.), `contrats.py` | `test_catalogue.py`. Contrat gelé `CatalogueMateriaux` = `{version, unite_monetaire, postes:{cout_unitaire, libelle}}` (PRD §5.3) : ni catégorie, ni fournisseur principal/alternatif, ni unité/couleur/dimension, ni compatibilité/substitution. |
| M6.2 | Registre des fournisseurs | **ABSENT** | — | Aucun fichier, aucune entité fournisseur dans le code. `BonDeCommandeDemande` lui-même (contrat gelé, `03-ARCHITECTURE.md` §2.4) n'a **aucun champ fournisseur**. Gentek/Royal/O.A.M./Kaycan n'existent que dans la doc produit. |
| M6.3 | Livre de prix (source) | **PARTIEL** | `catalogue.py` | `test_catalogue.py`. Résolution `PRIX_CATALOGUE → PRIX_HISTORIQUE_FALLBACK (dernier RECEPTION) → INDETERMINE` : couvre l'esprit d'`ESTIMATED`/`FALLBACK_PRICE_BOOK` mais avec un **vocabulaire différent** de celui du produit (à trancher : renommer ou documenter l'équivalence — un renommage touche 16 modules). Pas d'historique de hausses ni de lien explicite facture/PO. |
| M6.4 | Besoins matériaux depuis M3 | **ABSENT** | — | 0 résultat pour `materiau` dans `departments/m03-estimation/src/`. Ni contrat, ni fonction des deux côtés. |
| M6.5 | Moteur de PO (12 statuts) | **ABSENT** | — | Décision d'architecture **DA-M6-12** (`03-ARCHITECTURE.md` l.416-420) : *« M6 ne persiste PAS les BonDeCommandeDemande »*. Seuls 2 objets éphémères (`bon_demande`, `reception_po`) sont fournis en un seul appel de réception. Aucun statut, aucune approbation distincte, aucune persistance. |
| M6.6 | Commande par courriel via M1 | **ABSENT** | — | Aucune référence à M1 dans `m6_material_control`. |
| M6.7 | Réception et entrée en stock | **PARTIEL** | `reception.py`, `materiel.enregistrer_reception` | `test_reception.py`, `test_materiel_reception_et_comptage.py`, `test_outils_agent.py` (verdicts `CONFORME`/`INFERIEURE`/`SUPERIEURE`/`MIXTE` verts). Manquent : substitution, dommage/photo, dépôt vs chantier vs ramassage. |
| M6.8 | Réservation par chantier | **ABSENT** | — | Aucune notion réservé/disponible ; le « stock » est le solde net signé du registre (`stock.deriver_stock_theorique`). Pas de garde anti double-réservation. |
| M6.9 | Emplacements de stock | **ABSENT** | — | Seul `chantier_id` existe comme localisation. Aucun enum dépôt/camion/remorque/employé/fournisseur/retour/rebut, aucun transfert audité entre emplacements. |
| M6.10 | Formulaire mobile matériaux utilisés | **PARTIEL** | `materiel.consommer_materiaux`, skill `consommer-du-materiel-terrain` | `test_materiel.py`, `test_materiel_durcissement.py`. Contrat ne porte que `{materiau_id, quantite}` : pas d'item non prévu + raison, pas de retour/perte/bris/achat terrain distincts, pas de photo/reçu, pas de brouillon. **Aucun écran mobile** — `MOBILE.md` Phase 1 ne mentionne même pas M6. |
| M6.11 | Validation des sorties | **PARTIEL** | `stock.verifier_disponibilite_consommation` | `test_stock.py` (fail-closed, jamais négatif). Manque : comparaison à une liste prévue, cohérence d'unité, retours/pertes/bris comme types distincts, achat terrain, photo/reçu. |
| M6.12 | Variance estimé vs réel | **PARTIEL — mauvaise variance** | `variance.py` | `test_variance.py`. **Nuance importante** : compare un **comptage physique** au **stock théorique du registre** (audit d'inventaire), **pas** l'estimé M3 vs le consommé réel M4 à la clôture d'un chantier que §6/§9.7 décrivent. Aucune des 6 causes nommées (`estimation_error`/`field_change`/`waste`/`breakage`/`data_entry_error`/`unexplained_usage`) n'existe dans le code ; aucun lien vers `completed_pending_review` de M4. |
| M6.13 | Alertes perte/gaspillage/bris | **ABSENT** | — | Aucun des 7 déclencheurs de §7 (usage au-dessus d'un seuil, matériau cher sans estimation, pertes répétées par équipe, stock négatif, ajustements fréquents, commande reçue mais stock disparu, chantier fermé sans usage) n'est câblé. |
| M6.14 | Ajustements et piste d'audit | **PARTIEL** | `registre.py`, `encodage.py` | `test_registre.py` (chaîne hash validée, altération détectée). La **primitive** d'audit est solide, mais la **fonctionnalité** « ajustement » (acteur, raison, preuve, approbation, types perte/bris/retour/stock retrouvé/erreur de saisie/transfert/annulation) est **explicitement repoussée** (`03-ARCHITECTURE.md` §7.2 : *« correction du stock théorique = décision humaine, hors v1 »*). |
| M6.15 | Réapprovisionnement | **PARTIEL** | `reorder.py` | `test_reorder.py`. Seuil fixe fourni par l'appelant, silence si absent, garde AST anti-PO (`conformite.garde_ecriture_stock`, CA-M6-18) — bonne garantie structurelle. Manque : réservé/disponible, chantiers à venir (M4), besoins (M3), délai fournisseur, saison, prix, score de rupture. |
| M6.16 | Pont finance vers M5 | **PARTIEL** | `contrats_sortie.montant_decimal_a_la_frontiere` | `test_frontiere_finance_m5.py` — **preuve croisée réelle** : appelle le vrai `m5_financecore.validation` (import de test seulement, #109 respecté), prouve la conversion float→Decimal sûre. Aucun canal de **retour** M5→M6 (statut AP, coût validé, rapprochement). |
| M6.17 | Achats imprévus sur le terrain | **ABSENT** | — | Aucun concept d'achat terrain (fournisseur, montant, item, raison, photo, approbation). |
| M6.18 | Tableau de bord + mobile admin | **ABSENT** | — | `src/opsys/console/application.py` (FastAPI) n'expose que des routes génériques (`/departements`, `/approbations`, `/budgets`, `/modeles`) communes à tous les départements. Aucune route ni écran spécifique à M6. |
| M6.19 | Pont analytique M8 | **ABSENT** | — | `department.yaml` ne déclare que 2 KPI (`taux_reception_conforme`, `taux_prix_indetermine`). Aucun des 11 signaux nommés en §7 (`stockout_count`, `stock_value`, `reorder_recommendations`, `purchase_requests`, `supplier_price_change_rate`, `material_variance`, `inventory_accuracy`, `high_variance_jobs`, `material_waste_rate`, délai des PO, fiabilité fournisseurs) n'est calculé. |
| M6.20 | Signaux stratégiques M9 | **ABSENT** | — | Rien. |
| M6.21 | Mémoire M10 | **PARTIEL — déclaratif seul** | `department.yaml` (`memoire.lecture/ecriture`) | Le manifeste déclare les portées ; **aucun appel réel** vers `src/opsys/memoire/` depuis `m6_material_control`. M10 lui-même reste `STUB` côté produit — rien à écrire de fiable en face pour l'instant. |

**Hors numérotation, présent et solide :** 5 outils d'agent (`outils.py`, 295 l.) bien scopés en
autonomie (`m6_receptionner_commande`/`m6_consommer_materiaux`/`m6_soumettre_comptage` = T1 ;
`m6_produire_digest`/`m6_resoudre_prix_materiau` = T0), 3 skills, conformité statique AST propre au
paquet (`conformite.py`, 751 l., garde l'unicité du point d'écriture par type de mouvement et le
non-recalcul du hash WCT).

## 3. Écarts détaillés

### 3.1 Modèle de données

**Persistance — le trou structurel n°1.** `Registre` (`registre.py`) garde ses maillons dans une
liste Python en mémoire ; il n'existe **aucune** implémentation Postgres. Chaque outil agent
(`outils.py`) reçoit un `registre_historique` fourni par l'appelant, le rejoue pour reconstruire un
registre valide, puis renvoie l'historique complet mis à jour — **la conversation de l'agent est la
seule mémoire du stock entre deux appels.** C'est viable pour une démonstration en un seul tour,
mais incompatible avec : un PO dont l'approbation admin arrive des heures/jours plus tard, un stock
qui doit survivre entre deux conversations, une réception faite par un autre agent/canal que celui
qui a créé le PO. `psycopg[binary]` est déjà une dépendance optionnelle du projet (`pyproject.toml`,
extra `postgres`) mais **aucun département** (M3/M5/M6) ne l'utilise encore : c'est un problème
transversal, pas propre à M6, mais M6 ne peut pas construire de PO réel sans le résoudre en premier.

**Catalogue/SKU.** Contrat gelé minimal (§2 ci-dessus). Pas de catégories du §7 (gouttières,
descentes, coins, coudes, fascia, soffite, revêtement, moulures, membrane, vis, scellant,
accessoires, consommables, outils, équipements, matériaux spéciaux).

**Fournisseurs.** Absent à 100 %. `BonDeCommandeDemande` n'a pas de champ `fournisseur_id` — même
la structure de données la plus minimale pour un PO ne référence aucun fournisseur aujourd'hui.

**PO et ses 12 statuts.** Absent par décision d'architecture explicite (DA-M6-12), motivée à
l'époque par l'absence totale de persistance et par l'énuméré `type_mouvement` gelé qui ne porte
pas de valeur `PO_DEMANDE`. Cette décision doit être **révisée**, pas supprimée : le registre de
mouvements de stock (RECEPTION/CONSOMMATION/VARIANCE_INVENTAIRE) reste juste ; un **PO est un objet
différent avec son propre cycle de vie**, pas un mouvement de stock — il lui faut sa propre table
et sa propre machine à états, hors du registre append-only actuel.

**Réceptions/emplacements/réservations/sorties/retours/pertes.** Réceptions : voir M6.7. Le reste :
absent (M6.8/M6.9), sauf les sorties de base (M6.10/M6.11, partielles).

**Ajustements audités.** La primitive (registre hash-chaîné) existe et est testée
(`test_registre.py` détecte toute altération) ; la fonctionnalité (raison, acteur, preuve,
approbation) est un développement complet à faire (M6.14).

**Variance et causes.** Deux moteurs sont nécessaires et **ne doivent pas être confondus** :
(a) `variance.py` existant = comptage physique vs stock théorique (déjà fait, bien testé) ;
(b) variance de chantier = estimé M3 vs consommé réel M4, avec les 6 causes nommées (absent,
M6.12). Les nommer clairement dès la conception (`variance_inventaire.py` vs `variance_chantier.py`)
pour ne jamais les fusionner par erreur.

### 3.2 API

Il n'existe **aucune API HTTP propre à M6**. Le seul accès programmable est le serveur MCP générique
(`src/opsys/serveur_mcp.py`, point d'accès `/mcp/<département>` par département, ARCHITECTURE.md),
qui expose les 5 outils d'`outils.py` aux agents — pas aux écrans. Le dashboard web (Console OPSYS,
FastAPI) n'a que des routes génériques de département (mode, budget, approbations), aucune route
`/api/m6/...` pour stock, PO, écarts ou fournisseurs. La décision n°2 de l'ingénieur en chef (« les
moteurs métier … exposés … à l'app/dashboard par API ») n'est **pas encore réalisée** pour M6.

### 3.3 Événements (flux §6)

| Lien | Statut | Constat |
|---|---|---|
| M3 → M6 (besoins matériaux) | **ABSENT** | Rien des deux côtés (§3.1). |
| M6 → M3/M4 (dispo, coût, fournisseur, délai) | **ABSENT** | Rien à renvoyer, faute d'intake. |
| M4 → M6 (WCT, travaux terminés) | **PRÉSENT côté contrat, non testé en croisé** | `contrats.CHAMPS_WCT` mirore exactement les 12 clés de `m4_field_ops/outbox.py` (copie-adaptation, décision #109) ; `validation.valider_wct` vérifie `"M6" in consommateurs_cibles` et ne recalcule jamais `hash_maillon`. **Aucun test n'importe réellement les deux paquets ensemble** (seul `test_frontiere_finance_m5.py` le fait, pour M5) — une dérive du contrat côté M4 ne casserait aucun test M6 avant la production. |
| M6 → M5 (PO, réception, écart de prix) | **PARTIEL, testé en croisé** | `SignalPoAPayer` + conversion Decimal, prouvés contre le vrai validateur M5 (`test_frontiere_finance_m5.py`). |
| M5 → M6 (AP, statut paiement, coût validé, rapprochement) | **ABSENT** | Aucun canal de retour. |
| M1 ↔ M6 (envoi/réponse fournisseur) | **ABSENT** | Rien. |
| Cascade « travaux terminés » (§6/§9.7, étape 5) | **ABSENT** | Aucun mécanisme M6 ne peut faire basculer un statut de chantier M4 vers `completed_pending_review` ; le signal d'écart critique qui devrait le déclencher n'existe pas (M6.12/M6.13). |

### 3.4 Outils d'agent

Présents et bien conçus pour leur périmètre (§2, note « hors numérotation »). Manquants pour couvrir
le flux complet : `m6_evaluer_besoin_m3`, `m6_creer_po_brouillon`, `m6_approuver_po`,
`m6_marquer_po_envoye`/`m6_confirmer_fournisseur`, `m6_enregistrer_achat_terrain`,
`m6_soumettre_ajustement` (avec approbation), `m6_evaluer_variance_chantier`. Chacun doit recevoir
une autonomie T0–T3 explicite **dès sa création** (le département est en mode `ombre` : tout T1+
part aujourd'hui en approbation, ce qui est le bon défaut pour un PO ou un ajustement).

### 3.5 Formulaire mobile des matériaux utilisés et écrans admin (§9)

Backend partiel (M6.10/M6.11), **zéro écran**. `docs/architecture/MOBILE.md` Phase 1 (app OpenClaw
officielle, sans développement) ne liste que M3 (photos), M4 (pointage) et M1 (vocal) — **M6 est
absent de son propre tableau Phase 1**, alors que §9.3 en fait un besoin immédiat (« à Travaux
terminés, l'app ouvre le formulaire de matériaux utilisés »). Phase 2 (fork rebrandé) ne liste que 4
profils d'écrans (Patron, Estimateur, Chef d'équipe, Réception) sans écran « matériaux »/« inventaire »
explicite. Écrans admin attendus par §9.5 (PO à approuver, écarts, stock critique, réception rapide,
validation d'usage, rapport pertes/bris) : aucun.

### 3.6 Tableau de bord

Console générique seulement (§3.2). Aucun des éléments listés en §7 M6 (« stock critique, commandes
en attente, PO à approuver et envoyés, réceptions partielles, écarts importants, pertes et bris,
chantiers sans matériel prêt, fournisseurs en retard, hausses de prix, stock réservé/disponible,
variance par équipe/chantier/service ») n'a d'écran ni d'API pour l'alimenter.

### 3.7 Portes de politique et replis

| Porte | État |
|---|---|
| Envoi réel d'une commande à un fournisseur | Correctement bloquée (aucun outil n'envoie) — mais le **repli manuel documenté** exigé par §10 et le point ouvert §13.10 du produit **n'est écrit nulle part** dans `README.md`/`SOUL.md`/les skills M6. À corriger avant T1.9 (§5). |
| Ajustements de stock critiques | Repoussée par design (`03-ARCHITECTURE.md` DA-M6-15/§7.2) ; la file d'approbation générique (`src/opsys/approbations.py`, SQLite, rejoue les arguments exacts) existe déjà côté Core et est réutilisable, mais aucun outil « ajustement » ne l'invoque encore. |
| Achats terrain | Aucun outil, donc aucune porte à documenter pour l'instant. |
| OCR/vision sur factures, parsing courriel par LLM, intégration bancaire/paiement réel | **Correctement** classées GATED/T3 (DA-M6-15), cohérent avec P10 du produit. |

### 3.8 E2E exigés (mission)

| Scénario | État |
|---|---|
| Estimation → PO Gentek → approbation | **ABSENT** — bloqué par M6.2/M6.4/M6.5 (aucun fournisseur, aucun intake M3, aucun PO persistant). |
| Réception partielle | **PARTIEL** — le verdict `RECEPTION_INFERIEURE` est vert en test unitaire (`test_reception.py`, `test_outils_agent.py`), mais sans PO persisté en amont ce n'est pas un parcours de bout en bout, seulement un appel isolé. |
| Travaux terminés normaux | **PARTIEL** — le contrat WCT→consommation est mirroré et testé côté M6 seul (§3.3) ; pas de test croisé réel avec M4 ; formulaire mobile réduit à `{materiau_id, quantite}`. |
| Écart de 40 % | **PARTIEL, ambigu** — `variance.py` (comptage) n'a **aucun seuil de criticité** codé (toute variance non nulle est enregistrée, seuil de bruit explicitement hors v1) ; la variance de chantier (estimé/réel), seule pertinente pour « 40 % de plus que prévu », est absente (M6.12). |
| Risque de rupture | **PARTIEL** — `reorder.py` ne fait qu'un seuil binaire fourni par l'appelant, sans délai fournisseur, saisonnalité ni chantiers à venir. |

**Aucun des 5 scénarios n'est vert de bout en bout aujourd'hui.** Les 158 tests verts prouvent des
fonctions pures et des appels d'outil isolés, pas des parcours inter-départements.

## 4. Briques candidates

| Écart | Candidate | Licence (vérifiée) | Maturité | Verdict |
|---|---|---|---|---|
| Persistance du registre/PO | `psycopg[binary]` (déjà en dépendance optionnelle du projet, extra `postgres`) | **LGPL-3.0** — OK en dépendance dynamique (AGENTS.md) | Déjà dans `pyproject.toml`, inutilisé par aucun département | **Retenue** : écrire une classe `RegistrePostgres` qui implémente la même interface que `Registre` (`ajouter`/`ajouter_lot`/`lire`/`hash_tete`/`valider_chaine`) — les tests `test_registre.py` existants s'y rejouent sans changement (patron déjà recommandé par R8 §12.2). Pas de nouvelle brique externe à évaluer. |
| Modèle SKU/fournisseur/PO enrichi | [InvenTree](https://github.com/inventree/InvenTree) | **MIT** (vérifié GitHub + recoupé WebSearch : v0.23.2, 13 mai 2026 ; dépôt actif, dernier push fin août 2026) | Django, 7 600+★, très actif | **Retenue en référence de schéma seulement** (miner son modèle de données stock/fournisseur/PO/emplacement pour enrichir `CatalogueMateriaux` et le futur objet PO) — jamais en sidecar complet v1 : Django/son propre Postgres double la surface d'exploitation d'un mono-VPS et est incompatible avec le noyau stdlib pur de M6. |
| — (comparatif) | [ERPNext](https://github.com/frappe/erpnext) (module stock) | **GPL-3.0** (vérifié : v16.32.3, 18 août 2026, très actif) | Frappe/Python, 39 000+★ | **Écartée pour v1** : service séparé non modifié seulement (règle GPL d'AGENTS.md) ; framework Frappe entier incompatible avec le noyau stdlib ; redondante si InvenTree suffit comme référence de schéma. |
| Réapprovisionnement dynamique | [statsforecast](https://github.com/Nixtla/statsforecast) (Nixtla) / [Darts](https://github.com/unit8co/darts) (Unit8), déjà retenues R8/M5 | **Apache-2.0** (les deux, vérifiées R8) | statsforecast : 4 915★, push 2026-09-21 · Darts : 9 527★, push 2026-09-26 (très actif) | **Réutilisation, pas nouvelle brique** : consommer l'historique `CONSOMMATION` comme série temporelle pour affiner `SeuilReorder`, en restant une suggestion (garde AST CA-M6-18 étendue au nouveau chemin). Le point de commande simple (demande pendant délai + stock de sécurité) reste une **formule stdlib**, pas une dépendance — cohérent avec « le code calcule ». |
| OCR documents fournisseurs (factures, bordereaux) | [Docling](https://github.com/docling-project/docling) (déjà retenue R4/M10 pour l'ingestion RAG) | **MIT** (vérifié R4, `LICENSE` brut) | Active, LF AI & Data, exécution locale possible (Loi 25) | **Réutilisation** plutôt qu'une deuxième dépendance OCR : même brique pour M10 (RAG) et M6 (factures/bordereaux). Reste GATED/T3 tant que le poids GPU/modèle n'est pas budgété (DA-M6-15, cohérent). |
| Codes-barres/QR — génération serveur | [python-barcode](https://github.com/WhyNotHugo/python-barcode) + [python-qrcode](https://github.com/lincolnloop/python-qrcode), déjà retenues R8 | MIT / **BSD-3-Clause** (vérifiées R8) | python-barcode : 655★, push 2026-07-27 · python-qrcode : 4 944★, push 2026-03-25 | **Retenue**, dépendance pip directe, pour imprimer des étiquettes bacs/chantiers côté serveur si le repli « étiquette imprimée » est choisi. |
| Codes-barres/QR — scan mobile | `expo-camera` (scan intégré, remplace l'ancien `expo-barcode-scanner` déprécié) | Écosystème Expo, historiquement MIT — **licence du paquet non re-vérifiée fichier par fichier dans cette mission** | Actif, recommandation Expo 2026 | **Piste à confirmer avant adoption ferme** (vérifier `LICENSE` du paquet avant de l'ajouter à `INGREDIENTS.md`). Décoder côté client et n'envoyer que le texte décodé au backend M6 — évite une dépendance serveur de vision (pyzbar/zbar, LGPL-2.1) inutile ici (cohérent R8 §10). |
| Variance de chantier + causes nommées, alertes | — | — | — | **Aucune brique** : le produit interdit explicitement d'attribuer une cause automatiquement (R-020) — logique déterministe interne à écrire dans le même patron que `variance.py`/`materiel.py`, pas un package tiers. |

## 5. Plan par phases

### Phase 0 — Fondation de persistance (prérequis bloquant, hors PRD M6 v1 actuel)

1. `RegistrePostgres` : même interface que `Registre`, schéma SQL append-only (`index`,
   `hash_precedent`, `hash_maillon` inclus) — réutilise `test_registre.py` tel quel contre une base
   réelle. Petit, testable seul.
2. Table `bons_commande` (nouvelle, **distincte** du registre de mouvements de stock — un PO n'est
   pas un `type_mouvement`) : `po_id, chantier_id, fournisseur_id, statut, lignes, cree_le,
   modifie_le, hash_historique_statuts`. Petit, testable seul (CRUD + historique des transitions).

### Phase 1 — Tranche verticale (ordre du flux §6, tâches petites et testables)

1. Contrat `BesoinMaterielM3` (items, quantité estimée, unité, facteur de perte, confiance) +
   `besoins.valider_besoin` (fonction pure) — test nominal + refus de schéma.
2. `catalogue.py` : ajouter `categorie`, `fournisseur_principal`, `fournisseur_alternatif`, `unite`
   aux postes, en champs **optionnels rétrocompatibles** — test de non-régression sur
   `resoudre_prix` (les 158 tests actuels restent verts).
3. `fournisseurs.py` + table Postgres minimale (nom, courriel de commande, délai habituel,
   catégories vendues) ; fixtures Gentek/Royal Solution de Bâtiment/O.A.M./Kaycan **marquées
   `fictif: true`** (AGENTS.md). Outil `m6_lister_fournisseurs` (T0, lecture).
4. `m6_evaluer_besoin` : compare un `BesoinMaterielM3` au stock théorique du chantier, renvoie
   `DISPONIBLE`/`A_RESERVER`/`A_COMMANDER` par ligne — **aucun PO créé ici**.
5. Machine à états des 12 statuts (`draft → pending_admin_review → approved → email_ready →
   sent_to_supplier → supplier_confirmed → partially_received → received → closed`, branches
   `cancelled`/`disputed`/`invoiced`) : fonction pure `transition_autorisee(actuel, cible) -> bool`,
   table figée — test exhaustif des transitions autorisées/refusées (12×12).
6. `bons_commande.creer_brouillon` (T1, écrit `draft`) + outil `m6_creer_po_brouillon`.
7. Outil `m6_approuver_po` (T1, exige `approbateur` non vide, écrit `approved` — même exigence que
   F6/F7 de M5) ; en mode `ombre`, la file d'approbation générique du Core s'applique déjà.
8. Générateur de corps de courriel PO — **texte brut, aucune primitive d'envoi**, statut →
   `email_ready`. Documenter et coder le **repli manuel** (§3.7) dans `SOUL.md`/`README.md` en même
   temps que cette tâche, pas après.
9. Brancher `materiel.enregistrer_reception` sur un PO **persisté** (au lieu du `bon_demande`
   éphémère) : lit le PO par `po_id`, écrit `partially_received`/`received` selon le verdict déjà
   calculé par `reception.py` (réutilisé sans modification).
10. `m6_soumettre_materiaux_utilises` : contrat enrichi (lignes typées `prevu`/`non_prevu`/`retour`/
    `perte`/`bris`/`achat_terrain`, `photo_reçu_fourni: bool` obligatoire si `achat_terrain`) —
    étend `FormulaireConsommationMateriaux` sans casser `m6_consommer_materiaux`.
11. `variance_chantier.py` (nouveau module, **distinct** de `variance.py`) : estimé M3 vs déclaré
    réel, verdict neutre + `cause_possible` parmi les 6 valeurs nommées, jamais rempli seul
    (même discipline R-020 que `variance.py`).
12. Seuil de criticité configurable (ex. 40 %, paramètre du dashboard, jamais codé en dur) →
    `SignalVarianceChantierCritique`, consommé par M4 pour basculer en `completed_pending_review`
    (M6 émet le signal, ne modifie jamais le statut M4 lui-même — frontière respectée).
13. Digest quotidien étendu (`digest.py`) avec une section « écarts critiques » — réutilise le
    patron déjà vert, pas de nouveau moteur.
14. E2E Phase 1 : un test qui rejoue le scénario complet « estimation → PO Gentek → approbation »
    sur `RegistrePostgres`/table `bons_commande` de test (conteneur éphémère), du besoin M3 jusqu'au
    statut `approved`.

Chaque tâche est livrable et testable seule ; l'ordre respecte les dépendances (Phase 0 avant tout,
puis le flux §6 dans son ordre naturel).

## 6. Risques et points ouverts

- **Aucune accusation — respecté partout.** `variance.py`, les skills et `SOUL.md` sont cohérents
  avec R-020 ; à maintenir strictement dans `variance_chantier.py` (Phase 1, tâche 11) : jamais de
  `cause_possible` assignée automatiquement, jamais un nom d'employé lié à un écart par le système.
- **Piste d'audit incomplète au-delà du stock.** Le registre hash-chaîné protège les mouvements de
  stock ; la nouvelle table `bons_commande` (Phase 0) et les futurs ajustements (M6.14) doivent
  recevoir la même discipline (historique immuable, jamais un `UPDATE` qui efface l'état précédent)
  pour rester cohérents avec P3 (traçabilité totale) du produit.
- **Dépendance à M1 pour l'envoi des courriels, repli manuel non documenté.** Point ouvert §13.10 du
  produit, confirmé par l'audit : aucun document M6 ne décrit aujourd'hui la procédure quand M1
  n'est pas encore prêt à envoyer (admin copie-colle le texte généré, par exemple). À écrire dès la
  tâche 8 de la Phase 1, pas en aval.
- **Frontière Decimal/float bien gardée à un seul point.** `montant_decimal_a_la_frontiere` est
  testée contre le vrai M5, mais rien n'empêche un futur point de sortie (écran admin, export) de
  transmettre un `float` sans passer par cette fonction. À rappeler explicitement dans toute
  nouvelle tâche qui expose un montant M6 hors de son propre paquet.
- **Contrat WCT mirroré sans garde-fou automatique.** M4 et M6 gardent chacun leur copie des 12
  clés (décision #109, jamais d'import en production) ; seul un test manuel les recoupe pour
  l'instant, aucun test n'importe réellement les deux paquets ensemble (contrairement à M6→M5). Une
  dérive du contrat côté M4 ne casserait aucun test M6 avant la production — un test d'intégration
  croisé (comme `test_frontiere_finance_m5.py`, permis pour les tests) réduirait ce risque.
- **`MOBILE.md` ne liste encore aucun écran M6**, ni en Phase 1 (app officielle) ni en Phase 2 (fork)
  — à corriger dans la doc mobile en parallèle du code, sinon le premier employé qui cherche
  l'écran « matériaux utilisés » ne le trouve pas.
- **Nom commercial non tranché** (point ouvert §13.4 du produit : « Gouttières et Revêtements
  Synergy » vs « … Lanaudière » dans les anciens gabarits de courriel fournisseur) — à confirmer
  avant d'écrire un vrai gabarit de courriel PO (tâche 8).
- **Mode `ombre` à maintenir strictement** pour toute nouvelle capacité d'écriture (PO, ajustement,
  achat terrain) : assigner l'autonomie T0–T3 à la création de chaque outil, jamais en correction
  après coup — le patron actuel (`outils.py`) le fait déjà bien pour les 5 outils existants.
- **Licence `expo-camera` non re-vérifiée fichier par fichier** dans cette mission (§4) — à
  confirmer avant d'inscrire quoi que ce soit au sujet du scan mobile dans `INGREDIENTS.md`.

---

PREUVE: `/opt/opsys-venv/bin/python -m pytest departments/m06-material-control/tests -q
--import-mode=importlib -p no:cacheprovider` → **158 passed in 0.52s** (code de sortie 0, aucun
échec, aucune erreur). Lecture complète de `departments/m06-material-control/` (16 modules `src/`,
18 fichiers `tests/`, 3 `SKILL.md`, `README.md`, `SOUL.md`, `department.yaml`, 3 documents BMAD),
de `docs/produit/DEFINITION-PRODUIT.md` (intégral), de `docs/architecture/ARCHITECTURE.md`,
`docs/architecture/DEPARTEMENTS.md`, `docs/architecture/MOBILE.md`, `docs/research/R8-m5-m6.md`,
`docs/research/INGREDIENTS.md`, et des modules `src/opsys/` cités en §0/§3. Recherches web
exécutées : licence et fraîcheur InvenTree (MIT, v0.23.2 confirmée) et ERPNext (GPL-3.0-only,
v16.32.3 confirmée), état 2026 du scan de codes-barres/QR sous Expo. Aucun code tiers exécuté ;
aucun fichier modifié hors `docs/departements/M6-audit.md`.
