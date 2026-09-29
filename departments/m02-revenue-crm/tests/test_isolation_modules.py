import ast
import inspect
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import encodage, fixtures_garde, horodatage, registre, verdicts

# ---------------------------------------------------------------------------
# Racine des sources du paquet (lue par les contrôles de structure ; l'import du paquet
# passe par le `pythonpath` de pyproject.toml, aucun sys.path.insert n'est requis)
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parent.parent / "src"

_NOM_PAQUET = "m2_revenue_crm"

# ---------------------------------------------------------------------------
# Références en dur pour les tests paramétrés
# ---------------------------------------------------------------------------
_MODULES_M2 = {
    "encodage": encodage,
    "horodatage": horodatage,
    "verdicts": verdicts,
    "fixtures_garde": fixtures_garde,
    "registre": registre,
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nom_module,module", _MODULES_M2.items())
def test_modules_charges_depuis_le_paquet_m2(nom_module: str, module):
    """Chaque module doit provenir du PAQUET de M2, pas d'un arbre voisin.

    Le garde-fou est conservé après la mise en paquet (chore #109) : il ne prouve
    plus la même chose de la même façon, mais il prouve toujours
    l'APPARTENANCE. Avant, l'isolation reposait sur un processus pytest distinct
    par module — une garantie de configuration, pas de construction. Désormais le
    nom de paquet est unique au dépôt, donc la collision est impossible ; ce test
    reste la sentinelle qui le vérifie, et il échouerait si quelqu'un
    réintroduisait des modules à plat.
    """
    module_src = Path(module.__file__).resolve().parent
    attendu = (_SRC / "m2_revenue_crm").resolve()
    assert module_src == attendu, (
        f"Module {nom_module} chargé depuis {module_src} au lieu de {attendu} : "
        "un module à plat a été réintroduit, ou un arbre voisin a été chargé."
    )
    assert module.__name__.startswith("m2_revenue_crm."), (
        f"Module {nom_module} porte le nom {module.__name__!r} : il doit être "
        "qualifié par le paquet, sinon deux arbres peuvent encore se recouvrir "
        "dans sys.modules."
    )


def test_registre_expose_assert_chaine_avec_ancre():
    """Le module registre chargé doit être celui de M2 (assert_chaine avec ancre)."""
    reg = registre.Registre
    assert hasattr(reg, "assert_chaine"), (
        "La classe Registre ne possède pas la méthode assert_chaine. "
        "Module voisin probablement chargé."
    )
    sig = inspect.signature(reg.assert_chaine)
    assert "ancre" in sig.parameters, (
        "La méthode assert_chaine de Registre n'accepte pas le paramètre 'ancre'. "
        "Le module chargé semble provenir du module voisin."
    )


def test_verdicts_contient_code_m2():
    """Le module verdicts chargé doit contenir le catalogue de M2."""
    assert verdicts.est_verdict("REJ-FRONTIERE-VIOLEE") is True, (
        "Le module verdicts chargé ne reconnaît pas le code M2 "
        "'REJ-FRONTIERE-VIOLEE'. Il provient probablement du module voisin."
    )
    assert verdicts.est_verdict("CODE-INVENTE") is False, (
        "Le module verdicts chargé accepte un code inventé. "
        "Comportement inattendu : le module voisin pourrait s'être chargé."
    )


def test_aucun_module_m2_a_plat_dans_sys_modules():
    """PROUVE qu'aucun module de M2 n'occupe un nom de premier niveau.

    C'est la propriété que la mise en paquet apporte : tant que les modules
    s'appelaient « registre », « verdicts », « horodatage », le premier arbre
    chargé gagnait la place dans sys.modules et l'appartenance dépendait de
    l'ordre de collecte. Mesuré avant correctif : trois collisions et 21 tests
    de M2 exerçant le code du module voisin sans aucun signal.
    """
    noms_partages = ("registre", "verdicts", "horodatage", "encodage",
                     "contrats", "digest", "adaptateurs", "ingestion")
    fautifs = {}
    for nom in noms_partages:
        module = sys.modules.get(nom)
        if module is None:
            continue
        fichier = getattr(module, "__file__", None)
        if fichier and str(_SRC) in str(Path(fichier).resolve()):
            fautifs[nom] = fichier
    assert not fautifs, (
        "des modules de M2 occupent un nom de premier niveau, ce qui rouvre la "
        f"collision inter-modules : {fautifs}"
    )

def test_aucun_module_a_plat_sous_src():
    """PROUVE structurellement qu'aucun fichier .py ne subsiste À PLAT sous src/.

    L'identité de paquet ne protège que ce qui est DANS le paquet. Un nouveau
    module déposé directement sous src/ et importé à plat depuis un test
    rouvrirait exactement la collision que le chore #109 a fermée : sys.modules
    conserverait le premier arbre chargé et l'appartenance redeviendrait
    fonction de l'ordre de collecte.

    Ce contrôle est STRUCTUREL et non comportemental, à dessein : un fichier à
    plat que personne n'importe encore est inerte, donc invisible pour un test
    qui n'observe que les modules chargés — vérifié par mutation (copier
    verdicts.py à plat ne faisait rougir aucun test avant l'ajout de celui-ci).
    """
    a_plat = sorted(p.name for p in _SRC.glob("*.py"))
    assert a_plat == [], (
        f"modules à plat sous src/ : {a_plat}. Ils doivent vivre dans le paquet "
        f"{_SRC.name}/PAQUET/ pour que leur nom soit unique au dépôt."
    )
    paquets = [d.name for d in _SRC.iterdir()
               if d.is_dir() and (d / "__init__.py").exists()]
    assert len(paquets) == 1, (
        f"src/ doit contenir EXACTEMENT un paquet, trouvé : {paquets}"
    )

@pytest.mark.parametrize(
    "nom_script",
    ["preuve_cas_limites.py", "preuve_manuelle.py"],
    ids=["cas_limites", "manuelle"],
)
def test_scripts_de_preuve_sexecutent(nom_script):
    """PROUVE que les scripts de preuve du dossier tests/ s'exécutent encore.

    Ces fichiers ne commencent pas par ``test_``, donc pytest ne les collecte
    pas : ils peuvent pourrir en silence. C'est exactement ce qui s'est produit
    lors de la mise en paquet (chore #109) — les deux étaient CASSÉS
    (ModuleNotFoundError) alors que les 1311 tests étaient verts, et seule la
    revue scellée l'a signalé. Les exécuter ici les ramène dans la surface
    prouvée.

    On vérifie le code de retour, pas la sortie : ces scripts impriment des
    mesures, et figer leur texte les rendrait fragiles pour rien.
    """
    import subprocess

    chemin = Path(__file__).resolve().parent / nom_script
    assert chemin.exists(), f"script de preuve absent : {nom_script}"
    resultat = subprocess.run(
        [sys.executable, str(chemin)],
        capture_output=True, text=True,
    )
    assert resultat.returncode == 0, (
        f"{nom_script} ne s'exécute plus (rc={resultat.returncode}).\n"
        f"stdout: {resultat.stdout[-800:]}\nstderr: {resultat.stderr[-800:]}"
    )
    assert resultat.stdout.strip(), (
        f"{nom_script} n'a rien imprimé : il ne prouve plus rien"
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
