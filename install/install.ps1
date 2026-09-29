# install/install.ps1 : installe OPSYS (OPSYS-CORE + moteur metier) sur Windows, en une commande.
#
#   git clone https://github.com/leon36000/OPSYS-AI; .\OPSYS-AI\install\install.ps1
#   powershell -c "irm <URL de ce script> | iex"                       (une fois publie : decision humaine, T3)
#   & ([scriptblock]::Create((irm <URL de ce script>))) -SansService   (avec options)
#
# Meme enchainement que install/install.sh (voir son en-tete pour le detail et les raisons) :
#   1. prerequis : Node aux versions du fork, uv (qui fournit Python 3.11+), git (installation a distance), curl.exe
#   2. le code : depot voisin ou -Source tel quel ; sinon clone de OPSYS_REPO_URL a OPSYS_REF
#   3. construction d'OPSYS-CORE (pnpm a la version de core/package.json), moteur Python par uv
#   4. `opsys instance initialiser` : dossiers, base migree, secrets dans <etat du core>\.env (acces reserve a
#      l'utilisateur, jamais regeneres, jamais affiches), configuration du core, superviseur du moteur
#   5. verification que le core lit son etat la ou on vient de le preparer (`openclaw config file`), `openclaw
#      config validate`, puis service du Gateway (`openclaw gateway install` : tache planifiee de l'utilisateur),
#      qui supervise le moteur ; attente que le Gateway et le moteur repondent
#
# Le core tourne sous son profil "opsys" (PLAN T0.11-b) : toute commande du core passe `--profile opsys`, jamais
# OPENCLAW_STATE_DIR, OPENCLAW_CONFIG_PATH ni OPENCLAW_HOME. Son etat est alors le dossier canonique du profil
# (%USERPROFILE%\.openclaw-opsys), le seul pour lequel le core accepte d'installer un service, et le service porte
# un nom distinct de celui du core d'origine (tache "OpenClaw Gateway (opsys)"). `opsys instance dossier` donne ce
# dossier. Une installation faite avec l'ancienne disposition (%OPSYS_HOME%\core) est signalee, avec la marche a
# suivre, jamais migree en silence.
#
# Relancable sans rien casser : c'est aussi la mise a jour. Les donnees de l'instance ne sont jamais touchees.
#
# Options : -SansService  -Source <dossier>  -Ref <ref>  -Aide
# Variables : OPSYS_HOME (defaut %USERPROFILE%\.opsys), OPSYS_LOGICIEL (defaut %LOCALAPPDATA%\OPSYS),
#   OPSYS_BIN (defaut %LOCALAPPDATA%\OPSYS\bin), OPSYS_SOURCE, OPSYS_REPO_URL, OPSYS_REF, OPSYS_PORT_GATEWAY,
#   OPSYS_PORT_MOTEUR, OPSYS_EMBEDDINGS_URL, OPSYS_EMBEDDINGS_MODELE, OPSYS_EMBEDDINGS_CLE, OPSYS_PASSERELLE_URL,
#   OPSYS_VERBOSE=1
# Code de sortie : 0 tout est pret ; 1 une etape a echoue ; 3 installe mais il manque une decision (paliers de
# modeles, service d'embeddings) : le message dit quoi fournir, puis on relance la meme commande.
#
# Ce fichier est volontairement en ASCII pur (messages sans accents) : Windows PowerShell 5.1 lit un script UTF-8 sans
# BOM comme du texte ANSI, et un BOM casserait l'execution par `iex`. Il est lu par l'analyseur de PowerShell (job
# analyse) et joue sous Windows par le job installation-windows de la CI (tests/installateur/bout_en_bout.ps1) ; ce que ce
# job prouve, et ce qu'il ne prouve pas, est dit dans docs/exploitation/INSTALLATION.md (section 10).

[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$SansService,
    [string]$Source,
    [string]$Ref,
    [switch]$Aide
)

$ErrorActionPreference = 'Stop'
$script:CodeEnAttente = 3
$script:Marque = 'OPSYS-INSTALLATEUR : fichier gere par install.ps1, reecrit a chaque installation. Ne pas editer.'
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:OptSource = $Source
$script:OptRef = $Ref
$script:AvecService = -not $SansService
$script:Nettoyage = @()
$script:Secrets = @()
$script:Journal = ''
$script:Depot = ''
$script:DepotGere = 0
$script:DepotCommit = 'inconnu'
$script:Node = ''
$script:Pnpm = ''
$script:PnpmDir = ''
$script:ServiceInstalle = 0
$script:EnAttente = $false
# Profil du core et variables qui sortiraient son etat du dossier canonique (comme install.sh et instance.py).
$script:ProfilCore = 'opsys'
$script:VariablesEcartees = @('OPENCLAW_STATE_DIR', 'OPENCLAW_CONFIG_PATH', 'OPENCLAW_HOME', 'OPENCLAW_PROFILE', 'OPENCLAW_LAUNCHD_LABEL', 'OPENCLAW_SYSTEMD_UNIT', 'OPENCLAW_WINDOWS_TASK_NAME')
$script:DossierCore = ''
$script:BinAjoute = $false
$script:EnvAvant = $null

function Write-Info {
    param([string]$Message)
    Write-Host "[opsys] $Message"
}

function Write-Avert {
    param([string]$Message)
    Write-Host "[opsys] AVERTISSEMENT : $Message" -ForegroundColor Yellow
}

function Stop-Install {
    param([string]$Message)
    throw "ERREUR : $Message"
}

# Les variables d'environnement que ce script pose ou retire (CI=true pour pnpm, COREPACK_*, OPSYS_HOME, PYTHONUTF8, le
# PATH de pnpm, les OPENCLAW_* que Invoke-Noyau ecarte) sont celles du PROCESSUS de l'appelant : lance depuis une session
# interactive (`.\install.ps1`), le script les y laisserait (CI=true, PATH allonge a chaque appel de pnpm...). Elles sont
# rendues telles qu'elles etaient a la fin, sauf le dossier des commandes, ajoute au PATH pour qu'on s'en serve tout de suite.
$script:EnvTouchee = @('CI', 'COREPACK_ENABLE_DOWNLOAD_PROMPT', 'GIT_TERMINAL_PROMPT', 'OPSYS_HOME', 'OPSYS_NODE_VERSION_MJS', 'PYTHONUTF8') + $script:VariablesEcartees

function Save-Environnement {
    $script:EnvAvant = @{}
    foreach ($nom in ($script:EnvTouchee + @('Path'))) { $script:EnvAvant[$nom] = [Environment]::GetEnvironmentVariable($nom) }
}

function Restore-Environnement {
    if ($null -eq $script:EnvAvant) { return }
    foreach ($nom in $script:EnvTouchee) { [Environment]::SetEnvironmentVariable($nom, $script:EnvAvant[$nom]) }
    $chemin = [string]$script:EnvAvant['Path']
    if ($script:BinAjoute) { $chemin = "$chemin;$($script:Bin)" }
    [Environment]::SetEnvironmentVariable('Path', $chemin)
    $script:EnvAvant = $null
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

function Assert-Port {
    param([string]$Nom, [string]$Valeur)
    if ($Valeur -notmatch '^[0-9]+$' -or [int]$Valeur -lt 1 -or [int]$Valeur -gt 65535) {
        Stop-Install "$Nom : '$Valeur' n'est pas un numero de port (1 a 65535)."
    }
}

function Assert-CheminAbsolu {
    param([string]$Nom, [string]$Chemin)
    if (-not [System.IO.Path]::IsPathRooted($Chemin)) { Stop-Install "$Nom doit etre un chemin absolu (recu : $Chemin)." }
}

# -- Journal et masquage des secrets --------------------------------------------------------------------------------
function Update-Masque {
    $script:Secrets = @()
    if (-not $script:DossierCore) { return }
    $fichierEnv = Join-Path $script:DossierCore '.env'
    if (-not (Test-Path -LiteralPath $fichierEnv)) { return }
    foreach ($ligne in [System.IO.File]::ReadAllLines($fichierEnv, $script:Utf8)) {
        if ($ligne -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $nomVariable = $Matches[1]
            $valeurVariable = $Matches[2]
            if (($nomVariable -match 'JETON|TOKEN|_CLE|SECRET|PASSWORD') -and $valeurVariable.Length -ge 12) {
                $script:Secrets += $valeurVariable
            }
        }
    }
}

function Hide-Secrets {
    param([string]$Texte)
    foreach ($secret in $script:Secrets) { $Texte = $Texte.Replace($secret, '***') }
    return $Texte
}

function Add-Journal {
    param([string]$Texte)
    [System.IO.File]::AppendAllText($script:Journal, "$Texte`n", $script:Utf8)
}

function Open-Journal {
    $dossier = Join-Path $script:Logiciel 'journaux'
    New-Item -ItemType Directory -Force -Path $dossier | Out-Null
    $script:Journal = Join-Path $dossier 'installation.log'
    [System.IO.File]::WriteAllText($script:Journal, '', $script:Utf8)
    Update-Masque
}

# Lance une commande native sans que Windows PowerShell 5.1 ne traite son stderr comme une erreur fatale.
function Invoke-Capture {
    param([scriptblock]$Commande)
    $avant = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = 0
    try {
        $lignes = @(& $Commande 2>&1 | ForEach-Object { "$_" })
        $codeRetour = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $avant
    }
    return [pscustomobject]@{ Code = $codeRetour; Sortie = ($lignes -join "`n") }
}

function Invoke-Etape {
    param([string]$Libelle, [scriptblock]$Commande, [string]$Conseil = '')
    Write-Info "$Libelle..."
    Add-Journal "`n== $Libelle"
    $resultat = Invoke-Capture $Commande
    $texte = Hide-Secrets $resultat.Sortie
    if ($texte) { Add-Journal $texte }
    if ($env:OPSYS_VERBOSE -eq '1' -and $texte) { Write-Host $texte }
    if ($resultat.Code -ne 0) {
        if ($env:OPSYS_VERBOSE -ne '1' -and $texte) {
            $texte -split "`n" | Select-Object -Last 40 | ForEach-Object { Write-Host $_ }
        }
        Stop-Install "$Libelle : echec (code $($resultat.Code)). Journal complet : $($script:Journal). $Conseil"
    }
}

# -- Prerequis -----------------------------------------------------------------------------------------------------------
function Test-Prerequis {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Stop-Install "Node.js est introuvable. Installez Node 24.16+ ou 26.1+ (https://nodejs.org/), puis relancez cette commande."
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Stop-Install "uv est introuvable (il installe le moteur Python 3.11+). Installez-le (https://docs.astral.sh/uv/ : powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`"), puis relancez."
    }
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
        Stop-Install "curl.exe est introuvable (sondes de sante) : il est fourni avec Windows 10 (1803) et suivants."
    }
    $script:Node = (Get-Command node).Source
}

# Il n'y a plus de garde "ne jamais ecraser la tache d'une autre installation d'OpenClaw" : sous le profil "opsys", la
# tache porte un nom qui n'est pas celui du core d'origine ("OpenClaw Gateway (opsys)", core/src/daemon/constants.ts), et
# `gateway install --force` ne remplace que la tache de son profil.

# Le controle qui fait foi est celui du fork lui-meme (core/node-version.mjs), lu une fois le code en place.
function Test-VersionNode {
    $modeleJs = @'
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.env.OPSYS_NODE_VERSION_MJS).href);
process.exit(m.isSupportedOpenClawNodeVersion(process.versions.node) ? 0 : 1);
'@
    $fichierJs = Join-Path ([System.IO.Path]::GetTempPath()) ('opsys-node-' + [guid]::NewGuid().ToString('N') + '.mjs')
    [System.IO.File]::WriteAllText($fichierJs, $modeleJs, $script:Utf8)
    try {
        $env:OPSYS_NODE_VERSION_MJS = Join-Path $script:Depot 'core\node-version.mjs'
        $verdict = Invoke-Capture { & node $fichierJs }
        $version = (Invoke-Capture { & node -v }).Sortie.Trim()
    }
    finally {
        Remove-Item -LiteralPath $fichierJs -Force -ErrorAction SilentlyContinue
        Remove-Item Env:OPSYS_NODE_VERSION_MJS -ErrorAction SilentlyContinue
    }
    if ($verdict.Code -ne 0) {
        Stop-Install "Node $version n'est pas pris en charge par ce core : il faut Node 24.16+ (24.x) ou 26.1+. Changez de Node (https://nodejs.org/), puis relancez."
    }
}

# -- Le code ---------------------------------------------------------------------------------------------------------------
function Invoke-Git {
    param([string[]]$Arguments)
    $env:GIT_TERMINAL_PROMPT = '0'
    & git @Arguments
}

function Resolve-Ref {
    param([string]$Dossier, [string]$Reference)
    foreach ($candidat in @("origin/$Reference", "refs/tags/$Reference", $Reference)) {
        $r = Invoke-Capture { & git -C $Dossier rev-parse --verify --quiet "$candidat^{commit}" }
        if ($r.Code -eq 0 -and $r.Sortie.Trim()) { return $r.Sortie.Trim() }
    }
    return ''
}

function Sync-Depot {
    $depot = Join-Path $script:Logiciel 'source'
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Stop-Install "git est introuvable (necessaire pour telecharger OPSYS). Installez-le, ou clonez le depot vous-meme et lancez install\install.ps1 depuis ce depot."
    }
    if (Test-Path -LiteralPath (Join-Path $depot '.git')) {
        $etat = (Invoke-Capture { & git -C $depot status --porcelain }).Sortie.Trim()
        if ($etat) {
            Stop-Install "$depot a des modifications locales : rien n'est mis a jour. Annulez-les, ou installez depuis votre propre depot (OPSYS_SOURCE)."
        }
        Invoke-Etape "Recuperation de $($script:Ref)" { Invoke-Git @('-C', $depot, 'fetch', '--tags', '--prune', 'origin') }
    }
    else {
        if (Test-Path -LiteralPath $depot) { Stop-Install "$depot existe mais n'est pas un depot git : deplacez-le, puis relancez." }
        $temporaire = "$depot.installation-$PID"
        $script:Nettoyage += $temporaire
        Invoke-Etape "Telechargement d'OPSYS ($($script:RepoUrl))" { Invoke-Git @('clone', '--filter=blob:none', $script:RepoUrl, $temporaire) }
        Move-Item -LiteralPath $temporaire -Destination $depot
    }
    $commit = Resolve-Ref $depot $script:Ref
    if (-not $commit) { Stop-Install "la reference '$($script:Ref)' est introuvable dans $($script:RepoUrl) (branche, etiquette ou commit)." }
    Invoke-Etape "Positionnement sur $($script:Ref) ($($commit.Substring(0, 12)))" { Invoke-Git @('-C', $depot, 'checkout', '--quiet', '--detach', $commit) }
    $script:Depot = $depot
    $script:DepotGere = 1
}

function Initialize-Depot {
    if ($script:OptSource) {
        $candidat = $script:OptSource
        if (-not ((Test-Path -LiteralPath (Join-Path $candidat 'core\openclaw.mjs')) -and (Test-Path -LiteralPath (Join-Path $candidat 'pyproject.toml')))) {
            Stop-Install "$candidat n'est pas un depot OPSYS (core\openclaw.mjs et pyproject.toml attendus)."
        }
        $script:Depot = (Resolve-Path -LiteralPath $candidat).Path
    }
    elseif ($PSScriptRoot -and (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'core\openclaw.mjs')) -and (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'pyproject.toml'))) {
        $script:Depot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
        Write-Info "depot detecte : $($script:Depot) (utilise tel quel)"
    }
    else {
        Sync-Depot
    }
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $tete = (Invoke-Capture { & git -C $script:Depot rev-parse HEAD }).Sortie.Trim()
        if ($tete -match '^[0-9a-f]{40}$') { $script:DepotCommit = $tete }
    }
}

# -- Le core et le moteur -----------------------------------------------------------------------------------------------------
function Get-VersionPnpmDuCore {
    $paquet = Get-Content -Raw -LiteralPath (Join-Path $script:Depot 'core\package.json') | ConvertFrom-Json
    if ($paquet.packageManager -match '^pnpm@([^+]+)') { return $Matches[1] }
    return ''
}

function Get-VersionPnpm {
    param([string]$Exe)
    Push-Location (Join-Path $script:Depot 'core')
    try {
        $script:PnpmEssai = $Exe
        $r = Invoke-Capture { & $script:PnpmEssai --version }
    }
    finally {
        Pop-Location
    }
    if ($r.Code -ne 0) { return '' }
    $derniere = $r.Sortie -split "`n" | Select-Object -Last 1
    if (-not $derniere) { return '' }
    return $derniere.Trim()
}

function Initialize-Pnpm {
    $version = Get-VersionPnpmDuCore
    if (-not $version) { Stop-Install "core/package.json ne fixe pas la version de pnpm (champ packageManager) : depot inattendu." }
    $env:COREPACK_ENABLE_DOWNLOAD_PROMPT = '0'
    if ((Get-Command pnpm -ErrorAction SilentlyContinue) -and ((Get-VersionPnpm 'pnpm') -eq $version)) {
        $script:Pnpm = 'pnpm'
        Write-Info "pnpm $version pret (celui du systeme)"
        return
    }
    $dossier = Join-Path ([System.IO.Path]::GetTempPath()) ('opsys-pnpm-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $dossier | Out-Null
    $script:Nettoyage += $dossier
    if (Get-Command corepack -ErrorAction SilentlyContinue) {
        $r = Invoke-Capture { & corepack enable --install-directory $dossier pnpm }
        Add-Journal (Hide-Secrets $r.Sortie)
        $exe = Join-Path $dossier 'pnpm.cmd'
        if (($r.Code -eq 0) -and (Test-Path -LiteralPath $exe) -and ((Get-VersionPnpm $exe) -eq $version)) {
            $script:Pnpm = $exe
            $script:PnpmDir = $dossier
            Write-Info "pnpm $version pret (Corepack)"
            return
        }
    }
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        $prefixe = Join-Path $dossier 'npm'
        $r = Invoke-Capture { & npm install --global --prefix $prefixe "pnpm@$version" }
        Add-Journal (Hide-Secrets $r.Sortie)
        $exe = Join-Path $prefixe 'pnpm.cmd'
        if (($r.Code -eq 0) -and (Test-Path -LiteralPath $exe) -and ((Get-VersionPnpm $exe) -eq $version)) {
            $script:Pnpm = $exe
            $script:PnpmDir = $prefixe
            Write-Info "pnpm $version pret (npm)"
            return
        }
    }
    Stop-Install "impossible de disposer de pnpm $version (celui que fixe core/package.json). Installez Corepack ou npm avec Node, puis relancez. Journal : $($script:Journal)"
}

function Invoke-PnpmCore {
    param([string[]]$Arguments)
    Push-Location (Join-Path $script:Depot 'core')
    try {
        $env:CI = 'true'
        if ($script:PnpmDir) { $env:Path = "$($script:PnpmDir);$($env:Path)" }
        & $script:Pnpm @Arguments
    }
    finally {
        Pop-Location
    }
}

# Toute commande du core passe par ici, sous son profil : `--profile` est l'option racine qui projette le dossier d'etat
# et le fichier de configuration canoniques du profil (core/src/cli/profile.ts, applyCliProfileEnv) ; la seule variable
# OPENCLAW_PROFILE ne le fait pas. Les variables qui sortiraient l'etat de ce dossier sont ecartees : le core refuserait
# alors tout service (core/src/config/paths.ts, isDefaultInstallIdentity).
function Invoke-Noyau {
    param([string[]]$Arguments)
    $env:OPSYS_HOME = $script:OpsysHome
    foreach ($nom in $script:VariablesEcartees) { Remove-Item -LiteralPath "Env:$nom" -ErrorAction SilentlyContinue }
    & node (Join-Path $script:Depot 'core\openclaw.mjs') --profile $script:ProfilCore @Arguments
}

function Build-Core {
    Invoke-Etape "Installation des dependances du core (pnpm install)" { Invoke-PnpmCore @('install', '--frozen-lockfile') } -Conseil "Verifiez l'acces reseau (registre npm) et l'espace disque, puis relancez."
    Invoke-Etape "Construction du core (pnpm build, plusieurs minutes)" { Invoke-PnpmCore @('build') } -Conseil "Le journal donne la cause ; relancez apres correction."
    Invoke-Etape "Verification du core" { Invoke-Noyau @('--version') }
}

function Test-MoteurPython {
    if (-not (Test-Path -LiteralPath $script:VenvPy)) { return $false }
    $r = Invoke-Capture { & $script:VenvPy -c 'import sys; sys.exit(sys.version_info < (3, 11))' }
    return ($r.Code -eq 0)
}

# Extras d'execution du moteur (pyproject.toml) : sans eux, la cedule par tournees de M4 (PyVRP) et la soumission
# en PDF de M3 (ReportLab) echouent fermees. `postgres` et `console` restent a Docker Compose, `dev` aux contributeurs.
$script:ExtrasMoteur = 'tournees,soumission'

function Install-Moteur {
    if (-not (Test-MoteurPython)) {
        Invoke-Etape "Creation de l'environnement Python (uv venv)" { & uv venv --clear --python '>=3.11' $script:Venv } -Conseil "Il faut Python 3.11 ou plus : installez-le, ou laissez uv le telecharger (acces reseau)."
    }
    Invoke-Etape "Installation du moteur metier (uv pip install)" { & uv pip install --python $script:VenvPy --editable "$($script:Depot)[$($script:ExtrasMoteur)]" } -Conseil "Verifiez l'acces reseau (PyPI), puis relancez."
}

# -- L'instance -----------------------------------------------------------------------------------------------------------------
# Le dossier d'etat du core est celui que le moteur Python calcule (instance.dossier_core : la regle du fork, une seule
# implementation pour Linux, macOS et Windows). Le script ne le devine pas ; Test-DossierDuCore le confronte ensuite a la
# reponse du core lui-meme.
function Initialize-DossierCore {
    $env:OPSYS_HOME = $script:OpsysHome
    $env:PYTHONUTF8 = '1'
    $r = Invoke-Capture { & $script:VenvPy -m opsys.cli instance dossier }
    $chemin = ''
    $lignes = @($r.Sortie -split "`n" | Where-Object { $_.Trim() })
    if ($lignes.Count -gt 0) { $chemin = "$($lignes[-1])".Trim() }
    if (($r.Code -ne 0) -or (-not $chemin)) {
        Stop-Install "le dossier d'etat du core est indetermine : $($r.Sortie) (USERPROFILE est-il defini ?)"
    }
    Assert-CheminAbsolu "le dossier d'etat du core" $chemin
    $script:DossierCore = $chemin
    Update-Masque
}

# Le dossier que l'installateur a prepare doit etre celui que le core lira : le core dit lui-meme ou est sa configuration
# (`openclaw config file`). Si la regle de profil du fork change, on s'arrete ici, avant de demarrer un Gateway qui
# ignorerait la configuration generee.
function Test-DossierDuCore {
    Write-Info "Verification du dossier d'etat du core (openclaw config file)..."
    $r = Invoke-Capture { Invoke-Noyau @('config', 'file') }
    Add-Journal "`n== openclaw config file (code $($r.Code))`n$(Hide-Secrets $r.Sortie)"
    if ($r.Code -ne 0) { Stop-Install "openclaw config file a echoue (code $($r.Code)). Journal complet : $($script:Journal)" }
    $annonce = ''
    $lignes = @($r.Sortie -split "`n" | Where-Object { $_.Trim() })
    if ($lignes.Count -gt 0) { $annonce = "$($lignes[-1])".Trim() }
    $attendu = Join-Path $script:DossierCore 'openclaw.json'
    if (-not [string]::Equals($annonce, $attendu, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-Install "le core cherche sa configuration dans '$annonce', mais l'installateur a prepare '$attendu'. La regle du profil '$($script:ProfilCore)' a change dans le core (core/src/cli/profile-utils.ts) : rien n'est demarre. Journal : $($script:Journal)"
    }
}

function Initialize-Instance {
    $arguments = @('-m', 'opsys.cli', 'instance', 'initialiser', '--source', $script:Depot)
    if ($script:PortGateway) { $arguments += @('--port-gateway', $script:PortGateway) }
    if ($script:PortMoteur) { $arguments += @('--port-moteur', $script:PortMoteur) }
    $fichierErreurs = [System.IO.Path]::GetTempFileName()
    $script:Nettoyage += $fichierErreurs
    Write-Info "Initialisation de l'instance ($($script:OpsysHome))..."
    $env:OPSYS_HOME = $script:OpsysHome
    $env:PYTHONUTF8 = '1'
    $avant = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = 0
    try {
        $sortie = (& $script:VenvPy @arguments 2>$fichierErreurs | Out-String)
        $codeRetour = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $avant
    }
    Update-Masque
    $erreurs = Hide-Secrets ([System.IO.File]::ReadAllText($fichierErreurs))
    Add-Journal "`n== opsys instance initialiser (code $codeRetour)`n$erreurs`n$(Hide-Secrets $sortie)"
    if ($erreurs.Trim()) { Write-Host $erreurs.TrimEnd() }
    if ($codeRetour -eq $script:CodeEnAttente) { $script:EnAttente = $true }
    elseif ($codeRetour -ne 0) { Stop-Install "l'initialisation de l'instance a echoue (code $codeRetour) : voir ci-dessus. Journal : $($script:Journal)" }
    $verdict = $sortie | ConvertFrom-Json
    $script:PortGateway = [string]$verdict.port_gateway
    $script:PortMoteur = [string]$verdict.port_moteur
}

# -- Commandes openclaw (core) et opsys (moteur) ---------------------------------------------------------------------------------
function Assert-CheminCmd {
    param([string]$Chemin)
    if ($Chemin -match '[%"]') { Stop-Install "le chemin '$Chemin' contient % ou un guillemet : choisissez un autre dossier (OPSYS_HOME, OPSYS_LOGICIEL, OPSYS_BIN)." }
}

function Write-Enveloppe {
    param([string]$Cible, [string[]]$Lignes)
    if ((Test-Path -LiteralPath $Cible) -and -not (Select-String -LiteralPath $Cible -SimpleMatch -Pattern $script:Marque -Quiet)) {
        Stop-Install "$Cible existe deja et n'a pas ete installe par OPSYS : deplacez-le, ou choisissez un autre dossier (OPSYS_BIN)."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Cible) | Out-Null
    try { $encodage = [System.Text.Encoding]::GetEncoding([System.Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage) }
    catch { $encodage = $script:Utf8 }
    [System.IO.File]::WriteAllText($Cible, (($Lignes -join "`r`n") + "`r`n"), $encodage)
}

function Install-Commandes {
    foreach ($chemin in @($script:OpsysHome, $script:DossierCore, $script:Node, $script:Depot, $script:VenvPy)) { Assert-CheminCmd $chemin }
    # Le core d'OPSYS tourne sous son profil ; `setlocal` garde le retrait des variables hors de la session de l'appelant.
    $lignesCore = @('@echo off', "rem $($script:Marque)", 'setlocal', "if not defined OPSYS_HOME set `"OPSYS_HOME=$($script:OpsysHome)`"")
    foreach ($nom in $script:VariablesEcartees) { $lignesCore += "set `"$nom=`"" }
    $lignesCore += "`"$($script:Node)`" `"$($script:Depot)\core\openclaw.mjs`" --profile $($script:ProfilCore) %*"
    $lignesCore += 'exit /b %ERRORLEVEL%'
    Write-Enveloppe (Join-Path $script:Bin 'openclaw.cmd') $lignesCore
    # `setlocal` : sans lui, les secrets de .env lus ci-dessous resteraient dans l'environnement du cmd.exe de l'appelant.
    Write-Enveloppe (Join-Path $script:Bin 'opsys.cmd') @(
        '@echo off',
        "rem $($script:Marque)",
        'setlocal',
        "if not defined OPSYS_HOME set `"OPSYS_HOME=$($script:OpsysHome)`"",
        "set `"DOSSIER_CORE=$($script:DossierCore)`"",
        'rem Python ecrit sa sortie en UTF-8 meme redirigee (sinon, en cp1252, un caractere comme la fleche fait echouer print).',
        'set "PYTHONUTF8=1"',
        'if exist "%DOSSIER_CORE%\.env" (',
        '  for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%DOSSIER_CORE%\.env") do (',
        '    if not defined %%a set "%%a=%%b"',
        '  )',
        ')',
        "`"$($script:VenvPy)`" -m opsys.cli %*",
        'exit /b %ERRORLEVEL%')
    Write-Info "commandes installees : $($script:Bin)\openclaw.cmd et opsys.cmd"
    $cheminUtilisateur = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $cheminUtilisateur) { $cheminUtilisateur = '' }
    if (-not (($cheminUtilisateur -split ';') -contains $script:Bin)) {
        [Environment]::SetEnvironmentVariable('Path', (($cheminUtilisateur.TrimEnd(';') + ';' + $script:Bin).TrimStart(';')), 'User')
        $script:BinAjoute = $true
        $env:Path = "$($env:Path);$($script:Bin)"
        Write-Info "$($script:Bin) ajoute au PATH de l'utilisateur (ouvrez un nouveau terminal pour en profiter)."
    }
}

# -- Configuration valide, service, sante ---------------------------------------------------------------------------------------------
function Wait-Http {
    param([string]$Url, [int]$Delai)
    $ecoule = 0
    while ($ecoule -lt $Delai) {
        $r = Invoke-Capture { & curl.exe -fsS --noproxy '*' --max-time 3 -o NUL $Url }
        if ($r.Code -eq 0) { return $true }
        Start-Sleep -Seconds 2
        $ecoule += 2
    }
    return $false
}

function Install-Service {
    Invoke-Etape "Installation du service du Gateway (utilisateur)" { Invoke-Noyau @('gateway', 'install', '--force', '--port', $script:PortGateway) } -Conseil "Si la tache planifiee ne peut pas etre creee ici, relancez avec -SansService et demarrez le Gateway a la main : openclaw gateway run."
    Write-Info "attente du Gateway (port $($script:PortGateway)) et du moteur (port $($script:PortMoteur))..."
    if (-not (Wait-Http "http://127.0.0.1:$($script:PortGateway)/startupz" 240)) {
        Stop-Install "le Gateway ne repond pas sur le port $($script:PortGateway) apres 240 s. Voir : openclaw gateway status --deep ; openclaw logs"
    }
    if (-not (Wait-Http "http://127.0.0.1:$($script:PortMoteur)/sante" 240)) {
        Stop-Install "le moteur ne repond pas sur le port $($script:PortMoteur) apres 240 s (le Gateway le lance). Voir : openclaw gateway status --deep ; openclaw logs"
    }
    $script:ServiceInstalle = 1
    Write-Info "Gateway et moteur repondent."
}

function Write-Enregistrement {
    $lignes = @(
        "OPSYS_HOME=$($script:OpsysHome)",
        "OPSYS_BIN=$($script:Bin)",
        "PROFIL_CORE=$($script:ProfilCore)",
        "DOSSIER_CORE=$($script:DossierCore)",
        "SOURCE=$($script:Depot)",
        "SOURCE_GEREE=$($script:DepotGere)",
        "SOURCE_COMMIT=$($script:DepotCommit)",
        "PORT_GATEWAY=$($script:PortGateway)",
        "PORT_MOTEUR=$($script:PortMoteur)",
        "SERVICE=$($script:ServiceInstalle)",
        "INSTALLE_LE=$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))")
    [System.IO.File]::WriteAllText((Join-Path $script:Logiciel 'installation.env'), (($lignes -join "`n") + "`n"), $script:Utf8)
}

function Write-Bilan {
    Write-Host ''
    if ($script:EnAttente) {
        Write-Host "OPSYS est installe, mais l'instance n'est pas prete : il manque les decisions listees ci-dessus."
        Write-Host "Ce n'est pas une erreur d'installation. Fournissez-les, puis relancez la meme commande (rien n'est refait inutilement)."
    }
    else {
        Write-Host 'OPSYS est installe.'
    }
    Write-Host "  Donnees de l'instance : $($script:OpsysHome)  (jamais supprimees par la desinstallation)"
    Write-Host "  Etat du core          : $($script:DossierCore)  (profil $($script:ProfilCore) ; jamais supprime par la desinstallation)"
    Write-Host "  Reglages et secrets   : $($script:DossierCore)\.env  (acces reserve a l'utilisateur ; ne jamais partager)"
    Write-Host "  Logiciel              : $($script:Logiciel)  (commit $($script:DepotCommit.Substring(0, [Math]::Min(12, $script:DepotCommit.Length))))"
    Write-Host "  Commandes             : $($script:Bin)\openclaw.cmd (core), $($script:Bin)\opsys.cmd (moteur)"
    if (-not $script:EnAttente) {
        Write-Host "  Gateway               : http://127.0.0.1:$($script:PortGateway)  (moteur : 127.0.0.1:$($script:PortMoteur))"
        Write-Host "  Passerelle de modeles : non installee par ce script : attendue a l'adresse OPSYS_PASSERELLE_URL de .env"
        if ($script:ServiceInstalle -eq 1) { Write-Host "  Service               : installe (tache planifiee de l'utilisateur, profil $($script:ProfilCore)) ; etat : openclaw gateway status" }
        else { Write-Host '  Service               : non installe (-SansService) ; demarrage : openclaw gateway run' }
        Write-Host ''
        Write-Host 'Prochaines etapes :'
        Write-Host '  1. Creer le proprietaire : opsys personnes creer <identifiant> --nom "<Nom>" --role nathan_owner'
        Write-Host '  2. Appairer l''app mobile : openclaw qr, puis openclaw devices approve <demande>'
        Write-Host '  3. Sauvegarder : opsys instance exporter --sortie <fichier.tar.gz>'
    }
    Write-Host "  Journal de cette installation : $($script:Journal)"
}

function Invoke-Installation {
    if ($Aide) {
        Write-Host "install.ps1 : installe OPSYS (OPSYS-CORE + moteur metier) sur Windows."
        Write-Host "Options : -SansService  -Source <dossier>  -Ref <ref>  -Aide"
        Write-Host "Variables : OPSYS_HOME, OPSYS_LOGICIEL, OPSYS_BIN, OPSYS_SOURCE, OPSYS_REPO_URL, OPSYS_REF, OPSYS_PORT_GATEWAY,"
        Write-Host "  OPSYS_PORT_MOTEUR, OPSYS_EMBEDDINGS_URL, OPSYS_EMBEDDINGS_MODELE, OPSYS_EMBEDDINGS_CLE, OPSYS_PASSERELLE_URL, OPSYS_VERBOSE"
        Write-Host "Code de sortie : 0 pret, 1 echec d'une etape, 3 installe mais il manque une decision."
        return 0
    }
    $encodageConsole = $null
    Save-Environnement
    try {
        try { $encodageConsole = [Console]::OutputEncoding; [Console]::OutputEncoding = $script:Utf8 } catch { $encodageConsole = $null }
        $script:OpsysHome = Get-Reglage 'OPSYS_HOME' (Join-Path $env:USERPROFILE '.opsys')
        $script:Logiciel = Get-Reglage 'OPSYS_LOGICIEL' (Join-Path $env:LOCALAPPDATA 'OPSYS')
        $script:Bin = Get-Reglage 'OPSYS_BIN' (Join-Path $env:LOCALAPPDATA 'OPSYS\bin')
        Assert-CheminAbsolu 'OPSYS_HOME' $script:OpsysHome
        Assert-CheminAbsolu 'OPSYS_LOGICIEL' $script:Logiciel
        Assert-CheminAbsolu 'OPSYS_BIN' $script:Bin
        if (-not $script:OptSource) { $script:OptSource = Get-Reglage 'OPSYS_SOURCE' '' }
        if (-not $script:OptRef) { $script:OptRef = Get-Reglage 'OPSYS_REF' 'main' }
        $script:Ref = $script:OptRef
        $script:RepoUrl = Get-Reglage 'OPSYS_REPO_URL' 'https://github.com/leon36000/OPSYS-AI.git'
        $script:Venv = Join-Path $script:Logiciel 'venv'
        $script:VenvPy = Join-Path $script:Venv 'Scripts\python.exe'
        $enregistre = Read-Enregistrement (Join-Path $script:Logiciel 'installation.env')
        $script:PortGateway = Get-Reglage 'OPSYS_PORT_GATEWAY' ([string]$enregistre['PORT_GATEWAY'])
        $script:PortMoteur = Get-Reglage 'OPSYS_PORT_MOTEUR' ([string]$enregistre['PORT_MOTEUR'])
        if ($script:PortGateway) { Assert-Port 'OPSYS_PORT_GATEWAY' $script:PortGateway }
        if ($script:PortMoteur) { Assert-Port 'OPSYS_PORT_MOTEUR' $script:PortMoteur }

        # Le dossier d'etat note par la derniere installation ne sert qu'a masquer ses secrets des l'ouverture du journal :
        # il est redetermine (par le moteur Python) avant toute ecriture.
        $script:DossierCore = [string]$enregistre['DOSSIER_CORE']
        Test-Prerequis
        Open-Journal
        Write-Info "OPSYS : installation (journal : $($script:Journal))"
        Initialize-Depot
        Test-VersionNode
        Initialize-Pnpm
        Build-Core
        Install-Moteur
        Initialize-DossierCore
        Initialize-Instance
        Test-DossierDuCore
        Install-Commandes
        if (-not $script:EnAttente) {
            Invoke-Etape "Validation de la configuration par le core (openclaw config validate)" { Invoke-Noyau @('config', 'validate') }
            if ($script:AvecService) { Install-Service }
        }
        Write-Enregistrement
        Write-Bilan
        if ($script:EnAttente) { return $script:CodeEnAttente }
        return 0
    }
    catch {
        Write-Host "[opsys] $($_.Exception.Message)" -ForegroundColor Red
        return 1
    }
    finally {
        foreach ($chemin in $script:Nettoyage) { Remove-Item -LiteralPath $chemin -Recurse -Force -ErrorAction SilentlyContinue }
        Restore-Environnement
        if ($null -ne $encodageConsole) { try { [Console]::OutputEncoding = $encodageConsole } catch { $null = $_ } }
    }
}

# La derniere valeur rendue est le code de sortie, meme si une etape avait laisse une sortie perdue dans le flux.
$resultatInstallation = @(Invoke-Installation)
$codeSortie = [int]$resultatInstallation[-1]
$global:LASTEXITCODE = $codeSortie
if ($PSCommandPath) { exit $codeSortie }
