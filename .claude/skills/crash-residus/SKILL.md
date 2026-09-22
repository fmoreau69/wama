---
name: crash-residus
description: Après un crash hôte (Kernel-Power 41) — inventorier puis libérer les résidus disque qui s'empilent sur C: et D: (swap.vhdx orphelins de %TEMP%, core dumps WSL de %TEMP%\wsl-crashes, clichés VSS, dumps), et passer les contrôles post-crash connexes (HWiNFO, cards zombies, pilote/WSL). Utiliser quand l'utilisateur signale un crash, « les disques se remplissent », « résidus de crash », ou en début de session après un Kernel-Power 41.
---

# /crash-residus — Résidus de crash hôte sur C: et D:

> PROMU (n=2 : 2026-08-28 swap orphelins ; 2026-09-22 « C: rempli sans raison », 57,5 Go de
> core dumps WSL que le scan ne voyait pas — ajoutés au scan, §2).

Le mécanisme a son domicile : **`docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md` §« Chaque crash hôte FUITE jusqu'à
8 Go dans `%TEMP%` »** (2026-08-25) + §Inventaire disque. Ce skill est le geste REJOUABLE ;
les chiffres vivent là-bas et dans la sortie du scan — jamais recopiés ici.

## 1. Scanner (read-only, toujours en premier)

```
pwsh -NoProfile -File .claude/skills/crash-residus/scan_residus.ps1
```

Le script inventorie : espace libre C:/D: · `swap.vhdx` sous dossiers GUID de `%TEMP%` avec
**test de verrou** · dumps système (MEMORY.DMP, Minidump, LiveKernelReports, WER) · clichés
VSS de D: (échoue sans élévation — c'est attendu, voir §4) · journaux d'instrumentation du repo.

Ordre de grandeur (mesuré 2026-08-28, à ne pas croire sans re-scanner) : ~8 Go de swap orphelin
**par crash** ; deux crashs dans la journée avaient laissé 11,48 Go.

## 2. Interpréter — trois familles, trois traitements

| famille | critère | traitement |
|---|---|---|
| `swap.vhdx` orphelin | **le VERROU, ni la date ni la taille** (le vivant a déjà fait 36 Mo, un orphelin 8 Go) | supprimable → §3 |
| dumps (MEMORY.DMP, Minidump, WER…) | ce sont des **PREUVES** — l'enquête crashs est OUVERTE (`docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md §2026-08-28`) | inventorier, **ne jamais supprimer sans arbitrage Fabien**. NB : une coupure franche n'écrit en général AUCUN dump — un scan vide est normal |
| clichés VSS sur D: | 1 par redémarrage + 1/4 h → chaque crash en ajoute | **arbitrage Fabien** (§4) |
| core dumps WSL (`%TEMP%\wsl-crashes`) | un PROCESSUS Linux planté (pas l'hôte) : 5-9 Go chacun, 10 gardés par défaut | établir la cause d'abord (ci-dessous), puis supprimer |

⚠ **Les dumps WSL ont rempli C: le 2026-09-22** (9 × `python3.12`, 57,5 Go ; le scan ne les
voyait pas encore). Pour les lire sans `gdb` : `core_read.py` (à côté de ce skill, Python pur :
notes PRSTATUS/NT_FILE → signal, thread fautif, bibliothèques sur sa pile) suffit à nommer le
coupable — `wsl.exe -e bash -lc "<venv_linux>/bin/python <skill>/core_read.py /mnt/c/.../x.dmp"`. Pour REPRODUIRE sans produire un nouveau dump : `prctl(PR_SET_DUMPABLE, 0)` en tête
du script (ctypes, option 4). Cas du 22/09 : pyarrow (bibliothèque HuggingFace `datasets`, lecture
en flux) qui plante à la FERMETURE de Python — insoluble côté Python, parade `os._exit`
(`download_voice_refs`, commit `8eaa1c64`). Plafond : `maxCrashDumpCount` dans
`scripts/set_wslconfig.ps1`.

⚠ **Ne JAMAIS purger `%TEMP%` en bloc** : le swap VIVANT, des DLL en usage et le scratchpad de
l'agent y vivent. Chaque suppression est ciblée, verrou re-testé juste avant.
⚠ Journaux (`logs/`, hwlog, Apache, gunicorn) : **on DÉCALE, on ne VIDE pas** — et les
`rails_*_crash.csv` archivés sont des pièces d'enquête, pas des résidus.

## 3. Libérer les swap orphelins (le seul nettoyage auto-approuvable)

Suppression par **chemins explicites** relevés au scan, jamais par motif large. Le classifieur
de permissions bloque ce geste en mode auto (vécu 2026-08-28) : le proposer à l'utilisateur
pour validation, avec re-test du verrou dans la même séquence :

```
pwsh -NoProfile -Command "& { $f='<chemin\swap.vhdx du scan>'; try { $s=[IO.File]::Open($f,'Open','ReadWrite','None'); $s.Close() } catch { Write-Output 'VERROUILLE — abandon'; exit 1 }; Remove-Item $f -Force -Confirm:$false; Write-Output 'supprime' }"
```

⚠ Proposé via `! pwsh -File <script>` : le `!` passe par **Bash**, qui mange les antislashs
d'un chemin Windows — écrire le chemin avec des `/` (vécu 22/09).

Puis supprimer le dossier GUID parent s'il est vide, et re-lancer le scan pour constater le gain.

⚠ **L'espace libéré peut NE PAS apparaître** (vécu 29/08 : 11,5 Go supprimés, +0,3 Go visibles) :
les clichés VSS de C: **retiennent les blocs supprimés** jusqu'à leur purge. Le vérifier par
l'arithmétique — script rejouable :
`pwsh -NoProfile -File .claude/skills/crash-residus/scan_ecart_volume.ps1 -Drive C` —
somme des dossiers racine mesurables vs utilisé réel du volume : l'écart EST le stockage VSS
+ inaccessibles (mesuré ~34,8 Go le 29/08, ≈ le plafond par défaut de 10 %).
Deux pièges de mesure : `C:\Users\fmoreau\.ollama` est un **SymbolicLink → `D:\.ollama`**
(66 Go comptés à tort sur C: si on le scanne directement — toujours vérifier `LinkType` avant
de conclure) ; et le swap VIVANT regrossit vers ses 8 Go configurés — ce n'est pas une fuite.

## 4. Ce qui demande une session ÉLEVÉE ou un arbitrage (ne pas forcer)

- **VSS C: et D:** — mesurer : `vssadmin list shadowstorage` (admin ; `/for=C:` ou `/for=D:`).
  D: est plafonné à 10 Go depuis le 28/08. ⚠ **Sur C:, le resize est BLOQUÉ par SentinelOne**
  (vécu 29/08 en console admin : VSS 12289, `DeviceIoControl 0x80070005 Accès refusé` — la
  protection anti-ransomware des clichés ; détail : `docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md §2026-08-29`).
  Ne pas s'acharner ni tenter de contourner l'EDR : la voie de sortie est **le service info**
  (console S1). En attendant, le poste est BORNÉ à ~10 % du volume — pas une fuite.
  Rappel : les points C: sont éphémères de toute façon (volsnap purge ~1/jour ; le point utile
  se crée MANUELLEMENT avant un geste risqué).
- **Dumps volumineux** — signaler taille et date, laisser trancher.

## 5. Contrôles post-crash connexes (même moment, pas du disque)

1. **HWiNFO est-il relancé ?** Il meurt avec le crash et n'a aucun autostart — sans lui, le
   crash suivant ne sera pas instrumenté (leçon du 2ᵉ crash du 28/08, non instrumenté).
2. **Cards zombies RUNNING** : après reboot hôte, Celery répond `PENDING` (méta perdue avec
   Redis) → la réconciliation « preuve positive » (`wama/common/utils/process_control.py`,
   `reconcile_orphaned_running`) **ne mord pas**. Normaliser à la main via `stop_instance()`.
3. **Pilote NVIDIA changé depuis le dernier démarrage WSL ?** → `wsl --shutdown` puis relance
   de la stack, sinon TOUTE tâche CUDA échoue (`nvidia-smi` sans `libnvidia-ml.so`).
4. Un crash de plus = une ligne de plus dans la série d'`docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md` (signature
   montée VRAM vs repos) — consigner LÀ-BAS, pas ici.
