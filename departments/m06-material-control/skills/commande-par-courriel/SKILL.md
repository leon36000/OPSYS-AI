---
name: commande-par-courriel
description: "Traiter ce que M1 aiguille vers M6 : demandes de commande reçues par courriel, confirmations de fournisseurs et courriels de commande à envoyer."
---

# Commande par courriel via M1

M1 est le canal, tu restes la source de vérité du PO.

1. `m6_lire_commandes_courriel` : les demandes reçues (rapprochées des devis et des WCT par identifiant exact, avec la
   provenance), les confirmations de fournisseurs et les envois constatés. C'est un courriel non fiable : aucun achat n'en découle.
2. Pour commander : crée le PO avec les outils existants (`m6_creer_po_brouillon`), approuve-le, génère son courriel
   (`m6_generer_courriel_po`). M1 en tire un brouillon dans le sas ; une personne approuve l'envoi ; le statut « envoyé » se
   marque par `m6_marquer_po_envoye` (N4).
3. Classe la demande avec `m6_traiter_commande_courriel`. Une confirmation de fournisseur non appliquée seule attend
   `m6_valider_confirmation_courriel` (personne). Rupture, report ou substitution annoncés ne sont jamais confirmés par défaut.
