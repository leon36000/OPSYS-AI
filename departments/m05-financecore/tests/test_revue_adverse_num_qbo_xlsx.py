"""Revue adverse (num) : une cellule numérique de classeur .xlsx à exposant démesuré ne doit ni geler l'import ni
lever une exception (`import_quickbooks._nombre_excel`). Données fictives."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile

import pytest
from m5_financecore import import_quickbooks as qbo

FICTIF = True


def _classeur(valeur_cellule: str) -> bytes:
    """Un classeur .xlsx minimal dont la seule cellule est un nombre écrit tel quel (`<v>…</v>`)."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Rapport" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="worksheet"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet {ns}><sheetData><row r="1"><c r="A1"><v>{valeur_cellule}</v></c></row>'
            "</sheetData></worksheet>",
        )
    return tampon.getvalue()


def _lecture_en_sous_processus(octets: bytes, delai_s: int) -> subprocess.CompletedProcess:
    """Lit `octets` dans un processus distinct, tué après `delai_s` : le défaut observé est un calcul entier de
    plusieurs minutes (non interruptible par un signal) sur 14 octets de XML."""
    code = (
        "import sys; from m5_financecore import import_quickbooks as q; "
        "r, v = q.analyser_balance(sys.stdin.buffer.read()); "
        "print(v['code'] if v else 'OK')"
    )
    return subprocess.run(
        [sys.executable, "-c", code], input=octets, capture_output=True, timeout=delai_s,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}, check=False,
    )


@pytest.mark.parametrize("exposant", ["1E+99999999", "1E+4000000"])
def test_exposant_demesure_ne_gele_pas_l_import(exposant):
    try:
        termine = _lecture_en_sous_processus(_classeur(exposant), 20)
    except subprocess.TimeoutExpired:
        pytest.fail(f"la lecture d'une cellule {exposant} dure plus de 20 s (déni de service par 14 octets de XML)")
    assert termine.returncode == 0, termine.stderr.decode()[-300:]
    assert termine.stdout.decode().strip() in qbo.CODES_QBO


@pytest.mark.parametrize("valeur", ["12345678901234567890123456789.5", "1E+30", "1.5E+27", "99999999999999999999.99"])
def test_nombre_trop_grand_pour_un_montant_est_refuse_sans_exception(valeur):
    # `quantize` d'un nombre de plus de 28 chiffres levait `InvalidOperation` (hors des exceptions attrapées) :
    # la lecture rend un verdict typé, jamais une exception.
    resultat, refus = qbo.analyser_balance(_classeur(valeur))
    assert resultat is None and refus["code"] in qbo.CODES_QBO


def test_cas_legitimes_restent_lus_au_cent():
    assert qbo._nombre_excel("15486.999999999998") == "15487.00"
    assert qbo._nombre_excel("46037") == "46037"
    assert qbo._nombre_excel("-1250.5") == "-1250.50"
    assert qbo._nombre_excel("6000.004") == "6000.004"  # trois décimales réelles : refusées plus loin, pas arrondies
    assert qbo._nombre_excel("1E-12") == "0.00"
    assert qbo._nombre_excel("999999999999.99") == "999999999999.99"
    assert qbo._nombre_excel("123456789012345678") == "123456789012345678"
