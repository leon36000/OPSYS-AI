CHAMPS_DEFINITION_METRIQUE = frozenset({
    "id",
    "nom",
    "definition",
    "unite",
    "source_donnees",
    "frequence",
    "consommateur",
})

CHAMPS_SNAPSHOT_MODULE = frozenset({"module_source", "horodatage", "valeurs"})

TYPE_SIGNAL_XMR = (
    "HORS_LIMITE_SUPERIEURE",
    "HORS_LIMITE_INFERIEURE",
    "DONNEES_INSUFFISANTES",
)
