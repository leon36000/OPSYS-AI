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
