"""Le jour fourni par le core est anglais, quelle que soit la locale du processus."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_horodatage_plateforme_anglais_sous_locale_francaise():
    racine = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    chemin = os.pathsep.join(
        [str(racine / "departments/m01-front-office/src"), str(racine / "src")]
    )
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [chemin, env.get("PYTHONPATH", "")]))
    code = """
import locale
import sys
from m1_front_office.reception import heure_de_reception
for candidat in ('fr_CA.utf8', 'fr_CA.UTF-8', 'fr_FR.utf8', 'fr_FR.UTF-8'):
    try:
        locale.setlocale(locale.LC_TIME, candidat)
        break
    except locale.Error:
        pass
else:
    sys.exit(77)
print(heure_de_reception('Tue 2026-09-29 09:15:30 EDT'))
"""

    resultat = subprocess.run(
        [sys.executable, "-c", code], cwd=racine, env=env, capture_output=True, text=True, check=False
    )

    if resultat.returncode == 77:
        pytest.skip("aucune locale française LC_TIME installée")
    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stdout.strip() == "2026-09-29T09:15:30-04:00"


def test_horodatage_plateforme_refuse_un_mauvais_jour_sans_dependre_de_locale():
    from m1_front_office.reception import heure_de_reception

    with pytest.raises(ValueError, match="Mon ne correspond pas au 2026-09-29"):
        heure_de_reception("Mon 2026-09-29 09:15:30 EDT")
