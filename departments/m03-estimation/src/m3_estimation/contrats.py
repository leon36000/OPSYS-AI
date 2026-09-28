"""Constantes de contrat du module M3-estimation (cahier M3-S001).

Contrat gelé ``LeadQualifie``, marqueur de readiness M2, énuméré fermé des
types de travaux, liste noire des clés interdites et liste blanche du
sous-objet ``contact``. Aucune de ces constantes n'est importée d'un autre
module du dépôt (décision #109) : elles sont copiées et épinglées par les
tests.
"""

__all__ = [
    "CHAMPS_CONTRAT_GELE",
    "CHAMPS_CONTRAT_GELE_V2",
    "VERSION_CONTRAT_V2",
    "CHAMPS_CONTRAT_OPTIONNELS",
    "CHAMPS_UTM",
    "CHAMPS_MARQUEUR",
    "TYPES_TRAVAUX",
    "CLES_INTERDITES",
    "CHAMPS_CONTACT",
    "CHAMPS_SEUILS_QUALITE",
    "CHAMPS_PHOTO",
    "VERDICTS_ESTIMATION",
    "VERDICT_AUCUN_BLOCAGE",
    "VERDICT_QUALITE_ENTREE_INSUFFISANTE",
    "VERDICT_REFERENCE_ECHELLE_ABSENTE",
    "VERDICT_PLANCHER_RENTABILITE_FRANCHI",
    "VERDICT_CONTRAT_ENTREE_INVALIDE",
    "VERDICT_INDETERMINE",
    "CHAMPS_ESTIMATION_V1",
    "CHAMPS_INTERVALLE_CONFIANCE",
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

# Contrat LeadQualifie v2 (PLAN T0.13) : `service` (code de la taxonomie du socle, `opsys.taxonomie`)
# remplace `type_travaux`, et `schema_version` porte la version, EXPLICITE (jamais devinée : un lead
# sans `schema_version` est un lead v1, le contrat gelé v1 n'ayant pas ce champ). Copie épinglée de
# CHAMPS_CONTRAT_GELE_V2 du source departments/m02-revenue-crm/src/m2_revenue_crm/contrats.py, dans
# l'ordre du producteur ; le gate de cohérence du cadrage (docs/bmad/verif_coherence.py, contrôle
# 13 ter) la confronte à M2 et à l'architecture. Les trois clés optionnelles ci-dessous s'y ajoutent
# à l'identique de la v1.
VERSION_CONTRAT_V2 = 2
CHAMPS_CONTRAT_GELE_V2 = (
    "schema_version",
    "lead_id",
    "conversation_id",
    "service",
    "ville",
    "canal",
    "contact",
    "urgence_declaree",
)

# Clés OPTIONNELLES du LeadQualifie (PLAN T2.2) : copie épinglée de CHAMPS_CONTRAT_OPTIONNELS du
# source departments/m02-revenue-crm/src/m2_revenue_crm/contrats.py, dans l'ordre du producteur.
# M2 les accepte si elles sont fournies (provenance marketing déclarée par M7) ; M3 les accepte À
# L'IDENTIQUE — même forme exigée, même refus — sans jamais les exiger, sans leur inventer de
# valeur, et sans s'en servir pour estimer. Le contrat GELÉ reste celui des sept clés ci-dessus.
CHAMPS_CONTRAT_OPTIONNELS = ("source", "utm", "campagne")

# Sous-clés fermées de `utm` : copie épinglée de CLES_UTM du même source M2, dans l'ordre du
# producteur. Nommée CHAMPS_ comme CHAMPS_CONTACT (copie de CLES_CONTACT) : ce sont des noms de
# champs, pas un énuméré de domaine qui appellerait une échappatoire INDETERMINE.
CHAMPS_UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_content")

# Marqueur de readiness M2 : CINQ clés.
CHAMPS_MARQUEUR = (
    "readiness_ok",
    "lead_id",
    "hash_tete_registre",
    "horodatage",
    "empreinte",
)

# Énuméré du contrat GELÉ v1 seulement : les leads v2 n'ont plus d'énuméré local, leur `service`
# est validé contre la taxonomie du socle (`opsys.taxonomie`, profil d'entreprise de l'instance) ;
# aucune copie des services n'existe dans ce paquet.
# Provenance : constante TYPES_TRAVAUX du fichier source
# departments/m02-revenue-crm/src/m2_revenue_crm/contrats.py.
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
# departments/m02-revenue-crm/src/m2_revenue_crm/contrats.py.
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

CHAMPS_ESTIMATION_V1 = (
    "devis_id",
    "lead_id",
    "empreinte_marqueur_m2",
    "niveau_confiance",
    "verdict_estimation",
    "bareme_version",
    "prix_bloque",
    "intervalle_confiance",
    "alerte_plancher",
    "raison_blocage",
    "graine_monte_carlo",
    "hash_maillon",
)

CHAMPS_INTERVALLE_CONFIANCE = (
    "borne_basse",
    "borne_haute",
    "niveau",
)
