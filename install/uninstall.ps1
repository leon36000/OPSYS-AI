# install/uninstall.ps1 : retire OPSYS (service, commandes, logiciel) sur Windows SANS toucher aux donnees.
#
#   install\uninstall.ps1 [-ExporterAvant <archive.tar.gz>] [-Simuler]
#
# Meme comportement que install/uninstall.sh (voir son en-tete) :
#   1. avec -ExporterAvant : archive d'abord l'instance (`opsys instance exporter`, empreinte SHA-256 incluse) ; si
#      l'export echoue, RIEN n'est retire ;
#   2. arrete et retire le service du Gateway (`openclaw gateway uninstall`, sous le profil "opsys" du core : la tache
#      du core d'origine n'est jamais touchee), si l'installateur l'avait installe ;
#   3. retire openclaw.cmd et opsys.cmd (seulement ceux que l'installateur a ecrits), puis le dossier des commandes
#      et son entree du PATH de l'utilisateur s'il est vide ;
#   4. retire le logiciel : environnement Python, journal, et le clone gere par l'installateur. Un depot a vous n'est
#      jamais touche.
#
# Ce script ne supprime JAMAIS les donnees de l'instance : %OPSYS_HOME% (base, paliers, profil d'entreprise) ni l'etat
# du core (dossier du profil "opsys", %USERPROFILE%\.openclaw-opsys : secrets .env, etat du Gateway). La suppression
# definitive est une decision humaine, hors de ce script (docs/exploitation/INSTALLATION.md).
# Relancable. Variables : OPSYS_HOME, OPSYS_LOGICIEL, OPSYS_BIN. Code de sortie : 0 fait ; 1 arrete avant tout retrait
# irreversible, avec quoi faire.
#
# ASCII pur, comme install.ps1 (voir la raison dans son en-tete). Lu par l'analyseur de PowerShell (job analyse) et joue sous
# Windows par le job installation-windows de la CI (tests/installateur/bout_en_bout.ps1).

[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ExporterAvant,
    [switch]$Simuler,
    [switch]$Aide
)

$ErrorActionPreference = 'Stop'
$script:Marque = 'OPSYS-INSTALLATEUR : fichier gere par install.ps1, reecrit a chaque installation. Ne pas editer.'
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
# Comme install.ps1 : le profil du core et les variables qui sortiraient son etat du dossier canonique du profil.
$script:ProfilCore = 'opsys'
$script:VariablesEcartees = @('OPENCLAW_STATE_DIR', 'OPENCLAW_CONFIG_PATH', 'OPENCLAW_HOME', 'OPENCLAW_PROFILE', 'OPENCLAW_LAUNCHD_LABEL', 'OPENCLAW_SYSTEMD_UNIT', 'OPENCLAW_WINDOWS_TASK_NAME')

# Les variables d'environnement que ce script pose ou retire (OPSYS_HOME, PYTHONUTF8, les OPENCLAW_* que le core ne doit pas
# voir) sont celles du PROCESSUS de l'appelant : elles lui sont rendues telles qu'elles etaient (comme install.ps1).
$script:EnvTouchee = @('OPSYS_HOME', 'PYTHONUTF8') + $script:VariablesEcartees
$script:EnvAvant = $null

function Save-Environnement {
    $script:EnvAvant = @{}
    foreach ($nom in $script:EnvTouchee) { $script:EnvAvant[$nom] = [Environment]::GetEnvironmentVariable($nom) }
}

function Restore-Environnement {
    if ($null -eq $script:EnvAvant) { return }
    foreach ($nom in $script:EnvTouchee) { [Environment]::SetEnvironmentVariable($nom, $script:EnvAvant[$nom]) }
    $script:EnvAvant = $null
}

function Write-Info {
    param([string]$Message)
    Write-Host "[opsys] $Message"
}

function Write-Avert {
    param([string]$Message)
    Write-Host "[opsys] AVERTISSEMENT : $Message" -ForegroundColor Yellow
}

function Stop-Desinstall {
    param([string]$Message)
    throw "ERREUR : $Message"
}

function Get-Reglage {
    param([string]$Nom, [string]$Defaut)
    $valeur = [Environment]::GetEnvironmentVariable($Nom)
    if ([string]::IsNullOrWhiteSpace($valeur)) { return $Defaut }
    return $valeur
}

function Read-Enregistrement {
    param([string]$Fichier)
    $lu = @{}
    if (Test-Path -LiteralPath $Fichier) {
        foreach ($ligne in [System.IO.File]::ReadAllLines($Fichier, $script:Utf8)) {
            $position = $ligne.IndexOf('=')
            if ($position -gt 0) { $lu[$ligne.Substring(0, $position)] = $ligne.Substring($position + 1) }
        }
    }
    return $lu
}

function Get-CodeSortie {
    param([scriptblock]$Commande)
    $avant = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = 0
    try {
        & $Commande 2>&1 | ForEach-Object { Write-Host "$_" }
        $codeRetour = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $avant
    }
    return $codeRetour
}

# Un dossier qui est ou contient les donnees de l'instance ou l'etat du core, ou le dossier personnel, ne se supprime jamais.
# Le separateur est celui du systeme (\ sous Windows) : la garde se rejoue ainsi sous PowerShell 7 hors de Windows (tests).
function Test-Garde {
    param([string]$Dossier)
    $sep = [string][System.IO.Path]::DirectorySeparatorChar
    $dossierComplet = [System.IO.Path]::GetFullPath($Dossier).TrimEnd($sep)
    $donnees = [System.IO.Path]::GetFullPath($script:OpsysHome).TrimEnd($sep)
    $profil = [System.IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd($sep)
    $ignorer = [System.StringComparison]::OrdinalIgnoreCase
    if ($dossierComplet -eq '' -or [string]::Equals($dossierComplet, $profil, $ignorer) -or [string]::Equals($dossierComplet, $donnees, $ignorer)) {
        Stop-Desinstall "refus de supprimer '$Dossier' : c'est le dossier personnel ou celui des donnees. Rien n'a ete retire."
    }
    if (($donnees + $sep).StartsWith($dossierComplet + $sep, $ignorer)) {
        Stop-Desinstall "refus de supprimer '$Dossier' : il contient les donnees de l'instance ($($script:OpsysHome)). Rien n'a ete retire."
    }
    $etatCore = [string]$script:Enregistre['DOSSIER_CORE']
    if ($etatCore) {
        $etat = [System.IO.Path]::GetFullPath($etatCore).TrimEnd($sep)
        if (($etat + $sep).StartsWith($dossierComplet + $sep, $ignorer)) {
            Stop-Desinstall "refus de supprimer '$Dossier' : c'est l'etat du core ou il le contient ($etatCore). Rien n'a ete retire."
        }
    }
}

function Get-DossiersDuLogiciel {
    $liste = @($script:Venv, (Join-Path $script:Logiciel 'journaux'))
    if (($script:Enregistre['SOURCE_GEREE'] -eq '1') -and ($script:Enregistre['SOURCE'] -eq (Join-Path $script:Logiciel 'source'))) {
        $liste += (Join-Path $script:Logiciel 'source')
    }
    return $liste
}

function Invoke-Agir {
    param([string]$Libelle, [scriptblock]$Action)
    if ($Simuler) {
        Write-Info "[simulation] $Libelle"
        return
    }
    Write-Info $Libelle
    & $Action
}

# Windows refuse de supprimer un fichier que le processus qu'on vient d'arreter tient encore ouvert (python.exe du moteur,
# node.exe du Gateway) : le retrait est retente pendant vingt secondes avant de conclure a l'echec.
function Remove-CheminAvecReprises {
    param([string]$Chemin, [int]$Essais = 10)
    for ($essai = 1; $essai -le $Essais; $essai++) {
        try {
            Remove-Item -LiteralPath $Chemin -Recurse -Force -ErrorAction Stop
            return
        }
        catch {
            if ($essai -eq $Essais) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

function Remove-Dossier {
    param([string]$Dossier)
    Test-Garde $Dossier
    if (Test-Path -LiteralPath $Dossier) {
        Invoke-Agir "suppression de $Dossier" { Remove-CheminAvecReprises $Dossier }
    }
}

function Invoke-ExportAvant {
    if (-not $ExporterAvant) { return }
    if (-not (Test-Path -LiteralPath $script:VenvPy)) { Stop-Desinstall "l'export demande est impossible : l'environnement Python ($($script:VenvPy)) est introuvable. Rien n'a ete retire." }
    if (-not (Test-Path -LiteralPath (Join-Path $script:OpsysHome 'opsys.db'))) { Stop-Desinstall "l'export demande est impossible : aucune base dans $($script:OpsysHome). Rien n'a ete retire." }
    $archive = [System.IO.Path]::GetFullPath($ExporterAvant)
    if ($Simuler) {
        Write-Info "[simulation] export de l'instance vers $archive"
        return
    }
    Write-Info "export de l'instance vers $archive..."
    $env:OPSYS_HOME = $script:OpsysHome
    $env:PYTHONUTF8 = '1'
    $codeRetour = Get-CodeSortie { & $script:VenvPy -m opsys.cli instance exporter --sortie $archive --par 'poste:desinstallation' }
    if ($codeRetour -ne 0) { Stop-Desinstall "l'export a echoue : RIEN n'a ete retire. Corrigez la cause (message ci-dessus), puis relancez." }
    if (-not ((Test-Path -LiteralPath $archive) -and (Test-Path -LiteralPath "$archive.sha256"))) {
        Stop-Desinstall "l'export n'a pas produit l'archive et son empreinte : RIEN n'a ete retire."
    }
    Write-Info "export termine : $archive (empreinte : $archive.sha256). Protegez-le : il contient des renseignements personnels."
}

function Remove-ServiceGateway {
    if ($script:Enregistre['SERVICE'] -ne '1') {
        Write-Info "aucun service installe par l'installateur : rien a arreter."
        return
    }
    $coeur = Join-Path ([string]$script:Enregistre['SOURCE']) 'core\openclaw.mjs'
    if (-not (Test-Path -LiteralPath $coeur) -or -not (Get-Command node -ErrorAction SilentlyContinue)) {
        Stop-Desinstall "le service est installe mais le core ($coeur) ou Node est introuvable : impossible de le retirer proprement. Retirez la tache planifiee 'OpenClaw Gateway ($($script:ProfilCore))' a la main (Planificateur de taches), puis relancez. Rien n'a ete retire."
    }
    if ($Simuler) {
        Write-Info "[simulation] arret et retrait du service du Gateway"
        return
    }
    Write-Info "arret et retrait du service du Gateway (profil $($script:ProfilCore))"
    $env:OPSYS_HOME = $script:OpsysHome
    foreach ($nom in $script:VariablesEcartees) { Remove-Item -LiteralPath "Env:$nom" -ErrorAction SilentlyContinue }
    $codeRetour = Get-CodeSortie { & node $coeur --profile $script:ProfilCore gateway uninstall }
    if ($codeRetour -ne 0) { Stop-Desinstall "le service n'a pas pu etre retire (message ci-dessus). Rien d'autre n'a ete retire : corrigez, puis relancez." }
}

function Remove-Commandes {
    foreach ($nom in @('openclaw.cmd', 'opsys.cmd')) {
        $cible = Join-Path $script:Bin $nom
        if (Test-Path -LiteralPath $cible) {
            if (Select-String -LiteralPath $cible -SimpleMatch -Pattern $script:Marque -Quiet) {
                Invoke-Agir "suppression de la commande $cible" { Remove-Item -LiteralPath $cible -Force }
            }
            else {
                Write-Avert "$cible n'a pas ete installe par OPSYS : laisse en place."
            }
        }
    }
    if (-not $Simuler -and (Test-Path -LiteralPath $script:Bin) -and -not (Get-ChildItem -LiteralPath $script:Bin -Force)) {
        Remove-Item -LiteralPath $script:Bin -Force
        $cheminUtilisateur = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ($cheminUtilisateur) {
            $reste = @($cheminUtilisateur -split ';' | Where-Object { $_ -and ($_ -ne $script:Bin) })
            [Environment]::SetEnvironmentVariable('Path', ($reste -join ';'), 'User')
        }
    }
}

function Remove-Logiciel {
    foreach ($dossier in (Get-DossiersDuLogiciel)) { Remove-Dossier $dossier }
    if (($script:Enregistre['SOURCE_GEREE'] -ne '1') -and $script:Enregistre['SOURCE']) {
        Write-Info "le depot $($script:Enregistre['SOURCE']) n'est pas gere par l'installateur : laisse en place."
    }
    $fichier = Join-Path $script:Logiciel 'installation.env'
    if (Test-Path -LiteralPath $fichier) {
        Invoke-Agir "suppression de l'enregistrement de l'installation" { Remove-Item -LiteralPath $fichier -Force }
    }
    if (-not $Simuler -and (Test-Path -LiteralPath $script:Logiciel)) {
        if (Get-ChildItem -LiteralPath $script:Logiciel -Force) {
            Write-Avert "$($script:Logiciel) contient encore des fichiers qui ne sont pas a l'installateur : laisse en place."
        }
        else {
            Remove-Item -LiteralPath $script:Logiciel -Force
        }
    }
}

function Invoke-Desinstallation {
    if ($Aide) {
        Write-Host "uninstall.ps1 : retire OPSYS sans supprimer les donnees de l'instance."
        Write-Host "Options : -ExporterAvant <archive.tar.gz>  -Simuler  -Aide"
        Write-Host "Variables : OPSYS_HOME, OPSYS_LOGICIEL, OPSYS_BIN"
        return 0
    }
    Save-Environnement
    try {
        $script:Logiciel = Get-Reglage 'OPSYS_LOGICIEL' (Join-Path $env:LOCALAPPDATA 'OPSYS')
        $script:Enregistre = Read-Enregistrement (Join-Path $script:Logiciel 'installation.env')
        $script:OpsysHome = Get-Reglage 'OPSYS_HOME' ([string]$script:Enregistre['OPSYS_HOME'])
        if (-not $script:OpsysHome) { $script:OpsysHome = Join-Path $env:USERPROFILE '.opsys' }
        $script:Bin = Get-Reglage 'OPSYS_BIN' ([string]$script:Enregistre['OPSYS_BIN'])
        if (-not $script:Bin) { $script:Bin = Join-Path $env:LOCALAPPDATA 'OPSYS\bin' }
        $script:Venv = Join-Path $script:Logiciel 'venv'
        $script:VenvPy = Join-Path $script:Venv 'Scripts\python.exe'
        Write-Info "desinstallation d'OPSYS (donnees conservees : $($script:OpsysHome) et l'etat du core)"
        foreach ($dossier in (Get-DossiersDuLogiciel)) { Test-Garde $dossier }
        Invoke-ExportAvant
        Remove-ServiceGateway
        Remove-Commandes
        Remove-Logiciel
        Write-Host ''
        Write-Host 'OPSYS est retire.'
        Write-Host "  Donnees conservees : $($script:OpsysHome) (base, paliers, profil d'entreprise)."
        $etatConserve = [string]$script:Enregistre['DOSSIER_CORE']
        if (-not $etatConserve) { $etatConserve = "le dossier .openclaw-$($script:ProfilCore) de votre dossier personnel" }
        Write-Host "  Etat du core conserve : $etatConserve (secrets .env, etat du Gateway)."
        if (-not $ExporterAvant) { Write-Host '  Aucun export demande (-ExporterAvant). Pour en faire un maintenant : reinstallez OPSYS, puis opsys instance exporter.' }
        Write-Host '  Les supprimer definitivement est une decision humaine : voir docs/exploitation/INSTALLATION.md.'
        return 0
    }
    catch {
        Write-Host "[opsys] $($_.Exception.Message)" -ForegroundColor Red
        return 1
    }
    finally {
        Restore-Environnement
    }
}

$resultatDesinstallation = @(Invoke-Desinstallation)
$codeSortie = [int]$resultatDesinstallation[-1]
$global:LASTEXITCODE = $codeSortie
if ($PSCommandPath) { exit $codeSortie }
