"""Range les assets SYSTÈME de la médiathèque en sous-dossiers par NATURE.

    python manage.py organize_system_assets            # PLAN seul, n'écrit rien
    python manage.py organize_system_assets --apply    # déplace les fichiers et réécrit les lignes

POURQUOI (décision de Fabien, 2026-09-22 — ligne D18 de `MEDIA_STORAGE_TIERING §8.6`) :
`media_library/system/` était à plat, 9 avatars et 28 voix mêlés. Les nouveaux assets se rangent
déjà par nature (`SystemAsset.file` → `media_paths.UploadToSystemAssetPath`) ; cette commande
range ceux qui existaient AVANT. Le chemin cible vient de `media_paths.system_asset_relpath` —
jamais composé ici.

Repris du patron éprouvé de `migrate_media_to_user_home` (ses corrections y sont motivées) :
  • on DÉPLACE (`os.rename`), on ne copie jamais ;
  • la ligne est réécrite DANS la même transaction que le déplacement : un rename qui échoue
    ramène la base seule ;
  • une cible déjà prise est REFUSÉE et nommée, jamais écrasée (`os.rename` écrase en silence
    sous POSIX) ;
  • un pré-vol vérifie la longueur des chemins (`FileField` = 100 caractères par défaut) avant
    tout geste ;
  • idempotente : un asset déjà rangé est laissé tel quel.
"""
import os
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from wama.common.utils.media_paths import SYSTEM_ASSET_ROOT, system_asset_relpath


def build_plan():
    """`(moves, done, problems)` — `moves` : `[(current, target, [pks])]` à déplacer ;
    `done` : nombre de fichiers déjà rangés ; `problems` : `[(current, reason)]`, jamais touchés.
    Les lignes sont regroupées par FICHIER : deux lignes qui partagent un fichier bougent
    ensemble, ou pas du tout."""
    from wama.media_library.models import SystemAsset

    root = Path(settings.MEDIA_ROOT)
    max_length = SystemAsset._meta.get_field('file').max_length
    by_file = defaultdict(list)
    for asset in SystemAsset.objects.exclude(file='').only('id', 'file', 'asset_type'):
        by_file[asset.file.name].append(asset)

    moves, problems, done, claimed = [], [], 0, set()
    for current, assets in sorted(by_file.items()):
        natures = {a.asset_type for a in assets}
        if len(natures) > 1:
            problems.append((current, f"un fichier, plusieurs natures {sorted(natures)}"))
            continue
        target = system_asset_relpath(natures.pop(), current)
        if target == current:
            done += 1
            continue
        if not (root / current).is_file():
            problems.append((current, 'fichier absent du disque'))
        elif len(target) > max_length:
            problems.append((current, f'chemin cible trop long ({len(target)} > {max_length})'))
        elif (root / target).exists() or target in claimed:
            problems.append((current, f'cible déjà prise : {target}'))
        else:
            claimed.add(target)
            moves.append((current, target, [a.pk for a in assets]))
    return moves, done, problems


def audit():
    """`(missing, orphans)` — lignes dont le fichier manque ; fichiers de `system/` qu'aucune
    ligne ne référence (sous-dossiers compris)."""
    from wama.media_library.models import SystemAsset

    root = Path(settings.MEDIA_ROOT)
    referenced = set(SystemAsset.objects.exclude(file='').values_list('file', flat=True))
    missing = sorted(name for name in referenced if not (root / name).is_file())
    system_dir = root / SYSTEM_ASSET_ROOT
    on_disk = ({p.relative_to(root).as_posix() for p in system_dir.rglob('*') if p.is_file()}
               if system_dir.is_dir() else set())
    return missing, sorted(on_disk - referenced)


class Command(BaseCommand):
    help = "Range media_library/system/ en sous-dossiers par nature (SystemAsset.asset_type)"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Exécute réellement (sinon : PLAN seul, rien n'est écrit)")

    def handle(self, *args, **options):
        from wama.media_library.models import SystemAsset

        root = Path(settings.MEDIA_ROOT)
        apply = options['apply']
        moves, done, problems = build_plan()

        self.stdout.write(self.style.MIGRATE_HEADING(
            "ASSETS SYSTÈME → SOUS-DOSSIERS PAR NATURE — "
            + ("EXÉCUTION" if apply else "PLAN (rien n'est écrit)")))
        self.stdout.write(f"  déjà rangés : {done}   à déplacer : {len(moves)}   "
                          f"écartés : {len(problems)}")
        per_nature = defaultdict(int)
        for _current, target, _pks in moves:
            per_nature[target.split('/')[2]] += 1
        for nature, count in sorted(per_nature.items()):
            self.stdout.write(f"      {nature:12s} {count}")
        for current, target, _pks in moves:
            self.stdout.write(f"      {current}  →  {target}")
        for current, reason in problems:
            self.stdout.write(self.style.WARNING(f"  ⚠ écarté : {current} — {reason}"))

        if not apply:
            self.stdout.write("  → relancer avec --apply pour exécuter")
            return

        moved, failures = 0, []
        for current, target, pks in moves:
            try:
                with transaction.atomic():
                    SystemAsset.objects.filter(pk__in=pks).update(file=target)
                    (root / target).parent.mkdir(parents=True, exist_ok=True)
                    # `os.rename` et non `shutil.move` : le second copierait en silence.
                    os.rename(root / current, root / target)
            except Exception as exc:
                failures.append((current, f"{type(exc).__name__}: {exc}"))
                continue
            moved += 1

        missing, orphans = audit()
        self.stdout.write(self.style.SUCCESS(f"  déplacés : {moved} / {len(moves)}"))
        for current, error in failures:
            self.stdout.write(self.style.ERROR(f"    échec : {current} — {error}"))
        self.stdout.write(f"  bilan : {len(missing)} ligne(s) sans fichier, "
                          f"{len(orphans)} orphelin(s) dans {SYSTEM_ASSET_ROOT}/")
        for name in missing:
            self.stdout.write(self.style.ERROR(f"    sans fichier : {name}"))
        for name in orphans:
            self.stdout.write(self.style.WARNING(f"    orphelin : {name}"))
