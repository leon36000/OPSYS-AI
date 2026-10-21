from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(FIXTURES))


def _verifier_acces_prive(chemin: Path, *, mode: int | None = None) -> None:
    """Vérifie le mode POSIX, ou la DACL Windows effective du compte courant."""
    chemin = Path(chemin)
    if os.name != "nt":
        attendu = mode if mode is not None else (0o700 if chemin.is_dir() else 0o600)
        assert stat.S_IMODE(chemin.stat().st_mode) == attendu
        return

    powershell = shutil.which("pwsh") or shutil.which("powershell")
    assert powershell is not None, "PowerShell est requis pour inspecter la DACL Windows"
    script = r"""
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:OPSYS_ACL_TEST_PATH
$full = [long][System.Security.AccessControl.FileSystemRights]::FullControl
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) |
    ForEach-Object {
        [PSCustomObject]@{
            Sid = $_.IdentityReference.Value
            Type = $_.AccessControlType.ToString()
            Inherited = [bool]$_.IsInherited
            InheritanceFlags = [int]$_.InheritanceFlags
            FullControl = (([long]$_.FileSystemRights -band $full) -eq $full)
        }
    })
[PSCustomObject]@{
    Protected = [bool]$acl.AreAccessRulesProtected
    CurrentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    Rules = $rules
} | ConvertTo-Json -Depth 5 -Compress
"""
    environnement = os.environ.copy()
    environnement["OPSYS_ACL_TEST_PATH"] = str(chemin)
    resultat = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        env=environnement,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert resultat.returncode == 0, f"Get-Acl a échoué: {resultat.stderr}"
    acl = json.loads(resultat.stdout)
    assert acl["Protected"] is True, f"DACL encore héritée: {acl}"
    regles = acl["Rules"]
    if isinstance(regles, dict):  # ConvertTo-Json compresse parfois un tableau d'un élément.
        regles = [regles]
    assert isinstance(regles, list) and regles
    assert all(not regle["Inherited"] for regle in regles), f"ACE héritée: {regles}"
    assert all(regle["Type"] == "Allow" for regle in regles), f"ACE Deny explicite: {regles}"
    autorisations = regles
    assert all(regle["Sid"] == acl["CurrentSid"] for regle in autorisations), (
        f"un autre SID reçoit un accès: {autorisations}"
    )
    assert any(regle["FullControl"] for regle in autorisations), (
        f"le SID courant n'a pas FullControl: {autorisations}"
    )
    if chemin.is_dir():
        assert all(regle["InheritanceFlags"] == 3 for regle in autorisations), (
            f"l'ACE du dossier ne transmet pas OI et CI: {autorisations}"
        )


@pytest.fixture
def verifier_acces_prive():
    """Assertion partagée des tests qui attendent un fichier/dossier privé."""
    return _verifier_acces_prive


@pytest.fixture
def opsys_home(tmp_path, monkeypatch):
    home = tmp_path / "opsys-home"
    monkeypatch.setenv("OPSYS_HOME", str(home))
    return home


@pytest.fixture
def racine_demo() -> Path:
    return FIXTURES / "departements"


@pytest.fixture
def departements_demo(racine_demo):
    from opsys.departements import charger_departements

    return charger_departements(racine_demo)


@pytest.fixture
def session(opsys_home):
    """Base de l'instance migrée (ADR-0009) ; `etat.session` (alias de `stockage.transaction`)."""
    from opsys import etat, stockage

    stockage.migrer()
    yield etat.session
    stockage.liberer()


MOT_DE_PASSE_NATHAN = "mot-de-passe-de-test-nathan-1234"


@pytest.fixture
def nathan(session) -> str:
    """Personne 'nathan', rôle `nathan_owner` (ADR-0009 §5) : signe les décisions dans les tests du
    socle qui ne portent pas eux-mêmes sur l'identité. Rend son identifiant ('nathan')."""
    from opsys import identite

    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan St-Louis", MOT_DE_PASSE_NATHAN, ["nathan_owner"])
    return "nathan"
