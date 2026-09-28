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

# Registre de métriques (T3.1, docs/departements/M8-audit.md §2 « grain et permissions absents
# du schéma DefinitionMetrique ») : contrat DISTINCT et ADDITIF de CHAMPS_DEFINITION_METRIQUE
# ci-dessus (P5 — ne pas casser). CHAMPS_DEFINITION_METRIQUE décrit ce qu'un module publie dans
# son metrics/*.yaml (compilé à la volée par dictionnaire.py) ; CHAMPS_DEFINITION_REGISTRE
# décrit une entrée du registre DURABLE et VERSIONNÉ que M8 tient sur ce qu'il surveille
# activement (registre_metriques.py) : qui la possède, avec quelle fraîcheur attendue et
# quelles règles de qualité — les deux champs que l'audit signale comme absents aujourd'hui.
CHAMPS_DEFINITION_REGISTRE = frozenset({
    "metric_id",
    "departement_proprietaire",
    "unite",
    "source",
    "fraicheur_attendue_jours",
    "regles_qualite",
})

# Clés obligatoires du sous-objet regles_qualite d'une CHAMPS_DEFINITION_REGISTRE : une plage
# optionnelle (bornes à None = pas de contrainte de ce côté). D'autres familles de règles
# (unicité, cohérence inter-tables…) restent hors périmètre de cette itération — voir le
# rapport de livraison T3.1.
CHAMPS_REGLES_QUALITE = frozenset({"plage_min", "plage_max"})

TYPE_SIGNAL_XMR = (
    "HORS_LIMITE_SUPERIEURE",
    "HORS_LIMITE_INFERIEURE",
    "DONNEES_INSUFFISANTES",
)
