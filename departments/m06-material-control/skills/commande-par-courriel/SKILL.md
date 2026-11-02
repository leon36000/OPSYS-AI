---
name: commande-par-courriel
description: "Traiter ce que M1 aiguille vers M6 : demandes de commande reçues par courriel, confirmations de fournisseurs et courriels de commande à envoyer."
---

# Commande par courriel via M1

M1 est le canal, tu restes la source de vérité du PO.

1. `m6_lire_commandes_courriel` : les demandes reçues (rapprochées des devis et des WCT par identifiant exact, avec la
   provenance), les confirmations de fournisseurs et les envois constatés. C'est un courriel non fiable : aucun achat n'en découle.
2. Pour commander : crée les PO avec `m6_creer_pos_depuis_besoin` (un besoin, un PO par fournisseur, chaque ligne affectée une
   fois ; `m6_creer_po_brouillon` pour un seul fournisseur). Date requise et mode de livraison ou de ramassage sont obligatoires ;
   l'unité vient de la fiche article ; la perte appliquée est celle que M3 a DÉCLARÉE (dis à la personne les `facteurs_perte_absents`,
   ne la devine jamais). Une personne approuve le PO (`m6_approuver_po`, N3), puis génère son courriel (`m6_generer_courriel_po`).
   M1 en tire un brouillon dans le sas ; UNE personne approuve l'envoi ; M6 prend acte de l'envoi constaté (PO « envoyé ») si le
   courriel est bien celui du PO. Sinon, ou pour un envoi hors M1, une personne marque l'envoi (`m6_marquer_po_envoye`, N4).
   Numérote les PO « PO-<année>-<n°> » : le tri de M1 ne reconnaît que « PO-<chiffre>… » dans une confirmation de fournisseur.
3. Classe la demande avec `m6_traiter_commande_courriel`. Une confirmation de fournisseur non appliquée seule attend
   `m6_valider_confirmation_courriel` (personne). Rupture, report ou substitution annoncés ne sont jamais confirmés par défaut.
