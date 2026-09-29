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
# `type_travaux` (lead v1) et `service` (lead v2, PLAN T0.13-b) sont deux clés distinctes du WCT : M4
# n'en porte jamais qu'une, et aucune n'est déduite de l'autre.
# PLAN T1.5-d : le consentement du client à une demande d'avis et la preuve des consentements (qui les a
# recueillis, quand, quel texte) sont aussi portés par le WCT ; M6 les accepte sans les lire, comme le
# reste. Sans eux ici, `valider_wct` refuserait (`REJ-WCT-CHAMP-INATTENDU`) le formulaire des matériaux
# de tout chantier terminé avec un consentement.
# `tests/test_validation_entrees.py` garde cette liste alignée sur le catalogue.
CHAMPS_WCT_OPTIONNELS = (
    "ville",
    "type_travaux",
    "service",
    "photos",
    "description_factuelle",
    "consentement_marketing",
    "client_satisfait",
    "consentement_demande_avis",
    "consentement_recueilli_par",
    "consentement_recueilli_le",
    "consentement_version_texte",
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

# PLAN T2.5 point 2 (audit M6.2) — Registre des fournisseurs : IDENTITÉ ET COORDONNÉES
# SEULEMENT (Gentek, Royal Solution de Bâtiment, O.A.M., Kaycan cités par la définition produit
# et l'audit, jamais un prix/délai/condition inventé ici — le prix vit dans livre_prix.py,
# distinct). Champs requis vs optionnels distincts : un champ optionnel omis reste None, jamais
# une valeur devinée (AGENTS.md, « fail-closed, jamais une valeur par défaut inventée »).
CHAMPS_FOURNISSEUR_REQUIS = frozenset({"fournisseur_id", "nom"})
CHAMPS_FOURNISSEUR_OPTIONNELS = frozenset(
    {"courriel_commande", "telephone", "categories_vendues", "delai_habituel_jours", "format_commande_prefere"}
)

# PLAN T2.4 — Livre de prix (M6.3) : prix FOURNIS (jamais calculés/inventés), versionnés (chaque
# nouvelle entrée est un maillon append-only de plus, jamais une réécriture), datés
# (date_effet), PAR FOURNISSEUR (fournisseur_id). source_document est nullable : référence une
# facture/un PO d'origine (M6.3, « factures et PO liés ») quand elle existe, None pour un prix
# fourni directement (ex. grille tarifaire du fournisseur).
CHAMPS_ENTREE_PRIX_REQUIS = frozenset({"materiau_id", "fournisseur_id", "prix_unitaire", "devise", "date_effet"})
CHAMPS_ENTREE_PRIX_OPTIONNELS = frozenset({"source_document"})

# PLAN T2.5 point 3 — ligne d'un PO à la création (matériau + quantité demandée) : mêmes DEUX
# clés que CHAMPS_LIGNE_DEMANDEE (reception.py) par cohérence de vocabulaire, mais contrat
# SÉPARÉ et gardé séparément — CHAMPS_LIGNE_DEMANDEE reste le contrat gelé de RECEPTION
# (§2.4 architecture), jamais modifié ici (DA-M6-12 révisée ne touche pas au cycle de réception
# existant, réutilisé sans modification).
CHAMPS_LIGNE_PO = frozenset({"materiau_id", "quantite_demandee"})

# DEFINITION-PRODUIT.md §7 M6.5 (l.508) — les 12 statuts NOMMÉS du moteur de PO, reproduits mot
# pour mot (12 valeurs exactement, comptées : draft, pending_admin_review, approved, email_ready,
# sent_to_supplier, supplier_confirmed, partially_received, received, cancelled, disputed,
# invoiced, closed). frozenset (comme CAUSES_VARIANCE_CHANTIER/TYPES_LIGNE_MATERIAUX_UTILISES
# ci-dessus) : ce sont des noms d'état légaux du produit, pas un verdict que ce paquet invente —
# ajouter un 13e "INDETERMINE" pour satisfaire un vérificateur violerait la liste EXACTE de la
# définition produit (interdiction des données inventées, AGENTS.md).
STATUTS_PO = frozenset(
    {
        "draft",
        "pending_admin_review",
        "approved",
        "email_ready",
        "sent_to_supplier",
        "supplier_confirmed",
        "partially_received",
        "received",
        "cancelled",
        "disputed",
        "invoiced",
        "closed",
    }
)

# Table des transitions légales (bons_commande.py, DA-M6-12 révisée — docs/bmad/03-ARCHITECTURE.md).
# Un dict, jamais un tuple/liste/set au premier niveau : hors du contrôle "énuméré de domaine" de
# conformite.py (qui ne porte que sur les littéraux Tuple/List/Set assignés directement — un Dict
# ne l'est pas), parce que ceci décrit un GRAPHE d'états, pas un verdict calculé par ce paquet.
# États TERMINAUX (aucune clé ci-dessous, donc aucune transition sortante) : cancelled, closed.
# Raccourcis délibérés (même raisonnement que m3_estimation.devis_durable.marquer_devis_accepte,
# qui accepte brouillon OU envoye : aucun outil dédié n'expose encore la sous-étape intermédiaire) :
# - draft -> approved directement (sans passer par pending_admin_review, qu'aucun outil séparé
#   n'expose pour l'instant) ;
# - sent_to_supplier -> partially_received/received directement (sans passer par
#   supplier_confirmed, qu'aucun outil séparé n'expose pour l'instant).
# disputed ne revient jamais vers un statut d'exécution (sent_to_supplier/partially_received/
# received/invoiced) : une fois un litige ouvert, sa résolution reste une décision humaine hors
# machine à états (fermeture ou annulation), jamais une reprise automatique du flux normal.
TRANSITIONS_PO: dict[str, frozenset[str]] = {
    "draft": frozenset({"pending_admin_review", "approved", "cancelled"}),
    "pending_admin_review": frozenset({"approved", "cancelled"}),
    "approved": frozenset({"email_ready", "cancelled"}),
    "email_ready": frozenset({"sent_to_supplier", "cancelled"}),
    "sent_to_supplier": frozenset(
        {"supplier_confirmed", "partially_received", "received", "disputed", "cancelled"}
    ),
    "supplier_confirmed": frozenset({"partially_received", "received", "disputed", "cancelled"}),
    "partially_received": frozenset({"partially_received", "received", "disputed"}),
    "received": frozenset({"invoiced", "disputed"}),
    "invoiced": frozenset({"closed", "disputed"}),
    "disputed": frozenset({"closed", "cancelled"}),
}

VERDICT_PRIX_PO = ("PRIX_LIVRE", "INDETERMINE")

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
