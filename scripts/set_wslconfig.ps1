<#
.SYNOPSIS
    Genere %USERPROFILE%\.wslconfig en fonction de la RAM physique presente.

.DESCRIPTION
    A relancer apres tout changement de barrettes. Le dimensionnement suit une
    regle unique : on RESERVE a Windows ce qu'il engage reellement, plus une
    marge, et WSL2 recoit le reste.

    POURQUOI une reserve genereuse (et pas "tout sauf 8 Go") : `memory=` est un
    PLAFOND, pas une reservation -- vmmem ne prend que ce que l'invite utilise.
    Le risque n'est donc pas de "gaspiller", il est de laisser WSL monter jusqu'a
    un plafond qui etrangle Windows. Sur cette machine, 3 freezes durs
    (Kernel-Power 41, les 27/07/2026) sont survenus exactement comme ca, avant
    que le premier plafond ne soit pose.

    Reference (29/07/2026, 64 Go installes, 2x Samsung 32 Go a 3200 MT/s en
    dual channel) : reserve 16 Go -> WSL 48 Go. Windows conserve exactement ce
    dont il disposait sur la config 32 Go precedente (partage 16/16), qui ne
    posait pas de probleme de RAM.

    ATTENTION : Ollama tourne sur l'HOTE (pas dans WSL) et consomme de la RAM
    hote au chargement. La reserve doit l'absorber.

.PARAMETER ReserveGB
    RAM laissee a Windows. Defaut : 16 Go, plancher absolu 12 Go.

    NE PAS dimensionner cette reserve sur la memoire ENGAGEE (commit) de Windows :
    le commit est adossable au fichier d'echange, il depasse normalement le
    resident. Mesure du 29/07/2026 : 21,9 Go engages alors que la machine
    tournait tres bien avec 16 Go de RAM physique cote Windows (config 32 Go,
    partage 16/16). C'est le RESIDENT qui compte, et 16 Go le couvrent ici.

.PARAMETER MemoryGB
    Force le plafond WSL2 et ignore le calcul (echappatoire assumee).

.PARAMETER SwapGB
    Swap de l'invite. Defaut 8 Go. NE PAS mettre 0 : ce swap n'est touche que si
    l'invite depasse `memory=`, et il sert alors d'amortisseur au lieu d'un
    OOM-kill sec en plein chargement de modele. Un .vhdx inutilise ne coute rien.

.PARAMETER DryRun
    Affiche le fichier qui serait ecrit, sans rien modifier.

.EXAMPLE
    pwsh -File scripts/set_wslconfig.ps1
    pwsh -File scripts/set_wslconfig.ps1 -MemoryGB 48 -DryRun
#>

[CmdletBinding()]
param(
    [int]$ReserveGB = 16,
    [int]$MemoryGB = 0,
    [int]$SwapGB = 8,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- mesures
$os = Get-CimInstance Win32_OperatingSystem
$dimms = @(Get-CimInstance Win32_PhysicalMemory)

# Base de calcul = RAM PHYSIQUE installee (somme des barrettes), pas
# TotalVisibleMemorySize : ce dernier retranche la reservation materielle et
# donne des paliers batards (63 au lieu de 64).
$totalGB = [math]::Round(($dimms | Measure-Object Capacity -Sum).Sum / 1GB)
$visibleGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$committedGB = [math]::Round(($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / 1MB, 1)

Write-Host "RAM physique      : $totalGB Go ($visibleGB Go visibles par Windows)" -ForegroundColor Cyan
foreach ($d in $dimms) {
    "  - {0} {1} Go @ {2} MT/s ({3})" -f $d.Manufacturer.Trim(), ($d.Capacity / 1GB), $d.ConfiguredClockSpeed, $d.DeviceLocator | Write-Host
}
Write-Host "Windows engage    : $committedGB Go (WSL non compris s'il est arrete)" -ForegroundColor Cyan

# ---------------------------------------------------------------- calcul
# Plancher absolu : en dessous, Windows pagine en permanence quel que soit le total.
$floorReserve = 12
if ($ReserveGB -lt $floorReserve) {
    Write-Host "Reserve $ReserveGB Go relevee au plancher absolu de $floorReserve Go." -ForegroundColor Yellow
    $ReserveGB = $floorReserve
}

if ($MemoryGB -gt 0) {
    $wslGB = $MemoryGB
    Write-Host "Plafond force a $wslGB Go (-MemoryGB)." -ForegroundColor Yellow
} else {
    $wslGB = $totalGB - $ReserveGB
}

if ($wslGB -lt 4) { throw "Plafond calcule inexploitable ($wslGB Go). Verifie -ReserveGB." }

$remaining = $totalGB - $wslGB
Write-Host "Reserve Windows   : $remaining Go / plafond WSL2 : $wslGB Go" -ForegroundColor Cyan
if ($remaining -lt $floorReserve) {
    Write-Host ""
    Write-Host "ALERTE : $remaining Go pour Windows, sous le plancher de $floorReserve Go." -ForegroundColor Red
    Write-Host "         Risque d'etranglement de l'hote (freezes Kernel-Power 41 vecus le 27/07/2026)." -ForegroundColor Red
    Write-Host ""
}

# ---------------------------------------------------------------- rendu
$stamp = Get-Date -Format 'yyyy-MM-dd'
$content = @"
# Genere par scripts/set_wslconfig.ps1 le $stamp -- NE PAS editer a la main,
# relancer le script (il recalcule a partir de la RAM reellement presente).
#
# Machine au moment du calcul : $totalGB Go installes, Windows engageait $committedGB Go.
# Reserve Windows : $remaining Go. Plafond WSL2 : $wslGB Go.
#
# `memory` est un PLAFOND, pas une reservation : vmmem ne prend que ce que
# l'invite utilise. La reserve protege l'hote du cas ou WSL monte au plafond
# (3 freezes Kernel-Power 41 le 27/07/2026, avant la pose du premier plafond).
[wsl2]
memory=${wslGB}GB
swap=${SwapGB}GB

[experimental]
# Rend progressivement au host le page cache Linux (lectures volumineuses sur /mnt/d)
autoMemoryReclaim=gradual
"@

$target = Join-Path $env:USERPROFILE '.wslconfig'

Write-Host "--------------------------------------------------------"
Write-Host $content
Write-Host "--------------------------------------------------------"

if ($DryRun) {
    Write-Host "[dry-run] $target inchange." -ForegroundColor Yellow
    return
}

if (Test-Path $target) {
    $backup = "$target.bak"
    Copy-Item $target $backup -Force
    Write-Host "Sauvegarde : $backup"
}

# UTF-8 SANS BOM : WSL ne parse pas un .wslconfig commencant par un BOM.
[System.IO.File]::WriteAllText($target, $content, (New-Object System.Text.UTF8Encoding $false))

Write-Host "Ecrit : $target" -ForegroundColor Green
Write-Host ""
Write-Host "A APPLIQUER : wsl.exe --shutdown   (le plafond n'est relu qu'au prochain demarrage de la VM)" -ForegroundColor Yellow
