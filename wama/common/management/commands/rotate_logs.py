"""
Rotation des journaux au démarrage de WAMA.

À appeler UNE fois, SERVICES ARRÊTÉS, en tête des scripts de démarrage — voir
l'avertissement d'ordonnancement dans `wama/common/utils/log_rotation.py`.
"""

from django.core.management.base import BaseCommand

from wama.common.utils.log_rotation import (
    DEFAULT_KEEP,
    get_log_dir,
    resolve_targets,
    rotate_startup_logs,
)


class Command(BaseCommand):
    help = (
        "Décale les journaux du run précédent (X.log → X.log.1 → …) au lieu de les "
        "écraser, pour garder la trace exploitable après un crash."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            type=int,
            default=DEFAULT_KEEP,
            help=f"Nombre de runs conservés en plus du courant (défaut : {DEFAULT_KEEP}).",
        )
        parser.add_argument(
            "--log-dir",
            default=None,
            help="Répertoire des journaux (défaut : <BASE_DIR>/logs).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste ce qui serait tourné sans rien déplacer.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help=(
                "Tourne TOUT le répertoire (*.log) au lieu des seuls journaux de "
                "service. Attention : emporte les journaux d'archive à tirage unique "
                "(download_*.log…), qui disparaîtront au bout de --keep rotations."
            ),
        )

    def handle(self, *args, **options):
        keep = options["keep"]
        log_dir = options["log_dir"] or get_log_dir()
        pattern = "*.log" if options["all"] else None

        if options["dry_run"]:
            candidates = [
                p for p in resolve_targets(log_dir=log_dir, pattern=pattern)
                if p.exists() and p.stat().st_size > 0
            ]
            self.stdout.write(f"[dry-run] {len(candidates)} journal(aux) à tourner dans {log_dir} :")
            for path in candidates:
                self.stdout.write(f"  - {path.name} → {path.name}.1")
            return

        rotated = rotate_startup_logs(log_dir=log_dir, keep=keep, pattern=pattern)

        if not rotated:
            self.stdout.write(self.style.SUCCESS(f"Aucun journal à tourner ({log_dir})."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(rotated)} journal(aux) tourné(s) dans {log_dir} "
                f"({keep} run(s) conservé(s)) : {', '.join(rotated)}"
            )
        )
