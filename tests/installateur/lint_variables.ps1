# tests/installateur/lint_variables.ps1 : les variables lues dans une fonction sans avoir jamais ete posees.
#
# C'est la faute que Set-StrictMode ne montre qu'a l'execution ($lines pour $lignes, par exemple), et les scripts de
# l'installateur Windows ne s'executent qu'en CI. Ce controle lit l'arbre syntaxique de PowerShell (ce que le vrai
# analyseur de PowerShell produit) : pour chaque fonction, chaque variable lue doit etre un parametre, posee dans la
# fonction, une variable automatique, ou posee au niveau du script ; chaque $script:X lue doit etre posee quelque part.
# Une variable posee dans la fonction APPELANTE (portee dynamique) est refusee : elle est trop fragile.
#
# Second controle, du meme ordre : chaque commande appelee par son nom doit etre une fonction du script, une commande de
# ce PowerShell, un programme natif connu ou une commande propre a Windows que ce poste n'a peut-etre pas (Get-Acl,
# schtasks.exe...). Un nom qui n'est aucun des quatre est une faute de frappe (`Wirte-Etape`) qui n'echouerait qu'en CI.
#
# Usage : pwsh -NoProfile -File tests/installateur/lint_variables.ps1 <script.ps1>
# Sortie : une ligne par variable suspecte ; code de sortie 0 si aucune, 1 sinon, 2 si le script ne s'analyse pas.
# Lance par tests/test_installateur_windows.py (qui le confronte aussi a un script fautif). ASCII pur.

[CmdletBinding(PositionalBinding = $false)]
param([Parameter(Mandatory = $true, Position = 0)][string]$Fichier)

$erreurs = $null
$jetons = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $Fichier).Path, [ref]$jetons, [ref]$erreurs)
if ($erreurs.Count -gt 0) {
    $erreurs | ForEach-Object { "SYNTAXE ligne $($_.Extent.StartLineNumber) : $($_.Message)" }
    exit 2
}

# Variables que PowerShell pose lui-meme (ou que l'hote pose).
$automatiques = @('true', 'false', 'null', '_', 'PSItem', 'args', 'input', 'Matches', 'PID', 'PSScriptRoot', 'PSCommandPath',
    'ErrorActionPreference', 'LASTEXITCODE', 'error', 'ExecutionContext', 'Host', 'MyInvocation', 'PSCmdlet',
    'PSBoundParameters', 'env', 'StackTrace', 'PSVersionTable', 'IsWindows', 'IsLinux', 'IsMacOS', 'ConfirmPreference',
    'VerbosePreference', 'WarningPreference', 'ProgressPreference', 'OFS', 'HOME', 'pwd', 'ForEach', 'Error')

function Get-Nom {
    param($Variable)
    return ($Variable.VariablePath.UserPath -replace '^(script|global|local|private|using):', '')
}

function Test-DansFonction {
    param($Noeud)
    $parent = $Noeud.Parent
    while ($null -ne $parent) {
        if ($parent -is [System.Management.Automation.Language.FunctionDefinitionAst]) { return $true }
        $parent = $parent.Parent
    }
    return $false
}

# Les noms poses sous $Noeud : affectations, variables de foreach, parametres. Avec -HorsFonctions, ceux qui sont dans
# une fonction (imbriquee) ne comptent pas : c'est l'ensemble des variables posees au niveau du script.
function Get-Posees {
    param($Noeud, [switch]$HorsFonctions)
    $posees = New-Object System.Collections.Generic.HashSet[string] ([StringComparer]::OrdinalIgnoreCase)
    $ajouts = @()
    $affectations = $Noeud.FindAll({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true)
    foreach ($affectation in $affectations) {
        if ($HorsFonctions -and (Test-DansFonction $affectation)) { continue }
        $gauche = $affectation.Left.FindAll({ param($n) $n -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)
        $ajouts += @($gauche | ForEach-Object { Get-Nom $_ })
    }
    foreach ($boucle in $Noeud.FindAll({ param($n) $n -is [System.Management.Automation.Language.ForEachStatementAst] }, $true)) {
        if ($HorsFonctions -and (Test-DansFonction $boucle)) { continue }
        $ajouts += Get-Nom $boucle.Variable
    }
    foreach ($parametre in $Noeud.FindAll({ param($n) $n -is [System.Management.Automation.Language.ParameterAst] }, $true)) {
        if ($HorsFonctions -and (Test-DansFonction $parametre)) { continue }
        $ajouts += Get-Nom $parametre.Name
    }
    foreach ($nom in $ajouts) { [void]$posees.Add($nom) }
    return , $posees
}

# Les $script:X posees n'importe ou (dans une fonction, `$script:X = ...` pose bien la variable du script).
$auScriptAilleurs = New-Object System.Collections.Generic.HashSet[string] ([StringComparer]::OrdinalIgnoreCase)
foreach ($affectation in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true)) {
    foreach ($variable in $affectation.Left.FindAll({ param($n) $n -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)) {
        if ($variable.VariablePath.UserPath -match '^script:') { [void]$auScriptAilleurs.Add((Get-Nom $variable)) }
    }
}

$fonctions = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
$auScript = @(Get-Posees $ast -HorsFonctions)[0]
$suspectes = @()
foreach ($fonction in $fonctions) {
    $locales = @(Get-Posees $fonction)[0]
    $lues = $fonction.Body.FindAll({ param($n) $n -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)
    foreach ($variable in $lues) {
        $chemin = $variable.VariablePath
        if ($chemin.IsDriveQualified) { continue }
        $nom = Get-Nom $variable
        if ($chemin.UserPath -match '^script:') {
            if (-not ($auScript.Contains($nom) -or $auScriptAilleurs.Contains($nom))) { $suspectes += "$($fonction.Name) ligne $($variable.Extent.StartLineNumber) : `$script:$nom lue, jamais posee" }
            continue
        }
        if (($automatiques -contains $nom) -or $locales.Contains($nom) -or $auScript.Contains($nom)) { continue }
        $suspectes += "$($fonction.Name) ligne $($variable.Extent.StartLineNumber) : `$$nom lue, jamais posee"
    }
}
# -- commandes appelees par leur nom ------------------------------------------------------------------------------------------
$definies = @($fonctions | ForEach-Object { $_.Name })
$natives = @('node', 'uv', 'git', 'curl.exe', 'corepack', 'npm', 'pnpm', 'python', 'schtasks.exe', 'taskkill.exe', 'powershell.exe',
    'pwsh', 'bash')
$propresAWindows = @('Get-Acl', 'Get-ScheduledTask', 'Get-ScheduledTaskInfo', 'Get-CimInstance', 'Get-NetTCPConnection', 'Get-Command')
$commandes = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)
foreach ($commande in $commandes) {
    $premier = $commande.CommandElements[0]
    if ($premier -isnot [System.Management.Automation.Language.StringConstantExpressionAst]) { continue }  # & $variable, & (expr)
    $nom = $premier.Value
    if (($definies -contains $nom) -or ($natives -contains $nom) -or ($propresAWindows -contains $nom)) { continue }
    if ($nom -match '^[.&]$') { continue }
    if (Get-Command $nom -ErrorAction SilentlyContinue) { continue }
    $suspectes += "ligne $($commande.Extent.StartLineNumber) : la commande '$nom' n'existe pas (ni fonction du script, ni commande de PowerShell, ni programme connu)"
}

$suspectes | Sort-Object -Unique
if ($suspectes.Count -gt 0) { exit 1 }
exit 0
