---
name: crash-residus
description: Après un crash hôte (Kernel-Power 41) — inventorier puis libérer les résidus disque qui s'empilent sur C: et D: (swap.vhdx orphelins de %TEMP%, clichés VSS, dumps), et passer les contrôles post-crash connexes (HWiNFO, cards zombies, pilote/WSL). Utiliser quand l'utilisateur signale un crash, « les disques se remplissent », « résidus de crash », ou en début de session après un Kernel-Power 41.
---

# /crash-residus — Résidus de crash hôte sur C: et D:

> ⚠ CANDIDAT (n=1, 2026-08-28) — distillé d'une résolution unique, non confronté à une 2ᵉ occurrence.

Le mécanisme a son domicile : **`INFRA_WSL_VS_WINDOWS.md` §« Chaque crash hôte FUITE jusqu'à
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
| dumps (MEMORY.DMP, Minidump, WER…) | ce sont des **PREUVES** — l'enquête crashs est OUVERTE (`INFRA_WSL_VS_WINDOWS.md §2026-08-28`) | inventorier, **ne jamais supprimer sans arbitrage Fabien**. NB : une coupure franche n'écrit en général AUCUN dump — un scan vide est normal |
| clichés VSS sur D: | 1 par redémarrage + 1/4 h → chaque crash en ajoute | **arbitrage Fabien** (§4) |

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

Puis supprimer le dossier GUID parent s'il est vide, et re-lancer le scan pour constater le gain.

## 4. Ce qui demande une session ÉLEVÉE ou un arbitrage (ne pas forcer)

- **VSS D:** — mesurer : `vssadmin list shadowstorage /for=D:` (admin). La piste documentée
  (`INFRA_WSL_VS_WINDOWS.md §Inventaire`) : `vssadmin resize shadowstorage /for=D: /on=D:
  /maxsize=10GB` purge les plus anciens. **Décision Fabien** — c'est lui qui perd des points de
  restauration ; rappel : les points C: sont éphémères de toute façon (volsnap purge ~1/jour).
- **Dumps volumineux** — signaler taille et date, laisser trancher.

## 5. Contrôles post-crash connexes (même moment, pas du disque)

1. **HWiNFO est-il relancé ?** Il meurt avec le crash et n'a aucun autostart — sans lui, le
   crash suivant ne sera pas instrumenté (leçon du 2ᵉ crash du 28/08, non instrumenté).
2. **Cards zombies RUNNING** : après reboot hôte, Celery répond `PENDING` (méta perdue avec
   Redis) → la réconciliation « preuve positive » (`wama/common/utils/process_control.py`,
   `reconcile_orphaned_running`) **ne mord pas**. Normaliser à la main via `stop_instance()`.
3. **Pilote NVIDIA changé depuis le dernier démarrage WSL ?** → `wsl --shutdown` puis relance
   de la stack, sinon TOUTE tâche CUDA échoue (`nvidia-smi` sans `libnvidia-ml.so`).
4. Un crash de plus = une ligne de plus dans la série d'`INFRA_WSL_VS_WINDOWS.md` (signature
   montée VRAM vs repos) — consigner LÀ-BAS, pas ici.
