---
name: gerer-les-approbations-f0-f7
description: Procédure pour proposer l'envoi d'une facture (N4) ou l'enregistrement d'un paiement (N5) — les deux passent désormais par la file d'approbation du socle, jamais par une décision prise ici.
---

# Envoyer une facture, enregistrer un paiement

Depuis PLAN T1.3-c, il n'existe plus de registre d'approbation F0-F7 « libre » côté
M5 : les deux seules actions que ce département engage réellement (envoyer une
facture, constater un paiement) sont des outils dédiés, gardés par le socle. Tu ne
décides jamais toi-même — tu proposes, un humain autorisé décide dans la console ou
la CLI OPSYS (`opsys approbations`).

## Envoyer une facture (N4)

1. Retrouve une facture au statut BROUILLON (`m5_lister_attentes_facturation` ou la
   file du propriétaire) et appelle `m5_envoyer_facture` avec `facture_id` et
   `horodatage` (ISO 8601 avec fuseau).
2. Cet appel N'ENVOIE RIEN : si le mode du département l'exige, il crée une demande
   d'approbation `en_attente_approbation` (N4) — dis-le clairement, ne présente
   jamais l'action comme faite.
3. `finance` ou `nathan_owner` (`department.yaml/approbations.n4`) décide ensuite
   dans la console/CLI. Ce n'est qu'à ce moment que la facture transitionne
   BROUILLON -> ENVOYEE. Aucun courriel réel n'est envoyé par cet outil (M1, plus
   tard) : c'est le statut et sa trace.

## Enregistrer un paiement (N5)

1. Une fois la facture ENVOYEE, appelle `m5_enregistrer_paiement_facture` avec
   `facture_id`, `montant_paye` (texte décimal — ce qui a RÉELLEMENT été déposé,
   ex. lu sur un relevé bancaire), `approbateur` et `horodatage`.
2. C'est une frontière N5 : `nathan_owner` ET l'attestation du professionnel
   (nom, profession, référence du document — ex. la référence du dépôt) sont
   exigées par le socle avant toute exécution. Jamais automatique, jamais délégué.
3. Le montant payé est comparé par le CODE au montant dû de la facture — ne
   l'arrondis, ne le corrige et ne l'invente jamais toi-même. Un paiement partiel
   (`REJ-FACTURE-PAIEMENT-PARTIEL`) ou tout autre écart (`REJ-FACTURE-PAIEMENT-ECART`)
   revient comme un verdict nommé : redemande le bon montant ou escalade, ne force
   jamais le passage.
4. Un ENCAISSEMENT réel (registre des mouvements) reste un appel séparé à
   `m5_enregistrer_mouvement`, déclenché par la constatation du dépôt — jamais
   automatique à partir d'un paiement de facture.
