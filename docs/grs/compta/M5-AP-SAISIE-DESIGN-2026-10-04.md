# Fusion AP → saisie humaine M5 : conception avant implémentation

4 octobre 2026 UTC. Statut : conception préalable conservée; parcours qualifié localement dans le
[rapport de saisie](M5-AP-SAISIE-RAPPORT-2026-10-04.md), sans promotion globale.
Base : [contrôles préparatoires](M5-AP-VERIFICATION-REPRISE-2026-10-04.md).

Une facture fournisseur PDF native préparée dans Fusion reste `A_REVOIR`.
Après consultation des extraits, correction des champs et choix explicite d'un PO reçu
et de son fournisseur canonique, les contrôles déterministes M5 donnent une observation.
Un **second POST explicitement confirmé** doit permettre à une personne autorisée de
créer une unique facture `SAISIE` dans le registre M5 existant. Cette saisie constate
une dette interne non finale : aucun paiement, mouvement, export externe ou écriture
comptable finale. L'observation seule n'autorise rien.

## Réutilisation et autorité

Réutiliser le stockage transactionnel, la file d'approbation N3, l'idempotence,
le contrat `m5_saisir_facture_fournisseur`, ses validations et son registre.
Pas de deuxième vérité comptable ni de nouvelle bibliothèque. La route privée conserve
l'intersection d'autorité actuelle : personne active admin **et** finance, ou propriétaire.
Ni un rôle écrit dans le formulaire, ni une session historique ne font foi.
Ne pas ouvrir l'outil AP dans la surface générique de commandes console : cette route
seule possède les contrôles de provenance nécessaires. Aucun nouvel outil MCP.

## Préconditions de la commande

- CSRF, formulaire urlencoded borné, champs fermés, aucune query ; identifiants humains,
  révisions PDF/AP, clé de rejeu, attestation de correspondance et confirmation de saisie.
- L'observation porte un hash de commande liant son snapshot (PDF, AP, citations,
  configuration, taux et tête/rang M5) au PO et au fournisseur choisis.
- Dans une vraie transaction SQLite `BEGIN IMMEDIATE`, relire/déchiffrer la source,
  valider les citations et la chaîne M5, les montants CAD explicites, les taux versionnés
  et les doublons. Comparer le hash attendu ; aucune reconstruction depuis des montants
  ou identités fournis par le navigateur.
- Capturer les octets fiscaux bornés. L'exécution M5 doit utiliser **ces mêmes octets**,
  par un argument Python interne hors schéma d'outil ; les autres appelants conservent
  leur lecture habituelle. L'identité humaine canonique est toujours vérifiée par M5.
- Le serveur crée les six arguments métier et l'horodatage. L'approbation N3 immédiate
  exécute ce contrat exact au nom de la personne actuelle ; aucun approbateur extérieur.

## Atomicité et provenance

Une liaison `fusion_ap_saisies` par lot, migration Alembic 0024 depuis 0023, conserve
uniquement l'auteur, la clé de rejeu, le hash de commande, les références/hash de source,
la référence d'approbation, l'identifiant de facture et le hash/rang du maillon créé.
Les champs imprimés et les octets PDF ne sont pas dupliqués. Le brouillon demeure à revoir.
Liaison, approbation, reçu idempotent, maillon M5 et audit sont dans la même transaction.
La rétrogradation doit refuser d'effacer des liaisons existantes.

Après exécution, exiger exactement un append de facture attendu, l'approbation exécutée,
les bons auteur/arguments et les montants/taxes calculés. Relire les sources PDF/AP/taux
et l'autorité avant commit. Tout échec doit **lever hors du répartiteur d'approbation**
afin d'annuler également ses écritures et sa réclamation idempotente.

## Rejeu

Avant tout reçu historique, vérifier l'autorité courante et les sources PDF/AP/taux.
Un renvoi de la même clé et du même hash retourne la référence de la saisie originale,
sans exécuter M5 ni une seconde approbation. Valider la liaison et le maillon d'origine
dans la chaîne ; ses éventuelles corrections/annulations ultérieures ne sont pas annulées.
Une autre clé sur le même lot refuse une seconde saisie ; changement d'arguments ou
de source refuse le rejeu. Un refus ne transforme jamais le reçu en autorisation nouvelle.

## Vérification et limites

Tests ciblés : PDF natif/SQLite réels, observation sans effets, double confirmation,
approbation N3/arguments exacts, append unique, rejeu, doublon, sources/rates changées,
révocation pendant exécution, corruption de reçu/maillon, panne avant et après append,
rollback de toutes les tables, migration 0023→0024 et downgrade protégé, HTTP CSRF et
champs fermés. Régressions des contrôles AP, de l'approbation et de l'idempotence.

La qualification PostgreSQL, OCR/scans, ingestion massive, PO automatique, CPA,
paiements, écritures finales et parcours mobile demeurent hors de cette tranche.
Un hash compatible ne certifie pas la vérité de la facture ni la justesse humaine du mapping.
