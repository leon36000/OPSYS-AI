"""Hiérarchie des références d'échelle du module M3-estimation (cahier M3-S003).

Ce module classe le niveau de confiance d'une estimation à partir des SEULES
métadonnées des photos fournies : présence et certification d'une référence
d'échelle, valeurs d'angle distinctes, passage des seuils de résolution et
d'éclairage. Aucune image n'est lue, aucun pixel n'est analysé.

DA-M3-05 : M3 n'exécute AUCUN modèle d'inférence visuelle en v1 — ce module
ne charge aucun poids, n'ouvre aucune connexion réseau, ne lance aucun
sous-processus. La hiérarchie ratifiée est appliquée comme une logique de
décision pure sur les métadonnées, rien d'autre.

Pourquoi INDETERMINE existe (échappatoire D-032) : quand les métadonnées ne
permettent aucune classification, M3 dit « on ne sait pas » et bloque le
prix, plutôt que de forcer une valeur optimiste qui serait une précision
inventée. INDETERMINE n'est pas un échec du module : c'est un verdict
honnête.

Comme ``qualite_photos``, ce module ne porte AUCUNE valeur de seuil en
propre : les seuils arrivent par le contrat gelé ``SeuilsQualite`` fourni
par l'appelant. Sans seuil transmis, rien n'est comparé et l'entrée est
rejetée — aucune valeur par défaut n'est inventée.
"""

from . import qualite_photos
from . import verdicts
from . import contrats

# Jeu FERMÉ des quatre niveaux de confiance, déclaré dans l'ordre STRICT de
# la hiérarchie ratifiée : la première règle satisfaite gagne. L'échappatoire
# D-032 (INDETERMINE) ferme le jeu : toute entrée qui ne satisfait aucune des
# trois premières règles y tombe, jamais ailleurs.
NIVEAUX_CONFIANCE = (
    "REFERENCE_ECHELLE",
    "MULTI_VUES",
    "MONO_VUE_BORNES_LARGES",
    contrats.VERDICT_INDETERMINE,
)


def _compter_motifs(photos, resolution_minimale, eclairage_minimal):
    """Parcourt les photos UNE fois et cumule les compteurs de décision.

    Retourne ``(motifs, au_dessus_resolution)`` : le dict de motifs public
    et, à côté, le compteur interne des photos au-dessus du SEUL seuil de
    résolution — la condition de MULTI_VUES ignore l'éclairage, il faut
    donc un compteur distinct de ``photos_au_dessus_du_seuil``.
    """
    photos_avec_reference = 0
    angles_distincts = set()
    au_dessus_resolution = 0
    au_dessus_des_deux_seuils = 0
    for photo in photos:
        reference = photo["reference_echelle"]
        # Piège central du cahier : ``dimensions_connues: False`` déclare une
        # référence dont les dimensions ne sont PAS certifiées. La traiter
        # comme qualifiante donnerait une précision qui n'existe pas : seul
        # le booléen True élève le niveau (le type est garanti par la
        # validation structurelle amont — un non-booléen a déjà été rejeté).
        if (
            isinstance(reference, dict)
            and reference["dimensions_connues"] is True
        ):
            photos_avec_reference += 1
        # Compte les VALEURS d'angle distinctes, jamais les photos : trois
        # photos prises sous le même angle ne font qu'une seule vue.
        angles_distincts.add(photo["angle"])
        # RÈGLE TRANCHÉE reprise de qualite_photos : la PLUS PETITE des deux
        # dimensions est comparée au seuil, acceptation en ``>=`` — le cas
        # d'égalité est ACCEPTABLE, seul le strictement-inférieur échoue.
        resolution_ok = (
            min(photo["resolution_largeur"], photo["resolution_hauteur"])
            >= resolution_minimale
        )
        eclairage_ok = photo["eclairage"] >= eclairage_minimal
        if resolution_ok:
            au_dessus_resolution += 1
        if resolution_ok and eclairage_ok:
            au_dessus_des_deux_seuils += 1
    motifs = {
        # Compte les références QUALIFIANTES : une référence déclarée mais
        # non certifiée n'est pas une référence d'échelle au sens de
        # CA-M3-05 et n'entre donc pas dans ce compteur.
        "photos_avec_reference": photos_avec_reference,
        "angles_distincts": len(angles_distincts),
        # « Au-dessus du seuil » s'entend des DEUX seuils (résolution ET
        # éclairage), cohérent avec l'acceptabilité de qualite_photos.
        "photos_au_dessus_du_seuil": au_dessus_des_deux_seuils,
    }
    return motifs, au_dessus_resolution


def classifier_niveau_confiance(photos, seuils):
    """Classe le niveau de confiance selon la hiérarchie ratifiée.

    Ordre ÉPINGLÉ, identique à ``qualite_photos`` : seuils d'abord, photos
    ensuite, classification enfin ; rien n'est produit si un contrôle
    échoue. Retourne ``(niveau, motifs)`` lorsque les entrées sont
    structurellement valides, ``(None, verdict)`` sinon — JAMAIS une
    exception qui s'échappe.

    La discipline structurelle n'est pas réécrite ici : elle est réutilisée
    depuis ``qualite_photos`` (mêmes clés, mêmes codes
    ``REJ-SEUILS-INVALIDES`` / ``REJ-PHOTOS-INVALIDES``), pour qu'il
    n'existe qu'une seule source de vérité à faire dériver.
    """
    rejet = qualite_photos._valider_seuils(seuils)
    if rejet is not None:
        return None, rejet
    if not isinstance(photos, list):
        return None, verdicts.construire_verdict(
            "REJ-PHOTOS-INVALIDES",
            detail="photos n'est pas une liste",
        )
    for index, photo in enumerate(photos):
        rejet = qualite_photos._valider_photo(photo, index)
        if rejet is not None:
            return None, rejet

    motifs, au_dessus_resolution = _compter_motifs(
        photos,
        seuils["resolution_minimale"],
        seuils["eclairage_minimal"],
    )
    nombre_photos = len(photos)

    # Règle 1 — REFERENCE_ECHELLE : au moins UNE référence qualifiante.
    # Éprouvée EN PREMIER : elle prime même quand tout le reste est faible
    # et même quand MULTI_VUES est pleinement satisfait. Ce qu'elle empêche
    # : qu'une faiblesse des entrées rabatte sur INDETERMINE une estimation
    # qui dispose d'un ancrage métrique certifié.
    if motifs["photos_avec_reference"] >= 1:
        return NIVEAUX_CONFIANCE[0], motifs

    # Règle 2 — MULTI_VUES : au moins 3 photos, au moins 3 valeurs d'angle
    # DISTINCTES, TOUTES les photos au-dessus du seuil de résolution.
    # Ce qu'elle empêche : le comptage des photos à la place des angles
    # distincts (trois « face » ne font pas trois vues), et la moyenne ou la
    # majorité à la place du quantificateur universel (UNE seule photo sous
    # le seuil fait perdre le niveau). La clause « AUCUNE référence
    # qualifiante » est garantie par l'ordre : la règle 1 a déjà retourné.
    if (
        nombre_photos >= 3
        and motifs["angles_distincts"] >= 3
        and au_dessus_resolution == nombre_photos
    ):
        return NIVEAUX_CONFIANCE[1], motifs

    # Règle 3 — MONO_VUE_BORNES_LARGES : 1 ou 2 photos, TOUTES au-dessus du
    # seuil de résolution ET du seuil d'éclairage. Ce qu'elle empêche :
    # l'oubli de la conjonction (une entrée trop sombre ne doit pas donner
    # un niveau optimiste) et l'exigence d'angles distincts, qui n'existe
    # que dans MULTI_VUES. La clause « conditions de MULTI_VUES non
    # réunies » est garantie par l'ordre et par la borne « au plus 2 ».
    if (
        1 <= nombre_photos <= 2
        and motifs["photos_au_dessus_du_seuil"] == nombre_photos
    ):
        return NIVEAUX_CONFIANCE[2], motifs

    # Règle 4 — INDETERMINE (échappatoire D-032) : tout le reste, liste vide
    # comprise. Ce qu'elle empêche : une valeur optimiste par défaut —
    # quand les métadonnées ne permettent aucune classification, M3 dit
    # « on ne sait pas » et bloque le prix.
    return NIVEAUX_CONFIANCE[3], motifs


__all__ = [
    "NIVEAUX_CONFIANCE",
    "classifier_niveau_confiance",
]
