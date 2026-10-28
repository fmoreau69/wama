---
name: restauration
description: Restaurer WAMA après une PERTE de fichiers ou un doute sur la base — médias tirés de la sauvegarde du NAS par la route (`restore_backup`), base vérifiée contre un dump restauré dans une base SÉPARÉE, jamais dans la vivante. Utiliser quand l'utilisateur dit « les médias ont disparu », « je ne peux plus lire les fichiers / les aperçus », « restaure depuis la sauvegarde », « la base est-elle intègre ? », « vérifie la base contre une sauvegarde », ou après tout effacement accidentel.
---

# /restauration — médias et base, après une perte

> ⚠ CANDIDAT (n=1, 2026-10-27) — distillé d'une résolution unique (perte TOTALE de `media/`),
> non confronté à une 2ᵉ occurrence. Le récit et les chiffres : `docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §10`.

**Posture** : rien n'est écrit avant d'avoir MESURÉ ; chaque geste qui écrit (copie, base de
contrôle, suppression) se fait après accord de Fabien ; la base vivante ne reçoit JAMAIS de
restauration pour une vérification.

## 0. Avant de restaurer — arrêter la cause

Restaurer pendant que l'effacement continue ne sert à rien. Dater la perte (dernier fichier servi
au journal d'accès, `mtime` du dossier recréé, heure de la sauvegarde de la nuit), puis trouver
QUI a effacé (transcriptions des sessions, journaux) et le neutraliser.
Vécu le 2026-10-27 : un test lancé hors du lanceur (`unittest.TextTestRunner` après
`django.setup()`) — désormais refusé par `wama/common/utils/media_guard.py`.

## 1. Les médias — par la ROUTE, jamais par une copie maison

```bash
python manage.py restore_backup --domain media --dry-run --missing-only --known-only   # mesurer
python manage.py restore_backup --domain media --missing-only --known-only             # tirer
python manage.py check_media_integrity                                                 # références présentes ?
```

- `--missing-only` : seuls les fichiers ABSENTS en local reviennent ; un fichier présent n'est
  jamais écrasé, même de taille différente (une partition corrigée depuis la sauvegarde). Sans
  lui, le tirage remplace ce qui diffère par la version ancienne.
- `~Archives` est exclu par la route (`wama/common/management/commands/restore_backup.py`) —
  décision de Fabien, ne pas le réintégrer.
- `--known-only` : seul revient ce que la base connaît encore — dossiers des comptes réels, la
  médiathèque, les fichiers posés à la RACINE de `media/` (à l'utilisateur : le 27/10, un
  `WAMA_Presentation_VoixFab.wav` qu'aucune card ne référence avait été manqué), et ailleurs les
  fichiers qu'une card hors compte de test référence. La sauvegarde
  NE SUPPRIME JAMAIS : sans lui, le tirage ramène aussi les dossiers de comptes de test, de comptes
  supprimés et d'anciennes apps (mesuré le 2026-10-28 : 1 826 fichiers, 18,45 Go d'encombrement ;
  avec lui, exactement les 2 309 fichiers que la restauration du 27/10 avait retenus). Le 27/10,
  faute de cette option, le tri a été fait par un `rsync` sur une liste — un second chemin de copie,
  à ne pas refaire.
- Ce qui datait d'après la sauvegarde de la nuit est perdu ; un fichier retiré par l'utilisateur
  avant la nuit peut réapparaître. Le DIRE.

## 2. La base — vérifier sur une COPIE, jamais sur la vivante

🔴 **JAMAIS `manage.py restore_db` pour vérifier** : il restaure par `--create --clean`, donc
supprime et recrée `wama_db`. Les dumps : `backups/db/` (local) et l'espace distant de
`backup_db`.

```bash
PYTHONPATH=. venv_linux/bin/python .claude/skills/restauration/db_check_restore.py <dump> wama_check_<date>
PYTHONPATH=. venv_linux/bin/python .claude/skills/restauration/db_compare.py wama_check_<date> <rapport.json>
PYTHONPATH=. venv_linux/bin/python .claude/skills/restauration/db_structure.py
python manage.py migrate --check
```

- `db_compare` liste, table par table, les lignes du dump DISPARUES depuis. Chacune s'explique
  avant de conclure : le 27/10, 3 disparitions, toutes par les mécanismes normaux (un visiteur
  purgé et son profil, deux témoins du nocturne). Un test qui a tourné sur la vraie base dans un
  `TestCase` est annulé par sa transaction — mais la séquence d'`auth_user` avance (constat
  normal, pas une perte).
- `db_structure` : index invalides, contraintes non validées, orphelines sur chaque clé étrangère.
- La base de contrôle se supprime APRÈS accord (`db_check_restore.py --drop wama_check_<date>`) :
  ~230 Mo le 27/10.

## 3. Les process

Depuis le 2026-10-27, une sortie d'amont ABSENTE ne périme plus son aval (seule une empreinte
différente périme) : restaurer les fichiers à l'identique ne laisse aucun process « périmé »
(`ROUTE §10.6` point 4.3). Une sortie encore perdue se voit sur la card (« sortie perdue ») et
se rejoue à la relance.

## 4. Consigner

Le récit (datation, cause, ce qui est revenu, ce qui est perdu, garde-fous) va dans
`docs/construction/exploitation/MEDIA_STORAGE_TIERING.md` (§10 pour le 27/10, une section par
incident), puis la passe courte `/doc-sync §1`.
