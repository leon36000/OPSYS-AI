"""Revue adverse « web » (M5) : classeur .xlsx hostile dans l'import QuickBooks.

Un classeur de quelques centaines d'octets déclare une cellule à la colonne « AAAAAAAA » : sans borne, la lecture
construit une rangée de plusieurs milliards de cellules (épuisement mémoire du processus). L'exploit tourne dans un
sous-processus dont la mémoire est plafonnée, pour qu'un échec ne touche jamais la machine de test.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import zipfile

import pytest
from m5_financecore import import_quickbooks as qbo

FICTIF = True
_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'

_ENFANT = r"""
import json, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 ** 2, 1536 * 1024 ** 2))
from m5_financecore import import_quickbooks as qbo
octets = bytes.fromhex(sys.argv[1])
try:
    resultat, refus = qbo.analyser_liste_comptes(octets)
    print(json.dumps({"code": (refus or {}).get("code"), "ok": resultat is not None}))
except BaseException as exc:
    print(json.dumps({"exception": type(exc).__name__}))
"""


def _classeur(reference: str) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook {_NS} xmlns:r="http://schemas.openxmlformats.org/'
                         'officeDocument/2006/relationships"><sheets><sheet name="R" sheetId="1" r:id="rId1"/>'
                         '</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/'
                         'package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" '
                         'Type="worksheet"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet {_NS}><sheetData><row r="1"><c r="{reference}" '
                         't="inlineStr"><is><t>Account</t></is></c></row></sheetData></worksheet>')
    return tampon.getvalue()


def _lire_sous_plafond(reference: str) -> dict:
    sortie = subprocess.run([sys.executable, "-c", _ENFANT, _classeur(reference).hex()], capture_output=True,
                            text=True, timeout=120, env=os.environ.copy(), check=False)
    assert sortie.returncode == 0, sortie.stderr[-500:]
    return json.loads(sortie.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("reference", ["AAAAAAAA1", "ZZZZ1", "AAAAA1", "XFE1"])
def test_une_colonne_au_dela_de_la_limite_d_un_classeur_est_refusee_sans_epuiser_la_memoire(reference):
    resultat = _lire_sous_plafond(reference)
    assert "exception" not in resultat, resultat
    assert resultat["ok"] is False
    assert resultat["code"] == "REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE"


def test_la_derniere_colonne_d_un_classeur_reste_lue():
    """Cas négatif : XFD est la dernière colonne d'un classeur ; elle est lue (puis refusée pour ses en-têtes)."""
    resultat = _lire_sous_plafond("XFD1")
    assert "exception" not in resultat
    assert resultat["code"] == "REJ-QBO-ENTETES-INCONNUES"


def test_colonne_excel_borne_l_indice():
    assert qbo._colonne_excel("A1") == 0
    assert qbo._colonne_excel("XFD1") == 16383
    with pytest.raises(ValueError):
        qbo._colonne_excel("XFE1")
    with pytest.raises(ValueError):
        qbo._colonne_excel("AAAAAAAAAAAAAAAAAAAAAAAA1")
