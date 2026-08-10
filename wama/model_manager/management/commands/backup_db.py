r"""Sauvegarde de la base WAMA (pg_dump) + copie vers l'espace de sauvegarde distant.

Pendant : `remote_backup.py` (modèles → \\vrlescot\SAVES\DEEP_LEARNING\MODELS).
Ici, même racine, sous-dossier DB :
    WSL2     → /mnt/shares/SAVES/DEEP_LEARNING/DB
    Windows  → \\vrlescot\SAVES\DEEP_LEARNING\DB

Exemples :
    python manage.py backup_db                  # dump local + copie distante + rotation
    python manage.py backup_db --no-remote      # dump local seulement
    python manage.py backup_db --keep 20        # garde les 20 plus récents de chaque côté
"""
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

LOCAL_DIR = Path(settings.BASE_DIR) / "backups" / "db"
PREFIX = "wama_db_"
SUFFIX = ".dump"


def _default_remote_dir() -> str:
    """
    Espace distant des dumps. L'auto-détection WSL/Windows est passée dans la brique
    commune `mirror_sync` le 2026-08-10, quand la sauvegarde des médias en a eu besoin
    à son tour : la convention `DEEP_LEARNING/<domaine>` n'a plus qu'une définition.
    """
    from wama.common.services.mirror_sync import resolve_remote_root
    return resolve_remote_root("DB", env_var="WAMA_DB_BACKUP_PATH")


def _rotate(directory: Path, keep: int) -> list[str]:  # wama:redondance-ok — purge keep-N de dumps, mécanique distincte du décalage de logs (rotate_file)
    """Supprime les dumps les plus anciens, garde les `keep` plus récents."""
    dumps = sorted(directory.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.name, reverse=True)
    removed = []
    for old in dumps[keep:]:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return removed


class Command(BaseCommand):
    help = "Sauvegarde la base WAMA (pg_dump format custom) et la copie sur l'espace distant."

    def add_arguments(self, parser):
        parser.add_argument("--no-remote", action="store_true",
                            help="Ne pas copier vers l'espace de sauvegarde distant")
        parser.add_argument("--remote-dir", default=None,
                            help="Répertoire distant (défaut : WAMA_DB_BACKUP_PATH ou la convention DEEP_LEARNING/DB)")
        parser.add_argument("--keep", type=int, default=10,
                            help="Nombre de sauvegardes à conserver de chaque côté (défaut 10)")

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        if "postgresql" not in db["ENGINE"]:
            raise CommandError(f"Moteur non supporté : {db['ENGINE']} (postgresql attendu)")

        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        local_file = LOCAL_DIR / f"{PREFIX}{stamp}{SUFFIX}"

        # --format=custom : compressé et restaurable sélectivement via pg_restore.
        cmd = [
            "pg_dump", "--format=custom", "--no-owner", "--no-acl",
            "-h", db["HOST"], "-p", str(db["PORT"]), "-U", db["USER"],
            "-d", db["NAME"], "-f", str(local_file),
        ]
        env = {**os.environ, "PGPASSWORD": db["PASSWORD"]}

        self.stdout.write(f"Dump de {db['NAME']} → {local_file.name} …")
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
        except FileNotFoundError:
            raise CommandError("pg_dump introuvable (installer postgresql-client côté exécution)")
        except subprocess.TimeoutExpired:
            raise CommandError("pg_dump : délai dépassé (1 h)")

        if proc.returncode != 0:
            local_file.unlink(missing_ok=True)
            raise CommandError(f"pg_dump a échoué : {proc.stderr.strip()[:500]}")

        size_mb = local_file.stat().st_size / 1e6
        self.stdout.write(self.style.SUCCESS(f"✓ Dump local : {local_file} ({size_mb:.1f} Mo)"))

        for name in _rotate(LOCAL_DIR, opts["keep"]):
            self.stdout.write(f"  rotation locale : {name} supprimé")

        if opts["no_remote"]:
            return

        remote_dir = Path(opts["remote_dir"] or _default_remote_dir())
        try:
            remote_dir.mkdir(parents=True, exist_ok=True)
            remote_file = remote_dir / local_file.name
            shutil.copy2(local_file, remote_file)
            # Vérification de taille avant de considérer la copie fiable (même garde que offload_file).
            if remote_file.stat().st_size != local_file.stat().st_size:
                remote_file.unlink(missing_ok=True)
                raise CommandError(f"Copie distante incomplète, annulée : {remote_file}")
        except OSError as exc:
            self.stderr.write(self.style.WARNING(
                f"⚠ Copie distante impossible ({remote_dir}) : {exc}\n"
                f"  Le dump local reste valide : {local_file}"))
            return

        self.stdout.write(self.style.SUCCESS(f"✓ Copie distante : {remote_file}"))
        for name in _rotate(remote_dir, opts["keep"]):
            self.stdout.write(f"  rotation distante : {name} supprimé")
