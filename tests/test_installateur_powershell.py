"""Scripts PowerShell de l'installateur (PLAN T0.11) : garde-fous que le bac à sable peut tenir sans PowerShell.

Ce bac à sable n'a pas `pwsh` et n'exécute jamais `install.ps1` : la seule preuve de syntaxe est l'analyseur de
PowerShell, joué par le job `installateur` de la CI (`.github/workflows/installateur.yml`). Ces tests attrapent avant
la CI ce qui s'attrape sans lui : un caractère hors ASCII (Windows PowerShell 5.1 lit un script UTF-8 sans BOM comme
du texte ANSI, et un BOM casserait `iex`), des accolades ou des guillemets déséquilibrés, et un écart entre le
comportement de `install.ps1` et celui de `install.sh` qu'il doit refléter.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
INSTALL_PS1 = RACINE / "install" / "install.ps1"
UNINSTALL_PS1 = RACINE / "install" / "uninstall.ps1"
INSTALL_SH = RACINE / "install" / "install.sh"
SCRIPTS = [INSTALL_PS1, UNINSTALL_PS1]


def _desequilibre(texte: str) -> str | None:
    """Parcourt le script comme le ferait un lecteur (commentaires, chaînes, chaînes ici) et vérifie {} () [].

    Rend une description du premier défaut, ou `None`. Approximation volontaire : elle ne connaît pas toute la grammaire
    de PowerShell, mais elle connaît tout ce que ces scripts emploient.
    """
    paires = {"}": "{", ")": "(", "]": "["}
    pile: list[tuple[str, int]] = []
    i, ligne, n = 0, 1, len(texte)
    while i < n:
        c = texte[i]
        if c == "\n":
            ligne += 1
        elif c == "#":
            while i < n and texte[i] != "\n":
                i += 1
            continue
        elif texte.startswith("@'", i) and texte[i + 2:i + 3] in ("\n", "\r"):
            fin = texte.find("\n'@", i)
            if fin < 0:
                return f"chaîne ici non fermée (ligne {ligne})"
            ligne += texte.count("\n", i, fin + 1)
            i = fin + 3
            continue
        elif c == "'":
            i += 1
            while i < n:
                if texte[i] == "'":
                    if texte[i + 1:i + 2] == "'":
                        i += 2
                        continue
                    break
                ligne += texte[i] == "\n"
                i += 1
            else:
                return f"apostrophe non fermée (ligne {ligne})"
        elif c == '"':
            i += 1
            while i < n:
                if texte[i] == "`":
                    i += 2
                    continue
                if texte[i] == '"':
                    if texte[i + 1:i + 2] == '"':
                        i += 2
                        continue
                    break
                ligne += texte[i] == "\n"
                i += 1
            else:
                return f"guillemet non fermé (ligne {ligne})"
        elif c in "{([":
            pile.append((c, ligne))
        elif c in paires:
            if not pile or pile[-1][0] != paires[c]:
                return f"'{c}' inattendu (ligne {ligne})"
            pile.pop()
        i += 1
    if pile:
        return f"'{pile[-1][0]}' non fermé (ouvert ligne {pile[-1][1]})"
    return None


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_le_script_est_en_ascii_pur_sans_bom(script):
    octets = script.read_bytes()

    assert not octets.startswith(b"\xef\xbb\xbf"), "un BOM casserait l'exécution par `iex`"
    non_ascii = [(numero, ligne) for numero, ligne in enumerate(octets.decode("latin-1").splitlines(), 1)
                 if any(ord(c) > 127 for c in ligne)]
    assert not non_ascii, f"caractères hors ASCII : {non_ascii[:3]}"
    assert b"\r" not in octets, "fins de ligne LF (le dépôt les normalise)"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_accolades_parentheses_et_guillemets_sont_equilibres(script):
    assert _desequilibre(script.read_text(encoding="utf-8")) is None


def test_le_verificateur_attrape_les_fautes_qu_il_pretend_attraper():
    assert _desequilibre("function F { if ($x) { 'a' } ") is not None
    assert _desequilibre('Write-Host "abc') is not None
    assert _desequilibre("$a = (1 + 2))") is not None
    assert _desequilibre("$a = @'\nligne\n") is not None
    assert _desequilibre("function F { 'l''apostrophe' ; \"a `\" b\" ; # ) commentaire\n }") is None


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_le_script_lance_ses_commandes_natives_sans_faire_planter_powershell_5(script):
    texte = script.read_text(encoding="utf-8")

    assert "$ErrorActionPreference = 'Stop'" in texte
    # jamais `2>&1` nu sous 'Stop' (Windows PowerShell 5.1)
    assert "Invoke-Capture" in texte or "Get-CodeSortie" in texte
    assert "[CmdletBinding(PositionalBinding = $false)]" in texte
    assert "exit $codeSortie" in texte and "$PSCommandPath" in texte  # `exit` seulement quand lancé comme fichier


def test_install_ps1_reflete_install_sh():
    sh = INSTALL_SH.read_text(encoding="utf-8")
    ps = INSTALL_PS1.read_text(encoding="utf-8")

    variables = set(re.findall(r"\bOPSYS_[A-Z_]+\b", sh.split("set -euo pipefail")[0]))
    variables -= {"OPSYS_HOME", "OPSYS_LOGICIEL", "OPSYS_BIN"} | {"OPSYS_INSTALLATEUR"}
    manquantes = sorted(v for v in variables if v not in ps)
    assert not manquantes, f"install.ps1 ne connaît pas : {manquantes}"
    for commun in ("instance initialiser", "config validate", "gateway install", "'--force'", "--frozen-lockfile",
                   "'build'", "isSupportedOpenClawNodeVersion", "/startupz", "/sante", "installation.env",
                   "SOURCE_GEREE", "--clear", "'>=3.11'", "--editable", "packageManager", "-SansService", "24.16",
                   "26.1", "Test-ServiceEtranger"):
        assert commun in ps, commun
    assert "CodeEnAttente = 3" in ps and "CODE_EN_ATTENTE=3" in sh


def test_uninstall_ps1_reflete_uninstall_sh():
    sh = (RACINE / "install" / "uninstall.sh").read_text(encoding="utf-8")
    ps = UNINSTALL_PS1.read_text(encoding="utf-8")

    for commun in ("instance exporter", "gateway uninstall", "installation.env", "SOURCE_GEREE",
                   "poste:desinstallation", "-ExporterAvant", "-Simuler", "RIEN n'a ete retire",
                   "Rien d'autre n'a ete retire"):
        assert commun in ps, commun
    assert "--exporter-avant" in sh and "--simuler" in sh
    assert "Remove-Item -LiteralPath $script:OpsysHome" not in ps  # aucun chemin de suppression des données
    assert not re.search(r"Remove-Item[^\n]*OpsysHome", ps)
