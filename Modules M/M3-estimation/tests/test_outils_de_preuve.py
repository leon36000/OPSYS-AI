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


def _noms_cibles(noeud):
    """Retourne récursivement les noms liés par une cible d'affectation."""
    if isinstance(noeud, ast.Name):
        return [noeud.id]
    if isinstance(noeud, (ast.Tuple, ast.List)):
        return [
            nom
            for element in noeud.elts
            for nom in _noms_cibles(element)
        ]
    return []


def _chaines_de_valeur(valeur):
    """Extrait les littéraux chaîne réellement atteignables depuis une valeur."""
    return [
        noeud.value
        for noeud in ast.walk(valeur)
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)
    ]


def _valeur_est_un_chemin_source(valeur):
    """Distingue un chemin source d'un leurre affecté à une majuscule."""
    return (
        any(
            isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Div)
            for noeud in ast.walk(valeur)
        )
        or any("m3_estimation" in chaine for chaine in _chaines_de_valeur(valeur))
    )


def _affectations_chemins_source(arbre):
    """Extrait les littéraux des affectations majuscules de chemins source."""
    affectations = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Assign):
            noms = [
                nom
                for cible in noeud.targets
                for nom in _noms_cibles(cible)
                if nom.isupper()
            ]
            valeur = noeud.value
        elif isinstance(noeud, ast.AnnAssign):
            noms = [
                nom
                for nom in _noms_cibles(noeud.target)
                if nom.isupper()
            ]
            valeur = noeud.value
        else:
            continue

        if not noms or valeur is None or not _valeur_est_un_chemin_source(valeur):
            continue

        chaines = _chaines_de_valeur(valeur)
        for nom in noms:
            affectations.append((nom, chaines))
    return affectations


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
    """Exige une cible dans une affectation majuscule réellement liée à un chemin.

    Le nom du script ne suffit pas, mais une chaîne libre, une docstring ou une
    affectation à un nom minuscule ne suffit pas davantage. Deux formes correctes
    coexistent : un chemin complet construit dans une seule affectation, ou un
    dossier déclaré puis des noms de fichiers affectés simultanément dans un tuple.
    L'extracteur examine donc chaque nom majuscule de ces tuples et les littéraux
    atteignables dans leur valeur, y compris au sein d'opérateurs ``/`` imbriqués.
    Il refuse néanmoins un leurre tel que ``LEURRE = "foo.py"`` : l'affectation
    doit faire intervenir ``/`` ou contenir explicitement ``m3_estimation``.
    """
    discordances = []
    for outil in _outils_de_mutation():
        attendu = outil.stem[len("muter_"):]
        arbre = ast.parse(outil.read_text(encoding="utf-8"))
        affectations = _affectations_chemins_source(arbre)
        vise = any(
            chaine == f"{attendu}.py" or chaine.endswith(f"/{attendu}.py")
            for _, chaines in affectations
            for chaine in chaines
        )
        if not vise:
            examinees = [
                f"{nom}={chaines!r}"
                for nom, chaines in affectations
            ]
            discordances.append(
                f"{outil.name} : affectations examinées "
                f"{'; '.join(examinees) if examinees else '<aucune>'}"
            )
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
