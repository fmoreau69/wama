<#
.SYNOPSIS
    Range les permissions Claude Code : politique durable d'un côté, accumulation de l'autre.

.DESCRIPTION
    Problème observé : `.claude/settings.local.json` regrossit sans cesse (582 entrées le 31/07,
    déjà purgé le 25/07). Chaque approbation y écrit une entrée EXACTE, qui ne re-matchera plus
    jamais rien. Purger à la main est une corvée récurrente et risquée (on perd des motifs utiles).

    Levier : Claude Code n'écrit ses approbations QUE dans settings.local.json. Il ne touche
    jamais settings.json. D'où la partition :

        .claude/settings.json        POLITIQUE  — motifs génériques + garde-fous `ask`. Stable.
        .claude/settings.local.json  BROUILLON  — ce que Claude y accumule. Jetable.

    Ce script promeut vers la politique ce qui mérite de l'être, jette le reste, et vide le
    brouillon. Relançable : c'est le geste d'entretien, pas une opération unique.

    Il corrige aussi deux défauts structurels détectés le 31/07 :
      - `Bash(git:*)` SUBSUMAIT les garde-fous `Bash(git push:*)`, `git reset --hard`, `git rebase`.
        On ne parie pas sur la précédence allow/ask : on énumère les sous-commandes sûres.
      - les variantes `rtk git …` (imposées par le CLAUDE.md global) échappaient aux garde-fous.

.EXAMPLE
    pwsh -File scripts/clean_permissions.ps1
    pwsh -File scripts/clean_permissions.ps1 -WhatIf    # rapport seul, n'écrit rien
#>
param(
    [string]$Dir = 'D:\WAMA\web-app-for-media-automation\.claude',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$policyPath = Join-Path $Dir 'settings.json'
$localPath  = Join-Path $Dir 'settings.local.json'

# ── Sous-commandes git considérées comme sûres ───────────────────────────────
# Tout ce qui n'est pas listé (push, reset --hard, rebase, filter-repo…) reste demandé.
#
# `add` et `commit` en sont VOLONTAIREMENT absents. Un motif de préfixe ne sait pas exprimer
# « `git add <chemins>` oui, `git add .` non » : autoriser `git add:*` subsumerait le garde-fou.
# Or ce sont exactement les deux commandes qui ont déjà balayé 12 fichiers stagés par une autre
# instance Claude (CLAUDE.md, discipline git multi-instances). Elles restent donc demandées —
# deux clics par palier, contre le risque de réécrire l'index partagé d'une autre instance.
$gitSafe = @(
    'status', 'log', 'diff', 'show', 'branch', 'fetch',
    'stash', 'worktree', 'rev-parse', 'ls-files', 'remote', 'blame'
)

# ── Garde-fous : demandés, jamais accordés d'office ──────────────────────────
# `git add .` / `-A` : un commit sans pathspec a déjà balayé 12 fichiers stagés par une
# autre instance Claude (cf. CLAUDE.md, discipline git multi-instances).
# Déclinés sur les DEUX outils et les DEUX préfixes : `rtk git push` doit être aussi
# protégé que `git push` (le CLAUDE.md global impose le préfixe rtk), et un garde-fou
# absent d'un outil laisse passer les motifs larges de cet outil.
$ask = @()
foreach ($tool in @('Bash', 'PowerShell')) {
    foreach ($pref in @('git', 'rtk git')) {
        foreach ($c in @('push', 'reset --hard', 'rebase', 'add .', 'add -A', 'commit')) {
            $ask += "$tool($pref $c`:*)"
        }
    }
}
$ask += @('Bash(rm -rf:*)', 'PowerShell(Remove-Item -Recurse:*)')

# ── Entrées trop larges : remplacées par leur développement sûr ──────────────
$expand = @{
    'Bash(git:*)'        = @($gitSafe | ForEach-Object { "Bash(git $_`:*)" })
    'Bash(git *)'        = @($gitSafe | ForEach-Object { "Bash(git $_`:*)" })
    'Bash(rtk git:*)'    = @($gitSafe | ForEach-Object { "Bash(rtk git $_`:*)" })
    'Bash(rtk git *)'    = @($gitSafe | ForEach-Object { "Bash(rtk git $_`:*)" })
    'PowerShell(git:*)'  = @($gitSafe | ForEach-Object { "PowerShell(git $_`:*)" })
    'PowerShell(git *)'  = @($gitSafe | ForEach-Object { "PowerShell(git $_`:*)" })
}

# ── Escape hatches : autorisent l'exécution arbitraire via un wrapper de shell ──
$banned = @(
    'Bash(powershell:*)', 'Bash(powershell.exe:*)', 'Bash(pwsh:*)',
    'Bash(cmd /c:*)', 'Bash(cmd.exe:*)', 'Bash(sh -c:*)', 'Bash(eval:*)',
    'PowerShell(Invoke-Expression:*)', 'PowerShell(iex:*)', 'PowerShell(Start-Process:*)'
)
# `git add` / `git commit` : jamais accordés en bloc, quel que soit l'outil ou le préfixe.
# Un motif de préfixe ne distingue pas `git commit <chemins>` de `git commit` nu, et c'est
# le second qui emporte l'index partagé d'une autre instance.
foreach ($tool in @('Bash', 'PowerShell')) {
    foreach ($pref in @('git', 'rtk git')) {
        $banned += "$tool($pref add`:*)", "$tool($pref commit`:*)"
    }
}

function Read-Perms([string]$p) {
    if (-not (Test-Path $p)) { return @{ allow = @(); deny = @(); ask = @() } }
    $j = Get-Content $p -Raw | ConvertFrom-Json
    return @{
        allow = @($j.permissions.allow)
        deny  = @($j.permissions.deny)
        ask   = @($j.permissions.ask)
    }
}

$policy = Read-Perms $policyPath
$local  = Read-Perms $localPath

# ── Tri : ce qui est générique monte en politique, le reste tombe ────────────
$promoted = [System.Collections.Generic.List[string]]::new()
$rejected = [System.Collections.Generic.List[object]]::new()

foreach ($e in @($policy.allow + $local.allow)) {
    if ($banned -contains $e) {
        $rejected.Add([pscustomobject]@{ Entry = $e; Reason = 'escape hatch' }); continue
    }
    if ($expand.ContainsKey($e)) {
        foreach ($x in $expand[$e]) { $promoted.Add($x) }
        $rejected.Add([pscustomobject]@{ Entry = $e; Reason = 'trop large -> developpee en sous-commandes sures' })
        continue
    }
    # Formes durables : octroi d'outil, mcp, domaine WebFetch, portee **, motif : * ou  *
    $keep = ($e -match '^[A-Za-z_]+$') -or ($e -match '^mcp__') -or
            ($e -match '^WebFetch\(domain:[^)]+\)$') -or ($e -match '\*\*\)$') -or
            ($e -match ':\*\)$') -or ($e -match ' \*\)$')
    if ($e -match '__NEW_LINE_|__TRACKED_VAR__|\$[A-Za-z_]') { $keep = $false }

    # Un motif ":*)" ou " *)" n'est DURABLE que si son prefixe reste generique.
    # Le dialogue d'approbation suffixe " *" a des commandes entieres : sans ce
    # controle, une commande litterale (chemins en arguments, longue liste de
    # fichiers) se fait passer pour un motif et ne re-matchera jamais.
    # Le 1er jeton peut etre un chemin (l'executable) ; les ARGUMENTS non.
    $why = 'entree exacte a usage unique'
    if ($keep -and $e -match '^[A-Za-z_]+\((.+?) ?:?\*\)$') {
        $tok = @($Matches[1] -split '\s+' | Where-Object { $_ })
        # Une URL en argument reste generique (ex. un endpoint local) : on l'exempte.
        $argsPathy = @($tok | Select-Object -Skip 1 |
                       Where-Object { $_ -notmatch '^[''"]?https?://' -and $_ -match '[/\\''"]' })
        if ($tok.Count -gt 3 -or $argsPathy.Count) {
            $keep = $false
            $why  = 'commande litterale deguisee en motif'
        }
    }

    if ($keep) { $promoted.Add($e) }
    else       { $rejected.Add([pscustomobject]@{ Entry = $e; Reason = $why }) }
}

# ── Normalisation : `Tool(cmd *)` et `Tool(cmd:*)` font doublon -> garder `:*` ──
$colon = @{}
foreach ($e in $promoted) { if ($e -match '^(.+?)\((.+):\*\)$') { $colon["$($Matches[1])|$($Matches[2])"] = $true } }
$normalized = @($promoted | Where-Object {
    -not ($_ -match '^(.+?)\((.+) \*\)$' -and $colon["$($Matches[1])|$($Matches[2])"])
} | Sort-Object -Unique)

# ── Un allow ne doit JAMAIS subsumer un garde-fou ────────────────────────────
# Passe générique : on ne se fie pas à la précédence allow/ask de Claude Code (non vérifiée),
# on retire le motif trop large. Auto-protège les exécutions futures.
$filtered = [System.Collections.Generic.List[string]]::new()
foreach ($e in $normalized) {
    $ei   = ($e -replace '^[A-Za-z]+\(', '' -replace '[:) *]+$', '')
    $tool = ($e -split '\(')[0]
    $bad  = $false
    foreach ($a in $ask) {
        if ($a -notlike "$tool(*") { continue }
        $ai = ($a -replace '^[A-Za-z]+\(', '' -replace '[:) *]+$', '')
        # -eq : un allow AUSSI large que le garde-fou l'annule tout autant
        #       qu'un allow plus large (ex. allow "git commit *" vs ask "git commit:*").
        if ($ei -and ($ai -eq $ei -or $ai -like "$ei *")) { $bad = $true; break }
    }
    if ($bad) { $rejected.Add([pscustomobject]@{ Entry = $e; Reason = 'subsumait un garde-fou ask' }) }
    else      { $filtered.Add($e) }
}
$normalized = @($filtered)

# ── Vérification finale (doit toujours passer) ───────────────────────────────
$conflicts = @()
foreach ($a in $ask) {
    $ai = ($a -replace '^[A-Za-z]+\(', '' -replace '[:) *]+$', '')
    $tool = ($a -split '\(')[0]
    foreach ($e in $normalized) {
        if ($e -notlike "$tool(*") { continue }
        $ei = ($e -replace '^[A-Za-z]+\(', '' -replace '[:) *]+$', '')
        if ($ei -and $ai -like "$ei *") { $conflicts += "$a subsume par $e" }
    }
}

Write-Host "politique : $($policy.allow.Count) + local : $($local.allow.Count)  ->  $($normalized.Count) motifs"
Write-Host "rejete    : $($rejected.Count)"
Write-Host "garde-fous: $($ask.Count)"
if ($conflicts) {
    Write-Host "CONFLITS RESIDUELS :" -ForegroundColor Red
    $conflicts | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
} else {
    Write-Host "aucun conflit allow/ask" -ForegroundColor Green
}
($rejected | Group-Object Reason | Sort-Object Count -Descending |
    ForEach-Object { "  {0,4}  {1}" -f $_.Count, $_.Name }) | Write-Host

if ($WhatIf) { Write-Host "`n-WhatIf : rien ecrit."; return }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach ($p in @($policyPath, $localPath)) {
    if (Test-Path $p) { Copy-Item $p "$p.bak-$stamp" -Force }
}

# PRESERVER les clefs hors "permissions" (hooks, env, model...) : ce script ne
# gouverne QUE les permissions. Les ecraser detruirait silencieusement le reste
# de la configuration au prochain passage.
$out = [ordered]@{}
$prev = if (Test-Path $policyPath) { Get-Content $policyPath -Raw | ConvertFrom-Json } else { $null }
if ($prev) {
    foreach ($k in $prev.PSObject.Properties.Name) {
        if ($k -ne 'permissions') { $out[$k] = $prev.$k }
    }
}
$out['permissions'] = [pscustomobject]@{ allow = $normalized; deny = @(); ask = @($ask | Sort-Object -Unique) }
[pscustomobject]$out | ConvertTo-Json -Depth 20 | Set-Content $policyPath -Encoding UTF8

# Le brouillon repart vide : tout ce qui comptait est monté en politique.
[pscustomobject]@{ permissions = [pscustomobject]@{ allow = @(); deny = @(); ask = @() } } |
    ConvertTo-Json -Depth 20 | Set-Content $localPath -Encoding UTF8

Write-Host "`nsettings.json = politique ($($normalized.Count) motifs, $($ask.Count) garde-fous)"
Write-Host "settings.local.json = vide (brouillon)"
Write-Host "sauvegardes : *.bak-$stamp"
