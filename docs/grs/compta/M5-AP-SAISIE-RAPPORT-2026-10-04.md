# Fusion AP → saisie humaine confirmée dans M5

4 octobre 2026 UTC — étape 20 de la reprise, sous-capacité M5.2. **M5 et OPSYS-AI restent PARTIEL.** Le code permet une saisie réelle dans le registre interne canonique ; il ne lance aucun paiement et ne constitue pas une écriture comptable finale. La qualification est ciblée et locale.

## Parcours et autorité

Le [brouillon fournisseur PDF/AP](../../architecture/FUSION-AP-BROUILLONS.md) conserve `A_REVOIR`. Une personne active, administrateur possédant aussi `finance` ou propriétaire `nathan_owner`, corrige ses champs, choisit explicitement un PO reçu et son fournisseur M5, puis atteste la correspondance. Ce mapping humain ne devient pas une résolution automatique ni une preuve de vérité de la facture.

| Action privée | Effet |
|---|---|
| `POST /fusion/pdf/lots/{lot_id}/ap/verifier-m5` | Observation des contrôles courants, sans facture ni dette ; produit le hash de commande et le formulaire de confirmation. |
| `POST /fusion/pdf/lots/{lot_id}/ap/saisir-m5` | Second envoi explicitement confirmé : crée une facture fournisseur `SAISIE` et sa référence de provenance ; renvoie `SAISIE_M5_REFERENCEE`. |

Le préfixe de console s’applique (`/opsys` par défaut). Sessions vivantes, CSRF, formulaire urlencoded limité à 16 Kio, champs fermés et uniques, absence de query, UUID/révisions/hash/clé de rejeu sont contrôlés. Le travail bloquant passe par le threadpool. La réponse privée est `no-store`, son HTML échappé et ses droits sont revérifiés avant rendu.

Le navigateur transmet les références, attestations et confirmation ; il ne fournit ni montant, taux, auteur ni date d’exécution. Le serveur reconstruit les six arguments métier depuis les champs chiffrés, crée l’horodatage et appelle l’outil existant `m5_saisir_facture_fournisseur` **T1/N3** via `approbations.creer_demande` puis `approbations.decider`. L’approbateur est la personne authentifiée courante. Aucun nouvel outil MCP, permission de paiement ou ouverture de la commande console générique n’est ajouté.

## Fraîcheur, transaction et provenance

Dans la transaction SQLite existante, le pont relit PDF/extraits/citations, révisions AP/PDF, configuration, registre AP et taux versionnés. Le hash de commande lie ce snapshot au PO et au fournisseur choisis ; une tête, révision ou source modifiée exige une nouvelle observation. Les montants sont des décimaux positionnels explicites et la devise `CAD` ; taxes imprimées et total sont comparés au calcul M5. L’outil utilise les mêmes octets fiscaux bornés, transmis par une option Python interne absente du schéma MCP et de l’approbation.

La chaîne AP est prébornée à 10 000 maillons, 8 Mio au total et 64 Kio par maillon ; taux limités à 64 Kio. Après exécution, le pont exige un unique append attendu, contrôle facture/acteur/arguments/montants/taxes, puis revalide les sources et l’autorité avant commit. Un refus métier ou une panne transactionnelle lève hors du répartiteur d’approbation et annule ensemble dette, approbation, réclamation/reçu idempotent et provenance. Une révocation **après** commit bloque le rendu du reçu ; elle n’annule pas la dette déjà enregistrée.

La migration `0023 → 0024` ajoute uniquement `fusion_ap_saisies` : liaison unique par lot, auteur, clé de rejeu, hash de commande, preuve de références/empreintes, approbation, facture et rang/hash du maillon original. Elle ne duplique ni PDF, champs imprimés ni registre comptable. Une contrainte évite la réutilisation de la même clé par le même acteur ; le downgrade refuse d’effacer des liaisons existantes. Les empreintes ne rendent pas une base privilégiée inviolable.

## Rejeu et correction

Même clé, acteur et commande : le service recontrôle les sources et droits actuels, la provenance, l’approbation exécutée, le reçu idempotent et le maillon d’origine. Il renvoie la référence historique sans seconde approbation ni facture. Une autre clé sur le même lot, un mapping changé, des sources périmées ou un reçu/maillon incohérent sont refusés sans append.

Une correction ou annulation ultérieure reste dans le registre M5 : rejouer la saisie d’origine ne la défait pas et ne présente pas le reçu historique comme l’état financier actuel. Exemple de qualification fictif : facture PDF au sous-total `100.00`, taxes `14.98`, total `114.98`, PO reçu choisi explicitement ; observation sans effet, confirmation unique, correction/annulation dans M5, puis rejeu conservant cette évolution. Ce scénario ne qualifie aucune facture de Synergy réelle.

## Qualification et limites

ROOT annonce **r124 : 637/637 cas en 89,748 s JUnit, 18 fichiers complets, zéro échec/erreur/skip ; Ruff vert sur 12 fichiers et 1 236 sources surveillées inchangées**. La campagne inclut les régressions sélectionnées ; ses sous-comptes ne s’ajoutent pas à 637. Cette documentation ne relance aucun test.

r123 est conservé séparément : 633 réussites et quatre échecs d’assertions de fixtures (nom réel `registres_maillons`, puis préfixe `/opsys` doublé par la combinaison base_url/action de formulaire). Le code de production reste inchangé pour ces corrections ; migration, rollback et rejeu avaient déjà réussi. L’historique de [vérification AP r119](M5-AP-VERIFICATION-REPRISE-2026-10-04.md) reste distinct.

Les [reçus, JUnit, gels et préimages](../../research/REPRISE-2026-10-04/preuves/M5-AP-SAISIE-r1.tar.xz) sont conservés avec un [inventaire vérifiable](../../research/REPRISE-2026-10-04/preuves/M5-AP-SAISIE-r1.json). r122 conserve huit diagnostics Ruff ; pytest n’avait pas été lancé. La campagne utilise Python verrouillé, SQLite et le worker PDF natif sur fixtures fictives, sans héritage de secrets ; limites de ressources et absence de nouvel OOM figurent dans les reçus. La [CI native](../../research/REPRISE-2026-10-04/CI-PUBLICATION.md) reste propre au commit publié ; les succès des parents ne qualifient pas cette étape. La vérification Gitleaks r126 des 23 fichiers de code/documentation trouve zéro alerte, sans exclusion.

Les contrôles ciblent append unique/N3/idempotence, requêtes fermées/CSRF, refus de sources obsolètes et de corruption, rollback avant/après append, correction/annulation puis rejeu, migration et downgrade protégé. PostgreSQL pour ce pont, OCR/scans, corpus représentatif de factures réelles, ingestion massive, exactitude sémantique des citations/mapping, rétention et mobile restent à qualifier. Aucun ledger final, mouvement, décaissement, export QuickBooks/CCube, transmission M10 financière, LLM ou appel externe n’est ajouté. Une revue humaine/CPA reste nécessaire pour les actions officielles.

## Sources lues

- [Pont de saisie](../../../src/opsys/console/fusion_ap_m5_saisie.py#L230) : transaction/commande, N3 (`L318`), append/provenance (`L368`), garde terminale (`L406`), rejeu (`L174`).
- [Contrôles réutilisés](../../../src/opsys/console/fusion_ap_m5.py#L48) : bornes SQL, sources (`L67`), hash liant snapshot et mapping (`L162`).
- [Route privée](../../../src/opsys/console/fusion_ap_ui.py#L635) et [montage dans l’application](../../../src/opsys/console/application.py#L331) : session/CSRF/champs fermés/threadpool.
- [Outil canonique](../../../departments/m05-financecore/src/m5_financecore/outils.py#L1119), [provenance SQL](../../../src/opsys/stockage/schema.py#L577), [migration 0024](../../../src/opsys/stockage/migrations/versions/0024_fusion_ap_saisies.py#L14).
- [Rejeu après correction](../../../tests/test_fusion_ap_m5_saisie_gardes.py#L112), [révocation après commit](../../../tests/test_console_fusion_ap_m5_saisie.py#L148), [migration/downgrade](../../../tests/test_fusion_ap_saisie_migration.py#L51).
- [Design initial](M5-AP-SAISIE-DESIGN-2026-10-04.md) : contrat et limites conservés.
