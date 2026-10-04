# Fusion AP — retrouver une saisie et son état M5 courant

4 octobre 2026 UTC — tranche 21. **M5 et OPSYS-AI restent PARTIEL.** **Qualification locale ROOT r130 : 668/668 sur 21 fichiers complets**, sans échec, erreur ni test ignoré ; 104,600 s JUnit (105,373 s au mur). Ruff réussit sur 16 fichiers de code ; 1 240 sources gelées restent identiques et aucun OOM n’est observé. La CI native de cette tranche reste à obtenir sur son propre commit.

## Parcours privé existant

Après une [saisie humaine confirmée](M5-AP-SAISIE-RAPPORT-2026-10-04.md), fermer le navigateur puis se reconnecter ne doit plus obliger à renvoyer le POST de saisie pour retrouver sa référence. Le **GET existant** `/fusion/pdf/lots/{lot_id}/ap`, sous le préfixe de console (`/opsys` par défaut), consulte la liaison `fusion_ap_saisies` de la migration 0024. Le reçu de confirmation propose désormais un lien vers ce GET et vers la page `/finance` existante, sans inventer une vue détaillée ou filtrée des comptes à payer.

La référence financière est réservée à une personne active propriétaire `nathan_owner`, ou portant à la fois `admin` et `finance`. L’application revalide la session et l’autorité avant/après les lectures bloquantes et le rendu ; le lecteur les recontrôle dans la transaction SQLite. Un admin sans finance conserve la revue documentaire, sans lecture ni affichage de cette référence. La réponse privée reste `no-store`, les identifiants sont échappés, et les appels bloquants passent par le threadpool existant.

| Champ affiché | Signification |
|---|---|
| `facture_id` | Identifiant de la facture originale liée au lot. |
| `approbation_id` | Identifiant de l’approbation N3 exécutée lors de la saisie. |
| `statut_m5` | État courant projeté par M5 : `SAISIE`, `CORRIGEE` ou `ANNULEE`. |
| `corrections` | Nombre de corrections enregistré par le projecteur canonique M5. |

Le brouillon Fusion reste `A_REVOIR`. Une correction ou annulation append-only dans M5 ne réécrit pas la saisie initiale ; son statut courant est lu par `_etats_factures`, sans second projecteur ni nouvelle vérité financière. Une absence de liaison Fusion ne démontre pas l’absence d’une facture indépendante dans M5.

## Intégrité et limites de lecture

Le lecteur valide la forme fermée et les hashes de la preuve, les arguments et le résultat historiques de l’approbation N3, le reçu idempotent exact, le rang/hash du maillon d’origine et la chaîne AP actuelle. Il lit le reçu directement sans `reclamer` : aucune réclamation idempotente, approbation ou écriture n’est créée. Les preuves/reçus sont bornés à 4 Kio, les arguments/résultats d’approbation à 32 Kio avant décodage ; les bornes de chaîne AP existantes sont réutilisées. Toute incohérence de liaison, preuve, approbation, reçu ou chaîne refuse avec 503 (`M5_REFERENCE_INDISPONIBLE` côté lecteur, code de référence indisponible côté page). Elle n’est jamais convertie en référence absente.

Cette lecture compare les montants/taxes **enregistrés** entre pièces historiques ; elle ne recharge ni n’applique les taux fiscaux actuels. Un remplacement du fichier de taux n’efface pas la référence de dette. Le backend n’a pas besoin de relire les octets PDF pour lire la liaison, mais le **GET de revue conserve ses préconditions PDF et AP actuelles** : PDF extrait disponible, résultat/révision et brouillon consultables. Ce GET n’est donc pas une archive autonome si la source PDF devient indisponible.

Aucun montant, motif libre, argument d’approbation, corps PDF, source fiscale ou hash financier supplémentaire n’est ajouté au bloc de référence. Le brouillon et ses champs restent ceux de la revue documentaire existante. Aucun nouvel endpoint, POST automatique, migration, outil agent/MCP, fournisseur, paiement, mouvement ou ledger final n’est ajouté.

## Correctif de rejeu Unicode et preuves conservées

ROOT r127 conserve un **rouge réel : zéro réussite, un échec**. Un PO ou fournisseur Unicode accepté par la saisie pouvait échouer au rejeu : le recalcul utilisait `ensure_ascii=False`, alors que le hash de commande historique avait été créé avec l’encodeur JSON par défaut (`ensure_ascii=True`). Le recalcul de la commande utilise désormais la même sérialisation historique, dans le rejeu et dans le lecteur de référence. Les autres empreintes de preuve gardent leur convention propre ; aucun reçu ou maillon historique n’est réécrit.

ROOT r128 conserve deux erreurs d’imports Ruff, sans lancement de pytest. r129 donne 657 réussites et deux échecs sur 659 cas : un helper de test capturait le point de ponctuation du reçu dans les identifiants, faisant échouer la comparaison et une correction sur cet identifiant erroné. Le helper est corrigé ; les comportements de production ne sont pas assouplis pour ces échecs.

r130 passe les 668 cas des 21 fichiers complets, incluant les 637 cas de la tranche 20 ; ces campagnes se recouvrent et ne s’additionnent pas. La régression Unicode passe avec le vrai outil N3 puis un rejeu et la consultation. Les tests couvrent reconnexion, absence d’écriture sur toutes les tables, corrections et annulation canoniques, taux remplacés, droits/révocations pendant lecture et rendu, preuves rehashées incohérentes, `NaN`/`Infinity`, et écoute SQL empêchant la sélection complète des arguments/résultats >32 Kio ou du reçu >4 Kio.

Preuves : [capsule r1](../../research/REPRISE-2026-10-04/preuves/M5-AP-CONSULTATION-r1.tar.xz) et [manifeste SHA-256](../../research/REPRISE-2026-10-04/preuves/M5-AP-CONSULTATION-r1.json). Les campagnes rouges r127/r128/r129, les drivers, logs, JUnit, préimages et empreintes finales y sont conservés. Limites d’exécution : 180 s, 512 Mio de RSS ; le pic du groupe pytest est de 159 449 088 octets. Les environnements de test n’héritent pas des secrets de session.

La preuve locale sur SQLite et PDF natif fictif ne qualifie pas PostgreSQL pour ce pont, factures réelles représentatives, rétention/mobile AP, OCR, paiement, comptabilité finale ou CFO complet. Le [relevé CI](../../research/REPRISE-2026-10-04/CI-PUBLICATION.md) distingue chaque head et ne reporte aucun succès ancien sur le code de cette tranche.

## Sources et contrat

- [Design préalable](M5-AP-CONSULTATION-DESIGN-2026-10-04.md).
- [Lecteur](../../../src/opsys/console/fusion_ap_m5_reference.py#L263) : provenance/autorité, projection courante (`L320`), quatre champs (`L336`) ; bornes et approbation (`L105`), reçu sans écriture (`L232`).
- [GET AP et rendu](../../../src/opsys/console/fusion_ap_ui.py#L498), [bloc fermé de quatre champs](../../../src/opsys/console/fusion_ap_ui.py#L302), [liens du reçu](../../../src/opsys/console/fusion_ap_ui.py#L330).
- [Hash du rejeu corrigé](../../../src/opsys/console/fusion_ap_m5_saisie.py#L265) et [hash de commande historique vérifié par le lecteur](../../../src/opsys/console/fusion_ap_m5_reference.py#L128).
- Scénarios exécutés et vérifiés par ROOT : [backend](../../../tests/test_fusion_ap_m5_reference.py), [console](../../../tests/test_console_fusion_ap_m5_reference.py), [Unicode](../../../tests/test_fusion_ap_m5_saisie_unicode.py).
