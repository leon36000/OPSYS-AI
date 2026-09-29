# tests/installateur/bout_en_bout.ps1 : preuve de l'installateur Windows avec le VRAI core (PLAN T0.11-d), pour la CI.
#
# C'est le pendant de bout_en_bout.sh (Linux, macOS) : install.ps1 construit le core, installe le moteur par uv, le
# Gateway demarre et lance le moteur, l'export est coherent, le service (tache planifiee de l'utilisateur) tourne, et
# uninstall.ps1 retire le logiciel sans perdre une donnee. Chaque constat faux arrete le script, avec quoi regarder.
#
# Ce que le core fait sous Windows (core/src/daemon/schtasks-*.ts, lu sans etre execute) et que ce script confronte :
#   - `gateway install` cree la tache planifiee "OpenClaw Gateway (opsys)" POUR L'UTILISATEUR COURANT : declencheur a
#     l'ouverture de session, ouverture de session interactive, niveau d'execution LeastPrivilege. Aucun droit
#     d'administrateur n'est demande par ce dessin. Si `schtasks /Create` est refuse (acces refuse, delai), le core se
#     replie sur une entree du dossier Demarrage de l'utilisateur ; le script le DIT (avertissement et resume) ;
#   - la tache lance <etat du core>\gateway.cmd, qui pose l'environnement du service (profil opsys, dossier d'etat) ET les
#     valeurs de .env : l'environnement durable du service est ecrit tel quel dans ce script (core/src/commands/
#     daemon-install-helpers.ts ; core/src/daemon/schtasks-layout.ts, buildTaskScript). Ce script porte donc des secrets,
#     et sous Windows le core ne lui donne pas d'ACL propre : sa seule protection est celle du dossier d'etat, que
#     l'installateur reserve a l'utilisateur (icacls, instance.py, restreindre_dossier) ; le script de preuve le verifie ;
#   - `gateway uninstall` arrete le Gateway (arbre de processus), supprime la tache, l'entree de demarrage et le
#     script ;
#   - le dossier d'etat est %USERPROFILE%\.openclaw-opsys (profil opsys), reserve a l'utilisateur par une ACL sans
#     heritage que les fichiers du service heritent ; .env et l'archive d'export ont en plus leur propre ACL.
# Une seule commande (PLAN T0.7 lot 2) : `opsys` est le core (`openclaw` son alias), `opsys metier <commande>` lance le
# moteur Python par le core (core/src/cli/opsys-metier-cli.ts, d'apres `opsys\metier.json`), `opsys-metier` est le moteur
# seul, et l'ancienne forme (`opsys instance dossier`) dit la nouvelle sans rien executer. Tout cela est eprouve ici, avec
# le vrai core, sous Windows (PYTHONUTF8 pose par le core, chemins et arguments par `spawnSync`, sans shell).
# Ce script INSTALLE puis DESINSTALLE : il refuse de tourner sur un poste qui a deja un etat du core d'OPSYS ou sa tache
# (ne l'executez pas sur un poste reel ; la CI l'execute sur une machine neuve).
#
# Deux interpreteurs : l'installateur est joue par l'interpreteur de ce script (pwsh en CI) pour l'installation, le
# service et la desinstallation, puis par Windows PowerShell 5.1 (powershell.exe, celui que la plupart des utilisateurs
# ouvrent) pour la relance et la seconde desinstallation. Sans powershell.exe, le meme interpreteur sert partout et le
# resume le dit.
#
# Limite assumee : un arret GRACIEUX du Gateway n'est pas eprouve ici. Windows n'a pas de SIGTERM ; l'arret au premier
# plan est celui de l'arbre de processus (taskkill /T /F). Le retrait de la tache par le core arrete lui aussi l'arbre.
#
# Sortie : sous GitHub Actions, chaque etape est un groupe repliable (::group::) ; un echec ferme le groupe, imprime la
# cause, la pose en annotation (::error::) et dans le resume du job. Les valeurs secretes de .env sont declarees au
# masque de GitHub (::add-mask::) des qu'elles existent.
#
# Usage (depuis la racine du depot, Node 24+, Python 3.11+, uv, sur Windows) :
#   pwsh -File tests/installateur/bout_en_bout.ps1
# Variables : OPSYS_TRAVAIL (dossier de travail, defaut : un dossier temporaire), OPSYS_SANS_SERVICE=1 (saute la phase
# du service), OPSYS_SERVICE_REQUIS=1 (l'echec du service est un echec du script), OPSYS_PORT_GATEWAY et
# OPSYS_PORT_MOTEUR (defauts 18789 et 8765, comme l'installateur).
#
# Ce fichier est en ASCII pur, sans BOM (comme install.ps1) : pas d'accents, meme dans les messages.

[CmdletBinding(PositionalBinding = $false)]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$global:LASTEXITCODE = 0

$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:Latin1 = [System.Text.Encoding]::GetEncoding('iso-8859-1')
$script:EAigu = [string][char]0x00E9  # le "e" accentue des messages de Python (le script reste ASCII)
$script:Constats = New-Object System.Collections.Generic.List[string]
$script:EtapeCourante = 'preparation'
$script:GroupeOuvert = $false
$script:Secrets = @()
$script:GatewayProc = $null
$script:ServiceProuve = 'non'
$script:ModeService = 'aucun'
$script:PythonSysteme = ''

function Get-Reglage {
    param([string]$Nom, [string]$Defaut)
    $valeur = [Environment]::GetEnvironmentVariable($Nom)
    if ([string]::IsNullOrWhiteSpace($valeur)) { return $Defaut }
    return $valeur
}

$script:EnActions = -not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('GITHUB_ACTIONS'))
$script:Racine = (Resolve-Path -LiteralPath (Join-Path (Join-Path $PSScriptRoot '..') '..')).Path
$script:Travail = Get-Reglage 'OPSYS_TRAVAIL' (Join-Path ([System.IO.Path]::GetTempPath()) ('opsys-preuve-' + [guid]::NewGuid().ToString('N')))
$null = New-Item -ItemType Directory -Force -Path $script:Travail
$script:Travail = (Resolve-Path -LiteralPath $script:Travail).Path
$script:PortGateway = [int](Get-Reglage 'OPSYS_PORT_GATEWAY' '18789')
$script:PortMoteur = [int](Get-Reglage 'OPSYS_PORT_MOTEUR' '8765')
$script:NomTache = 'OpenClaw Gateway (opsys)'
$script:NomTacheOrigine = 'OpenClaw Gateway'
# Le dossier personnel se lit comme le fait le core (HOME, puis USERPROFILE) : core/packages/normalization-core/src/home-dir.ts
$script:Personnel = Get-Reglage 'HOME' ([Environment]::GetEnvironmentVariable('USERPROFILE'))
$script:EtatCore = Join-Path $script:Personnel '.openclaw-opsys'
$script:OpsysHome = Join-Path $script:Travail 'instance'
$script:Logiciel = Join-Path $script:Travail 'logiciel'
$script:Bin = Join-Path $script:Travail 'commandes'
$script:HotePrincipal = (Get-Process -Id $PID).Path
$commandeCinq = Get-Command 'powershell.exe' -ErrorAction SilentlyContinue
if ($commandeCinq) { $script:HoteSecondaire = $commandeCinq.Source } else { $script:HoteSecondaire = $script:HotePrincipal }

# Les decisions que l'installateur n'invente pas : un palier de modeles, un service d'embeddings et une passerelle de
# modeles. Aucun n'existe en CI : ce sont des adresses fermees, seul le demarrage est eprouve.
$env:OPSYS_HOME = $script:OpsysHome
$env:OPSYS_LOGICIEL = $script:Logiciel
$env:OPSYS_BIN = $script:Bin
$env:OPSYS_SOURCE = $script:Racine
$env:OPSYS_PORT_GATEWAY = [string]$script:PortGateway
$env:OPSYS_PORT_MOTEUR = [string]$script:PortMoteur
$env:OPSYS_EMBEDDINGS_URL = 'http://127.0.0.1:9/v1'
$env:OPSYS_EMBEDDINGS_MODELE = 'bge-m3'
$env:OPSYS_PASSERELLE_URL = 'http://127.0.0.1:9/v1'
$env:NO_PROXY = '127.0.0.1,localhost'
$env:no_proxy = '127.0.0.1,localhost'
$env:PYTHONUTF8 = '1'
$env:Path = "$($script:Bin);$($env:Path)"
try { [Console]::OutputEncoding = $script:Utf8 } catch { $null = $_ }

# -- Sortie : etapes, constats, echec ------------------------------------------------------------------------------------
function Close-Groupe {
    if ($script:GroupeOuvert) {
        Write-Host '::endgroup::'
        $script:GroupeOuvert = $false
    }
}

function Write-Etape {
    param([string]$Titre)
    $script:EtapeCourante = $Titre
    if ($script:EnActions) {
        Close-Groupe
        Write-Host "::group::$Titre"
        $script:GroupeOuvert = $true
    }
    Write-Host ''
    Write-Host "== $Titre"
}

function Add-Constat {
    param([string]$Texte)
    $script:Constats.Add($Texte)
    Write-Host "OK  $Texte"
}

function Write-Avertissement {
    param([string]$Texte)
    if ($script:EnActions) { Write-Host "::warning::$Texte" } else { Write-Host "AVERTISSEMENT : $Texte" }
}

# Un constat faux : le message part dans l'exception ; le point d'entree ferme le groupe et l'annonce.
function Stop-Preuve {
    param([string]$Message)
    $script:EchecPrevu = $true
    throw $Message
}
$script:EchecPrevu = $false

function ConvertTo-Annotation {
    param([string]$Texte)
    return $Texte.Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
}

function Write-Echec {
    param([string]$Message, [string]$Trace = '')
    if (Test-Path -LiteralPath (Join-Path $script:EtatCore '.env')) { Publish-Masque }
    Close-Groupe
    [Console]::Error.WriteLine("ECHEC : $Message")
    if ($Trace) { [Console]::Error.WriteLine($Trace) }
    $numero = ($script:EtapeCourante -split '\.')[0]
    if ($script:EnActions) {
        Write-Host ("::error title=Installateur Windows - etape $numero::" + (ConvertTo-Annotation $Message))
    }
    $resume = [Environment]::GetEnvironmentVariable('GITHUB_STEP_SUMMARY')
    if ($resume) {
        [System.IO.File]::AppendAllText($resume, "### Installateur (Windows) : ECHEC a l'etape '$($script:EtapeCourante)'`n`n$Message`n", $script:Utf8)
    }
}

# -- Secrets ---------------------------------------------------------------------------------------------------------------
function Get-ValeursSecretes {
    $fichier = Join-Path $script:EtatCore '.env'
    if (-not (Test-Path -LiteralPath $fichier)) { return @() }
    $valeurs = @()
    foreach ($ligne in [System.IO.File]::ReadAllLines($fichier, $script:Utf8)) {
        if ($ligne -match '^\s*(?:export\s+)?[A-Z0-9_]*(?:JETON|TOKEN|_CLE|SECRET|PASSWORD)[A-Z0-9_]*=(.{12,})$') { $valeurs += $Matches[1] }
    }
    return $valeurs
}

function Publish-Masque {
    $script:Secrets = @(Get-ValeursSecretes)
    foreach ($valeur in $script:Secrets) { Write-Host "::add-mask::$valeur" }
}

function Hide-Secrets {
    param([string]$Texte)
    foreach ($valeur in $script:Secrets) { $Texte = $Texte.Replace($valeur, '***') }
    return $Texte
}

# Les octets d'un fichier, meme si un processus l'a ouvert en ecriture (journal d'un service qui tourne).
function Read-Octets {
    param([string]$Chemin)
    $flux = [System.IO.File]::Open($Chemin, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $memoire = New-Object System.IO.MemoryStream
        $flux.CopyTo($memoire)
        return $memoire.ToArray()
    }
    finally { $flux.Dispose() }
}

function Test-Contient {
    param([string]$Chemin, [string]$Valeur)
    if (-not (Test-Path -LiteralPath $Chemin -PathType Leaf)) { return $false }
    return $script:Latin1.GetString((Read-Octets $Chemin)).Contains($Valeur)
}

function Assert-SansSecret {
    param([string]$Libelle, [string[]]$Fichiers)
    foreach ($valeur in (Get-ValeursSecretes)) {
        foreach ($fichier in $Fichiers) {
            if (Test-Contient $fichier $valeur) { Stop-Preuve "${Libelle} : un secret de .env apparait dans $fichier" }
        }
    }
}

# Un fichier ou un dossier qui porte des secrets (ou l'archive d'export) n'est accessible qu'a l'utilisateur. Avec
# -SansHeritage, l'ACL est en plus propre au chemin (icacls /inheritance:r /grant:r, src/opsys/instance.py) : .env,
# l'archive d'export et le dossier d'etat ; gateway.cmd, lui, herite de ce dossier.
# Seuls restent admis, comme root sous Unix derriere un 0700, les comptes que Windows garde sur tout dossier prive et
# que la politique du core tient deja pour surs (core/src/snapshot/local-repository-directory-policy.ts) : LocalSystem
# (S-1-5-18), les Administrateurs (S-1-5-32-544) et OWNER RIGHTS (S-1-3-4), qui designe le proprietaire du chemin,
# lui-meme verifie (l'utilisateur, ou les Administrateurs quand le compte en est membre). Compares par SID : les noms
# changent avec la langue du poste. Tout autre compte (Users, Authenticated Users, Everyone...) est un echec.
$script:SidsSysteme = @('S-1-5-18', 'S-1-5-32-544', 'S-1-3-4')

function Get-NomDuSid {
    param([string]$Sid)
    try { return ([System.Security.Principal.SecurityIdentifier]::new($Sid)).Translate([System.Security.Principal.NTAccount]).Value }
    catch { return $Sid }
}

function Assert-AclPrivee {
    param([string]$Chemin, [string]$Libelle, [switch]$SansHeritage)
    $acl = Get-Acl -LiteralPath $Chemin
    if ($SansHeritage -and (-not $acl.AreAccessRulesProtected)) {
        Stop-Preuve "$Libelle herite des droits de son dossier : l'ACL n'est pas reservee a l'utilisateur ($Chemin)"
    }
    $sidUtilisateur = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $proprietaire = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
    if ($proprietaire -ne $sidUtilisateur -and $proprietaire -notin @('S-1-5-18', 'S-1-5-32-544')) {
        Stop-Preuve "$Libelle appartient a un autre compte : $(Get-NomDuSid $proprietaire) ($Chemin)"
    }
    $regles = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
    $autres = @($regles | Where-Object { $_.IdentityReference.Value -ne $sidUtilisateur -and $script:SidsSysteme -notcontains $_.IdentityReference.Value })
    if ($autres.Count -gt 0) {
        Stop-Preuve "$Libelle est accessible a d'autres comptes : $((($autres | ForEach-Object { Get-NomDuSid $_.IdentityReference.Value }) -join ', ')) ($Chemin)"
    }
    if (@($regles | Where-Object { $_.IdentityReference.Value -eq $sidUtilisateur }).Count -eq 0) {
        Stop-Preuve "$Libelle n'a aucune entree d'ACL pour l'utilisateur ($Chemin)"
    }
}

# -- Empreintes ------------------------------------------------------------------------------------------------------------
function Get-Empreinte {
    param([string]$Chemin)
    return (Get-FileHash -LiteralPath $Chemin -Algorithm SHA256).Hash.ToLowerInvariant()
}

# Les fichiers que l'installateur ecrit ou garde : secrets, configuration du core, fragments OPSYS, reglages. Pas l'etat
# que le Gateway ecrit lui-meme (sessions, espaces de travail des agents).
function Get-EmpreinteDesFichiersGeres {
    $fichiers = @((Join-Path $script:EtatCore '.env'), (Join-Path $script:EtatCore 'openclaw.json'), (Join-Path $script:OpsysHome 'paliers.yaml'))
    $dossier = Join-Path $script:EtatCore 'opsys'
    if (Test-Path -LiteralPath $dossier) { $fichiers += @(Get-ChildItem -LiteralPath $dossier -Filter '*.json' -File | ForEach-Object { $_.FullName }) }
    $lignes = @($fichiers | ForEach-Object { (Get-Empreinte $_) } | Sort-Object)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    return -join ($sha.ComputeHash($script:Utf8.GetBytes($lignes -join "`n")) | ForEach-Object { $_.ToString('x2') })
}

# -- Commandes natives ------------------------------------------------------------------------------------------------------
# Lance une commande native sans que Windows PowerShell 5.1 ne traite son stderr comme une erreur fatale.
function Invoke-Natif {
    param([scriptblock]$Commande)
    $avant = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = 0
    try {
        $lignes = @(& $Commande 2>&1 | ForEach-Object { "$_" })
        $codeRetour = $global:LASTEXITCODE
    }
    finally { $ErrorActionPreference = $avant }
    return [pscustomobject]@{ Code = $codeRetour; Sortie = ($lignes -join "`n") }
}

# `opsys` : le core (PLAN T0.7 lot 2).
function Invoke-Opsys {
    param([string[]]$Arguments)
    return Invoke-Natif { & (Join-Path $script:Bin 'opsys.cmd') @Arguments }
}

# `openclaw` : l'alias du core.
function Invoke-Openclaw {
    param([string[]]$Arguments)
    return Invoke-Natif { & (Join-Path $script:Bin 'openclaw.cmd') @Arguments }
}

# `opsys metier <commande>` : le moteur Python, lance par le core d'apres opsys\metier.json.
function Invoke-OpsysMetier {
    param([string[]]$Arguments)
    return Invoke-Opsys (@('metier') + $Arguments)
}

# `opsys-metier` : le moteur seul.
function Invoke-Moteur {
    param([string[]]$Arguments)
    return Invoke-Natif { & (Join-Path $script:Bin 'opsys-metier.cmd') @Arguments }
}

function Get-DerniereLigne {
    param([string]$Texte)
    $lignes = @($Texte -split "`n" | Where-Object { $_.Trim() })
    if ($lignes.Count -eq 0) { return '' }
    return $lignes[$lignes.Count - 1].Trim()
}

# Joue un script de l'installateur dans un processus enfant (le code de sortie est celui du fichier). Le journal recoit
# la sortie, secrets masques.
function Invoke-Hote {
    param([string]$Hote, [string]$Fichier, [string[]]$Arguments, [string]$Journal)
    $resultat = Invoke-Natif { & $Hote -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Fichier @Arguments }
    # .env vient peut-etre d'etre cree par ce script : le masque est refait avant d'ecrire le journal.
    $script:Secrets = @(Get-ValeursSecretes)
    $texte = Hide-Secrets $resultat.Sortie
    [System.IO.File]::WriteAllText($Journal, $texte + "`n", $script:Utf8)
    return [pscustomobject]@{ Code = $resultat.Code; Sortie = $texte }
}

function Get-NomHote {
    param([string]$Hote)
    return [System.IO.Path]::GetFileNameWithoutExtension($Hote)
}

function Invoke-Installateur {
    param([string]$Journal, [string[]]$Options = @(), [string]$Hote = $script:HotePrincipal)
    $resultat = Invoke-Hote $Hote (Join-Path $script:Racine 'install\install.ps1') $Options $Journal
    Publish-Masque
    return $resultat
}

function Assert-Installe {
    param([string]$Libelle, $Resultat, [string]$Journal)
    if ($Resultat.Code -ne 0) {
        Write-Host $Resultat.Sortie
        Stop-Preuve "$Libelle a echoue (code $($Resultat.Code)) ; sortie ci-dessus, journal $Journal"
    }
    Assert-SansSecret "sortie de $Libelle" @($Journal, (Join-Path (Join-Path $script:Logiciel 'journaux') 'installation.log'))
}

# -- HTTP ------------------------------------------------------------------------------------------------------------------
Add-Type -AssemblyName System.Net.Http

# Le code HTTP, ou 0 si rien ne repond (000 de curl). Aucun proxy : tout est sur 127.0.0.1.
function Get-CodeHttp {
    param([string]$Url, [hashtable]$Entetes = @{})
    $gestionnaire = New-Object System.Net.Http.HttpClientHandler
    $gestionnaire.UseProxy = $false
    $client = New-Object System.Net.Http.HttpClient($gestionnaire)
    try {
        $client.Timeout = [TimeSpan]::FromSeconds(5)
        foreach ($nom in $Entetes.Keys) { $null = $client.DefaultRequestHeaders.TryAddWithoutValidation($nom, [string]$Entetes[$nom]) }
        $reponse = $client.GetAsync($Url).GetAwaiter().GetResult()
        return [int]$reponse.StatusCode
    }
    catch { return 0 }
    finally { $client.Dispose() }
}

function Wait-Http {
    param([string]$Url, [int]$Delai, [string]$Libelle)
    $ecoule = 0
    while ($ecoule -lt $Delai) {
        if ((Get-CodeHttp $Url) -eq 200) { return }
        if ($script:GatewayProc -and $script:GatewayProc.HasExited) {
            Stop-Preuve "${Libelle} : le Gateway s'est arrete avant de repondre (code $($script:GatewayProc.ExitCode) ; voir $($script:Travail)\gateway-premier-plan.out.log)"
        }
        Start-Sleep -Seconds 2
        $ecoule += 2
    }
    Stop-Preuve "${Libelle} : pas de reponse 200 sur $Url apres $Delai s"
}

# Attend qu'une adresse cesse de repondre 200 (arret d'un service : le processus draine ses connexions).
function Wait-Arret {
    param([string]$Url, [int]$Delai, [string]$Libelle)
    $ecoule = 0
    while ((Get-CodeHttp $Url) -eq 200) {
        if ($ecoule -ge $Delai) { Stop-Preuve "${Libelle} : $Url repond encore $Delai s apres l'arret (processus orphelin ?)" }
        Start-Sleep -Seconds 2
        $ecoule += 2
    }
}

# -- Gateway au premier plan ---------------------------------------------------------------------------------------------------
function Stop-GatewayPremierPlan {
    if ($script:GatewayProc -and -not $script:GatewayProc.HasExited) {
        $null = Invoke-Natif { & taskkill.exe /PID $script:GatewayProc.Id /T /F }
        $null = $script:GatewayProc.WaitForExit(30000)
    }
    $script:GatewayProc = $null
}

# -- Planificateur de taches ------------------------------------------------------------------------------------------------
function Test-Tache {
    param([string]$Nom)
    return ((Invoke-Natif { & schtasks.exe /Query /TN $Nom }).Code -eq 0)
}

function Get-EntreesDemarrage {
    $appdata = [Environment]::GetEnvironmentVariable('APPDATA')
    if (-not $appdata) { return @() }
    $dossier = Join-Path $appdata 'Microsoft\Windows\Start Menu\Programs\Startup'
    if (-not (Test-Path -LiteralPath $dossier)) { return @() }
    return @(Get-ChildItem -LiteralPath $dossier -Force | Where-Object { $_.Name -like 'OpenClaw Gateway (opsys)*' } | ForEach-Object { $_.FullName })
}

function Get-JournauxDuCore {
    $fichiers = @()
    $dossierLogs = Join-Path $script:EtatCore 'logs'
    if (Test-Path -LiteralPath $dossierLogs) { $fichiers += @(Get-ChildItem -LiteralPath $dossierLogs -File -Recurse | ForEach-Object { $_.FullName }) }
    $temp = [System.IO.Path]::GetTempPath()
    foreach ($dossier in @(Get-ChildItem -LiteralPath $temp -Directory -Filter 'openclaw*' -ErrorAction SilentlyContinue)) {
        $fichiers += @(Get-ChildItem -LiteralPath $dossier.FullName -File -Filter '*.log' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    }
    return $fichiers
}

function Confirm-ServiceWindows {
    $tache = $script:NomTache
    $tacheRegistree = Test-Tache $tache
    $entrees = @(Get-EntreesDemarrage)
    if ((-not $tacheRegistree) -and ($entrees.Count -eq 0)) {
        Stop-Preuve "ni la tache planifiee '$tache' ni une entree du dossier Demarrage n'existent apres 'gateway install'"
    }
    if (Test-Tache $script:NomTacheOrigine) {
        Stop-Preuve "la tache '$($script:NomTacheOrigine)', celle du core d'origine, existe : le nom du service n'est pas distinct"
    }
    $texteTache = ''
    if ($tacheRegistree) {
        $script:ModeService = 'tache planifiee'
        # schtasks ecrit son XML en UTF-16 : les octets nuls sont retires, comme le fait le core (schtasks-control.ts).
        $xml = (Invoke-Natif { & schtasks.exe /Query /TN $tache /XML }).Sortie.Replace([string][char]0, '')
        $texteTache = $xml
        if ($xml -notmatch 'LeastPrivilege') { Stop-Preuve "la tache '$tache' ne demande pas le niveau LeastPrivilege : le core exigerait les droits d'administrateur" }
        $etat = ''
        try { $etat = [string](Get-ScheduledTask -TaskName $tache -ErrorAction Stop).State } catch { $etat = "inconnu ($($_.Exception.Message))" }
        if ($etat -eq 'Running') {
            $script:ModeService = 'tache planifiee (en cours d execution par le Planificateur)'
        }
        else {
            Write-Avertissement "la tache '$tache' est enregistree mais son etat est '$etat' : le Gateway repond, mais il a ete lance par le repli direct du core, pas par le Planificateur (session interactive absente ?)"
            $script:ModeService = "tache planifiee enregistree, etat '$etat' (Gateway lance par le repli direct du core)"
        }
    }
    else {
        $script:ModeService = 'entree du dossier Demarrage (repli du core : schtasks /Create refuse)'
        Write-Avertissement "schtasks /Create a ete refuse : le core s'est replie sur une entree du dossier Demarrage ($($entrees -join ', ')). Le service n'est PAS une tache planifiee sur ce poste."
    }
    # gateway.cmd : ce que la tache lance ; le profil et le dossier d'etat canoniques. Il porte les valeurs de .env (voir
    # l'en-tete) : il est donc reserve a l'utilisateur, par l'ACL du dossier d'etat qu'il herite.
    $scriptTache = Join-Path $script:EtatCore 'gateway.cmd'
    if (-not (Test-Path -LiteralPath $scriptTache)) { Stop-Preuve "le script de la tache ($scriptTache) n'existe pas apres l'installation du service" }
    $contenu = [System.IO.File]::ReadAllText($scriptTache)
    if ($contenu.IndexOf($script:EtatCore, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Stop-Preuve "le script de la tache ne designe pas le dossier d'etat canonique du profil ($($script:EtatCore))"
    }
    if ($contenu.IndexOf('OPENCLAW_PROFILE=opsys', [System.StringComparison]::OrdinalIgnoreCase) -lt 0) { Stop-Preuve "le script de la tache ne porte pas le profil opsys" }
    if ($contenu.IndexOf((Join-Path $script:OpsysHome 'core'), [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { Stop-Preuve "le script de la tache designe l'ancien etat du core" }
    if ((Get-CodeHttp "http://127.0.0.1:$($script:PortGateway)/startupz") -ne 200) { Stop-Preuve "le Gateway ne repond pas sous le service" }
    if ((Get-CodeHttp "http://127.0.0.1:$($script:PortMoteur)/sante") -ne 200) { Stop-Preuve "le moteur ne repond pas sous le service" }
    Assert-AclPrivee $scriptTache 'le script de la tache (gateway.cmd)'
    $sondeTache = Join-Path $script:Travail 'tache-planifiee.xml'
    [System.IO.File]::WriteAllText($sondeTache, $texteTache, $script:Utf8)
    Assert-SansSecret 'definition de la tache (XML)' @($sondeTache)
    Assert-SansSecret 'entree du dossier Demarrage' $entrees
    Assert-SansSecret 'journaux du core' @(Get-JournauxDuCore)
    $porteDesSecrets = $false
    foreach ($valeur in (Get-ValeursSecretes)) { if ($contenu.Contains($valeur)) { $porteDesSecrets = $true } }
    if ($porteDesSecrets) { $texteScript = "porte les valeurs de .env (conception du core) et n'est accessible qu'a l'utilisateur" } else { $texteScript = "ne porte aucun secret" }
    Add-Constat "le service tourne ($($script:ModeService)), le moteur qu'il supervise repond ; gateway.cmd $texteScript ; aucun secret dans le XML de la tache ni dans les journaux du core"
    $script:ServiceProuve = 'oui'
}

# =====================================================================================================================
function Invoke-Preuve {
    # -- 0. Le poste ---------------------------------------------------------------------------------------------------
    Write-Etape "0. Poste : ni etat du core d'OPSYS ni sa tache ne doivent deja exister (ce script installe puis desinstalle)"
    if (Test-Path -LiteralPath $script:EtatCore) {
        Stop-Preuve "$($script:EtatCore) existe deja : ce script installe puis desinstalle, il ne s'execute pas sur un poste qui porte une instance OPSYS. Deplacez ce dossier, ou prenez un poste neuf."
    }
    if (Test-Tache $script:NomTache) { Stop-Preuve "la tache '$($script:NomTache)' existe deja sur ce poste : ce script ne s'execute pas sur un poste qui porte une instance OPSYS." }
    if (@(Get-EntreesDemarrage).Count -gt 0) { Stop-Preuve "une entree du dossier Demarrage d'OPSYS existe deja sur ce poste : ce script ne s'execute pas sur un poste qui porte une instance OPSYS." }
    # Le Python du poste (celui de setup-python), pour controler la base apres la desinstallation : l'environnement de l'installateur est alors retire.
    $commandePython = Get-Command 'python' -ErrorAction SilentlyContinue
    if (-not $commandePython) { Stop-Preuve "python est introuvable dans le PATH : il controle la base apres la desinstallation (setup-python en CI)" }
    $script:PythonSysteme = $commandePython.Source
    Add-Constat "poste neuf (Windows) : aucun etat du core d'OPSYS ($($script:EtatCore)) ni tache '$($script:NomTache)'"
    Add-Constat "interpreteurs : installation, service et desinstallation par $(Get-NomHote $script:HotePrincipal), relance et seconde desinstallation par $(Get-NomHote $script:HoteSecondaire) ($($script:HoteSecondaire))"

    Write-Etape '0 bis. Decision prealable : un palier de modeles (comme apres une restauration ou un premier reglage)'
    $null = New-Item -ItemType Directory -Force -Path $script:OpsysHome
    [System.IO.File]::WriteAllText((Join-Path $script:OpsysHome 'paliers.yaml'), "paliers:`n  standard: {provider: anthropic, model: claude-sonnet-5}`n", $script:Utf8)

    # -- 1. Installation sans service ----------------------------------------------------------------------------------
    Write-Etape '1. Installation (sans service) : Node, pnpm, uv, construction du core, moteur, instance, configuration'
    $journal = Join-Path $script:Travail 'installation-1.log'
    Assert-Installe 'install.ps1' (Invoke-Installateur $journal @('-SansService')) $journal
    foreach ($commande in @('opsys.cmd', 'openclaw.cmd', 'opsys-metier.cmd')) {
        if (-not (Test-Path -LiteralPath (Join-Path $script:Bin $commande))) { Stop-Preuve "la commande $commande n'est pas installee dans $($script:Bin)" }
    }
    Assert-AclPrivee $script:EtatCore "le dossier d'etat du core" -SansHeritage
    Assert-AclPrivee (Join-Path $script:EtatCore '.env') '.env' -SansHeritage
    if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $script:EtatCore 'opsys') 'metier.json'))) { Stop-Preuve "opsys\metier.json absent de $($script:EtatCore)" }
    if (Test-Path -LiteralPath (Join-Path $script:OpsysHome 'core')) { Stop-Preuve "un dossier core est apparu sous OPSYS_HOME : l'etat du core ne vit plus la (T0.11-b)" }
    if (-not ((Test-Path -LiteralPath (Join-Path $script:OpsysHome 'opsys.db')) -and (Test-Path -LiteralPath (Join-Path $script:OpsysHome 'paliers.yaml')))) {
        Stop-Preuve 'les donnees metier ne sont plus sous OPSYS_HOME'
    }
    Assert-SansSecret 'configuration du core' (@(Join-Path $script:EtatCore 'openclaw.json') + @(Get-ChildItem -LiteralPath (Join-Path $script:EtatCore 'opsys') -Filter '*.json' | ForEach-Object { $_.FullName }))
    Add-Constat "installation terminee : etat du core dans $($script:EtatCore) (dossier et .env reserves a l'utilisateur par ACL), donnees dans OPSYS_HOME, aucun secret dans la configuration, la sortie ni le journal de l'installateur"

    Write-Etape "1 bis. Le dossier d'etat : le moteur Python, le core et les attentes ecrites d'apres le fork s'accordent"
    $dossier = Get-DerniereLigne (Invoke-OpsysMetier @('instance', 'dossier')).Sortie
    if (-not [string]::Equals($dossier, $script:EtatCore, [System.StringComparison]::OrdinalIgnoreCase)) { Stop-Preuve "opsys metier instance dossier repond '$dossier' au lieu de $($script:EtatCore)" }
    $dossierMoteur = Get-DerniereLigne (Invoke-Moteur @('instance', 'dossier')).Sortie
    if (-not [string]::Equals($dossierMoteur, $script:EtatCore, [System.StringComparison]::OrdinalIgnoreCase)) { Stop-Preuve "opsys-metier instance dossier repond '$dossierMoteur' au lieu de $($script:EtatCore)" }
    $attendu = Join-Path $script:EtatCore 'openclaw.json'
    $configCore = Get-DerniereLigne (Invoke-Opsys @('config', 'file')).Sortie
    $configAlias = Get-DerniereLigne (Invoke-Openclaw @('config', 'file')).Sortie
    if (-not [string]::Equals($configAlias, $configCore, [System.StringComparison]::OrdinalIgnoreCase)) { Stop-Preuve "l'alias openclaw ne repond pas comme opsys : '$configAlias' au lieu de '$configCore'" }
    if (-not [string]::Equals($configCore, $attendu, [System.StringComparison]::OrdinalIgnoreCase)) { Stop-Preuve "le core cherche sa configuration dans '$configCore' au lieu de $attendu" }
    $ailleurs = Join-Path $script:Travail 'ailleurs'
    $foyerCore = Join-Path $script:Travail 'home-du-core'
    $polluee = ''
    try {
        $env:OPENCLAW_STATE_DIR = $ailleurs
        $env:OPENCLAW_CONFIG_PATH = Join-Path $ailleurs 'openclaw.json'
        $env:OPENCLAW_HOME = $foyerCore
        $env:OPENCLAW_PROFILE = 'autre'
        $polluee = Get-DerniereLigne (Invoke-Opsys @('config', 'file')).Sortie
        $polluee = "$polluee|" + (Get-DerniereLigne (Invoke-OpsysMetier @('instance', 'dossier')).Sortie)
    }
    finally {
        foreach ($nom in @('OPENCLAW_STATE_DIR', 'OPENCLAW_CONFIG_PATH', 'OPENCLAW_HOME', 'OPENCLAW_PROFILE')) { Remove-Item -LiteralPath "Env:$nom" -ErrorAction SilentlyContinue }
    }
    if (-not [string]::Equals($polluee, "$attendu|$($script:EtatCore)", [System.StringComparison]::OrdinalIgnoreCase)) { Stop-Preuve "un environnement OPENCLAW_* a deplace le core ou le moteur qu'il lance : ils repondent '$polluee' (la commande installee doit l'ecarter)" }
    if ((Test-Path -LiteralPath $ailleurs) -or (Test-Path -LiteralPath $foyerCore)) { Stop-Preuve "un dossier a ete cree d'apres l'environnement de l'appelant" }
    Add-Constat "opsys metier instance dossier, opsys-metier instance dossier, opsys config file (et son alias openclaw) et l'attente ecrite d'apres le fork donnent tous $($script:EtatCore) ; l'environnement de l'appelant n'y change rien"

    Write-Etape "1 bis bis. Une seule commande : opsys est le core, opsys metier le moteur, l'ancienne forme dit la nouvelle"
    $versionCore = Get-DerniereLigne (Invoke-Opsys @('--version')).Sortie
    if (-not $versionCore.StartsWith('OPSYS ', [System.StringComparison]::Ordinal)) { Stop-Preuve "opsys --version repond '$versionCore' au lieu de 'OPSYS <version>'" }
    if ((Get-DerniereLigne (Invoke-Openclaw @('--version')).Sortie) -ne $versionCore) { Stop-Preuve "l'alias openclaw ne repond pas comme opsys --version" }
    $versionMoteur = Get-DerniereLigne (Invoke-OpsysMetier @('--version')).Sortie
    if (-not $versionMoteur.StartsWith('opsys-metier ', [System.StringComparison]::Ordinal)) { Stop-Preuve "opsys metier --version repond '$versionMoteur' au lieu de 'opsys-metier <version>'" }
    if ((Get-DerniereLigne (Invoke-Moteur @('--version')).Sortie) -ne $versionMoteur) { Stop-Preuve "opsys-metier et opsys metier ne sont pas le meme moteur" }
    $etatBaseMetier = Invoke-OpsysMetier @('base', 'etat')
    if (($etatBaseMetier.Code -ne 0) -or ($etatBaseMetier.Sortie.IndexOf('"revision"', [System.StringComparison]::Ordinal) -lt 0)) { Stop-Preuve "opsys metier base etat ne rend pas l'etat de la base (code $($etatBaseMetier.Code)) : $($etatBaseMetier.Sortie)" }
    $erreurMoteur = Invoke-OpsysMetier @('base')
    if (($erreurMoteur.Code -ne 2) -or ($erreurMoteur.Sortie.IndexOf('usage: opsys-metier base', [System.StringComparison]::Ordinal) -lt 0)) { Stop-Preuve "le code de sortie et l'erreur du moteur ne sont pas relayes par opsys metier (attendu 2, recu $($erreurMoteur.Code)) : $($erreurMoteur.Sortie)" }
    $ancienneForme = Invoke-Opsys @('instance', 'dossier')
    if ($ancienneForme.Code -ne 2) { Stop-Preuve "l'ancienne forme 'opsys instance dossier' sort avec le code $($ancienneForme.Code) (attendu 2) : $($ancienneForme.Sortie)" }
    if ($ancienneForme.Sortie.IndexOf('Utilisez : opsys metier instance dossier', [System.StringComparison]::Ordinal) -lt 0) { Stop-Preuve "l'ancienne forme ne dit pas la nouvelle : $($ancienneForme.Sortie)" }
    if ($ancienneForme.Sortie.IndexOf($script:EtatCore, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { Stop-Preuve "l'ancienne forme a execute la commande (le dossier d'etat est dans sa sortie) : $($ancienneForme.Sortie)" }
    try {
        $env:OPENCLAW_SHELL = 'exec'
        $refusAgent = Invoke-OpsysMetier @('base', 'etat')
    }
    finally { Remove-Item -LiteralPath 'Env:OPENCLAW_SHELL' -ErrorAction SilentlyContinue }
    if (($refusAgent.Code -ne 1) -or ($refusAgent.Sortie.IndexOf('OPENCLAW_SHELL=exec', [System.StringComparison]::Ordinal) -lt 0)) { Stop-Preuve "opsys metier n'est pas refusee depuis le shell d'un agent (code $($refusAgent.Code)) : $($refusAgent.Sortie)" }
    Add-Constat "opsys est le core (OPSYS <version>, alias openclaw identique) ; opsys metier lance le moteur par le core (etat de la base, code de sortie et erreurs relayes) ; l'ancienne forme dit la nouvelle sans rien executer (code 2) ; opsys metier est refusee depuis le shell d'un agent"

    Write-Etape '1 ter. Le core accepte la configuration generee'
    $validation = Invoke-Opsys @('config', 'validate')
    if ($validation.Code -ne 0) { Write-Host $validation.Sortie; Stop-Preuve "opsys config validate refuse la configuration generee (code $($validation.Code))" }
    Add-Constat 'opsys config validate accepte la configuration (dont ${OPSYS_MCP_JETON}, lue dans .env)'

    Write-Etape '1 quater. Ancienne disposition ($OPSYS_HOME\core) : signalee avec la marche a suivre, jamais migree en silence'
    $ancien = Join-Path $script:OpsysHome 'core'
    $null = New-Item -ItemType Directory -Force -Path $ancien
    [System.IO.File]::WriteAllText((Join-Path $ancien '.env'), "MARQUEUR=ancien-etat-fictif`n", $script:Utf8)
    $ancienAvant = Get-Empreinte (Join-Path $ancien '.env')
    $geresAvant = Get-EmpreinteDesFichiersGeres
    # Les ports de l'installation : sans eux, `initialiser` reviendrait aux ports par defaut et changerait la configuration.
    $portsOpsys = @('--port-gateway', [string]$script:PortGateway, '--port-moteur', [string]$script:PortMoteur)
    $refus = Invoke-OpsysMetier (@('instance', 'initialiser') + $portsOpsys)
    if ($refus.Code -eq 0) { Stop-Preuve "opsys metier instance initialiser a accepte l'ancienne disposition" }
    if ($refus.Sortie.IndexOf("ancienne disposition d$($script:EAigu)tect$($script:EAigu)e", [System.StringComparison]::Ordinal) -lt 0) { Stop-Preuve "l'ancienne disposition n'est pas signalee : $($refus.Sortie)" }
    if ($refus.Sortie.IndexOf($ancien, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) { Stop-Preuve "le message ne nomme pas l'ancien dossier" }
    if ($refus.Sortie.IndexOf($script:EtatCore, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) { Stop-Preuve "le message ne nomme pas le dossier d'etat du core" }
    if ($refus.Sortie.IndexOf("Rien n'est migr$($script:EAigu) en silence", [System.StringComparison]::Ordinal) -lt 0) { Stop-Preuve "le message ne dit pas que rien n'est migre" }
    if ((Get-Empreinte (Join-Path $ancien '.env')) -ne $ancienAvant) { Stop-Preuve "l'ancien etat a ete modifie" }
    if ((Get-EmpreinteDesFichiersGeres) -ne $geresAvant) { Stop-Preuve "l'etat du core a change pendant le refus" }
    Move-Item -LiteralPath $ancien -Destination (Join-Path $script:OpsysHome 'core.ancien')  # la marche a suivre : repartir a neuf
    $reprise = Invoke-OpsysMetier (@('instance', 'initialiser') + $portsOpsys)
    if ($reprise.Code -ne 0) { Write-Host $reprise.Sortie; Stop-Preuve "opsys metier instance initialiser a echoue apres la mise de cote de l'ancien etat (code $($reprise.Code))" }
    if ((Get-EmpreinteDesFichiersGeres) -ne $geresAvant) { Stop-Preuve 'la reinitialisation a change un secret ou la configuration' }
    if ((Get-Empreinte (Join-Path (Join-Path $script:OpsysHome 'core.ancien') '.env')) -ne $ancienAvant) { Stop-Preuve "l'ancien etat mis de cote a ete modifie" }
    Add-Constat "l'ancienne disposition est refusee avec la marche a suivre, sans rien modifier ; mise de cote, l'instance se reinitialise sans changer un secret"

    # -- 2. Gateway au premier plan et moteur supervise -----------------------------------------------------------------
    Write-Etape '2. Gateway au premier plan : il lance le moteur (superviseur T0.10) avec le jeton de .env'
    $sortieGateway = Join-Path $script:Travail 'gateway-premier-plan.out.log'
    $erreurGateway = Join-Path $script:Travail 'gateway-premier-plan.err.log'
    $script:GatewayProc = Start-Process -FilePath (Join-Path $script:Bin 'opsys.cmd') -ArgumentList @('gateway', 'run', '--bind', 'loopback', '--port', [string]$script:PortGateway) `
        -RedirectStandardOutput $sortieGateway -RedirectStandardError $erreurGateway -PassThru -WindowStyle Hidden
    Wait-Http "http://127.0.0.1:$($script:PortGateway)/startupz" 300 'Gateway'
    Wait-Http "http://127.0.0.1:$($script:PortMoteur)/sante" 240 'moteur'
    Add-Constat 'GET /startupz du Gateway et GET /sante du moteur : 200'
    $jeton = ''
    foreach ($ligne in [System.IO.File]::ReadAllLines((Join-Path $script:EtatCore '.env'), $script:Utf8)) {
        if ($ligne.StartsWith('OPSYS_MCP_JETON=')) { $jeton = $ligne.Substring('OPSYS_MCP_JETON='.Length) }
    }
    if (-not $jeton) { Stop-Preuve "OPSYS_MCP_JETON est absent de .env" }
    $urlMcp = "http://127.0.0.1:$($script:PortMoteur)/mcp"
    if ((Get-CodeHttp $urlMcp) -ne 401) { Stop-Preuve 'le moteur accepte une requete sans jeton' }
    if ((Get-CodeHttp $urlMcp @{ Authorization = 'Bearer jeton-faux-0123456789abcdef' }) -ne 401) { Stop-Preuve 'le moteur accepte un mauvais jeton' }
    $codeAvecJeton = Get-CodeHttp $urlMcp @{ Authorization = "Bearer $jeton" }
    if (($codeAvecJeton -eq 401) -or ($codeAvecJeton -eq 0)) {
        Stop-Preuve "le moteur supervise refuse le jeton de .env (HTTP $codeAvecJeton) : le Gateway ne lui a pas donne celui de l'installation"
    }
    Add-Constat "une seule authentification : le moteur lance par le Gateway accepte le jeton de .env, refuse tout autre"
    Stop-GatewayPremierPlan
    Wait-Arret "http://127.0.0.1:$($script:PortMoteur)/sante" 60 "le moteur apres l'arret du Gateway"
    Wait-Arret "http://127.0.0.1:$($script:PortGateway)/startupz" 60 "le Gateway apres son arret"
    Add-Constat "l'arret de l'arbre de processus du Gateway arrete aussi le moteur (un arret gracieux n'est pas eprouve sous Windows)"
    Assert-SansSecret 'journal du Gateway' @($sortieGateway, $erreurGateway)
    Add-Constat 'aucun secret de .env dans le journal du Gateway (moteur compris)'

    # -- 3. Idempotence -------------------------------------------------------------------------------------------------
    Write-Etape "3. Relance (par $(Get-NomHote $script:HoteSecondaire)) : ni secret, ni configuration, ni donnee ne change"
    $avant = Get-EmpreinteDesFichiersGeres
    $journal = Join-Path $script:Travail 'installation-2.log'
    Assert-Installe "install.ps1 (relance, $(Get-NomHote $script:HoteSecondaire))" (Invoke-Installateur $journal @('-SansService') $script:HoteSecondaire) $journal
    if ((Get-EmpreinteDesFichiersGeres) -ne $avant) { Stop-Preuve 'la relance a modifie .env, la configuration ou les reglages de l''instance' }
    Add-Constat "relancer install.ps1 (sous $(Get-NomHote $script:HoteSecondaire)) laisse .env, la configuration du core et les reglages identiques"

    # -- 4. Export et restauration --------------------------------------------------------------------------------------
    Write-Etape '4. Export : archive privee, empreinte SHA-256, sans secret ; restauration dans une instance neuve'
    $archive = Join-Path $script:Travail 'export.tar.gz'
    $export = Invoke-OpsysMetier @('instance', 'exporter', '--sortie', $archive)
    if ($export.Code -ne 0) { Write-Host $export.Sortie; Stop-Preuve "opsys metier instance exporter a echoue (code $($export.Code))" }
    $attendueSha = ([System.IO.File]::ReadAllText("$archive.sha256") -split '\s+')[0].ToLowerInvariant()
    if ((Get-Empreinte $archive) -ne $attendueSha) { Stop-Preuve "l'empreinte SHA-256 de l'archive ne correspond pas a $archive.sha256" }
    Assert-AclPrivee $archive "l'archive d'export" -SansHeritage
    Assert-AclPrivee "$archive.sha256" "l'empreinte de l'archive d'export" -SansHeritage
    $py = Join-Path (Join-Path (Join-Path $script:Logiciel 'venv') 'Scripts') 'python.exe'
    $membres = (Invoke-Natif { & $py -c "import sys, tarfile; print(' '.join(sorted(tarfile.open(sys.argv[1]).getnames())))" $archive }).Sortie.Trim()
    if ($membres -ne 'opsys-export/manifeste.json opsys-export/opsys.db opsys-export/paliers.yaml') { Stop-Preuve "membres inattendus dans l'archive : $membres" }
    $decompose = Join-Path $script:Travail 'decompose'
    $null = New-Item -ItemType Directory -Force -Path $decompose
    $extraction = Invoke-Natif { & $py -c "import sys, tarfile; tarfile.open(sys.argv[1]).extractall(sys.argv[2])" $archive $decompose }
    if ($extraction.Code -ne 0) { Write-Host $extraction.Sortie; Stop-Preuve "l'archive d'export ne se decompose pas (code $($extraction.Code))" }
    $contenuExport = Join-Path $decompose 'opsys-export'
    Assert-SansSecret "archive d'export" @(Get-ChildItem -LiteralPath $contenuExport -File | ForEach-Object { $_.FullName })
    $manifeste = [System.IO.File]::ReadAllText((Join-Path $contenuExport 'manifeste.json'), $script:Utf8)
    if (-not $manifeste.Contains('"~/.openclaw-opsys/.env"')) { Stop-Preuve "le manifeste ne nomme pas l'etat du core (~/.openclaw-opsys) parmi les fichiers exclus" }
    foreach ($personnel in @($script:Personnel, $script:Personnel.Replace('\', '\\'))) {
        if ($manifeste.IndexOf($personnel, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { Stop-Preuve 'le manifeste porte le dossier personnel du poste' }
    }
    Add-Constat 'export : membres = liste blanche, SHA-256 verifie (Get-FileHash), ACL reservee a l''utilisateur, aucun secret de .env, etat du core nomme parmi les exclus'
    $etatAvantRestauration = Get-EmpreinteDesFichiersGeres
    $restaure = Join-Path $script:Travail 'restaure'
    try {
        $env:OPSYS_HOME = $restaure
        $restauration = Invoke-OpsysMetier @('instance', 'restaurer', $archive)
        $etatBase = Invoke-OpsysMetier @('base', 'etat')
    }
    finally { $env:OPSYS_HOME = $script:OpsysHome }
    if ($restauration.Code -ne 0) { Write-Host $restauration.Sortie; Stop-Preuve "opsys metier instance restaurer a echoue (code $($restauration.Code))" }
    if ($etatBase.Sortie.IndexOf('"revision"', [System.StringComparison]::Ordinal) -lt 0) { Stop-Preuve "la base restauree n'est pas lisible par opsys metier base etat : $($etatBase.Sortie)" }
    if (Test-Path -LiteralPath (Join-Path $restaure 'core')) { Stop-Preuve 'la restauration a pose un dossier core (secrets) : elle ne doit restaurer que les donnees' }
    if ((Get-EmpreinteDesFichiersGeres) -ne $etatAvantRestauration) { Stop-Preuve "la restauration a touche l'etat du core" }
    Add-Constat 'restauration dans une instance neuve : base lisible, aucun secret ni etat du Gateway restaure'

    # -- 5. Service utilisateur -----------------------------------------------------------------------------------------
    Write-Etape "5. Service utilisateur (tache planifiee '$($script:NomTache)') : installation, demarrage, supervision du moteur"
    if ((Get-Reglage 'OPSYS_SANS_SERVICE' '0') -eq '1') {
        Write-Avertissement 'phase du service sautee (OPSYS_SANS_SERVICE=1)'
        Add-Constat "service '$($script:NomTache)' NON prouve : phase sautee (OPSYS_SANS_SERVICE=1)"
    }
    else {
        $journal = Join-Path $script:Travail 'installation-3.log'
        $service = Invoke-Installateur $journal @()
        if ($service.Code -eq 0) {
            Assert-SansSecret "sortie de install.ps1 (service)" @($journal, (Join-Path (Join-Path $script:Logiciel 'journaux') 'installation.log'))
            Confirm-ServiceWindows
        }
        else {
            Write-Host $service.Sortie
            $raison = "install.ps1 avec le service a echoue (code $($service.Code)). Si le message parle d'acces refuse ou de droits, la tache planifiee exige ici des droits que ce poste n'a pas ; le Gateway a ete prouve au premier plan a l'etape 2. Relancez avec sans_service=1 pour prouver le reste sans le service."
            if ((Get-Reglage 'OPSYS_SERVICE_REQUIS' '0') -eq '1') { Stop-Preuve $raison }
            Write-Avertissement $raison
            Add-Constat "service '$($script:NomTache)' NON prouve : l'installation du service a echoue sur ce poste"
        }
    }

    # -- 6. Desinstallation sans perte de donnees -----------------------------------------------------------------------
    Write-Etape '6. Desinstallation avec export prealable : le logiciel part, les donnees restent'
    $envAvant = Get-Empreinte (Join-Path $script:EtatCore '.env')
    $configAvant = Get-Empreinte (Join-Path $script:EtatCore 'openclaw.json')
    $geresAvantDesinstallation = Get-EmpreinteDesFichiersGeres
    $paliersAvant = Get-Empreinte (Join-Path $script:OpsysHome 'paliers.yaml')
    $archiveAvant = Join-Path $script:Travail 'avant-desinstallation.tar.gz'
    $journalDesinstallation = Join-Path $script:Travail 'desinstallation.log'
    $des = Invoke-Hote $script:HotePrincipal (Join-Path $script:Racine 'install\uninstall.ps1') @('-ExporterAvant', $archiveAvant) $journalDesinstallation
    if ($des.Code -ne 0) { Write-Host $des.Sortie; Stop-Preuve "uninstall.ps1 a echoue (code $($des.Code))" }
    $attendueAvant = ([System.IO.File]::ReadAllText("$archiveAvant.sha256") -split '\s+')[0].ToLowerInvariant()
    if ((Get-Empreinte $archiveAvant) -ne $attendueAvant) { Stop-Preuve "l'empreinte de l'export prealable ne correspond pas a $archiveAvant.sha256" }
    foreach ($commande in @('opsys.cmd', 'openclaw.cmd', 'opsys-metier.cmd')) {
        if (Test-Path -LiteralPath (Join-Path $script:Bin $commande)) { Stop-Preuve "la commande $commande est encore la" }
    }
    if (Test-Path -LiteralPath $script:Logiciel) { Stop-Preuve "le logiciel est encore la : $((Get-ChildItem -LiteralPath $script:Logiciel -Force | ForEach-Object { $_.Name }) -join ', ')" }
    $cheminUtilisateur = [string][Environment]::GetEnvironmentVariable('Path', 'User')
    if (($cheminUtilisateur -split ';') -contains $script:Bin) { Stop-Preuve "le dossier des commandes est encore dans le PATH de l'utilisateur" }
    if (-not (Test-Path -LiteralPath (Join-Path $script:Racine 'core\openclaw.mjs'))) { Stop-Preuve "le depot de l'utilisateur a ete touche" }
    if ((Get-Empreinte (Join-Path $script:EtatCore '.env')) -ne $envAvant) { Stop-Preuve '.env a change pendant la desinstallation' }
    if ((Get-Empreinte (Join-Path $script:EtatCore 'openclaw.json')) -ne $configAvant) { Stop-Preuve 'openclaw.json a change pendant la desinstallation' }
    if ((Get-EmpreinteDesFichiersGeres) -ne $geresAvantDesinstallation) { Stop-Preuve 'un fichier gere a change pendant la desinstallation' }
    if ((Get-Empreinte (Join-Path (Join-Path $script:OpsysHome 'core.ancien') '.env')) -ne $ancienAvant) { Stop-Preuve "l'ancien etat mis de cote a change pendant la desinstallation" }
    if ($des.Sortie.IndexOf("Etat du core conserve : $($script:EtatCore)", [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Stop-Preuve "la desinstallation ne dit pas ou est l'etat du core qu'elle conserve"
    }
    if ((Get-Empreinte (Join-Path $script:OpsysHome 'paliers.yaml')) -ne $paliersAvant) { Stop-Preuve 'paliers.yaml a change pendant la desinstallation' }
    $controleBase = "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); assert c.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'base endommagee'; assert c.execute('SELECT count(*) FROM alembic_version').fetchone()[0] == 1, 'base non migree'"
    $base = Invoke-Natif { & $script:PythonSysteme -c $controleBase (Join-Path $script:OpsysHome 'opsys.db') }
    if ($base.Code -ne 0) { Stop-Preuve "la base de donnees n'est pas intacte apres la desinstallation : $($base.Sortie)" }
    if ($script:ServiceProuve -eq 'oui') {
        if (Test-Tache $script:NomTache) { Stop-Preuve "la tache '$($script:NomTache)' est encore enregistree apres la desinstallation" }
        if (@(Get-EntreesDemarrage).Count -gt 0) { Stop-Preuve "une entree du dossier Demarrage est encore la apres la desinstallation" }
        if (Test-Path -LiteralPath (Join-Path $script:EtatCore 'gateway.cmd')) { Stop-Preuve "le script de la tache (gateway.cmd) est encore la apres la desinstallation" }
        Wait-Arret "http://127.0.0.1:$($script:PortGateway)/startupz" 60 'le Gateway apres la desinstallation'
        Wait-Arret "http://127.0.0.1:$($script:PortMoteur)/sante" 60 'le moteur apres la desinstallation'
    }
    Add-Constat 'desinstallation : service, logiciel et commandes retires ; .env, configuration, reglages, base, etat du core et ancien etat mis de cote intacts ; export verifie'
    $seconde = Invoke-Hote $script:HoteSecondaire (Join-Path $script:Racine 'install\uninstall.ps1') @() (Join-Path $script:Travail 'desinstallation-2.log')
    if ($seconde.Code -ne 0) { Write-Host $seconde.Sortie; Stop-Preuve "la desinstallation n'est pas relancable (sous $(Get-NomHote $script:HoteSecondaire), code $($seconde.Code))" }
    Add-Constat "la desinstallation est relancable (sous $(Get-NomHote $script:HoteSecondaire))"

    # -- Resume ---------------------------------------------------------------------------------------------------------
    Write-Etape 'Tout est vrai'
    $resume = [Environment]::GetEnvironmentVariable('GITHUB_STEP_SUMMARY')
    if ($resume) {
        $lignes = @('### Installateur avec le vrai core (Windows)', '')
        foreach ($constat in $script:Constats) { $lignes += "- $constat" }
        $lignes += ''
        $lignes += "Service utilisateur prouve : **$($script:ServiceProuve)** ($($script:ModeService))"
        [System.IO.File]::AppendAllText($resume, (($lignes -join "`n") + "`n"), $script:Utf8)
    }
    Close-Groupe
}

$codeSortie = 0
try {
    Invoke-Preuve
}
catch {
    $codeSortie = 1
    if ($script:EchecPrevu) { Write-Echec $_.Exception.Message }
    else { Write-Echec "erreur inattendue du script de preuve : $($_.Exception.Message)" ($_.ScriptStackTrace) }
}
finally {
    Stop-GatewayPremierPlan
}
$global:LASTEXITCODE = $codeSortie
exit $codeSortie
