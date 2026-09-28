"""Tests de la confrontation au plancher rentable (cahier M3-S006).

Ces tests verrouillent la fonction ``plancher.confronter_au_plancher`` :
le déclenchement de l'alerte quand la borne basse tombe STRICTEMENT sous le
plancher rentable (CA-M3-12), l'absence d'alerte au-dessus (CA-M3-13), le
cas d'égalité qui ne doit JAMAIS alerter parce que la comparaison est
STRICTE, le caractère NON BLOQUANT de l'alerte — le verdict associé est
``PLANCHER_RENTABILITE_FRANCHI``, jamais un verdict de rejet —, le plancher
fourni par l'appelant et jamais codé en dur, l'appartenance du
``verdict_estimation`` au catalogue fermé ``contrats.VERDICTS_ESTIMATION``,
le rejet des bornes nulles et des entrées invalides sans qu'aucune
exception ne s'échappe, et l'absence de tout import de réseau, d'horloge,
d'aléa ou de processus dans le module.

Le module ``m3_estimation/plancher.py`` n'existe pas encore :
ce fichier doit ÉCHOUER à l'exécution — c'est le RED attendu de la story.
"""

import ast
import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from m3_estimation import contrats, plancher, verdicts


def _intervalle_valide(**surcharges):
    """Fabrique un intervalle valide par défaut, avec surcharges.

    Chaque test ne surcharge QUE ce qu'il fait varier ; tout le reste reste
    l'intervalle nominal de la forme rendue par
    ``monte_carlo.simuler_intervalle`` : TROIS clés, trois flottants, une
    ``borne_basse`` strictement positive et inférieure à ``borne_haute``.
    """
    intervalle = {
        "borne_basse": 100.0,
        "borne_haute": 200.0,
        "niveau": 0.9,
    }
    intervalle.update(surcharges)
    return intervalle


@pytest.mark.parametrize(
    "borne_basse, plancher_rentable",
    [
        (80.0, 100.0),
        (99.5, 100.0),
        (1.0, 250.0),
    ],
    ids=[
        "ecart_de_20_sous_le_plancher",
        "ecart_de_0_5_sous_le_plancher",
        "ecart_de_249_sous_le_plancher",
    ],
)
def test_borne_basse_strictement_sous_le_plancher_declenche_l_alerte(
    borne_basse, plancher_rentable
):
    """Borne basse STRICTEMENT sous le plancher : ``alerte_plancher`` vaut
    True (CA-M3-12).

    Empêcherait de casser : une alerte jamais levée — comparaison inversée,
    seuil ignoré, retour câblé à False — qui laisserait partir sans signal
    une estimation dont le bas de l'intervalle ne couvre pas le plancher
    rentable. PLUSIEURS écarts sont éprouvés : un seul pourrait déclencher
    l'alerte par accident sur une implémentation fausse. Le résultat est un
    booléen EXACT (``is True``), jamais une valeur simplement vraie.
    """
    intervalle = _intervalle_valide(borne_basse=borne_basse)
    constat, verdict = plancher.confronter_au_plancher(
        intervalle, plancher_rentable
    )
    assert verdict is None
    assert constat["alerte_plancher"] is True


@pytest.mark.parametrize(
    "borne_basse, plancher_rentable",
    [
        (150.0, 100.0),
        (100.01, 100.0),
    ],
    ids=[
        "borne_basse_de_50_au_dessus_du_plancher",
        "borne_basse_de_0_01_au_dessus_du_plancher",
    ],
)
def test_borne_basse_au_dessus_du_plancher_ne_declenche_pas_l_alerte(
    borne_basse, plancher_rentable
):
    """Borne basse supérieure au plancher : ``alerte_plancher`` vaut False
    et le verdict est ``AUCUN_BLOCAGE`` (CA-M3-13).

    Empêcherait de casser : une alerte SYSTÉMATIQUE, qui signalerait comme
    non rentables des affaires parfaitement rentables — et ferait passer le
    test CA-M3-12 par accident. Ce contre-pied éprouve que l'alerte est
    DISCRIMINANTE, y compris sur un écart minimal au-dessus du plancher, et
    que la voie sans alerte rend bien le verdict ``AUCUN_BLOCAGE``.
    """
    intervalle = _intervalle_valide(borne_basse=borne_basse)
    constat, verdict = plancher.confronter_au_plancher(
        intervalle, plancher_rentable
    )
    assert verdict is None
    assert constat["alerte_plancher"] is False
    assert constat["verdict_estimation"] == "AUCUN_BLOCAGE"


@pytest.mark.parametrize(
    "plancher_rentable",
    [100.0, 150.25],
    ids=[
        "egalite_a_100",
        "egalite_a_150_25",
    ],
)
def test_borne_basse_egale_au_plancher_ne_declenche_pas_l_alerte(
    plancher_rentable
):
    """``borne_basse == plancher_rentable`` : PAS d'alerte — la comparaison
    est STRICTE.

    Empêcherait de casser : le remplacement de ``<`` par ``<=``, qui
    signalerait à tort comme non rentable une estimation exactement au
    plancher — un test qui n'éprouve pas l'égalité laisserait cette
    mutation indétectable. L'égalité est construite en réutilisant la MÊME
    valeur des deux côtés de la confrontation, jamais deux littéraux
    simplement censés être égaux.
    """
    intervalle = _intervalle_valide(borne_basse=plancher_rentable)
    constat, verdict = plancher.confronter_au_plancher(
        intervalle, plancher_rentable
    )
    assert verdict is None
    assert constat["alerte_plancher"] is False
    assert constat["verdict_estimation"] == "AUCUN_BLOCAGE"


def test_l_alerte_plancher_ne_bloque_pas_l_estimation():
    """Sous alerte, le tuple rendu est ``(constat, None)`` et le constat ne
    porte AUCUNE clé de blocage : l'alerte NE BLOQUE PAS.

    Empêcherait de casser : la transformation de l'alerte en blocage — un
    tuple ``(None, verdict)`` de rejet, ou une clé de blocage ajoutée au
    constat — qui ferait refuser une affaire simplement peu rentable : le
    verdict ``PLANCHER_RENTABILITE_FRANCHI`` est un SIGNAL, pas un verrou.
    La structure EXACTE du constat — DEUX clés, ni plus ni moins — est
    verrouillée ici, sur la voie qui déclenche l'alerte.
    """
    intervalle = _intervalle_valide(borne_basse=50.0)
    constat, verdict = plancher.confronter_au_plancher(intervalle, 100.0)
    assert verdict is None
    assert constat is not None
    assert set(constat) == {"alerte_plancher", "verdict_estimation"}
    assert constat["alerte_plancher"] is True
    assert constat["verdict_estimation"] == "PLANCHER_RENTABILITE_FRANCHI"


def test_le_plancher_est_fourni_par_l_appelant():
    """Le MÊME intervalle confronté à deux planchers différents donne deux
    constats différents : le plancher vient de l'appelant.

    Empêcherait de casser : un plancher codé en dur dans le module, qui
    rendrait le paramètre ``plancher_rentable`` décoratif — aucun test à
    plancher unique ne le verrait jamais. Les deux planchers encadrent la
    borne basse, l'un en dessous et l'autre au-dessus, et les DEUX
    composantes du constat doivent changer d'un appel à l'autre.
    """
    intervalle = _intervalle_valide(borne_basse=100.0)
    constat_bas, verdict_bas = plancher.confronter_au_plancher(
        intervalle, 50.0
    )
    constat_haut, verdict_haut = plancher.confronter_au_plancher(
        intervalle, 150.0
    )
    assert verdict_bas is None
    assert verdict_haut is None
    assert constat_bas["alerte_plancher"] is False
    assert constat_haut["alerte_plancher"] is True
    assert (
        constat_bas["verdict_estimation"]
        != constat_haut["verdict_estimation"]
    )


@pytest.mark.parametrize(
    "borne_basse, plancher_rentable, alerte_attendue, verdict_attendu",
    [
        (
            80.0,
            100.0,
            True,
            contrats.VERDICT_PLANCHER_RENTABILITE_FRANCHI,
        ),
        (
            120.0,
            100.0,
            False,
            contrats.VERDICT_AUCUN_BLOCAGE,
        ),
        (
            100.0,
            100.0,
            False,
            contrats.VERDICT_AUCUN_BLOCAGE,
        ),
        (
            10.0,
            0.0,
            False,
            contrats.VERDICT_AUCUN_BLOCAGE,
        ),
    ],
    ids=[
        "sous_le_plancher",
        "au_dessus_du_plancher",
        "a_egalite_avec_le_plancher",
        "plancher_zero",
    ],
)
def test_verdict_estimation_appartient_toujours_au_catalogue_ferme(
    borne_basse, plancher_rentable, alerte_attendue, verdict_attendu
):
    """Chaque situation rend le verdict qui lui CORRESPOND : sous alerte,
    ``contrats.VERDICT_PLANCHER_RENTABILITE_FRANCHI`` ; sinon,
    ``contrats.VERDICT_AUCUN_BLOCAGE`` — désignés par leurs constantes de
    ``contrats``, jamais par des littéraux.

    Vérifier l'APPARTENANCE du verdict rendu à
    ``contrats.VERDICTS_ESTIMATION`` serait ici une TAUTOLOGIE : le module
    ne produit que deux verdicts DÉRIVÉS de ce même tuple, l'assertion
    serait vraie par construction et donnerait l'illusion d'une couverture.
    Ce qui se teste, c'est la CORRESPONDANCE entre la situation et le
    verdict : une PERMUTATION des deux verdicts — le franchissement servi
    au-dessus du plancher et l'absence de blocage servie en dessous — doit
    faire ROUGIR ce test. Les DEUX branches sont éprouvées, ainsi que
    l'égalité et le plancher zéro, et chaque cas paramétré porte son alerte
    ET son verdict attendus : sans les deux issues, une permutation ne
    serait visible d'aucun côté.
    """
    intervalle = _intervalle_valide(borne_basse=borne_basse)
    constat, verdict = plancher.confronter_au_plancher(
        intervalle, plancher_rentable
    )
    assert verdict is None
    assert set(constat) == {"alerte_plancher", "verdict_estimation"}
    assert constat["alerte_plancher"] is alerte_attendue
    assert constat["verdict_estimation"] == verdict_attendu


def test_borne_basse_none_est_rejetee_sans_comparaison():
    """Un intervalle dont ``borne_basse`` est None — prix bloqué en amont —
    est rejeté ``(None, verdict)`` : on ne compare JAMAIS avec None.

    Empêcherait de casser : une comparaison ``None < plancher`` — qui
    lèverait ``TypeError`` chez l'appelant, ou pire, serait avalée par un
    garde-fou mal placé en un constat d'apparence normale pour une
    estimation qui n'existe pas. L'appel est fait dans un ``try`` : toute
    exception échappée est un échec qui nomme son TYPE, et le code du
    verdict appartient au catalogue fermé M3.
    """
    intervalle = _intervalle_valide(borne_basse=None)
    try:
        constat, verdict = plancher.confronter_au_plancher(
            intervalle, 100.0
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert constat is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "intervalle_invalide",
    [
        ["borne_basse", "borne_haute", "niveau"],
        "intervalle",
        None,
        42,
    ],
    ids=[
        "liste_des_trois_noms_de_cles",
        "chaine",
        "none",
        "entier",
    ],
)
def test_intervalle_non_dictionnaire_est_rejete(intervalle_invalide):
    """Intervalle non-dict : rejet ``(None, verdict)``, jamais d'exception
    échappée.

    Empêcherait de casser : l'absence du contrôle de type — la liste des
    TROIS noms de clés répond « oui » à chaque test d'appartenance et
    traverserait un contrôle de clés seul ; le ``TypeError`` d'un test
    d'appartenance sur None ou sur un entier remonterait à l'appelant.
    L'appel est fait dans un ``try`` : toute exception échappée est un
    échec qui nomme son TYPE, et le code du verdict appartient au
    catalogue fermé M3.
    """
    try:
        constat, verdict = plancher.confronter_au_plancher(
            intervalle_invalide, 100.0
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert constat is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "cle_manquante",
    ["borne_basse", "borne_haute", "niveau"],
    ids=[
        "cle_borne_basse_manquante",
        "cle_borne_haute_manquante",
        "cle_niveau_manquante",
    ],
)
def test_intervalle_ampute_d_une_cle_est_rejete(cle_manquante):
    """Intervalle amputé d'une clé : rejet ``(None, verdict)``, jamais un
    ``KeyError`` échappé.

    Empêcherait de casser : l'absence du contrôle de présence des TROIS
    clés — un accès direct lèverait ``KeyError`` chez l'appelant, et une
    clé absente traitée par défaut produirait une confrontation sur une
    valeur inventée. Chaque clé est retirée à tour de rôle pour qu'aucun
    contrôle partiel ne fasse passer le test par accident. L'appel est
    fait dans un ``try`` : toute exception échappée est un échec qui
    nomme son TYPE.
    """
    intervalle = {
        cle: valeur
        for cle, valeur in _intervalle_valide().items()
        if cle != cle_manquante
    }
    try:
        constat, verdict = plancher.confronter_au_plancher(
            intervalle, 100.0
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert constat is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "borne_basse_invalide",
    ["100", True, False],
    ids=[
        "borne_basse_chaine",
        "borne_basse_booleenne_vraie",
        "borne_basse_booleenne_fausse",
    ],
)
def test_borne_basse_non_numerique_est_rejetee(borne_basse_invalide):
    """``borne_basse`` non numérique — chaîne ou booléen : rejet
    ``(None, verdict)``.

    Empêcherait de casser : une comparaison ``"100" < plancher`` lèverait
    ``TypeError`` chez l'appelant, et ``isinstance(True, int)`` étant vrai
    en Python, un booléen passerait pour un nombre si le garde-fou ne le
    refusait pas EXPLICITEMENT — ``True < 100.0`` est une comparaison
    syntaxiquement valide qui produirait un constat silencieusement faux.
    L'appel est fait dans un ``try`` : toute exception échappée est un
    échec qui nomme son TYPE.
    """
    intervalle = _intervalle_valide(borne_basse=borne_basse_invalide)
    try:
        constat, verdict = plancher.confronter_au_plancher(
            intervalle, 100.0
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert constat is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "plancher_invalide",
    [
        "100",
        None,
        True,
        False,
        float("inf"),
        float("-inf"),
        float("nan"),
    ],
    ids=[
        "plancher_chaine",
        "plancher_none",
        "plancher_booleen_vrai",
        "plancher_booleen_faux",
        "plancher_infini_positif",
        "plancher_infini_negatif",
        "plancher_nan",
    ],
)
def test_plancher_non_numerique_booleen_ou_non_fini_est_rejete(
    plancher_invalide
):
    """``plancher_rentable`` non numérique, booléen ou NON FINI : rejet
    ``(None, verdict)``.

    Empêcherait de casser : l'acceptation d'un seuil qui n'est pas un
    nombre FINI — ``isinstance(True, int)`` étant vrai en Python, le
    booléen doit être refusé EXPLICITEMENT ; avec l'infini, la comparaison
    devient constante et l'alerte un décorum ; avec nan, TOUTE comparaison
    est fausse et l'alerte ne se déclencherait jamais. L'appel est fait
    dans un ``try`` : toute exception échappée est un échec qui nomme son
    TYPE, et le code du verdict appartient au catalogue fermé M3.
    """
    intervalle = _intervalle_valide()
    try:
        constat, verdict = plancher.confronter_au_plancher(
            intervalle, plancher_invalide
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert constat is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "plancher_negatif",
    [-1, -0.5, -1000.0],
    ids=[
        "plancher_moins_1",
        "plancher_moins_0_5",
        "plancher_moins_1000",
    ],
)
def test_plancher_negatif_est_rejete(plancher_negatif):
    """Un plancher de rentabilité NÉGATIF n'a pas de sens : rejet
    ``(None, verdict)``.

    Empêcherait de casser : l'acceptation silencieuse d'un seuil négatif,
    sous lequel aucune borne basse légitime ne tombe jamais — l'alerte ne
    se déclencherait plus et le plancher deviendrait un décorum. Entiers
    et flottants négatifs sont éprouvés : le rejet ne doit pas dépendre
    de la forme du négatif. L'appel est fait dans un ``try`` : toute
    exception échappée est un échec qui nomme son TYPE.
    """
    intervalle = _intervalle_valide()
    try:
        constat, verdict = plancher.confronter_au_plancher(
            intervalle, plancher_negatif
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert constat is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "plancher_zero",
    [0, 0.0],
    ids=[
        "plancher_zero_entier",
        "plancher_zero_flottant",
    ],
)
def test_plancher_zero_est_accepte(plancher_zero):
    """Le plancher ZÉRO est ACCEPTABLE et produit un constat valide.

    Empêcherait de casser : un garde-fou « strictement positif » qui
    rejetterait zéro en même temps que les négatifs — la frontière du
    rejet est EXACTEMENT « négatif », pas « non strictement positif ».
    L'entier 0 est éprouvé au même titre que le flottant 0.0 : un nombre
    reste un nombre. Ce contre-pied éprouve que le rejet des planchers
    négatifs est DISCRIMINANT : sans lui, un refus de tout plancher
    ferait passer les tests de rejet par accident.
    """
    intervalle = _intervalle_valide(borne_basse=10.0)
    constat, verdict = plancher.confronter_au_plancher(
        intervalle, plancher_zero
    )
    assert verdict is None
    assert set(constat) == {"alerte_plancher", "verdict_estimation"}
    assert constat["alerte_plancher"] is False
    assert constat["verdict_estimation"] == "AUCUN_BLOCAGE"


@pytest.mark.parametrize(
    "champ, valeur_invalide",
    [
        ("intervalle", ["borne_basse", "borne_haute", "niveau"]),
        ("intervalle", "pas-un-dict"),
        ("intervalle", None),
        ("intervalle", {"borne_basse": 100.0, "niveau": 0.9}),
        ("intervalle", _intervalle_valide(borne_basse=None)),
        ("intervalle", _intervalle_valide(borne_basse="100")),
        ("intervalle", _intervalle_valide(borne_basse=True)),
        ("plancher_rentable", "100"),
        ("plancher_rentable", None),
        ("plancher_rentable", True),
        ("plancher_rentable", False),
        ("plancher_rentable", float("inf")),
        ("plancher_rentable", float("nan")),
        ("plancher_rentable", -1),
    ],
    ids=[
        "intervalle_liste_des_trois_cles",
        "intervalle_chaine",
        "intervalle_none",
        "intervalle_ampute_de_borne_haute",
        "intervalle_borne_basse_none",
        "intervalle_borne_basse_chaine",
        "intervalle_borne_basse_booleenne",
        "plancher_chaine",
        "plancher_none",
        "plancher_booleen_vrai",
        "plancher_booleen_faux",
        "plancher_infini",
        "plancher_nan",
        "plancher_negatif",
    ],
)
def test_entrees_invalides_sont_rejetees_sans_exception(
    champ, valeur_invalide
):
    """Toute entrée invalide poussée par le point d'entrée PUBLIC :
    ``(None, verdict)``, JAMAIS d'exception échappée.

    Empêcherait de casser : un plantage (``TypeError``, ``KeyError``...)
    remonté à l'appelant au lieu d'un verdict NOMMÉ — le contrat de
    ``confronter_au_plancher`` est fail-closed : entrée invalide, verdict
    de rejet. Chaque cas invalide des pièges intervalle et plancher est
    rejoué ici en ne faisant varier QU'UN argument à la fois depuis des
    entrées nominales ; le ``try``/``except`` nomme le TYPE de toute
    exception échappée, et chaque code de verdict appartient au catalogue
    fermé M3.
    """
    arguments = {
        "intervalle": _intervalle_valide(),
        "plancher_rentable": 100.0,
    }
    arguments[champ] = valeur_invalide
    try:
        constat, verdict = plancher.confronter_au_plancher(**arguments)
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert constat is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_aucun_import_de_reseau_d_horloge_ni_d_alea():
    """Test STATIQUE par AST : la source de ``plancher.py`` ne doit importer
    ni réseau, ni horloge, ni aléa, ni processus.

    Empêcherait de casser : toute source extérieure au paramètre
    ``plancher_rentable`` — horloge, réseau, aléa, sous-processus — qui
    rendrait la confrontation non reproductible, ou ferait venir le seuil
    d'ailleurs que de l'appelant. L'analyse est faite par ``ast.walk``
    sur ``ast.Import`` et ``ast.ImportFrom`` — jamais par recherche de
    texte : un nom cité en commentaire n'est pas un import.
    """
    modules_interdits = {
        "random",
        "time",
        "datetime",
        "os",
        "socket",
        "urllib",
        "secrets",
        "uuid",
        "subprocess",
    }
    source = Path(plancher.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                racine = alias.name.split(".")[0]
                assert racine not in modules_interdits, (
                    "import interdit dans plancher.py : " + alias.name
                )
        elif isinstance(noeud, ast.ImportFrom):
            module = noeud.module or ""
            racine = module.split(".")[0]
            assert racine not in modules_interdits, (
                "import interdit dans plancher.py : from "
                + module
                + " import ..."
            )


def test_une_borne_nulle_est_diagnostiquee_comme_un_blocage_amont():
    """Une ``borne_basse`` None est rejetée avec un détail qui NOMME le
    blocage amont, distinct de celui d'une borne non numérique.

    Cette garde ne détecte rien de plus que la suivante — elle NOMME autre
    chose. Comparer ``None`` à un nombre lèverait ``TypeError`` en Python 3,
    et confondre « prix bloqué en amont » avec « donnée corrompue »
    enverrait chercher une panne là où le pipeline s'est comporté
    normalement : la première situation est un enchaînement NORMAL du
    pipeline, la seconde une donnée corrompue. Empêcherait de casser : la
    suppression de la garde ``borne_basse is None``, dont le rattrapage par
    le contrôle « nombre fini » rend le MÊME code de verdict — seul le
    DÉTAIL change, et sans la comparaison des deux détails construits dans
    ce même test, sa suppression reste indétectable (mesuré). Les deux
    appels sont faits dans un ``try`` : toute exception échappée est un
    échec qui nomme son TYPE.
    """
    try:
        constat_nul, verdict_nul = plancher.confronter_au_plancher(
            _intervalle_valide(borne_basse=None), 100.0
        )
        constat_corrompu, verdict_corrompu = plancher.confronter_au_plancher(
            _intervalle_valide(borne_basse="100"), 100.0
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert constat_nul is None
    assert verdict_nul["code"] in verdicts.CODES_M3_LIST
    assert "bloqué en amont" in verdict_nul["detail"]
    assert constat_corrompu is None
    assert verdict_corrompu["code"] in verdicts.CODES_M3_LIST
    assert verdict_nul["detail"] != verdict_corrompu["detail"]


def test_aucun_verdict_n_est_recopie_en_litteral_dans_le_paquet():
    """Garde anti-recopie : un verdict se désigne par sa CONSTANTE de
    ``contrats``, jamais par un littéral recopié dans un module.

    La garde d'appartenance à ``contrats.VERDICTS_ESTIMATION`` détecte la
    dérive APRÈS coup ; cette garde-ci empêche la recopie TOUT COURT : hors
    ``contrats.py``, aucune chaîne littérale du paquet source ne peut être
    égale à l'un des six verdicts. La règle énoncée est « un verdict se
    désigne par sa constante » — et non « évitez de recopier tel ou tel
    littéral » — pour qu'aucune exemption ne s'y glisse. Empêcherait de
    casser : la réintroduction d'un littéral ``"INDETERMINE"`` ou
    ``"AUCUN_BLOCAGE"`` dans un module — une faute de frappe dedans ne se
    verrait qu'à l'exécution du chemin concerné, et la garde d'appartenance
    ne la verrait que si ce chemin est effectivement testé. L'analyse est
    faite par ``ast.walk`` sur ``ast.Constant`` — JAMAIS par recherche de
    texte : un verdict cité dans un commentaire ou une docstring n'est pas
    une recopie ; les docstrings (module, classe, fonction) sont exclues
    explicitement, sinon le test interdirait de DOCUMENTER les verdicts,
    ce qui est absurde. Si le parcours ne trouve AUCUN fichier à analyser,
    le test ÉCHOUE : un extracteur vide n'est pas probant. Le message
    d'échec nomme le FICHIER, la LIGNE et la VALEUR recopiée, sinon la
    correction se chercherait à l'aveugle.
    """
    racine_paquet = (
        Path(__file__).resolve().parent.parent / "src" / "m3_estimation"
    )
    verdicts_interdits = set(contrats.VERDICTS_ESTIMATION)

    def _identites_des_docstrings(arbre):
        """Identités des nœuds ``ast.Constant`` qui SONT des docstrings :
        un ``ast.Expr`` en tête de corps de module, de classe ou de
        fonction est de la documentation, pas du code.
        """
        identites = set()
        for noeud in ast.walk(arbre):
            if not isinstance(
                noeud,
                (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                 ast.ClassDef),
            ):
                continue
            if not noeud.body:
                continue
            premier = noeud.body[0]
            if (
                isinstance(premier, ast.Expr)
                and isinstance(premier.value, ast.Constant)
                and isinstance(premier.value.value, str)
            ):
                identites.add(id(premier.value))
        return identites

    fichiers_analyses = 0
    recopies = []
    for chemin in sorted(racine_paquet.rglob("*.py")):
        if chemin.name == "contrats.py":
            continue
        fichiers_analyses += 1
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        docstrings = _identites_des_docstrings(arbre)
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Constant):
                continue
            if id(noeud) in docstrings:
                continue
            if (
                isinstance(noeud.value, str)
                and noeud.value in verdicts_interdits
            ):
                recopies.append(
                    str(chemin.relative_to(racine_paquet))
                    + ":"
                    + str(noeud.lineno)
                    + " : verdict recopié en littéral : "
                    + repr(noeud.value)
                )
    assert fichiers_analyses > 0, (
        "extracteur vide donc non probant : aucun fichier .py trouvé sous "
        + str(racine_paquet)
    )
    assert not recopies, (
        "un verdict se désigne par sa constante de contrats, jamais par "
        "un littéral recopié :\n" + "\n".join(recopies)
    )


@pytest.mark.parametrize(
    "surcharges, plancher_rentable, accepte",
    [
        ({"borne_basse": 200.0, "borne_haute": 100.0}, 150.0, False),
        ({"borne_basse": 100.0, "borne_haute": 50.0}, 100.0, False),
        ({"borne_haute": "200"}, 100.0, False),
        ({"borne_haute": True}, 100.0, False),
        ({"borne_basse": 150.0, "borne_haute": 150.0}, 100.0, True),
    ],
    ids=[
        "bornes_inversees_la_vraie_basse_sous_le_plancher",
        "bornes_inversees_a_egalite_avec_le_plancher",
        "borne_haute_chaine",
        "borne_haute_booleenne",
        "intervalle_degenere_borne_basse_egale_borne_haute",
    ],
)
def test_un_intervalle_inverse_est_refuse(
    surcharges, plancher_rentable, accepte
):
    """Un intervalle INVERSÉ — ``borne_basse > borne_haute`` — ou dont la
    ``borne_haute`` n'est pas un nombre fini : rejet ``(None, verdict)`` ;
    un intervalle DÉGÉNÉRÉ — ``borne_basse == borne_haute`` — est ACCEPTÉ.

    Un intervalle inversé est une donnée incohérente : la confrontation
    comparerait la borne MAJEURE du lot au plancher, et l'alerte manquerait
    au moment précis où elle serait la plus utile — le premier cas reprend
    le scénario de la revue : ``borne_basse`` à 200, vraie borne inférieure
    à 100, plancher à 150, où ``200 < 150`` est faux alors que la vraie
    borne basse est sous le plancher. Empêcherait de casser : l'absence de
    la garde, qui laisserait confronter la mauvaise grandeur en silence ;
    ou une garde trop large qui refuserait AUSSI l'égalité — le cas de
    CONTRÔLE ``borne_basse == borne_haute`` (barème à coût fixe, intervalle
    dégénéré valide) doit être ACCEPTÉ, sinon le test ne distinguerait pas
    « inversé » de « dégénéré ». ``borne_haute`` non numérique est rejetée
    AVANT toute comparaison : ``isinstance(True, int)`` étant vrai en
    Python, le booléen est éprouvé au même titre que la chaîne. L'appel est
    fait dans un ``try`` : toute exception échappée est un échec qui nomme
    son TYPE, et chaque code de verdict de rejet appartient au catalogue
    fermé M3.
    """
    intervalle = _intervalle_valide(**surcharges)
    try:
        constat, verdict = plancher.confronter_au_plancher(
            intervalle, plancher_rentable
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    if accepte:
        assert verdict is None
        assert constat is not None
        assert set(constat) == {"alerte_plancher", "verdict_estimation"}
        assert constat["alerte_plancher"] is False
        assert (
            constat["verdict_estimation"] == contrats.VERDICT_AUCUN_BLOCAGE
        )
    else:
        assert constat is None
        assert verdict["code"] in verdicts.CODES_M3_LIST
