"""Tests de la hiérarchie des références d'échelle (cahier M3-S003).

Ces tests verrouillent la fonction
``hierarchie_echelle.classifier_niveau_confiance`` : les QUATRE niveaux
fermés (REFERENCE_ECHELLE, MULTI_VUES, MONO_VUE_BORNES_LARGES, INDETERMINE),
l'ordre de la hiérarchie (la première règle satisfaite gagne), le rejet
contrôlé ``(None, verdict)`` avec des codes du catalogue existant — aucun
nouveau code —, et la preuve statique d'absence de modèle d'inférence
(DA-M3-05) par analyse AST de la source.

Le module ``m3_estimation/hierarchie_echelle.py`` n'existe pas encore :
ce fichier doit ÉCHOUER à l'exécution — c'est le RED attendu de la story.
"""

import ast
import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from m3_estimation import contrats, hierarchie_echelle, verdicts

# Jeu FERMÉ des quatre niveaux de confiance (échappatoire D-032 incluse).
NIVEAUX_FERMES = frozenset(
    {
        "REFERENCE_ECHELLE",
        "MULTI_VUES",
        "MONO_VUE_BORNES_LARGES",
        "INDETERMINE",
    }
)

# Imports interdits par DA-M3-05 : ni réseau, ni chargement de poids de
# modèle. La classification est un calcul local sur les entrées fournies.
IMPORTS_INTERDITS = frozenset(
    {
        "socket",
        "urllib",
        "requests",
        "http",
        "torch",
        "tensorflow",
        "onnx",
        "cv2",
        "numpy",
        "subprocess",
    }
)

# Seuils nominaux des tests : resolution_minimale (int) et
# eclairage_minimal (float), la forme exacte du contrat gelé SeuilsQualite.
_SEUILS = {"resolution_minimale": 800, "eclairage_minimal": 5.0}


def _photo_valide(**surcharges):
    """Fabrique une photo valide, au-dessus des deux seuils nominaux.

    Chaque test ne surcharge QUE ce qu'il fait varier ; tout le reste reste
    la photo nominale : 1200x900, éclairage 7.0, angle « face », aucune
    référence d'échelle.
    """
    photo = {
        "photo_id": "photo-nominale",
        "resolution_largeur": 1200,
        "resolution_hauteur": 900,
        "eclairage": 7.0,
        "angle": "face",
        "reference_echelle": None,
    }
    photo.update(surcharges)
    return photo


def test_la_fabrique_respecte_les_contrats_geles():
    """La fabrique locale produit exactement les clés du contrat gelé
    ``PhotosFournies``, et les seuils nominaux celles de ``SeuilsQualite``.

    Empêcherait de casser : une dérive silencieuse entre les fixtures de
    test et les contrats gelés (clé renommée, clé ajoutée ou retirée), qui
    rendrait tous les autres tests caducs sans qu'aucun ne s'en aperçoive.
    """
    assert set(_photo_valide()) == set(contrats.CHAMPS_PHOTO)
    assert set(_SEUILS) == set(contrats.CHAMPS_SEUILS_QUALITE)


def test_dimensions_connues_false_n_est_pas_une_reference_qualifiante():
    """Piège central : référence DÉCLARÉE mais dimensions NON certifiées.

    Empêcherait de casser : la confusion entre « référence présente » et
    « référence d'échelle au sens de CA-M3-05 » — un dict
    ``reference_echelle`` dont ``dimensions_connues`` vaut False ne doit
    PAS faire monter le niveau à REFERENCE_ECHELLE ; la photo restant
    exploitable (une seule, au-dessus des deux seuils), le niveau attendu
    est MONO_VUE_BORNES_LARGES.
    """
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        [
            _photo_valide(
                reference_echelle={
                    "type": "feuille_a4",
                    "dimensions_connues": False,
                }
            )
        ],
        _SEUILS,
    )
    assert niveau != "REFERENCE_ECHELLE"
    assert niveau == "MONO_VUE_BORNES_LARGES"
    assert motifs["photos_au_dessus_du_seuil"] == 1


def test_angles_repetes_ne_satisfont_pas_multi_vues():
    """Trois photos ou plus mais angles RÉPÉTÉS (« face » trois fois).

    Empêcherait de casser : le comptage des photos à la place du comptage
    des valeurs d'angle DISTINCTES — la condition multi-vues n'est pas
    remplie, et trois photos excluent la mono-vue : le niveau doit
    retomber sur INDETERMINE, jamais sur MULTI_VUES.
    """
    photos = [
        _photo_valide(angle="face"),
        _photo_valide(angle="face"),
        _photo_valide(angle="face"),
    ]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau == "INDETERMINE"
    assert motifs["angles_distincts"] == 1
    assert motifs["photos_au_dessus_du_seuil"] == 3


def test_multi_vues_exige_toutes_les_photos_au_dessus_du_seuil():
    """Trois photos, trois angles distincts, UNE sous le seuil de
    résolution.

    Empêcherait de casser : une moyenne ou une majorité à la place du
    quantificateur universel « TOUTES les photos au-dessus du seuil » —
    une seule photo sous le seuil de résolution doit faire perdre
    MULTI_VUES, et trois photos excluent la mono-vue : INDETERMINE.
    """
    photos = [
        _photo_valide(angle="face"),
        _photo_valide(angle="profil"),
        _photo_valide(angle="dessus", resolution_largeur=799),
    ]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau == "INDETERMINE"
    assert motifs["angles_distincts"] == 3
    assert motifs["photos_au_dessus_du_seuil"] == 2


def test_eclairage_sous_le_seuil_exclut_mono_vue_bornes_larges():
    """Une photo au-dessus du seuil de résolution mais SOUS le seuil
    d'éclairage.

    Empêcherait de casser : l'oubli de la conjonction « résolution ET
    éclairage » dans MONO_VUE_BORNES_LARGES — une entrée trop sombre ne
    doit pas donner un niveau optimiste ; le niveau doit être
    INDETERMINE.
    """
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        [_photo_valide(eclairage=4.0)],
        _SEUILS,
    )
    assert niveau == "INDETERMINE"
    assert motifs["angles_distincts"] == 1


def test_liste_de_photos_vide_produit_indetermine_sans_plantage():
    """Liste de photos VIDE.

    Empêcherait de casser : un plantage (parcours sur liste vide non
    protégé) ou une valeur optimiste par défaut — l'échappatoire D-032
    doit rendre INDETERMINE avec tous les compteurs à zéro, sans
    exception.
    """
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        [], _SEUILS
    )
    assert niveau == "INDETERMINE"
    assert motifs == {
        "photos_avec_reference": 0,
        "angles_distincts": 0,
        "photos_au_dessus_du_seuil": 0,
    }


def test_reference_qualifiante_prime_meme_si_tout_le_reste_est_faible():
    """La hiérarchie place REFERENCE_ECHELLE en tête : une seule photo,
    sous les DEUX seuils, mais portant une référence qualifiante.

    Empêcherait de casser : un réordonnancement qui laisserait la
    faiblesse des entrées rabattre le niveau sur INDETERMINE alors qu'une
    référence d'échelle qualifiante (dict avec dimensions_connues True)
    existe.
    """
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        [
            _photo_valide(
                resolution_largeur=100,
                resolution_hauteur=100,
                eclairage=0.5,
                reference_echelle={
                    "type": "regle",
                    "dimensions_connues": True,
                },
            )
        ],
        _SEUILS,
    )
    assert niveau == "REFERENCE_ECHELLE"
    assert motifs["photos_avec_reference"] >= 1
    assert motifs["photos_au_dessus_du_seuil"] == 0


def test_egalite_exacte_aux_seuils_est_acceptable():
    """Cas d'ÉGALITÉ au seuil : ``>=``, cohérent avec ``qualite_photos``.

    Empêcherait de casser : une comparaison stricte ``>`` qui rejetterait
    une photo exactement au seuil — la résolution exactement égale au
    seuil est ACCEPTABLE, et l'éclairage exactement égal l'est aussi.
    """
    # Mono-vue : résolution ET éclairage exactement aux seuils.
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        [
            _photo_valide(
                resolution_largeur=800,
                resolution_hauteur=800,
                eclairage=5.0,
            )
        ],
        _SEUILS,
    )
    assert niveau == "MONO_VUE_BORNES_LARGES"
    assert motifs["photos_au_dessus_du_seuil"] == 1

    # Multi-vues : trois photos exactement au seuil de résolution.
    photos = [
        _photo_valide(
            resolution_largeur=800, resolution_hauteur=800, angle="face"
        ),
        _photo_valide(
            resolution_largeur=800, resolution_hauteur=800, angle="profil"
        ),
        _photo_valide(
            resolution_largeur=800, resolution_hauteur=800, angle="dessus"
        ),
    ]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau == "MULTI_VUES"
    assert motifs["photos_au_dessus_du_seuil"] == 3


@pytest.mark.parametrize(
    "scenarios",
    [
        [
            (
                "reference_qualifiante_seule_photo",
                [
                    _photo_valide(
                        reference_echelle={
                            "type": "regle",
                            "dimensions_connues": True,
                        }
                    )
                ],
                "REFERENCE_ECHELLE",
            ),
            (
                "trois_photos_trois_angles_distincts",
                [
                    _photo_valide(angle="face"),
                    _photo_valide(angle="profil"),
                    _photo_valide(angle="dessus"),
                ],
                "MULTI_VUES",
            ),
            (
                "deux_photos_au_dessus_des_deux_seuils",
                [
                    _photo_valide(angle="face"),
                    _photo_valide(angle="profil"),
                ],
                "MONO_VUE_BORNES_LARGES",
            ),
            (
                "une_seule_photo_borne_basse_de_la_mono_vue",
                [_photo_valide(angle="face")],
                "MONO_VUE_BORNES_LARGES",
            ),
            (
                "liste_vide_chemin_degenere",
                [],
                "INDETERMINE",
            ),
            (
                "trois_photos_angle_repete_cas_nominal_indetermine",
                [
                    _photo_valide(angle="face"),
                    _photo_valide(angle="face"),
                    _photo_valide(angle="face"),
                ],
                "INDETERMINE",
            ),
        ]
    ],
    ids=["six_scenarios_couvrant_les_quatre_niveaux_fermes"],
)
def test_niveau_toujours_dans_le_jeu_ferme_sur_entrees_variees(scenarios):
    """Aucune valeur retournée hors des QUATRE niveaux fermés, et les
    quatre niveaux restent atteignables sur des entrées VARIÉES.

    Empêcherait de casser : l'apparition d'un cinquième niveau (faute de
    frappe, niveau renommé, échappatoire D-032 contournée) — chaque niveau
    produit doit appartenir au jeu fermé déclaré par le module
    (``NIVEAUX_CONFIANCE``), et les quatre niveaux doivent rester
    atteignables.

    La portée du test doit être aussi large que son nom le promet : la
    borne basse de MONO_VUE_BORNES_LARGES (UNE SEULE photo, énoncée par
    CA-M3-07) et le cas nominal de l'échappatoire D-032 (des photos
    PRÉSENTES qui ne satisfont aucune règle) manquaient — un INDETERMINE
    obtenu seulement par liste vide est un chemin dégénéré, pas le cas
    nominal de l'échappatoire. Six scénarios identifiés éprouvent donc
    les quatre niveaux, et chacun porte son niveau attendu.
    """
    niveaux_obtenus = set()
    for identifiant, photos, attendu in scenarios:
        niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
            photos, _SEUILS
        )
        assert niveau in hierarchie_echelle.NIVEAUX_CONFIANCE, identifiant
        assert niveau == attendu, identifiant
        niveaux_obtenus.add(niveau)
    assert niveaux_obtenus == NIVEAUX_FERMES


def test_photos_qui_ne_sont_pas_une_liste_sont_rejetees():
    """Entrée ``photos`` qui n'est pas une liste.

    Empêcherait de casser : la remontée d'une exception nue au lieu du
    rejet contrôlé ``(None, verdict)`` — le verdict doit réutiliser le
    code du catalogue REJ-PHOTOS-INVALIDES, avec la même structure que
    celle produite par la fabrique du catalogue, AUCUN nouveau code.
    """
    niveau, verdict = hierarchie_echelle.classifier_niveau_confiance(
        "pas-une-liste", _SEUILS
    )
    gabarit = verdicts.construire_verdict(
        "REJ-PHOTOS-INVALIDES", detail="sonde de structure"
    )
    assert niveau is None
    assert set(verdict) == set(gabarit)
    assert verdict["code"] == "REJ-PHOTOS-INVALIDES"


def test_seuils_amputes_d_une_cle_sont_rejetes():
    """Entrée ``seuils`` amputée d'une clé du contrat gelé SeuilsQualite.

    Empêcherait de casser : l'invention d'une valeur par défaut pour la
    clé manquante (le module ne porte AUCUN seuil en propre, exactement
    comme ``qualite_photos``) — l'absence de ``eclairage_minimal`` doit
    produire ``(None, verdict)`` avec le code du catalogue
    REJ-SEUILS-INVALIDES, jamais une classification.
    """
    seuils_amputes = {"resolution_minimale": 800}
    niveau, verdict = hierarchie_echelle.classifier_niveau_confiance(
        [_photo_valide()], seuils_amputes
    )
    gabarit = verdicts.construire_verdict(
        "REJ-SEUILS-INVALIDES", detail="sonde de structure"
    )
    assert niveau is None
    assert set(verdict) == set(gabarit)
    assert verdict["code"] == "REJ-SEUILS-INVALIDES"


def test_aucun_import_reseau_ni_modele_d_inference():
    """Preuve STATIQUE d'absence de modèle d'inférence (DA-M3-05), par AST.

    Empêcherait de casser : l'introduction d'un import réseau (socket,
    urllib, requests, http), d'un sous-processus ou d'un moteur de poids
    (torch, tensorflow, onnx, cv2, numpy) dans le module — la
    classification doit rester un calcul local sur les entrées fournies.
    La preuve est faite en parcourant ``ast.walk`` sur ``ast.Import`` et
    ``ast.ImportFrom`` : un nom cité dans un commentaire n'est PAS un
    import, et les imports relatifs intra-paquet (``from . import ...``)
    sont exclus par construction (``level`` non nul).
    """
    source = Path(hierarchie_echelle.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                importes.add(alias.name.split(".")[0])
        elif isinstance(noeud, ast.ImportFrom):
            if noeud.level == 0 and noeud.module is not None:
                importes.add(noeud.module.split(".")[0])
    assert IMPORTS_INTERDITS.isdisjoint(importes)


def test_multi_vues_nominal_trois_photos_trois_angles_distincts():
    """Cas nominal MULTI_VUES : 3 photos, 3 angles distincts, toutes
    au-dessus du seuil de résolution, aucune référence d'échelle.

    Empêcherait de casser : une condition supplémentaire inventée (par
    exemple un seuil d'éclairage dans MULTI_VUES, ou l'exigence que les
    angles couvrent des valeurs précises) qui ferait échouer le cas
    nominal ratifié.
    """
    photos = [
        _photo_valide(angle="face"),
        _photo_valide(angle="profil"),
        _photo_valide(angle="dessus"),
    ]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau == "MULTI_VUES"
    assert motifs == {
        "photos_avec_reference": 0,
        "angles_distincts": 3,
        "photos_au_dessus_du_seuil": 3,
    }


def test_mono_vue_bornes_larges_nominal_deux_photos():
    """Cas nominal MONO_VUE_BORNES_LARGES : 2 photos au-dessus des deux
    seuils, aucune référence qualifiante, angles identiques.

    Empêcherait de casser : l'exigence d'angles distincts dans la
    mono-vue — cette condition n'existe que dans MULTI_VUES ; deux photos
    prises sous le même angle restent une mono-vue exploitable.
    """
    photos = [
        _photo_valide(angle="face"),
        _photo_valide(angle="face"),
    ]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau == "MONO_VUE_BORNES_LARGES"
    assert motifs["photos_au_dessus_du_seuil"] == 2
    assert motifs["angles_distincts"] == 1


def test_reference_qualifiante_prime_sur_multi_vues_satisfait():
    """Ordre de la hiérarchie : REFERENCE_ECHELLE est éprouvée en premier.

    Empêcherait de casser : un réordonnancement qui laisserait MULTI_VUES
    (pourtant pleinement satisfait : 3 photos, 3 angles distincts, toutes
    au-dessus du seuil) masquer une référence d'échelle qualifiante — la
    première règle satisfaite gagne.
    """
    photos = [
        _photo_valide(
            angle="face",
            reference_echelle={
                "type": "porte_standard",
                "dimensions_connues": True,
            },
        ),
        _photo_valide(angle="profil"),
        _photo_valide(angle="dessus"),
    ]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau == "REFERENCE_ECHELLE"
    assert motifs["angles_distincts"] == 3
    assert motifs["photos_avec_reference"] >= 1


def test_reference_non_certifiee_ne_bloque_pas_multi_vues():
    """Une référence déclarée mais NON certifiée ne doit ni élever vers
    REFERENCE_ECHELLE ni interdire MULTI_VUES.

    Empêcherait de casser : le test « référence présente » à la place du
    test « référence QUALIFIANTE » dans la clause « AUCUNE référence
    d'échelle qualifiante » de MULTI_VUES — une référence dont
    ``dimensions_connues`` vaut False laisse MULTI_VUES accessible.
    """
    photos = [
        _photo_valide(
            angle="face",
            reference_echelle={
                "type": "feuille_a4",
                "dimensions_connues": False,
            },
        ),
        _photo_valide(angle="profil"),
        _photo_valide(angle="dessus"),
    ]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau == "MULTI_VUES"
    assert motifs["angles_distincts"] == 3


def test_un_tuple_de_photos_valides_est_refuse():
    """Un tuple dont CHAQUE élément est une photo parfaitement valide doit
    être refusé : seule une ``list`` est acceptée pour ``photos``.

    Empêcherait de casser : sans ce cas, la garde de type de la collection
    est indétectable — un test qui passe une non-liste dont les ÉLÉMENTS
    sont invalides est vert grâce à une garde ultérieure, pas grâce à
    celle qu'il prétend viser (mesuré : sa suppression laisse la suite
    VERTE). Ici, aucun élément ne peut être rejeté individuellement :
    seul le contrôle ``isinstance(photos, list)`` peut produire le rejet
    ``(None, verdict)`` avec le code du catalogue REJ-PHOTOS-INVALIDES.
    """
    photos = (
        _photo_valide(angle="face"),
        _photo_valide(angle="profil"),
        _photo_valide(angle="dessus"),
    )
    niveau, verdict = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    gabarit = verdicts.construire_verdict(
        "REJ-PHOTOS-INVALIDES", detail="sonde de structure"
    )
    assert niveau is None
    assert set(verdict) == set(gabarit)
    assert verdict["code"] == "REJ-PHOTOS-INVALIDES"


@pytest.mark.parametrize(
    "position_fautive",
    [0, 2],
    ids=["fautive_en_premiere_position", "fautive_en_derniere_position"],
)
def test_une_photo_invalide_dans_une_liste_valide_est_refusee(
    position_fautive,
):
    """Une liste de photos valides dont UNE SEULE est structurellement
    invalide (clé inconnue) doit être refusée, et le détail du verdict doit
    désigner l'INDEX de la photo fautive.

    Empêcherait de casser : sans ce cas, la propagation du rejet d'une
    photo n'est tenue par rien ; une régression la supprimant laisserait
    des entrées invalides atteindre la classification. Le paramétrage sur
    la première et la dernière position empêche un passage par accident
    sur un seul rang : c'est la propagation (l'index remonté dans le
    détail), pas seulement le refus, qui est éprouvée.
    """
    photos = [
        _photo_valide(angle="face"),
        _photo_valide(angle="profil"),
        _photo_valide(angle="dessus"),
    ]
    photo_fautive = _photo_valide(angle="dessus")
    photo_fautive["cle_inconnue"] = "anomalie"
    photos[position_fautive] = photo_fautive
    niveau, verdict = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    gabarit = verdicts.construire_verdict(
        "REJ-PHOTOS-INVALIDES", detail="sonde de structure"
    )
    assert niveau is None
    assert set(verdict) == set(gabarit)
    assert verdict["code"] == "REJ-PHOTOS-INVALIDES"
    assert str(position_fautive) in verdict["detail"]


@pytest.mark.parametrize(
    "seuils_invalides",
    [
        "pas-un-dict",
        {"resolution_minimale": 800},
        {"resolution_minimale": "800", "eclairage_minimal": 5.0},
    ],
    ids=[
        "seuils_qui_ne_sont_pas_un_dict",
        "seuils_amputes_d_une_cle",
        "seuil_de_type_faux",
    ],
)
def test_des_seuils_invalides_ne_font_jamais_planter(seuils_invalides):
    """Des seuils structurellement invalides doivent produire un verdict de
    rejet du catalogue fermé, JAMAIS une exception qui s'échappe.

    Empêcherait de casser : l'architecture exige un verdict de rejet dédié
    plutôt qu'un plantage ; sans cette enveloppe, la garde de propagation
    des seuils n'est tenue que par le ``KeyError`` qu'elle devait éviter —
    son ROUGE n'est pas un refus, c'est le défaut lui-même. Chaque forme
    invalide doit rendre ``(None, verdict)`` dont le code appartient au
    catalogue fermé, sans qu'aucune exception ne remonte.
    """
    try:
        niveau, verdict = hierarchie_echelle.classifier_niveau_confiance(
            [_photo_valide()], seuils_invalides
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert niveau is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "surcharges_seconde_photo",
    [
        {"resolution_largeur": 799},
        {"eclairage": 4.0},
    ],
    ids=[
        "seconde_photo_sous_le_seuil_de_resolution",
        "seconde_photo_sous_le_seuil_d_eclairage",
    ],
)
def test_mono_vue_exige_que_TOUTES_les_photos_passent_les_deux_seuils(
    surcharges_seconde_photo,
):
    """Lot de DEUX photos dont UNE SEULE passe les deux seuils :
    INDETERMINE, jamais MONO_VUE_BORNES_LARGES.

    Le quantificateur de MONO_VUE_BORNES_LARGES est UNIVERSEL : TOUTES
    les photos du lot doivent passer le seuil de résolution ET le seuil
    d'éclairage. Sans ce cas, remplacer ``== nombre_photos`` par
    ``>= 1`` ne fait rougir aucun test, et une seule photo exploitable
    suffirait à annoncer une précision que le lot ne porte pas — une
    précision inventée sur des entrées dont la moitié est
    inexploitable. La première photo est nominale (au-dessus des deux
    seuils), seule la seconde est défaillante, d'une seule façon à la
    fois.
    """
    photos = [
        _photo_valide(angle="face"),
        _photo_valide(angle="profil", **surcharges_seconde_photo),
    ]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau == "INDETERMINE"
    assert motifs["photos_au_dessus_du_seuil"] == 1


def test_le_type_booleen_de_dimensions_connues_est_garanti_en_amont():
    """Redondance structurelle DÉCLARÉE : ``is True`` et ``bool(...)``
    sont équivalents ici PARCE QUE la garde amont l'a déjà garanti.

    Ce test déclare une redondance structurelle, il ne bouche pas un
    trou de couverture : ``qualite_photos._valider_photo`` rejette tout
    ``dimensions_connues`` dont le type n'est pas ``bool``, donc la
    classification ne voit JAMAIS autre chose qu'un booléen, et
    remplacer ``is True`` par ``bool(...)`` dans la classification ne
    change rien. Ce test épingle cette garantie amont — l'entier 1,
    « vrai » au sens de ``bool``, doit produire ``(None, verdict)``
    AVANT toute classification — de sorte que la disparition de la
    garde en amont deviendrait visible ici.
    """
    photo = _photo_valide(
        reference_echelle={
            "type": "regle",
            "dimensions_connues": 1,
        }
    )
    niveau, verdict = hierarchie_echelle.classifier_niveau_confiance(
        [photo], _SEUILS
    )
    gabarit = verdicts.construire_verdict(
        "REJ-PHOTOS-INVALIDES", detail="sonde de structure"
    )
    assert niveau is None
    assert set(verdict) == set(gabarit)
    assert verdict["code"] == "REJ-PHOTOS-INVALIDES"


@pytest.mark.parametrize(
    "angles",
    [
        ("face",),
        ("face", "face"),
        ("face", "profil", "face"),
        ("face", "profil", "dessus"),
        ("face", "profil", "dessus", "dessus"),
    ],
    ids=[
        "une_photo_un_seul_angle",
        "deux_photos_angles_repetes",
        "trois_photos_un_angle_repete",
        "trois_photos_trois_angles_distincts",
        "quatre_photos_un_angle_repete",
    ],
)
def test_trois_angles_distincts_impliquent_au_moins_trois_photos(angles):
    """Redondance structurelle DÉCLARÉE : la borne ``nombre_photos >= 3``
    de MULTI_VUES est impliquée par la borne ``angles_distincts >= 3``.

    Ce test déclare une redondance structurelle : ``angles_distincts``
    est le cardinal d'un ensemble de valeurs prises sur les photos, il
    ne peut donc JAMAIS excéder le nombre de photos fournies — et
    ``angles_distincts >= 3`` implique ``nombre_photos >= 3``, ce qui
    rend la borne sur le nombre de photos sans effet observable. Elle
    est conservée parce que le critère d'acceptation l'énonce, et ce
    test épingle l'implication qui la rend inoffensive : sur plusieurs
    lots (tailles différentes, angles répétés et angles distincts), le
    compteur rapporté dans les MOTIFS retournés par la classification —
    et non un calcul refait à côté — respecte toujours cette borne.
    """
    photos = [_photo_valide(angle=angle) for angle in angles]
    niveau, motifs = hierarchie_echelle.classifier_niveau_confiance(
        photos, _SEUILS
    )
    assert niveau in NIVEAUX_FERMES
    assert motifs["angles_distincts"] <= len(photos)
