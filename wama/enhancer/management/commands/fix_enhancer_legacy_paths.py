"""
Déplace les fichiers média « legacy » de l'enhancer restés à la RACINE de input/ (ou output/)
vers les sous-dossiers conventionnels input/media | input/audio (idem output), pour qu'ils
réapparaissent dans le filemanager (qui n'a de nœuds que pour …/media et …/audio).

Contexte : la migration 0006 a changé `upload_to` ('input' → 'input/media') mais n'a pas déplacé
les fichiers existants → fichiers image/vidéo invisibles dans le filemanager.

Sûr : par défaut DRY-RUN (n'écrit rien). `--apply` pour exécuter. Met à jour le FileField en DB
si un record (Enhancement/AudioEnhancement) référence l'ancien chemin (sinon = orphelin, simple move).
"""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'}
VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.3gp', '.m4v', '.wmv', '.flv'}
AUDIO_EXTS = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.opus', '.wma'}


def _subdir_for(ext: str):
    ext = ext.lower()
    if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
        return 'media'
    if ext in AUDIO_EXTS:
        return 'audio'
    return None  # type inconnu → on ne touche pas


class Command(BaseCommand):
    help = "Déplace les médias enhancer restés à la racine de input/output vers media/ ou audio/."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Exécute réellement (sinon dry-run, par défaut).")

    def handle(self, *args, **opts):
        apply = opts['apply']
        from wama.enhancer.models import Enhancement, AudioEnhancement

        media_root = Path(settings.MEDIA_ROOT)
        enhancer_root = media_root / 'enhancer'
        if not enhancer_root.exists():
            self.stdout.write("Aucun dossier enhancer.")
            return

        moved = skipped = db_updated = 0
        for user_dir in sorted(enhancer_root.iterdir()):
            if not user_dir.is_dir():
                continue
            for kind in ('input', 'output'):
                base = user_dir / kind
                if not base.is_dir():
                    continue
                # fichiers DIRECTEMENT dans input/ ou output/ (pas dans les sous-dossiers)
                for f in base.iterdir():
                    if not f.is_file():
                        continue
                    sub = _subdir_for(f.suffix)
                    if sub is None:
                        skipped += 1
                        continue
                    dest_dir = base / sub
                    dest = dest_dir / f.name
                    rel_old = str(f.relative_to(media_root)).replace('\\', '/')
                    rel_new = str(dest.relative_to(media_root)).replace('\\', '/')

                    if dest.exists():
                        self.stdout.write(f"  ⚠ existe déjà, ignoré : {rel_new}")
                        skipped += 1
                        continue

                    self.stdout.write(f"  {'MOVE' if apply else 'would move'} {rel_old} -> {rel_new}")
                    if apply:
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(f), str(dest))
                        # MAJ DB si un record référence l'ancien chemin
                        for Model in (Enhancement, AudioEnhancement):
                            for field in ('input_file', 'output_file'):
                                n = Model.objects.filter(**{field: rel_old}).update(**{field: rel_new})
                                db_updated += n
                    moved += 1

        verb = "déplacés" if apply else "à déplacer"
        self.stdout.write(self.style.SUCCESS(
            f"\n{moved} fichier(s) {verb}, {skipped} ignoré(s), {db_updated} record(s) DB mis à jour."
        ))
        if not apply:
            self.stdout.write("DRY-RUN — relancer avec --apply pour exécuter.")
