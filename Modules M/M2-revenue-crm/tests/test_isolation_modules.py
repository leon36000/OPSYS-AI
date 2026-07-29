import sys
from pathlib import Path
import inspect
import pytest

# ---------------------------------------------------------------------------
# Configuration du chemin d'import (identique au patron M2 existant)
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m2_revenue_crm import encodage  # noqa: E402
from m2_revenue_crm import horodatage  # noqa: E402
from m2_revenue_crm import verdicts  # noqa: E402
from m2_revenue_crm import fixtures_garde  # noqa: E402
from m2_revenue_crm import registre  # noqa: E402

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
