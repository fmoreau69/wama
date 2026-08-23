<#
.SYNOPSIS
    Journal matériel continu — instrumentation des coupures brutales de l'hôte.

.DESCRIPTION
    Les crashs observés (27/07/2026 x3, 31/07/2026 x1) n'écrivent AUCUNE trace côté
    Windows : Kernel-Power 41 avec BugcheckCode=0, pas de minidump, pas de MEMORY.DMP,
    redémarrage à froid. Le noyau ne reprend jamais la main — la seule façon de savoir
    ce qui a lâché est d'échantillonner en continu et de regarder OÙ le fichier s'arrête
    net, et sous quelle charge.

    Question à trancher : la machine meurt-elle sous pointe de consommation (protection
    de l'alimentation — RTX 4090 450 W + i9-9900K sur une Z390 de 2018) ou au repos
    (secteur / matériel dégradé) ? Le crash du 31/07 s'est produit à charge quasi nulle,
    ce qui rend la seconde piste crédible : il faut des mesures pour trancher.

    Coût : un appel nvidia-smi + deux requêtes CIM toutes les 10 s, soit environ 0,2 %
    d'un cœur. Aucune charge GPU induite (nvidia-smi est en lecture seule).

.NOTES
    Rotation quotidienne, purge au-delà de -RetentionDays.
    Écrit dans logs/hwlog/ (logs/ est gitignoré).
    Installé en tâche planifiée « WAMA-HwWatchdog » (déclenchement au démarrage, SYSTEM).

    Limite connue : nvidia-smi échantillonne à 10 s. Les transitoires microseconde d'une
    4090 (qui font déclencher une protection OCP) ne sont PAS capturés. Ce journal donne
    le CONTEXTE (charge au moment de la mort), pas la pointe elle-même. Pour les rails
    +12 V, il faut HWiNFO64 en complément.
#>
param(
    [int]$IntervalSeconds = 10,
    [string]$LogDir = 'D:\WAMA\web-app-for-media-automation\logs\hwlog',
    [int]$RetentionDays = 14,
    # Archives de rails : gardees 4x plus longtemps que les hwlog. Une capture de
    # rails vaut un crash INSTRUMENTE -- on en a obtenu la premiere le 2026-08-23
    # apres douze jours d'echecs, ce n'est pas une donnee qu'on jette au bout de 14 j.
    [int]$RailsRetentionDays = 60,
    [int]$RailsWarnMB = 500
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$header = 'timestamp,gpu_w,gpu_limit_w,gpu_temp_c,gpu_util_pct,gpu_clock_mhz,gpu_mem_mb,cpu_pct,ram_free_mb'
$currentDay = $null
$writer = $null

try {
    while ($true) {
        $now = Get-Date
        $day = $now.ToString('yyyyMMdd')

        # ── Rotation quotidienne ──────────────────────────────────────────────
        if ($day -ne $currentDay) {
            if ($writer) { $writer.Flush(); $writer.Dispose() }

            $file = Join-Path $LogDir "hwlog_$day.csv"
            $isNew = -not (Test-Path $file)
            $writer = New-Object System.IO.StreamWriter($file, $true)
            $writer.AutoFlush = $true
            if ($isNew) { $writer.WriteLine($header) }

            # Marqueur de session : si le boot est postérieur à la fin du fichier
            # précédent, la machine est morte entre les deux.
            $boot = ''
            try { $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('yyyy-MM-dd HH:mm:ss') } catch { }
            $writer.WriteLine("# session $($now.ToString('yyyy-MM-dd HH:mm:ss')) lastboot=$boot")

            Get-ChildItem (Join-Path $LogDir 'hwlog_*.csv') -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -lt $now.AddDays(-$RetentionDays) } |
                Remove-Item -Force -ErrorAction SilentlyContinue

            # --- Journaux de RAILS (HWiNFO) ---------------------------------
            # Deux poids, deux mesures, et c'est deliberе :
            #  * rails_*.csv = ARCHIVES de crash, ~73 Mo piece. Ce sont des PIECES A
            #    CONVICTION (une capture = un crash date). On les garde bien plus
            #    longtemps que les hwlog, sinon le menage detruit la seule preuve.
            #  * rails.csv   = journal VIVANT, ecrit par HWiNFO en continu (~76 Mo/jour).
            #    On ne peut PAS le tourner (c'est un process externe qui tient le
            #    descripteur) : on se contente d'ALERTER quand il devient gros.
            #    D: est deja sous 6 % de libre, donc le silence n'est pas une option.
            Get-ChildItem (Join-Path $LogDir 'rails_*.csv') -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -lt $now.AddDays(-$RailsRetentionDays) } |
                ForEach-Object {
                    $writer.WriteLine("# purge archive rails : $($_.Name) ($([math]::Round($_.Length/1MB)) Mo, > $RailsRetentionDays j)")
                    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
                }

            $vivant = Join-Path $LogDir 'rails.csv'
            if (Test-Path $vivant) {
                $mo = [math]::Round((Get-Item $vivant).Length / 1MB)
                if ($mo -ge $RailsWarnMB) {
                    $writer.WriteLine("# ATTENTION rails.csv = $mo Mo (seuil $RailsWarnMB) - archiver puis relancer la journalisation HWiNFO")
                }
            }

            $currentDay = $day
        }

        # ── GPU (6 champs, vides si nvidia-smi indisponible) ──────────────────
        $gpu = ',,,,,'
        try {
            $raw = & nvidia-smi --query-gpu=power.draw,power.limit,temperature.gpu,utilization.gpu,clocks.sm,memory.used --format=csv,noheader,nounits 2>$null
            if ($LASTEXITCODE -eq 0 -and $raw) {
                $gpu = (($raw | Select-Object -First 1) -replace '\s', '')
            }
        } catch { }

        # ── CPU / RAM (classes CIM : indépendantes de la locale) ──────────────
        $cpu = ''
        try { $cpu = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime } catch { }
        $ram = ''
        try { $ram = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024) } catch { }

        $writer.WriteLine("$($now.ToString('yyyy-MM-dd HH:mm:ss')),$gpu,$cpu,$ram")

        Start-Sleep -Seconds $IntervalSeconds
    }
}
finally {
    if ($writer) { $writer.Flush(); $writer.Dispose() }
}
