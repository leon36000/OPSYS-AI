# tests/installateur/diagnostic.ps1 : ce que la CI imprime apres un echec de bout_en_bout.ps1 (Windows).
#
# Ce script ne fait rien d'autre que lire : il n'installe, ne demarre ni ne supprime rien, et il ne s'arrete jamais sur
# une commande en echec (un diagnostic partiel vaut mieux que pas de diagnostic).
#
# Aucun secret : les valeurs secretes de <etat du core>\.env (jetons, cles) sont d'abord declarees au masque de GitHub
# (::add-mask::), puis remplacees par *** dans tout ce qui est imprime, meme hors de GitHub. Le contenu de .env n'est
# jamais imprime : seulement des noms et des tailles.
#
# Sortie : un groupe repliable (::group::) par sujet sous GitHub Actions, des titres "== sujet" ailleurs.
# Variables : OPSYS_TRAVAIL (dossier de travail de bout_en_bout.ps1), OPSYS_LOGICIEL (defaut : <travail>\logiciel),
# OPSYS_PORT_GATEWAY, OPSYS_PORT_MOTEUR (defauts 18789 et 8765), OPSYS_DIAGNOSTIC_LIGNES (defaut 300).
#
# ASCII pur, sans BOM, comme install.ps1.

[CmdletBinding(PositionalBinding = $false)]
param()

$ErrorActionPreference = 'Continue'
Set-StrictMode -Version 2.0

$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:EnActions = -not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('GITHUB_ACTIONS'))
$travail = [Environment]::GetEnvironmentVariable('OPSYS_TRAVAIL')
$logiciel = [Environment]::GetEnvironmentVariable('OPSYS_LOGICIEL')
if ([string]::IsNullOrEmpty($logiciel) -and -not [string]::IsNullOrEmpty($travail)) { $logiciel = Join-Path $travail 'logiciel' }
$personnel = [Environment]::GetEnvironmentVariable('HOME')
if ([string]::IsNullOrEmpty($personnel)) { $personnel = [Environment]::GetEnvironmentVariable('USERPROFILE') }
$etatCore = Join-Path $personnel '.openclaw-opsys'
$portGateway = 18789
$portMoteur = 8765
$valeur = [Environment]::GetEnvironmentVariable('OPSYS_PORT_GATEWAY')
if ($valeur -match '^[0-9]+$') { $portGateway = [int]$valeur }
$valeur = [Environment]::GetEnvironmentVariable('OPSYS_PORT_MOTEUR')
if ($valeur -match '^[0-9]+$') { $portMoteur = [int]$valeur }
$lignesMax = 300
$valeur = [Environment]::GetEnvironmentVariable('OPSYS_DIAGNOSTIC_LIGNES')
if ($valeur -match '^[0-9]+$') { $lignesMax = [int]$valeur }
$nomTache = 'OpenClaw Gateway (opsys)'
$script:Secrets = @()
try { [Console]::OutputEncoding = $script:Utf8 } catch { $null = $_ }

function Get-ValeursSecretes {
    $fichier = Join-Path $etatCore '.env'
    if (-not (Test-Path -LiteralPath $fichier)) { return @() }
    $valeurs = @()
    foreach ($ligne in [System.IO.File]::ReadAllLines($fichier, $script:Utf8)) {
        if ($ligne -match '^\s*(?:export\s+)?[A-Z0-9_]*(?:JETON|TOKEN|_CLE|SECRET|PASSWORD)[A-Z0-9_]*=(.{12,})$') { $valeurs += $Matches[1] }
    }
    return $valeurs
}

function Hide-Secrets {
    param([string]$Texte)
    foreach ($secret in $script:Secrets) { $Texte = $Texte.Replace($secret, '***') }
    return $Texte
}

function Write-Sujet {
    param([string]$Titre)
    if ($script:EnActions) { Write-Host "::group::$Titre" } else { Write-Host ''; Write-Host "== $Titre" }
}

function Write-FinSujet {
    if ($script:EnActions) { Write-Host '::endgroup::' }
}

# Les dernieres lignes d'un fichier, meme ouvert en ecriture par un processus qui tourne, secrets masques.
function Write-FinDuFichier {
    param([string]$Chemin)
    Write-Sujet $Chemin
    try {
        $flux = [System.IO.File]::Open($Chemin, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $lecteur = New-Object System.IO.StreamReader($flux, $script:Utf8)
            $lignes = @($lecteur.ReadToEnd() -split "`r?`n")
        }
        finally { $flux.Dispose() }
        $debut = [Math]::Max(0, $lignes.Count - $lignesMax)
        Write-Host (Hide-Secrets (($lignes[$debut..($lignes.Count - 1)]) -join "`n"))
    }
    catch { Write-Host "illisible : $($_.Exception.Message)" }
    Write-FinSujet
}

function Write-Commande {
    param([string]$Titre, [scriptblock]$Commande)
    Write-Sujet $Titre
    try { Write-Host (Hide-Secrets ((@(& $Commande 2>&1 | ForEach-Object { "$_" })) -join "`n")) }
    catch { Write-Host "echec : $($_.Exception.Message)" }
    Write-FinSujet
}

foreach ($secret in (Get-ValeursSecretes)) { Write-Host "::add-mask::$secret" }
$script:Secrets = @(Get-ValeursSecretes)

if ($travail) {
    foreach ($fichier in @(Get-ChildItem -LiteralPath $travail -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in '.log', '.err', '.xml' })) { Write-FinDuFichier $fichier.FullName }
}
if ($logiciel) {
    $dossierJournaux = Join-Path $logiciel 'journaux'
    foreach ($fichier in @(Get-ChildItem -LiteralPath $dossierJournaux -File -Filter '*.log' -ErrorAction SilentlyContinue)) { Write-FinDuFichier $fichier.FullName }
}

Write-Commande "tache planifiee '$nomTache' (schtasks /Query /V)" { & schtasks.exe /Query /TN $nomTache /V /FO LIST }
Write-Commande "tache planifiee '$nomTache' (dernier lancement)" { Get-ScheduledTask -TaskName $nomTache -ErrorAction Stop | Get-ScheduledTaskInfo | Format-List | Out-String }

$scriptTache = Join-Path $etatCore 'gateway.cmd'
if (Test-Path -LiteralPath $scriptTache) { Write-FinDuFichier $scriptTache }

$appdata = [Environment]::GetEnvironmentVariable('APPDATA')
if ($appdata) {
    Write-Commande 'entrees du dossier Demarrage (noms seulement)' {
        Get-ChildItem -LiteralPath (Join-Path $appdata 'Microsoft\Windows\Start Menu\Programs\Startup') -Force -ErrorAction Stop | ForEach-Object { $_.Name }
    }
}

# L'etat du core : les noms et les tailles seulement, jamais le contenu (.env : secrets en clair).
Write-Commande "etat du core ($etatCore : noms et tailles seulement)" {
    Get-ChildItem -LiteralPath $etatCore -Force -Recurse -Depth 2 -ErrorAction Stop | Select-Object -First 100 | ForEach-Object { '{0,10} {1}' -f $_.Length, $_.FullName }
}

$logsDuCore = @()
$dossierLogs = Join-Path $etatCore 'logs'
if (Test-Path -LiteralPath $dossierLogs) { $logsDuCore += @(Get-ChildItem -LiteralPath $dossierLogs -File -Recurse | ForEach-Object { $_.FullName }) }
foreach ($dossier in @(Get-ChildItem -LiteralPath ([System.IO.Path]::GetTempPath()) -Directory -Filter 'openclaw*' -ErrorAction SilentlyContinue)) {
    $logsDuCore += @(Get-ChildItem -LiteralPath $dossier.FullName -File -Filter '*.log' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
}
foreach ($fichier in $logsDuCore) { Write-FinDuFichier $fichier }

Write-Sujet 'sante du Gateway et du moteur'
foreach ($url in @("http://127.0.0.1:$portGateway/startupz", "http://127.0.0.1:$portMoteur/sante")) {
    try { $reponse = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop; Write-Host "$url -> $([int]$reponse.StatusCode)" }
    catch { Write-Host "$url -> $($_.Exception.Message)" }
}
Write-FinSujet

Write-Commande 'ports en ecoute (Gateway, moteur)' {
    Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in $portGateway, $portMoteur } | ForEach-Object { "port $($_.LocalPort) : processus $($_.OwningProcess)" }
}
Write-Commande 'processus node et python (la ligne de commande, secrets masques)' {
    Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -match '^(node|python|pythonw|uv)(\.exe)?$' } |
        Select-Object -First 30 | ForEach-Object { "{0} (parent {1}) {2} {3}" -f $_.ProcessId, $_.ParentProcessId, $_.Name, $_.CommandLine }
}
exit 0
