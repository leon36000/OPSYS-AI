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

import encodage          # noqa: E402
import horodatage        # noqa: E402
import verdicts          # noqa: E402
import fixtures_garde    # noqa: E402
import registre          # noqa: E402

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
def test_modules_charges_depuis_src_m2(nom_module: str, module):
    """Chaque module doit provenir du répertoire src/ de M2."""
    module_src = Path(module.__file__).resolve().parent
    attendu = _SRC.resolve()
    assert module_src == attendu, (
        f"Module {nom_module} chargé depuis {module_src} au lieu de {attendu}. "
        "La suite doit tourner dans un processus isolé par module "
        "(c'est ce que fait la CI) tant que les modules ne sont pas "
        "rendus uniques par paquet."
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
