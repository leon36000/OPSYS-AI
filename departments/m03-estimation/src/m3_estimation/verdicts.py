"""Catalogue des identifiants de verdicts stables du module M3.

Patron copié-adapté des catalogues voisins (décision ratifiée : copie, jamais
import — décision #109). Le catalogue est FERMÉ : ``construire_verdict``
refuse tout code qui n'y figure pas en levant ``CodeVerdictInconnu``.

``CODES_M3_LIST`` est un catalogue fermé de codes de rejet techniques, et non
un énuméré de domaine soumis à l'échappatoire ``INDETERMINE`` de D-032.
L'échappatoire ``INDETERMINE`` de D-032 existe pour le cas où le système ne
PEUT PAS classer à l'exécution : il doit alors pouvoir le dire d'un nom et
BLOQUER, plutôt que d'inventer ou de planter. Ce cas existe pour
``NiveauConfiance`` (les photos ne permettent pas de trancher) et pour
``VerdictEstimation`` (l'issue métier est indéterminée). Il n'existe PAS pour
un catalogue de codes de rejet : chaque site de rejet NOMME sa cause, il n'y a
aucun chemin d'exécution où M3 rejette sans savoir pourquoi. Un
``REJ-INDETERMINE`` n'aurait aucun producteur — et ce dépôt compte déjà deux
valeurs de ``VERDICTS_ESTIMATION`` sans producteur, c'est un défaut connu qu'il
ne faut pas reproduire. Le refus par exception vise une erreur de PROGRAMMATION
(un code mal orthographié), pas une lacune de classification.

Ce choix engage le module : si un jour un chemin d'exécution devait rejeter
sans cause nommée, cette décision tomberait et il faudrait une échappatoire.
"""

__all__ = [
    "CODES_M3_LIST",
    "CODES_M3",
    "CodeVerdictInconnu",
    "est_verdict",
    "construire_verdict",
]


class CodeVerdictInconnu(Exception):
    """Levée par construire_verdict lorsque le code demandé ne figure pas dans
    le catalogue M3. Hérite d'Exception pour rester attrapable par les tests
    qui font pytest.raises(Exception).
    """


# Identifiants stables du catalogue M3 — liste FERMÉE, ordre épinglé.
CODES_M3_LIST = [
    "REJ-CLE-INTERDITE",
    "REJ-CONTRAT-INVALIDE",
    "REJ-MARQUEUR-INVALIDE",
    # La readiness est constatée par M3, jamais re-déduite :
    # seul le registre hash-chaîné de M2 fait foi sur la traversée réelle de la gate
    # NOTE D'ANCRE : la phrase d'ancre ci-dessus est une ANCRE comparée mot
    # pour mot par le gate de cohérence du cadrage, et tout reformatage qui
    # la coupe, la reformule ou la répartit sur plusieurs lignes la casse.
    "REJ-READINESS-NON-CONSTATEE",
    "REJ-LEAD-ID-DISCORDANT",
    "REJ-PHOTOS-INVALIDES",
    "REJ-SIGNAL-INVALIDE",
    "REJ-PROFONDEUR-EXCESSIVE",
    # M3-S002 : REJ-SEUILS-INVALIDES est ajouté ; REJ-PHOTOS-INVALIDES figure
    # déjà ci-dessus dans le catalogue et n'est donc pas dupliqué.
    "REJ-SEUILS-INVALIDES",
    # PLAN T2.3-a (devis durable) : codes du module devis_durable.py, jamais utilisés ailleurs.
    "REJ-DEVIS-DEVIS-ID-VIDE",
    "REJ-DEVIS-LEAD-ID-VIDE",
    "REJ-DEVIS-CHANTIER-ID-INVALIDE",
    "REJ-DEVIS-HORODATAGE-VIDE",
    "REJ-DEVIS-LIGNES-VIDES",
    "REJ-DEVIS-LIGNE-INVALIDE",
    "REJ-DEVIS-TAUX-MARGE-MANQUANT",
    "REJ-DEVIS-TAUX-MARGE-INVALIDE",
    "REJ-DEVIS-TOTAL-INCOHERENT",
    "REJ-DEVIS-ID-DEJA-UTILISE",
    "REJ-DEVIS-INTROUVABLE",
    "REJ-DEVIS-TRANSITION-ILLEGALE",
    "REJ-DEVIS-APPROBATEUR-ABSENT",
    "REJ-DEVIS-ROLE-INCONNU",
    # PLAN T1.2-d (estimé vs réel, en second ordre) : codes du module estime_vs_reel.py.
    "REJ-ECART-DEVIS-ID-ABSENT",
    "REJ-ECART-ESTIMATION-ORIGINE-ABSENTE",
    "REJ-ECART-DUREE-ESTIMEE-INVALIDE",
    "REJ-ECART-FILTRE-ABSENT",
    "REJ-ECART-PERIODE-INCOMPLETE",
    "REJ-ECART-PERIODE-INVALIDE",
    # PLAN T2.3 (relance devis sans réponse) : codes du module devis_relance.py.
    "REJ-RELANCE-HORODATAGE-INVALIDE",
    "REJ-RELANCE-DELAI-INVALIDE",
    # PLAN T2.3 (politique Loi 25 « photos ») : code du module politique_photos.py.
    "REJ-PHOTO-POLITIQUE-NON-VALIDEE",
    # PLAN T1.4-c4 (projection par l'identité authentifiée du jeton d'appareil) : codes de
    # l'adaptateur outils.py, jamais utilisés dans un module pur du paquet.
    "REJ-IDENTITE-APPAREIL-INVALIDE",
    "REJ-ROLE-ELARGI",
    # PLAN T2.3-e (besoins matériaux M3 -> M6) : code du module besoins_materiaux.py, dont le
    # ``detail`` nomme la faute (bloc ``materiaux`` du barème, ou contrat de sortie).
    "REJ-BESOINS-MATERIAUX-INVALIDE",
]
CODES_M3 = set(CODES_M3_LIST)


def est_verdict(code):
    """Retourne True si le code fait partie du catalogue M3."""
    return code in CODES_M3


def construire_verdict(code, detail=""):
    """Construit un verdict dictionnaire si le code est reconnu.

    Lève CodeVerdictInconnu dans le cas contraire.
    """
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict invalide : {code!r}")
    return {"code": code, "detail": detail}
