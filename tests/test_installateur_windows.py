"""Les scripts PowerShell de l'installateur et de sa preuve, éprouvés par le VRAI PowerShell (PLAN T0.11-d).

Ni ce bac à sable ni les postes de développement Linux n'ont Windows : `install.ps1`, `uninstall.ps1` et
`tests/installateur/bout_en_bout.ps1` ne s'exécutent en entier qu'en CI, sur `windows-latest`. Mais PowerShell 7
existe sous Linux (préinstallé sur `ubuntu-24.04`) : ces tests l'emploient, quand `pwsh` est présent, pour tout ce qui
ne dépend pas de Windows.

- l'analyseur syntaxique de PowerShell lit chaque script (pas l'approximation de `test_installateur_powershell.py`) ;
- un contrôle de l'arbre syntaxique refuse toute variable lue sans avoir été posée : la faute que `Set-StrictMode`
  ne montre qu'à l'exécution, donc seulement en CI ;
- les FONCTIONS pures des scripts (masque des secrets, annotations GitHub, sondes HTTP, empreintes, recherche d'un
  secret, lancement d'une commande native, échec) sont chargées depuis l'arbre syntaxique et exécutées pour de vrai ;
- le script de preuve est joué jusqu'à sa première commande Windows, pour éprouver son enveloppe (variables, groupes,
  annotation d'échec, résumé, code de sortie).

Ce que ces tests ne prouvent PAS : tout ce qui touche Windows (tâche planifiée, icacls, `.cmd`, `curl.exe`, chemins
avec des lettres de lecteur, Windows PowerShell 5.1). Cela, seule la CI le prouve.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

FICTIF = True  # aucune valeur ci-dessous n'est réelle (AGENTS.md)

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "tests" / "installateur"
INSTALL_PS1 = RACINE / "install" / "install.ps1"
UNINSTALL_PS1 = RACINE / "install" / "uninstall.ps1"
PREUVE_PS1 = DOSSIER / "bout_en_bout.ps1"
DIAGNOSTIC_PS1 = DOSSIER / "diagnostic.ps1"
LINT_PS1 = DOSSIER / "lint_variables.ps1"
SCRIPTS_DE_PREUVE = [PREUVE_PS1, DIAGNOSTIC_PS1, LINT_PS1]
TOUS = [INSTALL_PS1, UNINSTALL_PS1, *SCRIPTS_DE_PREUVE]

PWSH = shutil.which("pwsh")
avec_pwsh = pytest.mark.skipif(
    PWSH is None or os.name == "nt",
    reason="pwsh sous Linux ou macOS : sous Windows, le job de la CI joue les scripts pour de vrai")

SECRET = "0123456789abcdef0123456789abcdef"  # fictif


def pwsh(*arguments: str, env: dict[str, str] | None = None, entree: str | None = None,
         timeout: int = 120) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    environnement = {**os.environ, "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1", "NO_COLOR": "1", **(env or {})}
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", *arguments], env=environnement, input=entree,
                          capture_output=True, text=True, timeout=timeout, check=False)


def _sortie(resultat: subprocess.CompletedProcess[str]) -> str:
    return resultat.stdout + resultat.stderr


# -- ce que PowerShell n'est pas nécessaire pour vérifier -------------------------------------------------------------
@pytest.mark.parametrize("script", SCRIPTS_DE_PREUVE, ids=lambda p: p.name)
def test_les_scripts_de_preuve_sont_en_ascii_pur_sans_bom_en_lf(script):
    octets = script.read_bytes()

    assert not octets.startswith(b"\xef\xbb\xbf"), "un BOM casserait l'exécution par `iex` (règle des scripts)"
    hors_ascii = [(numero, ligne) for numero, ligne in enumerate(octets.decode("latin-1").splitlines(), 1)
                  if any(ord(c) > 127 for c in ligne)]
    assert not hors_ascii, f"caractères hors ASCII : {hors_ascii[:3]}"
    assert b"\r" not in octets, "fins de ligne LF (le dépôt les normalise ; .gitattributes les garde)"


def test_les_scripts_de_preuve_ne_tolerent_aucun_echec_en_silence():
    for script in SCRIPTS_DE_PREUVE[:1]:
        code = re.sub(r"(?m)^\s*#.*$", "", script.read_text(encoding="utf-8"))
        assert "$ErrorActionPreference = 'Stop'" in code
        assert "Set-StrictMode -Version 2.0" in code
        assert "-ErrorAction SilentlyContinue" not in re.sub(
            r"Get-Command[^\n]*|Get-ChildItem[^\n]*|Remove-Item[^\n]*", "", code)  # seules ces sondes le permettent
        assert "exit $codeSortie" in code and "$global:LASTEXITCODE = $codeSortie" in code


# -- l'analyseur de PowerShell ---------------------------------------------------------------------------------------
@avec_pwsh
@pytest.mark.parametrize("script", TOUS, ids=lambda p: p.name)
def test_l_analyseur_de_powershell_accepte_le_script(script):
    programme = ("$e = $null; $t = $null; "
                 "[System.Management.Automation.Language.Parser]::ParseFile("
                 "$env:SCRIPT_ANALYSE, [ref]$t, [ref]$e) | Out-Null; "
                 "$e | ForEach-Object { \"ligne $($_.Extent.StartLineNumber) : $($_.Message)\" }; exit $e.Count")

    resultat = pwsh("-Command", programme, env={"SCRIPT_ANALYSE": str(script)})

    assert resultat.returncode == 0, _sortie(resultat)


@avec_pwsh
@pytest.mark.parametrize("script", TOUS, ids=lambda p: p.name)
def test_aucune_variable_n_est_lue_sans_avoir_ete_posee(script):
    resultat = pwsh("-File", str(LINT_PS1), str(script))

    assert resultat.returncode == 0, f"variables suspectes dans {script.name} :\n{_sortie(resultat)}"


@avec_pwsh
def test_le_controle_des_variables_attrape_les_fautes_qu_il_pretend_attraper(tmp_path):
    fautif = tmp_path / "fautif.ps1"
    fautif.write_text(
        "$script:A = 1\n"
        "function F { param([string]$X) $lignes = @(1); return ($lines -join ',') + $X + $script:B + $script:A }\n"
        "function G { $y = 2; foreach ($i in 1..3) { $y += $i }; return $y + $zzz }\n"
        "function H { return $script:A }\n"
        "function I { $poseeIci = 1 }\n"
        "function J { return $poseeIci }\n"
        "function K { Wirte-Etape 'faute de frappe'; Get-Date | Out-Null; I; & node --version; schtasks.exe /Query }\n",
        encoding="utf-8")

    resultat = pwsh("-File", str(LINT_PS1), str(fautif))

    assert resultat.returncode == 1
    lignes = resultat.stdout.splitlines()
    assert "F ligne 2 : $lines lue, jamais posee" in lignes
    assert "F ligne 2 : $script:B lue, jamais posee" in lignes
    assert "G ligne 3 : $zzz lue, jamais posee" in lignes
    assert "J ligne 6 : $poseeIci lue, jamais posee" in lignes  # posée dans une AUTRE fonction : refusée
    assert not any(ligne.startswith(("H ", "I ")) for ligne in lignes)  # les variables bien posées passent
    # une commande qui n'existe pas est refusée ; une fonction du script, une commande de PowerShell, un programme connu
    # et une commande propre à Windows passent
    faute = ("ligne 7 : la commande 'Wirte-Etape' n'existe pas "
             "(ni fonction du script, ni commande de PowerShell, ni programme connu)")
    assert faute in lignes
    assert sum("la commande" in ligne for ligne in lignes) == 1


@avec_pwsh
def test_le_controle_des_variables_refuse_un_script_qui_ne_s_analyse_pas(tmp_path):
    casse = tmp_path / "casse.ps1"
    casse.write_text("function F { if ($x) { 1 }\n", encoding="utf-8")

    resultat = pwsh("-File", str(LINT_PS1), str(casse))

    assert resultat.returncode == 2 and "SYNTAXE" in resultat.stdout


# -- les fonctions du script de preuve, chargées depuis l'arbre syntaxique et exécutées pour de vrai -------------------
CHARGEUR = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$global:LASTEXITCODE = 0
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:SCRIPT_CHARGE, [ref]$null, [ref]$null)
$definitions = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)
foreach ($definition in $definitions) { . ([scriptblock]::Create($definition.Extent.Text)) }
Add-Type -AssemblyName System.Net.Http
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:Latin1 = [System.Text.Encoding]::GetEncoding('iso-8859-1')
$script:Secrets = @()
$script:GroupeOuvert = $false
$script:GatewayProc = $null
$script:EnActions = $false
$script:EchecPrevu = $false
$script:EtapeCourante = '5. Service'
$script:EtatCore = $env:ETAT_CORE
$script:AncienProfil = $env:ANCIEN_PROFIL_ESSAI
$script:DossierInstance = $env:DOSSIER_INSTANCE_ESSAI
$script:InstanceExistait = $false
$script:OpsysHome = $env:OPSYS_HOME_ESSAI
$script:Travail = $env:TRAVAIL_ESSAI
$script:Constats = New-Object System.Collections.Generic.List[string]
"""


def _fonctions(tmp_path: Path, corps: str, script: Path = PREUVE_PS1, **env: str) -> subprocess.CompletedProcess[str]:
    """Charge les fonctions de `script` puis exécute `corps` (sous Set-StrictMode 2.0, comme le script)."""
    etat = tmp_path / "etat"
    etat.mkdir(exist_ok=True)
    (tmp_path / "instance").mkdir(exist_ok=True)
    (tmp_path / "travail").mkdir(exist_ok=True)
    environnement = {"SCRIPT_CHARGE": str(script), "ETAT_CORE": str(etat),
                     "ANCIEN_PROFIL_ESSAI": str(tmp_path / "ancien-profil"),
                     "DOSSIER_INSTANCE_ESSAI": str(tmp_path / "dossier-instance"),
                     "OPSYS_HOME_ESSAI": str(tmp_path / "instance"), "TRAVAIL_ESSAI": str(tmp_path / "travail"), **env}
    return pwsh("-Command", CHARGEUR + corps, env=environnement)


def _ecrire_env(tmp_path: Path) -> None:
    etat = tmp_path / "etat"
    etat.mkdir(exist_ok=True)
    (etat / ".env").write_text(
        f"OPSYS_MCP_JETON={SECRET}\nOPSYS_CLE_M01=sk-opsys-m01-fictive-0123456789\nRIEN=ceci\nOPSYS_COURT_JETON=court\n",
        encoding="utf-8")


@avec_pwsh
def test_les_valeurs_secretes_sont_celles_de_env_de_douze_caracteres_et_plus(tmp_path):
    _ecrire_env(tmp_path)

    resultat = _fonctions(tmp_path, "(Get-ValeursSecretes) -join '|'")

    assert resultat.returncode == 0, _sortie(resultat)
    assert resultat.stdout.strip() == f"{SECRET}|sk-opsys-m01-fictive-0123456789"  # ni RIEN=ceci, ni la valeur courte


@avec_pwsh
def test_les_secrets_sont_declares_au_masque_de_github_et_masques_dans_le_texte(tmp_path):
    _ecrire_env(tmp_path)

    resultat = _fonctions(tmp_path, f"Publish-Masque; Hide-Secrets 'le jeton {SECRET} et le reste'")

    assert resultat.returncode == 0, _sortie(resultat)
    lignes = resultat.stdout.splitlines()
    assert f"::add-mask::{SECRET}" in lignes and "::add-mask::sk-opsys-m01-fictive-0123456789" in lignes
    assert "le jeton *** et le reste" in lignes


@avec_pwsh
def test_un_secret_dans_un_fichier_est_trouve_meme_binaire_et_jamais_imprime(tmp_path):
    _ecrire_env(tmp_path)
    propre, fautif, binaire = tmp_path / "propre.log", tmp_path / "fautif.log", tmp_path / "base.db"
    propre.write_text("rien a voir\n", encoding="utf-8")
    fautif.write_text(f"le moteur dit {SECRET}\n", encoding="utf-8")
    binaire.write_bytes(b"\x00\xff\xfe" + SECRET.encode() + b"\x00\x01")

    sans = _fonctions(tmp_path, f"Assert-SansSecret 'journal' @('{propre}'); 'passe'")
    avec = _fonctions(tmp_path, f"Assert-SansSecret 'journal' @('{propre}', '{fautif}')")
    avec_binaire = _fonctions(tmp_path, f"Assert-SansSecret 'base' @('{binaire}')")

    assert sans.returncode == 0 and "passe" in sans.stdout, _sortie(sans)
    assert avec.returncode != 0 and "journal : un secret de .env apparait dans" in _sortie(avec)
    assert avec_binaire.returncode != 0 and "base : un secret de .env apparait dans" in _sortie(avec_binaire)
    assert SECRET not in _sortie(avec) and SECRET not in _sortie(avec_binaire)  # la faute n'imprime pas la valeur


@avec_pwsh
def test_l_empreinte_des_fichiers_geres_change_quand_un_fichier_gere_change(tmp_path):
    etat = tmp_path / "etat"
    (etat / "opsys").mkdir(parents=True)
    (etat / ".env").write_text("A=1\n", encoding="utf-8")
    (etat / "openclaw.json").write_text("{}", encoding="utf-8")
    (etat / "opsys" / "metier.json").write_text("{}", encoding="utf-8")
    (tmp_path / "instance").mkdir()
    (tmp_path / "instance" / "paliers.yaml").write_text("paliers: {}\n", encoding="utf-8")
    corps = ("$a = Get-EmpreinteDesFichiersGeres; $b = Get-EmpreinteDesFichiersGeres; "
             "Set-Content -LiteralPath (Join-Path $script:EtatCore 'opsys\\metier.json') -Value '{\"actif\": true}'; "
             "$c = Get-EmpreinteDesFichiersGeres; \"$a|$b|$c\"")
    corps = corps.replace("opsys\\metier.json", "opsys/metier.json")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.returncode == 0, _sortie(resultat)
    a, b, c = resultat.stdout.strip().split("|")
    assert a == b and a != c and re.fullmatch(r"[0-9a-f]{64}", a)


@avec_pwsh
def test_les_annotations_github_echappent_le_pourcentage_et_les_sauts_de_ligne(tmp_path):
    resultat = _fonctions(tmp_path, 'ConvertTo-Annotation "100% de`r`nlignes`nmultiples"')

    assert resultat.stdout.strip() == "100%25 de%0D%0Alignes%0Amultiples"


@avec_pwsh
def test_un_echec_ferme_le_groupe_pose_l_annotation_et_le_resume(tmp_path):
    resume = tmp_path / "resume.md"
    corps = ("$script:EnActions = $true; $script:GroupeOuvert = $true; Write-Host '::group::5. Service'; "
             "Write-Echec 'la cause'")

    resultat = _fonctions(tmp_path, corps, GITHUB_STEP_SUMMARY=str(resume))

    sortie = resultat.stdout.splitlines()
    assert resultat.returncode == 0, _sortie(resultat)
    assert sortie.index("::group::5. Service") < sortie.index("::endgroup::")  # fermé AVANT la cause
    assert "::error title=Installateur Windows - etape 5::la cause" in sortie
    assert "ECHEC : la cause" in resultat.stderr
    assert "ECHEC a l'etape '5. Service'" in resume.read_text(encoding="utf-8")


@avec_pwsh
def test_un_echec_declare_d_abord_les_secrets_au_masque_de_github(tmp_path):
    _ecrire_env(tmp_path)

    resultat = _fonctions(tmp_path, "Write-Echec 'la cause'")

    assert f"::add-mask::{SECRET}" in resultat.stdout.splitlines()


@avec_pwsh
def test_stop_preuve_leve_le_message_et_marque_l_echec_prevu(tmp_path):
    corps = ("try { Stop-Preuve 'constat faux' } "
             "catch { \"attrape : $($_.Exception.Message) prevu=$($script:EchecPrevu)\" }")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.stdout.strip() == "attrape : constat faux prevu=True"


@avec_pwsh
def test_les_sondes_http_rendent_le_code_ou_zero_et_attendent_l_arret(tmp_path):
    class Repond(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(401 if self.path == "/mcp" and "Bearer bon" not in str(self.headers) else 200)
            self.end_headers()

        def log_message(self, *_: object) -> None:
            return

    serveur = HTTPServer(("127.0.0.1", 0), Repond)
    port = serveur.server_port
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    try:
        ouvert = _fonctions(tmp_path, (
            f"'ok=' + (Get-CodeHttp 'http://127.0.0.1:{port}/x'); "
            f"'sans=' + (Get-CodeHttp 'http://127.0.0.1:{port}/mcp'); "
            f"'avec=' + (Get-CodeHttp 'http://127.0.0.1:{port}/mcp' @{{ Authorization = 'Bearer bon' }}); "
            f"try {{ Wait-Arret 'http://127.0.0.1:{port}/x' 2 'le service' }} "
            "catch { 'refus=' + $_.Exception.Message }"))
    finally:
        serveur.shutdown()
        serveur.server_close()
    ferme = _fonctions(tmp_path, (
        f"'ferme=' + (Get-CodeHttp 'http://127.0.0.1:{port}/x'); "
        f"Wait-Arret 'http://127.0.0.1:{port}/x' 2 'le service'; 'arrete'; "
        f"try {{ Wait-Http 'http://127.0.0.1:{port}/x' 2 'le moteur' }} catch {{ 'refus=' + $_.Exception.Message }}"))

    assert ouvert.returncode == 0, _sortie(ouvert)
    lignes = ouvert.stdout.splitlines()
    assert lignes[:3] == ["ok=200", "sans=401", "avec=200"]
    assert lignes[3].startswith("refus=le service : http://127.0.0.1:")
    assert "repond encore 2 s apres l'arret" in lignes[3]
    assert ferme.stdout.splitlines()[:2] == ["ferme=0", "arrete"]  # rien ne répond : 0, comme le 000 de curl
    assert "refus=le moteur : pas de reponse 200 sur" in ferme.stdout


@avec_pwsh
def test_invoke_natif_rend_le_code_de_sortie_et_les_deux_flux_sans_planter(tmp_path):
    corps = ("$r = Invoke-Natif { & bash -c 'echo sortie; echo erreur >&2; exit 3' }; "
             "\"code=$($r.Code) sortie=$($r.Sortie -replace \"`n\", '|')\"; "
             "$ok = Invoke-Natif { & bash -c 'exit 0' }; \"ok=$($ok.Code)\"")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.returncode == 0, _sortie(resultat)
    code, ok = resultat.stdout.splitlines()
    # l'ordre des deux flux n'est pas garanti
    assert code in {"code=3 sortie=sortie|erreur", "code=3 sortie=erreur|sortie"}
    assert ok == "ok=0"


@avec_pwsh
def test_get_derniere_ligne_et_get_reglage(tmp_path):
    corps = ("Get-DerniereLigne \"a`n`nb  `n\"; Get-DerniereLigne ''; "
             "'defaut=' + (Get-Reglage 'OPSYS_VARIABLE_INEXISTANTE' 'x'); 'pose=' + (Get-Reglage 'OPSYS_ESSAI' 'x')")

    resultat = _fonctions(tmp_path, corps, OPSYS_ESSAI="valeur")

    assert resultat.stdout.splitlines() == ["b", "", "defaut=x", "pose=valeur"]


# -- le script de preuve, joué jusqu'à sa première commande Windows --------------------------------------------------
@avec_pwsh
def test_le_script_de_preuve_echoue_proprement_hors_de_windows_avec_groupe_annotation_et_resume(tmp_path):
    personnel = tmp_path / "personnel"
    personnel.mkdir()
    resume = tmp_path / "resume.md"

    resultat = pwsh("-File", str(PREUVE_PS1), env={
        "HOME": str(personnel), "USERPROFILE": str(personnel), "OPSYS_TRAVAIL": str(tmp_path / "travail"),
        "GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(resume)})

    # schtasks.exe n'existe pas ici : c'est la première commande Windows du script
    assert resultat.returncode == 1, _sortie(resultat)
    assert "::group::0. Poste" in resultat.stdout and "::endgroup::" in resultat.stdout
    assert "::error title=Installateur Windows - etape 0::" in resultat.stdout
    assert "schtasks.exe" in resultat.stderr and "at Invoke-Preuve" in resultat.stderr  # la trace dit où
    assert "ECHEC a l'etape '0. Poste" in resume.read_text(encoding="utf-8")


@avec_pwsh
@pytest.mark.parametrize("dossier", [".opsys/core", ".openclaw-opsys"], ids=["etat-canonique", "ancien-emplacement"])
def test_le_script_de_preuve_refuse_un_poste_qui_porte_deja_un_etat_du_core(tmp_path, dossier):
    personnel = tmp_path / "personnel"
    (personnel / dossier).mkdir(parents=True)

    resultat = pwsh("-File", str(PREUVE_PS1), env={
        "HOME": str(personnel), "USERPROFILE": str(personnel), "OPSYS_TRAVAIL": str(tmp_path / "travail")})

    assert resultat.returncode == 1
    assert "existe deja : " in resultat.stderr and "script" in resultat.stderr
    assert str(personnel / dossier) in resultat.stderr
    assert "erreur inattendue" not in resultat.stderr  # un constat, pas un plantage


@avec_pwsh
def test_le_fichier_de_configuration_lu_est_opsys_json_ou_l_openclaw_json_qui_existe(tmp_path):
    corps = ("$e = $script:EtatCore; 'neuf=' + (Split-Path -Leaf (Get-ConfigDe $e)); "
             "Set-Content -LiteralPath (Join-Path $e 'openclaw.json') -Value '{}'; "
             "'ancien=' + (Split-Path -Leaf (Get-ConfigDe $e)); "
             "Set-Content -LiteralPath (Join-Path $e 'opsys.json') -Value '{}'; "
             "'les-deux=' + (Split-Path -Leaf (Get-ConfigDe $e))")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.returncode == 0, _sortie(resultat)
    assert resultat.stdout.splitlines() == ["neuf=opsys.json", "ancien=openclaw.json", "les-deux=opsys.json"]


@avec_pwsh
def test_le_env_du_core_est_celui_de_l_etat_canonique_ou_a_defaut_de_l_ancien_dossier(tmp_path):
    corps = ("$defaut = Get-EnvDuCore; 'defaut-ancien=' + ($defaut -eq (Join-Path $script:AncienProfil '.env')); "
             "Set-Content -LiteralPath (Join-Path $script:EtatCore '.env') -Value 'A=1'; "
             "'canonique=' + ((Get-EnvDuCore) -eq (Join-Path $script:EtatCore '.env'))")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.returncode == 0, _sortie(resultat)
    assert resultat.stdout.splitlines() == ["defaut-ancien=True", "canonique=True"]


@avec_pwsh
def test_l_empreinte_de_l_etat_ne_depend_pas_de_l_emplacement_et_la_liste_dit_ce_qui_manque(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for dossier in (a, b):
        (dossier / "opsys").mkdir(parents=True)
        (dossier / ".env").write_text("OPSYS_MCP_JETON=0123456789abcdef\n", encoding="utf-8")
        (dossier / "opsys" / "tools.json").write_text("{}", encoding="utf-8")
        (dossier / "opsys" / "metier.json").write_text('{"actif": true}', encoding="utf-8")
    corps = (f"$a = '{a}'; $b = '{b}'; "
             "if ((Get-EmpreinteDeLEtat $a) -eq (Get-EmpreinteDeLEtat $b)) { 'meme-empreinte' }; "
             "(Get-ListeDeLEtat $a) -join '|'; "
             "Remove-Item -LiteralPath (Join-Path $b 'opsys/tools.json'); "
             "try { Assert-RienDePerdu (Get-ListeDeLEtat $a) $b } catch { 'perdu=' + $_.Exception.Message }; "
             "Set-Content -LiteralPath (Join-Path $b '.env') -Value 'autre'; "
             "if ((Get-EmpreinteDeLEtat $a) -ne (Get-EmpreinteDeLEtat $b)) { 'secret-modifie-vu' }")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.returncode == 0, _sortie(resultat)
    lignes = resultat.stdout.splitlines()
    assert lignes[0] == "meme-empreinte"
    assert sorted(lignes[1].split("|")) == [".env", "opsys/metier.json", "opsys/tools.json"]
    assert lignes[2] == f"perdu=Doctor a perdu opsys/tools.json en deplacant l'etat vers {b}"
    assert lignes[3] == "secret-modifie-vu"


@avec_pwsh
def test_un_lien_de_dossier_se_reconnait_et_dit_sa_cible(tmp_path):
    cible, reel, lien = tmp_path / "cible", tmp_path / "reel", tmp_path / "lien"
    cible.mkdir()
    reel.mkdir()
    lien.symlink_to(cible, target_is_directory=True)
    corps = (f"'lien=' + (Test-LienDeDossier '{lien}'); 'reel=' + (Test-LienDeDossier '{reel}'); "
             f"'absent=' + (Test-LienDeDossier '{tmp_path / 'absent'}'); 'cible=' + (Get-CibleDuLien '{lien}'); "
             f"'vide=[' + (Get-CibleDuLien '{reel}') + ']'")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.returncode == 0, _sortie(resultat)
    assert resultat.stdout.splitlines() == ["lien=True", "reel=False", "absent=False", f"cible={cible}", "vide=[]"]


@avec_pwsh
def test_la_definition_du_service_nomme_le_dossier_d_etat_sans_tenir_compte_de_la_casse(tmp_path):
    script = 'set "OPENCLAW_STATE_DIR=C:\\Users\\x\\.opsys\\core"'
    corps = (f"$s = '{script}'; "
             "Test-EtatNommeParLeService $s 'C:\\Users\\x\\.opsys\\core'; "
             "Test-EtatNommeParLeService $s 'C:\\Users\\x\\.openclaw-opsys'; "
             "Test-EtatNommeParLeService $s 'c:\\users\\X\\.OPSYS\\core'")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.returncode == 0, _sortie(resultat)
    assert resultat.stdout.splitlines() == ["True", "False", "True"]


@avec_pwsh
def test_un_dossier_se_deplace_par_renommage(tmp_path):
    source, cible = tmp_path / "source", tmp_path / "cible"
    source.mkdir()
    (source / "f").write_text("x", encoding="utf-8")

    resultat = _fonctions(tmp_path, f"Move-DossierAvecReprises '{source}' '{cible}'; 'fin'")

    assert resultat.returncode == 0, _sortie(resultat)
    assert (cible / "f").is_file() and not source.exists()  # renommé, pas copié


@avec_pwsh
def test_le_dossier_d_instance_ne_se_retire_que_s_il_est_vide_et_né_avec_le_script(tmp_path):
    vide, plein, existait = tmp_path / "vide", tmp_path / "plein", tmp_path / "existait"
    for dossier in (vide, plein, existait):
        dossier.mkdir()
    (plein / "f").write_text("x", encoding="utf-8")
    corps = (f"$script:DossierInstance = '{vide}'; Remove-DossierInstanceVide; "
             f"$script:DossierInstance = '{plein}'; Remove-DossierInstanceVide; "
             f"$script:InstanceExistait = $true; $script:DossierInstance = '{existait}'; "
             "Remove-DossierInstanceVide; 'fin'")

    resultat = _fonctions(tmp_path, corps)

    assert resultat.returncode == 0, _sortie(resultat)
    assert not vide.exists()  # vide et né avec le script : retiré
    assert (plein / "f").is_file()  # jamais un dossier qui porte quelque chose
    assert existait.is_dir()  # jamais un dossier qui existait avant le script


@avec_pwsh
@pytest.mark.parametrize("dossier", [".opsys/core", ".openclaw-opsys"], ids=["etat-canonique", "ancien-emplacement"])
def test_le_diagnostic_imprime_les_journaux_sans_secret_ni_contenu_de_env_et_sort_en_0(tmp_path, dossier):
    personnel = tmp_path / "personnel"
    (personnel / dossier).mkdir(parents=True)
    (personnel / dossier / ".env").write_text(f"OPSYS_MCP_JETON={SECRET}\nRIEN=ceci\n", encoding="utf-8")
    travail = tmp_path / "travail"
    travail.mkdir()
    (travail / "installation-1.log").write_text(f"debut\nle moteur dit {SECRET} fin\n", encoding="utf-8")

    resultat = pwsh("-File", str(DIAGNOSTIC_PS1), env={
        "HOME": str(personnel), "USERPROFILE": str(personnel), "OPSYS_TRAVAIL": str(travail), "GITHUB_ACTIONS": "true"})

    assert resultat.returncode == 0, _sortie(resultat)
    imprime = "\n".join(ligne for ligne in _sortie(resultat).splitlines() if not ligne.startswith("::add-mask::"))
    assert f"::add-mask::{SECRET}" in resultat.stdout
    assert SECRET not in imprime and "le moteur dit *** fin" in imprime
    assert "RIEN=ceci" not in imprime and "OPSYS_MCP_JETON" not in imprime
    assert resultat.stdout.count("::group::") == resultat.stdout.count("::endgroup::")


# -- install.ps1 et uninstall.ps1 : l'environnement de l'appelant, les reprises de suppression -----------------------
def _ligne_du_script(script: Path, motif: str) -> str:
    """Une affectation de portée script (`$script:X = ...`) lue TELLE QUELLE dans le script : le test la rejoue."""
    trouvee = re.search(motif, script.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert trouvee, motif
    return trouvee.group(0)


@avec_pwsh
@pytest.mark.parametrize("script", [INSTALL_PS1, UNINSTALL_PS1], ids=lambda p: p.name)
def test_le_script_rend_a_l_appelant_l_environnement_qu_il_a_pose_ou_retire(tmp_path, script):
    prologue = "\n".join([
        _ligne_du_script(script, r"^\$script:VariablesEcartees = .*$"),
        _ligne_du_script(script, r"^\$script:EnvTouchee = .*$"),
        "$script:BinAjoute = $false; $script:Bin = 'BIN-AJOUTE'"])
    corps = prologue + """
$env:OPSYS_HOME = 'avant'
$env:OPENCLAW_STATE_DIR = 'etat-de-l-appelant'
$env:CI = $null
$env:PYTHONUTF8 = $null
$env:Path = 'chemin-initial'
$cheminAvant = $env:Path
Save-Environnement
# ce que le script fait pendant son travail :
$env:CI = 'true'
$env:OPSYS_HOME = 'autre'
$env:PYTHONUTF8 = '1'
$env:COREPACK_ENABLE_DOWNLOAD_PROMPT = '0'
Remove-Item -LiteralPath 'Env:OPENCLAW_STATE_DIR'
$env:Path = "pnpm-1;$($env:Path)"
$script:BinAjoute = __BIN__
Restore-Environnement
"CI=[$($env:CI)]"
"OPSYS_HOME=[$($env:OPSYS_HOME)]"
"PYTHONUTF8=[$($env:PYTHONUTF8)]"
"COREPACK=[$($env:COREPACK_ENABLE_DOWNLOAD_PROMPT)]"
"ETAT=[$($env:OPENCLAW_STATE_DIR)]"
"PATH_INCHANGE=$($env:Path -eq $cheminAvant)"
"PATH_AVEC_BIN=$($env:Path -eq ($cheminAvant + ';BIN-AJOUTE'))"
"""
    sans_bin = _fonctions(tmp_path, corps.replace("__BIN__", "$false"), script=script)
    avec_bin = _fonctions(tmp_path, corps.replace("__BIN__", "$true"), script=script)

    assert sans_bin.returncode == 0, _sortie(sans_bin)
    lignes = sans_bin.stdout.splitlines()
    assert lignes[1:5:3] == ["OPSYS_HOME=[avant]", "ETAT=[etat-de-l-appelant]"]  # posé puis rendu ; retiré puis rendu
    assert lignes[2] == "PYTHONUTF8=[]"
    if script == INSTALL_PS1:  # install.ps1 pose aussi CI=true (pnpm) et COREPACK_* : il les rend
        assert lignes[0] == "CI=[]" and lignes[3] == "COREPACK=[]"
        assert "PATH_INCHANGE=True" in lignes  # le PATH de pnpm ne reste pas dans la session
        assert "PATH_AVEC_BIN=False" in lignes
        # le dossier des commandes, lui, reste : on s'en sert tout de suite
        assert "PATH_AVEC_BIN=True" in avec_bin.stdout.splitlines()
    else:  # uninstall.ps1 ne pose pas CI : il ne s'en occupe pas (ici, la valeur que le test lui a donnée reste)
        assert lignes[0] == "CI=[true]"


@avec_pwsh
def test_restore_environnement_ne_fait_rien_sans_sauvegarde(tmp_path):
    prologue = "\n".join([_ligne_du_script(INSTALL_PS1, r"^\$script:VariablesEcartees = .*$"),
                          _ligne_du_script(INSTALL_PS1, r"^\$script:EnvTouchee = .*$"), "$script:EnvAvant = $null"])

    corps = prologue + "\n$env:CI = 'reste'; Restore-Environnement; $env:CI"

    resultat = _fonctions(tmp_path, corps, script=INSTALL_PS1)

    assert resultat.stdout.strip() == "reste"


def _moteur_de_reprises(essais_qui_echouent: int) -> str:
    """`Remove-Item` et `Start-Sleep` remplacés : le premier échoue n fois (fichier ouvert), l'autre ne dort pas."""
    return f"""
$script:Tentatives = 0
$script:Pauses = 0
function Remove-Item {{
    param([string]$LiteralPath, [switch]$Recurse, [switch]$Force, $ErrorAction)
    $script:Tentatives++
    if ($script:Tentatives -le {essais_qui_echouent}) {{
        throw 'Le processus ne peut pas acceder au fichier car il est utilise par un autre processus.'
    }}
}}
function Start-Sleep {{ param([int]$Seconds) $script:Pauses++ }}
"""


@avec_pwsh
def test_la_suppression_est_reessayee_tant_qu_un_processus_tient_un_fichier_ouvert(tmp_path):
    corps = (_moteur_de_reprises(3) + "Remove-CheminAvecReprises 'C:\\logiciel\\venv'; "
             "\"tentatives=$($script:Tentatives) pauses=$($script:Pauses)\"")

    resultat = _fonctions(tmp_path, corps, script=UNINSTALL_PS1)

    assert resultat.returncode == 0, _sortie(resultat)
    assert resultat.stdout.strip() == "tentatives=4 pauses=3"  # trois refus, un succès, une pause après chaque refus


@avec_pwsh
def test_la_suppression_abandonne_avec_l_erreur_d_origine_apres_les_essais(tmp_path):
    corps = (_moteur_de_reprises(99) + "try { Remove-CheminAvecReprises 'C:\\logiciel\\venv' 4 } "
             "catch { \"echec : $($_.Exception.Message)\" }; "
             "\"tentatives=$($script:Tentatives) pauses=$($script:Pauses)\"")

    resultat = _fonctions(tmp_path, corps, script=UNINSTALL_PS1)

    assert resultat.returncode == 0, _sortie(resultat)
    lignes = resultat.stdout.splitlines()
    assert lignes[0].startswith("echec : Le processus ne peut pas acceder au fichier")
    assert lignes[1] == "tentatives=4 pauses=3"  # pas de pause après le dernier essai


@avec_pwsh
def test_la_suppression_de_dossier_passe_par_les_reprises_apres_la_garde(tmp_path):
    """Le retrait du logiciel passe par `Remove-CheminAvecReprises`, et la garde des données reste avant lui."""
    source = UNINSTALL_PS1.read_text(encoding="utf-8")
    remove_dossier = re.search(r"function Remove-Dossier \{.*?\n\}", source, flags=re.DOTALL)

    assert remove_dossier is not None
    corps = remove_dossier.group(0)
    assert corps.index("Test-Garde $Dossier") < corps.index("Remove-CheminAvecReprises")
    assert "Remove-Item" not in corps


def test_opsys_metier_cmd_force_l_utf_8_de_python_pour_qu_une_sortie_redirigee_ne_plante_pas():
    """Sous Windows, Python encode un tube en cp1252 : la flèche de `opsys-metier mode` fait échouer `print`.

    `opsys metier <commande>` (par le core) reçoit le même réglage du core lui-même
    (`buildOpsysMetierCliEnv`, PYTHONUTF8 sous win32) ; ici, l'enveloppe du moteur seul.
    """
    source = INSTALL_PS1.read_text(encoding="utf-8")
    bloc = source[source.index("Write-Enveloppe $cibleMoteur @("):]
    bloc = bloc[:bloc.index("Write-Info \"commandes installees")]

    assert "'set \"PYTHONUTF8=1\"'" in bloc
    assert bloc.index("PYTHONUTF8") < bloc.index("-m opsys.cli")  # posé AVANT le lancement de Python
