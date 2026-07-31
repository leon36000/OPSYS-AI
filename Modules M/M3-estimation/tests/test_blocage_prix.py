"""Tests de la garde anti-précision-inventée et du prix bloqué (cahier M3-S004).

Ces tests verrouillent la fonction ``blocage_prix.decider_blocage`` : la règle
de blocage (niveau INDETERMINE ou verdict QUALITE_ENTREE_INSUFFISANTE), la
priorité du verdict qui NOMME la cause, l'absence totale de fuite numérique
quand le prix est bloqué (aucun chiffre ne quitte M3), les bornes EXACTEMENT
``None`` (jamais zéro), la reprise des éléments manquants dans une raison non
accusatoire (R-020), le rejet contrôlé ``(None, verdict)`` fail-closed sans
exception, et la preuve statique par AST d'absence de réseau, de modèle,
d'aléa et d'horloge.

Le module ``m3_estimation/blocage_prix.py`` n'existe pas encore :
ce fichier doit ÉCHOUER à l'exécution — c'est le RED attendu de la story.
"""

import ast
import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from m3_estimation import blocage_prix, contrats, hierarchie_echelle, qualite_photos, verdicts

# Verdicts d'estimation qui BLOQUENT le prix : celui qui nomme la cause
# (QUALITE_ENTREE_INSUFFISANTE) et l'échappatoire D-032 (INDETERMINE), qui ne
# doit être retenu que si rien d'autre ne classifie.
VERDICTS_BLOQUANTS = frozenset(
    {
        "QUALITE_ENTREE_INSUFFISANTE",
        "INDETERMINE",
    }
)

# Jeu FERMÉ des verdicts d'estimation que la décision peut produire : le
# verdict acceptable de la qualification, le verdict qui nomme la cause, et
# l'échappatoire D-032. Aucune autre valeur n'est légitime.
# Jeu FERMÉ des verdicts d'estimation, LU dans le contrat du paquet
# (``contrats.VERDICTS_ESTIMATION``) et JAMAIS recopié à la main — à
# l'identique des niveaux de confiance ci-dessous, lus dans le contrat du
# module voisin. Un catalogue recopié dans un test valide le code contre
# l'erreur du test : c'est exactement ainsi que « QUALITE_ENTREE_SUFFISANTE »,
# verdict inventé absent de l'énuméré VerdictEstimation de l'architecture, a
# traversé 238 tests verts. Le test de non-divergence plus bas confronte la
# copie à l'architecture pour qu'elle ne dérive pas en silence.
VERDICTS_ESTIMATION_FERMES = frozenset(contrats.VERDICTS_ESTIMATION)

# Les trois niveaux de confiance qui ne déclenchent PAS le blocage à eux
# seuls, lus dans le contrat du module voisin — jamais recopiés à la main.
NIVEAUX_NON_INDERMINES = [
    niveau
    for niveau in hierarchie_echelle.NIVEAUX_CONFIANCE
    if niveau != "INDETERMINE"
]

# Termes désignant un responsable, interdits par R-020 : les raisons de
# blocage sont des constats, jamais des accusations.
TERMES_ACCUSATOIRES = (
    "technicien",
    "client",
    "utilisateur",
    "faute",
    "oubli",
    "n'a pas",
)

# Imports interdits : ni réseau, ni sous-processus, ni moteur de poids, ni
# aléa, ni horloge — ce module ne tire rien, ne date rien, ne calcule aucun
# prix ; il décide seulement du blocage.
IMPORTS_INTERDITS = frozenset(
    {
        "socket",
        "urllib",
        "requests",
        "http",
        "random",
        "time",
        "datetime",
        "subprocess",
        "torch",
    }
)


def _qualification_valide(**surcharges):
    """Fabrique une qualification acceptable par défaut, avec surcharges.

    Chaque test ne surcharge QUE ce qu'il fait varier ; tout le reste reste
    la qualification nominale : des photos acceptables, un verdict d'entrée
    suffisante, aucun blocage, aucun élément manquant.
    """
    qualification = {
        "photos_acceptables": ["photo-nominale"],
        "verdict_estimation": "AUCUN_BLOCAGE",
        "prix_bloque": False,
        "elements_manquants": [],
    }
    qualification.update(surcharges)
    return qualification


def _iterer_valeurs_numeriques(structure, chemin=()):
    """Itère récursivement les ``(chemin, valeur)`` numériques d'une structure.

    Les booléens sont exclus EXPLICITEMENT : ``isinstance(True, int)`` est
    vrai en Python, et sans cette exclusion le test de non-fuite passerait
    pour la mauvaise raison — un booléen n'est pas un chiffre au sens de
    « aucun chiffre ne quitte M3 ».
    """
    if isinstance(structure, dict):
        for cle, valeur in structure.items():
            yield from _iterer_valeurs_numeriques(valeur, chemin + (cle,))
    elif isinstance(structure, (list, tuple)):
        for index, valeur in enumerate(structure):
            yield from _iterer_valeurs_numeriques(valeur, chemin + (index,))
    elif isinstance(structure, bool):
        return
    elif isinstance(structure, (int, float)):
        yield chemin, structure


def test_structure_exacte_de_la_decision():
    """La décision porte EXACTEMENT ses quatre clés, et l'intervalle les
    siennes.

    Empêcherait de casser : une dérive silencieuse de la structure (clé
    renommée, ajoutée ou retirée) qui rendrait caducs tous les consommateurs
    du contrat sans qu'aucun test ne s'en aperçoive.
    """
    decision, verdict = blocage_prix.decider_blocage(
        "MULTI_VUES", _qualification_valide()
    )
    assert verdict is None
    assert set(decision) == {
        "prix_bloque",
        "verdict_estimation",
        "intervalle_confiance",
        "raison_blocage",
    }
    assert isinstance(decision["prix_bloque"], bool)
    assert set(decision["intervalle_confiance"]) == {
        "borne_basse",
        "borne_haute",
        "niveau",
    }


def test_aucun_chiffre_ne_fuit_quand_le_prix_est_bloque():
    """Cœur de la story : parcours RÉCURSIF de la décision bloquée — aucune
    valeur numérique n'y apparaît, à la SEULE exception du champ
    ``intervalle_confiance["niveau"]``.

    Empêcherait de casser : une précision inventée qui fuiterait dans une
    structure imbriquée (borne, score, compteur) alors que le prix est
    bloqué — « aucun chiffre ne quitte M3 quand le prix est bloqué ». Les
    booléens sont exclus explicitement du comptage, sinon ``prix_bloque``
    lui-même serait lu comme un chiffre et le test passerait ou échouerait
    pour la mauvaise raison. Trois scénarios bloqués sont éprouvés :
    INDETERMINE seul, les deux causes cumulées, et la qualité insuffisante
    seule.
    """
    scenarios = [
        ("INDETERMINE", _qualification_valide()),
        (
            "INDETERMINE",
            _qualification_valide(
                verdict_estimation="QUALITE_ENTREE_INSUFFISANTE",
                prix_bloque=True,
                elements_manquants=["photo de face", "référence d'échelle"],
            ),
        ),
        (
            "MONO_VUE_BORNES_LARGES",
            _qualification_valide(
                verdict_estimation="QUALITE_ENTREE_INSUFFISANTE",
                prix_bloque=True,
                elements_manquants=["photo de face"],
            ),
        ),
    ]
    for niveau, qualification in scenarios:
        decision, verdict = blocage_prix.decider_blocage(niveau, qualification)
        assert verdict is None
        assert decision["prix_bloque"] is True
        for chemin, valeur in _iterer_valeurs_numeriques(decision):
            assert chemin == ("intervalle_confiance", "niveau"), (
                "valeur numérique hors du champ autorisé : "
                + repr(chemin)
                + " = "
                + repr(valeur)
            )


def test_les_bornes_sont_none_pas_zero_quand_le_prix_est_bloque():
    """Les bornes sont EXACTEMENT ``None``, jamais ``0``, ``0.0`` ou ``""``.

    Empêcherait de casser : une valeur « vide » qui serait lue comme un prix
    — ``0`` est un chiffre affichable, ``None`` est l'absence de prix. La
    comparaison est ``is None``, jamais un test de vacuité.
    """
    decision, verdict = blocage_prix.decider_blocage(
        "INDETERMINE", _qualification_valide()
    )
    assert verdict is None
    assert decision["prix_bloque"] is True
    assert decision["intervalle_confiance"]["borne_basse"] is None
    assert decision["intervalle_confiance"]["borne_haute"] is None


def test_raison_blocage_non_vide_et_non_blanche():
    """La raison de blocage est une chaîne non vide ET non blanche.

    Empêcherait de casser : une chaîne composée uniquement d'espaces —
    ``not "   "`` est faux en Python, donc un simple test de vérité ne
    suffit pas ; une raison blanche n'aide personne à comprendre le
    blocage.
    """
    decision, verdict = blocage_prix.decider_blocage(
        "INDETERMINE",
        _qualification_valide(
            verdict_estimation="QUALITE_ENTREE_INSUFFISANTE",
            prix_bloque=True,
            elements_manquants=["photo de face"],
        ),
    )
    assert verdict is None
    assert decision["prix_bloque"] is True
    raison = decision["raison_blocage"]
    assert isinstance(raison, str)
    assert raison != ""
    assert raison.strip() != ""


def test_le_verdict_qui_nomme_la_cause_prime_sur_indetermine():
    """Niveau INDETERMINE ET qualification QUALITE_ENTREE_INSUFFISANTE :
    le verdict retenu est QUALITE_ENTREE_INSUFFISANTE.

    Empêcherait de casser : un ordre de priorité inversé qui rabattrait le
    verdict sur l'échappatoire « on ne sait pas pourquoi » (D-032) alors
    qu'une cause nommable existe — INDETERMINE ne doit être choisi que si
    rien d'autre ne classifie. Éprouver un seul des deux cas ne
    distinguerait pas les deux ordres de priorité : le cas INDETERMINE
    seul est éprouvé par le test suivant.
    """
    decision, verdict = blocage_prix.decider_blocage(
        "INDETERMINE",
        _qualification_valide(
            verdict_estimation="QUALITE_ENTREE_INSUFFISANTE",
            prix_bloque=True,
            elements_manquants=["photo de face"],
        ),
    )
    assert verdict is None
    assert decision["prix_bloque"] is True
    assert decision["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"


def test_indetermine_seul_produit_le_verdict_indetermine():
    """Niveau INDETERMINE avec une qualification acceptable : le prix est
    bloqué et le verdict retenu est INDETERMINE.

    Empêcherait de casser : l'oubli de la première branche de la règle (le
    niveau à lui seul bloque), ou un verdict inventé hors de l'échappatoire
    D-032 quand aucune cause n'est nommable. La raison reste une phrase non
    vide même sans éléments manquants fournis.
    """
    decision, verdict = blocage_prix.decider_blocage(
        "INDETERMINE", _qualification_valide()
    )
    assert verdict is None
    assert decision["prix_bloque"] is True
    assert decision["verdict_estimation"] == "INDETERMINE"
    assert decision["raison_blocage"].strip() != ""


@pytest.mark.parametrize(
    "niveau",
    NIVEAUX_NON_INDERMINES,
    ids=[
        "reference_echelle",
        "multi_vues",
        "mono_vue_bornes_larges",
    ],
)
def test_pas_de_blocage_quand_rien_ne_bloque(niveau):
    """Pour chacun des trois niveaux non indéterminés, avec une qualification
    acceptable : aucun blocage.

    Empêcherait de casser : un blocage par défaut ou un verdict bloquant
    résiduel — ``prix_bloque`` est ``False``, ``raison_blocage`` est
    ``None``, le verdict n'est PAS un verdict bloquant, et les bornes
    restent ``None`` : ce module ne CALCULE aucun prix, il décide
    seulement du blocage (le calcul est S005).
    """
    decision, verdict = blocage_prix.decider_blocage(
        niveau, _qualification_valide()
    )
    assert verdict is None
    assert decision["prix_bloque"] is False
    assert decision["raison_blocage"] is None
    assert decision["verdict_estimation"] not in VERDICTS_BLOQUANTS
    assert decision["intervalle_confiance"]["borne_basse"] is None
    assert decision["intervalle_confiance"]["borne_haute"] is None
    # Le taux de l'intervalle et le nom du niveau de confiance sont deux
    # grandeurs différentes qui partagent un mot ; les confondre a laissé une chaîne occuper un champ numérique.
    assert isinstance(decision["intervalle_confiance"]["niveau"], float)
    assert decision["intervalle_confiance"]["niveau"] == blocage_prix.NIVEAU_CONFIANCE_NOMINAL


@pytest.mark.parametrize(
    "niveau, qualification",
    [
        ("REFERENCE_ECHELLE", _qualification_valide()),
        ("MULTI_VUES", _qualification_valide()),
        ("INDETERMINE", _qualification_valide()),
        (
            "MULTI_VUES",
            _qualification_valide(
                verdict_estimation="QUALITE_ENTREE_INSUFFISANTE",
                prix_bloque=True,
                elements_manquants=["photo de face"],
            ),
        ),
        (
            "INDETERMINE",
            _qualification_valide(
                verdict_estimation="QUALITE_ENTREE_INSUFFISANTE",
                prix_bloque=True,
                elements_manquants=["photo de face"],
            ),
        ),
    ],
    ids=[
        "reference_echelle_sans_blocage",
        "multi_vues_sans_blocage",
        "indetermine_seul",
        "qualite_insuffisante_seule",
        "les_deux_causes_cumulees",
    ],
)
def test_verdict_estimation_toujours_dans_le_catalogue_ferme(
    niveau, qualification
):
    """Le ``verdict_estimation`` produit appartient toujours au jeu fermé,
    sur des entrées VARIÉES — pas une seule.

    Empêcherait de casser : l'apparition d'un verdict hors catalogue (faute
    de frappe, verdict renommé, échappatoire D-032 contournée) sur l'un des
    chemins — bloqué par le niveau, bloqué par la qualification, bloqué par
    les deux, ou non bloqué.
    """
    decision, verdict = blocage_prix.decider_blocage(niveau, qualification)
    assert verdict is None
    assert decision["verdict_estimation"] in VERDICTS_ESTIMATION_FERMES


def test_les_elements_manquants_sont_repris_dans_la_raison():
    """Chaque élément manquant porté par la qualification se retrouve dans
    ``raison_blocage``.

    Empêcherait de casser : une raison générique qui n'aiderait personne —
    la phrase de blocage doit NOMMER ce qui manque. Ce scénario éprouve
    aussi la seconde branche de la règle prise isolément : la qualification
    seule (niveau MULTI_VUES par ailleurs satisfait) bloque le prix, et le
    verdict retenu est celui qui nomme la cause.
    """
    elements = ["photo de face", "référence d'échelle certifiée"]
    decision, verdict = blocage_prix.decider_blocage(
        "MULTI_VUES",
        _qualification_valide(
            verdict_estimation="QUALITE_ENTREE_INSUFFISANTE",
            prix_bloque=True,
            elements_manquants=elements,
        ),
    )
    assert verdict is None
    assert decision["prix_bloque"] is True
    assert decision["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    for element in elements:
        assert element in decision["raison_blocage"]


def test_raison_blocage_non_accusatoire_r020():
    """``raison_blocage`` ne contient aucun terme désignant un responsable.

    Empêcherait de casser : une formulation accusatoire (R-020) — les
    raisons de blocage sont des constats sur les entrées, jamais des mises
    en cause d'une personne. La comparaison est faite en minuscules pour ne
    pas dépendre de la casse.
    """
    decision, verdict = blocage_prix.decider_blocage(
        "INDETERMINE",
        _qualification_valide(
            verdict_estimation="QUALITE_ENTREE_INSUFFISANTE",
            prix_bloque=True,
            elements_manquants=["photo de face", "référence d'échelle"],
        ),
    )
    assert verdict is None
    assert decision["prix_bloque"] is True
    raison = decision["raison_blocage"].lower()
    for terme in TERMES_ACCUSATOIRES:
        assert terme not in raison


@pytest.mark.parametrize(
    "niveau, qualification",
    [
        ("NIVEAU_INCONNU", _qualification_valide()),
        ("MULTI_VUES", "pas-un-dict"),
        (
            "MULTI_VUES",
            {
                "photos_acceptables": ["photo-nominale"],
                "verdict_estimation": "AUCUN_BLOCAGE",
                "prix_bloque": False,
            },
        ),
    ],
    ids=[
        "niveau_hors_des_quatre_valeurs_fermees",
        "qualification_qui_n_est_pas_un_dict",
        "qualification_amputee_d_une_cle",
    ],
)
def test_entrees_invalides_fail_closed_sans_plantage(niveau, qualification):
    """Entrées invalides : ``(None, verdict)`` avec un code du catalogue,
    JAMAIS une exception qui s'échappe.

    Empêcherait de casser : la remontée d'une exception nue (KeyError sur
    clé absente, AttributeError sur non-dict) au lieu du rejet contrôlé —
    le module est fail-closed : toute entrée qu'il ne reconnaît pas produit
    un verdict du catalogue fermé, et l'appel est fait DANS un ``try`` pour
    que toute exception échappée soit un échec nommant son TYPE.
    """
    try:
        decision, verdict = blocage_prix.decider_blocage(niveau, qualification)
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
        )
    assert decision is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_aucun_import_reseau_modele_alea_ni_horloge():
    """Preuve STATIQUE par AST : aucun import de réseau, de sous-processus,
    de moteur de poids, d'aléa ni d'horloge.

    Empêcherait de casser : l'introduction d'un import réseau (socket,
    urllib, requests, http), d'un sous-processus, d'un moteur d'inférence
    (torch), d'un tirage aléatoire (random) ou d'une datation (time,
    datetime) — ce module ne tire rien, ne date rien et ne calcule aucun
    prix ; il décide seulement du blocage. La preuve parcourt ``ast.walk``
    sur ``ast.Import`` et ``ast.ImportFrom`` : un nom cité dans un
    commentaire n'est PAS un import, et les imports relatifs intra-paquet
    sont exclus par construction (``level`` non nul).
    """
    source = Path(blocage_prix.__file__).read_text(encoding="utf-8")
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


@pytest.mark.parametrize(
    "qualification",
    [
        set(_qualification_valide()),
        list(_qualification_valide()),
    ],
    ids=[
        "ensemble_portant_les_bons_noms",
        "liste_portant_les_bons_noms",
    ],
)
def test_un_ensemble_portant_les_bons_noms_est_refuse(qualification):
    """Une valeur qui n'est PAS un dict mais dont ``set(...)`` égale
    EXACTEMENT les clés attendues est refusée par la garde de TYPE.

    Les deux gardes — ``isinstance(qualification, dict)`` puis
    ``set(qualification) != CHAMPS_QUALIFICATION`` — paraissent redondantes
    mais ne le sont pas : une collection portant exactement les bons noms
    franchit le contrôle des clés, puis l'accès indexé
    ``qualification["verdict_estimation"]`` lèverait ``TypeError`` (sur un
    ``set``) ou lirait une chaîne comme un verdict (sur une ``list``). Ce
    que la garde de type garantit n'est pas une détection supplémentaire
    mais un refus NOMMÉ au lieu d'un plantage — et sans ce cas, sa
    suppression laisse la suite VERTE (mesuré), parce que les non-dict des
    autres tests sont rejetés par la garde des clés pour la mauvaise
    raison. L'enveloppe ``try`` est ce qui rend la promesse vérifiable :
    sans elle, l'échec du test SERAIT le plantage qu'il interdit. Deux
    formes sont éprouvées pour que le test ne passe pas par accident sur
    une seule.
    """
    try:
        decision, verdict = blocage_prix.decider_blocage(
            "MULTI_VUES", qualification
        )
    except Exception as erreur:
        pytest.fail(
            "une exception s'est échappée au lieu d'un verdict de rejet : "
            + type(erreur).__name__
            + " : "
            + str(erreur)
            + " (forme testée : "
            + type(qualification).__name__
            + ")"
        )
    assert decision is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def _extraire_verdicts_estimation(texte_architecture):
    """Extrait la liste ORDONNÉE des valeurs de l'énuméré ``VerdictEstimation``.

    La lecture est BORNÉE à la section de l'énuméré : elle démarre au titre
    markdown qui nomme ``VerdictEstimation`` et s'arrête au titre suivant,
    parce que l'architecture contient d'autres tableaux de même forme
    (``NiveauConfiance`` notamment) qu'une recherche non bornée mélangerait.
    Dans la section, seules les lignes de tableau markdown sont lues ; la
    valeur est prise dans la PREMIÈRE colonne, quand elle tient entièrement
    entre accents graves — l'en-tête du tableau et sa ligne de séparation
    n'ont pas d'accents graves et sont écartés sans test spécial. La collecte
    s'arrête à la première ligne hors tableau une fois le tableau commencé :
    le tableau suit le titre, et ce qui viendrait après dans la section ne
    lui appartiendrait pas. Les blocs clôturés par des accents graves triples
    sont ignorés : une ligne qui y ressemble à un titre ou à un tableau n'est
    ni un titre ni un tableau. Retourne une LISTE, jamais un ensemble :
    l'ordre de l'énuméré fait partie du contrat.
    """
    valeurs = []
    dans_section = False
    dans_tableau = False
    dans_bloc_code = False
    for ligne in texte_architecture.splitlines():
        ligne_nettoyee = ligne.strip()
        if ligne_nettoyee.startswith("```"):
            dans_bloc_code = not dans_bloc_code
            continue
        if dans_bloc_code:
            continue
        if ligne_nettoyee.startswith("#"):
            if dans_section:
                break
            if "VerdictEstimation" in ligne_nettoyee:
                dans_section = True
            continue
        if not dans_section:
            continue
        if not ligne_nettoyee.startswith("|"):
            if dans_tableau:
                break
            continue
        dans_tableau = True
        premiere_colonne = ligne_nettoyee.split("|")[1].strip()
        if (
            len(premiere_colonne) >= 2
            and premiere_colonne.startswith("`")
            and premiere_colonne.endswith("`")
        ):
            valeur = premiere_colonne[1:-1]
            if valeur != "" and "`" not in valeur:
                valeurs.append(valeur)
    return valeurs


def test_le_catalogue_des_verdicts_ne_diverge_pas_de_l_architecture():
    """Une copie qu'on ne confronte pas dérive en silence.

    ``contrats.VERDICTS_ESTIMATION`` est une COPIE de l'énuméré
    ``VerdictEstimation`` de ``docs/bmad/03-ARCHITECTURE.md``, et ce test la
    confronte à sa source : une copie qu'on ne confronte pas dérive en
    silence ; c'est exactement ainsi qu'un verdict inventé
    (« QUALITE_ENTREE_SUFFISANTE », déclaré à la main dans ce même fichier et
    absent de l'énuméré) a traversé 238 tests verts — le test validait le
    module contre un catalogue que le test avait lui-même inventé.

    Empêcherait de casser : toute dérive entre la copie épinglée et la
    source — valeur ajoutée, retirée, renommée ou RÉORDONNÉE. La comparaison
    porte sur des LISTES ordonnées, jamais des ensembles : l'ordre de
    l'énuméré fait partie du contrat, et une comparaison d'ensembles
    laisserait passer une permutation. L'extracteur est borné à la section de
    ``VerdictEstimation`` pour ne pas mélanger les autres tableaux de même
    forme (``NiveauConfiance`` notamment), et s'il n'extrait RIEN le test
    échoue : un extracteur vide passe toujours, donc un extracteur vide
    n'est jamais probant.
    """
    chemin_architecture = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "bmad"
        / "03-ARCHITECTURE.md"
    )
    texte_architecture = chemin_architecture.read_text(encoding="utf-8")
    verdicts_extraits = _extraire_verdicts_estimation(texte_architecture)
    assert verdicts_extraits != [], (
        "extracteur vide donc non probant : aucune valeur extraite de la "
        "section VerdictEstimation de "
        + str(chemin_architecture)
        + " — un extracteur qui ne trouve rien passe toujours ; vérifier que "
        "le fichier existe, que le titre de section nomme « VerdictEstimation » "
        "et que le tableau le suit"
    )
    assert list(contrats.VERDICTS_ESTIMATION) == verdicts_extraits, (
        "divergence entre contrats.VERDICTS_ESTIMATION et l'énuméré "
        "VerdictEstimation de l'architecture — la comparaison porte sur des "
        "listes ordonnées, l'ordre fait partie du contrat :\n"
        "copie contrats : "
        + repr(list(contrats.VERDICTS_ESTIMATION))
        + "\nsource architecture : "
        + repr(verdicts_extraits)
    )
