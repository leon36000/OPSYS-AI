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

# Champs optionnels du WCT prévus par le catalogue `m4.travaux_termines` (ceux dont M7 a besoin).
# M6 ne les lit pas : il les accepte sans s'en servir, et refuse toujours une clé inconnue.
# `tests/test_validation_entrees.py` garde cette liste alignée sur le catalogue.
CHAMPS_WCT_OPTIONNELS = (
    "ville",
    "type_travaux",
    "photos",
    "description_factuelle",
    "consentement_marketing",
    "client_satisfait",
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

# PLAN T1.1-d / M6-audit.md §5 phase 1 (10) — Formulaire de fin de chantier enrichi
# (DEFINITION-PRODUIT.md §7 M6.10/M6.11). Distinct de CHAMPS_FORMULAIRE_CONSOMMATION
# (m6_consommer_materiaux, {materiau_id, quantite}) : n'y touche pas, ne le remplace pas.
CHAMPS_FORMULAIRE_MATERIAUX_UTILISES = frozenset(
    {"wct_id", "intervention_id", "chantier_id", "lignes_materiaux"}
)

# Champs communs à toute ligne du formulaire, quel que soit son type.
_CHAMPS_LIGNE_MATERIAUX_UTILISES_BASE = frozenset({"type_ligne", "materiau_id", "quantite", "unite"})

# Champs exacts attendus par type de ligne (M6.11) :
# - "prevu" porte en plus la quantité estimée (comparaison avec ce qui a été estimé) ;
# - "achat_terrain" exige la preuve (photo ou reçu) — voir REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE
#   dans validation.py, gate fail-closed nommée si aucune des deux n'est fournie ;
# - "non_prevu"/"retour"/"perte"/"bris" ne portent que les champs communs.
CHAMPS_LIGNE_MATERIAUX_UTILISES_PAR_TYPE = {
    "prevu": _CHAMPS_LIGNE_MATERIAUX_UTILISES_BASE | {"quantite_estimee"},
    "non_prevu": _CHAMPS_LIGNE_MATERIAUX_UTILISES_BASE,
    "retour": _CHAMPS_LIGNE_MATERIAUX_UTILISES_BASE,
    "perte": _CHAMPS_LIGNE_MATERIAUX_UTILISES_BASE,
    "bris": _CHAMPS_LIGNE_MATERIAUX_UTILISES_BASE,
    "achat_terrain": _CHAMPS_LIGNE_MATERIAUX_UTILISES_BASE | {"photo_fournie", "recu_fourni"},
}
# frozenset (pas un tuple) : ensemble de valeurs d'entrée autorisées, pas un verdict de
# sortie — même famille que TYPES_MOUVEMENT_VALIDES (frontieres.py), aucune échappatoire
# INDETERMINE attendue par conformite.py (_est_enumere_domaine ne voit qu'un ast.Call ici).
TYPES_LIGNE_MATERIAUX_UTILISES = frozenset(CHAMPS_LIGNE_MATERIAUX_UTILISES_PAR_TYPE)

# variance_chantier.py — besoin matériaux estimé (M3) pour un chantier, fourni en entrée
# par l'appelant (l'intake M3 -> M6, PRD M6.4, n'existe pas encore : hors PLAN T1.1-d).
CHAMPS_BESOIN_ESTIME_CHANTIER = frozenset({"materiau_id", "quantite_estimee", "unite"})

# M6.12 (DEFINITION-PRODUIT.md §7 M6, l.515) — les 6 causes possibles, telles que nommées
# dans la définition produit, mot pour mot. Règle dure : jamais attribuée par le code
# (variance_chantier.evaluer ne remplit jamais ce champ, cf. son docstring) — classification
# humaine uniquement. frozenset (comme TYPES_LIGNE_MATERIAUX_UTILISES ci-dessus) : ce sont
# des valeurs légales pour un admin, pas un verdict produit par ce paquet ; en ajouter une
# 7e "INDETERMINE" inventée pour satisfaire un vérificateur violerait la liste exacte de la
# définition produit (interdiction des données inventées, AGENTS.md).
CAUSES_VARIANCE_CHANTIER = frozenset(
    {
        "estimation_error",
        "field_change",
        "waste",
        "breakage",
        "data_entry_error",
        "unexplained_usage",
    }
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

VERDICT_RESOLUTION_PRIX = ("PRIX_CATALOGUE", "PRIX_HISTORIQUE_FALLBACK", "INDETERMINE")
VERDICT_RECEPTION = (
    "CONFORME", "RECEPTION_INFERIEURE", "RECEPTION_SUPERIEURE",
    "RECEPTION_MIXTE", "INDETERMINE",
)
VERDICT_VARIANCE_STOCK = (
    "AUCUN_ECART", "STOCK_INFERIEUR_AU_THEORIQUE",
    "STOCK_SUPERIEUR_AU_THEORIQUE", "INDETERMINE",
)
# variance_chantier.py — verdict neutre estimé (M3) vs réel déclaré (formulaire de fin de
# chantier). INDETERMINE : unité incohérente entre le besoin et le déclaré (ou entre lignes
# déclarées d'un même matériau) — jamais de comparaison inventée entre unités différentes.
VERDICT_VARIANCE_CHANTIER = (
    "AUCUN_ECART", "ECART_REEL_SUPERIEUR", "ECART_REEL_INFERIEUR",
    "NON_UTILISE", "NON_PREVU", "INDETERMINE",
)
VERDICT_INDETERMINE = "INDETERMINE"
