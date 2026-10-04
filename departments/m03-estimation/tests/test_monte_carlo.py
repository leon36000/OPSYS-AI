"""Tests du Monte Carlo déterministe à graine fournie (cahier M3-S005, lot A).

Ces tests verrouillent la fonction ``monte_carlo.simuler_intervalle`` : la
reproductibilité BIT-À-BIT à graine égale (CA-M3-10), la sensibilité à la
graine (CA-M3-11), l'absence d'état global entre appels entrelacés, le
blocage quand le barème ne couvre pas le type de travaux demandé (CA-M3-21),
le rejet des bornes incohérentes du barème (avec le cas légitime du coût
fixe, ``min == max``), et le respect des bornes du barème par les bornes
produites — un tirage qui en sortirait inventerait un coût.

Le module ``m3_estimation/monte_carlo.py`` n'existe pas encore :
ce fichier doit ÉCHOUER à l'exécution — c'est le RED attendu de la story.
"""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from m3_estimation import contrats, monte_carlo, verdicts


def _bareme_valide(**surcharges):
    """Fabrique un barème valide par défaut, avec surcharges.

    Chaque test ne surcharge QUE ce qu'il fait varier ; tout le reste reste
    le barème nominal : une version, une unité, et des postes couvrant CHAQUE
    type de travaux du contrat (lus dans ``contrats.TYPES_TRAVAUX``, jamais
    recopiés), avec des bornes cohérentes et distinctes d'un type à l'autre
    pour qu'aucun test ne passe par accident sur des bornes uniformes.
    """
    bareme = {
        "version": "2025.1",
        "unite": "m2",
        "postes": {
            type_travaux: {
                "cout_unitaire_min": 100.0 * (rang + 1),
                "cout_unitaire_max": 250.0 * (rang + 1),
            }
            for rang, type_travaux in enumerate(contrats.TYPES_TRAVAUX)
        },
    }
    bareme.update(surcharges)
    return bareme


@pytest.mark.parametrize("quantite", [10, 10 ** 1000])
def test_depassement_numerique_retourne_un_verdict_avant_tirage(quantite):
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    bareme["postes"][type_travaux] = {"cout_unitaire_min": 1e308, "cout_unitaire_max": 1e308}
    intervalle, rejet = monte_carlo.simuler_intervalle(bareme, type_travaux, quantite, 7, 0.9)
    assert intervalle is None and rejet["code"] == "REJ-CONTRAT-INVALIDE"
    quantiles, rejet = monte_carlo.simuler_quantiles(bareme, type_travaux, quantite, 7, [0.5, 0.8])
    assert quantiles is None and rejet["code"] == "REJ-CONTRAT-INVALIDE"


def test_reproductibilite_bit_a_bit_a_graine_egale():
    """Deux appels, mêmes entrées, même graine : bornes EXACTEMENT égales
    (CA-M3-10).

    Empêcherait de casser : une source d'aléa non seedée (état global,
    horloge, tirage système) qui rendrait deux appels identiques non
    reproductibles — une estimation chiffrée qu'on ne peut pas rejouer à
    l'identique est indéfendable. La comparaison est une ÉGALITÉ de
    flottants, jamais ``pytest.approx`` : un approx masquerait précisément
    la dérive que ce test doit interdire.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    premier, verdict_premier = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, 12345, 0.9
    )
    second, verdict_second = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, 12345, 0.9
    )
    assert verdict_premier is None
    assert verdict_second is None
    assert premier["borne_basse"] == second["borne_basse"]
    assert premier["borne_haute"] == second["borne_haute"]
    assert premier == second


@pytest.mark.parametrize(
    "graine_a, graine_b",
    [
        (1, 2),
        (2024, 2025),
        (100000, 999999),
    ],
    ids=[
        "graines_1_et_2",
        "graines_2024_et_2025",
        "graines_100000_et_999999",
    ],
)
def test_graines_differentes_produisent_intervalles_differents(
    graine_a, graine_b
):
    """Mêmes entrées, graines différentes : au moins une borne diffère
    (CA-M3-11).

    Empêcherait de casser : une graine ignorée (générateur jamais seedé,
    tirage constant câblé dans le code) qui servirait le même « aléa » à
    tous les appelants — la graine fournie serait alors un décorum. Le
    paramétrage éprouve PLUSIEURS couples de graines distinctes pour ne pas
    dépendre d'un couple heureux qui différerait par accident.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[1]
    intervalle_a, verdict_a = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, graine_a, 0.9
    )
    intervalle_b, verdict_b = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, graine_b, 0.9
    )
    assert verdict_a is None
    assert verdict_b is None
    assert (
        intervalle_a["borne_basse"] != intervalle_b["borne_basse"]
        or intervalle_a["borne_haute"] != intervalle_b["borne_haute"]
    )


def test_aucun_etat_global_entre_appels_entrelaces():
    """Graines A, B, puis A de nouveau : le troisième appel rend EXACTEMENT
    le premier.

    Empêcherait de casser : un générateur partagé au niveau du module, dont
    l'état avancerait à chaque appel — les tests de reproductibilité et de
    sensibilité à la graine passeraient quand même, mais l'ordre des appels
    contaminerait les résultats. L'égalité est une égalité EXACTE de
    flottants, jamais ``pytest.approx``.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[2]
    premier_a, verdict_a1 = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, 7, 0.9
    )
    _, verdict_b = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, 99, 0.9
    )
    second_a, verdict_a2 = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, 7, 0.9
    )
    assert verdict_a1 is None
    assert verdict_b is None
    assert verdict_a2 is None
    assert second_a["borne_basse"] == premier_a["borne_basse"]
    assert second_a["borne_haute"] == premier_a["borne_haute"]
    assert second_a == premier_a


@pytest.mark.parametrize(
    "type_travaux",
    list(contrats.TYPES_TRAVAUX),
    ids=list(contrats.TYPES_TRAVAUX),
)
def test_bareme_sans_le_type_demande_bloque_la_simulation(type_travaux):
    """Le barème ne couvre pas le type demandé : ``(None, verdict)``
    (CA-M3-21).

    Empêcherait de casser : une extrapolation depuis un autre poste ou des
    bornes par défaut — une simulation sans modèle sous-jacent produirait
    des bornes arbitraires, ce qui est le cœur de l'objection de revue
    scellée. Chaque type du contrat est éprouvé en retrait, pas un seul,
    pour qu'un rejet ne passe pas par accident sur un type particulier.
    L'appel est fait dans un ``try`` : toute exception échappée est un
    échec qui nomme son TYPE.
    """
    bareme = _bareme_valide(
        postes={
            autre_type: {
                "cout_unitaire_min": 100.0,
                "cout_unitaire_max": 200.0,
            }
            for autre_type in contrats.TYPES_TRAVAUX
            if autre_type != type_travaux
        }
    )
    try:
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, 10, 12345, 0.9
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert intervalle is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "type_travaux",
    list(contrats.TYPES_TRAVAUX),
    ids=list(contrats.TYPES_TRAVAUX),
)
def test_bornes_incoherentes_du_bareme_sont_rejetees(type_travaux):
    """``cout_unitaire_min > cout_unitaire_max`` : rejet ``(None, verdict)``.

    Empêcherait de casser : l'acceptation silencieuse d'un barème
    incohérent, qui produirait un intervalle inversé ou arbitraire — le
    rejet doit être NOMMÉ, pas un plantage. Le barème testé COUVRE le type
    demandé (seules ses bornes sont inversées) pour que ce piège soit
    isolé du piège de couverture. Tous les types du contrat sont éprouvés.
    L'appel est fait dans un ``try`` pour que toute exception échappée soit
    un échec nommant son TYPE.
    """
    bareme = _bareme_valide(
        postes={
            type_travaux: {
                "cout_unitaire_min": 300.0,
                "cout_unitaire_max": 100.0,
            }
        }
    )
    try:
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, 10, 12345, 0.9
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert intervalle is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_bornes_egales_du_bareme_produisent_un_intervalle_valide():
    """``cout_unitaire_min == cout_unitaire_max`` : un coût fixe est
    LÉGITIME et doit produire un intervalle valide.

    Empêcherait de casser : le rejet d'un barème à coût fixe (un garde-fou
    qui confondrait « bornes égales » et « bornes incohérentes »), ou un
    intervalle qui s'écarterait du coût fixe — avec des bornes égales, le
    respect du barème impose que les deux bornes produites vaillent
    EXACTEMENT ``quantite * cout_fixe`` (égalité de flottants exacte :
    toute marge aléatoire s'annule quand ``max - min == 0.0``). La
    structure exacte de l'intervalle — TROIS clés, trois flottants, niveau
    repris à l'identique — est verrouillée ici, sur ce cas minimal.
    """
    cout_fixe = 250.0
    quantite = 10
    niveau = 0.9
    type_travaux = contrats.TYPES_TRAVAUX[0]
    bareme = _bareme_valide(
        postes={
            type_travaux: {
                "cout_unitaire_min": cout_fixe,
                "cout_unitaire_max": cout_fixe,
            }
        }
    )
    intervalle, verdict = monte_carlo.simuler_intervalle(
        bareme, type_travaux, quantite, 12345, niveau
    )
    assert verdict is None
    assert set(intervalle) == {"borne_basse", "borne_haute", "niveau"}
    assert isinstance(intervalle["borne_basse"], float)
    assert isinstance(intervalle["borne_haute"], float)
    assert isinstance(intervalle["niveau"], float)
    assert intervalle["niveau"] == niveau
    assert intervalle["borne_basse"] == quantite * cout_fixe
    assert intervalle["borne_haute"] == quantite * cout_fixe


@pytest.mark.parametrize(
    "graine",
    [0, 1, 7, 123456789, 2147483647],
    ids=[
        "graine_0",
        "graine_1",
        "graine_7",
        "graine_123456789",
        "graine_2147483647",
    ],
)
def test_bornes_produites_respectent_le_bareme(graine):
    """``borne_basse >= quantite * cout_min`` et ``borne_haute <= quantite
    * cout_max``, quelle que soit la graine.

    Empêcherait de casser : un tirage qui sortirait des bornes du barème —
    il INVENTERAIT un coût que le barème ne couvre pas, c'est-à-dire une
    précision inventée chiffrée. Plusieurs graines sont éprouvées : une
    seule pourrait retomber dans les bornes par chance. Les comparaisons
    sont des inégalités directes sur les flottants produits, jamais des
    approximations.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    quantite = 10
    poste = bareme["postes"][type_travaux]
    intervalle, verdict = monte_carlo.simuler_intervalle(
        bareme, type_travaux, quantite, graine, 0.9
    )
    assert verdict is None
    assert intervalle["borne_basse"] >= quantite * poste["cout_unitaire_min"]
    assert intervalle["borne_haute"] <= quantite * poste["cout_unitaire_max"]


@pytest.mark.parametrize(
    "graine",
    [0, 1, 42, 12345, 2147483647],
    ids=[
        "graine_0",
        "graine_1",
        "graine_42",
        "graine_12345",
        "graine_2147483647",
    ],
)
def test_borne_basse_ne_depasse_jamais_borne_haute(graine):
    """``borne_basse <= borne_haute``, pour toute graine et tout type de
    travaux.

    Empêcherait de casser : un intervalle inversé — borne basse au-dessus
    de la borne haute — serait une estimation incohérente livrée aux
    appelants : personne ne peut défendre un chiffrage dont le bas
    dépasse le haut. Chaque type du contrat est éprouvé (lu dans
    ``contrats.TYPES_TRAVAUX``, jamais recopié) sous plusieurs graines :
    un ordre correct constaté sur un seul tirage pourrait être un hasard.
    """
    bareme = _bareme_valide()
    for type_travaux in contrats.TYPES_TRAVAUX:
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, 10, graine, 0.9
        )
        assert verdict is None
        assert intervalle["borne_basse"] <= intervalle["borne_haute"]


@pytest.mark.parametrize(
    "niveau",
    [0.5, 0.8, 0.9, 0.95, 0.99],
    ids=[
        "niveau_0_5",
        "niveau_0_8",
        "niveau_0_9",
        "niveau_0_95",
        "niveau_0_99",
    ],
)
def test_niveau_rendu_est_exactement_le_niveau_fourni(niveau):
    """Le ``niveau`` rendu est EXACTEMENT celui fourni, et c'est un
    flottant.

    Empêcherait de casser : un niveau arrondi, plafonné ou recalculé en
    interne — l'intervalle serait alors étiqueté avec un taux qui n'est
    pas celui demandé, c'est-à-dire une précision inventée. L'égalité
    est EXACTE, jamais ``pytest.approx`` : un approx masquerait
    précisément la dérive que ce test doit interdire. Plusieurs niveaux
    sont éprouvés pour qu'une coïncidence sur une seule valeur ne fasse
    pas passer le test par accident.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    intervalle, verdict = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, 12345, niveau
    )
    assert verdict is None
    assert isinstance(intervalle["niveau"], float)
    assert intervalle["niveau"] == niveau


@pytest.mark.parametrize(
    "quantite_invalide",
    [0, -1, -7.5, "10", None, True, False],
    ids=[
        "quantite_zero",
        "quantite_negative_entiere",
        "quantite_negative_flottante",
        "quantite_chaine",
        "quantite_none",
        "quantite_booleenne_vraie",
        "quantite_booleenne_fausse",
    ],
)
def test_quantite_invalide_est_rejetee(quantite_invalide):
    """Quantité nulle, négative, non numérique ou booléenne : rejet
    ``(None, verdict)``.

    Empêcherait de casser : une quantité invalide acceptée en silence —
    zéro écraserait l'intervalle à 0, un négatif l'inverserait, et
    ``isinstance(True, int)`` étant vrai en Python, un booléen passerait
    pour un entier si le garde-fou ne le refusait pas EXPLICITEMENT.
    L'appel est fait dans un ``try`` : toute exception échappée est un
    échec qui nomme son TYPE, et le code du verdict appartient au
    catalogue fermé M3.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    try:
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, quantite_invalide, 12345, 0.9
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert intervalle is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "quantite_acceptee",
    [1, 3, 0.5, 2.5],
    ids=[
        "quantite_entiere_1",
        "quantite_entiere_3",
        "quantite_flottante_0_5",
        "quantite_flottante_2_5",
    ],
)
def test_quantite_strictement_positive_est_acceptee(quantite_acceptee):
    """Une quantité strictement positive — y compris flottante — est
    LÉGITIME et doit produire un intervalle qui respecte le barème.

    Empêcherait de casser : un garde-fou qui rejetterait TOUTE quantité,
    ou seulement les non-entiers, bloquerait des estimations valides —
    le contrat dit « nombre strictement positif », pas « entier ». Ce
    contre-pied éprouve que le rejet est DISCRIMINANT : sans lui, un
    refus systématique ferait passer les tests de rejet par accident.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    poste = bareme["postes"][type_travaux]
    intervalle, verdict = monte_carlo.simuler_intervalle(
        bareme, type_travaux, quantite_acceptee, 12345, 0.9
    )
    assert verdict is None
    assert intervalle["borne_basse"] <= intervalle["borne_haute"]
    assert (
        intervalle["borne_basse"]
        >= quantite_acceptee * poste["cout_unitaire_min"]
    )
    assert (
        intervalle["borne_haute"]
        <= quantite_acceptee * poste["cout_unitaire_max"]
    )


@pytest.mark.parametrize(
    "graine_invalide",
    [0.0, 1.5, "12345", None, True, False],
    ids=[
        "graine_flottante_nulle",
        "graine_flottante",
        "graine_chaine",
        "graine_none",
        "graine_booleenne_vraie",
        "graine_booleenne_fausse",
    ],
)
def test_graine_invalide_est_rejetee(graine_invalide):
    """Graine non entière ou booléenne : rejet ``(None, verdict)``.

    Empêcherait de casser : une graine flottante rendrait la
    reproductibilité bit-à-bit dépendante de la représentation interne
    du flottant — deux appelants fournissant « la même » graine
    pourraient ne plus obtenir le même tirage — et un booléen, qui EST
    un entier pour ``isinstance``, seederait silencieusement avec 0 ou
    1. L'appel est fait dans un ``try`` : toute exception échappée est
    un échec nommant son TYPE, et le code du verdict appartient au
    catalogue fermé M3.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    try:
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, 10, graine_invalide, 0.9
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert intervalle is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "niveau_invalide",
    [0, 1, 0.0, 1.0, -0.1, 1.5, "0.9", None, True, False],
    ids=[
        "niveau_zero_entier",
        "niveau_un_entier",
        "niveau_zero_flottant",
        "niveau_un_flottant",
        "niveau_negatif",
        "niveau_superieur_a_un",
        "niveau_chaine",
        "niveau_none",
        "niveau_booleen_vrai",
        "niveau_booleen_faux",
    ],
)
def test_niveau_invalide_est_rejete(niveau_invalide):
    """Niveau nul, égal à un, hors de ]0, 1[, non numérique ou booléen :
    rejet ``(None, verdict)``.

    Empêcherait de casser : un niveau à 0 ou 1 produirait un intervalle
    dégénéré présenté comme un taux de confiance, et un niveau hors
    bornes n'a aucun sens statistique — l'estimation afficherait un taux
    inventé. Un booléen, entier pour ``isinstance``, doit être refusé
    EXPLICITEMENT. L'appel est fait dans un ``try`` : toute exception
    échappée est un échec nommant son TYPE, et le code du verdict
    appartient au catalogue fermé M3.
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    try:
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, 10, 12345, niveau_invalide
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert intervalle is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "niveau_accepte",
    [0.01, 0.5, 0.99],
    ids=[
        "niveau_0_01",
        "niveau_0_5",
        "niveau_0_99",
    ],
)
def test_niveau_strictement_entre_zero_et_un_est_accepte(niveau_accepte):
    """Un niveau strictement entre 0 et 1 — même au voisinage des bornes —
    est LÉGITIME et doit être rendu à l'identique.

    Empêcherait de casser : un garde-fou aux inégalités trop larges
    (``<=`` là où il faut ``<``) rejetterait des niveaux valides proches
    des bornes — le rejet de 0 et de 1 ne doit pas emporter leurs
    voisins. Ce contre-pied éprouve que la frontière du rejet est
    EXACTEMENT l'ouvert ]0, 1[, et que le niveau accepté traverse sans
    être réinventé (égalité EXACTE, jamais ``pytest.approx``).
    """
    bareme = _bareme_valide()
    type_travaux = contrats.TYPES_TRAVAUX[0]
    intervalle, verdict = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 10, 12345, niveau_accepte
    )
    assert verdict is None
    assert isinstance(intervalle["niveau"], float)
    assert intervalle["niveau"] == niveau_accepte


@pytest.mark.parametrize(
    "champ, valeur_invalide",
    [
        ("quantite", 0),
        ("quantite", -4),
        ("quantite", "10"),
        ("quantite", True),
        ("graine", 2.5),
        ("graine", "12345"),
        ("graine", False),
        ("niveau", 0),
        ("niveau", 1),
        ("niveau", -0.1),
        ("niveau", 1.5),
        ("niveau", "0.9"),
        ("niveau", True),
    ],
    ids=[
        "quantite_zero",
        "quantite_negative",
        "quantite_chaine",
        "quantite_booleenne",
        "graine_flottante",
        "graine_chaine",
        "graine_booleenne",
        "niveau_zero",
        "niveau_un",
        "niveau_negatif",
        "niveau_superieur_a_un",
        "niveau_chaine",
        "niveau_booleen",
    ],
)
def test_entrees_invalides_sont_rejetees_sans_exception(
    champ, valeur_invalide
):
    """Toute entrée invalide poussée par le point d'entrée PUBLIC :
    ``(None, verdict)``, JAMAIS d'exception échappée.

    Empêcherait de casser : un plantage (``TypeError``, ``ValueError``,
    ``KeyError``...) remonté à l'appelant au lieu d'un verdict NOMMÉ —
    le contrat de ``simuler_intervalle`` est fail-closed : entrée
    invalide, verdict de rejet. Chaque cas invalide des pièges quantité,
    graine et niveau est rejoué ici en ne faisant varier QU'UN argument
    à la fois depuis des entrées nominales ; le ``try``/``except``
    nomme le TYPE de toute exception échappée, et chaque code de verdict
    appartient au catalogue fermé M3.
    """
    arguments = {
        "bareme": _bareme_valide(),
        "type_travaux": contrats.TYPES_TRAVAUX[0],
        "quantite": 10,
        "graine": 12345,
        "niveau": 0.9,
    }
    arguments[champ] = valeur_invalide
    try:
        intervalle, verdict = monte_carlo.simuler_intervalle(**arguments)
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert intervalle is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_aucune_source_d_alea_ni_d_horloge_non_controlee():
    """Test STATIQUE par AST : la source de ``monte_carlo.py`` ne doit
    contenir ni horloge, ni aléa non contrôlé.

    Empêcherait de casser : une source d'aléa ou d'horloge non seedée
    (``time``, ``datetime``, ``os``, ``socket``, ``urllib``, ``secrets``,
    ``uuid``, ``numpy``) rendrait les tirages non reproductibles — et
    les tests dynamiques ne la verraient pas forcément, deux exécutions
    pouvant tomber juste par hasard. Le module ``random`` est AUTORISÉ,
    mais uniquement via la CLASSE ``random.Random`` instanciée
    localement : tout appel à une fonction du MODULE (``random.random``,
    ``random.seed``, ``random.uniform``, ``random.choice`` ou tout autre
    attribut) toucherait l'état global du générateur et contrecarrerait
    la graine fournie. L'analyse est faite par ``ast.walk`` sur
    ``ast.Import``, ``ast.ImportFrom`` et ``ast.Call`` — jamais par
    recherche de texte : un nom cité en commentaire n'est pas un appel.
    """
    modules_interdits = {
        "time",
        "datetime",
        "os",
        "socket",
        "urllib",
        "secrets",
        "uuid",
        "numpy",
    }
    source = Path(monte_carlo.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    noms_lies_au_module_random = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                racine = alias.name.split(".")[0]
                assert racine not in modules_interdits, (
                    "import interdit dans monte_carlo.py : " + alias.name
                )
                if racine == "random":
                    noms_lies_au_module_random.add(
                        alias.asname or alias.name
                    )
        elif isinstance(noeud, ast.ImportFrom):
            module = noeud.module or ""
            racine = module.split(".")[0]
            assert racine not in modules_interdits, (
                "import interdit dans monte_carlo.py : from "
                + module
                + " import ..."
            )
            if racine == "random":
                for alias in noeud.names:
                    assert alias.name == "Random", (
                        "seule la classe Random peut être importée depuis "
                        "random ; import interdit : from random import "
                        + alias.name
                    )
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        func = noeud.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in noms_lies_au_module_random
        ):
            assert func.attr == "Random", (
                "seule la classe random.Random peut être appelée ; "
                "appel interdit : "
                + func.value.id
                + "."
                + func.attr
            )


@pytest.mark.parametrize(
    "cas, bareme, type_travaux",
    [
        # Garde L72 — « not isinstance(bareme, dict) ». La liste des
        # trois noms de clés répond « oui » à chaque appartenance : la
        # garde des clés (L76) passe, et SEUL le contrôle de type peut
        # refuser — une non-dict quelconque serait rattrapée par L76 et
        # la suppression de L72 resterait indétectable.
        (
            "liste des trois noms de clés",
            ["version", "unite", "postes"],
            contrats.TYPES_TRAVAUX[0],
        ),
        # Garde L76 — une clé exigée manque, les deux autres présentes
        # et valides. Sans « version » ou sans « unite », aucune garde
        # ultérieure ne lit la clé absente : la simulation aboutirait
        # si la garde était supprimée. Sans « postes », un KeyError
        # s'échapperait — jamais un verdict d'une garde ultérieure.
        (
            "clé version manquante",
            {
                cle: valeur
                for cle, valeur in _bareme_valide().items()
                if cle != "version"
            },
            contrats.TYPES_TRAVAUX[0],
        ),
        (
            "clé unite manquante",
            {
                cle: valeur
                for cle, valeur in _bareme_valide().items()
                if cle != "unite"
            },
            contrats.TYPES_TRAVAUX[0],
        ),
        (
            "clé postes manquante",
            {
                cle: valeur
                for cle, valeur in _bareme_valide().items()
                if cle != "postes"
            },
            contrats.TYPES_TRAVAUX[0],
        ),
        # Garde L82 — « postes » vide ou non dictionnaire. La liste
        # contient le type demandé : l'appartenance testée par la garde
        # de couverture répond « oui », et seul le contrôle de
        # structure de « postes » peut refuser.
        (
            "postes dictionnaire vide",
            _bareme_valide(postes={}),
            contrats.TYPES_TRAVAUX[0],
        ),
        (
            "postes liste contenant le type demandé",
            _bareme_valide(postes=[contrats.TYPES_TRAVAUX[0]]),
            contrats.TYPES_TRAVAUX[0],
        ),
        # Garde L92 — type hors contrat mais PRÉSENT dans « postes »
        # avec un poste parfaitement valide : sinon la garde de
        # couverture (type absent des postes) le rattraperait et la
        # suppression de L92 resterait indétectable.
        (
            "type hors contrat présent dans les postes",
            _bareme_valide(
                postes={
                    "type_hors_contrat": {
                        "cout_unitaire_min": 100.0,
                        "cout_unitaire_max": 200.0,
                    }
                }
            ),
            "type_hors_contrat",
        ),
        # Garde L110 — poste non dictionnaire. La chaîne contient les
        # deux noms de clés de coût : l'appartenance testée par la
        # garde des clés de coût (L115) répond « oui » par sous-chaîne,
        # et seul le contrôle de type du poste peut refuser.
        (
            "poste chaîne contenant les deux noms de clés de coût",
            _bareme_valide(
                postes={
                    contrats.TYPES_TRAVAUX[0]: (
                        "cout_unitaire_min et cout_unitaire_max"
                    )
                }
            ),
            contrats.TYPES_TRAVAUX[0],
        ),
        # Garde L115 — le poste ne porte que « cout_unitaire_min » :
        # sans la garde, un KeyError s'échapperait sur
        # « cout_unitaire_max », jamais un verdict ultérieur.
        (
            "poste sans cout_unitaire_max",
            _bareme_valide(
                postes={
                    contrats.TYPES_TRAVAUX[0]: {
                        "cout_unitaire_min": 100.0
                    }
                }
            ),
            contrats.TYPES_TRAVAUX[0],
        ),
        # Garde L122 — coût non numérique, puis non FINI : le module
        # exige un « nombre FINI », pas seulement un « nombre » —
        # l'infini doit être refusé comme la chaîne.
        (
            "cout_unitaire_min chaîne",
            _bareme_valide(
                postes={
                    contrats.TYPES_TRAVAUX[0]: {
                        "cout_unitaire_min": "cent",
                        "cout_unitaire_max": 200.0,
                    }
                }
            ),
            contrats.TYPES_TRAVAUX[0],
        ),
        (
            "cout_unitaire_max infini",
            _bareme_valide(
                postes={
                    contrats.TYPES_TRAVAUX[0]: {
                        "cout_unitaire_min": 100.0,
                        "cout_unitaire_max": float("inf"),
                    }
                }
            ),
            contrats.TYPES_TRAVAUX[0],
        ),
    ],
    ids=[
        "garde_type_bareme_liste_des_trois_cles",
        "garde_cles_version_manquante",
        "garde_cles_unite_manquante",
        "garde_cles_postes_manquante",
        "garde_postes_dictionnaire_vide",
        "garde_postes_liste",
        "garde_type_hors_contrat_present_dans_postes",
        "garde_poste_chaine",
        "garde_cle_cout_unitaire_max_manquante",
        "garde_cout_unitaire_min_chaine",
        "garde_cout_unitaire_max_infini",
    ],
)
def test_baremes_structurellement_invalides_sont_refuses(
    cas, bareme, type_travaux
):
    """Barème structurellement invalide : ``(None, verdict)``, jamais
    d'exception échappée.

    Empêcherait de casser : les sept gardes STRUCTURELLES de
    ``simuler_intervalle`` — barème non dictionnaire, clé
    ``version``/``unite``/``postes`` manquante, ``postes`` vide ou non
    dictionnaire, type de travaux hors contrat, poste non dictionnaire,
    clé de coût manquante, coût non numérique ou non fini — que AUCUN
    test existant ne tenait : la suite couvre la cohérence des bornes,
    la quantité, la graine et le niveau, mais pas la validation
    structurelle du barème, et la suppression de l'une de ces gardes
    laissait 316 tests verts. Chaque cas franchit les gardes
    ANTÉRIEURES pour n'échouer que sur celle qu'il vise : sans cela,
    une garde ultérieure rattraperait l'entrée, le test resterait vert
    pour la mauvaise raison et la suppression de la garde visée
    resterait indétectable. Le cas le plus instructif est la liste des
    trois noms de clés : ``["version", "unite", "postes"]`` répond
    « oui » à chaque test d'appartenance, traverse donc le contrôle
    des clés, et n'est arrêtée que par le contrôle de type — une
    non-dict quelconque serait rattrapée par la garde des clés. Le même
    principe préside au ``postes`` liste contenant le type demandé et
    au poste chaîne contenant les deux noms de clés de coût. L'appel
    est fait dans un ``try`` : toute exception échappée est un échec
    qui nomme le TYPE de l'exception et l'identifiant du cas, et le
    code du verdict appartient au catalogue fermé M3.
    """
    try:
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, 10, 12345, 0.9
        )
    except Exception as erreur:
        pytest.fail(
            "cas « "
            + cas
            + " » : une exception s'est échappée au lieu d'un verdict "
            "de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert intervalle is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_un_niveau_plus_eleve_donne_un_intervalle_plus_large():
    """Pour une MÊME graine et un MÊME barème, trois niveaux croissants
    donnent des largeurs STRICTEMENT croissantes.

    Empêcherait de casser : un taux figé dans le code — par exemple
    ``alpha = (1.0 - 0.90) / 2.0`` au lieu de ``(1.0 - niveau) / 2.0`` —
    qui ignorerait le ``niveau`` de l'appelant. Sans ce cas, une telle
    mutation passerait inaperçue : tous les autres tests n'éprouvent
    qu'un seul niveau à la fois et constatent seulement que le niveau
    RENDU est celui fourni, jamais qu'il a un EFFET sur les bornes.
    L'intervalle porterait alors une étiquette de confiance qui ne
    correspond à rien — une précision inventée. Les comparaisons sont
    des inégalités STRICTES sur des flottants produits avec la même
    graine : le tirage sous-jacent est identique, seul le découpage
    change, et un niveau plus élevé doit retenir davantage de tirages.
    """
    type_travaux = contrats.TYPES_TRAVAUX[0]
    bareme = _bareme_valide(
        postes={
            type_travaux: {
                "cout_unitaire_min": 10.0,
                "cout_unitaire_max": 250.0,
            }
        }
    )
    quantite = 7.3
    graine = 42
    niveaux = [0.50, 0.90, 0.99]
    largeurs = []
    for niveau in niveaux:
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, quantite, graine, niveau
        )
        assert verdict is None
        largeurs.append(
            intervalle["borne_haute"] - intervalle["borne_basse"]
        )
    assert largeurs[0] < largeurs[1]
    assert largeurs[1] < largeurs[2]


def test_les_deux_queues_de_l_intervalle_sont_symetriques():
    """En élargissant le niveau de 0.50 à 0.90 sur une même graine,
    l'élargissement vers le bas et l'élargissement vers le haut sont du
    MÊME ordre de grandeur.

    Empêcherait de casser : un découpage asymétrique des queues — par
    exemple ``alpha = 1.0 - niveau`` au lieu de ``alpha = (1.0 -
    niveau) / 2.0`` — qui enverrait tout l'écart dans la queue basse :
    la borne basse s'effondrerait tandis que la borne haute ne
    bougerait presque pas, et l'intervalle présenté comme centré ne le
    serait plus. La tolérance est un RAPPORT relatif explicite : le
    quotient des deux élargissements doit rester entre 0.5 et 2.0.
    Une égalité exacte serait FAUSSE : l'échantillon est aléatoire, les
    tirages ne se répartissent pas en deux moitiés parfaitement
    symétriques, et les deux queues ne sont donc jamais strictement
    égales — seule leur COMPARABILITÉ prouve que le découpage partage
    l'écart en deux queues du même poids, et non que le hasard d'une
    graine a produit deux nombres identiques.
    """
    type_travaux = contrats.TYPES_TRAVAUX[0]
    bareme = _bareme_valide(
        postes={
            type_travaux: {
                "cout_unitaire_min": 10.0,
                "cout_unitaire_max": 250.0,
            }
        }
    )
    quantite = 7.3
    graine = 42
    intervalle_50, verdict_50 = monte_carlo.simuler_intervalle(
        bareme, type_travaux, quantite, graine, 0.50
    )
    intervalle_90, verdict_90 = monte_carlo.simuler_intervalle(
        bareme, type_travaux, quantite, graine, 0.90
    )
    assert verdict_50 is None
    assert verdict_90 is None
    elargissement_bas = (
        intervalle_50["borne_basse"] - intervalle_90["borne_basse"]
    )
    elargissement_haut = (
        intervalle_90["borne_haute"] - intervalle_50["borne_haute"]
    )
    assert elargissement_bas > 0.0
    assert elargissement_haut > 0.0
    rapport = elargissement_bas / elargissement_haut
    assert 0.5 <= rapport <= 2.0


def test_valeurs_d_or_du_pipeline_complet():
    """Non-régression : le pipeline complet produit EXACTEMENT ces deux
    bornes pour ce barème, cette quantité, cette graine et ce niveau.

    Empêcherait de casser : toute modification d'un maillon de la
    simulation que les autres tests ne distinguent pas — par exemple le
    nombre de tirages (déclaré FIXE pour que deux estimations restent
    comparables entre elles) passant de 10000 à 101, un changement
    d'ordre des opérations, ou un autre calcul des indices de quantile.
    De telles mutations changent silencieusement toutes les bornes
    tout en laissant verts les tests de reproductibilité, de respect du
    barème et de cohérence : seule une valeur de référence ÉPINGLÉE les
    détecte. L'égalité est une égalité EXACTE de flottants, jamais
    ``pytest.approx`` : un approx masquerait précisément la dérive que
    ce test doit interdire. Ce test échoue dès qu'un maillon change ;
    sa mise à jour doit être un acte DÉLIBÉRÉ et justifié, jamais un
    réflexe pour faire passer la suite.
    """
    type_travaux = contrats.TYPES_TRAVAUX[0]
    bareme = _bareme_valide(
        postes={
            type_travaux: {
                "cout_unitaire_min": 10.0,
                "cout_unitaire_max": 250.0,
            }
        }
    )
    intervalle, verdict = monte_carlo.simuler_intervalle(
        bareme, type_travaux, 7.3, 20260731, 0.90
    )
    assert verdict is None
    assert intervalle["borne_basse"] == 161.73912543357872
    assert intervalle["borne_haute"] == 1733.9000588101496
