"""Les outils de preuve doivent être EXÉCUTABLES là où ils sont livrés.

Une revue scellée a rendu APPROVE 0/3 sur une première version du dossier
``outils_preuve`` : elle embarquait ``muter_plancher.py`` alors que
``plancher.py`` n'existait pas encore sur la branche. Le script plantait sur
``FileNotFoundError``, et les sorties présentées dans le pack avaient été
produites sur une AUTRE branche — donc irreproductibles là où on les montrait.

Ces tests ferment cette classe : un outil qui accompagne une cible absente est
un outil qui ment sur ce qu'il prouve.
"""
import ast
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_OUTILS = Path(__file__).resolve().parent / "outils_preuve"
_SOURCE = _RACINE / "src" / "m3_estimation"
sys.path.insert(0, str(_RACINE / "src"))


def _outils_de_mutation():
    """Les scripts muter_<module>.py présents, triés — jamais une liste vide."""
    trouves = sorted(_OUTILS.glob("muter_*.py"))
    assert trouves, (
        f"aucun outil de mutation trouvé sous {_OUTILS} — un scanner qui ne "
        f"trouve rien passe toujours, donc ce test refuse de conclure"
    )
    return trouves


def test_chaque_outil_de_mutation_a_son_module_cible():
    """Un `muter_<module>.py` sans `<module>.py` plante au lieu de mesurer.

    Empêcherait de casser : la livraison d'un outil dont la cible n'existe pas
    encore sur la branche — exactement le défaut trouvé par la revue, où le
    script rendait FileNotFoundError et où les sorties du pack venaient d'une
    autre branche.
    """
    orphelins = []
    for outil in _outils_de_mutation():
        module = outil.stem[len("muter_"):]
        if not (_SOURCE / f"{module}.py").exists():
            orphelins.append(f"{outil.name} cible {module}.py, absent de {_SOURCE}")
    assert not orphelins, (
        "outil(s) de preuve sans cible — un outil ne vit dans le dépôt qu'avec "
        "le module qu'il mesure :\n  " + "\n  ".join(orphelins)
    )


def test_chaque_outil_de_mutation_declare_sa_cible_dans_son_code():
    """Le nom du fichier ne suffit pas : la cible doit être lue dans le code.

    Empêcherait de casser : un script renommé sans que son SRC soit mis à jour —
    le nom promettrait un module et le script en mesurerait un autre. La cible
    est extraite par AST du littéral affecté à SRC, jamais par le nom du fichier.
    """
    discordances = []
    for outil in _outils_de_mutation():
        attendu = outil.stem[len("muter_"):]
        arbre = ast.parse(outil.read_text(encoding="utf-8"))
        # Deux styles de déclaration coexistent : un chemin complet en un
        # littéral, ou un dossier puis le nom du fichier (``D / "module.py"``).
        # L'extracteur doit couvrir les DEUX, sinon il rapporte « aucune cible »
        # pour un script parfaitement correct — mesuré sur muter_qualite_photos.
        chaines = [
            n.value for n in ast.walk(arbre)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        vise = any(c == f"{attendu}.py" or c.endswith(f"/{attendu}.py") for c in chaines)
        if not vise:
            fichiers = sorted({c for c in chaines if c.endswith(".py")})
            discordances.append(f"{outil.name} : fichiers cités {fichiers or '<aucun>'}")
    assert not discordances, (
        "le nom du script ne correspond pas au module qu'il mesure :\n  "
        + "\n  ".join(discordances)
    )


@pytest.mark.parametrize("nom", ["enumerer_gardes.py"])
def test_les_outils_transverses_sont_presents_et_documentes(nom):
    """Un outil sans docstring ne dit pas ce qu'il prouve ni ce qu'il ne prouve pas.

    Empêcherait de casser : un instrument de mesure livré muet, dont personne ne
    peut vérifier la portée — c'est la portée sur-affirmée qui a valu deux
    objections de revue sur ce dossier.
    """
    chemin = _OUTILS / nom
    assert chemin.exists(), f"{nom} absent de {_OUTILS}"
    doc = ast.get_docstring(ast.parse(chemin.read_text(encoding="utf-8")))
    assert doc and len(doc) > 200, (
        f"{nom} : docstring absent ou trop court pour énoncer ce qu'il prouve"
    )
