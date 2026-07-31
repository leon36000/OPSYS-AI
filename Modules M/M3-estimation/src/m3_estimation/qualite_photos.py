"""Qualification des entrées visuelles du module M3-estimation (cahier M3-S002).

RÈGLE TRANCHÉE : une photo n'est acceptable que si ses DEUX dimensions
atteignent le seuil, soit ``min(largeur, hauteur) >= resolution_minimale``.
Pourquoi : le cadrage déclare largeur et hauteur mais un seuil au singulier ;
le choix fail-closed est retenu — une photo très large mais très plate ne
compense pas la dimension qui manque.

Ce module ne porte AUCUNE valeur de seuil : ils sont fournis par l'appelant
via le contrat gelé ``SeuilsQualite``, exactement comme le barème. Sans seuil
transmis, rien n'est comparé et l'entrée est rejetée — aucune valeur par
défaut n'est inventée.
"""

from . import contrats
from . import verdicts


def _cles_fautives(cles_recues, cles_attendues):
    """Retourne la description triée des clés en plus ou en moins."""
    diff = set(cles_recues).symmetric_difference(cles_attendues)
    return ", ".join(str(cle) for cle in sorted(diff, key=str))


def _rejet_champ_photo(index, champ):
    """Construit le verdict ``REJ-PHOTOS-INVALIDES`` nommant index et champ."""
    return verdicts.construire_verdict(
        "REJ-PHOTOS-INVALIDES",
        detail=f"photo[{index}] : champ fautif {champ}",
    )


def _valider_seuils(seuils):
    """Valide structurellement le contrat gelé ``SeuilsQualite``.

    Retourne ``None`` si les seuils sont exploitables, sinon le verdict
    ``REJ-SEUILS-INVALIDES`` dont le détail nomme la clé fautive.
    """
    if not isinstance(seuils, dict):
        return verdicts.construire_verdict(
            "REJ-SEUILS-INVALIDES",
            detail="seuils n'est pas un dictionnaire",
        )
    if set(seuils) != set(contrats.CHAMPS_SEUILS_QUALITE):
        return verdicts.construire_verdict(
            "REJ-SEUILS-INVALIDES",
            detail=(
                "clé fautive : "
                + _cles_fautives(seuils, contrats.CHAMPS_SEUILS_QUALITE)
            ),
        )
    # type(...) is int : un booléen est refusé car bool est sous-classe de int.
    if type(seuils["resolution_minimale"]) is not int:
        return verdicts.construire_verdict(
            "REJ-SEUILS-INVALIDES",
            detail="clé fautive : resolution_minimale",
        )
    if type(seuils["eclairage_minimal"]) not in (int, float):
        return verdicts.construire_verdict(
            "REJ-SEUILS-INVALIDES",
            detail="clé fautive : eclairage_minimal",
        )
    return None


def _valider_photo(photo, index):
    """Valide structurellement une photo du contrat ``PhotosFournies``.

    Retourne ``None`` si la photo est exploitable, sinon le verdict
    ``REJ-PHOTOS-INVALIDES`` dont le détail nomme l'index de la photo et le
    champ fautif.
    """
    if not isinstance(photo, dict):
        return verdicts.construire_verdict(
            "REJ-PHOTOS-INVALIDES",
            detail=f"photo[{index}] : n'est pas un dictionnaire",
        )
    if set(photo) != set(contrats.CHAMPS_PHOTO):
        return verdicts.construire_verdict(
            "REJ-PHOTOS-INVALIDES",
            detail=(
                f"photo[{index}] : champ fautif "
                + _cles_fautives(photo, contrats.CHAMPS_PHOTO)
            ),
        )
    if not isinstance(photo["photo_id"], str) or not photo["photo_id"].strip():
        return _rejet_champ_photo(index, "photo_id")
    # type(...) is int : un booléen est refusé car bool est sous-classe de int.
    largeur = photo["resolution_largeur"]
    if type(largeur) is not int or largeur <= 0:
        return _rejet_champ_photo(index, "resolution_largeur")
    hauteur = photo["resolution_hauteur"]
    if type(hauteur) is not int or hauteur <= 0:
        return _rejet_champ_photo(index, "resolution_hauteur")
    eclairage = photo["eclairage"]
    if type(eclairage) not in (int, float) or not 0 <= eclairage <= 10:
        return _rejet_champ_photo(index, "eclairage")
    if not isinstance(photo["angle"], str) or not photo["angle"].strip():
        return _rejet_champ_photo(index, "angle")
    reference = photo["reference_echelle"]
    if reference is not None:
        if not isinstance(reference, dict) or set(reference) != {
            "type",
            "dimensions_connues",
        }:
            return _rejet_champ_photo(index, "reference_echelle")
        if not isinstance(reference["type"], str) or not reference["type"].strip():
            return _rejet_champ_photo(index, "reference_echelle.type")
        if type(reference["dimensions_connues"]) is not bool:
            return _rejet_champ_photo(
                index, "reference_echelle.dimensions_connues"
            )
    return None


def qualifier_photos(photos, seuils):
    """Qualifie les entrées visuelles au regard des seuils fournis.

    Ordre ÉPINGLÉ : seuils d'abord, photos ensuite, qualification enfin ;
    rien n'est produit si un contrôle échoue. Retourne ``(qualification,
    None)`` lorsque les entrées sont structurellement valides, ``(None,
    verdict)`` sinon.
    """
    # Sans seuil, on ne compare rien — aucune valeur par défaut n'est inventée.
    rejet = _valider_seuils(seuils)
    if rejet is not None:
        return None, rejet

    if not isinstance(photos, list):
        return None, verdicts.construire_verdict(
            "REJ-PHOTOS-INVALIDES",
            detail="photos n'est pas une liste",
        )
    for index, photo in enumerate(photos):
        rejet = _valider_photo(photo, index)
        if rejet is not None:
            return None, rejet

    resolution_minimale = seuils["resolution_minimale"]
    eclairage_minimal = seuils["eclairage_minimal"]
    elements_manquants = []
    for index, photo in enumerate(photos):
        # RÈGLE TRANCHÉE : la plus petite des deux dimensions est comparée au
        # seuil ; l'acceptation est ``>=``, donc le cas d'égalité est
        # ACCEPTABLE et seul le strictement-inférieur constitue une faiblesse.
        plus_petite_dimension = min(
            photo["resolution_largeur"], photo["resolution_hauteur"]
        )
        if plus_petite_dimension < resolution_minimale:
            elements_manquants.append(
                f"photo[{index}] : résolution constatée sous le seuil fourni "
                f"({plus_petite_dimension} < {resolution_minimale})"
            )
        if photo["eclairage"] < eclairage_minimal:
            elements_manquants.append(
                f"photo[{index}] : éclairage constaté sous le seuil fourni "
                f"({photo['eclairage']} < {eclairage_minimal})"
            )

    if not photos:
        elements_manquants.append("aucune entrée visuelle n'a été fournie")

    if elements_manquants:
        return {
            "photos_acceptables": False,
            "verdict_estimation": "QUALITE_ENTREE_INSUFFISANTE",
            "prix_bloque": True,
            "elements_manquants": elements_manquants,
        }, None
    return {
        "photos_acceptables": True,
        "verdict_estimation": "AUCUN_BLOCAGE",
        "prix_bloque": False,
        "elements_manquants": [],
    }, None


__all__ = [
    "qualifier_photos",
]
