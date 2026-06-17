"""
Détecte et (optionnellement) nettoie les modèles HuggingFace MAL PLACÉS / EN DOUBLE
dans AI-models/models/ — séquelle de la course os.environ['HF_HUB_CACHE'] qui a déversé
des modèles dans speech/kokoro, vision/sam, etc. (cf. ROADMAP §5b).

DRY-RUN par défaut : n'affiche qu'un rapport, NE SUPPRIME RIEN.
    python manage.py dedup_models

--apply : supprime UNIQUEMENT les copies REDONDANTES situées dans un dossier « dump »
(speech/kokoro, vision/sam) lorsqu'une AUTRE copie du même modèle existe ailleurs.
Ne supprime JAMAIS la dernière copie. Les modèles mal placés SANS doublon sont seulement
signalés (déplacement/retéléchargement manuel) — jamais supprimés.
    python manage.py dedup_models --apply
"""

import os
import shutil
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand

# Dossiers « dump » : ne devraient contenir QUE leur propre modèle.
DUMP_DIRS = {'speech/kokoro', 'vision/sam'}


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _gb(n: int) -> float:
    return n / (1024 ** 3)


def _misplaced_target(name: str):
    """Dossier canonique (relatif à models/) d'un modèle mal placé connu, ou None si inconnu.

    pyannote (segmentation, diarization, wespeaker) → speech/diarization.
    """
    n = name.lower()
    if 'pyannote' in n:
        return 'speech/diarization'
    return None


class Command(BaseCommand):
    help = "Rapport (dry-run) des modèles mal placés/en double dans AI-models/models ; --apply pour nettoyer les doublons."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Supprime les copies redondantes dans les dossiers dump (sûr : garde toujours ≥1 copie).")
        parser.add_argument('--move-misplaced', action='store_true',
                            help="Déplace (PAS supprimer) les modèles mal placés sans doublon vers leur dossier canonique (ex. pyannote → speech/diarization).")

    def handle(self, *args, **options):
        models_root = Path(settings.AI_MODELS_DIR) / 'models'
        if not models_root.exists():
            self.stderr.write(f"Introuvable : {models_root}")
            return

        # 1) Recense tous les dossiers HF (models--*), groupés par nom de modèle.
        by_name = {}   # basename -> [Path, ...]
        for d in models_root.rglob('models--*'):
            if not d.is_dir() or '/.locks/' in str(d).replace('\\', '/') or d.name == '.locks':
                continue
            # On ne garde que le dossier modèle racine (pas les sous-dossiers snapshots/blobs)
            if d.parent.name in ('snapshots', 'blobs', 'refs'):
                continue
            by_name.setdefault(d.name, []).append(d)

        def rel(p: Path) -> str:
            return str(p.relative_to(models_root)).replace('\\', '/')

        def in_dump(p: Path) -> bool:
            r = rel(p)
            return any(r.startswith(dd + '/') for dd in DUMP_DIRS)

        duplicates = {n: ds for n, ds in by_name.items() if len(ds) > 1}
        misplaced_singletons = []  # mal placés (dans un dump) mais SANS doublon → ne pas supprimer
        for n, ds in by_name.items():
            if len(ds) == 1 and in_dump(ds[0]):
                # Le dossier dump ne doit contenir que SON modèle (kokoro / sam3).
                owner = rel(ds[0].parent)  # ex. speech/kokoro
                own_ok = (('kokoro' in n.lower() and owner.endswith('kokoro'))
                          or ('sam' in n.lower() and owner.endswith('sam')))
                if not own_ok:
                    misplaced_singletons.append(ds[0])

        # 2) Rapport + plan de suppression (doublons dans un dump avec copie ailleurs).
        to_delete = []
        reclaim = 0
        self.stdout.write(self.style.MIGRATE_HEADING("=== DOUBLONS (même modèle à plusieurs emplacements) ==="))
        for n, ds in sorted(duplicates.items()):
            sizes = {d: _dir_size(d) for d in ds}
            # Copie à GARDER : en priorité une hors dump ; sinon la plus grosse.
            non_dump = [d for d in ds if not in_dump(d)]
            keep = (max(non_dump, key=lambda d: sizes[d]) if non_dump
                    else max(ds, key=lambda d: sizes[d]))
            self.stdout.write(f"\n{n}")
            for d in ds:
                tag = "GARDER" if d is keep else ("supprimable" if in_dump(d) else "(hors dump — non touché)")
                self.stdout.write(f"  [{tag:>22}] {rel(d)}  ({_gb(sizes[d]):.2f} Go)")
                if d is not keep and in_dump(d):
                    to_delete.append(d)
                    reclaim += sizes[d]

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== MAL PLACÉS SANS DOUBLON (déplacement, JAMAIS suppression) ==="))
        moves = []   # (src Path, dst Path)
        for d in misplaced_singletons:
            target_rel = _misplaced_target(d.name)
            if target_rel:
                dst = models_root / target_rel / d.name
                if dst.exists():
                    self.stdout.write(f"  = {rel(d)} — déjà présent dans {target_rel} (sera ignoré ; doublon)")
                else:
                    moves.append((d, dst))
                    self.stdout.write(f"  → {rel(d)}  →  {target_rel}/{d.name}  ({_gb(_dir_size(d)):.2f} Go)")
            else:
                self.stdout.write(f"  ! {rel(d)} — destination inconnue, à traiter manuellement")

        self.stdout.write("")
        self.stdout.write(f"Doublons supprimables (dans dump) : {len(to_delete)} — récupère {_gb(reclaim):.2f} Go (avec --apply)")
        self.stdout.write(f"Mal placés à déplacer : {len(moves)} (avec --move-misplaced)")

        if not options['apply'] and not options['move_misplaced']:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN — rien modifié. --apply (supprime doublons) et/ou --move-misplaced (déplace mal placés)."))
            return

        # 3a) --apply : supprime les copies redondantes (sûr : la copie GARDER reste).
        if options['apply']:
            for d in to_delete:
                try:
                    shutil.rmtree(d)
                    self.stdout.write(self.style.SUCCESS(f"Supprimé : {rel(d)}"))
                except Exception as e:
                    self.stderr.write(f"Échec suppression {rel(d)} : {e}")
            self.stdout.write(self.style.SUCCESS(f"✓ {len(to_delete)} doublon(s) supprimé(s), ~{_gb(reclaim):.2f} Go."))

        # 3b) --move-misplaced : DÉPLACE (jamais supprime) les mal placés vers leur dossier canonique.
        if options['move_misplaced']:
            for src, dst in moves:
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                    self.stdout.write(self.style.SUCCESS(f"Déplacé : {rel(src)} → {dst.relative_to(models_root)}".replace('\\', '/')))
                except Exception as e:
                    self.stderr.write(f"Échec déplacement {rel(src)} : {e}")
            self.stdout.write(self.style.SUCCESS(f"✓ {len(moves)} modèle(s) déplacé(s)."))

        self.stdout.write("\nPense à relancer `python manage.py sync_models` pour rafraîchir le catalogue.")
