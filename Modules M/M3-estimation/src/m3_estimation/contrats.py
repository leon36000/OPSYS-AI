"""Constantes de contrat du module M3-estimation (cahier M3-S001).

Contrat gelé ``LeadQualifie``, marqueur de readiness M2, énuméré fermé des
types de travaux, liste noire des clés interdites et liste blanche du
sous-objet ``contact``. Aucune de ces constantes n'est importée d'un autre
module du dépôt (décision #109) : elles sont copiées et épinglées par les
tests.
"""

__all__ = [
    "CHAMPS_CONTRAT_GELE",
    "CHAMPS_MARQUEUR",
    "TYPES_TRAVAUX",
    "CLES_INTERDITES",
    "CHAMPS_CONTACT",
]

# Contrat LeadQualifie gelé : SEPT clés, dans l'ordre ratifié.
CHAMPS_CONTRAT_GELE = (
    "lead_id",
    "conversation_id",
    "type_travaux",
    "ville",
    "canal",
    "contact",
    "urgence_declaree",
)

# Marqueur de readiness M2 : CINQ clés.
CHAMPS_MARQUEUR = (
    "readiness_ok",
    "lead_id",
    "hash_tete_registre",
    "horodatage",
    "empreinte",
)

# Provenance : constante TYPES_TRAVAUX du fichier source
# Modules M/M2-revenue-crm/src/m2_revenue_crm/contrats.py.
# Cette copie est épinglée parce que la décision #109 interdit tout import
# inter-modules ; toute dérive entre cette copie et le source M2 est rattrapée
# par un contrôle de CI qui compare les deux listes.
TYPES_TRAVAUX = (
    "renovation_totale",
    "extension",
    "ravalement",
    "isolation_thermique",
    "autre",
)

# Neuf clés interdites, traquées récursivement sur les trois entrées.
CLES_INTERDITES = frozenset(
    {
        "prix",
        "montant",
        "date_execution",
        "engagement",
        "tva",
        "montant_ttc",
        "conditions_paiement",
        "creneau",
        "duree",
    }
)

# Liste blanche fermée du sous-objet ``contact`` : les fixtures des tests
# fournissent exactement {"nom", "telephone"} — rien de plus n'est admis.
CHAMPS_CONTACT = ("nom", "telephone")
