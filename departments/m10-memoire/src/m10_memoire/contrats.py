from __future__ import annotations

CHAMPS_EVENEMENT_MEMOIRE = frozenset(
    {
        "evenement",
        "resume",
        "preuves",
        "impact",
        "prochaine_action",
    }
)

CHAMPS_DECISION = frozenset(
    {
        "decision_id",
        "raison",
        "statut",
        "options_ecartees",
    }
)

# Les 12 champs EXACTS du contrat WorkCompletionTriggerV1 gelé par M4
# (m4_field_ops/outbox.py). M10 est un consommateur déclaré de ce contrat.
CHAMPS_WCT = frozenset(
    {
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
    }
)

CHAMPS_REFERENCE_MEMOIRE = frozenset({"ligne_id", "registre", "hash_tete"})

CONSOMMATEUR_ATTENDU = "M10"

ECHAPPATOIRE_INDETERMINE = "indetermine"

# Énumérés fermés de domaine, chacun portant l'échappatoire D-032 : une valeur
# hors énuméré est un REJET nommé, jamais une coercition silencieuse vers
# l'échappatoire — celle-ci est un choix EXPLICITE de l'appelant.
STATUT_DECISION = (
    "proposee",
    "validee",
    "remplacee",
    "annulee",
    ECHAPPATOIRE_INDETERMINE,
)

# Aucune valeur de fusion : réviser n'est jamais fusionner (DA-M10-05). Une
# fusion est irréversible dans un registre append-only.
STATUT_REVISION = (
    "en_attente",
    "distincts_confirmes",
    "obsolete_marquee",
    ECHAPPATOIRE_INDETERMINE,
)
