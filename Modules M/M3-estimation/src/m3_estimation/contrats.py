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
# Provenance : cette liste n'a AUCUNE contrepartie chez M2 — c'est une
# frontière PROPRE à M3, ratifiée par le critère CA-M3-22 : le prix est la
# SORTIE de M3 et jamais son entrée, les dates appartiennent à M4. Elle se
# dérive donc du critère, pas d'un module voisin, et c'est pourquoi elle n'a
# volontairement AUCUN test de non-dérive : il n'y a rien à quoi la
# confronter, et un futur relecteur ne doit pas chercher un test qui ne doit
# pas exister.
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

# Liste blanche fermée du sous-objet ``contact`` : les TROIS clés que M2
# émet, dans l'ordre du producteur.
# Provenance : constante CLES_CONTACT du fichier source
# Modules M/M2-revenue-crm/src/m2_revenue_crm/contrats.py.
# Cette copie est épinglée parce que la décision #109 interdit tout import
# inter-modules ; toute dérive entre cette copie et le source M2 est rattrapée
# par un contrôle de CI qui compare les deux listes. Cette liste blanche se
# dérive du PRODUCTEUR, jamais des fixtures de test : une liste blanche
# dérivée des tests ferait rejeter par le consommateur des contacts
# légitimes portant ``courriel``.
CHAMPS_CONTACT = ("nom", "telephone", "courriel")

# Provenance : constante tirée de la section ``SeuilsQualite`` de
# l'architecture M3 (cadrage). Liste FERMÉE : aucune clé en plus, aucune
# valeur par défaut.
CHAMPS_SEUILS_QUALITE = ("resolution_minimale", "eclairage_minimal")

# Provenance : constante tirée de la section ``PhotosFournies`` de
# l'architecture M3 (cadrage). Liste FERMÉE : aucune clé en plus, aucune
# valeur par défaut.
CHAMPS_PHOTO = ("photo_id", "resolution_largeur", "resolution_hauteur",
                "eclairage", "angle", "reference_echelle")

# Copie épinglée de l'énuméré ``VerdictEstimation`` de ``03-ARCHITECTURE.md``
# section 2.5 : un test de non-divergence l'extrait de la source et confronte
# les deux listes, parce qu'une copie qu'on ne confronte pas dérive en silence.
VERDICTS_ESTIMATION = (
    "AUCUN_BLOCAGE",
    "QUALITE_ENTREE_INSUFFISANTE",
    "REFERENCE_ECHELLE_ABSENTE",
    "PLANCHER_RENTABILITE_FRANCHI",
    "CONTRAT_ENTREE_INVALIDE",
    "INDETERMINE",
)

# Noms canoniques des verdicts d'estimation : la SEULE façon de désigner un
# verdict dans le paquet. Chaque nom est DÉRIVÉ du tuple par son indice —
# jamais réécrit en littéral — : il ne peut donc pas diverger de
# ``VERDICTS_ESTIMATION``, et une faute de frappe sur le nom devient une
# erreur d'import, visible immédiatement et non au premier passage sur le
# chemin concerné.
VERDICT_AUCUN_BLOCAGE = VERDICTS_ESTIMATION[0]
VERDICT_QUALITE_ENTREE_INSUFFISANTE = VERDICTS_ESTIMATION[1]
VERDICT_REFERENCE_ECHELLE_ABSENTE = VERDICTS_ESTIMATION[2]
VERDICT_PLANCHER_RENTABILITE_FRANCHI = VERDICTS_ESTIMATION[3]
VERDICT_CONTRAT_ENTREE_INVALIDE = VERDICTS_ESTIMATION[4]
VERDICT_INDETERMINE = VERDICTS_ESTIMATION[5]
