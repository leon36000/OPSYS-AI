"""Tests M3-S002 — qualification des photos (phase RED).

Le sous-module ``m3_estimation.qualite_photos`` n'existe pas encore : ces
tests doivent ÉCHOUER à l'import. Ils définissent le contrat que
l'implémentation devra tenir :

- une photo porte EXACTEMENT six clés : ``photo_id`` (str),
  ``resolution_largeur`` (int > 0), ``resolution_hauteur`` (int > 0),
  ``eclairage`` (float, échelle 0-10), ``angle`` (str) et
  ``reference_echelle`` (dict ou None ; si dict :
  ``{type: str, dimensions_connues: bool}``) ;
- les seuils portent EXACTEMENT deux clés — ``resolution_minimale`` (int) et
  ``eclairage_minimal`` (float) — liste FERMÉE, aucune valeur par défaut ;
- une photo n'est acceptable que si ``min(largeur, hauteur)`` atteint le
  seuil : choix fail-closed, une très grande largeur ne compense jamais une
  hauteur insuffisante ;
- les bornes sont INCLUSIVES : exactement au seuil, la photo est acceptable ;
- toute déviation du contrat de seuils est rejetée ``REJ-SEUILS-INVALIDES``
  et toute photo malformée est rejetée ``REJ-PHOTOS-INVALIDES`` ;
- un lot bien formé mais insuffisant n'est PAS rejeté : il est disqualifié
  (``photos_acceptables`` faux, ``QUALITE_ENTREE_INSUFFISANTE``, prix bloqué,
  éléments manquants non vides).
"""

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Localisation du paquet sous test : insertion du src/ de M3-estimation dans
# sys.path, dérivée de Path(__file__) — JAMAIS depuis le répertoire courant.
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, qualite_photos, verdicts

# ---------------------------------------------------------------------------
# Aides de construction — chaque appel retourne des dictionnaires NEUFS :
# jamais un littéral partagé qu'un test muterait pour les suivants.
# ---------------------------------------------------------------------------


def _photo_valide():
    """Retourne une photo NEUVE conforme au contrat, au-dessus des seuils."""
    return {
        "photo_id": "photo-000",
        "resolution_largeur": 4000,
        "resolution_hauteur": 3000,
        "eclairage": 8.5,
        "angle": "face",
        "reference_echelle": {
            "type": "piece_de_monnaie",
            "dimensions_connues": True,
        },
    }


def _lot_valide():
    """Retourne un lot NEUF de trois photos valides et distinctes.

    La troisième photo n'a pas de référence d'échelle : ``None`` est une
    valeur conforme du contrat, le cas nominal couvre ainsi les deux formes.
    """
    photos = []
    for index, angle in enumerate(("face", "profil", "trois_quarts")):
        photo = _photo_valide()
        photo["photo_id"] = "photo-%03d" % index
        photo["angle"] = angle
        photos.append(photo)
    photos[2]["reference_echelle"] = None
    return photos


def _seuils_valides():
    """Retourne des seuils NEUFS conformes : exactement les deux clés du contrat."""
    return {"resolution_minimale": 800, "eclairage_minimal": 4.0}


def _assert_verdict_rejet(verdict, code_attendu):
    """Asserte qu'un retour est un verdict du catalogue portant le code attendu."""
    assert verdict is not None
    assert verdicts.est_verdict(verdict["code"])
    assert verdict["code"] == code_attendu


# ---------------------------------------------------------------------------
# 1. Cas nominal.
# ---------------------------------------------------------------------------


def test_nominal_lot_valide_accepte():
    """Cas nominal : un lot entièrement au-dessus des deux seuils est accepté.

    Sans ce test, un module qui bloque TOUT passerait tous les cas de blocage.
    """
    qualification, verdict = qualite_photos.qualifier_photos(
        _lot_valide(), _seuils_valides()
    )
    assert verdict is None
    assert qualification is not None
    assert isinstance(qualification["photos_acceptables"], bool)
    assert isinstance(qualification["verdict_estimation"], str)
    assert isinstance(qualification["prix_bloque"], bool)
    assert isinstance(qualification["elements_manquants"], list)
    assert qualification["photos_acceptables"] is True
    assert qualification["prix_bloque"] is False
    assert qualification["elements_manquants"] == []


# ---------------------------------------------------------------------------
# 2. Les trois causes de blocage, chacune ISOLÉE.
# ---------------------------------------------------------------------------


def _lot_vide():
    """Retourne un lot vide : aucune photo transmise."""
    return []


def _lot_avec_resolution_sous_seuil():
    """Retourne un lot NEUF dont une photo est sous le seuil de résolution."""
    lot = _lot_valide()
    lot[1]["resolution_largeur"] = 100
    lot[1]["resolution_hauteur"] = 100
    return lot


def _lot_avec_eclairage_sous_seuil():
    """Retourne un lot NEUF dont une photo est sous le seuil d'éclairage."""
    lot = _lot_valide()
    lot[1]["eclairage"] = 0.5
    return lot


@pytest.mark.parametrize(
    "fabriquer_lot",
    (
        _lot_vide,
        _lot_avec_resolution_sous_seuil,
        _lot_avec_eclairage_sous_seuil,
    ),
    ids=("liste-vide", "resolution-sous-seuil", "eclairage-sous-seuil"),
)
def test_blocages_causes_isolees(fabriquer_lot):
    """Chaque cause de blocage, ISOLÉE, disqualifie le lot et bloque le prix.

    L'entrée est bien formée mais insuffisante : ce n'est PAS un rejet, le
    retour est une qualification dont le verdict d'estimation vaut
    ``QUALITE_ENTREE_INSUFFISANTE``.
    """
    qualification, verdict = qualite_photos.qualifier_photos(
        fabriquer_lot(), _seuils_valides()
    )
    assert verdict is None
    assert qualification is not None
    assert qualification["photos_acceptables"] is False
    assert qualification["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert qualification["prix_bloque"] is True
    assert qualification["elements_manquants"] != []
    assert all(
        isinstance(element, str)
        for element in qualification["elements_manquants"]
    )


# ---------------------------------------------------------------------------
# 3. La dimension plate — ambiguïté tranchée, choix fail-closed.
# ---------------------------------------------------------------------------


def test_photo_plate_largeur_ne_compense_pas_hauteur():
    """Choix fail-closed retenu : une photo très large mais très plate est FAIBLE.

    Le seuil est au singulier, la photo déclare deux dimensions : c'est
    ``min(largeur, hauteur) >= resolution_minimale`` qui décide. Une très
    grande largeur ne compense JAMAIS une hauteur sous le seuil.
    """
    lot = _lot_valide()
    lot[0]["resolution_largeur"] = 8000
    lot[0]["resolution_hauteur"] = 200
    qualification, verdict = qualite_photos.qualifier_photos(
        lot, _seuils_valides()
    )
    assert verdict is None
    assert qualification is not None
    assert qualification["photos_acceptables"] is False
    assert qualification["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert qualification["prix_bloque"] is True
    assert qualification["elements_manquants"] != []


# ---------------------------------------------------------------------------
# 4. Les bornes — tests distincts, bornes INCLUSIVES.
# ---------------------------------------------------------------------------


def test_borne_resolution_exactement_au_seuil_acceptable():
    """Résolution EXACTEMENT au seuil : la photo reste ACCEPTABLE.

    La comparaison est ``>=`` et non ``>`` : seule l'égalité démasque une
    implémentation qui utiliserait une borne stricte.
    """
    seuils = _seuils_valides()
    lot = _lot_valide()
    lot[0]["resolution_largeur"] = seuils["resolution_minimale"]
    lot[0]["resolution_hauteur"] = seuils["resolution_minimale"]
    qualification, verdict = qualite_photos.qualifier_photos(lot, seuils)
    assert verdict is None
    assert qualification is not None
    assert qualification["photos_acceptables"] is True
    assert qualification["prix_bloque"] is False
    assert qualification["elements_manquants"] == []


def test_borne_resolution_un_pixel_sous_seuil_faible():
    """Un pixel EN DESSOUS du seuil de résolution : la photo devient FAIBLE."""
    seuils = _seuils_valides()
    lot = _lot_valide()
    lot[0]["resolution_largeur"] = seuils["resolution_minimale"] - 1
    lot[0]["resolution_hauteur"] = seuils["resolution_minimale"] - 1
    qualification, verdict = qualite_photos.qualifier_photos(lot, seuils)
    assert verdict is None
    assert qualification is not None
    assert qualification["photos_acceptables"] is False
    assert qualification["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert qualification["prix_bloque"] is True
    assert qualification["elements_manquants"] != []


def test_borne_eclairage_exactement_au_seuil_acceptable():
    """Éclairage EXACTEMENT au seuil : la photo reste ACCEPTABLE (borne inclusive)."""
    seuils = _seuils_valides()
    lot = _lot_valide()
    lot[0]["eclairage"] = seuils["eclairage_minimal"]
    qualification, verdict = qualite_photos.qualifier_photos(lot, seuils)
    assert verdict is None
    assert qualification is not None
    assert qualification["photos_acceptables"] is True
    assert qualification["prix_bloque"] is False
    assert qualification["elements_manquants"] == []


def test_borne_eclairage_sous_seuil_faible():
    """Éclairage EN DESSOUS du seuil : la photo devient FAIBLE."""
    seuils = _seuils_valides()
    lot = _lot_valide()
    lot[0]["eclairage"] = seuils["eclairage_minimal"] - 0.1
    qualification, verdict = qualite_photos.qualifier_photos(lot, seuils)
    assert verdict is None
    assert qualification is not None
    assert qualification["photos_acceptables"] is False
    assert qualification["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert qualification["prix_bloque"] is True
    assert qualification["elements_manquants"] != []


# ---------------------------------------------------------------------------
# 5. Contrat de seuils fail-closed — liste FERMÉE, aucune valeur par défaut.
# ---------------------------------------------------------------------------


def _seuils_none():
    """Seuils absents : ``None`` au lieu du dictionnaire."""
    return None


def _seuils_dict_vide():
    """Seuils vides : aucune des deux clés requises."""
    return {}


def _seuils_sans_eclairage():
    """Seuils incomplets : seule ``resolution_minimale`` est présente."""
    return {"resolution_minimale": 800}


def _seuils_sans_resolution():
    """Seuils incomplets : seule ``eclairage_minimal`` est présente."""
    return {"eclairage_minimal": 4.0}


def _seuils_avec_cle_inconnue():
    """Seuils portant une clé INCONNUE en plus des deux clés du contrat."""
    seuils = _seuils_valides()
    seuils["seuil_inconnu"] = 1
    return seuils


def _seuils_resolution_en_chaine():
    """Seuils dont ``resolution_minimale`` est une chaîne et non un entier."""
    return {"resolution_minimale": "800", "eclairage_minimal": 4.0}


def _seuils_eclairage_en_chaine():
    """Seuils dont ``eclairage_minimal`` est une chaîne et non un flottant."""
    return {"resolution_minimale": 800, "eclairage_minimal": "4.0"}


@pytest.mark.parametrize(
    "fabriquer_seuils",
    (
        _seuils_none,
        _seuils_dict_vide,
        _seuils_sans_eclairage,
        _seuils_sans_resolution,
        _seuils_avec_cle_inconnue,
        _seuils_resolution_en_chaine,
        _seuils_eclairage_en_chaine,
    ),
    ids=(
        "none",
        "dict-vide",
        "sans-eclairage",
        "sans-resolution",
        "cle-inconnue",
        "resolution-en-chaine",
        "eclairage-en-chaine",
    ),
)
def test_seuils_invalides_rejetes(fabriquer_seuils):
    """Toute déviation du contrat de seuils est rejetée ``REJ-SEUILS-INVALIDES``.

    Le retour est ``(None, verdict)`` : jamais de valeur par défaut, jamais
    de clé tolérée en plus ou en moins, jamais de type converti en silence.
    """
    qualification, verdict = qualite_photos.qualifier_photos(
        _lot_valide(), fabriquer_seuils()
    )
    assert qualification is None
    _assert_verdict_rejet(verdict, "REJ-SEUILS-INVALIDES")


# ---------------------------------------------------------------------------
# 6. Photos malformées — rejet ``REJ-PHOTOS-INVALIDES``.
# ---------------------------------------------------------------------------


def _lot_photo_non_dict():
    """Lot dont la « photo » n'est pas un dictionnaire."""
    return ["ceci-n-est-pas-une-photo"]


def _lot_photo_cle_manquante():
    """Lot dont la photo a perdu une clé requise (``angle``)."""
    photo = _photo_valide()
    del photo["angle"]
    return [photo]


def _lot_photo_cle_inconnue():
    """Lot dont la photo porte une clé inconnue en plus des six du contrat."""
    photo = _photo_valide()
    photo["cle_inconnue"] = "valeur"
    return [photo]


def _lot_photo_largeur_zero():
    """Lot dont la photo a une ``resolution_largeur`` à zéro."""
    photo = _photo_valide()
    photo["resolution_largeur"] = 0
    return [photo]


def _lot_photo_largeur_negative():
    """Lot dont la photo a une ``resolution_largeur`` négative."""
    photo = _photo_valide()
    photo["resolution_largeur"] = -100
    return [photo]


def _lot_photo_eclairage_hors_echelle():
    """Lot dont la photo a un ``eclairage`` à 11, hors de l'échelle 0-10."""
    photo = _photo_valide()
    photo["eclairage"] = 11.0
    return [photo]


@pytest.mark.parametrize(
    "fabriquer_lot",
    (
        _lot_photo_non_dict,
        _lot_photo_cle_manquante,
        _lot_photo_cle_inconnue,
        _lot_photo_largeur_zero,
        _lot_photo_largeur_negative,
        _lot_photo_eclairage_hors_echelle,
    ),
    ids=(
        "photo-non-dict",
        "cle-manquante",
        "cle-inconnue",
        "largeur-zero",
        "largeur-negative",
        "eclairage-hors-echelle",
    ),
)
def test_photos_malformees_rejetees(fabriquer_lot):
    """Toute photo malformée est rejetée : ``(None, verdict)`` ``REJ-PHOTOS-INVALIDES``."""
    qualification, verdict = qualite_photos.qualifier_photos(
        fabriquer_lot(), _seuils_valides()
    )
    assert qualification is None
    _assert_verdict_rejet(verdict, "REJ-PHOTOS-INVALIDES")


# ---------------------------------------------------------------------------
# 7. Le catalogue reste fermé.
# ---------------------------------------------------------------------------


def test_catalogue_ferme_contient_les_codes_de_rejet():
    """Les deux codes de rejet exercés ici appartiennent à ``CODES_M3_LIST``."""
    assert "REJ-SEUILS-INVALIDES" in verdicts.CODES_M3_LIST
    assert "REJ-PHOTOS-INVALIDES" in verdicts.CODES_M3_LIST
