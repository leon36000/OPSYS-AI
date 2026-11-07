# M6 — audit initial Quadruple A, état réel du dépôt

Audit du 27 octobre 2026, source `9c4df1d10524191b39070123a5f866f337a5033f`.
Statut : PARTIAL. Cet audit complète les audits ciblés existants; il ne remplace pas leurs
preuves ni ne transforme l’état connu de juin (STUB) en qualification de production.

## Objectif, pourquoi et périmètre

Retrouver les capacités réelles avant de poursuivre CRM-14, afin de préparer les listes de prix
fournisseurs sans contourner le livre M6, réévaluer les devis historiques ou engager un achat.
Données fictives seulement; aucune nouvelle connexion de courriel ou donnée d’entreprise lue.

## Réponses à l’audit demandé

| Question | Constat sourcé |
|---|---|
| Où est M6? | `departments/m06-material-control`, manifeste `department.yaml`, module `m6_material_control.outils`, mode ombre. Ancien chemin `grs_api/modules/module6_inventory` non utilisé ici. |
| Fichiers inventaire? | Propriétaires `stock.py`, `materiel.py`, `reservations.py`, `emplacements.py`, `reception.py`, `variance_chantier.py`, `reapprovisionnement.py`, `bons_commande.py`; `outils.py` adapte stockage/événements/permissions. |
| Routes? | Console existante `/crm/materiaux`, `/crm/fournisseurs`, formulaires `/crm/materiaux/{id}/tarifs` et GET `/crm/materiaux/{id}/tarifs/historique`. Les outils privés sont raccordés dans `src/opsys/console/metier.py`; la liste `/api/inventory` du prompt n’est pas une preuve de routes déployées. |
| Tables? | Journaux persistés par `opsys.stockage`/`REGISTRES`, pas des tables transactionnelles PostgreSQL dédiées attestées par cette tranche. SQLite privé qualifié; PostgreSQL du nouveau flux non qualifié. |
| Catalogue? | `catalogue_materiaux.py` et `catalogue_console.py` : fiches versionnées, unité immuable, saisie admin privée. |
| Fournisseurs? | `fournisseurs.py`, `fournisseurs_console.py` et console. Gentek/Royal/O.A.M./Kaycan sont des fournisseurs connus du besoin; aucun contact, stock ou tarif réel n’est prérempli sur cette base. Fixtures Gentek présentes, pas preuve de fiches production. |
| Livre de prix? | `livre_prix.py`, saisie comparée `prix_console.py`, sélection M3 `tarif_soumission.py`, historique propriétaire et port privé. Prix fournis, pas inventés. |
| PO? | `bons_commande.py`, outils et tests `test_outils_po.py`. Brouillon/approbation/corps de courriel distincts de l’engagement externe. |
| Réception? | `reception.py`, réceptions cumulées/partielles et événements; tests dédiés existants. Pas de nouvelle qualification réception dans ce lot. |
| Sortie terrain? | `materiel.py`, consommation issue du WCT M4, tests de fin de chantier et durcissement. Formulaire mobile complet non démontré ici. |
| M3? | Le manifeste consomme `m3.devis_accepte` et `m3.besoins_materiaux`; propriétaires `besoins_materiaux_recus.py`, `besoins_prevus.py`. |
| M4 completion? | `m4.travaux_termines` consommé; stock/réserve/readiness gardent leur propre autorité. Aucune reconstruction M4. |
| M5? | `m6.reception_enregistree` et tests `test_frontiere_finance_m5.py`; M6 ne paie pas. Pas de comptabilité réelle vérifiée par cet audit. |
| Dashboard/mobile? | Cockpit admin catalogue/fournisseurs/tarifs et historique HTTP qualifiés localement. L’application mobile reste une phase ultérieure; pas de nouvelle preuve mobile ici. |
| Variance? | `variance.py`, `variance_chantier.py`, seuils explicites du manifeste; écarts neutres et contexte. |
| Alertes admin? | Digest, signaux de variance/prix et réapprovisionnement; pas d’accusation automatique ni achat déclenché. Leur couverture complète d’interface reste à qualifier. |
| Tests? | Tests départementaux de stock, réception, PO, réservations, finance, registre, prix et fournisseurs. Dernière tranche historique : 61 PASS dont 29 cas HTTP, plus preuves compatibles référencées dans l’audit dédié, sans addition. Aucun nouveau E2E global exécuté par cet audit. |
| Risques? | Prix sans source, unités/devise ambiguës, substitutions de fournisseur, import partiel, doublons, source périmée, double confirmation, confusion date commerciale/réception et exposition de contacts. |
| Phase minimale? | Préparation pure d’un lot de tarifs depuis lignes explicitement mappées et source binaire bornée; puis aperçu privé, mapping documenté et confirmation contrôlée par les ports existants. |

## Architecture, workflows et mémoire

M3 fournit le prévu, M4 le réel, M6 conserve matériaux/réservations/mouvements, M5 reçoit les
faits financiers, M8/M9 exploitent les signaux et M10 garde les références. Les détails et tests
exacts restent dans les audits ciblés du dossier. Le nouveau candidat d’import ne modifie aucun
journal. La future confirmation devra conserver le CAS, la réception idempotente, l’audit et les
références M10 de `prix_console.py`/`src/opsys/receptions_tarifs.py`.

Préflight M10 exécuté dans une instance de développement privée vide, sous identité fictive
admin SQL : résultat conservé hors Source dans `price-import-m10-preflight-v1-CONTEXT.json`.
Cela n’interroge pas la mémoire d’affaires/production et ne prouve pas l’absence de contexte
projet antérieur. Le contrat M10 versionné et les directives actuelles ont aussi été relus.

## Réévaluation du 7 novembre 2026

L’audit du 27 octobre reste une photographie historique. La présente réévaluation part de la
branche `claude/ligne-architecte` à `8137881a07e4795cbb86a45097772955cad656a7` et du
[README M6](../../../departments/m06-material-control/README.md), sans changer les règles ni les
données de M6.

| Sujet | Preuve actuelle et limite |
|---|---|
| Bons de commande et prix | `bons_commande.py`, `po_lecture.py`, `cout_sortie.py` et `commande_courriel_outils.py` couvrent les lignes avec unités, le facteur de perte déclaré, les PO par fournisseur, la lecture admin et le coût de sortie par source. Le courriel reste un brouillon/flux M1 éprouvé sur double; il n’y a pas de commande réelle fournisseur qualifiée. |
| Fournisseurs initiaux | `fournisseurs_a_fournir.py` nomme Gentek, Royal Solution de Bâtiment, O.A.M. et Kaycan comme données à fournir. Aucune adresse de commande, condition, grille tarifaire ou délai réel n’est déduit de leur nom. |
| Réception, stock et terrain | `details_reception.py`, `emplacements.py`, `materiel.py`, `variance_chantier.py`, `achats_terrain.py` et `ajustements.py` portent les parcours locaux et leur audit. Le formulaire employé existe dans `mobile/app/(employee)/job/[id]/materials.tsx` et l’écran stock admin dans `mobile/app/(admin)/stock.tsx`. Leur présence et leurs tests ne prouvent pas une exécution sur téléphone réel. |
| Réglages et alertes | `seuils_variance.py`, `alertes_approvisionnement.py`, `reorder.py` et la console `seuils_materiaux_ui.py` existent. Les seuils, planchers et catégories sont des décisions de direction non remplies par défaut; les valeurs proposées par agent ne sont pas des paramètres approuvés. Les alertes restent neutres, sans accusation d’employé. |
| Jonctions | Le code reçoit M3 (`m3.besoins_materiaux`), M4 (`m4.travaux_termines`), publie des faits de réception et de coût pour M5, des constats de disponibilité pour M8, des signaux lus par M9 et des références/événements pour M10. Chaque jonction doit encore être qualifiée dans un E2E unique avec données fictives avant de conclure au critère « estimation → finance ». |
| Tests rejoués | `tests/test_m6_scenario_sortie_article_po.py`, `tests/test_console_commandes_m6.py` et `tests/test_console_m6_intention_reconciliation.py` : **46 tests passés** le 7 novembre 2026 avec `OPSYS_HOME` isolé. Cette sélection ne qualifie ni PostgreSQL, ni fournisseur réel, ni appareil mobile natif. |

Le risque de rejeu d’une intention mobile après perte de l’identité d’appareil reste **conditionnel** :
le dépôt ne prouve pas que l’outbox SQLite survive à une réinitialisation qui efface SecureStore.
La politique de rapprochement ne doit pas être élargie sur cette seule hypothèse.

**Patch minimal suivant :** construire et rejouer un E2E fictif d’un seul tenant M3 → besoin M6 →
PO approuvé → courriel M1 sur double → réception partielle → fin M4 et usage mobile → variance et
revue admin → coût M5 → constats M8/M9 → mémoire M10. Ajouter les contre-épreuves de rejeu et de
permissions. Les contacts, prix, formats de commande et conditions réels des quatre fournisseurs
doivent venir de sources fournies et datées avant tout envoi réel.

## Permissions, gates Nathan et suites

Aucun outil/droit nouveau. Préparer un candidat est réversible et sans engagement. Envoi réel
fournisseur, import officiel sous politique/validation, ajustement de stock, données réelles,
nouvelle source, paiement et déploiement gardent leurs gates. La mise à jour automatique à
réception des listes de prix reste l’objectif; aucun format PDF/XLSX/CSV fournisseur n’est
supposé. Ce document et le prochain contrat ne déclarent ni M6 ni OPSYS complet.

La directive d’autonomie plus récente de Nathan cible une confirmation administrateur pour les
**commandes de matériel**, les paiements et les dépôts de paie. Les autres gates énumérés dans
l’audit historique décrivent le code de l’époque; ils doivent être revus par action et testés
avant d’être retirés. Le présent audit ne change aucune permission.
