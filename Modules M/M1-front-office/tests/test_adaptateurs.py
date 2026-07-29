"""Normalisation déterministe des adaptateurs M1 (chore #111).

Le repli ``repr(obj)`` de ``_normaliser_objet_deterministe`` mettait l'adresse
mémoire de l'objet dans la valeur normalisée, donc dans l'identifiant dérivé :
trois processus donnaient trois identifiants différents pour la même entrée. Ces
tests fixent le contrat de remplacement — types tagués explicites, refus par
TypeError pour tout le reste — et prouvent le déterminisme inter-processus.
"""

import subprocess
import sys
from pathlib import Path
from decimal import Decimal
from datetime import date, datetime, time
from uuid import UUID

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import adaptateurs  # noqa: E402


class TestNormalisationDeterministe:
    """Vérifie que la normalisation est injective, déterministe et refuse les types non stables."""

    def test_types_tagues_normalises(self):
        """Chaque type supporté produit la forme balisée attendue."""
        from adaptateurs import _normaliser_objet_deterministe
        from decimal import Decimal
        from datetime import date, datetime, time
        from uuid import UUID
        import pytest

        cas = [
            (Decimal("10.5"), {"__decimal__": "10.5"}, "Decimal"),
            (datetime(2023, 8, 15, 14, 30, 45), {"__datetime__": "2023-08-15T14:30:45"}, "datetime"),
            (date(2023, 8, 15), {"__date__": "2023-08-15"}, "date"),
            (time(14, 30, 45), {"__time__": "14:30:45"}, "time"),
            (UUID("12345678-1234-5678-1234-567812345678"), {"__uuid__": "12345678-1234-5678-1234-567812345678"}, "UUID"),
            (b"hello", {"__bytes__": "68656c6c6f"}, "bytes"),
            (bytearray(b"world"), {"__bytearray__": "776f726c64"}, "bytearray"),
            (complex(1, 2), {"__complex__": ["1.0", "2.0"]}, "complex"),
        ]
        for valeur, attendu, _ in cas:
            assert _normaliser_objet_deterministe(valeur) == attendu, \
                f"Échec pour {type(valeur).__name__}"

    def test_datetime_avant_date(self):
        """Un datetime NE doit PAS être traité comme une date (clé __datetime__ et heure conservée)."""
        from adaptateurs import _normaliser_objet_deterministe
        from datetime import datetime
        obj = datetime(2023, 8, 15, 14, 30, 45)
        res = _normaliser_objet_deterministe(obj)
        assert "__datetime__" in res, "La clé __datetime__ est absente"
        assert "14:30:45" in res["__datetime__"], "L'heure a été perdue"

    def test_type_non_supporte_leve_typeerror(self):
        """Sans ce refus, repr() mettrait l'adresse mémoire dans l'identifiant."""
        from adaptateurs import _normaliser_objet_deterministe
        import pytest
        import math
        types_refuses = [
            object(),
            len,
            math,
            (x for x in range(1)),  # générateur
        ]
        for val in types_refuses:
            with pytest.raises(TypeError, match="Type non supporté"):
                _normaliser_objet_deterministe(val)

    def test_determinisme_inter_processus(self, tmp_path):
        """Trois processus avec des PYTHONHASHSEED différents produisent la même normalisation."""
        import subprocess
        import json
        import sys
        from pathlib import Path

        # Construire le chemin absolu du répertoire src contenant adaptateurs.py
        src_dir = Path(__file__).resolve().parents[1] / "src"
        script = (
            "import sys, json\n"
            f"sys.path.insert(0, {repr(str(src_dir))})\n"
            "from adaptateurs import _normaliser_objet_deterministe\n"
            "from decimal import Decimal\n"
            "from datetime import datetime\n"
            "val = {\n"
            "    'dict': {'a': 1, 'b': 2},\n"
            "    'set': {3, 4},\n"
            "    'list': [Decimal('1.1'), datetime(2023,1,1,12,0,0)],\n"
            "    'bytes': b'hello'\n"
            "}\n"
            "print(json.dumps(_normaliser_objet_deterministe(val)))\n"
        )

        graines = ["0", "7", "99"]
        resultats = []
        for graine in graines:
            env = {
                "PYTHONHASHSEED": graine,
                "PYTHONPATH": str(src_dir),
                "PATH": "/usr/bin:/bin"
            }
            proc = subprocess.run([sys.executable, "-c", script],
                                  capture_output=True, text=True, env=env)
            assert proc.returncode == 0, f"Échec subprocess (graine={graine}): {proc.stderr}"
            sortie = proc.stdout.strip()
            assert sortie, f"Sortie vide pour la graine {graine}"
            resultats.append(sortie)

        assert len(set(resultats)) == 1, "Les normalisations diffèrent selon le hash seed"

    def test_identifiant_stable_pour_objet_taguable(self):
        """Deux appels à proposer sur une valeur composite équivalente donnent le même identifiant."""
        from adaptateurs import _ApprovalEngine
        from decimal import Decimal
        from datetime import datetime
        eng = _ApprovalEngine(mode_ombre=True)
        valeur = {
            "meta": {"set": {1, 2}, "list": [Decimal("1.1"), datetime(2023,1,1,12,0,0)]},
            "payload": b"abc"
        }
        id1 = eng.proposer(valeur, acteur="test")
        id2 = eng.proposer(valeur, acteur="test")
        assert id1 == id2, "L'identifiant n'est pas stable"
