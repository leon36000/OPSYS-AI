"""Scripts PowerShell de l'installateur (PLAN T0.11) : garde-fous que le bac à sable peut tenir sans PowerShell.

Ce fichier ne lit que le TEXTE des scripts, pour ce qui s'attrape sans PowerShell : un caractère hors ASCII (Windows
PowerShell 5.1 lit un script UTF-8 sans BOM comme du texte ANSI, et un BOM casserait `iex`), des accolades ou des
guillemets déséquilibrés, et un écart entre le comportement de `install.ps1` et celui de `install.sh` qu'il doit
refléter. Quand `pwsh` existe (`ubuntu-24.04` l'a), le vrai PowerShell fait le reste : l'analyseur syntaxique et le
contrôle des variables (`test_installateur_windows.py`), l'exécution des deux scripts contre de fausses commandes
(`test_installateur_powershell_faux.py`). Sous Windows, le job `installation-windows` de la CI les exécute pour de vrai
(`.github/workflows/installateur.yml`, `tests/installateur/bout_en_bout.ps1`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from opsys import instance

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
                   "SOURCE_GEREE", "--clear", "'>=3.11'", "uv sync --locked", "packageManager", "-SansService", "24.16",
                   "26.1", "instance dossier", "config', 'file'", "Test-DossierDuCore", "Initialize-DossierCore",
                   "--profile $script:ProfilCore", "DOSSIER_CORE", "PROFIL_CORE", "instance fichier-config"):
        assert commun in ps, commun
    for commun in ("instance dossier", "verifier_dossier_du_core", "determiner_dossier_core", "DOSSIER_CORE",
                   "PROFIL_CORE", '--profile "$PROFIL_CORE"', "instance fichier-config"):
        assert commun in sh, commun
    # T0.7 lot 3 : le fichier de configuration attendu est celui que dit le moteur, jamais un nom écrit en dur
    for script, texte in (("install.sh", sh), ("install.ps1", ps)):
        code = re.sub(r"(?m)^\s*#.*$", "", texte)
        assert "openclaw.json" not in code and "opsys.json" not in code, script
    assert "CodeEnAttente = 3" in ps and "CODE_EN_ATTENTE=3" in sh


def test_les_installateurs_verifient_docker_linux_et_preparent_l_image_sandbox_avant_gateway():
    sh = re.sub(r"(?m)^\s*#.*$", "", INSTALL_SH.read_text(encoding="utf-8"))
    ps = re.sub(r"(?m)^\s*#.*$", "", INSTALL_PS1.read_text(encoding="utf-8"))
    image = "openclaw-sandbox:bookworm-slim"

    assert "command -v docker" in sh and "docker info --format '{{.OSType}}'" in sh
    assert "Test-DockerPrerequis" in ps and "docker info --format '{{.OSType}}'" in ps
    assert image in sh and image in ps
    assert "core/scripts/sandbox-setup.sh" in sh
    assert "scripts\\docker\\sandbox\\Dockerfile" in ps
    assert "docker build -t $image -f $dockerfile $core" in ps
    assert sh.index("construire_core\n    preparer_image_sandbox") < sh.index("installer_moteur\n")
    assert ps.rindex("Build-Core\n        Prepare-SandboxImage") < ps.rindex("Install-Moteur")
    assert "docker pull" not in sh and "docker pull" not in ps


def test_les_deux_installateurs_synchronisent_les_memes_extras_verrouilles():
    for script in (INSTALL_SH, INSTALL_PS1):
        texte = script.read_text(encoding="utf-8")
        lignes = re.sub(r"\\\n[ \t]*", " ", texte)
        commandes = re.findall(r"\buv sync --locked[^\n]*", lignes)
        assert len(commandes) == 2, script.name
        for commande in commandes:
            assert "--group build" in commande and "--no-dev" in commande, script.name
            assert re.findall(r"--extra (\w+)", commande) == ["tournees", "soumission"], script.name
            assert "--no-build-isolation" in commande, script.name
        assert "--no-install-project" in commandes[0]
        assert "--no-install-project" not in commandes[1]


def test_l_installateur_ne_garde_plus_le_service_d_une_autre_installation_et_ne_pose_aucun_etat_a_la_main():
    """Sous le profil « opsys », le service a son propre nom : la garde d'avant T0.11-b n'a plus d'objet."""
    for script in (INSTALL_PS1, UNINSTALL_PS1, INSTALL_SH, RACINE / "install" / "uninstall.sh"):
        code = re.sub(r"(?m)^\s*#.*$", "", script.read_text(encoding="utf-8"))
        assert "Test-ServiceEtranger" not in code and "verifier_service_etranger" not in code, script.name
        assert "OPENCLAW_STATE_DIR = " not in code and "OPENCLAW_STATE_DIR=" not in code, script.name
        assert "schtasks.exe /Query" not in code, script.name


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_le_profil_et_les_variables_ecartees_de_powershell_sont_ceux_du_moteur(script):
    texte = script.read_text(encoding="utf-8")

    assert f"$script:ProfilCore = '{instance.PROFIL_CORE}'" in texte
    liste = re.search(r"\$script:VariablesEcartees = @\((.*?)\)", texte)
    assert liste and re.findall(r"'([A-Z_]+)'", liste.group(1)) == list(instance.VARIABLES_ECARTEES)
    # le retrait de l'environnement se fait avant de lancer le core, et le core reçoit l'option racine du profil
    assert "Remove-Item -LiteralPath \"Env:$nom\"" in texte
    assert "--profile $script:ProfilCore" in texte


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
    assert not re.search(r"Remove-Item[^\n]*DossierCore", ps)  # ni de l'état du core (secrets, état du Gateway)
    assert "--profile $script:ProfilCore gateway uninstall" in ps and '--profile "$PROFIL_CORE" gateway uninstall' in sh
    assert "Etat du core conserve" in ps and "État du core conservé" in sh
