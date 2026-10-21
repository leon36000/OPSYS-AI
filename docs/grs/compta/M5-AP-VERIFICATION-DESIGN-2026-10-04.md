# Vérification préparatoire AP depuis Fusion — design avant code

Date : 2026-10-04. Statut initial : à implémenter et qualifier, M5 global PARTIEL.

## Audit et réutilisation

`fusion_ap.py` stocke une proposition humaine chiffrée `A_REVOIR`, avec citations
revalidées contre l'extrait PDF courant. Ses valeurs textuelles ne sont pas des
identités fournisseur/PO ni des montants validés. `comptes_a_payer.py` contrôle
déjà réception du PO, fournisseur, dates, taxes versionnées, total imprimé et
doublons à leur état courant. Sa saisie écrit immédiatement une dette `SAISIE`;
elle ne constitue donc pas un brouillon à appeler pour vérifier.

La première brique réutilisée est ce domaine M5 existant. Aucun nouveau logiciel,
tax engine, registre, endpoint MCP ou statut comptable n'est nécessaire.

## Tranche retenue

- Extraire une préparation pure commune au vérificateur et à la saisie. Conserver
  l'ordre des refus et les résultats historiques de la saisie; seule celle-ci
  conserve son appel à `_ranger_facture`.
- Ajouter une action POST privée `.../ap/verifier-m5`, CSRF, administrateur actif
  possédant aussi `finance` ou `nathan_owner`. Ne pas déduire le rôle finance du
  seul rôle admin ou du cookie.
- L'humain choisit explicitement les identifiants PO/fournisseur connus de M5 et
  atteste leur correspondance avec les champs imprimés. Aucun rapprochement
  automatique du nom libre n'est prétendu.
- Relire/déchiffrer le brouillon et les citations sous transaction SQLite courante,
  contrôler les révisions PDF/AP attendues; préborner les maillons AP et vérifier
  leur chaîne. Charger les taux existants avec leur version/source, conserver
  leurs empreintes; refuser une source changée pendant le calcul.
- Exiger `CAD`, une date ISO et trois montants décimaux positionnels au cent
  (sous-total, total des taxes, total). Aucun parsing ambigu, taux supposé ou
  normalisation des libellés OCR. Des champs tels que `100.00 CAD` ou un détail
  `TPS ...; TVQ ...` doivent être revus dans le formulaire humain existant.
- Calculer par M5, comparer aussi les taxes imprimées. Afficher seulement le code
  de refus ou les montants calculés, versions/source des taux, instant et empreinte
  du snapshot; aucune exception, contenu PDF ou ciphertext dans la réponse.
- Revalider les sources juste avant réponse et l'identité vivante après chaque
  appel bloquant. Le résultat est une observation datée, jamais une approbation
  durable ni une permission de saisie/paiement.

## Preuves requises

Tests purs comparant contrôle/saisie et refus canoniques; tests SQLite réels et
console authentifiée avec PDF fictif natif isolé : succès et répétition sans
écriture, absence de PO reçu, fournisseur différent, doublon courant, taxes/total
incohérents, devise/format manquants, source/révision/taux changés, chaîne corrompue,
CSRF, admin sans finance, révocation pendant lecture, limites et HTML échappé.
Comparer toutes les lignes des tables métier avant/après (hors fixtures établies
avant action). Aucun appel de saisie ni effet réseau/M10.

## Suite et limites

Cette tranche ne confirme, n'importe, ne poste et ne paie aucune facture. La
future saisie M5 avec provenance Fusion requerra un parcours distinct N3, une
nouvelle validation des sources et une décision explicite. Exonérations,
fournisseurs sans PO, OCR/image, factures réelles et ingestion massive demeurent
hors de cette qualification; les taux/sources actuels ne sont pas une validation
CPA ni une garantie de conformité pour chaque facture.
