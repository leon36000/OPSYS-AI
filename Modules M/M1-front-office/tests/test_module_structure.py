import ast
import pytest
from pathlib import Path

_NOM_PAQUET = "m1_front_office"

_M1 = Path(__file__).resolve().parents[1]


def test_arborescence_module():
    """Vérifie la présence des dossiers fondamentaux du module M1."""
    dossiers_requis = ["src", "tests", "contracts", "docs"]
    for dossier in dossiers_requis:
        chemin = _M1 / dossier
        assert chemin.is_dir(), f"Dossier manquant : {dossier} (attendu dans {_M1})"


def test_cadrage_bmad_present():
    """Vérifie que les trois artefacts de cadrage BMAD existent et contiennent un minimum de contenu."""
    artefacts = [
        "docs/bmad/01-BRIEF-ANALYSTE.md",
        "docs/bmad/02-PRD-PM.md",
        "docs/bmad/03-ARCHITECTURE.md",
    ]
    for artefact in artefacts:
        chemin = _M1 / artefact
        assert chemin.is_file(), f"Artefact BMAD absent : {artefact}"
        taille = chemin.stat().st_size
        assert taille > 500, (
            f"Artefact {artefact} trop léger ({taille} octets). "
            "Minimum 500 octets attendu pour un contenu significatif."
        )


def test_readme_present():
    """Vérifie la présence du README.md à la racine du module."""
    readme = _M1 / "README.md"
    assert readme.is_file(), "README.md introuvable à la racine du module"

def test_aucun_module_a_plat_sous_src():
    """PROUVE structurellement qu'aucun fichier .py ne subsiste À PLAT sous src/.

    L'identité de paquet ne protège que ce qui est DANS le paquet. Un nouveau
    module déposé directement sous src/ et importé à plat depuis un test
    rouvrirait exactement la collision que le chore #109 a fermée : sys.modules
    conserverait le premier arbre chargé et l'appartenance redeviendrait
    fonction de l'ordre de collecte.

    Ce contrôle est STRUCTUREL et non comportemental, à dessein : un fichier à
    plat que personne n'importe encore est inerte, donc invisible pour un test
    qui n'observe que les modules chargés — vérifié par mutation (copier un
    module à plat ne faisait rougir aucun test avant l'ajout de celui-ci).
    """
    src = _M1 / "src"
    a_plat = sorted(chemin.name for chemin in src.glob("*.py"))
    assert a_plat == [], (
        f"modules à plat sous src/ : {a_plat}. Ils doivent vivre dans le paquet "
        "src/m1_front_office/ pour que leur nom soit unique au dépôt."
    )
    paquets = [d.name for d in src.iterdir()
               if d.is_dir() and (d / "__init__.py").exists()]
    assert paquets == ["m1_front_office"], (
        f"src/ doit contenir exactement le paquet m1_front_office, trouvé : {paquets}"
    )

def test_aucun_sys_path_insert_vise_le_paquet():
    """PROUVE qu'aucun fichier de test n'insère le PAQUET dans sys.path.

    Deux chemins, deux rôles, et les confondre casse l'un des deux : sys.path
    doit recevoir src/ — le PARENT du paquet — car c'est lui qui rend
    « from PAQUET import ... » résoluble ; le paquet lui-même ne sert qu'à
    SCANNER les sources.

    Défaut réel trouvé par la revue scellée (round 2) : un fichier insérait le
    paquet et échouait EXÉCUTÉ SEUL, tout en passant dans la suite complète
    parce qu'un autre fichier avait inséré src/ avant lui — une dépendance à
    l'ordre de collecte, précisément ce que la mise en paquet doit supprimer.

    L'analyse est faite par AST et non sur le texte : une première version ne
    regardait que les lignes COMMENÇANT par « sys.path.insert », et un appel
    étalé sur plusieurs lignes lui échappait — trou confirmé par mutation au
    round 4. L'AST voit l'appel quelle que soit sa mise en forme.
    LIMITE ASSUMÉE, mesurée et signalée par la revue (round 5) : cette garde ne
    voit que les littéraux chaîne présents dans les arguments de l'appel. Une
    variable intermédiaire lui échappe :

        chemin = str(_SRC / "PAQUET")
        sys.path.insert(0, chemin)      # non détecté

    C'est acceptable parce que cette garde est un DÉTECTEUR PRÉCOCE, pas la
    garantie. La garantie vient de deux mécanismes que rien n'esquive :

    1. les imports RELATIFS du paquet rendent le chargement à plat
       structurellement IMPOSSIBLE — mesuré : insérer le paquet dans sys.path
       puis « import registre » lève
       « ImportError: attempted relative import with no known parent package » ;
    2. la garde sys.modules est COMPORTEMENTALE : elle constate tout nom de
       premier niveau effectivement enregistré, quelle que soit la façon dont il
       l'a été.

    Rendre cette garde exhaustive contre un contournement délibéré demanderait un
    suivi de flot de données, pour une propriété déjà garantie ailleurs.
    """
    tests_dir = Path(__file__).resolve().parent
    fautifs = []
    for fichier in sorted(tests_dir.glob("*.py")):
        source = fichier.read_text(encoding="utf-8")
        arbre = ast.parse(source)
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            cible = noeud.func
            # sys.path.insert(...) ou path.insert(...) après un alias
            if not (isinstance(cible, ast.Attribute) and cible.attr in ("insert", "append")):
                continue
            recepteur = cible.value
            if not (isinstance(recepteur, ast.Attribute) and recepteur.attr == "path"):
                continue
            # le nom du paquet apparaît-il dans les arguments, où qu'il soit ?
            for argument in noeud.args:
                for litteral in ast.walk(argument):
                    if (isinstance(litteral, ast.Constant)
                            and isinstance(litteral.value, str)
                            and _NOM_PAQUET in litteral.value):
                        fautifs.append(
                            f"{fichier.name}:{noeud.lineno}: sys.path.{cible.attr} "
                            f"avec {litteral.value!r}"
                        )
    assert not fautifs, (
        "sys.path visant le paquet au lieu de son parent :\n  "
        + "\n  ".join(fautifs)
    )

def test_aucun_module_m1_a_plat_dans_sys_modules():
    """PROUVE qu'aucun module de M1 n'occupe un nom de premier niveau.

    Symétrie explicite avec la garde équivalente de M2. Signalée manquante par la
    revue scellée (chore #109, round 3) : les gardes structurelle (aucun .py à
    plat sous src/) et statique (aucun sys.path.insert visant le paquet) ne
    voient PAS un test qui réenregistrerait un module sous un nom à plat dans
    sys.modules — par exemple en aliasant le module qualifié.

    La propriété était peut-être déjà couverte indirectement, mais un garde-fou
    implicite est fragile : un refactor peut le retirer sans que personne sache
    qu'il portait cette propriété. On la nomme donc.
    """
    import sys

    noms_partages = ("registre", "verdicts", "horodatage", "contrats",
                     "digest", "adaptateurs", "provenance", "qualification")
    src = (_M1 / "src").resolve()
    fautifs = {}
    for nom in noms_partages:
        module = sys.modules.get(nom)
        if module is None:
            continue
        fichier = getattr(module, "__file__", None)
        if fichier and str(src) in str(Path(fichier).resolve()):
            fautifs[nom] = fichier
    assert not fautifs, (
        "des modules de M1 occupent un nom de premier niveau, ce qui rouvre la "
        f"collision inter-modules : {fautifs}"
    )
