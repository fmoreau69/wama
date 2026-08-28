# scan_ecart_volume.ps1 — READ-ONLY : l'arithmétique « somme des fichiers vs utilisé réel »
# qui rend VISIBLE ce que les fichiers ne montrent pas (stockage VSS + dossiers à ACL).
# Usage : pwsh -NoProfile -File scan_ecart_volume.ps1 [-Drive C]
# Leçon du 2026-08-29 : 11,5 Go supprimés, +0,3 Go visibles — les clichés VSS RETIENNENT les
# blocs supprimés ; l'écart mesuré ici (~34,8 Go sur C:) était le plafond VSS par défaut (10 %).
param([string]$Drive = 'C')
$ErrorActionPreference = 'Continue'
$root = "${Drive}:\"

Write-Output ("=== CARTE DES DOSSIERS RACINE DE {0} (fichiers accessibles ; les liens/reparse points" -f $root)
Write-Output "=== ne sont PAS suivis — piège vécu : C:\Users\fmoreau\.ollama est un lien vers D:) ==="
$grand = 0.0
foreach ($dir in Get-ChildItem $root -Directory -Force -ErrorAction SilentlyContinue) {
    if ($dir.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        Write-Output ("      lien  {0} -> ignore ({1})" -f $dir.Name, $dir.Target)
        continue
    }
    $sum = (Get-ChildItem $dir.FullName -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum).Sum
    if ($null -eq $sum) { $sum = 0 }
    $grand += $sum / 1GB
    Write-Output ("{0,10:N2} Go  {1}" -f ($sum / 1GB), $dir.Name)
}
$rootFiles = (Get-ChildItem $root -File -Force -ErrorAction SilentlyContinue |
    Measure-Object Length -Sum).Sum
if ($null -eq $rootFiles) { $rootFiles = 0 }
$grand += $rootFiles / 1GB
Write-Output ("{0,10:N2} Go  (fichiers racine : pagefile, swapfile...)" -f ($rootFiles / 1GB))
Write-Output ''
$d = Get-PSDrive $Drive
Write-Output ("SOMME MESUREE : {0:N2} Go — UTILISE REEL : {1:N2} Go — ECART (VSS + inaccessibles) : {2:N2} Go" -f $grand, ($d.Used / 1GB), (($d.Used / 1GB) - $grand))
Write-Output "Un ecart ~10 % du volume = plafond VSS par defaut. Mesure exacte : vssadmin list shadowstorage (admin)."
