# scan_residus.ps1 — inventaire READ-ONLY des résidus de crash hôte (C: et D:).
# Ne supprime RIEN. Le nettoyage est dans cleanup_residus.ps1 (swap orphelins seulement).
# Réf. mécanisme : INFRA_WSL_VS_WINDOWS.md §« Chaque crash hôte FUITE jusqu'à 8 Go dans %TEMP% ».
$ErrorActionPreference = 'Continue'

function Test-FileLocked([string]$path) {
    # Seul critère fiable pour distinguer le swap VIVANT d'un orphelin (ni date ni taille).
    try {
        $fs = [System.IO.File]::Open($path, 'Open', 'ReadWrite', 'None')
        $fs.Close()
        return $false
    } catch {
        return $true
    }
}

Write-Output '=== 1. ESPACE LIBRE ==='
foreach ($d in Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Name -in 'C','D' }) {
    $total = ($d.Used + $d.Free) / 1GB
    $pct = if ($total -gt 0) { 100 * $d.Free / 1GB / $total } else { 0 }
    Write-Output ("{0}: libre {1:N2} Go / {2:N2} Go ({3:N1} %)" -f $d.Name, ($d.Free / 1GB), $total, $pct)
}

Write-Output ''
Write-Output '=== 2. swap.vhdx ORPHELINS dans %TEMP% (dossiers GUID) — ~1 par crash ==='
$guidDirs = Get-ChildItem $env:TEMP -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^\{?[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}?$' }
$orphanTotal = 0.0
$found = $false
foreach ($dir in $guidDirs) {
    $vhdx = Get-ChildItem $dir.FullName -Filter *.vhdx -ErrorAction SilentlyContinue
    foreach ($f in $vhdx) {
        $found = $true
        $locked = Test-FileLocked $f.FullName
        $state = if ($locked) { 'VIVANT (verrouillé) — NE PAS TOUCHER' } else { 'ORPHELIN (libre)' }
        if (-not $locked) { $orphanTotal += $f.Length / 1GB }
        Write-Output ("{0,-30} {1,8:N2} Go  modif {2:yyyy-MM-dd HH:mm}  {3}" -f $f.Name, ($f.Length / 1GB), $f.LastWriteTime, $state)
        Write-Output ("    -> {0}" -f $f.FullName)
    }
}
if (-not $found) { Write-Output 'Aucun .vhdx sous un dossier GUID de %TEMP%.' }
Write-Output ("TOTAL orphelin recuperable : {0:N2} Go" -f $orphanTotal)

Write-Output ''
Write-Output '=== 3. DUMPS SYSTEME sur C: (PREUVES de diagnostic — inventorier, ne PAS supprimer sans arbitrage) ==='
$dumpPaths = @(
    "$env:SystemRoot\MEMORY.DMP",
    "$env:SystemRoot\Minidump",
    "$env:SystemRoot\LiveKernelReports",
    "$env:LOCALAPPDATA\CrashDumps",
    "$env:ProgramData\Microsoft\Windows\WER\ReportQueue",
    "$env:ProgramData\Microsoft\Windows\WER\ReportArchive"
)
foreach ($p in $dumpPaths) {
    if (Test-Path $p) {
        if ((Get-Item $p) -is [System.IO.DirectoryInfo]) {
            $items = Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue
            $size = ($items | Measure-Object Length -Sum).Sum
            if ($null -eq $size) { $size = 0 }
            Write-Output ("{0,-60} {1,8:N2} Go  ({2} fichiers)" -f $p, ($size / 1GB), @($items).Count)
        } else {
            $f = Get-Item $p
            Write-Output ("{0,-60} {1,8:N2} Go  modif {2:yyyy-MM-dd HH:mm}" -f $p, ($f.Length / 1GB), $f.LastWriteTime)
        }
    } else {
        Write-Output ("{0,-60} absent" -f $p)
    }
}

Write-Output ''
Write-Output '=== 4. CLICHES VSS sur D: (1 par redemarrage + 1/4h — purge = ARBITRAGE Fabien) ==='
try {
    $out = vssadmin list shadowstorage /for=D: 2>&1
    Write-Output ($out | Out-String)
} catch {
    Write-Output "vssadmin inaccessible (elevation requise ?) : $_"
}

Write-Output ''
Write-Output '=== 5. JOURNAUX D INSTRUMENTATION du repo (on DECALE, on ne VIDE pas) ==='
$repoLogs = 'D:\WAMA\web-app-for-media-automation\logs'
foreach ($sub in @('hwlog', 'ui_smoke')) {
    $p = Join-Path $repoLogs $sub
    if (Test-Path $p) {
        $items = Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue
        $size = ($items | Measure-Object Length -Sum).Sum
        if ($null -eq $size) { $size = 0 }
        Write-Output ("{0,-60} {1,8:N2} Go  ({2} fichiers)" -f $p, ($size / 1GB), @($items).Count)
    }
}
$bigLogs = Get-ChildItem $repoLogs -File -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 100MB }
foreach ($f in $bigLogs) {
    Write-Output ("{0,-60} {1,8:N2} Go  (>100 Mo, verifier rotation)" -f $f.FullName, ($f.Length / 1GB))
}
