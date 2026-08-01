"""Les gardes des outils de preuve sont vérifiées directement par pytest.

Ces tests remplacent un vérificateur monolithique dont la complexité était devenue
le goulot : après sept rondes de revue, chaque itération avait apporté son défaut
propre. Les mêmes propriétés tiennent ici en quelques lignes lisibles, isolées par
pytest et exécutées par la CI.

Limite assumée : ces tests certifient que les gardes se déclenchent sur les
sabotages effectués ici. Ils ne certifient pas les instruments contre un auteur
hostile : un outil simulant exactement les messages attendus passerait. Un
instrument ne peut pas prouver qu'un autre instrument n'est pas un leurre.
"""

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

# Ce sont des PHRASES, et non des mots isolés : un mot pourrait être présent dans
# une sortie saine ou dans une erreur sans rapport et ne discriminerait pas la garde.
PHRASE_SUITE_ROUGE = "muter une suite non verte ne prouve rien"
PHRASE_SANS_GARDE = "l'extracteur n'a rien trouvé"

_M3 = Path(__file__).resolve().parents[1]
_RACINE = Path(__file__).resolve().parents[3]
_TESTS = _M3 / "tests"
_SOURCE = _M3 / "src" / "m3_estimation"
_OUTILS = _TESTS / "outils_preuve"
_ENUMERATEUR = _OUTILS / "enumerer_gardes.py"
_OUTILS_MUTATION = sorted(_OUTILS.glob("muter_*.py"))
_SENTINEL_RECURSION = _TESTS / ".gardes_des_outils_enfant"

if _SENTINEL_RECURSION.exists():
    pytestmark = pytest.mark.skip(
        reason="processus enfant d'un outil : éviter l'exécution récursive des épreuves"
    )


def _parametres_outils():
    """Conserve un cas exécutable afin qu'une liste vide échoue explicitement."""
    return _OUTILS_MUTATION or [None]


def _identifier_outil(outil):
    return outil.name if outil is not None else "aucun-outil-de-mutation"


def _exiger_outil(outil):
    assert _OUTILS_MUTATION, (
        "aucun outil de mutation trouvé : le contrôle n'est pas probant, "
        "car un scanner vide passe toujours"
    )
    assert outil is not None, "outil de mutation absent malgré une paramétrisation active"


def _sortie(resultat):
    return resultat.stdout + "\n" + resultat.stderr


def _lancer(outil, *arguments):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(outil),
            str(_RACINE),
            *arguments,
        ],
        capture_output=True,
        text=True,
        cwd=_RACINE,
    )


@pytest.fixture
def lancer_outil():
    """Empêche qu'un pytest lancé par un outil ne relance ces épreuves récursivement."""
    assert not _SENTINEL_RECURSION.exists(), (
        f"sentinelle d'épreuve déjà présente : {_SENTINEL_RECURSION}"
    )
    _SENTINEL_RECURSION.write_text("processus enfant des gardes\n", encoding="utf-8")
    try:
        yield _lancer
    finally:
        if _SENTINEL_RECURSION.exists():
            _SENTINEL_RECURSION.unlink()


@pytest.fixture
def suite_deja_rouge():
    """Dépose puis retire un test volontairement rouge pour les batteries."""
    chemin = _TESTS / "test_epreuve_garde_suite_rouge.py"
    assert not chemin.exists(), f"fichier d'épreuve déjà présent : {chemin}"
    chemin.write_text(
        "def test_epreuve_deliberement_rouge():\n"
        '    assert False, "épreuve volontairement rouge des gardes"\n',
        encoding="utf-8",
    )
    try:
        yield chemin
    finally:
        if chemin.exists():
            chemin.unlink()


@pytest.fixture
def module_sans_garde():
    """Dépose puis retire un module dont l'AST ne contient aucun ``if``."""
    chemin = _SOURCE / "epreuve_module_sans_garde.py"
    assert not chemin.exists(), f"module d'épreuve déjà présent : {chemin}"
    chemin.write_text(
        "def valeur_epreuve():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    try:
        yield chemin
    finally:
        if chemin.exists():
            chemin.unlink()


@pytest.mark.parametrize(
    "outil",
    _parametres_outils(),
    ids=_identifier_outil,
)
def test_chaque_batterie_refuse_une_suite_deja_rouge(
    outil, suite_deja_rouge, lancer_outil
):
    _exiger_outil(outil)
    resultat = lancer_outil(outil)
    sortie = _sortie(resultat)

    assert resultat.returncode != 0, f"{outil.name} a accepté une suite déjà rouge"
    assert PHRASE_SUITE_ROUGE in sortie, (
        f"{outil.name} a échoué sans identifier la suite déjà rouge :\n{sortie}"
    )


def test_l_enumerateur_refuse_une_suite_deja_rouge(
    suite_deja_rouge, lancer_outil
):
    resultat = lancer_outil(_ENUMERATEUR)
    sortie = _sortie(resultat)

    assert resultat.returncode != 0, "l'énumérateur a accepté une suite déjà rouge"
    assert PHRASE_SUITE_ROUGE in sortie, (
        "l'énumérateur a échoué sans identifier la suite déjà rouge :\n"
        f"{sortie}"
    )


def test_l_enumerateur_refuse_un_module_sans_garde(
    module_sans_garde, lancer_outil
):
    resultat = lancer_outil(_ENUMERATEUR, module_sans_garde.stem)
    sortie = _sortie(resultat)

    assert resultat.returncode != 0, "l'énumérateur a accepté un module sans garde"
    assert PHRASE_SANS_GARDE in sortie, (
        "l'énumérateur a échoué sans identifier l'extracteur vide :\n"
        f"{sortie}"
    )


def test_les_deux_abandons_de_l_enumerateur_sont_distincts(
    suite_deja_rouge, module_sans_garde, lancer_outil
):
    resultat_rouge = lancer_outil(_ENUMERATEUR)
    resultat_vide = lancer_outil(_ENUMERATEUR, module_sans_garde.stem)
    sortie_rouge = _sortie(resultat_rouge)
    sortie_vide = _sortie(resultat_vide)

    assert resultat_rouge.returncode != 0, (
        "l'énumérateur a accepté la condition de suite déjà rouge"
    )
    assert resultat_vide.returncode != 0, (
        "l'énumérateur a accepté la condition d'extracteur vide"
    )
    assert PHRASE_SUITE_ROUGE in sortie_rouge, (
        "abandon suite rouge non identifié :\n" f"{sortie_rouge}"
    )
    assert PHRASE_SANS_GARDE in sortie_vide, (
        "abandon extracteur vide non identifié :\n" f"{sortie_vide}"
    )
    assert sortie_rouge != sortie_vide, (
        "les abandons suite rouge et extracteur vide produisent la même sortie"
    )


@pytest.mark.parametrize(
    "outil",
    _parametres_outils(),
    ids=_identifier_outil,
)
def test_chaque_outil_est_sain_avant_sabotage(outil, lancer_outil):
    _exiger_outil(outil)
    resultat = lancer_outil(outil)
    sortie = _sortie(resultat)

    assert resultat.returncode == 0, (
        f"{outil.name} n'est pas sain avant sabotage :\n{sortie}"
    )
    assert PHRASE_SUITE_ROUGE not in sortie, (
        f"{outil.name} annonce une suite rouge à l'état sain :\n{sortie}"
    )


def _empreinte_chemin(chemin):
    """Retourne sha256 et mode ; un dossier a une empreinte vide stable."""
    mode = chemin.stat().st_mode & 0o7777
    if chemin.is_dir():
        return hashlib.sha256(b"").hexdigest(), mode
    return hashlib.sha256(chemin.read_bytes()).hexdigest(), mode


def _instantane_arborescence():
    """Capture tous les chemins utiles sous src/ et tests/, caches exclus."""
    instantane = {}
    for racine in (_M3 / "src", _TESTS):
        chemins = [racine, *racine.rglob("*")]
        for chemin in sorted(chemins, key=str):
            relatif = chemin.relative_to(_M3)
            if "__pycache__" in relatif.parts or ".pytest_cache" in relatif.parts:
                continue
            instantane[str(relatif)] = _empreinte_chemin(chemin)
    return instantane


def test_aucune_trace_apres_les_epreuves(
    suite_deja_rouge, module_sans_garde, lancer_outil
):
    avant = _instantane_arborescence()

    for outil in _OUTILS_MUTATION:
        resultat = lancer_outil(outil)
        sortie = _sortie(resultat)
        assert resultat.returncode != 0, (
            f"{outil.name} a accepté l'épreuve complète de suite rouge"
        )
        assert PHRASE_SUITE_ROUGE in sortie, (
            f"{outil.name} n'a pas nommé la suite rouge :\n{sortie}"
        )

    resultat_rouge = lancer_outil(_ENUMERATEUR)
    resultat_vide = lancer_outil(_ENUMERATEUR, module_sans_garde.stem)
    assert resultat_rouge.returncode != 0, (
        "l'énumérateur a accepté l'épreuve complète de suite rouge"
    )
    assert PHRASE_SUITE_ROUGE in _sortie(resultat_rouge), (
        "l'énumérateur n'a pas nommé la suite rouge"
    )
    assert resultat_vide.returncode != 0, (
        "l'énumérateur a accepté l'épreuve complète d'extracteur vide"
    )
    assert PHRASE_SANS_GARDE in _sortie(resultat_vide), (
        "l'énumérateur n'a pas nommé l'extracteur vide"
    )

    apres = _instantane_arborescence()
    chemins_avant = set(avant)
    chemins_apres = set(apres)
    apparus = sorted(chemins_apres - chemins_avant)
    disparus = sorted(chemins_avant - chemins_apres)
    contenu_modifie = sorted(
        chemin
        for chemin in chemins_avant & chemins_apres
        if avant[chemin][0] != apres[chemin][0]
    )
    mode_modifie = sorted(
        chemin
        for chemin in chemins_avant & chemins_apres
        if avant[chemin][1] != apres[chemin][1]
    )

    # L'horodatage est volontairement absent : pytest réécrit des caches et le
    # rendrait bruyant, tandis que contenu, mode et chemins restent probants.
    differences = {
        "chemin apparu": apparus,
        "chemin disparu": disparus,
        "contenu modifié": contenu_modifie,
        "mode modifié": mode_modifie,
    }
    assert not any(differences.values()), (
        "trace laissée après les épreuves : "
        + "; ".join(
            f"{nature}={chemins}"
            for nature, chemins in differences.items()
            if chemins
        )
    )
