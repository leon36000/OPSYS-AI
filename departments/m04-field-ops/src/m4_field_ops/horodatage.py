"""Validation stricte des horodatages selon le contrat M4-S003, et origine de l'heure d'un fait.

ORIGINE D'UNE HEURE (PLAN T4.27-a2, DEFINITION-PRODUIT §5 P2 : chaque chiffre dit d'où il vient). L'``horodatage`` d'un
maillon de fait a deux origines possibles :

    ``serveur``   l'heure de RÉCEPTION du serveur, posée par la plateforme pendant un appel d'appareil
                  (``opsys.contexte.horodatage_reception()``), jamais par l'appelant ni par un modèle ;
    ``appelant``  l'heure que l'appelant a écrite (un agent, la console, ou un fait inscrit avant T4.27-a2).

Le signe est celui que le pointage écrit depuis T1.4-d : un fait reçu d'un appareil porte l'heure de l'appareil À
CÔTÉ, sous la clé sœur ``horodatage_appareil`` (affichage seulement, jamais lue pour un calcul), et son ``horodatage``
est alors l'heure du serveur. Un fait sans cette clé porte l'heure de l'appelant. ``origine`` ne devine rien : sans la
clé, elle ne dit jamais ``serveur``. Ce module n'a aucune horloge : c'est ``outils.py``, seul, qui décide d'où vient
l'heure qu'il passe aux modules purs.
"""

from datetime import datetime

__all__ = [
    "CLE_HORODATAGE_APPAREIL",
    "ORIGINE_APPELANT",
    "ORIGINE_SERVEUR",
    "origine",
    "valider_horodatage",
]

CLE_HORODATAGE_APPAREIL = "horodatage_appareil"
ORIGINE_SERVEUR = "serveur"
ORIGINE_APPELANT = "appelant"


def valider_horodatage(texte):
    """Retourne `texte` inchangé s'il est un horodatage ISO 8601 avec fuseau.

    Accepte le séparateur espace documenté par datetime.fromisoformat.
    Lève ValueError("REJ-HORODATAGE-INVALIDE") from None dans tous les autres cas.
    """
    if not isinstance(texte, str):
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    try:
        dt = datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    if dt.tzinfo is None:
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    return texte


def origine(maillon):
    """D'où vient l'``horodatage`` de ce maillon de fait : ``serveur`` ou ``appelant``.

    ``serveur`` seulement si le maillon porte l'heure de l'appareil à côté (``horodatage_appareil``, une chaîne non
    vide) : c'est la preuve qu'il a été reçu d'un appareil et que son ``horodatage`` est l'heure de réception du
    serveur. Tout autre maillon (sans la clé, vide, ou pas un dictionnaire) : ``appelant``, l'heure écrite par celui qui
    l'a inscrit. Lecture pure."""
    valeur = maillon.get(CLE_HORODATAGE_APPAREIL) if isinstance(maillon, dict) else None
    if isinstance(valeur, str) and valeur != "":
        return ORIGINE_SERVEUR
    return ORIGINE_APPELANT
