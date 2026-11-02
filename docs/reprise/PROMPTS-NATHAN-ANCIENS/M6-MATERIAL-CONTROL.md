# M6 — Material Control OS : inventaire, achats, fournisseurs, bons de commande, réservations, sorties terrain, variance, alertes (condensé fonctionnel du prompt de Nathan, 2026-06-23)

(« GRS » = ancien nom d'OPSYS-AI.) But : le **système de vérité des matériaux** — pas un tableau de stock. M6 sait quels matériaux existent, quels fournisseurs vendent quoi, quels prix sont connus,
quel matériau chaque estimation requiert, ce qui est réservé par chantier, ce qui doit être commandé, quel bon de commande (PO) est parti, ce que le fournisseur a confirmé, ce qui est reçu,
disponible, réservé, utilisé, retourné, perdu, brisé ou manquant, l'écart estimé/réel, ce que l'admin doit auditer, quel coût réel envoyer à M5, quelle leçon envoyer à M3 et M10.
Éviter : matériau oublié, commande en double, mauvais fournisseur/prix/item, chantier planifié sans matériel, équipe envoyée sans matériel, matériau utilisé non déclaré, perte disproportionnée
non détectée, erreur d'estimation non apprise, vol potentiel non signalé, PO non suivi, stock faux, facture fournisseur non rapprochable, marge détruite par coût réel supérieur.
Flux : M3 matériaux estimés → M6 besoins → réservation/achat/PO → M1 envoie le courriel au fournisseur si requis → confirmation → réception en stock → M4 chantier → l'employé déclare les
matériaux utilisés → M6 compare estimé/réel → alerte admin si écart → M5 reçoit les coûts réels → M8 mesure la variance → M9 analyse risque/occasion → M10 mémorise.
Règles : ne pas reconstruire M3/M4/M5 ; **aucune commande fournisseur réelle sans validation ou politique autorisée** ; **ne jamais accuser un employé de vol automatiquement** (message
imposé : « Écart matériaux critique — validation admin requise. Causes possibles : erreur d'estimation, changement terrain, perte, bris, mauvaise saisie, retour non déclaré ou usage non
expliqué. ») ; aucun ajustement d'inventaire sans trace ; aucun coût fournisseur officiel sans source ; pas de « terminé » sans E2E estimation → commande → réception → sortie terrain →
variance → finance. Fournisseurs connus : **Gentek, Royal Solution de Bâtiment, O.A.M., Kaycan**.

## Fonctions attendues
- **M6.1 Catalogue de matériaux** : SKU interne, nom, catégorie, service lié, fournisseur principal/alternatif, unité, couleur, longueur, largeur, profil, matériau, prix estimé/validé, statut,
  notes, compatibilités, substitutions, dernière mise à jour ; catégories (gouttières, descentes, coins, coudes, fascia, soffite, revêtement, moulures, membrane, vis, scellant, accessoires,
  consommables, outils, équipements, matériaux spéciaux) ; recherche.
- **M6.2 Registre de fournisseurs** : contact, courriel de commande, téléphone, adresse, conditions, délai habituel, catégories vendues, format de commande préféré, notes, statut, historique
  de prix, fiabilité, erreurs passées, substitutions offertes ; carnet de prix et commandes par fournisseur.
- **M6.3 Carnet de prix fournisseurs** : prix par item et fournisseur, date d'effet, estimé vs confirmé, historique, hausses/baisses, source, facture et PO liés, validation admin ;
  **un prix sans source est marqué ESTIMATED ou FALLBACK_PRICE_BOOK** ; import, mise à jour, historique, changements.
- **M6.4 Besoins en matériaux issus de M3** (job, estimation, service, matériaux {id, description, quantité estimée, unité, facteur de perte, confiance}, risque, notes) → valider les items, vérifier
  le stock, **réserver si disponible**, générer le besoin de commande si manquant, recommander un fournisseur, estimer le coût, retourner la préparation à M4/M3 (disponibilité, source du coût,
  fournisseur recommandé, besoin de commande, délai, substitution possible, risque de rupture).
- **M6.5 Moteur de bons de commande** : statuts (brouillon, en revue admin, approuvé, courriel prêt, envoyé, confirmé par le fournisseur, partiellement reçu, reçu, annulé, contesté, facturé,
  fermé) ; champs (fournisseur, chantier, estimation, items, quantités, prix estimé/confirmé, livraison ou ramassage, date requise, notes, validation, courriel envoyé, confirmation).
- **M6.6 Flux de commande par courriel via M1** (M1 = canal administratif ; M6 reste la source de vérité du PO) : brouillon de courriel (destinataire, objet « Commande matériaux — PO … — ville »,
  liste, chantier, date requise, livraison/ramassage, numéro de PO, pièces jointes), révision, envoi si autorisé, suivi de la réponse, confirmation enregistrée, historique de courriels.
- **M6.7 Réception / entrée en stock** : complète, partielle, item manquant, substitué, prix différent, dommage, photo du reçu, facture, livraison au dépôt/directe au chantier/ramassage ;
  si prix réel ≠ prévu au-delà d'un seuil → alerte admin + signal M5/M8.
- **M6.8 Réservation de stock par chantier** (réserver, empêcher la double réservation, lier au chantier, libérer à l'annulation, ajuster après modification d'estimation, transférer la
  réservation en sortie terrain, conflits).
- **M6.9 Emplacements** (dépôt principal, camion, remorque, chantier, employé, fournisseur, retour, rebut, inconnu), stock par emplacement, transferts audités.
- **M6.10 Formulaire mobile de matériaux utilisés** (quand l'employé clique « travaux terminés » dans M4) : matériaux prévus et quantités prévues affichés, quantités réellement utilisées,
  non utilisé, retourné, brisé, perte, achat sur place (photo/reçu obligatoire), notes, photos, ajout d'un item non prévu avec raison d'écart, confirmation/signature ; **l'employé ne voit
  pas les coûts ni marges sensibles**.
- **M6.11 Validation des sorties** (item prévu ou non, quantité vs estimée, unité cohérente, stock disponible, réservation existante, retour/perte/bris déclarés, achat justifié, preuve requise) :
  valider/approuver/rejeter, file de revue.
- **M6.12 Moteur de variance estimé vs réel** : écarts (quantité supérieure/inférieure, item non prévu, prévu non utilisé, perte élevée, retour non déclaré, coût supérieur, prix fournisseur différent,
  mauvais matériau, erreur d'unité, erreur d'estimation) ; scores (variance de quantité %, variance de coût montant/%, variance de perte %, score d'erreur d'estimation, score de risque d'usage
  terrain, revue admin requise) ; sortie {niveau, estimé, réel, causes possibles, revue admin, actions recommandées}.
- **M6.13 Alertes de perte / gaspillage / bris / usage inexpliqué** (usage au-dessus du seuil, matériau cher non estimé, perte/bris trop élevés, plusieurs écarts non expliqués pour une même équipe,
  item manquant à répétition, stock négatif, ajustements manuels fréquents, commande reçue mais stock disparu, chantier fermé sans usage déclaré) — **jamais « vol » automatiquement** ; visibles au
  tableau admin, mobile admin, rapport hebdomadaire M8/M9, mémoire M10 ; assignation et résolution avec cause classée (erreur d'estimation, changement terrain, perte, bris, erreur de saisie,
  inexpliqué) ; si erreur d'estimation → retour à l'apprentissage M3 ; si stock → ajustement ; si finance → M5.
- **M6.14 Ajustements d'inventaire et piste d'audit** (correction, perte, bris, retour fournisseur/chantier, stock retrouvé, erreur de saisie, inventaire physique, transfert, annulation) avec
  acteur, raison, avant/après, date, source, preuve, approbation si nécessaire, trace ; comptage physique.
- **M6.15 Moteur de réapprovisionnement** (seuil minimal, réservé, disponible, chantiers à venir M4, besoins M3, délai fournisseur, saison, prix, quantité économique) : recommandations, création de PO,
  risque de rupture.
- **M6.16 Pont fournisseur / finance (M5)** : M6 envoie PO, réception, fournisseur, items, prix estimé/confirmé, facture fournisseur, taxes, écart de prix, chantier ; M5 retourne facture à
  payer, statut de paiement, coût validé, rapprochement, anomalie ; **M6 ne paie pas**.
- **M6.17 Achats sur place** (urgent, fournisseur, montant, item, raison, photo du reçu, chantier, approbation) : limités, tracés, envoyés à M5.
- **M6.18 Tableau de bord et mobile admin/employé** (stock critique, commandes en attente, PO à approuver/envoyés, réceptions partielles, écarts importants, pertes/bris, chantiers sans matériel
  prêt, fournisseurs en retard, hausses de prix, réservé/disponible, alertes à réviser, variance par équipe/chantier/service ; admin mobile : alertes, PO à approuver, écarts, stock critique,
  réception rapide, validation d'usage, rapport perte/bris ; employé : matériaux prévus, formulaire, ajout d'item, quantités, retour, perte/bris, achat, reçu, notes).
- **M6.19 Analytique M8** (ruptures, valeur du stock, recommandations de réapprovisionnement, demandes d'achat, variation de prix fournisseur, variance de matériaux, exactitude de l'inventaire,
  chantiers à forte variance, taux de perte, durée du cycle de PO, fiabilité des fournisseurs) ; **M9** (signaux de rupture et de variance, stratégie fournisseur, achat en volume, hausse
  de prix, économies) ; **M10** (nouveau fournisseur, prix changé, PO envoyé/reçu, écart, erreur d'estimation, bris/perte, ajustement, fournisseur problématique, substitution, décision admin,
  correction de stock, leçon terrain).
- **Sécurité** : rôles (admin, gestionnaire d'inventaire, employé terrain, vendeur, finance, agent système, propriétaire) et permissions (voir matériaux, gérer le catalogue, voir prix fournisseurs,
  créer/approuver PO, envoyer une commande, recevoir, soumettre usage, approuver une variance, ajuster le stock, voir les coûts, voir les alertes, exporter) ; employé ne voit pas les coûts
  sensibles mais déclare l'usage réel ; PO réel = validation ; ajustement critique = audit obligatoire ; pas de suppression dure sans décision ; toutes les actions tracées.
- **Tâches automatiques** (besoins depuis l'estimation, courriel de PO, rappel de réception, scan de risque de rupture, revue d'usage de chantier, alerte de variance à l'admin, rapport de
  variation de prix fournisseurs, rapport hebdomadaire de variance) : peuvent créer tâches, notifications, brouillons, scans, rapports ; **ne peuvent pas** envoyer une commande sans politique/
  validation, ajuster un stock critique sans audit, accuser un employé, payer un fournisseur, supprimer l'historique, masquer un écart.
- **Tests visés** : catalogue, fournisseurs, carnet de prix, besoins M3, génération de PO, brouillon de courriel, réception, réservation, formulaire d'usage, variance, alertes, ajustements,
  pont financier ; intégrations (M3 → besoins → PO → brouillon M1 → confirmation → réception → fin de chantier M4 → formulaire → décrément → alerte de variance → coût réel M5 → métriques M8 → leçon
  M10) ; E2E (estimation → commande Gentek ; réception partielle avec écart ; travaux terminés normaux ; écart de 40 % avec revue en attente et retour à M3 ; risque de rupture avec signal M9).
- **Critères de sortie** : catalogue, fournisseurs, carnet de prix (ou repli documenté), besoins M3, PO, courriel fournisseur via M1 (ou repli manuel documenté), réception, réservations, formulaire
  mobile, sortie de stock, variance, alertes admin, M5/M8/M9/M10, aucun employé accusé automatiquement, piste d'audit sur chaque ajustement, tests, docs, matrice.
