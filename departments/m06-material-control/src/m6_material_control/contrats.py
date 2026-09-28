CHAMPS_WCT = (
    "wct_id",
    "intervention_id",
    "lead_id",
    "technicien_id",
    "horodatage_completion",
    "fix_gps_completion",
    "duree_reelle_minutes",
    "ecart_signale",
    "revue_id",
    "hash_maillon",
    "consommateurs_cibles",
    "devis_id",
)

CONSOMMATEUR_ATTENDU = "M6"

CHAMPS_FORMULAIRE_CONSOMMATION = (
    "wct_id",
    "intervention_id",
    "chantier_id",
    "lignes_consommees",
)

# §5.4/§5.5 PRD — BonDeCommandeDemande, ReceptionPO, ComptageInventaire, SeuilReorder.
CHAMPS_BON_DEMANDE = frozenset({"po_id", "chantier_id", "lignes_demandees", "horodatage"})
CHAMPS_LIGNE_DEMANDEE = frozenset({"materiau_id", "quantite_demandee"})
CHAMPS_RECEPTION_PO = frozenset({"po_id", "chantier_id", "lignes_recues", "horodatage"})
CHAMPS_LIGNE_RECUE = frozenset({"materiau_id", "quantite_recue"})
CHAMPS_COMPTAGE = frozenset({"chantier_id", "materiau_id", "quantite_comptee", "horodatage"})
CHAMPS_SEUIL_REORDER = frozenset({"chantier_id", "materiau_id", "seuil_quantite"})

MOTS_INTERDITS_DOMAINE = frozenset(
    {
        "statut_paiement",
        "virement",
        "reference_bancaire",
        "mode_paiement",
        "prix_vente",
        "date_execution",
        "creneau",
        "duree",
    }
)

VERDICT_RESOLUTION_PRIX = ("PRIX_CATALOGUE", "PRIX_HISTORIQUE_FALLBACK", "INDETERMINE")
VERDICT_RECEPTION = (
    "CONFORME", "RECEPTION_INFERIEURE", "RECEPTION_SUPERIEURE",
    "RECEPTION_MIXTE", "INDETERMINE",
)
VERDICT_VARIANCE_STOCK = (
    "AUCUN_ECART", "STOCK_INFERIEUR_AU_THEORIQUE",
    "STOCK_SUPERIEUR_AU_THEORIQUE", "INDETERMINE",
)
VERDICT_INDETERMINE = "INDETERMINE"
